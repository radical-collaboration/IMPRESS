import asyncio
import os
from concurrent.futures import ThreadPoolExecutor,ProcessPoolExecutor
from typing import List

from radical.asyncflow import LocalExecutionBackend
from rhapsody.backends import DragonExecutionBackendV3

from impress import ImpressManager, PipelineSetup
from small_molecule_binding import (
    SmallMoleculeBindingPipeline,
    STEP_DONE, STEP_RFD3, STEP_MPNN, STEP_FASTRELAX, STEP_INTERFACE, STEP_AF2,
    STEP_RETRY_SEQ,
    ETYPE_BACKBONE, ETYPE_SEQUENCE, ETYPE_FOLD,
    _ca_rmsd, _seq_identity, _ensemble_selective_avg,
)

import logging
import rhapsody
rhapsody.enable_logging(level=logging.DEBUG)

# ── Per-step quality thresholds ────────────────────────────────────────────
BACKBONE_MAX_CA_DEVIATION = 1.0
BACKBONE_MIN_SS_FRACTION  = 0.5
FASTRELAX_MAX_FA_REP      = 100.0   # fa_rep REU
FASTRELAX_MAX_SCORE       = 0.0    # total_score REU
INTERFACE_MIN_SC          = 0.35
FOLD_MIN_PLDDT            = 70.0


async def adaptive_decision(pipeline: SmallMoleculeBindingPipeline) -> None:
    step     = pipeline.state.get('last_analysis_step')
    metrics  = pipeline.state.get('last_analysis_metrics', {})
    passed   = metrics.get('pass', False)
    ensemble = pipeline.state.get('ensemble', [])

    def _prior(ttype):
        """All ensemble entries of ttype except the most recent one (which is 'current')."""
        current = next((t for t in reversed(ensemble) if t[0] == ttype), None)
        return current, [t for t in ensemble if t[0] == ttype and t is not current]

    if step == 'backbone':
        if not passed:
            pipeline.next_step = STEP_RFD3
        else:
            current, prior = _prior(ETYPE_BACKBONE)
            pipeline.state['seq_retry_count'] = 0  # reset on any new backbone
            if not prior:
                pipeline.next_step = STEP_MPNN
            else:
                overall, selective, has_data = _ensemble_selective_avg(
                    current[3], prior, _ca_rmsd, similar_if_low=True)
                if has_data and selective is not None:
                    pipeline.next_step = STEP_MPNN if selective > overall else STEP_RFD3
                else:
                    # No data (e.g. CIF.GZ in real mode) → fall back to simple gating
                    pipeline.next_step = STEP_MPNN

    elif step == 'sequence':
        current, prior = _prior(ETYPE_SEQUENCE)
        if not prior:
            pipeline.state['seq_retry_count'] = 0
            pipeline.next_step = STEP_MPNN
        else:
            overall, selective, has_data = _ensemble_selective_avg(
                current[3], prior, _seq_identity, similar_if_low=False)
            if has_data and selective is not None and selective >= overall:
                pipeline.state['seq_retry_count'] = 0
                pipeline.next_step = STEP_MPNN
            else:
                count = pipeline.state.get('seq_retry_count', 0) + 1
                pipeline.state['seq_retry_count'] = count
                if count >= 3:
                    pipeline.state['seq_retry_count'] = 0
                    pipeline.next_step = STEP_RFD3
                else:
                    pipeline.next_step = STEP_RETRY_SEQ

    elif step == 'packmin':
        pipeline.next_step = STEP_MPNN

    elif step == 'fastrelax':
        pipeline.next_step = STEP_INTERFACE if passed else STEP_MPNN

    elif step == 'interface':
        if passed:
            pipeline.state['interface_fail_count'] = 0
            pipeline.next_step = STEP_AF2
        else:
            count = pipeline.state.get('interface_fail_count', 0) + 1
            pipeline.state['interface_fail_count'] = count
            if count >= 5:
                pipeline.state['interface_fail_count'] = 0
                pipeline.next_step = STEP_RFD3
            else:
                pipeline.next_step = STEP_MPNN

    elif step == 'fold':
        current, prior = _prior(ETYPE_FOLD)
        if not passed:
            # Failed fold — don't use this model as a backbone guide
            pipeline.state['rfd3_input_pdb'] = None
        else:
            if not prior:
                pipeline.state['rfd3_input_pdb'] = None
            else:
                overall, selective, has_data = _ensemble_selective_avg(
                    current[3], prior, _ca_rmsd, similar_if_low=True)
                if has_data and selective is not None and selective > overall:
                    pipeline.state['rfd3_input_pdb'] = current[3]  # guided backbone
                else:
                    pipeline.state['rfd3_input_pdb'] = None         # scratch
        pipeline.next_step = STEP_RFD3

    else:
        pipeline.logger.pipeline_log(f"[adaptive] Unknown step: {step!r}")
        pipeline.next_step = STEP_DONE

    pipeline.logger.pipeline_log(
        f"[adaptive/{step}] passed={passed} next_step={pipeline.next_step} "
        f"ensemble={len(ensemble)}"
    )


async def impress_smallmol_bind() -> None:
    """Execute the small-molecule binding pipeline."""
    backend = await LocalExecutionBackend(ProcessPoolExecutor())
    #backend = await DragonExecutionBackendV3()
    manager: ImpressManager = ImpressManager(execution_backend=backend)

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name='p1',
            type=SmallMoleculeBindingPipeline,
            adaptive_fn=adaptive_decision,
            kwargs={
                "backbone_max_ca_deviation": BACKBONE_MAX_CA_DEVIATION,
                "backbone_min_ss_fraction":  BACKBONE_MIN_SS_FRACTION,
                "fastrelax_max_fa_rep":      FASTRELAX_MAX_FA_REP,
                "fastrelax_max_total_score": FASTRELAX_MAX_SCORE,
                "interface_min_sc":          INTERFACE_MIN_SC,
                "fold_min_plddt":            FOLD_MIN_PLDDT,
            },
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)
    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(impress_smallmol_bind())
