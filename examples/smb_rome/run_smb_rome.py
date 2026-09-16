"""Small-molecule binding pipeline with ROME-A adaptive LigandMPNN fine-tuning.

This script is a thin wrapper around ``run_small_molecule_binding.py``.  The
scientific pipeline is completely unchanged — this file only adds the two ROME
hooks to ``adaptive_decision``:

  Hook 1 (fold branch): stage the AF2 best model and add it to the ROME corpus
  Hook 2 (fold branch): log the current training status and latest model path

The designed chains (A) and ligand context (HETATM) are handled automatically
by LigandMPNN — no wrapper changes there.

**Reward function.**  ``smb_reward_fn`` below is the scientist-visible reward
signal.  It is defined at module level so it is pickle-able (required by
``train_kwargs``).  Edit it for your campaign — then the per-sample loss
weights in fine-tuning will reflect your domain objectives.

Usage::

    dragon -s run_smb_rome.py
"""

import asyncio
import os
import shutil
import tempfile
from typing import Any, List, Optional

from rhapsody.backends import DragonExecutionBackend

from impress import find_gpus, ImpressManager, PipelineSetup

try:
    from examples.small_molecule_binding.run_small_molecule_binding import (
        RunConfig, PROD, TEST, adaptive_decision as _base_adaptive_decision,
    )
    from examples.small_molecule_binding.small_molecule_binding import SmallMoleculeBindingPipeline
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    from small_molecule_binding.run_small_molecule_binding import (
        RunConfig, PROD, TEST, adaptive_decision as _base_adaptive_decision,
    )
    from small_molecule_binding.small_molecule_binding import SmallMoleculeBindingPipeline

try:
    from examples.smb_rome.ligandmpnn_trainer import (
        LigandMPNNConfig,
        LigandMPNNTrainer,
        percentile_sampler,
    )
except ModuleNotFoundError:
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from ligandmpnn_trainer import LigandMPNNConfig, LigandMPNNTrainer, percentile_sampler

import rome

import rhapsody, logging
rhapsody.enable_logging(level=logging.INFO)


# ── Configuration ─────────────────────────────────────────────────────────────

TEST_MODE = os.getenv("IMPRESS_TEST_MODE", "0") == "1"
cfg = TEST if TEST_MODE else PROD

N_PIPELINES = 2 if TEST_MODE else int(os.environ.get("IMPRESS_N_PIPELINES", cfg.n_pipelines))
MAX_PASSES   = 1 if TEST_MODE else int(os.environ.get("ROME_MAX_PASSES", 10))

#: LigandMPNN checkout — same directory mpnn.sh and mpnn_run.py use.
MPNN_DIR = os.environ.get("MPNN_DIR", "")


# ── Reward function (scientist-visible) ───────────────────────────────────────

def smb_reward_fn(record: dict) -> float:
    """Per-sample training reward for small-molecule binding designs.

    Higher reward → more gradient for this sample in the fine-tuning round.
    Rewards are normalized within each epoch so relative values matter, not
    absolute scale.

    Fields available in ``record``:
        plddt               (float): mean AF2 pLDDT of the best model [0-100]
        interaction_energy  (float): Rosetta interaction energy [REU, negative = better]
        max_sc              (float): shape complementarity [0-1, higher = better]

    Adjust the weights and thresholds for your campaign.
    """
    plddt   = float(record.get("plddt")   or 0.0)
    interact = float(record.get("interaction_energy") or 0.0)
    max_sc  = float(record.get("max_sc")  or 0.0)

    # Normalize each metric to an approximate [0, 1] range
    r_plddt   = max(0.0, plddt - 75.0)  / 25.0      # 75 → 0,  100 → 1
    r_interact = max(0.0, -interact - 5.0) / 15.0   # -5 → 0, -20 → 1
    r_max_sc  = max(0.0, max_sc  - 0.5) / 0.3       # 0.5 → 0, 0.8 → 1

    return r_plddt + r_interact + r_max_sc           # 0–3 combined


# ── Trainer builder ───────────────────────────────────────────────────────────

def _build_trainer(checkpoint_dir: str) -> Any:
    """LigandMPNN fine-tuner; falls back to dummy if ROME_TRAINER=dummy or MPNN_DIR missing."""
    rome_trainer = os.environ.get("ROME_TRAINER", "mpnn").lower()
    if rome_trainer != "dummy" and MPNN_DIR and os.path.isdir(MPNN_DIR):
        return LigandMPNNTrainer(LigandMPNNConfig(mpnn_dir=MPNN_DIR), gpus=1)

    if rome_trainer != "dummy":
        print(
            f"[ROME] MPNN_DIR={MPNN_DIR!r} not found; falling back to DummyTrainer "
            "(set MPNN_DIR to enable real fine-tuning, or export ROME_TRAINER=dummy to silence this)."
        )
    from rome.dummy import DummyTrainer
    return DummyTrainer(train_seconds=1.0, gpus=0)


# ── Main ──────────────────────────────────────────────────────────────────────

async def impress_smallmol_bind_rome() -> None:
    workdir = tempfile.mkdtemp(prefix="impress_smb_rome_")
    stage_dir = os.path.join(workdir, "designs")
    os.makedirs(stage_dir, exist_ok=True)

    rome_backend = await DragonExecutionBackend()
    rome_manager = rome.Manager(
        backend=rome_backend,
        data_config=rome.DataConfig(
            min_samples=int(os.environ.get("ROME_MIN_SAMPLES", 8)),
            sample_func=percentile_sampler(0.33, on_summary=print),
        ),
        trainer_config=rome.TrainerConfig(
            trainer=_build_trainer(os.path.join(workdir, "checkpoints")),
            checkpoint_dir=os.path.join(workdir, "checkpoints"),
            poll_interval=5.0,
            result_fallback_seconds=float(os.environ.get("ROME_FALLBACK", 60)),
            train_kwargs={"reward_fn": smb_reward_fn},
        ),
    )
    await rome_manager.start()

    backend = await DragonExecutionBackend()
    manager: ImpressManager = ImpressManager(execution_backend=backend)

    async def adaptive_decision(pipeline: SmallMoleculeBindingPipeline) -> None:
        step    = pipeline.state.get("last_analysis_step")
        metrics = pipeline.state.get("last_analysis_metrics", {})

        # Cache metrics that are overwritten by later analysis steps.
        # At 'fastrelax' the dict has 'interact'; at 'interface' it has 'max_sc'.
        # By 'fold', both are gone — we read back from pipeline.state.
        if step == "fastrelax":
            pipeline.state["_rome_interact"] = metrics.get("interact")
        elif step == "interface":
            pipeline.state["_rome_max_sc"] = metrics.get("max_sc")

        # Delegate all decision logic to the base adaptive_decision.
        await _base_adaptive_decision(pipeline)

        # ROME hooks — only at the fold step (after AF2).
        if step != "fold":
            return

        plddt   = metrics.get("best_complex_plddt", -1.0)
        interact = pipeline.state.get("_rome_interact")
        max_sc  = pipeline.state.get("_rome_max_sc")

        # Stage the best AF2 model for training.
        best_model = pipeline.state.get("best_fold_model")
        accepted = 0
        if best_model and os.path.exists(best_model):
            stem   = os.path.splitext(os.path.basename(best_model))[0]
            staged = os.path.join(
                stage_dir,
                f"{pipeline.name}_pass{pipeline.passes}_{stem}.pdb",
            )
            shutil.copyfile(best_model, staged)
            uid = rome_manager.add_training_data(
                path=staged,
                plddt=float(plddt),
                interaction_energy=float(interact) if interact is not None else None,
                max_sc=float(max_sc)    if max_sc   is not None else None,
                score=float(plddt),
            )
            accepted = uid is not None

        weights = rome_manager.get_current_model()
        pipeline.logger.pipeline_log(
            f"ROME: corpus {rome_manager.data.total_count} (+{accepted} this pass) | "
            f"{rome_manager.get_training_status().name}"
            + (f" | model {os.path.basename(weights)}" if weights else "")
        )

    examples_dir = os.path.dirname(os.path.abspath(__file__))
    smb_dir      = os.path.join(examples_dir, "..", "small_molecule_binding")
    output_dir   = os.environ.get(
        "IMPRESS_OUTPUT_DIR", os.path.join(examples_dir, "IMPRESS_outputs")
    )
    os.makedirs(output_dir, exist_ok=True)

    all_gpus = find_gpus()

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name=f"p{str(i)}",
            type=SmallMoleculeBindingPipeline,
            adaptive_fn=adaptive_decision,
            kwargs={
                "base_path":                 output_dir,
                "scripts_path":              os.path.join(os.path.abspath(smb_dir), "scripts"),
                "input_dir":                 os.path.join(os.path.abspath(smb_dir), f"p{i}_in"),
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
                **({"gpu_id": all_gpus[(i - 1) % len(all_gpus)]} if all_gpus else {}),
            }
        )
        for i in range(1, N_PIPELINES + 1)
    ]

    try:
        await manager.start(pipeline_setups=pipeline_setups)
        print("\nROME:", rome_manager.report())
    finally:
        await rome_manager.stop()


if __name__ == "__main__":
    asyncio.run(impress_smallmol_bind_rome())
