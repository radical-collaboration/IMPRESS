# Control models: what each reasoner is shown, and what it may choose

The four reasoners, as they run today. `resolution.md` is the pipeline all of them drive —
caller inputs to specified targets to a programmed Stage; this page covers the four places a
model's choice enters it, what the model is shown when it does, and how its answer is constrained
before the engine acts on it.

Anything true of every campaign is in `resolution.md` and is not repeated here.

## The letters

Every reasoner is a **Specifier half and a Planner half** (`policy/registry.py:385`,
`build_roles`). `decide(obs) -> Decision` was deleted in phase 11 and nothing else is a reasoner;
`manager._reasoner` raises `TypeError` on anything that is neither a pair nor a `conduct`
implementation.

| letter | Specifier half | Planner half | calls/cycle | status |
|---|---|---|---|---|
| **A** four-node loop | `hypothesize` (**call**) → `analyze` | `select_tasks` (**call**) → `parameterize` | 2 | partial |
| **B** oracle | one `SPEC_SCHEMA` call per signal | one `STAGE_SCHEMA` call per planning round | 2 | partial |
| **C** external | a `{"role": "specifier"}` inbox | a `{"role": "planner"}` inbox | 0 — a caller is the model | implemented |
| **D** explicit | `Goal → Spec`, deterministically | Tasks by output type | 0 | implemented |
| `null` | an empty `Spec` | never asked | 0 | implemented |
| `replay` | re-authors a recorded `specs.jsonl` | re-authors a recorded `stages.jsonl` | 0 | partial |

**A letter is a decision frontend, not a deployment topology.** Any of them runs either in one
process (`impress-a run`) or split across `impress-a serve` + `impress-a control`; the one exception
is C, which `run` refuses because it means an external caller steers and `run` attaches no plane.
Where the model is *hosted* is a third, separate axis: a `--model-profile` names a hosted endpoint
(`kind: openai_compat`) or a model served inside the allocation on the campaign's own engine
(`kind: rhapsody_vllm`, e.g. the `local-dragon` profile), and the latter is reached through
`session.infer` rather than over the network.

`null` and `replay` are shipped deciders **outside** the four-model taxonomy, which is why
"exactly one of four" and `--model`'s choices do not agree. `replay` reads the two
**executor-written** records rather than anything a reasoner kept, so the record exists for every
model whether or not it takes notes and a reasoner cannot write itself a flattering one; it needs
`--replay-from`, and it diverges loudly rather than improvising — a recorded Stage refused where
the original was admitted means the campaign differs from the one recorded.

Model **A makes two calls per cycle, not four.** Its four nodes are two per half, and `analyze`
and `parameterize` are deterministic: they act on the strategy the node before them chose.
Measured on Beam, that is the same per-cycle call count as B.

`impress-a models` prints this table from `policy/registry.MODELS`, which is the mechanism that
keeps the status column honest — a claim nobody can see goes stale quietly, and `docs/` once
described four working control models while two had no LLM behind them.

**`ReasonerModel.llm_calls` is the count with no `--model-profile` attached**, which is why every
row in the registry reads `0`. Nothing in this repository constructs a live client unless a profile
names one; A then runs its rule cascades and B runs `RehearsalOracle`, and both report zero calls.
`tests/test_reasoner_registry.py` holds the field at 0 for exactly that reason, so it cannot rise
by accident.

### What A, B and C share with D

**Chain resolution, typed port wiring and `replan` come from `ThresholdPlanner`**, held by each as
`self._mechanics` and used by composition rather than reimplemented. Those are *correctness* —
which tool produces the artifact another consumes, and which port it arrives on — and two
implementations would be two things to keep in step. A four-arm comparison's one-variable claim is
about decisions, not about whether a graph is wired correctly; an arm that wired it differently
would be a different engine, not a different reasoner.

What is genuinely each model's own: **breadth, the parameter vector, and — for B alone — which
subset of the declared chain to run.**

**And none of them decides when the campaign is done.** No shipped half overrides
`BaseSpecifier.satisfied`, so satisfaction is computed from the data registry
(`resolution.md` step 8). The protocol permits an override, and says such a Specifier owes an
explanation in provenance; nothing takes it.

## What reaches a half

`policy` may import `core` only (ADR 0010), so `CampaignSpec` — which lives in `runtime/` — can
never reach a reasoner. Two plain-data objects cross the boundary, by two different routes.

```
impress-a run      CampaignSpec ─┬→ _options_for()   → ReasonerOptions → build_roles()
                                 └→ goal_from_spec() → Goal → initial_spec()
impress-a control  CampaignObservation → _role_pair() + a Goal rebuilt from the observation
```

`ReasonerOptions` (`policy/registry.py:53`, filled by `cli._options_for:243`) is the
construction-time half. Every field is optional because most models use two or three:

| option | from | read by |
|---|---|---|
| `stages` | `stages:` | **all four planners.** Without it every model falls back to its built-in default, which is the **mock** chain — so a campaign naming real toolkits would load them, validate them, and then execute mocks |
| `replicas` | `replicas:` | all four planners, as `base_replicas` |
| `oracle` **and** `reasoner` | `--model-profile` | B's single-call seam and A's per-node seam. **One client fills both**, because `OpenAICompatOracle` implements `reasoning.NodeReasoner`; a letter picks one shape or the other, so a second client would only be a second connection to the same endpoint. A `rhapsody_vllm` profile fills them with `SessionOracle` instead, which calls `session.infer` rather than an endpoint |
| `timeout_s`, `on_timeout` | `control_liveness_timeout_s:` | **C only** |
| `records`, `spec_records`, `stage_records` | `--replay-from` | `replay` only |
| `fallback` | built by the caller | B and C |
| `sink` | always | whichever halves record their own reasoning |
| `max_cycles`, `target_front` | `max_cycles:`, `target_front:` | **nothing in `policy/` reads either** — see `resolution.md`, finding 4. `target_front` reaches a Specifier through the `Goal` |

`impress-a control` takes the second route (`cli/__init__.py:601`): it passes only `stages`, the
client, `replicas` and a sink, because a remote driver has no `CampaignSpec` — the campaign's
bounds arrive as `obs.max_cycles`, `obs.target_front` and `obs.replicas` from the observation
instead, and a `Goal` is rebuilt from it. Dropping any of those made a remotely driven arm run to
a different bound from the in-process arms it was being compared with.

The campaign's **`params:` reaches no reasoner at all** — the executor merges it as defaults under
the policy's choices (`resolution.md` step 6). A reasoner never has to learn a tool's parameter
names.

## What each model is shown

This is where A and B actually differ, and it is a bigger difference than their judgement.

| | A — `hypothesize` / `select_tasks` | B — `SPEC_SCHEMA` / `STAGE_SCHEMA` |
|---|---|---|
| Specifier side | goal, cycle, open objectives, count satisfied, the front with its metric values, population stats, and **`toolkit.ids` only** | the same, plus the declared objectives as data and two machine-readable lines (`FRONT_IDS`, `METRICS`), plus budget remaining |
| Planner side | goal, cycle, ready objectives, what is being refined, **the chain as bare ids**, in-flight count, budget remaining, max lineages | the chain **plus each enabled tool's full card**: outputs, metrics, and every `tunable` parameter with type, default, min, max, `trades` and `kind` |
| chooses | a strategy word, and a lineage count | the chain subset, the width, and every parameter value |

Model A's Specifier is shown tool **ids** and no cards on purpose: that node chooses a *strategy*,
and tool detail belongs to the half that chooses tasks. Its Planner is shown no cards either,
because its parameter vector is computed by the deterministic `parameterize` node from the
strategy word — `explore` sets quality knobs to 83% of each declared range and diversity to 35%,
`exploit` 39% and 5%, which are `FourNodePolicy`'s own shipped numbers re-expressed as fractions
so they mean the same thing on a chain nobody wrote them for.

**B's prompt filters by `tunable()`, which does not look at `kind`.** So B is shown the breadth
parameters that `_knobs` forbids A and D to touch, labelled `kind: breadth`, and it raises them —
`num_designs` to 2, 3, 4 and 8 on the mock lab's live arms. `rfd3_design`'s own spec records that
`num_designs` stays at 1 because its adapter keeps index 0, and `cost_model` is per invocation, so
nothing prices the extra draws either. **A-vs-B is therefore partly a filtered knob set against an
unfiltered one, not only one model's judgement against another's.** Backlog H10, with three ways
to close it: filter the prompt by kind, mark the real breadth parameters `operator_only`, or make
the cost models scale.

What no model is shown, on any path: a parameter marked `operator_only`. `tools/view.card_for` puts
it in `TaskCard.frozen` with its reason, so `tunable` skips it, B's prompt omits it, and B's schema
check refuses a reply naming it (`resolution.md` step 3).

## How a reply is constrained

**A reasoner never constructs a `Stage`.** It returns a JSON object, and `_to_stage`
(`policy/planners/oracle.py:156`) passes three of its fields — `stages`, `replicas`, `params` — as
*arguments* to `ThresholdPlanner.plan`. Task ids, lineage indices, typed port `inputs`, objective
attribution, `deferrals`, `cancels` and `parent_node` are all engine-authored and unreachable from
a reply. Most of the format cannot be violated because the model was never given the pen.

What it can get wrong is caught in six layers. All of model A's calls use the same machinery with
a two-field schema.

| layer | where | what it does, and the defect it exists for |
|---|---|---|
| the schema, stated twice | `policy/llm.py:198`, `_render:224` | prose in the request *and* `response_format: json_object`. An endpoint rejecting the parameter with `400` is retried **once** without it rather than failing the decision — "OpenAI-compatible" is not a uniform surface |
| parsed, never brace-sliced | `:303` | `json.loads`, absorbing only a ``` fence. The predecessor took `text[find("{"):rfind("}")+1]`, which accepts a prose answer containing two braces and builds a decision from whatever was between them |
| bounded corrective retry | `policy/reasoning.ask:75` | `isinstance` dict → `required` keys non-empty → the node's own `validate`, **all inside** the loop, with the rejection appended to the prompt. Two attempts; a third has nothing new to add while costing a round trip. Every attempt is recorded, rejected ones with `ok: false` |
| the state-bound validator | `planners/oracle.py:109` | built per call against this cycle's enabled chain and view: a tool outside the chain (the error names the chain), `replicas` out of bounds (names the bound), `params` naming a tool not in the stage, then **frozen → unknown → range, in that order**, and `parent_node` refused outright as the Specifier's decision |
| the typed model | `core/spec.py:325` | `Stage` is pydantic: wrong types raise at construction, omitted optional fields take defaults |
| guard, then Reviewer | `policy/wrappers.StageGuard:65`, `runtime/reviewer.py` | `forbid_tools`, which **refuses rather than edits**; then coverage against the applied Spec, gates 1–6, budget and the dry-run (`resolution.md` step 7) |

Two details worth keeping. The **frozen-before-unknown ordering** was a real fix: `card_for`
leaves a frozen parameter out of `parameters` and reports it under `frozen`, so the "declares no
parameter" branch fired first and a model naming `difficulty` was told the tool has no such
parameter — which is false, and **a corrective retry cannot act on a correction that is a lie.**
And one exchange is scoped to one decision (`ask` calls the client's `reset`): the live client
carries earlier turns because a reasoning model may require its own reasoning content back on a
follow-up, and nothing was ending the exchange, so by cycle fifty the prompt carried fifty
decisions with both halves' exchanges interleaved inside one client.

**A model-supplied chain is intersected, never substituted.** `ThresholdPlanner.plan` computes
`enabled = [t for t in declared if t in view and t in self.stages]`, and `self.stages` stays the
campaign's chain. The oracle and external planners used to assign `self._mechanics.stages = reply`
before delegating, so one reply naming a subset narrowed the campaign for **every later cycle** —
including the cycles planned by the fallback, which *is* that object — and a degrade afterwards
could not restore it, because nothing held the original. A tool the campaign never enabled cannot
enter by this route whatever a reply says.

**The corrective-retry path has never fired against a live endpoint.** Across 140 live calls
(`Beam-501B-A23B`, 2026-11-10) there were zero retries and zero degraded turns, so layers 3 and 4
are proven by tests and by the offline rehearsal, not by a model getting it wrong in production.

## Degraded mode is declared, never improvised

Models A, B and C each depend on something outside the job, and each has a defined answer when it
does not arrive.

- **A** — a node that exhausts its attempts raises `NodeRefused`, falls back to that node's own
  rule cascade, and records a `reasoner_degraded` transition. The campaign continues.
- **B** — either half falls back to a model-D half, sets `degraded = True`, and records the same
  event. A declared fallback is mandatory for a real run: an API outage must degrade explicitly,
  never stall a multi-GPU allocation.
- **C** — `on_timeout` defaults to **`stop`**, and `ExternalPlanner` refuses
  `on_timeout="fallback"` with no fallback declared. `fallback` is what makes "a model-C arm that
  silently became a model-D arm" possible, and such an arm is byte-for-byte a D campaign and
  invisible in the result. `impress-a run --model C` is refused outright rather than timing out
  (backlog C6).

`reasoning.degraded` writes one event name for every model, so a single query over `transitions`
finds every degraded decision in a campaign whatever made it. That is what makes the
pre-registration's "a degraded arm is void" rule enforceable at all — before the sink was
subscribed, no campaign on any machine recorded a prompt, a reply, a model id, an attempt count or
a timing, and the rule could not fire on a laptop or on Delta.

**Check `degraded_events` before reading any live arm's yield.** A non-zero count means what the
arm produced is not that model's result.

## Writing another one

Two protocols and a registry row. [`frontends.md`](frontends.md#writing-your-own) has the
procedure and a worked example, including why a new Planner should compose `ThresholdPlanner`
rather than reimplement chain resolution.

What belongs here rather than there is the constraint that shapes such a half: a reasoner reads
only `ReasonerOptions`, never a `CampaignSpec` — see "What reaches a half" above — so a builder
that needs a campaign field wants another option, not an import.
