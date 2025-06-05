import asyncio

from radical.flow import WorkflowEngine
from radical.flow import ThreadExecutionBackend

from impress.impress_manager import ImpressManager
from impress.pipelines.protein_binding import ProteinBindingPipeline

async def impress_protein_bind():

    manager = ImpressManager(execution_backend=ThreadExecutionBackend({}))

    futures = await manager.start(pipeline_setups=[{'type': ProteinBindingPipeline, 'config': {}, 'name': 'p1'},
                                                   {'type': ProteinBindingPipeline, 'config': {}, 'name': 'p2'}])

asyncio.run(impress_protein_bind())
