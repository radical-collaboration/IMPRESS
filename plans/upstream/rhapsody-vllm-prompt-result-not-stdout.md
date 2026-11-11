# rhapsody + asyncflow: a prompt_task routed to DragonVllmInferenceBackend never resolves

**Component:** rhapsody-py 0.7.0 (`src/rhapsody/backends/ai/vllm.py`, checked at `aca8e3e`) with
radical.asyncflow 0.7.0 (`src/radical/asyncflow/workflow_manager.py`, `482f166`) · **Severity:**
the documented AI route hangs · **Status:** diagnosed, not reported upstream
**Evidence:** reproduced 2026-11-11 with a stand-in backend that completes a task exactly as
`vllm.py:390-392` does (IMPRESS `agent/tests/test_infer.py: FakeVllm`). The prompt task's future
never resolved (process killed at 60 s). The identical stand-in that also sets `stdout` resolves
at once.

## What we saw

asyncflow's `docs/multi_backend.md` routes `@flow.prompt_task(backend="ai")` to an inference
backend from rhapsody. With `DragonVllmInferenceBackend`, that future never completes.

## Cause

The backend reports a finished prompt with its answer in `task["response"]`, a list with one
entry per prompt, each a Dragon Inference dict `{"assistant": ...}`, then calls back DONE
(`vllm.py:390-392`). asyncflow resolves any non-function task from `component["stdout"]` (the
prompt path sets `FUNCTION` to `None`, `workflow_manager.py:916-923`, so `handle_component_success`
takes the `stdout` branch). The key is absent, so the callback fails and the future is never
set.

A second defect on the same path: a batch that times out is reported **DONE**, with answers
like `"ERROR: Batch timeout, response 1 not received"` (`vllm.py:374`). A consumer receives
an error message as if the model had said it.

## Fix

In `vllm.py`, when completing a task, also set `task["stdout"]` to the unwrapped text
(`_unwrap_assistant_response` already exists, `:40`). Report a timed-out or errored prompt as
FAILED, with the message in `task["exception"]`/`stderr`. Alternatively, asyncflow could read
`response` for prompt tasks, but the backend contract that every other backend follows
(`stdout`) is the better place to fix it.

## Impact on us

IMPRESS-A runs a locally hosted reasoner's calls as prompt tasks on this backend. Local
workaround: `agent/src/impress_a/exec/backend.py: PromptResults` wraps the backend's state
callback. It copies the unwrapped answer to `stdout` and turns an in-band `ERROR:` string into
FAILED. It is removed when this is fixed.
