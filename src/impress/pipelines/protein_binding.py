import asyncio
import copy
import os

from .impress_pipeline import ImpressBasePipeline

TASK_PRE_EXEC = [
    "module load anaconda",
    "source activate base",
    (f"conda activate /anvil/scratch/{os.environ['USER']}/impress/ve.impress"),
]

MPNN_PATH = f"/anvil/scratch/{os.environ['USER']}/impress/ProteinMPNN"


class ProteinBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs=None, **kwargs):
        # Execution metadata
        if configs is None:
            configs = {}
        self.passes = kwargs.get("passes", 1)
        self.step_id = kwargs.get("step_id", 1)
        self.seq_rank = kwargs.get("seq_rank", 0)
        self.num_seqs = kwargs.get("num_seqs", 10)
        self.sub_order = kwargs.get("sub_order", 0)
        self.max_passes = kwargs.get("max_passes", 4)
        self.mpnn_path = kwargs.get("mpnn_path", MPNN_PATH)

        # Sequence and score state
        self.current_scores = {}
        self.iter_seqs = kwargs.get("iter_seqs", {})
        self.previous_scores = kwargs.get("previous_score", {})

        super().__init__(name, flow, **configs, **kwargs)

        # Input-related
        self.fasta_list_2 = kwargs.get("fasta_list_2", [])
        self.base_path = kwargs.get("base_path", os.getcwd())
        self.input_path = os.path.join(self.base_path, f"{self.name}_in")

        # Output paths
        self.output_path = os.path.join(
            self.base_path, "af_pipeline_outputs_multi", self.name
        )
        self.output_path_mpnn = os.path.join(self.output_path, "mpnn")
        self.output_path_af = os.path.join(
            self.output_path, "/af/prediction/best_models"
        )

        # might have to do outside of initialization, so new pipelines
        # do not run this can be declared directly as argument
        for file_name in os.listdir(self.input_path):
            self.fasta_list_2.append(file_name)

    def set_up_new_pipeline_dirs(self, new_pipeline_name):
        base_output = os.path.join(
            self.base_path, "af_pipeline_outputs_multi", new_pipeline_name
        )
        input_dir = os.path.join(self.base_path, f"{new_pipeline_name}_in")

        if os.path.isdir(base_output):
            return  # already exists, nothing to do

        # all directories to create
        subdirs = [
            "af/fasta",
            "af/prediction/best_models",
            "af/prediction/best_ptm",
            "af/prediction/dimer_models",
            "af/prediction/logs",
            "mpnn",
            *[f"mpnn/job_{i}" for i in range(1, 6)],
        ]

        paths_to_create = [input_dir, base_output] + [
            os.path.join(base_output, subdir) for subdir in subdirs
        ]

        for path in paths_to_create:
            os.makedirs(path, exist_ok=True)

    def register_pipeline_tasks(self):
        """Register all pipeline tasks"""

        @self.auto_register_task()  # MPNN
        async def s1(task_description=None):
            if task_description is None:
                task_description = {"ranks": 1}
            mpnn_script = os.path.join(self.base_path, "mpnn_wrapper.py")
            output_dir = os.path.join(self.output_path_mpnn, f"job_{self.passes}")

            chain = "A" if self.passes == 1 else "B"
            input_path = self.input_path if self.passes == 1 else self.output_path_af

            return (
                f"python3 {mpnn_script} "
                f"-pdb={input_path} "
                f"-out={output_dir} "
                f"-mpnn={self.mpnn_path} "
                f"-seqs={self.num_seqs} "
                "-is_monomer=0 "
                f"-chains={chain}"
            )

        @self.auto_register_task(local_task=True)
        async def s2():
            job_seqs_dir = f"{self.output_path_mpnn}/job_{self.passes}/seqs"

            for file_name in os.listdir(job_seqs_dir):
                seqs = []
                with open(os.path.join(job_seqs_dir, file_name)) as fd:
                    lines = fd.readlines()[2:]  # Skip first two lines

                score = None
                for line in lines:
                    line = line.strip()
                    if line.startswith(">"):
                        score = float(line.split(",")[2].replace(" score=", ""))
                    else:
                        seqs.append([line, score])

                seqs.sort(key=lambda x: x[1])  # Sort by score
                self.iter_seqs[file_name.split(".")[0]] = seqs

        # fasta - don't use helper script - cannot run x tasks for x structures
        @self.auto_register_task(local_task=True)
        async def s3():
            output_dir = os.path.join(self.output_path, "af", "fasta")

            fasta_file_to_return = []
            for fasta_file in self.fasta_list_2:
                base_name = fasta_file.split(".")[0]
                fasta_file_to_return.append(base_name)
                design_seq = self.iter_seqs[base_name][self.seq_rank][0]
                pep_seq = "EGYQDYEPEA"

                fasta_path = os.path.join(output_dir, f"{base_name}.fa")
                with open(fasta_path, "w") as f:
                    f.write(f">pdz\n{design_seq}\n>pep\n{pep_seq}\n")

            return fasta_file_to_return

        # alphafold, must be run separately for each structure one at a time!
        @self.auto_register_task()
        async def s4(target_fasta, task_description=None):
            if task_description is None:
                task_description = {"gpus_per_rank": 1}
            cmd = (
                f"/bin/bash {self.base_path}/af2_multimer_reduced.sh "
                f"{self.output_path}/af/fasta/ "
                f"{target_fasta}.fa "
                f"{self.output_path}/af/prediction/dimer_models/ "
            )

            return cmd

        @self.auto_register_task()  # plddt_extract
        async def s5(task_description=None):
            if task_description is None:
                task_description = {}
            return (
                f"python3 {self.base_path}/plddt_extract_pipeline.py "
                f"--path={self.base_path} "
                f"--iter={self.passes} "
                f"--out={self.name}"
            )

    async def get_scores_map(self):
        """Return current and previous scores"""
        return {"c_scores": self.current_scores, "p_scores": self.previous_scores}

    def finalize(self, sub_iter_seqs):
        # finalize the "cleanup" of the current pipeline
        for a in sub_iter_seqs:
            self.fasta_list_2.remove(f"{a}.pdb")
            os.unlink(f"{self.output_path_af}/{a}.pdb")
            os.unlink(f"{self.output_path}/af/fasta/{a}.fa")
        self.previous_scores = copy.deepcopy(self.current_scores)

    async def run(self):
        """Main execution logic"""

        self.logger.pipeline_log(f"Running for a maximum of {self.max_passes} passes")

        while self.passes <= self.max_passes:
            self.logger.pipeline_log(f"Starting pass {self.passes}")

            self.logger.pipeline_log("Submitting MPNN task")
            await self.s1(task_description={"pre_exec": TASK_PRE_EXEC})
            self.logger.pipeline_log("MPNN task finished")

            self.logger.pipeline_log("Submitting sequence ranking task")
            await self.s2()
            self.logger.pipeline_log("Sequence ranking task finished")

            self.logger.pipeline_log("Submitting scoring task")
            fasta_files = await self.s3()
            self.logger.pipeline_log("Scoring task finished")

            alphafold_tasks = []

            for target_fasta in fasta_files:
                models_path = os.path.join(
                    self.output_path, "af", "prediction", "dimer_models", target_fasta
                )

                best_model_pdb = os.path.join(
                    self.output_path,
                    "af",
                    "prediction",
                    "best_models",
                    f"{target_fasta}.pdb",
                )
                best_ptm_json = os.path.join(
                    self.output_path,
                    "af",
                    "prediction",
                    "best_ptm",
                    f"{target_fasta}.json",
                )
                mpnn_pdb = os.path.join(
                    self.output_path,
                    "mpnn",
                    f"job_{self.passes}",
                    f"{target_fasta}.pdb",
                )

                s4_description = {
                    "pre_exec": TASK_PRE_EXEC,
                    "post_exec": [
                        f"cp {models_path}/*ranked_0*.pdb {best_model_pdb}",
                        f"cp {models_path}/*ranking_debug*.json {best_ptm_json}",
                        f"cp {models_path}/*ranked_0*.pdb {mpnn_pdb}",
                    ],
                }

                # launch coroutine without awaiting yet
                alphafold_tasks.append(
                    self.s4(target_fasta=target_fasta, task_description=s4_description)
                )

            self.logger.pipeline_log(
                f"Submitting {len(alphafold_tasks)} Alphafold tasks asynchronously"
            )
            await asyncio.gather(*alphafold_tasks, return_exceptions=True)
            self.logger.pipeline_log(f"{len(alphafold_tasks)} Alphafold tasks finished")

            self.logger.pipeline_log("Submitting plddt extract")

            staged_file = f"af_stats_{self.name}_pass_{self.passes}.csv"

            await self.s5(
                task_description={
                    "pre_exec": TASK_PRE_EXEC,
                    "output_staging": [
                        {
                            "source": f"task:///{staged_file}",
                            "target": f"client:///{staged_file}",
                        }
                    ],
                }
            )
            self.logger.pipeline_log("Plddt extract finished")

            await self.run_adaptive_step(wait=True)

            self.passes += 1
