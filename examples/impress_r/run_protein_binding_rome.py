import copy
import csv
import os
import shutil
import asyncio
import tempfile
from typing import Dict, Any, Optional, List

from rhapsody.backends import DragonExecutionBackend
from rhapsody.telemetry import define_event
from rhapsody.telemetry.events import make_event

from impress import GPUPolicy, _find_gpus, _make_policy, ImpressManager, PipelineSetup

try:
    from examples.impress_r.protein_binding_rome import ProteinBindingPipeline
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from protein_binding_rome import ProteinBindingPipeline

try:
    from examples.impress_r.mpnn import (
        ProteinMPNNConfig,
        ProteinMPNNTrainer,
        percentile_sampler,
    )
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mpnn import ProteinMPNNConfig, ProteinMPNNTrainer, percentile_sampler

import rome

import rhapsody, logging
rhapsody.enable_logging(level=logging.INFO)


# ── Test mode (IMPRESS_TEST_MODE=1) ───────────────────────────────────────────
# Runs 2 pipelines with max_passes=1 and no child pipelines, so a single
# MPNN → Boltz → pLDDT → ROME cycle completes for integration testing.
TEST_MODE = os.getenv("IMPRESS_TEST_MODE", "0") == "1"
N_PIPELINES = 2 if TEST_MODE else int(os.environ.get("IMPRESS_N_PIPELINES", 16))
MAX_PASSES  = 1 if TEST_MODE else int(os.environ.get("ROME_MAX_PASSES", 10))
# IMPRESS_MAX_SUB_PIPELINES: max depth of child pipeline spawning (0 = none, 3 = full).
# Unset or blank → inherit the inline default of 3.
_sub_env = os.environ.get("IMPRESS_MAX_SUB_PIPELINES", "").strip()
MAX_SUB_PIPELINES_OVERRIDE = 0 if TEST_MODE else (int(_sub_env) if _sub_env else None)


# ── ProteinMPNN repo ───────────────────────────────────────────────────────────
# The same checkout IMPRESS runs for inference; ROME fine-tunes and publishes back
# into vanilla_model_weights/ so the next pass picks it up with no wrapper change.
MPNN_REPO = os.environ.get(
    "ROME_MPNN_REPO",
    os.environ.get("MPNN_PATH", ""),
)


# ---------------------------------------------------------------------------
# Custom telemetry events
# ---------------------------------------------------------------------------

ProteinScore = define_event(
    "impress.ProteinScore",
    protein=str,
    pipeline_name=str,
    pass_num=int,
    current_score=float,
    previous_score=float,
    decision=str,
)

PassSummary = define_event(
    "impress.PassSummary",
    pipeline_name=str,
    pass_num=int,
    num_proteins=int,
    num_degraded=int,
    child_spawned=bool,
)

ChildPipelineSpawned = define_event(
    "impress.ChildPipelineSpawned",
    parent_name=str,
    child_name=str,
    num_proteins=int,
    seq_rank=int,
)


# ---------------------------------------------------------------------------
# ROME trainer builder
# ---------------------------------------------------------------------------

def _build_trainer(checkpoint_dir: str):
    """ProteinMPNN fine-tuner by default; a no-op dummy for smoke testing.

    ROME_TRAINER=mpnn  → real ProteinMPNN fine-tune (needs ROME_MPNN_REPO)
    ROME_TRAINER=dummy → smoke test (no GPU/torch required for training)
    """
    want = os.environ.get("ROME_TRAINER", "mpnn").lower()
    if want == "mpnn" and os.path.isdir(MPNN_REPO):
        return ProteinMPNNTrainer(ProteinMPNNConfig(
            mpnn_repo=MPNN_REPO,
            initial_weights=os.path.join(MPNN_REPO, "vanilla_model_weights", "v_48_020.pt"),
            model_name="v_48_020",
            publish_into_repo=True,
        ), gpus=1)

    if want == "mpnn":
        print(f"[ROME-A] ROME_MPNN_REPO={MPNN_REPO!r} not found; "
              "falling back to the dummy trainer (set ROME_MPNN_REPO or "
              "ROME_TRAINER=dummy to silence this).")
    from rome.dummy import DummyTrainer
    return DummyTrainer(train_seconds=1.0, gpus=0)


# ---------------------------------------------------------------------------
# Real-time failure subscriber
# ---------------------------------------------------------------------------

def _on_task_event(event) -> None:
    if event.event_type == "TaskFailed":
        wid = getattr(event, "workflow_id", None)
        print(f"[TELEMETRY] TaskFailed  task={event.task_id}  workflow={wid}")


# ---------------------------------------------------------------------------
# Adaptive criteria
# ---------------------------------------------------------------------------

def adaptive_criteria(current_score: float, previous_score: float) -> bool:
    return current_score > previous_score


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def impress_protein_bind() -> None:
    workdir = tempfile.mkdtemp(prefix="impress_r_")
    stage_dir = os.path.join(workdir, "designs")
    os.makedirs(stage_dir, exist_ok=True)

    # ROME-A gets its own Dragon backend so training tasks run in their own
    # processes (separate CUDA context) independent of IMPRESS tasks.
    rome_backend = await DragonExecutionBackend()
    rome_manager = rome.Manager(
        backend=rome_backend,
        data_config=rome.DataConfig(
            min_samples=int(os.environ.get("ROME_MIN_SAMPLES", 2)),
            sample_func=percentile_sampler(0.33),
        ),
        trainer_config=rome.TrainerConfig(
            trainer=_build_trainer(os.path.join(workdir, "checkpoints")),
            checkpoint_dir=os.path.join(workdir, "checkpoints"),
            poll_interval=1.0,
            result_fallback_seconds=float(os.environ.get("ROME_FALLBACK", 60)),
        ),
    )
    await rome_manager.start()

    backend = await DragonExecutionBackend()
    manager: ImpressManager = ImpressManager(
        execution_backend=backend,
        telemetry_config={
            "checkpoint_path": "./telemetry/",
            "resource_poll_interval": 5.0,
        },
        telemetry_subscribers=[_on_task_event],
    )

    # adaptive_decision closes over manager and rome_manager.
    async def adaptive_decision(pipeline: ProteinBindingPipeline) -> Optional[Dict[str, Any]]:
        MAX_SUB_PIPELINES: int = (
            MAX_SUB_PIPELINES_OVERRIDE if MAX_SUB_PIPELINES_OVERRIDE is not None else 3
        )
        tel = manager.telemetry
        sid = tel.session_id if tel else None

        # Read CSV — written by s5_plddt_extract.sh to output_base_path.
        file_name = os.path.join(
            pipeline.output_base_path,
            f"af_stats_{pipeline.name}_pass_{pipeline.passes}.csv",
        )
        accepted = 0
        with open(file_name) as fd:
            for row in csv.DictReader(fd):  # ID, avg_plddt, ptm, avg_pae
                protein = row["ID"].split(".")[0]
                pipeline.current_scores[protein] = float(row["avg_pae"])

                # -- ROME-A HOOK 1: contribute this design to the training corpus
                src = os.path.join(pipeline.output_path_af, f"{protein}.pdb")
                if not os.path.exists(src):
                    continue
                staged = os.path.join(
                    stage_dir,
                    f"{pipeline.name}_pass{pipeline.passes}_{protein}.pdb",
                )
                shutil.copyfile(src, staged)
                ranked = pipeline.iter_seqs.get(protein) or []
                sequence = ranked[pipeline.seq_rank][0] if len(ranked) > pipeline.seq_rank else ""
                uid = rome_manager.add_training_data(
                    path=staged,
                    sequence=sequence,
                    backbone_id=protein,
                    pLDDT=float(row["avg_plddt"]),
                    pTM=float(row["ptm"]),
                    pAE=float(row["avg_pae"]),
                    score=float(row["avg_plddt"]),
                )
                accepted += uid is not None

        # -- ROME-A HOOK 2: collect the improved model for next pass
        weights = rome_manager.get_current_model()
        pipeline.logger.pipeline_log(
            f"ROME-A: corpus {rome_manager.data.total_count} (+{accepted} this pass) | "
            f"{rome_manager.get_training_status().name}"
            + (f" | model {os.path.basename(weights)}" if weights else "")
        )

        # First pass — just save current scores as previous
        if not pipeline.previous_scores:
            pipeline.logger.pipeline_log("Saving current scores as previous and returning")
            pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)
            return

        # Identify proteins that got worse (higher avg_pae = worse interface)
        sub_iter_seqs: Dict[str, str] = {}
        for protein, curr_score in pipeline.current_scores.items():
            if protein not in pipeline.iter_seqs:
                continue
            prev_score = pipeline.previous_scores[protein]
            decision = adaptive_criteria(curr_score, prev_score)
            pipeline.logger.pipeline_log(f"Adaptive decision: {decision}")

            if tel:
                tel.emit(make_event(
                    ProteinScore,
                    session_id=sid,
                    backend="rhapsody",
                    protein=protein,
                    pipeline_name=pipeline.name,
                    pass_num=pipeline.passes,
                    current_score=curr_score,
                    previous_score=prev_score,
                    decision="degrade" if decision else "keep",
                ))

            if decision:
                sub_iter_seqs[protein] = pipeline.iter_seqs.pop(protein)

        # Spawn a new pipeline for degraded proteins
        child_spawned = False
        if sub_iter_seqs and pipeline.sub_order < MAX_SUB_PIPELINES:
            new_name: str = f"{pipeline.name}_sub{pipeline.sub_order + 1}"
            pipeline.set_up_new_pipeline_dirs(new_name)

            for protein in sub_iter_seqs:
                src = f"{pipeline.output_path_af}/{protein}.pdb"
                dst = f"{pipeline.input_base_path}/prod_in/{new_name}_in/{protein}.pdb"
                shutil.copyfile(src, dst)

            if tel:
                tel.emit(make_event(
                    ChildPipelineSpawned,
                    session_id=sid,
                    backend="rhapsody",
                    parent_name=pipeline.name,
                    child_name=new_name,
                    num_proteins=len(sub_iter_seqs),
                    seq_rank=pipeline.seq_rank + 1,
                ))

            new_config = {
                "name": new_name,
                "type": type(pipeline),
                "adaptive_fn": adaptive_decision,
                "config": {
                    "is_child": True,
                    "start_pass": pipeline.passes,
                    "passes": pipeline.passes,
                    "iter_seqs": sub_iter_seqs,
                    "seq_rank": pipeline.seq_rank + 1,
                    "sub_order": pipeline.sub_order + 1,
                    "previous_scores": copy.deepcopy(pipeline.previous_scores),
                    "input_base_path": pipeline.input_base_path,
                    "output_base_path": pipeline.output_base_path,
                },
            }

            pipeline.submit_child_pipeline_request(new_config)
            pipeline.finalize(sub_iter_seqs)

            if not pipeline.fasta_list_2:
                pipeline.kill_parent = True

            child_spawned = True
        else:
            pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)

        if tel:
            tel.emit(make_event(
                PassSummary,
                session_id=sid,
                backend="rhapsody",
                pipeline_name=pipeline.name,
                pass_num=pipeline.passes,
                num_proteins=len(pipeline.current_scores),
                num_degraded=len(sub_iter_seqs),
                child_spawned=child_spawned,
            ))

    # Paths — same convention as protein_binding runner.
    scripts_dir = os.environ.get(
        "IMPRESS_SCRIPTS_DIR", os.path.dirname(os.path.abspath(__file__))
    )
    input_base_dir = os.environ.get("IMPRESS_BASE_DIR", scripts_dir)
    output_base_dir = os.environ.get("IMPRESS_OUTPUT_DIR", scripts_dir)
    os.makedirs(output_base_dir, exist_ok=True)

    all_gpus = _find_gpus()

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name=f"p{str(i)}",
            type=ProteinBindingPipeline,
            config={
                "base_path": scripts_dir,
                "input_base_path": input_base_dir,
                "output_base_path": output_base_dir,
                "policy": _make_policy(all_gpus, i - 1),
            },
            adaptive_fn=adaptive_decision,
            max_passes=MAX_PASSES,
        )
        for i in range(1, N_PIPELINES + 1)
    ]

    try:
        await manager.start(pipeline_setups=pipeline_setups)
        print("\nROME-A:", rome_manager.report())
        if manager.telemetry:
            summary = manager.telemetry.summary()
            print(f"[TELEMETRY] tasks={summary.get('tasks', {})}")
            dur = summary.get("duration")
            if dur:
                print(f"[TELEMETRY] mean task time: {dur['mean_seconds'] * 1000:.1f} ms")
            await manager.telemetry.stop()
    finally:
        await rome_manager.stop()


if __name__ == "__main__":
    asyncio.run(impress_protein_bind())
