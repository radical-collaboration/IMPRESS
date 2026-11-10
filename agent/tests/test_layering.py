"""The import contract, asserted rather than reviewed.

`CLAUDE.md` lists three layering rules as invariants and records their enforcement as
"review". They are the load-bearing ones:

  * `policy` must not import `tools`, `exec` or `runtime` - a policy that can reach a tool
    adapter stops emitting abstract intent, and control models stop being swappable;
  * `compose` must not import `exec` - this is what keeps the whole validation path
    testable with no backend, which is the entire laptop test tier;
  * `core` imports nothing internal.

This file walks the source with `ast` and checks all three, plus every other edge, against
one table that mirrors `docs/reference/architecture.md`. `ast.walk` is used deliberately
rather than a scan of module-level imports: the real adapters defer their science imports
into `run()` bodies on purpose (see `tools/_pdbtools.py`), and a deferred
`from ..exec import ...` inside a `compose` function would be exactly as fatal as one at
the top of the file.

One honest blind spot: a dynamic `importlib.import_module("impress_a.x")` is invisible
here. `Registry.agent_for` uses one, legitimately, and within its own layer.
"""
from __future__ import annotations

import ast
import pathlib

import impress_a

SRC = pathlib.Path(impress_a.__file__).resolve().parent

#: layer -> the internal layers it MAY import. Mirrors docs/reference/architecture.md.
#: An allow-list, not a deny-list: a NEW cross-layer import fails by default, which is the
#: direction that matters. A new layer is one line here, and an unlisted layer fails
#: `test_every_layer_is_in_the_table`, so this cannot silently fall out of step.
#:
#: When a row here conflicts with the code, reconcile the DOC up to the code and fix this
#: table only if the edge is genuinely allowed. Loosening a row to make a failure go away
#: is how the contract dies.
#:
#: Three allowances are documented but not currently exercised - `control -> runtime`,
#: `runtime -> policy` and `tools -> exec`. They are kept because the doc grants them; the
#: table is a mirror of the contract, not a snapshot of today's edges.
ALLOWED = {
    "core": frozenset(),
    "compose": frozenset({"tools", "core"}),
    "tools": frozenset({"exec", "core"}),
    "exec": frozenset({"compose", "tools", "core"}),
    "policy": frozenset({"core"}),
    "runtime": frozenset({"policy", "compose", "exec", "tools", "core"}),
    # `manager -> tools` is real (manager.py:39 imports Registry) and was missing from
    # architecture.md until this test surfaced it. Doc corrected, table records the code.
    "manager": frozenset({"runtime", "policy", "tools", "core"}),
    "control": frozenset({"manager", "runtime", "core"}),
    # cli/ and __main__ appeared in no layer of the doc's table at all.
    #
    # `control` and `runtime` were added when `impress-a serve`/`control` landed: the CLI is
    # the composition root, the one layer whose job is to know every other, which is why it
    # already has the widest row. `serve` must build a control plane and an HTTP server;
    # `control` must build a `RolesDriver`. Both edges were already transitively true through
    # `manager` (which imports `runtime` directly), and neither touches the three rules this
    # contract exists for: no policy reaches a tool adapter, no compose reaches exec, and core
    # still imports nothing internal.
    "cli": frozenset({"control", "manager", "runtime", "policy", "compose", "tools",
                      "core", "analysis"}),
    # `analysis` is downstream of everything and must reach no reasoner. The rule that
    # matters is the ABSENCE of `policy` and `control`: a scorer that could reach a reasoner
    # could score a campaign by asking it, and the comparison's whole method is that figures
    # come from provenance, the ledgers and the artifacts on disk - never from an arm's own
    # bookkeeping. `validate_tasks` genuinely executes a chain, so it needs `exec`, `compose`
    # and `tools`; `compare_arms` will use `core` alone, which this row permits without
    # requiring.
    "analysis": frozenset({"runtime", "exec", "compose", "tools", "core"}),
    "__main__": frozenset({"cli"}),
}


def _layer(dotted: str | None) -> str | None:
    """"impress_a.tools.gates" -> "tools". Anything not inside the package -> None."""
    if not dotted:
        return None
    parts = dotted.split(".")
    if parts[0] != "impress_a" or len(parts) < 2:
        return None
    return parts[1]


def _package_of(path: pathlib.Path) -> tuple[str, ...]:
    """The dotted package CONTAINING `path`, as parts relative to the package root.

    Correct for `foo/bar.py` and `foo/__init__.py` alike - both live in package `foo`,
    which is what a relative import resolves against.
    """
    rel = path.relative_to(SRC)
    return ("impress_a",) + rel.parts[:-1]


def _resolve(node: ast.ImportFrom, pkg: tuple[str, ...]) -> str | None:
    """The absolute dotted name an `ImportFrom` refers to, relative levels included."""
    if node.level == 0:
        return node.module
    base = pkg[:len(pkg) - (node.level - 1)] if node.level > 1 else pkg
    return ".".join(base + ((node.module,) if node.module else ()))


def _edges() -> list[tuple[pathlib.Path, int, str, str]]:
    """(file, lineno, importer_layer, imported_layer) for every internal import."""
    out: list[tuple[pathlib.Path, int, str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        pkg = _package_of(path)
        importer = _layer(".".join(pkg)) or (
            path.stem if path.parent == SRC else None)
        if importer is None:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _layer(_resolve(node, pkg))
            elif isinstance(node, ast.Import):
                imported = next(
                    (lay for a in node.names if (lay := _layer(a.name))), None)
            else:
                continue
            if imported and imported != importer:
                out.append((path, node.lineno, importer, imported))
    return out


def test_core_imports_nothing_internal():
    """`core` is the vocabulary every other layer shares, so it may depend on none of them.

    Its own files say why they exist there: `core/session.py` and `core/results.py` hold
    the shapes a reasoner in another process needs, precisely so that reaching for them
    does not drag in `runtime`.
    """
    bad = [f"{p.relative_to(SRC.parent)}:{ln}: core must not import {b}"
           for p, ln, a, b in _edges() if a == "core"]
    assert bad == [], "\n".join(bad)


def test_the_import_contract_holds():
    """Every internal import, against the table. All violations reported in one run."""
    # Guard the TABLE first. The realistic failure is not someone adding a bad import and
    # ignoring the test - it is someone hitting the failure and editing the row.
    assert ALLOWED["policy"].isdisjoint({"tools", "exec", "runtime"}), \
        "a policy that can reach a tool adapter stops emitting abstract intent"
    assert "exec" not in ALLOWED["compose"], \
        "compose reaching exec would make the validation path need a backend"
    assert ALLOWED["analysis"].isdisjoint({"policy", "control"}), \
        "a scorer that can reach a reasoner can score a campaign by asking it, and every " \
        "figure the comparison publishes is supposed to come from the executor's own record"

    bad = [f"{p.relative_to(SRC.parent)}:{ln}: {a} must not import {b}"
           for p, ln, a, b in _edges() if b not in ALLOWED[a]]
    assert bad == [], "\n".join(bad)


#: The only modules that may import the root `impress` package. IMPRESS-A depends on it for the
#: execution loop (`ImpressBasePipeline`, `ImpressManager`) and for nothing else: a `policy` or
#: `core` module reaching it would put framework types into the reasoner contract, and
#: `ImpressBasePipeline` cannot cross the `CampaignSession` boundary.
IMPRESS_IMPORTERS = {"runtime/runner.py", "runtime/pipelines.py"}


def test_only_the_runner_imports_impress():
    """The dependency boundary, asserted the same way as the internal one.

    `agent/` depends on the repository root's `impress` and may not modify it. Keeping the
    import surface to two modules is what makes that a boundary rather than a coupling: it is
    the difference between "the execution loop is built on IMPRESS" and "IMPRESS-A is a fork of
    it". Passes trivially while nothing imports it, which is the point - it holds as the Runner
    lands rather than being written afterwards to describe whatever happened.
    """
    bad = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in IMPRESS_IMPORTERS:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
            elif isinstance(node, ast.Import):
                mod = next((a.name for a in node.names
                            if a.name == "impress" or a.name.startswith("impress.")), "")
            else:
                continue
            # `impress_a` also starts with "impress"; match the package, not the prefix.
            if mod == "impress" or mod.startswith("impress."):
                bad.append(f"{rel}:{node.lineno}: imports {mod!r}")
    assert bad == [], (
        "only " + ", ".join(sorted(IMPRESS_IMPORTERS)) + " may import the root `impress` "
        "package:\n" + "\n".join(bad))


def test_the_offer_cannot_reach_the_execution_layer():
    """`impress-a offer` prices a campaign without running it, and nothing may erode that.

    The layer row permits `runtime -> exec`, correctly - the executor lives there. The offer
    does not get that licence: a caller asks it what an invocation would cost precisely
    because it has not decided to make one, so a module that could dispatch a task is the
    wrong shape for the answer. The synchronous signature is the other half of the guarantee
    (`tests/test_validation.py`), and this is the half review would otherwise have to hold.
    """
    offered = SRC / "runtime" / "offer.py"
    assert offered.exists(), "runtime/offer.py has moved; update this test with it"
    reached = {imported for path, _ln, _a, imported in _edges() if path == offered}
    assert "exec" not in reached, (
        f"runtime/offer.py imports the exec layer (reaches {sorted(reached)}) - it can now "
        f"dispatch work, and an offer must not be able to run what it is pricing")


def test_every_keyword_passed_to_a_core_model_is_a_field_of_it():
    """A projection that passes a field the model does not declare loses it silently.

    `tools/view.card_for` passed `burn_rate=` and `max_commitment=` to `TaskCard`, which
    declared neither, from the line's first day - and pydantic's default `extra` is `ignore`,
    so both were dropped without a word. Nothing observably broke because no shipped spec
    sets either key, and `core/budget.Commitment` meanwhile documented a rule against a field
    that could not exist (backlog D1).

    `extra="forbid"` is NOT the fix: these models cross the HTTP control-plane boundary, and
    forbidding extras would turn a newer peer's observation into a 500 rather than a field
    this version ignores. So the check is mechanical instead, and it is cheap: every keyword
    any module passes to a model declared in `core/toolkit` or `core/decision` must be one of
    that model's fields. Walked with `ast`, for the reason the rest of this file is.
    """
    import pydantic

    from impress_a.core import decision as decision_mod
    from impress_a.core import toolkit as toolkit_mod

    models = {
        name: obj
        for mod in (toolkit_mod, decision_mod)
        for name, obj in vars(mod).items()
        if isinstance(obj, type) and issubclass(obj, pydantic.BaseModel)
        and obj.__module__ == mod.__name__
    }
    assert "TaskCard" in models and "CampaignObservation" in models, (
        f"the model sweep found {sorted(models)}; it has stopped seeing the models it is "
        f"meant to guard")

    bad = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if (model := models.get(node.func.id)) is None:
                continue
            for kw in node.keywords:
                if kw.arg is None:          # **kwargs - nothing named to check
                    continue
                if kw.arg not in model.model_fields:
                    bad.append(f"{path.relative_to(SRC)}:{node.lineno} passes "
                               f"`{kw.arg}=` to {node.func.id}, which has no such field - "
                               f"pydantic drops it silently")
    assert bad == [], "\n".join(bad)


def test_every_layer_is_in_the_table():
    """A new package under `impress_a/` must be placed in the contract, not skipped.

    Without this, adding a layer means it is silently unchecked - the table would still
    pass while saying nothing about the new code.
    """
    layers = {p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    layers |= {p.stem for p in SRC.glob("*.py") if p.stem != "__init__"}
    missing = sorted(layers - set(ALLOWED))
    assert missing == [], f"not in ALLOWED: {missing}"


#: Names the legacy decision path defined, each of which phase 11 deleted. Listed rather than
#: pattern-matched, because "no module defines `decide`" is a claim about these specific things
#: and a regex would also catch a future unrelated `decide`.
DELETED_IN_PHASE_11 = (
    "ControlPolicy", "BasePolicy", "SequentialPolicyDriver", "DecideAsRoles",
    "LegacyPlanner", "LegacySpecifier", "ThresholdPolicy", "FourNodePolicy",
    "OraclePolicy", "ExternalPolicy", "ReplayPolicy", "NullPolicy",
    "PolicyWrapper", "LoggingPolicy", "RuleCorrectionsPolicy", "LangChainOracle",
    "DecisionModel",
)


def test_no_module_defines_decide():
    """The mechanical proof the strangler finished.

    `decide(obs) -> Decision` answered "what should the campaign be trying to achieve" and
    "which tool should run next" in one call, which is exactly what made it impossible to say
    which half of a control model earned its cost - and the four-arm comparison's whole claim
    is that those two seams are separately attributable. A `decide` reappearing anywhere means
    the two questions have been merged again.

    `interpret` and `on_rejected` go with it: the Listener owns ingestion, and answering a
    rejection is `Planner.replan`.
    """
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    node.name in ("decide", "interpret", "on_rejected"):
                offenders.append(
                    f"{path.relative_to(SRC.parent)}:{node.lineno}: defines {node.name}()")
    assert offenders == [], "\n".join(offenders)


def test_nothing_defines_the_deleted_legacy_names():
    """Each of these was a class the `decide` contract needed, and each is gone.

    A name reappearing is not necessarily wrong - but it is a decision, and it should fail a
    test rather than arrive in a diff nobody connects to the phase that removed it. The
    rulings the deleted modules carried survive elsewhere and are named where they landed:
    bounded retry per experiment is `Planner.replan`, the concurrency hold is the Deployer's
    in-flight cap, and the reasoner owning `interpret` is the Listener owning ingestion.
    """
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in DELETED_IN_PHASE_11:
                found.append(f"{path.relative_to(SRC.parent)}:{node.lineno}: {node.name}")
    assert found == [], "\n".join(found)


def test_the_decision_union_is_gone_and_nothing_imports_it():
    """`ComposeAndRun`, `Backtrack`, `Stop` and the `Decision` union were what a policy
    returned. None of them is a thing any reasoner returns now: a Stage is what a Planner
    emits, a Spec revision is what a Specifier emits, stopping is the executor's call on the
    Listener's request, and branching from an earlier node is `SpecObjective.parent_node`.

    **Two names survive, each because it is not a decision.** `RequestHuman` is the payload of
    `CampaignSession.request_human`, a live operation that parks a campaign and records the
    question; the control plane exposes it.

    And `ExperimentIntent`, which is the one with a reason worth stating:
    `Composer.compose` takes a chain and a width, which is what computing a trust signature at
    a declared replica width needs (`impress-a trust --assert`) and what validating a chain
    needs (`impress-a validate-tasks`). Neither is a policy decision, so ADR 0010's clause
    about policies emitting abstract intent is amended rather than this type deleted: a
    `Stage` of `TaskMapping`s is what a reasoner emits, and this is a composer input.
    """
    gone = {"Decision", "ComposeAndRun", "Backtrack", "Stop"}
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in gone:
                offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno}: {node.name}")
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in gone:
                        offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno}: "
                                         f"imports {alias.name}")
    assert offenders == [], "\n".join(offenders)

    from impress_a.core.decision import ExperimentIntent, RequestHuman
    assert ExperimentIntent is not None, "the composer's input must still exist"
    assert RequestHuman is not None, "a live session operation's payload must still exist"
