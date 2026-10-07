"""Mock task agents for the laptop test tier.

Deliberately includes a tool that LIES - produces plausible-but-wrong output that only a
QC gate catches. Part A found silent failure is the dominant hazard, so the test suite
has to manufacture some (Part C doc 05).
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

from .agent import TaskAgent, TaskRequest


def _rng(seed_parts: Any) -> random.Random:
    h = hashlib.sha256(str(seed_parts).encode()).hexdigest()
    return random.Random(int(h[:8], 16))


def _upstream(inputs: dict[str, Any]) -> list[Any]:
    """What a mock's draw may depend on: each upstream task's tool, outputs and metrics.

    Not the whole input dict. Inputs also carry each upstream task's QC report, so seeding
    on `str(inputs)` made the mock's science a function of the QC schema: adding one field
    to `GateResult` reshuffled every downstream draw and changed the demo campaign's outcome.
    """
    return [(k, v.get("tool"), v.get("outputs"), v.get("metrics"))
            if isinstance(v, dict) else (k, v) for k, v in sorted(inputs.items())]


class GenerateAgent(TaskAgent):
    """Backbone generation. Quality improves with diffusion_steps (a real trade-off)."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id))
        steps = params.get("diffusion_steps", 50)
        n = params.get("num_designs", 1)
        quality = min(0.95, 0.35 + steps / 250.0 + r.uniform(-0.05, 0.05))
        return {"result": "backbone", "count": n,
                "outputs": {"designs": f"backbone[{n}]"},
                "metrics": {"ss_fraction": round(max(0.0, quality), 3),
                            "designability": round(quality, 3)}}


class DesignAgent(TaskAgent):
    """Inverse folding. Lower temperature -> higher recovery, less diversity."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        t = params.get("temperature", 0.1)
        recovery = max(0.15, min(0.85, 0.75 - t * 0.9 + r.uniform(-0.04, 0.04)))
        return {"result": "sequence", "count": params.get("num_seqs", 1),
                "outputs": {"sequences": "SEQ"},
                "metrics": {"seq_recovery": round(recovery, 3),
                            "diversity": round(min(1.0, t * 1.4), 3)}}


class FoldAgent(TaskAgent):
    """Structure prediction. Emits the confidence metrics an agent gates on."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        rec = 0.5
        for v in req.inputs.values():
            if isinstance(v, dict):
                rec = v.get("metrics", {}).get("seq_recovery", rec)
        iptm = max(0.1, min(0.98, rec + r.uniform(-0.12, 0.22)))
        sc_rmsd = max(0.4, 6.0 * (1.0 - iptm) + r.uniform(-0.3, 0.6))
        return {"result": "complex", "count": 1,
                "outputs": {"complex": "CPLX"},
                "metrics": {"iptm": round(iptm, 3), "sc_rmsd": round(sc_rmsd, 3),
                            "ss_fraction": round(0.3 + iptm * 0.5, 3)}}


class ScoreAgent(TaskAgent):
    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        ddg = round(r.uniform(-3.5, 2.0), 3)
        return {"result": "scores", "count": 1, "outputs": {"metrics": "M"},
                "metrics": {"ddg": ddg, "clashscore": round(abs(r.gauss(4, 3)), 2)}}


class NoodleAgent(TaskAgent):
    """A tool that LIES.

    Completes successfully, returns confident-looking numbers, and produces a structure
    with essentially no secondary structure. Only the `has_secondary_structure` gate
    catches it - exactly the Part A failure mode.
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        return {"result": "backbone", "count": params.get("num_designs", 1),
                "outputs": {"designs": "noodle"},
                "metrics": {"ss_fraction": 0.02, "designability": 0.91}}
