"""Turn an abstract ExperimentIntent into a concrete typed DAG.

The composer is the only component that knows how to wire tools together. Policies emit
intent; the composer emits graphs. That separation is what keeps policies swappable.
"""
from __future__ import annotations

import hashlib

from ..core.decision import ExperimentIntent
from ..core.spec import Stage
from ..core.types import Pattern
from ..tools.registry import Registry
from .graph import TaskGraph, TaskNode


def _replica_seed(run_label: str, lineage: int, salt: str = "") -> int:
    """A distinct, reproducible draw per replica lineage.

    `replicas: N` means N INDEPENDENT lineages, but the composer gives every chain the
    same parameters - so independence has to come from somewhere else. Until now it came
    from nothing: it was an accident of the mock tools seeding on a task id that happened
    to differ. A real tool taking an explicit seed would have produced N identical
    designs, collapsing N lineages into one.

    Derived from the run label rather than a random source so that two concurrent
    submissions of the same intent differ, while a replayed campaign reproduces exactly.

    **The salt is what makes two CAMPAIGNS differ** (backlog G7). Run labels restart at
    `r0001` in every job, so without one every job that ever ran drew from the same pool: 17
    designs on record turned out to be 5 independent folds sampled about three times each.
    Seeding fixes length and biases fold - same-seed pairs measured median TM 0.82 against
    0.28 across seeds - and does not reproduce coordinates (median Ca RMSD 2.4 A), so this is
    variance *reduction* rather than exact pairing. It is recorded in `campaign` provenance and
    in the job manifest, because a draw nobody can name is a draw nobody can repeat.
    """
    h = hashlib.sha256(f"{salt}/{run_label}/{lineage}".encode()).hexdigest()
    return int(h[:8], 16)


class Composer:
    def __init__(self, reg: Registry, seed_salt: str = ""):
        self.reg = reg
        #: Distinguishes this campaign instance's draws from every other's. Empty reproduces
        #: the pre-G7 behaviour exactly, which is what keeps every recorded figure comparable.
        self.seed_salt = seed_salt

    def compose(self, intent: ExperimentIntent, run_label: str = "") -> TaskGraph:
        """Build `intent.replicas` INDEPENDENT chains through the declared stages.

        A replica is a whole lineage, not a fan-out at stage 0 that funnels back into a
        single downstream node - that would make N candidates collapse into one.

        P6 tools are INLINED, never added as scheduled nodes (Part B doc 05 gate 4).
        """
        g = TaskGraph(intent_goal=intent.goal)
        stages = [t for t in intent.stages
                  if self.reg.get(t).pattern is not Pattern.P6]
        for r in range(max(1, intent.replicas)):
            prev: str | None = None
            for i, tool_id in enumerate(stages):
                spec = self.reg.get(tool_id)
                tid = f"r{r}_s{i}_{tool_id}"
                inputs: dict[str, str] = {}
                deps: list[str] = []
                if prev is not None:
                    deps = [prev]
                    src_spec = self.reg.get(g.nodes[prev].tool)
                    for port, ps in spec.inputs.items():
                        match = next((op for op, os_ in src_spec.outputs.items()
                                      if os_.type.unifies_with(ps.type)), None)
                        if match:
                            inputs[port] = f"{prev}.{match}"
                g.add(TaskNode(id=tid, tool=tool_id,
                               params=dict(intent.params.get(tool_id, {})),
                               deps=deps, inputs=inputs,
                               node_id=intent.parent_node, lineage=r,
                               seed=_replica_seed(run_label or g.id, r, self.seed_salt)))
                prev = tid
        return g

    def compose_stage(self, stage: Stage, run_label: str = "") -> TaskGraph:
        """Build the DAG for a Stage's Objective:Task mappings.

        Where `compose` derives the shape from an ordered tool list and a replica count, this
        is handed the mappings directly - so a Planner can express work `compose` cannot: two
        independent Aims in one Stage, a chain that branches, or a task serving several
        objectives.

        Three things it must preserve, because the rest of the system is built on them:

        * **Shape only, in the signature.** Stage id, generation, attempt, rationale and
          deferrals are not graph shape and never reach `pattern_signature()`. Every trust
          record a site has earned stays valid; backlog A10 is the standing proof of what
          leaking something non-structural into that hash costs.
        * **Lineages stay independent.** A replica is a whole chain, not a fan-out that
          funnels back - and its seed comes from `_replica_seed`, unchanged, so a lineage that
          declares no seed still gets a distinct draw.
        * **P6 is inlined.** A scheduled P6 node is a composer bug (gate 4), so the mappings
          are filtered here exactly as `compose` filters the stage list.

        CANCEL mappings are not composed: a cancel is an instruction about work already
        deployed, not work to do.
        """
        g = TaskGraph(intent_goal=stage.rationale)
        runs = [m for m in stage.runs
                if self.reg.get(m.tool).pattern is not Pattern.P6]
        by_id = {m.task_id: m for m in runs}
        for mapping in runs:
            spec = self.reg.get(mapping.tool)
            deps: list[str] = []
            inputs: dict[str, str] = {}
            for port, ref in mapping.inputs.items():
                dep_id = ref.split(".", 1)[0]
                if dep_id in by_id:
                    deps.append(dep_id)
                    inputs[port] = ref
            # A mapping that named no inputs but follows another task in its own lineage is
            # the common linear case; wire it the way `compose` does, by type.
            if not deps:
                prior = [m for m in runs if m.lineage == mapping.lineage
                         and m.task_id != mapping.task_id
                         and runs.index(m) < runs.index(mapping)]
                if prior:
                    prev = prior[-1]
                    src = self.reg.get(prev.tool)
                    for port, ps in spec.inputs.items():
                        match = next((op for op, os_ in src.outputs.items()
                                      if os_.type.unifies_with(ps.type)), None)
                        if match:
                            inputs[port] = f"{prev.task_id}.{match}"
                    if inputs:
                        deps = [prev.task_id]
            g.add(TaskNode(id=mapping.task_id, tool=mapping.tool,
                           params=dict(mapping.params), deps=deps, inputs=inputs,
                           node_id=self._parent_of(mapping, stage),
                           lineage=mapping.lineage,
                           seed=mapping.seed
                           if mapping.seed is not None
                           else _replica_seed(run_label or g.id, mapping.lineage,
                                              self.seed_salt)))
        return g

    @staticmethod
    def _parent_of(mapping, stage: Stage) -> str | None:
        """The design node this task refines, if its Stage says so.

        Carried from the Stage rather than from the mapping so a Planner does not have to
        repeat it per task. Phase 8 is what makes it executable - today it labels lineage, and
        feeding a parent's artifacts into a child chain is that phase's work.
        """
        del mapping
        return getattr(stage, "parent_node", None)
