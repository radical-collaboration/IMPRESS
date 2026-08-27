import asyncio
import copy
import os

from .impress_pipeline import ImpressBasePipeline

_mpnn = os.environ.get("MPNN_PATH")
if not _mpnn:
    raise EnvironmentError("MPNN_PATH is not set (path to the ProteinMPNN repo)")

MPNN_PATH = _mpnn


class ProteinBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs=None, **kwargs):
        # Execution metadata
        if configs is None:
            configs = {}

        # Child pipelines receive state in `configs`; top-level pipelines in `**kwargs`.
        # Check kwargs first so callers can override any config key.
        def _cfg(key, default):
            if key in kwargs:
                return kwargs[key]
            if key in configs:
                return configs[key]
            return default

        self.is_child: bool = _cfg("is_child", False)
        self.passes = _cfg("passes", 1)
        self.start_pass: int = _cfg("start_pass", 1)
        self.step_id = _cfg("step_id", 1)
        self.seq_rank = _cfg("seq_rank", 0)
        self.num_seqs = _cfg("num_seqs", 10)
        self.sub_order = _cfg("sub_order", 0)
        self.max_passes = _cfg("max_passes", int(os.environ.get("ROME_MAX_PASSES", 10)))
        self.mpnn_path = _cfg("mpnn_path", MPNN_PATH)
        self.policy = _cfg("policy", None)

        # Sequence and score state
        self.current_scores = {}
        self.iter_seqs = _cfg("iter_seqs", {})
        self.previous_scores = _cfg("previous_scores", {})

        # Exclude from configs any keys already in kwargs to prevent duplicate-keyword TypeError.
        filtered_configs = {k: v for k, v in configs.items() if k not in kwargs}
        super().__init__(name, flow, **filtered_configs, **kwargs)

        self.fasta_list_2 = kwargs.get("fasta_list_2", [])

        # Separate base directories — kwargs take priority (child pipelines),
        # env vars are the default for top-level pipelines.
        self.input_base_path = kwargs.get(
            "input_base_path", os.environ.get("IMPRESS_INPUT_DIR", "")
        )
        self.output_base_path = kwargs.get(
            "output_base_path", os.environ.get("IMPRESS_OUTPUT_DIR", "")
        )
        self.scripts_path = kwargs.get(
            "scripts_path", os.environ.get("IMPRESS_SCRIPTS_DIR", "")
        )

        if not self.input_base_path:
            raise EnvironmentError(f"IMPRESS_INPUT_DIR is not set (dir containing {name}_in/ folders)")
        if not self.output_base_path:
            raise EnvironmentError("IMPRESS_OUTPUT_DIR is not set (dir for af_pipeline_outputs_multi/)")
        if not self.scripts_path:
            raise EnvironmentError("IMPRESS_SCRIPTS_DIR is not set (dir with mpnn_wrapper.py and af2_multimer_reduced.sh)")

        self.input_path = os.path.join(self.input_base_path, f"{self.name}_in")
        self.output_path = os.path.join(self.output_base_path, "af_pipeline_outputs_multi", self.name)
        self.output_path_mpnn = os.path.join(self.output_path, "mpnn")
        self.output_path_af = os.path.join(self.output_path, "af/prediction/best_models")

        for subdir in [
            "af/fasta",
            "af/prediction/best_models",
            "af/prediction/best_ptm",
            "af/prediction/dimer_models",
            "af/prediction/logs",
            *[f"mpnn/job_{i}" for i in range(1, self.max_passes + 1)],
        ]:
            os.makedirs(os.path.join(self.output_path, subdir), exist_ok=True)

        for file_name in os.listdir(self.input_path):
            self.fasta_list_2.append(file_name)

    def _gpu_env(self):
        """Return subprocess env with CUDA_VISIBLE_DEVICES set from policy gpu_affinity."""
        env = {**os.environ}
        if self.policy and self.policy.gpu_affinity:
            env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in self.policy.gpu_affinity)
        return env

    def set_up_new_pipeline_dirs(self, new_pipeline_name):
        base_output = os.path.join(
            self.output_base_path, "af_pipeline_outputs_multi", new_pipeline_name
        )
        input_dir = os.path.join(self.input_base_path, f"{new_pipeline_name}_in")

        # No early-return guard: max_passes may have changed since the directory was
        # first created, and exist_ok=True makes every makedirs call idempotent.

        # all directories to create
        subdirs = [
            "af/fasta",
            "af/prediction",
            "af/prediction/best_models",
            "af/prediction/best_ptm",
            "af/prediction/dimer_models",
            "af/prediction/logs",
            "mpnn",
            *[f"mpnn/job_{i}" for i in range(1, self.max_passes + 1)],
        ]

        paths_to_create = [input_dir, base_output] + [
            os.path.join(base_output, subdir) for subdir in subdirs
        ]

        for path in paths_to_create:
            os.makedirs(path, exist_ok=True)

    def register_pipeline_tasks(self):
        """Register all pipeline tasks"""

        @self.auto_register_task(local_task=True)  # MPNN
        async def s1():
            mpnn_script = os.path.join(self.scripts_path, "mpnn_wrapper.py")
            output_dir = os.path.join(self.output_path_mpnn, f"job_{self.passes}")

            chain = "A" if self.passes == 1 else "B"
            input_path = self.input_path if self.passes == 1 else self.output_path_af

            cmd = (
                f"python {mpnn_script} "
                f"-pdb={input_path} "
                f"-out={output_dir} "
                f"-mpnn={self.mpnn_path} "
                f"-seqs={self.num_seqs} "
                "-is_monomer=0 "
                f"-chains={chain}"
            )
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._gpu_env(),
            )
            stdout, _ = await proc.communicate()
            if stdout:
                print(stdout.decode(), end="", flush=True)
            if proc.returncode != 0:
                raise RuntimeError(f"MPNN failed with exit code {proc.returncode}")

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

                seqs.sort(key=lambda x: x[1], reverse=True)  # descending: best (least-negative log-prob) first
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
        @self.auto_register_task(local_task=True)
        async def s4(target_fasta):
            cmd = (
                f"/bin/bash {self.scripts_path}/af2_multimer_reduced.sh "
                f"{self.output_path}/af/fasta/ "
                f"{target_fasta}.fa "
                f"{self.output_path}/af/prediction/dimer_models/ "
            )
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self._gpu_env(),
            )
            stdout, _ = await proc.communicate()
            if stdout:
                print(stdout.decode(), end="", flush=True)
            if proc.returncode != 0:
                raise RuntimeError(f"AlphaFold failed with exit code {proc.returncode}")

        @self.auto_register_task(local_task=True)
        async def s4_post(target_fasta):
            import glob
            import shutil

            models_path = os.path.join(
                self.output_path, "af", "prediction", "dimer_models", target_fasta
            )
            best_model_pdb = os.path.join(
                self.output_path, "af", "prediction", "best_models", f"{target_fasta}.pdb"
            )
            best_ptm_json = os.path.join(
                self.output_path, "af", "prediction", "best_ptm", f"{target_fasta}.json"
            )
            mpnn_pdb = os.path.join(
                self.output_path, "mpnn", f"job_{self.passes}", f"{target_fasta}.pdb"
            )

            ranked0 = glob.glob(os.path.join(models_path, "*ranked_0*.pdb"))
            ranking_debug = glob.glob(os.path.join(models_path, "*ranking_debug*.json"))

            if ranked0:
                shutil.copy(ranked0[0], best_model_pdb)
                shutil.copy(ranked0[0], mpnn_pdb)
            if ranking_debug:
                shutil.copy(ranking_debug[0], best_ptm_json)

        @self.auto_register_task(local_task=True)  # pLDTT_extract
        async def s5():
            cmd = (
                f"python3 {self.scripts_path}/plddt_extract_pipeline.py "
                f"--path={self.output_base_path} "
                f"--iter={self.passes} "
                f"--out={self.name}"
            )
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            if stdout:
                print(stdout.decode(), end="", flush=True)
            if proc.returncode != 0:
                raise RuntimeError(f"pLDDT extraction failed with exit code {proc.returncode}")

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

            if self.is_child and self.passes == self.start_pass:
                self.logger.pipeline_log(
                    "Skipping MPNN and Ranking steps for this child pipeline "
                    "in the current pass only."
                )

                pass

            else:
                self.logger.pipeline_log("Submitting MPNN task")
                await self.s1()
                self.logger.pipeline_log("MPNN task finished")

                self.logger.pipeline_log("Submitting sequence ranking task")
                await self.s2()
                self.logger.pipeline_log("Sequence ranking task finished")

            self.logger.pipeline_log("Submitting scoring task")
            fasta_files = await self.s3()
            self.logger.pipeline_log("Scoring task finished")

            alphafold_tasks = []

            for target_fasta in fasta_files:
                # launch coroutine without awaiting yet
                alphafold_tasks.append(self.s4(target_fasta=target_fasta))

            self.logger.pipeline_log(
                f"Submitting {len(alphafold_tasks)} Alphafold tasks asynchronously"
            )
            results = await asyncio.gather(*alphafold_tasks, return_exceptions=True)
            failed = [(i, r) for i, r in enumerate(results) if isinstance(r, Exception)]
            for i, r in failed:
                self.logger.pipeline_log(f"AlphaFold task {i} FAILED: {r}")
            if failed:
                raise RuntimeError(
                    f"{len(failed)}/{len(alphafold_tasks)} AlphaFold task(s) failed — aborting pass {self.passes}"
                )
            self.logger.pipeline_log(f"{len(alphafold_tasks)} Alphafold tasks finished")

            self.logger.pipeline_log("Copying AlphaFold best models")
            for target_fasta in fasta_files:
                await self.s4_post(target_fasta=target_fasta)
            self.logger.pipeline_log("AlphaFold best models copied")

            self.logger.pipeline_log("Submitting pLDTT extraction task")
            await self.s5()
            self.logger.pipeline_log("pLDTT extract finished")

            await self.run_adaptive_step(wait=True)

            if self.kill_parent:
                break

            self.passes += 1
