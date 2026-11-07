"""The reasoner models, as data.

The letter -> class mapping lived in `cli/__init__.py` as a bare dict, so the taxonomy the
whole design rests on - four interchangeable reasoners over one engine - was a CLI detail.
Anything not going through the CLI re-derived it: the control plane by duck-typing for
`steer`, `slides/api/run_model.py` by importing the CLI's dict, a reader by grepping.

So this module holds it instead, and holds what the dict could not express: which mode a
model runs in, how many LLM calls it makes, whether it is actually finished, and what is
wrong with it if not. `impress-a models` prints the table, which is the mechanism that
keeps the status column honest - a claim nobody can see goes stale quietly.

`cli.POLICIES` is now derived from here, so there is one list and not two.

Two constraints on what may live in this file:

* **`policy` may import `core` only** (ADR 0010, asserted by `tests/test_layering.py`).
  `CampaignSpec` is in `runtime/`, so a builder cannot take one. `ReasonerOptions` below
  is the plain-data stand-in, and `cli.build_policy` is the adapter between them. If a
  builder ever needs something only the spec has, the answer is another field here, not an
  import.
* **The imports below are eager, deliberately unchanged.** Importing `agentic` costs
  langgraph, which is why `impress-a tools` pays for a graph library it never uses
  (`slides/api/DECK_SCRIPT.md:556` records the open ask). That cost moved here from the
  CLI rather than growing: this is now the one place to make it lazy if that ask is
  actioned, and doing it by storing a dotted path per model would work.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .agentic import FourNodePolicy
from .explicit import ReplayPolicy, ThresholdPolicy
from .external import ExternalPolicy
from .oracle import OraclePolicy
from .planners import (
    AgenticPlanner,
    ExternalPlanner,
    ReplayPlanner,
    ThresholdPlanner,
)
from .specifiers import (
    AgenticSpecifier,
    ExternalSpecifier,
    ReplaySpecifier,
    ThresholdSpecifier,
)
from .wrappers import NullPlanner, NullPolicy, NullSpecifier


@dataclass(frozen=True)
class ReasonerOptions:
    """Everything a builder may need, and nothing a builder must not see.

    Not `CampaignSpec`: see the import contract note in the module docstring. Every field
    is optional because most models use two or three of them; a builder reads what it
    needs and ignores the rest.
    """

    #: The campaign's own chain. Without it every model falls back to its built-in
    #: default, which is the MOCK chain - so a campaign naming real toolkits would load
    #: them, validate them, and then execute mocks.
    stages: list[str] | None = None
    #: Model C only: how long `decide` blocks on the control plane, and what it does when
    #: nothing arrives. `hold | fallback | stop`.
    timeout_s: float = 5.0
    on_timeout: str = "fallback"
    #: Models A and D.
    max_cycles: int = 6
    target_front: int = 3
    #: Model D's replay variant. There is no default that makes sense: a replay with no
    #: records is not a degraded replay, it is a different campaign.
    records: list[dict[str, Any]] | None = None
    #: The replay HALVES read two executor-written records instead of the one each model used
    #: to write for itself: `specs.jsonl` and `stages.jsonl`. Kept separate from `records`
    #: because they are different files and because `--specifier replay --planner X` is the
    #: one experiment that isolates the planning half with no new allocation, so one half
    #: must be loadable without the other.
    spec_records: list[dict[str, Any]] | None = None
    stage_records: list[dict[str, Any]] | None = None
    #: Model A's per-node reasoner, when one exists. Unwired today - see `agentic.py`.
    reasoner: Any = None
    #: Model B's `DecisionModel`. `None` selects `RehearsalOracle`, the deterministic
    #: network-free stand-in, which is what `--model B` runs today.
    oracle: Any = None
    #: Provenance sink, passed through to whichever models record their own reasoning.
    sink: Any = None
    #: The degraded-mode policy for B and C. A model-D instance; built by the caller
    #: because it needs `stages` too.
    fallback: Any = None


@dataclass(frozen=True)
class ReasonerModel:
    """One control model, described well enough to print and to check."""

    letter: str
    name: str
    #: `autonomous` or `headless`. Not orthogonal to the letter - decision 0002 ruled that
    #: model C *is* the headless mode rather than a mode any model can run in.
    mode: str
    #: LLM calls per decision cycle, as implemented TODAY. The specification's targets are
    #: A ~3 and B 1 (`planning/phase1-partB-architecture/02-control-models.md` sections 2
    #: and 3); both are 0 here, and that gap is the point of recording this field.
    llm_calls: int
    #: What the specification asks for: `none | per-node | single-call | external`.
    llm_shape: str
    #: `implemented | partial | stub`. Asserted against the class in
    #: `tests/test_reasoner_registry.py` - a model claiming `implemented` whose `decide` is
    #: still `BasePolicy`'s `NotImplementedError` fails the suite.
    status: str
    cls: type
    build: Callable[[ReasonerOptions], Any]
    #: The two halves. `None` means "derive them from `build`", which is what every model
    #: does while the strangler is in place: `DecideAsRoles` presents a `ControlPolicy` as a
    #: Specifier/Planner pair, so `--model X --control roles` runs the same decisions through
    #: the role pipeline. Phase 9 fills these in per model, and the pair stops being derived.
    specifier: Callable[[ReasonerOptions], Any] | None = None
    planner: Callable[[ReasonerOptions], Any] | None = None
    #: Why the status is not `implemented`, or what is true of this model that a reader
    #: would otherwise have to learn from a backlog item. Printed by `impress-a models`.
    note: str = ""
    #: Where the model is specified. `planning/` is process history rather than reference
    #: (`CLAUDE.md`), but for the control models it is still the only full treatment, so
    #: pointing at it beats pointing at nothing.
    spec_ref: str = ""


def _threshold(o: ReasonerOptions) -> ThresholdPolicy:
    """Model D, and the fallback every other model degrades into."""
    return ThresholdPolicy(stages=o.stages, max_cycles=o.max_cycles,
                           target_front=o.target_front)


def _spec_d(o: ReasonerOptions) -> ThresholdSpecifier:
    """Model D's real Specifier half.

    Takes nothing from the options: a deterministic `Goal -> Spec` is a function of the Goal
    and of what the Toolkit can produce, both of which arrive at call time. That is what makes
    D reproducible end to end, and so the baseline the other three justify their cost against.
    """
    return ThresholdSpecifier()


def _plan_d(o: ReasonerOptions) -> ThresholdPlanner:
    """Model D's real Planner half.

    Takes the campaign's chain for the same reason `_threshold` does: without it the planner
    falls back to whatever the Toolkit happens to hold, and on a real campaign that is the mock
    toolkit sitting beside the real one.
    """
    return ThresholdPlanner(stages=o.stages)


def _spec_a(o: ReasonerOptions) -> AgenticSpecifier:
    """Model A's Specifier half: nodes 1 and 4 of the four-node loop.

    `o.reasoner` is finally read. It was stored and never used (backlog H1), so the slot for a
    model was decoration and `--model A` was a LangGraph-shaped rule cascade; with a reasoner
    attached each node is a bounded schema-checked call that falls back to that cascade and
    records the transition.
    """
    return AgenticSpecifier(reasoner=o.reasoner, sink=o.sink)


def _plan_a(o: ReasonerOptions) -> AgenticPlanner:
    """Model A's Planner half: node 2, as `select_tasks -> parameterize`."""
    return AgenticPlanner(stages=o.stages, reasoner=o.reasoner, sink=o.sink)


def _spec_c(o: ReasonerOptions) -> ExternalSpecifier:
    """Model C's Specifier half: one of the two role inboxes."""
    return ExternalSpecifier(timeout_s=o.timeout_s, sink=o.sink)


def _plan_c(o: ReasonerOptions) -> ExternalPlanner:
    """Model C's Planner half, and the one where `on_timeout` is a safety question.

    The fallback is only built when it will be used. `ExternalPlanner` refuses
    `on_timeout="fallback"` with none, and passing one under `stop` would put a model-D
    planner in the object graph of an arm whose whole claim is that it never runs one.
    """
    fallback = (o.fallback or _plan_d(o)) if o.on_timeout == "fallback" else None
    return ExternalPlanner(stages=o.stages, timeout_s=o.timeout_s,
                           on_timeout=o.on_timeout, fallback=fallback, sink=o.sink)


def _spec_replay(o: ReasonerOptions) -> ReplaySpecifier:
    return ReplaySpecifier(o.spec_records if o.spec_records is not None else o.records)


def _plan_replay(o: ReasonerOptions) -> ReplayPlanner:
    return ReplayPlanner(o.stage_records if o.stage_records is not None else o.records)


def _build_a(o: ReasonerOptions) -> FourNodePolicy:
    return FourNodePolicy(stages=o.stages, max_cycles=o.max_cycles,
                          target_front=o.target_front, reasoner=o.reasoner,
                          sink=o.sink)


def _build_b(o: ReasonerOptions) -> OraclePolicy:
    # A declared fallback is mandatory for the oracle: an API outage must degrade
    # explicitly, never stall a multi-GPU allocation (Part A risk R7). Built here rather
    # than defaulted inside `OraclePolicy` so it carries the campaign's own chain.
    return OraclePolicy(model=o.oracle, fallback=o.fallback or _threshold(o),
                        sink=o.sink)


def _build_c(o: ReasonerOptions) -> ExternalPolicy:
    return ExternalPolicy(timeout_s=o.timeout_s, on_timeout=o.on_timeout,
                          fallback=o.fallback or _threshold(o), sink=o.sink)


def _build_replay(o: ReasonerOptions) -> ReplayPolicy:
    # Refuse rather than raise `TypeError` from a positional argument nobody passed.
    # `build_policy` used to call `cls()` for anything that was not A/B/C/D, so
    # `--model replay` died before the campaign started, with a traceback that named
    # `records` and not the missing flag.
    if o.records is None:
        raise ValueError(
            "replay needs a recorded decision sequence: pass --replay-from <provenance "
            "dir>. A replay with no records is a different campaign, not a degraded one")
    return ReplayPolicy(o.records)


MODELS: dict[str, ReasonerModel] = {
    "A": ReasonerModel(
        letter="A", name="four-node agentic loop", mode="autonomous",
        llm_calls=0, llm_shape="per-node", status="partial",
        cls=FourNodePolicy, build=_build_a,
        specifier=_spec_a, planner=_plan_a,
        note="FOUR nodes now, two per half - `hypothesize`/`analyze` on the Specifier and "
             "`select_tasks`/`parameterize` on the Planner - and the `reasoner` seam is "
             "read: each node is a bounded schema-checked call with corrective retry that "
             "falls back to its rule cascade and records a `reasoner_degraded` transition. "
             "Still `llm_calls: 0` under `--model A`, because nothing attaches a client yet; "
             "with none attached the cascades run, and A then differs from D in two named "
             "ways (it retires an unmeasurable objective, and it moves the diversity knobs)",
        spec_ref="planning/phase1-partB-architecture/02-control-models.md section 2"),
    "B": ReasonerModel(
        letter="B", name="heavyweight LLM oracle", mode="autonomous",
        llm_calls=0, llm_shape="single-call", status="partial",
        cls=OraclePolicy, build=_build_b,
        note="the policy, prompt, bounded retry and logged degraded transition are "
             "complete; no live client is constructed, so `--model B` runs "
             "`RehearsalOracle`, the deterministic stand-in",
        spec_ref="planning/phase1-partB-architecture/02-control-models.md section 3"),
    "C": ReasonerModel(
        letter="C", name="external caller steering", mode="headless",
        llm_calls=0, llm_shape="external", status="implemented",
        cls=ExternalPolicy, build=_build_c,
        specifier=_spec_c, planner=_plan_c,
        note="two role inboxes, routed by a `role` key inside the directive `steer` already "
             "carries, so one headless mode stays one mode (decision 0002) and no plane "
             "operation is added (ADR 0007). A caller may add and delete objectives but may "
             "NOT declare one satisfied, and the planner half defaults to `on_timeout='stop'` "
             "- a fallback is what makes a C arm that silently became a D arm possible. "
             "`impress-a run --model C` is refused outright rather than timing out (C6)",
        spec_ref="docs/decisions/0002-model-c-is-control-mode-2.md"),
    "D": ReasonerModel(
        letter="D", name="explicit policy", mode="autonomous",
        llm_calls=0, llm_shape="none", status="implemented",
        cls=ThresholdPolicy, build=_threshold,
        specifier=_spec_d, planner=_plan_d,
        note="the scientific control: reproducible end to end, and the baseline the other "
             "models must justify their cost against. `ThresholdSpecifier` maps the Goal onto "
             "the Toolkit's output space; `ThresholdPlanner` selects Tasks by output type and "
             "varies their real parameters, stepping the quality knobs a quarter of their "
             "declared headroom per refinement and leaving breadth and seed alone (backlog "
             "H3). The bandit, Bayesian-optimization and evolutionary variants the "
             "specification lists do not exist",
        spec_ref="planning/phase1-partB-architecture/02-control-models.md section 5"),
    "null": ReasonerModel(
        letter="null", name="no-op baseline", mode="autonomous",
        llm_calls=0, llm_shape="none", status="implemented",
        cls=NullPolicy, build=lambda o: NullPolicy(),
        specifier=lambda o: NullSpecifier(), planner=lambda o: NullPlanner(),
        note="stops immediately; a control and a smoke test. The halves need no special "
             "case anywhere: an empty Spec makes `complete()` true, so the Listener stops "
             "the campaign through the designed path. A fifth shipped decider "
             "outside the four-model taxonomy, which is why 'exactly one of four' and "
             "`--model`'s choices do not agree"),
    "replay": ReasonerModel(
        letter="replay", name="replay a recorded campaign", mode="autonomous",
        llm_calls=0, llm_shape="none", status="partial",
        cls=ReplayPolicy, build=_build_replay,
        specifier=_spec_replay, planner=_plan_replay,
        note="provenance as an executable artifact, and the halves are strictly better than "
             "the policy: `specs.jsonl` and `stages.jsonl` are EXECUTOR-written, so the "
             "record exists for every model whether or not it keeps notes and a reasoner "
             "cannot write a flattering one. Needs `--replay-from`. Diverges loudly rather "
             "than improvising: a recorded Stage refused where the original was admitted "
             "means the campaign differs from the one recorded",
        spec_ref="planning/phase1-partB-architecture/02-control-models.md section 5"),
}

#: The shape `cli.POLICIES` had, derived rather than restated.
CLASSES: dict[str, type] = {k: m.cls for k, m in MODELS.items()}


def build(letter: str, options: ReasonerOptions | None = None) -> Any:
    """Construct one reasoner. Raises `KeyError` with the known letters on a bad one."""
    if letter not in MODELS:
        raise KeyError(f"unknown control model {letter!r}; known: {sorted(MODELS)}")
    return MODELS[letter].build(options or ReasonerOptions())


class RolePair:
    """A Specifier half and a Planner half, which may come from different models.

    `--model X` takes both halves from one row, which keeps the four-arm comparison
    one-variable. `--specifier X --planner Y` takes one from each, which is what makes it
    measurable whether specification or planning is where a model earns its cost. The second
    form is reachable from the first day rather than retrofitted, because a pair that can only
    ever come from one row is not two interfaces - it is one with a seam drawn on it.
    """

    def __init__(self, specifier: Any, planner: Any, label: str = "") -> None:
        self.specifier = specifier
        self.planner = planner
        self.name = label or f"{getattr(specifier, 'name', '?')}+{getattr(planner, 'name', '?')}"

    def steer(self, directive: dict[str, Any]) -> None:
        """Route one external directive to the half it is addressed to.

        The `role` key lives inside the dict `steer` already carries, so decision 0002's one
        headless mode stays one mode and ADR 0007 is untouched - a `steer_specifier` operation
        would have to be added to the core protocol and rendered by every adapter to express
        what one field expresses. A directive with no `role` goes to the planner, which is
        what every existing caller sends.

        Raises `ValueError` when the addressed half has no inbox. The control plane turns that
        into a refusal with its reason; silently dropping it would tell a caller its directive
        was accepted, and an external arm whose directives went nowhere is indistinguishable
        from one steering a campaign badly.
        """
        role = str(directive.get("role") or "planner").strip().lower()
        if role not in ("specifier", "planner"):
            raise ValueError(f"unknown role {role!r}; expected 'specifier' or 'planner'")
        target = self.specifier if role == "specifier" else self.planner
        if not hasattr(target, "steer"):
            raise ValueError(
                f"this campaign's {role} half ({getattr(target, 'name', '?')}) takes no "
                f"external directives")
        target.steer(directive)


def _half(letter: str, which: str, options: ReasonerOptions) -> Any:
    """One half of one model, derived from `build` while the strangler is in place."""
    if letter not in MODELS:
        raise KeyError(f"unknown control model {letter!r}; known: {sorted(MODELS)}")
    model = MODELS[letter]
    explicit = model.specifier if which == "specifier" else model.planner
    if explicit is not None:
        return explicit(options)
    from .legacy import DecideAsRoles
    pair = DecideAsRoles(model.build(options))
    return pair.specifier if which == "specifier" else pair.planner


def build_roles(spec_letter: str, plan_letter: str | None = None,
                options: ReasonerOptions | None = None) -> RolePair:
    """Build a Specifier/Planner pair. One letter means both halves from that model."""
    o = options or ReasonerOptions()
    plan_letter = plan_letter or spec_letter
    label = spec_letter if plan_letter == spec_letter else f"{spec_letter}/{plan_letter}"
    return RolePair(_half(spec_letter, "specifier", o),
                    _half(plan_letter, "planner", o), label=label)


def table() -> list[tuple[str, ...]]:
    """Rows for `impress-a models`, header first."""
    rows = [("model", "name", "mode", "llm", "calls", "status")]
    for letter in sorted(MODELS):
        m = MODELS[letter]
        rows.append((m.letter, m.name, m.mode, m.llm_shape, str(m.llm_calls), m.status))
    return rows
