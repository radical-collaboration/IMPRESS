# Integrated Machine-learning for PRotEin Structures at Scale (IMPRESS)

IMPRESS is a high-performance computational framework to enable the inverse design of proteins using Foundation Models such as AlphaFold and ESM2.


## Documentation
📚 [IMPRESS Docs](https://radical-collaboration.github.io/IMPRESS/)


## Installation
```shell
git clone https://github.com/radical-collaboration/IMPRESS.git
cd IMPRESS
pip install .
```


## Example on HPC
```python
import asyncio
from typing import Dict, Any, Optional, List

from radical.asyncflow import await RadicalExecutionBackend

from impress import PipelineSetup
from impress import ImpressManager
from impress.pipelines.protein_binding import ProteinBindingPipeline


async def impress_protein_bind() -> None:
    """
    Execute protein binding analysis with adaptive optimization.
    
    Creates and manages multiple ProteinBindingPipeline instances with
    adaptive optimization capabilities. Each pipeline can spawn child
    pipelines based on protein quality degradation.
    """
    manager: ImpressManager = ImpressManager(
        execution_backend = await RadicalExecutionBackend(
            {'gpus':2,
             'cores': 32,
             'runtime' : 13 * 60,
             'resource': 'purdue.anvil_gpu'
             }))

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name='p1',
            type=ProteinBindingPipeline,
            adaptive_fn=adaptive_decision
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)

    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(impress_protein_bind())

```


## Resources
To learn more, please visit the project website at https://radical-project.github.io/impress/