# Branch lineage: `main` to the IMPRESS-A work

**Written:** 2026-11-09 · **Repo:** `radical-collaboration/IMPRESS` · **`main`:** `d51c292`
(PR #73, "merge-impress-a") · **Method:** every ancestry claim below is from
`git merge-base --is-ancestor`, every file count from `git diff --name-only`, and the conflict
surface from a non-destructive `git merge-tree --write-tree`. Nothing was merged, rebased,
pushed or deleted to produce it.

## Shape

The IMPRESS-A work is a **stack with one fork**, not a line. `agent/reasoner-models` has two
children: the control-plane chain that leads to the current work, and `project/unify-ci-and-docs`,
which is a sibling and **not** an ancestor of the current tip.

```
main                                          d51c292
 │  25 commits                                                 ── touches IMPRESS pipeline
 └─ examples/agentic-small-molecule-binding    f323fa2  main+25   [remote tip = fork point]
     │                                         (+2 local, unpushed, NOT in the stack)
     │  2 commits
     └─ agent/reasoner-models                  fd851ea  main+27
         │
         ├─ agent/control-plane-p0-p3          3bf42e5  main+35
         │   │  3
         │   └─ agent/control-plane-p4-p6      2cf61f9  main+38
         │       │  7
         │       └─ agent/control-plane-p7-p9  23de122  main+45
         │           │  9
         │           └─ agent/calibration-p10-p11  2ec9011  main+54  [remote tip]
         │               │  11 unpushed    →  6f5e528  main+65  [local tip]
         │               └─ agent/stopping-rules    25550f7  main+71  [local only] ← current
         │
         └─ project/unify-ci-and-docs          f3d1ef3  main+35   ── touches IMPRESS pipeline
                                                                      (NOT an ancestor of the tip)
```

## What each branch is, and what it touches

The distinction that matters for review: **`agent/`** is the IMPRESS-A sub-project; anything
under root `src/`, `tests/`, `examples/`, `docs/`, `.github/`, `tox.ini`, `mkdocs.yml`,
`pyproject.toml` or `README.md` is IMPRESS proper.

| branch | commits | files | touches |
|---|---|---|---|
| `examples/agentic-small-molecule-binding` | 25 | 16 | **pipeline** |
| `agent/reasoner-models` | 2 | 7 | `agent/` only |
| `agent/control-plane-p0-p3` | 8 | 65 | `agent/` + 1 CI file |
| `agent/control-plane-p4-p6` | 3 | 23 | `agent/` only |
| `agent/control-plane-p7-p9` | 7 | 59 | `agent/` only |
| `agent/calibration-p10-p11` | 9 + 11 local | 73 + 21 | `agent/` only |
| `agent/stopping-rules` | 6 | 22 | `agent/` only |
| `project/unify-ci-and-docs` | 8 | 101 | **pipeline, heavily** |

**`examples/agentic-small-molecule-binding`** — adds the agentic small-molecule-binding example
to IMPRESS proper: `examples/agentic_small_molecule_binding/` (pipeline, LLM client, prompts,
tools, a vLLM service, `models.yaml`, tests), its page under `docs/examples/`, a BACKLOG entry in
the non-agentic example, and registration in `mkdocs.yml` and `pyproject.toml`. Carries the
model-provenance guard that fails the suite if a profile names a barred vendor. Its **remote tip
is the fork point for everything below**, so the whole stack rests on it. Two local commits sit
past that point — model D's first hardware run, and the control arm finding the harness is not
neutral — and are in neither the stack nor the remote.

**`agent/reasoner-models`** — gives the four control models a home with a checkable status, and
records the reasoner-model plan beside the code. Where the A/B/C/D vocabulary begins, and the
point the stack forks.

**`agent/control-plane-p0-p3`** — phases 0–3: a real toolchain and a lint ceiling of zero, the
Spec vocabulary and the two role contracts, the role pipeline proven to change nothing, the
Toolkit a reasoner can see, `Goal → Spec` for real, asserted trust, and Stage as the unit of
admission. Adds `.github/workflows/agent-tests.yml` — the only non-`agent/` file the entire
agent stack authors.

**`agent/control-plane-p4-p6`** — phases 4–6: inputs wired by declared port, `DELETED` reaching
`CANCEL`, cost measured as well as declared, and the execution loop running on `impress` itself,
opt-in and proven equivalent.

**`agent/control-plane-p7-p9`** — phases 7–9: the control plane in its own process and a bug only
the split could find, the refinement loop, four models' real halves, GPU pinning on both
execution loops, model B's live client, and arm C's real arrangement with four security-review
findings.

**`agent/calibration-p10-p11`** — phases 10–11: the thresholds a campaign is judged on, gate 6,
`impress-a validate-tasks`, the scoring harness, and deletion of the legacy `decide` path; then
the four-arm experiment — pre-registration, both campaign specs, the Delta launcher. Its 11
unpushed commits are defects only running it could find: the C11 checkout discovery, a preflight
probe that bypassed the MPNN shim and blamed the tool, the Rosetta XML and cost-model unit
errors, the QC-failure path that could not survive a QC failure, and the liveness bound that
killed the three arms with no control plane.

**`agent/stopping-rules`** — the current work. G11 (`target_front` was declared in two places and
read by nothing, so a campaign asked for ten designs stopped at one), G12 (arm C served a
campaign that two reasoners drove), a C11 recurrence in the validation wrapper, G13 (the control
arm composed half the width under a different trust interlock), and a ten-item provenance sweep.

**`project/unify-ci-and-docs`** — the sibling, and the most pipeline-invasive branch in the
family: one lint contract for both projects, a mechanical reformat and lint-clean of both, agent
environments folded into `tox`, `ci.yml` replacing `tests.yml` / `agent-tests.yml` / `docs.yml`,
`agent/docs` moved to `docs/impress-a` with 71 references updated, and a tip commit that repeals
a boundary rule the work breaks. Footprint: `agent/` 59, `docs/` 21, `tests/` 7, **root `src/` 5
including `src/impress/impress_manager.py`**, `.github/` 4, plus `tox.ini`, `scripts/`,
`pyproject.toml`, `mkdocs.yml` and `README.md`.

## The conflict surface, measured

`git merge-tree --write-tree origin/project/unify-ci-and-docs agent/stopping-rules` reports
**18 conflicted paths**: 14 content, 4 modify/delete.

**The docs move is not among them.** Unify renames all 21 `agent/docs/*` to `docs/impress-a/*`
as pure renames (`R100`, no content change), so git's rename detection follows them and the six
files the stack edited under `agent/docs` merge cleanly. An earlier reading of this review
predicted a docs-tree conflict; that prediction was wrong.

**Modify/delete (4):**

| path | what happened |
|---|---|
| `.github/workflows/agent-tests.yml` | unify deletes it (`ci.yml` supersedes); the stack modifies it |
| `agent/src/impress_a/policy/agentic.py` | the stack **deleted** it (phases 9/11 split policy into `planners/` and `specifiers/`); unify reformatted it |
| `agent/src/impress_a/policy/explicit.py` | same |
| `agent/src/impress_a/policy/external.py` | same |

**Content (14):** `agent/pyproject.toml`, `agent/plans/backlog.md`,
`compose/validate.py`, `core/provenance.py`, `policy/oracle.py`, `policy/registry.py`,
`policy/wrappers.py`, `tools/registry.py`, `tools/rosetta_agents.py`, and five test files
(`test_campaign`, `test_core`, `test_gate_fixtures`, `test_real_toolkits`, `test_validation`).

**Almost all of it is one mechanical reformat.** Attributing the 16 conflicting source paths to
the unify commits that touch them:

| unify commit | conflicting files touched | |
|---|---|---|
| `6e576d5` | **12** | Mechanical: reformat root at the new width, autofix both projects |
| `8821dd5` | **10** | Clear the last 23 lint findings, and correct the ceiling |
| `168c848` | 2 | Publish IMPRESS-A: nav, site metadata, 71 moved references |
| `04e72cb` | 1 | One test entry point: agent environments in tox |
| `f0bfed1` | **0** | One lint contract for both projects |
| `5b33806` | **0** | One workflow: `ci.yml` replaces three |
| `115437d` | **0** | Move `agent/docs` to `docs/impress-a` |
| `f3d1ef3` | **0** | Repeal the boundary rule this work breaks |

The four structurally novel commits conflict with **nothing**. The entire surface comes from
reformatting files that 36 later commits of agent work then rewrote or deleted.

## Merge order, and what follows from the measurement

1. **`examples/agentic-small-molecule-binding` first.** Its remote tip is the fork point, so any
   PR of the stack carries its 25 commits unless it lands first. Decide what to do with the two
   unpushed commits past the fork before, not during.
2. **Then the agent stack, in its published order** — `reasoner-models`, `control-plane-p0-p3`,
   `p4-p6`, `p7-p9`, `calibration-p10-p11`, `stopping-rules`. Each is `agent/`-only bar one CI
   file, so each reviews against a stable pipeline.
3. **Then `project/unify-ci-and-docs`, with its two mechanical commits regenerated rather than
   merged.** `f0bfed1`, `5b33806`, `115437d`, `168c848` and `f3d1ef3` carry the structural change
   and conflict with nothing. `6e576d5` and `8821dd5` are a formatter run, and re-running the
   formatter against the post-stack tree is both cheaper and more correct than resolving 16
   files of reformat-versus-rewrite by hand — a resolution that cannot be verified by reading
   the diff, which is the worst property a merge resolution can have.

Two things this review does not settle. `f3d1ef3`, "Repeal the boundary rule this work breaks,
and say what it protected", is a policy change and wants its own review rather than a place in a
merge order. And `agent/pyproject.toml` is a genuine content conflict, not a formatting one: two
lint contracts have to be reconciled deliberately, since the stack's local `[tool.ruff]` table is
what makes its ceiling of zero mean anything.

## Branches outside this family

| branch | vs `main` | touches |
|---|---|---|
| `smb-nonadaptive-benchmark` | +18 / −64 | **pipeline** — root `src/` 2, `tests/` 7, `docs/`, `examples/` |
| `smb-benchmark-f19` | +24 / −56 | **pipeline** — `examples/`, `docs/`, `plans/` |
| `slides/fold-in-2026-10-26-analysis` | — | reported to contend with unify over `agent/slides/run_model.py`; not verified here |
| `boltz-integration`, `telemetry-scaleup`, `use_case/secondary_diffusion`, `fix/remove-scratch-paths`, six `feature/*`, `archive/*`, `gh-pages` | — | not surveyed |
| `merge-impress-a`, `docs/post-pr72`, `framework-defaults-pr1` | merged or deleted upstream | stale local refs |

## Correction record

An earlier pass at this review was produced with `git branch`, which lists **local refs only**.
Four `agent/*` branches and `project/unify-ci-and-docs` have no local ref in that checkout, so
they were absent from the survey and the stack was described as five branches rather than
eight. Two conclusions drawn from that incomplete set were wrong and are corrected above:
`project/unify-ci-and-docs` was filed as unrelated work on the strength of its name, when it is
a child of `agent/reasoner-models`; and the agent family was said to touch no IMPRESS pipeline
component but the example branch, when that sibling touches root `src/`, `tests/` and `docs/`.
Any future survey of this repository should start from `git ls-remote --heads origin`.
