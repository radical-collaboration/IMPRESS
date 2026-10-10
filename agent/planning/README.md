# Planning Record

**This is process history, not reference documentation, and is not part of the published package.**

These are the working documents that produced IMPRESS-A: a toolkit survey, an architecture design, a
project-structure design, a middleware evaluation, a prior-art review, and implementation notes. They are
kept because the *reasoning* behind several non-obvious decisions lives here and is hard to reconstruct —
including findings that were later corrected.

For anything you need in order to work on or use the system, read `docs/` instead:

| You want | Read |
|---|---|
| How it works | `docs/reference/architecture.md` |
| Why it works that way | `docs/decisions/` |
| How to extend it | `docs/reference/authoring-tools.md` |
| What it cannot do | `docs/limitations.md` |

Where these documents disagree with `docs/` or with the code, **the code and `docs/` are correct**.
Several conclusions here were revised by later phases or by building the thing — that is the point of
keeping them, not a reason to trust them.

| Directory | Contents |
|---|---|
| `phase1-partA-toolkit/` | Survey of 40 scientific tools; the compute-pattern taxonomy originated here |
| `phase1-partB-architecture/` | The agent architecture design |
| `phase1-partC-structure/` | Repository layout, environments, test strategy |
| `phase2-middleware/` | Evaluation of asyncflow, rhapsody, ADR, flowgentic, radex, ORBIT |
| `phase3-prior-art/` | Three prior attempts at related work, with an adopt/adapt/avoid catalogue |
| `phase4-implementation/` | What was built, and what building it taught us |
