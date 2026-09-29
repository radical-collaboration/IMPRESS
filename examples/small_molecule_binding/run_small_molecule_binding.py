import argparse
import asyncio
import os
from dataclasses import dataclass, replace
from typing import List

from radical.asyncflow import WorkflowEngine

from impress import ImpressManager, PipelineSetup
from small_molecule_binding import (
    SmallMoleculeBindingPipeline,
    STEP_DONE, STEP_RFD3, STEP_MPNN, STEP_FASTRELAX, STEP_INTERFACE, STEP_AF2,
    STEP_RETRY_SEQ,
    ETYPE_BACKBONE, ETYPE_SEQUENCE, ETYPE_FOLD,
    _ca_rmsd, _seq_identity, _ensemble_selective_avg, _stage_metrics_improving,
)

import logging
import rhapsody
rhapsody.enable_logging(level=logging.INFO)


def _on_task_event(event) -> None:
    """Surface task failures in the job log as they happen.

    Telemetry writes a JSONL file that is only read after the fact; this makes
    failures visible while the run is in flight.  Note the workflow label lives
    in event.attributes, NOT as an event attribute -- run_nonadaptive.py in the
    protein_binding example does getattr(event, "workflow_id", None), which
    always yields None.  Dispatch swallows subscriber exceptions, so a bug here
    would fail silently; keep it trivial.
    """
    if getattr(event, "event_type", None) == "TaskFailed":
        attrs = getattr(event, "attributes", None) or {}
        label = attrs.get("asyncflow.workflow_id") or attrs.get("executable")
        print(f"[TELEMETRY] TaskFailed task={event.task_id} "
              f"label={label} error={getattr(event, 'error_type', None)}")


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
    fold_min_ligand_iptm: float | None  # Boltz-2 protein-ligand interface confidence; None = off
    # diffusion / refinement
    diffusion_batch_size: int
    num_refine_cycles: int
    mpnn_ensemble_size: int            # cycle-0 MPNN sequence candidates per backbone
    rfd3_partial_t: float             # RFD3 partial-diffusion noise (A) for guided backbone feedback


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
    # Off by default so switching to Boltz-2 doesn't silently make PROD stricter.
    # 0.5 is a reasonable starting point if ligand-binding-confidence gating is
    # wanted later — a signal plain AlphaFold2 could never provide since it
    # never folded the ligand at all.
    fold_min_ligand_iptm      = None,
    diffusion_batch_size      = 4,
    num_refine_cycles         = 2,
    mpnn_ensemble_size        = 10,
    rfd3_partial_t            = 10.0,
)

BACKEND = os.environ.get("IMPRESS_BACKEND", "dragon").lower()

if BACKEND == "dragon":
    from rhapsody.backends import DragonExecutionBackend
else:
    from concurrent.futures import ProcessPoolExecutor
    from rhapsody.backends import ConcurrentExecutionBackend

# Run config is taken from the command line first, environment second.
#
# The CLI path exists because environment variables DO NOT reach this process on
# a multi-node run.  `dragon -w ssh` propagates only a fixed allowlist to the
# backends (dragon/launcher/wlm/ssh.py:29-41 BASE_ENV_VARNAMES: PATH, PYTHONPATH,
# LD_LIBRARY_PATH, PYTHONSTARTUP, VIRTUAL_ENV and DRAGON_*), so IMPRESS_N_PIPELINES
# / IMPRESS_WORK_DIR set by delta_gpu_run.sh are silently dropped and the defaults
# below would be used instead.  Confirmed on job 22466127, which ran the built-in
# defaults rather than the config the launcher asked for.  (MPNN_DIR / BOLTZ_CACHE
# / FOUNDRY_SIF_PATH / SCRATCH survive that hop only because ~/.bashrc exports them
# and the ssh login shell sources it -- do not rely on that for new settings.)
# Dragon passes everything after PROG straight through to us, so argv is the one
# channel that always works.  parse_known_args so any extra argv is ignored.
_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument("--n-pipelines", type=int, default=None)
_ap.add_argument("--work-dir", default=None)
_args, _ = _ap.parse_known_args()

cfg = PROD

# Scale pipeline count with the allocation without editing PROD.  run() is a
# sequential state machine, so n_pipelines IS the job's total concurrency and
# each pipeline keeps roughly one GPU busy -- delta_gpu_run.sh sets this to the
# allocated GPU count.  Requires a matching p{i}_in/ dir per pipeline (the
# launcher caps it at however many exist).  replace() rather than mutating
# PROD in place: it is a module-level singleton that run_nonadaptive.py and
# run_test_small_molecule_binding.py also import.
_n_pipelines = _args.n_pipelines or os.getenv("IMPRESS_N_PIPELINES")
if _n_pipelines:
    cfg = replace(cfg, n_pipelines=int(_n_pipelines))

# Thread caps, set here rather than in the batch script for the same reason:
# OMP_NUM_THREADS exported by delta_gpu_run.sh never survives the ssh hop.
# 11 of the 13 tasks are local_task=True and run as concurrent subprocesses of
# this process, inheriting os.environ -- so setting it here is what actually
# takes effect.  Without a cap each of them defaults to every core on the node.
# Divide by 2x the pipeline count to leave room for Dragon tasks co-resident on
# this node; PyRosetta (fastrelax/packmin/filter_shape) is single-threaded
# regardless, so this budget really targets the PyTorch tasks.
# sched_getaffinity respects the cgroup/CPU mask SLURM applies to the job;
# os.cpu_count() reports the physical core count and would over-subscribe on any
# allocation smaller than a whole node.
try:
    _ncpu = len(os.sched_getaffinity(0))
except AttributeError:          # not Linux
    _ncpu = os.cpu_count() or 64
_omp = max(1, _ncpu // (cfg.n_pipelines * 2))
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS",
             "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, str(_omp))
# PASSIVE is what actually stops idle OpenMP teams from spinning on cores.
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")


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
            # Safety net: a guided (partial-diffusion) backbone that keeps
            # failing QC -- whether for real structural reasons or an
            # unforeseen RFD3 metrics-schema gap -- would otherwise loop on
            # the same rfd3_input_pdb forever, since only a *successful* fold
            # ever clears it. Fall back to unguided regeneration after a few
            # consecutive guided-mode failures instead of deadlocking.
            if pipeline.state.get('rfd3_input_pdb') is not None:
                count = pipeline.state.get('backbone_guided_fail_count', 0) + 1
                pipeline.state['backbone_guided_fail_count'] = count
                if count >= 3:
                    pipeline.state['rfd3_input_pdb'] = None
                    pipeline.state['backbone_guided_fail_count'] = 0
                    pipeline.logger.pipeline_log(
                        "[adaptive/backbone] guided backbone QC failed 3x in a "
                        "row -- abandoning guided mode, reverting to unguided "
                        "(scratch) RFD3 generation"
                    )
            pipeline.next_step = STEP_RFD3
        else:
            current, prior = _prior(ETYPE_BACKBONE)
            # Reset on any new backbone -- these are per-backbone retry state,
            # not per-pipeline, and must not leak into the next backbone's
            # first fastrelax/interface attempt (see _stage_metrics_improving).
            pipeline.state['backbone_guided_fail_count'] = 0
            pipeline.state['seq_retry_count']       = 0
            pipeline.state['fastrelax_prev_metrics'] = None
            pipeline.state['interface_prev_metrics'] = None
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
                    # A guided backbone that fails downstream of backbone-QC
                    # gets only this one shot -- otherwise rfd3_input_pdb stays
                    # pinned to the same seed indefinitely (only 'backbone' QC
                    # failures and 'fold' decisions used to clear it), causing
                    # RFD3 to regenerate near-duplicate doomed backbones for
                    # dozens of cycles in a row (confirmed via job 21945304:
                    # 17 consecutive p2 rfd3 generations produced byte-identical
                    # guided_scaffold.pdb output from one stuck seed).
                    pipeline.state['rfd3_input_pdb'] = None
                    pipeline.next_step = STEP_RFD3
                    pipeline.logger.pipeline_log(
                        "[adaptive/sequence] sequence-similarity gate failed "
                        "3x in a row on this backbone -- escalating to a new, "
                        "unguided backbone (STEP_RFD3) instead of another "
                        "resequencing retry"
                    )
                else:
                    pipeline.next_step = STEP_RETRY_SEQ

    elif step == 'packmin':
        total_score = metrics.get('total_score')
        if total_score is not None and total_score > 0:
            # See the sequence-stage comment above: any STEP_RFD3 escalation
            # must clear a stuck guided seed, not just backbone-QC failures.
            pipeline.state['rfd3_input_pdb'] = None
            pipeline.next_step = STEP_RFD3   # badly packed — restart backbone
            pipeline.logger.pipeline_log(
                f"[adaptive/packmin] total_score={total_score} > 0 -- badly "
                "packed, escalating to a new, unguided backbone (STEP_RFD3)"
            )
        else:
            pipeline.next_step = STEP_MPNN

    elif step == 'fastrelax':
        if passed:
            pipeline.state['fastrelax_fail_count']   = 0
            pipeline.state['fastrelax_prev_metrics'] = None
            pipeline.next_step = STEP_INTERFACE
        else:
            # Metric-agnostic short-circuit: a backbone whose fastrelax metrics
            # (interact/total_score/fa_rep, whichever combination is failing)
            # aren't improving attempt-over-attempt is backbone-driven, not
            # sequence-driven -- resequencing (STEP_MPNN) can't fix it, only a
            # new backbone (STEP_RFD3) can. Confirmed against real HPC data
            # (job 21913252): 15 fastrelax attempts across 3 backbones, zero
            # improvement and zero eventual recoveries once a backbone's
            # metrics went flat. Retry cap = 1 (escalate on the first
            # non-improving retry) per that evidence; the count>=5 check
            # remains as an outer safety net in case metrics oscillate.
            prev = pipeline.state.get('fastrelax_prev_metrics')
            specs = [
                ('interact',    True, pipeline.fastrelax_max_interact),
                ('total_score', True, pipeline.fastrelax_max_total_score),
                ('fa_rep',      True, pipeline.fastrelax_max_fa_rep),
            ]
            improving = _stage_metrics_improving(metrics, prev, specs)
            pipeline.state['fastrelax_prev_metrics'] = dict(metrics)

            count = pipeline.state.get('fastrelax_fail_count', 0) + 1
            pipeline.state['fastrelax_fail_count'] = count

            if (prev is not None and not improving) or count >= 5:
                reason = "safety cap (5 attempts)" if count >= 5 else "non-improving metrics"
                pipeline.state['fastrelax_fail_count']   = 0
                pipeline.state['fastrelax_prev_metrics'] = None
                # See the sequence-stage comment above: any STEP_RFD3 escalation
                # must clear a stuck guided seed, not just backbone-QC failures.
                pipeline.state['rfd3_input_pdb'] = None
                pipeline.next_step = STEP_RFD3
                pipeline.logger.pipeline_log(
                    f"[adaptive/fastrelax] escalating to a new, unguided "
                    f"backbone (STEP_RFD3) ({reason}); attempt={count} metrics={metrics}"
                )
            else:
                pipeline.next_step = STEP_MPNN

    elif step == 'interface':
        if passed:
            pipeline.state['interface_fail_count']   = 0
            pipeline.state['interface_prev_metrics'] = None
            pipeline.next_step = STEP_AF2
        else:
            # Same metric-agnostic short-circuit as 'fastrelax' above, applied
            # to shape complementarity -- confirmed the identical wasteful
            # pattern occurs here too (job 21913252: 5 interface attempts on
            # one backbone, shape complementarity flat within ~0.02, never
            # nearing threshold).
            prev = pipeline.state.get('interface_prev_metrics')
            specs = [('max_sc', False, pipeline.interface_min_sc)]  # higher is better
            improving = _stage_metrics_improving(metrics, prev, specs)
            pipeline.state['interface_prev_metrics'] = dict(metrics)

            count = pipeline.state.get('interface_fail_count', 0) + 1
            pipeline.state['interface_fail_count'] = count

            if (prev is not None and not improving) or count >= 5:
                reason = "safety cap (5 attempts)" if count >= 5 else "non-improving metrics"
                pipeline.state['interface_fail_count']   = 0
                pipeline.state['interface_prev_metrics'] = None
                # See the sequence-stage comment above: any STEP_RFD3 escalation
                # must clear a stuck guided seed, not just backbone-QC failures.
                pipeline.state['rfd3_input_pdb'] = None
                pipeline.next_step = STEP_RFD3
                pipeline.logger.pipeline_log(
                    f"[adaptive/interface] escalating to a new, unguided "
                    f"backbone (STEP_RFD3) ({reason}); attempt={count} metrics={metrics}"
                )
            else:
                pipeline.next_step = STEP_MPNN

    elif step == 'fold':
        current, prior = _prior(ETYPE_FOLD)
        if not passed:
            # Failed fold — don't use this model as a backbone guide
            pipeline.state['rfd3_input_pdb'] = None
            pipeline.logger.pipeline_log(
                "[adaptive/fold] fold failed -- next backbone will be unguided (scratch)"
            )
        else:
            if not prior:
                pipeline.state['rfd3_input_pdb'] = None
                pipeline.logger.pipeline_log(
                    "[adaptive/fold] fold passed but no prior fold history yet -- "
                    "next backbone will be unguided (scratch)"
                )
            else:
                overall, selective, has_data = _ensemble_selective_avg(
                    current[3], prior, _ca_rmsd, similar_if_low=True)
                if has_data and selective is not None and selective > overall:
                    pipeline.state['rfd3_input_pdb'] = current[3]  # guided backbone
                    pipeline.logger.pipeline_log(
                        f"[adaptive/fold] similar-cluster avg ({selective:.2f}) > "
                        f"overall avg ({overall:.2f}) -- next backbone guided from {current[3]}"
                    )
                else:
                    pipeline.state['rfd3_input_pdb'] = None         # scratch
                    pipeline.logger.pipeline_log(
                        f"[adaptive/fold] guided-feedback condition not met "
                        f"(has_data={has_data}, selective={selective}, overall={overall}) "
                        "-- next backbone will be unguided (scratch)"
                    )
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
    # --work-dir first for the same reason as --n-pipelines: IMPRESS_WORK_DIR is
    # another variable that does not survive the `dragon -w ssh` hop, so on a
    # multi-node run the env value set by delta_gpu_run.sh never arrives and we
    # would silently fall back to examples_dir/logs.
    work_dir = _args.work_dir or os.environ.get(
        "IMPRESS_WORK_DIR", os.path.join(examples_dir, "logs")
    )
    os.makedirs(work_dir, exist_ok=True)
    # Input data lives in the source tree; pass as absolute so it resolves
    # correctly regardless of what base_path / work_dir is set to. Each
    # pipeline reads its own p{i}_in/ directory rather than sharing one.

    if BACKEND == "dragon":
        backend = await DragonExecutionBackend()
    else:
        backend = await ConcurrentExecutionBackend.create(ProcessPoolExecutor())
    flow = await WorkflowEngine.create(backend=backend)
    manager: ImpressManager = ImpressManager(
        flow,
        telemetry_config={
            # Absolute, derived from the already-resolved work_dir.  A relative
            # path (as the protein_binding reference uses) resolves against the
            # cwd of whichever process builds the TelemetryManager -- under
            # delta_gpu_run.sh that is $SCRATCH, not the source tree.  Deriving
            # it from work_dir also inherits per-job scoping for free, since
            # IMPRESS_WORK_DIR is logs/$SLURM_JOB_ID.
            "checkpoint_path": os.path.join(work_dir, "telemetry"),
            # The reference uses 5.0, which made ResourceUpdate 69% of its
            # output file.  15s cuts that dominant term ~3x and leaves task
            # lifecycle events untouched.
            "resource_poll_interval": 15.0,
            # The reference omits this, so nothing reaches disk until stop().
            # The file is 128KB-buffered, so a job killed by the wall clock
            # loses everything.  Flush every 5 minutes instead.
            "checkpoint_interval": 300.0,
        },
        telemetry_subscribers=[_on_task_event],
    )

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name=f"p{str(i)}",
            type=SmallMoleculeBindingPipeline,
            adaptive_fn=adaptive_decision,
            kwargs={
                "base_path":                 work_dir,
                "scripts_path":              os.path.join(examples_dir, "scripts"),
                "input_dir":                 os.path.join(examples_dir, f"p{i}_in"),
                "backbone_max_ca_deviation": cfg.backbone_max_ca_deviation,
                "backbone_min_ss_fraction":  cfg.backbone_min_ss_fraction,
                "fastrelax_max_fa_rep":      cfg.fastrelax_max_fa_rep,
                "fastrelax_max_total_score": cfg.fastrelax_max_score,
                "fastrelax_max_interact":    cfg.fastrelax_max_interact,
                "interface_min_sc":          cfg.interface_min_sc,
                "fold_min_plddt":            cfg.fold_min_plddt,
                "fold_min_ligand_iptm":      cfg.fold_min_ligand_iptm,
                "diffusion_batch_size":      cfg.diffusion_batch_size,
                "num_refine_cycles":         cfg.num_refine_cycles,
                "mpnn_ensemble_size":        cfg.mpnn_ensemble_size,
                "rfd3_partial_t":            cfg.rfd3_partial_t,
                "max_tasks":                 cfg.max_tasks,
            }
        )
        for i in range(1, cfg.n_pipelines + 1)
    ]

    try:
        await manager.start(pipeline_setups=pipeline_setups)
    finally:
        # stop() is the only thing that writes the metric/span sections and
        # flushes the 128KB-buffered checkpoint file, so it must run even when
        # manager.start() raises -- the reference implementation puts it in the
        # try block and loses the file on any error.  Before flow.shutdown().
        if manager.telemetry:
            try:
                await manager.telemetry.stop()
            except Exception as exc:               # never mask the real error
                print(f"[TELEMETRY] stop() failed: {exc!r}")
        await flow.shutdown()


if __name__ == "__main__":
    asyncio.run(impress_smallmol_bind())
