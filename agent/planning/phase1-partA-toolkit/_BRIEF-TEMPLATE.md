# Brief Template

Copy this structure exactly. All nine sections are required. If a section does not apply, write
`n/a` and one clause saying why — do not delete the heading. Filename: `briefs/<lowercase-tool>.md`.

---

# <Tool Name>

**One-line identity.** What it is, in a sentence.

## Identity
- **Version / release examined:** (cite a VERSION file, `pyproject.toml`, CMake `project()`, or release tag)
- **Provenance:** upstream org, license, refcode path if present in `impress-a-refcodes/tools/`
- **Maturity:** production / active research / unmaintained

## Scientific role
What problem it solves, and which of the four in-scope problem classes it serves:
stability/thermostabilization · de novo binder design · enzyme/catalytic design · small-molecule binding.
Name the pipeline stage(s) it occupies: generate / inverse-fold / predict / score / simulate / search / analyze.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI (give the actual argv), Python API (give the actual import
  and call), or both. Cite the entrypoint — `[project.scripts]`, the CLI module, the binary name.
- **Inputs:** exact formats
- **Outputs:** exact formats, and where they land
- **A concrete example** taken from the repo's own `examples/` or docs, not invented

## Compute pattern
- **Pattern:** P1–P7 (secondary pattern only if genuinely dual-mode)
- **GPU vendor portability:** CUDA-only / CUDA+HIP / CUDA+SYCL-XPU / portable / CPU-only / n/a — **with evidence** (build flag, import, dependency pin)
- **State model:** stateless / checkpointable / restart-required
- **Data locality:** shared-FS required / streamable / self-contained
- **Staging burden:** model weights / sequence-structure DB / none — with approximate size
- **Container availability:** official / community / build-required / n/a

## Deployment on DOE & ACCESS
Per-platform reality for Frontier (HIP), Aurora (SYCL/XPU), Polaris (CUDA), ACCESS NVIDIA.
Say plainly where it will **not** run and why. Note module-vs-conda-vs-apptainer, weight download
mechanics, and any license gate that blocks deployment.

## Agentic surface
- **Native MCP:** yes / community / no. A `yes` **must** cite a specific server module or upstream doc URL. Unverifiable claims are downgraded to `community / unverified`.
- **Parameters worth exposing for autonomous variation:** a short table of `parameter · type · sane range · default · what it trades off`. Only parameters that genuinely change outcomes — not every flag.
- **Parameters that must NOT be agent-varied:** and why (correctness, cost blowup, or silent invalidity)

## Failure modes & what the agent must check
How it fails. Distinguish **loud failure** (non-zero exit, exception) from **silent bad output**
(converged to garbage, produced a structure with no secondary structure, returned a confident wrong
score). Name the specific post-hoc check that catches each silent mode.

## Cost per unit of work
`unit of work · typical wall-clock · resource shape (nodes/GPUs/cores) · checkpointable?`
Approximate is fine; state the assumption. This feeds any budget-aware policy.

## Verdict
**Core** (load-bearing, must be in the toolkit) · **Recommended** (clear value, include) ·
**Defer** (real but not now — say what would change the answer) · **Reject** (say why).
One paragraph of justification.

## Sources
Refcode paths (must resolve on disk), upstream docs, papers. Mark anything inferred rather than verified.

---

## Accepted variant: multi-entity briefs

Some briefs cover several closely related entities that differ materially in license, weights access,
or deployment (e.g. `alphafold.md` covering AF2 / AF3 / ColabFold; `docking.md` covering Vina / GNINA /
DiffDock). These may nest the first five sections — `Identity`, `Scientific role`,
`Invocation & I/O contract`, `Compute pattern`, `Deployment on DOE & ACCESS` — one level down (`###`)
under a per-entity `##` heading, then carry `Agentic surface`, `Failure modes`, `Cost per unit of work`,
`Verdict`, and `Sources` once at `##` level for the group.

Two rules still bind:

1. **All ten canonical section names must appear**, at `##` or `###`.
2. **Each entity gets its own row in the master roster (T1)** with its own pattern assignment and
   verdict, even though they share one file. The brief-to-row mapping is one-to-many, not one-to-one.
