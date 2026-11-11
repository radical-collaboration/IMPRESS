# Pipelines as asyncflow blocks

**2026-11-11.** Recorded, not started. Backlog **F26**.

## Why

`ImpressBasePipeline` and `ImpressManager` predate asyncflow's `@flow.block`, and they hand-build
what a block now gives natively:

| The pipeline layer has | A block has |
|---|---|
| `ImpressManager.start()` polling every 0.5 s (F12) | `asyncio.wait` on block futures |
| A pipeline's result reachable only as a dict key (F4) | The block's future is its result |
| `kill_parent`, which cancels the pipeline's asyncio Task and never reaches the backend | `block_fut.cancel()` cascades to every unfinished member, each cancel sent to the backend that runs it (asyncflow 0.7.0, #118) |
| `submit_child_pipeline_request`, a single-slot mailbox a second request overwrites | A child is a new block call; there is no mailbox |
| An exit as soon as nothing is in flight, so a long-lived caller needs a keep-alive pipeline | Nothing to keep alive: there is no manager loop |
| `{pipeline}:{stage}` labels, set by hand | Members inherit the block in telemetry and carry an explicit `workflow_id` |

IMPRESS-A (`agent/`) made this move on branch `agent/one-engine`: each Stage is a block
(`agent/src/impress_a/exec/stage.py`). Its parity test replays a campaign recorded from the
loop it replaced and gets the same result. A cancel test shows that a queued command never
starts once its Stage is cancelled. That loop never ran on hardware, which is why the agent did
not wait for this change.

## The mapping

- **A pipeline is a block.** `run()` becomes the block body. Its stages stay tasks, called
  inside the body so they register as members.
- **`adaptive_fn` is a member task on the `local` route**, as F19 already declares it, called
  from the body where `run_adaptive_step()` sits today. Its exceptions surface on its future
  instead of being swallowed (F9).
- **A child pipeline is a block** that the parent's body (or its adaptive task) calls. The
  manager's role shrinks to: start the initial blocks, wait on whatever is in flight, report.
- **`kill_parent` is `block.cancel()`** on the parent.

## What has to be decided first

- **Python floor.** asyncflow 0.7.0 requires 3.11. Root is `>=3.9`, and its 3.9/3.10 CI legs
  resolve an older asyncflow. Either the framework keeps a pre-0.7 path (blocks exist from 0.5,
  but the cancel cascade to the right backend is 0.7.0), or root moves to 3.11.
- **Compatibility.** Every example subclasses `ImpressBasePipeline`. Keep the class as a thin
  shim that builds the block, or migrate the examples in the same change.

## How it will be tested

- Unit: a pipeline's result arrives on its future, a cancelled parent cancels its queued stages
  on their backend, and two children requested in one sweep both run.
- Re-run each example's acceptance on Delta (smb, protein_binding, discontinuous_scaffolds) and
  compare against its recorded baseline. The row closes on those runs, not on the unit tier.

Closes, if it lands as described: F4, F9, F12, F16, F21 (that bare-`adaptive_fn` failure lives
in the mailbox path this removes).
