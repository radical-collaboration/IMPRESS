# Invocation: from a tool spec to a running command

[`resolution.md`](resolution.md) ends with an admitted graph, and
[`observation.md`](observation.md) begins when a run is absorbed. This page is the part between:
how one node of that graph — a tool id and a parameter dict — becomes **a command line running
on a compute node**, and what is written down about it.

Every step says what it takes, who owns it, what it produces and what refuses it, in the order a
task executes them. If this page and the code disagree, the code is right and this page is a bug.

Two things to read it for. **Knowing what the system actually executes**, from the source rather
than from a finished run's logs — step 4 is the answer, one table per tool, each anchored to the
single function that builds that tool's command. And **adding or changing a tool safely**, for
which [`authoring-tools.md`](authoring-tools.md) is the how-to and this page is the reason behind
each rule in it.

The one fact to carry through the rest: **a spec declares what a tool accepts; it does not
declare what the tool runs.** There is no command template in `spec.yaml`. The executable, the
flag names, the config-file schema and the environment contract live in Python, in the adapter
`entry:` points at — and in exactly one function of it.

```
toolkits/<tk>/tools/<id>/spec.yaml ──→ ToolSpec                              step 0
ToolSpec.entry ──importlib──→ a TaskAgent subclass (the adapter)             step 1
TaskGraph node ──node_task──→ TaskRequest + Placement    (a `local` thread)  step 2
TaskRequest.params ──parameterize──→ resolved params      (= the dry run)    step 3
resolved params ──<tool>_command()──→ argv                 (pure, in Python) step 4
argv ──run_cmd → Launcher──→ an executable task on `compute`, placed         step 5
files in work/<tool>_<node>/ ──post_process──→ ArtifactRefs, metrics, QC     step 6
Launcher.records ──→ provenance/tasks.jsonl `commands`                       step 7
```

Anchors are relative to `agent/src/impress_a/`.

---

## Step 0 — what a spec says about invocation, and what it does not

**In:** `toolkits/<toolkit>/tools/<id>/spec.yaml`. **Owner:** `tools/spec.ToolSpec:109`.
**Out:** the typed contract every later step reads.

| declared | what it does for invocation |
|---|---|
| `entry:` (`:131`) | the dotted path of the adapter class — step 1 |
| `parameters`, `frozen_parameters` | the only keys a node may set, with their bounds — step 3 |
| `inputs` / `outputs` ports | which upstream file the adapter opens, and the type its results are filed under — steps 4 and 6 |
| `resources` | `gpus` decides whether the command is pinned to a device; `walltime_s` becomes its timeout — step 5 |
| `qc_gates`, `metrics` | what the adapter's return value is held to — step 6 |

**Not declared, anywhere in a spec:** the executable, its flags, its environment variables, its
container image, its working directory. `ToolSpec` has no field for any of them. So a spec can
be valid, load cleanly and be planned against while naming a parameter no command ever receives
— finding 2 — and nothing at load time can compare a spec with the CLI it fronts.

## Step 1 — `entry:` becomes a class

**In:** a tool id. **Owner:** `tools/registry.Registry.agent_for:90`. **Out:** a `TaskAgent`
subclass.

```python
mod, _, cls = spec.entry.rpartition(".")
return getattr(importlib.import_module(mod), cls)
```

An ordinary import, so the adapter has to be importable from the campaign's environment:
toolkit directories are *not* put on `sys.path`. Every shipped tool points into the package
(`impress_a.tools.<toolkit>_agents`). A spec with no `entry:` gets `EchoTaskAgent`
(`tools/agent.py:266`), which runs nothing.

Adapters keep heavy imports (PyRosetta, gemmi, Biopython) **inside `run()`**, never at module
scope. This import happens at load, on a login node, and in the dry run; a module-level
`import pyrosetta` would cost minutes there and fail where PyRosetta is not installed.

## Step 2 — a graph node becomes a request, and a placement

**In:** an admitted `TaskGraph`. **Owner:** `runtime/executor._dispatch:1036` →
`exec/stage.StageExecutor.submit:119` → `exec/dispatch.node_task:144`. **Out:** one
`TaskRequest` (`tools/agent.py:28`) and one `Placement` (`exec/resources.py:86`) per node.

`node_task` is the **single factory for every node of every graph** — there is no per-tool and
no per-pattern dispatch (finding 6). For each node it builds:

| field of `TaskRequest` | from |
|---|---|
| `tool`, `params` | the node, i.e. the planner's `TaskMapping` with the campaign's `params:` merged under it (`resolution.md` step 6) |
| `node_id` | `<run_label>:<task id>` — also the name of the task's work directory |
| `seed` | the lineage's seed, from the composer |
| `inputs`, `input_ports` | the composer's typed wiring: this tool's own input port → the upstream payload, and which of its output ports was meant |
| `seed_inputs` | artifacts from outside the graph: the parent design a refinement starts from |
| `gpu_index` | informational only; the placement is what pins |

The `Placement` is decided here, once per node: the lineage's GPU (round-robin over
`site.gpus_per_node`, and only if the tool declares `gpus > 0`), a host, and the thread share.

**A node is two kinds of engine work**, and this is the step that splits them. The adapter runs
as a function task on the engine's `local` route (`exec/dispatch.py:222`) — a thread *in the
campaign process*. Each command it starts is a separate task on the `compute` route (step 5).
So nothing about the adapter is pickled, and the backend schedules binaries rather than an
opaque Python callable.

## Step 3 — parameters are resolved, and that is all admission proved

**In:** `TaskRequest.params`. **Owner:** `tools/agent.TaskAgent.parameterize:151`, inherited by
every adapter. **Out:** the `params` dict `run()` receives.

1. Start from the spec's defaults — **only those that are not `null`**. A parameter whose
   default is `null` (`seed`, everywhere) is simply absent, which is why adapters read it with
   `params.get("seed")`.
2. For each key the node set: refuse it if it is in `frozen_parameters`, refuse it if the spec
   does not declare it, refuse it if `ParameterSpec.validate_value` (`tools/spec.py:57`) rejects
   its type, choice or range. Otherwise it overrides the default.
3. If the request carries a seed, the spec declares `seed`, and the node did not set one:
   `seed = req.seed % 2**31`.

Each refusal is a `ValueError` naming the tool and the key. These are the same rules gate 3
applied at admission; this is the second, authoritative application, in the process that is
about to act on them.

**The dry-run gate is this step and nothing after it.** `compose/validate.Validator.dry_run:186`
calls `agent.dry_run` (`tools/agent.py:260`) — `pre_process` then `parameterize` — on a
`TaskRequest` holding only the tool and its params: no inputs, no work directory, no seed. An
admitted graph has therefore been shown to have legal *parameter values*. Whether the binary
exists, the environment variable is set, or the flag is one the real CLI has, admission never
asked (finding 1). `impress-a preflight` and `impress-a validate-tasks` ask it, outside the
loop.

## Step 4 — the adapter builds the command

**In:** resolved params and the request. **Owner:** each adapter's `run()`, which is the only
method an adapter overrides — and inside it, **one pure function per tool that returns the
argv**. **Out:** a `list[str]`.

`run()` does four things in order: check the environment and fail loudly if a variable is
unset; stage files into the task's work directory (`workdir_for`, step 6) and find its inputs
(`input_path(req, port)`); call its command builder; hand the result to `run_cmd`. The builder
takes params and paths as arguments, reads no environment and touches no disk, so the command
below can be read — and is tested — without a binary, a GPU or an allocation.

**Where the executable comes from** is never the spec and never `sites/*.yaml`:

| tool | executable | supplied by |
|---|---|---|
| `rfd3_design` | `apptainer exec … <image> rfd3 design` | `apptainer` on `PATH`; image from `$FOUNDRY_SIF_PATH` |
| `ligandmpnn_design` | `<python> mpnn_run.py <checkout>` | `sys.executable`; checkout from `$MPNN_DIR` |
| `boltz_predict` | `boltz predict` | `boltz` on `PATH` (the campaign's venv); weights from `$BOLTZ_CACHE` |
| `packmin`, `fastrelax`, `filter_shape` | `<python> worker.py` | `sys.executable`; PyRosetta is an import inside the worker |

`scripts/delta_env_setup.sh` is what sets those variables on Delta.

### `rfd3_design` — `tools/rfd3_agents.rfd3_command:198`

```
apptainer exec --nv --bind <tree>:<tree> … $FOUNDRY_SIF_PATH \
  rfd3 design out_dir=<work> inputs=<work>/<staged spec>.json skip_existing=False \
  dump_trajectories=False prevalidate_inputs=True \
  diffusion_batch_size=<num_designs> inference_sampler.num_timesteps=<diffusion_steps> \
  [seed=<seed>]
```

| parameter | becomes |
|---|---|
| `input_spec_path` | `inputs=` — not the file itself but a copy staged into the work directory with its relative paths made absolute (`_inputs_with_absolute_paths:143`) |
| `num_designs` | `diffusion_batch_size=` |
| `diffusion_steps` | `inference_sampler.num_timesteps=` |
| `seed` | `seed=`, when set |

`rfd3 design` takes **Hydra overrides, not `--flags`**. Binds are `$WORK_DIR`, the input spec's
directory and the work directory, de-duplicated (`_binds:172`). Environment: the campaign's,
minus `PYTHONPATH` / `PYTHONUSERBASE` / `PYTHONDONTWRITEBYTECODE`, plus `PYTHONNOUSERSITE=1`
(`_container_env:28`), so the container imports its own Python stack. No `cwd`.

### `ligandmpnn_design` — `tools/ligandmpnn_agents.ligandmpnn_command:133`

```
<sys.executable> <work>/mpnn_run.py $MPNN_DIR --model_type ligand_mpnn \
  --checkpoint_ligand_mpnn $MPNN_DIR/model_params/ligandmpnn_v_32_010_25.pt \
  --checkpoint_path_sc     $MPNN_DIR/model_params/ligandmpnn_sc_v_32_002_16.pt \
  --pdb_path <upstream backbone> --out_folder <work> \
  --temperature <temperature> --batch_size <batch_size> --number_of_batches <number_of_batches> \
  [--seed <seed>] \
  [--pack_side_chains 1 --pack_with_ligand_context 1 --number_of_packs_per_design 1] \
  [--fixed_residues <fixed_residues>]
```

| parameter | becomes |
|---|---|
| `temperature`, `batch_size`, `number_of_batches` | the flags of the same name |
| `pack_side_chains` | when true, the three packing flags, each fixed at `1` |
| `fixed_residues` | `--fixed_residues`, when non-empty |
| `seed` | `--seed`, when set |
| `num_seqs` | **nothing** — declared, validated, never passed (finding 2) |

`mpnn_run.py` is `MPNN_SHIM` (`:69`), written into the work directory at run time: it patches
the numpy aliases LigandMPNN's vendored openfold still uses and then runs `$MPNN_DIR/run.py`.
`--pdb_path` is the artifact wired to this tool's `backbone` port. Runs with `cwd=$MPNN_DIR`
and the campaign's whole environment.

### `boltz_predict` — `tools/boltz_agents.boltz_command:112`, `boltz_input:93`

```
boltz predict <work>/boltz_input.yaml --out_dir <work>/out --cache $BOLTZ_CACHE \
  --devices 1 --accelerator gpu --diffusion_samples <diffusion_samples> \
  --output_format pdb --no_kernels [--seed <seed>] [--use_msa_server]
```

Two parameters reach the tool through **a config file rather than a flag**:

| parameter | becomes |
|---|---|
| `diffusion_samples` | `--diffusion_samples` |
| `seed` | `--seed`, when set |
| `use_msa_server` | `--use_msa_server`, **and** `msa: auto` (else `empty`) in `boltz_input.yaml` |
| `ligand_smiles` | a `ligand: {id: [B], smiles: …}` entry in `boltz_input.yaml`, when non-empty |

The protein sequence in that file is extracted from the artifact on the `structure` port. A
`flock` on the cache is held across the first run, because Boltz extracts its component
dictionary inside `boltz predict`. No `cwd`; the campaign's whole environment.

### `packmin`, `fastrelax`, `filter_shape` — `tools/rosetta_agents.worker_command:278`

```
<sys.executable> <work>/worker.py <positional args…> <work>/result.json
```

PyRosetta is a Python API, not a binary, so each tool writes a worker script (`_PACKMIN_WORKER`
`:20`, `_FASTRELAX_WORKER` `:72`, `_FILTER_SHAPE_WORKER` `:171`) into its work directory and
runs it in a fresh interpreter. Its arguments are **positional**:

| tool | builder | arguments, in order |
|---|---|---|
| `packmin` | `packmin_args:331` | structure, out pdb, `cycles`, `seed`\|`none`, `ligand_params_path`\|`none` |
| `fastrelax` | `fastrelax_args:337` | structure, out pdb, `relax_cycles`, `nstruct`, `seed`\|`none`, `ligand_params_path`\|`none` |
| `filter_shape` | `filter_shape_args:343` | structure, `ligand_params_path`\|`none` |

The flags Rosetta itself sees are assembled inside the worker and passed to `pyrosetta.init`:
`-mute all`, plus `-run:constant_seed -run:jran <seed>` when a seed was given, plus
`-extra_res_fa <ligand_params_path> -ignore_unrecognized_res -ignore_zero_occupancy` when a
ligand params file was. No `cwd`, and no `env` (finding 5).

### Mocks stop here

The mock adapters (`tools/mock_agents.py`, `tools/mock_smb_agents.py`) override `run()` and
return seeded draws. They never call `run_cmd`, so steps 5 and 7 do not happen for them: no
executable task is submitted and their `commands` list is empty.

**What refuses a change here:** `tests/test_real_toolkits.py` pins each builder's argv at its
spec defaults, and `test_every_declared_parameter_reaches_its_command` compares each spec's
parameters against the keys its builder reads. A parameter that is declared and unread must be
added to that test's exemption table with a reason.

## Step 5 — the command becomes an engine task

**In:** `run_cmd(argv, cwd=, env=, timeout_s=)`. **Owner:** `tools/_subprocess.run_cmd:48` →
`exec/launch.Launcher.run:123` → `_submit_and_wait:194`. **Out:** `(stdout, stderr)`, or a
`SubprocessError` carrying the command line, the exit code and both streams.

`run_cmd` does not start a process. Inside a node it finds that node's `Launcher` in the
`LAUNCHER` context variable (`tools/_subprocess.py:30`, set at `exec/dispatch.py:198`) and
hands the command over; the `Launcher` submits it to the engine as an `executable_task` on the
`compute` route. A context variable rather than an argument, so that no adapter can forget to
pass it — one that shelled out with `subprocess` directly would run its binary on the campaign
host, unplaced, and nothing would say so.

What is added to the adapter's argv on the way, by backend (`exec/resources.Placement.describe:116`):

| | concurrent backend | Dragon |
|---|---|---|
| walltime | argv is prefixed `timeout --kill-after=10 <walltime_s>` | the task's own `timeout`, `walltime_s + 10`; **never** the wrapper |
| GPU | `CUDA_VISIBLE_DEVICES=<index>` in the environment | `Policy(gpu_affinity=[index])`; the variable is not set |
| threads | `OMP_`/`MKL_`/`OPENBLAS_`/`NUMEXPR_NUM_THREADS`, `OMP_WAIT_POLICY=PASSIVE` | the same |
| environment | the adapter's `env`, or `os.environ`, replaced whole | only what differs from the campaign's, merged into the node's |
| concurrency | bounded by `workers` (`exec/stage.command_slots:44`) | the backend's own |

The walltime only reaches a command because **each adapter passes
`timeout_s=spec.resources.walltime_s`**; a `run_cmd` call without it is unbounded. Why the
wrapper is refused under Dragon, and what a cancel does and does not kill, are in
[`middleware-integration.md`](middleware-integration.md) and
[`limitations.md`](../limitations.md) and are not repeated here.

Outside a node — `impress-a preflight`, the gate fixtures, a direct test — no `Launcher` is
set and `run_cmd` runs the child itself with `asyncio.create_subprocess_exec`.

## Step 6 — files come back as typed results

**In:** whatever the command wrote, and `run()`'s return dict. **Owner:**
`tools/_subprocess.workdir_for:159`, then `tools/agent.TaskAgent.post_process:203`.
**Out:** a `TaskResult`.

Every real adapter writes under `workdir_for(req, prefix)`:

```
<campaign process CWD>/work/<prefix>_<run_label>_<task id>/
```

created on demand and never cleaned — it holds the campaign's results. The root is the process
CWD because `TaskRequest.workdir` is never set (finding 4); on Delta the launcher has already
changed into a per-job directory on shared storage.

The adapter reads its tool's native output there (a sidecar JSON, FASTA headers, a confidence
file, the worker's `result.json`) and returns `{"outputs": …, "metrics": …}` plus whatever keys
its gates inspect. `post_process` then, without the adapter's help:

- turns each output into an `ArtifactRef` whose **type is the spec's declared output port**
  (`_as_artifacts:175`); a `Path` is hashed as a file, anything else is an inline value, and an
  output name the spec does not declare **raises**;
- runs the spec's QC gates over the return value;
- records the declared cost beside the measured one.

An adapter **omits** a metric it could not read; the `metrics_reported` gate is what turns the
omission into an integrity failure rather than a low score.

## Step 7 — what is written down

**In:** the `Launcher`'s records and the `TaskResult`. **Owner:**
`runtime/executor._log_task_telemetry:1319`. **Out:** one row per task in
`provenance/tasks.jsonl`.

| question | where it is answered |
|---|---|
| which parameters did the planner choose? | `provenance/stages.jsonl`, `mappings` |
| **what command ran?** | `provenance/tasks.jsonl`, `commands` |
| where and for how long? | the same row: `host`, `pid`, `cuda_visible_devices`, `wall_s`, `phases` |
| what did it write? | `work/<prefix>_<node>/`, and the node's `ArtifactRef`s in `results.jsonl` |

`commands` has one entry per `run_cmd` call, in order, as the backend was handed it:

```json
{"argv": ["timeout", "--kill-after=10", "900", "apptainer", "exec", "--nv", "…"],
 "cwd": null, "backend": "concurrent", "host": null, "gpu_index": 0,
 "placement_env": {"OMP_NUM_THREADS": "4", "…": "…", "CUDA_VISIBLE_DEVICES": "0"},
 "timeout_s": 900.0, "exit_code": 0, "queued_s": 0.01, "ran_s": 44.9}
```

`argv` is the realized form of what step 4's builder returned — the `timeout` wrapper is there
when one was added — so the page above can be checked against a run instead of trusted. The
environment recorded is **only what the placement added**: adapters pass their child a copy of
`os.environ`, and provenance is not the place for whatever that holds.

---

## What invocation does not enforce

Seven places where the implementation does not do what a reader of the design would reasonably
assume. Each is verified against the source at the anchor given. **Read this section before
changing any step above.**

| # | the reasonable assumption | what the code does | anchor | item |
|---|---|---|---|---|
| 1 | An admitted graph is one whose commands can run | Admission's dry run calls `parameterize` on a request with **no inputs, no work directory and no seed**. It proves parameter values are legal and nothing about the binary, the environment variable, the container image or whether a flag exists. Four defects reached hardware through this gap; `preflight` and `validate-tasks` exist because of it, and run outside the loop | `compose/validate.py:186-195`, `tools/agent.py:260` | J1 |
| 2 | A parameter a spec declares changes what the tool does | Nothing connects a spec's parameters to its adapter. `ligandmpnn_design.num_seqs` is validated, shown to a planner, written to `stages` provenance, and passed to no command. A test now refuses a *new* one; this one is exempted by name | `tools/ligandmpnn_agents.py:133`, `tests/test_real_toolkits.py` (`_NOT_IN_THE_COMMAND`) | J2 |
| 3 | Asking a tool for N candidates yields N to choose from | `rfd3_design` passes `num_designs` as the diffusion batch size and converts `cif_models[0]` only: N are paid for and one is kept. LigandMPNN and Boltz do select. The spec says so, and the planner may not move it (`resolution.md` step 6) | `tools/rfd3_agents.py:198`, `toolkits/rfd3/tools/rfd3_design/spec.yaml` | — |
| 4 | Where a tool writes is the campaign's decision | `StageExecutor` is built without `workdir`, so `TaskRequest.workdir` is always `None` and every task writes under the **process CWD**. Correct only because the launcher scripts `cd` first; nothing in the package enforces it | `runtime/executor.py:1459`, `tools/_subprocess.py:159` | J4 |
| 5 | Every tool's child sees the same environment contract | The three Rosetta tools pass no `env` to `run_cmd`; the others pass `child_env(req)`. Equivalent today on both backends, by the fallback in `Placement.describe` rather than by intent | `tools/rosetta_agents.py:290`, `exec/resources.py:116` | J5 |
| 6 | A tool's compute pattern selects how it is dispatched | `exec/` never reads `ToolSpec.pattern`. Every node takes the one path in step 2. Pattern is read by gates 2 and 4 only — whether QC gates are mandatory, whether P6 was scheduled, whether external submission is allowed | `exec/dispatch.py:144`, `compose/validate.py:94,121,125` | J6 |
| 7 | Every command a campaign ran is on the record | A task whose adapter **raises** records its error string — which contains the failing command line — and no `commands` list; a command run outside the engine records nothing; and the base environment is never recorded, by decision | `exec/dispatch.py:213`, `exec/launch.py:121` | J7 |

Two properties that are **by design** and are listed so they are not mistaken for the above.
The executable's location is an environment contract rather than a spec field or a
`sites/*.yaml` entry, because the right value is machine-specific and a spec is shared across
machines; the cost is that only `impress-a preflight` checks it (backlog J3). And `filter_shape`
returns its *input* structure as its output: it is a filter, so the artifact it passes
downstream is the one it was given, with the same content hash.

## Seeing it on disk

`impress-a mock-lab --only arms --stage sweep` writes one campaign per arm in about half a
minute with no allocation, and shows steps 2, 3, 6 and 7 — with `commands: []`, because mocks
run none. Steps 4 and 5 need a tool that shells out: `tests/test_placement.py` runs real
commands through a real engine on a laptop, and a Delta run shows the science tools.

| step | where it landed |
|---|---|
| 2 | `provenance/graphs.jsonl` — the admitted graph, each node with its tool; `provenance/tasks.jsonl` — each task's `lineage` and `seed` |
| 3 | `provenance/stages.jsonl`, `mappings` — the parameter vector before defaults are filled in; a refusal carries its gate |
| 4, 5 | `provenance/tasks.jsonl`, `commands[].argv` — the builder's argv, plus the `timeout` wrapper where one was added |
| 5 | the same entry's `backend`, `gpu_index`, `placement_env`, `queued_s`, `ran_s`, `exit_code`; `telemetry/`, when on, has a span per command named `<node>.<program>` |
| 6 | `work/<prefix>_<node>/` — the staged inputs (`boltz_input.yaml`, `mpnn_run.py`, `worker.py`) and the tool's own outputs |
| 7 | `provenance/tasks.jsonl` — one row per task |

A step whose output cannot be pointed at in one of those files is a step this page has
described wrongly.
