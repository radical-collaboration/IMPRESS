# AuCaM Integration

How IMPRESS-A offers itself to an enclosing campaign manager as one subordinate workflow, and
what that relationship is not.

AuCaM (`radical-project/campaign_manager`) is the canonical superstrate: it orchestrates many
heterogeneous workflows toward a higher goal, launches each as an `async def` taking a reporter,
sizes it from a declared cost, bounds its spending, may pause or cancel it, and reads its progress
back through `reporter.emit()`. One IMPRESS-A campaign is one such workflow.

## The seam

```
   AuCaM  ── launches the block ──►   impress_a_<spec>(reporter, context)
     │       declared_spending            │
     │       spending_limit ──────────────┤  narrows CampaignSpec.budget
     │       resources ───────────────────┤  fits concurrency
     │                                    │
     │  ◄── reporter.emit(score, ─────────┤  one CampaignDigest per absorbed cycle
     │       metrics, iteration)          │
     └──── PAUSE / RESUME ───────────────►┘  gates admission only
                                          │
                                   the campaign keeps its own engine,
                                   its own cycle loop, and the decision to stop
```

Two modules, and the split is deliberate:

| Module | Role |
|---|---|
| `integrations/reporting.py` | Transport-neutral. The `CycleSink` protocol, `JsonlSink`, the `Bridge` pump and `run_with_sink`. **Names no superstrate's vocabulary** — an in-process block function, an HTTP poller and a subprocess reporting over Redis are three sinks, not three payloads |
| `integrations/aucam.py` | The adapter. **The only module in the package that imports AuCaM**, which `tests/test_layering.py` asserts, so the dependency stays optional and one file wide |

The pump never touches the executor. It reads `observe()`, which is synchronous and await-free by
invariant, and awaits the sink outside it, so no `await` enters a mutating block and the
one-writer property is untouched.

**The trigger is `observe().seq`, the absorption watermark, not `cycle`.** `cycle` is incremented
in `_dispatch`, so it counts *submissions*, and a report fired there would carry no results. `seq`
advances once per lineage absorbed, which is exactly when there is something new to say. The
`report_interval_s` is therefore a **floor and not the only trigger**: a cycle of the real chain
runs minutes of tasks with nothing absorbed, and a caller's staleness bound has to stay satisfiable
while that happens.

`run_with_sink` sends one report before the campaign starts, so a caller has a liveness anchor
before there is any work to describe, and one after it ends — and the last one must be the real
one, because the stores a caller reads these through keep only the last value per workflow.

Whatever the sink, the digests are also kept on disk: `JsonlSink` writes one JSON line each under
the campaign root at `reports/<sink>.jsonl`, deliberately **not** under `provenance/`, where the
executor is the only writer — a report is a record of what somebody else was told, not a campaign
record. So a campaign can be asked afterwards what it reported, and when.

What `integrations/aucam.py` exposes:

| Function | What it is for |
|---|---|
| `workflow_config(spec_path, …)` | An AuCaM `WorkflowConfig` for one whole campaign, built from the same `impress-a offer` a caller could read for itself |
| `make_impress_worker(spec_path, …)` | The block function AuCaM launches. Builds the campaign *inside* the coroutine |
| `launch_bounds(offer)` | `{dimension: (floor, ceiling)}` for the caller's own `LaunchRequest.bounds` |
| `reward_fn(result)` | A `WorkflowResult` as a reward in `[0, 1]`, for `BanditSchedulingPolicy(reward_fn=…)` |
| `report_once(manager, reporter)` | One digest on demand, for a campaign somebody else is driving |

`launch_bounds` is separate from `workflow_config` because `bounds` is a `LaunchRequest` field
and not a `WorkflowConfig` one: the controller attaches it per launch, and `SchedulingPolicy.size()`
then picks a point inside it using learned costs this side never sees.

`reward_fn` exists because AuCaM's default bandit reward is `1.0 if returncode == 0 else 0.0` —
throughput — and no shipped AuCaM policy can rank a dict. A cancelled or failed campaign scores 0
whatever it had found, because the bandit is choosing whether to launch this arm again and a run
that could not finish is not evidence that it would.

## A caller, not a control model

The tempting reading is that an outer manager is control model C: there is already a headless
mode, an external half and a control plane. That reading is wrong, and
[decision 0014](../decisions/0014-an-enclosing-campaign-manager-is-not-a-control-model.md) is the
record of why — every design that follows from it differs.

| | Model C | An enclosing campaign manager |
|---|---|---|
| What it is | a **reasoner** over `CampaignSession` | the **owner of the process** |
| What it does | publishes Specs, submits Stages, answers a rejection through `replan` | launches, bounds a budget, allots resources, pauses, cancels, reads reports |
| What it is refused by | the same six gates as any policy | nothing: it proposes no graph |
| Its opinion | which tool runs next | whether this campaign deserves to be running |

So `CampaignControlPlane` gains no operation, and the adapter registers no control plane at all.
See [Control Models](control-models.md) for what model C actually is, and
[Pluggable Frontends](frontends.md) for where each kind of caller plugs in.

Three consequences of that ruling are visible in the adapter and worth knowing before you read it:

**A spending limit arrives as a budget, not as a kill switch.** `_narrow_budget` applies
`min(current, limit)` to `CampaignSpec.budget` — the adapter's load-bearing line. A limit enforced
from outside can only cancel a campaign *after* it has overspent; the same number as a budget is
refused from the inside by `reserve` and gate 5 *before* a task runs, and the campaign stops itself
with a reason naming the dimension instead of being killed with work in flight.

**The caller is told measured cost, not declared.** `BudgetLedger.spent` holds the declared figure,
which is inflated on purpose because it feeds gates that refuse graphs. Reporting it upward would
misinform the caller by the full headroom and leave its learned-cost estimate permanently wrong, so
the digest carries `cost_measured` under `cpu_hours`/`gpu_hours` — the keys AuCaM's own
`_spent_so_far` reads.

**Pause gates admission only.** In-flight runs are allowed to finish, because cancellation is
advisory and a reclaimed GPU is not something this system can promise. A paused campaign therefore
keeps spending for up to one cycle, and the offer declares that.

## Sizing an invocation

```bash
impress-a offer campaigns/<spec>.yaml           # what one invocation would cost, and which
                                                # goals the toolkit could address
impress-a offer campaigns/<spec>.yaml --json    # the form a caller reads to size its own spec
impress-a offer campaigns/<spec>.yaml --validation validate_tasks.json
```

The handshake is a **caller-side function call made before the caller's own spec exists**, not a
plane operation — AuCaM's `declared_spending`, `spending_limit` and `resources` are static dicts
fixed when the caller builds its spec, so there is nothing to negotiate at launch.

A different question from `preflight`: that asks whether this machine can run the binaries, this
asks what a caller is buying.

`--validation` is **the only route by which a measured figure enters an offer.** Everything else is
declared, and the payload says so. Declared cost models sit multiples above measurement on purpose,
because they feed gates that *refuse* graphs — so an offer states its basis and never passes for a
prediction. `workflow_config` logs the offer's `warnings` rather than discarding them, so a caller
that never read the offer still hears that the estimate is parameter-blind.

The offer also declares `report_interval_s`, so a caller's staleness bound can be a multiple of it.
`workflow_config` sets `stale_timeout_s` to **4×** that interval rather than AuCaM's stated 3×
minimum, because 3× is the floor the contract names rather than a margin, and a child of this
process can spend minutes in `import pyrosetta` alone off slow storage.

## Installing it

```bash
pip install -e ".[aucam]"
python -c "import src.aucam, impress_a.integrations.aucam"    # the check CI runs
```

Both `scripts/dev_setup.sh` and CI install this extra, so a skipped `tests/test_aucam.py` is a real
failure rather than an absent optional — see the first gotcha below.

## Gotchas

**The import name is `src.aucam`, not `aucam`.** The distribution is named `aucam`, but upstream's
`[tool.setuptools.packages.find]` declares `include = ["src*"]`, so the importable package is the
generic name `src` — which setuptools itself warns about at install time. This repository has
`src/` at its root and `agent/src/` under it, neither a package, so a same-named namespace portion
sits ahead of AuCaM's on the path whenever the working directory is either one. It resolves because
a regular package beats a namespace portion. `_aucam()` tries `src.aucam`, then `aucam` in case
upstream ever renames, and otherwise raises an error naming the resolved `src.__path__` — because
when this breaks, the message must say so rather than blame the adapter.

**A skip is not a pass.** `tests/test_aucam.py` opens with
`pytest.importorskip("src.aucam")`, so without the extra the whole file exits 0 and the suite looks
green. CI therefore installs the extra *and* runs the import check above as its own step, which
fails loudly instead.

**The pin is a fact about a moment, not a version.** The extra pins a 40-character commit, and
`tests/test_toolchain.py::test_the_aucam_extra_pins_a_commit_not_a_branch` holds it that way — a
branch pin reinstalls something different next week and moves this tier under us. What that test
cannot express is *which* ref the commit came from:

| Ref | Relationship to the pin |
|---|---|
| `aucam-v2` | the pinned commit is this branch's **tip** |
| `devel` (upstream default) | a different, **older** commit — the pin is ahead of it |
| `main` / `master`, newest tag `v0.2.1` | the pre-v2 line |

So the adapter is written against an in-progress branch that upstream has not merged or tagged,
and three things follow. `aucam-v2` will advance, so the pin needs deliberate bumping and the
adapter may need to move with it. There is no tag to pin instead, because the v2 work is untagged.
And if that branch is rebased, force-pushed or deleted once it lands, a pinned SHA can stop being
fetchable and `pip install -e ".[aucam]"` fails — a red CI run whose cause is in another
repository. `aucam` is not on PyPI, which is why the extra is a git requirement at all.

**The adapter does not take AuCaM's engine.** AuCaM passes its shared `WorkflowEngine` to a block
that asks for one; this block does not declare `flow`. `WorkflowEngine.__init__` captures the loop
it is built on, and the executor builds its own through the only sanctioned constructor,
`exec.backend.make_engine_bounded`, which also bounds Dragon's synchronous startup. There is no
"use this engine instead" seam, and inventing one is how two allocations were spent on an engine
that dispatched nothing. The cost of not taking it is that our tasks are invisible to AuCaM's
per-task telemetry, so its task-level charging never applies — which is why spending travels in our
own reports.

**Liveness runs outward.** `control_liveness_timeout_s` cannot protect a campaign under an
enclosing manager: the pump calls `observe()`, and `observe()` calls `touch()`, which refreshes the
very clock that bound reads. A campaign with a pump attached therefore cannot detect a lost caller
by silence, and liveness has to come from the enclosing manager's own staleness bound. Recorded as
finding 7 of [Observation](observation.md).

**`wall_hours` is declared but never offered as a limit.** It is an input to AuCaM's proration, not
a dimension it bills, and offering it as a limit would cancel a campaign for taking the time it
said it would take. It *is* reported in `declared_spending`, at the offer's ceiling, because too
small a figure makes AuCaM's proration exceed 100% and cancel a campaign that is behaving normally.

## What is not built

**The off-process path.** Everything above runs the campaign *in* the caller's process, as a block
function. A campaign inside its own `sbatch`, reporting to an AuCaM running elsewhere, is the
variant that is not built: `CycleSink` is already the seam for it — it names no superstrate — and
the implementation would be a reporter over a Redis or Dragon `DataBackend` reachable from the
compute node. The backlog holds it open deliberately, as worth doing only after the in-process path
has run once on real hardware.

That is also the honest status of this page: the adapter is exercised on every push, by a real
AuCaM campaign driving a real IMPRESS-A one, but on CI runners rather than in an allocation.

## What the tests prove

`tests/test_aucam.py` drives a real campaign through a real AuCaM `WorkflowReporter` — no fake
reporter and no stub config, because a test written against a double would not have caught the
thing that actually bit, the `src.aucam` import name. Eight tests:

- a `WorkflowConfig` the real AuCaM accepts
- a campaign runs as one AuCaM workflow and reports through its reporter
- the score is a float a bandit can rank
- the metrics carry *measured* spending under the keys AuCaM charges against
- the caller's spending limit becomes the campaign's own budget
- a PAUSE from AuCaM is translated into the bridge's own vocabulary
- the bounds a caller attaches are not on the `WorkflowConfig`
- an AuCaM campaign launches a whole IMPRESS campaign and charges what it reported

`tests/test_toolchain.py` adds the two packaging guards: that the extra pins a commit rather than a
branch, and that `src.aucam` resolves to the installed AuCaM rather than to a directory in this
repository.
