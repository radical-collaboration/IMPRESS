# Build Asynchronous Protein Pipelines

This tutorial walks you step-by-step through writing and running an **asynchronous workflow of multiple protein pipelines** using **IMPRESS** manager.

By the end, you will have a working script that runs *N pipelines concurrently*, each of which executes 3 tasks asynchronously.

---

## Overview

We’ll build:

- A **custom pipeline class**, `ProteinPipeline`, which represents one protein analysis pipeline.
- A **script to start all pipelines asynchronously**.

You can adapt the number of pipelines (`N`) and tasks as needed.

---

## Step 1: Import the Required Libraries

First, we import the libraries we need:

```python
import asyncio

from impress import PipelineSetup
from impress import ImpressBasePipeline
from impress import ImpressManager

from radical.asyncflow import WorkflowEngine
from rhapsody.backends import RadicalExecutionBackend
```


We use:

- `asyncio` — Python's built-in asynchronous library.
- `WorkflowEngine` — the `radical.asyncflow` engine that submits tasks to an execution backend.
- `RadicalExecutionBackend` — an execution backend (from `rhapsody`) that runs tasks in parallel through RADICAL-Pilot.
- `ImpressBasePipeline` — base class for defining a pipeline.
- `ImpressManager` — manages and executes multiple pipelines.
- `PipelineSetup` — describes one pipeline to submit.

!!! note

    `rhapsody` is installed separately (`pip install rhapsody-py`). To try
    this tutorial without it, use `LocalExecutionBackend` from
    `radical.asyncflow` instead:

    ```python
    from concurrent.futures import ThreadPoolExecutor
    from radical.asyncflow import LocalExecutionBackend

    backend = await LocalExecutionBackend(ThreadPoolExecutor())
    ```

## Step 2: Define a Custom Pipeline
We now define our custom ProteinPipeline.
This simulates a simple workflow operating on dummy protein sequences.

```python
class ProteinPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs={}, **kwargs):
        # Simulated sequence data and scores
        self.iter_seqs = {f"protein_{i}": f"sequence_{i}" for i in range(1, 4)}
        self.current_scores = {f"protein_{i}": i * 10 for i in range(1, 4)}
        self.previous_scores = {f"protein_{i}": i * 10 for i in range(1, 4)}

        super().__init__(name, flow, **configs, **kwargs)
```

Here we:

- Initialize some dummy sequences and scores.
- Call the parent constructor to properly set up the pipeline. The
  constructor calls `register_pipeline_tasks()`, so any attributes your
  tasks need should be set before `super().__init__()`.

### 2.2 Register Tasks
```python
    def register_pipeline_tasks(self):
        @self.auto_register_task()
        async def s1(*args, **kwargs):
            return "python3 run_homology_search.py"

        @self.auto_register_task()
        async def s2(*args, **kwargs):
            return "python3 annotate_domains.py"

        @self.auto_register_task()
        async def s3(*args, **kwargs):
            return "python3 predict_structure.py"
```

Here we define 3 tasks. Each one is registered on the pipeline by
`auto_register_task()` and becomes callable as `self.s1()`, `self.s2()`,
`self.s3()`. A task returns the shell command to execute; the commands
above are placeholders for your own tools.

### 2.3 Run the Pipeline

```python
    async def run(self):  # The tasks will execute sequentially
        s1_res = await self.s1()
        s2_res = await self.s2()
        s3_res = await self.s3()
```

`run()` controls the execution order: run `s1`, then `s2`, then `s3`.

`register_pipeline_tasks()` and `run()` are the only methods a pipeline
must implement. `finalize()` is optional and is a no-op by default.

!!! tip

    You can change the execution order of your tasks by passing the handle
    of each task (without `await`) to the task that depends on it. For
    example, to make `s3` wait for both `s1` and `s2`, which run in
    parallel:

    ```python
    async def run(self):  # s1/s2 start in parallel; s3 waits for both
        s1_fut = self.s1()
        s2_fut = self.s2()
        s3_res = await self.s3(s1_fut, s2_fut)
    ```


## Step 3: Create and Run Multiple Pipelines
We now create a function that starts N pipelines at once.

```python
async def run_pipelines():
    backend = await RadicalExecutionBackend({'resource': 'local.localhost'})
    flow = await WorkflowEngine.create(backend=backend)
    manager = ImpressManager(flow)

    # start 3 pipelines in parallel and wait for them to finish
    try:
        await manager.start(
            pipeline_setups = [
                PipelineSetup(name='p1', type=ProteinPipeline),
                PipelineSetup(name='p2', type=ProteinPipeline),
                PipelineSetup(name='p3', type=ProteinPipeline)]
        )
    finally:
        await flow.shutdown()
```

Here:

- We create an execution backend, build a `WorkflowEngine` on it, and pass
  the engine to `ImpressManager`.
- We call `start()` with a list of pipeline setups, each with a unique name
  (`p1`, `p2`, `p3`) and our `ProteinPipeline` class. `start()` returns once
  every pipeline (and any adaptive work it triggered) has finished.
- The caller owns the engine: `ImpressManager` never creates or shuts down
  the flow, so we shut it down ourselves in a `finally` block.

You can add more pipelines by adding more entries to the list.

## Step 4: Run the Script
Finally, add the entry point to run everything with `asyncio`:

```python
if __name__ == "__main__":
    asyncio.run(run_pipelines())
```

This starts the event loop and runs all the pipelines concurrently.

## Full Code
Here is the complete script for convenience:

```python
import asyncio

from impress import PipelineSetup
from impress import ImpressBasePipeline
from impress import ImpressManager

from radical.asyncflow import WorkflowEngine
from rhapsody.backends import RadicalExecutionBackend


class ProteinPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs={}, **kwargs):
        self.iter_seqs = {f"protein_{i}": f"sequence_{i}" for i in range(1, 4)}
        self.current_scores = {f"protein_{i}": i * 10 for i in range(1, 4)}
        self.previous_scores = {f"protein_{i}": i * 10 for i in range(1, 4)}

        super().__init__(name, flow, **configs, **kwargs)

    def register_pipeline_tasks(self):
        @self.auto_register_task()
        async def s1(*args, **kwargs):
            return "python3 run_homology_search.py"

        @self.auto_register_task()
        async def s2(*args, **kwargs):
            return "python3 annotate_domains.py"

        @self.auto_register_task()
        async def s3(*args, **kwargs):
            return "python3 predict_structure.py"

    async def run(self):
        s1_res = await self.s1()
        s2_res = await self.s2()
        s3_res = await self.s3()

async def run_pipelines():
    backend = await RadicalExecutionBackend({'resource': 'local.localhost'})
    flow = await WorkflowEngine.create(backend=backend)
    manager = ImpressManager(flow)

    try:
        await manager.start(
            pipeline_setups = [
                PipelineSetup(name='p1', type=ProteinPipeline),
                PipelineSetup(name='p2', type=ProteinPipeline),
                PipelineSetup(name='p3', type=ProteinPipeline)]
        )
    finally:
        await flow.shutdown()


if __name__ == "__main__":
    asyncio.run(run_pipelines())
```

Each pipeline runs its three tasks in order, and all pipelines run concurrently.