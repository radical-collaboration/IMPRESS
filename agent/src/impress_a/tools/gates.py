"""Shared QC gate library.

Gates are referenced by id from specs so there are not fifty subtly different
implementations of the same check. Gates are ALWAYS deterministic code, even for
LLM-driven task agents: an LLM may author a protocol, it does not get to judge whether
the result passed its clash check.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable

from ..core.qc import GateOutcome, GateResult, QCReport

if TYPE_CHECKING:
    from .spec import ToolSpec

GateFn = Callable[[dict[str, Any], dict[str, Any]], GateResult]
_REGISTRY: dict[str, GateFn] = {}


def gate(name: str) -> Callable[[GateFn], GateFn]:
    def deco(fn: GateFn) -> GateFn:
        _REGISTRY[name] = fn
        return fn
    return deco


def get(name: str) -> GateFn:
    if name not in _REGISTRY:
        raise KeyError(f"unknown QC gate {name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def known() -> list[str]:
    return sorted(_REGISTRY)


def evaluate(spec: ToolSpec, out: dict[str, Any]) -> QCReport:
    """Run a spec's gates over one raw payload, stamping each result with its role.

    The one place a QCReport is built from a spec - `TaskAgent.post_process` and the
    fixture tests both call this, so the fixtures test exactly what runs.
    """
    qc = QCReport()
    for g in spec.qc_gates:
        qc.add(get(g.id)(out, g.params).model_copy(update={"role": g.role}))
    return qc


@gate("output_present")
def _output_present(out: dict, p: dict) -> GateResult:
    key = p.get("key", "result")
    ok = out.get(key) is not None
    return GateResult(gate="output_present", outcome=GateOutcome.PASS if ok else GateOutcome.FAIL,
                      observed=key, detail="" if ok else f"missing output {key!r}")


@gate("count_matches_request")
def _count_matches(out: dict, p: dict) -> GateResult:
    want, got = p.get("expected"), out.get("count")
    ok = want is None or got == want
    return GateResult(gate="count_matches_request",
                      outcome=GateOutcome.PASS if ok else GateOutcome.FAIL,
                      observed=got, threshold=want,
                      detail="" if ok else f"produced {got}, requested {want}")


@gate("metrics_reported")
def _metrics_reported(out: dict, p: dict) -> GateResult:
    """Each named metric was actually reported, as a finite number.

    The integrity half of every acceptance threshold. An adapter that could not read a
    value must omit it rather than report 0.0 - and then this gate, not the threshold,
    is what catches it. Both real cases were exactly that: Boltz run with no ligand chain
    (`ligand_iptm` absent, once papered over as 0.0) and an unparsed LigandMPNN header.
    """
    names = list(p.get("metrics", []))
    metrics = out.get("metrics") or {}
    missing = [n for n in names
               if not isinstance(metrics.get(n), (int, float))
               or not math.isfinite(metrics[n])]
    return GateResult(gate="metrics_reported",
                      outcome=GateOutcome.FAIL if missing else GateOutcome.PASS,
                      observed=sorted(set(names) - set(missing)), threshold=names,
                      detail=f"not reported: {missing}" if missing else "")


@gate("metric_in_range")
def _metric_in_range(out: dict, p: dict) -> GateResult:
    name = p["metric"]
    v = (out.get("metrics") or {}).get(name)
    lo, hi = p.get("min"), p.get("max")
    ok = v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)
    return GateResult(gate=f"metric_in_range[{name}]",
                      outcome=GateOutcome.PASS if ok else GateOutcome.FAIL,
                      # A list, not a tuple: JSON has no tuple, so a round-tripped
                      # report would otherwise never compare equal to the original -
                      # and these reports now travel to a reasoner in another process.
                      observed=v, threshold=[lo, hi],
                      detail="" if ok else f"{name}={v} outside [{lo},{hi}]")


@gate("has_secondary_structure")
def _has_ss(out: dict, p: dict) -> GateResult:
    """Catches the classic silent 'designed a noodle' failure."""
    frac = (out.get("metrics") or {}).get("ss_fraction")
    lo = p.get("min_ss_fraction", 0.3)
    ok = frac is not None and frac >= lo
    return GateResult(gate="has_secondary_structure",
                      outcome=GateOutcome.PASS if ok else GateOutcome.FAIL,
                      observed=frac, threshold=lo,
                      detail="" if ok else f"ss_fraction={frac} < {lo} (likely disordered)")
