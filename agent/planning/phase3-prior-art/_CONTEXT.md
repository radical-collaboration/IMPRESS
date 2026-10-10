# Phase 3 shared context — prior art review

## Purpose
These are **prior attempts at work related to IMPRESS-A**. Review them for patterns worth reusing,
adapting, or deliberately avoiding in Phase 4 (implementation). You are not judging whether they are good
software; you are extracting **transferable design decisions** and **evidence about what actually works**
on the asyncflow/rhapsody stack.

## What IMPRESS-A is (condensed)
An autonomous protein-design agent for HPC. One outer loop:
`observe → decide → compose → validate → execute → analyze → update → terminate?`
Only `decide` varies between four control models, all implementing one `ControlPolicy`
(`decide`, optional `interpret`, mandatory `on_rejected`) returning
`ComposeAndRun | Backtrack | RequestHuman | Stop`:
- **A** explicit four-node agentic loop · **B** heavyweight LLM oracle
- **C** external caller steering (= headless control mode 2) · **D** user-supplied explicit policy
Control model is **fixed at launch**.

**State:** append-only tree of design lineages, multi-objective Pareto front, backtracking, full
provenance, cycle-boundary checkpointing, multi-dimensional budget ledger.
**Composition:** the agent composes *arbitrary typed DAGs* at runtime, through five validation gates
(type, structure, parameter, resource, budget) plus dry-run, governed by a self-promoting interlock.
**Task agents:** per tool, hybrid (deterministic or LLM), phases pre-process → parameterize → execute →
post-process (post-process enforces QC gates).
**Patterns:** P1 GPU-in-job · P2 CPU fan-out · P3 MPI · P4 external batch job (durable ledger, outlives
agent) · P5 network service · P6 in-process, never scheduled · P7 composite pipeline · P8 external
experiment (forward-declared).

## Phase 2 conclusions you should build on (do not re-derive)
- **asyncflow is adopted.** Its `WorkflowEngine` supports runtime-composed DAGs: dependencies are
  **unawaited futures passed as call arguments**, resolved by a ready-queue scheduler. Task types:
  `executable_task` (async fn returning a shell command string), `function_task`, `prompt_task`.
- **rhapsody is a direct dependency** for real backends (`DragonExecutionBackend`,
  `ConcurrentExecutionBackend`), reachable by name via `BackendRegistry.get_backend()`. asyncflow only
  intermediates rhapsody for **telemetry** (`flow.start_telemetry()` + `subscribe`).
- **Resource shapes are NOT portable** across backends (RADICAL `{"ranks","gpus_per_rank"}` vs. Dragon
  `process_template`). We must own a normalization layer.
- **asyncflow has no retry primitive and no durable job ledger.** Both are ours to build.
- **flowgentic (0.1.0)** bridges LangGraph tool calls to asyncflow tasks but does **not** implement
  control policies. Recommendation was: mine the pattern, don't depend on the package.
- **radical.adr (0.1.0)** has a real `Policy`/`@decide`/`Decision` abstraction, but its `Operator.run()`
  owns a complete outer loop that conflicts with ours. Recommendation: mine patterns, keep our loop.
- **ORBIT** holds the only PBS Pro support and the only external-batch path (`plugin_psij`).

## What to look for, in priority order
1. **How the outer loop is actually structured** in working code, and who owns it.
2. **How a policy/decision is expressed and swapped**, and whether it resembles our `ControlPolicy`.
3. **How tasks are composed and submitted to asyncflow** — concrete idioms we can copy.
4. **How state, provenance, checkpointing and restart** are handled (or not).
5. **How LLMs are integrated** — prompt construction, output parsing, failure handling.
6. **Real deployment detail** — SLURM/PBS scripts, container invocation, env setup. These encode
   hard-won operational knowledge.
7. **What went wrong** — abandoned code, TODOs, workarounds. A dead end documented is as valuable as a
   pattern adopted.

## Ground rules
- Reference code is **READ-ONLY**. Never modify it, never check out a branch, never change HEAD.
- For files on branches that are not checked out, read with
  `git -C <repo> show <ref>:<path>` and list with `git -C <repo> ls-tree -r --name-only <ref>`.
- Cite `repo@ref:path` precisely. Quote real code.
- Distinguish verified-from-source from inferred. Note what you could not determine.
- Judge transferability explicitly: **adopt / adapt / avoid**, with a reason.
