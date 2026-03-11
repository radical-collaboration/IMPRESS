from __future__ import annotations

import copy
import shutil
from pathlib import Path

from .pipeline import ProteinBindingFlowgenticPipeline


async def adaptive_decision(pipeline: ProteinBindingFlowgenticPipeline) -> None:
    """Adaptive decision policy mirroring IMPRESS protein binding behavior."""

    if pipeline.passes < 2:
        pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)
        return

    sub_iter_seqs: dict[str, list] = {}

    for protein, scores in pipeline.score_history.items():
        if protein not in pipeline.iter_seqs or len(scores) < 2:
            continue

        previous = scores[-2]
        current = scores[-1]

        if current > previous + pipeline.degradation_threshold:
            sub_iter_seqs[protein] = pipeline.iter_seqs.pop(protein)

    can_spawn = (
        bool(sub_iter_seqs)
        and pipeline.sub_order < pipeline.max_sub_pipelines
        and (pipeline.seq_rank + 1) < pipeline.num_seqs
    )

    if not can_spawn:
        pipeline.previous_scores = copy.deepcopy(pipeline.current_scores)
        return

    new_name = f"{pipeline.name}_sub{pipeline.sub_order + 1}"
    pipeline.set_up_new_pipeline_dirs(new_name)

    for protein in sub_iter_seqs:
        src = Path(pipeline.output_path_af) / f"{protein}.pdb"
        dst = Path(pipeline.base_path) / f"{new_name}_in" / f"{protein}.pdb"
        if src.exists():
            shutil.copyfile(src, dst)

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
            "score_history": copy.deepcopy(pipeline.score_history),
            "base_path": str(pipeline.base_path),
            "max_passes": pipeline.max_passes,
            "num_seqs": pipeline.num_seqs,
            "max_sub_pipelines": pipeline.max_sub_pipelines,
            "degradation_threshold": pipeline.degradation_threshold,
        },
    }

    pipeline.submit_child_pipeline_request(new_config)
    pipeline.finalize(sub_iter_seqs)

    if not pipeline.fasta_list_2:
        pipeline.kill_parent = True
