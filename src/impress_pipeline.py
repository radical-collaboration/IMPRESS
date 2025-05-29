class BasePipeline:
    def __init__(self, config: dict):
        self.config = config
        self.state = {}

    def decide(self):
        """Optional: override in subclass"""
        pass
