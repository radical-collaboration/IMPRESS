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

    **And not the input KEYS either**, which is the same lesson learned twice. They used to be
    in the seed, so when the dispatcher started keying inputs by declared port instead of
    `dep0..depN`, every downstream draw reshuffled and the demo campaign's cycle count changed
    - a rename of the wiring altering the science. Sorted by key for a deterministic order,
    seeded on the CONTENT only.
    """
    return [(v.get("tool"), v.get("outputs"), v.get("metrics"))
            if isinstance(v, dict) else (v,) for _, v in sorted(inputs.items())]


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


class JoinAgent(TaskAgent):
    """Two typed inputs, and it checks which one it got on which port.

    Reports `wired_correctly: 1.0` only if `backbone` resolves to a Backbone-ish artifact and
    `sequences` to a ProteinSequence-ish one. An integrity gate refuses anything else, so a
    mis-wire fails the node rather than quietly producing a plausible number - which is the
    whole failure mode: the positional scan returned whichever dep came first, and both of
    these are dicts with an `outputs` key.
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        del params
        backbone = self._value_of(req.input_ref("backbone"))
        sequences = self._value_of(req.input_ref("sequences"))
        # The mock producers emit bare strings as their output values: GenerateAgent and
        # NoodleAgent emit "backbone[n]", DesignAgent emits "SEQ". Checking which arrived
        # where is the whole job of this tool, so the strings are the assertion.
        ok = (isinstance(backbone, str) and backbone.startswith("backbone")
              and sequences == "SEQ")
        return {"result": "joined", "count": 1, "outputs": {"complex": "CPLX"},
                "metrics": {"wired_correctly": 1.0 if ok else 0.0,
                            "inputs_seen": float(len(req.inputs))}}

    @staticmethod
    def _value_of(ref: Any) -> Any:
        """An `ArtifactRef`, or its serialized form once it has crossed a process boundary."""
        if ref is None:
            return None
        if isinstance(ref, dict):
            return ref.get("value")
        return getattr(ref, "value", None)


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
