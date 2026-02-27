import copy
import json
import os
import shutil
import asyncio
from typing import Dict, Any, Optional, List

from radical.asyncflow import RadicalExecutionBackend
from radical.asyncflow import ConcurrentExecutionBackend
from concurrent.futures import ThreadPoolExecutor

from impress import PipelineSetup
from impress import ImpressManager
from small_molecule_binding import SmallMoleculeBindingPipeline


# Score thresholds — adjust these to match the desired design quality bar
ENERGY_THRESHOLD = -10.0                # REU; ligand binding energy must be below this value
SHAPE_COMPLEMENTARITY_THRESHOLD = 0.5  # 0–1 scale; interface SC must be at or above this value
PLDDT_THRESHOLD = 70.0                 # 0–100 scale; mean per-residue pLDDT must be at or above this

# Step IDs used to route the next pipeline pass
STEP_BACKBONE_DIFFUSION = 1  # entry point: rfd3
STEP_SEQUENCE_DESIGN = 2     # entry point: mpnn (skips backbone diffusion)


async def adaptive_criteria(pipeline: SmallMoleculeBindingPipeline) -> bool:
    """
    Read Rosetta energy, shape complementarity, and AlphaFold pLDDT scores
    from the current pass output files and check them against predefined thresholds.

    Output paths are derived from pipeline.base_path and pipeline.taskcount, which
    reflect the last task that incremented the counter (af2/alphafold). The filter
    tasks write to sibling directories sharing the same count.

    Args:
        pipeline: The running pipeline instance.

    Returns:
        True if ALL three score thresholds are satisfied, False otherwise.
    """
    base = pipeline.base_path
    tc = pipeline.taskcount  # set by the af2 task; filter tasks do not advance it

    energy_file = os.path.join(base, f"{tc}_filter_energy", "out",
                               "negative_ligand_energies.txt")
    shape_file  = os.path.join(base, f"{tc}_filter_shape",  "out",
                               "shape_complementarity_values.txt")
    af_dir      = os.path.join(base, f"{tc}_alphafold", "out")

    # --- Rosetta ligand binding energy ---
    # File format (one entry per passing structure):
    #   <pdb_filename>\tLigand Energy: <float>
    energy_ok = False
    if os.path.exists(energy_file):
        with open(energy_file) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                parts = line.split('\t')
                if len(parts) >= 2:
                    try:
                        energy = float(parts[1].split(': ')[-1])
                        if energy < ENERGY_THRESHOLD:
                            energy_ok = True
                            break
                    except ValueError:
                        continue
    pipeline.logger.pipeline_log(
        f"Energy threshold ({ENERGY_THRESHOLD} REU): {'PASS' if energy_ok else 'FAIL'}"
    )

    # --- Rosetta shape complementarity ---
    # File format (one entry per structure):
    #   <pdb_filename>\tShape Complementarity: <float>
    shape_ok = False
    if os.path.exists(shape_file):
        with open(shape_file) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                parts = line.split('\t')
                if len(parts) >= 2:
                    try:
                        sc = float(parts[1].split(': ')[-1])
                        if sc >= SHAPE_COMPLEMENTARITY_THRESHOLD:
                            shape_ok = True
                            break
                    except ValueError:
                        continue
    pipeline.logger.pipeline_log(
        f"Shape complementarity threshold ({SHAPE_COMPLEMENTARITY_THRESHOLD}): "
        f"{'PASS' if shape_ok else 'FAIL'}"
    )

    # --- AlphaFold mean pLDDT ---
    # ColabFold writes per-rank JSON score files whose names contain 'scores'.
    # Each file contains a 'plddt' key with a list of per-residue confidence values.
    plddt_ok = False
    if os.path.isdir(af_dir):
        for fname in os.listdir(af_dir):
            if 'scores' in fname and fname.endswith('.json'):
                fpath = os.path.join(af_dir, fname)
                try:
                    with open(fpath) as fh:
                        data = json.load(fh)
                    plddt_arr = data.get('plddt', [])
                    if plddt_arr:
                        mean_plddt = sum(plddt_arr) / len(plddt_arr)
                        if mean_plddt >= PLDDT_THRESHOLD:
                            plddt_ok = True
                            break
                except (json.JSONDecodeError, OSError):
                    continue
    pipeline.logger.pipeline_log(
        f"AlphaFold mean pLDDT threshold ({PLDDT_THRESHOLD}): "
        f"{'PASS' if plddt_ok else 'FAIL'}"
    )

    all_met = energy_ok and shape_ok and plddt_ok
    pipeline.logger.pipeline_log(
        f"All thresholds met: {all_met} — next pass entry: "
        f"{'sequence design (mpnn)' if all_met else 'backbone diffusion (rfd3)'}"
    )
    return all_met


async def adaptive_decision(pipeline: SmallMoleculeBindingPipeline) -> Optional[Dict[str, Any]]:
    """
    Set the pipeline entry point for the next pass based on score thresholds.

    Calls adaptive_criteria() to evaluate the current pass outputs:
    - If all thresholds (energy, shape complementarity, pLDDT) are met, the next
      pass starts from the sequence design step (mpnn), skipping backbone diffusion.
    - If any threshold is not met, the next pass restarts from backbone diffusion (rfd3).

    The chosen entry point is recorded in pipeline.step_id for the run() loop to use.

    Args:
        pipeline: The running pipeline instance.

    Returns:
        None (pipeline.step_id is updated in place).
    """
    thresholds_met = await adaptive_criteria(pipeline)

    if thresholds_met:
        pipeline.logger.pipeline_log(
            "Adaptive decision: thresholds met — starting next pass from sequence design (mpnn)"
        )
        pipeline.step_id = STEP_SEQUENCE_DESIGN
    else:
        pipeline.logger.pipeline_log(
            "Adaptive decision: thresholds not met — restarting next pass from backbone diffusion (rfd3)"
        )
        pipeline.step_id = STEP_BACKBONE_DIFFUSION


async def impress_smallmol_bind() -> None:
    """
    Execute protein binding analysis with adaptive optimization.
    
    Creates and manages multiple ProteinBindingPipeline instances with
    adaptive optimization capabilities. Each pipeline can spawn child
    pipelines based on protein quality degradation.
    """
#    backend = await RadicalExecutionBackend(
#            {
##                'gpus':1,
#                'cores': 4,
#                'runtime' : 23 * 60,
#                'resource': 'local.localhost'
#                }
#            )
    backend = await ConcurrentExecutionBackend(ThreadPoolExecutor())
    
    manager: ImpressManager = ImpressManager(execution_backend=backend)

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name='p1',
            type=SmallMoleculeBindingPipeline,
            adaptive_fn=adaptive_decision
        )
    ]

    await manager.start(pipeline_setups=pipeline_setups)

    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(impress_smallmol_bind())
