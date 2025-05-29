import typeguard

from .impress_pipeline import BasePipeline

class ImpressManager:
    def __init__(self, flow: Flow):
        self.flow = flow
        self.active_pipelines = []

    def start(self, pipeline: BasePipe, config: dict):
        self.active_pipelines.append(pipeline)
        return pipeline

    def submit_new_pipeline(self, pipeline: BasePipeline, config: dict):
        new_pipeline = pipeline.__class__(config)
        self.active_pipes.append(new_pipeline)
        return new_pipeline
