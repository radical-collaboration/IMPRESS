# Next Delta run: make promotion reachable, then execute the trusted path once

The trusted path has never executed. That path means no forced dry-run, no provisional cost cap, a
normal QC verdict instead of auto-`suspect`, and concurrent instances allowed. Job 22702568 was
built to exercise it, and it did not get there. This plan fixes the reason first, then repeats
that run with one variable changed.

## What 22702568 showed

The run had 5 cycles, and all 30 tasks succeeded. The site ledger nevertheless recorded
`failure, clean, failure, failure, clean` for pattern `f5b21d82924fbcd0`, so nothing was promoted.
Per-gate results, from the task outcomes in `jobs/ledger.jsonl`. The provenance `results`
log carried only the verdict, which is why this took digging:

| Run | Verdict | Gates that failed |
|---|---|---|
| r0001 | fail | boltz `complex_plddt` 0.486 < 0.5 and `ligand_iptm` 0.327 < 0.4 |
| r0002 | suspect | none |
| r0003 | fail | ligandmpnn `overall_confidence` 0.355 < 0.4 and filter_shape `shape_complementarity` 0.519 < 0.55 |
| r0004 | fail | boltz `complex_plddt` 0.426 < 0.5 |
| r0005 | suspect | none |

`_record_evidence` (`runtime/executor.py`) counts a run as clean only when **every** gate passes,
the design-quality thresholds included. Every tool worked in every cycle; three designs simply
fell short. Promotion was therefore a function of how hard the target is.

At the observed all-gates pass rate of about 43% (3 of 7 complete runs), a 6-cycle campaign has
a ~17% chance of ever admitting a trusted graph, and even odds need ~15 cycles. Rerunning
unchanged would mostly buy another 13 minutes of the same evidence.

**Ruling (2026-10-07):** only *integrity* gates feed the trust ledger. *Acceptance* gates still
FAIL the node and keep it off the front, so that invariant is untouched, but they no longer
reset trust. The interlock asks "did this composition behave?", not "was this design good?".

## The change (implemented on `integrity-gates`; decision 0013)

- **Gate roles.** Each QC gate in a spec has a `role`, either `integrity` (the default) or
  `acceptance`. `_record_evidence` now counts a run as clean when no task failed and no
  integrity gate failed. Acceptance failures still FAIL the node and keep it off the front.
- **Reclassified as acceptance**, exactly these five: LigandMPNN `overall_confidence` and
  `ligand_confidence`, filter_shape `shape_complementarity`, and Boltz `complex_plddt` and
  `ligand_iptm`. Everything else stays integrity.
- **Fabricated zeros removed.** Two known-bad fixtures had been caught only by those thresholds,
  and both recorded a run *breaking*: Boltz with no ligand chain, and an unparsed LigandMPNN
  header. In both, the adapter wrote 0.0 for a value it never read. Adapters now omit such
  values. A new integrity gate, `metrics_reported`, catches the omission, and `ToolSpec`
  validation refuses an acceptance threshold with no presence check behind it.
- **Provenance.** `results.jsonl` records `failed_gates` (with roles) per node, and
  `graphs.jsonl` records each admission's full `scrutiny`: forced dry-run, cost cap, and
  suspect marking.
- **Replay.** Feeding 22702568's recorded per-task metrics through the new rule
  (`tests/test_validation.py::test_replaying_job_22702568_promotes_at_its_third_run`) promotes
  at r0003. The old rule reproduces the recorded fail/pass/fail/fail/pass exactly.

## The run

**One variable:** the meaning of "clean". Everything else matches 22702568:
- the same spec, `campaigns/delta-small-molecule-trust.yaml`, unedited (`max_cycles: 6`,
  `replicas: 1`, `concurrency: 1`);
- the same allocation: 1 node, `gpuA100x4-interactive`, 1h;
- the same site ledger, left in place. It is evidence, and deleting it would make the result
  harder to read.

```bash
export WORK_DIR=/work/nvme/<project>/$USER
impress-a preflight campaigns/delta-small-molecule-trust.yaml
sbatch --partition=gpuA100x4-interactive --time=01:00:00 \
       scripts/delta_gpu_run.sh campaigns/delta-small-molecule-trust.yaml
```

### Prediction, stated before submitting

The ledger currently folds to `clean_runs=1`, because its last event was `clean`. Integrity has
held on every complete run so far, so:
- r0001 and r0002 are integrity-clean, and `pattern_promoted` is logged after **r0002**;
- **r0003–r0006 are admitted trusted**. `graphs.jsonl` shows `"trusted": true` with
  `scrutiny: {force_dry_run: false, cost_cap_fraction: null, mark_suspect: false}`, and the
  heartbeat shows `trusted`;
- trusted nodes that pass acceptance get verdict **`pass`**, the first `pass` ever on real
  hardware rather than `suspect`;
- nodes that miss acceptance are `fail` and absent from the front, and their `failed_gates`
  carry only `role: acceptance` entries. Any `role: integrity` entry means the prediction failed
  (see below);
- six cycles at ~2.5 min each, plus startup, comes to about 18 minutes.

### Reading the outcome

| Observed | Meaning | Next |
|---|---|---|
| Promoted after r0002, trusted cycles complete | The trusted path works. Record it and move on | Replicas (below) |
| Promoted, but a trusted cycle errors | The first real bug in a path that has never run, and the point of the exercise | Diagnose from `failed_gates` and the logs, fix, rerun |
| An integrity gate fails | Demotion is *correct*; `failed_gates` names the tool | Investigate that tool, not the interlock |
| No `pattern_promoted`, and no integrity failure | The change did not take effect | Stop; check the ledger events against `_record_evidence` |

This is also the first real use of the new run-directory layout
(`<jobid>_<campaign>/manifest.json`, `slurm.out` moved in on exit). Check it, but it is
infrastructure, not the variable under test.

## Outcome: job 22726105 (2026-10-07, 13m41s, COMPLETED 0:0, commit 5629a9a)

| Run | Admitted | Tasks | QC | Failed gates | Ledger |
|---|---|---|---|---|---|
| r0001 | provisional | 6/6 | suspect | none | clean |
| r0002 | provisional | 6/6 | fail | Boltz pLDDT 0.475, ipTM 0.389 (acceptance) | clean, **promoted** |
| r0003 | **trusted** | 6/6 | fail | LigandMPNN confidence 0.377 (acceptance) | - |
| r0004 | **trusted** | 6/6 | fail | **packmin total_score 1064.5 (integrity)**, pLDDT 0.498 | failure, **demoted** |
| r0005 | provisional | 6/6 | fail | pLDDT 0.417, ipTM 0.382 (acceptance) | clean |

- **Held:** promotion after r0002, exactly as predicted. **The trusted path executed for the
  first time** (r0003, r0004), with `scrutiny` confirming no forced dry-run and no cost cap.
- **Missed:** r0005 and r0006 were predicted trusted. r0004 tripped an integrity gate.
- **Missed:** no plain `pass`. The only node to clear every gate (r0001) was untrusted, so it was
  `suspect`. The front is that single node.
- **Diagnosis:** the integrity failure was packmin's `total_score <= 1000` bound over a
  +1064.5 pre-relax pose that fastrelax took to -336.0 (`fa_rep` 119.1). It was a false alarm
  from a bound set one observation wide. **Fix:** packmin no longer bounds its own score, and an
  exploded pose is judged by fastrelax converging (its two integrity gates). Replaying this job
  with the fix stays trusted from r0002 on
  (`test_replaying_job_22726105_stays_trusted_once_promoted`).
- **Infrastructure:** the first real use of the new run layout. The manifest carried the real
  commit (clean) and exit 0, and `slurm.out` was moved in. Provenance `failed_gates` and
  `scrutiny` made the diagnosis possible from the logs alone.

## After this

Next: `plans/next-run-sustained-trust.md`. The items below are queued behind it.


These are queued, one variable each, not folded into this run:

1. **`replicas: 2`**, same spec otherwise. This exercises the N-independent-lineages invariant,
   which has never run. Promotion must hold first, because the untrusted-pattern cap would
   otherwise serialise it.
2. **A measurement superseding a prediction.** The calibration machinery is untested against
   reality.

Also noticed while reading `_absorb`: real tool metrics are stored on nodes with
`PropertySource(name="mock_toolkit", authority=10)`. That is the wrong provenance label for
Delta results, and it matters once item 2 compares predicted values against measured ones.
