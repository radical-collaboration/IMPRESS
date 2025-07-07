# IMPRESS

**Integrated Machine-learning for PRotEin Structures at Scale**

IMPRESS is an async framework for managing complex protein design pipelines with adaptive decision-making capabilities. Built for high-performance computing environments.

IMPRESS is a high-performance computational framework that allows scientist to build and execute high performance asynchronous protein design pipelines effortlessly using Foundation Models such as AlphaFold and ESM2.

## Features

- 🧬 **Protein Design Pipelines**: Prebuilt and custom workflows
- 🔄 **Adaptive Execution**: Dynamic pipeline spawning
- ⚡ **HPC Optimized**: High-performance async execution
- 🎯 **Flexible Architecture**: Standard and user-defined pipelines

## Quick Example

```python
from impress import ImpressBasePipeline, ImpressManager

class MyPipeline(ImpressBasePipeline):
    def register_pipeline_tasks(self):
        @self.auto_register_task()
        async def analyze(self):
            return "echo 'Analyzing sequences'"

    async def run(self):
        await self.analyze()
        await self.invoke_adaptive_step(wait=False)

async def run_dummy_pipelines():

    manager = ImpressManager(execution_backend=ThreadExecutionBackend({}))

    await manager.start(pipeline_setups=[{'name': 'p1', 'config': {}, 
                                          'type': MyPipeline},
                                         {'name': 'p2', 'config': {}, 
                                          'type': MyPipeline},
                                         {'name': 'p3', 'config': {},
                                          'type': MyPipeline}])

asyncio.run(run_dummy_pipelines())
```




