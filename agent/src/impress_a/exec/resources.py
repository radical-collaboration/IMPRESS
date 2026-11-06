"""Resource normalization.

Phase 2 finding (M2): resource shapes are NOT portable. RADICAL takes
{"ranks","gpus_per_rank"}; Dragon takes process_template(s). There is no common
vocabulary, so ToolSpec.resources -> per-backend description is ours to own.
"""
from __future__ import annotations

from typing import Any

from ..tools.spec import ResourceShape


def to_backend_description(shape: ResourceShape, backend_kind: str) -> dict[str, Any]:
    kind = backend_kind.lower()
    if kind in ("radical", "radical_pilot"):
        d: dict[str, Any] = {"ranks": shape.ranks}
        if shape.gpus:
            d["gpus_per_rank"] = shape.gpus
        if shape.cores > 1:
            d["cores_per_rank"] = shape.cores
        return d
    if kind == "dragon":
        # Dragon speaks process templates, not ranks/gpus.
        return {"process_templates": [{"target": None,
                                       "nproc": max(shape.ranks, 1),
                                       "cpu_affinity": list(range(shape.cores))}]}
    # concurrent / local / noop take no resource description at all.
    return {}


def thread_caps(threads: int) -> dict[str, str]:
    """Environment that holds a CPU-bound child to `threads`.

    The same five variables the reference pipeline sets, and for the same measured reason:
    uncapped, one tool took about 30 cores of the Dragon primary on smoke job 22670942, and
    `os.cpu_count()` reports the node rather than the allocation - so on anything less than a
    whole node every CPU stage claims every core and the stages fight each other.
    `OMP_WAIT_POLICY=PASSIVE` because spinning idle threads burn a core each while a stage
    waits on the GPU stages.
    """
    caps = {v: str(max(1, threads)) for v in
            ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
             "NUMEXPR_NUM_THREADS")}
    caps["OMP_WAIT_POLICY"] = "PASSIVE"
    return caps


def gpu_env(gpu_index: int | None, backend_kind: str) -> dict[str, str]:
    """Environment that pins a child to one GPU - where the env is what does the pinning.

    Backlog A10's other half: concurrent GPU tasks were not pinned at all, and
    `to_backend_description` above had no caller.

    **Two shapes, and only one of them is an env var.** Under a concurrent backend the env
    passed to `asyncio.create_subprocess_exec` REPLACES the child's environment, so
    `CUDA_VISIBLE_DEVICES` set there works. Under Dragon it does not: local services MERGES a
    process template's env (`the_env = dict(os.environ); the_env.update(req_env)`) and then
    applies the placement policy afterwards, so a policy with no `gpu_affinity` resolves to
    every GPU on the node whatever the env said. Dragon needs
    `Policy(gpu_affinity=[gpu_index])` on the process template instead, which is why this
    returns nothing for it rather than something that looks like it should work.
    """
    if gpu_index is None or backend_kind.lower() == "dragon":
        return {}
    return {"CUDA_VISIBLE_DEVICES": str(gpu_index)}
