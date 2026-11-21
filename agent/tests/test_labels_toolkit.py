"""The `asteer_labels` toolkit, and the type edge item 36 derived without being able to run it.

**The decisive test here is `test_the_two_stage_label_chain_passes_gate_1`.** Item 36 reasoned from
`ArtifactType.unifies_with` that `[md_label, abfe_label]` fails gate 1 unless `md_label` declares a
second output typed `Complex`, and marked the conclusion *"inferred from the enum, not run"* —
because no label tool existed to compose. This episode makes it runnable, so the inference becomes
a measurement, and the negative case is asserted too: drop the second port and the chain is
refused. A derivation that is never executed is a guess with citations.

Skipped, not failed, when impress-a is absent: it is a sibling checkout, not a dependency.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")

from impress_a.compose.graph import TaskGraph, TaskNode  # noqa: E402
from impress_a.compose.validate import SiteCaps, Validator  # noqa: E402
from impress_a.core.budget import BudgetLedger  # noqa: E402
from impress_a.core.types import ArtifactType  # noqa: E402
from impress_a.tools.asteer_labels_agents import (  # noqa: E402
    ABFELabelAgent,
    LabelAdapterNotImplemented,
    MDLabelAgent,
    MissingRootInput,
)
from impress_a.tools.registry import Registry  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TOOLKIT = REPO / "toolkits" / "asteer_labels"



@pytest.fixture
def registry() -> Registry:
    reg = Registry().load()
    # No exemption any more. Upstream's referential check attributed a spec to a directory by
    # the spec's `toolkit` FIELD, so a twin declaring `toolkit: mock` charged IMPRESS's own
    # `mock/SKILL.md` with it -- six permanent lines this fixture had to filter out. Fixed in
    # IMPRESS `3ad5412` (EI.28, item 32), so the fixture can assert what it wanted to all
    # along.
    assert not reg.errors, f"the toolkit did not load cleanly: {reg.errors}"
    return reg


def _validator(reg: Registry, delivery: str = "real") -> Validator:
    """Site and budget sized not to bind, so only the gate under test can refuse."""
    return Validator(reg, SiteCaps(gpu_api="cuda", gpus_per_node=1),
                     BudgetLedger(limits={"gpu_hours": 1000.0, "cpu_hours": 1000.0}),
                     tool_delivery=delivery)


def _chain(reg: Registry, *, second_port: bool = True) -> TaskGraph:
    """`md_label -> abfe_label`, wired on the `structure` port.

    `second_port=False` rebuilds `md_label`'s spec without its `Complex` output, which is the
    counterfactual item 36 asserts and the reason the port exists.
    """
    if not second_port:
        spec = reg.get("md_label")
        reg.specs["md_label"] = spec.model_copy(
            update={"outputs": {"trajectory": spec.outputs["trajectory"]}}
        )
    g = TaskGraph()
    g.add(TaskNode(id="md", tool="md_label", params={"design_dir": "/runs/d0"}))
    g.add(TaskNode(id="abfe", tool="abfe_label", deps=["md"],
                   inputs={"structure": "md.structure"}))
    return g


def test_the_two_stage_label_chain_passes_gate_1(registry):
    """Item 36's inference, now run: the chain types, because of the second output port."""
    failure = _validator(registry)._g1_types(_chain(registry))
    assert failure is None, f"the label chain does not type: {failure}"


def test_without_md_labels_second_output_the_chain_is_refused(registry):
    """The counterfactual, which is what makes the port a requirement rather than a preference.

    `unifies_with` admits identity, `COMPLEX -> BACKBONE` and `METRIC_SET -> METRIC` and nothing
    else, so a `Trajectory` cannot satisfy a `Complex` requirement. Asserting the refusal is the
    only way to know the passing case above passes *for the stated reason*.
    """
    failure = _validator(registry)._g1_types(_chain(registry, second_port=False))
    assert failure is not None, "a Trajectory satisfied a Complex requirement"
    assert failure.gate == "type"
    assert "structure" in failure.reason
    assert not ArtifactType.TRAJECTORY.unifies_with(ArtifactType.COMPLEX)


def test_the_whole_chain_passes_every_gate(registry):
    """Gate 1 is the interesting one, but a chain that fails gate 2 or 5 is not composable either.

    Gate 2 is the one worth naming: it refuses a graph whose tools declare no QC gates at all, so
    this also asserts both specs carry theirs.
    """
    assert _validator(registry).validate(_chain(registry)) is None


def test_both_tools_are_real_so_tool_delivery_mock_refuses_them(registry):
    """The mirror of EI.5's assertion, on the label chain (CON-10).

    These declare `toolkit: asteer_labels`, so a campaign running the *mock* label chain must not
    pick them up. The twins are `mock_md_label` / `mock_abfe_label`, arriving with their own
    commit.
    """
    failure = _validator(registry, delivery="mock")._g6_delivery(_chain(registry))
    assert failure is not None, "real label tools were admitted under tool_delivery: mock"
    assert sorted(failure.detail["offending_tools"]) == ["abfe_label", "md_label"]


@pytest.mark.parametrize(
    ("tool", "declared"),
    [
        ("md_label", ("preorg_rmsd", "rotamer_entropy", "ligand_rmsf")),
        ("abfe_label", ("dg_abfe", "dg_sem")),
    ],
)
def test_the_measured_metrics_are_the_ones_the_naming_table_names(registry, tool, declared):
    """Item 36's naming contract, as far as a spec can carry it.

    A spec cannot assert what *property* the bridge ingests under — that is item 24's — but it can
    assert the tool reports the metrics the table expects, and that it reports no metric named for a
    posterior. `dg_lcb`, `sigma_dg` and `sigma_preorg` describe a distribution rather than a
    molecule, and a measurement ingested under one of those names would quietly redefine the
    objective item 14 ranks on.
    """
    metrics = set(registry.get(tool).metrics)
    assert set(declared) <= metrics
    assert not metrics & {"dg_lcb", "sigma_dg", "sigma_preorg"}


def test_the_convergence_gates_are_integrity_not_acceptance(registry):
    """Decision 0013: only integrity failures demote a pattern.

    A measurement that did not converge is a broken instrument, not a weak design. Filing it as
    acceptance would count a tool failure against the molecule *and* leave the pattern's trust
    intact, so the next batch would run the same broken instrument.
    """
    for tool, metric in (("md_label", "rmsd_plateau_frac"),
                         ("abfe_label", "min_window_overlap")):
        gates = [g for g in registry.get(tool).qc_gates
                 if g.params.get("metric") == metric]
        assert gates, f"{tool} declares no bound on {metric}"
        assert all(str(getattr(g.role, "value", g.role)) == "integrity"
                   for g in gates), (
            f"{tool}'s convergence bound is not integrity-role"
        )


def test_no_gate_bounds_the_measurement_itself(registry):
    """A bar on `dg_abfe` would be the campaign's objective leaking into the instrument.

    The tool's job is to measure; deciding whether -9.8 kcal/mol is good enough belongs to the
    design campaign's objectives, and a tool that refused its own measurement would silently drop
    exactly the designs worth arguing about.
    """
    bounded = {g.params.get("metric") for g in registry.get("abfe_label").qc_gates}
    assert "dg_abfe" not in bounded


def test_the_declared_costs_are_the_figures_the_split_was_argued_from(registry):
    """8.1 and 18, which is why the chain became two campaigns (decision L1).

    Pinned because the arithmetic in item 36 rests on them: 8.1 needs 81 GPU-h available at the
    interlock's 10% cap and fits a 96-192 envelope; 18 needs 180 and does not. If either figure
    moves, that argument has to be re-made rather than quietly inherited.
    """
    assert registry.get("md_label").cost_model.cost["gpu_hours"] == 8.1
    assert registry.get("abfe_label").cost_model.cost["gpu_hours"] == 18.0


def test_md_label_refuses_a_missing_root_input_before_anything_else():
    """The check no gate performs, and it fires before the not-implemented refusal.

    `compose/validate.py:79`-`:81` is a literal `pass` for an unsatisfied root input, so a campaign
    that omits `design_dir` composes cleanly and would measure whatever the empty default points
    at. The order matters: the caller should be told the thing they can fix.
    """
    agent = MDLabelAgent(spec=_spec_stub("md_label"))
    with pytest.raises(MissingRootInput, match="literal"):
        # asyncio.run rather than an async test: this package's [dev] extra is pytest alone,
        # and two tests do not justify an async plugin in a repo whose whole point is few deps.
        asyncio.run(agent.run(None, {}))


@pytest.mark.parametrize(
    ("cls", "tool", "params"),
    [
        (MDLabelAgent, "md_label", {"design_dir": "/runs/d0"}),
        (ABFELabelAgent, "abfe_label", {"structure_path": "holo.cif"}),
    ],
)
def test_an_unimplemented_label_adapter_refuses_rather_than_returning_numbers(
    cls, tool, params
):
    """The whole reason these adapters exist as refusals.

    A label's output supersedes a prediction and is never recomputed, so an invented number does
    not report a wrong result once — it writes itself into the design tree as measured truth and
    trains a surrogate against itself. The message names the twin to use instead.
    """
    with pytest.raises(LabelAdapterNotImplemented) as exc:
        asyncio.run(cls(spec=_spec_stub(tool)).run(None, params))
    assert f"mock_{tool}" in str(exc.value)
    assert "supersedes a prediction" in str(exc.value)


@pytest.mark.parametrize("tool", ["md_label", "abfe_label"])
def test_each_tool_ships_a_known_bad_fixture_for_its_own_failure_mode(tool):
    """`tests/test_gate_fixtures.py` fails any non-mock tool with no `.bad.json`, and item 15's
    Test asks for one per gate. What is checked here is sharper: that the fixture names the gate it
    is supposed to fail, and that the gate is one the spec actually declares."""
    spec = yaml.safe_load((TOOLKIT / "tools" / tool / "spec.yaml").read_text())
    # The gate ids a label fixture may name -- compared against the LABEL `evaluate` emits,
    # which for `metric_in_range` carries its metric in brackets (2026-11-21, when these
    # fixtures came under `tests/test_gate_fixtures.py`'s exact-set check).
    declared = {g["id"] for g in spec["qc_gates"]}
    declared |= {f"{g['id']}[{g['params']['metric']}]"
                 for g in spec["qc_gates"] if "metric" in g.get("params", {})}
    fixtures = sorted((TOOLKIT / "tools" / tool / "tests").glob("*.bad.json"))
    assert fixtures, f"{tool} ships no known-bad fixture"
    for path in fixtures:
        payload = json.loads(path.read_text())
        assert payload["why"].strip(), f"{path.name} does not say why it is bad"
        assert payload["failing_gates"], f"{path.name} names no failing gate"
        assert set(payload["failing_gates"]) <= declared, (
            f"{path.name} expects a gate {tool} does not declare"
        )


def _spec_stub(tool_id: str):
    """The smallest thing `TaskAgent.__init__` needs: something with an `id`."""
    from types import SimpleNamespace

    return SimpleNamespace(id=tool_id, parameters={}, metrics=[], qc_gates=[])


# ---------------------------------------------------------------------------
# The twins: what makes the label chain runnable at M1
# ---------------------------------------------------------------------------

MOCK_CHAIN = ("mock_md_label", "mock_abfe_label")


def _mock_chain(reg: Registry, **params) -> TaskGraph:
    g = TaskGraph()
    g.add(TaskNode(id="md", tool="mock_md_label",
                   params={"design_dir": "/runs/d0", **params}))
    g.add(TaskNode(id="abfe", tool="mock_abfe_label", deps=["md"],
                   inputs={"structure": "md.structure"},
                   params={k: v for k, v in params.items() if k == "n_lambda_windows"}))
    return g


def test_the_mock_label_chain_types_and_passes_every_gate(registry):
    """The twins are the real chain's shape or they are decoration.

    Same two-stage graph, same `structure` edge, same gates — which is only true because
    `mock_md_label` declares the second output port too.
    """
    assert _validator(registry, delivery="mock").validate(_mock_chain(registry)) is None


def test_the_mock_label_chain_is_refused_under_tool_delivery_real(registry):
    """CON-10 on the label chain, which is the half EI.5 could not assert."""
    failure = _validator(registry, delivery="real")._g6_delivery(_mock_chain(registry))
    assert failure is not None, "the label twins were admitted by a real campaign"
    assert sorted(failure.detail["offending_tools"]) == sorted(MOCK_CHAIN)


@pytest.mark.parametrize("tool", MOCK_CHAIN)
def test_each_twin_carries_the_prefix_and_declares_the_field(registry, tool):
    """The two naming rules, for their two different reasons."""
    spec = registry.get(tool)
    assert tool.startswith("mock_"), "an id collision disables a whole toolkit, silently"
    assert spec.toolkit == "mock", "gate 6 matches the field, so this one decides admission"


@pytest.mark.parametrize(
    ("twin", "real"), [("mock_md_label", "md_label"), ("mock_abfe_label", "abfe_label")]
)
def test_a_twin_declares_its_real_tool_s_ports_and_metrics(registry, twin, real):
    """The convention's actual content: a missing metric must fail at M1, not at M2.

    Ports and metrics are compared, not costs — a twin declaring 8.1 GPU-h would make a laptop
    campaign refuse its own chain at gate 5, so the cost model is deliberately *not* copied.
    """
    t, r = registry.get(twin), registry.get(real)
    assert {k: v.type for k, v in t.outputs.items()} == {k: v.type for k, v in r.outputs.items()}
    assert {k: v.type for k, v in t.inputs.items()} == {k: v.type for k, v in r.inputs.items()}
    assert set(t.metrics) == set(r.metrics), "a twin that omits a metric moves the failure to M2"
    assert t.cost_model.cost != r.cost_model.cost, (
        "the twin copied the real cost model; gate 5 would refuse the laptop chain"
    )


def test_both_twins_populate_every_metric_they_declare(registry):
    """Asserted by running them, which is the only way to know."""
    for tool, params in (("mock_md_label", {"design_dir": "/runs/d0"}),
                         ("mock_abfe_label", {"structure_path": "holo.cif"})):
        agent = registry.agent_for(tool)(spec=registry.get(tool))
        out = asyncio.run(agent.run(_req_stub(), params))
        assert set(out["metrics"]) == set(registry.get(tool).metrics), (
            f"{tool} did not report every metric its ToolSpec declares"
        )
        assert set(out["outputs"]) == set(registry.get(tool).outputs)


def test_the_instability_dial_crosses_the_integrity_floor(registry):
    """The dial exists to be watched crossing a bound, so the crossing is pinned.

    At the default the run equilibrates and `rmsd_plateau_frac` clears its 0.5 floor; at 0.9 it
    does not, which demotes the pattern's trust rather than failing the design (decision 0013).
    """
    agent = registry.agent_for("mock_md_label")(spec=registry.get("mock_md_label"))
    settled = asyncio.run(agent.run(_req_stub(), {"design_dir": "/d"}))
    broken = asyncio.run(agent.run(_req_stub(), {"design_dir": "/d", "instability": 0.9}))

    assert settled["metrics"]["rmsd_plateau_frac"] >= 0.5
    assert broken["metrics"]["rmsd_plateau_frac"] < 0.5


def test_too_few_lambda_windows_breaks_the_overlap_diagnostic(registry):
    """ATM's real parameter, doing what a surrogate dial would otherwise have to.

    And the number it reports stays ordinary: a broken run that produced an implausible `dg_abfe`
    would be a kinder failure than the one this models.
    """
    agent = registry.agent_for("mock_abfe_label")(spec=registry.get("mock_abfe_label"))
    structure = {"structure_path": "holo.cif"}
    ok = asyncio.run(agent.run(_req_stub(), {**structure, "n_lambda_windows": 22}))
    thin = asyncio.run(agent.run(_req_stub(), {**structure, "n_lambda_windows": 8}))

    assert ok["metrics"]["min_window_overlap"] >= 0.1
    assert thin["metrics"]["min_window_overlap"] < 0.1
    assert -12.0 < thin["metrics"]["dg_abfe"] < -7.0, (
        "a broken run should still report an ordinary-looking number; that is the hazard"
    )


def test_the_md_twin_refuses_a_missing_root_input_like_the_real_adapter(registry):
    """A twin that accepted it would certify a campaign the real chain refuses."""
    agent = registry.agent_for("mock_md_label")(spec=registry.get("mock_md_label"))
    with pytest.raises(MissingRootInput):
        asyncio.run(agent.run(_req_stub(), {}))


def _req_stub(**inputs):
    """`inputs` is how a wired port reaches an agent, so a test can supply one or not."""
    from types import SimpleNamespace

    return SimpleNamespace(node_id="n0", inputs=dict(inputs), artifacts={})


# ---------------------------------------------------------------------------
# Decision L1 turned abfe_label into a root, and roots are unchecked (EI.22)
# ---------------------------------------------------------------------------


def test_a_lone_abfe_stage_passes_every_gate_with_its_required_input_unwired(registry):
    """The finding, measured rather than argued, and the reason the agents check it themselves.

    `abfe_label` declares `structure: {type: Complex}` as a **required** input. Composed as one
    graph with `md_label` that port is typed and gate 1 checks it — item 36's argument, and
    `test_the_two_stage_label_chain_passes_gate_1` above. But decision L1 split the chain into two
    campaigns, so at runtime this is a root in its own graph, and
    `compose/validate.py:79`-`:81` is a literal `pass` for an unsatisfied required input on a node
    with no dependencies: *"roots may be satisfied from campaign inputs"*.

    So the gates admit it. A campaign that forgets the structure composes cleanly, runs, and would
    measure whatever an empty path points at — at 18 declared GPU-hours a ligand. This test asserts
    the *admission*, because an assertion that something is checked elsewhere is worth nothing
    unless the gap it covers is pinned too.
    """
    g = TaskGraph()
    g.add(TaskNode(id="abfe", tool="abfe_label"))
    assert _validator(registry)._g1_types(g) is None, "gate 1 grew a root-input check"
    assert _validator(registry).validate(g) is None, "some other gate now catches it"


@pytest.mark.parametrize("tool", ["abfe_label", "mock_abfe_label"])
def test_abfe_refuses_when_it_has_neither_a_wired_port_nor_a_path(registry, tool):
    """Both the real adapter and the twin, because a twin that accepted it would certify a
    label campaign that cannot run."""
    agent = registry.agent_for(tool)(spec=registry.get(tool))
    with pytest.raises(MissingRootInput, match="18 declared GPU-hours"):
        asyncio.run(agent.run(_req_stub(), {}))


@pytest.mark.parametrize("tool", ["abfe_label", "mock_abfe_label"])
def test_abfe_accepts_either_route_to_the_structure(registry, tool):
    """The wired port when composed as one graph, `structure_path` when it is its own campaign.

    Accepting both is not indecision: which one carries the structure is a property of how the
    chain was deployed, and L1 chose split *campaigns* while leaving the composed chain the thing
    gate 1 types.
    """
    agent = registry.agent_for(tool)(spec=registry.get(tool))
    expected = LabelAdapterNotImplemented if tool == "abfe_label" else None

    for req, params in ((_req_stub(structure="holo.cif"), {}),
                        (_req_stub(), {"structure_path": "holo.cif"})):
        if expected is None:
            out = asyncio.run(agent.run(req, params))
            assert out["metrics"]["dg_abfe"] < 0.0
        else:
            with pytest.raises(expected):  # gets past the root check, then refuses as unbuilt
                asyncio.run(agent.run(req, params))


def test_both_abfe_specs_declare_the_path_parameter_and_keep_the_port(registry):
    """Keeping the port is not redundant: it is what types the composed chain, and dropping it
    would silently retire item 36's gate-1 argument along with the test that pins it."""
    for tool in ("abfe_label", "mock_abfe_label"):
        spec = registry.get(tool)
        assert "structure" in spec.inputs, "the typed port went away; the chain stops typing"
        assert "structure_path" in spec.parameters, "no cross-campaign route for the structure"
