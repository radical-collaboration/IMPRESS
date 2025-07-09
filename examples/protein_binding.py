import copy
import shutil
import asyncio
from typing import Dict, Any, Optional, List

from radical.asyncflow import ThreadExecutionBackend

from impress import PipelineSetup
from impress import ImpressManager
from impress.pipelines.protein_binding import ProteinBindingPipeline


async def adaptive_criteria(current_score: float, previous_score: float) -> bool:
    """
    Determine if protein quality has degraded requiring pipeline migration.
    
    Compares current and previous protein scores to decide if a protein
    should be moved to a new pipeline for optimization.
    
    Args:
        current_score: Current protein structure quality score
        previous_score: Previous protein structure quality score
        
    Returns:
        True if quality has degraded (score increased), False otherwise
    """
    return current_score > previous_score

async def adaptive_decision(pipeline: ProteinBindingPipeline) -> Optional[Dict[str, Any]]:
    """
    Adaptive function for AlphaFold protein structure optimization.

    Evaluates protein scores and creates child pipelines for proteins with
    degraded quality. Implements adaptive optimization strategy by moving
    underperforming proteins to new pipeline instances.

    Args:
        pipeline: The protein binding pipeline to evaluate
        
    Returns:
        Pipeline configuration dictionary for new child pipeline if needed,
        None otherwise
    """
    MAX_SUB_PIPELINES: int = 3
    sub_iter_seqs: Dict[str, str] = {}

    # Read current scores from CSV
    file_name = f'af_stats_{pipeline.name}_pass_{pipeline.passes}.csv'
    with open(file_name) as fd:
        for line in fd.readlines()[1:]:
            line = line.strip()
            if not line:
                continue

            name, *_, score_str = line.split(',')
            protein = name.split('.')[0]
            pipeline.curr_scores[protein] = float(score_str)

    # First pass — just save current scores as previous
    if not pipeline.prev_scores:
        pipeline.prev_scores = copy.deepcopy(pipeline.curr_scores)
        return

    # Identify proteins that got worse
    sub_iter_seqs = {}
    for protein, curr_score in pipeline.curr_scores.items():
        if protein not in pipeline.iter_seqs:
            continue

        decision = await adaptive_criteria(curr_score, pipeline.prev_scores[protein])

        if decision:
            sub_iter_seqs[protein] = pipeline.iter_seqs.pop(protein)

    # Spawn a new pipeline for bad proteins
    if sub_iter_seqs and pipeline.sub_order < MAX_SUB_PIPELINES:
        new_name: str = f"{pipeline.name}_sub{pipeline.sub_order + 1}"

        pipeline.set_up_new_pipeline_dirs(new_name)

        # Copy PDB files for bad proteins
        for protein in sub_iter_seqs:
            src = f'{pipeline.output_path_af}/{protein}.pdb'
            dst = f'{pipeline.base_path}/{new_name}_in/{protein}.pdb'
            shutil.copyfile(src, dst)

        # Queue new pipeline
        new_config = {
            'name': new_name,
            'type': type(pipeline),
            'adaptive_fn': adaptive_decision,
            'config': {
                'sub_order': pipeline.sub_order + 1,
                'passes': pipeline.passes,
                'iter_seqs': sub_iter_seqs,
                'seq_rank': pipeline.seq_rank + 1,
                'prev_scores': copy.deepcopy(pipeline.prev_scores),
                'stage_id': 1
            } 
        }

        pipeline.submit_child_pipeline_request(new_config)

        pipeline.finalize()


async def impress_protein_bind() -> None:
    """
    Execute protein binding analysis with adaptive optimization.
    
    Creates and manages multiple ProteinBindingPipeline instances with
    adaptive optimization capabilities. Each pipeline can spawn child
    pipelines based on protein quality degradation.
    """
    manager: ImpressManager = ImpressManager(execution_backend=ThreadExecutionBackend({}))

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name='p1',
            type=ProteinBindingPipeline,
            adaptive_fn=adaptive_decision
        ),
        PipelineSetup(
            name='p2',
            type=ProteinBindingPipeline,
            adaptive_fn=adaptive_decision
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)


if __name__ == "__main__":
    asyncio.run(impress_protein_bind())
