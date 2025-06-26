import copy
import asyncio
import random

from radical.asyncflow import ThreadExecutionBackend

from impress.impress_manager import ImpressManager
from impress.pipelines.protein_binding import ProteinBindingPipeline

async def adaptive_criteria(current_score, previous_score):
	# True indicates that the quality has gotten worse, and the protein should be moved to a new pipeline
	# Separate comparison method helps implement custom functions for judging structure quality
	if current_score > previous_score:
		return True
	return False

async def alphafold_adaptive_fn1(pipeline):
    MAX_SUB_PIPELINES = 3
    current_scores = await pipeline.get_scores_map()
    sub_iter_seqs = {}

    # Compare each protein's score
    for protein, score in current_scores['c_scores'].items():
        prev = current_scores['p_scores'].get(protein)
        if prev is not None and score > prev:
            if pipeline.iter_seqs.get(protein):
                bad_condition = await adaptive_criteria(score, pipeline.previous_scores[protein])
                if bad_condition:
                    # Got worse, must move to new pipeline
                    sub_iter_seqs[protein] = pipeline.iter_seqs.pop(protein)

    if sub_iter_seqs and pipeline.sub_order < MAX_SUB_PIPELINES:
        new_name = f"{pipeline.name}_sub{pipeline.sub_order + 1}"

        new_pipe_config = {
            'name': new_name,
            'type': type(pipeline),
            'config': {'iter_seqs': sub_iter_seqs,
                       'step_id': pipeline.step_id + 1,
                       'sub_order': pipeline.sub_order + 1,
                       'previous_score': copy.deepcopy(current_scores['c_scores']),},
            'adaptive_fn': alphafold_adaptive_fn1}

        # Dummy randomized version to simulate that if not fasta files
        # left, then kill the parent pipeline
        if random.choice([True, False]):
            print("[DUMMY] Simulating: pipeline.fasta_list_2 is empty")
            pipeline.kill_parent = True
        else:
            print("[DUMMY] Simulating: pipeline.fasta_list_2 is not empty")

        return new_pipe_config

    return None


async def impress_protein_bind():

    manager = ImpressManager(execution_backend=ThreadExecutionBackend({}))

    await manager.start(pipeline_setups=[{'name': 'p1', 'config': {}, 
                                          'type': ProteinBindingPipeline,
                                          'adaptive_fn': alphafold_adaptive_fn1},
                                         {'name': 'p2', 'config': {}, 
                                          'type': ProteinBindingPipeline,
                                          'adaptive_fn': alphafold_adaptive_fn1}])

asyncio.run(impress_protein_bind())
