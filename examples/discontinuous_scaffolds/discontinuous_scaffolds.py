
import asyncio
import json
import os
import pathlib

import pandas as pd

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
DEFAULT_LMPNN_NUM_BATCHES = 4


# ── Module-level helper ──────────────────────────────────────────────────────

def _identify_passing_models(df, model_col, thresholds):
    """
    Returns (passing_models, failing_models) lists.

    A model passes if any of its rows passes ALL active thresholds
    simultaneously (full battery).  If no thresholds are active, all
    models pass.

    Args:
        df: pandas DataFrame of analysis results.
        model_col: column name identifying the binding motif model.
        thresholds: dict of metric_name → (lower, upper) or None.
            None entries are skipped.  A bound value of None means
            that side of the interval is open (no bound applied).
    """
    active = {k: v for k, v in thresholds.items() if v is not None}
    if not active:
        return list(df[model_col].unique()), []

    passing, failing = [], []
    for model, group in df.groupby(model_col):
        model_passes = False
        for _, row in group.iterrows():
            row_passes = True
            for metric, (lower, upper) in active.items():
                if metric not in row.index or pd.isna(row[metric]):
                    row_passes = False
                    break
                v = row[metric]
                if (lower is not None and v < lower) or (upper is not None and v > upper):
                    row_passes = False
                    break
            if row_passes:
                model_passes = True
                break
        (passing if model_passes else failing).append(model)

    return passing, failing


def generate_lmpnn_jsons(rfd_input_filepath, diffusion_batch_size, output_dir):
    """
    Derive LMPNN batch JSON files from an RFD input file.

    Generates two JSON files in ``output_dir``:
    - ``generated_lmpnn_pdb.json``: maps expected PDB paths to ``""``
    - ``generated_lmpnn_fixed_res.json``: maps expected PDB paths to a
      space-separated string of fixed residue keys from ``select_fixed_atoms``

    PDB path keys use the ``./outputs_rfd3/`` prefix and the filename
    convention ``{campaign_name}_{model_name}_0_model_{num}.pdb``, where
    ``campaign_name`` is the stem of ``rfd_input_filepath`` and ``num``
    ranges from 0 to ``diffusion_batch_size - 1``.

    Returns ``(pdb_multi_path, fixed_res_path)``.
    """
    campaign_name = pathlib.Path(rfd_input_filepath).stem
    with open(rfd_input_filepath) as fh:
        rfd_data = json.load(fh)

    pdb_multi = {}
    fixed_res = {}
    for model_name, model_cfg in rfd_data.items():
        fixed = " ".join(model_cfg["select_fixed_atoms"].keys())
        for num in range(diffusion_batch_size):
            key = f"./outputs_rfd3/{campaign_name}_{model_name}_0_model_{num}.pdb"
            pdb_multi[key] = ""
            fixed_res[key] = fixed

    os.makedirs(output_dir, exist_ok=True)
    pdb_path   = os.path.join(output_dir, "generated_lmpnn_pdb.json")
    fixed_path = os.path.join(output_dir, "generated_lmpnn_fixed_res.json")
    with open(pdb_path,   "w") as fh:
        json.dump(pdb_multi, fh, indent=2)
    with open(fixed_path, "w") as fh:
        json.dump(fixed_res, fh, indent=2)
    return pdb_path, fixed_path


class DiscontinuousScaffoldsPipeline(ImpressBasePipeline):
    """
    IMPRESS pipeline for the discontinuous scaffolds protein design campaign.

    Encodes eight sequential steps grouped into three process stages:

    Backbone stage (steps 1–3):
      1. Backbone generation      (RFDiffusion3 via apptainer)
      2. Backbone postprocessing  (cif_to_pdb.py)
      3. Backbone analysis        (analysis_backbone.py + plot_backbone_analysis.py)

    Sequence stage (steps 4–6):
      4. Sequence prediction      (LigandMPNN)
      5. Sequence postprocessing  (split_seqs.py)
      6. Sequence analysis        (analysis_sequence.py + plot_sequence_analysis.py)

    Fold stage (steps 7–8):
      7. Fold prediction          (Chai-lab)
      8. Pipeline analysis        (analysis.py + plot_campaign.py)

    After each stage an adaptive step checks per-model quality against
    configurable thresholds.  Models that fail are rerouted to a branch
    pipeline starting from that stage; the current pipeline continues
    with only the passing models.

    Branch pipelines are supported via the ``start_step`` kwarg, which
    causes ``run()`` to skip all stages before that step.  The
    ``branch_id`` kwarg is used to namespace output directories.
    ``initial_state`` allows pre-seeding ``self.state`` for pipelines
    that start partway through (e.g. a seq-start branch needs
    ``pdb_dir`` already set).
    """

    def __init__(self, name, flow, configs=None, **kwargs):
        if configs is None:
            configs = {}

        # ── bookkeeping ─────────────────────────────────────────────────────
        self.taskcount = 0

        # ── branching control ────────────────────────────────────────────────
        self.start_step = kwargs.get('start_step', STEP_BACKBONE_GEN)
        self.branch_ct  = kwargs.get('branch_ct',  0)
        self.branch_id  = kwargs.get('branch_id',  f"b{self.branch_ct}")

        # ── configurable paths ──────────────────────────────────────────────
        self.base_path        = kwargs.get("base_path",        os.getcwd())
        self.scripts_path     = kwargs.get("scripts_path",     DEFAULT_SCRIPTS_PATH)
        self.foundry_sif_path = kwargs.get("foundry_sif_path", DEFAULT_FOUNDRY_SIF)
        self.mpnn_dir         = kwargs.get("mpnn_dir",         DEFAULT_MPNN_DIR)

        # ── configurable pipeline inputs ────────────────────────────────────
        self.rfd_input_filepath   = kwargs.get("rfd_input_filepath",   DEFAULT_RFD_INPUT)
        self.island_counts_csv    = kwargs.get("island_counts_csv",    None)
        self.mcsa_pdb_dir         = kwargs.get("mcsa_pdb_dir",         None)
        self.rmsd_threshold       = kwargs.get("rmsd_threshold",       DEFAULT_RMSD_THRESHOLD)
        self.diffusion_batch_size = kwargs.get("diffusion_batch_size", DEFAULT_DIFFUSION_BATCH_SIZE)
        self.lmpnn_num_batches    = kwargs.get("lmpnn_num_batches",    DEFAULT_LMPNN_NUM_BATCHES)

        # Derive LMPNN JSONs from RFD input if not explicitly provided.
        # Branch pipelines always receive explicit (pre-filtered) JSONs, so
        # generation is only triggered for root pipelines.
        if kwargs.get("lmpnn_pdb_multi_json") and kwargs.get("lmpnn_fixed_res_json"):
            self.lmpnn_pdb_multi_json = kwargs["lmpnn_pdb_multi_json"]
            self.lmpnn_fixed_res_json = kwargs["lmpnn_fixed_res_json"]
        else:
            gen_dir = os.path.join(self.base_path, self.branch_id)
            self.lmpnn_pdb_multi_json, self.lmpnn_fixed_res_json = generate_lmpnn_jsons(
                self.rfd_input_filepath, self.diffusion_batch_size, gen_dir
            )

        # ── backbone thresholds — (lower, upper) or None to disable ─────────
        self.backbone_rog_bounds      = kwargs.get('backbone_rog_bounds',      None)
        self.backbone_ala_bounds      = kwargs.get('backbone_ala_bounds',      None)
        self.backbone_gly_bounds      = kwargs.get('backbone_gly_bounds',      None)
        self.backbone_helix_bounds    = kwargs.get('backbone_helix_bounds',    None)
        self.backbone_sheet_bounds    = kwargs.get('backbone_sheet_bounds',    None)
        self.backbone_lig_dist_bounds = kwargs.get('backbone_lig_dist_bounds', None)

        # ── sequence thresholds ──────────────────────────────────────────────
        self.seq_ligand_conf_bounds  = kwargs.get('seq_ligand_conf_bounds',  None)
        self.seq_overall_conf_bounds = kwargs.get('seq_overall_conf_bounds', None)

        # super().__init__ calls register_pipeline_tasks(), so all self.* must
        # be set before this call.
        super().__init__(name, flow, **configs, **kwargs)

        # Pre-populate state for branch pipelines that skip early stages
        # (e.g. a seq-start branch needs pdb_dir already set).
        self.state.update(kwargs.get('initial_state', {}))

    # ── Task registration ───────────────────────────────────────────────────

    def register_pipeline_tasks(self):
        """Register all eight pipeline steps plus the local analysis checks."""

        # ── Step 1: Backbone generation (GPU) ───────────────────────────────
        @self.auto_register_task()
        async def backbone_gen(task_description={"gpus_per_rank": 1}):
            self.taskcount += 1
            taskname = "backbone_gen"
            taskdir  = f"{self.base_path}/{self.branch_id}/{self.taskcount}_{taskname}"
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
            taskdir  = f"{self.base_path}/{self.branch_id}/{self.taskcount}_{taskname}"
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
            taskdir  = f"{self.base_path}/{self.branch_id}/{self.taskcount}_{taskname}"
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
        async def seq_pred(task_description={"gpus_per_rank": 1}):
            self.taskcount += 1
            taskname = "seq_pred"
            taskdir  = f"{self.base_path}/{self.branch_id}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            output_dir = f"{taskdir}/out"
            self.state['lmpnn_out_dir'] = output_dir

            # Use filtered JSONs if the backbone adaptive step created them;
            # otherwise fall back to the original pipeline inputs.
            lmpnn_json = self.state.get(
                'current_lmpnn_pdb_multi_json', self.lmpnn_pdb_multi_json)
            fixed_json = self.state.get(
                'current_lmpnn_fixed_res_json', self.lmpnn_fixed_res_json)

            # Remap static JSON keys to runtime pdb_dir paths.
            # The static JSONs use relative paths (e.g. "./outputs_rfd3/model.pdb")
            # but PDB files are generated at runtime under self.state['pdb_dir'].
            pdb_dir = self.state['pdb_dir']

            def _remap_json(src_path, dst_path):
                with open(src_path) as fh:
                    data = json.load(fh)
                remapped = {
                    os.path.join(pdb_dir, os.path.basename(k)): v
                    for k, v in data.items()
                }
                with open(dst_path, 'w') as fh:
                    json.dump(remapped, fh, indent=2)
                return dst_path

            runtime_json       = _remap_json(lmpnn_json,  f"{taskdir}/in/lmpnn_pdb_multi.json")
            runtime_fixed_json = _remap_json(fixed_json,   f"{taskdir}/in/lmpnn_fixed_res.json")

            return (
                f"bash {self.scripts_path}/step4_seq_pred.sh "
                f"{self.mpnn_dir} "
                f"{output_dir} "
                f"{runtime_json} "
                f"{runtime_fixed_json} "
                f"{self.lmpnn_num_batches} "
            )

        # ── Step 5: Sequence postprocessing — split_seqs (CPU) ──────────────
        @self.auto_register_task()
        async def seq_post(task_description={}):
            self.taskcount += 1
            taskname = "seq_post"
            taskdir  = f"{self.base_path}/{self.branch_id}/{self.taskcount}_{taskname}"
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
            taskdir  = f"{self.base_path}/{self.branch_id}/{self.taskcount}_{taskname}"
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
            taskdir  = f"{self.base_path}/{self.branch_id}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            # Use filtered seqs dir if the sequence adaptive step created one.
            input_dir  = self.state.get(
                'current_seqs_split_dir', self.state['seqs_split_dir'])
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
            taskdir  = f"{self.base_path}/{self.branch_id}/{self.taskcount}_{taskname}"
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

        # ── Local check: backbone analysis results ────────────────────────────
        @self.auto_register_task(local_task=True)
        async def check_backbone_results():
            csv = self.state.get('backbone_analysis_csv')
            self.state['last_analysis_step'] = 'backbone'

            if not csv or not os.path.isfile(csv):
                self.logger.pipeline_log(
                    f"[check_backbone] CSV not found at {csv!r}; treating all models as failing"
                )
                self.state['passing_backbone_models'] = []
                self.state['failing_backbone_models'] = []
                return

            df = pd.read_csv(csv)
            thresholds = {
                'radius_of_gyration':           self.backbone_rog_bounds,
                'alanine_content':              self.backbone_ala_bounds,
                'glycine_content':              self.backbone_gly_bounds,
                'helix_fraction':               self.backbone_helix_bounds,
                'sheet_fraction':               self.backbone_sheet_bounds,
                'n_clashing.ligand_min_distance': self.backbone_lig_dist_bounds,
            }
            passing, failing = _identify_passing_models(df, 'model_name', thresholds)

            self.state['passing_backbone_models'] = passing
            self.state['failing_backbone_models'] = failing
            self.logger.pipeline_log(
                f"[check_backbone] passing={len(passing)} failing={len(failing)} models"
            )

        # ── Local check: sequence analysis results ────────────────────────────
        @self.auto_register_task(local_task=True)
        async def check_seq_results():
            csv = self.state.get('seq_analysis_csv')
            self.state['last_analysis_step'] = 'sequence'

            if not csv or not os.path.isfile(csv):
                self.logger.pipeline_log(
                    f"[check_seq] CSV not found at {csv!r}; treating all models as failing"
                )
                self.state['passing_seq_models'] = []
                self.state['failing_seq_models'] = []
                return

            df = pd.read_csv(csv)
            thresholds = {
                'ligand_confidence':  self.seq_ligand_conf_bounds,
                'overall_confidence': self.seq_overall_conf_bounds,
            }
            passing, failing = _identify_passing_models(df, 'model_name', thresholds)

            self.state['passing_seq_models'] = passing
            self.state['failing_seq_models'] = failing
            self.logger.pipeline_log(
                f"[check_seq] passing={len(passing)} failing={len(failing)} models"
            )

        # ── Local check: fold/pipeline analysis results ───────────────────────
        @self.auto_register_task(local_task=True)
        async def check_fold_results():
            self.state['last_analysis_step'] = 'fold'
            csv = self.state.get('analysis_csv')

            if not csv or not os.path.isfile(csv):
                self.logger.pipeline_log(
                    f"[check_fold] CSV not found at {csv!r}; treating all models as failing"
                )
                self.state['best_fold'] = {}
                self.state['passing_fold_models'] = []
                self.state['failing_fold_models'] = []
                return

            df = pd.read_csv(csv)
            chai_out = self.state.get('chai_out_dir', '')
            best_fold = {}
            for model_name, group in df.groupby('model_name'):
                best_row = group.loc[group['motif_rmsd'].idxmin()]
                best_fold[model_name] = {
                    'motif_rmsd':         float(best_row['motif_rmsd']),
                    'run_dir':            os.path.abspath(
                                              os.path.join(chai_out, str(best_row['run_dir']))
                                          ),
                    'seed':               int(best_row['seed']),
                    'chai1_model_idx':    int(best_row['chai1_model_idx']),
                    'anchor_residues':    str(best_row.get('anchor_residues', '')),
                    'anchor_sequences':   str(best_row.get('anchor_sequences', '')),
                    'anchor_ref_residues': str(best_row.get('anchor_ref_residues', '')),
                }

            self.state['best_fold'] = best_fold

            passing = [m for m, v in best_fold.items() if v['motif_rmsd'] < self.rmsd_threshold]
            failing = [m for m, v in best_fold.items() if v['motif_rmsd'] >= self.rmsd_threshold]

            self.state['passing_fold_models'] = passing
            self.state['failing_fold_models'] = failing
            self.logger.pipeline_log(
                f"[check_fold] passing={len(passing)} failing={len(failing)} models"
            )

    # ── Main execution loop ─────────────────────────────────────────────────

    async def run(self):
        """
        Execute pipeline stages sequentially, with an adaptive check after
        each stage.

        Supports starting at an arbitrary stage via ``self.start_step`` so
        that branch pipelines (spawned by the adaptive function) can begin
        at the sequence or fold stage without re-running earlier work.

        Adaptive behaviour per stage:
          - Backbone: adaptive_fn may spawn a backbone-start branch for
            failing models and filter LMPNN inputs for the current pipeline.
          - Sequence: adaptive_fn may spawn a sequence-start branch for
            failing models and filter seqs_split_dir for the current pipeline.
          - Fold: adaptive_fn sets next_step = STEP_DONE.

        The adaptive_fn sets ``self.next_step``; setting it to STEP_DONE
        terminates the current pipeline after the current stage.
        """
        self.state.setdefault('run_count', 0)
        self.next_step = STEP_SEQ_PRED   # default continuation sentinel

        # ── Stage 1: Backbone (steps 1–3) ────────────────────────────────────
        if self.start_step <= STEP_BACKBONE_GEN:
            self.logger.pipeline_log("Stage 1 / Step 1: backbone generation (RFD3)")
            await self.backbone_gen(task_description={"gpus_per_rank": 1})
            self.logger.pipeline_log("Step 1 finished")

            self.logger.pipeline_log("Stage 1 / Step 2: backbone postprocessing (cif_to_pdb)")
            await self.backbone_post(task_description={})
            self.logger.pipeline_log("Step 2 finished")

            self.logger.pipeline_log(
                "Stage 1 / Step 3: backbone analysis (analysis_backbone + plot_backbone_analysis)")
            await self.backbone_analysis(task_description={})
            self.logger.pipeline_log("Step 3 finished")

            await self.check_backbone_results()
            await self.run_adaptive_step(wait=True)

            if self.next_step == STEP_DONE:
                self.logger.pipeline_log(
                    "DiscontinuousScaffoldsPipeline terminating after backbone stage")
                return

        # ── Stage 2: Sequence (steps 4–6) ────────────────────────────────────
        if self.start_step <= STEP_SEQ_PRED:
            self.logger.pipeline_log("Stage 2 / Step 4: sequence prediction (LigandMPNN)")
            await self.seq_pred(task_description={})
            self.logger.pipeline_log("Step 4 finished")

            self.logger.pipeline_log("Stage 2 / Step 5: sequence postprocessing (split_seqs)")
            await self.seq_post(task_description={})
            self.logger.pipeline_log("Step 5 finished")

            self.logger.pipeline_log(
                "Stage 2 / Step 6: sequence analysis (analysis_sequence + plot_sequence_analysis)")
            await self.seq_analysis(task_description={})
            self.logger.pipeline_log("Step 6 finished")

            await self.check_seq_results()
            await self.run_adaptive_step(wait=True)

            if self.next_step == STEP_DONE:
                self.logger.pipeline_log(
                    "DiscontinuousScaffoldsPipeline terminating after sequence stage")
                return

        # ── Stage 3: Fold (steps 7–8) ─────────────────────────────────────────
        self.logger.pipeline_log("Stage 3 / Step 7: fold prediction (Chai-lab)")
        await self.fold_pred(task_description={"gpus_per_rank": 1})
        self.logger.pipeline_log("Step 7 finished")

        self.logger.pipeline_log(
            "Stage 3 / Step 8: pipeline analysis (analysis.py + plot_campaign.py)")
        await self.pipeline_analysis(task_description={})
        self.logger.pipeline_log("Step 8 finished")

        await self.check_fold_results()
        await self.run_adaptive_step(wait=True)

        self.logger.pipeline_log("DiscontinuousScaffoldsPipeline complete")

    async def finalize(self):
        pass
