
import asyncio
import os

from impress.pipelines.impress_pipeline import ImpressBasePipeline


# ── State-machine step constants ────────────────────────────────────────────

STEP_DONE              = 0
STEP_BACKBONE_GEN      = 1   # RFD3 diffusion
STEP_BACKBONE_POST     = 2   # cif_to_pdb
STEP_BACKBONE_ANALYSIS = 3   # analysis_backbone + plot_backbone_analysis
STEP_SEQ_PRED          = 4   # LigandMPNN
STEP_SEQ_POST          = 5   # split_seqs
STEP_SEQ_ANALYSIS      = 6   # analysis_sequence + plot_sequence_analysis
STEP_FOLD_PRED         = 7   # chai-lab
STEP_ANALYSIS          = 8   # analysis.py + plot_campaign.py


# ── Default paths ───────────────────────────────────────────────────────────

DEFAULT_SCRIPTS_PATH     = "/home/mason/exdrive/rad/discontinuous_scaffolds/rfd3-islands-validation"
DEFAULT_FOUNDRY_SIF      = "/ocean/projects/dmr170002p/hooten/foundry.sif"
DEFAULT_MPNN_DIR         = "/ocean/projects/dmr170002p/hooten/LigandMPNN"
DEFAULT_RFD_INPUT        = "mcsa_mod8-5.json"
DEFAULT_RMSD_THRESHOLD   = 1.5
DEFAULT_DIFFUSION_BATCH_SIZE = 10


class DiscontinuousScaffoldsPipeline(ImpressBasePipeline):
    """
    IMPRESS pipeline for the discontinuous scaffolds protein design campaign.

    Encodes eight sequential steps:
      1. Backbone generation      (RFDiffusion3 via apptainer)
      2. Backbone postprocessing  (cif_to_pdb.py)
      3. Backbone analysis        (analysis_backbone.py + plot_backbone_analysis.py)
      4. Sequence prediction      (LigandMPNN)
      5. Sequence postprocessing  (split_seqs.py)
      6. Sequence analysis        (analysis_sequence.py + plot_sequence_analysis.py)
      7. Fold prediction          (Chai-lab)
      8. Pipeline analysis        (analysis.py + plot_campaign.py)

    After step 8 a local adaptive step checks whether the analysis CSV is
    present and, if so, restarts the pipeline from step 1.
    """

    def __init__(self, name, flow, configs=None, **kwargs):
        if configs is None:
            configs = {}

        # ── bookkeeping ─────────────────────────────────────────────────────
        self.taskcount = 0
        self.next_step = STEP_BACKBONE_GEN

        # ── configurable paths ──────────────────────────────────────────────
        self.base_path        = kwargs.get("base_path",        os.getcwd())
        self.scripts_path     = kwargs.get("scripts_path",     DEFAULT_SCRIPTS_PATH)
        self.foundry_sif_path = kwargs.get("foundry_sif_path", DEFAULT_FOUNDRY_SIF)
        self.mpnn_dir         = kwargs.get("mpnn_dir",         DEFAULT_MPNN_DIR)

        # ── configurable pipeline inputs ────────────────────────────────────
        self.rfd_input_filepath   = kwargs.get("rfd_input_filepath",   DEFAULT_RFD_INPUT)
        self.lmpnn_pdb_multi_json = kwargs.get("lmpnn_pdb_multi_json", None)
        self.lmpnn_fixed_res_json = kwargs.get("lmpnn_fixed_res_json", None)
        self.island_counts_csv    = kwargs.get("island_counts_csv",    None)
        self.mcsa_pdb_dir         = kwargs.get("mcsa_pdb_dir",         None)
        self.rmsd_threshold       = kwargs.get("rmsd_threshold",       DEFAULT_RMSD_THRESHOLD)
        self.diffusion_batch_size = kwargs.get("diffusion_batch_size", DEFAULT_DIFFUSION_BATCH_SIZE)

        # super().__init__ calls register_pipeline_tasks(), so all self.* must
        # be set before this call.
        super().__init__(name, flow, **configs, **kwargs)

    # ── Task registration ───────────────────────────────────────────────────

    def register_pipeline_tasks(self):
        """Register all eight pipeline steps plus the local analysis check."""

        # ── Step 1: Backbone generation (GPU) ───────────────────────────────
        @self.auto_register_task()
        async def backbone_gen(task_description={"gpus_per_rank": 1}):
            self.taskcount += 1
            taskname = "backbone_gen"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            output_dir = f"{taskdir}/out"
            self.state['rfd3_out_dir'] = output_dir

            return (
                f"bash {self.scripts_path}/step1_backbone_gen.sh "
                f"{self.foundry_sif_path} "
                f"{output_dir} "
                f"{self.rfd_input_filepath} "
                f"{self.diffusion_batch_size}"
            )

        # ── Step 2: Backbone postprocessing — CIF.GZ → PDB (CPU) ────────────
        @self.auto_register_task()
        async def backbone_post(task_description={}):
            self.taskcount += 1
            taskname = "backbone_post"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)
            print(f"state.rfd3_out_dir value before bb-post update is {self.state['rfd3_out_dir']}")
            rfd3_out = self.state['rfd3_out_dir']
            print(f"state.rfd3_out_dir value after bb-post update is {rfd3_out}")
            # Conversion is in-place; PDB files land alongside the CIFs.
            self.state['pdb_dir'] = rfd3_out

            return (
                f"bash {self.scripts_path}/step2_backbone_post.sh "
                f"{self.scripts_path} "
                f"{rfd3_out}"
            )

        # ── Step 3: Backbone analysis (CPU) ─────────────────────────────────
        @self.auto_register_task()
        async def backbone_analysis(task_description={}):
            self.taskcount += 1
            taskname = "backbone_analysis"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            pdb_dir    = self.state['pdb_dir']
            output_csv = f"{taskdir}/out/campaign_analysis_backbone.csv"
            output_dir = f"{taskdir}/out"

            self.state['backbone_analysis_csv']     = output_csv
            self.state['backbone_analysis_out_dir'] = output_dir

            return (
                f"bash {self.scripts_path}/step3_backbone_analysis.sh "
                f"{self.scripts_path} "
                f"{pdb_dir} "
                f"{output_csv} "
                f"{output_dir} "
                f"{self.island_counts_csv}"
            )

        # ── Step 4: Sequence prediction — LigandMPNN (CPU) ──────────────────
        @self.auto_register_task()
        async def seq_pred(task_description={}):
            self.taskcount += 1
            taskname = "seq_pred"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            output_dir = f"{taskdir}/out"
            self.state['lmpnn_out_dir'] = output_dir

            return (
                f"bash {self.scripts_path}/step4_seq_pred.sh "
                f"{self.mpnn_dir} "
                f"{output_dir} "
                f"{self.lmpnn_pdb_multi_json} "
                f"{self.lmpnn_fixed_res_json}"
            )

        # ── Step 5: Sequence postprocessing — split_seqs (CPU) ──────────────
        @self.auto_register_task()
        async def seq_post(task_description={}):
            self.taskcount += 1
            taskname = "seq_post"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            lmpnn_out  = self.state['lmpnn_out_dir']
            seqs_dir   = f"{lmpnn_out}/seqs"
            split_dir  = f"{taskdir}/out/seqs_split"
            self.state['seqs_split_dir'] = split_dir

            return (
                f"bash {self.scripts_path}/step5_seq_post.sh "
                f"{self.scripts_path} "
                f"{seqs_dir} "
                f"{split_dir}"
            )

        # ── Step 6: Sequence analysis (CPU) ──────────────────────────────────
        @self.auto_register_task()
        async def seq_analysis(task_description={}):
            self.taskcount += 1
            taskname = "seq_analysis"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            seqs_split = self.state['seqs_split_dir']
            output_csv = f"{taskdir}/out/campaign_analysis_sequence.csv"
            output_dir = f"{taskdir}/out"

            self.state['seq_analysis_csv']     = output_csv
            self.state['seq_analysis_out_dir'] = output_dir

            return (
                f"bash {self.scripts_path}/step6_seq_analysis.sh "
                f"{self.scripts_path} "
                f"{seqs_split} "
                f"{output_csv} "
                f"{output_dir} "
                f"{self.island_counts_csv}"
            )

        # ── Step 7: Fold prediction — Chai-lab (GPU) ─────────────────────────
        @self.auto_register_task()
        async def fold_pred(task_description={"gpus_per_rank": 1}):
            self.taskcount += 1
            taskname = "fold_pred"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            input_dir  = self.state['seqs_split_dir']
            output_dir = f"{taskdir}/out"
            self.state['chai_out_dir'] = output_dir

            return (
                f"bash {self.scripts_path}/step7_fold_pred.sh "
                f"{self.scripts_path} "
                f"{input_dir} "
                f"{output_dir}"
            )

        # ── Step 8: Pipeline analysis — analysis.py + plot_campaign.py (CPU) ─
        @self.auto_register_task()
        async def pipeline_analysis(task_description={}):
            self.taskcount += 1
            taskname = "pipeline_analysis"
            taskdir  = f"{self.base_path}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            chai_out   = self.state['chai_out_dir']
            output_csv = f"{taskdir}/out/campaign_analysis.csv"
            output_dir = f"{taskdir}/out"

            self.state['analysis_csv']     = output_csv
            self.state['analysis_out_dir'] = output_dir

            return (
                f"bash {self.scripts_path}/step8_pipeline_analysis.sh "
                f"{self.scripts_path} "
                f"{chai_out} "
                f"{output_csv} "
                f"{output_dir} "
                f"{self.mcsa_pdb_dir} "
                f"{self.island_counts_csv} "
                f"{self.rmsd_threshold}"
            )

        # ── Local check: did analysis produce the expected CSV? ───────────────
        @self.auto_register_task(local_task=True)
        async def check_analysis_results():
            analysis_csv = self.state.get('analysis_csv')

            if analysis_csv and os.path.isfile(analysis_csv):
                self.state['analysis_present']   = True
                self.state['last_analysis_step'] = 'analysis'
                self.logger.pipeline_log(
                    f"[check] Analysis CSV found at {analysis_csv}; analysis_present=True"
                )
            else:
                self.state['analysis_present']   = False
                self.state['last_analysis_step'] = 'analysis'
                self.logger.pipeline_log(
                    f"[check] Analysis CSV not found at {analysis_csv!r}; analysis_present=False"
                )

    # ── Main execution loop ─────────────────────────────────────────────────

    async def run(self):
        """
        Execute the eight-step pipeline sequentially.

        The outer while-loop supports the adaptive restart: if the adaptive
        function sets next_step = STEP_BACKBONE_GEN after analysis, all eight
        steps run again from the top.
        """
        self.next_step = STEP_BACKBONE_GEN
        self.state.setdefault('run_count', 0)
        self.logger.pipeline_log("DiscontinuousScaffoldsPipeline starting")

        while self.next_step != STEP_DONE:

            self.logger.pipeline_log("Step 1: backbone generation (RFD3)")
            await self.backbone_gen(task_description={"gpus_per_rank": 1})
            self.logger.pipeline_log("Step 1 finished")

            self.logger.pipeline_log("Step 2: backbone postprocessing (cif_to_pdb)")
            await self.backbone_post(task_description={})
            self.logger.pipeline_log("Step 2 finished")

            self.logger.pipeline_log("Step 3: backbone analysis (analysis_backbone + plot_backbone_analysis)")
            await self.backbone_analysis(task_description={})
            self.logger.pipeline_log("Step 3 finished")

            self.logger.pipeline_log("Step 4: sequence prediction (LigandMPNN)")
            await self.seq_pred(task_description={})
            self.logger.pipeline_log("Step 4 finished")

            self.logger.pipeline_log("Step 5: sequence postprocessing (split_seqs)")
            await self.seq_post(task_description={})
            self.logger.pipeline_log("Step 5 finished")

            self.logger.pipeline_log("Step 6: sequence analysis (analysis_sequence + plot_sequence_analysis)")
            await self.seq_analysis(task_description={})
            self.logger.pipeline_log("Step 6 finished")

            self.logger.pipeline_log("Step 7: fold prediction (Chai-lab)")
            await self.fold_pred(task_description={"gpus_per_rank": 1})
            self.logger.pipeline_log("Step 7 finished")

            self.logger.pipeline_log("Step 8: pipeline analysis (analysis.py + plot_campaign.py)")
            await self.pipeline_analysis(task_description={})
            self.logger.pipeline_log("Step 8 finished")

            await self.check_analysis_results()
            await self.run_adaptive_step(wait=True)
            # adaptive_fn sets self.next_step:
            #   STEP_BACKBONE_GEN → restart loop
            #   STEP_DONE         → exit loop

        self.logger.pipeline_log("DiscontinuousScaffoldsPipeline complete")

    async def finalize(self):
        pass
