from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from radical.asyncflow import ConcurrentExecutionBackend

from .adaptive import adaptive_decision
from .io import seed_initial_inputs
from .manager import FlowgenticImpressManager
from .pipeline import ProteinBindingFlowgenticPipeline
from .setup import PipelineSetup


async def run_impress_flowgentic(base_path: Path | None = None) -> dict[str, Any]:
    root = base_path or (Path(__file__).resolve().parents[1] / "workspace")
    root.mkdir(parents=True, exist_ok=True)

    seed_initial_inputs(
        base_path=root,
        pipeline_name="p1",
        protein_ids=["protein_a", "protein_b", "protein_c"],
        max_passes=4,
    )

    backend = await ConcurrentExecutionBackend(ThreadPoolExecutor(max_workers=8))
    manager = FlowgenticImpressManager(execution_backend=backend, base_path=root)

    setups = [
        PipelineSetup(
            name="p1",
            type=ProteinBindingFlowgenticPipeline,
            adaptive_fn=adaptive_decision,
            config={
                "base_path": str(root),
                "max_passes": 4,
                "num_seqs": 6,
                "max_sub_pipelines": 3,
                "degradation_threshold": 0.12,
            },
        )
    ]

    return await manager.start(setups)
