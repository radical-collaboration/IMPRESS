# Done — making a real toolkit runnable

The four real toolkits were genuine integrations, not stubs — and further along than the docs
claimed. All 11 tools registered and validated, the canonical chain type-checked end to end, and the
Delta deployment scaffolding was complete: site profile, campaign specs, env setup, SLURM script,
Dragon entrypoint.

## The headline bug

**None of it was connected.** `sbatch scripts/delta_gpu_run.sh` launches `--model D`, which is
`ThresholdPolicy()` constructed bare, which falls back to its own default chain — the **mock** one.
`CampaignSpec` had no `stages` field and `load_spec` read none.

So the documented "real" run would load the real toolkits, validate them, and then execute mock tools
on a GPU allocation. `campaigns/_runs/` containing only `mock-*` directories confirmed it had never
been otherwise.

Worth remembering as a class of bug: every individual piece was correct and tested, and the seam
between them was never exercised because nothing ran the whole path.

## Rulings worth keeping

**Campaign parameters merge in the executor, not in the policy.** The ligand is campaign
configuration — it describes the scientific question — not a search decision. Merging it centrally in
`_admit_once` means an external directive and a `conduct` reasoner get it for free and no policy ever
has to know a tool's parameter names.

**`replicas` in a campaign spec is a CAP, not a default.** How wide a campaign may go is the
campaign's call; how wide to go within that is the policy's, and a policy shrinking its request after
a rejection must still shrink. Defaulting it to 1 in `load_spec` silently narrowed every existing
campaign to one lineage — caught because mock model D dropped from front 3 to front 2. Unset means 0,
meaning "the policy decides".

**The work directory defaults to the process CWD.** Not configured, not derived from `spec.root`. The
launcher already solved it: `delta_gpu_run.sh` cds to `$SCRATCH/$USER/impress_a_runs/$SLURM_JOB_ID` —
shared across nodes, per-job so concurrent campaigns cannot collide, and already where asyncflow
writes its session files. The adapters were overriding all of that with `tempfile.mkdtemp()`, which
is node-local; under Dragon multi-node a downstream task on another node gets a path that does not
exist, surfacing deep inside a science tool. Setting the value once, in the launcher that knows the
machine, means laptop / login node / batch job each get the right answer with no code aware of which.

**Breadth comes from `replicas`, not from each tool's internal sampling.** The adapters generated N
samples and kept only `[0]`, paying 4-5× GPU for one candidate. Internal N now defaults to 1.

## Bugs found that had never run

- **Boltz wrote invalid YAML** — `msa:` indented one level too deep, under the `sequence:` scalar.
  `yaml.safe_load` raises `ScannerError`; `boltz predict` would abort on spec parse before loading a
  model. The clearest possible evidence the adapter had never been executed.
- **`FastRelaxAgent` fabricated its count** — reported `nstruct` while writing one structure, and
  never passed `nstruct` to the worker at all. A declared, range-validated, budgeted parameter with no
  effect: exactly the silent-failure shape this project exists to catch, inside the project.
- **Rosetta workers crashed instead of failing QC** — an unconditional `json.loads` of a result file
  a worker might exit 0 without writing. Plus an fd leak per call and the racy `tempfile.mktemp`.
- **Replicas were not independent.** No spec declared a `seed`, so the per-lineage draw built in
  Stage 0 was dead code for every real tool. `replicas: 4` against RFD3 meant four uncontrolled,
  unreproducible draws; against `packmin`/`fastrelax`, four identical reruns.

## Still true after this work

The first real run has not happened — see `../first-real-run.md`. The seed flag names and
LigandMPNN's `--number_of_batches` semantics remain unverified against installed versions, and are
marked at their call sites.
