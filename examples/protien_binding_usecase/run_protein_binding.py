import copy
import shutil
import asyncio
from typing import Dict, Any, Optional, List
import json

from radical.asyncflow import RadicalExecutionBackend

from impress import PipelineSetup
from impress import ImpressManager
from impress.pipelines.protein_binding import ProteinBindingPipeline
from impress.utils.agentic import llm_agent, adaptive_criteria
from impress.utils.agentic.agent import pipelines_decisions


import logging

logger = logging.getLogger(__name__)


async def adaptive_criteria(protein_name:str, score_history: List[float], pipeline: ProteinBindingPipeline) -> bool:
    """
    Determine if protein quality has degraded, requiring pipeline migration.
    
    Uses an AI agent with historical analysis tools for decision-making.
    
    Args:
        protein_name: The name of the protein being evaluated.
        score_history: A list of all scores for this protein from previous passes.
        pipeline: The complete parent pipeline object.
        
    Returns:
        True if a new pipeline should be spawned, False otherwise.
    """
    context = {
        "protein_name": protein_name,
        "score_history": score_history,
        "current_pass": pipeline.passes,
        "max_passes": pipeline.max_passes,
        "current_sub_pipeline_order": pipeline.sub_order,
        "max_sub_pipelines": 3, # Hardcoded value
        "current_sequence_rank": pipeline.seq_rank
    }
    
    llm_message = f"Evaluate the performance of protein `{protein_name}`\
                   . Here is the context: {context}\
                    Should I spawn a new pipeline for it?"

    llm_response = await llm_agent.prompt(message=llm_message) 
    spawn_new_pipeline_decision = llm_response.parsed_response.spawn_new_pipeline
    confidence = llm_response.parsed_response.confidence

    logger.info(f"Agent decision for {protein_name}: "
                f"Spawn New = {spawn_new_pipeline_decision}. "
                f"Confidence =  {confidence}")

    return spawn_new_pipeline_decision


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
            score = float(score_str)
            if protein not in pipeline.score_history: # Appending scores
                pipeline.score_history[protein] = []
            pipeline.score_history[protein].append(score)

    # We  will wait for at least two passes 
    if pipeline.passes < 2:
        pipeline.logger.pipeline_log('Not enough data for adaptive decision, continuing.')
        return

    # Identify proteins that got worse
    sub_iter_seqs = {}
    for protein, scores in pipeline.score_history.items():
        if protein not in pipeline.iter_seqs:
            continue

        try:
            decision = await adaptive_criteria(protein, scores, pipeline)
        except Exception as e:
            logger.error(e) 
            continue

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
                "score_history": copy.deepcopy(pipeline.score_history),
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
    backend = await RadicalExecutionBackend(
            {
                'gpus':1,
                'cores': 32,
                'runtime' : 23 * 60,
                'resource': 'purdue.anvil_gpu'
                }
            )

    manager: ImpressManager = ImpressManager(execution_backend=backend)

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name='p1',
            type=ProteinBindingPipeline,
            adaptive_fn=adaptive_decision
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)

    await manager.flow.shutdown()

    log_filename = "agent_decisions.log"
    with open(log_filename, "w") as f:
        json.dump(pipelines_decisions, f, indent=4)


if __name__ == "__main__":
    asyncio.run(impress_protein_bind())
