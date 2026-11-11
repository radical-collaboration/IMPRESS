# radical.asyncflow: start_telemetry does not expose rhapsody's drain_on_stop

**Component:** radical.asyncflow 0.7.0 (`src/radical/asyncflow/workflow_manager.py`, checked at
`482f166`) with rhapsody-py 0.7.0 · **Severity:** feature gap; a slow shutdown near walltime
cannot skip the drain · **Status:** diagnosed, not reported upstream
**Evidence:** signatures at the commits above; IMPRESS `agent/src/impress_a/runtime/executor.py:
_stop_telemetry`.

## What we saw

rhapsody 0.7.0 added `drain_on_stop=False` so that a shutdown close to a job's walltime can
discard the event backlog instead of processing it. `Session.start_telemetry` exposes it
(`rhapsody/api/session.py:319`). `WorkflowEngine.start_telemetry` does not, so an asyncflow
caller cannot reach it.

## Cause

`WorkflowEngine.start_telemetry` (`workflow_manager.py:272-280`) takes `resource_poll_interval`,
`checkpoint_interval`, `checkpoint_path`, `span_processors`, `metric_readers` and `resource`, and
builds `TelemetryManager(...)` (`:308`) without `drain_on_stop`, which `TelemetryManager.__init__`
accepts (`rhapsody/telemetry/manager.py:122`).

## Fix

Add `drain_on_stop: bool = True` to `start_telemetry` and forward it, as `Session.start_telemetry`
does. A related note for the docs: `flow.shutdown()` does not stop telemetry, so a caller has to
call `stop()` itself, from the same task that started it. A `stop()` run in a different task
(e.g. under `asyncio.wait_for(asyncio.shield(...))`) makes OpenTelemetry log "Failed to detach
context ... created in a different Context". This was reproduced with plain asyncflow and a
single block.

## Impact on us

IMPRESS-A bounds `telemetry.stop()` with `asyncio.timeout` before the engine's bounded teardown.
That is the only way to cut a stalled drain short today, and it cancels mid-drain rather than
skipping it cleanly.
