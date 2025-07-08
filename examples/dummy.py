import copy
import asyncio
import random
from typing import Dict, Any, Optional, List

from radical.asyncflow import ThreadExecutionBackend

from impress import PipelineSetup
from impress import ImpressBasePipeline
from impress.impress_manager import ImpressManager


class DummyProteinPipeline(ImpressBasePipeline):
    """
    A dummy protein pipeline for testing and demonstration purposes.
    
    Simulates protein sequence analysis with three sequential steps and maintains
    scoring data for proteins.
    """

    def __init__(self, name: str, flow: Any, configs: Dict[str, Any] = {}, **kwargs) -> None:
        """
        Initialize the DummyProteinPipeline.
        
        Args:
            name: Name identifier for the pipeline
            flow: Workflow engine instance
            configs: Configuration dictionary for the pipeline
            **kwargs: Additional keyword arguments passed to parent class
        """
        self.iter_seqs: Optional[Dict[str, str]] = None
        self.iter_seqs = {f"protein_{i}": f"sequence_{i}" for i in range(1, 4)}
        self.current_scores: Dict[str, int] = {f"protein_{i}": i * 10 for i in range(1, 4)}
        self.previous_scores: Dict[str, int] = {f"protein_{i}": i * 10 for i in range(1, 4)}

        super().__init__(name, flow, **configs, **kwargs)

    def register_pipeline_tasks(self) -> None:
        """
        Register the three sequential tasks for the protein pipeline.
        
        Creates three async tasks (s1, s2, s3) that execute shell commands
        to simulate protein analysis steps.
        """
        @self.auto_register_task()
        async def s1(*args, **kwargs) -> str:
            """Execute step 1 of protein analysis."""
            return "/bin/echo I am S1 executed at && /bin/date"

        @self.auto_register_task()
        async def s2(*args, **kwargs) -> str:
            """Execute step 2 of protein analysis."""
            return "/bin/echo I am S2 executed at && /bin/date"

        @self.auto_register_task()
        async def s3(*args, **kwargs) -> str:
            """Execute step 3 of protein analysis."""
            return "/bin/echo I am S3 executed at && /bin/date"

    async def run(self) -> None:
        """
        Execute the complete protein pipeline workflow.
        
        Runs three sequential steps (s1, s2, s3) and prints their results
        with pipeline name prefixes for identification.
        """
        s1_res: str = await self.s1()
        s2_res: str = await self.s2()

        print(f'[{self.name}] {s1_res}')
        print(f'[{self.name}] {s2_res}')

        s3_res: str = await self.s3()

        print(f'[{self.name}] {s3_res}')


async def run_dummy_pipelines() -> None:
    """
    Run multiple dummy protein pipelines concurrently.
    
    Creates and starts three DummyProteinPipeline instances (p1, p2, p3)
    using the ImpressManager for coordinated execution.
    """
    manager: ImpressManager = ImpressManager(execution_backend=ThreadExecutionBackend({}))

    pipeline_setups: List[PipelineSetup] = [PipelineSetup(name='p1', type=DummyProteinPipeline),
                                            PipelineSetup(name='p2', type=DummyProteinPipeline),
                                            PipelineSetup(name='p3', type=DummyProteinPipeline)]

    await manager.start(pipeline_setups=pipeline_setups)


if __name__ == "__main__":
    asyncio.run(run_dummy_pipelines())
