# Integrated Machine-learning for PRotEin Structures at Scale (IMPRESS)

IMPRESS is a high-performance computational framework to enable the inverse design of proteins using foundation models such as ProteinMPNN, RFDiffusion3, and Boltz-2. It runs many asynchronous, adaptive protein-design pipelines concurrently on HPC resources through [RADICAL AsyncFlow](https://pypi.org/project/radical-asyncflow/).


## Documentation
[IMPRESS Docs](https://radical-collaboration.github.io/IMPRESS/)


## Installation
```shell
git clone https://github.com/radical-collaboration/IMPRESS.git
cd IMPRESS
pip install .
```

HPC execution backends (Dragon, RADICAL-Pilot) come from `rhapsody`, which is
installed separately:

```shell
pip install "rhapsody-py[dragon,telemetry]"
```


## Example
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

from radical.asyncflow import WorkflowEngine
from rhapsody.backends import ConcurrentExecutionBackend, DragonExecutionBackend

from impress import ImpressBasePipeline, ImpressManager, PipelineSetup


class MyPipeline(ImpressBasePipeline):
    def register_pipeline_tasks(self):
        @self.auto_register_task()
        async def design(*args, **kwargs):
            return "python3 design.py"

        @self.auto_register_task()
        async def fold(*args, **kwargs):
            return "python3 fold.py"

    async def run(self):
        await self.design()
        await self.fold()
        await self.run_adaptive_step(wait=True)


async def main() -> None:
    # The caller owns the engine: create it, hand it to the manager,
    # and shut it down when done.  Stages run on `compute`; the adaptive
    # callback runs on `local`, a thread pool, because it mutates the live
    # pipeline object.
    compute = await DragonExecutionBackend(name="compute")
    local = await ConcurrentExecutionBackend(ThreadPoolExecutor(), name="local")
    flow = await WorkflowEngine.create(backend=[compute, local])
    manager = ImpressManager(flow)

    # adaptive_fn must be a declared engine task; a bare function raises
    # TypeError in PipelineSetup.
    @flow.function_task(backend="local")
    async def adaptive_decision(pipeline: MyPipeline) -> None:
        # Inspect pipeline.state and optionally spawn a child pipeline:
        # pipeline.submit_child_pipeline_request({...})
        pass

    try:
        await manager.start(pipeline_setups=[
            PipelineSetup(name=f"p{i}", type=MyPipeline,
                          adaptive_fn=adaptive_decision)
            for i in range(1, 5)
        ])
    finally:
        await flow.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
```

Complete, runnable workflows live under [`examples/`](examples/):
[protein binding](examples/protein_binding/) (ProteinMPNN + Boltz-2),
[small molecule binding](examples/small_molecule_binding/) (RFDiffusion3 +
LigandMPNN + Rosetta + Boltz-2), and
[discontinuous scaffolds](examples/discontinuous_scaffolds/).


## Resources
To learn more, please visit the [IMPRESS documentation](https://radical-collaboration.github.io/IMPRESS/).