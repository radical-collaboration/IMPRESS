
from radical.flow import RadicalExecutionBackend
from src.pipelines.protein_binding import ProteinBindingPipeline

manager = ImpressManager(backend=RadicalExecutionBackend({}))

futures = manager.start(pipeline_setup=[{'type': ProteinBindingPipeline, 'config': {}}])
