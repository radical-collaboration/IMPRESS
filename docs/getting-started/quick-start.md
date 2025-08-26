# Build Asynchronous Protein Pipelines

This tutorial walks you step-by-step through writing and running an **asynchronous workflow of multiple protein pipelines** using **IMPRESS** manager.

By the end, you will have a working script that runs *N pipelines concurrently*, each of which executes 3 tasks asynchronously.

---

## Overview

We’ll build:

✅ A **custom pipeline class**, `ProteinPipeline`, which represents one protein analysis pipeline.  
✅ A **script to start all pipelines asynchronously**.

You can adapt the number of pipelines (`N`) and tasks as needed.

---

## Step 1: Import the Required Libraries

First, we import the libraries we need:

```python
import asyncio

from impress import PipelineSetup
from impress import ImpressBasePipeline
from impress import ImpressManager

from radical.asyncflow import RadicalExecutionBackend
```


We use:

asyncio — Python’s built-in asynchronous library.

RadicalExecutionBackend — runs tasks in parallel.

ImpressBasePipeline — base class for defining a pipeline.

ImpressManager — manages and executes multiple pipelines.

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

Initialize some dummy sequences and scores.

Call the parent constructor to properly set up the pipeline.

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

Here we define 3 tasks:

Each task is registered automatically to the pipeline.

### 2.3 Run the Pipeline

```python
async def run_pipeline(self): # The tasks will execute sequentially
    s1_res = await self.s1() 
    s2_res = await self.s2()
    s3_res = await self.s3()
```

This method controls the execution order:
Run s1, then s2, then s3 asynchronously.
Print the result of each task along with the pipeline name.

!!! tip

You can change the execution order of your tasks by passing the handler of each task (without `await`) to the other task that depends on it.
For Example: to make `s3` wait for both `s1` and `s2` execution, then you can rewrite your function as follows:

```python
async def run_pipeline(self): # s1/s2 starts first in parallel and s3 will wait for them
    s1_fut = self.s1()
    s2_fut = self.s2()
    s3_res = await self.s3(s1_fut, s2_fut)
```


## Step 3: Create and Run Multiple Pipelines
We now create a function that starts N pipelines at once.

```python
async def run():
    manager = ImpressManager(
        execution_backend=RadicalExecutionBackend({'resource': 'local.localhost'})
    )
    
    # start 3 pipelines in parallel and wait for them to finish
    await manager.start(
        pipeline_setups = [
            PipelineSetup(name='p1', type=ProteinPipeline),
            PipelineSetup(name='p2', type=ProteinPipeline),
            PipelineSetup(name='p3', type=ProteinPipeline)]
    )
```

Here:

We initialize an ImpressManager with a RadicalExecutionBackend to enable parallel task execution.

We call start() and provide a list of pipeline setups, each with a unique name (p1, p2, p3) and our ProteinPipeline class.

You can add more pipelines by adding more entries to the list.

## Step 4: Run the Script
Finally, add the entry point to run everything with `asyncio`:

```python
if __name__ == "__main__":
    asyncio.run(run_pipeline())
```

This starts the event loop and runs all the pipelines concurrently.

💻 Full Code
Here is the complete script for convenience:

```python
import asyncio

from impress import PipelineSetup
from impress import ImpressBasePipeline
from impress import ImpressManager

from radical.asyncflow import RadicalExecutionBackend


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

async def run_pipeline():
    manager = ImpressManager(
        execution_backend=RadicalExecutionBackend({'resource': 'local.localhost'})
    )

    await manager.start(
        pipeline_setups = [
            PipelineSetup(name='p1', type=ProteinPipeline),
            PipelineSetup(name='p2', type=ProteinPipeline),
            PipelineSetup(name='p3', type=ProteinPipeline)]
    )


if __name__ == "__main__":
    asyncio.run(run_pipeline())
```

Each pipeline runs its three tasks in order, and all pipelines run concurrently.