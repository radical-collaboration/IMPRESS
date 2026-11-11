# Campaigns

A campaign spec is one YAML file naming a goal, a chain of tools, a budget and the
thresholds a design has to clear. `impress-a run <spec>` drives it.

Most of the files here need a GPU allocation. One does not:

```bash
./scripts/dev_setup.sh                                          # once
source .venv/bin/activate
impress-a run campaigns/mock-small-molecule-binding.yaml --model D
```

That finishes in under a second on a laptop. The rest of this file is about what it is for
and which knobs to turn.

---

## 1. What `mock-small-molecule-binding.yaml` mocks

It is a surrogate of the six-stage chain the Delta arms run:

| real stage | what it really does | the surrogate | what the surrogate does |
|---|---|---|---|
| `rfd3_design` | RFDiffusion3 in an Apptainer container: diffuses a protein backbone around a ligand | `mock_rfd3_design` | draws `ss_fraction` from `diffusion_steps` and `difficulty` |
| `ligandmpnn_design` | LigandMPNN: designs a sequence for that backbone, picking the best of its own ensemble | `mock_mpnn_design` | draws a confidence from the backbone's `ss_fraction`, `temperature` and the ensemble width |
| `packmin` | PyRosetta PackRotamers + MinMover: prepares the pose for relaxation | `mock_packmin` | turns that confidence into a pre-relax `total_score` |
| `fastrelax` | PyRosetta FastRelax: relaxes the complex and scores the interface | `mock_fastrelax` | turns the pre-relax score into `total_score`, `fa_rep` and `interaction_energy` |
| `filter_shape` | PyRosetta ShapeComplementarity across the protein-ligand interface | `mock_filter_shape` | turns the interface energy into `shape_complementarity` |
| `boltz_predict` | Boltz-2 co-folding of the designed complex | `mock_boltz_predict` | turns the shape score into `complex_plddt` and `ligand_iptm` |

**The numbers are drawn, not measured.** Every surrogate hashes its parameters and its
upstream's metrics into a seeded RNG. They model no chemistry.

**The thresholds are the real campaign's**, copied from the real specs unchanged:

| gate | bar | role |
|---|---|---|
| `has_secondary_structure` | `ss_fraction >= 0.3` | integrity |
| `metric_in_range` | `ss_fraction >= 0.5` | acceptance |
| `metric_in_range` | `overall_confidence >= 0.4`, `ligand_confidence >= 0.4` | acceptance |
| `metric_in_range` | `total_score <= 0`, `fa_rep <= 500` | integrity (did the relax converge) |
| `metric_in_range` | `total_score <= -250`, `fa_rep <= 100`, `interaction_energy <= -8.0` | acceptance |
| `metric_in_range` | `shape_complementarity >= 0.55` | acceptance |
| `metric_in_range` | `complex_plddt >= 0.75`, `ligand_iptm >= 0.4` | acceptance |

So a reading that clears `complex_plddt >= 0.75` here cleared the bar the Delta arms
measure against, and the difference between an **integrity** failure (the tool broke; the
pattern's trust suffers) and an **acceptance** failure (the design fell short; trust is
untouched) is visible on a laptop. That difference is `docs/decisions/0013`.

The six surrogates declare `toolkit: mock`, which is load-bearing rather than tidy. Gate 6
classifies a tool by that field exactly, so a surrogate in a toolkit of its own would be
classified **real** and admitted by a campaign declaring `tool_delivery: real` - a chain of
random number generators reporting its draws as science. `tests/test_mock_smb.py` pins
both the classification and the refusal.

---

## 2. Running it

```bash
./scripts/dev_setup.sh              # once: creates .venv, installs BOTH projects editable
source .venv/bin/activate

impress-a tools                     # 18 tools, six of them this chain's surrogates
impress-a preflight campaigns/mock-small-molecule-binding.yaml     # 3/3 ok, 8 n/a
impress-a run campaigns/mock-small-molecule-binding.yaml --model D
```

Without the editable install, prefix with `PYTHONPATH=src` and use `python -m impress_a`:

```bash
PYTHONPATH=src python -m impress_a run campaigns/mock-small-molecule-binding.yaml --model D
```

**Preflight on this campaign checks three things and reports eight as `n/a`** - no stage of
it needs `$FOUNDRY_SIF_PATH`, `$MPNN_DIR`, `$BOLTZ_CACHE`, PyRosetta or `ml_collections`.
Run it against `delta-small-molecule-arms-smoke.yaml` and all eight come back.

**Which `--model`:**

| flag | what drives the campaign | needs a network? |
|---|---|---|
| `--model D` | the explicit policy: deterministic rules, no model | no |
| `--model B` | the heavyweight oracle. With no `--model-profile` it runs the **deterministic rehearsal** and says so | no |
| `--model A` | the four-node agentic loop. With no `--model-profile`, two of its nodes fall back to their rule cascades | no |
| `--model B --model-profile NAME` | a live endpoint from `models.yaml` | yes |
| `--model C` | **refused under `run`** (backlog C6). It needs `impress-a serve` in one process and `impress-a control` in another | - |

D and B are the interesting pair here, because they end for different reasons from the same
spec (measured, trust ledger cleared before each):

```
--model D   cycles 2   stop: every spec objective satisfied   nodes 2   front 1
--model B   cycles 8   stop: max_cycles=8 reached             nodes 8   front 3
```

The draws are **deterministic**: the same spec run twice returns the same metrics to the
digit. Only the four-character suffix on a node id changes, because that is a per-process
token and is deliberately not reproducible. To re-draw the whole campaign, set `seed_salt`
in the spec or `$IMPRESS_A_SEED_SALT` in the environment.

**Clear the trust ledger between comparisons.** It lives at `campaigns/_runs/_trust/` and
is *site-scoped on purpose*: promotion counts consecutive clean runs across runs, so a
second invocation of the same campaign starts with the pattern already trusted and its
nodes come back `pass` where the first run's came back `suspect`. Every number in this file
was measured after `rm -rf campaigns/_runs/_trust`.

---

## 3. The knobs

### 3a. Tool parameters - under `params:` in the spec

| knob | stage | what it does | what you will see change |
|---|---|---|---|
| `difficulty` | `mock_rfd3_design` | **surrogate-only; rfd3 has no such flag.** How hard this campaign is, 0.0-1.0 | 0.25 passes everything; ~0.55 misses the `ss_fraction` acceptance bar; ~0.7 fails the whole chain on acceptance; >0.75 fails the integrity floor and demotes the pattern |
| `diffusion_steps` | `mock_rfd3_design` | 20-200. Buys secondary structure | +0.30 of `ss_fraction` across its range and +0.09 of `complex_plddt` - it can pull a chain back over its bars after `difficulty` has pushed it under |
| `num_designs` | `mock_rfd3_design` | 1-64 | `num_models` only. The real adapter still keeps `cif_models[0]`, so the surrogate does not pretend selecting pays |
| `temperature` | `mock_mpnn_design` | 0.0-1.0. Diversity vs recovery | -0.40 of `overall_confidence` and -0.26 of `complex_plddt` across its range. At 0.5 about one lineage in ten misses the pLDDT bar; at 0.6, two thirds do |
| `batch_size` × `number_of_batches` | `mock_mpnn_design` | the ensemble to pick the best of | 8 → 1 costs 0.11 of confidence and 0.07 of pLDDT; 8 → 64 buys 0.15 of pLDDT back. Sublinear, as picking best-of-N is |
| `cycles` | `mock_packmin` | 1-5 | a lower pre-relax `total_score`, worth +0.08 of `complex_plddt` at the top - the cheapest rescue knob in the chain |
| `relax_cycles`, `nstruct` | `mock_fastrelax` | 1-8 each | `fa_rep` down, `interaction_energy` down; both at 8 is +0.08 of `complex_plddt` |
| `diffusion_samples` | `mock_boltz_predict` | 1-25, the ensemble to pick the best of | 1 costs 0.09 of pLDDT, enough that about one lineage in six misses the bar at otherwise default settings; 25 buys 0.07 back. This stage carries the tightest bar, so this is where a marginal chain is saved or lost |

Every one of these exists on the real tool too, **except `difficulty`**.
`tests/test_mock_smb.py::test_difficulty_is_the_only_parameter_without_a_real_counterpart`
is what keeps that list at one.

### 3b. Campaign knobs - top-level fields of `CampaignSpec`

| knob | what it does | what you will see change |
|---|---|---|
| `max_cycles` | runs the reasoner may be driven through | the `stop:` line, once something else is not ending it first. 8 here |
| `stagnation_limit` | consecutive informed runs with no front progress before giving up | at `difficulty: 0.70` this is what ends the run: `stagnation: front unchanged over 4 informed attempts` |
| `target_front` | how many **readings** over every bounded objective the Spec asks for | 1 stops on the first passing design; 10 runs to `max_cycles`. See experiment 2 |
| `replicas` | independent lineages per run - N `DesignNode`s, not N copies | nodes per cycle, and the **pattern signature**, so a new width starts untrusted. See experiment 3 |
| `concurrency` | experiments in flight at once | wall time, not outcome, at this scale |
| `budget` | the ledger gate 5 and the untrusted-pattern cap are checked against | shrink it and graphs start being refused. See experiment 3 |
| `objectives` | what the Pareto front ranks and which bars make a node feasible | front membership. A node failing a bounded objective is not on the front |
| `tool_delivery` | `mock` \| `real` \| `any` - gate 6 | set it to `real` here and every graph is refused at validation: `gate=tool_delivery` |
| `max_attempts` | bounded retry per experiment after a rejection | how many times the Planner gets to re-plan before the cycle is given up |
| `max_runs` | total submissions; 0 = unbounded | a second ceiling beside `max_cycles`, for a `conduct` reasoner that is not cycle-driven |
| `max_unproductive_runs` | backstop for runs exempted from the stagnation counter | nothing, unless the chain can never produce a bounded objective - then it is the thing that stops the burn |
| `max_failed_cycles` | consecutive all-failed runs before aborting | at `difficulty: 0.85` this is what raises `CampaignAborted: 3 consecutive all-failed runs` |
| `max_admission_failures` | executor-side cap on rejected admissions | binds any reasoner, including one that ignores `max_attempts` |
| `seed_salt` | distinguishes this campaign instance's draws from every other's | every drawn number. Empty reproduces the previous run exactly; set it (or `$IMPRESS_A_SEED_SALT`) and the whole campaign re-draws |

---

## 4. Three worked experiments

Each is a one-line edit to the spec. The before/after is measured, not predicted: run
`rm -rf campaigns/_runs/_trust` first, or the second run starts from the first one's trust.

### Experiment 1 - `difficulty`, and the two kinds of failure

`params.mock_rfd3_design.difficulty`, which is the one knob with no real counterpart.

| `difficulty` | cycles | stop | front | failed gates | trust ledger |
|---|---|---|---|---|---|
| **0.25** (shipped) | 2 | every spec objective satisfied | 1 | none | `clean` x2 |
| **0.55** | 1 | every spec objective satisfied | 0 | `metric_in_range[ss_fraction]` **acceptance** | `clean` x1 |
| **0.70** | 4 | stagnation: front unchanged over 4 informed attempts | 0 | `ss_fraction`, `ligand_confidence`, `shape_complementarity`, `complex_plddt`, `fa_rep` - **all acceptance** | `clean` x3 |
| **0.85** | - | `CampaignAborted: 3 consecutive all-failed runs` | - | `has_secondary_structure` **integrity**, plus seven acceptance gates | **`failure` x4** |

The row that matters is the last one. At 0.70 every stage in the chain is failing and the
trust ledger still records `clean`: those are *weak designs*, and decision 0013 says a weak
design must not cost a pattern its trust. At 0.85 the backbone drops under the 0.3 integrity
floor, which means *the tool produced nothing usable* - and now the ledger records `failure`
and the pattern is demoted. Two failures that look identical in the `front: 0` line and are
not the same event at all.

The 0.85 run exits non-zero. That is `max_failed_cycles: 3` doing its job, not a crash.

### Experiment 2 - `target_front`, which is backlog G11 on a laptop

Change `target_front: 1` to `target_front: 10`.

| `target_front` | cycles | stop | nodes | front |
|---|---|---|---|---|
| **1** | 2 | every spec objective satisfied | 2 | 1 |
| **10** | 8 | `max_cycles=8 reached` | 8 | 2 |

This is the defect G11 fixed, reproduced without an allocation. `target_front` sets
`SatisfactionRule.n` on every **bounded** objective, so the Spec is satisfied when ten
readings clear each bar rather than one. Before G11 the value was parsed, forwarded and
read by no code, and arm C of the first four-arm smoke ran 24 tasks and stopped at cycle 0
on "every spec objective satisfied". Here it is the difference between a two-cycle run and
one that uses its whole cycle budget.

Also visible in the 10 run: the pattern promotes partway through. The first three nodes come
back `suspect` and the last five `pass`, because the trust ledger logged three clean runs and
the interlock stopped marking the pattern provisional.

### Experiment 3 - `replicas`, the pattern signature, and the cost cap

Change `replicas: 1` to `replicas: 4`.

| run | cycles | nodes | front | pattern signature | verdicts |
|---|---|---|---|---|---|
| `replicas: 1` | 2 | 2 | 1 | `2bc0c4b1bb38885f` | suspect x2 |
| `replicas: 4` | 2 | 8 | 3 | `dcccc62b0b3ce256` | suspect x8 |

Two things to notice. **Four lineages, four distinct designs** - `replicas: N` means N
independent `DesignNode`s with their own seeds, not one design computed four times; the
front goes from 1 to 3 because there are now genuinely different candidates to be
non-dominated. And **the signature changed**, so as far as the trust ledger is concerned
this is a pattern nobody has run: every node comes back `suspect` again even though the
width-1 pattern had just been promoted. Pattern signatures ignore parameter *values* and
not graph *shape*, and breadth is shape.

**The 10%-of-budget cost cap does not bind at the shipped budget**, and saying otherwise
would be the easy mistake here: one width-4 pass declares 0.024 gpu-h against a cap of 0.4.
To see the cap work, shrink the budget in the same edit:

```yaml
budget:
  gpu_hours: 0.2
  cpu_hours: 0.2
```

| run | cycles | nodes | front | signatures seen |
|---|---|---|---|---|
| `replicas: 4`, budget 4.0 | 2 | 8 | 3 | `dcccc62b0b3ce256` |
| `replicas: 4`, budget 0.2 | 2 | **6** | 2 | `dcccc62b0b3ce256`, then `fb59b16d523e96d4` |

The width-4 graph is refused against the untrusted pattern's 0.02 gpu-h cap, the composer
narrows to three lineages, and the ledger records a *second* signature - which is the cap
visibly changing what ran, rather than failing the run.

Shrink the budget far enough and it stops the campaign before a single task runs. At
`gpu_hours: 0.05` / `cpu_hours: 0.05`, even one width-1 pass is over the cap:

```
cycles 0   stop: rejected at interlock: provisional pattern capped at 10% of available
                 gpu_hours (0.006 > 0.005)
```

---

## 5. What this campaign cannot tell you

- **The numbers are drawn, not measured.** `complex_plddt: 0.93` here is a hash of some
  parameters. It is evidence about the engine and about nothing else. For what the real
  chain has actually produced, see `CLAUDE.md`'s "Known open risks" and
  `docs/limitations.md`.
- **The timings are not timings.** Each surrogate returns in microseconds and declares a
  `cost_model` of 0.002 gpu-h or cpu-h. Those figures are sized so a laptop budget never
  binds; they are not a prediction of anything. The real specs carry measured figures with
  their own provenance comments.
- **`n` counts readings, not distinct designs.** `target_front: 10` is satisfied by ten
  readings over each bar. Nothing here clusters sequences, and at one scoring task per
  lineage the two track closely enough to stop on - but the stopping rule is not the score.
- **A node that FAILED QC can still satisfy the Spec.** Visible in experiment 1's
  `difficulty: 0.55` row: the run stops on "every spec objective satisfied" with an **empty
  front**. The front correctly excludes the FAILed node, but `DataRegistry.ingest` records
  every task's metrics regardless of verdict and `SatisfactionRule` reads them, so the
  downstream metrics - which did clear their bars - satisfied the Spec on their own. A stop
  reason and an empty front disagreeing like that is a real gap in the engine, not an
  artefact of the surrogate; it is simply cheaper to see here. Not fixed on this branch:
  changing what satisfaction counts would change how the pre-registered Delta arms stop.
- **A surrogate chain under `tool_delivery: real` is refused on purpose.** Gate 6, and the
  reason these tools live in the `mock` toolkit at all.

## 6. Running the knobs as a sweep instead of by hand

The three experiments above are the knobs one at a time, typed. `impress-a mock-lab` is the
same campaigns run across a grid, with the executor's own provenance flattened into CSVs and
six figures drawn from them - four arms and five swept knobs, in about half a minute:

```bash
pip install -e ".[figures]"     # once; the sweep and collect stages do not need it
impress-a mock-lab
```

It writes to `campaigns/_runs/_analysis`. `docs/reference/mock-lab.md` has what each table
and figure holds, which of its numbers mean anything, and the three defects the sweep found
in the engine around the surrogate (backlog G14, G15, G16).
