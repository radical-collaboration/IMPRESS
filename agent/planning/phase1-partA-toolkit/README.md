# Phase 1, Part A — Science Background & Toolkit

**Project:** IMPRESS-A — autonomous protein design on HPC
**Status:** complete, 2026-09-21. Input to Part B (agent architecture) and Part C (project structure).

---

## Reading order

| # | Document | What it is |
|---|---|---|
| 1 | **[`summary-report.md`](summary-report.md)** | **Start here.** The deliverable: findings, seven tables (T1–T7), risk register, and hand-off questions for Parts B and C. |
| 2 | [`compute-pattern-taxonomy.md`](compute-pattern-taxonomy.md) | The P1–P7 classification scheme every table keys off. Normative — read before the briefs. |
| 3 | [`mcp-landscape.md`](mcp-landscape.md) | Systematic MCP survey across the 26-entry roster, with explicit verified/unverified discipline. |
| 4 | [`rejected-candidates.md`](rejected-candidates.md) | What was considered and not adopted, and what would change each answer. Makes the curation auditable. |
| 5 | [`briefs/`](briefs/) | 40 per-tool briefs. [`_BRIEF-TEMPLATE.md`](_BRIEF-TEMPLATE.md) defines their structure. |

## Scope

Part A establishes **what the toolkit contains and how each tool must be scheduled.** It does not design the
agent (Part B), structure the project (Part C), explore middleware (Phase 2), or write code (Phase 4).

Decisions fixed by the user before research began:

| Question | Answer |
|---|---|
| Target platforms | DOE leadership (Frontier / Aurora / Polaris) **and** NSF ACCESS (Delta / Bridges-2 / Expanse) |
| Compute-node egress | Full outbound HTTPS |
| Deliverable depth | Briefs and report only — no manifest, no code, no skill docs |
| Search breadth | Curated additions with justification, not an exhaustive survey |
| IMPRESS's role | Coarse-grained composite tool (pattern P7) |
| Problem classes | Stability, de novo binder design, enzyme/catalytic design, small-molecule binding |

## How this was produced

Three read-only exploration agents surveyed the reference codebases in
`<workspace>/impress-a-refcodes/tools/`. Eight research agents then wrote the briefs in two waves,
each against the fixed template and taxonomy, grounding claims in refcode where a tool was vendored and in web
research otherwise. Refcode-grounded and web-sourced claims are distinguished inline throughout.

Four agents were killed mid-task by an API rate limit; their completed files were retained and only the
missing files re-commissioned. No work was duplicated.

## Verification performed

| Check | Result |
|---|---|
| Template conformance (all ten canonical sections present) | ✅ **40/40 briefs conform.** Two required repair during the first pass: `bio-databases.md` and `cheminformatics-io.md` had the right content under non-canonical headings. |
| Bijection: T1 roster rows ↔ brief files | ✅ **Clean.** Every brief is cited in T1; every T1 citation resolves. **57 entities across 40 files** — multi-entity briefs map one-to-many by design. |
| Refcode citations resolve on disk | ✅ **162 concrete paths checked, 0 genuinely unresolved.** Three initial flags were regex artifacts (a stripped `source/` prefix, an external URL, and a combined `.cc/.hh` citation); the underlying files all exist. |
| Every brief carries a P1–P7 assignment | ✅ 40/40 |
| Every brief carries an MCP statement | ✅ 40/40 — `agent-rosetta.md` initially lacked one and was completed. |
| Every curated addition appears in T7 or `rejected-candidates.md` | ✅ |
| Anthropic model pricing in `llm-oracle.md` | ✅ Verified against the current model table rather than accepted from recall: Opus 5 $5/$25, Sonnet 5 $2/$10, Haiku 4.5 $1/$5 per 1M tokens. |
| MCP "native: yes" claims require a cited server module or live URL | ✅ Enforced. **2 of 26 entries survived as verified** (ChemGraph, RCSB PDB). |

### Corrections made during verification

- **PyMOL MCP was downgraded from "verified" to "identified, not runtime-verified."** The tool schemas are
  registered in this session, but a direct `mcp__pymol__status` call returns
  `ConnectionError ... 127.0.0.1:9877 (Connection refused)` — no backing process. The initial "verified" claim
  originated with the orchestrator, not the research, and was propagated to two agents before being caught and
  retracted. The architectural point it exposed is recorded in `mcp-landscape.md`: this server is a plugin
  inside a live GUI process on a local TCP port, which is not viable unattended in a headless batch job.

### Second pass, 2026-09-21 (decision round)

Three refcodes were added and the corresponding work redone from source.

| Change | Result |
|---|---|
| `tools/chai-lab` added | `chai.md` rewritten from source, 67 → 362 lines. **Defer → Recommended.** The suspected flash-attention CUDA lock-in does not exist. |
| `tools/PLACER` added | `placer.md` written from source. Recommended as a constraint-free validation layer. |
| Developability gap closed | `developability-surrogates.md` written, with honest accuracy reporting and an explicit design for later supersession by robotic-lab measurement. |
| Platform priority decided | Frontier deprioritized; R1 moved from High to accepted/scoped-out (`decisions/0008`). |
| Pattern **P8** forward-declared | External experiment, for the measurement seam (`decisions/0012`, Part B `09`). |
| PROSS resolved | Stabilization protocols become skill definitions, deferred as later work. |

### Known limitations of this pass
- **Chai-1's off-NVIDIA portability is plausible but unverified.** The blocking dependency turned out not to
  exist, but three `torch.cuda.empty_cache()` calls and a `cuda:0` default remain untested off-NVIDIA.
- **The Rosetta refcode ships without documentation.** `documentation/`, `demos/`, `rosetta_scripts_scripts/`,
  `pyrosetta_scripts/`, and `PyRosetta.notebooks/` are uninitialized submodules (all empty). Rosetta claims are
  sourced from `source/src` and `database/` instead, which are fully populated.
- **T6 groups some entities by family** rather than listing all 52 individually; the per-tool platform detail
  lives in each brief's Deployment section.
- **Gaps that remain uninvestigated** — immunogenicity prediction and multi-state/ensemble design — are listed
  in `rejected-candidates.md` so they are not mistaken for considered-and-rejected. PLACER and the
  developability surrogates, previously on that list, have now been briefed.

## Headline findings

1. **Portability is inverted from expectation.** GROMACS and LAMMPS build natively for CUDA, HIP and SYCL; the
   ML core has **no HIP path at all** (zero grep hits across `tools/foundry`). Aurora is better supported than
   Frontier for the generative stack, and worse for MD.
2. **The self-consistency loop is the scientific core** — generate → inverse-fold → predict → superpose. The
   accept/reject decision is a TM-score, not an energy.
3. **Co-folding has largely absorbed classical docking.** Boltz-2's joint structure-plus-affinity prediction
   outclasses Vina/GNINA/DiffDock as an affinity signal.
4. **Silent failure, not crashes, is the dominant hazard** — and it recurs in every single cluster.
5. **MCP cannot carry execution.** 2 of 26 entries verified; database lookup is healthy, HPC compute is absent.
6. **Cost spans seven orders of magnitude** between ML and physics answers to the same question, which makes
   cheap-screen-then-confirm the only defensible policy.
