"""The Spec: the Goal mapped onto what the Toolkit can produce.

The planning artifact this architecture turns on. A `Spec` is a set of atomic
`SpecObjective`s organised into hierarchical `Aim`s; Aims carry the dependency structure, so
Aims that depend on nothing run in parallel. The Goal is fixed at call time (`core/goal.py`);
**the Spec may change at runtime**, which is what the Specifier exists to do.

Three design points, each of which was a decision rather than a default:

**Append-only, and DELETED is a flag.** A revision appends objectives and flips statuses; it
never removes a record. `ObjectiveStatus.DELETED` is the signal the Planner reads to find
pending Tasks that no live objective wants any more, so deleting the objective would delete the
reason its orphans are cancellable. Same discipline as `CampaignTree`, for the same reason: the
history is the part you cannot reconstruct.

**`SpecObjective` is not `pareto.Objective`.** Decision 0012 pins the word "objective" to a
declaration against a property *name*, and every campaign YAML uses it that way, so that type
keeps the name. A `SpecObjective` is a unit of *work to be planned* and refers to ranking
objectives by name through `targets`. A generated objective is therefore still a declaration
against a property name, and a measurement arriving later still supersedes against that name
through `CampaignTree.ingest_measurement`.

**A Stage contributes nothing to the pattern signature.** `TaskGraph.pattern_signature()` is
shape-only, and ADR 0003 binds the trust interlock to it. Stage ids, generations, attempt
counts, objective ids and deferrals are all excluded by construction - they are not graph shape
- so every trust record a site has already earned stays valid. Backlog A10 is the standing
proof of what happens when something non-structural leaks into that hash.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .ids import counter
from .pareto import Objective
from .types import ArtifactType

new_objective_id = counter("o")
new_aim_id = counter("a")
new_stage_id = counter("s")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ObjectiveStatus(str, Enum):
    """Where one objective stands. The only mutable field on a `SpecObjective`."""

    OPEN = "open"            # wants planning
    PLANNED = "planned"      # a Task is mapped to it and in flight
    DEFERRED = "deferred"    # cannot be planned yet: a dependency is unsatisfied
    SATISFIED = "satisfied"  # its satisfaction rule holds against realized data
    DELETED = "deleted"      # superseded; its orphan Tasks are cancellable
    FAILED = "failed"        # planned, ran, and cannot be satisfied by retrying

    @property
    def is_open(self) -> bool:
        """Still wants work. DEFERRED is open: it wants work it cannot have yet."""
        return self in (ObjectiveStatus.OPEN, ObjectiveStatus.DEFERRED)

    @property
    def is_terminal(self) -> bool:
        return self in (ObjectiveStatus.SATISFIED, ObjectiveStatus.DELETED,
                        ObjectiveStatus.FAILED)


class TaskDirective(str, Enum):
    RUN = "run"
    CANCEL = "cancel"


class StageStatus(str, Enum):
    CANDIDATE = "candidate"  # the Planner emitted it; the Reviewer has not ruled
    REJECTED = "rejected"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    SETTLED = "settled"


class SatisfactionRule(BaseModel):
    """When one objective counts as met.

    `metric_in_range` delegates to `Objective.satisfied_by` rather than re-implementing the
    comparison: two implementations of "is this value acceptable" is how a threshold ends up
    meaning one thing to the front and another to the Listener.
    """

    kind: str = "metric_in_range"   # metric_in_range | metric_present | artifact_present | count
    metric: str | None = None
    min: float | None = None
    max: float | None = None
    port: ArtifactType | None = None
    n: int = 1

    @property
    def is_bounded(self) -> bool:
        """Whether this rule expresses a condition at all.

        `metric_in_range` with neither bound set expresses nothing, and must not be read as
        "already satisfied". That distinction is load-bearing rather than pedantic: a campaign
        objective with a direction and no bound - `total_score: minimize`, the common case - is
        an optimisation target, never a finish line. `Objective.satisfied_by` answers True for
        any non-None value when both bounds are None, which is correct for *ranking* (nothing
        is pruned) and wrong for *satisfaction*, so the two readings part company here rather
        than in a caller.
        """
        return self.min is not None or self.max is not None

    def as_objective(self) -> Objective | None:
        """The ranking objective this rule is equivalent to, for a bounded `metric_in_range`."""
        if self.kind != "metric_in_range" or self.metric is None or not self.is_bounded:
            return None
        # Direction is irrelevant to `satisfied_by`, which reads min/max only.
        return Objective(name=self.metric, direction="minimize", min=self.min, max=self.max)

    def holds_for_value(self, value: float | None) -> bool:
        """For the two value-shaped kinds. Artifact and count kinds need the registry."""
        if self.kind == "metric_present":
            return value is not None
        if self.kind != "metric_in_range" or self.metric is None:
            raise ValueError(f"{self.kind!r} cannot be decided from a value alone")
        obj = self.as_objective()
        return obj.satisfied_by(value) if obj is not None else False


class SpecObjective(BaseModel):
    """One atomic thing the campaign is trying to produce."""

    id: str = Field(default_factory=new_objective_id)
    aim: str
    statement: str = ""

    #: The Toolkit output space this objective maps the Goal onto - what kind of artifact
    #: satisfying it produces. The Planner selects a Task by unifying these with a tool's
    #: declared output ports, which is why they are types and not prose.
    outputs: list[ArtifactType] = Field(default_factory=list)

    #: Ranking objectives this informs, by NAME (decision 0012). Never a source, never a tool.
    targets: list[str] = Field(default_factory=list)

    satisfied_when: SatisfactionRule = Field(default_factory=SatisfactionRule)

    #: Other `SpecObjective` ids that must be SATISFIED before this one can be planned. An
    #: objective whose dependencies are unmet is DEFERRED, not refused.
    depends_on: list[str] = Field(default_factory=list)

    status: ObjectiveStatus = ObjectiveStatus.OPEN

    #: Which revision introduced it, and what replaced it. `superseded_by` is set when the
    #: objective is DELETED in favour of another, so a reader can follow the substitution
    #: rather than finding a hole.
    generation: int = 0
    superseded_by: str | None = None

    #: The `DesignNode` this objective is about, when it is about one - a refinement of an
    #: existing candidate rather than a fresh draw. This is what keeps ADR 0004's
    #: non-destructive backtracking reachable from the Spec: an objective can name any earlier
    #: node, so re-specifying never costs the population.
    parent_node: str | None = None

    created_at: datetime = Field(default_factory=_now)


class Aim(BaseModel):
    """A group of objectives, and the unit of dependency and parallelism.

    An Aim with an empty `depends_on` is independent and may run alongside every other
    independent Aim. The hierarchy is `parent`; the execution order is `depends_on`. They are
    separate on purpose - "part of the same effort" and "must wait for" are different claims,
    and collapsing them makes every sub-aim serial.
    """

    id: str = Field(default_factory=new_aim_id)
    statement: str = ""
    parent: str | None = None
    objectives: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class SpecRevision(BaseModel):
    """One append to the Spec. What the Specifier authors; the executor applies it."""

    generation: int = 0
    new_aims: list[Aim] = Field(default_factory=list)
    new_objectives: list[SpecObjective] = Field(default_factory=list)
    #: Objective ids to mark DELETED. Never removed - the flag is what makes orphan Tasks
    #: cancellable downstream.
    deleted: list[str] = Field(default_factory=list)
    #: Objective id -> new status, for transitions a Specifier decides (SATISFIED, FAILED).
    status_changes: dict[str, ObjectiveStatus] = Field(default_factory=dict)
    #: Objective id -> the id that replaces it, recorded alongside a deletion.
    superseded_by: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.new_aims or self.new_objectives or self.deleted
                    or self.status_changes)


class Spec(BaseModel):
    """The Goal mapped onto the Toolkit's output space. Append-only; mutated via revisions."""

    campaign_id: str = ""
    generation: int = 0
    aims: dict[str, Aim] = Field(default_factory=dict)
    objectives: dict[str, SpecObjective] = Field(default_factory=dict)

    # -- reading -------------------------------------------------------------
    def open_objectives(self) -> list[SpecObjective]:
        """Everything still wanting work, DEFERRED included."""
        return [o for o in self.objectives.values() if o.status.is_open]

    def ready(self) -> list[SpecObjective]:
        """Open objectives whose dependencies are all SATISFIED - plannable now."""
        return [o for o in self.open_objectives() if self._deps_met(o)]

    def blocked(self) -> list[SpecObjective]:
        """Open objectives that are not ready. What a Planner must DEFER rather than drop."""
        return [o for o in self.open_objectives() if not self._deps_met(o)]

    def _deps_met(self, o: SpecObjective) -> bool:
        for dep in o.depends_on:
            d = self.objectives.get(dep)
            if d is None or d.status is not ObjectiveStatus.SATISFIED:
                return False
        return True

    def complete(self) -> bool:
        """The Listener's stop condition: nothing is open any more.

        An empty Spec is complete, which is deliberate - it is what makes a Specifier that
        declines to specify anything terminate the campaign immediately, with no special case
        anywhere else.
        """
        return not self.open_objectives()

    def aim_order(self) -> list[str]:
        """Aim ids in dependency order. Independent Aims keep their insertion order.

        Raises on a cycle, in the same spirit as `TaskGraph.topo_order`: a cyclic Aim graph is
        a Specifier bug, and discovering it as a campaign that never plans anything is worse
        than discovering it here.
        """
        pending = {a.id: set(a.depends_on) & set(self.aims) for a in self.aims.values()}
        out: list[str] = []
        while pending:
            free = [aid for aid, deps in pending.items() if not deps - set(out)]
            if not free:
                raise ValueError(f"cycle among aims: {sorted(pending)}")
            for aid in free:
                out.append(aid)
                del pending[aid]
        return out

    def objectives_of(self, aim_id: str) -> list[SpecObjective]:
        return [o for o in self.objectives.values() if o.aim == aim_id]

    # -- writing -------------------------------------------------------------
    def apply(self, rev: SpecRevision) -> Spec:
        """Apply one revision in place and return self. APPEND-ONLY.

        Synchronous and `await`-free by construction: the executor is the only caller, and
        every mutating block it owns must stay free of suspension points or an observation can
        be taken half way through one. Nothing here can suspend, so nothing here can tear.
        """
        self.generation += 1
        for aim in rev.new_aims:
            self.aims[aim.id] = aim
        for obj in rev.new_objectives:
            obj.generation = self.generation
            self.objectives[obj.id] = obj
            aim = self.aims.get(obj.aim)
            if aim is not None and obj.id not in aim.objectives:
                aim.objectives.append(obj.id)
        for oid, status in rev.status_changes.items():
            if (o := self.objectives.get(oid)) is not None:
                o.status = status
        for oid in rev.deleted:
            if (o := self.objectives.get(oid)) is not None:
                o.status = ObjectiveStatus.DELETED
                if (sup := rev.superseded_by.get(oid)) is not None:
                    o.superseded_by = sup
        return self


class Deferral(BaseModel):
    """Why one objective could not be planned this round.

    A Deferral is an answer, not a failure: the Reviewer accepts it in place of a Task, which
    is what lets a Stage cover every open objective without inventing work for the ones whose
    inputs do not exist yet.
    """

    objective: str
    reason: str = ""
    waiting_on: list[str] = Field(default_factory=list)


class TaskMapping(BaseModel):
    """One Task, and the objectives it serves.

    `objectives` is a list because one Task can serve several - and that is exactly what makes
    cancellation decidable: a pending Task is an orphan only when *every* objective mapped to
    it is DELETED.
    """

    task_id: str
    objectives: list[str] = Field(default_factory=list)
    tool: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    #: port -> "<task_id>.<out_port>" within this same Stage. Typed wiring, resolved by the
    #: composer and - from phase 4 - honoured by the dispatcher rather than re-keyed
    #: positionally.
    inputs: dict[str, str] = Field(default_factory=dict)
    lineage: int = 0
    seed: int | None = None
    directive: TaskDirective = TaskDirective.RUN


class Stage(BaseModel):
    """A candidate set of Objective:Task mappings, as the Planner emits it.

    Carries its own identity so it can be reviewed, rejected, re-planned and tracked - which a
    bare list of tool ids at list indices could not be. None of that identity reaches the
    pattern signature; see the module docstring.
    """

    id: str = Field(default_factory=new_stage_id)
    spec_generation: int = 0
    attempt: int = 0
    tasks: list[TaskMapping] = Field(default_factory=list)
    deferrals: list[Deferral] = Field(default_factory=list)
    #: Task ids to cancel: pending Tasks whose every objective is now DELETED.
    cancels: list[str] = Field(default_factory=list)
    estimate: dict[str, float] = Field(default_factory=dict)
    commitment: dict[str, float] = Field(default_factory=dict)
    graph_id: str = ""
    status: StageStatus = StageStatus.CANDIDATE
    rationale: str = ""
    #: The design node every task in this Stage refines, when it refines one. On the Stage
    #: rather than per task so a Planner need not repeat it; phase 8 makes it executable by
    #: feeding the parent's artifacts into the chain.
    parent_node: str | None = None

    @property
    def runs(self) -> list[TaskMapping]:
        return [t for t in self.tasks if t.directive is TaskDirective.RUN]

    @property
    def covered(self) -> set[str]:
        """Objective ids this Stage answers, by a Task or by a Deferral."""
        out = {o for t in self.runs for o in t.objectives}
        return out | {d.objective for d in self.deferrals}

    @property
    def tools(self) -> list[str]:
        return [t.tool for t in self.runs]

    @property
    def lineages(self) -> int:
        return len({t.lineage for t in self.runs}) or 1


class TaskState(str, Enum):
    """Where one Task stands. Task granularity, not run granularity."""

    PENDING = "pending"        # in an approved Stage, not yet dispatched
    DEPLOYED = "deployed"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"      # every objective it served is DELETED, and it had started

    @property
    def is_terminal(self) -> bool:
        return self in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED)

    @property
    def is_cancellable(self) -> bool:
        """Only work that has not started can be reclaimed.

        Cancellation is advisory once a callable is running: the concurrent backend's
        `Future.cancel()` returns False and asyncflow discards that answer, and `impress`'s
        own `kill_parent` cancels a pipeline's asyncio Task without reaching the backend. So
        this is the honest set, and a RUNNING task marked for cancellation is recorded as
        ORPHANED rather than pretended to be CANCELLED.
        """
        return self is TaskState.PENDING


class TaskRecord(BaseModel):
    """One Task, durably, keyed by a campaign-global id.

    Everything durable was run-keyed before this: the job ledger folds on `job_id`, per-task
    data existed only nested inside a `RunOutcome`, and a task id was `r{r}_s{i}_{tool}` -
    unique only within one `TaskGraph`. So nothing could be deferred, re-planned or cancelled
    *as work*, and asyncflow cannot help: it tags tasks with `workflow_id` and exposes no way
    to look one up by it, which is why the caller's own table is the only index there has ever
    been.

    Holds state and accounting, never metrics. Metrics stay in the run's outcome, and
    `outcome_ref` points at it - two places claiming to know a number is how they come to
    disagree.
    """

    task_id: str
    campaign_id: str = ""
    stage_id: str = ""
    run_id: str = ""
    graph_node_id: str = ""
    tool: str = ""
    objectives: list[str] = Field(default_factory=list)
    state: TaskState = TaskState.PENDING
    directive: TaskDirective = TaskDirective.RUN
    deployed_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    #: Projected at admission, settled on completion. Phase 5 adds the measured figures.
    commitment: dict[str, float] = Field(default_factory=dict)
    outcome_ref: str = ""

    def orphaned_by(self, spec: Spec) -> bool:
        """Whether every objective this Task serves is now DELETED.

        *Every*, not any - which is why `objectives` is a list. A Task serving one live
        objective and three dead ones is still wanted, and with a single objective per task
        the question could not be asked at all.
        """
        if not self.objectives:
            return False
        return all(
            (o := spec.objectives.get(oid)) is not None
            and o.status is ObjectiveStatus.DELETED
            for oid in self.objectives)
