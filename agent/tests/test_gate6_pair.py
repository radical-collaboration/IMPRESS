"""CON-10: the twins run under `tool_delivery: mock` and are refused under `real`.

**This test is the episode.** The toolkit, the SKILL.md and the campaign file are structure; a
structure that nothing checks is how a delivery-honesty gate stops working without anyone
noticing. Two runs of the same campaign differing only in one line is the assertion.

It also pins the thing the plan for this episode got wrong. The plan said naming the dev
toolkit `mock_asd` "keeps it runnable under `mock` and refused under `real`". It is the other
way round: `_g6_delivery` evaluates `(spec.toolkit == "mock") is want_real`, so a toolkit
named `mock_asd` is refused under `mock` and **admitted** under `real` — the dangerous
direction, and the one IMPRESS's own `toolkits/mock/SKILL.md` warns about in those words. The
fix is that the directory is `mock_asd` while every spec's `toolkit` field says `mock`, and
`test_a_twin_declares_the_toolkit_the_gate_reads` is what keeps anyone from "tidying" that up.

Skipped, not failed, when impress-a is absent: it is a sibling checkout, not a dependency of
this package, and every other test here runs without it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="impress-a's spec loader is not installed")
pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")

from impress_a.compose.graph import TaskGraph, TaskNode  # noqa: E402
from impress_a.compose.validate import SiteCaps, Validator  # noqa: E402
from impress_a.core.budget import BudgetLedger  # noqa: E402
from impress_a.tools.registry import Registry  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TOOLKITS = REPO / "toolkits"

#: Prefix for the copied-toolkit fixtures, so their ids exist in the copy and nowhere else.
PROBE = "probe_"
CAMPAIGN = REPO / "campaigns" / "asd-smb-mock.yaml"


def our_tool_ids() -> list[str]:
    """The ids declared in THIS toolkit, read from its spec files.

    Not `registry.ids()`: the registry searches the IMPRESS checkout too, so after a load it
    holds that whole catalogue - boltz, ligandmpnn, rfd3, rosetta and IMPRESS's own mock
    chain. A test that asserted over `ids()` would be asserting about their tools.
    """
    return sorted(
        yaml.safe_load(f.read_text())["id"]
        for f in (TOOLKITS / "mock_asd" / "tools").glob("*/spec.yaml")
    )


#: The load error this toolkit used to provoke upstream, **and no longer does** since
#: IMPRESS `3ad5412` (EI.28, item 32). Kept as a constant rather than deleted because
#: `test_the_registry_now_loads_with_no_errors_at_all` names it: a reader who sees this string
#: come back needs to know it was once expected and why.
_FORMER_ERROR = "mock: SKILL.md does not mention tool"


@pytest.fixture
def registry() -> Registry:
    """Loaded the way `$IMPRESS_A_TOOLKITS` loads it: our root first, IMPRESS's after.

    `Registry.load(explicit)` searches our path AND the IMPRESS checkout, so the real
    multi-root behaviour is what gets tested rather than our directory in isolation.
    """
    reg = Registry().load()
    assert not reg.errors, f"the toolkit did not load cleanly: {reg.errors}"
    return reg


def _graph(reg: Registry) -> TaskGraph:
    g = TaskGraph()
    for stage in yaml.safe_load(CAMPAIGN.read_text())["stages"]:
        reg.get(stage)  # a stage the registry cannot resolve is this test's bug, not a pass
        g.add(TaskNode(id=stage, tool=stage))
    return g


def _validator(reg: Registry, delivery: str) -> Validator:
    """Site and budget sized not to bind: gate 6 is the subject, so nothing else may refuse
    the graph first and make a pass look like a verdict about delivery."""
    return Validator(reg, SiteCaps(gpu_api="cuda", gpus_per_node=1),
                     BudgetLedger(limits={"gpu_hours": 10.0, "cpu_hours": 10.0}),
                     tool_delivery=delivery)


def test_the_toolkit_loads_from_outside_the_impress_checkout(registry):
    """The property the whole integration rests on (`registry.py:34`, `:97`).

    If this fails, nothing else in the project works the way it is planned: the toolkits, the
    task agents, the gates and the roles all live here and load into IMPRESS by path and by
    dotted import. It is asserted first because it is the cheapest thing to get wrong and the
    most expensive to discover later.
    """
    assert "mock_liganchor_propose" in registry.ids()
    spec = registry.get("mock_liganchor_propose")
    assert spec.entry.startswith("asteer."), "a twin must load from this package, not IMPRESS"
    assert registry.agent_for("mock_liganchor_propose").__name__ \
        == "MockLigAnchorProposeAgent"


def test_a_twin_id_is_prefixed_so_it_cannot_shadow_its_real_tool(registry):
    """Ids are one flat namespace, and a collision disables a whole toolkit silently.

    `_load_toolkit` raises `duplicate tool id` and registers nothing for that toolkit, so a
    twin sharing its real tool's id would take the real toolkit down with it the day item 12
    lands — all-or-nothing, with one line in `reg.errors` and no refusal anywhere. Measured:
    with the twin named `liganchor_propose`, loading a real `liganchor_propose` beside it
    reported `asteer_design: duplicate tool id 'liganchor_propose'` and registered **none** of
    that toolkit.

    So the id carries `mock_` and the field says `mock`. The prefix is the convention gate 6
    declines to trust; the field is the fact it reads. Both are required, for different
    reasons, and this is the test for the first one.
    """
    for tool_id in our_tool_ids():
        assert tool_id.startswith("mock_"), (
            f"{tool_id} does not carry the mock_ prefix; if a real tool ever takes this id, "
            "whichever toolkit loads second registers nothing at all"
        )


def test_a_twin_declares_the_toolkit_the_gate_reads(registry):
    """`toolkit: mock`, not `mock_asd`, and this is the test that stops the "fix".

    `_g6_delivery` is `(spec.toolkit == "mock") is want_real`. A twin declaring `mock_asd`
    would be classified REAL and admitted by a campaign declaring `tool_delivery: real`:
    seeded draws reported as science, which is the documented failure gate 6 exists to
    prevent. The directory name is ours; the field is the gate's.
    """
    for tool_id in our_tool_ids():
        spec = registry.get(tool_id)
        assert spec.toolkit == "mock", (
            f"{tool_id} declares toolkit={spec.toolkit!r}; gate 6 matches 'mock' exactly, so "
            "this twin would be admitted by a campaign declaring tool_delivery: real"
        )


def test_the_same_graph_is_admitted_under_mock_and_refused_under_real(registry):
    """The CON-10 assertion: one campaign, one line different, opposite verdicts."""
    graph = _graph(registry)

    under_mock = _validator(registry, "mock")._g6_delivery(graph)
    assert under_mock is None, f"the twins must run under mock: {under_mock}"

    under_real = _validator(registry, "real")._g6_delivery(graph)
    assert under_real is not None, (
        "the twins were ADMITTED by a campaign declaring real tools — this is the failure "
        "gate 6 exists to prevent, and it means a spec declares the wrong toolkit"
    )
    assert under_real.gate == "tool_delivery"
    assert sorted(under_real.detail["offending_tools"]) == sorted(graph.nodes)


def test_tool_delivery_any_admits_the_twins(registry):
    """`any` is the escape hatch, and it must stay an explicit one.

    Worth pinning because it is the wrong fix for a `real` refusal: a campaign that meets the
    refusal and sets `any` has turned the gate off rather than corrected the chain.
    """
    assert _validator(registry, "any")._g6_delivery(_graph(registry)) is None


def test_the_campaign_file_declares_mock_and_names_only_resolvable_stages(registry):
    """A stage no enabled tool provides is a load-time error; item 30 is the same failure at
    campaign scale, so the cheap half of it is asserted here."""
    campaign = yaml.safe_load(CAMPAIGN.read_text())
    assert campaign["tool_delivery"] == "mock"
    assert campaign["stages"], "a campaign naming no stage plans nothing and still exits 0"
    for stage in campaign["stages"]:
        registry.get(stage)
    # The union over EVERY stage, not the first one's. This read `stages[0]` while the
    # campaign had exactly one stage, which made it right by coincidence; EI.9 added a second
    # and the assertion started rejecting that stage's own objectives. The sentence it is
    # enforcing is "no enabled tool reports this metric", and every stage is enabled.
    declared = {m for stage in campaign["stages"] for m in registry.get(stage).metrics}
    for objective in campaign["objectives"]:
        assert objective["name"] in declared, (
            f"objective {objective['name']!r} names a metric no enabled tool reports"
        )


def test_dropping_a_required_section_disables_the_toolkit_rather_than_crashing(tmp_path):
    """`_load_toolkit` raises per toolkit and `load()` records it, so one bad SKILL.md must
    not take the registry down with it — asserted on a copy, never on ours."""
    import shutil

    root = tmp_path / "toolkits"
    shutil.copytree(TOOLKITS, root)

    # EVERY TOOL IN THE COPY IS RENAMED, and that is required since H4 rather than tidiness.
    # `load(explicit)` searches the DEFAULT root too, and since these toolkits live in this
    # checkout the default root ships the very ids this copy carries -- so "the broken toolkit
    # registered nothing" would read as false against the shipped copy whatever the copy did.
    # Prefixing makes the copy's ids exist nowhere else, which is what the assertions need.
    ids = sorted((yaml.safe_load(f.read_text())["id"] for f in root.glob("*/tools/*/spec.yaml")),
                 key=len, reverse=True)  # longest first: one id is a suffix of another
    for tk in sorted(root.iterdir()):
        sk = tk / "SKILL.md"
        if sk.exists():
            text = sk.read_text()
            for i in ids:
                text = text.replace(i, PROBE + i)
            sk.write_text(text)
    for f in sorted(root.glob("*/tools/*/spec.yaml")):
        f.write_text(f.read_text().replace(f"id: {yaml.safe_load(f.read_text())['id']}",
                                           f"id: {PROBE}{yaml.safe_load(f.read_text())['id']}", 1))
        f.parent.rename(f.parent.with_name(PROBE + f.parent.name))

    skill = root / "mock_asd" / "SKILL.md"
    skill.write_text(skill.read_text().replace("## Pitfalls", "## Gotchas"))

    reg = Registry().load(root)
    assert any("SKILL.md missing sections" in e for e in reg.errors), reg.errors
    # `mock_liganchor_propose`, not `liganchor_propose`. This assertion named the REAL tool
    # until EI.8, when the real tool came into existence and the test began failing: the id it
    # named had never existed anywhere, so "it is absent" had been vacuously true since EI.5.
    # The twin-naming rule is what makes the two ids differ, and this test was reaching for the
    # wrong one. It is also why the real tool landing is what exposed it rather than a review.
    assert PROBE + "mock_liganchor_propose" not in reg.ids(), (
        "a toolkit that fails to load must register nothing — all-or-nothing is what keeps a "
        "half-loaded toolkit from running"
    )
    assert PROBE + "liganchor_propose" in reg.ids(), (
        "and the OTHER toolkit must be unaffected: one bad SKILL.md disables its own toolkit, "
        "not the registry"
    )


def test_the_registry_now_loads_with_no_errors_at_all(registry):
    """**This assertion was inverted until IMPRESS `3ad5412`, and that is what it is for.**

    `_load_toolkit` attributed a spec to a directory by the spec's `toolkit` FIELD:

        for tid in [s.id for s in self.specs.values() if s.toolkit == d.name]:

    So when IMPRESS's own `mock/` directory loaded, the check demanded that *its* SKILL.md
    mention every spec anywhere declaring `toolkit: mock` - including our six. **Gate 6
    requires a surrogate to declare exactly that** (CON-10), so the two rules were jointly
    unsatisfiable for any twin outside `IMPRESS/agent/toolkits/mock/`, and the clash was never
    about this project: any two toolkit directories sharing a `toolkit` value tripped it.

    This test asserted the six lines were PRESENT, so that the day it was fixed a test would
    say so. It said so. EI.28 iterates `staged` - the specs each directory actually loaded -
    and our six errors became zero with the same thirty specs registered.

    What it asserts now is the thing that was worth having: **`reg.errors` is a usable
    signal.** It was permanently non-empty for anyone using the documented extension
    mechanism, and a signal that is always on is not a signal - so the assertion is that it is
    empty, by name, and the former error is named too, because a reader who sees that string
    come back needs to know it was once expected.
    """
    assert registry.errors == [], (
        f"the registry reports load errors again: {registry.errors}. If one of them is "
        f"{_FORMER_ERROR!r}, item 32 has regressed upstream - the check is reading "
        "`self.specs` filtered by the `toolkit` field again instead of `staged`"
    )
    assert "mock_liganchor_propose" in registry.ids(), (
        "and the toolkit still registers - the old error was cosmetic, appending to `errors` "
        "rather than raising, which is why it could stay wrong for so long"
    )


def test_every_tool_in_the_toolkit_is_mentioned_in_its_skill_md(registry):
    """Written as a replacement for a check that could not see this toolkit, and kept.

    Upstream's referential check matched on the spec's `toolkit` FIELD, and ours say `mock`
    while the directory is `mock_asd` - so it matched this directory for no spec at all and
    our SKILL.md was never checked by anything. **EI.28 fixed that too**: iterating `staged`
    means each directory is checked against its own SKILL.md whatever its specs' field says,
    so upstream now covers this.

    Kept anyway, for one reason: it fails with the missing tool's NAME, where upstream's
    appends a line to `reg.errors` that the fixture above turns into one aggregate failure.
    The redundancy is cheap and the message is better.
    """
    text = (TOOLKITS / "mock_asd" / "SKILL.md").read_text()
    assert our_tool_ids(), "a toolkit with no tools proves nothing about gate 6"
    for tool_id in our_tool_ids():
        assert tool_id in text, f"SKILL.md does not mention {tool_id!r}"


# ---------------------------------------------------------------------------
# The label half of the pair (EI.22). EI.5 could not assert this: the label
# workflow did not exist, and no mock label campaign was in anyone's scope.
# ---------------------------------------------------------------------------

LABEL_CAMPAIGNS = {
    "campaigns/asd-labels-md-mock.yaml": "mock_md_label",
    "campaigns/asd-labels-abfe-mock.yaml": "mock_abfe_label",
}


def _campaign_graph(reg: Registry, path: str) -> TaskGraph:
    g = TaskGraph()
    for stage in yaml.safe_load((REPO / path).read_text())["stages"]:
        reg.get(stage)
        g.add(TaskNode(id=stage, tool=stage))
    return g


@pytest.mark.parametrize("path", sorted(LABEL_CAMPAIGNS))
def test_each_mock_label_campaign_is_admitted_under_mock_and_refused_under_real(registry, path):
    """The pair, run twice — once per label campaign, because L1 split the chain.

    Two files rather than one is decision L1 (item 36): `md_label` and `abfe_label` are
    dispatched at different rates and ask the allocation for different resources, so they are
    two campaigns. That makes this assertion two assertions.
    """
    graph = _campaign_graph(registry, path)

    assert _validator(registry, "mock")._g6_delivery(graph) is None, (
        f"{path} declares tool_delivery: mock and its own stage was refused"
    )
    refused = _validator(registry, "real")._g6_delivery(graph)
    assert refused is not None, f"{path}'s twins were ADMITTED by a real campaign"
    assert refused.detail["offending_tools"] == [LABEL_CAMPAIGNS[path]]


@pytest.mark.parametrize("path", sorted(LABEL_CAMPAIGNS))
def test_each_mock_label_campaign_declares_what_item_36_requires_of_one(registry, path):
    """A label campaign is a different object, and the file has to say so (item 36).

    `replicas: 1` is the one that interacts with the control model: `--model B`'s
    `RehearsalOracle` asks for 2 or 3 (`policy/oracle.py:95`), and `replicas` is a **cap**
    (`runtime/executor.py:861`, clamped at `:866`), so the file is what makes B safe here.
    """
    campaign = yaml.safe_load((REPO / path).read_text())

    assert campaign["tool_delivery"] == "mock"
    assert campaign["replicas"] == 1, "a replicate of a multi-GPU-hour measurement is waste"
    assert campaign["max_cycles"] == 1, "a label campaign measures a fixed set of points once"
    assert campaign["budget"], "CON-9: a label batch must not draw on the design campaign's budget"
    assert len(campaign["stages"]) == 1, "L1 split the chain; one stage per label campaign"


@pytest.mark.parametrize("path", sorted(LABEL_CAMPAIGNS))
def test_a_label_campaigns_objectives_report_rather_than_bound(registry, path):
    """Decision 0013, as a property of the campaign file.

    A label whose run did not converge is *the tool broke*, not *the design is weak*, so the
    convergence check is an **integrity** QC gate on the tool and the objectives carry no bars.
    A bounded objective here would file an instrument failure under the other heading, leave the
    pattern's trust intact, and let the next batch run the same broken instrument.
    """
    campaign = yaml.safe_load((REPO / path).read_text())
    for objective in campaign["objectives"]:
        assert not {"min", "max"} & set(objective), (
            f"{objective['name']} is bounded in {path}; a label objective reports"
        )
    # And the convergence telemetry is NOT an objective at all: it says whether the instrument
    # worked, which is the gate's business and not the front's.
    names = {o["name"] for o in campaign["objectives"]}
    assert not names & {"rmsd_plateau_frac", "min_window_overlap", "cycle_closure_kcal"}


@pytest.mark.parametrize("path", sorted(LABEL_CAMPAIGNS))
def test_every_label_objective_names_a_metric_the_stage_reports(registry, path):
    """An objective naming a metric no enabled tool declares is a load-time error, and the
    campaign's own stage is the only enabled tool here."""
    campaign = yaml.safe_load((REPO / path).read_text())
    declared = set(registry.get(campaign["stages"][0]).metrics)
    for objective in campaign["objectives"]:
        assert objective["name"] in declared, (
            f"{objective['name']} is not reported by {campaign['stages'][0]}"
        )


def test_the_two_label_campaigns_have_distinct_ids(registry):
    """M1's campaigns criterion counts campaign ids: the plane keys managers by id
    (`control/plane.py:93`, `:103`), and that keying is the thing under test. Two files with one
    id would satisfy the file count and fail the criterion."""
    ids = {yaml.safe_load((REPO / p).read_text())["campaign_id"] for p in LABEL_CAMPAIGNS}
    assert len(ids) == len(LABEL_CAMPAIGNS), f"campaign ids collide: {ids}"
    design = yaml.safe_load((REPO / "campaigns" / "asd-smb-mock.yaml").read_text())
    assert design["campaign_id"] not in ids, "a label campaign shares the design campaign's id"
