# Next Delta run: make promotion reachable, then execute the trusted path once

The trusted path has never executed. That path means no forced dry-run, no provisional cost cap, a
normal QC verdict instead of auto-`suspect`, and concurrent instances allowed. Job 22702568 was
built to exercise it, and it did not get there. This plan fixes the reason first, then repeats
that run with one variable changed.

## What 22702568 showed

The run had 5 cycles, and all 30 tasks succeeded. The site ledger nevertheless recorded
`failure, clean, failure, failure, clean` for pattern `f5b21d82924fbcd0`, so nothing was promoted.
Reconstructed from the recorded metrics, because provenance logs only the verdict:

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

## Code change (before the run)

1. **`tools/spec.py::GateSpec`**: add `role: Literal["integrity", "acceptance"] = "integrity"`.
   The default is the safe one: a gate nobody classified keeps blocking trust. An unknown role
   is a load-time error, like every other spec defect.
2. **`core/qc.py::GateResult`**: add `role: str = "integrity"`. In `tools/agent.py:114`, copy
   `g.role` onto each result (`.model_copy(update={"role": g.role})`). That edit is line-neutral.
3. **`exec/dispatch.py`**: add `ExecutionResults.integrity_passed`: no task failures, and no
   integrity-role gate FAILed. `all_gates_passed` stays as it is, because
   `policy/explicit.py:76` and `policy/agentic.py:114` use it to judge design quality, which is
   correct for them.
4. **`runtime/executor.py::_record_evidence`**: use `integrity_passed`.
5. **Provenance**:
   - add `"failed_gates": [{gate, role, observed, threshold}]` to each `results` record, so the
     next run explains itself rather than needing the reconstruction above;
   - log the admission's scrutiny (trusted/provisional, forced dry-run, cost cap); today the
     dry-run skip is not visible anywhere.
6. **Spec classification.** Mark these five as `role: acceptance`:
   - ligandmpnn `overall_confidence` and `ligand_confidence`
   - filter_shape `shape_complementarity`
   - boltz `complex_plddt` and `ligand_iptm`

   The rest stay integrity: `output_present`, `has_secondary_structure`, packmin
   `total_score < 1000`, fastrelax `total_score < 0` and `fa_rep < 500`. Those are "the tool
   broke" bounds, not taste.
7. **Docs**:
   - new ADR `docs/decisions/0013`, amending 0003's "clean run";
   - `docs/reference/architecture.md` (the interlock section);
   - README lines 95–97;
   - `docs/reference/authoring-tools.md` (the `role` field);
   - `docs/limitations.md`: **trust now rests on the structural gates, which are thin**
     (backlog B). A tool that silently produced confident garbage could already promote; one
     that produced *low-confidence* garbage now can too.
8. **Deck**: steps 3–5 move `exec/dispatch.py` and `runtime/executor.py` anchors. Run
   `slides/check_anchors.py`, fix the anchors in `check_anchors.py`, `build_deck.js` and
   `CODE_FOR_DECK.md`, then rebuild using the procedure in the `build_deck.js` header.

### Tests
- **Mock campaign:** a pattern whose only failures are acceptance gates promotes after 3 runs,
  and its failed nodes are still off the front.
- **`mock_noodle`:** its `has_secondary_structure` failure is an integrity failure and still
  demotes. This is the regression that matters.
- **`test_real_toolkits`:** pin the classification. Exactly the five gates above are acceptance.
- **Replay:** fold 22702568's recorded metrics through the new rule. It should promote at r0003.
  That is the offline prediction the run is checked against.
- **Load errors:** an unknown `role` is rejected, and an omitted `role` means integrity.

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
- **r0003–r0006 are admitted trusted**: `"trusted": true` in `graphs.jsonl`, the heartbeat shows
  `trusted`, the scrutiny log shows no forced dry-run and no cost cap;
- trusted nodes that pass acceptance get verdict **`pass`**, the first `pass` ever on real
  hardware rather than `suspect`;
- nodes that miss acceptance are `fail` and absent from the front, with `failed_gates` naming why;
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

## After this

These are queued, one variable each, not folded into this run:

1. **`replicas: 2`**, same spec otherwise. This exercises the N-independent-lineages invariant,
   which has never run. Promotion must hold first, because the untrusted-pattern cap would
   otherwise serialise it.
2. **A measurement superseding a prediction.** The calibration machinery is untested against
   reality.

Also noticed while reading `_absorb`: real tool metrics are stored on nodes with
`PropertySource(name="mock_toolkit", authority=10)`. That is the wrong provenance label for
Delta results, and it matters once item 2 compares predicted values against measured ones.
