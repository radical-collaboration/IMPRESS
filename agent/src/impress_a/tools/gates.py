"""Shared QC gate library.

Gates are referenced by id from specs so there are not fifty subtly different
implementations of the same check. Gates are ALWAYS deterministic code, even for
LLM-driven task agents: an LLM may author a protocol, it does not get to judge whether
the result passed its clash check.
"""
from __future__ import annotations

import importlib
import math
import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..core.qc import GateOutcome, GateResult, QCReport

if TYPE_CHECKING:
    from .spec import ToolSpec

GateFn = Callable[[dict[str, Any], dict[str, Any]], GateResult]
_REGISTRY: dict[str, GateFn] = {}

#: Path-separated dotted module names, imported once before any gate id is resolved. The
#: counterpart of `$IMPRESS_A_TOOLKITS`: that variable lets a site add a toolkit without
#: forking the package, and this one lets that toolkit's specs declare gates the package
#: does not ship. Both are read by `Registry.load()`.
GATE_MODULES_ENV = "IMPRESS_A_GATE_MODULES"


class GateModuleError(Exception):
    """A module named in `$IMPRESS_A_GATE_MODULES` could not be imported."""


def gate(name: str) -> Callable[[GateFn], GateFn]:
    def deco(fn: GateFn) -> GateFn:
        _REGISTRY[name] = fn
        return fn
    return deco


def load_modules(explicit: str | None = None) -> list[str]:
    """Import the gate-registering modules named by `$IMPRESS_A_GATE_MODULES`.

    `_REGISTRY` is filled by the `@gate` decorator at import time, so a gate defined outside
    this package exists only once its module has run - and nothing in `impress-a run` gave a
    caller the chance to make that happen. The consequence was not a missing gate but a
    missing *toolkit*: `Registry._load_toolkit` resolves every declared gate id before it
    registers anything and is all-or-nothing, so one unresolvable id disabled the whole
    toolkit, with one line in `reg.errors` and no refusal. This hook is that chance.

    **An unimportable module raises, where an unreadable `$IMPRESS_A_TOOLKITS` path is
    skipped, and the asymmetry is deliberate.** A missing directory on a search path is
    plausibly another site's entry in a shared profile; a dotted module name is something
    this run explicitly asked for, and the only alternative to failing here is the silent
    toolkit loss above. `Registry.load()` is otherwise non-fatal per toolkit - this is the
    one thing that stops it, because it is a fault in the environment rather than in a
    toolkit.

    Importing is idempotent through `sys.modules`, so repeated `Registry().load()` calls in
    one process re-run no module bodies and cannot double-register.
    """
    raw = os.environ.get(GATE_MODULES_ENV, "") if explicit is None else explicit
    names = [n.strip() for n in raw.split(os.pathsep) if n.strip()]
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:
            raise GateModuleError(
                f"${GATE_MODULES_ENV} names {name!r}, which could not be imported: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
    return names


def get(name: str) -> GateFn:
    if name not in _REGISTRY:
        raise KeyError(f"unknown QC gate {name!r}; known: {sorted(_REGISTRY)}; a gate "
                       f"registered outside impress_a must be named in ${GATE_MODULES_ENV}")
    return _REGISTRY[name]


def known() -> list[str]:
    return sorted(_REGISTRY)


def evaluate(spec: ToolSpec, out: dict[str, Any]) -> QCReport:
    """Run a spec's gates over one raw payload, stamping each result with its role.

    The one place a QCReport is built from a spec - `TaskAgent.post_process` and the
    fixture tests both call this, so the fixtures test exactly what runs.

    **A label that two gates would share gets its role appended.** Decision 0013's whole
    point is that one metric can carry two gates with different roles and different bounds -
    `total_score <= 0.0` means the relax diverged, `total_score <= -250` means the design
    fell short - and `metric_in_range` labels itself by metric alone, so both results came
    back as `metric_in_range[total_score]`. A `QCReport`'s gates are read as a set in several
    places, so the two collapsed into one and a report could not say which had fired:
    "the tool broke" and "the design is weak" became the same sentence. Suffixed only on
    collision, so no existing label changes.
    """
    qc = QCReport()
    results = [get(g.id)(out, g.params).model_copy(update={"role": g.role})
               for g in spec.qc_gates]
    seen: dict[str, int] = {}
    for r in results:
        seen[r.gate] = seen.get(r.gate, 0) + 1
    for r in results:
        qc.add(r.model_copy(update={"gate": f"{r.gate} ({r.role})"})
               if seen[r.gate] > 1 else r)
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


# ---------------------------------------------------------------------------
# Item 15's six, moved in from `asteer.impress.gates` on 2026-11-21 (episode H6).
#
# They were registered from OUTSIDE this package until now, through
# `$IMPRESS_A_GATE_MODULES` -- a hook item 39 put here for exactly that, and which these
# six were the only user of. Registering from outside worked and was opt-in, so a stock
# `impress-a run` that forgot the variable lost the whole toolkit declaring them, silently.
# As built-ins there is nothing to forget.
#
# **None of them imports `asteer`**, which is why they could come in here rather than into an
# adapter module. Each reads the task's reported output dict and nothing else. The one piece
# that does need `asteer` -- `check_from_pipeline`, which walks a built pipeline input to
# PRODUCE the two counts `conditioning_applied` reads -- stayed behind in
# `asteer.conditioning`, beside the arithmetic it wraps and where the tool adapters' own
# docstrings already name it. A gate that reads two numbers and a helper that computes them
# are different jobs on different sides of the task boundary.
#
# **Five of the six are integrity and one is acceptance, and that is decision 0013 rather
# than caution.** Only integrity failures demote a pattern in the trust ledger. Each of the
# five catches *the tool or the pipeline broke*; `calibration_in_range` is the acceptance one,
# because a sigma outside its range is a model that needs retraining rather than a run that
# went wrong. Roles are declared per `qc_gates` entry in a spec, not here -- `evaluate` stamps
# `role` from the spec -- so a gate's default matters only when a spec omits it.
# ---------------------------------------------------------------------------

#: The six item 15 added, which arrived here on 2026-11-21 from `asteer.impress.gates`.
#: Exported so a test can assert the set rather than discovering it.
ASD_GATE_IDS = (
    "ligand_present_in_complex",
    "chain_break",
    "contig_length",
    "surrogate_version_present",
    "calibration_in_range",
    "conditioning_applied",
)


def _result(name: str, ok: bool, *, observed: Any = None, threshold: Any = None,
            detail: str = "") -> GateResult:
    return GateResult(
        gate=name,
        outcome=GateOutcome.PASS if ok else GateOutcome.FAIL,
        observed=observed, threshold=threshold, detail=detail if not ok else "",
    )


@gate("ligand_present_in_complex")
def _ligand_present_in_complex(out: dict, p: dict) -> GateResult:
    """Did the ligand survive into the predicted complex? (integrity)

    The failure this catches is documented upstream and was papered over once: Boltz run with
    no ligand chain reported `ligand_iptm` as 0.0 rather than omitting it. A complex with no
    ligand is not a weak binder, it is a prediction of the wrong system — so every downstream
    number describes something nobody asked about, and an acceptance threshold on
    `ligand_iptm` would call it a bad design.

    Reads the metric a tool reports rather than parsing a structure: a gate that parsed a
    `.cif` would need a structure library in the driver (CON-4), and the tools that know
    whether the ligand is there already report it.
    """
    key = p.get("key", "n_ligand_atoms")
    metrics = out.get("metrics") or {}
    value = metrics.get(key)
    present = isinstance(value, (int, float)) and math.isfinite(value) and value > 0
    return _result(
        "ligand_present_in_complex", present, observed=value, threshold=f"{key} > 0",
        detail=(f"{key} is {value!r}: the ligand did not survive into the complex, so every "
                "other metric on this node describes a different system"),
    )


@gate("chain_break")
def _chain_break(out: dict, p: dict) -> GateResult:
    """No backbone discontinuity. (integrity)

    `max_ca_gap_angstrom` above ~4.5 Å is a break rather than a strained bond: consecutive Cα
    atoms sit at 3.8 Å. A broken backbone scores well on anything that averages over residues,
    which is why this is structural rather than a threshold on a score.
    """
    limit = float(p.get("max_ca_gap_angstrom", 4.5))
    metrics = out.get("metrics") or {}
    gap = metrics.get("max_ca_gap_angstrom")
    if not isinstance(gap, (int, float)) or not math.isfinite(gap):
        # Not reported is not the same as fine. `metrics_reported` is the gate that says a
        # metric is missing; this one declines to guess, and says so.
        return _result("chain_break", False, observed=gap, threshold=f"<= {limit}",
                       detail="max_ca_gap_angstrom was not reported, so continuity is unknown; "
                              "declare metrics_reported beside this gate")
    return _result("chain_break", gap <= limit, observed=gap, threshold=f"<= {limit}",
                   detail=f"backbone gap {gap} A exceeds {limit} A: the chain is broken")


@gate("contig_length")
def _contig_length(out: dict, p: dict) -> GateResult:
    """The design matches the requested contig. (integrity)

    A generator that silently returned a different length has not produced the thing the
    campaign asked for, and length is the one property every downstream stage assumes without
    checking. `tolerance` defaults to 0 because a contig is a request, not a preference.
    """
    requested = p.get("requested")
    tolerance = int(p.get("tolerance", 0))
    metrics = out.get("metrics") or {}
    actual = metrics.get(p.get("key", "contig_length"))
    if requested is None:
        return _result("contig_length", False, observed=actual,
                       detail="no `requested` length in the gate's params: this gate cannot "
                              "check a request nobody declared")
    if not isinstance(actual, (int, float)):
        return _result("contig_length", False, observed=actual, threshold=requested,
                       detail="contig_length was not reported")
    ok = abs(float(actual) - float(requested)) <= tolerance
    return _result("contig_length", ok, observed=actual, threshold=f"{requested} ± {tolerance}",
                   detail=f"designed {actual} residues, campaign asked for {requested}")


@gate("surrogate_version_present")
def _surrogate_version_present(out: dict, p: dict) -> GateResult:
    """Every surrogate score carries its model id and version. (integrity, CON-5)

    **Integrity-role deliberately**, and the reasoning is the sharpest in this file: per decision
    0013 only integrity failures demote a pattern, so an unattributed score cannot quietly
    accumulate trust. A score with no model version is not a weak result — it is a result nobody
    can attribute, and attribution is this project's central claim. Treating it as acceptance
    would let a chain build trust on numbers whose provenance is gone.

    The stream is where CON-5 is *sourced* (every `SurrogateResponse` carries `(model_id,
    version)` by construction); this gate only enforces what the stream already states, which is
    why it checks the reported payload rather than reaching for a registry.
    """
    keys = list(p.get("metrics", []))
    metrics = out.get("metrics") or {}
    versions = out.get("model_versions") or {}
    scored = [k for k in keys if k in metrics]
    unattributed = [k for k in scored if not str(versions.get(k) or "").strip()]
    return _result(
        "surrogate_version_present", not unattributed,
        observed=sorted(set(scored) - set(unattributed)), threshold=keys,
        detail=(f"no (model_id, version) for {unattributed}: an unattributed score must not "
                "accumulate trust, which is why this is integrity-role"),
    )


@gate("calibration_in_range")
def _calibration_in_range(out: dict, p: dict) -> GateResult:
    """Model C's σ is neither collapsed nor unbounded. (acceptance)

    **The one acceptance gate here**, and the role is the whole point: a σ outside its range
    means the model needs recalibrating, not that the run broke. Collapsed σ is the dangerous
    direction — item 14 ranks on the lower confidence bound of C's ΔG, so a σ of ~0 turns an
    LCB into a posterior mean and the ranking silently stops accounting for uncertainty. With
    10–20 ATM labels *recalibrating* a GP rather than fitting it, an over-confident model is
    more damaging than an uncertain one.
    """
    key = p.get("metric", "sigma_dg")
    low = float(p.get("min", 0.1))
    high = float(p.get("max", 5.0))
    metrics = out.get("metrics") or {}
    sigma = metrics.get(key)
    if not isinstance(sigma, (int, float)) or not math.isfinite(sigma):
        return _result("calibration_in_range", False, observed=sigma,
                       threshold=f"{low} <= {key} <= {high}",
                       detail=f"{key} was not reported, so calibration is unknown")
    ok = low <= float(sigma) <= high
    return _result(
        "calibration_in_range", ok, observed=sigma, threshold=f"{low} <= {key} <= {high}",
        detail=(f"{key}={sigma} is {'collapsed' if sigma < low else 'unbounded'}: "
                "a collapsed sigma turns item 14's lower confidence bound into a mean"),
    )


@gate("conditioning_applied")
def _conditioning_applied(out: dict, p: dict) -> GateResult:
    """A design that requested conditioning was conditioned on something. (integrity, item 29)

    M0 measured the failure this exists for (job `24155612`): RFD3 resolves a ligand
    `select_hotspots`, `build()` drops the annotation, `constants.py:19` supplies zeros, and
    **the design completes and reports success** conditioned on nothing. Item 26 answers that
    instance in the `rfd3` wrapper; this gate answers the class, for any tool and any channel.

    It reads two reported counts rather than re-deriving them, because the derivation needs the
    pipeline input and that lives inside the task. `asteer.conditioning` is the shared
    implementation the tool uses to produce them — one measurement, not two — and its rule is
    the narrow one: only a per-entry numeric array counts, never the request echoed back.
    """
    metrics = out.get("metrics") or {}
    requested = metrics.get(p.get("requested_key", "conditioning_requested"))
    applied = metrics.get(p.get("applied_key", "conditioning_applied"))

    if not isinstance(requested, (int, float)):
        # A tool that declares this gate and reports no counts has not been wired to
        # `asteer.conditioning`. Failing closed: the alternative reads as "nothing was asked
        # for", which is precisely the silent success the gate exists to catch.
        return _result("conditioning_applied", False, observed=requested,
                       detail="conditioning_requested was not reported: a tool declaring this "
                              "gate must emit the counts asteer.conditioning produces")
    if requested <= 0:
        # Nothing was asked for, so nothing was dropped. This is the unsteered control arm, and
        # it must pass -- a control that failed QC would make the comparison unreadable.
        return _result("conditioning_applied", True, observed=0,
                       threshold="no conditioning requested")
    ok = isinstance(applied, (int, float)) and applied > 0
    return _result(
        "conditioning_applied", ok, observed=applied, threshold=f"> 0 of {requested} requested",
        detail=(f"{requested} conditioning entries were requested and {applied!r} reached the "
                "model: the run completed conditioned on nothing, which it will report as "
                "success (backlog item 26)"),
    )
