# Known Limitations

Stated plainly rather than discovered later.

## Scientific scope

**The loop closes *in silico*.** Nothing in the current toolkit consumes experimental data, so the Pareto
front ranks *predicted* quantities. A campaign's output is a prioritized hypothesis set, not validated
designs, and results should be reported that way.

The architecture anticipates this changing: `Property` carries a source and authority so a measurement
supersedes a prediction for the same objective without any change to a campaign specification, and
`ingest_measurement` accepts assay results even after a campaign terminates (`docs/decisions/0012`). What
is *not* built is the other half — nothing selects which designs to send for assay or manages samples.

**Some problem classes need a human-supplied hypothesis.** Where a design protocol depends on expert
mechanistic judgement (catalytic geometry being the clearest case), the agent can vary parameters and run
QC around a supplied hypothesis but cannot author it. Autonomy is narrower there, and a campaign should
say so.

## Residual risk in free composition

The validation regime prevents type-incoherent workflows, missing QC gates, frozen-parameter tampering,
resource-infeasible and platform-impossible graphs, budget overruns, and every *catalogued* silent
failure. It does not prevent a **novel** silent failure — one of a kind no `ToolSpec` anticipated, in a
tool combination no human reviewed. Cross-tool consistency and distributional checks are the general
defences, and they are statistical, not sound.

The self-promoting interlock buys **examination and delay, not soundness**: a *consistent* novel silent
failure — one that passes every gate, agrees with a correlated tool, and looks distributionally ordinary
on all N runs — will promote. Two consequences: raise the promotion threshold for patterns feeding
irreversible or expensive commitments, and weight cross-tool agreement conservatively, since tools
sharing training data or architecture may agree *because* they share a bias.

Since decision 0013, the interlock counts only **integrity** gates, which ask whether the tool ran and
reported real numbers. It ignores **acceptance** gates, the quality thresholds. That made promotion
reachable on a hard target, and it narrowed what trust rests on. For the real toolkits the integrity
gates are thin: presence checks, `has_secondary_structure`, and the Rosetta divergence bounds. There is
nothing structural (backlog B1). A tool that emits well-formed, plausibly-scored garbage could already
promote; one that emits well-formed, *low*-scored garbage now can too, as long as it reports its numbers.
Acceptance failures still keep such a node off the front.

## Reproducibility, by layer

| Layer | Reproducible? |
|---|---|
| Core, composition, validation | Bit-exact |
| Model D policies | Bit-exact, seeded |
| Tool execution | Approximately — pinned versions and checkpoint hashes; GPU non-determinism remains |
| Model A / B policies | **No** — frontier APIs offer no usable seed, and temperature 0 does not guarantee determinism |
| A campaign as a whole | **Reconstructable, not replayable** |

An LLM-steered campaign can be audited and reconstructed from provenance; it cannot be re-run to the same
answer. Model D exists partly so there is a fully reproducible baseline to compare against.

## Cost estimates are unmeasured

Validation gate 5 refuses graphs against `cost_model` figures drawn from literature and documentation,
not measurements on the target platforms. Early campaigns should record actual-versus-estimated cost per
tool and recalibrate; until then the gate should carry a safety margin rather than be treated as precise.

**Two real numbers now exist, and the second one was a latent bug rather than a mis-estimate.**
`rfd3_design` cost 0.25 GPU-h against a 0.5 estimate (job 22669509). `ligandmpnn_design` had
`walltime_s: 300` - and that same job shows its task spending **276s reaching a `ModuleNotFoundError`
in module-level imports**, before allocating a tensor. Roughly 280s of every invocation is `import
torch` paging off a Lustre mount, so the tool could not have finished importing inside its own
timeout, and would have failed as `timed out after 300s`: a message that reads like a hang and blames
the tool rather than the budget. Now 1800s, with the measurement recorded in the spec.

The general point is about where these numbers hide rather than about this tool. A `walltime_s` that
is too small does not announce itself as a mis-estimate; it announces itself as a timeout, which is
the same shape as a hang. On shared HPC the import cost can dominate a short task entirely, and it is
invisible to every local test because no local test pays it. The other four real tools' figures are
still literature guesses, and the first thing each one's real run will produce is the true number.

## Cancellation

**Still the open risk, but now measured.** Backtracking works by *branching the tree*, which avoids
needing to cancel in-flight work. The spike has since been done against the installed asyncflow, and the
answer is: cancellation exists and is **advisory only**.

`ConcurrentExecutionBackend.cancel_task` calls `Future.cancel()`, which returns `False` once a callable
has started — so **queued work is reclaimed and running work is not** — and asyncflow's own cancel hook
discards that boolean, so a caller never learns which happened. `Dispatcher.cancel` and the control
plane's `cancel_run` therefore say so in their return value, and a run's terminal state always comes
from collecting it, never from the fact that cancel was called.

What this leaves unsolved: reclaiming a GPU from a long-running task that should have been abandoned.
That needs cooperative cancellation inside the task agents, or a backend that can kill a process.

## Not yet implemented

The **MCP** control-plane adapter, checkpoint/restart **resume** (the job ledger now records run state
and outcomes, and `RunService.reattach` reconciles what a previous process left open — but nothing
resumes a campaign from it yet), and the P5 network-service governor (caching, per-service concurrency
caps, `Retry-After` backoff).

## The Dragon backend can hang silently during construction

`rhapsody`'s Dragon execution backend builds `Batch()` (the results DDict, a GPU-affinity worker
pool, telemetry) **synchronously** inside its own constructor, with no `await` points. A stall there
blocks the event loop entirely: not the campaign's own heartbeat, not the process, nothing gets a
chance to run until `Batch()` returns - so a genuinely hung construction is indistinguishable from a
process still starting up, right up until whatever wall-clock limit kills the job. This is exactly
what happened to job 22318678: the process ran for its full 2-hour SLURM allocation and was killed
on the time limit having produced only Dragon's own internal infra-connect log lines - no campaign
log, no ledger entry, no heartbeat, nothing else, the entire time.

Bounded now by `CampaignSpec.backend_startup_timeout_s` (0 = disabled, the default - every existing
campaign is unaffected) and `backend_startup_heartbeat_s`: the backend's *synchronous* construction
runs on a dedicated daemon thread so the calling event loop stays free to heartbeat-log and enforce
the timeout, and a stall past the bound raises `BackendConstructionTimeout` with a clear diagnostic
instead of silently consuming the rest of the allocation. Both Delta campaign YAMLs set a 600s bound.

**The bound is not purely protective, and getting it wrong costs whole allocations.** Only the
synchronous construction may be offloaded. A `WorkflowEngine` captures the running loop in
`__init__` and puts its `run-component` dispatch task on it, and a rhapsody backend captures its own
loop during async init - so both must be built on the loop that will submit to them. The first
version of this bound ran all of `make_engine` on the daemon thread under `asyncio.run(...)`; that
call's exit cancelled `run-component` and closed the loop, and the caller received an engine that
looked healthy and dispatched nothing. Jobs 22328172 and 22328262 - the only two campaigns that had
`backend_startup_timeout_s > 0` - each logged `r0001 submitted` and then sat silent for their full
walltime. Fixed in `exec/backend.py`; `tests/test_backend_bound.py` now runs a real task through a
bounded engine, because a dead engine is indistinguishable from a live one until you do.

What this does **not** solve: *why* a real construction might stall inside Dragon's own
`Batch()`/`Pool()` (most likely GPU-affinity worker rendezvous or OFI/libfabric negotiation) is
still unknown - see backlog A5.

## ...and during teardown

The mirror image, and the more expensive one, because by then the campaign has already produced
everything it was asked for. Measured on the reference IMPRESS pipeline (job 22491438):
`flow.shutdown()` never returned after all sixteen of its pipelines had finished. The job sat 60
minutes and had to be cancelled by hand - roughly 64 GPU-hours, 37% of its billed total, spent
after the science was done. That project's own conclusion was to treat it as reproducible until
shown otherwise.

Bounded by `CampaignSpec.backend_shutdown_timeout_s` (0 disables, as with startup; 300s in both
Delta campaigns). On expiry the teardown is **abandoned with a warning rather than raised**:
every result is already durable in provenance and the ledger by that point, so the worst case is
leaked backend state in a process that is about to exit - whereas raising would turn a campaign
that succeeded into one that reports failure.

Note this is a place where we deliberately diverge from the reference pipeline, which declined the
in-code bound and relies on an operator watching the log and issuing `scancel`. The SLURM wall
clock remains our second line of defence, which is part of why `scripts/delta_gpu_run.sh` asks for
12 hours rather than the partition maximum.

## ...and when a task's exception cannot be unpickled

Dragon hands a worker's exception back by pickling it into a DDict. If it cannot be unpickled,
rhapsody's monitor loop logs `Critical error in monitor loop` and drops every completion in that
sweep. No FAILED arrives, and the run sits in flight until the SLURM wall clock kills it (job
22536706, on a LigandMPNN failure). Our own `SubprocessError` is now pickle-safe. Any other
exception with a required-argument `__init__` that does not forward those arguments to `super()`
still triggers it, and nothing bounds a single run's wall-clock time. If a campaign log shows that
error followed by a heartbeat whose `inflight` never drops, `scancel` it. See backlog G6.

## Dragon removes the root logger's handlers

`dragon.native.Pool.__init__` and `ProcessGroup.__init__` call `setup_BE_logging`, which begins with
`_clear_root_log_handlers()` - every handler on the **root** logger is closed and removed, and
handlers are re-added only where `DRAGON_LOG_DEVICE_{STDERR,DRAGON_FILE,ACTOR_FILE}` asks for them.
rhapsody builds `Batch()` inside the Dragon backend constructor, so on the Delta path this happens
during engine bring-up and everything logged afterwards is discarded. This is the second reason jobs
22328172/22328262 produced no diagnostics: even once the hang is fixed, a batch run configured only
through `logging.basicConfig` goes mute the moment the backend comes up.

`scripts/delta_run_campaign.py` now keeps its handlers (stderr plus a `campaign.log` transcript in
the job working directory) on the `impress_a`/`rhapsody`/`radical`/`dragon` loggers with
`propagate = False`, out of root's reach, and logs a one-off WARNING naming `setup_BE_logging` when
it notices root has been emptied. Anything that logs to the root logger directly is still lost.

## Storage was the bottleneck, and it masqueraded as three other bugs

Every path this project reads at runtime used to hang off `$SCRATCH`, which on Delta
resolves under HDD-backed `/work/hdd`. Measured there: `import pyrosetta` **471s** (a 598 MB
`rosetta.so`, demand-paged), `pyrosetta.init` 4.5s, `get_fa_scorefxn` 58.2s - **533.8s before
any work**, against a `packmin` budget of 300s. `import torch` cost ~280s of LigandMPNN's
292.6s.

What makes this worth a section is not the slowness but the disguise. It arrived as a task
timeout, which reads as a hung tool; it was about to be "fixed" by raising three walltimes
to 1800/3600/1200 with the 533.8s figure written into each spec as justification. Moving
`$WORK_DIR` to `/work/nvme` (ported from the reference pipeline's PR #67) instead produced,
on job 22684607: `ligandmpnn_design` 292.6s → **18.1s**, and `packmin` - which could not
finish importing in 300s - completing in **15.9s**, with `fastrelax` 25.9s and
`filter_shape` 10.2s. The existing walltimes were never wrong. Had the raises shipped, the
real cost would have stayed hidden behind timeouts six times larger than necessary.

Two general points. **A timeout names a budget, not a cause** - which is why `run_cmd` now
preserves whatever a killed process already wrote, and why the Rosetta workers emit phase
timings to stderr. And **an estimate that feeds a refusal gate is not harmless when it is
too high**: the cost models were 6-69x over, the gpu side summed past the untrusted-pattern
cap, and the budget correction that followed silently truncated `boltz_predict` - the only
producer of two of the campaign's four objectives - off the end of the chain.

## One campaign has completed — what that does and does not establish

Job 22692304 ran all six real tools end to end (`6/6 tasks ok`, 2m53s), admitted on the first
attempt, every stage passing its gates, terminating with a one-node Pareto front. All four
campaign objectives carry real values: `total_score` -272.0, `shape_complementarity` 0.591,
`complex_plddt` 0.507, `ligand_iptm` 0.752. Per-tool cost is measured for all six and the
`cost_model` figures corrected from it.

**It establishes that the machinery runs.** It does not establish that the science is good, and
it is important not to read it as more than one draw:

- **One lineage.** `replicas > 1` has never executed, so `replicas: N` producing N *independent*
  `DesignNode`s - the invariant the whole seed-plumbing exists for - remains unverified.
- **One cycle.** `max_cycles: 1`, so no policy has ever acted on an observation, and backtracking
  has never been exercised against real results.
- **Nothing trusted, and for a while nothing could be.** The ledger resolved against a relative
  path inside each job's working directory, so every SLURM job started with an empty one and
  promotion - three *consecutive* clean runs in one file - was unreachable on Delta from the
  first run onward. Fixed; the path is now site-scoped and logged absolutely at campaign start.
  The *trusted* code path (no forced dry-run, no 10% cost cap) has now executed - two cycles of
  job 22726105 - but has not yet run sustained, and no real node has reached plain `pass`:
  untrusted nodes are always `suspect`, and both trusted ones missed an acceptance threshold.
- **No measurement has superseded a prediction.** `ingest_measurement` and the whole
  predicted-vs-measured calibration story still have no real assay data behind them.
- **The QC thresholds have one or two observations each.** `complex_plddt` cleared its 0.5 bound
  by 0.007. `filter_shape` returned 0.524 against 0.55 on the run before and 0.591 here. Whether
  these numbers sit in the right place is unknown, and `packmin`'s turned out to be upstream's
  *fastrelax* threshold copied onto the wrong stage - it failed +145.3 and +14.8, both healthy.

**Cost figures are single samples and should not be tightened.** `rfd3_design` took 145.7s in job
22684607 and 45.0s in 22692304 - same campaign, same allocation shape, same parameters, 3.2x
apart. The declared `cost_model` values deliberately sit 3-5x above measurement because they feed
gate 5 and the untrusted-pattern cap, both of which *refuse* graphs; tuning them to a fast
observation is how a campaign starts being rejected for no real reason.

### Getting here cost four defects, none of which a dry run could have found

The first stage to execute paid for itself immediately. Its real `out_dir` showed that
`RFD3DesignAgent`'s `*.cif.gz` glob
was selecting a diffusion **trajectory** rather than the design - trajectories carry the same
extension and `denoised` sorts first - so the backbone passed downstream was a multi-frame stack.
Discovery now goes through the sidecar `*_model_*.json`. That turned out to be the expected yield
of executing each remaining stage rather than a one-off.

Job 22669509 made the point again and sharpened it. Handed the correct 53 KB backbone, LigandMPNN
still failed - in `run.py`'s **module-level imports**, before parsing an argument: first a missing
`ml_collections`, then `np.int`, which numpy removed in 1.24. Neither had anything to do with the
trajectory bug, which had merely been the plausible-looking explanation for the earlier failure; the
two defects were independent. Both are environmental rather than logical - LigandMPNN vendors a copy
of openfold written against pre-1.20 numpy, and this venv carries 2.x because Boltz requires it - and
the adapter now runs `run.py` through a shim restoring those aliases, as the reference pipeline
always did. The recurring lesson: **an adapter checked against a binary's contract is not an adapter
that has been run**, and what breaks first is usually the environment, not the arguments.

What makes this class expensive is *where* it was found. A missing module and a removed numpy alias
are both knowable on a login node in seconds; both were instead discovered inside a GPU allocation,
after a queue wait. `impress-a preflight` now runs LigandMPNN's real import chain through the same
shim the adapter uses - but only for someone who runs it, since no launcher invokes preflight. In
the same pass, preflight gained an **undetermined** state: a probe that times out now reports `warn`
rather than `FAIL`, because a check that could not be run to a conclusion is not a check that failed,
and two meaningless FAILs teach a reader to ignore the column that matters.

A verification pass against the actual installed toolkits on Delta (not just old scripts) found and
fixed real contract bugs rather than merely confirming guesses: `rfd3_design` was invoking `rfd3`
with flags (`--config`/`--out`) that do not exist on the real Hydra-based CLI at all and would have
failed immediately - rewritten to the real `out_dir=`/`inputs=`/`diffusion_batch_size=`/
`inference_sampler.num_timesteps=`/`seed=` contract. `boltz_predict` was missing the required
`--no_kernels` flag (a verified CUDA ABI mismatch between the pinned torch and
cuequivariance-ops-cu12 versions, not an optional flag). `ligandmpnn_design` had no way to express a
fixed-residue constraint. None of the three Rosetta toolkits (`packmin`, `fastrelax`, `filter_shape`)
had a way to pass a ligand `.params` file, so a real ligand-bearing PDB would likely raise in
`pose_from_pdb()` rather than silently mis-score. All four are now fixed (see each toolkit's
`SKILL.md`); LigandMPNN's own seed/batch flags were checked and confirmed correct as originally
written. `impress-a preflight` still runs cleanly for the ALR benchmark target on a Delta login node,
but this list is checked contracts, not an executed run - see "no campaign has yet run them on real
hardware," above.

Related: the QC gates the real toolkits declare lean almost entirely on `metric_in_range` against a
tool's **own** self-reported confidence — which is exactly what a confidently-wrong tool passes. There
are no structural gates yet (is the ligand actually in the output complex, are there chain breaks, does
the sequence length match the contig), and no toolkit carries the known-bad fixtures under `tests/` that
this document's authoring guide asks for.
