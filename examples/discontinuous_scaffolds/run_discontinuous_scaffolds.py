
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List

from radical.asyncflow import LocalExecutionBackend
from rhapsody.backends import DragonExecutionBackendV3

from impress import ImpressManager, PipelineSetup
from discontinuous_scaffolds import (
    DiscontinuousScaffoldsPipeline,
    STEP_BACKBONE_GEN,
    STEP_SEQ_PRED,
    STEP_FOLD_PRED,
    STEP_DONE,
)


# ── Configurable parameters ─────────────────────────────────────────────────

SCRIPTS_PATH     = "/ocean/projects/dmr170002p/hooten/discontinuous_scaffolds/IMPRESS/examples/discontinuous_scaffolds/scripts"
FOUNDRY_SIF_PATH = "/ocean/projects/dmr170002p/hooten/foundry.sif"
MPNN_DIR         = "/ocean/projects/dmr170002p/hooten/LigandMPNN"

RFD_INPUT_FILEPATH   = f"{SCRIPTS_PATH}/mcsa_41_one.json"
ISLAND_COUNTS_CSV    = f"{SCRIPTS_PATH}/island_counts.csv"
MCSA_PDB_DIR         = f"{SCRIPTS_PATH}/mcsa_41"
RMSD_THRESHOLD       = 1.5
DIFFUSION_BATCH_SIZE = 1
LMPNN_NUM_BATCHES    = 1

# ── Adaptive thresholds ──────────────────────────────────────────────────────
# Each value is either None (threshold disabled) or a (lower, upper) tuple.
# A model passes the backbone stage if at least one of its backbone structures
# satisfies ALL active backbone thresholds simultaneously.
# A model passes the sequence stage if at least one of its sequences
# satisfies ALL active sequence thresholds simultaneously.

BACKBONE_ROG_BOUNDS      = (0,19.1)   # radius_of_gyration,           e.g. (5.0, 25.0)
BACKBONE_ALA_BOUNDS      = (.15,.55)   # alanine_content
BACKBONE_GLY_BOUNDS      = (.035,.115)   # glycine_content
BACKBONE_HELIX_BOUNDS    = (.01,1)   # helix_fraction
BACKBONE_SHEET_BOUNDS    = (0,0.4)   # sheet_fraction
BACKBONE_LIG_DIST_BOUNDS = (0,4.5)   # n_clashing.ligand_min_distance

SEQ_LIGAND_CONF_BOUNDS   = (0.37,1)   # ligand_confidence,            e.g. (0.5, 1.0)
SEQ_OVERALL_CONF_BOUNDS  = (0.42,1)   # overall_confidence


# ── Helper functions ─────────────────────────────────────────────────────────

def _filter_json_by_models(json_path, model_list, output_path):
    """
    Load a JSON file whose top-level keys are model names, keep only the keys
    present in ``model_list``, and write the result to ``output_path``.

    Returns ``output_path``.
    """
    with open(json_path) as fh:
        data = json.load(fh)

    filtered = {k: v for k, v in data.items() if k in model_list}
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as fh:
        json.dump(filtered, fh, indent=2)

    return output_path


def _filter_rfd_json_by_models(json_path, model_list, output_path):
    """
    Like _filter_json_by_models but also rewrites each entry's "input" value
    from a path relative to json_path's directory to an absolute path.
    This is required when the filtered JSON is written to a different directory
    (e.g. a branch pipeline directory) than the original.
    """
    base_dir = os.path.dirname(os.path.abspath(json_path))
    with open(json_path) as fh:
        data = json.load(fh)

    filtered = {}
    for k, v in data.items():
        if k not in model_list:
            continue
        entry = dict(v)
        if 'input' in entry:
            entry['input'] = os.path.normpath(
                os.path.join(base_dir, entry['input'])
            )
        filtered[k] = entry

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as fh:
        json.dump(filtered, fh, indent=2)
    return output_path


def _create_filtered_seqs_dir(seqs_dir, model_list, output_dir):
    """
    Create ``output_dir`` and symlink every ``.fa`` file from ``seqs_dir``
    whose filename contains any of the model names in ``model_list``.

    Returns ``output_dir``.
    """
    os.makedirs(output_dir, exist_ok=True)
    for fname in os.listdir(seqs_dir):
        if not fname.endswith('.fa'):
            continue
        if any(model in fname for model in model_list):
            src = os.path.join(seqs_dir, fname)
            dst = os.path.join(output_dir, fname)
            if not os.path.exists(dst):
                os.symlink(src, dst)
    return output_dir


def _next_branch_id(pipeline):
    """
    Increment ``pipeline.state['branch_count']`` and return a new branch ID
    string derived from the pipeline's own branch_id.
    """
    n = pipeline.state.get('branch_count', 0) + 1
    pipeline.state['branch_count'] = n
    return f"b{n}"
#    return f"{pipeline.branch_id}_b{n}"


def _shared_pipeline_kwargs(pipeline):
    """
    Return a dict of all kwargs that every branch pipeline should inherit
    from the originating pipeline.  These include path constants, analysis
    inputs, and all threshold bounds.
    """
    return {
        'scripts_path':            pipeline.scripts_path,
        'foundry_sif_path':        pipeline.foundry_sif_path,
        'mpnn_dir':                pipeline.mpnn_dir,
        'island_counts_csv':       pipeline.island_counts_csv,
        'mcsa_pdb_dir':            pipeline.mcsa_pdb_dir,
        'rmsd_threshold':          pipeline.rmsd_threshold,
        'diffusion_batch_size':    pipeline.diffusion_batch_size,
        # threshold bounds
        'backbone_rog_bounds':      pipeline.backbone_rog_bounds,
        'backbone_ala_bounds':      pipeline.backbone_ala_bounds,
        'backbone_gly_bounds':      pipeline.backbone_gly_bounds,
        'backbone_helix_bounds':    pipeline.backbone_helix_bounds,
        'backbone_sheet_bounds':    pipeline.backbone_sheet_bounds,
        'backbone_lig_dist_bounds': pipeline.backbone_lig_dist_bounds,
        'seq_ligand_conf_bounds':   pipeline.seq_ligand_conf_bounds,
        'seq_overall_conf_bounds':  pipeline.seq_overall_conf_bounds,
    }


# ── Adaptive function ───────────────────────────────────────────────────────

async def adaptive_decision(pipeline: DiscontinuousScaffoldsPipeline) -> None:
    """
    Multi-point adaptive decision function for the discontinuous scaffolds
    pipeline.

    Called after each process stage.  Reads ``pipeline.state['last_analysis_step']``
    to determine which stage just completed, then:

    backbone stage
        - Identifies passing/failing models from the backbone analysis CSV.
        - If all models fail: terminates the current pipeline (STEP_DONE).
        - If some models fail: filters the current pipeline's LMPNN inputs to
          passing models only, and spawns a backbone-start branch pipeline for
          the failing models.
        - Sets next_step = STEP_SEQ_PRED to continue the current pipeline.

    sequence stage
        - Identifies passing/failing models from the sequence analysis CSV.
        - If all models fail: terminates the current pipeline.
        - If some models fail: creates a filtered seqs_split dir for the
          current pipeline's fold stage, and spawns a sequence-start branch
          pipeline (carrying the failing models' LMPNN inputs and pdb_dir).
        - Sets next_step = STEP_FOLD_PRED to continue the current pipeline.

    fold stage
        - Sets next_step = STEP_DONE (pipeline complete).
    """
    step = pipeline.state.get('last_analysis_step')
    base = pipeline.base_path

    # ── Backbone stage adaptive ──────────────────────────────────────────────
    if step == 'backbone':
        passing = pipeline.state.get('passing_backbone_models', [])
        failing = pipeline.state.get('failing_backbone_models', [])

        pipeline.logger.pipeline_log(
            f"[adaptive/backbone] passing={passing} failing={failing}"
        )

        pipeline.next_step = STEP_SEQ_PRED

        if failing:
            branch_id = _next_branch_id(pipeline)

            # Filter current pipeline's LMPNN inputs to passing models only.
            filt_pdb = _filter_json_by_models(
                pipeline.lmpnn_pdb_multi_json,
                passing,
                f"{base}/{pipeline.branch_id}/filtered_lmpnn_pdb.json",
            )
            filt_res = _filter_json_by_models(
                pipeline.lmpnn_fixed_res_json,
                passing,
                f"{base}/{pipeline.branch_id}/filtered_lmpnn_fixed_res.json",
            )
            pipeline.state['current_lmpnn_pdb_multi_json'] = filt_pdb
            pipeline.state['current_lmpnn_fixed_res_json'] = filt_res

            # Build a filtered RFD input JSON for the branch pipeline.
            # Uses _filter_rfd_json_by_models to rewrite relative "input" paths
            # to absolute paths, since the filtered JSON lands in a different
            # directory than the original.
            branch_rfd = _filter_rfd_json_by_models(
                pipeline.rfd_input_filepath,
                failing,
                f"{base}/{branch_id}/{self.rfd_input_filepath}.json",
            )

            pipeline.logger.pipeline_log(
                f"[adaptive/backbone] Spawning backbone-start branch '{branch_id}' "
                f"for {len(failing)} failing model(s)"
            )
            pipeline.submit_child_pipeline_request({
                'name':                 f"{pipeline.name}_{branch_id}",
                'type':                 DiscontinuousScaffoldsPipeline,
                'adaptive_fn':          adaptive_decision,
                'start_step':           STEP_BACKBONE_GEN,
                'branch_id':            branch_id,
                'rfd_input_filepath':   branch_rfd,
                'lmpnn_pdb_multi_json': pipeline.lmpnn_pdb_multi_json,
                'lmpnn_fixed_res_json': pipeline.lmpnn_fixed_res_json,
                **_shared_pipeline_kwargs(pipeline),
            })
            
        if not passing:
            pipeline.logger.pipeline_log(
                "[adaptive/backbone] No models passed backbone QC; terminating pipeline"
            )
            pipeline.next_step = STEP_DONE
#            return


    # ── Sequence stage adaptive ──────────────────────────────────────────────
    elif step == 'sequence':
        passing = pipeline.state.get('passing_seq_models', [])
        failing = pipeline.state.get('failing_seq_models', [])

        pipeline.logger.pipeline_log(
            f"[adaptive/sequence] passing={passing} failing={failing}"
        )

        pipeline.next_step = STEP_FOLD_PRED

        if failing:
            branch_id = _next_branch_id(pipeline)
            seqs_dir  = pipeline.state['seqs_split_dir']

            # Filter current pipeline's seqs dir to passing models only.
            filt_dir = _create_filtered_seqs_dir(
                seqs_dir,
                passing,
                f"{base}/{pipeline.branch_id}/filtered_seqs_split",
            )
            pipeline.state['current_seqs_split_dir'] = filt_dir

            # Build filtered LMPNN inputs for the branch pipeline.
            branch_pdb = _filter_json_by_models(
                pipeline.lmpnn_pdb_multi_json,
                failing,
                f"{base}/{branch_id}/branch_lmpnn_pdb.json",
            )
            branch_res = _filter_json_by_models(
                pipeline.lmpnn_fixed_res_json,
                failing,
                f"{base}/{branch_id}/branch_lmpnn_fixed_res.json",
            )

            pipeline.logger.pipeline_log(
                f"[adaptive/sequence] Spawning sequence-start branch '{branch_id}' "
                f"for {len(failing)} failing model(s)"
            )
            pipeline.submit_child_pipeline_request({
                'name':                 f"{pipeline.name}_{branch_id}",
                'type':                 DiscontinuousScaffoldsPipeline,
                'adaptive_fn':          adaptive_decision,
                'start_step':           STEP_SEQ_PRED,
                'branch_id':            branch_id,
                'lmpnn_pdb_multi_json': branch_pdb,
                'lmpnn_fixed_res_json': branch_res,
                'initial_state':        {'pdb_dir': pipeline.state['pdb_dir']},
                **_shared_pipeline_kwargs(pipeline),
            })

        if not passing:
            pipeline.logger.pipeline_log(
                "[adaptive/sequence] No models passed sequence QC; terminating pipeline"
            )
            pipeline.next_step = STEP_DONE
#            return


    # ── Fold stage adaptive ──────────────────────────────────────────────────
    elif step == 'fold':
        pipeline.logger.pipeline_log(
            "[adaptive/fold] Fold stage complete; marking pipeline done"
        )
        pipeline.next_step = STEP_DONE

    else:
        pipeline.logger.pipeline_log(
            f"[adaptive] Unexpected last_analysis_step={step!r}; marking pipeline done"
        )
        pipeline.next_step = STEP_DONE

    pipeline.logger.pipeline_log(
        f"[adaptive] next_step={pipeline.next_step}"
    )


# ── Runner ──────────────────────────────────────────────────────────────────

async def run_discontinuous_scaffolds() -> None:
    """Set up the IMPRESS manager and launch the discontinuous scaffolds pipeline."""
    #backend = await LocalExecutionBackend(ThreadPoolExecutor())
    # For HPC execution use:
    backend = await DragonExecutionBackendV3()

    manager: ImpressManager = ImpressManager(execution_backend=backend)

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name="discontinuous_scaffolds_p1",
            type=DiscontinuousScaffoldsPipeline,
            adaptive_fn=adaptive_decision,
            kwargs={
                "scripts_path":             SCRIPTS_PATH,
                "foundry_sif_path":         FOUNDRY_SIF_PATH,
                "mpnn_dir":                 MPNN_DIR,
                "rfd_input_filepath":       RFD_INPUT_FILEPATH,
                "island_counts_csv":        ISLAND_COUNTS_CSV,
                "mcsa_pdb_dir":             MCSA_PDB_DIR,
                "rmsd_threshold":           RMSD_THRESHOLD,
                "diffusion_batch_size":     DIFFUSION_BATCH_SIZE,
                "lmpnn_num_batches":        LMPNN_NUM_BATCHES,
                # threshold bounds
                "backbone_rog_bounds":      BACKBONE_ROG_BOUNDS,
                "backbone_ala_bounds":      BACKBONE_ALA_BOUNDS,
                "backbone_gly_bounds":      BACKBONE_GLY_BOUNDS,
                "backbone_helix_bounds":    BACKBONE_HELIX_BOUNDS,
                "backbone_sheet_bounds":    BACKBONE_SHEET_BOUNDS,
                "backbone_lig_dist_bounds": BACKBONE_LIG_DIST_BOUNDS,
                "seq_ligand_conf_bounds":   SEQ_LIGAND_CONF_BOUNDS,
                "seq_overall_conf_bounds":  SEQ_OVERALL_CONF_BOUNDS,
            },
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)
    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(run_discontinuous_scaffolds())
