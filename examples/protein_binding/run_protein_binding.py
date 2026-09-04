import copy
import os
import shutil
import asyncio
from typing import Dict, Any, Optional, List

from rhapsody.backends import DragonExecutionBackend
from rhapsody.telemetry import define_event
from rhapsody.telemetry.events import make_event

from impress import GPUPolicy, _find_gpus, _make_policy, ImpressManager, PipelineSetup
from protein_binding import ProteinBindingPipeline

import rhapsody, logging
rhapsody.enable_logging(level=logging.DEBUG)


# ── Test mode (IMPRESS_TEST_MODE=1) ───────────────────────────────────────
# Runs 2 pipelines with max_passes=1 and no child pipelines, so a single
# MPNN → score → AF2 cycle completes for integration testing.
TEST_MODE = os.getenv("IMPRESS_TEST_MODE", "0") == "1"
N_PIPELINES = 2      if TEST_MODE else 16
MAX_PASSES  = 1      if TEST_MODE else 10
MAX_SUB_PIPELINES_OVERRIDE = 0 if TEST_MODE else None  # None = use inline default


# ---------------------------------------------------------------------------
# Custom application-level telemetry events
# ---------------------------------------------------------------------------

ProteinScore = define_event(
    "impress.ProteinScore",
    protein=str,
    pipeline_name=str,
    pass_num=int,
    current_score=float,
    previous_score=float,
    decision=str,       # "keep" | "degrade"
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
# Real-time failure subscriber (runs on the asyncio event loop)
# ---------------------------------------------------------------------------

def _on_task_event(event) -> None:
    if event.event_type == "TaskFailed":
        wid = getattr(event, "workflow_id", None)
        print(f"[TELEMETRY] TaskFailed  task={event.task_id}  workflow={wid}")


# ---------------------------------------------------------------------------
# Adaptive helpers
# ---------------------------------------------------------------------------

def adaptive_criteria(current_score: float, previous_score: float) -> bool:
    return current_score > previous_score


async def impress_protein_bind() -> None:
    backend = await DragonExecutionBackend()

    manager: ImpressManager = ImpressManager(
        execution_backend=backend,
        telemetry_config={
            "checkpoint_path": "./telemetry/",
            "resource_poll_interval": 5.0,
        },
        telemetry_subscribers=[_on_task_event],
    )

    # adaptive_decision closes over `manager` so it can emit events via
    # manager.telemetry, which is set inside start() before any pipeline runs.
    async def adaptive_decision(pipeline: ProteinBindingPipeline) -> Optional[Dict[str, Any]]:
        MAX_SUB_PIPELINES: int = MAX_SUB_PIPELINES_OVERRIDE if MAX_SUB_PIPELINES_OVERRIDE is not None else 3
        tel = manager.telemetry
        sid = tel.session_id if tel else None

        # Read current scores from CSV
        file_name = os.path.join(pipeline.output_base_path, f'af_stats_{pipeline.name}_pass_{pipeline.passes}.csv')
        with open(file_name) as fd:
            for line in fd.readlines()[1:]:
                line = line.strip()
                if not line:
                    continue
                name, *_, score_str = line.split(',')
                protein = name.split('.')[0]
                pipeline.current_scores[protein] = float(score_str)

        # First pass — just save current scores as previous
        if not pipeline.previous_scores:
            pipeline.logger.pipeline_log('Saving current scores as previous and returning')
            pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)
            return

        # Identify proteins that got worse
        sub_iter_seqs: Dict[str, str] = {}
        for protein, curr_score in pipeline.current_scores.items():
            if protein not in pipeline.iter_seqs:
                continue

            prev_score = pipeline.previous_scores[protein]
            decision = adaptive_criteria(curr_score, prev_score)
            pipeline.logger.pipeline_log(f'Adaptive decision: {decision}')

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
                src = f'{pipeline.output_path_af}/{protein}.pdb'
                dst = f'{pipeline.input_base_path}/prod_in/{new_name}_in/{protein}.pdb'
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
                'name': new_name,
                'type': type(pipeline),
                'adaptive_fn': adaptive_decision,
                'config': {
                    'is_child': True,
                    'start_pass': pipeline.passes,
                    'passes': pipeline.passes,
                    'iter_seqs': sub_iter_seqs,
                    'seq_rank': pipeline.seq_rank + 1,
                    'sub_order': pipeline.sub_order + 1,
                    'previous_scores': copy.deepcopy(pipeline.previous_scores),
                    'input_base_path': pipeline.input_base_path,
                    'output_base_path': pipeline.output_base_path,
                }
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

    # IMPRESS_SCRIPTS_DIR  = protein_binding examples dir (scripts/, mpnn_wrapper.py)
    # IMPRESS_BASE_DIR     = parent of prod_in/ (input PDB files)
    # IMPRESS_OUTPUT_DIR   = where af_pipeline_outputs_multi/ is written
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

    await manager.start(pipeline_setups=pipeline_setups)

    if manager.telemetry:
        summary = manager.telemetry.summary()
        print(f"[TELEMETRY] tasks={summary.get('tasks', {})}")
        dur = summary.get("duration")
        if dur:
            print(f"[TELEMETRY] mean task time: {dur['mean_seconds'] * 1000:.1f} ms")
        await manager.telemetry.stop()



if __name__ == "__main__":
    asyncio.run(impress_protein_bind())
