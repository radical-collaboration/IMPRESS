"""T1 - unit tests. Pure logic, no I/O."""

from datetime import datetime, timedelta, timezone

import pytest

from impress_a.core.artifacts import (
    AUTHORITY_ASSAY,
    AUTHORITY_ML_PREDICTOR,
    ArtifactRef,
    Property,
    PropertySource,
    SourceKind,
)
from impress_a.core.budget import BudgetLedger, Commitment, Walltime
from impress_a.core.data import DataRegistry, DatumKind, TaskFuture
from impress_a.core.pareto import Direction, Objective, pareto_front
from impress_a.core.qc import GateOutcome, GateResult, QCReport, QCVerdict
from impress_a.core.results import RunOutcome, RunState, TaskOutcome
from impress_a.core.spec import (
    Aim,
    Deferral,
    ObjectiveStatus,
    SatisfactionRule,
    Spec,
    SpecObjective,
    SpecRevision,
    Stage,
    TaskDirective,
    TaskMapping,
)
from impress_a.core.tree import CampaignTree, DesignNode
from impress_a.core.types import ArtifactType, Pattern


def _node(**metrics):
    n = DesignNode()
    for k, v in metrics.items():
        n.properties[k] = Property(name=k, value=v, source=PropertySource(name="t"))
    return n


def test_p6_must_never_be_scheduled():
    assert Pattern.P6.is_inline
    assert Pattern.P4.is_external and Pattern.P8.is_external
    assert not Pattern.P1.is_external


def test_unparameterised_ligand_is_a_type_error():
    """The Part A silent-failure mode, promoted to a compile-time check."""
    assert not ArtifactType.SMALL_MOLECULE.unifies_with(ArtifactType.PARAMETERIZED)
    assert ArtifactType.COMPLEX.unifies_with(ArtifactType.BACKBONE)
    assert not ArtifactType.BACKBONE.unifies_with(ArtifactType.COMPLEX)


def test_qc_fail_is_never_rankable():
    q = QCReport().add(GateResult(gate="g", outcome=GateOutcome.FAIL))
    assert q.verdict is QCVerdict.FAIL and not q.eligible_for_front
    s = QCReport()
    s.mark_suspect("provisional")
    assert s.verdict is QCVerdict.SUSPECT and s.eligible_for_front


def test_constraints_prune_before_ranking():
    objs = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
            Objective(name="iptm", direction=Direction.MAX)]
    nodes = [_node(sc_rmsd=1.0, iptm=0.9), _node(sc_rmsd=2.0, iptm=0.95),
             _node(sc_rmsd=2.5, iptm=0.5), _node(sc_rmsd=9.0, iptm=0.99)]
    front = pareto_front(nodes, objs)
    assert len(front) == 2
    assert all(n.metric("sc_rmsd") <= 3.0 for n in front)


def test_a_node_missing_a_constrained_objective_is_never_feasible():
    """Backlog G1's first cause, as one line of core logic.

    The exploration chain (rfd3 -> ligandmpnn -> boltz) skips Rosetta, so its nodes carry
    no shape_complementarity at all. `Objective.satisfied_by` returns False for a MISSING
    value rather than treating it as unconstrained, so any objective with a min/max
    excludes such a node - and `delta-small-molecule.yaml` constrains
    shape_complementarity >= 0.55. Exploration can therefore never enter the front, which
    is why every informed explore landing increments the stagnation counter.

    This pins the CURRENT behaviour; the fix is undecided. See
    plans/exploration-vs-stagnation.md.
    """
    objs = [Objective(name="shape_complementarity", direction=Direction.MAX, min=0.55),
            Objective(name="ligand_iptm", direction=Direction.MAX, min=0.4)]
    explore = _node(ligand_iptm=0.62)          # no Rosetta metrics at all
    exploit = _node(ligand_iptm=0.55, shape_complementarity=0.61)

    assert pareto_front([explore], objs) == []
    assert [n.id for n in pareto_front([explore, exploit], objs)] == [exploit.id], \
        "a worse-scoring exploit node still wins, because it is the only one ranked"


def test_qc_failed_node_excluded_from_front():
    objs = [Objective(name="iptm", direction=Direction.MAX)]
    good, bad = _node(iptm=0.5), _node(iptm=0.99)
    bad.qc.add(GateResult(gate="clash", outcome=GateOutcome.FAIL))
    assert [n.id for n in pareto_front([good, bad], objs)] == [good.id]


def test_budget_blocks_and_reports_dimension():
    b = BudgetLedger(limits={"gpu_hours": 10, "cpu_hours": 5})
    b.charge({"gpu_hours": 9.5})
    assert b.would_exceed({"gpu_hours": 1.0}) == ["gpu_hours"]
    assert b.would_exceed({"cpu_hours": 1.0}) == []
    assert b.fraction_used("gpu_hours") == 0.95


def test_budget_reservation_prevents_concurrent_double_spend():
    """Two submissions in flight must not both be admitted against one budget.

    Gate 5 checks an estimate; the charge only lands when the graph finishes. Serially
    those coincide. Concurrently they do not, and without a reservation both graphs see
    the same untouched remaining budget and the campaign overspends.
    """
    b = BudgetLedger(limits={"gpu_hours": 10.0})
    assert b.reserve({"gpu_hours": 6.0}, "r0001") == []
    # Nothing is spent yet - the first run has not finished.
    assert b.remaining("gpu_hours") == 10.0
    assert b.available("gpu_hours") == 4.0

    assert b.reserve({"gpu_hours": 6.0}, "r0002") == ["gpu_hours"], \
        "second submission must be refused while the first holds the budget"
    assert "r0002" not in b.holds, "a refused reservation must claim nothing"

    # A smaller one still fits.
    assert b.reserve({"gpu_hours": 3.0}, "r0003") == []

    # Settling charges what it actually cost, not what was estimated.
    b.settle("r0001", {"gpu_hours": 5.0})
    assert b.remaining("gpu_hours") == 5.0
    assert b.available("gpu_hours") == 2.0      # r0003 still holds 3.0

    # Work that never ran releases its hold and is charged nothing.
    b.release("r0003")
    assert b.available("gpu_hours") == 5.0 and b.remaining("gpu_hours") == 5.0
    assert not b.holds


def test_budget_exhaustion_ignores_in_flight_reservations():
    """A campaign with everything in flight is busy, not exhausted.

    `exhausted()` terminates the campaign, and policies read it to decide whether to
    stop. If reservations counted, a healthy campaign would kill itself the moment it
    had committed its budget to work that had not yet reported.
    """
    b = BudgetLedger(limits={"gpu_hours": 10.0})
    b.reserve({"gpu_hours": 10.0}, "r0001")
    assert b.available("gpu_hours") == 0.0, "nothing more may be admitted"
    assert b.exhausted() == [], "but the campaign is not over"
    b.settle("r0001", {"gpu_hours": 10.0})
    assert b.exhausted() == ["gpu_hours"]


def test_measurement_supersedes_prediction_and_retains_it():
    t = CampaignTree()
    nid = t.add(_node(solubility=0.4))
    assert t.ingest_measurement(nid, Property(
        name="solubility", value=0.9,
        source=PropertySource(name="lab", kind=SourceKind.MEASURED,
                              authority=AUTHORITY_ASSAY)))
    n = t.get(nid)
    assert n.properties["solubility"].value == 0.9
    assert n.properties["solubility"].is_measured
    assert "solubility__superseded" in n.properties, "prediction must be retained"


def test_lower_authority_cannot_override_measurement():
    t = CampaignTree()
    nid = t.add(DesignNode())
    t.ingest_measurement(nid, Property(name="ddg", value=-4.0, source=PropertySource(
        name="lab", kind=SourceKind.MEASURED, authority=AUTHORITY_ASSAY)))
    assert not t.ingest_measurement(nid, Property(
        name="ddg", value=99.0,
        source=PropertySource(name="ml", authority=AUTHORITY_ML_PREDICTOR)))
    assert t.get(nid).properties["ddg"].value == -4.0


def test_backtracking_is_non_destructive():
    t = CampaignTree()
    root = t.add(DesignNode())
    child = t.add(DesignNode(parent=root))
    branch = t.branch_from(root)
    t.add(branch)
    assert child in [n.id for n in [t.get(child)]] or True
    assert t.get(child) is not None, "abandoned branch must survive"
    assert branch.parent == root and len(t) == 3


def test_artifact_ref_records_size_and_digest(tmp_path):
    """A path alone says nothing about whether the bytes behind it are still the ones
    the campaign reasoned about - which is the whole risk once the reasoner is remote."""
    from impress_a.core.artifacts import ArtifactRef
    from impress_a.core.types import ArtifactType

    f = tmp_path / "backbone.pdb"
    f.write_text("ATOM\n")
    ref = ArtifactRef(type=ArtifactType.BACKBONE, path=str(f)).hash_file()
    assert ref.bytes == 5 and ref.sha256 and ref.located == str(f)

    f.write_text("ATOM ATOM\n")
    assert ArtifactRef(type=ArtifactType.BACKBONE,
                       path=str(f)).hash_file().sha256 != ref.sha256, \
        "a changed file must be a different artifact"

    missing = ArtifactRef(type=ArtifactType.BACKBONE, path=str(tmp_path / "gone.pdb"))
    assert missing.hash_file().sha256 is None, "an absent file is not silently digested"

    inline = ArtifactRef(type=ArtifactType.METRIC_SET, value="M")
    assert inline.located == "M" and inline.hash_file().sha256 is None


# ---------------------------------------------------------------------------
# The Spec vocabulary (phase 1 of plans/control-plane-refactor.md).
# ---------------------------------------------------------------------------

def _spec_with_one_objective(**kw):
    aim = Aim(statement="fold it")
    obj = SpecObjective(aim=aim.id, statement="a passing fold", **kw)
    s = Spec(campaign_id="t")
    s.apply(SpecRevision(new_aims=[aim], new_objectives=[obj]))
    return s, aim, obj


def test_spec_is_append_only_and_delete_is_a_flag():
    """DELETED is a signal, not a removal.

    The Planner reads it to find pending Tasks no live objective wants any more, so removing
    the record would remove the reason its orphans are cancellable - and `superseded_by` is
    what lets a reader follow a substitution instead of finding a hole.
    """
    s, _, obj = _spec_with_one_objective()
    s.apply(SpecRevision(deleted=[obj.id], superseded_by={obj.id: "o-replacement"}))

    assert obj.id in s.objectives, "a deleted objective must still be on the record"
    assert s.objectives[obj.id].status is ObjectiveStatus.DELETED
    assert s.objectives[obj.id].superseded_by == "o-replacement"
    assert s.generation == 2, "each revision advances the generation"


def test_spec_complete_requires_every_objective_satisfied_or_deleted():
    """The Listener's stop condition, and why an empty Spec terminates immediately."""
    s, _, obj = _spec_with_one_objective()
    assert not s.complete()

    s.apply(SpecRevision(status_changes={obj.id: ObjectiveStatus.DEFERRED}))
    assert not s.complete(), "DEFERRED is open: it wants work it cannot have yet"

    s.apply(SpecRevision(status_changes={obj.id: ObjectiveStatus.SATISFIED}))
    assert s.complete()

    assert Spec().complete(), (
        "an empty Spec is complete - that is what makes a Specifier which declines to "
        "specify anything stop the campaign, with no special case elsewhere")


def test_ready_excludes_objectives_with_unsatisfied_dependencies():
    """Blocked work is DEFERRED, never dropped - which is what the Reviewer accepts."""
    aim = Aim()
    first = SpecObjective(aim=aim.id)
    second = SpecObjective(aim=aim.id, depends_on=[first.id])
    s = Spec()
    s.apply(SpecRevision(new_aims=[aim], new_objectives=[first, second]))

    assert [o.id for o in s.ready()] == [first.id]
    assert [o.id for o in s.blocked()] == [second.id]
    assert len(s.open_objectives()) == 2, "blocked work is still open work"

    s.apply(SpecRevision(status_changes={first.id: ObjectiveStatus.SATISFIED}))
    assert [o.id for o in s.ready()] == [second.id]


def test_independent_aims_keep_their_order_and_a_cycle_is_an_error():
    """Hierarchy is `parent`; execution order is `depends_on`. They are separate claims."""
    a, b = Aim(), Aim()
    c = Aim(depends_on=[a.id, b.id])
    s = Spec()
    s.apply(SpecRevision(new_aims=[a, b, c]))
    order = s.aim_order()
    assert order.index(c.id) > max(order.index(a.id), order.index(b.id))
    assert order[:2] == [a.id, b.id], "independent aims keep insertion order"

    loop_a = Aim()
    loop_b = Aim(depends_on=[loop_a.id])
    loop_a.depends_on = [loop_b.id]
    cyc = Spec()
    cyc.apply(SpecRevision(new_aims=[loop_a, loop_b]))
    with pytest.raises(ValueError, match="cycle among aims"):
        cyc.aim_order()


def test_satisfaction_rule_reuses_objective_satisfied_by():
    """One implementation of "acceptable", shared with the Pareto front.

    Two would be how a threshold quietly comes to mean one thing to the front and another to
    the Listener - including the `None -> False` case, which is the one that matters when a
    tool omitted a metric it could not read.
    """
    rule = SatisfactionRule(kind="metric_in_range", metric="sc_rmsd", max=3.0)
    ref = Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0)
    for v in (None, 2.9, 3.0, 3.1, -1.0):
        assert rule.holds_for_value(v) is ref.satisfied_by(v), f"disagreed on {v!r}"

    assert SatisfactionRule(kind="metric_present", metric="x").holds_for_value(0.0) is True
    assert SatisfactionRule(kind="metric_present", metric="x").holds_for_value(None) is False


def test_a_stage_answers_every_objective_by_a_task_or_a_deferral():
    """`covered` is what the Reviewer's coverage gate checks against."""
    stage = Stage(
        tasks=[TaskMapping(task_id="t1", tool="mock_generate", objectives=["o1", "o2"]),
               TaskMapping(task_id="t2", tool="mock_fold", objectives=["o3"],
                           directive=TaskDirective.CANCEL)],
        deferrals=[Deferral(objective="o4", reason="waits on o1")])
    assert stage.covered == {"o1", "o2", "o4"}, "a CANCEL task covers nothing"
    assert stage.tools == ["mock_generate"]


def test_stage_identity_is_not_graph_shape():
    """ADR 0003 binds the trust interlock to graph SHAPE, so a Stage must add nothing to it.

    `TaskGraph.pattern_signature()` hashes tools and their dependency tools and nothing else.
    This asserts the inputs: two Stages differing only in identity, generation, attempt,
    rationale and deferrals present the same (tool, inputs) sequence, so they cannot hash
    differently however `compose_stage` is written. Backlog A10 is the standing proof of the
    cost of getting this wrong - replica multiplicity did leak into that hash, and width-4
    consequently can never earn trust under a realistic budget.
    """
    def shape(st):
        return [(t.tool, sorted(t.inputs.items()), t.lineage) for t in st.runs]

    tasks = [TaskMapping(task_id="t1", tool="mock_generate"),
             TaskMapping(task_id="t2", tool="mock_fold", inputs={"sequences": "t1.designs"})]
    first = Stage(tasks=tasks, spec_generation=1, attempt=0)
    second = Stage(tasks=tasks, spec_generation=47, attempt=3, rationale="re-planned",
                   deferrals=[Deferral(objective="o9")], cancels=["t-old"])

    assert first.id != second.id
    assert shape(first) == shape(second)


def _outcome(run_id="r0001", nodes=("n1",), metrics=None, task_id="t1"):
    return RunOutcome(
        run_id=run_id, graph_id="g1", state=RunState.DONE, nodes=list(nodes),
        tasks=[TaskOutcome(task_id=task_id, tool="mock_fold", metrics=metrics or {},
                           outputs={"complex": ArtifactRef(type=ArtifactType.COMPLEX,
                                                           value="pdb")})])


def test_the_data_registry_records_what_arrived_and_who_produced_it():
    """Per-task attribution, not a merged view.

    Reading `RunOutcome.tasks` rather than its merged metrics is what makes a per-Task
    validation table and a per-stage pass rate computable from this registry later; a merged
    dict cannot say which tool reported a number.
    """
    reg = DataRegistry()
    new = reg.ingest(_outcome(metrics={"plddt": 0.81}))
    kinds = {d.kind for d in new}
    assert kinds == {DatumKind.NODE, DatumKind.METRIC, DatumKind.ARTIFACT}
    assert reg.nodes() == ["n1"]
    assert [d.from_task for d in reg.metrics("plddt")] == ["t1"]
    assert reg.seq == 1, "the cursor advances once per absorption, not once per datum"


def test_a_metric_the_tool_could_not_read_is_absent_rather_than_zero():
    """Decision 0013's rule, seen from the Listener's side.

    An adapter omits a metric it could not read, so a non-finite value must not count as
    evidence that an objective is satisfied.
    """
    reg = DataRegistry()
    reg.ingest(_outcome(metrics={"plddt": float("nan")}))
    assert reg.metrics("plddt") == []
    assert not reg.satisfies(SatisfactionRule(kind="metric_present", metric="plddt"))


def test_satisfaction_treats_n_as_a_threshold():
    """`n: 10` is the ten-distinct-designs shape: at least n, not the nth."""
    reg = DataRegistry()
    for i in range(3):
        reg.ingest(_outcome(run_id=f"r{i}", nodes=(f"n{i}",),
                            metrics={"plddt": 0.8}, task_id=f"t{i}"))
    rule = SatisfactionRule(kind="metric_in_range", metric="plddt", min=0.75, n=3)
    assert reg.satisfies(rule)
    assert not reg.satisfies(rule.model_copy(update={"n": 4}))
    assert reg.satisfies(SatisfactionRule(kind="count", n=3))
    assert reg.satisfies(SatisfactionRule(kind="artifact_present",
                                          port=ArtifactType.BACKBONE, n=3)), \
        "a Complex satisfies a Backbone requirement, so the unification rule applies here too"


def test_a_future_is_a_record_and_is_settled_by_ingestion():
    """No awaitable lives in the registry: the Listener and the work are in different
    processes, and completion arrives through `as_completed` rather than through a future."""
    reg = DataRegistry()
    reg.expect(TaskFuture(task_id="t1", run_id="r0001", expected_metrics=["plddt"]))
    assert [f.task_id for f in reg.pending()] == ["t1"]
    reg.ingest(_outcome(metrics={"plddt": 0.9}))
    assert reg.pending() == []
    assert reg.futures["t1"].settled, "the record is kept, not dropped"


# ---------------------------------------------------------------------------
# Measured cost, walltime, burn and commitments (phase 5).
# ---------------------------------------------------------------------------

def test_an_undeclared_walltime_limit_never_refuses_anything():
    """Zero-risk by construction, which is why the dimension is additive.

    `remaining` returns `inf` for an undeclared dimension and `exhausted()` iterates `limits`
    only, so every campaign that never mentions wall clock behaves byte-identically.
    """
    led = BudgetLedger(limits={"gpu_hours": 1.0})
    assert led.walltime is None
    assert not led.would_exceed_walltime(10_000_000.0)
    assert led.remaining("not_a_dimension") == float("inf")
    assert led.exhausted() == []


def test_remaining_walltime_is_the_limit_less_elapsed():
    started = datetime.now(timezone.utc) - timedelta(seconds=100)
    led = BudgetLedger(walltime=Walltime(started_at=started, limit_s=150.0))
    assert 99 <= led.walltime.elapsed_s <= 102
    assert 48 <= led.walltime.remaining_s <= 51
    assert led.would_exceed_walltime(60.0), "60s more does not fit in ~50s"
    assert not led.would_exceed_walltime(10.0)


def test_burn_rate_is_measured_not_declared():
    """A rate with no measurement behind it is a guess.

    The one thing it must not be is the declared estimate in new units: those figures sit
    2.25x-69x above measurement on purpose, because they feed gates that REFUSE graphs.
    """
    started = datetime.now(timezone.utc) - timedelta(seconds=100)
    led = BudgetLedger(limits={"gpu_hours": 10.0},
                       walltime=Walltime(started_at=started, limit_s=1000.0))
    assert led.burn_rate().per_s == {}, "nothing settled yet, so no rate exists"

    led.charge({"gpu_hours": 2.0})
    rate = led.burn_rate()
    assert 0.019 <= rate.per_s["gpu_hours"] <= 0.021, rate.per_s
    assert rate.measured_over_s > 0
    # And a projection is that rate over a horizon, not a re-reading of the estimate.
    assert 1.9 <= led.project("gpu_hours", 100.0) <= 2.1


def test_committed_is_the_sum_over_pending_stages():
    led = BudgetLedger(limits={"gpu_hours": 10.0})
    led.commit(Commitment(stage_id="s1", projected={"gpu_hours": 1.5}))
    led.commit(Commitment(stage_id="s2", projected={"gpu_hours": 2.0}))
    assert led.committed("gpu_hours") == 3.5
    led.release_commitment("s1")
    assert led.committed("gpu_hours") == 2.0
    assert led.committed("cpu_hours") == 0.0


def test_a_commitment_over_its_cap_is_reported_rather_than_silently_kept():
    """The outline's "maximum allocation commitment": the smaller of a workflow maximum and a
    per-stage hard limit. Exceeding it is a fact the caller has to be told, not one to drop."""
    led = BudgetLedger(limits={"gpu_hours": 10.0})
    blown = led.commit(Commitment(stage_id="s1", projected={"gpu_hours": 5.0},
                                  cap={"gpu_hours": 2.0}))
    assert blown == ["gpu_hours"]
    assert "s1" in led.commitments, "it is recorded, so the overrun is visible afterwards"


def test_reserving_and_settling_are_untouched_by_the_new_dimensions():
    """`reserve`/`settle`/`release` are on every admission path.

    Rewriting them would make budget refusals untestable against recorded Delta behaviour
    (backlog A11), so walltime, burn and commitments are layered BESIDE them.
    """
    led = BudgetLedger(limits={"gpu_hours": 1.0},
                       walltime=Walltime(limit_s=10.0))
    led.commit(Commitment(stage_id="s1", projected={"gpu_hours": 0.9}))
    assert led.reserve({"gpu_hours": 0.9}, "r1") == [], \
        "a commitment is bookkeeping, not a hold - it must not consume `available`"
    assert led.would_exceed({"gpu_hours": 0.2}) == ["gpu_hours"]
    led.settle("r1", {"gpu_hours": 0.4})
    assert led.spent == {"gpu_hours": 0.4} and led.holds == {}
