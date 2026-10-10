# 01 — Repository Layout

## 1. The organizing constraint

Part B's layers have **different change rates, different audiences, and radically different dependency
weights.** The layout follows from that, not from taste.

| Layer | Changes | Edited by | Dependencies |
|---|---|---|---|
| Core (state, tree, Pareto, provenance, budget) | Rarely | Engineers | Pure Python + pydantic |
| Composition + validation | Occasionally | Engineers | Core only |
| Policies (A, B, D) | Per experiment | Engineers + scientists | LLM client, optional graph framework |
| Tool specs + task agents | **Constantly** | **Scientists** | Declarative; heavy deps stay out of process |
| Execution layer | Per platform | Engineers | `radical.*`, `rhapsody` |
| Control plane + adapters | Rarely | Engineers | HTTP/MCP server libs |
| Site configuration | Per machine | Whoever ports it | None |

Two facts make this tractable, both established in Part A:

- **Heavy scientific tools are invoked as subprocesses or containers, not imported.** IMPRESS already does
  this (`apptainer exec ... rfd3 design ...`). So torch, PyRosetta, GROMACS and the rest are *not* Python
  dependencies of the agent. The Python floor conflict (IMPRESS ≥3.9 vs. foundry ≥3.12) dissolves at the
  process boundary rather than needing reconciliation.
- **The exception is P6 tools**, which are in-process by definition — RDKit, Biotite, AtomWorks, US-align,
  `paretoset`. These are the agent's only genuinely scientific dependencies, and they are light.

## 2. Recommendation: one repository, one package, enforced internal layering

A multi-package workspace was considered and rejected for now. The dependency pressure that would justify it
does not exist, because the heavy tools are out-of-process. Splitting packages would buy isolation we already
have and cost cross-package version churn during a phase when interfaces are still moving.

What the single package must *not* do is let layers reach through each other. That is enforced by an import
contract (§4), not by directory politeness.

```
impress-a/
├── docs/
│   ├── phase1-partA-toolkit/          # science background, 38 briefs, report
│   ├── phase1-partB-architecture/     # agent architecture
│   ├── phase1-partC-structure/        # this
│   └── decisions/                     # numbered decision records — see §5 on naming
│
├── src/impress_a/
│   ├── core/          # types, artifacts, design tree, Pareto, provenance, budget, QC
│   ├── compose/       # composer + the five validation gates + dry-run
│   ├── policy/        # ControlPolicy protocol; models A, B, D
│   ├── tools/         # registry, spec loader, task-agent base classes, QC gate runners
│   ├── exec/          # asyncflow/rhapsody seam, pattern dispatch, P5 governor, job ledger
│   ├── control/       # CampaignControlPlane + adapters (inproc, http, mcp)
│   ├── manager.py     # the outer loop
│   └── cli/
│
├── toolkits/                          # DECLARATIVE — first-class, not buried in src/
│   ├── generation/
│   │   ├── SKILL.md
│   │   ├── toolkit.yaml
│   │   └── tools/rfdiffusion3/{spec.yaml, agent.py, tests/}
│   ├── structure_prediction/
│   ├── physics_design/
│   ├── stability/
│   ├── simulation/
│   ├── search/
│   ├── ligand/
│   ├── analysis/
│   └── composite/                     # IMPRESS pipelines (P7)
│
├── sites/                             # per-machine config: frontier, aurora, polaris, delta, local
├── containers/                        # container definitions + build scripts
├── campaigns/                         # example + golden campaign specs
├── tests/
└── pyproject.toml
```

## 3. Why `toolkits/` is top-level rather than inside `src/`

This is the layout's one genuinely contestable choice, so the reasoning is explicit.

Tool specs are **the artifact scientists edit most and engineers edit least.** Burying them under
`src/impress_a/tools/specs/` frames them as internals of a Python package. Hoisting them to the top level
frames them as the project's scientific content — which, given Part A produced 52 entities, they are.

It also keeps the registry honest: because `toolkits/` is discovered from a configurable path rather than
imported as package data, a site or a user can add a toolkit without forking the package. The loader resolves
toolkits from, in order: an explicit config path, `$IMPRESS_A_TOOLKITS`, installed entry points, then the
bundled directory.

The cost is that packaging must handle non-package data deliberately. That is a known, contained problem.

## 4. Import contract

Enforced in CI by an import-linter rule, because layering that is merely documented does not survive.

```
cli      → everything
control  → manager, core
manager  → policy, compose, exec, tools, core
policy   → core                      (NOT tools, NOT exec — policies emit abstract intent)
compose  → tools, core               (NOT exec — composition is execution-agnostic)
tools    → exec, core
exec     → core
core     → (nothing internal)
```

Three rules carry real design weight:

- **`policy` may not import `tools` or `exec`.** Part B's whole interchangeability argument rests on policies
  emitting abstract `ExperimentIntent`, never concrete tool invocations. If a policy can import a tool
  adapter, someone will call it directly and the seam rots.
- **`compose` may not import `exec`.** Composition and validation must be testable without any backend, which
  is what makes the mock-backend test tier (`05`) possible.
- **`core` imports nothing internal.** It holds the types everything else agrees on.

## 5. A naming collision worth avoiding

`radical.adr` is a middleware component this project will use. "ADR" also conventionally means *Architecture
Decision Record*. Naming our decision-record directory `docs/adr/` would create a permanent, low-grade
ambiguity in a project that uses both.

The layout above uses **`docs/decisions/`** instead. Records are numbered and immutable
(`0001-impress-is-a-tool-not-the-control-plane.md`), which matters because Phase 1 has already produced
several decisions — IMPRESS's demotion, free graph composition, model C as mode 2 — whose rationale should
outlive this conversation.

## 6. Package naming — decided

| Role | Name |
|---|---|
| Human-facing project name | **IMPRESS-A** |
| Distribution (PyPI / wheel) | **`impress-a`** — matches the repository directory |
| Import package | **`impress_a`** |
| Environment variables | `IMPRESS_A_SHARED`, `IMPRESS_A_CAMPAIGNS`, `IMPRESS_A_TOOLKITS` |

The earlier working name `impressa` was rejected. The reference tree contains
`impress-a-refcodes/tools/IMPRESS`, so `impressa` and `impress` would sit one character apart in the same
workspace: a `grep` for `impress` hits both, and `import impress` versus `import impressa` offers no visual
break. The hazard applies to human readers and, more acutely, to LLM agents working in this tree later,
where both names are plausible completions of each other.

`impress_a` is also the idiomatic Python spelling (PEP 8: lowercase with underscores); `IMPRESS_A` as an
*import* name would be unusual, so the uppercase form is reserved for prose and environment variables. The
underscore supplies exactly the separation that was missing.
