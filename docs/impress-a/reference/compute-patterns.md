# Compute Patterns

**Normative.** Every `ToolSpec` declares one. Dispatch, validation and cost estimation all key off it.

## Why patterns rather than categories

A tool's compute pattern is not what it computes — it is **what kind of scheduling commitment a call to it
represents**. Two tools share a pattern if and only if the execution layer must treat them the same way.
An autonomous agent cannot reason about "run AlphaFold" as an undifferentiated action; it has to know
whether the call consumes a GPU it already holds, blocks for hours, can fail because a remote host is
down, or can be retried for free.

## The patterns

| ID | Pattern | Scheduling implication | Examples |
|---|---|---|---|
| **P1** | GPU-node-local, in-job | Placed on a GPU the agent already holds; contends with other P1 work | Diffusion generators, inverse folding, structure prediction |
| **P2** | CPU-parallel fan-out, in-job | Scales by replica count; the natural knob for adaptive batch sizing | Physics ensembles, structural search, per-design scoring |
| **P3** | MPI multi-node, in-job | Needs a reserved rank topology; not resizable mid-run | Molecular dynamics, MPI-parallel design protocols |
| **P4** | External HPC job | Async submit/poll; **outlives the agent**; needs a durable ledger entry | Long production runs, work needing a different queue |
| **P5** | Network service over HTTPS | No local resource cost; fails by latency, quota, outage, **schema drift** | Structure/sequence databases, MSA services, an LLM oracle |
| **P6** | In-process library call | **Must never be scheduled** — overhead would exceed the work | Cheminformatics, structure parsing, metric computation |
| **P7** | Composite pipeline | Parameterize and launch; internal stages are not individually steered | A whole externally-defined multi-stage pipeline |
| **P8** | External experiment | Latency of days to weeks; completes **out-of-band**, often after the campaign ends | Wet-lab or robotic-lab assay |

## The three that change how code is written

**P4 is not P1–P3 with a longer timeout.** P1–P3 run inside the allocation the agent already holds. P4
leaves it, so the work can outlive the agent process. That demands a durable job ledger
(`exec/ledger.py`) and introduces queue wait as a cost term unrelated to the science.

**P6 is an instruction to inline.** A tool that takes 30 ms does real damage if treated as a task: the
orchestration layer pays scheduling, serialization and filesystem cost orders of magnitude greater than
the work. The composer inlines P6 tools and validation gate 4 rejects any graph that schedules one.

**P8 is forward-declared.** No tool in the current registry is P8. It exists so the data model, the
storage layout and the control plane are shaped correctly now, when that is nearly free, rather than
retrofitted later. A measurement arrives out-of-band as an update to an existing design node, not as a
task result — see `docs/decisions/0012`.

## Orthogonal attributes

Pattern alone is insufficient. `ToolSpec` also declares:

| Attribute | Why it matters |
|---|---|
| `gpu_portability` (cuda / hip / sycl_xpu) | Checked at compose time against the site's `gpu_api`. A tool with no proven path on the running platform is refused before it consumes anything |
| `resources` | Normalized per backend by `exec/resources.py`; backends do **not** share a resource vocabulary |
| `cost_model` | Feeds the budget gate and the cost objective |
| `qc_gates` | Mandatory for non-P6 tools; gate 2 refuses a tool composed without them |

## Classification rules

1. **Classify by dominant cost, not capability.** A tool that *can* use a GPU but is normally run on CPU
   is P2.
2. **A secondary pattern is allowed** for genuinely dual-mode tools — record as
   `P2 (primary) / P4 (when the ensemble exceeds remaining walltime)`. Never more than two.
3. **Wrappers inherit what they wrap.** A Python API over an MPI binary is P3.
4. **Egress-dependent tools are P5 even with a local fallback.** Record the fallback under failure modes.
