import asyncio
from typing import List

from radical.asyncflow import LocalExecutionBackend
from concurrent.futures import ProcessPoolExecutor
from rhapsody.backends import DragonExecutionBackend

from impress import ImpressManager, PipelineSetup
from small_molecule_binding import (
    SmallMoleculeBindingPipeline,
    STEP_DONE, STEP_RFD3, STEP_MPNN, STEP_FASTRELAX, STEP_INTERFACE, STEP_AF2,
)

import logging
import rhapsody
rhapsody.enable_logging(level=logging.DEBUG)

# ── Per-step quality thresholds ────────────────────────────────────────────
# These are passed to pipeline analysis tasks for metric logging but are not
# used by nonadaptive_decision to gate routing.
BACKBONE_MAX_CA_DEVIATION = 1.0
BACKBONE_MIN_SS_FRACTION  = 0.5
FASTRELAX_MAX_FA_REP      = 100.0
FASTRELAX_MAX_SCORE       = -250.0
FASTRELAX_MAX_INTERACT    = -8.0
INTERFACE_MIN_SC          = 0.55
FOLD_MIN_PLDDT            = 75.0


async def nonadaptive_decision(pipeline: SmallMoleculeBindingPipeline) -> None:
    step = pipeline.state.get('last_analysis_step')
    routes = {
        'backbone':  STEP_MPNN,
        'sequence':  STEP_MPNN,
        'packmin':   STEP_MPNN,
        'fastrelax': STEP_INTERFACE,
        'interface': STEP_AF2,
    }
    if step == 'fold':
        pipeline.state['rfd3_input_pdb'] = None
        pipeline.next_step = STEP_RFD3
    elif step in routes:
        pipeline.next_step = routes[step]
    else:
        pipeline.logger.pipeline_log(f"[nonadaptive] Unknown step: {step!r}")
        pipeline.next_step = STEP_DONE

    pipeline.logger.pipeline_log(
        f"[nonadaptive/{step}] next_step={pipeline.next_step} "
        f"ensemble={len(pipeline.state.get('ensemble', []))}"
    )


async def impress_smallmol_nonadaptive() -> None:
    """Execute the small-molecule binding pipeline without adaptive routing."""
    #backend = await LocalExecutionBackend(ProcessPoolExecutor())
    backend = await DragonExecutionBackend()
    manager: ImpressManager = ImpressManager(execution_backend=backend)

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name=f"p{str(i)}",
            type=SmallMoleculeBindingPipeline,
            adaptive_fn=nonadaptive_decision,
            kwargs={
                "backbone_max_ca_deviation": BACKBONE_MAX_CA_DEVIATION,
                "backbone_min_ss_fraction":  BACKBONE_MIN_SS_FRACTION,
                "fastrelax_max_fa_rep":      FASTRELAX_MAX_FA_REP,
                "fastrelax_max_total_score": FASTRELAX_MAX_SCORE,
                "fastrelax_max_interact":    FASTRELAX_MAX_INTERACT,
                "interface_min_sc":          INTERFACE_MIN_SC,
                "fold_min_plddt":            FOLD_MIN_PLDDT,
                "diffusion_batch_size":      4,
                "num_refine_cycles":         2,
            }
        )
        for i in [1,2,4,6,7,8,10,11,12,13,14,15,16,18,19,20,23,26,27,30,32]
    ]

    await manager.start(pipeline_setups=pipeline_setups)
    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(impress_smallmol_nonadaptive())
