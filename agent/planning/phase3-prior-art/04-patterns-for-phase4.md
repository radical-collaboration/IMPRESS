# 04 — Synthesis: Patterns for Phase 4

Consolidation of `01`–`03`. What three prior attempts teach us, what they all failed to do, and what to
carry into implementation.

## 1. Chronology matters

| Prior art | Last commit | Note |
|---|---|---|
| `radical.adr@feature/prototype` — examples | 2026-06-28 | Oldest. ADR's *intended* usage. |
| `flowgentic@demo/radical` — ai-hpc-coupling | 2026-08-19 | *"AsyncFlow drives Flowgentic"* — note the direction. **7 months newer than flowgentic `main`**, which is what Phase 2 assessed. |
| `campaign_manager@new_cm` — small_molecule_binding | 2026-09-08 | Newest and most sophisticated. Its base `devel` head is **2021-02-10** — a dormant repo revived by a 21-commit wholesale rework. |

Where these disagree, weight the newest. The progression is legible: ADR's examples cede the loop,
the flowgentic demo works around ceding it, and campaign_manager solves it.

## 2. The loop-ownership question — resolved, with a reconciliation

Two reviews appear to contradict each other. They do not.

- **`03` (ADR examples):** all 11 examples let `Operator.run()` / `run_to_completion()` own the entire
  outer loop. None invoke ADR pieces from a caller-owned loop.
- **`02` (campaign_manager):** `run_supervised()` drives `operator.run()` as a background task racing
  `cm.wait()`, with ADR confined to a four-verb lever surface — the *"ADR sacred boundary."*

**The reconciliation:** ADR's *own examples* cede the loop; a *downstream consumer* found a way not to.
The enabling mechanism is that `Operator.run()` is an **async generator** — `async for _snapshot in
operator.run()` (`campaign_manager@new_cm:src/campaign/adr/supervisor.py:55`), pumped inside
`asyncio.ensure_future(_drive())`. The caller owns the pump. Phase 2's "ADR owns the loop" was right about
intent and overstated about mechanism.

Three architectures are therefore available, and they are not equivalent:

| Architecture | Seen in | Verdict for IMPRESS-A |
|---|---|---|
| Collapse the whole cycle into one opaque `@act`, cede the loop | `flowgentic@demo/radical:adr_control.py` | **Avoid.** Works only because that cycle has no decision points needing mid-cycle visibility. Ours has `Backtrack` and `RequestHuman` mid-cycle. |
| Run ADR as a **concurrent supervisor** pulling levers through a narrow view | `campaign_manager:adr/supervisor.py` | **Adapt.** Excellent for a supervisory layer (priority, batch size, cutoffs). Not a fit for our primary `decide`, which must return a typed `Decision` *within* the cycle. |
| Use ADR's `Policy` base class directly, no `Operator` at all | `campaign_manager:campaigns/.../sm_binding_operator.py` subclasses `radical.adr.policy.base.Policy` with `@decide async def run(obs) -> Decision` | **Adopt.** This is the clean path: reuse the policy abstraction, skip the runtime. |

**Decision for Phase 4:** our loop stays ours; implement `ControlPolicy` over ADR's `Policy` base where it
helps; do not instantiate `Operator`. Reserve the supervisor pattern as an optional second-order control
(budget/priority governance) if we ever want it.

## 3. What every prior attempt failed to do

This is the clearest signal in Phase 3, and it cuts both ways.

| Capability | Any prior art? | Consequence |
|---|---|---|
| **Runtime DAG composition** | **No.** campaign_manager treats each replica as one opaque call into IMPRESS's pipeline; the flowgentic demo runs a fixed numeric search; ADR examples are single-stage | Our free-composition work is **non-redundant** — and **unvalidated by precedent**. Nobody has done this on this stack. |
| **Real data-driven adaptivity** | **No.** campaign_manager's operator is explicitly *"a dummy policy… future versions will generate varied inputs based on completed pipeline scores"* | The newest prior art has not yet done the thing we are designing. |
| **Durable state / restart** | **No.** campaign_manager has `save_checkpoint_full`/`load_checkpoint_full` but **never invokes them** | Confirms Phase 2 at a third layer. Ours to build. |
| **Control model A** (structured multi-node loop) | **No.** Example 09's LangGraph collapses to one flat `Decision` | Undemonstrated anywhere. |
| **Control model C** (external steering) | **No.** No example touches MCP; example 02's "steered" is internal policy steering | Our headless mode has no precedent on this stack. |
| **Cancellation** | **No.** No example calls `cancel_task`/`cancel_operator`. Example 05 "spawn-block" shows **zero** cancellation despite its name | **Elevates the M4 risk.** Backtracking depends on cancellation, and it is empirically unexercised. |
| **Governance / pre-flight gates** | **No.** Example 10's resource `Goal` is a per-cycle advisory stop condition, never a pre-spawn gate | Our five gates have no precedent to borrow from. |

The honest reading: **we are building the part nobody has built.** The prior art is strong on plumbing and
policy shape, and empty on composition, adaptivity, durability and governance — which is exactly the
territory Parts B and C occupy.

## 4. Pattern catalogue

Ranked by value to Phase 4. Source notation: `F` = flowgentic demo, `C` = campaign_manager, `A` = ADR examples.

### Adopt

| # | Pattern | Source | Why |
|---|---|---|---|
| 1 | **Policy decorators** — `RuleCorrectionsPolicy`, `LoggingPolicy`, `NullSchedulingPolicy` wrapping another policy | `C:src/campaign/adr/policies/wrappers.py` | Composable enforcement and provenance without touching policy internals. Cleaner than either codebase's alternative, and directly implements Part B's "validation is external to the policy." `NullSchedulingPolicy` is also our no-op baseline. |
| 2 | **Narrow view protocol** — `CampaignViewProtocol`: `observe() -> dict`, `set_priority`, `set_batch_size`, `trigger` | `C:src/campaign/adr/view.py:74-80` | Policies depend only on this, so they unit-test with no live campaign. This is the seam Part B needs between `CampaignObservation` and policies. |
| 3 | **External unconditional guards** — `enforce_candidate_policy` / `enforce_supervisor_policy` as free functions validating *every* agent output before execution | `F:agent_contracts.py` | Separation of authority. Combine with #1: guards as decorators. |
| 4 | **Typed LLM decisions** — render observation → typed vendor call (`instructor`/`response_model`, or LangChain `with_structured_output`) → validated Pydantic `Decision` | `A:03`, `F:augmented_agents.py` | Both independently rejected the string-matching approach of the IMPRESS oracle precedent. This is the reference for control model B. |
| 5 | **Rehearsal/live decision-model split** behind one protocol | `F` (`RehearsalDecisionModel` / `LangChainDecisionModel`) | A deterministic, network-free stand-in for every LLM decision point. Exactly what Part C's laptop test tier needs. |
| 6 | **Record/replay** — `RecordingObserver` + `replay_trace` JSONL | `A:11` | The mechanism for our model-D replay policy. **Must extend the schema** — confirmed still missing prompts, model ids, rationale. |
| 7 | **`CampaignAbortedError` + `max_failed_ticks`** — distinguish transient infrastructure failure (SLURM preemption) from goal or programming error; abort when consecutive ticks are all-failed | `C:src/campaign/adr/supervisor.py` | A degenerate-campaign detector Part B lacks. Stagnation detection catches "no progress"; this catches "everything is failing." |
| 8 | **Idempotent spawn gated on status** — `ChildHandle.started` / `.done` | `A:08` | Small, correct, reusable independently of ADR's operator hierarchy. |
| 9 | **`_validate_stopping_condition()`** — fail loudly at construction if a policy declares no goal and no `max_cycles` | `C` | Catches the commonest policy authoring error at the earliest possible point. |
| 10 | **`RetryConfig`** field shape — attempts, backoff, jitter, timeout, exception filter | `F` (flowgentic package) | asyncflow has **no** retry primitive; this is a sane starting schema. |

### Adapt

| Pattern | Source | Adaptation needed |
|---|---|---|
| ADR `Policy` base + `@decide async def run(obs) -> Decision` | `C:sm_binding_operator.py` | Our `Decision` is a typed union (`ComposeAndRun`/`Backtrack`/`RequestHuman`/`Stop`); ADR's is a flat action bag. Reuse the shape, widen the type. |
| `Goal` / `AllGoal` / `AnyGoal` | `A` | Good stopping-condition primitive. **Not** a resource gate — example 10 misuses it that way. Keep separate from our Pareto front. |
| Policy library — bandit, rule, ensemble (`BlendPolicy`, `ConsensusPolicy`) | `C:policies/` | Concrete model-D implementations and a cross-checking mechanism. Retarget from stage scheduling to our decision space. |
| Shared engine + N independent per-lineage loops via `asyncio.gather` | `A` | Validates our loop shape for parallel lineages. |
| Delta deployment recipe | `C` | `gpuA40x4` partition, Dragon fabric `LD_LIBRARY_PATH`, `setuptools<71` pin, LigandMPNN missing-deps workaround, idempotent AF2 weight download. Delta is a **primary** platform. |

### Avoid

| Anti-pattern | Source | Why |
|---|---|---|
| Collapsing the cycle into one opaque `@act` to satisfy a framework's loop | `F:adr_control.py` | Forfeits mid-cycle control, which we need for `Backtrack`/`RequestHuman`. |
| Side-channel state read inside `@observe` — pickle files, module-level dicts fed by telemetry subscribers | `A:02`, `A:10` | Bypasses the state model; unrecoverable and untestable. Our provenance requires the opposite. |
| Duplicated near-identical stop-reason loops across variants | `F` | Four copies drifted. One loop, pluggable policy — which is Part B's design. |
| Poking a policy's private attributes from the runner to kickstart cycle 0 | `C` | A seam that should be a constructor argument. |
| Building a sandbox `.tar.gz` while every consumer expects a `.sif` | `C:pull_foundry.sh` | A live inconsistency in the prior art. Do not inherit. |

## 5. What changes for Phase 4

1. **Phase 2's ADR verdict is revised.** Not "mine patterns, avoid the runtime" but "**use `Policy`, skip
   `Operator`**" — with the supervisor pattern held in reserve for second-order governance.
2. **Phase 2's flowgentic verdict stands, with a caveat.** Phase 2 assessed `main` (Jan); the demo branch
   (Aug) is newer and better. Even so, the reusable content is patterns, not the package.
3. **M4 (cancellation) is upgraded from open question to risk.** No prior art exercises it, and example 05
   does not do what its name suggests. Backtracking depends on it. **Spike this early** against released
   asyncflow before committing to the backtracking design.
4. **`src/campaign/adr/` is the single best reference implementation in the refcode set** — view protocol,
   policy library, decorators, recorder, telemetry, supervisor. Phase 4 should read it in full before
   writing our policy layer.
5. **Nothing validates runtime DAG composition.** Our highest-risk design choice has no precedent on this
   stack. The Phase 2 recommendation — spike the generic dispatch loop on `ConcurrentExecutionBackend`
   early — is now the single most important de-risking step.
