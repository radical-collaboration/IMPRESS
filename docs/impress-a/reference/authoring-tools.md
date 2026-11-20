# Authoring Tools and Toolkits

## What a tool is, to the system

A tool is three things, read by three different readers:

| part | where | read by | says |
|---|---|---|---|
| the **spec** | `toolkits/<tk>/tools/<id>/spec.yaml` | the planner, the composer, the gates | what the tool accepts and produces: typed ports, parameters and their bounds, metrics, QC gates, cost |
| the **adapter** | the `TaskAgent` subclass `entry:` names | the engine, once per task | how to stage inputs, run the tool and read its output back |
| the **command builder** | one pure function in the adapter's module | **a person**, and a test | the exact argv the tool runs |

The division matters because **a spec does not say what gets executed** — it has no command,
executable or environment field. A reasoner chooses a tool and its parameter values from the spec
alone and never sees a command line. The adapter turns those values into a command, and the
engine places that command on a compute node. So the adapter is the only place where "which
command does this system run" can be answered, and the rules below exist to make that answer
short enough to read.

[`invocation.md`](invocation.md) walks the whole path — spec, request, parameters, argv, placed
process, recorded command — with the shipped tools' commands written out. Read it once before
writing an adapter; this page is the how-to that follows from it.

## Layout

Tools are declarative data plus a behaviour class. A toolkit is a directory:

```
toolkits/<toolkit>/
├── SKILL.md                     # agent-facing guidance for the whole toolkit
└── tools/<tool_id>/
    ├── spec.yaml                # the ToolSpec  (data)
    └── tests/                   # fixtures, including known-BAD outputs
```

The behaviour class lives wherever `entry:` points. In practice every shipped tool points into the
package (`src/impress_a/tools/<toolkit>_agents.py`) rather than co-locating an `agent.py` here, because
several tools in a toolkit share helpers and a subprocess worker.

Toolkits are discovered from, in precedence order: an explicit path, `$IMPRESS_A_TOOLKITS`, installed
`impress_a.toolkits` entry points, then the bundled `toolkits/` directory. A site or third party can add
a toolkit without forking the package — and if its specs declare QC gates this package does not ship,
`$IMPRESS_A_GATE_MODULES` is what makes them resolvable (see *QC gates*).

## Adding a tool

1. **Run the real tool by hand first**, and keep the command that worked. Every flag in an
   adapter should be one somebody has executed: RFD3 was once invoked with `--config`/`--out`,
   flags its CLI does not have, on the strength of its documentation.
2. Write `spec.yaml` (below). Declare a parameter only if step 3 will pass it to the tool.
3. Write the **command builder**: a module-level function taking the resolved params and the
   paths it needs, returning the argv, with no I/O in it.
4. Write the `TaskAgent` subclass around it — override `run()` only — and set `entry:` to its
   dotted path.
5. Add known-bad and known-good fixtures under `tests/` (see *QC gates*).
6. Mention the tool in the toolkit's `SKILL.md`.
7. Pin the command: add the tool to `_build` in `tests/test_real_toolkits.py`, which gives it
   the golden-argv test and the declared-parameters test.
8. Teach `impress-a preflight` about any environment variable or executable it needs, then run
   `impress-a validate-tasks` on hardware. Admission cannot tell you the binary is missing
   ([`invocation.md`](invocation.md), finding 1).

**If you find yourself editing the composer, validator or manager to add a tool, the layering is wrong.**

## `spec.yaml`

```yaml
id: example_fold
toolkit: prediction
version: "0.1"
pattern: P1                                  # see reference/compute-patterns.md
entry: mypkg.agents.FoldAgent
resources: {gpus: 1, cores: 4, walltime_s: 60}
gpu_portability: {cuda: proven, hip: unproven, sycl_xpu: unproven}
inputs:
  sequences: {type: ProteinSequence}
outputs:
  complex: {type: Complex}
parameters:
  recycles: {type: int, default: 3, min: 1, max: 12, trades: "accuracy vs wall-clock"}
frozen_parameters:
  checkpoint: "Mixing checkpoints within a campaign makes designs non-comparable."
qc_gates:
  - {id: output_present, params: {key: result}}
  - {id: has_secondary_structure, params: {min_ss_fraction: 0.25}}
cost_model: {unit: invocation, cost: {gpu_hours: 0.03}}
```

### The `toolkit` field is read by gate 6, and it is not the directory name

`toolkit:` looks like a label and is a **classification**. `compose/validate.py::_g6_delivery`
decides whether a tool is a surrogate by matching this field against `"mock"` **exactly** — never
the directory the spec sits in, never a prefix — and a campaign declaring `tool_delivery: real`
refuses a graph containing one, while `tool_delivery: mock` refuses a graph containing a real
tool. Two consequences, and the second is the one that bites:

* **A surrogate must declare `toolkit: mock`**, whatever directory it lives in. A stand-in in a
  toolkit of its own name — `toolkit: my_mocks` — is classified **real** and is *admitted* by a
  campaign asking for real tools. The run completes and reports seeded draws as science, which is
  the failure gate 6 exists to prevent.
* **A tool id is one flat global namespace**, not per toolkit. So a surrogate cannot take its real
  tool's id, and the convention is a `mock_` prefix on the id while the field stays `mock`. See
  *Loading is validating* for what a collision actually does.

`toolkits/mock/SKILL.md` and `campaigns/README.md` both state the first rule correctly, and an
author of a *new* toolkit reads neither.

### What a parameter is for

A `parameters` entry is a promise in two directions. To a **planner** it is a knob: the `trades`
sentence is how a planner decides whether it may move it (quality and diversity, yes; breadth and
identity, no — [`resolution.md`](resolution.md) step 6), and the bounds are how far. To the
**adapter** it is a key that will arrive in `params`, already validated. A parameter that reaches
no command breaks the first promise silently — a planner can tune it forever with no effect — so
the test suite refuses one unless it is exempted by name with a reason.

Give a parameter a `null` default only when "unset" is a real state, as with `seed`. It is then
*absent* from `params` unless something set it, so read it with `params.get(...)`.

Inputs that identify the campaign's target — a ligand SMILES, an input-spec path, a params file —
are ordinary parameters with an empty-string default. The campaign's `params:` block supplies
them, so a reasoner never has to know a tool's parameter names to run a campaign correctly.

### `frozen_parameters` matters as much as `parameters`

Settings an agent must never touch — a scorefunction's reference weights, a checkpoint identity, a retry
backoff floor. Freezing them declaratively means the composer cannot propose them and gate 3 rejects any
graph that tries. Each entry carries its reason, which is surfaced in the rejection.

### Loading is validating

A malformed spec, a default outside its own declared range, an unknown QC gate id, **a duplicate tool
id**, a `P1` tool declaring no GPU, or a `SKILL.md` missing a required section is a **load-time error**.
A toolkit that fails anywhere registers **nothing** — never a partial set. A gate id is unknown unless
the package ships it or `$IMPRESS_A_GATE_MODULES` names the module that registers it (see *QC gates*).

**The duplicate-id case is worth spelling out, because the toolkit that dies is not the one you
edited.** Ids are one flat namespace across every search path, and `_load_toolkit` stages a
toolkit's specs and registers them only if all of them resolve. So adding a tool whose id already
exists makes **the toolkit being loaded second register nothing at all** — every other tool in it
disappears too — and the only evidence is one line in `Registry.errors`:

```
errors: ["mytoolkit: duplicate tool id 'rfd3_design'"]
```

Nothing refuses, nothing raises, and `impress-a run` proceeds with a vocabulary quietly missing a
toolkit. Check `reg.errors` after a load; `impress-a tools` listing fewer tools than you expect is
the symptom.

## QC gates

Gates are shared by id from `impress_a.tools.gates`, not reimplemented per tool, so there are not fifty
subtly different versions of the same check:

```python
from impress_a.tools import gates
from impress_a.core.qc import GateOutcome, GateResult

@gates.gate("my_check")
def _my_check(out: dict, params: dict) -> GateResult:
    v = (out.get("metrics") or {}).get("thing")
    ok = v is not None and v >= params.get("min", 0)
    return GateResult(gate="my_check",
                      outcome=GateOutcome.PASS if ok else GateOutcome.FAIL,
                      observed=v, threshold=params.get("min"))
```

**A gate defined outside this package must be named in `$IMPRESS_A_GATE_MODULES`** — a path-separated
list of dotted module names, imported by `Registry.load()` before any gate id is resolved. `@gates.gate`
registers at *import* time, so an out-of-tree gate exists only once its module has run, and the registry
resolves every id a spec declares **before** it registers anything. Without the variable the result is
not a gate error but a **missing toolkit** — the tools in it that declared nothing unusual included —
reported as one line in `Registry.errors`. A module named there that cannot be imported raises
`gates.GateModuleError`, the one thing that stops `Registry.load()` rather than being collected as a
per-toolkit error, because the alternative is reading as a toolkit that quietly went missing.

**Gates are mandatory for non-P6 tools** — gate 2 refuses a tool composed without them. They are the
boundary at which a tool's output enters campaign state, and the only defence against silent failure.

**Each gate has a `role`** — `integrity` (the default) or `acceptance`:

```yaml
qc_gates:
  - {id: output_present, params: {key: result}}
  - {id: metrics_reported, params: {metrics: [complex_plddt]}}                 # integrity
  - {id: metric_in_range, role: acceptance, params: {metric: complex_plddt, min: 0.5}}
```

An **integrity** failure means the tool or pipeline broke, and it demotes the composition pattern. An
**acceptance** failure means the tool worked and the design is not good enough: the node still FAILs, and
is never rankable, but the trust ledger ignores it (decision 0013). Use acceptance only for a quality
threshold; anything that detects a *malfunction* stays integrity. Load-time validation enforces one rule
here: every acceptance `metric_in_range` must have its metric named in an integrity `metrics_reported`
gate. That rule exists because a value the adapter never read must be an integrity failure, never a low
score. Adapters therefore **omit** a metric they could not read rather than reporting 0.0.

Write gates against the failure you have actually seen. A gate that has never seen the output it was
written to catch is an assertion, not a test — so every non-mock tool carries known-bad fixtures under
`tests/`, and `tests/test_gate_fixtures.py` fails if a new one does not. A `.bad.json` must fail at least
one integrity gate; one that records a genuinely weak design, caught only by acceptance, says so with
`"acceptance_only": true`.

```
toolkits/<tk>/tools/<id>/tests/
├── <name>.bad.json     # a raw run() payload this tool's OWN gates must FAIL
├── <name>.good.json    # a raw run() payload they must PASS
└── raw/                # tool-native artifacts (a real FASTA, a real out_dir listing);
                        # never collected as fixtures
```

The **filename suffix is authoritative**, never a field inside the file: a typo'd `"expect": "pass"`
would be silently wrong, a wrong suffix cannot be. Each file has three keys:

```json
{
  "why": "the failure this records, and where it was observed",
  "failing_gates": ["output_present", "metric_in_range[ligand_iptm]"],
  "output": {"result": null, "count": 0, "outputs": {}, "metrics": {}}
}
```

`output` is verbatim what the agent's `run()` returns, and `outputs` is always `{}` — these fixtures
cover the **QC** contract; the artifact contract is `_as_artifacts`, covered in `test_real_toolkits.py`.
`failing_gates` is an exact set of *rendered* `GateResult.gate` labels, so `metric_in_range` entries take
the `metric_in_range[<name>]` form. A fixture cannot claim to demonstrate one gate while tripping another.

`toolkits/mock/tools/mock_noodle/tests/` is the worked example, and the one fixture pinned directly to
the code that produces it.

## Task agents

```python
class FoldAgent(TaskAgent):
    async def pre_process(self, req): ...        # stage inputs, check preconditions
    def parameterize(self, req): ...             # usually inherited: defaults + range + frozen checks
    async def run(self, req, params): ...        # the only required override
    async def post_process(self, req, raw): ...  # usually inherited: metric extraction + gate execution
```

The driver is `TaskAgent.__call__`, which runs the four phases in order and times each. **Override
`run()` and nothing else**: no shipped adapter overrides another phase, and the inherited
`parameterize` and `post_process` are what make parameter checks and QC gates impossible to skip.
`run()` returns a plain dict with `outputs`, `metrics`, and whatever keys the gates inspect.

### The shape of an adapter

```python
def fold_command(params, *, input_fasta, out_dir, weights) -> list[str]:
    """THE command `example_fold` runs. Pure: every path is an argument.

    `fold` comes from PATH and `weights` from $FOLD_WEIGHTS; neither is in the spec.
    """
    cmd = ["fold", "predict", str(input_fasta), "--out", str(out_dir),
           "--weights", str(weights), "--recycles", str(params["recycles"])]
    if params.get("seed") is not None:
        cmd += ["--seed", str(params["seed"])]
    return cmd


class FoldAgent(TaskAgent):
    async def run(self, req, params):
        weights = os.environ.get("FOLD_WEIGHTS")
        if not weights:                                   # 1. fail loudly, before any work
            raise RuntimeError("FOLD_WEIGHTS is not set - see scripts/delta_env_setup.sh")
        sequences = input_path(req, "sequences")          # 2. inputs, by declared port
        work = workdir_for(req, "fold")                   #    and a directory of its own
        cmd = fold_command(params, input_fasta=sequences, out_dir=work, weights=weights)
        await run_cmd(cmd, env=child_env(req),            # 3. the engine runs it, placed
                      timeout_s=float(self.spec.resources.walltime_s))
        return {"result": "complex",                      # 4. read the output back
                "outputs": {"complex": work / "model_0.pdb"},
                "metrics": _read_confidence(work)}
```

### The adapter's contract

Each rule is here because breaking it failed quietly at least once.

| rule | why |
|---|---|
| **Every command goes through `run_cmd`.** Never `subprocess`, never `os.system` | `run_cmd` submits the command to the engine, which places it on the node's GPU with its thread share and records its argv. A command started any other way runs on the campaign host, unplaced and unrecorded, and nothing says so |
| **Build the argv in one pure function** | It is the only place a reader can learn what the tool runs, and the only form a test can pin without the binary |
| **Every declared parameter reaches the command** — a flag, a config-file key or a positional argument | Otherwise it is a knob connected to nothing |
| **Pass `timeout_s=spec.resources.walltime_s`** | The walltime bounds a command only because the adapter passes it. A call without it is unbounded |
| **Never pin a GPU or cap threads yourself** | Placement is the engine's, and differs by backend: an environment variable under the concurrent backend, a `Policy` under Dragon. An adapter that set `CUDA_VISIBLE_DEVICES` under Dragon would name a device it was never given |
| **Pass `env=child_env(req)`**, or a filtered copy of `os.environ` if the child must not see yours | The environment given to a child *replaces* its own, so pass a whole one. `child_env` carries no pinning; the engine adds that |
| **Write under `workdir_for(req, prefix)`**, and pass absolute paths | `tempfile.mkdtemp()` is local to one node and unreachable from wherever the next task runs. Most commands run with no `cwd`, so a relative path resolves against the campaign's directory, not the tool's |
| **Read inputs with `input_path(req, port)`** | It resolves by your own declared input port — the wiring the composer computed and gate 1 type-checked. Scanning the upstream payloads mis-wires a node with two typed inputs |
| **Check environment variables first, and raise** | A missing variable should name itself, not surface as a tool's own confusing failure |
| **Keep heavy imports inside `run()`** | The module is imported at registry load and in the dry run, on a login node, where `import pyrosetta` costs minutes or does not exist |
| **Omit a metric you could not read** — never report `0.0` | A fabricated zero turns "the tool broke" into "the design is weak" |
| **If the tool produces N candidates, select one and say how many** | Report `ensemble_size`; breadth across designs comes from `replicas`, never from a tool's internal N |

### Outputs are typed handles, not strings

Return a **`pathlib.Path`** for anything written to disk, and a plain value for anything small enough
to carry inline. `post_process` turns both into `ArtifactRef`s, taking the **type from the spec's
declared output port** — so a handle can never disagree with the contract the composer type-checked
the graph against, and an adapter never has to repeat itself.

```python
return {"result": "backbone",                       # what `output_present` looks for
        "outputs": {"backbone": work / "design.pdb"},   # a Path: a file
        "metrics": {"ss_fraction": 0.62}}
```

Returning a `Path` is how an adapter *declares* a file; returning `str(path)` makes it an inline
value instead. Files get their size and a content digest recorded, which is what lets a reasoner in
another process tell whether the bytes behind a path are still the ones the campaign reasoned about.

**`ArtifactType` is a closed enum** (`core/types.py`), so the vocabulary of artifact types is fixed
and gate 1 validates every declared port against it. A genuinely new kind of artifact is therefore a
**code change to this package**, not a spec change — a spec naming an unknown type fails to load,
with a pydantic `input_value='MyType'` error that reads as a typo rather than as a closed
vocabulary. Before adding a member, check whether an existing one is the honest answer:
`Parameterized`, for instance, covers a parameterisation handed to a sampler, and the enum's own
docstring draws the `SmallMolecule`/`Parameterized` line exactly there. The members are few on
purpose — the type is what gate 1 uses to refuse a mis-wired chain, and a vocabulary that grows per
tool stops being able to.

An output your spec does not declare is a **load-bearing error**, not something to drop quietly:
nothing downstream could consume it and the composer never type-checked it, so `post_process` raises
rather than let a spec bug surface later as a missing input.

To consume an upstream artifact, `_subprocess.input_path(req, port)` returns the thing to open,
resolved by **your own declared input port** — the wiring the composer computed and gate 1
type-checked. It replaces a helper that scanned the dependency payloads for a matching output name,
which is right only while a node has exactly one upstream: with two typed inputs it returned
whichever dependency came first, and that type-checks at composition and mis-wires at runtime.

### Checking what your tool ran

After a run, `provenance/tasks.jsonl` has one row per task, and its `commands` field lists each
command as the backend was handed it — your builder's argv, with a `timeout` prefix where the
engine added one, the GPU it was placed on and its exit code. `work/<prefix>_<node>/` holds what
you staged and what the tool wrote. Compare the first against your builder and the second against
what `run()` returned; a tool that exits 0 having written nothing is the failure these files are
for.

## Skill documents

`SKILL.md` is agent-facing guidance, not an API reference — the spec is the reference. Required sections:
**Purpose** (and when *not* to use the toolkit), **Canonical sequences**, **Cost posture**, **Pitfalls**.

Every tool in the toolkit must be mentioned, and every tool mentioned must exist; the registry checks
both. Co-location is what keeps docs and specs in step: one pull request touches both.

**That check attributes a spec to a toolkit by the spec's `toolkit` field, not by the directory it
sits in** — so a tool whose field and directory differ is checked against the *field's* `SKILL.md`.
This matters for exactly one case, and gate 6 creates it: a surrogate must declare `toolkit: mock`
(above), so a surrogate living outside `toolkits/mock/` is attributed to `toolkits/mock/SKILL.md`,
which is then told it must mention a tool in a directory it has never heard of. The result is a
line in `Registry.errors` and nothing else — the toolkit still loads, since this check appends
rather than raising — but the error is unactionable: satisfying it would mean editing another
toolkit's documentation to name yours.
