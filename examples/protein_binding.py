import copy
import asyncio
import random
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


async def alphafold_adaptive_fn1(pipeline: ProteinBindingPipeline) -> Optional[Dict[str, Any]]:
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
    current_scores: Dict[str, Dict[str, float]] = await pipeline.get_scores_map()
    sub_iter_seqs: Dict[str, str] = {}

    # Compare each protein's score
    for protein, score in current_scores['c_scores'].items():
        prev: Optional[float] = current_scores['p_scores'].get(protein)
        if prev is not None and score > prev:
            if pipeline.iter_seqs.get(protein):
                bad_condition: bool = await adaptive_criteria(score, pipeline.previous_scores[protein])
                if bad_condition:
                    # Got worse, must move to new pipeline
                    sub_iter_seqs[protein] = pipeline.iter_seqs.pop(protein)

    if sub_iter_seqs and pipeline.sub_order < MAX_SUB_PIPELINES:
        new_name: str = f"{pipeline.name}_sub{pipeline.sub_order + 1}"

        new_pipe_config: Dict[str, Any] = {
            'name': new_name,
            'type': type(pipeline),
            'config': {
                'iter_seqs': sub_iter_seqs,
                'step_id': pipeline.step_id + 1,
                'sub_order': pipeline.sub_order + 1,
                'previous_score': copy.deepcopy(current_scores['c_scores']),
            },
            'adaptive_fn': alphafold_adaptive_fn1
        }

        # Dummy randomized version to simulate that if not fasta files
        # left, then kill the parent pipeline
        if random.choice([True, False]):
            print("[DUMMY] Simulating: pipeline.fasta_list_2 is empty")
            pipeline.kill_parent = True
        else:
            print("[DUMMY] Simulating: pipeline.fasta_list_2 is not empty")

        return new_pipe_config

    return None


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
            adaptive_fn=alphafold_adaptive_fn1
        ),
        PipelineSetup(
            name='p2',
            type=ProteinBindingPipeline,
            adaptive_fn=alphafold_adaptive_fn1
        ),
        PipelineSetup(
            name='p3',
            type=ProteinBindingPipeline,
            adaptive_fn=alphafold_adaptive_fn1
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)


if __name__ == "__main__":
    asyncio.run(impress_protein_bind())
