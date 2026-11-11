# IMPRESS-A

**Autonomous protein design on HPC.**

IMPRESS-A conducts scientific exploration of protein design space given a design prompt —
*"stabilize the given protein"* — by repeatedly deciding what experiment to run next, composing a
workflow to run it, executing that workflow on HPC, interpreting the result, and updating a
population of design candidates.

!!! tip "Run it before you read it"

    [Ten minutes with a mock campaign](../notebooks/impress_a_knob_lab.ipynb)
    runs that loop in a browser tab against a laptop surrogate of the
    small-molecule binding chain — same executor, same gates, same thresholds,
    no allocation. It walks the four knob arms, then asks you to predict what a
    campaign will do before you break it.

## What *autonomous* means here

Workflow parameters **and topology** are modified at runtime in response to production data. The
agent is not a pipeline with a smart scheduler: it composes a new workflow each cycle from a registry
of tools.

That is the distinction from [Adaptive Execution](../concepts/adaptive-execution.md), which is
IMPRESS's own protocol for a pipeline spawning child pipelines from a decision function you write.
There, the shape of the work is fixed and the branching is parameterised. Here, the shape itself is
the output of a reasoner, and nothing in the graph is written down ahead of time.

### One experiment, one variable step

```
observe ─→ DECIDE ─→ compose ─→ validate ─→ execute ─→ analyze ─→ update ─→ terminate?
         (reasoner)   (typed     (5 gates    (asyncflow) (QC        (tree,
                       DAG)       + dry-run)             gates)     Pareto,
                                      │                             provenance)
                                      └── reject ──→ back to DECIDE (bounded retry)
```

Those steps happen in that order for any one experiment, but the reasoner is not the loop body, so
several experiments sit at different steps at once. The executor owns all campaign state and is its
only writer.

## Relationship to IMPRESS

IMPRESS-A is a **separate package**: `impress_a`, Python >= 3.11, living in this repository under
[`agent/`](https://github.com/radical-collaboration/IMPRESS/tree/main/agent). It is not on PyPI and
is not installed by `pip install .` at the repository root — see
[Installation](../getting-started/installation.md).

It runs on the same middleware as IMPRESS — one `radical.asyncflow` engine over `rhapsody`
backends, reaching Dragon only through them — but not on the `impress` package: each Stage is an
asyncflow block, and each tool command an engine task placed per backend. See
[Architecture](../concepts/architecture.md) for the shared engine conventions. The two also share
science:
[Small Molecule Binding](../examples/small-molecule-binding.md) runs the same
rfd3 → LigandMPNN → Rosetta → Boltz chain as a fixed adaptive pipeline, where IMPRESS-A composes it
per cycle.

Neither package depends on the other. The two are never installed into one environment as a
merged dependency set: IMPRESS targets Python >= 3.9 with radical.pilot, and IMPRESS-A >= 3.11 with
langgraph, rhapsody and biopython.

## This section

| | |
|---|---|
| [Architecture](reference/architecture.md) | The loop, layers, import contract, invariants |
| [Resolution](reference/resolution.md) | How the toolkit, goal, budget and parameters become specified targets and a programmed Stage — step by step, with what refuses each one |
| [Observation](reference/observation.md) | How a running campaign's state becomes a `CampaignObservation`, who is shown it, what survives to disk, and how any of it reaches a caller |
| [Pluggable Frontends](reference/frontends.md) | The two frontend axes: which seams are swappable, the protocols they implement, and how to write one |
| [Control Models](reference/control-models.md) | The four reasoners: what each is shown, what it may choose, how its reply is constrained |
| [Compute Patterns](reference/compute-patterns.md) | P1–P8 — normative for every `ToolSpec` |
| [Authoring Tools](reference/authoring-tools.md) | Writing tools, gates and skill documents |
| [Middleware Integration](reference/middleware-integration.md) | asyncflow / rhapsody seam and its gotchas |
| [AuCaM Integration](reference/aucam.md) | Running as one subordinate workflow under an enclosing campaign manager: the seam, the offer handshake, and the pin |
| [The Mock Knob Lab](reference/mock-lab.md) | The laptop knob lab and the reasoner axis: what it runs and what its numbers license |
| [Known Limitations](limitations.md) | Known gaps and residual risks, stated plainly |
| [Decisions](decisions/index.md) | Numbered, immutable architecture decision records |
| [Roadmap](roadmap/academy-for-task-agents.md) | Standing notes on task-agent training |
