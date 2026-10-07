# Next Delta run: sustained trust

Job 22726105 executed the trusted path for the first time: it promoted after r0002 and ran
r0003 and r0004 trusted. It held for only two cycles. r0004 was demoted by packmin's
`total_score <= 1000` integrity bound over a +1064.5 pre-relax pose that relaxed normally to
-336.0. That bound is now gone, and whether a pose exploded is judged by fastrelax converging
(`toolkits/rosetta/SKILL.md`). The outcome is recorded in `plans/next-run-promotion.md`.

Two things have still never happened on real hardware:
1. **Sustained trusted operation:** several consecutive trusted cycles with no demotion.
2. **A plain `pass`:** a node that clears every gate *while trusted*. Untrusted nodes are
   always `suspect`, and both trusted nodes so far missed an acceptance threshold.

This run is designed to get the first and give the second a good chance. It is cheap: one
interactive node for about 15 minutes. It is worth doing before `replicas: 2`, because a
replicated graph has a different signature, so it starts untrusted and tests none of this.

## One variable: packmin no longer bounds its own score

Everything else matches 22726105:
- **Spec:** `campaigns/delta-small-molecule-trust.yaml`, unedited: `max_cycles: 6`,
  `replicas: 1`, `concurrency: 1`, `stagnation_limit: 6`, and a budget of 6 GPU-h / 10 CPU-h
  against about 1.0 / 0.4 used.
- **Allocation:** `gpuA100x4-interactive`, 1 node, 1h limit. 22726105 used 13m41s.
- **Site ledger:** `$WORK_DIR/_trust/cuda.jsonl`, left in place. For `f5b21d82924fbcd0` it
  folds to `clean_runs=1`, untrusted, 1 demotion. The pattern signature covers tool ids and
  typed edges only, so the gate change does not reset it.

Before submitting:
- `main` contains the packmin change, `pytest tests -q` is green, and ruff is ≤ 41;
- `impress-a preflight campaigns/delta-small-molecule-trust.yaml` reports 12/12.

```bash
export WORK_DIR=/work/nvme/<project>/$USER
impress-a preflight campaigns/delta-small-molecule-trust.yaml
sbatch --partition=gpuA100x4-interactive --time=01:00:00 \
       scripts/delta_gpu_run.sh campaigns/delta-small-molecule-trust.yaml
```

Watch it with the `slurm-job-watch` skill, matching
`submitted r|reaped|pattern_promoted|pattern_demoted|terminated|Traceback|ERROR`, with the log
glob `$WORK_DIR/impress_a_runs/<jobid>_delta-small-molecule-trust/campaign.log`.

## Prediction, stated before submitting

**Ledger:**
- r0001 is clean (2), and r0002 is clean, so **`pattern_promoted` after r0002**;
- **r0003–r0006 are admitted trusted**, four cycles. In `graphs.jsonl`: `trusted: true`,
  `scrutiny.force_dry_run: false`, `cost_cap_fraction: null`;
- **no `pattern_demoted`**. Across the 11 complete six-stage runs so far, the only integrity
  failure was the packmin bound that has now been removed. Replaying 22726105 under the new
  rule stays trusted from r0002 on (`test_replaying_job_22726105_stays_trusted_once_promoted`).

**QC:**
- trusted nodes are `pass` or `fail`, never `suspect`; untrusted nodes are `suspect` or `fail`;
- `failed_gates` on every node holds only `role: acceptance` entries;
- **plain `pass` is likely, not certain.** 4 of 11 complete runs cleared every acceptance
  threshold (about 36%), so four trusted cycles give roughly an 80% chance of at least one
  `pass`. A run with none does **not** falsify the prediction. It is a draw, and is reported as
  one.

**Timing:** about 2.5 min per cycle. Trusted cycles skip the dry run, and r0003 in 22726105 took
2m39s against r0002's 3m00s, so expect trusted cycles slightly shorter. The total is about 15
minutes.

## Reading the outcome

| Observed | Meaning | Next |
|---|---|---|
| Promoted after r0002, r0003–r0006 trusted, no demotion | **Sustained trust holds.** Record it | `replicas: 2` (below) |
| …and at least one node is `pass` | The first plain `pass` on real hardware; it should be on the front | Record which node and its metrics |
| …and no node is `pass` | Acceptance draws missed; not a defect | Nothing to fix; note the rate |
| A trusted cycle errors (task failure or exception) | A real bug on the trusted path, which has run only twice | Diagnose from the logs and `failed_gates`, fix, rerun |
| `pattern_demoted`, and `failed_gates` names fastrelax `total_score`/`fa_rep` | A relax that did not converge: the gate doing its job | Inspect that pose; if it looks healthy, the fastrelax bounds are next to calibrate |
| `pattern_demoted` on `metrics_reported` | An adapter failed to read a value it should have | Fix the adapter; this is the silent-failure case decision 0013 exists for |
| No `pattern_promoted` at all | Ledger state differs from the fold above | Stop; compare `cuda.jsonl` against `_record_evidence` |

## Afterwards

- **Analyse:** tabulate `graphs.jsonl` (trusted and scrutiny per run) and `results.jsonl` (qc and
  `failed_gates` per node). Per-task metrics are in `jobs/ledger.jsonl` under each `outcome`.
- **Record:**
  - a row in `$WORK_DIR/impress_a_runs/INDEX.md`;
  - an outcome section here;
  - CLAUDE.md "Known open risks";
  - backlog A12;
  - the deck's status lines, which still say the trusted path has never run.
- **Recalibrate:** add the run's packmin and fastrelax scores to the observed range in
  `toolkits/rosetta/SKILL.md`. That widens the evidence behind the fastrelax bounds, which are
  now the only integrity judgement on a pose.

## Outcome: job 22728140 (2026-10-07, 13m37s, COMPLETED 0:0, commit e9f44cd)

| Run | Admitted | Tasks | QC | Failed gates (all acceptance) |
|---|---|---|---|---|
| r0001 | provisional | 6/6 | suspect | none |
| r0002 | provisional, then **promoted** | 6/6 | fail | ipTM 0.395 |
| r0003 | **trusted** | 6/6 | fail | LigandMPNN confidence 0.394/0.391, shape complementarity 0.471 |
| r0004 | **trusted** | 6/6 | fail | pLDDT 0.364, ipTM 0.349 |
| r0005 | **trusted** | 6/6 | fail | LigandMPNN confidence 0.397, pLDDT 0.494, ipTM 0.360 |

- **Held:** promotion after r0002, three consecutive trusted cycles (no forced dry run, no
  cost cap), **no demotion**, and not one integrity failure. **Sustained trust is shown.**
- **The packmin change did its job:** r0005's packmin scored +808.5 and relaxed to -200.1. All
  five relaxes converged (fastrelax -493.7 to -200.1, `fa_rep` 75–190).
- **Missed: no plain `pass`.** All three trusted nodes fell short on quality. That was given
  ~80%, so it is a draw, not a defect. The acceptance rate is now 5 of 16 complete runs (~31%).
  The front is r0001's node, which cleared every gate but was `suspect`.
- **Missed: 5 cycles, not 6.** Not a draw: an **off-by-one**. The driver counted a Backtrack
  (one in every trust run) as a cycle, so `max_cycles: 6` gave 5 runs while the executor,
  counting runs, reported `cycles: 5`. Fixed in `policy/driver.py` (backtracks are free, but two
  in a row with no run between them stop the campaign), and pinned by
  `test_a_backtrack_does_not_spend_a_cycle`. Every earlier trust plan assumed 6 runs; that was
  wrong for all three jobs.

## Queued after (one variable each)

1. **`replicas: 2`**, same spec otherwise. This exercises the N-independent-lineages invariant,
   which has never run. Its pattern signature differs from the one-lineage pattern, so it starts
   untrusted. The untrusted cost cap is 10% of available budget. Check before submitting that a
   two-lineage graph fits under that cap; otherwise the policy's `on_rejected` silently shrinks
   it back to one lineage and the run tests nothing.
2. **A measurement superseding a prediction.** First fix the `PropertySource(name="mock_toolkit")`
   label that real metrics carry (`runtime/executor.py:265`).
