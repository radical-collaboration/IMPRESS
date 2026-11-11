# IMPRESS-A

**Autonomous protein design on HPC.**

> IMPRESS-A lives in the IMPRESS repository under `agent/`, as a subproject with its own
> `pyproject.toml`: run every command below from `agent/`. It runs on the same middleware as
> IMPRESS - one `radical.asyncflow` engine over `rhapsody` backends - but not on the `impress`
> package itself: each Stage is an asyncflow block, and each tool command an engine task placed
> per backend (`exec/stage.py`, `exec/launch.py`). An earlier execution loop was built on
> `ImpressBasePipeline`/`ImpressManager`; blocks gave natively what that layer had to be taught,
> and `tests/test_layering.py` asserts nothing imports `impress` now.
> The rest of the relationship is shared science — `examples/small_molecule_binding` runs the same
> rfd3 → LigandMPNN → Rosetta → Boltz chain as a fixed adaptive pipeline, where IMPRESS-A composes
> it per cycle.

IMPRESS-A conducts scientific exploration of protein design space given a design prompt — *"stabilize the
given protein"* — by repeatedly deciding what experiment to run next, composing a workflow to run it,
executing that workflow on HPC, interpreting the result, and updating a population of design candidates.

*Autonomous* here has a specific meaning: workflow parameters **and topology** are modified at runtime in
response to production data. The agent is not a pipeline with a smart scheduler; it composes new
workflows each cycle from a registry of tools.

---

## Architecture

### One experiment, one variable step

```
observe ─→ DECIDE ─→ compose ─→ validate ─→ execute ─→ analyze ─→ update ─→ terminate?
         (reasoner)   (typed     (5 gates    (asyncflow) (QC        (tree,
                       DAG)       + dry-run)             gates)     Pareto,
                                      │                             provenance)
                                      └── reject ──→ back to DECIDE (bounded retry)
```

Those steps happen in that order for **any one experiment** — but the reasoner is not the loop body,
so several experiments sit at different steps at once. The executor owns all campaign state and is
its only writer; it reaps runs as they finish and decides termination, because budget, stagnation and
repeated failure are facts about state a reasoner cannot see.

**Only the reasoner differs between control models.** Everything below it — composition, validation,
execution, state, provenance — is shared. That is the whole design: a campaign run by a hand-written
rule cascade exercises identical machinery to one steered by a frontier LLM.

There are two ways to be a reasoner:

- **a Specifier and a Planner** — two halves with separate contracts. The Specifier turns the
  caller's `Goal` into a mutable `Spec` of atomic objectives and revises it as data arrives; the
  Planner maps the ready objectives onto Tasks and emits a candidate `Stage`. This replaced
  `decide(obs) -> Decision`, which answered what the campaign should be trying to achieve and which
  tool should run next in one call — so nothing could say which half of a model earned its cost.
- **`conduct(session)`** — drive yourself. Submit as many experiments as you like, then collect them
  with `as_completed` in the order they *finish*. This is what makes a federation of task agents
  generating an ensemble in parallel expressible at all.

### Pluggable frontends

Two independent frontend axes plug into the same engine. Neither requires changes below the layer it
occupies.

```
        ┌──── INTERFACE FRONTEND ──────┐       who talks to the campaign
        │  in-process · HTTP+SSE · MCP  │
        └───────────────┬───────────────┘
                        │  CampaignControlPlane — one protocol, adapters translate transport only
        ┌───────────────┴───────────────┐
        │      DECISION FRONTEND        │      who decides what runs next
        │    A · B · C · D · your own   │
        └───────────────┬───────────────┘
                        │  Specifier: Goal → Spec   ·   Planner: objectives → Stage
        ═════════════════════════════════       shared engine
           runtime executor · CampaignSession
           compose · validate · tools · exec
```

**Decision frontend — four control models**, exactly one active per campaign, fixed at launch:

Each is a **Specifier half** (`Goal → Spec`, then revisions) and a **Planner half**
(`Spec → Stage`), never a single `decide` call — so a transcript can say which half earned a model
its cost:

| | Model | Mode | the two halves |
|---|---|---|---|
| **A** | Four-node agentic loop | autonomous | A LangGraph graph, two nodes per half; `hypothesize` and `select_tasks` call the model, `analyze` and `parameterize` are deterministic |
| **B** | Heavyweight LLM oracle | autonomous | One structured call per half: `SPEC_SCHEMA` in the Spec's vocabulary, `STAGE_SCHEMA` in the engine's |
| **C** | External caller steering | **headless** | Two role inboxes; blocks on the control plane for a directive |
| **D** | Explicit policy | autonomous | Rules end to end, fully reproducible — the baseline the others justify their cost against |

Writing a fifth is implementing the two protocols and adding a row to `policy/registry.MODELS`.
A reasoner emits *abstract intent* — a `Stage` of `TaskMapping`s, never a concrete DAG — which is
what keeps the models swappable, and halves compose: wrap a Planner in `StageGuard` for an
unconditional external guard, or either half in `LoggingSpecifier`/`LoggingPlanner` for provenance.
See [`docs/impress-a/reference/control-models.md`](../docs/impress-a/reference/control-models.md).

**Interface frontend — control-plane adapters.** One transport-agnostic protocol (`observe`, `events`,
`steer`, `artifacts`, `provenance`, `ingest_measurement`, lifecycle). `observe()` returns the **same
observation object an in-process half is given** — informed monitoring means parity of evidence, not a
progress bar. The protocol also carries runs by id — `submit_run`, `list_runs`, `run_result`,
`cancel_run` — with **synchronous admission**: accepted with an id, or refused with the gate and the
reason that refused it. In-process and HTTP+SSE adapters ship; MCP is the same protocol behind a
different transport.

**The substrate is pluggable too.** Execution backends are selected *by name* from site configuration —
`concurrent` on a laptop, `dragon` or `radical` on HPC — so no backend class is named outside one module.

### What the engine guarantees

- **Free graph composition, five gates.** Type, structure, parameter, resource and budget checks run
  before anything executes, then a dry-run in which every task agent parameterizes without executing.
  Rejection hands the policy a structured reason and another attempt.
- **A QC-failed node is never rankable**, whatever its scores. Scientific tools fail *silently* far more
  often than they crash, so a zero exit code is never sufficient evidence.
- **A self-promoting interlock.** Novel workflow shapes are neither blocked nor trusted on sight: they
  run under a cost cap and a forced dry-run, are marked `suspect` regardless of outcome, and promote only
  after N runs with no *integrity* failure — demoting immediately on one. A design that merely scores
  below threshold still fails its node, but is not evidence against the workflow (decision 0013).
- **Append-only state.** A tree of design lineages ranked by a multi-objective Pareto front, with
  non-destructive backtracking and a complete provenance log.
- **Predicted and measured values are one type.** An objective is declared against a property *name*, so
  a surrogate today and a wet-lab assay tomorrow are interchangeable with no change to the campaign spec.
- **Concurrency that does not lie about evidence.** An *untrusted* workflow shape may have only one
  instance in flight, because promotion counts consecutive clean runs and concurrent instances are one
  draw sampled N times. Stagnation counts *informed* attempts for the same reason — a wave of runs
  launched before any of them reported is one attempt, not N.
- **Typed, serializable artifacts.** A tool hands on an `ArtifactRef` — declared type, path or inline
  value, size and content digest — never a bare string. That is what lets a reasoner in another process
  hold a result, compare it, and pass it back without the file crossing the wire.
- **Durable runs.** Every submission and outcome is written to an append-only ledger, so a finished
  run's result is recoverable by id from a process that did not produce it.

---

## Quickstart

```bash
./scripts/dev_setup.sh && source .venv/bin/activate       # installs `impress` from .. first
                                                          # - it is unreleased, so order matters

ruff check src tests                                      # reports; never rewrites. Ceiling: zero
pytest tests -q                                           # the whole local tier, ~19s, no allocation
impress-a tools                                           # list registered tools
impress-a offer campaigns/mock-stabilize.yaml             # what one invocation costs, and
                                                          # which goals it can address
impress-a run campaigns/mock-stabilize.yaml --model D     # run a campaign
```

A complete campaign runs on a laptop against the bundled mock toolkit — real manager, real policies, real
composer and validator, with stubbed science. That is deliberate: HPC iteration is slow and expensive, so
almost everything is verifiable locally.

```
$ impress-a run campaigns/mock-stabilize.yaml --model A
  cycles : 3
  stop   : front target reached
  nodes  : 6  front: 3
    n000004 qc=pass  sc_rmsd=2.023 iptm=0.645 ddg=1.517
    n000005 qc=pass  sc_rmsd=0.431 iptm=0.906 ddg=-2.04
    n000006 qc=pass  sc_rmsd=2.116 iptm=0.607 ddg=0.073
```

### On Delta

```bash
export WORK_DIR=/work/nvme/<project>/$USER     # NVMe, not /work/hdd - see docs/impress-a/limitations.md
impress-a preflight campaigns/delta-small-molecule-smoke.yaml
sbatch scripts/delta_gpu_run.sh campaigns/delta-small-molecule-smoke.yaml
```

Each job writes one self-contained directory, `$WORK_DIR/impress_a_runs/<jobid>_<campaign>/`:

```
manifest.json            job id, campaign, model, nodes, git sha (+dirty), start/end, exit code
slurm.out                the job's SLURM output, moved here on exit
campaign.log             the campaign transcript
<campaign_id>-<model>/   provenance/*.jsonl and jobs/ledger.jsonl
work/                    one directory per tool task, with its real outputs
runinfo/                 Dragon's own
```

The trust ledger is site-scoped and lives outside it, in `$WORK_DIR/_trust/`.
`$WORK_DIR/impress_a_runs/INDEX.md` records which jobs were kept and what each one showed.

## Defining a campaign

```yaml
campaign_id: stabilize-lysozyme
goal: "Stabilize the given protein while preserving the designed fold"
backend: concurrent                 # or dragon / radical on HPC
budget: {gpu_hours: 2.0, cpu_hours: 12.0}
objectives:
  - {name: sc_rmsd, direction: minimize, max: 3.0}    # constraints prune
  - {name: iptm,    direction: maximize, min: 0.55}   # directions rank
  - {name: ddg,     direction: minimize}
```

## Adding a tool

A declarative `spec.yaml` plus a `TaskAgent` subclass, in a toolkit directory alongside the `SKILL.md`
that tells an agent how to use it. Loading is validating — a bad range, an unknown QC gate, or a missing
skill section fails at load, and a toolkit that fails anywhere registers nothing. Adding a tool never
requires touching the composer, validator or manager. See
[`docs/impress-a/reference/authoring-tools.md`](../docs/impress-a/reference/authoring-tools.md).

## Requirements

Python **≥3.11** everywhere (radical.asyncflow and rhapsody 0.7.0 require it); Dragon is the
`[dragon]` extra. Scientific tools run
as subprocesses or in containers and do not constrain the agent environment. Built on
[`radical.asyncflow`](https://github.com/radical-cybertools/radical.asyncflow) and
[`rhapsody`](https://github.com/radical-cybertools/rhapsody); LangGraph drives the control-model-A loop.

## Documentation

| | |
|---|---|
| [`docs/impress-a/reference/architecture.md`](../docs/impress-a/reference/architecture.md) | The loop, layers, import contract, invariants |
| [`docs/impress-a/reference/resolution.md`](../docs/impress-a/reference/resolution.md) | **How the toolkit, goal, budget and parameters become specified targets and a programmed Stage** — step by step, with what refuses each one |
| [`docs/impress-a/reference/observation.md`](../docs/impress-a/reference/observation.md) | **How a running campaign's state becomes a `CampaignObservation`, who is shown it, what survives to disk, and how any of it reaches a caller** — with the eleven things the plane does not enforce |
| [`docs/impress-a/reference/frontends.md`](../docs/impress-a/reference/frontends.md) | The two frontend axes: which seams are swappable, the protocols they implement, and how to write one |
| [`docs/impress-a/reference/control-models.md`](../docs/impress-a/reference/control-models.md) | The four reasoners: what each is shown, what it may choose, how its reply is constrained |
| [`docs/impress-a/reference/mock-lab.md`](../docs/impress-a/reference/mock-lab.md) | The laptop knob lab and the reasoner axis: what it runs and what its numbers license |
| [`docs/impress-a/reference/compute-patterns.md`](../docs/impress-a/reference/compute-patterns.md) | P1–P8 — normative for every `ToolSpec` |
| [`docs/impress-a/reference/authoring-tools.md`](../docs/impress-a/reference/authoring-tools.md) | Writing tools, gates and skill documents |
| [`docs/impress-a/reference/middleware-integration.md`](../docs/impress-a/reference/middleware-integration.md) | asyncflow / rhapsody seam and its gotchas |
| [`docs/impress-a/reference/aucam.md`](../docs/impress-a/reference/aucam.md) | Running as one subordinate workflow under an enclosing campaign manager: the seam, the offer handshake, and the pin |
| [`docs/impress-a/decisions/`](../docs/impress-a/decisions/) | Numbered, immutable architecture decision records |
| [`docs/impress-a/limitations.md`](../docs/impress-a/limitations.md) | Known gaps and residual risks, stated plainly |

`planning/` holds the design record that produced this system. It is process history, not reference
documentation, and is not part of the published package.

## Status

Reference implementation, exercised end to end on a laptop and not yet on real hardware.

| | |
|---|---|
| Engine — compose, five gates, interlock, Pareto tree, provenance | works |
| Four control models (A/B/C/D), plus `conduct` reasoners | works |
| Concurrent experiments, durable runs, reattach after restart | works |
| Control plane — in-process and HTTP+SSE adapters | works |
| Mock toolkit campaign | works |
| Real toolkits (RFdiffusion3, LigandMPNN, PyRosetta, Boltz) | six-stage chain executed end to end on Delta; trusted path reached (job 22726105); `replicas > 1` never run |

`pytest tests -q` — ~10s, no allocation. A complete campaign runs on a laptop with stubbed
science, which is deliberate: HPC iteration is slow and expensive, so almost everything is verifiable
locally. The corollary is that everything *only* verifiable on HPC is unverified.

## Known issues

**No real campaign has ever run.** The four real toolkits register, validate, type-check as a chain
and dry-run, and their adapters invoke real binaries — but no line of RFdiffusion, LigandMPNN,
PyRosetta or Boltz code has executed through this system. Treat the real path as untested.

**The Dragon backend can hang silently during construction.** `Batch()` is built synchronously with
no `await` points, so a stall there blocks the event loop entirely — no heartbeat, no timeout, until
whatever wall-clock limit kills the job. Measured, not theoretical: job 22318678 spent its full
2-hour allocation this way. Bounded now by `backend_startup_timeout_s`/`backend_startup_heartbeat_s`
on `CampaignSpec` (both Delta campaigns set 600s); see `docs/impress-a/limitations.md`.

**`ligand_smiles` was empty** in both Delta campaign specs. Resolved for the ALR benchmark target
(`campaigns/data/alr/`, borrowed from `examples/small_molecule_binding`) — both campaigns now set it to
the real ligand's SMILES, and a fail-fast check catches any future target that leaves it blank
instead of silently modeling no ligand.

**Three tool arguments were unverified** and are now checked directly against the installed real
toolkits on Delta: LigandMPNN's and Boltz's seed/batch flags were confirmed correct as written.
RFD3's contract was not merely unverified but **wrong** — it invoked flags (`--config`/`--out`) the
real Hydra-based CLI doesn't have — and has been rewritten to the real contract. `boltz_predict` was
also found to be missing a required `--no_kernels` flag along the way. Run `impress-a preflight` on
a login node first regardless — it now also checks `ligand_smiles`.

**QC for the real toolkits is thin where it matters most.** The specs lean almost entirely on
`metric_in_range` against each tool's *own* self-reported confidence — which is exactly what a
confidently-wrong tool passes. There are no structural gates (is the ligand actually in the output
complex, are there chain breaks, does sequence length match the contig). Every real tool now
carries the known-bad fixtures `docs/impress-a/reference/authoring-tools.md` asks for, so its declared gates
have been seen to fail on output that should fail them; what those gates *measure* is still the
tool's own opinion of itself.

**Cancellation is advisory.** Measured, not assumed: the concurrent backend's `Future.cancel()`
returns `False` once a callable has started and asyncflow discards that answer, so queued work is
reclaimed and running work is not. A run's terminal state always comes from collecting it. Reclaiming
a GPU from an abandoned run is unsolved.

**Cost models are unmeasured.** Gate 5 and the interlock's 10% provisional cap refuse graphs against
literature figures, not measurements. This already bites: a campaign budget can be too small to admit
its own first run.

**`sites/*.yaml` is read by no code.** Its `tool_delivery: {real|mock}` switch is inert.

## Plans

`plans/` holds the working plans: [`plans/backlog.md`](plans/backlog.md) is the live list of
outstanding work with a recommended order, `plans/*.md` are stubs for the next tracks, and
`plans/done/` records completed work and the decisions behind it — the rulings are the part worth
keeping, not the task lists.

Nearest term: structural QC gates (the known-bad fixtures now exist), then the first real Delta run. Further out:
the MCP adapter, checkpoint/restart resume (the ledger and `reattach` exist; nothing resumes from
them yet), registry hardening, and the P5 network-service governor.
