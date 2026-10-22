"""The toolkit the LLM drives, and the schemas it sees.

Every tool here is a thin wrapper over a task the reference pipeline already
registers in `_register_real_tasks()`. The wrapper awaits the executable task
and then its paired `analysis_*` step -- the two must stay adjacent, because
each analysis step reads `{taskcount}_<stage>/out` and `taskcount` is a flat
counter incremented by every executable task.

Because the tasks are the inherited ones, each keeps the reference's own
`task_description`: GPU tools pinned to the pipeline's device with 8 threads
(4 for LigandMPNN), Rosetta tools on CPU with 1, analysis local. No resource
plumbing is written here, and none should be.

A handler never raises for a bad request. It returns an error payload, so a
model that calls a tool out of order can read the reason and recover instead of
killing the pipeline.
"""

from __future__ import annotations

import os
from typing import Any

from small_molecule_binding import (
    ETYPE_BACKBONE,
    ETYPE_FOLD,
    ETYPE_SEQUENCE,
    _ca_rmsd,
    _ensemble_selective_avg,
    _seq_identity,
)

# ── Schemas ────────────────────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "design_backbone",
            "description": (
                "Run RFdiffusion3 to generate binder backbones around the "
                "ligand, then score the best one (ligand clashes, max CA "
                "deviation, secondary-structure fraction). Runs on the GPU. "
                "Pass guide_model to start from a previously folded complex "
                "by partial diffusion; pass null for an unguided design."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "guide_model": {
                        "type": ["string", "null"],
                        "description": (
                            "Path to a folded complex from a previous "
                            "fold_complex result, or null for unguided."
                        ),
                    }
                },
                "required": ["guide_model"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "design_sequence",
            "description": (
                "Run LigandMPNN to design sequences for the current structure, "
                "then pick the highest-confidence candidate. Runs on the GPU. "
                "source='backbone' designs from the newest backbone and "
                "generates an ensemble of candidates; source='packed' designs "
                "a single candidate from the current packed structure, which "
                "is what a refinement cycle uses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": ["backbone", "packed"],
                    }
                },
                "required": ["source"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pack_minimize",
            "description": (
                "Rosetta pack and minimize the current sequence onto its "
                "structure, and report the total score. CPU, single-threaded. "
                "Always 'passes'; the score is for your judgement."
            ),
            "parameters": {"type": "object", "properties": {},
                           "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "relax",
            "description": (
                "Rosetta FastRelax the current packed structure and score it "
                "(interaction energy, total score, fa_rep). CPU. Passes only "
                "when all three are below their thresholds."
            ),
            "parameters": {"type": "object", "properties": {},
                           "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_interface",
            "description": (
                "Measure shape complementarity of the relaxed interface. CPU. "
                "Must follow relax. Passes when max_sc clears the threshold."
            ),
            "parameters": {"type": "object", "properties": {},
                           "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fold_complex",
            "description": (
                "Co-fold the designed sequence with the ligand using Boltz-2 "
                "and report complex_plddt and ligand_iptm. Runs on the GPU and "
                "is the most expensive tool. This is the campaign's output: a "
                "passing fold is a result worth keeping."
            ),
            "parameters": {"type": "object", "properties": {},
                           "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_ensemble",
            "description": (
                "Read the campaign history without running anything. Returns "
                "counts and the best entries per stage, and -- when kind is "
                "given -- how the newest entry compares with its predecessors "
                "by structural or sequence similarity. Free and instant; use "
                "it before deciding whether to keep refining or start over."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["backbone", "sequence", "fold"],
                        "description": "Which entry type to compare.",
                    },
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "End this pipeline. Only call this when the budget is spent or "
                "no further progress is possible."
            ),
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_NAMES = [s["function"]["name"] for s in TOOL_SCHEMAS]


# ── Result shaping ─────────────────────────────────────────────────────────

def _error(stage: str, message: str) -> dict:
    return {"stage": stage, "ok": False, "error": message}


def _result(pipeline, stage: str, **extra) -> dict:
    """The common payload: what the analysis step just concluded, plus budget.

    Deliberately small -- metrics and paths, never file contents -- because
    every one of these stays in the context window for the rest of the run.
    """
    metrics = dict(pipeline.state.get("last_analysis_metrics") or {})
    payload = {
        "stage": stage,
        "ok": True,
        "pass": bool(metrics.pop("pass", False)),
        "metrics": metrics,
        "ensemble_used": len(pipeline.state.get("ensemble", [])),
        "ensemble_budget": pipeline.max_tasks,
    }
    payload.update(extra)
    return payload


# ── Handlers ───────────────────────────────────────────────────────────────

async def design_backbone(pipeline, guide_model: str | None = None, **_) -> dict:
    if guide_model:
        if not os.path.isfile(guide_model):
            return _error("backbone", f"no such file: {guide_model}")
        pipeline.state["rfd3_input_pdb"] = guide_model
    else:
        pipeline.state["rfd3_input_pdb"] = None

    await pipeline.rfd3(workflow_id=f"{pipeline.name}:rfd3")
    await pipeline.analysis_backbone()
    return _result(
        pipeline, "backbone",
        backbone_path=pipeline.state.get("best_backbone_path"),
        guided=bool(guide_model),
    )


async def design_sequence(pipeline, source: str = "backbone", **_) -> dict:
    if source not in ("backbone", "packed"):
        return _error("sequence",
                      f"source must be 'backbone' or 'packed', got {source!r}")
    if source == "backbone" and not pipeline.state.get("best_backbone_path"):
        return _error("sequence", "no backbone yet - call design_backbone first")
    if source == "packed" and not pipeline.state.get("best_packed_pdb"):
        return _error("sequence", "no packed structure yet - call design_sequence "
                                  "with source='backbone', then pack_minimize")

    # The reference keys MPNN's input and ensemble size off the refinement
    # cycle index: cycle 0 reads the backbone and makes an ensemble, later
    # cycles read the packed structure and make one candidate.
    pipeline._current_cycle_i = 0 if source == "backbone" else 1

    await pipeline.mpnn(workflow_id=f"{pipeline.name}:mpnn")
    await pipeline.analysis_sequence()
    return _result(
        pipeline, "sequence",
        source=source,
        packed_pdb=pipeline.state.get("best_packed_pdb"),
    )


async def pack_minimize(pipeline, **_) -> dict:
    if not pipeline.state.get("best_packed_pdb"):
        return _error("packmin", "nothing to pack - call design_sequence first")
    await pipeline.packmin(workflow_id=f"{pipeline.name}:packmin")
    await pipeline.analysis_packmin()
    return _result(pipeline, "packmin",
                   packed_pdb=pipeline.state.get("best_packed_pdb"))


async def relax(pipeline, **_) -> dict:
    if not pipeline.state.get("best_packed_pdb"):
        return _error("fastrelax", "nothing to relax - call design_sequence first")
    await pipeline.fastrelax(workflow_id=f"{pipeline.name}:fastrelax")
    await pipeline.analysis_fastrelax()
    return _result(pipeline, "fastrelax", thresholds={
        "max_interact": pipeline.fastrelax_max_interact,
        "max_total_score": pipeline.fastrelax_max_total_score,
        "max_fa_rep": pipeline.fastrelax_max_fa_rep,
    })


async def score_interface(pipeline, **_) -> dict:
    # filter_shape reads the fastrelax output directory at the current
    # taskcount, so anything run in between would point it at the wrong dir.
    if pipeline.previous_task != "fastrelax":
        return _error("interface",
                      "score_interface must come directly after relax "
                      f"(last tool was {pipeline.previous_task})")
    await pipeline.filter_shape(workflow_id=f"{pipeline.name}:filter_shape")
    await pipeline.analysis_interface()
    return _result(pipeline, "interface",
                   threshold={"min_sc": pipeline.interface_min_sc})


async def fold_complex(pipeline, **_) -> dict:
    if not pipeline.state.get("last_seq_fasta"):
        return _error("fold", "no sequence to fold - call design_sequence first")
    await pipeline.boltz(workflow_id=f"{pipeline.name}:boltz")
    await pipeline.analysis_fold()
    return _result(pipeline, "fold",
                   fold_model=pipeline.state.get("best_fold_model"),
                   threshold={"min_plddt": pipeline.fold_min_plddt,
                              "min_ligand_iptm": pipeline.fold_min_ligand_iptm})


_ETYPES = {
    "backbone": (ETYPE_BACKBONE, _ca_rmsd, True),
    "sequence": (ETYPE_SEQUENCE, _seq_identity, False),
    "fold":     (ETYPE_FOLD, _ca_rmsd, True),
}


async def inspect_ensemble(pipeline, kind: str | None = None,
                           top_k: int = 5, **_) -> dict:
    ensemble = pipeline.state.get("ensemble", [])
    counts: dict[str, int] = {}
    for etype, *_rest in ensemble:
        counts[etype] = counts.get(etype, 0) + 1

    out: dict[str, Any] = {
        "stage": "inspect",
        "ok": True,
        "counts": counts,
        "ensemble_used": len(ensemble),
        "ensemble_budget": pipeline.max_tasks,
    }

    if kind:
        if kind not in _ETYPES:
            return _error("inspect", f"kind must be one of {sorted(_ETYPES)}")
        etype, sim_fn, similar_if_low = _ETYPES[kind]
        entries = [e for e in ensemble if e[0] == etype and e[3]]
        out["top"] = [
            {"score": round(score, 4), "output": path}
            for _t, score, _i, path in sorted(
                entries, key=lambda e: e[1], reverse=True)[:max(1, min(top_k, 20))]
        ]
        if len(entries) >= 2:
            current = entries[-1]
            overall, selective, has_data = _ensemble_selective_avg(
                current, entries[:-1], sim_fn, similar_if_low)
            if has_data:
                # The reference reads this comparison the same way: a selective
                # average above the overall one means the newest entry's close
                # neighbours score better than the population, i.e. this region
                # is worth staying in.
                out["similarity"] = {
                    "kind": kind,
                    "overall_avg": round(overall, 4),
                    "selective_avg": round(selective, 4),
                    "neighbourhood_better": selective > overall,
                }
    return out


async def finish(pipeline, reason: str = "", **_) -> dict:
    return {"stage": "finish", "ok": True, "reason": reason}


HANDLERS = {
    "design_backbone": design_backbone,
    "design_sequence": design_sequence,
    "pack_minimize":   pack_minimize,
    "relax":           relax,
    "score_interface": score_interface,
    "fold_complex":    fold_complex,
    "inspect_ensemble": inspect_ensemble,
    "finish":          finish,
}
