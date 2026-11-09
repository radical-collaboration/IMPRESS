"""Surrogate task agents for the small-molecule binding chain.

A laptop stand-in for `rfd3_design -> ligandmpnn_design -> packmin -> fastrelax ->
filter_shape -> boltz_predict`, with the science replaced by seeded random draws.

**What is faithful, and what is not.** The ports, patterns, parameters, metric names, QC
gates and acceptance thresholds are copied from the real specs, so a reading that clears
`complex_plddt >= 0.75` here cleared the same bar the real campaign measures against. What
produces the number is a hash of the parameters and the upstream metrics. These tools model
no chemistry and their outputs are not evidence about any molecule.

**Why `toolkit: mock` and not a toolkit of their own.** Gate 6 classifies a tool as mock by
`ToolSpec.toolkit == "mock"` exactly, so a surrogate in any other toolkit would be admitted
by a campaign declaring `tool_delivery: real` - a chain of random numbers reported as
science, which is the documented failure that gate exists to prevent.

**The draw propagates down the chain**, which is the point: a knob on the first stage has to
be able to change the last stage's verdict, or there is nothing to learn by turning it. Each
stage inherits from its IMMEDIATE upstream only, because that is all `TaskRequest.inputs`
carries - `exec/dispatch` wires a node to its direct dependencies and nothing further back.
So the quality signal is passed hand to hand rather than read from the top: `ss_fraction`
becomes a confidence, the confidence becomes an energy, the energy becomes a shape score,
and the shape score becomes a pLDDT. A chain that reached two stages back for a number it
could not see would silently freeze that number at its default, and every knob upstream of
it would stop mattering.

**Calibration.** The defaults pass every acceptance gate, so a first run succeeds and the
knobs have somewhere to move; `difficulty` on `mock_rfd3_design` is what takes that away.
`tests/test_mock_smb.py` pins both halves of that claim.
"""
from __future__ import annotations

import math
from typing import Any

from .agent import TaskAgent, TaskRequest
from .mock_agents import _rng, _upstream


def _inherit(inputs: dict[str, Any], metric: str, default: float) -> float:
    """One upstream metric, or `default` when no upstream reported it.

    Reads the metrics rather than the artifact because a surrogate has no artifact to read -
    the chain's state lives entirely in the numbers. Takes the LAST upstream that reported it
    so a chain reports its most recent estimate, which is what superseding means here.
    """
    value = default
    for _, v in sorted(inputs.items()):
        if isinstance(v, dict):
            metrics = v.get("metrics") or {}
            if metric in metrics:
                value = float(metrics[metric])
    return value


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _soft_cap(x: float, ceiling: float, knee: float) -> float:
    """Linear below `knee`, asymptotic to `ceiling` above it. Never reaches the ceiling.

    A hard clamp is what a bounded metric looks like from outside, and it made the
    surrogate's Pareto front degenerate. The refinement path escalates parameters on every
    other cycle, so an eight-cycle run came back with three front members carrying
    `shape_complementarity` 0.950 and `complex_plddt` 0.980 to the digit - a front that
    cannot be ordered by either of the two objectives the campaign cares most about, and a
    reader turning a knob at the top of its range watching nothing move. A real confidence
    metric approaches its ceiling; it does not arrive there and stop.
    """
    if x <= knee:
        return x
    span = ceiling - knee
    return ceiling - span * math.exp(-(x - knee) / span)


class MockRFD3DesignAgent(TaskAgent):
    """Backbone generation. `diffusion_steps` buys structure; `difficulty` takes it away."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id))
        steps = int(params.get("diffusion_steps", 50))
        n = int(params.get("num_designs", 1))
        difficulty = float(params.get("difficulty", 0.25))
        # 0.60 at the default 50 steps and 0.25 difficulty, which clears the 0.5 acceptance
        # bar with room; 200 steps reaches ~0.85. The slope on `difficulty` is set so that
        # 0.55 lands between the two bars (acceptance shortfall, trust untouched) and 0.85
        # lands under the 0.3 `has_secondary_structure` floor (integrity failure, trust
        # demoted). That separation is the whole point of the dial - see decision 0013.
        ss = _clamp(0.70 + 0.30 * (steps - 20) / 180.0 - 0.60 * difficulty
                    + r.uniform(-0.03, 0.03), 0.0, 0.98)
        helix = ss * r.uniform(0.5, 0.7)
        return {
            "result": "backbone", "count": n,
            "outputs": {"backbone": f"backbone[{n}]"},
            "metrics": {
                "ss_fraction": round(ss, 3),
                "num_models": float(n),
                "ca_deviation": round(_clamp(1.6 * (1.0 - ss) + r.uniform(-0.05, 0.10),
                                             0.0, 5.0), 3),
                "ligand_clashes": float(r.choices([0, 0, 0, 1, 2],
                                                  weights=[6, 4, 3, 2, 1])[0]),
                "helix_fraction": round(helix, 3),
                "sheet_fraction": round(max(0.0, ss - helix), 3),
            },
        }


class MockMPNNDesignAgent(TaskAgent):
    """Inverse folding. Low temperature recovers; a wider ensemble gives more to pick from."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        ss = _inherit(req.inputs, "ss_fraction", 0.5)
        temp = float(params.get("temperature", 0.2))
        ensemble = (int(params.get("batch_size", 8))
                    * int(params.get("number_of_batches", 1)))
        # Picking the best of N is worth something, with diminishing returns - the real tool
        # selects the best member of its own ensemble, so this is the shape that mirrors.
        pick = 0.06 * (ensemble ** 0.5 - 1.0)
        # The 0.80 on `ss` is the first of five gains chosen together rather than one at a
        # time, and the reason is in the module docstring: the chain is a product of slopes,
        # so a comfortable-looking coefficient at each stage multiplies out to a last stage
        # that barely moves. An earlier tuning had 0.55 here and 0.016 in the shape stage,
        # and `difficulty` 0.6 - which failed the FIRST stage outright - still left
        # `complex_plddt` at 0.81, comfortably over its bar. A surrogate whose last stage
        # cannot be moved from its first is a surrogate of nothing.
        base = 0.13 + 0.80 * ss - 0.40 * temp + pick
        overall = _clamp(_soft_cap(base + r.uniform(-0.015, 0.015), 0.99, 0.80), 0.0, 0.99)
        return {
            "result": "structure", "count": int(params.get("num_seqs", 1)),
            "outputs": {"structure": "complex"},
            "metrics": {
                "overall_confidence": round(overall, 3),
                "ligand_confidence": round(_clamp(overall - r.uniform(0.02, 0.10),
                                                  0.0, 0.99), 3),
                "ensemble_size": float(ensemble),
                "ensemble_paired": 1.0,
            },
        }


class MockPackMinAgent(TaskAgent):
    """Pack and minimise. Reports the pre-relax energy the next stage improves on.

    This is also the only place the chain's quality signal can live between MPNN and relax:
    `total_score` is the single metric this tool declares, so `MockFastRelaxAgent` recovers a
    confidence from it rather than reaching past its own input for one it cannot see.
    """

    #: `total_score = -(FLOOR + SPAN * confidence + 18 * (cycles - 1))`, inverted by
    #: `MockFastRelaxAgent._quality`. Named rather than written twice, because the two
    #: halves drifting apart would decouple the whole chain without failing anything.
    FLOOR = 150.0
    SPAN = 240.0

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        conf = _inherit(req.inputs, "overall_confidence", 0.5)
        cycles = int(params.get("cycles", 1))
        # The noise is +/-4 on a 240-wide span, so it perturbs the recovered confidence by
        # about 0.017. It is deliberately small for that reason: this stage's scatter is
        # multiplied by every gain below it, and at +/-20 it alone put the shape score's
        # spread across its own acceptance bar at the DEFAULTS.
        score = -(self.FLOOR + self.SPAN * conf + 18.0 * (cycles - 1)) + r.uniform(-4.0, 4.0)
        return {"result": "structure", "count": 1,
                "outputs": {"structure": "complex"},
                "metrics": {"total_score": round(score, 3)}}


class MockFastRelaxAgent(TaskAgent):
    """Relax. Where the campaign's binding objective is decided."""

    @staticmethod
    def _quality(pre: float) -> float:
        """Recover packmin's confidence from the energy it reported.

        packmin declares one metric, so the alternative was for this agent to read
        `overall_confidence` from two stages back - which `TaskRequest.inputs` does not
        carry, meaning it would silently take its default forever and `temperature` would
        stop reaching the binding objective.
        """
        return _clamp((-pre - MockPackMinAgent.FLOOR) / MockPackMinAgent.SPAN, 0.0, 1.0)

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        pre = _inherit(req.inputs, "total_score", -300.0)
        q = self._quality(pre)
        cycles = int(params.get("relax_cycles", 3))
        nstruct = int(params.get("nstruct", 1))
        gain = 1.0 + 0.04 * (cycles - 1) + 0.03 * (nstruct - 1)
        score = pre * gain + r.uniform(-8.0, 8.0)
        return {
            "result": "structure", "count": nstruct,
            "outputs": {"structure": "complex"},
            "metrics": {
                "total_score": round(score, 3),
                "fa_rep": round(_clamp(150.0 - 90.0 * q - 8.0 * (cycles - 1)
                                       - 5.0 * (nstruct - 1) + r.uniform(-6.0, 6.0),
                                       0.0, 600.0), 3),
                "interaction_energy": round(-(4.0 + 22.0 * q) - 0.5 * (cycles - 1)
                                            - 0.8 * (nstruct - 1) + r.uniform(-0.5, 0.5), 3),
            },
        }


class MockFilterShapeAgent(TaskAgent):
    """Interface shape complementarity, carrying the real 0.55 acceptance bar."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        ie = _inherit(req.inputs, "interaction_energy", -18.0)
        # -0.05 + 0.040 x energy: 0.71 at the defaults, crossing the 0.55 bar as the chain's
        # quality falls, and bending over rather than hitting 0.95 once the refinement path
        # has escalated a few times.
        sc = _clamp(_soft_cap(-0.05 + 0.040 * -ie + r.uniform(-0.015, 0.015), 0.95, 0.70),
                    0.0, 0.95)
        return {"result": "structure", "count": 1,
                "outputs": {"structure": "complex"},
                # 1.0 is the ligand-property selector, which is the mode every reading from
                # this chain would be taken in. Reported for the same reason the real tool
                # reports it: two campaigns' numbers are not comparable across modes.
                "metrics": {"shape_complementarity": round(sc, 3),
                            "sc_selector_mode": 1.0}}


class MockBoltzPredictAgent(TaskAgent):
    """Co-folding. The stage the campaign's `complex_plddt` bar sits on."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        sc = _inherit(req.inputs, "shape_complementarity", 0.65)
        samples = int(params.get("diffusion_samples", 8))
        pick = 0.05 * (samples ** 0.5 - 1.0)
        # 0.86 at the defaults against a 0.75 bar, crossing it at about `difficulty` 0.55 -
        # which is where the FIRST stage starts missing its own acceptance threshold, so the
        # two bars fail together rather than the chain's head failing alone.
        plddt = _clamp(_soft_cap(0.20 + 0.80 * sc + pick + r.uniform(-0.015, 0.015),
                                 0.98, 0.85), 0.0, 0.98)
        return {
            "result": "complex", "count": 1,
            "outputs": {"complex": "complex"},
            "metrics": {
                "complex_plddt": round(plddt, 3),
                "ligand_iptm": round(_clamp(plddt - r.uniform(0.0, 0.08), 0.0, 0.98), 3),
                "ensemble_size": float(samples),
                "ensemble_paired": 1.0,
            },
        }


__all__ = ["MockBoltzPredictAgent", "MockFastRelaxAgent", "MockFilterShapeAgent",
           "MockMPNNDesignAgent", "MockPackMinAgent", "MockRFD3DesignAgent"]
