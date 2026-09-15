# IMPRESS

**Integrated Machine-learning for PRotEin Structures at Scale**

IMPRESS is an asynchronous framework for managing complex protein design pipelines with adaptive decision-making capabilities. It is built for deploying heterogeneous scientific worflows (mixed CPU/GPU and data sharing) in high-performance computing environments. Using a building-block approach to workflow design, IMPRESS enables high-throughput campaigns based on foundation models like AlphaFold and ESM2 or with custom models requiring runtime training and optimization.


## Features
|<!-- -->|<!-- -->|
| ----------- | ----------- |
|🧬|**Protein Design Pipelines**: Prebuilt and custom workflows|
|🔄|**Adaptive Execution**: Dynamic pipeline spawning|
|⚡|**HPC Optimized**: High-performance async execution|
|🎯| **Flexible Architecture**: Standard and user-defined pipelines|


## Quick Example
```python
from radical.asyncflow import WorkflowEngine

from impress import ImpressBasePipeline, ImpressManager
from impress.utils.session import session_work_dir

class MyPipeline(ImpressBasePipeline):
    def register_pipeline_tasks(self):
        @self.auto_register_task()
        async def analyze(self):
            return "echo 'Analyzing sequences'"

    async def run(self):
        await self.analyze()
        await self.invoke_adaptive_step(wait=False)

async def run_dummy_pipelines():

    backend = ThreadExecutionBackend({})
    flow = await WorkflowEngine.create(backend=backend, work_dir=session_work_dir())
    manager = ImpressManager(flow)

    try:
        await manager.start(pipeline_setups=[{'name': 'p1', 'config': {},
                                              'type': MyPipeline},
                                             {'name': 'p2', 'config': {},
                                              'type': MyPipeline},
                                             {'name': 'p3', 'config': {},
                                              'type': MyPipeline}])
    finally:
        await flow.shutdown()

asyncio.run(run_dummy_pipelines())
```


