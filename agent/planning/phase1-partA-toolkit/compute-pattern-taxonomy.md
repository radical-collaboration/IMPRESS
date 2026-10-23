# Compute-Pattern Taxonomy

**Phase 1, Part A — IMPRESS-A autonomous protein design agent**
Status: normative for Part A. Every tool brief and every table in `summary-report.md` keys off this scheme.

## Purpose

An autonomous agent cannot reason about "run AlphaFold" as an undifferentiated action. What it must
reason about is *what kind of scheduling commitment a tool call represents*: whether it consumes a GPU
the agent already holds, whether it blocks for hours, whether it can fail because a remote host is
down, whether it can be retried for free.

The taxonomy below is therefore organized by **scheduling implication**, not by scientific function.
Two tools share a pattern if and only if the execution layer must treat them the same way.

## Platform assumptions

| Assumption | Value |
|---|---|
| Target platforms | DOE leadership: **Frontier** (AMD MI250X / HIP), **Aurora** (Intel PVC / SYCL-XPU), **Polaris** (NVIDIA A100 / CUDA). NSF ACCESS: **Delta**, **Bridges-2**, **Expanse** (NVIDIA A100/H100 / CUDA) |
| Compute-node egress | **Full outbound HTTPS.** Pattern P5 is viable in-job; a remote LLM oracle can be called inline |
| Scheduler | SLURM (ACCESS, Frontier, Delta) and PBS Pro (Polaris, Aurora) |
| Deployment unit | Container-first (Apptainer/Singularity) where possible; module + conda otherwise |

Full egress is a *decision*, not a discovery. If it is later retracted, every P5 tool needs a
brokered or pre-cached fallback and the coverage matrix loses its database-lookup column.

## The seven patterns

| ID | Pattern | Definition | Scheduling implication | Canonical examples |
|---|---|---|---|---|
| **P1** | GPU-node-local, in-job | Single-node GPU work executed inside the agent's own allocation | Placed on a GPU the agent already holds; competes with other P1 work for the same devices | RFD3, ProteinMPNN, Boltz-2, ESMFold, Chai |
| **P2** | CPU-parallel fan-out, in-job | Embarrassingly parallel CPU work inside the allocation | Scales by replica count; ideal for adaptive batch-size variation | Rosetta `nstruct` ensembles, FoldSeek search, per-design scoring |
| **P3** | MPI multi-node, in-job | Tightly coupled work needing a rank layout across nodes | Requires a reserved rank topology; cannot be resized mid-run | GROMACS `mdrun`, LAMMPS, Rosetta MPI |
| **P4** | External HPC job | Work submitted as a **separate batch job** outside the agent's allocation | Async submit/poll; survives the agent's own walltime; needs a persisted job-tracking store | Long MD production, jobs needing a different queue or resource shape |
| **P5** | Network service over HTTPS | Remote API call | No local resource cost; failure modes are latency, quota, rate limit, and outage rather than compute | RCSB/PDB, UniProt, AlphaFold DB, ColabFold MSA server, LLM oracle |
| **P6** | In-process library call | Sub-second, in-memory, no scheduling | **Must never become a scheduled task.** Scheduling overhead would exceed the work | RDKit ops, BioPython parsing, metric computation |
| **P7** | Composite pipeline | An entire multi-stage campaign exposed as one callable | The agent parameterizes and launches it, then observes; internal stages are not individually steered | IMPRESS `protein_binding`, `small_molecule_binding`, `discontinuous_scaffolds` |
| **P8** | External experiment *(forward-declared)* | A wet-lab or robotic-lab assay | Latency of days to weeks; completes **out-of-band**, routinely after the requesting cycle and often after the campaign itself | None in the current roster — see below |

### Why P4 is distinct from P1–P3

P1–P3 run inside the allocation the agent is already holding. P4 leaves it. That difference is the
single most consequential one for an autonomous outer loop: P4 work can outlive the agent, so it
demands durable job state, and it introduces queue wait as a cost term that has nothing to do with
the science. A tool is P4 not because of what it computes but because of *where it must be submitted*.

### Why P8 exists before anything uses it

No tool in the Part A roster is P8. It is declared because a wet-lab assay has a scheduling implication
none of P1–P7 capture, and P4 — the closest — is still wrong: a P4 job finishes in hours and the agent polls
it, whereas an assay finishes in days to weeks, out-of-band, frequently after the campaign has terminated.

Declaring it now shapes the data model, the storage layout and the control plane correctly while doing so is
nearly free. Retrofitting it later would not be. The decision that prompted it — that developability
surrogates must be replaceable by robotic-lab measurements — is recorded in `decisions/0012`, and the
resulting design is Part B `09`.

### Why P6 is called out at all

A tool that takes 30 ms does real damage if the agent treats it as a task: the orchestration layer
pays scheduling, serialization, and filesystem cost orders of magnitude greater than the work. P6 is
an instruction to the execution layer to inline the call.

## Orthogonal attributes

Pattern alone is insufficient. Each brief additionally records:

| Attribute | Values | Why it matters |
|---|---|---|
| **GPU vendor portability** | CUDA-only · CUDA+HIP · CUDA+SYCL/XPU · portable · CPU-only · n/a | Decides whether the tool runs on Frontier and Aurora at all. The sharpest platform risk in this project |
| **State model** | stateless · checkpointable · restart-required | Decides whether a preemption or walltime kill is recoverable or wasted |
| **Data locality** | shared-FS required · streamable · self-contained | Decides whether a task can move between nodes or sites |
| **Staging burden** | model weights · sequence/structure DB · none | Large one-time cost; must happen before the agent's first iteration, not during it |
| **Container availability** | official image · community image · build-required · n/a | Primary deployment mechanism on leadership machines |

## Classification rules

1. **Classify by the dominant cost**, not by capability. A tool that *can* use a GPU but is normally
   run on CPU is P2.
2. **A tool may carry a secondary pattern** when it is genuinely dual-mode — record it as
   `P2 (primary) / P4 (when ensemble size exceeds remaining walltime)`. Do not list more than two.
3. **Wrapper packages inherit the pattern of what they wrap.** A Python API over an MPI binary is P3.
4. **P7 is reserved for IMPRESS pipelines** in this project. Do not assign it to any tool whose
   internal stages the agent can address individually.
5. **Egress-dependent tools are P5 even when they have a local fallback.** Record the fallback under
   failure modes.
