
import asyncio
import copy
import os
import shutil

from impress.pipelines.impress_pipeline import ImpressBasePipeline

MPNN_PATH = os.environ.get("MPNN_PATH", "")

_BOLTZ_CHAIN_MAP = {'pdz': 'A', 'pep': 'B'}

def _copy_pdb_rename_chains(src, dst, chain_map=_BOLTZ_CHAIN_MAP):
    """Copy a PDB, replacing Boltz multi-char chain IDs with standard single-char IDs."""
    with open(src) as f_in, open(dst, 'w') as f_out:
        for line in f_in:
            if line.startswith(('ATOM', 'HETATM', 'TER')):
                chain = line[21:24]
                if chain in chain_map:
                    line = line[:21] + chain_map[chain] + line[24:]
            f_out.write(line)


class ProteinBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs=None, **kwargs):
        if configs is None:
            configs = {}

        self.is_child: bool = kwargs.get("is_child", False)
        self.passes = kwargs.get("passes", 1)
        self.start_pass: int = kwargs.get("start_pass", 1)
        self.step_id = kwargs.get("step_id", 1)
        self.seq_rank = kwargs.get("seq_rank", 0)
        self.num_seqs = kwargs.get("num_seqs", 10)
        self.sub_order = kwargs.get("sub_order", 0)
        self.max_passes = kwargs.get("max_passes", 10)
        self.mpnn_path = kwargs.get("mpnn_path") or MPNN_PATH
        if not self.mpnn_path:
            raise ValueError("mpnn_path must be supplied via kwarg or MPNN_PATH env var")
        self.peptide_seq: str = kwargs.get("peptide_seq", "EGYQDYEPEA")
        self.policy = kwargs.get("policy", None)

        self.current_scores = {}
        self.iter_seqs = kwargs.get("iter_seqs", {})
        self.previous_scores = kwargs.get("previous_scores", {})

        super().__init__(name, flow, **configs, **kwargs)

        self.fasta_list_2 = kwargs.get("fasta_list_2", [])
        self.base_path = kwargs.get("base_path", os.getcwd())
        self.input_base_path = kwargs.get("input_base_path", self.base_path)
        self.output_base_path = kwargs.get("output_base_path", self.base_path)
        self.scripts_path = os.path.join(self.base_path, "scripts")
        self.input_path = os.path.join(self.input_base_path, f"prod_in/{self.name}_in")

        self.output_path = os.path.join(
            self.output_base_path, "af_pipeline_outputs_multi", self.name
        )
        self.output_path_mpnn = os.path.join(self.output_path, "mpnn")
        self.output_path_af = os.path.join(
            self.output_path, "af/prediction/best_models"
        )

        for file_name in os.listdir(self.input_path):
            self.fasta_list_2.append(file_name)

    def set_up_new_pipeline_dirs(self, new_pipeline_name):
        base_output = os.path.join(
            self.output_base_path, "af_pipeline_outputs_multi", new_pipeline_name
        )
        input_dir = os.path.join(self.input_base_path, f"prod_in/{new_pipeline_name}_in")

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

        @self.auto_register_task(local_task=True)
        async def s1():
            self.step_id += 1
            mpnn_script = os.path.join(self.base_path, "mpnn_wrapper.py")
            output_dir = os.path.join(self.output_path_mpnn, f"job_{self.passes}")
            os.makedirs(output_dir, exist_ok=True)

            chain = "A"
            input_path = self.input_path if self.passes == 1 else self.output_path_af

            cmd = (
                f"bash {self.scripts_path}/s1_mpnn.sh "
                f"{mpnn_script} "
                f"{input_path} "
                f"{output_dir} "
                f"{self.mpnn_path} "
                f"{self.num_seqs} "
                f"{chain}"
            )
            log_path = os.path.join(output_dir, "mpnn_run.log")
            with open(log_path, "w") as lf:
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=lf, stderr=asyncio.subprocess.STDOUT,
                    env=self._gpu_env(),
                )
            rc = await proc.wait()
            if rc != 0:
                raise RuntimeError(f"s1 MPNN failed (exit {rc})")

        @self.auto_register_task(local_task=True)
        async def s2():
            self.step_id += 1
            job_seqs_dir = f"{self.output_path_mpnn}/job_{self.passes}/seqs"

            for file_name in os.listdir(job_seqs_dir):
                seqs = []
                with open(os.path.join(job_seqs_dir, file_name)) as fd:
                    lines = fd.readlines()[2:]

                score = None
                for line in lines:
                    line = line.strip()
                    if line.startswith(">"):
                        score = float(line.split(",")[2].replace(" score=", ""))
                    else:
                        seqs.append([line, score])

                seqs.sort(key=lambda x: x[1])
                self.iter_seqs[file_name.split(".")[0]] = seqs

        @self.auto_register_task(local_task=True)
        async def s3():
            self.step_id += 1
            output_dir = os.path.join(self.output_path, "af", "fasta")
            msa_cache = os.path.expanduser("~/boltz/msa_cache")

            fasta_file_to_return = []
            for fasta_file in self.fasta_list_2:
                base_name = fasta_file.split(".")[0]
                fasta_file_to_return.append(base_name)
                design_seq = self.iter_seqs[base_name][self.seq_rank][0]
                pep_seq = self.peptide_seq

                pdz_msa = os.path.join(
                    msa_cache, f"boltz_results_{base_name}", "msa", f"{base_name}_0.csv"
                )
                pep_msa = os.path.join(
                    msa_cache, f"boltz_results_{base_name}", "msa", f"{base_name}_1.csv"
                )
                if os.path.exists(pdz_msa) and os.path.exists(pep_msa):
                    pdz_tag = f">pdz|protein|{pdz_msa}"
                    pep_tag = f">pep|protein|{pep_msa}"
                else:
                    pdz_tag = ">pdz|protein|empty"
                    pep_tag = ">pep|protein|empty"

                fasta_path = os.path.join(output_dir, f"{base_name}.fa")
                with open(fasta_path, "w") as f:
                    f.write(f"{pdz_tag}\n{design_seq}\n{pep_tag}\n{pep_seq}\n")

            return fasta_file_to_return

        @self.auto_register_task(local_task=True)
        async def s4(target_fasta):
            self.step_id += 1
            cmd = (
                f"bash {self.scripts_path}/s4_boltz.sh "
                f"{self.output_path}/af/fasta/{target_fasta}.fa "
                f"{self.output_path}/af/prediction/dimer_models/{target_fasta}"
            )
            self.logger.pipeline_log(f"s4 command for {target_fasta}: {cmd}")
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=self._gpu_env(),
            )
            rc = await proc.wait()
            if rc != 0:
                raise RuntimeError(f"Boltz failed for {target_fasta} (exit {rc})")

        @self.auto_register_task(local_task=True)
        async def s4_post_exec(
            target_fasta,
            models_path,
            best_model_pdb,
            best_ptm_json,
            mpnn_pdb
        ):
            self.step_id += 1
            _copy_pdb_rename_chains(f"{models_path}/{target_fasta}_model_0.pdb", best_model_pdb)
            shutil.copy(f"{models_path}/confidence_{target_fasta}_model_0.json", best_ptm_json)
            _copy_pdb_rename_chains(f"{models_path}/{target_fasta}_model_0.pdb", mpnn_pdb)

        @self.auto_register_task()
        async def s5():
            self.step_id += 1
            return (
                f"bash {self.scripts_path}/s5_plddt_extract.sh "
                f"{self.output_base_path} "
                f"{self.passes} "
                f"{self.name}"
            )

    async def get_scores_map(self):
        return {"c_scores": self.current_scores, "p_scores": self.previous_scores}

    def finalize(self, sub_iter_seqs):
        from pathlib import Path
        for a in sub_iter_seqs:
            self.fasta_list_2.remove(f"{a}.pdb")
            Path(f"{self.output_path_af}/{a}.pdb").unlink(missing_ok=True)
            Path(f"{self.output_path}/af/fasta/{a}.fa").unlink(missing_ok=True)
        self.previous_scores = copy.deepcopy(self.current_scores)

    async def run(self):
        self.logger.pipeline_log(f"Running for a maximum of {self.max_passes} passes")

        self.set_up_new_pipeline_dirs(self.name)

        while self.passes <= self.max_passes:
            self.logger.pipeline_log(f"Starting pass {self.passes}")

            if self.is_child and self.passes == self.start_pass:
                self.logger.pipeline_log(
                    "Skipping MPNN and Ranking steps for this child pipeline "
                    "in the current pass only."
                )
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
            post_exec_tasks = []

            _boltz_sem = asyncio.Semaphore(2)

            async def _guarded_s4(target_fasta):
                async with _boltz_sem:
                    return await self.s4(target_fasta=target_fasta)

            for target_fasta in fasta_files:
                models_path = os.path.join(
                    self.output_path, "af", "prediction", "dimer_models", target_fasta,
                    f"boltz_results_{target_fasta}", "predictions", target_fasta
                )
                best_model_pdb = os.path.join(
                    self.output_path, "af", "prediction", "best_models",
                    f"{target_fasta}.pdb",
                )
                best_ptm_json = os.path.join(
                    self.output_path, "af", "prediction", "best_ptm",
                    f"{target_fasta}.json",
                )
                mpnn_pdb = os.path.join(
                    self.output_path, "mpnn", f"job_{self.passes}",
                    f"{target_fasta}.pdb",
                )

                alphafold_tasks.append(_guarded_s4(target_fasta))
                post_exec_tasks.append(
                    self.s4_post_exec(
                        target_fasta=target_fasta,
                        models_path=models_path,
                        best_model_pdb=best_model_pdb,
                        best_ptm_json=best_ptm_json,
                        mpnn_pdb=mpnn_pdb,
                    )
                )

            self.logger.pipeline_log(
                f"Submitting {len(alphafold_tasks)} Boltz tasks asynchronously"
            )
            s4_results = await asyncio.gather(*alphafold_tasks, return_exceptions=True)
            self.logger.pipeline_log(f"{len(alphafold_tasks)} Boltz tasks finished")
            for fasta_name, result in zip(fasta_files, s4_results):
                if isinstance(result, Exception):
                    self.logger.pipeline_log(f"s4 FAILED for {fasta_name}: {result}")
                else:
                    self.logger.pipeline_log(f"s4 DONE for {fasta_name}")

            s4_post_results = await asyncio.gather(*post_exec_tasks, return_exceptions=True)
            any_s4_ok = False
            for fasta_name, result in zip(fasta_files, s4_post_results):
                if isinstance(result, Exception):
                    self.logger.pipeline_log(f"s4_post_exec FAILED for {fasta_name}: {result}")
                else:
                    self.logger.pipeline_log(f"s4_post_exec DONE for {fasta_name}")
                    any_s4_ok = True

            if not any_s4_ok:
                raise RuntimeError("All s4 tasks failed — skipping pLDDT extraction")

            self.logger.pipeline_log("Submitting pLDDT extraction task")

            staged_file = f"af_stats_{self.name}_pass_{self.passes}.csv"
            await self.s5(
                task_description={
                    "output_staging": [
                        {
                            "source": f"task:///{staged_file}",
                            "target": f"client:///{staged_file}",
                        }
                    ],
                }
            )
            self.logger.pipeline_log("pLDDT extraction finished")

            await self.run_adaptive_step(wait=True)

            if self.kill_parent:
                break

            self.passes += 1
