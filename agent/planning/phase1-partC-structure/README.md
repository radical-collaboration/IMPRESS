# Phase 1, Part C — Project Structure

**Project:** IMPRESS-A — autonomous protein design on HPC
**Status:** complete, 2026-09-21. Builds on [Part A](../phase1-partA-toolkit/) and
[Part B](../phase1-partB-architecture/). Completes Phase 1.

## Reading order

| # | Document | Answers |
|---|---|---|
| 1 | [`01-repository-layout.md`](01-repository-layout.md) | Module boundaries, the import contract, naming (C1) |
| 2 | [`02-tool-registry-and-toolkits.md`](02-tool-registry-and-toolkits.md) | Where `ToolSpec`s and skill docs live (C2, C3) |
| 3 | [`03-campaign-storage.md`](03-campaign-storage.md) | On-disk campaign layout, recovery, retention (C4) |
| 4 | [`04-environments-and-sites.md`](04-environments-and-sites.md) | Two-tier environments, site config, containers (C5) |
| 5 | [`05-testing-and-reproducibility.md`](05-testing-and-reproducibility.md) | Four test tiers; what "reproducible" means per layer (C6) |
| 6 | [`06-open-questions.md`](06-open-questions.md) | Contestable decisions and what Part C could not settle |

## The structure at a glance

```
impress-a/
├── docs/{phase1-partA-toolkit, phase1-partB-architecture, phase1-partC-structure, decisions}/
├── src/impress_a/{core, compose, policy, tools, exec, control, cli}/  + manager.py
├── toolkits/<toolkit>/{SKILL.md, toolkit.yaml, tools/<tool>/{spec.yaml, agent.py, tests/}}
├── sites/{frontier,aurora,polaris,delta,local}.yaml
├── containers/
├── campaigns/
└── tests/
```

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **One repository, one package**, with a CI-enforced import contract | Heavy tools are out-of-process, so the dependency pressure that would justify splitting does not exist. Layering is enforced by import-linter, not directory convention. |
| 2 | **`toolkits/` is top-level**, discovered from a configurable path | Tool specs are the project's scientific content and the thing scientists edit most. A site can add a toolkit without forking. |
| 3 | **Declarative `spec.yaml` + `agent.py` per tool** | The spec is read by four consumers and reviewed by scientists; behaviour stays in code. Part A's briefs are the prose form of these specs. |
| 4 | **Skill docs live in their toolkit directory**, with required sections and referential integrity checked in CI | Co-location is the answer to drift: one diff touches spec and doc together. |
| 5 | **Two-tier environments** — light agent env (≥3.12), heavy tools in containers | Dissolves Part A's Python floor conflict at the process boundary rather than reconciling it. |
| 6 | **All machine-specific facts in `sites/<name>.yaml`** | Includes `scheduler` (PBS Pro vs. SLURM), `gpu.api` (drives the compose-time portability gate), and fixed P5 concurrency caps. |
| 7 | **Campaign state is append-only JSONL; checkpoints are derived** | Crash-safe, `grep`-able on a login node, lock-free for concurrent readers. The log is truth; the checkpoint is an index. |
| 8 | **P5 cache is shared across campaigns**, not per-campaign | The cheapest available mitigation for the ColabFold single-point-of-failure (R3). |
| 9 | **Four test tiers, with a full mock campaign runnable on a laptop** | HPC iteration is slow and expensive; the architecture was built so almost everything is verifiable locally. |
| 10 | **`docs/decisions/`, not `docs/adr/`** | `radical.adr` is a middleware component this project uses; "ADR" would be permanently ambiguous. |

## Two choices worth highlighting

**The import contract is the load-bearing part of the layout.** Specifically `policy ↛ tools` and
`compose ↛ exec`. The first is what keeps Part B's control models genuinely interchangeable — policies emit
abstract intent and cannot reach for a tool adapter. The second is what makes the laptop-runnable mock
campaign possible. Both are enforced in CI because layering that is only documented does not survive contact
with a deadline.

**Mock tools must be able to lie.** T2 mocks that return plausible-but-wrong output are how the QC layer
gets tested at campaign scale. Part A found silent failure is the dominant hazard, so the test suite has to
manufacture some.

## How Part C closes Phase 1

| Part A finding | Part C mechanism |
|---|---|
| Python floor conflict (IMPRESS ≥3.9, foundry ≥3.12) | Two-tier environments — the conflict dissolves at the process boundary |
| No HIP path for the ML core (R1) | `gpu_portability` in `spec.yaml` × `gpu.api` in `sites/*.yaml` → compose-time refusal; `containers/frontier/` is where the spike lands |
| Prior art assumes SLURM; Polaris/Aurora are PBS Pro | `scheduler` is site config; the agent emits no scheduler commands |
| ColabFold MSA server is a shared single point of failure (R3) | Shared P5/MSA cache + fixed per-service concurrency caps in site config |
| `foundry install` cannot detect a truncated download | Checkpoints staged centrally and hashed at load, not trusted from config |
| Silent failure dominates | Gate implementations are a shared tested library; fixtures include known-bad outputs; mocks lie |
| 38 briefs risk becoming a snapshot | CI cross-checks every `ToolSpec` against a Part A brief, both directions |

## Phase 1 is complete

Part A established **what the toolkit is**, Part B **how the agent is organized**, Part C **how the project
is laid out**. Phase 2 (middleware exploration) and Phase 4 (implementation) follow.

Open items across all three parts are consolidated in [`06-open-questions.md`](06-open-questions.md).
