# 0015 — One engine, two processes, and where each boundary falls

**Date:** 2026-11-11 · **Status:** accepted · **Amends:** nothing; records what
[0010](0010-single-package-with-import-contract.md) and
[0014](0014-an-enclosing-campaign-manager-is-not-a-control-model.md) assumed but never stated

## Context

IMPRESS-A was conceived as three loops — a Spec Loop, a Planning Loop and an execution loop — and
the reason given for separating them was that spec resolution, planning and task computation must be
mutually non-blocking. That requirement is older than any of the code: the phase-1 architecture
record asks for "async, non-blocking submission — the outer loop must observe and remain steerable
while work runs", and for a long time nothing implemented it. The reasoner was the loop body of a
serial cycle, and three awaits on one coroutine serialised it.

"Mutually non-blocking" bundles three different hazards, and they do not have the same remedy:

| Hazard | Does a process boundary fix it? | What fixed it here |
|---|---|---|
| A **synchronous** call on a shared event loop | Yes | Async structure: `AsyncOpenAI` for live reasoners, `asyncio.to_thread` for the blocking backend construction and the ledger's `flock` |
| **Serialisation by awaits** — one coroutine doing everything in order | No. Two processes with the same await chain are equally serial | Structure, in one process: `manager.run` races `executor.pump()` against the reasoner's `conduct()` as two tasks |
| **CPU contention** between roles | Yes | Never an observed problem; the roles do almost no CPU work |

The only measured precedent for the first row is job 22534628, where a synchronous decision body
took 67% of wall clock (p99 56 s) — and that is the *sibling example's* synchronous client, replaced
by an async one before IMPRESS-A ever ran a live reasoner. It argues for async structure. It does
not, by itself, argue for a process boundary.

Two mechanical facts constrain any answer. A `WorkflowEngine` captures the loop it is built on and
schedules its dispatch there, so an engine built elsewhere looks healthy and dispatches nothing —
jobs 22328172 and 22328262 each wrote `r0001 submitted` and then burned a full allocation in
silence. And admission is synchronous because the dry-run instantiates task agents, so it has to run
where the toolkit is installed.

## Decision

**Two processes, not three, and `CampaignSession` is the split.** The Spec Loop and the Planning
Loop are co-resident in a control process, because they are independent of execution but *not of
each other*: a plan consumes the revision respecification just made, and in the shipped driver they
are sequential awaits inside one `conduct` (`runtime/roles.py`). The Reviewer and Deployer are
execution-side, because admission needs the toolkit. A third process for the Planner is therefore
out of scope by construction rather than deferred. What separates the processes is the session
boundary — **a second `WorkflowEngine` or a second event loop is not**, and must never become the
mechanism.

**One engine per campaign, on the execution process's loop, carrying named routes.** `compute` is
Dragon on an allocation and rhapsody's concurrent backend off one; `local` is a thread pool for
adapters and QC; `ai` is added when the campaign serves its own reasoner. A decorator names its
route, and an unknown name fails at decoration.

**A Stage is one `@flow.block`.** The block's future is the graph's result, its members inherit its
uid as `workflow_id`, and cancelling it cascades to every unfinished member with each cancel sent to
the backend that member was routed to (`radical.asyncflow` 0.7.0).

**Each tool command is an executable task placed per backend.** `exec/launch.Launcher` submits it,
`exec/resources.Placement` says where it runs — a Dragon `Policy(gpu_affinity=[g])`, or a child
environment carrying `CUDA_VISIBLE_DEVICES` on the concurrent backend — and thread caps travel with
it rather than with the process.

**What this replaced.** The previous engine had a single backend and ran each graph node as one
opaque `function_task` carrying adapter, subprocess, post-process and QC together, with no
`task_description` at all: `exec/resources.to_backend_description` had no caller, no `Policy` was
ever built, and on Delta every GPU tool saw every GPU. Thread caps were written into the campaign
process's environment at start-up. A cancel cancelled a side-channel future, so a run was reaped
FAILED and its budget released while its tasks kept running. A second, opt-in execution loop ran on
the root project's `ImpressManager` with a 0.5 s poll and a single-slot child mailbox, and never ran
on hardware. `exec/dispatch.Dispatcher`, `runtime/runner.py`, `runtime/pipelines.py` and
`CampaignSpec.runner` are deleted; a spec that sets `runner:` is refused with a pointer here.

**The root `impress` package is no longer a dependency.** `tests/test_layering.py::test_nothing_imports_impress`
and `tests/test_toolchain.py::test_impress_is_not_a_dependency` keep it that way; the second because
`impress` is on no index, so re-declaring it would be a dependency-confusion exposure.

## Consequences

- **Non-blocking is delivered by async structure first**, and by route separation inside the
  execution process second. The process boundary adds one guarantee on top: tolerance of a reasoner
  that blocks *synchronously*. That guarantee is **not** covered by the test tier — the planned test
  used a synchronous stall, and what shipped (`tests/test_split_process.py`) stalls with
  `await asyncio.sleep`, which one process already survives.
- **Whether the boundary costs or buys anything is measurable and unmeasured.** Arms B and C share a
  client and a profile and differ only in topology, so a B-vs-C gap is plane latency and round
  trips, never decision quality. Arm C has never run on Delta.
- **Co-residency has a measured cost, and it is not blocking.** `control_liveness_timeout_s` reads a
  clock that an in-process campaign's own role driver refreshes, and that driver is silent exactly
  when it is busy awaiting the tasks it asked for: job 23671367 lost arms A, B and D after one cycle
  each. The bound now arms only once a plane has registered and is suspended while work is in
  flight. Job 23675997 showed the mirror image, running two reasoners against one executor.
- **A locally hosted reasoner puts the model execution-side.** `CampaignSession.infer` is a
  `prompt_task` on the `ai` route: the decision stays in the control process, the weights sit beside
  the tools, sharing that process's GPUs (`StageExecutor.gpu_offset` keeps tools off them) and its
  `backend_startup_timeout_s`. A stalled vLLM bring-up would stall the loop Dragon's `Batch()`
  stalled. This path has not run on hardware.
- **The `local` route brought its own coupling.** asyncflow's `LocalExecutionBackend.shutdown` joins
  its pool synchronously on the engine loop, so an adapter thread still waiting on a command
  deadlocks teardown; `exec/stage._settle` and `Launcher.idle` drain first. Filed upstream.
- **An enclosing campaign manager gets two surfaces, not one.** AuCaM builds a single-backend engine
  and asyncflow fixes backends at creation, so an in-process AuCaM run cannot share its engine and
  IMPRESS-A's tasks stay invisible to AuCaM's per-task telemetry.
- **Cancellation stays advisory for running work on the concurrent backend**, where rhapsody's
  `cancel_task` leaves the child process alive. A run's terminal state always comes from collecting
  it.
- **`cost_measured` changed meaning.** It now excludes the time a command spent queued, recorded
  separately as `usage.phases["queued"]`, so figures recorded before this change are not comparable
  with figures recorded after it.
- The Python floor moved to **3.11** and both middleware pins to **0.7.0**, with Dragon as the
  `[dragon]` extra so CI and the laptop tier need none of it.

**Evidence.** Job **23815248** ran the two-lineage Delta smoke on this loop: `12/12 tasks ok` in
3m45s, lineage 0 on GPU 0 and lineage 1 on GPU 1 under Dragon's placement policy with GPUs 2–3 idle,
one telemetry block span per Stage with every command under it, Dragon up in 4.5 s and torn down in
2 s. Job **23814643** is the failure that preceded it: a coreutils `timeout` wrapper, correct on the
concurrent backend, became an unreaped process-group leader under Dragon and hung stage 1.
Commits `e69e982`, `8d22cf8`, `0e3d945`, `d9420bc`, `ed0fde2`.
