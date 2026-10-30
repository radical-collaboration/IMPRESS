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

from dataclasses import dataclass
from typing import Any, Callable

from .agentic import FourNodePolicy
from .explicit import ReplayPolicy, ThresholdPolicy
from .external import ExternalPolicy
from .oracle import OraclePolicy
from .wrappers import NullPolicy


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
        note="the LangGraph loop runs, but its nodes are deterministic rule cascades and "
             "the `reasoner` seam is unwired, so model A is bit-exact today and "
             "behaviourally a sibling of D",
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
        note="the policy is complete and covered end to end over HTTP, but nothing "
             "attaches a control plane under `impress-a run`, so from the CLI it times "
             "out and silently runs D (backlog C6, blocked on C5's entry points)",
        spec_ref="docs/decisions/0002-model-c-is-control-mode-2.md"),
    "D": ReasonerModel(
        letter="D", name="explicit policy", mode="autonomous",
        llm_calls=0, llm_shape="none", status="implemented",
        cls=ThresholdPolicy, build=_threshold,
        note="the scientific control: reproducible end to end, and the baseline the other "
             "models must justify their cost against. The bandit, Bayesian-optimization "
             "and evolutionary variants the specification lists do not exist",
        spec_ref="planning/phase1-partB-architecture/02-control-models.md section 5"),
    "null": ReasonerModel(
        letter="null", name="no-op baseline", mode="autonomous",
        llm_calls=0, llm_shape="none", status="implemented",
        cls=NullPolicy, build=lambda o: NullPolicy(),
        note="stops immediately; a control and a smoke test. A fifth shipped decider "
             "outside the four-model taxonomy, which is why 'exactly one of four' and "
             "`--model`'s choices do not agree"),
    "replay": ReasonerModel(
        letter="replay", name="replay a recorded campaign", mode="autonomous",
        llm_calls=0, llm_shape="none", status="partial",
        cls=ReplayPolicy, build=_build_replay,
        note="a model-D variant that turns a provenance log into an executable artifact. "
             "Needs `--replay-from`; nothing loads records yet, and no test constructs it",
        spec_ref="planning/phase1-partB-architecture/02-control-models.md section 5"),
}

#: The shape `cli.POLICIES` had, derived rather than restated.
CLASSES: dict[str, type] = {k: m.cls for k, m in MODELS.items()}


def build(letter: str, options: ReasonerOptions | None = None) -> Any:
    """Construct one reasoner. Raises `KeyError` with the known letters on a bad one."""
    if letter not in MODELS:
        raise KeyError(f"unknown control model {letter!r}; known: {sorted(MODELS)}")
    return MODELS[letter].build(options or ReasonerOptions())


def table() -> list[tuple[str, ...]]:
    """Rows for `impress-a models`, header first."""
    rows = [("model", "name", "mode", "llm", "calls", "status")]
    for letter in sorted(MODELS):
        m = MODELS[letter]
        rows.append((m.letter, m.name, m.mode, m.llm_shape, str(m.llm_calls), m.status))
    return rows
