import copy
import shutil
import asyncio
from typing import Dict, Any, Optional, List

from rhapsody.backends import DragonExecutionBackendV3
from rhapsody.telemetry import define_event
from rhapsody.telemetry.events import make_event

from impress import PipelineSetup
from impress import ImpressManager
from protein_binding import ProteinBindingPipeline

import rhapsody, logging
rhapsody.enable_logging(level=logging.DEBUG)


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

async def adaptive_criteria(current_score: float, previous_score: float) -> bool:
    return current_score > previous_score


async def impress_protein_bind() -> None:
    backend = await DragonExecutionBackendV3()

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
        MAX_SUB_PIPELINES: int = 3
        tel = manager.telemetry
        sid = tel.session_id if tel else None

        # Read current scores from CSV
        file_name = f'af_stats_{pipeline.name}_pass_{pipeline.passes}.csv'
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
            decision = await adaptive_criteria(curr_score, prev_score)
            pipeline.logger.pipeline_log(f'Adaptive decision: {decision}')

            if tel:
                tel.emit(make_event(
                    ProteinScore,
                    session_id=sid,
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
                dst = f'{pipeline.base_path}/prod_in/{new_name}_in/{protein}.pdb'
                shutil.copyfile(src, dst)

            if tel:
                tel.emit(make_event(
                    ChildPipelineSpawned,
                    session_id=sid,
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
                pipeline_name=pipeline.name,
                pass_num=pipeline.passes,
                num_proteins=len(pipeline.current_scores),
                num_degraded=len(sub_iter_seqs),
                child_spawned=child_spawned,
            ))

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name=f"p{str(i)}",
            type=ProteinBindingPipeline,
            adaptive_fn=adaptive_decision
        )
        for i in range(1, 17)
    ]

    await manager.start(pipeline_setups=pipeline_setups)

    if manager.telemetry:
        summary = manager.telemetry.summary()
        print(f"[TELEMETRY] tasks={summary.get('tasks', {})}")
        dur = summary.get("duration")
        if dur:
            print(f"[TELEMETRY] mean task time: {dur['mean_seconds'] * 1000:.1f} ms")

    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(impress_protein_bind())
