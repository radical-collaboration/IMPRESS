# Pre-registration: the four-arm reasoner comparison

**Frozen before any arm runs.** The sha256 of this file is recorded in every arm's
`manifest.json` as `prereg_sha`, and `impress-a compare` refuses to publish a comparison whose
arms disagree about it. A comparison whose rules were chosen after the numbers arrived is not a
comparison.

> **Amendment 1, 2026-11-08, before any arm had run.** Three arms now carry a live client.
> `--model-profile` reached model B's oracle alone; it now fills model A's per-node seam too
> (backlog H1's last half), and arm C's caller is an `impress-a control` sidecar driving the
> served campaign with that same client. The endpoint is Reflection Beam
> (`Beam-501B-A23B`, the `beam` profile). **D is unchanged and remains the control**: it has no
> reasoner seam to fill. What this amendment touches is §6's A-vs-D row, §7's arm-C
> attribution, §9's H2 entry, §10's procedure and §14's first claim; the hypothesis, the tiers,
> the endpoint, the distinctness rule, the decision rule and every threshold are untouched.
> Made before the first arm was submitted, which is the only time an amendment is legitimate -
> afterwards it voids the comparison, and `compare`'s `prereg_sha` guard is what makes that
> mechanical rather than a matter of trust.

Spec: `campaigns/delta-small-molecule-arms.yaml`, one file, four arms, `--model` the only
difference. Smoke: `campaigns/delta-small-molecule-arms-smoke.yaml`, identical science.

---

## 1. Hypothesis

Under one fixed workflow, target, draw sequence and budget, the choice of reasoner changes the
rate at which distinct physics-passing designs are produced per node-hour by a factor
detectable at this allocation size.

**D is the control.** A, B and C are each tested against it. D is reproducible end to end, so
it is the baseline the other three have to justify their cost against.

## 2. Tiers, frozen

Computed from the metrics on disk, joined by `(run, lineage)` - never from a node's cached
properties. `analysis/tiers.py` holds the definitions and `T2_THRESHOLDS`/`T3_THRESHOLDS` are
the executable form of this section.

| Tier | Meaning | Condition |
|---|---|---|
| **T1** | plumbing | all six tools ran, no integrity gate failed, **every declared metric reported** |
| **T2** | physics | T1, and every `PROD` threshold except the fold |
| **T3** | the Goal | T2, and the fold bar and the ligand interface |

T2: `total_score <= -250`, `fa_rep <= 100`, `interaction_energy <= -8`,
`shape_complementarity >= 0.55`, `ss_fraction >= 0.5`. T3 adds `complex_plddt >= 0.75` and
`ligand_iptm >= 0.4`.

Every number is upstream's own calibrated `PROD` instance in
`examples/small_molecule_binding/run_small_molecule_binding.py`, verified against that file
rather than against a copy of it. Two things that must appear beside every T3 figure:
`complex_plddt` is PROD's `fold_min_plddt: 75.0` **rescaled** (that is a 0-100 figure and this
metric is the 0-1 one), and `ligand_iptm >= 0.4` is **stricter than PROD**, which leaves that
gate off entirely.

**Job 22692304 - this project's best run, `6/6 tasks ok`, every stage passing its gates - is
T0**, because `interaction_energy` was computed by nothing. That is pinned as a test, and it is
the measure of how much the calibration changed.

## 3. Primary endpoint

**Distinct T2 designs per billed node-hour**, charging every node an arm held:

    C_T2 / (AllocNodes x gpus_per_node x Elapsed_h)

`AllocNodes` and `Elapsed` from `sacct --json`, written **inside the job**, never from the
campaign's own clock and never from a later query. Scored over a common window
`T_cut = 3.25 h` measured from each arm's **first task start**, so unequal Dragon startup
cannot bias an arm; the full-allocation figure is reported beside it.

`C_T3` is reported as the Goal's literal answer, with a **pre-registered expectation of 0**.
Across every run this project has recorded, `complex_plddt` is 0.426 / 0.486 / 0.507 against a
0.75 bound: 0 of 3.

## 4. Distinctness

Clustered, not counted. Single-linkage clusters at amino-acid identity `>= theta`, then a
structural merge of equal-length pairs. The exact-identity count is reported beside it as the
**upper bound**, over the same population, and the gap between the two says how much of a yield
is re-draws.

`theta` is set **from the smoke**, as the 95th percentile of the pairwise identity distribution
of *same-seed* pairs, so anything a re-draw of one seed can produce collapses to one cluster.
Default 0.90, frozen at the go/no-go.

G7 measured the over-count this removes: same-seed designs share length exactly, have median
Cα RMSD 2.4 Å between them, and are never byte-identical - roughly a 3x over-count if unique
sequences are counted.

**The structural merge is Cα RMSD, not TM-score, and a report must say so.** This section used
to say TM >= 0.8; there is no TM-score implementation here that could be validated, so the
merge ships a Kabsch-superposed Cα RMSD at 2.5 Å and `Clustering.criterion` records which ran.
Sequences come from the LigandMPNN FASTA **on disk**, located through the executor's own job
ledger, never from a reasoner's bookkeeping.

## 5. Decision rule

`C_arm ~ Poisson(mu)`, `log mu = b0 + b_arm + log(node_h)`; three contrasts (A, B, C against
D), Holm-corrected at family alpha = 0.05. For two arms that reduces exactly to a log rate
ratio with a Wald interval, which is what `analysis/tiers.rate_ratio` computes - three lines,
no scipy, hand-checkable.

**An arm wins iff its Holm-adjusted 95% interval lies entirely above 1.3 AND its point estimate
is at least 1.5.**

**Stated now, before the numbers:** at an expected `C_T2` near 14 the interval spans roughly
x/÷ 2.1, so **this experiment can only detect a >= 2.2x difference**. One allocation per arm
gives zero degrees of freedom for overdispersion, and A11's measured 3.2x wall-time swing means
between-allocation variance is **not estimable here**. The honest claim is the interval, not the
p-value. A smaller effect needs 2 replicates per arm (32 node-h), which is out of scope.
`impress-a compare` prints this figure from the counts it got.

## 6. Uninformative outcomes, pre-registered

- All arms `C_T2 = 0` => report the funnel, the cost and the plumbing only.
- An arm shown degraded, fallen back, or to have executed a mock tool => **void**, named as
  void, dropped. `impress-a compare` exits non-zero rather than publishing it.
- An arm terminating before 80% of usable wall clock for any reason other than its own stop =>
  its yield figure is void.
- **A and D differing by more than the engine's nondeterminism band => the one-variable claim
  fails.** A was behaviourally D before phase 9, so this doubled as the only positive control
  this design had for an uncontrolled variable. **Amendment 1 retires it as a control.** A now
  differs from D in three named ways - it retires an objective the Toolkit cannot measure, it
  moves the diversity knobs, and its four nodes are live calls to Beam - so an A-vs-D
  difference is the thing being measured rather than a check on the harness. What replaces it
  as the positive control is the **null arm's absence**: there is none, and this design has no
  residual check for an uncontrolled variable. Stated plainly rather than papered over. The
  nearest substitute is arm C against arm B, which share a client and a profile and differ
  only in process topology; a large B-vs-C gap is a finding about the control plane, not about
  reasoning.
- Zero `interaction_energy` values => T2 and T3 are undefined.
- Arms not co-resident within +/- 30 min => flagged.
- **An asserted pattern demoting in any arm => the assertion was wrong**, and every figure
  derived from an asserted-trusted admission in that arm is reported as such.
- **Admissions-under-scrutiny differing by more than 2x between arms => the yield comparison
  carries a throttle, not only a decision quality.** An arm that composed novel shapes paid the
  forced dry-run, the 10% cap and one-instance-in-flight; the contrast must be reported beside
  the subset restricted to asserted-shape admissions.

## 7. Attribution: Specifier or Planner

**Specifier.** The composed stage set per cycle, the number of distinct pattern signatures ever
composed, unproducible objectives, and the objectives emitted at campaign start. If an arm's
Specifier emits objectives differing from the spec's four, **the arm is void for the primary
endpoint** - otherwise the arms are not optimising the same thing.

**Planner.** Per-tool parameter values per cycle (from `stages` provenance's `mappings`, which
is why that record carries params at all), `replicas` requested, `parent_node` chosen, backtrack
frequency, `replan` behaviour, **admissions-under-scrutiny**, demotions of an asserted pattern,
and stage pass rates *conditioned on* the parameter vector.

`C_T2`, cost per design and time-to-tenth are **joint and not attributable**.

**Arm C, after amendment 1.** The served process holds the inbox halves and does no reasoning;
the `impress-a control` sidecar is the reasoner, and it drives with **model B on the same
`beam` profile arm B runs in-process**. So arm C is not a fourth model - it is arm B's model
reached over the control plane, and the only difference it can claim is the arrangement.
Read every arm-C figure that way: a B-vs-C gap is plane latency, directive round-trips and the
`--caller-timeout` boundary, never decision quality. Reported as such, or not reported.

## 8. The two dangerous failure modes

> A model-B arm that silently executed mock tools on a GPU allocation, or a model-C arm that
> silently fell back and was reported as model C, is what this design most needs to exclude.
> Both are silent: a mock chain completes `6/6 tasks ok` with plausible metrics, and a
> fallen-back C arm is byte-for-byte a D campaign.

Each gets structural prevention **and** a positive check.

*Mock on GPU.* `_build_b` forwards `stages`; `RehearsalOracle` has no chain of its own and
refuses without one; **gate 6** refuses a mock-toolkit node under `tool_delivery: real`. The
harness then asserts per arm that the tool set is exactly the six real tools and that no task
ran a mock tool. An arm failing this is not published.

*Silent fallback.* Model C's planner defaults to `on_timeout="stop"`, a fallback must be
declared to exist at all, and taking one writes a `caller_timeout` transition naming it.
`impress-a run --model C` is refused outright. The harness requires zero degraded events, and
counts directives per cycle.

## 9. Prerequisite gate

**Blocks the smoke.** X1 (the campaign's `max_cycles` reaches the reasoner) · H3 (a planner
varies a real tool's parameter) · phase 8's adapter selection, with internal sampling at 8 where
the adapter selects and the declared cost and walltime honest at that setting · **H2's live
client probed on a login node for BOTH live autonomous arms** - `--model B` and `--model A`,
each against `campaigns/mock-stabilize.yaml`, each showing a live model id every cycle and
**zero degraded turns**, run long enough to take a corrective retry. One turn is not a probe:
an endpoint that drops `reasoning_content` passes the first turn and fails the second, which
is how 144 degraded turns were once reported as a healthy run. A's is the one that matters,
because its seam has never carried a client · **arm C's sidecar reaching the plane**: `serve`
writes its URL and `impress-a control` connects, which has no test and no prior execution
anywhere · C5+C6 (`serve`/`control`, fail-closed C) ·
G4+G5 (the thresholds, and which interface `filter_shape` measures) · G7 (a recorded seed salt) ·
G1 (`stagnation_limit > max_cycles`, with the characterization tests untouched) · A10 (GPU
pinning on **both** execution loops, and the budget raised rather than the cost models retuned) ·
A6 (`impress-a preflight --quick` in the launcher; the deep form once on a login node) ·
E1/gate 6 · **`impress-a validate-tasks` passing on every Task of the chain** · and
**`impress-a trust --assert` applied to every arm's ledger** at width 1 and width 4, with a
reason naming the validation job.

**Blocks production.** A8 (refusal, and no tail truncation) · G8 (instrumentation) · A11 (budget
sized so gate 5 and the untrusted cap cannot bind - **do not retune the cost models**) · A5
(keep the startup/teardown bounds; a startup timeout voids the arm) · per-arm trust dirs.

**Deferred.** H1's live client · H6 · B1 · C1-C4 · C7 · D1-D7 except D6 · F1-F4.

## 10. Procedure

```bash
export SBATCH_ACCOUNT=<project>-delta-gpu
export WORK_DIR=/work/nvme/<project>/$USER        # MUST be nvme: pyrosetta imports in 471 s off HDD
export IMPRESS_A_ARMS=A,B,C,D
export IMPRESS_A_EXPERIMENT=arms-smoke-$(date +%Y%m%d)
export IMPRESS_A_SEED_SALT=${IMPRESS_A_EXPERIMENT}
# Amendment 1. The profile reaches arms A, B and C; D has no seam and ignores it. The key must
# be in the job's environment, not only in the submitting shell.
export IMPRESS_A_MODEL_PROFILE=beam
export REFLECTION_API_KEY=...
impress-a preflight campaigns/delta-small-molecule-arms-smoke.yaml     # deep, login node, 0 FAIL
impress-a run campaigns/mock-stabilize.yaml --model B --model-profile beam   # H2, both arms
impress-a run campaigns/mock-stabilize.yaml --model A --model-profile beam

# 1. Per-Task validation on real hardware, BEFORE any arm and before any assertion.
sbatch --partition=gpuA40x4-interactive --time=00:40:00 \
       --job-name=impress_a_validate_tasks \
       scripts/delta_validate_tasks.sh campaigns/delta-small-molecule-arms-smoke.yaml

# 2. Only once step 1 is clean: assert trust per arm, citing step 1's job id.
for M in A B C D; do
  IMPRESS_A_TRUST_DIR=${WORK_DIR}/_trust_arms/${IMPRESS_A_EXPERIMENT}/${M} \
  impress-a trust --assert campaigns/delta-small-molecule-arms-smoke.yaml \
      --replicas 1 --replicas 4 \
      --reason "proven toolkit from examples/small_molecule_binding; validate-tasks job <id> clean"
  IMPRESS_A_TRUST_DIR=${WORK_DIR}/_trust_arms/${IMPRESS_A_EXPERIMENT}/${M} \
  impress-a trust --list        # must show both shapes as asserted, 0 demotions
done

# 3. The four arms.
sbatch --array=0-3 --partition=gpuA40x4 --time=01:00:00 \
       --job-name=impress_a_arms_smoke \
       scripts/delta_gpu_run.sh campaigns/delta-small-molecule-arms-smoke.yaml
```

4 node-h / **16 GPU-h**. Do **not** override `--output`: `impress_a_%j.out` expands per array
task, which is what the EXIT trap looks for.

**Arm C is one array index like the others, and the launcher knows it.** `impress-a run --model
C` is refused (C6), so `delta_gpu_run.sh` selects `serve` when the arm is C and starts an
`impress-a control` sidecar beside it; the sidecar waits for the 0600 `control_plane.url` that
`serve` writes, takes the campaign id from that file's own directory, and drives with
`--model B --model-profile beam`. Before amendment 1 the procedure above would have had
argparse kill arm C at launch with the other three already queued. Nothing here needs a second
submission, which is what keeps one submit time and one priority across the four arms.

**Production** is the same three steps against `delta-small-molecule-arms.yaml`, with
`--time=04:00:00` and a fresh `IMPRESS_A_EXPERIMENT`. 16 node-h / **64 GPU-h**. The trust
assertion is repeated against the production spec, because the signature is computed at that
spec's own declared width - but it cites the **smoke's** validation job, since nothing about the
Tasks changed between them. `git rev-parse HEAD` must match the smoke and
`git status --porcelain -uno` must be empty.

**One shared seed salt** across all four arms, deliberately: G7 measured the seed as the
dominant variance component (same-seed median TM 0.82 against 0.28 across seeds), so sharing it
removes "arm B drew luckier backbones" as an explanation at an MDE already as coarse as 2.2x. It
is variance reduction, not exact pairing - rfd3 is not reproducible to coordinates (median Cα
RMSD 2.4 Å) - so the paired subset is a secondary, lower-variance analysis.

**Per-arm trust dirs are required, not optional.** Sharing one would let four concurrent
processes each admit an instance of an untrusted signature, breaking one-instance-in-flight
*across processes*, and one arm's evidence would subsidise the other three. Each dir is seeded
identically by `trust --assert`, so no arm spends allocation re-earning trust on a proven
Toolkit. Three consequences on the record: promotion stops being an experimental outcome (there
is nothing to promote for an asserted shape, and `on_clean_run` returns False for a trusted
record, so no phantom evidence accrues); "cycles to first trusted admission" is dropped as a
secondary endpoint, replaced by **admissions-under-scrutiny** and **demotions of an asserted
pattern**; and A10 stops binding, because width 4 could never earn trust under a realistic
budget when the signature includes replica multiplicity.

## 11. Smoke abort criteria

Stop and fix; do not proceed. Any Task failing an integrity row in step 1 · any arm whose ledger
does not show both asserted shapes, or shows a demotion of one · any mock-toolkit task · any arm
C fallback or directive-less cycle · a control-model log line disagreeing with `manifest.json` ·
a width-4 run producing fewer than 4 `DesignNode`s, or two lineages with identical metrics · two
lineages sharing a GPU index · zero finite `interaction_energy` · **any** budget/interlock/
objectives rejection (the budget was sized not to bind and the shapes were asserted, so one
means the sizing or the assertion is wrong) · any arm stopping on stagnation, a default
`max_cycles`, or the admission-failure cap · fewer than 3 cycles in 40 min · Dragon startup over
600 s.

## 12. Go/no-go for production

Every row, or no production run.

`validate-tasks` exited 0 with every Task's integrity rows clean and its per-Task table on file
- this is the row the trust assertion rests on, so it is first · every arm's ledger shows both
asserted shapes marked `asserted` rather than earned, with zero demotions, and `graphs`
provenance shows r0001 admitted trusted with no forced dry-run and no cost cap ·
admissions-under-scrutiny recorded per arm · zero mock tasks · arm C: one directive per cycle,
zero fallbacks · arm B: live model id every cycle, zero degraded · control-model log line matches
`manifest.json` · >= 6 cycles per arm with no stagnation/default-`max_cycles`/budget/interlock/
admission-cap stop · **every width-4 run produced 4 `DesignNode`s with distinct metrics** (A10's
independence invariant, first execution) · four distinct GPU indices and >= 2 GPUs busy
simultaneously · finite `interaction_energy` on >= 95% of completed fastrelax tasks · all six new
acceptance gates seen firing on real numbers · `pytest tests -q` green · per-task timestamps and
`cost_measured` on 100% of tasks with `cost_measured/cost_estimated` in [0.05, 1.0] for every
tool - **above 1.0 means a declared figure is below measurement and gate 5 would start refusing
real work** · `sacct.json`, `seff.txt`, `gpusample.csv` present · harness clean on all four dirs
with its own suite green · **theta frozen** in a commit · `p_T1 >= 0.6`.

And the tier decision, computed from the 8-sample measurements rather than the one-sample
baseline:

- `p_T2 >= 0.06` => proceed as planned.
- `0.02 <= p_T2 < 0.06` => raise to 1 node x 8 h per arm (32 node-h) with a recorded
  justification.
- `p_T2 < 0.02` => **no-go on the yield comparison.** Re-scope to a plumbing-and-contract
  comparison on T1 per node-h, decision-layer share and refusal behaviour, and report it as
  such.

## 13. Feasibility, and what is unmeasured

At **one** sample per stage: measured per-stage medians give a 173 s serial chain (matching job
22692304's 2 m 53 s); at width 4 with pinning, ~230 s per run; 225 usable minutes => ~58 runs,
~232 draws per arm, 0.069 GPU-h per draw attempted. For `P(X >= 10) >= 0.9` you need
`N ~ 14/p`, so at 58 draws per node-h the threshold is **`p* ~ 0.06`**. Best estimates:
`p_T2 ~ 0.27 x 0.67 x 0.33 ~ 0.06` - at the boundary, before the unmeasured
`interaction_energy` factor, which can only lower it - and `p_T3 <= 0.04` with a point estimate
of 0. **So at one sample per stage, ten T3 designs is not reachable in a 4 h 1-node arm**: at
`p_T3 = 0.01` the Goal needs 24 node-h *per arm*.

At **8** samples per stage this arithmetic does not hold, and it must be **re-measured rather
than re-derived**. Three effects move in different directions and only their product matters:
cycle time rises, sublinearly on the GPU stages (that is the whole reason for the setting);
draws per cycle stay ~1 per lineage, because each stage selects its best member rather than
fanning out, so raw draw count *falls*; and `p` per draw should rise, which is the point - the
reference's median pLDDT of 94.4 comes from best-of-N plus refinement.

The product is **unmeasured** and this document does not guess it. The smoke measures the
8-sample cycle time, and the go/no-go's tier decision uses that and the measured `p_T2` instead
of the baseline numbers above. **If the smoke's cycle time and `p_T2` imply fewer than
~14/`p_T2` draws in 4 h, the sizing is raised there and not after the fact.** Two figures to
watch for a negative result: a per-cycle wall clock more than ~3x the 230 s baseline means the
batch is not amortising, and a GPU-busy share that fails to rise above the <= 17% already
measured means the batch never reached the device.

## 14. What this experiment cannot say

The ten-sequence Goal is **probably not reachable** at this allocation size, and the go/no-go
routes to a plumbing-and-contract comparison if the smoke says so. That is a stated outcome, not
a surprise.

**Amendment 1 makes A, B and C live**, so an A-vs-B difference is now a difference between two
*shapes* of use of one model, and not between two models. **Measured on the login-node probe,
both shapes cost two calls per cycle.** Model A has four nodes but only two of them call the
model - `hypothesize` and `select_tasks`; `analyze` and `parameterize` are deterministic and act
on the strategy the node before them chose. So the difference is what is asked, not how often:
A splits a strategy choice from a task selection and derives the rest by rule, while B answers
`SPEC_SCHEMA` and `STAGE_SCHEMA`. An A-vs-B gap is a finding about prompt decomposition at equal
call cost. Nothing here compares Beam to another vendor, and no figure from this
experiment says anything about which model to use; it says how to spend one. A, B and C
sharing a client is also why their degraded-turn counts must be read together: one endpoint
hiccup shows up in three arms at once, and a correlated dip is a fact about the endpoint rather
than about three reasoners.

And one allocation per arm cannot estimate between-allocation variance, which A11 measured at 3.2x
on wall time alone - so an arm that wins by less than 2.2x has not been shown to win.
