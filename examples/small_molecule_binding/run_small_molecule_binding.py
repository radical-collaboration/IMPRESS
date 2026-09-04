import asyncio
import os
from dataclasses import dataclass
from typing import List

from rhapsody.backends import DragonExecutionBackend

from impress import GPUPolicy, _find_gpus, _make_policy, ImpressManager, PipelineSetup
from small_molecule_binding import (
    SmallMoleculeBindingPipeline,
    STEP_DONE, STEP_RFD3, STEP_MPNN, STEP_FASTRELAX, STEP_INTERFACE, STEP_AF2,
    STEP_RETRY_SEQ,
    ETYPE_BACKBONE, ETYPE_SEQUENCE, ETYPE_FOLD,
    _ca_rmsd, _seq_identity, _ensemble_selective_avg,
)

import logging
import rhapsody
rhapsody.enable_logging(level=logging.INFO)


@dataclass
class RunConfig:
    n_pipelines: int
    max_tasks: int
    # backbone
    backbone_max_ca_deviation: float
    backbone_min_ss_fraction: float
    # fastrelax
    fastrelax_max_fa_rep: float
    fastrelax_max_score: float       # total_score REU
    fastrelax_max_interact: float    # interaction energy REU
    # interface
    interface_min_sc: float          # shape complementarity
    # fold
    fold_min_plddt: float            # mean pLDDT; init is -1.0 so -1.0 = always pass
    # diffusion / refinement
    diffusion_batch_size: int
    num_refine_cycles: int


PROD = RunConfig(
    n_pipelines               = 4,
    max_tasks                 = 300,
    backbone_max_ca_deviation = 1.0,
    backbone_min_ss_fraction  = 0.5,
    fastrelax_max_fa_rep      = 100.0,
    fastrelax_max_score       = -250.0,  # data range -193 to -510
    fastrelax_max_interact    = -8.0,    # p75 = -8.8
    interface_min_sc          = 0.55,
    fold_min_plddt            = 75.0,
    diffusion_batch_size      = 4,
    num_refine_cycles         = 2,
)

# Inert thresholds — everything passes; low task budget for one full cycle.
TEST = RunConfig(
    n_pipelines               = 2,
    max_tasks                 = 10,
    backbone_max_ca_deviation = 9999.0,
    backbone_min_ss_fraction  = 0.0,
    fastrelax_max_fa_rep      = 9999.0,
    fastrelax_max_score       = 9999.0,
    fastrelax_max_interact    = 9999.0,
    interface_min_sc          = 0.0,
    fold_min_plddt            = -1.0,
    diffusion_batch_size      = 1,
    num_refine_cycles         = 1,
)

cfg = TEST if os.getenv("IMPRESS_TEST_MODE", "0") == "1" else PROD


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
        total_score = metrics.get('total_score')
        if total_score is not None and total_score > 0:
            pipeline.next_step = STEP_RFD3   # badly packed — restart backbone
        else:
            pipeline.next_step = STEP_MPNN

    elif step == 'fastrelax':
        if passed:
            pipeline.state['fastrelax_fail_count'] = 0
            pipeline.next_step = STEP_INTERFACE
        else:
            count = pipeline.state.get('fastrelax_fail_count', 0) + 1
            pipeline.state['fastrelax_fail_count'] = count
            if count >= 5:
                pipeline.state['fastrelax_fail_count'] = 0
                pipeline.next_step = STEP_RFD3
            else:
                pipeline.next_step = STEP_MPNN

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
    # Resolve paths before launching Dragon (os.getcwd() is the examples dir).
    examples_dir = os.path.dirname(os.path.abspath(__file__))
    work_dir = os.environ.get(
        "IMPRESS_WORK_DIR", os.path.join(examples_dir, "logs")
    )
    os.makedirs(work_dir, exist_ok=True)
    # Input data lives in the source tree; pass as absolute so it resolves
    # correctly regardless of what base_path / work_dir is set to.
    input_dir = os.path.join(examples_dir, "p1_in")

    #backend = await LocalExecutionBackend(ProcessPoolExecutor())
    backend = await DragonExecutionBackend()
    manager: ImpressManager = ImpressManager(execution_backend=backend)

    all_gpus = _find_gpus()

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name=f"p{str(i)}",
            type=SmallMoleculeBindingPipeline,
            adaptive_fn=adaptive_decision,
            kwargs={
                "base_path":                 work_dir,
                "scripts_path":              os.path.join(examples_dir, "scripts"),
                "input_dir":                 input_dir,
                "backbone_max_ca_deviation": cfg.backbone_max_ca_deviation,
                "backbone_min_ss_fraction":  cfg.backbone_min_ss_fraction,
                "fastrelax_max_fa_rep":      cfg.fastrelax_max_fa_rep,
                "fastrelax_max_total_score": cfg.fastrelax_max_score,
                "fastrelax_max_interact":    cfg.fastrelax_max_interact,
                "interface_min_sc":          cfg.interface_min_sc,
                "fold_min_plddt":            cfg.fold_min_plddt,
                "diffusion_batch_size":      cfg.diffusion_batch_size,
                "num_refine_cycles":         cfg.num_refine_cycles,
                "max_tasks":                 cfg.max_tasks,
                "policy":                    _make_policy(all_gpus, i - 1),
            }
        )
        for i in range(1, cfg.n_pipelines + 1)
    ]

    await manager.start(pipeline_setups=pipeline_setups)


if __name__ == "__main__":
    asyncio.run(impress_smallmol_bind())
