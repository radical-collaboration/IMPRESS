"""
Test runner for SmallMoleculeBindingPipeline using mock tasks.

Runs the full pipeline with mock=True so no HPC tools are required.
Each task writes hardcoded placeholder output files instead of executing
real jobs, allowing the framework's orchestration and adaptive routing
to be tested end-to-end on any machine.

Usage:
    cd examples/small_molecule_binding
    python run_test_small_molecule_binding.py
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List

from radical.asyncflow import ConcurrentExecutionBackend

from impress import ImpressManager, PipelineSetup
from small_molecule_binding import SmallMoleculeBindingPipeline
from run_small_molecule_binding import adaptive_decision

BASE_PATH = os.path.dirname(os.path.abspath(__file__))


def setup_mock_inputs(pipeline_name: str) -> None:
    """Create the minimal p1_in/ directory with placeholder input files."""
    inputs_dir = os.path.join(BASE_PATH, f"{pipeline_name}_in")
    os.makedirs(inputs_dir, exist_ok=True)

    placeholders = [
        "fixed_residues.txt",
        "common_filenames.txt",
        "ALR.params",
        "ALR_binder_design.json",
    ]
    for fname in placeholders:
        fpath = os.path.join(inputs_dir, fname)
        if not os.path.exists(fpath):
            with open(fpath, "w") as fh:
                fh.write(f"# mock placeholder: {fname}\n")


def check_af2_filename_derivation() -> None:
    """Regression check for analysis_fold()'s scores.json -> unrelaxed.pdb
    filename derivation, against real ColabFold (colabfold_batch) naming."""
    cases = [
        (
            "binder_scores_rank_001_alphafold2_model_3_seed_999.json",
            "binder_unrelaxed_rank_001_alphafold2_model_3_seed_999.pdb",
        ),
        (
            "binder_scores_rank_005_alphafold2_ptm_model_1_seed_000.json",
            "binder_unrelaxed_rank_005_alphafold2_ptm_model_1_seed_000.pdb",
        ),
    ]
    for sf, expected in cases:
        derived = sf.replace('_scores_', '_unrelaxed_').replace('.json', '.pdb')
        assert derived == expected, f"{sf!r} -> {derived!r}, expected {expected!r}"


async def run_mock_test() -> None:
    pipeline_name = "p1"
    setup_mock_inputs(pipeline_name)

    backend = await ConcurrentExecutionBackend(ThreadPoolExecutor())
    manager: ImpressManager = ImpressManager(execution_backend=backend)

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name=pipeline_name,
            type=SmallMoleculeBindingPipeline,
            adaptive_fn=adaptive_decision,
            kwargs={
                "mock":               True,
                "base_path":          BASE_PATH,
                "num_refine_cycles":  3,
                "mpnn_ensemble_size": 10,
                "max_tasks":          100,
            },
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)
    await manager.flow.shutdown()


if __name__ == "__main__":
    check_af2_filename_derivation()
    asyncio.run(run_mock_test())
