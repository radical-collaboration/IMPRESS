import copy
import shutil
import asyncio
from typing import Dict, Any, Optional, List

from radical.asyncflow import RadicalExecutionBackend

from impress import PipelineSetup
from impress import ImpressManager
from impress.pipelines.protein_binding import ProteinBindingPipeline
from impress import llm_agent, provide_llm_context, PipelineContext

import logging

logger = logging.getLogger(__name__)


async def adaptive_criteria(current_score: float, previous_score: float, pipeline: ProteinBindingPipeline) -> bool:
    """
    Determine if protein quality has degraded requiring pipeline migration.
    
    Uses AI agent for decision-making.
    
    Args:
        current_score: Current protein structure quality score
        previous_score: Previous protein structure quality score
        pipeline: Complete pipeline object 
        
    Returns:
        True if quality has degraded, False otherwise
    """
    score_change = current_score - previous_score
    percent_change = (score_change / previous_score * 100) if previous_score != 0 else 0
    
    if percent_change > 2:
        trend = "improving"
    elif percent_change < -2:
        trend = "degrading"
    else:
        trend = "stable"
    
    context = PipelineContext(
        previous_score=previous_score,
        current_score=current_score,
        passes=pipeline.passes,
        max_passes=pipeline.max_passes,
        seq_rank=pipeline.seq_rank,
        sub_order=pipeline.sub_order,
        max_sub_pipelines=3,  # Hardcoded value
        num_proteins_remaining=len(pipeline.iter_seqs),
        score_trend=trend,
        avg_score_change=percent_change,
        pipeline_name=pipeline.name
    )
    
    llm_context = provide_llm_context(pipeline_context=context)
    llm_response = await llm_agent.prompt(message=llm_context)

    return llm_response.parsed_response.spawn_new_pipeline


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
            pipeline.current_scores[protein] = float(score_str)

    # First pass — just save current scores as previous
    if not pipeline.previous_scores:
        pipeline.logger.pipeline_log('Saving current scores as previous and returning')
        pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)
        return

    # Identify proteins that got worse
    sub_iter_seqs = {}
    for protein, curr_score in pipeline.current_scores.items():
        if protein not in pipeline.iter_seqs:
            continue

        try:
            decision = await adaptive_criteria(curr_score, 
                                            pipeline.previous_scores[protein], 
                                            pipeline)
        except Exception as e:
            logger.error(e) 

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

        # Build a request for a new pipeline
        new_config = {
            'name': new_name,
            'type': type(pipeline),
            'adaptive_fn': adaptive_decision,
            'config': {
                'passes': pipeline.passes,
                'iter_seqs': sub_iter_seqs,
                'seq_rank': pipeline.seq_rank + 1,
                'sub_order': pipeline.sub_order + 1,
                'previous_scores': copy.deepcopy(pipeline.previous_scores),
            } 
        }

        # Submit the request
        pipeline.submit_child_pipeline_request(new_config)

        pipeline.finalize()

        if not pipeline.fasta_list_2:
            pipeline.kill_parent = True


async def impress_protein_bind() -> None:
    """
    Execute protein binding analysis with adaptive optimization.
    
    Creates and manages multiple ProteinBindingPipeline instances with
    adaptive optimization capabilities. Each pipeline can spawn child
    pipelines based on protein quality degradation.
    """
    manager: ImpressManager = ImpressManager(execution_backend=RadicalExecutionBackend({'gpus':2,
                                                                                        'cores': 32,
                                                                                        'runtime' : 13 * 60,
                                                                                        'resource': 'purdue.anvil_gpu'}))

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name='p1',
            type=ProteinBindingPipeline,
            adaptive_fn=adaptive_decision
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)

    await manager.flow.shutdown()

    logger.debug(f"AGENTIC RESULTS: \
        pipelines approved: {llm_agent.pipelines_aproved} \
        pipelines rejected: {llm_agent.pipelines_rejected}")


if __name__ == "__main__":
    asyncio.run(impress_protein_bind())
