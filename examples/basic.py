
from radical.flow import RadicalExecutionBackend
from src.pipelines.protein_binding import ProteinBindingPipeline

manager = ImpressManager(backend=RadicalExecutionBackend({}))

# add this as a class method
#manager.set_pipeline_type = ProteinBindingPipeline

futures = manager.start(pipeline_setup=[{'type': ProteinBindingPipeline, 'config': {}}])
