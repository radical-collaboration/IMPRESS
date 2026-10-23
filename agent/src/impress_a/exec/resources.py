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
