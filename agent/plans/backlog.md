# Backlog

Everything outstanding. Each item says why it matters so the list can be triaged rather than
worked through top to bottom. Items resolved since the list was written carry a **RESOLVED**
paragraph in place rather than being deleted - the evidence that forced them is the useful part.

State it is measured against: local tier green, lint at its ceiling, the import contract clean **and
now asserted** (`tests/test_layering.py`), all control models
run, the real Delta chain composes, dry-runs, and passes `impress-a preflight` for the ALR target
on Delta - but no line of the real toolkits has executed yet (A1).

---

## A. Blocked on a person, not on code

**A1. No real campaign has ever run.** Every claim about the real toolkits is validation, dry-run and
unit-level. `campaigns/_runs/` holds only mock runs.

**A2. `ligand_smiles` was empty** in both Delta campaigns - RESOLVED for the ALR target: both
campaigns now set it to the real value borrowed from the original IMPRESS project's small-molecule
benchmark (`campaigns/data/alr/ALR.smiles`), and `_check_ligand_smiles` (`cli/__init__.py`, wired
into both `run_campaign()` and `preflight()`) fails fast for any *future* target that leaves it
blank, instead of silently modeling no ligand. Verified on Delta: `impress-a preflight` on the
smoke campaign shows no `ligand_smiles` failure row.

**A3. Three unverified arguments — RESOLVED**, checked directly against the installed real
toolkits on Delta this session: LigandMPNN's `--seed`/`--number_of_batches` (confirmed correct as
originally written — `--batch_size` defaults to `1`, so `--number_of_batches <num_seqs>` alone gives
exactly `num_seqs` sequences), and Boltz's `--seed`. RFD3's contract, however, was **wrong**, not
merely unverified: `rfd3_agents.py` invoked `rfd3 design --config <json> --out <dir>`, but the real
CLI (`rfd3.cli:design`, a Typer app forwarding every arg as a Hydra `key=value` override) has no
`--flag` options at all - that invocation would have failed immediately. Rewritten to the real
`out_dir=`/`inputs=`/`diffusion_batch_size=`/`inference_sampler.num_timesteps=`/`seed=` contract; see
`toolkits/rfd3/SKILL.md`. Also found and fixed in the same pass: `boltz_predict` was missing the
required `--no_kernels` flag (a verified CUDA ABI mismatch, not optional); `ligandmpnn_design` had
no way to express a fixed-residue constraint (`--fixed_residues` is a real flag); none of the three
Rosetta toolkits had a way to pass a ligand `.params` file (`-extra_res_fa`), so a real ALR-ligand
PDB would likely raise in `pose_from_pdb()`. All four fixed; see each toolkit's `SKILL.md`.

**A5. The Dragon backend construction hang is bounded, not diagnosed.** Job 22318678 ran the full
2-hour allocation and was killed on the time limit after producing only Dragon's own infra-connect
log lines - no campaign log, no ledger entry, nothing else, for the whole run. Traced to
`rhapsody.DragonExecutionBackend.__init__` building Dragon's `Batch()` (results DDict, GPU-affinity
worker pool, telemetry) synchronously with no `await` points, blocking the event loop entirely -
the codebase's own heartbeat never fired once in 2 hours because of it. Now bounded by
`backend_startup_timeout_s`/`backend_startup_heartbeat_s` on `CampaignSpec` (see
`exec/backend.make_engine_bounded`, `docs/limitations.md`): a future stall fails loudly within
minutes instead of consuming the whole allocation silently. What remains open: *why* `Batch()`/
`Pool()` didn't complete inside 2 hours in the first place (most likely GPU-affinity worker
rendezvous or OFI/libfabric negotiation under single-node `-s` Dragon mode) is still unknown - that
needs a person on a real allocation, with the bounded timeout now giving a fast, clear failure to
iterate against instead of another silent multi-hour loss.

**A4. The rfd3_design rewrite needs a real smoke-run confirmation.** The Hydra contract and
`DesignInputSpecification` JSON shape are verified against the installed `rfd3` CLI's own source,
but the output-parsing half of `RFD3DesignAgent` (glob for `*.cif.gz`, convert via `cif_gz_to_pdb`)
was not re-verified against a real `out_dir` listing - confirm the exact output filenames on the
first real smoke run (`dump_prediction_metadata_json`/`output_full_json` are both `True` by
default, so this should be visible immediately). **Largely answered by the reference pipeline**,
which discovers candidates as `*.json` containing `_model_` and derives the structure by
`.replace('.json', '.cif.gz')` - so the shape is `*_model_*.cif.gz` alongside `*_model_*.json`. Our
glob finds the structures; confirm on the first real run, and see G2 for using the JSON we discard.

## B. Silent-failure defences — unmet for the real toolkits

The project's central claim is that these tools fail *silently*. For the real toolkits that defence
is currently a threshold on each tool's own opinion of itself.

**B1. No structural QC gates.** Nothing checks the ligand is actually present in the output complex,
that there are no chain breaks, or that sequence length matches the contig. `mock_noodle` exists to
prove this failure mode is the dominant one; the real tools have no equivalent.

  **Cheaper than this entry implies, for rfd3 at least.** RFD3 already reports its own structural
  metrics in a sidecar `*_model_*.json` beside each `.cif.gz`: `n_clashing.ligand_clashes`,
  `n_clashing.interresidue_clashes_w_sidechain`/`_w_backbone`, `max_ca_deviation`, `helix_fraction`,
  `sheet_fraction`. The reference IMPRESS pipeline gates on exactly these
  (`analysis_backbone`, `small_molecule_binding.py:766-833`). We ignore the JSON entirely: we glob
  `*.cif.gz`, take `cif_models[0]` unconditionally, and compute our own phi/psi SS fraction
  (`_pdbtools.py:19-42`, explicitly not DSSP). A `ligand_clashes == 0` gate is a real structural
  check, and unlike `metric_in_range` on a self-reported confidence it is a measurement of the
  output geometry rather than the tool's opinion of itself - so it is not the caveat in
  `docs/limitations.md`. See G2.

**B2. No known-bad fixtures — RESOLVED.** Every non-mock tool now carries `tests/*.bad.json` and
`tests/*.good.json`, run against its own declared gates by `tests/test_gate_fixtures.py`, which also
fails if a new real tool arrives without one. The payloads are transcribed from each adapter's own
failure branches, not observed from a run (A1 is still open), and two of them are filed as bug
reports rather than as reassurance: `ligandmpnn_design/tests/unparsed_confidence_header.bad.json`
pins a parser failure being reported as 0.0 confidence, and
`fastrelax/tests/passes_ours_fails_upstream.good.json` is the executable record of G4 — it must move
to `.bad.json` when G4 closes. What remains unmet is B1: no fixture here is *structural*, because no
structural gate exists to feed.

**B3. `count_matches_request` is implemented and referenced by nothing** — while `FastRelaxAgent` was,
until recently, fabricating exactly the count such a gate would have caught. It now has its first
test (`test_gate_fixtures.py::test_count_matches_request_catches_a_fabricated_count`), which also
pins the reason wiring it up is not free: with no `expected` param the gate abstains, so adding the
id to a spec does nothing on its own.

## C. Unbuilt from the roadmap

**C1. MCP adapter.** The protocol and the HTTP adapter exist, so this is a second transport over a
settled interface. `RemoteSession` (`control/session.py`) is written against a duck-typed client and
imports `core` only, so an MCP client satisfies it without further work on this side.

**C2. Checkpoint/restart resume.** The ledger records run state and outcomes and `RunService.reattach()`
reconciles what a previous process left open — but nothing *resumes* a campaign from it. Now also the
reasoner's problem: with C5 the reasoner is a separate process that can die and come back, and
`RemoteSession.as_completed` holds a stream cursor it cannot currently persist.

**C3. P5 network-service governor** — caching, per-service concurrency caps, `Retry-After` backoff.

**C4. Cancellation cannot reclaim a running GPU.** Measured, not unknown: queued work is reclaimed,
running work is not, and the backend does not report which happened. Closing this needs cooperative
cancellation inside task agents, or a backend that can kill a process.

**C5. The out-of-process reasoner has no entry points.** `RemoteSession` and the routes it needs
exist and are covered end to end, but only `tests/` ever constructs a `ControlPlaneServer` — there is
no `impress-a serve` (executor side, inside the allocation, holding the plane open) and no
`impress-a reason` (reasoner side, outside it, driving a `RemoteSession`). The split is reachable
from the test suite and not from a shell, which is the state `docs/reference/frontends.md:107-111`
already describes as "implemented".

**C6. `--model C` fails open.** `cli/__init__.py:78-80` builds an `ExternalPolicy` with
`on_timeout="fallback"` and no control plane attached, so its inbox can never be filled: it times out
every 5s and silently runs `ThresholdPolicy` instead. The documented headless mode
(`docs/decisions/0002`) is therefore unreachable from `impress-a run`, and reports a model-D campaign
as a model-C one. It should refuse and point at C5's entry points instead. Blocked on C5.

**C7. Where the control plane is reachable from is undecided.** `docs/reference/frontends.md:110`
offers HTTP+SSE for "a reasoner outside the allocation", but `control/http.py:17-21` is loopback,
single trusted client, no auth, no TLS. Planning question M6
(`planning/phase1-partB-architecture/06-headless-control-protocol.md:115-117`) — where the adapter
process runs relative to the job — was sidestepped rather than answered, and a real split on Delta
needs it settled: the compute node's private interface, or a tunnel, and what the security boundary
then is. Blocked on C5.

**C8. Concurrent Boltz runs can corrupt the shared CCD cache.** `download_boltz2()` checks
`mols.exists()` - presence, not completeness - so a second concurrent lineage skips extraction and
reads a half-populated directory, failing with `CCD component <resname> not found!`. Measured
upstream; their fix holds `flock -x 200` across the whole check-and-repair and writes a
`.mols_complete` marker (`scripts/boltz.sh:15-31`). We run `replicas: 4` against one shared
`$BOLTZ_CACHE`, and `delta_env_setup.sh`'s warm-up is non-fatal, so a partial cache is reachable.

  **RESOLVED, with one deliberate departure.** `_claim_cache` (`tools/boltz_agents.py`) takes an
  exclusive `flock` on an unproven cache and holds it across the prediction - the extraction being
  raced happens *inside* `boltz predict`, so a check-then-release would not close the window - then
  writes `.mols_complete`. Only the first run pays; later lineages take the fast path and predict
  in parallel. The lock is acquired via `asyncio.to_thread`, because a blocking `flock` on the
  event loop would stall the heartbeat the same way Dragon's synchronous `Batch()` did. The
  departure: **we never delete a partial cache**, where upstream repairs by removing and
  re-downloading. Compute nodes have no egress - the reason the warm-up runs on a login node at
  all - so deleting a cache that turned out to be fine would end the campaign with no way back.
  Instead `delta_env_setup.sh` step 11 writes the marker on a *successful* warm-up, and
  `impress-a preflight` now reports an unmarked cache, on the node that can still repair it.
  A genuinely half-extracted cache that reaches a compute node unmarked is therefore caught early
  and loudly rather than silently, but still cannot be repaired there.

**C9. No thread caps; the Rosetta stages oversubscribe.** Upstream sizes from the cgroup -
`sched_getaffinity(0)`, `_omp = max(1, _ncpu // (n_pipelines * 2))` across
`OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS` plus `OMP_WAIT_POLICY=PASSIVE`, explicitly not
`os.cpu_count()` which over-subscribes on any allocation smaller than a whole node
(`run_small_molecule_binding.py:134-143`). We set none, with `replicas: 4` and three CPU-bound P2
stages.

  **RESOLVED.** `_thread_caps` (`cli/__init__.py`) applies upstream's sizing at campaign start.
  Placed there rather than in an adapter because it is the only layer that knows both numbers: a
  `TaskRequest` carries no concurrency information and an agent cannot see how many siblings it
  has. Applied with `setdefault`, so an operator's own export wins - and the log reports the
  *effective* value, not the computed one, so a run is never described as something it is not.
  `run_cmd` passes `env=None`, so every child inherits these without any adapter change.

**C10. `$HOME` leaks into the rfd3 container.** apptainer mounts `$HOME` by default; upstream does
`unset PYTHONPATH PYTHONUSERBASE PYTHONDONTWRITEBYTECODE; export PYTHONNOUSERSITE=1` (set, not
unset) before exec (`scripts/rfd3.sh:19-22`). `run_cmd` passes no `env`, so our container inherits
everything including user site-packages.

  **RESOLVED.** `_container_env()` (`tools/rfd3_agents.py`) strips exactly those three and sets
  `PYTHONNOUSERSITE=1`, passed as `env=` to the `apptainer exec`. Everything else is passed
  through deliberately - `$SCRATCH`, the SLURM and CUDA variables all have to reach the container.
  Pinned by `test_rfd3_does_not_leak_this_pythons_packages_into_the_container`, which also asserts
  an unrelated variable survives, so a future "strip more" does not quietly break the bind.

## D. Registry and spec-contract gaps

All undercut the documented "loading is validating" guarantee.

**D1. `ToolSpec` has no `extra="forbid"`** — pydantic ignores unknown keys, so a typo'd field in a
`spec.yaml` is silently dropped instead of failing at load.

**D2. `entry:` importability is never checked at load time** — only when `agent_for` is first called,
i.e. mid-campaign rather than at registration.

**D3. Entry-point discovery is documented but absent.** `authoring-tools.md` promises
`impress_a.toolkits` entry points; `registry.py` has no `importlib.metadata` call.

**D4. The SKILL.md ↔ spec integrity check is half-built and soft.** "Every tool mentioned must exist"
is not implemented; the forward direction is a naive substring test that appends to `errors` **without
disabling the toolkit**, contradicting the all-or-nothing claim in the same docs.

**D5. `filter_shape` declares no parameters**, so gate 3 rejects any composer-proposed tuning of it.

**D6. No `frozen_parameters` in any real toolkit.** The mechanism the authoring guide calls out as
mattering "as much as `parameters`" is exercised only by `mock_generate`.

**D7. `boltz_predict` is P1 while `use_msa_server: true` makes it egress-dependent.**
`compute-patterns.md` rule 4 says such a tool is P5 even with a local fallback; its own SKILL.md
admits the deviation. The validator therefore never applies P5's failure model to a call that can
fail on the network.

## E. Configuration that exists and does nothing

**E1. `sites/*.yaml` is read by no code** — both files say so in their own comments. Its
`tool_delivery: {real|mock}` switch is exactly what would have prevented the mock-chain-on-a-GPU bug.

**E2. Cost models are unmeasured literature guesses**, and gate 5 plus the interlock's 10% cap refuse
graphs against them. Already concrete: the smoke campaign's original budget rejected its own first
run. Early campaigns should record actual-vs-estimated per tool.

## F. Documentation debt

**F1. No ADR records the decoupling** — the largest architectural change in the repo, including the
`on_rejected` scope change (per-cycle → per-experiment, now enforced in two places) and the rebuttal
to `planning/phase3-prior-art/04-patterns-for-phase4.md:41`. Now also owes the process boundary: that
`CampaignSession` is the split, that a second `WorkflowEngine` or a second event loop is *not* (an
engine is bound to its creating loop), and that `interpret` belongs to whoever collects the outcome —
it moved from `CampaignExecutor._reap` to `SequentialPolicyDriver._collect`, which removed the
executor's only call into the reasoner.

**F2. ADRs 0003, 0005, 0007 unamended** — the interlock's per-signature concurrency rule; ADR 0005's
"fixed at launch" now needing the reattach policy-identity check that `RunService` provides but
nothing enforces; ADR 0007's per-client cursor. ADR 0007 also now owes the five operations added to
`CampaignControlPlane` for the remote session (`status`, `inflight`, `backtrack`, `request_human`,
`await_run_result`) and the two widened signatures (`observe(since=)`, `events(stream=)`).

**F4. `docs/reference/` has no record of the remote session** — neither `RemoteSession` nor the routes
it needs appear in `frontends.md` or `architecture.md`, and `limitations.md` does not mention that a
`conduct` policy collecting for itself must now call `interpret` for itself.

**F3. `planning/phase2-middleware/05-integration-map.md:60`** still claims there is no way to
enumerate the tasks of a run. Softened, not false: `workflow_id` tagging exists in asyncflow 0.5.1,
but no lookup API does.

## G. Engine semantics

**G1. Exploration cannot move the front, so it counts toward stagnation.** Nodes from the explore
chain (`rfd3 → ligandmpnn → boltz`) have no Rosetta metrics, so `pareto.feasible` rejects them against
`shape_complementarity ≥ 0.55`. Every informed explore landing then increments the stagnation
counter. With the shipped `stagnation_limit: 4`, a modeled campaign stops at t≈135 min, before the
first exploit run lands (`slides/timeline_model.py --limit 4`). This is latent, because no shipped
policy emits that chain yet. Raising the limit is the wrong fix. Stub:
[`exploration-vs-stagnation.md`](exploration-vs-stagnation.md).

**G2. rfd3 output parsing ignores the metrics rfd3 reports.** See B1 and A4. Switching
`RFD3DesignAgent` to read the sidecar `*_model_*.json` would give a genuine structural gate
(`ligand_clashes == 0`), replace our non-DSSP phi/psi estimate with rfd3's own `helix_fraction`/
`sheet_fraction`, and let us select the *best* model rather than `cif_models[0]`. Deferred
deliberately until a real run shows what an `out_dir` actually contains - it changes what the gates
measure, and A1 is still open.

**G3. `dump_trajectories=True` writes 99.4% waste.** Upstream measured trajectories at 11.85 MB of
each 11.92 MB rfd3 output dir and flipped it to False (`0800ad8`), taking a campaign from ~30 GB to
~3.8 GB. Safe because trajectory files ship no `.json`. We never read them.

  **RESOLVED** - flipped to `False` (`tools/rfd3_agents.py`) and asserted in the Hydra-contract
  test. It was held back only to be decided alongside G2; on inspection they are independent.
  G2 changes *which* file the agent reads for its metrics, while this changes whether a file
  nothing reads is written at all, so flipping it early costs G2 nothing.

**G4. The fastrelax gates are far looser than upstream's calibrated ones.** Ours:
`total_score max: 0.0`, `fa_rep max: 500.0`, no `interaction_energy` at all. Upstream PROD:
`total_score < -250.0`, `fa_rep < 100.0`, `interaction_energy < -8.0`. `interaction_energy` is the
one that actually measures binding and our worker does not compute it (`rosetta_agents.py:88-91`).
`toolkits/rosetta/SKILL.md` already admits these are uncalibrated.

**G5. `filter_shape` may be measuring the wrong interface.** Ours hardcodes
`<ShapeComplementarity name="sc" jump="1"/>` with the default scorefunction
(`rosetta_agents.py:104`); upstream uses explicit chain selectors (`residue_selector1="chainA"`,
`residue_selector2="chainB"`) under `beta_nov16`. `jump="1"` assumes a particular chain/jump
arrangement in the relaxed pose - if the ligand is not across jump 1 the gate is meaningless
rather than obviously wrong.

**G6. A worker exception that cannot be unpickled hangs the run.** Measured on job 22536706:
ligandmpnn failed and `run_cmd` raised `SubprocessError`. Dragon pickles a worker's exception into
its results DDict, but `SubprocessError`'s `args` held only the message, so unpickling failed. In
rhapsody's `DragonExecutionBackend._monitor_loop`, `batch_task.get()` is guarded, but the
follow-up `get_stdout(block=False)` re-reads the same entry and catches only `OSError`. The
error goes to the outer handler (`Critical error in monitor loop`) and **that whole sweep's
completions are dropped**. No FAILED is ever delivered, so the run stays `inflight=1` until walltime.
The LigandMPNN stderr, the actual failure, was lost with it.

  **Our half RESOLVED:** `SubprocessError.__reduce__`, pinned by
  `test_real_toolkits.py::test_subprocess_error_survives_the_worker_boundary`. It is the only
  custom exception raised inside a worker. **Still open:** rhapsody should catch `Exception`
  around `get_stdout`/`get_stderr` and fail the one task instead of the sweep. That is an upstream
  report, not a vendored patch. We have no per-run wall-clock bound that would catch the hang
  either, so any third-party exception with the same shape (a required-arg `__init__` that does
  not forward those args to `super()`) reproduces it.

---

## Recommended order

This order was written at the stagnation fix, before C8-C10 and G2-G5 existed. Two things it got
wrong, corrected here: **B1 partly depended on its own item 2** (B1's cheapest form is G2, which is
deferred until a real run shows what an `out_dir` contains — whereas B2 needed nothing, since every
gate takes a plain dict), and **the pre-run hazards were unranked** although they would have been
paid for out of the first allocation.

1. ~~**B2 known-bad fixtures**~~ — **DONE.** Every real tool now carries them, with a guard test
   that fails when a tool has none. B1's structural gates remain open and follow G2.
2. ~~**C8, C9, C10, G3 the pre-run hazards**~~ — **DONE.** Code-only, no allocation needed, and
   each would have corrupted or wasted the first `replicas: 4` run.
3. **A1-A3 the first real run** — needs a person, and everything else is speculation until it happens.
4. **D1-D4 registry hardening** — small, self-contained, restores "loading is validating".
5. **F1-F4 docs** — cheap, and the absent ADR is the one a future reader will most want.
6. **C5-C7 the reasoner's entry points** — the transport is built and tested; without these
   it can only be reached from `tests/`, and `--model C` keeps reporting a model-D campaign.
7. **B1 structural gates and G2/G4/G5** — all four wait on the first real run, which is what
   tells us what rfd3 actually writes and what the Rosetta numbers actually look like.
8. **C1-C3** on demand; **C4** only if a real campaign shows abandoned runs holding GPUs.
9. **G1** before any `conduct()` reasoner that explores with a truncated chain ships. Latent until
   then, and now pinned by two characterization tests that must change when it is decided.

## Verification that applies to any item

`pytest tests -q` green, no allocation. `ruff check src tests` **must not exceed 41** — the one
number worth stating, and a budget that drifts upward is the thing you want to notice. The import
contract is asserted by `tests/test_layering.py` rather than checked by eye. `impress-a run campaigns/mock-stabilize.yaml --model D` and
`--model A` still terminate with a stated reason and a non-empty front, and
`impress-a run campaigns/delta-small-molecule-smoke.yaml --model D` must compose `rfd3_design…`,
never `mock_generate…`.
