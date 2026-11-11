<!-- Full approved plan, saved for reference. Phases are executed in branch groups:
     p0-p3, p4-p6, p7-p9, p10-p11. Each group is one readable PR. -->

# IMPRESS-A: phased refactor to the Spec/Planning/Execution architecture, and the four-arm reasoner experiment

## Context

`agent/` (package `impress_a`) today implements an autonomous protein-design campaign as
**one loop with a pluggable decision function**: `SequentialPolicyDriver` asks a policy
`decide(obs)`, the policy returns an abstract `ExperimentIntent`, and `CampaignExecutor`
composes it into a DAG, runs it through five gates and a trust interlock, dispatches it, and
absorbs the result into an append-only Pareto tree. It works — one real six-stage Delta
campaign has completed (job 22692304) and the trusted path held for three consecutive cycles
(job 22728140).

The target architecture splits that single decision point into two cooperating control loops
over an execution loop: a **Spec Loop** (Listener + Specifier) turning a fixed caller **Goal**
into a mutable **Spec** of atomic **Objectives** organised into hierarchical **Aims**; a
**Planning Loop** (Planner + Reviewer + Deployer) mapping Objectives onto **Tasks**, emitting
a candidate **Stage**, validating coverage and budget, and deploying it; and an execution loop
registering each Task for backend execution.

Three things motivate it. The current design has **no representation of what the campaign is
trying to achieve** — `goal` is free text no reasoner parses, `objectives` is a flat
caller-supplied list with no state, hierarchy, dependencies or satisfaction tracking. There is
**no Task-level identity** — everything durable is run-keyed, task ids are unique only within
one graph, so nothing can be deferred, re-planned or cancelled *as work*. And **budget is
declared rather than measured** — per-task cost is a static copy of the tool spec, nothing
times a task, so the architecture's burn rates and remaining-walltime accounting have no data
source.

The intended outcome is that the four reasoners become comparable at two distinct seams,
specification and planning, so a multi-arm experiment can attribute an outcome difference to
one or the other rather than to "the decision function" as a whole.

## Decisions taken before planning

| | Decision | Consequence |
|---|---|---|
| Engine | **Reuse `impress` directly.** The execution loop is `ImpressBasePipeline` + `ImpressManager`. | `impress` becomes a dependency of `agent/pyproject.toml`. `agent/` still must not *modify* top-level `src/`, `tests/`, `examples/`, `docs/` or root packaging. |
| Reasoners | **One model, two halves.** Each of A/B/C/D supplies a Specifier half and a Planner half behind two typed interfaces, selected by one `--model` flag. | The four-arm comparison stays one-variable; `--specifier X --planner Y` stays reachable. |
| Migration | **Strangler, then delete.** | Every phase ends with `pytest tests -q` green and `impress-a run campaigns/mock-stabilize.yaml --model D` working. |
| Experiment | **Smoke first, then four 1-node / 4 h arms.** | Matches the sibling example's measured shape. |
| Thresholds | **Close G4 *and* G5 as a gating phase.** | The reference `PROD` thresholds become IMPRESS-A acceptance gates; `interaction_energy` gets implemented; each arm steers by the target it is judged on. |
| LLM path | **Port the sibling's OpenAI-compatible client** (`examples/agentic_small_molecule_binding/llm.py` + `models.yaml`). | One request shape across every model; carries the measured caveat that Opus declines this workload through that endpoint while Sonnet answers normally. |
| Endpoint | **Ten is the target; the rate is the endpoint.** | Distinct passing designs per billed node-hour, plus time-to-Nth, so the comparison's validity does not depend on 4 h being enough. |
| Distinctness | **Exact sequence identity, plus a structural check.** | Clustered count is the headline; exact identity is the upper bound; a TM-score check makes draw-collapse visible. |
| Process split | **Two OS processes: control plane and execution.** The Spec Loop and Planning Loop are co-resident in a control process with its own event loop; the executor, Reviewer, Deployer, Runner and the single asyncflow engine are in an execution process. | Decouples decision-making from execution, which is where the measured blocking precedent is (job 22534628: a synchronous decision body took 67 % of wall clock, p99 56 s). One supervision boundary, not two. The two control loops are independent of execution but not of each other. |
| Supervision | **Execution drains, then stops and says so.** | On loss of the control process, in-flight Stages run to completion and are absorbed, no new Stage is admitted, and the campaign ends with a stop reason naming the lost process. Nothing is silently abandoned and no allocation is held idle waiting for a planner that is gone. |
| Asserted trust | **Build the user-facing shortcut — it does not exist today — and use it for both experiments.** A pre-loaded Toolkit of proven Tasks does not spend allocation re-earning trust at runtime. | New ledger event `asserted` plus `impress-a trust --assert`. Trust is asserted for the *known* shapes only; a shape a reasoner invents is still untrusted, which keeps the interlock meaningful for the thing it is for — and introduces one confound, flagged below. |
| Task validation | **Every Task is validated individually on real hardware in the smoke, before the multi-arm experiment**, via a new `impress-a validate-tasks`. | This is what *justifies* the trust assertion: asserting trust without it would be asserting trust on untested Tasks. It is also the only check shaped like the four defects that reached hardware. |
| Breadth | **Breadth comes from `replicas` *and* from a Tool's internal sampling.** Internal sampling is set to **8** on every Tool that supports batched sampling, **preferring one wide batch over several narrow ones** where a tool offers both. This overrules the standing "breadth is `replicas`, not internal N" ruling. | These models are tuned for batched output, so batch-of-1 wastes the GPU — a wide batch is close to sublinear in wall time where N serial batches is linear. **Strictly sequenced after the adapters stop keeping index `[0]` (Phase 8)**: set to 8 before that, it pays 8× and still yields one design. Declared `walltime_s` and `cost_model` must then be re-derived at the 8-sample setting, because those figures feed gates that *refuse* graphs. |

---

## The finding that reshapes the experiment

**The stated Goal is not reachable, and the binding constraint is not the allocation.** Two
mechanisms the reference pipeline uses to produce a 75-pLDDT fold do not exist in IMPRESS-A:

| Reference mechanism | `PROD` value | IMPRESS-A equivalent | Status |
|---|---|---|---|
| Partial-diffusion refinement loop | `num_refine_cycles: 2`, `rfd3_partial_t: 10.0` | `ExperimentIntent.parent_node` | **Absent.** `_absorb` sets `DesignNode.parent` and nothing feeds a parent's artifacts into a child chain. "Exploit a node" re-runs its *recipe*, not its *structure*. |
| Per-stage ensembling | `mpnn_ensemble_size: 10`, `diffusion_batch_size: 4` | `num_seqs`, `num_designs`, `diffusion_samples` | **Inert.** Every adapter keeps index `[0]`. Raising them costs GPU-hours and yields one design — which is why Phase 8 fixes the adapters *before* internal sampling goes to 8, and why the plan does not simply raise the numbers. |

The consequence is measurable on the only real data there is. Job 22692304 — the project's
best evidence, `6/6 tasks ok` — **fails `PROD` on two axes** (`fa_rep` 109.4 > 100,
`complex_plddt` 0.507 < 0.75) and is unscorable on a third (`interaction_energy` never
computed). Across all recorded runs `complex_plddt` is 0.426 / 0.486 / 0.507 against a 0.75
bound: **0 of 3**. The reference's median pLDDT of 94.4 is a product of the refinement loop,
which is why that is a mechanism and not bad luck.

Two consequences for this plan, both load-bearing:

1. **The refactor owes a phase the outline does not mention** — feeding a parent node's
   artifacts into a child chain, and selecting the best of an ensemble rather than `[0]`.
   Phase 8. Without it no arm can reach the Goal and the comparison measures reasoners
   steering an engine that cannot converge.
2. **The experiment is tiered.** T1 plumbing / T2 physics / T3 the full Goal. The primary
   endpoint is *distinct T2 designs per node-hour*; `C_T3` is reported as the Goal's literal
   answer with a pre-registered expectation of 0. Feasibility: `p* ≈ 0.06` is the threshold
   probability at which ten designs become reachable in a 4 h 1-node arm, and the best
   estimate is `p_T2 ≈ 0.06` (at the boundary, before the unmeasured `interaction_energy`
   factor) and `p_T3 ≤ 0.04`. Phase 8 is what moves those numbers.

---

## The constraint ledger

Recorded rulings, several bought with burned allocations. Honoured or explicitly amended.

**One engine, one loop — and what that does *not* constrain.**
`WorkflowEngine.__init__` captures the running loop and schedules `run-component` on exactly
it. An engine built on another loop looks healthy and dispatches nothing — every submit hangs
silently (jobs 22328172, 22328262, two full allocations). So there is **exactly one asyncflow
engine, on the execution process's loop**, and only
`exec/backend._construct_backend_sync` may be offloaded to a thread.

That constrains the *engine*, not the roles. `agent/plans/done/01-reasoner-decoupling.md`
saying "**`CampaignSession` is the process split; a second `WorkflowEngine` or a second event
loop is not**" means: separate at the session boundary, don't separate by spinning up a second
engine. A control process with its own loop, holding the Specifier and Planner and talking to
the executor over that session, contains no second engine and is the sanctioned configuration
— `control/session.py:48` `RemoteSession` already implements the whole `CampaignSession`
surface (`observe`, `submit`, `status`, `result`, `as_completed` over the event stream,
`inflight`, `cancel`, `backtrack`, `stop`) over an async httpx client, and
`tests/test_remote_session.py` drives a campaign from genuinely out of process and asserts the
same tree and front as in-process.

**Admission is synchronous, and that pins two roles to the execution process.** `dry_run`
instantiates task agents (`compose/validate.py:142-153`), so the gate chain must run where the
toolkit is installed. The **Reviewer and Deployer therefore live execution-side**. This fits
the outline rather than fighting it: `submit_run` already answers synchronously with
accept-plus-id or reject-plus-reason (202 / 409 over HTTP), which is exactly "review rejections
route back to the Planner for updates".

**The Spec has one author and one writer, and they are in different processes.** The Specifier
*authors* revisions; the executor *applies* them to its own replica in an `await`-free block,
and that replica is what the Reviewer's coverage gate checks against — **never the Planner's
own claim about what is open**, since not trusting that claim is the Reviewer's whole purpose.
Two consequences worth keeping: `specs` and `stages` provenance is written executor-side, which
preserves the property the experiment's scoring method depends on (provenance is written by the
executor, not by a reasoner); and a Planner cannot widen its own coverage by asserting a
smaller Spec.

**Role separation needs two operations in the core protocol, not in an adapter.** ADR 0007
forbids an adapter adding an operation the core lacks, so `submit_stage(stage)` and
`publish_spec(revision)` are added to `CampaignSession` **and** `CampaignControlPlane` in
Phase 3, before the split in Phase 7 needs them.

**Naming.** `WorkflowEngine` means `radical.asyncflow.WorkflowEngine` and nothing else (ADR
0001 collision). The outline's "Workflow Engine" is the **Runner**. The outline's "Objective"
is **`SpecObjective`**; `core/pareto.Objective` keeps its name as the metric target, because
ADR 0012 pins that word to a declaration against a property name and every campaign YAML uses
it that way. This is the one place the plan deviates from the outline's wording.

**No new top-level package.** Everything lands in `core/`, `policy/`, `runtime/`, `exec/`,
`tools/`, `cli/`, plus one new `analysis/`. `tests/test_layering.py::ALLOWED` therefore gains
exactly one row (`analysis: {core}`), and ADR 0010's own revisit trigger is not pulled.
Intra-`core` imports are invisible to the walker, so the Spec vocabulary can be several files
in `core/`.

**Trust survives.** `TaskGraph.pattern_signature()` (`compose/graph.py:51-61`) is shape-only.
**A `Stage` contributes nothing to it** — not its id, generation, attempt, objective ids or
deferrals — so every trust record under `$IMPRESS_A_TRUST_DIR/<gpu_api>.jsonl` stays valid.
Backlog A10 proves the hazard: because replica multiplicity already enters the signature,
width-4 can never earn trust under a 6.0 GPU-h budget. Corollary to record: a Stage holding
two independent Aims is a *wider shape*, hence a new signature with zero trust, running under
the 10 % provisional cap and one-instance-in-flight until promoted.

**Asserted trust: validated as absent, and the ledger cannot currently express it.**
There is **no user-facing way to assert trust**. The CLI has four subcommands
(`run`, `tools`, `models`, `preflight`) and none touches the ledger. The only existing path is
an in-process monkeypatch used at three test sites —
`mgr.trust.patterns[sig] = PatternRecord(signature=sig, trusted=True, clean_runs=3)`
(`tests/test_campaign.py:441`, `:628`, `tests/test_remote_session.py:102`). And the on-disk
vocabulary is only `seen | clean | failure` (`compose/interlock.py:_apply`), so **hand-writing
lines into the JSONL cannot assert trust either** — it would take three forged `clean` events,
which are indistinguishable from earned evidence and would corrupt the one record the interlock
reasons from. That is the wrong workaround, and it is why this needs a real event kind rather
than a file edit.

So Phase 3 adds: `PatternRecord.asserted: bool`, ledger events `asserted` and `revoked`
recognised by `_apply`, and `impress-a trust --assert <spec> --reason "..."` (refusing to
assert without a reason), which **composes the spec's declared chain at its declared
`replicas`** to compute the signature — at the width it will actually run, because the
signature includes replica multiplicity. Four properties are load-bearing:

- **Earned and asserted trust are never conflated.** The record carries `asserted`, `by`,
  `reason`, `at` and the git sha, so no later figure can claim a pattern earned trust through
  clean runs when an operator granted it.
- **Demotion stays live.** `on_failure` demotes an asserted pattern like any other, and that is
  a *finding* — it says the assertion was wrong — not a nuisance to suppress.
- **It widens the residual risk ADR 0003 already accepts.** 0003 accepts that a *consistent*
  novel silent failure will promote; an asserted pattern never gets the examination-and-delay
  the interlock buys at all. The justification is external evidence — the Tasks are proven in
  `examples/small_molecule_binding`, and `impress-a validate-tasks` re-proves each one on this
  hardware — not fiat.
- **Assertion covers known shapes only.** A reasoner that composes a novel shape — a wide
  multi-Aim Stage, or the Phase 8 refinement chain with a parent edge — gets a different
  signature and is still untrusted. That is correct, and it is **a confound the experiment must
  report**: an arm that explores pays the forced dry-run, the 10 % cap and
  one-instance-in-flight where an arm that sticks to the asserted shape does not. Mitigation:
  assert the small set of shapes the experiment expects (the six-stage chain at width 1 and
  width 4, plus the refinement variant), and report **admissions-under-scrutiny per arm** as a
  figure rather than letting it sit inside the yield number.

**Single writer, and the executor still decides termination.** Every mutating block in
`CampaignExecutor` is `await`-free by discipline. The Listener supplies the "all Objectives
satisfied" fact; it calls `session.stop(...)` and does not end the campaign itself.

**Admission stays synchronous**, including over HTTP, because `dry_run` instantiates task
agents and so admission must happen where the toolkit is installed.

**Not to be reinvented:** the informed-wave stagnation rule; one instance in flight for an
untrusted pattern; campaign parameters merge in the executor, not the policy; `replicas` is a
cap, not a default. **One ruling is deliberately overruled:** `plans/done/02-real-toolkit.md`'s
"breadth comes from `replicas`, not from each tool's internal sampling, which the adapters
discard all but the first of" described a *consequence of the adapter defect*, not a property
worth keeping — and the second clause names the defect outright. Breadth now comes from both.
The ruling's force is preserved as an ordering constraint: internal sampling may only be raised
once the adapters select from the ensemble, which is Phase 8, and the declared cost and
walltime must be re-derived at the new setting.

**ADR 0013 is pinned by fixtures.** Gate `role`; only integrity failures count against a
pattern; acceptance failures still fail the node; adapters omit an unreadable metric rather
than reporting 0.0; an acceptance `metric_in_range` requires an integrity `metrics_reported`
partner naming the same metric.

**What `impress` does not give us.** No task registry (`auto_register_task` does `setattr` and
keeps no collection, so a name collision silently overwrites); no runtime-mutable graph within
a pipeline (`register_pipeline_tasks()` runs once from `__init__`, two lines before
`self.logger` exists); no real task cancellation (`kill_parent` cancels the pipeline's asyncio
Task, nothing reaches the backend); no budget or walltime accounting; no retry/checkpoint/
resume; no `ImpressManager.shutdown()`. Two sharp edges: the child-pipeline mailbox is a
**single slot** a second submit silently overwrites, and **adaptive-function exceptions are
swallowed** with the barrier still released, so a failed decision is indistinguishable from a
made one. We never use `run_adaptive_step` — the outer loop is ours (ADR 0001) — and the
Deployer calls `manager.submit_new_pipelines([...])` directly rather than through the mailbox.

---

## Phases

Each phase ends green: `pytest tests -q` passes and `impress-a run
campaigns/mock-stabilize.yaml --model D` works.

### Phase 0 — Toolchain, lint gate, `impress` dependency

Exists first because `agent/.venv` does not exist in this checkout, `test_campaign.py` and
`test_reasoner_registry.py` fail at *collection* (no `langgraph`), and ruff currently walks up
to the root config with `fix = true` — the documented `ruff check src tests` **rewrites the
working tree** (36 files on first run, H6). A refactor started under those conditions cannot
distinguish its own breakage from the environment's.

- **M** `agent/pyproject.toml` — add `impress` to dependencies (name only; root is installed
  editable in the same venv, and `>=0.5.1` ∩ `>=0.4.0` is `>=0.5.1`, so no downgrade). Add
  `[tool.ruff]` with **`fix = false`** and the rule set `src/` already satisfies.
- **M** `agent/CLAUDE.md` — venv recipe becomes `pip install -e .. -e ".[dev]"`; record the
  py≥3.11-under-Dragon floor. **C** `agent/scripts/dev_setup.sh`.
- **M** `.github/workflows/agent-tests.yml` — add `ruff check src tests`.
- Tests: `test_impress_is_importable_and_pinned` (asserts the three-name public API hasn't
  grown); `test_ruff_config_is_local` (so a future lint can never resolve to the root config
  again). Do **not** assert a lint count — `plans/backlog.md` is the one place for the ceiling.
- Smoke: both commands above, now reproducible for the first time.
- Risk: pulling `impress` pulls `radical.pilot`, which agent never declared. It is import-time
  inert for the concurrent backend, and `test_campaign.py` proves that in the same run.

### Phase 1 — The Spec vocabulary, the two interfaces, and a parity seam

Lands every new type and both role protocols, and runs **today's exact decisions** through the
new role pipeline — still in one process, because the parity test needs a seam before the split
can be shown not to change anything. Exists before anything moves because a refactor without a
parity test is a rewrite.

- **C** `core/goal.py` — `Goal{text, objectives, reference_data, budget, walltime_s,
  declared_at}`, fixed at call time.
- **C** `core/spec.py` — `ObjectiveStatus{OPEN, PLANNED, DEFERRED, SATISFIED, DELETED,
  FAILED}`; `SatisfactionRule` (delegating `metric_in_range` to `Objective.satisfied_by`, one
  implementation); `SpecObjective{id, aim, statement, outputs, targets, satisfied_when,
  depends_on, status, generation, superseded_by, parent_node}`; `Aim{id, statement, parent,
  objectives, depends_on}` (empty `depends_on` == runs in parallel); `Spec` with
  `ready()/open_objectives()/blocked()/complete()`; `SpecRevision`; `TaskMapping`; `Deferral`;
  `Stage{id, spec_generation, attempt, tasks, deferrals, cancels, estimate, commitment,
  graph_id, status}`; `TaskDirective{RUN, CANCEL}`; `StageStatus`.
- **C** `core/data.py` — `DataRegistry{realized, futures}`, `TaskFuture`, `RealizedDatum`.
- **C** `core/channels.py` — `SpecChannel`, `StageChannel` protocols.
- **C** `policy/specifier.py`, `policy/planner.py` — the two protocols (signatures below).
- **C** `policy/legacy.py` — `DecideAsRoles(policy)`: a Specifier+Planner pair wrapping any
  `ControlPolicy`, turning a returned `ComposeAndRun.intent` into a one-task-per-stage `Stage`.
  Preserves `policy/driver.py`'s bounded-retry semantics.
- **C** `runtime/roles.py` — `listen()`, `specify()`, `plan_and_review()`, `deploy()`.
- **M** `runtime/executor.py` — `spec_state`, `stages`, and the `await`-free appliers
  `apply_revision()`, `apply_stage()`, `mark_objectives()`; channels as `asyncio.Queue`s
  beside `self._completed`; `CampaignSpec.control: str = "legacy"`.
- **M** `manager.py` — `_roles()` beside `_reasoner()`; the role coroutines are started beside
  `ex.pump()` under the same `asyncio.wait(FIRST_COMPLETED)` → cancel → `await
  ex.shutdown(aborted)` teardown when `control == "roles"`. This is the in-process rehearsal of
  the two-process topology, not the target topology.
- **M** `policy/registry.py` — `ReasonerModel` gains `specifier`/`planner` builders, both
  defaulting to `DecideAsRoles(build(o))` this phase; new `build_roles()`.
- **D** `core/types.py::Verdict` — no reader, and a second `DEFER` beside
  `ObjectiveStatus.DEFERRED` guarantees the wrong one gets imported.
- Tests: `test_spec_is_append_only_and_delete_is_a_flag`;
  `test_spec_complete_requires_every_objective_satisfied_or_deleted`;
  `test_ready_excludes_objectives_with_unsatisfied_dependencies`;
  `test_satisfaction_rule_reuses_objective_satisfied_by` (agrees on `{None, 2.9, 3.1}`);
  `test_stage_contributes_nothing_to_the_pattern_signature`; and the one that matters most,
  **`test_roles_pipeline_reproduces_the_legacy_campaign`** — same `_shape(nodes)`, front size
  and `stop_reason` as the legacy path. That is the strangler's seam.
- Smoke: `impress-a run campaigns/mock-stabilize.yaml --model D` **and** the same with
  `--control roles`. Proves the roles neither deadlock nor change the science.
- Risks: the fan-out reintroduces the recorded deadlock class (a role blocked on a channel when
  the executor halts) — every channel `get` races `_halt` exactly as `result()` does, and
  `_fail_waiters` drains the channels. A role that `await`s inside an executor mutation breaks
  single-writer — all mutation goes through the `await`-free `apply_*` methods.

### Phase 2 — Goal → Spec for real, objective state, spec-completeness termination, G1

The Specifier decomposes a Goal against the Toolkit's output space; the Listener terminates on
spec completeness. Exists before the Planner because a Planner with nothing to plan against is
untestable, and this is where **G1** stops being latent.

- **C** `core/toolkit.py` — `ToolkitView{tools: dict[str, TaskCard], skills}`;
  `TaskCard{id, toolkit, pattern, inputs, outputs, parameters (type/min/max/choices/default/
  trades), frozen, metrics, gates (id+role), declared_cost, declared_walltime_s, burn_rate,
  max_commitment}`. `trades` is carried because it is the only prose a reasoner gets about what
  a parameter costs.
- **C** `tools/view.py` — `view_of(registry, enabled)`. Gives `Registry.toolkit_skills()` its
  first caller (H4) and replaces `obs.available_tools`' bare ids.
- **C** `policy/specifiers/explicit.py` — `ThresholdSpecifier`: one Aim per declared
  `Objective`'s producing chain, `satisfied_when` lifted from the campaign's own `min`/`max`;
  the explore/exploit cascade expressed as Spec **revisions** rather than parameter tweaks.
- **M** `core/decision.py` — `CampaignObservation` gains `toolkit` and `spec`; new
  `SpecEvidence{observation, data, walltime}` where `.observation` **is** the object
  `observe()` returns, which is how ADR 0007's parity of evidence survives a second consumer.
- **M** `runtime/executor.py` — `observe()` fills both; **`_note_progress` is amended so a
  Stage containing only exploring objectives does not count toward stagnation**. That is G1's
  principled fix: additive, so a Stage with any exploit objective counts exactly as today.
- **M** `runtime/roles.py` — `listen()` consumes `session.as_completed()`, ingests into
  `DataRegistry`, calls `specifier.satisfied()`, applies statuses, signals `specify()`, and on
  `spec.complete()` calls `session.stop("every spec objective satisfied")`.
- **M** `core/provenance.py` — new kinds `specs`, `stages`.
- Tests: `test_toolkit_view_exposes_every_declared_parameter_and_range` (all real tools, no
  frozen parameter leaks); `test_toolkit_view_carries_the_skill_docs`;
  `test_specifier_maps_every_campaign_objective_onto_a_spec_objective`;
  `test_listener_stops_the_campaign_when_the_spec_completes`;
  `test_listener_requests_stop_and_does_not_decide_it`;
  **`test_exploring_stages_do_not_count_toward_stagnation`** — this *replaces* the two
  characterization tests G1 pins, so name them in the commit message; the change is deliberate.
- Smoke: `--control roles` must stop with `every spec objective satisfied` or a budget/cycle
  reason, never with stagnation before the first exploit Stage lands (the modelled t≈135 min
  failure).
- Risk: changing the stagnation rule changes when campaigns stop, including on Delta. The
  `stagnation_limit = 10_000` lesson applies — a magic number in a test is often a bug report.

### Phase 3 — Stage, the task registry, and the Reviewer as a gate

The candidate Stage becomes the unit of admission and the Reviewer becomes the gate **A8** has
been missing. Exists before the flags because DEFER/CANCEL have nothing to act on without a
registry.

- **C** `policy/planners/explicit.py` — `ThresholdPlanner`: select by output-type unification
  (`ArtifactType.unifies_with`), `Deferral` for unresolved `depends_on`, `cancels` for every
  `PENDING`/`DEPLOYED` `TaskRecord` whose objectives are all DELETED.
- **C** `runtime/reviewer.py` — `StageReviewer.review()`, three layers in order:
  **(1) coverage** — every `spec.ready()` objective appears as a Task or a Deferral, and every
  RUN task serves ≥1 non-DELETED objective; **(2)** the five gates + forced `dry_run`,
  unchanged; **(3) budget** — `estimate + committed ≤ available`, and `projected_wall + elapsed
  ≤ limit` when a walltime limit is declared. Rejections are `ValidationFailure` with
  `gate="coverage"` added, routed to `planner.replan`, bounded as `driver.py:106` bounds today.
- **C** `runtime/deployer.py` — compose → `session.submit` → write `TaskRecord`s → publish
  `TaskFuture`s to the Listener from `DispatchHandle.futures` → issue `cancels`.
- **C** `exec/task_ledger.py` — `TaskLedger`, `exec/ledger.py`'s fold keyed on `task_id`, in a
  **second file** `jobs/tasks.jsonl`. Not a key change: `RunService.outcome()` recovery depends
  on run-keying.
- **M** `compose/composer.py` — `compose_stage(stage, run_label)`; params ride per-task, so the
  silent drop at `composer.py:63` becomes impossible, and a params key naming a tool absent
  from the Stage is a `ValidationFailure(gate="parameter")` (**H3**, part 1).
- **M** `runtime/executor.py` — `submit_stage()`; the Reviewer's verdict becomes `_admit_once`'s
  first step; **`_objectives_without_a_producer`'s warning is deleted**, its logic moving into
  coverage as a refusal.
- **M** `compose/interlock.py` — `PatternRecord.asserted: bool = False`; `_apply` recognises
  `asserted` (sets `trusted=True, asserted=True`) and `revoked`; `_append` carries `by`,
  `reason`, `git_sha`. `on_clean_run` already returns `False` for a trusted record, so an
  asserted pattern accumulates no phantom promotion. `on_failure` demotes it like any other.
- **C** `cli/__init__.py` — subcommand **`impress-a trust`**, joining `SUBCOMMANDS` (which
  `slides/api/run_model.py` reads, so it must be added there and not hardcoded): `--assert
  <spec> --reason "..."` (composes the spec's chain at its declared `replicas`, prints the
  signature and the tools, refuses without a reason), `--list` (showing earned vs asserted and
  demotion counts), `--revoke <sig> --reason "..."`.
- **Task ids become campaign-global**: `f"{campaign_id}/{stage_id}/{objective_id}/{lineage}"`.
  Today's `f"r{r}_s{i}_{tool_id}"` is unique only within one graph, and asyncflow offers no
  `workflow_id` lookup, so the caller's table is the only index.
- **M** `core/session.py`, `control/plane.py`, `control/http.py`, `control/session.py` — two new
  operations, added to the **core protocol** and then rendered by every adapter, because ADR
  0007 forbids an adapter adding an operation the core lacks: `submit_stage(stage) -> RunId`
  (synchronous admission, accept-with-id or `SubmissionRejected` carrying the gate and reason —
  202/409 over HTTP, mirroring `submit_run`) and `publish_spec(revision) -> int` (the Specifier
  authors, the executor applies to its replica in an `await`-free block and returns the applied
  generation). `RemoteSession` gains both, so Phase 7's split needs no further protocol work.
  Stages and the task registry reach a read-only caller through the existing
  `provenance(campaign_id, kind)` with the new `specs`/`stages` kinds.
- Tests: **`test_reviewer_refuses_a_stage_that_cannot_produce_an_objective`** — the job
  22675512 shape, rejected at `gate="coverage"` where today it is admitted with a warning
  (**A8**); `test_reviewer_accepts_a_defer_in_place_of_a_task`;
  `test_reviewer_refuses_a_stage_that_overruns_available_budget`;
  `test_rejection_routes_back_to_the_planner_and_is_bounded`;
  `test_params_for_a_tool_outside_the_stage_are_refused_not_dropped`;
  `test_task_registry_records_every_deployed_task_task_keyed`;
  `test_task_ids_are_unique_across_graphs`;
  `test_asserted_trust_skips_the_cap_and_the_forced_dry_run` (a `Scrutiny` for an asserted
  signature has `trusted=True`, `cost_cap_fraction=None`, `force_dry_run=False`);
  `test_asserted_trust_is_distinguishable_from_earned_trust` (the folded record and the
  `--list` output both say which); `test_an_asserted_pattern_still_demotes_on_an_integrity_failure`;
  `test_trust_assert_refuses_without_a_reason`;
  `test_trust_assert_computes_the_signature_at_the_declared_replica_width` (A10: asserting at
  width 1 does **not** trust width 4);
  `test_a_novel_shape_is_untrusted_even_when_every_task_is_asserted` (the confound, pinned).
- Smoke: `--control roles` plus `pytest tests/test_http_adapter.py -q` with
  `provenance("stages")` read back over the socket.
- Risks: turning a warning into a refusal will refuse campaigns that previously ran — exactly
  the A11 hazard. No escape hatch is offered; the right fix is a correct Stage. A multi-Aim
  Stage is a new untrusted signature, so `ThresholdPlanner` emits single-chain Stages until
  Phase 4 and widening is opt-in.

### Phase 4 — Typed multi-input wiring, then DEFER / DELETED / CANCEL

Makes an Aim hierarchy with real dependencies actually execute correctly, then wires the three
flags. Exists before the Runner because `TaskNode.inputs` is **read only by the validator**
today — the dispatcher re-keys deps positionally as `dep0..depN` and adapters recover artifacts
by scanning, so **a multi-input node type-checks and mis-wires at runtime**. An Aim hierarchy
hits that on its first branch, and a pipeline's task set is frozen at registration.

- **M** `exec/dispatch.py` — `_make_task` builds `TaskRequest.inputs` as
  `{port: dep_outputs[out_port]}` from the node's `inputs` map.
- **M** `tools/agent.py` — `TaskRequest.input_ref(port) -> ArtifactRef`.
- **M** `tools/_subprocess.py` — `first_dep_output` becomes a deprecating shim that **raises
  rather than guesses** when more than one dep could match, so all five real adapters keep
  working; they migrate in Phase 11.
- **M** `runtime/roles.py`, `runtime/deployer.py` — DELETED ⇒ orphan detection over
  `TaskLedger.snapshot()` ⇒ `stage.cancels` ⇒ `Dispatcher.cancel(handle)` for queued work,
  `TaskState.CANCELLED` in the registry, and a `transitions` record for a RUNNING task that
  could not be recalled.
- **M** `compose/validate.py` — gate 1's `pass` for unsatisfied root ports becomes "satisfied
  from `Goal.reference_data` by declared type, or refused".
- Tests: **`test_a_two_input_node_receives_each_input_on_its_declared_port`** — fails today;
  this is the proof; `test_independent_aims_run_in_parallel`;
  `test_a_dependent_aim_waits_for_its_predecessor`;
  `test_deleting_an_objective_cancels_its_orphan_tasks` (PENDING → CANCELLED; RUNNING → DONE
  with `cancel_requested`); `test_required_port_with_no_producer_and_no_reference_datum_is_refused`;
  `test_every_real_adapter_recovers_its_inputs_by_port`.
- Smoke: a two-Aim mock campaign (`campaigns/mock-branch.yaml`, new).
- Risks: the shim is what five real adapters rely on, and a silent mis-map corrupts a Delta run
  — the `*.cif.gz`-trajectory precedent. Tightening gate 1 could refuse the working six-stage
  chain; `test_validation.py`'s replays of jobs 22702568/22726105 must stay green.
  **Cancellation of running work stays advisory (C4)** — see "Flagged as partial" below.

### Phase 5 — Measured cost, walltime, burn rates, commitments

Makes the Budget a measurement. Exists before the experiment because **G8** records that the
ledger's `cost` is the admission estimate repeated, and nothing times a task.

- **M** `core/budget.py` — add `walltime: Walltime|None` and `commitments: dict[str,
  Commitment]`, plus `committed`, `burn_rate`, `would_exceed_walltime`, `project`.
  **`limits`/`spent`/`holds` and `reserve`/`settle`/`release` are untouched** — they are on
  every admission path, and rewriting them would make budget refusals untestable against
  recorded Delta behaviour. New `Walltime`, `BurnRate`, `Commitment`. The outline's "smaller of
  an optional workflow maximum and a per-stage hard limit" is
  `min(goal.budget.get(d, inf), card.max_commitment.get(d, inf))`.
- **M** `tools/agent.py` — `__call__` times the phase chain; `post_process` stops copying
  `cost_model.cost` and returns `cost_measured` beside `cost_estimated`, plus
  `TaskUsage{started_at, finished_at, wall_s, cpu_s, gpu_s, host, rc}`. **`cost_estimated`
  remains what the budget settles on** — changing settlement mid-campaign would change what
  admission refuses, and refusal behaviour must be identical across arms. Two numbers recorded,
  not one number fixed.
- **M** `exec/dispatch.py` — the `_run` closure records `t_start`, `t_end`, `host`, `pid`,
  `cuda_visible_devices`, `gpu_index`, `peak_rss`. It is the only code that runs *where* the
  task runs. Also `TaskRequest.gpu_index` from `node.lineage % site.gpus_per_node`, and the
  three GPU adapters export `CUDA_VISIBLE_DEVICES` (**A10**'s pinning half).
- **M** `exec/resources.py` — `walltime_cost(shape)`, `nodes_cost(shape)`, finally translating
  `ResourceShape.walltime_s`/`nodes`; `to_backend_description` gets its first caller for the
  Dragon `cpu_affinity` half.
- **M** `compose/validate.py` — `estimate()` adds `walltime_s` **only when the campaign
  declares a limit**. Zero-risk by construction: `remaining` returns `inf` for an undeclared
  dimension and `exhausted()` iterates `limits` only, so every existing campaign is identical.
- **M** `tools/spec.py` — `CostModel` gains `burn: dict[str,float]` (per-second) and
  `max_commitment`; validation refuses a `max_commitment` below `cost_model.cost`.
- **M** `core/artifacts.py` / `runtime/executor.py` — `PropertySource` stops being hardcoded
  `name="mock_toolkit", authority=10` for every metric from every tool; the source becomes the
  producing tool and its declared authority band.
- **M** `compose/composer.py` — `_replica_seed` takes a per-campaign-instance salt from
  `IMPRESS_A_SEED_SALT`, recorded in `manifest.json` and the `campaign` record (**G7**).
- **M** `runtime/executor.py` — `RunRecord`'s `scrutiny`, `intent`, `informed_by`, `turn`
  become durable.
- **New provenance kind `tasks`** — one line per task at settle, so the harness never parses
  the ledger's nested payload; the ledger stays the durable record of last resort.
- Tests: `test_remaining_walltime_is_the_limit_less_elapsed`;
  `test_an_undeclared_walltime_limit_never_refuses_anything`;
  `test_committed_is_the_sum_over_pending_stages_and_actual_over_settled`;
  `test_burn_rate_is_measured_not_declared`; **`test_a_task_reports_its_own_wall_clock`**
  (fails today); `test_settlement_charges_measured_cost_while_admission_reserves_declared`;
  `test_property_source_names_the_producing_tool`;
  `test_two_campaign_instances_draw_different_seeds`;
  `test_a_tool_may_not_declare_a_commitment_below_its_own_cost`.
- Smoke: local, checking `jobs/tasks.jsonl` carries a non-constant `wall_s`; **plus one short
  Delta allocation** on `delta-small-molecule-smoke.yaml` — GPU-second accounting cannot be
  proven locally, and G8 reports GPU-busy ≤17 % with three of four GPUs idle.
- Risks: settling measured cost would change when campaigns stop — which is why it does not.
  **This phase does not touch a single `cost_model` number** (A11, and job 22675512's
  truncation). Timing inside `TaskAgent.__call__` measures the agent, not queue wait; the
  Deployer's `deployed_at` brackets that, so the two are distinguishable.

### Phase 6 — The Runner, on `impress`

The execution loop becomes a `StageRunner` over `ImpressManager` + `StagePipeline`.

- **C** `runtime/pipelines.py` — `StagePipeline(ImpressBasePipeline)` stashes `self._stage`
  **before** `super().__init__(...)`, because `register_pipeline_tasks()` is called two lines
  before `self.logger` is assigned. `register_pipeline_tasks()` registers each `TaskMapping`
  once: an **executable** tool via `auto_register_task(backend=<name>)` on a coroutine
  returning the command string, with `task_description` as a **signature default** (asyncflow
  reads `sig.parameters["task_description"]`); an **in-process `TaskAgent`** via
  `flow.function_task(...)` + `setattr`, as `Dispatcher._make_task` does. `auto_register_task`
  has only two branches and neither is a function task, so that one documented extension is
  unavoidable — chosen over `local_task=True`, which would move mock execution into the agent's
  own process and stop `test_campaign.py` proving a task closure is picklable.
  `ControlPipeline` holds one keep-alive `local_task`, because `ImpressManager.start()` exits
  the moment pipelines, buffer and adaptive tasks are all empty — structural, not decorative.
- **C** `runtime/runner.py` — `StageRunner` owns one `ImpressManager` and one
  `asyncio.create_task(manager.start([control_setup]))`. `deploy(stage)` calls
  **`manager.submit_new_pipelines([PipelineSetup(...)])` directly** — the child mailbox is a
  single slot a second submit silently overwrites, while this is public, creates the task
  immediately on the caller's loop, and carries no 0.5 s latency. A Stage is passed as one
  `stage=` key holding its JSON dump, because `config` and `kwargs` merge into one flat
  `**kwargs` and `from_dict` sweeps unknown keys. Returns a `DispatchHandle`-shaped handle so
  `_reap`/`drain` need no change.
- **M** `exec/backend.py` — named backends built with **constructors, not `.create()`** (which
  takes no name): `compute` (Dragon or Concurrent) plus `local`
  (`ConcurrentExecutionBackend(ThreadPoolExecutor(n), name="local")`), then
  `WorkflowEngine.create(backend=[compute, local])`, on the caller's loop, with `work_dir=`.
- **M** `exec/resources.py` — GPU pinning in two shapes: Concurrent →
  `{"env": {**os.environ, **caps}}` with `CUDA_VISIBLE_DEVICES`; Dragon →
  `{"process_template": {"env": caps, "policy": Policy(gpu_affinity=[i])}}`, because Dragon
  merges template env and applies the layout afterwards so `CUDA_VISIBLE_DEVICES` does not work
  there. Thread caps `ROSETTA_THREADS=1`, `MPNN_THREADS=4`, `GPU_TOOL_THREADS=8`,
  `OMP_WAIT_POLICY=PASSIVE`, merged with `cli._thread_caps`.
- **M** `runtime/executor.py` — `_shutdown_engine` gains `telemetry.stop()` in a `finally`
  **before** `flow.shutdown()`, because `stop()` flushes a 128 KB-buffered checkpoint. The
  bounded-teardown rule is preserved exactly (job 22491438: 60 min, ~64 GPU-hours after the
  science was done).
- Tests (**C** `tests/test_runner.py`): `test_stage_pipeline_registers_before_the_logger_exists`
  (and the variant that raises); `test_an_executable_task_must_return_a_non_empty_command`;
  `test_capture_stdio_resolves_to_a_path_not_text`;
  `test_two_stages_deployed_in_one_sweep_both_run` (the mailbox hazard, proven absent);
  `test_the_manager_does_not_exit_during_an_idle_gap`;
  `test_a_stage_pipeline_stays_hashable_by_identity` (pipelines are dict keys);
  `test_the_engine_belongs_to_the_submitting_loop` (extends the fake-backend harness with
  `assert flow.loop is asyncio.get_running_loop()` plus real work through the engine);
  `test_only_the_runner_imports_impress` (AST walk — mechanically enforces the dependency
  boundary and keeps `impress` out of `policy`/`core`). `tests/test_campaign.py` must pass
  **unchanged** on the Runner path; that is the acceptance criterion for deleting
  `Dispatcher.submit`.
- Smoke: local, **plus a Delta smoke nothing local replaces** — `sbatch
  scripts/delta_gpu_run.sh campaigns/delta-small-molecule-smoke.yaml --model D`, expecting
  `6/6 tasks ok` as job 22692304 did in 2 m 53 s. Only a real allocation proves Dragon
  placement, GPU affinity and bounded teardown. `impress-a preflight` first.
- Strangler: `Dispatcher.submit`/`collect`/`run` **deleted** once the Delta smoke passes; the
  task factory moves into `runtime/pipelines.py`; `ExecutionResults` stays, because it is the
  projection source for `RunOutcome` and `core` may not import `exec`.

### Phase 7 — Split the control plane into its own process

The Spec Loop and Planning Loop move into a control process with its own event loop, talking to
execution over `CampaignSession`. Exists after Phase 6 because the execution side must be whole
before it can be served, and before Phase 9 because a real model-C arm falls out of this phase
for free. It subsumes **C5** and makes **C6** impossible rather than fixed.

- **M** `cli/__init__.py` — two subcommands. **`impress-a serve <spec>`**: the execution
  process — executor, Reviewer, Deployer, Runner, the one asyncflow engine — registered with
  `InProcessControlPlane` behind `ControlPlaneServer`, with **no reasoner at all**.
  **`impress-a control --connect <url> --model X`**: the control process — `RemoteSession` plus
  Listener, Specifier and Planner on its own loop. `--model C` then means "a third party drives
  the control process", not "the reasoner is absent", so the fail-open path has nowhere to live.
- **M** `runtime/roles.py` — the roles take a `CampaignSession`, never an executor, so the same
  code runs in-process (Phase 1) and across the wire. That is the whole reason Phase 1 built
  them against the protocol.
- **M** `runtime/executor.py` — `CampaignSpec.control_liveness_timeout_s` (0 disables; set in
  both Delta specs). The executor records last contact from **any** session call, so no
  heartbeat operation is added (the Listener polls `observe()` anyway, and ADR 0007 would
  otherwise be in play). On expiry: stop admitting, drain in-flight through the existing
  `drain`/`_reap` path, absorb every outcome, then
  `request_stop("control plane lost after Ns")` and a `transitions` event `control_lost`.
- **M** `scripts/delta_gpu_run.sh` — start `serve`, then `control` as a sidecar on the same
  node; fold the control process's exit code into the job's so a dead control process cannot
  look like a clean run.
- Tests: **`test_split_control_plane_reproduces_the_in_process_campaign`** — Phase 1's parity
  test run again across a loopback socket, asserting the same `_shape(nodes)`, front and stop
  reason. That is the proof the split changes nothing.
  **`test_a_blocking_specifier_does_not_stall_execution`** — a Specifier that sleeps
  *synchronously*; tasks must keep completing. That is the test which justifies the split
  existing at all, and it is the one that would fail under the single-process design.
  `test_execution_drains_and_stops_when_the_control_process_dies`;
  `test_no_new_stage_is_admitted_after_control_loss`;
  `test_a_stage_rejection_crosses_the_wire_with_its_gate_and_reason` (409 carrying
  `gate="coverage"`);
  **`test_spec_revisions_are_applied_by_the_executor_not_the_author`** — the coverage gate reads
  the applied replica, so a Planner asserting a smaller Spec cannot widen its own coverage.
- Smoke: `impress-a serve campaigns/mock-stabilize.yaml &` then
  `impress-a control --connect http://127.0.0.1:<port> --model D`, with the same result as the
  single-process run; then a Delta smoke with the sidecar.
- Risks: a dead control process means a campaign that silently stops replanning — exactly what
  the liveness timeout and drain-and-stop are for, and why they land in this phase and not
  later. `RemoteSession`'s event-stream cursor is in memory, so a restarted control process
  cannot resume; accepted, because the chosen policy is drain-and-stop rather than reconnect,
  which is also why `RunService.reattach()` stays caller-less and resume stays out of scope.
  The plane has no auth and no TLS (**C7**); both ends sit on the same compute node bound to
  loopback, which is the only boundary defensible today — record that in the ADR rather than
  leaving C7 open by implication.

### Phase 8 — Refinement and ensembling: the two mechanisms the Goal needs

Not in the outline, and the experiment cannot produce a T3 design without it. Exists after
Phase 4 because feeding a parent's artifacts into a child chain *is* a typed multi-input edge.

- **M** `runtime/executor.py` / `compose/composer.py` — `parent_node` stops being a lineage
  label: a Stage whose `SpecObjective.parent_node` is set has its first task's input ports
  satisfied from that `DesignNode.artifacts`, so `rfd3_design` receives a structure and can run
  partial diffusion (`partial.input`/`partial_t`), which is the reference's `num_refine_cycles`.
- **M** `toolkits/rfd3/tools/rfd3_design/spec.yaml` — declare the optional `Backbone`/`Complex`
  input port and the `partial_t` parameter, matching the reference's `rfd3_partial_t: 10.0`.
- **M** `tools/ligandmpnn_agents.py`, `tools/boltz_agents.py`, `tools/rfd3_agents.py`,
  `tools/rosetta_agents.py` — **stop keeping index `[0]`.** Each adapter selects the best member
  of its own ensemble by its own declared metric and emits that, plus the ensemble itself on a
  `SEQUENCE_SET`/`ENSEMBLE` port so a downstream stage or a Planner can see the spread. Selecting
  the best of a wide batch is the reference's own shape — and the reference records that
  `analysis_sequence` was silently never comparing MPNN candidates at all, because it read only
  the first line of a `.fa` that holds every candidate. Until this bullet lands, `num_designs`,
  `num_seqs`, `diffusion_samples` and `nstruct` stay `frozen_parameters` (their first real use,
  D6); **the moment it lands they are unfrozen and defaulted to 8**, so a Planner may tune them.
- **M** the four specs — **internal sampling to 8, wider batch preferred over more batches:**

  | Tool | Parameter | 1 → 8 | Note |
  |---|---|---|---|
  | `rfd3_design` | `num_designs` | **8** (max 64) | one invocation, 8 backbones |
  | `ligandmpnn_design` | **new `batch_size`** | **8**, with `num_seqs`/`number_of_batches` left at **1** | the case worth naming: `ligandmpnn_agents.py:157-160` passes `--number_of_batches num_seqs` with `--batch_size` **unset**, so today 8 sequences would be 8 serial batches of 1 — the worse of the two options, and the adapter's own comment says to confirm against `run.py --help` first |
  | `boltz_predict` | `diffusion_samples` | **8** (max 25) | batched co-folding |
  | `fastrelax` | `nstruct` | **8** (its declared max) | included as sampling, but flag it: `nstruct` is 8 *serial CPU trajectories*, not a GPU batch, so its cost scales **linearly** where the three above are close to sublinear |
  | `packmin`, `filter_shape` | — | unchanged | `cycles` is convergence, not sampling; `filter_shape` is a pure measurement (and declares no parameters at all, D5) |

- **M** `cli/__init__.py` `preflight` — a contract check for `--batch_size` against the installed
  `run.py --help`. A3's lesson is that a tool's contract was not merely unverified but **wrong**
  (RFD3 was invoked with `--config`/`--out`, flags its real Hydra CLI does not have), so a flag
  nobody has run is a flag that may not exist.
- **M** `toolkits/*/tools/*/spec.yaml` — `cost_model.cost` and `resources.walltime_s`
  **re-derived from `validate-tasks` measured at the 8-sample setting**, preserving the
  ≥2.25×-worst-observed headroom rule. Not guessed, and not left alone: these figures feed gate
  5 and the untrusted cap, which *refuse* graphs, and an unchanged `walltime_s` at 8× sampling
  presents as a timeout — which names a budget, not a cause.
- Tests: `test_a_child_stage_receives_its_parent_nodes_artifacts`;
  `test_partial_diffusion_is_reachable_from_a_parent_node`;
  `test_an_ensemble_adapter_selects_its_best_member_not_the_first`;
  `test_an_ensemble_port_carries_every_member`;
  `test_mpnn_prefers_one_wide_batch_over_several_narrow_ones` (asserts the argv carries
  `--batch_size 8 --number_of_batches 1`, which is the one place the preference is mechanical);
  `test_raising_a_frozen_ensemble_parameter_is_refused` (before the adapters land) and
  `test_sampling_parameters_are_tunable_once_the_adapters_select` (after);
  `test_declared_walltime_covers_the_eight_sample_measurement`;
  a characterization test recording the measured yield change on mock tools.
- Smoke: a Delta smoke comparing `p_T2` at 1 vs 8 samples, with and without refinement — this
  is the phase whose whole purpose is to move that number, so it is measured, not assumed. It
  also supplies the re-derived cost and walltime figures.
- Risk: this is the one phase whose success is not guaranteed by construction. If refinement
  does not raise `complex_plddt`, the Goal stays unreachable and the experiment's go/no-go
  (G-15) routes to the plumbing-and-contract comparison. That is a stated outcome, not a
  surprise.

### Phase 9 — The four arms as Specifier/Planner halves that actually reason

- **C** `policy/specifiers/agentic.py`, `policy/planners/agentic.py` — **A** split. Today
  `_build()` registers 2 nodes while the docstring describes 4 (**H1**). The four land where
  they belong: `hypothesize` + `analyze` in `AgenticSpecifier`, `select_tasks` + `parameterize`
  in `AgenticPlanner`. `self.reasoner`, stored and never read, becomes two real call sites.
- **C** `policy/specifiers/oracle.py`, `policy/planners/oracle.py`, `policy/llm.py` — **B**.
  `DECISION_SCHEMA` splits into `SPEC_SCHEMA` and `STAGE_SCHEMA`; `RehearsalOracle` keeps both
  halves network-free **and derives its chain from the stages it is given** rather than
  returning the hardcoded mock chain; `_build_b` forwards `o.stages` (**H2**, and the dangerous
  half of it). `OpenAICompatOracle` is ported from the sibling's `llm.py` with `models.yaml`,
  one profile per model, pinned dated model id in provenance.
- **C** `policy/specifiers/external.py`, `policy/planners/external.py` — **C**. Two inboxes fed
  by `plane.steer` with a `{"role": "specifier"|"planner"}` discriminator **inside the existing
  directive dict** — no new plane operation, so ADR 0007 holds.
- **C** `policy/planners/explicit.py` (from Phase 3) — **D**, the control.
  `ReplaySpecifier`/`ReplayPlanner` replace `ReplayPolicy`, replaying `specs.jsonl` +
  `stages.jsonl` — strictly better, because a Stage is now a durable artifact.
- **M** `policy/wrappers.py` — role twins: `LoggingSpecifier`, `LoggingPlanner`, `StageGuard`
  (replicas cap, `forbid_tools`, plus refusal of a RUN task serving no objective).
  `NullSpecifier` returns an empty Spec, so `Spec.complete()` is trivially true and the
  Listener stops immediately — today's semantics with no special case.
- **M** `cli/__init__.py` — `--specifier`/`--planner` promoted to documented flags. The entry
  points came in Phase 7, so **C5** is already closed and **C6** is structurally gone: a
  control process *is* the reasoner, and arm C is built with `on_timeout="stop"` and **no
  fallback**, so it halts rather than becoming D. Also **X1**, found during planning:
  `build_policy` deliberately does not forward `max_cycles`, so `ReasonerOptions` defaults
  (`max_cycles=6`, `target_front=3`) reach A and D — **a 4 h arm would make 6 decisions in
  ~20 min at 8 % allocation use.** Forward `max_cycles` and `target_front`, and make
  `RehearsalOracle`'s hardcoded `cycle >= 4` / `front >= 3` constructor arguments.
- **M** `policy/registry.py` — per-half builders, `llm_calls`/`status`/`note` per half, so
  `impress-a models` keeps the status column honest. Store a dotted path per half and import
  lazily — the module docstring already names this as the one place to do it, and adding
  litellm/openai on top of langgraph doubles the cost of `impress-a tools`.
- Tests: `test_every_model_supplies_both_halves`; `test_halves_mix_independently`;
  `test_model_a_registers_four_nodes`;
  **`test_model_c_under_the_cli_does_not_silently_run_d`**;
  **`test_a_planner_can_vary_a_real_tools_parameter`** (**H3** — the item that blocks any claim
  about decision quality); `test_policy_max_cycles_equals_the_spec` (X1);
  `tests/test_remote_session.py` rewritten against the role interfaces, still asserting the
  same tree and front as in-process — the remote seam is the only sanctioned out-of-process
  boundary, so that test must never be deleted; `test_steer_routes_by_role`.
- Smoke: four local runs `--model A|B|C|D --control roles`, plus `impress-a serve` +
  `impress-a reason` over a loopback socket. Proves C5 and C6 together.
- Risks: ADR 0005 — both halves are declared at launch, and per-role `fallback` is the same
  declared exception the ADR already grants. A live LLM makes A and B non-reproducible, so the
  pinned model id, prompt and raw reply go to provenance, which is also what makes `replay`
  meaningful. An LLM-authored wide Stage can hit A10's cap by a new route; the rejection names
  `gate="interlock"` with `transient=True` and `replan` is bounded.

### Phase 10 — Calibration (G4/G5), gate 6, and the comparison harness

- **M** `toolkits/rosetta/tools/fastrelax/spec.yaml` — **keep** `total_score ≤ 0.0` and
  `fa_rep ≤ 500` as **integrity** (divergence bounds: the only judge of whether packmin's pose
  blew up); **add** `metrics_reported[total_score, fa_rep, interaction_energy]` integrity and
  three **acceptance** gates `total_score ≤ −250`, `fa_rep ≤ 100`, `interaction_energy ≤ −8`.
  Two gates on one metric with different roles is exactly what 0013 is for: `+1500` means the
  tool broke; `−12` means the design fell short.
- **M** `tools/rosetta_agents.py` — compute `interaction_energy` via
  `InteractionEnergyMetric` with `ResiduePropertySelector(LIGAND)` vs `NotResidueSelector`
  (selector-based, so it is correct regardless of chain layout), ported from the reference's
  `joey_utils.interaction_energy`. **If it cannot be computed, omit it** — the
  `metrics_reported` partner then fails as integrity, which is the correct reading. **G5**:
  `filter_shape`'s XML moves to `beta_nov16` with explicit residue selectors instead of
  `jump="1"` — and the selectors are chosen **from a measurement**, by printing
  `pose.pdb_info().chain(i)` and `pose.num_jump()` on a real `fastrelax.pdb` and committing
  that chain map as a fixture. Copying upstream's `Chain chains="A"/"B"` is only right if the
  ligand is its own chain.
- **M** `toolkits/rfd3/.../spec.yaml` — new metrics `ca_deviation` and `ligand_clashes`, read
  from the sidecar JSON the adapter already opens and reads nothing from (G2's other half);
  acceptance gates `ss_fraction ≥ 0.5`, `ca_deviation ≤ 1.0`, `ligand_clashes ≤ 0`, keeping
  `has_secondary_structure` at 0.3 as the integrity floor. Prefer rfd3's own
  `helix_fraction`/`sheet_fraction` and **record the change of definition in `SKILL.md`** — it
  changes what the number means.
- **M** `toolkits/boltz/.../spec.yaml` — `complex_plddt` acceptance `0.5 → 0.75`, with the
  rescale recorded (`PROD`'s `fold_min_plddt: 75.0` applies to `complex_plddt * 100.0`).
  `ligand_iptm ≥ 0.4` kept, with a comment that `PROD` leaves it off deliberately — **ours is
  stricter than `PROD` on one axis and every T3 figure must say so.**
- **Fixtures**: `fastrelax/tests/passes_ours_fails_upstream.good.json` → **`.bad.json`** (and
  it must gain `interaction_energy`, or it fails `metrics_reported` and cannot be
  `acceptance_only`); new `no_interaction_energy.bad.json` (integrity),
  `weak_binder.bad.json` (converged, well-packed, does not bind — the gate's reason for
  existing), `ca_deviation_too_high.bad.json`, `ligand_clash.bad.json`,
  `no_backbone_metrics.bad.json`, and **`low_plddt_fold.bad.json` carrying job 22692304's real
  0.507** — the project's best run becomes the known-bad fixture for the new fold gate. Every
  `.good.json` gains the new metrics or stops being good.
- **M** `compose/validate.py` — **gate 6**: `tool_delivery: real` on `CampaignSpec` refuses any
  graph containing a node whose `ToolSpec.toolkit == "mock"`. A **gate**, not the guard wrapper,
  because `RuleCorrectionsPolicy(forbid_tools=...)` is bypassed by `--no-guard`. This is
  **E1**'s inert switch finally wired, moved from `sites/*.yaml` (read by no code) to the
  campaign spec the loader already reads.
- **M** `on_rejected` in both oracle and explicit planners — **stop truncating the stage tail**.
  On `budget`/`interlock`/`objectives`, shrink `replicas`; at `replicas == 1`, `Stop`. Job
  22675512 recorded `rejected: null` while being unwinnable because the tail carried the only
  producer of two of four objectives.
- **C** `src/impress_a/analysis/compare_arms.py` + `cli` subcommand `impress-a compare`. In
  `src/` not `scripts/`, because CI runs only `pytest tests -q` and a harness that is not
  importable is a harness that is not tested. New layering row `analysis: {core}`.
- **C** `src/impress_a/analysis/validate_tasks.py` + **`impress-a validate-tasks <spec>`** —
  per-**Task** validation on real hardware, which is what justifies asserting trust on the
  pre-loaded Toolkit. It executes each Task in the spec's chain once, in dependency order, and
  emits one row per Task:

  | Check | Why it is the check |
  |---|---|
  | ran, exit status, and the `[phase]` breakdown persisted | separates import time from work time — `import pyrosetta` took **471 s** off HDD against a 300 s budget (job 22675512), and a timeout names a budget, not a cause |
  | every declared output port produced, with its declared `ArtifactType`, present on disk with non-trivial size and a digest | the `*.cif.gz` glob that selected a diffusion *trajectory* rather than the design |
  | inputs recovered **by declared port**, not positionally | the Phase 4 fix; a multi-input node type-checks and mis-wires without it |
  | every declared metric reported and **finite** | `metrics_reported`, per Task and as a table; a fabricated 0.0 is the failure this forbids |
  | integrity gates pass; acceptance gates reported **separately** | a weak design is not a broken Task (decision 0013) |
  | measured wall time vs declared `resources.walltime_s` | the smoke is where you learn a declared walltime is too small, which otherwise presents as a hang |
  | `cost_measured / cost_estimated ≤ 1.0` per dimension | above 1.0 a declared figure sits below measurement and gate 5 starts refusing real work |
  | the tool is not from the `mock` toolkit | the mock-on-GPU failure mode, checked per Task rather than per campaign |

  Exits non-zero if any Task fails any **integrity** row. This is the only check shaped like
  all four defects that reached hardware — what a tool writes, whether it can import, where the
  bytes live, and an estimate that refuses work — none of which a dry run can find, because
  "checked against the binary" is not "executed".
- Tests: `test_validate_tasks_fails_a_task_that_omits_a_declared_metric`;
  `test_validate_tasks_fails_a_task_whose_declared_output_port_is_missing`;
  `test_validate_tasks_separates_acceptance_from_integrity` (a weak-but-working Task exits 0
  with its acceptance row marked); `test_validate_tasks_flags_a_declared_walltime_below_measurement`;
  `test_validate_tasks_refuses_a_mock_tool`. All fixture-driven over a synthetic work dir, so
  they are green before the tool is pointed at an allocation.
- Tests: `test_fastrelax_gates_match_upstream_calibration` (the four numbers, once, cited);
  `test_filter_shape_selects_the_declared_interface`; `test_gate_fixtures.py` unchanged in
  mechanics — the suffix is authoritative, so every tightened `.good.json` fails loudly;
  gate-6 refusal test; the twelve harness tests below.

### Phase 11 — Delete the legacy path

**D** `policy/driver.py`, `policy/legacy.py`, `policy/base.ControlPolicy`/`BasePolicy`, the
`decide`/`on_rejected`/`interpret` methods on all four arms, the old `policy/wrappers.py`
classes, `CampaignSpec.control`, `CampaignExecutor.submit(intent)`,
`core/decision.ExperimentIntent`/`ComposeAndRun`, `CampaignObservation.available_tools`,
`tools/_subprocess.first_dep_output`. **Kept deliberately:** `RunService.reattach()` (still no
caller — resume is out of scope), `ExecutionResults`, `Pattern`/`ArtifactType`, the interlock.

Test: `test_no_module_defines_decide` — an AST walk, the mechanical proof the strangler
finished. Risk: `ExperimentIntent` is the type ADR 0010's "policies emit abstract intent"
clause names, so its deletion needs the amendment saying a `Stage` of `TaskMapping`s is the new
abstract intent — otherwise the CLAUDE.md invariant table starts lying.

### Dependency graph

```
P0 toolchain
 └─> P1 vocabulary + 2 interfaces + roles in-process    (the parity test IS the seam)
      └─> P2 ToolkitView + Goal→Spec + Listener + G1     (a Planner needs a Spec)
           └─> P3 Stage + TaskRegistry + Reviewer (A8)   (DEFER/CANCEL need a registry;
                │                                         submit_stage/publish_spec land here)
                ├─> P4 typed multi-input + flags + Aim parallelism
                │     ├─> P6 Runner on impress           (a pipeline's tasks freeze at registration)
                │     │     └─> P7 split the control plane out  (execution must be whole first)
                │     │           └─> P9 the four arms   (H1 H2 H3 X1; C5/C6 closed by P7)
                │     └─> P8 refinement + ensembling     (a parent edge IS a typed multi-input edge)
                └─> P5 measured cost/walltime/burn       (G7 G8 (h) (k) (j))
P5 + P8 + P9 ─> P10 calibration + gate 6 + harness ─> P11 delete legacy
```

The split is P7 and not P1 for the strangler's sake: the roles are written against
`CampaignSession` from the start, proven behaviour-identical in one process, and only then moved
across a socket — so a failure after P7 is a transport failure and nothing else.

---

## The reasoner restructuring

```python
# policy/specifier.py
@runtime_checkable
class Specifier(Protocol):
    name: str
    async def initial_spec(self, goal: Goal, toolkit: ToolkitView) -> Spec: ...
    async def revise(self, spec: Spec, ev: SpecEvidence) -> SpecRevision: ...
    async def satisfied(self, spec: Spec, ev: SpecEvidence) -> list[str]: ...

# policy/planner.py
@runtime_checkable
class Planner(Protocol):
    name: str
    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage: ...
    async def replan(self, stage: Stage, rejection: ValidationFailure) -> Stage: ...
```

Both import `core` only, so `test_layering.py`'s disjointness assertion keeps them honest.
`SpecEvidence.observation` **is** the `CampaignObservation` `observe()` returns.

| Arm | Specifier half | Planner half |
|---|---|---|
| **A** | `AgenticSpecifier` — LangGraph `hypothesize → revise_spec`; nodes 1 and 4 | `AgenticPlanner` — `select_tasks → parameterize`; nodes 2 and 3. Four total, matching the docstring |
| **B** | `OracleSpecifier` — one structured call per signal, `SPEC_SCHEMA`-validated, bounded retry, declared fallback, logged transition | `OraclePlanner` — one call per planning round, `STAGE_SCHEMA`-validated. `RehearsalOracle` serves both offline; `OpenAICompatOracle` is the live client |
| **C** | `ExternalSpecifier` — blocks on a `{"role":"specifier"}` inbox | `ExternalPlanner` — same for `planner`. **No fallback in the experiment**: `on_timeout="stop"`, so C cannot silently become D |
| **D** | `ThresholdSpecifier` — deterministic Goal→Spec from the declared objectives; explore/exploit as revisions | `ThresholdPlanner` — output-type matching, DEFER on unresolved deps, CANCEL for DELETED orphans. The scientific control |
| **null** | empty Spec ⇒ `complete()` true ⇒ immediate stop | never asked |
| **replay** | reads `specs.jsonl` | reads `stages.jsonl`; diverges loudly on rejection |

`policy/driver.py`'s three rulings survive its deletion: per-experiment bounded retry →
`Planner.replan`; the `concurrency` hold → the Deployer's in-flight cap; and `_collect`'s rule
that **the reasoner owns `interpret`** → the Listener owns ingestion, and the executor still
never reaches into a reasoner. `--model X` builds both halves from one row;
`--specifier X --planner Y` is mutually exclusive with it; the campaign log names both halves —
the ambiguity that let 144 degraded turns read as a frontier-model result for a day.

---

## ADRs

**Amend.** **0001** — "Workflow Engine" as a role name is retired; the role is the Runner, and
`WorkflowEngine` means asyncflow's engine only; the agent also owns the `ImpressManager`.
**0002** — the two halves do not multiply control modes; C remains the single headless mode
with two role inboxes behind one `steer`. **0003** — a Stage contributes nothing to the pattern
signature; a multi-Aim Stage is a wider shape and therefore a new untrusted pattern. **And an
operator may assert trust** for a pattern whose Tasks are proven outside this system, through a
distinct `asserted` ledger event carrying who, why and when — never by forging `clean` events.
Asserted trust is visibly distinct from earned trust in every record and figure derived from
it; demotion still applies and is a finding; and it **widens the residual risk 0003 already
accepts**, because an asserted pattern never receives the examination-and-delay the interlock
buys. The justification is external evidence plus a passing `impress-a validate-tasks` on this
hardware, not fiat.
**0004** — Goal→Spec→Objective→Stage is *how a decision is made*, not a replacement for the
population; `SpecObjective.parent_node` keeps backtracking reaching any earlier node.
**0005** — Specifier and Planner are concurrent roles with distinct scopes, both fixed at
launch. **0007** — the protocol gains **two core operations**, `submit_stage` and
`publish_spec`, rendered by every adapter, because no adapter may carry an operation the core
lacks; `steer` additionally carries a `role` discriminator inside its existing dict.
**0010** — one new layer (`analysis`),
one new `ALLOWED` row; a `Stage` of `TaskMapping`s is the new abstract intent. **0012** — a
*generated* `SpecObjective` still declares against property **names**, and its satisfaction
delegates to `Objective.satisfied_by`, so a late measurement still supersedes against the same
name.

**New.** **0014 — two processes, and where the boundary falls.** There is exactly one asyncflow
engine on the execution process's loop (jobs 22328172, 22328262); the Spec Loop and Planning
Loop run in a control process with its own loop, over `CampaignSession`; the Reviewer and
Deployer are execution-side because `dry_run` must run where the toolkit is installed; both
ends are bound to loopback on one compute node, which settles **C7** for this configuration;
and on loss of the control process execution drains, absorbs, and stops with a reason naming
the loss, so a lost planner is never a silently idle allocation and never a disguised model-D
arm. **0015** the Spec is runtime-mutable, append-only and single-writer, authored by the
Specifier and applied by the executor;
DELETED is a flag, never a removal. **0016** the task registry is task-keyed, durable and
campaign-global; `jobs/tasks.jsonl` is a second file because run-keyed recovery depends on
`job_id`. **0017** cost is declared at estimation and measured at settlement; estimates refuse
work and must stay conservative. **0018** `agent/` depends on `impress` and may not modify it;
`runtime/runner.py` and `runtime/pipelines.py` are the only importers, asserted by a test.
**0019** (**F1**, already owed) the reasoner decoupling and the process boundary.

---

## The four-arm experiment

Branch `agent/reasoner-models`. Spec: **`campaigns/delta-small-molecule-arms.yaml`** (new) —
**one file, four arms, `--model` the only difference**; `campaign_id` becomes
`delta-small-molecule-arms-<MODEL>` inside `run_campaign`, so four output trees stay separate
without four files. Pre-registration is committed to `plans/arms-preregistration.md` and its
sha recorded in every arm's `manifest.json` as `prereg_sha`.

### Pre-registration

**Hypothesis.** Under one fixed workflow, target, draw sequence and budget, the choice of
reasoner changes the rate at which distinct physics-passing designs are produced per
node-hour by a factor detectable at this allocation size. **D is the control**; A, B and C are
each tested against it.

**Tiers, frozen before any run.** **T1 plumbing** — all six tools ran, no integrity gate
failed, every declared metric reported. **T2 physics** — T1 and every `PROD` threshold except
the fold (`total_score ≤ −250`, `fa_rep ≤ 100`, `interaction_energy ≤ −8`,
`shape_complementarity ≥ 0.55`, `ca_deviation < 1.0`, `ligand_clashes == 0`,
`ss_fraction > 0.5`). **T3 the Goal** — T2 and `complex_plddt ≥ 0.75` and
`ligand_iptm ≥ 0.4` (stricter than `PROD`, which leaves `ligand_iptm` off; flagged in every
table).

**Primary endpoint.** `C_T2 / (AllocNodes × gpus_per_node × Elapsed_h)` — **distinct T2
designs per billed GPU-hour, charging every node an arm holds**, with `AllocNodes` and
`Elapsed` from `sacct`, never the campaign's own clock. Scored over a common window
`T_cut = 3.25 h` measured from each arm's **first task start**, so unequal Dragon startup
cannot bias an arm; the full-allocation figure is reported alongside. `C_T3` is reported as the
Goal's literal answer, with a pre-registered expectation of 0.

**Distinctness.** Primary: single-linkage clusters at amino-acid identity ≥ θ, merging
equal-length pairs with TM ≥ 0.8 on their Boltz complexes. **θ is set from the smoke**, as the
95th percentile of the pairwise identity distribution of *same-seed* pairs, so anything a
re-draw of one seed can produce collapses to one cluster; default 0.90, frozen at the go/no-go.
Exact-identity count is reported as the upper bound. G7 measured that same-seed designs share
length exactly, have median TM 0.82, and are never byte-identical — which is the historic ~3×
over-count. Sequences come from the LigandMPNN FASTA on disk, never from a reasoner's
bookkeeping.

**Decision rule.** `C_arm ~ Poisson(μ)`, `log μ = β₀ + β_arm + log(node_h)`; three contrasts
(A/B/C vs D), Holm-corrected at family α = 0.05. **An arm wins iff its rate ratio vs D has a
Holm-adjusted 95 % CI entirely above 1.3 and a point estimate ≥ 1.5.** Stated now: at an
expected `C_T2 ≈ 14` the CI spans roughly ×/÷ 2.0, so **this experiment can only detect a
≥ 2.2× difference**, one allocation per arm gives zero degrees of freedom for overdispersion,
and A11's measured 3.2× wall-time swing means between-allocation variance is **not estimable
here**. The honest claim is the CI, not the p-value; a smaller effect needs 2 replicates per
arm (32 node-h). Said here so nobody discovers it in the analysis.

**Uninformative (pre-registered).** All arms `C_T2 = 0` ⇒ report funnel, cost and plumbing
only. An arm shown degraded, fallen back, or to have executed a mock tool ⇒ **void**, named as
void, dropped. An arm terminating before 80 % of usable wall clock for any reason other than
its own `Stop` ⇒ yield figure void. **A and D differing by more than the engine's
nondeterminism band ⇒ the one-variable claim fails** — A is behaviourally D today (H1), so
this doubles as the only positive control this design has for an uncontrolled variable. Zero
`interaction_energy` values ⇒ T2/T3 undefined. Arms not co-resident within ±30 min ⇒ flagged.
**An asserted pattern demoting in any arm ⇒ the assertion was wrong**, and every figure derived
from an asserted-trusted admission in that arm is reported as such rather than quietly kept.
**Admissions-under-scrutiny differing by more than 2× between arms ⇒ the yield comparison
carries a throttle, not only a decision quality**: an arm that composed novel shapes paid the
forced dry-run, the 10 % cap and one-instance-in-flight, and the contrast must be reported
alongside the subset restricted to asserted-shape admissions.

**Specifier vs Planner attribution.** Specifier: the composed stage set per cycle, the number
of distinct pattern signatures ever composed, `unproducible_objectives`, the objectives emitted
at campaign start. Planner: per-tool parameter values per cycle, `replicas` requested,
`parent_node` chosen, `Backtrack` frequency, `on_rejected` behaviour,
**admissions-under-scrutiny** (how often the arm composed a shape outside the asserted set and
so paid the forced dry-run, the 10 % cap and one-instance-in-flight), demotions of an asserted
pattern, and stage pass rates *conditioned on* the parameter vector. `C_T2`, cost per design
and time-to-tenth are **joint and not attributable**. If an arm's Specifier emits objectives
differing from the spec's four, the arm is void for the primary endpoint — otherwise the arms
are not optimising the same thing.

### The two dangerous failure modes

> **A model-B arm that silently executed mock tools on a GPU allocation, or a model-C arm that
> silently fell back to `ThresholdPolicy` and was reported as model C, is what this design most
> needs to exclude.** Both are silent: a mock chain completes `6/6 tasks ok` with plausible
> metrics, and a fallen-back C arm is byte-for-byte a D campaign. Neither is visible in the
> campaign log.

Each gets **structural prevention plus a positive check**. Mock-on-GPU: `_build_b` forwards
`stages`, `RehearsalOracle` derives its chain, and **gate 6** refuses a mock-toolkit node under
`tool_delivery: real` (Phase 10); the harness then asserts per arm that the tool set is exactly
the six real tools and that every absorbed node has real-shaped artifacts on disk (an rfd3
`backbone_*.pdb` ≥ 10 kB — the trajectory bug makes a size check meaningful — a `seqs/*.fa`
whose header matches the confidence regex, a Rosetta `result.json` carrying
`interaction_energy`, a Boltz `confidence_*.json`). **An arm failing any of these is not
published.** Model C: built with `on_timeout="stop"` and **no fallback**, so it stops rather
than running D, and `--model C` with no plane attached refuses at startup; the harness then
requires exactly one external directive per cycle, stamped with the driver's pid/host and a
monotonic id, zero degraded events, and `C_cycles == directives_received`.

### Prerequisite gate

**Blocks the smoke:** X1 (`max_cycles` not forwarded — else every arm makes 6 decisions in
~20 min), H3 (params reach real tools), **Phase 8's adapter selection landed and internal
sampling set to 8 with the declared cost and walltime re-derived at that setting** — before
that, 8 samples pay 8× for one design and an unchanged `walltime_s` reads as a hang —
H2 (live client, `stages`
forwarded, real chain composed — verified on a **login node**, which costs pennies), C5+C6
(`serve`/`reason`, fail-closed C), G4+G5 (the thresholds), G7 (recorded salt), G1
(`stagnation_limit > max_cycles`), A10 (GPU pinning, and budget route (b) — raising
`gpu_hours`, since the signature includes replica multiplicity so route (a) is impossible), A6
(launcher runs `impress-a preflight --quick`; the **deep** form runs once on a login node where
its 900 s LigandMPNN probe is free, and its printed elapsed time is the early warning for that
tool's `walltime_s`), E1/gate 6, **`impress-a validate-tasks` passing on every Task of the
chain** (the gate that justifies the next row), and **`impress-a trust --assert` applied to
every arm's ledger** for the six-stage chain at width 1 and width 4 plus the refinement
variant, with the reason naming this experiment and the validation run that justifies it.
**Blocks production:** A8 (refusal, and no tail truncation),
G8 (instrumentation), A11 (budget so gate 5 and the untrusted cap *cannot* bind — **do not
retune the cost models**), A5 (keep the bounds; a startup timeout voids the arm), per-arm trust
dirs. **Deferred:** H1 (registered in advance as the A≈D expectation), H6, B1, C1–C4, C7,
D1–D7 except D6, F1–F4.

### Smoke, then production

**Smoke** — `campaigns/delta-small-molecule-arms-smoke.yaml`, identical science to the arms
spec, differing only in how long it runs; **width 4 on purpose**, because this is the first
execution of `replicas > 1` and the production shape. `max_cycles: 6`,
`stagnation_limit: 7`, `tool_delivery: real`, `budget: {gpu_hours: 20.0, cpu_hours: 15.0}`
(sized so neither gate 5 nor the 10 % untrusted cap can bind — 2.0 cap vs 0.68 for one width-4
run), `replicas: 4`, `concurrency: 1`, objectives with `complex_plddt min: 0.75` so the front's
feasibility filter is not slacker than the gate. **Internal sampling at 8** —
`rfd3_design.num_designs: 8`, `ligandmpnn_design.batch_size: 8` with `number_of_batches: 1`,
`boltz_predict.diffusion_samples: 8`, `fastrelax.nstruct: 8` — so breadth is 4 lineages × 8
samples per sampled stage, with each stage selecting its best member. ALR target, with the
footgun recorded in a comment: **the ligand resname is the literal `A:R`, not `ALR`.**
The budget above is the figure **before** the 8-sample re-derivation; it is restated from the
Phase 8 smoke's measurements before this spec is submitted, because the declared cost is what
gate 5 refuses against.

```bash
export SBATCH_ACCOUNT=<project>-delta-gpu
export WORK_DIR=/work/nvme/<project>/$USER          # MUST be nvme: pyrosetta imports in 471 s off HDD
export IMPRESS_A_ARMS=A,B,C,D
export IMPRESS_A_EXPERIMENT=arms-smoke-$(date +%Y%m%d)
export IMPRESS_A_SEED_SALT=${IMPRESS_A_EXPERIMENT}
impress-a preflight campaigns/delta-small-molecule-arms-smoke.yaml    # deep, login node, 0 FAIL

# Step 1 - Task-level validation on real hardware, BEFORE any arm and before any assertion.
#          One short allocation, one pass of the chain, one row per Task. Non-zero exit on
#          any integrity row stops the experiment here.
sbatch --partition=gpuA40x4-interactive --time=00:40:00 \
       --job-name=impress_a_validate_tasks \
       scripts/delta_validate_tasks.sh campaigns/delta-small-molecule-arms-smoke.yaml

# Step 2 - only once step 1 is clean: assert trust per arm for the shapes the experiment runs.
#          The reason names the validation job, so the ledger records WHY trust was granted.
for M in A B C D; do
  IMPRESS_A_TRUST_DIR=${WORK_DIR}/_trust_arms/${IMPRESS_A_EXPERIMENT}/${M} \
  impress-a trust --assert campaigns/delta-small-molecule-arms-smoke.yaml \
      --replicas 1 --replicas 4 \
      --reason "proven toolkit from examples/small_molecule_binding; validate-tasks job <id> clean"
  IMPRESS_A_TRUST_DIR=${WORK_DIR}/_trust_arms/${IMPRESS_A_EXPERIMENT}/${M} \
  impress-a trust --list        # must show the shapes as asserted, 0 demotions
done

# Step 3 - the four arms.
sbatch --array=0-3 --partition=gpuA40x4 --time=01:00:00 \
       --job-name=impress_a_arms_smoke \
       scripts/delta_gpu_run.sh campaigns/delta-small-molecule-arms-smoke.yaml
```

**C** `scripts/delta_validate_tasks.sh` — the launcher for step 1: the same environment,
preflight and per-job directory as `delta_gpu_run.sh`, running `impress-a validate-tasks`
instead of a campaign, and writing `validate_tasks.json` + the per-Task table beside
`manifest.json`. Its job id is what the trust assertion's `--reason` cites.

4 node-h / **16 GPU-h**, ~96 draws. `--array` is the right device: one submission means one
submit time and one priority. Do **not** override `--output` — `impress_a_%j.out` expands per
array task, which is what the EXIT trap looks for.

**Launcher changes** (`scripts/delta_gpu_run.sh`): derive `MODEL` from `SLURM_ARRAY_TASK_ID`;
per-arm `IMPRESS_A_TRUST_DIR=${WORK_DIR}/_trust_arms/${IMPRESS_A_EXPERIMENT}/${MODEL}`;
`impress-a preflight --quick "$CAMPAIGN" || exit 1` before the `dragon` line; start
`nvidia-smi --query-gpu=... -l 10 > gpusample.csv` and kill it in `_finish`; write
`sacct --json` and `seff` **inside the job** in `_finish` (G9 cost a day to the opposite);
record `seed_salt`, `experiment`, `prereg_sha`, `arms`, `trust_dir` in `manifest.json`; for arm
C, start the sidecar `impress-a reason` on the same node.

**Smoke abort criteria** (stop and fix; do not proceed): any Task failing an integrity row in
step 1; any arm whose ledger does not show the asserted shapes, or shows a demotion of one; any
mock-toolkit task; any arm C fallback or directive-less cycle; a control-model log line
disagreeing with `manifest.json`; a width-4 run producing fewer than 4 `DesignNode`s or two
lineages with identical metrics; two lineages sharing a GPU index; zero finite
`interaction_energy`; **any** budget/interlock/objectives rejection (the budget was sized not to
bind, and the shapes were asserted, so one means either the sizing or the assertion is wrong);
any arm stopping on stagnation, a policy default, or the admission-failure cap; fewer than 3
cycles in 40 min; Dragon startup over 600 s.

**Production** — same spec file with `max_cycles: 200`, `stagnation_limit: 201`,
`budget: {gpu_hours: 100.0, cpu_hours: 60.0}`:

```bash
git rev-parse HEAD && git status --porcelain -uno     # must match the smoke; must be empty
export IMPRESS_A_EXPERIMENT=arms-prod-$(date +%Y%m%d)
export IMPRESS_A_SEED_SALT=${IMPRESS_A_EXPERIMENT}    # ONE salt, shared by all four arms
impress-a preflight campaigns/delta-small-molecule-arms.yaml
# A new experiment means new trust dirs, so the assertion is repeated against the PRODUCTION
# spec - the signature is computed at that spec's own declared width. Cite the smoke's
# validate-tasks job, not a new one: nothing about the Tasks changed between them.
for M in A B C D; do
  IMPRESS_A_TRUST_DIR=${WORK_DIR}/_trust_arms/${IMPRESS_A_EXPERIMENT}/${M} \
  impress-a trust --assert campaigns/delta-small-molecule-arms.yaml --replicas 1 --replicas 4 \
      --reason "proven toolkit; validate-tasks job <id> clean; smoke <id> clean"
done
sbatch --array=0-3 --partition=gpuA40x4 --nodes=1 --time=04:00:00 \
       --job-name=impress_a_arms \
       scripts/delta_gpu_run.sh campaigns/delta-small-molecule-arms.yaml
```

16 node-h / **64 GPU-h**, ≈ 230 draws per arm (≈ 58 cycles × 4 lineages at ~230 s/cycle).
`--time=04:00:00` overrides the script's 12 h backstop, which is right for one long campaign
and wrong for a fixed-window comparison. `--cpus-per-task=64` is not overridden: 64 cores is
free because 4 GPUs already bills the node under `PriorityFlags=MAX_TRES`.

**Held identical:** one spec file (sha256 recorded; the harness refuses to publish if the four
differ), target/ligand/SMILES/`fixed_residues`, thresholds, git sha and dirty flag, **one seed
salt**, budget, `replicas: 4`, `concurrency: 1`, `max_cycles`, `stagnation_limit`, partition/
nodes/GPUs/cores/memory/wall clock, submit time and priority, thread caps, and four trust
ledgers all starting empty. **Varied: exactly the `--model` letter.**

**Two choices that need their reasons on the record.** *`stagnation_limit > max_cycles`* is not
the fix G1 forbids: G1's complaint is that raising the limit *hides* a defect in the engine's
notion of progress, and the characterization tests stay untouched. This removes stagnation from
the role of a stopping rule and records `_stagnant` per cycle as a **dependent variable** —
necessary because the front will likely stay empty (most nodes miss `complex_plddt ≥ 0.75`), so
at the shipped limit of 4 an arm would end ~15 min into a 4 h allocation, and an arm's
terminating condition must be the allocation or the arms have different draw budgets.
*One shared salt* applies common random numbers: G7 measured the seed as the dominant variance
component (same-seed median TM 0.82 vs 0.28 across seeds), so sharing it removes "arm B drew
luckier backbones" as an explanation at an MDE already as coarse as 2.2×. It is variance
reduction, not exact pairing — rfd3 is not reproducible to coordinates (median Cα RMSD 2.4 Å) —
and the pairing is exact only for runs composing the same shape with the same parameters, so
the paired subset is reported as a secondary, lower-variance analysis. **Per-arm trust dirs**
are required, not optional: sharing one would let four concurrent processes each admit an
instance of an untrusted signature, breaking one-instance-in-flight *across processes*, and one
arm's evidence would subsidise the other three. **Each arm's dir is pre-seeded identically by
`impress-a trust --assert`**, so all four start with the same asserted shapes and none spends
allocation re-earning trust on a Toolkit that is already proven. Three consequences on the
record: promotion stops being an experimental outcome (there is nothing to promote for the
asserted shapes, and `on_clean_run` returns `False` for a trusted record, so no phantom
evidence accrues); "cycles to first trusted admission" is dropped as a secondary endpoint and
replaced by **admissions-under-scrutiny** and **demotions of an asserted pattern**, the latter
being the loud signal that an assertion was wrong; and **A10 stops binding** — width 4 could
never earn trust under a realistic budget because the signature includes replica multiplicity,
so asserting at width 4 is what makes the production shape runnable at all rather than
serialised behind one-instance-in-flight.

### Instrumentation

Per task, written by the `_run` closure in `exec/dispatch.py` (the only code that runs *where*
the task runs): `t_submit`, `t_start`, `t_end`, `host`, `pid`, `cuda_visible_devices`,
`gpu_index`, `peak_rss`; per-phase durations from `TaskAgent.__call__`; `cost_measured` beside
the unchanged `cost_estimated`; and the worker's `[phase]` lines **persisted** to
`work/<task>/worker.stderr` rather than only surfacing on failure. Per cycle, `decisions`
provenance for **every** arm (not only backtracks, as today): `t_decide_start`/`end`, the
decision kind, the rationale, and for B the model id, token counts and live-vs-fallback.
`transitions` carries `_stagnant` per cycle, promotions/demotions with cycle index, and every
rejection with gate and reason. Allocation level: `gpusample.csv`, `sacct.json`, `seff.txt`,
`manifest.json`. Handlers stay on our own loggers with `propagate = False` and stdout
line-buffered — Dragon's `Pool()` calls `_clear_root_log_handlers()`, and Dragon pipes stdout so
Python block-buffers it.

### The scoring harness

`src/impress_a/analysis/compare_arms.py`, `impress-a compare`. **Scored from provenance, the
ledgers and the on-disk Boltz/Rosetta outputs — never from a reasoner's own bookkeeping**,
which is sound here for a structural reason: IMPRESS-A's provenance is written by the executor.
For arm B the LLM transcript is read for decision-layer timing only, never for a yield, cost or
quality figure.

Metrics: draws attempted; T1/T2/T3 counts (tiered from the on-disk metrics joined by
`(run, lineage)`, not from a node's cached properties); **`C_Tk` cluster count**; exact-identity
upper bound; GPU-h per passing design charged per node; passing per node-h; integrity and
acceptance stage pass rates; **fastrelax `PROD` pass rate** against the reference's own 49–64 %
band; mpnn tasks per fold attempted (reference 6.8 healthy / 13.0 degraded; ours should read
≈1.0, and *that is the finding* — no MPNN screening); decision-layer share of wall clock;
**time-to-tenth, right-censored at `T_cut` and reported as `"> 3.25 h (censored)"`, never null
or zero**; GPU-busy share; `Σ cost_measured / Σ cost_estimated` per tool (the number that
closes G8); refusals by gate; `_stagnant` trace; trust transitions; per-stage wall-time
distribution against A11's 101-task baseline; and the integrity guards (mock count must be 0,
fallbacks 0, directives-per-cycle for C, spec/salt/git sha equality).

Twelve tests in `tests/test_compare_arms.py`, **green before the harness scores a real run**:
a fixture-driven synthetic run directory with every published figure asserted against a
hand-computed value; **per-node charging** (two arms with identical output at 1 and 2 nodes —
the sibling harness's exact 2× understatement, as a regression test); **no hardcoded pipeline
divisor** (7 rfd3 tasks reports 7, not 7/4 — its other bug); distinctness at θ = 0.90 vs 0.99
and the TM merge; **tier assignment against job 22692304's real metrics, which must land T1 and
not T2** — the project's best run as the test case; censoring; mock detection refusing to
publish; fallback detection marking void; **`test_says_sacct_is_unavailable_rather_than_
reporting_nan`** (G9's exact lesson, which once printed "at most nan% of the billed GPU time
had a GPU task running" as a finding); the one-variable guard refusing a comparison when shas
disagree; robustness to a truncated ledger and byte-identical rescoring; and the Poisson
contrast plus Holm adjustment against hand-computed tables.

### Feasibility, and the go/no-go

**The baseline arithmetic, at one sample per stage.** Measured per-stage medians give a 173 s
serial chain (matching job 22692304's 2 m 53 s); at width 4 with pinning, ~230 s per run;
225 usable minutes ⇒ **≈ 58 runs, ≈ 232 draws per arm**, 0.069 GPU-h per draw attempted. For
`P(X ≥ 10) ≥ 0.9` you need `N ≈ 14/p`, so at 58 draws per node-h the threshold is
**`p* ≈ 0.06`**. Best estimates: `p_T2 ≈ 0.27 × 0.67 × 0.33 ≈ 0.06` (at the boundary, before
the unmeasured `interaction_energy` factor, which can only lower it) and `p_T3 ≤ 0.04` with a
point estimate of 0. **So at one sample per stage, ten T3 designs is not reachable in a 4 h
1-node arm** — at `p_T3 = 0.01` the Goal would need 24 node-h *per arm*.

**At 8 samples per stage this arithmetic no longer holds, and it must be re-measured rather
than re-derived.** Three effects move in different directions and only their product matters:

- **Cycle time rises, sublinearly on the GPU stages.** rfd3, LigandMPNN and Boltz are tuned for
  batched output, so a batch of 8 costs far less than 8 sequential invocations — that is the
  whole reason for the setting. `fastrelax.nstruct: 8` is the exception: 8 serial CPU
  trajectories, scaling linearly, and on a node where CPU efficiency has measured ~42 % that is
  where the added wall clock will actually land.
- **Draws per cycle stay ≈ 1 per lineage**, because each stage selects its best member rather
  than fanning out 8-wide. So raw draw count per arm *falls*.
- **`p` per draw should rise**, which is the point: a best-of-8 backbone, a best-of-8 sequence
  and a best-of-8 fold is the reference's own shape, and the reference's median pLDDT of 94.4
  comes from exactly this plus refinement.

The product — distinct T2 designs per node-hour — is therefore **unmeasured**, and the plan does
not guess it. The Phase 8 smoke measures `p_T2` at 1 vs 8 samples on identical inputs, and the
arms smoke measures the 8-sample cycle time; the go/no-go's tier decision then uses those two
numbers instead of the baseline ones above. **If the arms smoke's cycle time and `p̂_T2` imply
fewer than ~14/`p̂_T2` draws in 4 h, the sizing is raised there and not after the fact.** Two
figures to watch for a *negative* result: a total wall clock per cycle more than ~3× the 230 s
baseline would mean the batch is not amortising and `nstruct` should come back to 1; and
GPU-busy share failing to rise above the ≤17 % already measured would mean the batch never
reached the device.

**Go/no-go (production only if every row holds).** **`impress-a validate-tasks` exited 0 with
every Task's integrity rows clean, and its per-Task table is on file** — this is the row the
trust assertion rests on, so it is first. **Every arm's ledger shows the asserted shapes at
both widths, marked `asserted` rather than earned, with zero demotions**, and `graphs`
provenance shows r0001 admitted trusted with no forced dry-run and no cost cap.
**Admissions-under-scrutiny recorded per arm**, so the exploration confound is a number rather
than a surprise. Zero mock tasks. Arm C: one directive per
cycle, zero fallbacks. Arm B: live model id every cycle, zero degraded, heartbeat continuous
across each call. Control-model log line matches `manifest.json`. ≥ 6 cycles per arm with no
stagnation/default-`max_cycles`/budget/interlock/admission-cap stop. **Every width-4 run
produced 4 `DesignNode`s with distinct metrics** (A10's independence invariant, first
execution). Four distinct GPU indices and ≥ 2 GPUs busy simultaneously. Finite
`interaction_energy` on ≥ 95 % of completed fastrelax tasks. All six new acceptance gates seen
firing on real numbers, `pytest tests -q` green including the moved fixture. Per-task
timestamps and `cost_measured` on 100 % of tasks, with
`cost_measured/cost_estimated ∈ [0.05, 1.0]` for every tool — **above 1.0 means a declared
figure is below measurement and gate 5 would start refusing real work**. `sacct.json`,
`seff.txt`, `gpusample.csv` present. Harness clean on all four dirs with its own suite green.
**θ frozen** in the pre-registration commit. `p̂_T1 ≥ 0.6`. **Every sampled Task produced 8
members and selected from them** — not 8 members discarded down to `[0]`, and not 1 member from
a flag that silently did nothing — with `--batch_size 8 --number_of_batches 1` visible in the
LigandMPNN argv, and the per-cycle wall clock within ~3× the one-sample baseline. And the tier
decision, now computed from the 8-sample measurements rather than the baseline ones:
**`p̂_T2 ≥ 0.06` ⇒ proceed as planned; `0.02 ≤ p̂_T2 < 0.06` ⇒ raise to 1 node × 8 h per arm
(32 node-h) with a recorded justification; `p̂_T2 < 0.02` ⇒ no-go on the yield comparison** —
re-scope to a plumbing-and-contract comparison on T1 per node-h, decision-layer share and
refusal behaviour, and report it as such.

---

## Verification

| Level | Command | Proves |
|---|---|---|
| Unit + integration, every phase | `cd agent && pytest tests -q` | The whole local tier, no allocation. ~2 min on a login node |
| Lint, from Phase 0 | `ruff check src tests` | Now resolves to `agent/`'s own config with `fix = false`, so it reports rather than rewrites |
| Parity, Phase 1 | `pytest tests -q -k roles_pipeline_reproduces` | The strangler's seam: the new pipeline is behaviour-identical before anything moves |
| Local end to end, every phase | `impress-a run campaigns/mock-stabilize.yaml --model D` and `--control roles` | A complete campaign on mock tools: real manager, roles, composer, gates, interlock, tree, provenance |
| Branching, Phase 4 | `impress-a run campaigns/mock-branch.yaml --model D --control roles` | Independent Aims in parallel, a DEFER→plan transition, DELETED→CANCEL |
| Over a socket, Phase 3+ | `pytest tests/test_http_adapter.py tests/test_remote_session.py -q` | A campaign driven end to end over loopback, and a reasoner genuinely out of process |
| **Split parity, Phase 7** | `pytest tests -q -k split_control_plane_reproduces` | The two-process topology produces the same tree, front and stop reason as one process — so a later failure is a transport failure and nothing else |
| **Non-blocking, Phase 7** | `pytest tests -q -k blocking_specifier_does_not_stall` | A Specifier that blocks *synchronously* cannot stall execution. The test that justifies the split, and the one that fails without it |
| **Supervision, Phase 7** | `pytest tests -q -k control_process_dies` | In-flight Stages are absorbed, no new Stage is admitted, and the campaign stops with `control_lost` rather than holding the allocation |
| Split end to end, Phase 7+ | `impress-a serve campaigns/mock-stabilize.yaml &` then `impress-a control --connect <url> --model D` | The target topology on a laptop, same result as the single-process run |
| Import contract, every phase | `pytest tests/test_layering.py -q` | `policy → core` only; `compose ↛ exec`; `impress` imported only by the Runner; every layer in the table |
| Toolkit contracts, Phase 10 | `pytest tests/test_gate_fixtures.py tests/test_real_toolkits.py -q` | Every real tool's gates against its known-bad fixtures; tool counts derived from disk |
| **Asserted trust, Phase 3** | `pytest tests -q -k "asserted_trust or trust_assert"` then `impress-a trust --assert <spec> --reason …` and `--list` | The shortcut exists, refuses a reasonless assertion, computes the signature at the declared width, stays distinguishable from earned trust, and still demotes |
| **Per-Task validation, Phase 10** | `pytest tests -q -k validate_tasks` then `impress-a validate-tasks <spec>` on an allocation | Each proven Task actually runs here: declared outputs, typed and on disk; metrics finite; integrity vs acceptance separated; measured wall time and cost against the declared figures. The gate the trust assertion rests on |
| Harness, Phase 10 | `pytest tests/test_compare_arms.py -q` then `impress-a compare <dirs>` | The scorer is right *before* it scores a real run |
| Hardware, Phase 5/6/8 | `impress-a preflight <spec>` then `sbatch scripts/delta_gpu_run.sh campaigns/delta-small-molecule-smoke.yaml` | GPU-second accounting, Dragon placement and affinity, bounded teardown — none provable locally |
| Experiment | the two `sbatch --array=0-3` lines above, then `impress-a compare` | The four arms, against the pre-registered endpoint and go/no-go |

## Flagged as partial or not implementable as written

1. **"The Workflow Engine cancels Tasks flagged CANCEL"** — implementable for PENDING/queued
   tasks, **advisory for RUNNING ones**. Measured, not assumed: `Future.cancel()` returns
   `False` once the callable has started, asyncflow discards that answer, and `impress`'s
   `kill_parent` never reaches the backend. Reclaiming a GPU from an abandoned run (C4) is
   unsolved and out of scope.
2. **"The Listener stops the workflow"** — implemented as a *request*. The executor decides
   termination; budget, stagnation and repeated failure are facts a role cannot see.
3. **"The Spec may change at runtime"** — true at Spec level, false at Stage level. A deployed
   Stage's task set is immutable because `register_pipeline_tasks()` runs once from `__init__`;
   a revision produces a **new** Stage.
4. **Three processes as three OS processes** — delivered as **two**, not three. The Reviewer's
   `dry_run` instantiates task agents, so admission must run where the toolkit is installed;
   the Reviewer and Deployer therefore sit execution-side, and the Planning Loop is split across
   the boundary (Planner in the control process, Reviewer+Deployer in execution) rather than
   being a process of its own. The Planner still gets a synchronous accept-or-reject, which is
   what the outline's review-then-route-back actually requires.
5. **"Maximum allocation commitments"** — honest only after Phase 5. Before it, every
   commitment is a declared figure sitting 2.25×–69× above measurement, so a commitment-based
   refusal would refuse work that fits.
6. **"The production ensemble" as a new Data type** — declined. `CampaignTree.live()` +
   `pareto_front()` already are it; a second representation would be a second truth.
7. **The ten-sequence Goal** — not reachable before Phase 8, and possibly not after; the
   go/no-go routes to a plumbing-and-contract comparison if the smoke says so.

## Out of scope

The experiment's second replicate (needed for any claim below 2.2×, 32 node-h); checkpoint/
restart resume (`RunService.reattach()` stays caller-less — resuming needs Spec, registry and
budget reconstructible together, and the chosen supervision policy is drain-and-stop rather
than reconnect, which is what makes leaving it out acceptable); a third process for the Planner
(its Reviewer cannot leave the toolkit); structural QC gates beyond the G4/G5 calibration (B1, which
follows G2); replacing `BudgetLedger.holds`; renaming `core/pareto.Objective`; an MCP adapter;
P4/P8 external patterns; multi-site; H6 beyond Phase 0's local ruff config; deleting
`exec/dispatch.py` wholesale.
