# A laptop campaign that mocks the small-molecule binding toolkit

**Status:** **planned, nothing implemented** · **Branch:** `agent/mock-smb-campaign`, cut from
`agent/stopping-rules` at `25550f7` · **Items:** none yet; open one when work starts

**Handoff.** This document was written at the end of a session that ran out of room to build
it. Nothing below has been executed: no spec has been loaded by the registry, no agent has
been run, no campaign has been composed. The draft code in *Appendix A* is **unverified** and
is embedded here rather than committed to its real path precisely so it cannot be mistaken for
working code, and cannot break the `mock` toolkit's all-or-nothing load. Start by verifying,
not by trusting.

## Why

Every campaign that exercises the real chain — `rfd3_design -> ligandmpnn_design -> packmin ->
fastrelax -> filter_shape -> boltz_predict` — needs a GPU allocation, so nobody can watch the
engine *behave* without spending node-hours. The existing `mock` toolkit models a different
shape: a four-stage self-consistency loop (`mock_generate -> mock_design -> mock_fold ->
mock_score`) with its own metrics (`sc_rmsd`, `iptm`, `ddg`). A laptop run of `mock-stabilize`
therefore says nothing about the campaign the four-arm experiment actually runs.

What is missing is a surrogate of *that* chain: same stage count, same typed ports, same
parameters, same metric names, same QC gates and the same acceptance thresholds, with the
science replaced by seeded draws. Then a person can run it on a laptop, turn one knob, and
watch the campaign respond — more cycles or fewer, satisfied or run to the cycle bound, a
pattern promoted or held under the untrusted cost cap, a front that grows or stays empty.
Those are the behaviours this project spent 2026-11-09 debugging on real hardware (G11, G12,
G13), and none of them needs a GPU to observe.

**Intended outcome:** `impress-a run campaigns/mock-small-molecule-binding.yaml --model D`
finishes on a laptop in seconds, and a README names the knobs and what each one changes, with
measured before/after numbers rather than promises.

## Two constraints that are already settled, and should not be re-litigated

**1. The surrogate tools belong to the `mock` toolkit.** Gate 6 (`tool_delivery`) classifies a
tool by `ToolSpec.toolkit == "mock"` exactly — `compose/validate.py::_g6_delivery`, whose
docstring says "the toolkit a spec declares is a fact", not a name prefix. A toolkit called
`surrogate` or `rng` would be classified **real**, so a campaign declaring
`tool_delivery: real` would admit a chain of random number generators and report its numbers
as science. That is the documented failure gate 6 exists to prevent, and `CLAUDE.md` forbids
the alternative outright: "Never edit the composer, validator or manager to add a tool."
Declaring `toolkit: mock` also exempts them from
`test_every_real_tool_carries_a_known_bad_fixture`, which filters on the same field.

**2. Do not work in the primary checkout while a Delta array is in flight.** Arms read
`$SLURM_SUBMIT_DIR` at run time, `impress_a` is editable-installed from the checkout, and
`Registry` discovers toolkits from `parents[3]/toolkits` relative to the installed source. New
toolkit directories reach queued jobs mid-flight, and a toolkit that fails to load fails their
preflight. Worse and more certain: an uncommitted tree flips `git_dirty` in the manifests of
the arms that start after the edit, so arms of one experiment disagree about their own
provenance. Check `sacct` first. If anything is pending, use a git worktree.

## Design

### Tools — six specs under `toolkits/mock/tools/`

| surrogate | mirrors | pattern | ports | metrics |
|---|---|---|---|---|
| `mock_rfd3_design` | `rfd3_design` | P1 | → `Backbone` | `ss_fraction`, `num_models`, `ca_deviation`, `ligand_clashes`, `helix_fraction`, `sheet_fraction` |
| `mock_mpnn_design` | `ligandmpnn_design` | P1 | `Backbone` → `Complex` | `overall_confidence`, `ligand_confidence`, `ensemble_size`, `ensemble_paired` |
| `mock_packmin` | `packmin` | P2 | `Complex` → `Complex` | `total_score` |
| `mock_fastrelax` | `fastrelax` | P2 | `Complex` → `Complex` | `total_score`, `fa_rep`, `interaction_energy` |
| `mock_filter_shape` | `filter_shape` | P2 | `Complex` → `Complex` | `shape_complementarity`, `sc_selector_mode` |
| `mock_boltz_predict` | `boltz_predict` | P1 | `Complex` → `Complex` | `complex_plddt`, `ligand_iptm`, `ensemble_size`, `ensemble_paired` |

**Build each by copying the real spec and changing exactly five things**, which is cheaper and
less error-prone than writing them fresh, and keeps the mirror honest:

1. `id:` → `mock_<name>`, `toolkit:` → `mock`
2. `entry:` → `impress_a.tools.mock_smb_agents.Mock<Name>Agent`
3. `resources.walltime_s` → 30 (the agent draws numbers; a bound that can never bind teaches
   nothing). **Keep `gpus: 1` on the P1 tools** — a P1 tool declaring no GPU is a load-time
   error, and it costs nothing on a laptop.
4. `cost_model` → thousandths of an hour, so a laptop budget is never what stops the campaign
5. Strip the real spec's hardware-provenance comments; keep every `parameters` entry, every
   `metrics` name, and **every `qc_gates` entry including the acceptance thresholds**

Mirroring the bars is the whole point: a reader watches readings cross the same line the real
campaign measures against — `complex_plddt >= 0.75`, `ligand_iptm >= 0.4`,
`shape_complementarity >= 0.55`, `interaction_energy <= -8.0`, `ss_fraction >= 0.5`, plus
`fastrelax`'s integrity bounds `total_score <= 0` and `fa_rep <= 500`. Only the five implemented
gate ids may be used: `output_present`, `metrics_reported`, `metric_in_range`,
`has_secondary_structure`, `count_matches_request` (`gates.known()`).

**One parameter has no real counterpart:** `difficulty` on `mock_rfd3_design` (float, 0.0–1.0,
default 0.25). It shifts the quality the whole chain inherits, so a reader can make the campaign
easy or impossible without editing a threshold. Label it as the surrogate's own dial in both the
spec and the README — an undocumented extra knob would quietly break the mirror. Above roughly
0.75 it drives `ss_fraction` under the `has_secondary_structure` floor of 0.3, which is an
**integrity** failure rather than a weak design: the node fails *and* the pattern's trust
suffers, where an acceptance shortfall leaves trust alone. That is decision 0013's distinction,
and being able to watch it is worth more than reading it.

### Agents — `src/impress_a/tools/mock_smb_agents.py`

Full draft in *Appendix A*. It reuses `mock_agents._rng` and `mock_agents._upstream` by import
rather than copying them: `_upstream`'s docstring records two bugs it was taught by — seeding a
draw on the QC report made the science a function of the QC schema, and seeding on input *keys*
made a rename of the wiring reshuffle every downstream draw. A fresh copy would reintroduce
both.

Each agent returns `{"result", "count", "outputs", "metrics"}` and reports **exactly** the
metrics its spec declares, because `test_every_tool_declares_the_metrics_it_reports` checks
that, and the "omit, never report 0.0" invariant means a metric it cannot derive must be absent
rather than zero.

**The draw must propagate**, or no upstream knob can change a downstream verdict:

| agent | inherits | knob that moves it |
|---|---|---|
| `MockRFD3DesignAgent` | — | `diffusion_steps` ↑ → `ss_fraction` ↑; `difficulty` shifts everything |
| `MockMPNNDesignAgent` | `ss_fraction` | `temperature` ↓, `batch_size` ↑ → confidences ↑ |
| `MockPackMinAgent` | `overall_confidence` | `cycles` ↑ → `total_score` ↓ |
| `MockFastRelaxAgent` | `total_score`, `overall_confidence` | `relax_cycles`, `nstruct` ↑ → `fa_rep` ↓, `interaction_energy` ↓ |
| `MockFilterShapeAgent` | `interaction_energy` | — |
| `MockBoltzPredictAgent` | `shape_complementarity`, `overall_confidence` | `diffusion_samples` ↑ → `complex_plddt` ↑ |

### `toolkits/mock/SKILL.md` — add a section

Required, not optional: the registry enforces referential integrity — every tool whose
`toolkit` matches the directory must be mentioned in that directory's SKILL.md, or loading
appends an error (`tools/registry.py`, the `REQUIRED_SKILL_SECTIONS` block and the loop after
it). Keep the four required headings (Purpose, Canonical sequences, Cost posture, Pitfalls) and
add the surrogate chain beside the self-consistency one. Say in Purpose that these draw numbers
and model no chemistry.

### `campaigns/mock-small-molecule-binding.yaml`

Mirror `delta-small-molecule-arms-smoke.yaml`'s goal, objectives and thresholds. Change:
`backend: concurrent`, `backend_config: {workers: 4}`, `tool_delivery: mock`, `stages:` the six
surrogates, a budget sized not to bind, and
`site: {gpu_api: cuda, gpus_per_node: 1, nodes: 1, allow_external: false}` as
`mock-stabilize.yaml` has it. Comment each field with the knob it is, since the README points
at them.

### `campaigns/README.md`

1. **What this mocks** — the six real tools, what each really does, what the surrogate does
   instead, and that the thresholds are the real campaign's.
2. **Running it** — `./scripts/dev_setup.sh`, then `impress-a run ... --model D`; the
   `PYTHONPATH=src python -m impress_a` form; `impress-a preflight`; `impress-a tools`; and
   `--model B` (deterministic rehearsal oracle, no network) against `--model D`. Note
   `--model C` is refused under `run` and needs `serve` + `control` (backlog C6), and that
   `--model A`/`B` reach a live endpoint only with `--model-profile`.
3. **The knobs, in two groups** — tool parameters under the spec's `params:`, and the campaign
   knobs from `CampaignSpec`: `max_cycles`, `stagnation_limit`, `target_front`, `replicas`,
   `concurrency`, `budget`, `objectives`, `max_attempts`, `max_runs`, `max_unproductive_runs`,
   `max_failed_cycles`, `max_admission_failures`, `tool_delivery`, `seed_salt`. Each row: what
   it does, and **what you will see change**.
4. **Three worked experiments**, each a one-line edit, each with its measured before/after
   pasted in after both runs:
   - raise `difficulty` until the Spec stops being satisfied, then past 0.75 to see an
     integrity failure and a trust demotion;
   - raise `target_front` from 1 to 10 and watch the stop reason move from "every spec
     objective satisfied" to `max_cycles=N reached` — this is G11, reproduced on a laptop;
   - set `replicas: 4` and watch the pattern signature change and the first runs go untrusted
     under the 10% cost cap — this is G13.
5. **What it cannot tell you** — the numbers are drawn, not measured; `n` counts readings and
   not distinct designs; and a surrogate chain under `tool_delivery: real` is refused by gate 6
   on purpose.

## Test

1. **Registry loads.** `impress-a tools` lists 18 tools with the six new ones, and
   `Registry().load().errors` is empty. A toolkit that fails anywhere registers **nothing**, so
   a silently missing mock family is the failure to look for.
2. **Preflight.** `impress-a preflight campaigns/mock-small-molecule-binding.yaml` — no FAIL.
3. **It runs.** `impress-a run campaigns/mock-small-molecule-binding.yaml --model D` exits 0
   with a front and a stop reason. Repeat with `--model B`.
4. **The knobs move the behaviour.** Run each README experiment both ways and paste the real
   `cycles` / `stop` / front size in. If a knob does not change the outcome, say so rather than
   claiming it does — a tutorial whose promised effect does not reproduce is worse than none.
5. **Determinism.** Same spec and `seed_salt` twice gives the same stop reason and the same
   metrics. A difference means a draw is keyed on something it should not be, which is the bug
   `_upstream` records twice.
6. **Suite and lint.** `pytest tests -q` (417 at `25550f7`) and `ruff check src tests`, ceiling
   zero. `test_gate_fixtures.py` derives the tool count from the directories and checks the
   registry against them, so it covers the new specs without being edited.

## Environment notes from the session that planned this

Recorded because they cost most of the time available:

- **`pgrep` hangs on the Delta login node.** It scans a process table with thousands of entries
  and does not return inside two minutes. It also returns other users' command lines. Do not
  use it; ask git or `sacct` instead.
- **Home (`/u`) was degraded.** A `git worktree add` into `$CLAUDE_JOB_DIR` never completed.
  Put worktrees on `/work/nvme`.
- **A killed `git worktree add` leaves a stale ref lock** at
  `.git/refs/heads/<branch>.lock` — four levels deep, so `find .git -maxdepth 2 -name '*.lock'`
  misses it. The symptom is a later `add` failing with "cannot lock ref". It can also leave a
  registered worktree marked `locked`, which `git worktree prune` skips until
  `.git/worktrees/<name>/locked` is removed.

## Appendix A — draft agents module, UNVERIFIED

Never imported, never run, never loaded by the registry. Written against the specs described
above; treat every constant as a guess that has not been checked against a composed graph. The
calibration intent is that the **defaults pass** — so a first run succeeds and the knobs have
somewhere to move — and that `difficulty` is what takes that away.

```python
"""Surrogate task agents for the small-molecule binding chain.

A laptop stand-in for `rfd3_design -> ligandmpnn_design -> packmin -> fastrelax ->
filter_shape -> boltz_predict`, with the science replaced by seeded random draws.

**What is faithful, and what is not.** The ports, patterns, parameters, metric names, QC
gates and acceptance thresholds are copied from the real specs, so a reading that clears
`complex_plddt >= 0.75` here cleared the same bar the real campaign measures against. What
produces the number is a hash of the parameters and the upstream metrics. These tools model
no chemistry and their outputs are not evidence about any molecule.

**Why `toolkit: mock` and not a toolkit of their own.** Gate 6 classifies a tool as mock by
`ToolSpec.toolkit == "mock"` exactly, so a surrogate in any other toolkit would be admitted
by a campaign declaring `tool_delivery: real` - a chain of random numbers reported as
science, which is the documented failure that gate exists to prevent.

**The draw propagates down the chain**, which is the point: a knob on the first stage has to
be able to change the last stage's verdict, or there is nothing to learn by turning it.
"""
from __future__ import annotations

from typing import Any

from .agent import TaskAgent, TaskRequest
from .mock_agents import _rng, _upstream


def _inherit(inputs: dict[str, Any], metric: str, default: float) -> float:
    """One upstream metric, or `default` when no upstream reported it.

    Reads the metrics rather than the artifact because a surrogate has no artifact to read -
    the chain's state lives entirely in the numbers. Takes the LAST upstream that reported it
    so a chain reports its most recent estimate, which is what superseding means here.
    """
    value = default
    for _, v in sorted(inputs.items()):
        if isinstance(v, dict):
            metrics = v.get("metrics") or {}
            if metric in metrics:
                value = float(metrics[metric])
    return value


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class MockRFD3DesignAgent(TaskAgent):
    """Backbone generation. `diffusion_steps` buys structure; `difficulty` takes it away."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id))
        steps = int(params.get("diffusion_steps", 50))
        n = int(params.get("num_designs", 1))
        difficulty = float(params.get("difficulty", 0.25))
        # 0.62 at the default 50 steps and 0.25 difficulty, which clears the 0.5 acceptance
        # bar with room; 200 steps reaches ~0.82; difficulty 0.8 drops it to ~0.27, under the
        # integrity floor.
        ss = _clamp(0.62 + 0.30 * (steps - 20) / 180.0 - 0.50 * difficulty
                    + r.uniform(-0.04, 0.04), 0.0, 0.98)
        helix = ss * r.uniform(0.5, 0.7)
        return {
            "result": "backbone", "count": n,
            "outputs": {"backbone": f"backbone[{n}]"},
            "metrics": {
                "ss_fraction": round(ss, 3),
                "num_models": float(n),
                "ca_deviation": round(_clamp(1.6 * (1.0 - ss) + r.uniform(-0.05, 0.10),
                                             0.0, 5.0), 3),
                "ligand_clashes": float(r.choices([0, 0, 0, 1, 2],
                                                  weights=[6, 4, 3, 2, 1])[0]),
                "helix_fraction": round(helix, 3),
                "sheet_fraction": round(max(0.0, ss - helix), 3),
            },
        }


class MockMPNNDesignAgent(TaskAgent):
    """Inverse folding. Low temperature recovers; a wider ensemble gives more to pick from."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        ss = _inherit(req.inputs, "ss_fraction", 0.5)
        temp = float(params.get("temperature", 0.2))
        ensemble = (int(params.get("batch_size", 8))
                    * int(params.get("number_of_batches", 1)))
        # Picking the best of N is worth something, with diminishing returns - the real tool
        # selects the best member of its own ensemble, so this is the shape that mirrors.
        pick = 0.06 * (ensemble ** 0.5 - 1.0)
        base = 0.28 + 0.55 * ss - 0.40 * temp + pick
        overall = _clamp(base + r.uniform(-0.03, 0.03), 0.0, 0.99)
        return {
            "result": "structure", "count": int(params.get("num_seqs", 1)),
            "outputs": {"structure": "complex"},
            "metrics": {
                "overall_confidence": round(overall, 3),
                "ligand_confidence": round(_clamp(overall - r.uniform(0.02, 0.12),
                                                  0.0, 0.99), 3),
                "ensemble_size": float(ensemble),
                "ensemble_paired": 1.0,
            },
        }


class MockPackMinAgent(TaskAgent):
    """Pack and minimise. Reports the pre-relax energy the next stage improves on."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        conf = _inherit(req.inputs, "overall_confidence", 0.5)
        cycles = int(params.get("cycles", 1))
        score = -(120.0 + 220.0 * conf + 18.0 * (cycles - 1)) + r.uniform(-25.0, 25.0)
        return {"result": "structure", "count": 1,
                "outputs": {"structure": "complex"},
                "metrics": {"total_score": round(score, 3)}}


class MockFastRelaxAgent(TaskAgent):
    """Relax. Where the campaign's binding objective is decided."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        pre = _inherit(req.inputs, "total_score", -250.0)
        conf = _inherit(req.inputs, "overall_confidence", 0.5)
        cycles = int(params.get("relax_cycles", 3))
        nstruct = int(params.get("nstruct", 1))
        gain = 1.0 + 0.04 * (cycles - 1) + 0.03 * (nstruct - 1)
        score = pre * gain + r.uniform(-20.0, 20.0)
        return {
            "result": "structure", "count": nstruct,
            "outputs": {"structure": "complex"},
            "metrics": {
                "total_score": round(score, 3),
                "fa_rep": round(_clamp(150.0 - 90.0 * conf - 8.0 * (cycles - 1)
                                       + r.uniform(-12.0, 12.0), 0.0, 600.0), 3),
                "interaction_energy": round(-(4.0 + 22.0 * conf) + r.uniform(-3.0, 3.0), 3),
            },
        }


class MockFilterShapeAgent(TaskAgent):
    """Interface shape complementarity, carrying the real 0.55 acceptance bar."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        ie = _inherit(req.inputs, "interaction_energy", -12.0)
        sc = _clamp(0.40 + 0.016 * min(28.0, -ie) + r.uniform(-0.03, 0.03), 0.0, 0.95)
        return {"result": "structure", "count": 1,
                "outputs": {"structure": "complex"},
                "metrics": {"shape_complementarity": round(sc, 3),
                            "sc_selector_mode": 1.0}}


class MockBoltzPredictAgent(TaskAgent):
    """Co-folding. The stage the campaign's `complex_plddt` bar sits on."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        r = _rng((self.spec.id, params, req.node_id, _upstream(req.inputs)))
        sc = _inherit(req.inputs, "shape_complementarity", 0.55)
        conf = _inherit(req.inputs, "overall_confidence", 0.5)
        samples = int(params.get("diffusion_samples", 8))
        pick = 0.05 * (samples ** 0.5 - 1.0)
        plddt = _clamp(0.34 + 0.42 * sc + 0.22 * conf + pick + r.uniform(-0.03, 0.03),
                       0.0, 0.98)
        return {
            "result": "complex", "count": 1,
            "outputs": {"complex": "complex"},
            "metrics": {
                "complex_plddt": round(plddt, 3),
                "ligand_iptm": round(_clamp(plddt - r.uniform(0.0, 0.10), 0.0, 0.98), 3),
                "ensemble_size": float(samples),
                "ensemble_paired": 1.0,
            },
        }


__all__ = ["MockBoltzPredictAgent", "MockFastRelaxAgent", "MockFilterShapeAgent",
           "MockMPNNDesignAgent", "MockPackMinAgent", "MockRFD3DesignAgent"]
```

## Appendix B — draft spec, UNVERIFIED

`mock_rfd3_design` only, because it is the one carrying the novel `difficulty` parameter; the
other five follow the five-step recipe above from their real counterparts.

```yaml
id: mock_rfd3_design
toolkit: mock
version: "0.1"
pattern: P1
entry: impress_a.tools.mock_smb_agents.MockRFD3DesignAgent
resources: {gpus: 1, cores: 8, walltime_s: 30}
gpu_portability: {cuda: proven, hip: unproven, sycl_xpu: unproven}
outputs:
  backbone: {type: Backbone}
parameters:
  num_designs: {type: int, default: 1, min: 1, max: 64, trades: "coverage vs GPU-hours"}
  diffusion_steps: {type: int, default: 50, min: 20, max: 200, trades: "quality vs wall-clock"}
  seed: {type: int, default: null, min: 0, max: 2147483647,
         trades: "per-lineage draw; replicas are only independent if this is honoured"}
  input_spec_path: {type: str, default: ""}
  # THE ONE PARAMETER WITH NO REAL COUNTERPART. rfd3 has no such flag; this is the
  # surrogate's own dial, so a reader can make the campaign easy or impossible without
  # editing a threshold. Above ~0.75 it drives `ss_fraction` under the
  # `has_secondary_structure` floor of 0.3, which is an INTEGRITY failure rather than a weak
  # design - the node fails and the pattern's trust suffers (decision 0013).
  difficulty: {type: float, default: 0.25, min: 0.0, max: 1.0,
               trades: "how hard this campaign is; surrogate-only, no rfd3 counterpart"}
metrics: [ss_fraction, num_models, ca_deviation, ligand_clashes,
          helix_fraction, sheet_fraction]
qc_gates:
  - {id: output_present, params: {key: result}}
  - {id: has_secondary_structure, params: {min_ss_fraction: 0.3}}
  - {id: metrics_reported, params: {metrics: [ss_fraction, num_models]}}
  - {id: metric_in_range, role: acceptance, params: {metric: ss_fraction, min: 0.5}}
cost_model: {unit: invocation, cost: {gpu_hours: 0.002}}
```
