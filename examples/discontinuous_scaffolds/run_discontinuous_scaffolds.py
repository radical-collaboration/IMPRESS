
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List

from radical.asyncflow import LocalExecutionBackend
from rhapsody.backends import DragonExecutionBackendV3

from impress import ImpressManager, PipelineSetup
from discontinuous_scaffolds import (
    DiscontinuousScaffoldsPipeline,
    STEP_BACKBONE_GEN,
    STEP_DONE,
)


# ── Configurable parameters ─────────────────────────────────────────────────

SCRIPTS_PATH     = "/ocean/projects/dmr170002p/hooten/discontinuous_scaffolds/IMPRESS/examples/discontinuous_scaffolds/scripts"
FOUNDRY_SIF_PATH = "/ocean/projects/dmr170002p/hooten/foundry.sif"
MPNN_DIR         = "/ocean/projects/dmr170002p/hooten/LigandMPNN"

RFD_INPUT_FILEPATH   = f"{SCRIPTS_PATH}/mcsa_mod8-5.json"
LMPNN_PDB_MULTI_JSON = f"{SCRIPTS_PATH}/lmpnn_batch_jsons/batch_pdbs_mod8-5.json"
LMPNN_FIXED_RES_JSON = f"{SCRIPTS_PATH}/lmpnn_batch_jsons/batch_fixed_res_mod8-5.json"
ISLAND_COUNTS_CSV    = f"{SCRIPTS_PATH}/island_counts.csv"
MCSA_PDB_DIR         = f"{SCRIPTS_PATH}/mcsa_41"
RMSD_THRESHOLD       = 1.5
DIFFUSION_BATCH_SIZE = 10


# ── Adaptive function ───────────────────────────────────────────────────────

async def adaptive_decision(pipeline: DiscontinuousScaffoldsPipeline) -> None:
    """
    Dummy adaptive step for the discontinuous scaffolds pipeline.

    Checks whether the step-6 analysis CSV was produced.  If it was, the
    pipeline restarts from backbone generation (step 1).  If not, the
    pipeline is marked complete.
    """
    analysis_present = pipeline.state.get('analysis_present', False)

    if analysis_present:
        pipeline.logger.pipeline_log(
            "[adaptive] Analysis results found; restarting from backbone generation"
        )
        pipeline.state['run_count'] = pipeline.state.get('run_count', 0) + 1
        pipeline.taskcount = 0
        pipeline.next_step = STEP_BACKBONE_GEN
    else:
        pipeline.logger.pipeline_log(
            "[adaptive] Analysis results not found; marking pipeline done"
        )
        pipeline.next_step = STEP_DONE

    pipeline.logger.pipeline_log(
        f"[adaptive] analysis_present={analysis_present} "
        f"next_step={pipeline.next_step} "
        f"run_count={pipeline.state.get('run_count', 0)}"
    )


# ── Runner ──────────────────────────────────────────────────────────────────

async def run_discontinuous_scaffolds() -> None:
    """Set up the IMPRESS manager and launch the discontinuous scaffolds pipeline."""
    backend = await LocalExecutionBackend(ThreadPoolExecutor())
    # For HPC execution use:
    # backend = await DragonExecutionBackendV3()

    manager: ImpressManager = ImpressManager(execution_backend=backend)

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name="discontinuous_scaffolds_p1",
            type=DiscontinuousScaffoldsPipeline,
            adaptive_fn=adaptive_decision,
            kwargs={
                "scripts_path":        SCRIPTS_PATH,
                "foundry_sif_path":    FOUNDRY_SIF_PATH,
                "mpnn_dir":            MPNN_DIR,
                "rfd_input_filepath":  RFD_INPUT_FILEPATH,
                "lmpnn_pdb_multi_json": LMPNN_PDB_MULTI_JSON,
                "lmpnn_fixed_res_json": LMPNN_FIXED_RES_JSON,
                "island_counts_csv":   ISLAND_COUNTS_CSV,
                "mcsa_pdb_dir":        MCSA_PDB_DIR,
                "rmsd_threshold":      RMSD_THRESHOLD,
                "diffusion_batch_size": DIFFUSION_BATCH_SIZE,
            },
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)
    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(run_discontinuous_scaffolds())
