import copy
import shutil
import asyncio
from typing import Dict, Any, Optional, List

from radical.asyncflow import RadicalExecutionBackend

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

    pipeline.logger.pipeline_log(f'iITER SEQ {pipeline.iter_seqs}')

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

        decision = await adaptive_criteria(curr_score, pipeline.previous_scores[protein])
        
        pipeline.logger.pipeline_log(f'Pipeline Scores {curr_score}, {pipeline.previous_scores[protein]}')
        pipeline.logger.pipeline_log(f'Adaptive descision: {decision}')
        
        if decision:
            pipeline.logger.pipeline_log(f'Entered if decsison')
            sub_iter_seqs[protein] = pipeline.iter_seqs.pop(protein)

    # Spawn a new pipeline for bad proteins
    pipeline.logger.pipeline_log(f'Before if MAX_SUB_PIPELINES {MAX_SUB_PIPELINES}: {sub_iter_seqs}, {pipeline.sub_order}')
    if sub_iter_seqs and pipeline.sub_order < MAX_SUB_PIPELINES:
        pipeline.logger.pipeline_log(f'Entered pipeline.sub_order < MAX_SUB_PIPELINES')
        pipeline.logger.pipeline_log(f'maybe submit new pipeline: {pipeline.sub_order}')
        new_name: str = f"{pipeline.name}_sub{pipeline.sub_order + 1}"

        pipeline.set_up_new_pipeline_dirs(new_name)

        # Copy PDB files for bad proteins
        for protein in sub_iter_seqs:
            src = f'{pipeline.output_path_af}/{protein}.pdb'
            dst = f'{pipeline.base_path}/{new_name}_in/{protein}.pdb'
            pipeline.logger.pipeline_log(f'{pipeline.output_path_af}, {pipeline.base_path}')
            shutil.copyfile(src, dst)

        # Build a request for a new pipeline
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

        # Submit the request
        pipeline.submit_child_pipeline_request(new_config)

        pipeline.finalize(sub_iter_seqs)

        if not pipeline.fasta_list_2:
            pipeline.kill_parent = True
    else:
        pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)


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


if __name__ == "__main__":
    asyncio.run(impress_protein_bind())
