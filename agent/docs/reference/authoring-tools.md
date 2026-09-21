# Authoring Tools and Toolkits

## Layout

Tools are declarative data plus a behaviour class. A toolkit is a directory:

```
toolkits/<toolkit>/
├── SKILL.md                     # agent-facing guidance for the whole toolkit
└── tools/<tool_id>/
    ├── spec.yaml                # the ToolSpec  (data)
    ├── agent.py                 # a TaskAgent subclass (behaviour), or point `entry` elsewhere
    └── tests/                   # fixtures, including known-BAD outputs
```

Toolkits are discovered from, in precedence order: an explicit path, `$IMPRESS_A_TOOLKITS`, installed
`impress_a.toolkits` entry points, then the bundled `toolkits/` directory. A site or third party can add
a toolkit without forking the package.

## Adding a tool

1. Write `spec.yaml`.
2. Write a `TaskAgent` subclass; set `entry:` to its dotted path.
3. Mention the tool in the toolkit's `SKILL.md`.

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

### `frozen_parameters` matters as much as `parameters`

Settings an agent must never touch — a scorefunction's reference weights, a checkpoint identity, a retry
backoff floor. Freezing them declaratively means the composer cannot propose them and gate 3 rejects any
graph that tries. Each entry carries its reason, which is surfaced in the rejection.

### Loading is validating

A malformed spec, a default outside its own declared range, an unknown QC gate id, a `P1` tool declaring
no GPU, or a `SKILL.md` missing a required section is a **load-time error**. A toolkit that fails anywhere
registers **nothing** — never a partial set.

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

**Gates are mandatory for non-P6 tools** — gate 2 refuses a tool composed without them. They are the
boundary at which a tool's output enters campaign state, and the only defence against silent failure.

Write gates against the failure you have actually seen. A gate that has never seen the output it was
written to catch is an assertion, not a test — keep known-bad fixtures under `tests/`.

## Task agents

```python
class FoldAgent(TaskAgent):
    async def pre_process(self, req): ...        # stage inputs, check preconditions
    def parameterize(self, req): ...             # usually inherited: defaults + range + frozen checks
    async def run(self, req, params): ...        # the only required override
    async def post_process(self, req, raw): ...  # usually inherited: metric extraction + gate execution
```

`run()` returns a plain dict with `outputs`, `metrics`, and whatever keys the gates inspect. Do not
override `execute()`.

## Skill documents

`SKILL.md` is agent-facing guidance, not an API reference — the spec is the reference. Required sections:
**Purpose** (and when *not* to use the toolkit), **Canonical sequences**, **Cost posture**, **Pitfalls**.

Every tool in the toolkit must be mentioned, and every tool mentioned must exist; the registry checks
both. Co-location is what keeps docs and specs in step: one pull request touches both.
