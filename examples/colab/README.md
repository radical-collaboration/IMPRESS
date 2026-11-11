# A runnable IMPRESS quickstart

The helper behind the Colab notebook at
[`docs/notebooks/impress_adaptive_quickstart.ipynb`](../../docs/notebooks/impress_adaptive_quickstart.ipynb).

Unlike the other directories under `examples/`, this one needs **no allocation, no
GPU, no model weights and no rhapsody**. It runs on a laptop in about five
seconds, on nothing but `impress` and `radical.asyncflow`.

Everything about the framework here is real: a real `ImpressManager`, a real
`WorkflowEngine` on asyncflow's `LocalExecutionBackend`, real executable tasks
that start real subprocesses, and real adaptive child-pipeline spawning. Only
the science is simulated. **Every score is a seeded pseudo-random draw and says
nothing about any protein.** What the run measures is the framework's own
behaviour: when it decides to spawn a child pipeline, and what that does to the
shape of the run.

## The files

| File | What it is |
|---|---|
| `toy_science.py` | The simulated scoring model and the adaptive rule, as pure functions. Standard library only -- no IMPRESS import, no event loop. |
| `score_stage.py` | One analysis stage as a standalone process. The pipeline's tasks exec it, so the scores arrive as a task's stdout. |
| `impress_toy.py` | The pipeline, the adaptive callback, the event recorder and the runner. |
| `toy_figures.py` | The figures. Imports matplotlib lazily, so `impress_toy` works without a plotting stack. |

## Running it outside Colab

```bash
pip install "radical.asyncflow>=0.5.1" pydantic
pip install --no-deps .          # from the repository root

python - <<'EOF'
import asyncio, sys
sys.path.insert(0, "examples/colab")
from toy_science import ToyConfig
from impress_toy import run_toy, summary_table

async def main():
    result = await run_toy(ToyConfig(degradation_threshold=2.0))
    for row in summary_table(result):
        print(row)

asyncio.run(main())
EOF
```

`--no-deps` is deliberate. `impress` declares `radical.pilot` but never imports
it -- the only `radical` import in `src/` is `radical.asyncflow` -- and
`radical.pilot` is published as an sdist with a C extension, so installing it
turns a few seconds into a few minutes for a run that will never use it. Install
it normally when you are going to an HPC backend.

In a notebook, use top-level `await` rather than `asyncio.run`: `WorkflowEngine`
requires a running event loop and a notebook already has one.

## Three things to know before changing it

**Commands use bare tokens only.** `LocalExecutionBackend` receives the command
string, `shlex.split`s it, and re-joins the parts with spaces, so quoting is
lost: `'two words'` arrives as two separate arguments. That is backlog F15. This
is why `score_stage.py` takes eight positional scalars rather than anything that
would need quoting.

**The adaptive function must be a declared engine task.** `PipelineSetup` raises
`TypeError` on a bare coroutine, and so does a child config that carries one.
Declare it with `flow.function_task(...)` on a **thread** pool -- it mutates the
live pipeline object, and a process pool would mutate a pickled copy.

**The generation cap is the only thing stopping unbounded recursion.** The
framework has no generation concept and enforces no limit of its own.
`ImpressManager.start()` returns when no pipeline is left, so a rule that always
spawns never returns.

## Tests

```bash
pytest tests/unit/test_colab_toy.py              # arithmetic and the event log
pytest tests/integration/test_colab_toy_run.py   # a real run, ~45s
```
