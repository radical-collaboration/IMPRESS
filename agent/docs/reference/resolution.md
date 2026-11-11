# Resolution: from caller inputs to a programmed Stage

How a campaign's four inputs — **the toolkit, the goal, the budget and the parameters** — become
the targets the campaign is scored on and the work it actually runs.

This page is the spine. Every step says what it takes, who owns it, what it produces and what
refuses it, in the order a campaign executes them. Steps 4 to 6 are the ones a reasoner takes part
in, and what each model is *shown* when it does is [`control-models.md`](control-models.md);
[`architecture.md`](architecture.md) covers the loop around all of this. If this page and the code
disagree, the code is right and this page is a bug.

Two things to read it for. **Reconciling the implementation against a theoretical account** of what
an adaptive campaign ought to do — for which the last section, *What the pipeline does not
enforce*, is the important one. And **changing any of this safely**, for which the refusal named in
each step is the thing to preserve.

```
toolkits/*/tools/*/spec.yaml ──load, validating──→ Registry.specs           step 0
campaign.yaml ──load_spec──→ CampaignSpec                                   step 1
   ├─ goal, objectives, budget, target_front ──goal_from_spec──→ Goal       step 2
   ├─ stages ──view_of──→ ToolkitView      (narrowed; frozen hidden)        step 3
   └─ params, replicas, loop bounds ───────→ the executor keeps these
Goal ──initial_spec (no toolkit in the room)──→ Spec: Aims + SpecObjectives step 4
Spec × ToolkitView ──reporting()──→ which targets are producible at all     step 5
Spec.ready() × ToolkitView ──_resolve + _knobs──→ Stage[TaskMapping]        step 6
Stage ──compose_stage──→ TaskGraph ──Reviewer + Scrutiny──→ RunRecord       step 7
RunOutcome ──ingest──→ readings ──satisfies──→ targets closed               step 8
```

---

## Step 0 — the toolkit becomes a typed vocabulary

**In:** `toolkits/<toolkit>/tools/<id>/spec.yaml` plus the toolkit's `SKILL.md`.
**Owner:** `tools/registry.py`. **Out:** `Registry.specs: {tool_id: ToolSpec}`.

Discovery walks the search paths, `IMPRESS_A_TOOLKITS` included, so toolkits are **not package
data** — a tool can be added without touching the package.

**Loading is validating** (`Registry._load_toolkit:52`). A malformed spec, a default outside its
own declared range, a `qc_gates` entry naming an unimplemented check, a duplicate tool id, or a
`SKILL.md` missing one of `REQUIRED_SKILL_SECTIONS` (`:19` — Purpose, Canonical sequences, Cost
posture, Pitfalls) is a load-time error. And it is **all-or-nothing per toolkit**: a toolkit that
fails anywhere registers *nothing*, never a partial set, so a campaign can never plan against half
a toolkit.

What each `ToolSpec` carries that a later step reads:

| declared | read by |
|---|---|
| typed `inputs` / `outputs` ports | steps 6 and 7 — chain resolution and gate 1 |
| `parameters` with `min`/`max`/`default`/`trades`, `frozen_parameters`, `operator_only` | step 6 (`_knobs`), gate 3 |
| `metrics` — the metric names this tool's agent reports | step 5, the whole producibility question |
| `qc_gates`, each `role: integrity \| acceptance` | step 8, and trust ([decision 0013](../decisions/0013-trust-counts-integrity-not-acceptance.md)) |
| `cost_model`, `resources` | gates 4 and 5, the interlock's cap |

`metrics` is **declared, never inferred** (`tools/spec.py:127`). Inferring it from
`metric_in_range` gate parameters was tried and warned falsely on the mock campaign, whose tools
emit `ddg`/`iptm`/`sc_rmsd` and gate on none of them — so a graph that demonstrably produced a
four-node front was reported as unable to produce anything. The declaration is held honest at
runtime by the `metrics_reported` gate (`tools/gates.py:85`): an adapter that could not read a
value must **omit** it rather than report `0.0`, and that gate, not the threshold, is what catches
it.

## Step 1 — the campaign YAML becomes a `CampaignSpec`

**In:** `campaigns/<spec>.yaml`. **Owner:** `cli.load_spec:69`. **Out:** `CampaignSpec`.

The rule this loader is written to, recorded in its own comment: **every field is read
exhaustively, because a key a spec file sets and the loader ignores does nothing and says
nothing.** `control_liveness_timeout_s: 120` sat in all three Delta specs doing exactly that until
the line existed, and `sites/*.yaml`'s `tool_delivery` switch is the same shape still open
(backlog E1).

Three resolutions worth naming:

- **`objectives:` → `core.pareto.Objective(**o)`.** The caller's target schema *is* the
  ranking-objective type (`core/pareto.py:21`): `name`, `direction`, and optional `min`/`max`.
  There is no second vocabulary for "what the campaign wants".
- **`params:` → `_resolve_path_params:53`.** A relative `*_path` value is resolved against **the
  campaign YAML's directory**, not the CWD, because the launcher cds into a per-job directory
  before loading the spec; an absolute path would tie the spec to one checkout on one machine.
- **`replicas: 0` means unset, not one.** `replicas` is a *cap* (step 6), and defaulting it to 1
  would silently narrow every campaign that never mentioned it.

`root`, `trust_root` and `seed_salt` are read from the environment when YAML does not set them,
deliberately: the right value is machine-specific or must be shared across several submissions of
one spec, and YAML carries no env expansion.

## Step 2 — the split: what the campaign is *for* vs how it is *driven*

**In:** `CampaignSpec`. **Owner:** `runtime/roles.goal_from_spec:210`. **Out:** `Goal`.

The `Goal` carries `text`, `objectives`, `budget` and `target_front` — and deliberately nothing
about the loop. `target_front` crosses because it is success criteria ("ten designs over the bar"),
while `max_cycles`, `stagnation_limit` and `concurrency` stay on the `CampaignSpec` for the
executor because they are statements about how the engine gets there. That split is what makes
`Goal → Spec` a statement about the science rather than about the engine, and it is why a
Specifier can be handed the Goal and nothing else.

Two of the `Goal`'s own fields are inert: **`reference_data` is never populated and never read**,
and **`walltime_s` is never read**. The caller's input *data* therefore does not travel as typed
reference data — it travels in `params:` as `input_spec_path`, `ligand_smiles` and their like (see
*What the pipeline does not enforce*, finding 1).

## Step 3 — the toolkit is projected, and narrowed to the campaign

**In:** `Registry` + `CampaignSpec.stages`. **Owner:** `tools/view.view_of:55`, called once at
`runtime/executor.py:255`. **Out:** `ToolkitView` — the only toolkit a reasoner can ever see.

`policy` may import `core` only (ADR 0010, asserted by `tests/test_layering.py`), so a reasoner
cannot hold a `ToolSpec` or a `Registry`. `card_for:14` projects each spec into a `TaskCard`, and
`runtime` is the one layer that can see both sides.

**Narrowing to `stages:` is a safety property, not economy.** A Specifier shown the mock toolkit on
a real campaign can map the Goal onto outputs that would then execute mocks on a GPU allocation —
the headline bug of the real-toolkit work. Gate 6 refuses such a graph; this keeps it from being
proposed. `mock_noodle` is the reason the floor matters: it completes successfully, reports a
confident `designability`, and produces a structure with no secondary structure.

`card_for` is also the **single seam** where a parameter is hidden from a reasoner. Both
`frozen_parameters` and `operator_only` arrive in `TaskCard.frozen` with their reason and are
absent from `TaskCard.parameters`, so everything that reads a card — `_knobs.tunable`, the oracle
planner's prompt, its schema check — treats them alike without a flag threaded through four
readers. `ToolSpec.parameters` keeps an `operator_only` entry, so gate 3 and the campaign's own
`params:` see it exactly as before: the campaign may set `difficulty`; a reasoner may not propose
it.

`ToolkitView.skills` is filled with each toolkit's `SKILL.md` text here and reaches no prompt
(finding 6).

## Step 4 — targets: `Goal → Spec`, with no toolkit in the room

**In:** `Goal`. **Owner:** `ThresholdSpecifier.initial_spec:59`. **Out:** a `Spec` of `Aim`s and
`SpecObjective`s, applied by the executor.

One `Aim` from the Goal's prose, then one `SpecObjective` per declared objective, with
`targets=[name]` — **names, never sources** ([decision 0012](../decisions/0012-one-property-two-sources.md)),
so a measurement arriving months later supersedes against the same name.

The satisfaction rule attached here decides everything downstream:

| declared objective | rule | `n` |
|---|---|---|
| bounded (`min` and/or `max`) | `metric_in_range` | `target_front`, or 1 |
| unbounded (direction only) | `metric_present` | always 1 |

An objective with a direction and no bound is an **optimisation target, not a finish line**: it
ranks and never prunes, so what the campaign owes it is a *measurement*. Raising `n` on one would
be meaningless — ten readings of a number nobody has to beat say nothing more than one.

And `n` counts **readings**, not distinct designs: `DataRegistry.satisfies` is
`len(metrics(metric)) >= n`, one row per (task, metric) per ingested outcome. The experiment's own
endpoint — distinct designs after sequence clustering — is a different and smaller number. This
rule is a stopping condition, not a score.

`initial_spec` takes the Goal **alone**; the toolkit arrives only with the observation, at step 5.
That is deliberate, and it is why models A and B both *delegate* this call to model D's Specifier:
every arm of a comparison must start from the same objectives, and a model asked to restate four
objectives it was given can only get it wrong.

## Step 5 — which targets this toolkit can inform

**In:** `Spec` + the observation's `ToolkitView`. **Owner:** `ToolkitView.reporting(metric)` and
`ThresholdSpecifier.unproducible:104`, run **per cycle**. **Out:** the open objectives that no
enabled tool can measure.

```python
for obj in spec.open_objectives():
    if obj.targets and not any(view.reporting(t) for t in obj.targets):
        out.append(obj.id)
```

Read off the *enabled* view, not the registry: a campaign that narrowed its stages has narrowed
what it can produce, and saying otherwise is the mock-chain-on-a-GPU failure in another form.

What happens next is the one genuine difference between the control models at this step, and it is
pre-registered rather than incidental: **model D** records `unproducible` in the statement and
leaves the objective OPEN, so its Spec can never complete while one exists; **model A** retires it
by DELETE; **model B** retires on `action: "retire"`. Both answers are defensible; they are not the
same campaign. On the real six-stage chain every declared objective is producible, so the branch
does not fire there.

`failed()` (`:190`) returns **only** the unproducible. Everything else is a matter of more draws,
and at the one-in-three acceptance rate this project has measured, calling that failure would end
most campaigns that were merely unlucky.

### "Available" means three different things

| scope | computed by | who sees it |
|---|---|---|
| everything installed | `Registry.ids()` | nobody in `policy` |
| the campaign's chain | `ToolkitView` | the Specifier and the Planner |
| **this graph** | `_producible_metrics(graph)` (`executor.py:719`) | the executor only, as a gate |

The executor checks the third scope itself, trusting no reasoner's account:

- **`_objectives_without_a_producer:751`** — campaign objectives no tool *in the admitted graph*
  reports. A **refusal** on the Stage path (`gate="coverage"`). Job 22675512 is why: a budget
  correction truncated `boltz_predict` off the chain, taking the only producer of `complex_plddt`
  and `ligand_iptm` — two of four objectives. The composer and validator never receive
  `spec.objectives` at all, so the graph was type-correct, affordable, admitted, and incapable of
  informing half of what it was for. The admitted graph recorded `rejected: null`.
- **`_could_reach_the_front:734`** — the same comparison restricted to *constrained* objectives,
  because unbounded ones rank but never prune, so missing one costs a node nothing.

The gap between scopes two and three is where that campaign was unwinnable from the moment it was
admitted.

## Step 6 — the Stage is programmed

**In:** `Spec.ready()` — open objectives whose dependencies are SATISFIED (`core/spec.py:218`) —
plus the `ToolkitView`. **Owner:** `ThresholdPlanner.plan:100`, which A, B and C all delegate to.
**Out:** a candidate `Stage` of `TaskMapping`s.

### Which tools, and how they wire

`_resolve:189` selects **by output type, never by chain position**:

1. For each ready objective's `targets`, `_producer_of:240` returns the **earliest** enabled tool
   declaring that metric. Earliest rather than best: a metric reported twice in one chain
   supersedes by name (ADR 0012), so taking the earlier producer never loses the later one, while
   taking the later could drop the chain that feeds it.
2. `_require:251` adds that tool and recurses through its **required** input ports, finding each
   port's producer with `_source_for:274` — the nearest tool declared *before* the consumer whose
   output `unifies_with` the port. Restricting to earlier tools is what keeps the result acyclic
   with no topological pass: the campaign's declared order is the only ordering either side has.
3. Producers for every **declared campaign objective** are added even when only one objective is
   ready, because a node missing one of those can never be feasible and so can never reach the
   front whatever the science did. Planning the minimal chain for one refinement objective
   produced a child measured on `iptm` alone, incomparable with everything already on the front,
   and unwinnable from the moment it was planned.
4. The chain is sorted into the **campaign's** declared order, and a ready objective no enabled
   tool can measure gets a `Deferral` naming what it waits on — never a silent drop.

The same unification rule is used by the composer and gate 1, so a Planner, a validator and a
composer agree about what satisfies what.

One `TaskMapping` per tool **per lineage**, carrying the served objective ids, the typed `inputs`,
and `params`. Attribution is at **lineage granularity** and that is a property of the engine:
`_absorb` produces exactly one `DesignNode` per lineage, with that lineage's whole chain merged
into one candidate judged on *all* the objectives. So tasks are not severally responsible for
separate objectives — which is why `rfd3_design`, reporting no campaign objective at all, is
indispensable to every one. The cost is recorded rather than hidden: deleting one objective can no
longer orphan a single task, only a whole lineage once *every* objective the Stage serves is
DELETED, which is still decidable and is what `TaskMapping.objectives` being a list exists for.

### Which parameters may move, and how far

What a parameter is *for* is read from the one sentence the spec gives about it —
`ParamCard.trades` — by `policy/planners/_knobs.py`, shared by every Planner half because what a
parameter means is a property of the Toolkit, not of a control model.

| kind | example | raising it | may a Planner? |
|---|---|---|---|
| **quality** | `diffusion_steps`, `recycles` | the same draw, harder | yes — the refinement axis |
| **diversity** | `temperature` | a different draw, same cost | yes, and nearly free |
| **breadth** | `num_designs`, `batch_size`, `nstruct` | more draws, more cost | **no** |
| **identity** | `seed` | a different lineage | **no** |

`kind_of:48` returns `None` for a sentence that says nothing *and* for one naming two kinds —
ambiguity is refused rather than guessed, because a planner resolving a spec's ambiguity is how a
GPU bill doubles. `tunable:60` additionally demands a numeric type, declared bounds and a default,
and excludes anything in `card.frozen` (so `operator_only` lands here). Breadth is excluded **on
evidence**: `rfd3_design`'s own spec records that `num_designs` stays at 1 because its adapter
keeps index 0, and the tools whose adapters *do* select from an ensemble already carry 8 as their
declared default. Identity is excluded because moving `seed` would break the independence of the
replica lineages the arm is credited for.

How far a knob moves is the one thing each model does differently (`control-models.md`): D steps
`step_up:91` a quarter of declared headroom per refinement and nothing while exploring, because a
rule-driven arm has no business inventing a vector from no evidence; A sets `at_fraction:72` from
the strategy its model named; B names values itself.

### Then the campaign's own parameters are merged — underneath

`executor._apply_campaign_params:800` (and `_apply_campaign_defaults:772` on the intent path)
merges `CampaignSpec.params` into the Stage as **defaults under** whatever the policy set: *the
policy always wins on any key it did set.* Target identity lives there —
`boltz_predict.ligand_smiles`, `rfd3_design.input_spec_path`, the contig — so a reasoner never has
to learn a tool's parameter names to run a campaign correctly, and `difficulty` can be a campaign
condition no model is shown. A roles-driven Delta campaign once ran `boltz_predict` with no ligand
because this merge was missing on the Stage path; it does not fail, it models no ligand and the
front optimises the wrong objective.

`replicas` is the exception to that order, because it is a **cap**:
`min(intent.replicas, spec.replicas)`. How wide a campaign *may* go is the campaign's call; how
wide to go within that is the policy's, so a policy that shrinks its request after a rejection
still shrinks.

**The merge order has a consequence worth knowing before you set a knob in `params:`.** A
Planner's escalation is computed from the **tool spec's declared default**, not from the campaign's
value — `step_up` is `base = float(param.default)` — and the policy wins on any key it set. So a
quality knob a campaign raised **above** that default is *lowered* by the first refinement. Read
off `arm-rescued-D`'s own `stages.jsonl`:

| knob | spec default | the campaign set | cycle 1 (explore) | cycle 2 (refine) |
|---|---|---|---|---|
| `rfd3_design.diffusion_steps` | 50 | **200** | 200 | **88** ← `50 + (200−50)/4` |
| `packmin.cycles` | 1 | **5** | 5 | **2** ← `1 + (5−1)/4` |
| `boltz_predict.diffusion_samples` | 8 | **25** | 25 | **25** — breadth, so no planner touches it |

Nothing is wrong at any one step: exploring emits no parameters, so the campaign's values stand;
refining escalates from the tool's own headroom, which is the only scale a planner can reason
about on a chain nobody wrote its numbers for; and the policy must win, or a campaign's defaults
would override the decisions being measured. The composition of the three is still that **a
campaign cannot raise a quality floor that survives its own first refinement** — only a breadth or
frozen parameter persists. Backlog G17.

## Step 7 — the Stage becomes a graph, and is admitted

**In:** `Stage`. **Owner:** `compose.composer.compose_stage:83`, then
`runtime/reviewer.StageReviewer.review:106`, then the interlock. **Out:** a `RunRecord`, or a
`ValidationFailure` with the gate that refused it.

Three properties `compose_stage` preserves, because the rest of the system rests on them:

- **Shape only reaches `pattern_signature()`.** Stage id, generation, attempt, rationale,
  deferrals — and **parameter values** — are excluded, so tuning a parameter never resets a
  pattern's accumulated trust.
- **Lineages stay independent.** A replica is a whole chain, never a fan-out that funnels back, and
  each gets its own seed from `_replica_seed:18` over the run label, the lineage index and the
  campaign's `seed_salt`.
- **P6 is inlined, never scheduled** — a scheduled P6 node is a composer bug (gate 4).

A refinement Stage's root tasks are seeded from the parent design's artifacts by **declared type**
(`_seed_inputs`), not by name: the producer names an artifact for its own output port and the
consumer for its own purpose, so matching by name would work only where the two happen to agree.

Then the Reviewer, cheapest refusal first, which is deliberate because only the last step
instantiates anything:

| layer | refuses |
|---|---|
| **coverage** (`:40`) | a ready objective neither planned nor deferred; a task serving no live objective; a task naming an objective not in the applied Spec |
| **gates 1–6** (`compose/validate.py`) | type mismatch · cycles, empty graph, missing QC gates · out-of-range, unknown or frozen parameters · P6 scheduled, resources over the site, unproven GPU portability · estimate over remaining budget · mock tools under `tool_delivery: real` |
| **budget** (`:88`) | the Stage-level commitment gate 5 cannot see. Marked `transient`, because contention is a property of the moment rather than of the graph |
| **dry-run** (`:186`) | every task agent parameterizes *without* executing |

**Coverage reads the executor's applied Spec, never the Stage's claim about what is open.** Not
trusting that claim is the Reviewer's entire purpose: a Planner that could assert a smaller Spec
could widen its own coverage to whatever it had chosen to do. It is also why the Spec has a single
writer on the execution side, so a remote Planner cannot smuggle a revision in with a Stage.

Admission then applies the interlock (`compose/interlock.Scrutiny.for_pattern:225`). An untrusted
pattern runs under a cost cap of `provisional_budget_fraction` (0.10), a **mandatory** dry-run, an
auto-`suspect` result marking whatever the outcome, and at most one instance in flight — because
promotion counts *consecutive* clean runs, and concurrent instances are one draw sampled N times.

`transient` matters to what a Planner may do about a refusal: `budget` and `interlock` are
answerable by asking for less at once, so `replan` **shrinks breadth and never the chain**.
Truncating the tail is a cost heuristic that knows nothing about what the graph can then measure,
and it is what took the only producer of two of four objectives off job 22675512.

## Step 8 — the loop closes, and the two populations part

**In:** a `RunOutcome`. **Owner:** `core/data.DataRegistry` and `core/pareto`. **Out:** closed
targets, a new front, and the next cycle's evidence.

`ingest:85` records one `RealizedDatum` per node, per (task, metric) reading and per output
artifact — **with no reference to the QC verdict**. `satisfies:129` then counts those readings
against each objective's rule, and `BaseSpecifier.satisfied` (`policy/specifier.py:106`) asks the
registry. **No shipped half overrides it**, so the stop condition is *computed, never argued*: the
protocol permits an override and says such a Specifier owes an explanation in provenance, and
nothing in `policy/` takes it.

Meanwhile `pareto.feasible:56` admits a node to the front only if `qc.eligible_for_front` — a
`FAIL` verdict is never eligible, whatever its scores, because these tools fail silently and an
exit code is never sufficient evidence.

So **satisfaction and the front read two different populations**: readings, and eligible designs.
They can disagree completely, and finding 3 below is what that costs.

`ThresholdSpecifier.revise:120` is the one place the implementation already compensates. When the
front is non-empty it adds at most one refinement objective naming the design to improve on
(`parent_node`), with its threshold bound to **new** evidence as `n = hits + 1` — because
satisfaction counts everything realized so far, the parent's own measurement included, so a
default `n=1` rule would be met the instant the objective existed, and the open-refinement cap
would never bind because a satisfied objective is not an open one.

Termination is the **executor's**, never a reasoner's: budget, stagnation, repeated failure and
the abort rule are facts about state a reasoner cannot see. A reasoner may *request* a stop. An
empty Spec is complete (`core/spec.py:233`), which is what makes a Specifier that declines to
specify anything end the campaign through the designed path with no special case anywhere.

---

## What the pipeline does not enforce

Seven places where the implementation does not do what a reader of the design would reasonably
assume. Each is verified against the source at the anchor given. **Read this section first before
changing any step above.**

| # | the reasonable assumption | what the code does | anchor | item |
|---|---|---|---|---|
| 1 | The caller's input files reach a graph as `Goal.reference_data`, and gate 1 checks that every required root port was satisfied | `reference_data` is **never populated and never read**. Gate 1's required-root-port loop is a literal `pass` commented `# roots may be satisfied from campaign inputs`. Input data arrives as `params:` entries, and **nothing validates that a root port was satisfied at all** | `core/goal.py:55`, `compose/validate.py:79-81` | H4, and A2's neighbour |
| 2 | A budget gate prices what a Stage will actually consume | `Validator.estimate` sums `cost_model.cost` **per node**. Raising a breadth parameter buys N draws and costs nothing in any gate | `compose/validate.py:142` | H10 |
| 3 | A campaign cannot report every target satisfied while producing no usable design | Satisfaction counts **readings** (`ingest` records metrics whatever the QC verdict); the front counts **eligible nodes**. Both are reachable at once, and the abort rule is reached by *running cycles*, so a Specifier that declines to add a refinement objective stops before it | `core/data.py:85,129` · `core/pareto.py:56` | G14, H11 |
| 4 | A reasoner's cycle and front bounds come from the campaign | `ReasonerOptions.max_cycles` and `.target_front` are read by **nothing** in `policy/`. They are forwarded so a model's own bound can never be tighter than the campaign's (X1); the `RehearsalOracle` literals that consumed them were deleted. `target_front` reaches a Specifier through `Goal` instead | `policy/registry.py:80-81` | H4 |
| 5 | `Goal.walltime_s` bounds a campaign's wall clock | read by nothing. On HPC SLURM's `--time` is the real backstop | `core/goal.py:74` | H4 |
| 6 | The guidance written for an agent reaches one | `Registry.toolkit_skills()` has no caller, and `ToolkitView.skills` is populated by `view_of` and included in no prompt | `tools/registry.py:86`, `tools/view.py:67` | H4 |
| 7 | A knob a campaign sets in `params:` stays set for the campaign | A **quality** knob raised above the tool spec's default is *lowered* by the first refinement, because `step_up` escalates from that default and the policy wins the merge. Only breadth and frozen parameters persist — measured on `arm-rescued-D`, step 6 | `policy/planners/_knobs.py:91`, `runtime/executor.py:800` | G17 |

Two further asymmetries that are **by design** and are listed so they are not mistaken for the
above. An unbounded objective can never be *unsatisfied*, only unmeasured, because direction ranks
and only `min`/`max` prune. And only **integrity** gate failures count against a pattern's trust;
an acceptance failure still FAILs the node and keeps it off the front but says nothing about
whether the pattern is sound — counting quality thresholds made promotion a function of target
difficulty, and job 22702568 ran 30/30 tasks clean and promoted nothing
([decision 0013](../decisions/0013-trust-counts-integrity-not-acceptance.md)).

## Seeing it on disk

Every step's output is in provenance, which is the only way to check this page rather than trust
it. `impress-a mock-lab --only arms --stage sweep` writes one campaign per arm in about half a
minute with no allocation:

| step | where it landed |
|---|---|
| 1 | `specs/<cell>.yaml` — the `CampaignSpec` that cell actually ran |
| 4, 8 | `runs/<cell>/*/provenance/specs.jsonl` — each revision as the executor applied it |
| 6, 7 | `.../stages.jsonl` — `deployed` carries `mappings`, the full per-task parameter vector; a refusal carries its gate and reason |
| 7 | `.../graphs.jsonl`, `jobs/ledger.jsonl` — the admitted graph and its outcome |
| — | `.../decisions.jsonl` — what a reasoner was asked and answered, when one was asked |

A step whose output cannot be pointed at in one of those files is a step this page has described
wrongly.
