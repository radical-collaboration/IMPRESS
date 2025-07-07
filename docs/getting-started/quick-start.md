# 🚀 Tutorial: Submit N Protein Pipelines Asynchronously

This tutorial walks you step-by-step through writing and running an **asynchronous workflow of multiple protein pipelines** using **Impress** and **Radical AsyncFlow**.

By the end, you will have a working script that runs *N pipelines concurrently*, each of which executes 3 tasks asynchronously.

---

## 🧾 Overview

We’ll build:

✅ A **custom pipeline class**, `DummyProteinPipeline`, which represents one protein analysis pipeline.  
✅ A **manager**, `ImpressManager`, that orchestrates multiple pipelines.  
✅ An **execution backend** to run tasks asynchronously in threads.  
✅ A **script to start and await all pipelines asynchronously**.

You can adapt the number of pipelines (`N`) and tasks as needed.


!!! tip
For simplicity we are using `ThreadExecutionBackend`. For more computational intensive workflows, it is
recommended to use `RadicalExecutionBackend`


---

## 📄 Step 1: Import the Required Libraries

First, we import the libraries we need:

```python
import asyncio

from radical.asyncflow import ThreadExecutionBackend
from impress import ImpressBasePipeline
from impress.impress_manager import ImpressManager
```


We use:

asyncio — Python’s built-in asynchronous library.

ThreadExecutionBackend — runs tasks in parallel threads.

ImpressBasePipeline — base class for defining a pipeline.

ImpressManager — manages and executes multiple pipelines.

## 🧬 Step 2: Define a Custom Pipeline
We now define our custom DummyProteinPipeline.
This simulates a simple workflow operating on dummy protein sequences.

```python
class DummyProteinPipeline(ImpressBasePipeline):
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
            return "/bin/echo I am S1 executed at && /bin/date"

        @self.auto_register_task()
        async def s2(*args, **kwargs):
            return "/bin/echo I am S2 executed at && /bin/date"

        @self.auto_register_task()
        async def s3(*args, **kwargs):
            return "/bin/echo I am S3 executed at && /bin/date"
```

Here we define 3 tasks:

s1, s2, s3: each returns a dummy shell command that echoes its name and prints the date.

Each task is registered automatically by decorating it with @self.auto_register_task().

### 2.3 Run the Pipeline

```python
async def run_dummy_pipelines(self):
    s1_res = await self.s1()
    s2_res = await self.s2()
    print(f"[{self.name}] {s1_res}")
    print(f"[{self.name}] {s2_res}")

    s3_res = await self.s3()
    print(f"[{self.name}] {s3_res}")
```

This method controls the execution order:

Run s1, then s2, then s3 asynchronously.

Print the result of each task along with the pipeline name.

### 🧩 Step 3: Create and Run Multiple Pipelines
We now create a function that starts N pipelines at once.

```python
async def run():
    manager = ImpressManager(
        execution_backend=ThreadExecutionBackend({})
    )

    await manager.start(
        pipeline_setups=[
            {"name": "p1", "config": {}, "type": DummyProteinPipeline},
            {"name": "p2", "config": {}, "type": DummyProteinPipeline},
            {"name": "p3", "config": {}, "type": DummyProteinPipeline},
        ]
    )
```

Here:

We initialize an ImpressManager with a ThreadExecutionBackend to enable parallel task execution.

We call start() and provide a list of pipeline setups, each with a unique name (p1, p2, p3) and our DummyProteinPipeline class.

You can add more pipelines by adding more entries to the list.

### 🔗 Step 4: Run the Script
Finally, add the entry point to run everything with `asyncio`:

```python
if __name__ == "__main__":
    asyncio.run(run_dummy_pipelines())
```

This starts the event loop and runs all the pipelines concurrently.

💻 Full Code
Here is the complete script for convenience:

```python
import asyncio

from radical.asyncflow import ThreadExecutionBackend
from impress import ImpressBasePipeline
from impress.impress_manager import ImpressManager


class DummyProteinPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs={}, **kwargs):
        self.iter_seqs = {f"protein_{i}": f"sequence_{i}" for i in range(1, 4)}
        self.current_scores = {f"protein_{i}": i * 10 for i in range(1, 4)}
        self.previous_scores = {f"protein_{i}": i * 10 for i in range(1, 4)}

        super().__init__(name, flow, **configs, **kwargs)

    def register_pipeline_tasks(self):
        @self.auto_register_task()
        async def s1(*args, **kwargs):
            return "/bin/echo I am S1 executed at && /bin/date"

        @self.auto_register_task()
        async def s2(*args, **kwargs):
            return "/bin/echo I am S2 executed at && /bin/date"

        @self.auto_register_task()
        async def s3(*args, **kwargs):
            return "/bin/echo I am S3 executed at && /bin/date"

    async def run(self):
        s1_res = await self.s1()
        s2_res = await self.s2()
        print(f"[{self.name}] {s1_res}")
        print(f"[{self.name}] {s2_res}")

        s3_res = await self.s3()
        print(f"[{self.name}] {s3_res}")


async def run_dummy_pipelines():
    manager = ImpressManager(
        execution_backend=ThreadExecutionBackend({})
    )

    await manager.start(
        pipeline_setups=[
            {"name": "p1", "config": {}, "type": DummyProteinPipeline},
            {"name": "p2", "config": {}, "type": DummyProteinPipeline},
            {"name": "p3", "config": {}, "type": DummyProteinPipeline},
        ]
    )


if __name__ == "__main__":
    asyncio.run(run_dummy_pipelines())
```


📊 Example Output
When you run the script, you should see output similar to:

```shell
ThreadPool execution backend started successfully
[p2] I am S1 executed at
Mon Jul  7 09:48:16 PM UTC 2025

[p2] I am S2 executed at
Mon Jul  7 09:48:16 PM UTC 2025

[p3] I am S1 executed at
Mon Jul  7 09:48:16 PM UTC 2025

[p3] I am S2 executed at
Mon Jul  7 09:48:16 PM UTC 2025

[p1] I am S1 executed at
Mon Jul  7 09:48:16 PM UTC 2025

[p1] I am S2 executed at
Mon Jul  7 09:48:16 PM UTC 2025

[p3] I am S3 executed at
Mon Jul  7 09:48:16 PM UTC 2025

[p1] I am S3 executed at
Mon Jul  7 09:48:16 PM UTC 2025

[p2] I am S3 executed at
Mon Jul  7 09:48:16 PM UTC 2025

All pipelines finished. Exiting.
```
Each pipeline runs its three tasks in order, and all pipelines run concurrently.