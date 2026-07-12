"""Shared telemetry mocks for tests exercising ImpressManager telemetry wiring."""

from contextlib import asynccontextmanager


class MockTelemetryManager:
    """Stands in for the object returned by `flow.start_telemetry()`."""

    def __init__(self):
        self.session_id = "test-session"
        self.subscribers = []
        self.emitted = []

    def subscribe(self, fn):
        self.subscribers.append(fn)

    def emit(self, event):
        self.emitted.append(event)

    def summary(self):
        return {"tasks": {"submitted": 0, "completed": 0}}


class MockWorkflowEngineWithTelemetry:
    """Mock workflow engine that also supports start_telemetry()/workflow_scope()."""

    def __init__(self):
        self.telemetry = None
        self.workflow_scope_calls = []

    @classmethod
    async def create(cls, backend=None):
        return cls()

    async def start_telemetry(self, **kwargs):
        self.telemetry = MockTelemetryManager()
        return self.telemetry

    @asynccontextmanager
    async def workflow_scope(self, name):
        self.workflow_scope_calls.append(name)
        yield name
