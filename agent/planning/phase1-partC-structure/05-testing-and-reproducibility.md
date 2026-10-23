# 05 — Testing and Reproducibility

Answers Part B's C6. The governing constraint: **HPC iteration is slow and expensive, so almost everything
must be verifiable on a laptop.** The architecture was built to allow this; the test strategy is where that
investment is collected.

## 1. Four tiers

| Tier | Runs on | Duration | Gates |
|---|---|---|---|
| **T1 — unit** | Laptop, CI | seconds | Every commit |
| **T2 — mock campaign** | Laptop, CI | minutes | Every commit |
| **T3 — smoke** | One HPC site | ~1 hour | Merge to main, site bring-up |
| **T4 — golden campaign** | HPC | hours | Release, and after composer/validator changes |

### T1 — unit

Pure logic, no I/O. The Pareto computation, tree operations and backtracking, budget ledger, artifact type
unification, each validation gate in isolation, each QC gate against recorded fixtures.

The QC gate tests matter more than their size suggests. Each gate exists because Part A documented a
specific silent failure, and `tools/*/tests/fixtures/` holds **real recorded outputs** — including known-bad
ones. A gate that has never seen the failure it was written for is an assertion, not a test.

### T2 — mock campaign

A complete campaign, end to end, on a laptop: real manager, real policy, real composer, real validator, real
state and provenance — with `ConcurrentExecutionBackend(ProcessPoolExecutor)` and **mock tool specs** that
return canned artifacts with plausible metrics.

This tier exercises every layer above the substrate and is the reason the import contract (`01 §4`) forbids
`compose → exec`. It should cover:

- All three autonomous policies (A, B with a stubbed oracle, D) reaching termination
- Headless mode driven by a scripted caller through the in-process adapter
- Graph rejection at each of the five gates, and each policy's `on_rejected` response
- Kill-and-recover mid-campaign, asserting the resumed tree matches
- Budget exhaustion, stagnation, and goal-satisfaction terminations
- Oracle failure triggering declared degraded mode — the demonstrated R7 path

**A mock tool must be able to lie.** Mocks that return plausible-but-wrong output — a structure with no
secondary structure, an affinity on an out-of-regime ligand — are how the QC layer is tested at campaign
scale rather than per gate. Silent failure is the dominant hazard; the test suite has to produce some.

### T3 — smoke

Minimal real campaign on a real site: one real tool per compute pattern, two or three cycles, small designs.
Validates the things mocks cannot — container invocation, checkpoint staging and hashing, scheduler
submission, real GPU placement, P4 submit/poll against the real queue, P5 against real services.

Part of site bring-up (`04 §5`), and the place measured costs are collected.

### T4 — golden campaign

A recorded campaign replayed via model D's replay policy (Part B `02 §5`), asserting the same decision
sequence composes to the same graphs and passes the same gates.

This is the payoff of the provenance design: it detects regressions in the composer, validator, cost model
and registry that unit tests cannot, because it exercises them against a real decision trace.

**It is a regression test, not a science test.** LLM policies are not bit-reproducible; the golden campaign
replays *recorded decisions* through the deterministic machinery below them. What it proves is that the same
inputs still produce the same workflow — not that the science is right.

## 2. What reproducibility means here, precisely

Worth stating plainly, because "reproducible" is doing different work at each layer.

| Layer | Reproducible? | Mechanism |
|---|---|---|
| Core, composition, validation | **Bit-exact** | Pure functions, seeded |
| Model D policies | **Bit-exact** | Deterministic, seeded |
| Tool execution | **Approximately** | Pinned versions and checkpoint hashes; GPU non-determinism remains |
| Model A / B policies | **No** | No `seed` on the Anthropic API; temperature 0 does not guarantee determinism |
| A campaign as a whole | **Reconstructable, not replayable** | Full provenance; replay re-executes recorded decisions |

Part A's R8 is a scientific-integrity issue, not an engineering one, and the honest claim is the last row:
an LLM-steered campaign can be *audited and reconstructed*, not *re-run to the same answer*. A campaign
write-up should say so. Model D exists partly so there is a fully reproducible baseline to compare against.

## 3. Continuous integration

| Check | Enforces |
|---|---|
| T1 + T2 | Correctness |
| Import-linter against the contract in `01 §4` | Layering — especially `policy ↛ tools` and `compose ↛ exec` |
| Registry load of every toolkit | Every `spec.yaml` parses, ranges include defaults, gates resolve |
| Skill-doc referential integrity | Required sections present; tools and docs mention each other (`02 §4`) |
| Spec-to-brief cross-check | Every `ToolSpec` has a Part A brief and vice versa |
| Cost-model sanity | Every spec has a `cost_model`; Gate 5 cannot be bypassed by omission |

The spec-to-brief cross-check keeps Part A's 38 briefs live documentation rather than a snapshot that
silently diverges the first time a tool is added in code alone.

## 4. What is not tested, and is therefore a standing risk

Stated rather than implied.

- **Scientific validity.** Nothing here tests whether a design is good. The Pareto front ranks predicted
  quantities, and Part A established the loop closes *in silico* only. Validation is wet-lab work outside
  this system.
- **Novel silent failure.** By definition untestable in advance (Part B `05 §9`). T2's lying mocks test the
  gates we wrote, not the ones we did not think of.
- **Cross-tool independence.** T2 can assert the consistency check fires; it cannot establish that ESMFold
  and Boltz agreeing means anything, which Part B `08` flags as an open empirical question.
- **Real multi-day campaign behaviour.** Drift, accumulation, and degradation over hundreds of cycles are
  not reachable by any tier above. Only operation will surface these.
