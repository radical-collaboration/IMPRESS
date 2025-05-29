class ImpressBasePipeline:
    def __init__(self, config: dict):
        self.state = {}
        self.config = config

    @abstractmethod
    def decide(self):
        """Optional: override in subclass"""
        pass

    @abstractmethod
    def submit_next(self):
        """Optional: override in subclass"""
        pass
