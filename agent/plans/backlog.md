# Backlog

Everything outstanding. Each item says why it matters so the list can be triaged rather than
worked through top to bottom. Items resolved since the list was written carry a **RESOLVED**
paragraph in place rather than being deleted - the evidence that forced them is the useful part.

State it is measured against: local tier green, lint reporting nothing, the import contract clean **and
now asserted** (`tests/test_layering.py`), all control models
run, the real Delta chain composes, dry-runs, and passes `impress-a preflight` for the ALR target
on Delta. **One campaign has completed:** job 22692304 ran all six stages to `6/6 tasks ok`
in 2m53s, admitted on the first attempt, every gate passing, terminating with a one-node front and
all four objectives valued. One lineage, one cycle, one draw - see A1 for what that does not cover.

---

## A. Blocked on a person, not on code

**A1. No real campaign has ever completed — RESOLVED by job 22692304** (see the ruling at the end of this entry). The history that got there, in order. Job 22536706
(`delta-small-molecule-smoke`, model D, one lineage) reached Delta on 2026-09-29:

- `rfd3_design` **executed and succeeded** - roughly 3 minutes wall-clock, real output in
  `impress_a_runs/22536706/work/rfd3_r0001_r0_s0_rfd3_design/` (no longer retained: the archived
  `22536706_delta-small-molecule-smoke/` keeps logs and provenance only). The Hydra contract rewrite (A3) is
  confirmed against the real CLI by execution, not by reading. The output shape is confirmed too
  (A4) - and reading it found a real defect in our own adapter, below.
- `ligandmpnn_design` **failed**, having written nothing into its work dir. *Why* is unknown and
  probably unrecoverable: its stderr was lost with the monitor-loop sweep that G6 describes.
- The campaign then hung at `inflight=1` until the allocation ended. `jobs/ledger.jsonl` holds
  `campaign_started` and r0001 `submitted` with no terminal record - the shape G6 predicts.

So: one stage proven, one stage failed for reasons we destroyed, nothing downstream touched, and no
front, no measurement and no ledger outcome. A repeat run with the G6 fix in place is the next thing
that moves this item, and it should now surface the real LigandMPNN error instead of hanging.

  **The repeat run happened: job 22669509, 2026-10-04, and it did exactly that.** `rfd3_design`
  succeeded again and this time selected the right file (A4's fix: `backbone_0.pdb` 53,784 B from
  the sidecar-identified `*_model_0.cif.gz`, against the multi-MB trajectory of the first run).
  `ligandmpnn_design` reached `FAILED` with its full stderr attached - no `Critical error in monitor
  loop`, no hang - and the campaign terminated on `max_cycles=1` with Dragon shutting down in 1.5s.
  The ledger carries a `failed` outcome with a complete payload: QC gates, metrics
  (`ss_fraction` 0.847, `num_models` 1), cost (0.25 GPU-h against a 0.5 estimate) and the artifact's
  sha256. Both the G6 and A4 fixes are therefore confirmed by execution, not just by test.

  Still one stage. LigandMPNN's recovered stderr showed it cannot import at all here (A6), so
  `packmin` onwards remain untouched and this item does not move.

  **RESOLVED by job 22692304.** All six stages ran (`6/6 tasks ok`, 2m53s), admitted on the first
  attempt with `rejected: None`, every stage passing its gates, terminating `front:
  ["n000001-4101"]`. Node metrics: `ss_fraction` 0.827, `overall_confidence` 0.448,
  `ligand_confidence` 0.424, `total_score` -272.0, `fa_rep` 109.4, `shape_complementarity` 0.591,
  `complex_plddt` 0.507, `ligand_iptm` 0.752. The ledger carries a `done` outcome and per-tool cost
  for all six tools.

  **Read it as a floor.** One lineage, one cycle, one draw. The node is `suspect` rather than
  `pass` because the pattern is provisional (`executor.py:245`), which is the interlock working.
  What this run does NOT cover, and what should replace this item on the list: `replicas > 1` has
  never run (A10); and no measurement has superseded a prediction, so calibration is untested.
  (Promotion has since happened: job 22726105, see A12.)

  **C11 provenance:** the evidence above is jobs 22536706, 22669509, 22692304, 22726105, which ran
  the `/work/hdd` checkout rather than this one. The measurements stand as measurements; what they
  cannot be read as is evidence about *this* code. See C11.

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

  **C11 provenance:** the evidence above is job 22318678, which ran the `/work/hdd` checkout
  rather than this one. The measurements stand as measurements; what they cannot be read as is
  evidence about *this* code. See C11.

**A4. The rfd3_design rewrite needs a real smoke-run confirmation.** The Hydra contract and
`DesignInputSpecification` JSON shape are verified against the installed `rfd3` CLI's own source,
but the output-parsing half of `RFD3DesignAgent` (glob for `*.cif.gz`, convert via `cif_gz_to_pdb`)
was not re-verified against a real `out_dir` listing - confirm the exact output filenames on the
first real smoke run (`dump_prediction_metadata_json`/`output_full_json` are both `True` by
default, so this should be visible immediately). **Largely answered by the reference pipeline**,
which discovers candidates as `*.json` containing `_model_` and derives the structure by
`.replace('.json', '.cif.gz')` - so the shape is `*_model_*.cif.gz` alongside `*_model_*.json`. Our
glob finds the structures; confirm on the first real run, and see G2 for using the JSON we discard.

  **RESOLVED, and it was not finding them.** Job 22536706's `out_dir`, in full:

  | file | size | sidecar JSON |
  |---|---|---|
  | `ALR_binder_design_partial_0_denoised_model_0.cif.gz` | 1.7 MB | no - trajectory |
  | `ALR_binder_design_partial_0_model_0.cif.gz` | **19 KB** | **yes - the design** |
  | `ALR_binder_design_partial_0_noisy_model_0.cif.gz` | 1.6 MB | no - trajectory |

  Trajectories are `.cif.gz` as well, and `denoised` sorts **before** the design's own name. So
  `sorted(work.glob("*.cif.gz"))[0]` took a multi-frame trajectory, converted it, measured
  `ss_fraction` on the stack and handed it to LigandMPNN as the backbone - the 5.7 MB
  `backbone_0.pdb` in that directory, against a 19 KB design. A candidate for what killed
  LigandMPNN, though the stderr that would prove it is gone (G6).

  **It was not what killed LigandMPNN.** Job 22669509 handed it the correct 53 KB backbone and
  LigandMPNN still failed, at import, for a wholly unrelated reason (A6). Worth keeping as a note on
  how this reasoning went: the trajectory was a real defect *and* a plausible explanation for a
  failure it had nothing to do with, and the only thing that separated the two was recovering the
  actual stderr. A plausible cause in hand is what stops you looking for the real one.

  Note what this says about G3: `dump_trajectories=False` makes the bug *unreachable* on current
  code, because those two files are never written. It was flipped for footprint, and it silently
  fixed a correctness defect nobody had found - which is the argument for not letting one flag's
  default carry another decision's correctness. Selection now goes through the sidecar JSON
  (`*_model_*.json` → `.cif.gz`, the reference pipeline's own rule), so it holds either way, and an
  `out_dir` of structures with no metadata raises instead of guessing. Pinned by
  `test_rfd3_never_hands_downstream_a_trajectory` and
  `test_rfd3_refuses_an_out_dir_it_cannot_identify_a_design_in`.

  **C11 provenance:** the evidence above is jobs 22536706, 22669509, which ran the `/work/hdd`
  checkout rather than this one. The measurements stand as measurements; what they cannot be read
  as is evidence about *this* code. See C11.

**A6. LigandMPNN cannot import under this venv's numpy — RESOLVED in code, unexecuted.** Job
22669509's recovered stderr: `run.py` dies in its **module-level imports**, before parsing an
argument, so no flag, path or checkpoint we pass is ever read. Two independent holes, hit in
sequence:

- `openfold/config.py` does `import ml_collections`, which was not installed. It is in LigandMPNN's
  own `requirements.txt` alongside `dm-tree`; `dm-tree` arrived incidentally via Boltz's step 5, so
  `ml_collections` was the single omission from `delta_env_setup.sh` step 6.
- With that installed, `openfold/np/residue_constants.py:1124` does `np.zeros(..., dtype=np.int)`.
  numpy removed `np.int` in 1.24. LigandMPNN pins numpy 1.23.5; this venv carries 2.5.3 because
  Boltz and the rest of the stack require it, so pinning down is not available to us.

**RESOLVED.** `ml-collections` added to step 6 (with an import check, and the weak
`_check "LigandMPNN" test -d` widened to assert `run.py` and both checkpoints). For the aliases, the
adapter no longer runs `run.py` directly: `MPNN_SHIM` (`tools/ligandmpnn_agents.py`) is written into
the task workdir and run with `sys.executable`, restoring the aliases before handing off via `runpy`
with `run_name="__main__"`. Same device as the reference pipeline's `scripts/mpnn_run.py`, and the
same device as `rosetta_agents.py`'s `_*_WORKER` constants. Pinned by
`test_ligandmpnn_runs_run_py_through_the_numpy_alias_shim` and
`test_the_mpnn_shim_restores_the_aliases_openfold_needs`, the latter hermetic - a fake checkout, no
torch, no GPU. Verified against the real checkout on a login node before resubmitting.

**A third hole, found while fixing the first two, and the one that would have cost the next
allocation.** `ligandmpnn_design` declared `walltime_s: 300`. Job 22669509's own log says
`task.000002` went RUNNING at 23:09:51 and FAILED at 23:14:27 - **276s to reach a
`ModuleNotFoundError`**, before one tensor was allocated. Roughly 280s of that is `import torch`
paging 1.6 GB of shared objects off Lustre (measured again on a login node: ~360s wall for 9s of
CPU). So fixing the imports alone would have produced `timed out after 300s` on the next run -
indistinguishable from a hang, attributed to LigandMPNN rather than to the number, and paid for out
of an allocation. `walltime_s` is now 1800 and `cost_model.gpu_hours` 0.1 → 0.25, both with the
measurement in the spec, and pinned by `test_ligandmpnn_walltime_covers_the_measured_import_cost`.

  Worth generalising: the import cost was sitting in plain sight in the log of the run we had
  already diagnosed. The failure we were looking for made the number next to it invisible. Every
  remaining stage's `walltime_s` is still a literature guess, and the first thing each one's real
  run will produce is the true figure - `rfd3_design`'s is now known (0.25 GPU-h against a 0.5
  estimate), the other four are not.

**Still open, and it is the part worth reading.** Both holes were knowable on a login node in
seconds, and both were found inside a GPU allocation after a queue wait. `impress-a preflight` now
runs the real import chain through the same shim (`--help`, which exercises every module-level
import and then exits 0 because `run.py` does its work under a `__main__` guard), and gained an
**undetermined** state so a probe that times out reports `warn` instead of `FAIL` - two meaningless
FAILs train a reader to ignore the column. But **no launcher invokes preflight**: not
`delta_gpu_run.sh`, not `delta_run_campaign.py`. It is operator-run and gates nothing by itself.
Making the launcher run it, and failing the job early when it reports a real FAIL, is the open item.

Note also what this says about where the remaining risk lives. Three stages have now been fixed
before execution (A3's Hydra contract) or by execution (A4's selection, A6's imports), and the two
found *by* execution were both things a contract check cannot see: what a tool writes, and whether it
can import. Expect the same shape from `packmin`, `fastrelax`, `filter_shape` and `boltz_predict` —
their arguments are checked, their environments are not.

**A6 RESOLVED by execution.** Job 22684607: `ligandmpnn_design` ran in 18.1s and passed its gates
(`overall_confidence` 0.525, `ligand_confidence` 0.496). `MPNN_SHIM` and the pinned `ml-collections`
both hold on real hardware.

**A6b. The batch-flags probe bypassed the shim and blamed LigandMPNN for it.** **RESOLVED**
(2026-11-08), found by running the deep preflight on a login node before the smoke - which is
the first time it had been run since the probe was added.

`preflight` carried two probes of one binary. The imports probe ran `run.py --help` through
`MPNN_SHIM`; the batch-flags probe, three lines below, ran `run.py` **directly** - which is the
one thing A6 above establishes you cannot do, since the vendored openfold dies on `np.int`,
removed in numpy 1.24. The traceback landed on stderr, so `helptext` was non-empty, neither
flag appeared in it, and the probe reported `installed run.py does not offer --batch_size,
--number_of_batches - the adapter passes them and would fail inside the job`. Both flags are
declared at `run.py:846,852` and the adapter is right to pass them.

So the deep preflight returned `12/14 ok` with two FAILs on a correct environment, one of them
pointing at the wrong component, on a run whose §10 gate is **0 FAIL**. A reader following the
message would have gone looking at LigandMPNN's version. The neighbouring row said `ligandmpnn
imports [ok] run.py --help exited 0 in 15s` at the same moment - two probes of one binary
disagreeing, with no way to tell from the output which to believe.

One shim invocation serves both checks now, which also halves the deep probe's cost, and a
non-zero exit is **undetermined** rather than a missing flag: a program that did not reach its
argument parser has said nothing about its arguments. Re-run clean: **14/14 ok, exit 0**, with
`--batch_size and --number_of_batches both offered`. Pinned by
`tests/test_toolchain.py::test_the_batch_flag_probe_goes_through_the_shim_and_abstains_on_a_
crash`, confirmed to fail against the old probe on the invocation itself.

The general lesson is A4's, from inside the tool written to prevent it: *the probe must run
what the job runs*. A second thing worth keeping - the other FAIL in that same output,
`boltz not on PATH`, was an artefact of invoking `.venv/bin/impress-a` without activating the
venv. Real on its face, caused by the harness. The launcher activates, so it never sees it.

  **C11 provenance:** the evidence above is jobs 22669509, 22684607, which ran the `/work/hdd`
  checkout rather than this one. The measurements stand as measurements; what they cannot be read
  as is evidence about *this* code. See C11.

**A7. `boltz_predict` has never executed, and a budget correction is why — RESOLVED.** Not a tool failure. The
`cost_model` figures were literature guesses 6-69x over measurement; the gpu side summed to 0.65
against the untrusted-pattern cap of 0.60 (10% of a 6.0 budget), the chain was refused three times,
and `ThresholdPolicy.on_rejected` truncated the last stage off (`policy/explicit.py`, `stages[:-1]`).
`boltz_predict` is last for a documented scientific reason and is the only producer of
`complex_plddt` and `ligand_iptm` - two of the campaign's four objectives, both with `min:` bounds,
so a missing value is a constraint violation and no node from that graph can reach the front. The
run was unwinnable from the moment it was admitted and nothing said so.

  **Costs corrected** from job 22684607's measurements (rfd3 0.25→0.10, ligandmpnn 0.25→0.02,
  packmin 0.2→0.02, fastrelax 0.5→0.03, filter_shape 0.05→0.01), and the six-stage estimate is now
  gpu 0.27 / cpu 0.06 against caps of 0.60 / 1.00 - admitted on the first attempt, verified by
  simulating the real admission path. The budget itself is untouched: raising it to accommodate a
  wrong number would have hidden the defect.

  **RESOLVED.** Job 22692304: `boltz_predict` executed for the first time in 57.8s, passed both
  gates and produced `complex_plddt` 0.507 and `ligand_iptm` 0.752 - the two objectives that had
  never had a producer in a completed graph. Its own cost model was the last literature guess
  standing (0.15 against 0.0160 measured, 9.3x) and is now 0.05.

  **C11 provenance:** the evidence above is jobs 22684607, 22692304, which ran the `/work/hdd`
  checkout rather than this one. The measurements stand as measurements; what they cannot be read
  as is evidence about *this* code. See C11.

**A8. Nothing checks that an admitted graph can produce the campaign's objectives.** `grep -rn
"objective" src/impress_a/compose` returns nothing - the composer and validator never receive them.
A terminal-metrics gate was specified in
`planning/phase1-partB-architecture/05-graph-composition-and-validation.md:66` and never built.

  **Half-resolved.** `runtime/executor._objectives_without_a_producer` now WARNs and records
  `unproducible_objectives` in `graphs` provenance, and `on_rejected` logs the stage it drops.
  Both are warn-and-proceed. The warning is a **heuristic**: `ToolSpec` has no `metrics:` field, so
  producible metrics were inferred from each spec's `metric_in_range` gate params, and a tool
  that emits a metric it does not gate read as a non-producer.

  **That inference was wrong in practice, not just in theory.** It warned on `mock-stabilize`
  that the graph could not produce `ddg`, `iptm` or `sc_rmsd` while that same run returned a
  four-node front carrying all three - the mock tools emit them and gate on none. A warning that
  fires on a healthy campaign is noise. `ToolSpec.metrics` is now declared by all eleven tools
  and is the source of truth, with gate metrics unioned in so a drifting declaration still gets
  caught; `test_every_tool_declares_the_metrics_it_reports` enforces both halves. **Still open:**
  this is a warning, not a gate.

**RESOLVED on the Stage path** (phase 3 of `control-plane-refactor.md`). `submit_stage` refuses a
graph that no tool in it reports a declared objective for, with `gate="coverage"` and the metric
named, and `StageReviewer` additionally refuses a Stage that leaves a *ready* objective neither
planned nor deferred, a task that serves only DELETED objectives, and a task naming an objective
absent from the applied Spec. The terminal-metrics gate specified in
`planning/phase1-partB-architecture/05-...:66` therefore exists, five years of intent later.

Two deliberate limits. The coverage check reads the **executor's applied Spec**, never the
Stage's own claim about what is open - not trusting that claim is the Reviewer's whole purpose,
and it is why the Spec keeps one writer on the execution side so a remote Planner in phase 7
cannot smuggle a revision in with a Stage. And the legacy `submit` **keeps its warning**: that
leaves the old path's behaviour unchanged, including
`test_a_truncated_chain_does_not_count_toward_stagnation`, which runs a sub-chain on purpose.
The two paths differ here by design, and phase 11 deletes the warning with the path.

**A9. Three of four admission attempts are wasted, and the fourth is the last one.** `ThresholdPolicy.
decide` asks for `base_replicas + 1 = 3` replicas, but the campaign's `replicas: 1` is applied
downstream as an executor cap (`executor._apply_campaign_defaults`), so the policy never sees it.
On job 22675512 attempts 1-3 shrank replicas 3→2→1 while composing **identical** graphs - same
signature, same estimate, same rejection - and only attempt 4 reached the stage-dropping branch.
`max_attempts` is 4: one more rejection and the campaign would have run nothing at all. The policy
should see the effective replica count.

  **C11 provenance:** the evidence above is job 22675512, which ran the `/work/hdd` checkout
  rather than this one. The measurements stand as measurements; what they cannot be read as is
  evidence about *this* code. See C11.

**A10. `replicas > 1` has never executed.** `plans/first-real-run.md` calls the four-lineage
independence check the invariant most likely to be silently wrong: `replicas: N` must produce N
`DesignNode`s carrying DIFFERENT metrics, which is the only evidence the per-lineage seed plumbing
does anything. Every real run so far has been `replicas: 1`.

  **It does not currently fit, and that is worth knowing before an allocation is spent on it.**
  Simulated against the real admission path: `replicas: 4` composes 24 nodes at **0.68 gpu-h**
  against the untrusted cap of 0.60 - rejected, and `on_rejected` would then shrink replicas
  4 → 3 → 2 and admit *three* lineages, quietly turning the four-lineage independence check into
  a three-lineage one. The check would still be meaningful but it would not be the check that was
  asked for, and nothing in the log would say so except the new correction warning.

  Three ways out, in preference order. **(a) Earn trust first:** three consecutive clean runs
  promote the pattern (`TrustLedger.promote_after`), and a trusted pattern bypasses the cap
  entirely - `max_cycles: 1` means that is three smoke campaigns, which are now ~3 minutes each.
  This is the path the interlock was designed for and it costs almost nothing. **(b)** Raise
  `budget.gpu_hours` for a replicas-4 campaign specifically (8.0 gives a 0.80 cap). **(c)** Run
  `replicas: 2` (0.34, fits today) and accept a weaker version of the check.

  **Correction (2026-10-07): route (a) does not work.** The pattern signature includes replica
  multiplicity (`f5b21d82…` at 1, `f8bcefed…` at 2, `78e730c6…` at 4), so trust earned at
  width 1 does not transfer, and width 4 can never be admitted untrusted at a 6.0 GPU-h budget,
  so it can never earn trust there either. Width 4 needs route (b), or a deliberate ruling on
  whether multiplicity belongs in the signature.

  **Annotation (2026-11-09): the *Trust* half below is incomplete rather than wrong.**
  `--replicas 1 --replicas 4` presumes every arm composes the same width, and on array 23680876
  they did not: A, B and C composed 4 and model D composed 2, so D's `f8bcefed…` was in no
  arm's ledger and D alone ran three cycles untrusted. The remedy here made width 4 *runnable*;
  it does not make the arms *comparable*. See **G13** and
  [replica-width-confound](replica-width-confound.md). The budget and pinning halves are
  unaffected. Separately, concurrent GPU tasks are not pinned:
  every task sees `CUDA_VISIBLE_DEVICES=0,1,2,3`, and `exec/resources.to_backend_description` is
  called by nothing. `plans/next-run-replicas.md` pins lineages to GPUs before running width 2.

**HALF-RESOLVED** (phases 3a and 6 of `control-plane-refactor.md`). The budget half and the
pinning half were separate problems and are addressed separately.

*Trust.* Asserting trust is now possible and is how a width-4 pattern becomes runnable:
`impress-a trust --assert <spec> --replicas 1 --replicas 4` computes the signature at each
width, because the signature includes replica multiplicity and so width 1 does not cover
width 4. That is this item's route (a) made available rather than impossible - earning trust at
width 4 still cannot happen under a realistic budget, and now does not have to.

*Pinning.* `exec/resources.to_backend_description` has a sibling with a caller:
`Dispatcher._gpu_for(lineage)` assigns one device per lineage, round-robin across
`SiteCaps.gpus_per_node`, and `TaskRequest.gpu_index` carries it to the adapter. `gpu_env`
returns `CUDA_VISIBLE_DEVICES` for a concurrent backend and **nothing for Dragon**, because
local services merges a template's env and applies the placement policy afterwards - so an env
var there looks like pinning and does nothing, and Dragon needs
`Policy(gpu_affinity=[gpu_index])` on the process template instead.

*Pinning, completed in phase 9.* The adapters now apply it, and two things changed on the way.
The assignment is no longer the adapter's to interpret: `exec/dispatch.node_task` resolves it to
an environment where the backend is known and puts the result on `TaskRequest.gpu_env`, which an
adapter merges through `_subprocess.child_env(req)` without asking which case it is in. An adapter
deciding for itself would have to know its backend, and setting `CUDA_VISIBLE_DEVICES=2` inside a
process Dragon had already restricted to one device points it at a device it was never given. And
the **Runner path had no pinning at all** - `StagePipeline` registered every task without a
`gpu_index`, so this item was fixed on the Dispatcher and reintroduced by omission on the path a
Delta campaign selects with `runner: impress`. `gpu_for` is now shared by both loops, for the same
reason `node_task` is.

**Still open:** `replicas > 1` has still never executed on hardware. Nothing here has seen a GPU,
so the pinning is asserted against the factory's own arguments and not against `nvidia-smi`.

**A11. Wall time varies 3.2x between identical runs, and the cost models are single samples.**
`rfd3_design` took 145.7s in job 22684607 and 45.0s in 22692304 - same campaign, same allocation
shape, same parameters. Every `cost_model` figure now in the specs comes from one or two
observations. This is not a reason to revert to literature guesses, which were 6-69x out; it is a
reason the declared figures deliberately sit ~3-5x above measurement and must not be tightened
toward equality. These numbers feed gate 5 and the untrusted-pattern cap, both of which REFUSE
graphs, so erring low is how a campaign starts getting rejected for no real reason. Recalibrate
from a distribution once several runs exist, and treat a single fast run as the least trustworthy
input. Pinned by `test_cost_models_are_within_an_order_of_magnitude_of_measurement`, which asserts
a band rather than a value for exactly this reason.

  **Now a distribution (2026-10-08, `performance_analysis` C1/C2):** 101 timed tasks over 5 jobs.
  Every declared figure is ≥2.25x the *worst* observed task, so no observed draw would have been
  refused. The 3.2x swing is one outlier: rfd3 is 40-45s in **15** of its 17 tasks (the other two
  are 48.0s and 145.7s, the latter only in 22684607). Each job's first run is slower on four
  stages (ligandmpnn +8.6s, packmin +10.5s, Boltz +7.8s, rfd3 +4.3s), which looks like warm-up.
  Measured GPU per six-stage chain is 0.029 GPU-h (median) against 0.17 declared. At p90 x 3 the
  chain would be 0.105, which admits **5** untrusted lineages under the 0.60 cap instead of 3. Not
  applied: changing the specs changes what admission refuses, so that is a decision, not a cleanup.

  **Reproduced off-cluster (2026-10-09)** from `impress_a_runs_2026-10-08.tar.gz` alone, on this
  laptop, at the same commit: every figure above holds to the digit except the 16-of-17, corrected
  here. So these are archive-derived, not Delta-session-derived - the distinction G9 is about.

  **C11 provenance:** the evidence above is jobs 22684607, 22692304, which ran the `/work/hdd`
  checkout rather than this one. The measurements stand as measurements; what they cannot be read
  as is evidence about *this* code. See C11.

**A12. The trust ledger reset every job, so promotion was unreachable on Delta — RESOLVED.**
`executor.py` loaded it from `Path(spec.root) / "_trust"`, and `spec.root` defaults to the
*relative* `campaigns/_runs`. `delta_gpu_run.sh` cds into `$WORK_DIR/impress_a_runs/$SLURM_JOB_ID`
before launching, so that path resolved inside each job's own directory. On disk after two real
runs: `22684607/campaigns/_runs/_trust/cuda.jsonl` with 0 clean events and
`22692304/.../cuda.jsonl` with 1. Two files, `promote_after=3` counting within one file.

  This was structural, not a shortfall of runs - it had been true since the first Delta job, so
  **the trusted code path has never executed**: no pattern has ever skipped the forced dry-run,
  and `provisional_budget_fraction` has applied to every graph ever composed on real hardware.
  That cap is exactly what truncated `boltz_predict` off the chain twice (A7). Worth noting how
  it hid: nothing ever logged where the ledger was, so a file that silently reset looked
  identical to one that had not earned promotion yet - and I reported it that way.

  **RESOLVED.** `CampaignSpec.trust_root` (new), filled by `cli.load_spec` from
  `$IMPRESS_A_TRUST_DIR`, which `delta_gpu_run.sh` exports as `${WORK_DIR}/_trust`. The relative
  default is unchanged for the laptop tier, where CWD is stable. Campaign start now logs the
  absolute ledger path with a pattern/trusted count. Pinned by
  `test_trust_survives_a_campaign_running_from_a_different_directory`, which builds executors
  from three different CWDs and asserts promotion - it fails on the old code. Verified end to
  end: two runs from different directories reported `0 patterns known, 0 trusted` then
  `2 patterns known, 1 trusted`.

  **Promotion on Delta - DONE, with two follow-ups.** Job 22702568 (6 cycles) promoted nothing,
  but not because of the ledger: every reset was a quality threshold, which decision 0013 stopped
  counting against trust. Job 22726105 then promoted after r0002 and ran r0003-r0004 **trusted** -
  the first time that path executed. r0004 was demoted by packmin's `total_score <= 1000`
  integrity bound over +1064.5, a pose that relaxed normally to -336.0; the bound was removed and
  fastrelax convergence now judges an exploded pose (see `toolkits/rosetta/SKILL.md`).
  **Sustained trust - DONE.** Job 22728140 promoted after r0002 and ran r0003-r0005 trusted, with
  no demotion and no integrity failure (it asked for 6 cycles and got 5, because of a driver
  off-by-one that has since been fixed). **Still open:** the first node to reach plain `pass`. All
  five trusted nodes so far missed an acceptance threshold, at a ~31% acceptance rate, so this
  wants more trusted draws, not code. `plans/next-run-sustained-trust.md`.

**G2b / G5b / A11b. What `validate-tasks` found on real hardware (job 23670171).**
**RESOLVED in code 2026-11-08, re-run pending.** The first per-Task validation this project
has run. Three tools failed integrity rows; two passed clean (`ligandmpnn_design` 9/9,
`packmin` 9/9). None of the three was visible to a dry run, and none was introduced by the
deployment work - they were waiting.

**G2b. `rfd3_design` declared two metrics it never reported** - `ca_deviation`,
`ligand_clashes` - failing `metrics_declared_and_finite`. The spec said this would happen:
"the key names are inferred rather than observed ... the gates land when one real out_dir
confirms the names". This is that out_dir. Of four guesses, two were right
(`helix_fraction`, `sheet_fraction`, both reported fine) and two wrong:

    ca_deviation    -> metrics.max_ca_deviation            wrong NAME; it is a max, not a mean
    ligand_clashes  -> metrics.n_clashing.ligand_clashes   right name, wrong DEPTH

**The second of those was then misdiagnosed, and the re-run caught it.** The dot is part
of the key: `metrics` is a FLAT dict holding the literal key `"n_clashing.ligand_clashes"`,
and there is no `n_clashing` object. It was first read as two levels of nesting and "fixed"
by making the flattener descend twice - which job 23670891 duly failed, still missing
`ligand_clashes` while `ca_deviation` now came back fine.

The cause of the misreading is worth keeping: the diagnostic was a recursive key-printer that
joins nested keys with dots, so it renders `{"a": {"b": 1}}` and `{"a.b": 1}` identically. It
could not answer the question it was being asked, and nothing about its output said so.
Settled by printing `list(metrics)` instead. The speculative two-level descent was removed
rather than left in as insurance - an unexercised branch written against a shape nobody has
seen is the same guesswork that put the wrong names in this file to begin with - and the
regression test is built from `list(metrics)` on the real file, so a nested fixture cannot
make it pass again. `max_ca_deviation` being a maximum matters for anything that later gates
on it.

**G5b. `filter_shape` could not run at all.** PyRosetta rejected the RosettaScripts XML:
`Element 'ResidueProperty': This element is not expected`. 0 of 1 rows, and the chain stopped
there - `boltz_predict` was never reached, which is why it also shows 0/1. The adapter refused
loudly rather than falling back to a jump or chain split, which is the behaviour the port was
built to have and the reason this is a clean diagnosis rather than a plausible wrong number.

Its own comment had named the gap exactly: "this XML is the one part of the port that no local
test can exercise". The filter is now built through the **Python API** -
`ResiduePropertySelector(LIGAND)`, `NotResidueSelector`, `selector1`/`selector2`/`quick` - the
same pair of calls `interaction_energy` already makes, so the two ports agree by construction
rather than by two spellings being kept in step, and no schema is in the path. Verified on job
23670171's own relaxed pose: 1 ligand residue selected, **SC = 0.612**, which also clears T2's
`shape_complementarity >= 0.55`. The `beta_nov16` scorefunction went with the XML: SC is
geometric and takes no scorefunction, so it was decoration.

**A11b. The rosetta toolkit's cpu cost models were a UNITS ERROR, not stale numbers.**
`fastrelax` failed `cost_ratio[cpu_hours]` at measured/declared = 2.38 - a declared figure
*below* measurement, the direction that makes gate 5 and the untrusted-pattern cap refuse work
that fits. The cause: every comment computed `wall_seconds / 3600` and called it cpu_hours,
while the executor measures wall x cores. So the believed headroom was `cores` times smaller
than it read:

    fastrelax   believed ~4x   actually 0.52x   -> measured 2.38, FAIL
    packmin     believed ~5x   actually 1.14x   -> measured 0.81, passed by luck
    filter_shape believed ~4x  actually ~2x     -> never executed

`tests/test_real_toolkits.py::test_cost_models_are_within_an_order_of_magnitude_of_measurement`
was a **third** instance of the same error - it parametrised wall seconds and divided by 3600 -
so the specs and the test agreed with each other and with nothing that runs. Corrected to
`wall x cores` for cpu dimensions; gpu dimensions stay wall-based, since the declared figure
is device-time and `cores` is the CPU request.

`fastrelax` 0.03 -> **0.25** (3.5x measured, matching the 3.2x wall-time swing A11 records).
`packmin` 0.02 -> **0.06** (3.7x) although its row passed, because 1.14x of real headroom
means the next slower task blocks the smoke again. `filter_shape` left at **0.01** and
deliberately not adjusted: it has still never produced a cost measurement, so there is nothing
to derive a figure from, and the re-run is what will say.

  **C11 provenance:** the evidence above is jobs 22684607, 22692304, 22702568, 22726105, 22728140,
  which ran the `/work/hdd` checkout rather than this one. The measurements stand as measurements;
  what they cannot be read as is evidence about *this* code. See C11.

**G9. The code that reports a QC failure could not survive one.** **RESOLVED**
(2026-11-08). Found by the first four-arm smoke, job 23671024: all four arms died inside
their allocation with

    executor.py:1197  "failed_gates": [g.gate for g in task.qc.failed()],
    AttributeError: 'dict' object has no attribute 'gate'

`QCReport.failed()` returns provenance-shaped **dicts** - its own docstring says "in the form
provenance records them", and the executor's other caller (`:506`) records them whole. This
one reached for an attribute.

**Why nothing caught it, which is the part worth keeping.** A list comprehension over an
EMPTY list never dereferences, and `failed_gates: []` is what a passing task logs. So the line
was exercised constantly and the bug was unreachable until a task actually failed a gate on
hardware. Every campaign-tier test, every prior Delta run and - decisively -
`impress-a validate-tasks` all produced the empty case. **The clean validation that authorised
this smoke was structurally incapable of finding it**: a validation pass whose Tasks all pass
their integrity rows has nothing to put in that list. One gate failure in a real campaign, and
the executor takes the campaign down while reporting it.

Cost: four arms x ~4 minutes, about 1.1 GPU-h, and the arms had already produced real work -
arm A ran `rfd3_design` at **width 4 with four distinct lineages, seeds and metrics** (A10's
independence invariant, executing for the first time) and a full `ligandmpnn_design` stage
before it died.

Pinned by `tests/test_core.py::test_the_failed_gate_list_is_logged_in_the_shape_failed_
actually_returns`, asserted against `failed()`'s contract rather than through a campaign, so it
holds whatever the executor does around it.

**The coverage gap behind it, which is the more useful finding.**
`test_lying_tool_is_caught_by_qc` is the only test in the suite that produces a QC FAIL, and
it drives `Dispatcher` directly - so `_log_task_telemetry` never runs for it. Every test that
DOES go through the executor uses tools that pass. So the expression was exercised on every
task in the suite and never once on a non-empty list.

Closed by
`tests/test_campaign.py::test_a_failed_gate_reaches_tasks_provenance_through_the_executor`,
which runs `mock_noodle` at the HEAD of a real chain - same `Backbone` output as
`mock_generate`, no inputs - through a real `CampaignManager`, and asserts the gate NAMES land
in `tasks` provenance. The chain matters: a noodle-only campaign plans nothing and reaps
nothing, which is how the first draft of this test was written and would have passed against
the bug. Asserting names rather than absence-of-crash matters for the same reason - a silent
drop of the field would also not raise. Confirmed to reproduce the exact `AttributeError`.

**The general lesson, and it is not the first time in this pass:** the failure path is the
untested path, and a green validation run is evidence about the success path only. There are
only two callers of `failed()` today and the other is correct.

**G10. The liveness bound killed the three arms that had no control plane.** **RESOLVED**
(2026-11-08). Second four-arm smoke, job 23671367: all four arms exited 0, no crashes - and
A, B and D each terminated after ONE cycle with `control plane lost after 267s/182s/185s of
silence` against `control_liveness_timeout_s: 120`. Arm C, the only arm with a caller, ran to
its own stop.

Two things were wrong. `touch()` records "any session operation", and an in-process campaign's
"caller" is the role driver in the same process - silent exactly when it is busy awaiting the
tasks it just asked for. And a cycle of this chain runs ~180s of tasks with no session
traffic, so **any bound shorter than a cycle turns normal progress into a lost plane**, for a
served campaign as much as an in-process one.

The spec's own comment said the bound "matters for any arm driven from a control process",
which is the opposite of what it did. `cli/__init__.py` records that `control_liveness_
timeout_s: 120` did nothing in all three Delta specs until the loader began reading it - so
its first real outing was the one that lost three arms.

Armed now only when a control plane has REGISTERED the campaign, and suspended entirely while
work is in flight. The flag is explicit (`under_external_control`, set by
`ControlPlane.register`) rather than inferred from `prov_sink`, which the plane also happens
to set: a bound that stops campaigns must not rest on a side effect of provenance mirroring.
It needed a property on `CampaignManager` too - `__getattr__` delegates reads of a known set
and nothing delegates writes, so a bare assignment would have landed on the manager while the
executor kept its default, leaving the bound disarmed for arm C as well.

**G11. The Goal asks for ten designs; the Spec is satisfied by one.** **RESOLVED** in code
on `agent/stopping-rules`, **unrun on hardware**. Doc:
[stopping-rules](stopping-rules.md). Arm C ran 24 tasks and stopped on "every spec objective satisfied" at cycle 0.
That was CORRECT behaviour, and the diagnosis is the interesting part.

`ThresholdSpecifier` translates each declared objective into a `SatisfactionRule` and leaves
`n` at its default of **1** (`policy/specifiers/explicit.py:72`). The campaign's
`target_front: 10` never reaches it. So the Spec is satisfied the moment ONE node clears each
threshold, while the Goal reads "Design at least ten distinct small-molecule binders meeting
every declared threshold" and the endpoint counts distinct T2 designs per node-hour. Two
stopping rules disagree and the laxer one wins - backlog X1's shape, inverted.

**And a node did clear them.** Arm C's own tasks:

    complex_plddt         0.904   bar 0.75   PASS
    ligand_iptm           0.851   bar 0.40   PASS
    shape_complementarity 0.731   bar 0.55   PASS
    interaction_energy  -25.47    bar -8     PASS (T2)

Prereg section 3 pre-registers `C_T3 = 0`, on the evidence that `complex_plddt` measured
0.426 / 0.486 / 0.507 across every run this project had recorded - "0 of 3". **Those three
runs came from the `/work/hdd` checkout** (C11), so that baseline describes different code.

**The cure, and what it turned out to be.** `target_front` did not merely fail to reach the
rule - it was read by **no code anywhere**: parsed into `CampaignSpec`, forwarded into
`ReasonerOptions`, consumed by nothing. Both Delta arm specs had declared `target_front: 10`
since they were written and it had never done anything. Section E's category, surviving because
the field existed in two places and so looked wired.

It now lives on the `Goal`, which `core/goal.py`'s own docstring argues for: the Goal carries
what success means and not how the campaign is driven, and "ten designs" is success criteria
rather than a loop knob. That placement also lets `ThresholdSpecifier` read it while `_spec_d`
keeps its ruling that a deterministic `Goal -> Spec` takes nothing from the options.
`SatisfactionRule.n` is set from it on **bounded** objectives only - an unbounded objective
ranks, and ten readings of a number nobody has to beat say nothing more than one. Campaigns
declaring no target are unaffected, because `CampaignSpec.target_front` defaults to 0.

It also crosses the control plane as `CampaignObservation.target_front`. A remote caller builds
its `Goal` from the observation and nothing else, so without that field arm C would stop at one
design while A, B and D ran to ten - a difference between arms that is not the model, and one
`impress-a compare`'s one-variable guard cannot see, since every arm would still complete with
plausible numbers.

**What `n` is not:** it counts READINGS over the bar (`len(metrics(metric)) >= n`), not distinct
designs. The endpoint clusters sequences; this does not. A stopping condition, not a score.
The pre-registered expectation should be read against this before the next smoke, and the
tier arithmetic in sections 12-13 rests on the same numbers.

**G12. Arm C served a campaign that two reasoners drove, and neither finished.** **PARTLY
RESOLVED** in code on `agent/stopping-rules`, **unrun on hardware**. Doc:
[external-control-arm-c](external-control-arm-c.md). Evidence: job 23675997.

`impress-a serve --model C` builds model C's inbox halves **in the serving process** and then
calls `mgr.run()`, so that process drives the campaign and waits to be `steer`ed.
`impress-a control` is not a steerer: it is the same `RolesDriver` the in-process arms use,
against a `RemoteSession`, and it drives by calling `submit_stage` over the plane. **Nothing
shipped calls `plane.steer`.** So job 23675997 ran two reasoners against one executor - the
sidecar planned and submitted r0001's 24 tasks, all of which passed, and the served driver sat
at turn 0 waiting for a directive nothing would send, timed out after `--caller-timeout`, and
stopped the campaign while r0001 was still running.

The first diagnosis - G10's shape, a 120 s patience expiring while a ~180 s cycle ran - was
wrong, and the stop reason is the proof: it names *cycle 0*, and `RolesDriver` increments
`turn` the moment a stage is deployed, so a planner that had already placed r0001 could not
report cycle 0. Raising the timeout would have bought the same stop later. It also explains
23671367, where arm C stopped at cycle 0 on "every spec objective satisfied": the served
driver's Specifier saw a Spec the sidecar's run had already satisfied at `n=1`.

**Fixed:** arm C now serves **bare** (`scripts/delta_gpu_run.sh` drops `--model` and
`--caller-timeout`), so `serve` attaches `_Idle` and the sidecar is the campaign's one and only
reasoner - which is the two-process split C5 built and the only contrast arm C can honestly
claim. And `CampaignObservation` gains `max_cycles`/`max_attempts`, because
`cli.control_campaign` drove with `max_turns=10_000` - a number no campaign declares - while
every in-process arm uses `spec.max_cycles`; arm C has never survived past cycle 1, so nothing
could notice. That is G11's observation gap again, in the half that says how a campaign is
driven rather than what it is for.

**Still open:** model C's own code - the inbox halves, `on_timeout`, directive validation, the
`steer` route - is exercised by `tests/` and by nothing on Delta, because the steering caller
does not exist. Writing it carries a design question of its own (what a directive should carry
that a Stage does not). Until then arm C measures the out-of-process split rather than the
inbox halves, and the pre-registration should say so.

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
failure branches, not observed from a run (A1 is still open). Two were filed as bug reports rather than
as reassurance. `ligandmpnn_design/tests/unparsed_confidence_header.bad.json` pinned a parser failure
being reported as 0.0 confidence. That is FIXED: the adapter now omits what it cannot parse, and the
integrity gate `metrics_reported` catches it (decision 0013). The other is
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

**C8. Refinement is reachable generically but not for rfd3, so partial diffusion is unreachable.**
The generic half of phase 8 landed: a `Stage` carrying `parent_node` has its root task's input
ports satisfied from that `DesignNode.artifacts`, matched by declared TYPE, and
`test_campaign.py::test_a_refinement_stage_starts_from_its_parents_artifacts` proves it on
`mock_design`. The rfd3 half did not. `toolkits/rfd3/tools/rfd3_design/spec.yaml` declares
**no inputs at all** (only `outputs.backbone`) and no `partial_t`, so there is no port for a
parent structure to arrive on and no way to ask RFD3 for partial diffusion. The reference's
`num_refine_cycles: 2` / `rfd3_partial_t: 10.0` therefore has no equivalent here, and the
measured consequence was taken to be on the record: `complex_plddt` 0.426 / 0.486 / 0.507
against a 0.75 bound, 0 of 3.

  **Those three numbers no longer support that conclusion** (C11, and G11's own evidence). All
  three runs were produced by the `/work/hdd` checkout, so they describe different code; and on
  the current tree arm C of job 23671367 measured `complex_plddt` **0.904**, one for one over
  the same bound, with rfd3 refinement still unreachable. So whatever is wrong here, those
  three numbers are not the measurement of it. The argument that partial diffusion is
  unreachable stands on the spec declaring no inputs and no `partial_t`, which is checkable by
  reading the file; the fold-quality consequence is unmeasured. The pre-registration quotes
  the same three numbers in sections 3 and 13 and has not yet been re-derived.

  This is **not** blocking the four-arm experiment, and the specs are honest about it:
  `delta-small-molecule-arms{,-smoke}.yaml` keep `rfd3_design.num_designs: 1` with the reason
  recorded in the spec, the trust assertion covers widths 1 and 4 and **no refinement variant**,
  and `plans/arms-preregistration.md` §14 pre-registers the Goal as probably unreachable. What
  the item protects against is reading the prereg's "best-of-N plus refinement" sentence - which
  describes the *reference* - as a mechanism these arms have.

  **When this lands, `length` must be dropped from the guided spec.** RFD3's
  `DesignInputSpecification` validator rejects `length` outright whenever `partial.input` /
  `partial_t` are set (`ValidationError: ... Length argument must not be provided during partial
  diffusion`) - length is inferred from the input structure in that mode. The committed
  `campaigns/data/alr/ALR_binder_design.json` carries both `partial.input` and
  `"length": "70-170"`, which is correct and safe **today** precisely because partial diffusion
  is unreachable: that `length` is the from-scratch contig. The sibling example learned this by
  losing a production run - job `21928556`, 3 of 3 pipelines that reached guided feedback crashed
  on their first attempt - and fixed it in `_write_guided_rfd3_json()` with `partial.pop('length',
  None)`. `_inputs_with_absolute_paths` in `tools/rfd3_agents.py` rewrites `input` paths and
  nothing else, so it would carry `length` straight through.
  `test_real_toolkits.py::test_rfd3_partial_diffusion_would_have_to_drop_length` is a guard that
  abstains while `partial_t` is undeclared and fails the moment it is added without the drop.

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

**RESOLVED** (phase 7 of `control-plane-refactor.md`). `impress-a serve <spec>` runs the
execution process - executor, Reviewer, Deployer, Runner, the one asyncflow engine - with no
reasoner at all, behind `ControlPlaneServer`, and prints the URL it bound. `impress-a control
--connect <url> --campaign <id> --model X` runs the Spec and Planning loops in their own
process against `RemoteSession`. The split is now reachable from a shell, which is what this
item was about; `test_serve_and_control_drive_a_campaign_in_two_processes` spawns both and
drives a campaign, because every other test shares one interpreter and so cannot claim it.

**C6. `--model C` fails open.** `cli/__init__.py:78-80` builds an `ExternalPolicy` with
`on_timeout="fallback"` and no control plane attached, so its inbox can never be filled: it times out
every 5s and silently runs `ThresholdPolicy` instead. The documented headless mode
(`docs/decisions/0002`) is therefore unreachable from `impress-a run`, and reports a model-D campaign
as a model-C one. It should refuse and point at C5's entry points instead. Blocked on C5.

**RESOLVED** (phase 7), by refusing rather than by detecting. `impress-a run --model C` now
exits 1 and names the two commands to use instead. The entry points that make C real exist, so
"no caller attached" is an operator error with an answer rather than a mode to degrade into -
and `--specifier C` and `--planner C` are refused the same way, since they are the same hazard
wearing a different flag. A disguised arm is indistinguishable from a real one in every figure
derived from it, which is why this is a refusal and not a warning.

**C7. Where the control plane is reachable from is undecided.** `docs/reference/frontends.md:110`
offers HTTP+SSE for "a reasoner outside the allocation", but `control/http.py:17-21` is loopback,
single trusted client, no auth, no TLS. Planning question M6
(`planning/phase1-partB-architecture/06-headless-control-protocol.md:115-117`) — where the adapter
process runs relative to the job — was sidestepped rather than answered, and a real split on Delta
needs it settled: the compute node's private interface, or a tunnel, and what the security boundary
then is. Blocked on C5.

**ANSWERED for this configuration** (phase 7): nowhere else. `impress-a serve` binds
`127.0.0.1` by default and both processes belong on the same compute node, so the boundary is
the node rather than a token nobody rotates. `--host` exists for a deliberate choice, and the
plane still has no auth and no TLS - so anything other than loopback is a decision this item
should be reopened for, not a flag to set casually.

**C9. The Delta launcher could not run arm C, and gave every arm one trust ledger.** **RESOLVED**
(2026-11-08), both found by reading `scripts/delta_gpu_run.sh` against
`plans/arms-preregistration.md` §10 rather than by a run.

*Arm C died at launch.* `IMPRESS_A_COMMAND` defaulted to `run` with no reference to the arm, and
`impress-a run --model C` is refused outright (C6). So the §10 submission - `sbatch --array=0-3`,
one job, four arms - would have had argparse kill index 2 while the other three queued normally,
printing a message about the environment. The launcher now selects `serve` when the arm is C and
starts an `impress-a control` sidecar beside it; an exported command still wins, which is how
`delta_validate_tasks.sh` keeps working. The sidecar polls for the 0600 `control_plane.url`
`serve` writes rather than being told a port (the port is ephemeral on purpose - see A9/C7), and
takes the campaign id from that file's own parent directory, which cannot disagree with the
server because `InProcessControlPlane.register` keys on the same `spec.campaign_id`. It drives
with `--model B`, not `--model C`: the caller **is** the reasoner, and C on that side would build
the inbox halves a second time and stop after one `--caller-timeout` with nobody steering the
steerer. The refusal message at `cli/__init__.py:742` still prints `--model C` for the control
line and is wrong about it; left alone here because amending the text would change nothing that
runs, but it is the one place a reader is told the deadlocking thing.

*Every arm shared one trust ledger.* The per-arm block interpolated `${MODEL}` a hundred lines
**above** where `MODEL` is resolved from `SLURM_ARRAY_TASK_ID`. There is no `set -u`, so it
expanded to nothing and all four arms resolved to `_trust_arms/<experiment>/` - exactly the
shared ledger §10 calls mandatory to avoid, since four concurrent processes would each admit an
instance of the same untrusted signature, breaking one-instance-in-flight across processes, and
one arm's evidence would subsidise the other three. Silent in every way: the directory exists,
`trust --assert` seeds it, and the arms differ only by which ran first. The arm block now sits
above the ledger block, with the ordering constraint written where someone moving it will read
it. **Nothing has run under the broken form**, so no recorded result is affected.

Both pinned in `tests/test_toolchain.py` (`..._sends_arm_c_to_serve_...`,
`..._forwards_a_model_profile_...`), each confirmed to fail with the fix reverted. **Unrun on
hardware.**

**C10. `delta_validate_tasks.sh` could not be submitted.** **RESOLVED** (2026-11-08), found
by running the pre-registration's own step 1 - the first time that command line had been sent
to sbatch.

The wrapper sets `IMPRESS_A_COMMAND=validate-tasks` and `exec`s `delta_gpu_run.sh`, which is the
right shape: everything that makes a Delta job work here was bought one burned allocation at a
time, and two copies would be two things to keep in step. But **Slurm parses `#SBATCH` out of
the file it is handed, at submit time**, and the `exec` happens at run time. So none of
`delta_gpu_run.sh`'s ten directives applied to a job submitted through the wrapper, which
declared none of its own. The documented command died at submit with

    sbatch: error: Jobs requesting no GPU resources must be submitted under CPU type accounts

- a message naming the ACCOUNT, for a missing GPU request, on the one step the entire trust
assertion cites as its evidence. A reader would have gone to check their allocations.

The resource shape now lives in the wrapper, mirroring the launcher's and for the same reason:
4 GPUs already reserves and bills the whole node, so 64 cores and 240G are free at that price,
and a validation pass on a narrower shape would not be validating the arms' hardware.
`--output=impress_a_%j.out` is load-bearing - the EXIT trap looks for that exact name.
`--time` and `--partition` stay on the command line, where the submission shows them.

Pinned by `tests/test_toolchain.py::test_every_documented_sbatch_entry_point_requests_its_own_
resources`, which reads every documented submission out of the docs and the scripts and checks that
the named script declares its own resources. Confirmed to fail against the old wrapper. One
detail worth keeping: the first version of that test passed against the broken script, because
every documented submission wraps across three lines with `\` and the regex was line-bounded -
the same shape of mistake as the bug it was written for.

**C11. Every submitted job has run a different checkout than the one submitted.**
**REOPENED 2026-11-09, RESOLVED AGAIN** on `agent/stopping-rules`. The most serious thing this
deployment pass found, and it was invisible by construction.

**It recurred the day after it was closed.** Job **23680592** was submitted as
`sbatch scripts/delta_validate_tasks.sh <smoke spec>` and ran
`dragon -s /work/hdd/bdyk/hooten1/impress_a/scripts/delta_run_campaign.py run ... --model D`:
19m49s on four A40s, an arm-D campaign where a validation pass was asked for. The sentence
below that reads "the wrapper resolves its sibling the same way" was false. It tried
`$IMPRESS_A_DIR` **before** `$SLURM_SUBMIT_DIR`, the submitting shell carried a stale
`/work/hdd` value that predated the `~/.bashrc` repoint, `sbatch --export=ALL` handed it over,
and the wrapper exec'd that tree's `delta_gpu_run.sh` - a copy predating the `validate-tasks`
branch, which ignored the exported `IMPRESS_A_COMMAND` and used its own `run`/`MODEL=D`
defaults.

**The launcher's refusal could not fire, because it is in the file the wrapper declined to
run.** That is the general lesson and it is worth more than the lost allocation: *a check that
only exists in the file you failed to reach is not a check*. The wrapper now prefers
`$SLURM_SUBMIT_DIR` and refuses a disagreeing `$IMPRESS_A_DIR` at its own hop, and
`tests/test_toolchain.py::test_the_validate_wrapper_refuses_the_same_disagreement_as_the_
launcher` runs the shipped script from a directory with no sibling beside it - the position
sbatch actually puts it in - rather than trusting that the two files agree. The four arms of
job 23675376 and the validation pass 23675119 all record
`Checkout: /work/nvme/bdyk/hooten1/IMPRESS/agent`, so this recurrence cost one job and no
results.

Two causes, and the second hid the first. `${BASH_SOURCE[0]}` **is not the repo under
sbatch**: Slurm copies the submitted script to the compute node as
`/var/spool/slurmd/job<ID>/slurm_script`, so `delta_gpu_run.sh`'s computed fallback resolves
to `/var/spool/slurmd`, which has no `.venv` and no `scripts/`. That never surfaced, because
`sbatch` exports the submitting environment and `~/.bashrc` carried
`export IMPRESS_A_DIR=/work/hdd/bdyk/hooten1/impress_a` - a DIFFERENT CHECKOUT - which the
`${IMPRESS_A_DIR:-...}` default preferred. Job 22692304's own `slurm.out` records it:
`dragon -s /work/hdd/bdyk/hooten1/impress_a/scripts/delta_run_campaign.py`, with that tree's
campaign spec. The launcher, the runner, the spec and the package were all the other repo's.

So **every result this project has recorded was produced by a tree nobody was reading**, and
`git_sha` in those manifests is that repo's HEAD rather than this one's - detectable
afterwards only by a reader who already suspects it. For the four-arm comparison, which is an
argument about code, an arm that ran another tree is not a result that can be corrected later;
it is a void arm that would not have been named void.

Found when `delta_validate_tasks.sh` failed at 7s with exit 127 - the `exec` of its sibling
looked in the spool directory (C10's cousin, same root). Had the wrapper worked, the job would
have run the old tree silently.

The launcher now prefers `$SLURM_SUBMIT_DIR`, requires the result to contain
`scripts/delta_gpu_run.sh`, and **refuses outright** when an inherited `$IMPRESS_A_DIR`
disagrees with the submission rather than picking a winner - a job that cannot say which
checkout it runs must not run. It also refuses when it can locate no checkout at all, instead
of proceeding with a path under `/var/spool`. The wrapper resolves its sibling the same way.
`~/.bashrc` was repointed at this checkout as well (and `IMPRESS_A_VENV` with it), so the
default is right and the guard is the backstop rather than the only defence.

Pinned by `tests/test_toolchain.py::test_the_launcher_refuses_a_checkout_that_is_not_the_one_
submitted`, which runs the resolution block itself in four environments.

**Not retrospectively fixable:** results recorded before this commit were produced by the
`/work/hdd` tree. Anything cited from them should say so, and now does: every item below whose
evidence is a job before the cutover carries a **C11 provenance** note naming its jobs. The rule
is mechanical - **any job id below 23670000 ran the other checkout** - and the sweep found ten
items, derived from the file rather than from memory:

| item | pre-cutover jobs it cites |
|---|---|
| A1 | 22536706, 22669509, 22692304, 22726105 |
| A4 | 22536706, 22669509 |
| A5 | 22318678 |
| A6 | 22669509, 22684607 |
| A7 | 22684607, 22692304 |
| A9 | 22675512 |
| A11 | 22684607, 22692304 |
| A12 | 22684607, 22692304, 22702568, 22726105, 22728140 (and 23670171, 23670891, which are this tree) |
| G4 | 22702568 |
| G6 | 22536706 |

A3 and G8 cite no job id at all, so neither needed one - which is worth recording, because both
were on the list this sweep was planned from and that list was written from memory.

**C12. Arm C's serve/control pair had never been executed.** **RUN, 2026-11-08**, on a login
node with mock tools - the first time the two processes have talked to each other anywhere.
Nothing in the suite covers `control_campaign`, and no document carried a worked pairing.

Two clean runs. With a model-D caller: `control` exited 0 and the served campaign stopped on
"every spec objective satisfied" after 2 cycles - steered, not timed out, which is the
distinction that matters, since an unsteered arm C stops on the planner's `on_timeout="stop"`
and reports a plausible campaign either way. With the Beam-backed `--model B` caller the smoke
will use: exit 0, 8 cycles, 15 nodes, stopping on the untrusted-pattern cost cap (an interlock
refusal that will not bind in the smoke, where trust is asserted).

Also confirmed: `serve` writes `control_plane.url` at 0600, the campaign id is recoverable from
that file's parent directory, and it agrees with what `InProcessControlPlane.register` keys on.

**One failure that did not reproduce, recorded rather than dropped.** An earlier attempt died
with `httpx.ConnectError: All connection attempts failed` against a URL that matched what
`serve` had printed, on a port later confirmed LISTEN, with no proxy variables set and `curl`
and `httpx` both reaching that port at +0/2/5/10/20s in a separate probe. Not seen again in
the runs since. `serve` writes the URL inside its own `async with`, so the window between the
file appearing and the accept loop running is small but not provably zero.

Undiagnosed, so the sidecar now **retries five times, two seconds apart**, before failing the
arm. That is insurance and not a fix: an unattended arm must not be lost to one refused
connection, and a transient nobody has explained is not a thing to spend an allocation
discovering. If it recurs inside a job, the retry line in the log is the evidence to reopen
this with.

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
  through deliberately - `$WORK_DIR`, the SLURM and CUDA variables all have to reach the container.
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
**The switch is DONE** (phase 10): it is `tool_delivery: real` on each Delta campaign spec, enforced
by validation **gate 6**, which refuses any graph containing a tool whose declared toolkit is
`mock`. Moved to the campaign spec because `cli.load_spec` already reads that file and a key in
`sites/` nobody reads is how it stayed inert for so long; `sites/*.yaml` now spells it
`copy_to_campaign_spec`, so it reads as a value to copy rather than as a control. A **gate** and not
`RuleCorrectionsPolicy(forbid_tools=...)` because `--no-guard` must not be able to switch off "is
this real", and it checks the declared toolkit rather than a `mock_` prefix because a prefix is a
convention. A test asserts every `delta-*.yaml` declares it and that the value reaches the spec.
**The rest of E1 stands:** nothing else in `sites/*.yaml` is read by any code.

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

**RESOLVED** (phase 2 of `control-plane-refactor.md`). The ruling: **a run that could not have
moved the front is not evidence that progress has stalled.** `pareto.feasible` admits a node
only if every *constrained* objective has a value satisfying it, and `satisfied_by(None)` is
False - so a graph that cannot produce one of those names cannot produce a front-eligible node,
whatever the science does. `RunRecord.could_reach_the_front` is answered at admission, where the
graph is in hand, and `_note_progress` skips the increment when it is False.

It is the same KIND of flaw as the fan-out one in `plans/done/03-stagnation-under-fanout.md`, and
it was found the same way: the counter was asking "did the front change" when the question it
needs answered is "did something that could have changed the front fail to". Unconstrained
objectives are deliberately excluded - they rank but never prune, so missing one costs a node
nothing.

Additive by construction: a run that can produce every constrained objective counts exactly as
it did, which `test_stagnation_still_counts_a_chain_that_could_have_moved_the_front` pins.
Without that second test, "exclude the runs that never had a chance" would be
indistinguishable from "stop counting". `test_a_truncated_chain_can_never_move_the_front` is
renamed `..._does_not_count_toward_stagnation` and asserts the opposite of what it did, which
its own docstring said would be the first thing to change. Raising the limit remains the wrong
fix and was not what happened.

**G2. rfd3 output parsing ignores the metrics rfd3 reports.** **HALF DONE** (phase 10). The
adapter reads the sidecar `*_model_*.json` it was already selecting candidates by and had never
opened, and reports `ca_deviation`, `ligand_clashes`, `helix_fraction` and `sheet_fraction` -
declared in the spec so a reasoner can see them and the campaign records them.

**Nothing gates on them, and that is the remaining half.** The key names are inferred rather
than observed: no sidecar from a real `out_dir` has been read. An acceptance gate needs an
integrity `metrics_reported` partner, so a partner naming a wrong key would fail every real run
as an INTEGRITY failure - refusing the chain and demoting the pattern on a guess. Backlog A3 is
the standing lesson about flags nobody has run. `rfd3_agents.SIDECAR_KEYS` holds the candidate
names and the adapter **logs the sidecar's actual keys**, so one real run resolves it from the
log; `impress-a validate-tasks` is the run that will. Selecting the best of several models is
also still open, for the reason the spec records at `num_designs`.

The other half of the original item is settled differently than proposed: the structural gate it
wanted (`ligand_clashes == 0`) waits on the names above, and the phi/psi estimate stays as the
integrity floor at 0.3 with upstream's own 0.5 as an acceptance gate beside it.

  **Half of it landed early, forced by A4:** *discovery* now reads the sidecar JSON, because a bare
  `*.cif.gz` glob was selecting trajectories. What G2 still asks for is the rest - reading
  `n_clashing.ligand_clashes` and friends *out* of that JSON for a structural gate, using rfd3's own
  `helix_fraction`/`sheet_fraction` instead of our phi/psi estimate, and selecting the best model
  rather than the first. The file is now open in the adapter; nothing is read from it yet.

**Still the blocker for rfd3's ensembling** (noted in phase 8 of
`control-plane-refactor.md`). `ligandmpnn_design` and `boltz_predict` now select the best member
of their own ensemble and their sampling is raised to 8; `rfd3_design` cannot, because choosing
among its designs means reading the sidecar `*_model_*.json` and nothing here has confirmed
which metric names it carries. So rfd3 stays at `num_designs: 1` with that reason recorded in
its spec, and this item is now what gates raising it.

**G3. `dump_trajectories=True` writes 99.4% waste.** Upstream measured trajectories at 11.85 MB of
each 11.92 MB rfd3 output dir and flipped it to False (`0800ad8`), taking a campaign from ~30 GB to
~3.8 GB. Safe because trajectory files ship no `.json`. We never read them.

  **RESOLVED** - flipped to `False` (`tools/rfd3_agents.py`) and asserted in the Hydra-contract
  test. It was held back only to be decided alongside G2; on inspection they are independent.
  G2 changes *which* file the agent reads for its metrics, while this changes whether a file
  nothing reads is written at all, so flipping it early costs G2 nothing.

**G4. The fastrelax gates are far looser than upstream's calibrated ones.** **DONE** (phase 10).
Every number verified against `run_small_molecule_binding.py`'s own `PROD` instance rather than
against the plan's copy of it: `fastrelax_max_fa_rep=100.0`, `fastrelax_max_score=-250.0` (data
range -193 to -510), `fastrelax_max_interact=-8.0` (p75 -8.8), `interface_min_sc=0.55`,
`backbone_min_ss_fraction=0.5`, `fold_min_plddt=75.0`. They land as **acceptance** gates beside
the existing wide divergence bounds, which stay integrity - two gates on one metric with
different roles is what decision 0013 is for, and `+1500` meaning "the tool broke" must not be
the same sentence as `-12` meaning "the design fell short". `complex_plddt` rises 0.5 -> 0.75
(PROD's 75.0 is a 0-100 figure; this metric is the 0-1 one), and `ligand_iptm >= 0.4` is kept and
is **stricter than PROD**, which leaves that gate off - every T3 figure has to say so.

`interaction_energy` is computed now, ported from upstream's own `scripts/fastrelax.py`:
`InteractionEnergyMetric` over `ResiduePropertySelector(LIGAND)` against its complement.
Selector-based rather than `jump="1"` or `chains="A"/"B"`, because which chain a ligand is in is
a property of the input and a chain split would silently measure the energy between two halves
of the protein instead. An empty ligand selection omits the metric rather than computing a
confident zero.

**What closing it cost, which is the finding.** A replay of job 22702568 - five runs recorded
`6/6 tasks ok` - now **fails integrity on every one**, because none of them computed
`interaction_energy`: those runs were never evidence that the chain worked, since the chain was
not measuring what the campaign was for. And with the fold bar at upstream's own 0.75, **not one
of the five contains a design the reference would have accepted** (two passed at 0.5). Both are
pinned as tests. Also fixed while there: `scores.get("fa_rep", 0.0)` fabricated a zero for a term
Rosetta had not computed, and 0.0 is a *passing* fa_rep, so a broken score function read as a
perfectly packed structure.

**rfd3's two new metrics are declared and ungated, deliberately.** `ca_deviation` and
`ligand_clashes` are read from the sidecar `*_model_*.json` the adapter was already selecting
candidates by and had never opened (G2's remaining half), but the key names are **inferred rather
than observed** - no sidecar from a real out_dir has been read. An acceptance gate needs an
integrity `metrics_reported` partner, so a partner naming a wrong key would fail every real run as
an integrity failure: a wrong guess would not merely be useless, it would refuse the chain and
demote the pattern. Backlog A3 is the standing lesson about flags nobody has run. The adapter logs
the sidecar's actual keys, so one real run resolves it; the gates land then.

  **C11 provenance:** the evidence above is job 22702568, which ran the `/work/hdd` checkout
  rather than this one. The measurements stand as measurements; what they cannot be read as is
  evidence about *this* code. See C11.

**G5. `filter_shape` may be measuring the wrong interface.** **DONE** (phase 10), and not by
copying upstream. Upstream splits by chain (`Chain chains="A"` against `chains="B"`), which is
right only when the ligand is its own chain - a property of the input, not of the tool. The pair
is now the ligand **residue property** against its complement, the same pair the
`interaction_energy` port uses, so it is correct whatever the chain layout is. `quick="0"` is
explicit because the default is Rosetta's and quick mode is a faster, less accurate SC;
`beta_nov16` is declared to match upstream's protocol, with the honest note that
ShapeComplementarity is geometric and takes no scorefunction, so it does not change the number.

A failure to build the selector filter **refuses** rather than falling back: a fallback would
keep producing numbers while measuring a different interface, and nothing downstream could tell.
An empty ligand selection refuses too, naming the commonest cause (a missing `-extra_res_fa`,
which drops the ligand entirely).

**`sc_selector_mode` is reported as a metric** - 0.0 the old jump filter, 1.0 the selector pair -
so one real run settles this from provenance, and a number recorded before phase 10 cannot be
compared with one recorded after without noticing. Every number this project has recorded is
mode 0.0.

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

  **C11 provenance:** the evidence above is job 22536706, which ran the `/work/hdd` checkout
  rather than this one. The measurements stand as measurements; what they cannot be read as is
  evidence about *this* code. See C11.

**G7. A run's seed comes from its run label, so every job samples the same five designs.**
`_replica_seed(run_label, lineage)`, and labels restart at r0001 in every job. Found by
`performance_analysis` S5/S6 (2026-10-08), over 17 designs from 5 jobs, and reproduced off-cluster
from the export on 2026-10-09 (5 distinct seeds, 21 same-seed pairs, every figure below unchanged):
- **The seed fixes the design's length.** All 21 same-label pairs share a length, and no pair
  with different labels does.
- **The seed biases the fold:** median TM-score 0.82 for same-label pairs against 0.28 for the rest.
- **The seed does not reproduce the coordinates:** 0 of 21 backbones are byte-identical, with a
  median Cα RMSD of 2.4 Å.

So the 17 designs are **5 independent folds**, sampled about 3 times each. That has two
consequences:
- every trust job re-explores r0001-r0005's folds instead of new ones;
- a rerun cannot reproduce a design, which is the other half of the replicas plan's
  "independent, REPRODUCIBLE draw".

The fix is a decision: salt the seed per campaign instance, for example with the job id, and
record the salt. Making rfd3 deterministic is a separate question, probably GPU nondeterminism.

**RESOLVED** (phase 5 of `control-plane-refactor.md`). `_replica_seed` takes a per-campaign-instance
salt: `sha256(f"{salt}/{run_label}/{lineage}")`. `cli.load_spec` fills it from
`$IMPRESS_A_SEED_SALT`, and it is recorded in `campaign` provenance, because a draw nobody can
name is one nobody can repeat. An empty salt reproduces the pre-G7 behaviour byte for byte,
which is what keeps every recorded figure comparable.

The decision the item asked for, stated: **the four-arm experiment shares ONE salt across its
arms.** G7 measured the seed as the dominant variance component (same-seed median TM 0.82
against 0.28 across seeds), so sharing it applies common random numbers and removes "that arm
drew luckier backbones" as an explanation - which matters at a minimum detectable effect as
coarse as 2.2x. It is variance reduction and not exact pairing: rfd3 is not reproducible to
coordinates (median Ca RMSD 2.4 A), and the pairing holds only for runs composing the same
shape with the same parameters.

**G8. Hardware use is unmeasured, and the ledger's `cost` is not a measurement.** **The
measurement half is DONE** (phase 5), and phase 10 added the thing that reads it:
`impress-a compare` reports `sum(cost_measured) / sum(cost_estimated)` per tool and dimension,
which is the figure this item asks for, and `impress-a validate-tasks` fails a Task whose ratio
exceeds 1.0 - above that a declared figure sits below measurement and gate 5 starts refusing
work that would in fact fit. The GPU-sampling half still needs an allocation: the launcher
writes `gpusample.csv`, and nothing has yet produced one to read.

The original finding, for the record:
- **The `cost` field:** each run's ledger `cost` repeats its admission estimate (0.17 in every
  trust run). Measured task time exists only as asyncflow state lines in `campaign.log`, which
  is what `performance_analysis/timeline.py` parses.
- **GPU use:** nothing samples it. C3 bounds the GPU-busy share at **≤17%** of billed GPU time
  in every job (15.4-16.7%), because one GPU works at a time and three sit idle, and CPU
  efficiency is ~42% (37-42%). The reference IMPRESS pipeline already writes a per-job
  `<jobid>.gpusample.txt` (`IMPRESS/examples/small_molecule_binding/logs/`), so check it before
  building a sampler here.
- **Both numbers are now archive-backed**, not session-backed: confirmed off-cluster on
  2026-10-09 from the sacct snapshot shipped with the run archive (G9).
- **The idle GPUs are the whole of it.** Tasks fill 95% of elapsed in the trust jobs, so
  orchestration is not where the allocation goes - three of four GPUs never have work.

**HALF-RESOLVED** (phase 5 of `control-plane-refactor.md`). Cost is measured now, and recorded
BESIDE the declared figure rather than replacing it. `TaskAgent.__call__` times all four phases;
`TaskUsage` carries `wall_s`, the per-phase breakdown, host, pid and `CUDA_VISIBLE_DEVICES`;
`TaskOutcome` carries `cost_measured` next to `cost`; and a new `tasks` provenance kind writes
one line per task so a scoring harness never has to parse the ledger's nested payload.

Two numbers, deliberately. The declared figure feeds gate 5 and the untrusted-pattern cap, and
those REFUSE graphs, so it must stay conservative rather than drift toward measurement (A11) -
settling the measured figure instead would change what admission refuses for every campaign at
once. Their ratio is the number this item wanted, and above 1.0 it says a declared figure has
fallen below measurement, at which point gate 5 refuses work that would in fact fit.

**Still open:** the hardware-side half. `gpusample.csv`, `sacct` and `seff` are the launcher's
to collect, and nothing yet measures GPU occupancy from inside the allocation - so "GPU-busy at
most 17%" remains the last word until an arm runs with the sampler attached.

**G9. The run export omitted `sacct.json`, so C3 could not be reproduced off-cluster — RESOLVED.**
`performance_analysis` was written on Delta with sacct reachable, and
`impress_a_runs_2026-10-08.tar.gz` was built without running `snapshot_sacct.py` first. Rerun
off-cluster on 2026-10-09, eleven of the twelve sections reproduced to the digit; C3 was the
exception, and everything it lost came from the allocation rather than the campaign: queue wait,
elapsed, billed GPU time, the GPU-busy share behind G8's ≤17%, CPU efficiency and peak RSS.

How it hid is the part worth keeping. `data.sacct` found no file, `Ctx.sacct` fell through to a
live query, `snapshot_sacct.query` caught the `OSError` from a missing `sacct` binary and returned
`{}` — and the report still labelled the source `live sacct` and printed *"at most nan% of the
billed GPU time had a GPU task running"*. A section that cannot answer its question reported a
`nan` as though it were a finding. Fixed: the label is `unavailable` when both the snapshot and
the query come back empty, C3 names the missing file and drops the columns it cannot fill, and
`test_c3_says_sacct_is_unavailable_rather_than_reporting_nan` pins it.

**RESOLVED the same day.** The snapshot was taken on Delta for the five Tier A/B jobs and now sits
beside the unpacked archive, so **all twelve sections reproduce off-cluster** and every G8 number
is archive-backed rather than session-backed: GPU-busy share 15.4-16.7% per job, CPU efficiency
37-42%, peak RSS 16.3 of 240 GB. Two facts C3 could not show before:

- **Tasks fill 95% of the allocation's elapsed time** in the trust jobs (86-88% in the two short
  smoke jobs, where a fixed ~20s prelaunch is a bigger share). Orchestration is not the overhead
  worth attacking; the three idle GPUs are.
- **Queue wait dwarfs the work.** 12269s, 26626s and 25278s for the first three jobs against
  478s and 184s for the last two - up to 32x the campaign's own elapsed time, on
  `gpuA100x4-interactive`. It is not billed, but it is the real latency of a test cycle.

`impress_a_runs_2026-10-08.tar.gz` has been rebuilt to carry `sacct.json` in the run root, so a
fresh unpack reproduces all twelve sections: verified by extracting the rebuilt archive to a
scratch directory and diffing its report against the working one (identical). Any future export
must run `snapshot_sacct.py` *before* packing. The same run exposed a second Delta-only
assumption, already fixed:
`datetime.UTC` is 3.11+, and the project declares `requires-python = ">=3.10"`, so `report.py`
had never run anywhere but Delta's 3.12.

---

**G13. The arms do not compose the same replica width, and the control arm fell through the
gap.** **FIXED** in code on `agent/stopping-rules`, **unrun on hardware**. Diagnosed on the
four-arm smoke of 2026-11-09. Doc:
[replica-width-confound](replica-width-confound.md). Evidence: array 23680876 (arms 23680888,
23680907, 23681055, 23680876).

Arms A, B and C composed **4 lineages** per cycle and arm D composed **2**, on one campaign
declaring `replicas: 4`. `ThresholdPlanner.__init__` carries `base_replicas: int = 2`
(`policy/planners/explicit.py:79`, used at `:127`) and nothing overrides it - `_plan_d`
(`policy/registry.py:147-154`) passes only `stages`, and `ReasonerOptions` has no replicas
field. The declared width cannot correct it, because `runtime/executor.py:763-765` applies
`min(intent.replicas, spec.replicas)`: `replicas` is a **ceiling, not a target**, so it is a
number only the arms with a model in them ever reach.

**It cost twice.** Replica multiplicity is part of the pattern signature
(`compose/graph.py:56-65` sorts one entry per node, so four lineages contribute four copies
where two contribute two - despite the docstring's "SHAPE ONLY"). Trust was asserted at widths 1
and 4, as `plans/arms-preregistration.md` §10 step 2 prescribes, so D's `f8bcefed63c493ae` was
in no arm's ledger and **D alone ran untrusted for r0001-r0003** - forced dry-run, 10% cost cap,
one instance in flight - earning trust at r0004, while A, B and C ran trusted from r0001. The
control arm therefore spent half its campaign at half the width under a different admission
regime from the arms it is the control for, and anything per-cycle measures that as well as the
model.

A10 predicted the signature half of this and `impress-a trust --replicas` was built for it. What
nobody enumerated is that **the arms do not all agree on width**, so no assertion list can cover
them all, and the arm that falls through is the control.

**Ruling: breadth is held FIXED across the arms, and the campaign declares it.** The comparison
exists to observe differences that follow from the reasoning track and from what that reasoning
costs; an arm targeting a smaller ensemble spends differently per cycle for a reason the
endpoint cannot separate from reasoning quality, so every arm targets an ensemble of similar
size. Model A's inherited explore-3 / exploit-2 breadth (`PROFILES`,
`policy/planners/agentic.py:64`, carried over from `FourNodePolicy`) is **not** a rigorous part
of model A - its purpose is projecting LLM reasoning onto a research-cycle structure - so the
declared width overrides it. A's quality and diversity fractions are untouched: those are the
strategy.

**The fix was not one wire, and a test comparing the arms to each other is what showed it.**
All four planners built `ThresholdPlanner(stages=stages)` and inherited `base_replicas = 2`, so
the declared width reached **none** of them. Three routes to one confound: (1) D's and C's
mechanics took the hardcoded 2 - the one the smoke measured; (2) A and B override with their
own numbers, reaching 4 only because a live Beam model asked for 4 every cycle, so **a degraded
turn would have silently halved that arm's width** and dropped it into the untrusted interlock
with the model blamed for it (probed: with no client they compose 3); (3)
`ExternalPlanner._to_stage` read `directive.get("replicas") or 1`, so a caller silent about
breadth composed **one** lineage.

`ReasonerOptions.replicas` now carries it, fed from `spec.replicas` and from
`CampaignObservation.replicas` for a remote driver; every planner forwards `base_replicas` to
its mechanics; A and B treat a declared width as authoritative over their own; `ExternalPlanner`
passes `lineages=None` rather than 1 when the directive is silent. 0 everywhere still means the
planner's own default, so no campaign declaring no width moves. `CampaignSpec.replicas` stays a
ceiling in the executor, which can clamp a graph down but cannot add lineages - the planners are
where width has to be composed.

**And `impress-a trust --assert` now covers every width from 1 to the declared one** rather than
the declared width alone, because a width nobody asserted runs under forced dry-run and a 10%
cost cap. On the smoke spec that is four signatures rather than two - `f5b21d82…` at 1,
`f8bcefed…` at 2 (the one D fell through), `fa8f3389…` at 3 (the one a degraded model-A arm
would have hit, never asserted by anyone), `78e730c6…` at 4.

**Tests:** `test_every_arm_composes_the_width_the_campaign_declared` builds a Stage from each of
the four arms against a spec declaring `replicas: 4` and asserts they agree - the comparison the
suite never made, since every other test checks one arm alone where a narrower width is merely
different. `test_a_campaign_that_declares_no_width_keeps_the_planners_own_default` pins the 0
case. Arm D now costs ~0.68 gpu-h per run (4.08 over six cycles, inside the 6.0 budget) and runs
trusted from r0001.

**Forces a pre-registration amendment** before any production arm (§10 step 2, §11's width-4
abort criterion and §12's admissions-under-scrutiny line). Drafted verbatim in the doc and
deliberately **not applied**: the prereg's own header rules that an amendment after the first
arm has run voids the comparison, `impress-a compare` enforces it through `prereg_sha`, and all
four smoke manifests record `c710f017…`.

## H. Reasoner models

The abstraction the whole decision frontend rests on, and the gap between what `docs/` claims for it
and what runs. Full evidence, the harmonization options and the hardware follow-on are in
[`plans/reasoner-models.md`](reasoner-models.md); the items below are what is outstanding from it.
`policy/registry.py`, `impress-a models` and the `--model replay` fix are **DONE** (`fa0266f`).

**H1. Model A has no LLM, and the slot for one is dead.** **MOSTLY DONE** (phase 9). The four
nodes exist and are compiled, two per half - `hypothesize`/`analyze` on `AgenticSpecifier`,
`select_tasks`/`parameterize` on `AgenticPlanner` - and `self.reasoner` is read: each node calls
`policy/reasoning.ask`, which is bounded (two attempts), schema-checked, and **corrective** - the
rejection is appended to the prompt, and the node's own domain check (is this one of the three
strategies?) runs *inside* the retry loop, because a check afterwards would reject a model that
invented a strategy and degrade on the spot without ever telling it what the strategies are.
Exhausting the attempts falls back to the rule cascade and writes a `reasoner_degraded`
transition, named the same way model B's `oracle_degraded` is, so one query over `transitions`
finds every degraded decision in a campaign whatever model made it - which is what the four-arm
experiment's void rule needs.

**RESOLVED** (2026-11-08). `cli._options_for` built the profile's client into `oracle` and left
`reasoner` at `None`, so `--model-profile` reached model B alone and `--model A --model-profile
X` ran the rule cascade while reporting nothing wrong - the quiet form of the failure the flag
exists to prevent, arriving by the other door. One client now fills both slots, which is sound
because `OpenAICompatOracle` implements `policy/reasoning.NodeReasoner` and no letter uses both
shapes; a second build would only be a second connection to one endpoint. Same change in
`_role_pair`, so `impress-a control --model A --model-profile X` is live too. `llm_calls: 0` in
`impress-a models` now means "with no profile named", which is what it always meant for B.
Pinned by `tests/test_reasoner_registry.py::test_a_model_profile_reaches_model_as_four_nodes_
and_not_only_model_bs_oracle`, confirmed to fail with the `reasoner=` assignment removed.
**PROBED on a login node, 2026-11-08**, against Reflection Beam (`Beam-501B-A23B`) on
`campaigns/mock-stabilize.yaml` and on a copy with thresholds raised so the campaign could not
stop early: exit 0 both times, a live model id on every call, **zero `reasoner_degraded`
transitions** and zero corrective retries. The seam carries a client. Unrun on *hardware*; that
is the smoke.

**And the probe corrected the record.** Only **two** of model A's four nodes ever call the
model: `hypothesize` and `select_tasks`. `_analyze` (`policy/specifiers/agentic.py:139`) and
`_parameterize` (`policy/planners/agentic.py:161`) make no `reasoning.ask` call at all - they
act on the strategy the node before them chose. The registry note claimed "each node is a
bounded schema-checked call", which has never been true, and it was believed well enough to be
written into the pre-registration's amendment as "A makes ~4 calls per cycle to B's ~2". The
measurement is **2 per cycle for both**: 3 `hypothesize` + 3 `select_tasks` over 3 cycles for A,
8 spec + 8 stage over 8 cycles for B. Corrected in the note and in prereg §14. Not a code defect
- the two-call shape is a reasonable design - but an A-vs-B contrast at *equal* call cost is a
different claim from one at double, and the figure was wrong in the direction that flatters the
experiment. **What is still unexercised:** both halves' corrective-retry path, since nothing was
rejected; a rejection has still never been seen against a live endpoint.

A is no longer behaviourally D, though: it retires an
objective the Toolkit cannot measure (D names it and leaves it open) and it moves the diversity
knobs (D never does), both asserted in `tests/test_planner.py`.

The original finding, for the record:  `planning/phase1-partB-architecture/02-control-models.md:59-61`
specifies "each node is a bounded LLM call with a declared input and output schema", ~3 per cycle,
parse-retry with corrective feedback, escalation to a degraded policy. In code `_hypothesize`
(`policy/agentic.py:57`) and `_parameterize` (`:75`) are deterministic threshold cascades, and
`self.reasoner` (`:51`) is stored and never read. There is no schema, no retry, and no `fallback`
argument - B and C both have one. `_build()` registers two nodes while the module docstring describes
four. So `--model A` is a LangGraph-shaped rule cascade, bit-exact and behaviourally a sibling of D,
and its only test asserts termination (`tests/test_campaign.py:53`), never a node.

**H2. Model B's live path is never constructed.** **DONE but for a live probe** (phase 9).
`policy/llm.py` carries `OpenAICompatOracle`, ported from
`examples/agentic_small_molecule_binding/llm.py` - which has four hardware runs behind it -
with everything Part B doc 02 sections 3 and 7 ask for: a pinned dated model id, pinned
sampling (temperature stated on every request, because a comparison cannot hold it constant if
no request does), `Retry-After` honoured, retryable statuses separated from a 400 that will
fail identically however often it is sent, and the model's own `reasoning_content` carried back
for an endpoint that requires it. Async rather than synchronous: the halves run on the control
process's own loop, which is what phase 7 bought, so no thread is needed. `models.yaml` holds
one profile per model and `--model-profile` selects it; the extra is now `openai` rather than
the `litellm` nothing imported, as `plans/reasoner-models.md` specified.

Three defects closed with it, each silent. **The rehearsal returned the mock chain whatever the
campaign declared** and `_build_b` did not forward `o.stages`: against the six-stage Delta
chain that is a campaign which validates the real toolkits and then executes mocks, with
plausible metrics and `6/6 tasks ok`, reported as a model-B result. There is no default chain
now and a chainless rehearsal refuses by name. **Its stopping conditions were hardcoded** at
`cycle >= 4` / `front >= 3`, which is X1 by another route. **A reply was brace-sliced** out of
the text, so a prose answer containing two braces produced a decision from whatever was between
them; it is parsed, and a reply that is not a JSON object is a schema failure `reasoning.ask`
tells the model about. And `DECISION_SCHEMA` split in two: `SPEC_SCHEMA` answers in metrics and
thresholds, `STAGE_SCHEMA` in tools, breadth and parameters, sharing only `rationale` - which a
test asserts, and which caught `parent_node` being asked of both halves.

**Still open:** no request has reached a real endpoint from this project. The sibling example
measured `claude-opus-5-5` declining *its* workload through this endpoint
(`finish_reason=content_filter`, 0 completion tokens, with and without the system prompt);
whether a request for a JSON decision hits the same filter is unmeasured, so probe it on a
login node before an allocation depends on it. That probe is the prerequisite gate's H2 row.

The original finding, for the record:  `OraclePolicy` defaults to `RehearsalOracle`
(`policy/oracle.py:85`) and nothing passes a model, so `--model B` runs the deterministic stand-in.
`LangChainOracle` (`:65-77`) is built nowhere, brace-slices JSON out of the reply despite a docstring
claiming structured output, and has none of what Part B doc 02 sections 3 and 7 require: pinned dated
model id, sampling parameters, `Retry-After` backoff, 429-vs-529. `pyproject.toml`'s
`oracle = ["litellm"]` extra is imported by nothing. A working OpenAI-compatible client with
per-model profiles already exists in `examples/agentic_small_molecule_binding/llm.py` and has
hardware results behind it; porting it is the plan's step 1.

**H3. No policy can vary a real tool's parameters.** **DONE for model D** (phase 9): its Planner
half, `policy/planners/explicit.ThresholdPlanner`, chooses parameters from the `ToolkitView`'s own
`ParamCard`s - so the tool ids and the ranges come from the specs rather than from this file - and
`tests/test_real_toolkits.py::test_a_planner_can_vary_a_real_tools_parameter` asserts against the
real six-stage chain that the tool is in the chain, the parameter is one that tool declares, the
value is inside the declared range, and it differs from the default. Which parameter is read from
the spec's `trades` sentence, the only prose a reasoner gets: `quality`/`accuracy`/`convergence` is
the refinement axis, while `coverage`/`sampling`/`candidates` (breadth) and `seed` (lineage
identity) are deliberately left alone - raising rfd3's `num_designs` pays N times for one design
while its adapter keeps index 0, and moving `seed` would break the independence of the replicas the
arm is credited for. **Still open for A, B and C**, whose planner halves are still derived from
`decide` and still emit the mock keys below. Two gaps found while closing it, both of which would
have made a real roles-driven campaign wrong rather than merely limited: `submit_stage` applied
neither the campaign's `params` nor its `replicas` cap (`_apply_campaign_defaults` ran on the intent
path only), so a Delta campaign on the roles path would have run `boltz_predict` with an empty
`ligand_smiles` - which models no ligand rather than failing, A2 by a new route - and
`CampaignObservation` did not carry the campaign's declared chain, so a Planner driving a campaign
over a socket could not learn its ORDER and would have wired each port to the wrong producer.

The original finding, for the record: A and D emit `params` keyed to `mock_generate`
and `mock_design` (`policy/agentic.py:84`, `policy/explicit.py:69`), and B's rehearsal the same
(`policy/oracle.py:60`), even when `stages` is the real six-stage chain. `compose/composer.py:63`
reads `intent.params.get(tool_id, {})` per composed stage, so those keys are silently dropped. On a
real campaign a policy's only levers are stage selection, `parent_node`, `Backtrack` and `Stop` - and
A9 records that even `replicas` is capped downstream where the policy cannot see it. **This is the
item that blocks any claim about decision quality**, and it is why model D cannot yet be the
benchmark against the reference's `adaptive_decision()`, which varies the route and the retry.

**H4. Declared-but-inert seams.** `ToolSpec.agent: Literal["deterministic", "llm"]`
(`tools/spec.py:96`) is read by no code, while decision 0006, `docs/reference/architecture.md:145` and
`docs/roadmap/academy-for-task-agents.md:90` all present it as working. `Registry.toolkit_skills()`
(`tools/registry.py:85`) has zero callers, although Part B doc 04:112-124 specifies skill documents are
"supplied to the policy at campaign start" and doc 06:65 gives the observation field for them - so
`obs.available_tools` is bare ids and model B's prompt lists tool names with no parameters, costs or
pitfalls. The fifth specified skill section, **Composition guidance** (doc 04:122), was dropped from
`docs/reference/authoring-tools.md:180`'s four required sections, and it is the one a reasoner most
needs. `ExperimentIntent.toolkit_hint` (`core/decision.py:26`) is read nowhere.

**H5. No `conduct` reasoner ships.** The entry point, `core/session.py`'s ten-operation surface and
`policy/driver.py`'s adapter all exist and are covered, but every `conduct` implementation in the
repository is a test double (`tests/test_campaign.py:401,467,548,615,789`,
`tests/test_remote_session.py:68`, `tests/test_http_adapter.py:62`). Free tool-calling over
`CampaignSession` - a reasoner whose tools are `observe`/`submit`/`result`/`as_completed`/`backtrack`/
`stop` - is the shape `examples/agentic_small_molecule_binding` actually built, and it is **not**
model B: Part B doc 02 sections 3 and 6 specify B as one structured call per cycle, and that ruling
stands. Worth building as its own reasoner, named as such.

**H6. The lint ceiling stated below does not reproduce, and nothing lints `agent/` at all.**
`.github/workflows/agent-tests.yml` runs only `pytest tests -q`, and `tox -e lint` resolves to
`ruff check src tests` from the repository root, which is IMPRESS's `src/impress` and its own
`tests/`. Meanwhile `agent/pyproject.toml` declares no `[tool.ruff]`, so ruff walks up and applies
IMPRESS's root config - `line-length = 88`, `target-version = "py39"` for a package whose floor is
3.10, and `fix = true`, which makes the documented `ruff check` command **rewrite the working tree**
(36 files on first run). Measured under that config: **449 findings**, 404 of them E501, against the
41 stated below; under ruff's own defaults, 9. The ceiling was evidently recorded against defaults.
This belongs to the project-level CI and documentation consolidation, not to a reasoner item, but it
is recorded here because the verification paragraph below currently states a number no configuration
produces.

**RESOLVED** (phase 0 of `control-plane-refactor.md`). `agent/pyproject.toml` now carries its own
`[tool.ruff]` at `line-length = 100`, `target-version = "py310"` and **`fix = false`** — a linter
that edits the tree cannot be a gate, because a clean run and a run that rewrote 36 files are
indistinguishable afterwards. The residual against that config was **57**, and all 57 were closed
rather than budgeted: 37 by one deliberate `ruff check --fix`, 20 by hand (10 line reflows, 3 unused
locals, 3 `zip(strict=)`, 2 semicolons, 2 `N806`, 1 `E741`, 1 `B904`). `N818` is **declined**, not
worked around — an `Error` suffix on `CampaignAborted`, `CampaignStopped`, `SubmissionRejected` and
`BackendConstructionTimeout` would falsify every sentence in `docs/decisions/`, `plans/done/` and
`CLAUDE.md` that names them, for no runtime benefit; the reason sits beside the `ignore` entry.
`.github/workflows/agent-tests.yml` runs `ruff check src tests` before the suite, and its path
filter now includes `src/impress/**` and the root `pyproject.toml`, because this package now
depends on the root one. **The ceiling is zero**, stated in `CLAUDE.md`, so a finding is a
regression rather than a budget — which is the only form in which a ceiling is worth anything.
One measurement worth keeping: the 3.2× spread between the numbers quoted here came from *which
config resolved*, not from drift, and that is why the table a tool reads must live next to the code
it lints.

**H7. Hardware: paired 1-hour, 1-node runs of B and D.** After H2. One spec, two arms, differing only
in `--model`, submitted together - `campaigns/delta-small-molecule-arms.yaml` derived from
`delta-small-molecule-trust.yaml`, 1 node on `gpuA40x4`, 8 GPU-h total. They test the `ControlPolicy`
contract under a live LLM: a real `Decision`, an LLM-authored `ExperimentIntent` passing or being
refused by the five gates, `on_rejected` under a real rejection, the degraded transition and its
labelling. **They cannot test decision quality** while H3 is open, and must not be reported as if they
could. Prerequisites with their evidence, and the scoring method, are in the plan.

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
6. ~~**C5-C6 the reasoner's entry points**~~ **DONE** (phases 7 and 9). `impress-a serve` /
   `impress-a control` exist and are covered by a two-process test, `--model C` under
   `impress-a run` is refused rather than timing out, and model C now has **two role inboxes**
   routed by a `role` key inside the directive `steer` already carries - one headless mode
   (decision 0002) and no new plane operation (ADR 0007). Its planner half defaults to
   `on_timeout="stop"`, a fallback must be declared to exist, and taking one writes a
   `caller_timeout` transition naming it, because a fallen-back C arm is byte-for-byte a D
   campaign - and the default was wrong until a shell run showed it: `ExternalPlanner`
   defaulted to `stop` while `ReasonerOptions.on_timeout` defaulted to `fallback`, so every
   path through the registry, which is every path the CLI takes, built the dangerous one.
   `impress-a serve --model C` logged `no directive in 5.0s; on_timeout=fallback` and finished
   on model D's planner. Both defaults are `stop` now, pinned by a test.

   **The arrangement for arm C is one process, and that is a finding rather than a choice.**
   `plane.steer` reaches `manager.policy`, which lives in the *execution* process - so a
   campaign served with no reasoner for `impress-a control` to attach to has nothing for a
   third party to steer, and every directive comes back `campaign is not under external
   control`. Decision 0002 says model C *is* the headless mode, and the headless mode is one
   process serving a campaign whose halves are its inboxes: `impress-a serve <spec> --model C`.
   The two-process split stays for A, B and D, whose halves have no inbox. Verified across two
   OS processes from a shell, with the caller's `recycles: 6` reaching the deployed tasks.

   **C7 remains**: the plane has no auth and no TLS, settled for the loopback configuration in
   ADR 0014 and open for any other - and `--model C` raises the stakes, because a directive is
   now the campaign's parameter vector rather than a suggestion.

   What the loopback configuration actually rests on, since `impress-a serve --model C` makes it
   load-bearing: **loopback** (`--host` defaults to `127.0.0.1`, and the launcher does not
   override it), **an ephemeral port** (`--port` defaults to 0; the Delta launcher pinned 8711
   for one commit, which was a regression against that default - a fixed port is guessable and
   collides with a second `serve` on the same node), and **the URL in a 0600 file** that a
   sidecar reads instead of being told a number. All three are asserted in
   `tests/test_split_process.py`.

   **A token would add nothing to this, and that is worth recording so it is not proposed
   again.** The one threat loopback does not exclude is another process of the *same user* on
   the same node, and that process can read a token file as easily as the sidecar can. What
   rules it out is the node being the job's - 4 of 4 GPUs, 64 of 64 cores and 240G of ~249G
   leaves nothing schedulable beside it - which is an inference from the resource request rather
   than a guarantee. `--exclusive` is the flag that would make it one, and a Unix domain socket
   with 0700 is the stronger fix if the plane ever needs to run where the node is shared; both
   are what closing C7 properly would involve.
7. **B1 structural gates and G2/G4/G5** — all four wait on the first real run, which is what
   tells us what rfd3 actually writes and what the Rosetta numbers actually look like.
8. **C1-C3** on demand; **C4** only if a real campaign shows abandoned runs holding GPUs.
9. ~~**G1**~~ **DONE** — decided in phase 2, before the `conduct()` role pipeline it was gating
   could explore with a truncated chain. The characterization test did change, exactly as it
   said it would, and a second test now holds the fix to being additive.
10. ~~**H6 the lint gate**~~ **DONE** — it was the reason H1-H5 went unnoticed, and it was cheap.
    ~~**H3**~~ **DONE for model D** in phase 9, which is what unblocks any claim about decision
    quality for the control arm; A, B and C follow with their own planner halves. Then **H2**
    (the client exists and has hardware behind it), then **H7**. **H1** after H2, which is what
    makes it cheap. **H4** and **H5** on demand. H1-H3 and H7 are now phase 9 and the experiment
    of [`control-plane-refactor.md`](control-plane-refactor.md).
11. ~~**X1 `max_cycles` was not forwarded to the reasoner**~~ **DONE** (phase 9). Found while
    planning the four-arm experiment. `build_policy` withheld it on the reasoning that
    `CampaignManager._reasoner` already bounds the driver and bounding one thing twice hides an
    off-by-one. The consequence was worse than what it avoided: every model carried
    `ReasonerOptions.max_cycles`'s default of **6**, so a four-hour arm declaring `max_cycles: 200`
    would have decided six times in about twenty minutes, stopped itself, and reported a clean
    campaign having spent roughly 8% of its allocation. `target_front` had the same shape with no
    second bound at all behind it, and is now a declared `CampaignSpec` field (0 keeps the model's
    own 3) rather than an inferred one, because how many designs a campaign wants is a property of
    the Goal and `core.pareto.Objective` says nothing about it.
12. ~~**G13 the replica-width confound**~~ — **FIXED in code, unrun on hardware.** It was not
    the one wire it looked like: the declared width reached no planner at all, and two of the
    three routes were latent rather than measured. The pre-registration amendment it forces is
    drafted and still unapplied, and is only legitimate before the production arms are
    submitted - so that ordering is not a preference. **A smoke rerun is what closes it**, and
    the thing to read is whether all four arms report the same lineage count and all four run
    trusted from r0001.

## The legacy decision path is gone (phase 11)

`decide(obs) -> Decision` and everything that implemented it were deleted: `policy/driver.py`,
`policy/legacy.py`, `policy/base.py`, the four policy classes, `NullPolicy`, the policy-level
wrappers, `CampaignSpec.control`, `CampaignObservation.available_tools`, and the `Decision` union
(`ComposeAndRun`, `Backtrack`, `Stop`). A reasoner is now a Specifier/Planner pair or a `conduct`
implementation, and `manager._reasoner` raises `TypeError` for anything else -
`tests/test_layering.py::test_no_module_defines_decide` is the mechanical proof.

**Three rulings the deleted modules carried survive, and here is where each landed.** Bounded
retry per experiment is `Planner.replan`, bounded by `runtime/roles.py::_deploy` and
independently by the executor. The concurrency hold is the Deployer's in-flight cap. And
`_collect`'s rule that the reasoner owns `interpret` is the Listener owning ingestion - which is
the structural version of it rather than a hook, so the executor never reaches into a reasoner
at all.

**Two names survive with reasons.** `RequestHuman` is the payload of
`CampaignSession.request_human`, a live operation. `ExperimentIntent` is the composer's input: a
chain and a width, which is what `impress-a trust --assert` needs to compute a signature at a
declared replica width and what `impress-a validate-tasks` needs to run a chain once. ADR 0010 is
amended accordingly rather than the type deleted.

**Two tests were deleted because their purpose finished**, not because they became inconvenient.
`test_roles_pipeline_reproduces_the_legacy_campaign` was the strangler's seam - it ran the same
policy down both control paths over five policy shapes, and it is what made every phase's failure
attributable to that phase. There is one path now. `test_a_stage_round_trips_through_an_intent`
pinned the two adapters that let phase 1 avoid touching `compose/` and `exec/`; both are gone.
What they protected lives in `test_split_process.py` (one process against a socket) and
`test_remote_session.py` (inside the process against outside it).

**One defect surfaced by the deletion.** Removing the tail truncation showed that it had been
defeating the interlock's one-instance-in-flight rule: truncation changes the graph's SHAPE, so a
refused instance was re-admitted as a different pattern. Two concurrency tests were passing
because of it, and both stopped admitting anything the moment it went.

## Verification that applies to any item

**`impress-a validate-tasks <spec>` on an allocation, before trusting a toolkit.** It executes
each Task of the chain once, in dependency order, through the ordinary composer and dispatcher,
and checks: it ran; it is not from the `mock` toolkit; the `[phase]` breakdown is there, so
import time is separable from work; every declared output port produced, with its declared
`ArtifactType`, on disk, above a size floor; every declared metric reported and **finite**;
integrity gates passed, with acceptance reported separately; measured wall time within the
declared `walltime_s`; and `cost_measured / cost_estimated <= 1.0` per dimension.

It is the only check shaped like all four defects that reached real hardware - what a tool
writes, whether it can import, where the bytes live, and an estimate that refuses work - none
of which a dry run can find, because "checked against the binary" is not "executed". Exits
non-zero on any integrity row, which is the gate `impress-a trust --assert` cites as its reason.


`pytest tests -q` green, no allocation. `ruff check src tests` **must report nothing** — the one
number worth stating, and it is zero rather than a budget, so any finding is a regression. It was
quoted as 41 until H6 found that no configuration produced that number. The import
contract is asserted by `tests/test_layering.py` rather than checked by eye. `impress-a run campaigns/mock-stabilize.yaml --model D` and
`--model A` still terminate with a stated reason and a non-empty front, and
`impress-a run campaigns/delta-small-molecule-smoke.yaml --model D` must compose `rfd3_design…`,
never `mock_generate…`.
