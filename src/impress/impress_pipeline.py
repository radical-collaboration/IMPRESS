from abc import ABC, abstractmethod

class ImpressBasePipeline(ABC):
    def __init__(self, config: dict):
        self.state = {}
        self.config = config

    @abstractmethod
    def run(self):
        """Optional: override in subclass"""
        pass

    @abstractmethod
    def register_pipeline_tasks(self):
        """Optional: override in subclass"""
        pass
