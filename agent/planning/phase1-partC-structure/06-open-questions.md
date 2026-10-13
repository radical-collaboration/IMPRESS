# 06 — Open Questions from Part C

Decisions made in Part C that are genuinely contestable, plus what Part C could not settle. These feed the
consolidated question round covering Parts A, B and C.

## Decisions made that deserve confirmation

| # | Decision | Why it could go the other way |
|---|---|---|
| Q1 | **Single package**, not a multi-package workspace | Chosen because heavy tools are out-of-process, so the dependency pressure justifying a split does not exist. If policies pull in LangGraph *and* Academy, or if a site needs the execution layer without the policy layer, splitting becomes attractive — and splitting later is more disruptive than starting split. |
| Q2 | **`toolkits/` at the top level**, discovered from a path, not package data | Makes specs first-class scientific content and lets sites add toolkits without forking. Costs a non-trivial packaging story. The conventional alternative is `src/impress_a/toolkits/` as package data. |
| Q3 | **Declarative `spec.yaml` + `agent.py`**, not pure Python specs | YAML is scientist-reviewable and importable without heavy deps. Costs a schema to maintain and loses type checking at authoring time. Pydantic models in Python would invert both trade-offs. |
| Q4 | **`docs/decisions/`**, avoiding "ADR" because `radical.adr` is a middleware component | A real but small collision. If the team already says "ADR" for architecture decision records, fighting it may cost more than the ambiguity. |
| ~~Q5~~ | ~~Package name~~ | **RESOLVED.** Distribution `impress-a`, import package `impress_a`, prose name IMPRESS-A. See `01 §6`. |
| Q6 | **P5 cache shared across campaigns**, tree stored append-only as JSONL | Both are load-bearing (R3 mitigation; crash-safety). Neither is controversial, but both assume a POSIX shared filesystem that behaves — worth confirming for each target site, since leadership-machine filesystems have opinions about small-file append workloads. |
| Q7 | **Artifact retention defaults to full for Pareto-front lineages, metrics-only for pruned** | Trajectories dominate storage. If quota is tighter than assumed, or if pruned lineages turn out to matter for later analysis, this default is wrong in one direction or the other. |

## Could not be settled in Part C

| # | Question | Blocked on |
|---|---|---|
| Q8 | Whether the control-plane adapter runs on a compute, login, or service node | Phase 2 (network topology of each target machine) |
| Q9 | Whether `toolkits/` entry-point discovery is worth building now or later | Whether third parties will actually ship toolkits — a project-governance question |
| Q10 | Storage quotas and filesystem policy per site | Site-specific facts we do not have |
| Q11 | Whether golden campaigns are stored in-repo or in external storage | Their size, which is unknown until one exists |

## Carried forward, still open

From Part A: PROSS's classification (in-house job vs. external webserver), and the deferred license
determinations for FoldX, ESM-C/ESM3, and AlphaFold3.

From Part B: the residual novel-silent-failure risk under free composition, the human-supplied theozyme
constraint in enzyme design, the *in silico*-only loop closure, the tool-independence assumption behind
cross-tool consistency checking, and unmeasured budget estimates.


---

## Resolved after Part C (decision round of 2026-09-21)

| Item | Resolution |
|---|---|
| Package name (Q5) | Distribution `impress-a`, import `impress_a`, prose IMPRESS-A. `01 §6`. |
| Platform priority | **Polaris and NSF ACCESS primary; Aurora second; Frontier deprioritized.** Frontier stays in the site matrix and the portability gate but is unimplemented; no HIP spike is scheduled. `04 §2`. |
| Composition posture | **Self-promoting interlock.** Not temporary scaffolding and not permanent sign-off — novel compositions run under extra scrutiny and promote automatically after N clean runs. Part B `05 §10`. |
| PROSS classification | Deferred by decision: stabilization protocols will be expressed as **skill definitions**, left as later work. Not a tool-registry entry for now. |
| Developability gap | Surrogates to be added (`briefs/developability-surrogates.md`), explicitly designed so they can be replaced or supplemented by future tools querying experimental results from a **robotic lab**. Drives the measurement seam in Part B `09`. |
| Chai-1 grounding | Refcode added at `impress-a-refcodes/tools/chai-lab`; brief rewritten from source. |
| PLACER | Refcode added at `impress-a-refcodes/tools/PLACER`; brief written. |

Q1–Q4 and Q6–Q11 remain open as written above.
