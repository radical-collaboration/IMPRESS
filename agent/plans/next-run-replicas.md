# Next Delta run: two independent lineages

`replicas: N` must mean **N independent lineages**, one `DesignNode` each (CLAUDE.md
invariants). It has never run on real hardware, and `plans/first-real-run.md` calls it the
invariant most likely to be silently wrong. If the per-lineage seed plumbing does nothing, a
real tool given an explicit seed produces N identical designs, and N candidates silently
collapse into one. Sustained trust is now shown (job 22728140), so this is the next thing to
make real.

## What the groundwork found

**Trust does not carry over.** The pattern signature includes replica multiplicity:
- one lineage: `f5b21d82…`, trusted in the site ledger;
- **two: `f8bcefed…`, unknown, so it starts untrusted**;
- three: `fa8f3389…`;
- four: `78e730c6…`.

Backlog A10's preferred route, "earn trust at one lineage and a trusted pattern bypasses the
cap", therefore does not work. Each width earns its own trust, under the 10% untrusted cost cap.

**Width is limited by that cap.** Simulated against the real admission path, with the trust
campaign's 6.0 GPU-h budget (cap 0.60):

| Replicas | Nodes | Estimate GPU-h | Untrusted cap |
|---|---|---|---|
| 1 | 6 | 0.17 | fits |
| **2** | **12** | **0.34** | **fits, with room for 6 cycles** (available stays ≥ 3.4 for 7 runs) |
| 3 | 18 | 0.51 | fits |
| 4 | 24 | 0.68 | **refused**. `on_rejected` would shrink it to 3 and say so only in a correction warning |

**Seeds are per lineage.** `compose/composer._replica_seed(run_label, lineage)` gives each
lineage its own draw. `TaskAgent.parameterize` passes it to every tool that declares a `seed`:
rfd3, ligandmpnn, packmin, fastrelax and boltz (filter_shape is deterministic). It does so
*unless the campaign names a seed*, which would collapse the lineages. The trust spec names
none. Keep it that way.

**Concurrent GPU tasks are not pinned, and this is the blocker.** With two lineages, the two
`rfd3_design` tasks run at the same time, as do the two `boltz_predict` tasks. Nothing has ever
run two GPU tasks at once on Delta: every real run so far was one serial chain.
- **No per-task GPU:** every task inherits `CUDA_VISIBLE_DEVICES=0,1,2,3` (the launcher logs
  it), and the tools default to the first visible device. So both lineages would share GPU 0
  while GPUs 1–3 sit idle.
- **Dead code:** `exec/resources.to_backend_description` would translate a spec's `gpus`/`cores`
  for Dragon, but nothing calls it, and its Dragon branch assigns no GPU anyway.
- **Same cores:** it pins every task to cores `0..N-1`, so concurrent tasks would also share cores.

Run as-is, a failure would be ambiguous between lineage independence and two models on one
GPU. That breaks the one-variable rule.

## Step 1 (code, before the run): pin each lineage to its own GPU

- **Assign:** within one graph, stages of a lineage run in series and lineages run in parallel.
  So `gpu = lineage % gpus_per_node` gives concurrent GPU tasks distinct devices, for up to
  `gpus_per_node` lineages at `concurrency: 1`. It is deterministic, needs no cross-process
  allocator, and is recorded at submit time.
- **Plumb:** `TaskRequest` gains the device. `_subprocess.run_cmd` callers in the four
  adapters launch with `CUDA_VISIBLE_DEVICES=<gpu>` in the child env (rfd3's apptainer passes
  the variable through). Tasks with `resources.gpus == 0` are left alone.
- **Record:** the device appears in each task's outcome in `jobs/ledger.jsonl`, so the run
  proves which GPU each lineage used.
- **Delete** the dead `to_backend_description`, or wire it. Do not leave it implying Dragon
  receives resource shapes.
- **Tests:**
  - a two-lineage graph assigns GPUs 0 and 1;
  - a CPU-only tool gets no override;
  - the child env really carries the variable (a fake command that echoes it);
  - `concurrency > 1` is out of scope, so a test documents that lineage-based pinning
    assumes one graph in flight.

The alternative is to skip pinning and treat co-location as part of what is measured. That is
cheaper today, but it is two variables, and an OOM would not say which.

## Step 2: the run

**Spec:** a new `campaigns/delta-small-molecule-replicas.yaml`, a copy of the trust spec with
`replicas: 2` and nothing else changed:
- 6 cycles, which now really means 6 runs, since the driver no longer counts a backtrack as a
  cycle;
- `concurrency: 1`, `stagnation_limit: 6`, and the same budget (6 GPU-h, 10 CPU-h; ~2.0 / 0.7
  expected).

`ThresholdPolicy` asks for 3 lineages while the front is empty, and the spec caps that at 2.
That keeps every run at signature `f8bcefed…`, so the ledger accumulates on one pattern.

**Allocation:** as before, `gpuA100x4-interactive`, 1 node, 1h. At about 3 minutes per cycle
with pinned GPUs, expect ~20 minutes.

**Preconditions:**
- step 1 is merged; `pytest tests -q` is green; ruff ≤ 41; preflight is 12/12;
- a local dry check composes the replicas spec at 2 lineages, under the cap, at `f8bcefed…`.

```bash
export WORK_DIR=/work/nvme/<project>/$USER
impress-a preflight campaigns/delta-small-molecule-replicas.yaml
sbatch --partition=gpuA100x4-interactive --time=01:00:00 \
       scripts/delta_gpu_run.sh campaigns/delta-small-molecule-replicas.yaml
```

## Prediction, stated before submitting

**Independence, which is the point:**
- every run produces **two DesignNodes**, lineage 0 and lineage 1, 12 tasks each 6/6 ok;
- **within each run, the two lineages differ at every seeded stage.** The rfd3 backbones have
  different `sha256` in `jobs/ledger.jsonl`, and so do the LigandMPNN sequences and the
  packmin, fastrelax and Boltz outputs; their metrics differ. Identical artifacts across
  lineages, at any seeded stage, is a failed prediction;
- across runs the seeds differ too, because they are derived from the run label.

**GPUs:** in each run the two lineages' GPU tasks report devices 0 and 1, never the same one.
The two rfd3 tasks overlap in time and do not run in series: their workdir timestamps
interleave.

**Trust, for the new signature `f8bcefed…`:** r0001–r0003 are untrusted and integrity-clean,
then `pattern_promoted` after **r0003**, and **r0004–r0006 run trusted**. A two-lineage run is
clean only if all 12 tasks are, which doubles the exposure. Replayed under the current gates,
all 15 chains from the three trust jobs are integrity-clean.

**Front:** acceptance is ~31% per lineage, so roughly half the runs should put at least one node
on the front, and a trusted plain `pass` becomes more likely than before.

## Reading the outcome

| Observed | Meaning | Next |
|---|---|---|
| Two distinct nodes per run, lineages differ everywhere, promoted after r0003 | Independence holds; replicas works | Record; consider 3 lineages (fits the cap) |
| Lineages produce **identical** artifacts at some stage | The seed did not reach that tool (`parameterize`, the adapter's flag, or a campaign-level seed) | Fix that adapter; this is the silent failure A10 warned about |
| One node per run, or nodes with merged metrics | A fan-out/funnel collapse in the composer or `_absorb` | Fix before anything else; it breaks a core invariant |
| CUDA OOM or device errors | Pinning did not take effect (check the ledger's device field) | Check the env plumbing per adapter |
| An admission refused by the interlock cap | The estimate or budget differs from the simulation | Compare `graphs.jsonl` `estimate` to 0.34 |
| `pattern_demoted` | An integrity failure in one lineage; `failed_gates` names it | Investigate that tool |

## Also record

- **Backlog A10:** route (a) ("earn trust at width 1") does not work, because the signature
  includes multiplicity, and replicas 4 cannot be admitted untrusted at a 6.0 budget, so it can
  never earn trust there either. Width 4 needs a bigger budget (route b) or a deliberate ruling
  that multiplicity should not change the signature, which is a design decision, not a fix.
- **Backlog:** the dead `to_backend_description` and the shared-core pinning.
