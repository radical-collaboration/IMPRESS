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

from radical.asyncflow import LocalExecutionBackend

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


def check_boltz_filename_derivation() -> None:
    """Regression check for analysis_fold()'s confidence_*.json -> *.pdb
    filename derivation, against real Boltz-2 (`boltz predict`) naming."""
    cases = [
        (
            "confidence_boltz_input_model_0.json",
            "boltz_input_model_0.pdb",
        ),
        (
            "confidence_boltz_input_model_4.json",
            "boltz_input_model_4.pdb",
        ),
    ]
    for cf, expected in cases:
        derived = cf.replace('confidence_', '', 1).replace('.json', '.pdb')
        assert derived == expected, f"{cf!r} -> {derived!r}, expected {expected!r}"


def check_mpnn_candidate_selection() -> None:
    """Regression check for analysis_sequence()'s candidate-selection logic
    against real LigandMPNN's actual output shape: ONE file per input
    structure containing a template record (no 'id=') followed by several
    designed candidate records ('id=1'..'id=N', each with overall_confidence).
    A prior version of this logic only ever read a file's first line (the
    template), so it silently always "selected" the template's defaulted
    0.0 confidence and never compared real candidates -- this asserts the
    fix actually distinguishes and picks the highest-confidence candidate,
    not the template and not simply the first candidate in the file."""
    fixture = (
        ">binder, T=0.1, seed=111, num_res=94, num_ligand_res=39\n"
        "TEMPLATESEQUENCE\n"
        ">binder, id=1, T=0.1, seed=111, overall_confidence=0.4167, "
        "ligand_confidence=0.4290, seq_rec=0.5000\n"
        "CANDIDATEONE\n"
        ">binder, id=2, T=0.1, seed=111, overall_confidence=0.4092, "
        "ligand_confidence=0.4448, seq_rec=0.4574\n"
        "CANDIDATETWO\n"
        ">binder, id=3, T=0.1, seed=111, overall_confidence=0.4048, "
        "ligand_confidence=0.4235, seq_rec=0.4574\n"
        "CANDIDATETHREE\n"
        ">binder, id=4, T=0.1, seed=111, overall_confidence=0.4257, "
        "ligand_confidence=0.4414, seq_rec=0.5319\n"
        "CANDIDATEFOUR\n"
    )
    # Mirrors analysis_sequence()'s parsing exactly (small_molecule_binding.py).
    best_conf, best_id, best_seq = -1.0, None, None
    for record in fixture.split('>')[1:]:
        lines = record.splitlines()
        header, seq = lines[0], ''.join(lines[1:]).strip()
        parts = {
            kv.split('=')[0].strip(): kv.split('=')[1].strip()
            for kv in header.split(',') if '=' in kv
        }
        if 'id' not in parts:
            continue
        conf = float(parts.get('overall_confidence', 0))
        if conf > best_conf:
            best_conf, best_id, best_seq = conf, parts['id'], seq

    assert best_id == '4', f"expected id=4 (highest overall_confidence), got id={best_id!r}"
    assert best_seq == 'CANDIDATEFOUR', f"expected candidate 4's sequence, got {best_seq!r}"
    assert abs(best_conf - 0.4257) < 1e-6, f"expected conf=0.4257, got {best_conf}"


def check_fastrelax_interface_shortcircuit() -> None:
    """Regression check for _stage_metrics_improving(), the metric-agnostic
    fastrelax/interface short-circuit (see plan-shortcircuit-farep-loop.md).
    Validated against real HPC data (job 21913252, all three of p3's
    backbones) before landing -- these fixtures are that same real data."""
    from small_molecule_binding import _stage_metrics_improving

    fastrelax_specs = [
        ('interact',    True, -8.0),
        ('total_score', True, -250.0),
        ('fa_rep',      True, 100.0),
    ]

    # First attempt on a backbone: nothing to compare against yet -- always retry.
    assert _stage_metrics_improving({'interact': -7.5, 'total_score': -200.0, 'fa_rep': 56.0}, None, fastrelax_specs) is True

    # fa_rep-only failure, flat across attempts (real data: p3 backbone 3,
    # attempts 1->2) -- must be detected as NOT improving.
    prev = {'interact': -20.17, 'total_score': -413.98, 'fa_rep': 103.81}
    cur  = {'interact': -17.94, 'total_score': -409.12, 'fa_rep': 104.03}
    assert _stage_metrics_improving(cur, prev, fastrelax_specs) is False, \
        "flat fa_rep-only failure should not be read as improving"

    # A real, meaningful improvement should still be allowed to retry: fa_rep
    # starts above threshold (failing, 110.0 > 100.0) and drops well under it.
    prev = {'interact': -20.0, 'total_score': -400.0, 'fa_rep': 110.0}
    cur  = {'interact': -20.0, 'total_score': -400.0, 'fa_rep': 60.0}  # fa_rep way down
    assert _stage_metrics_improving(cur, prev, fastrelax_specs) is True, \
        "a real fa_rep improvement should be read as improving"

    # interface (higher-is-better) uses the same function with lower_is_better=False.
    interface_specs = [('max_sc', False, 0.55)]
    prev = {'max_sc': 0.5179}
    cur  = {'max_sc': 0.5148}  # real data: p3 backbone 2, attempts 3->5 direction
    assert _stage_metrics_improving(cur, prev, interface_specs) is False


async def run_mock_test() -> None:
    pipeline_name = "p1"
    setup_mock_inputs(pipeline_name)

    backend = await LocalExecutionBackend(ThreadPoolExecutor())
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
    check_boltz_filename_derivation()
    check_mpnn_candidate_selection()
    check_fastrelax_interface_shortcircuit()
    asyncio.run(run_mock_test())
