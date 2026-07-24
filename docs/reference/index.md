# API Reference

This section documents the public classes that make up the IMPRESS core
library: `impress.impress_manager`, `impress.pipelines.impress_pipeline`,
`impress.pipelines.setup`, and `impress.utils.logger`. Each page below is
generated directly from the source docstrings.

| Module | Class | Description |
|---|---|---|
| [`impress.impress_manager`](manager.md) | `ImpressManager` | Orchestrates pipeline submission, adaptive-step execution, child-pipeline spawning, and lifecycle cleanup. |
| [`impress.pipelines.impress_pipeline`](pipeline.md) | `ImpressBasePipeline` | Abstract base class for user-defined pipelines; provides the adaptive execution and child-pipeline request protocol. |
| [`impress.pipelines.setup`](setup.md) | `PipelineSetup` | Pydantic model describing a single pipeline submission (name, type, config, adaptive function). |
| [`impress.utils.logger`](logger.md) | `ImpressLogger` | Colorized console logger used internally by the manager and pipelines. |

See [Architecture](../concepts/architecture.md) for a narrative overview of
how these pieces fit together.
