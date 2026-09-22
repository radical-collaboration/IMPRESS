"""Login-node validation for the real (non-mock) small_molecule_binding toolkits:
rfd3, ligandmpnn, rosetta, boltz.

Exercises registry loading, composition and the five validation gates (including
dry_run, which calls each TaskAgent's generic `parameterize()` for real) WITHOUT
executing any real RFD3/LigandMPNN/PyRosetta/Boltz binary - none of those need to be
installed for this file to pass. That is only possible because every heavy import in the
real agent modules is deferred to inside `run()` (see CLAUDE.md's tool-authoring notes
and each toolkit's SKILL.md Pitfalls).
"""
from __future__ import annotations

import pytest

from impress_a.compose.composer import Composer
from impress_a.compose.validate import SiteCaps, Validator
from impress_a.core.budget import BudgetLedger
from impress_a.core.decision import ExperimentIntent
from impress_a.tools.registry import Registry

CHAIN = ["rfd3_design", "ligandmpnn_design", "packmin", "fastrelax", "filter_shape",
         "boltz_predict"]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _v(reg, **site):
    caps = SiteCaps(**{"gpu_api": "cuda", "gpus_per_node": 4, **site})
    return Validator(reg, caps, BudgetLedger(limits={"gpu_hours": 100, "cpu_hours": 500}))


def test_real_toolkits_load_cleanly(reg):
    """rfd3/, ligandmpnn/, rosetta/, boltz/ each register with zero errors - proves the
    SKILL.md-section + spec.yaml-validation + entry-resolution path works for real tools
    without any of their science dependencies installed."""
    assert reg.errors == [], reg.errors
    assert set(reg.ids()) >= set(CHAIN)
    for toolkit in ("rfd3", "ligandmpnn", "rosetta", "boltz"):
        assert toolkit in reg.skills, f"{toolkit} toolkit did not register a SKILL.md"


def test_real_chain_passes_all_gates(reg):
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    assert len(g.nodes) == len(CHAIN)
    f = _v(reg).validate(g)
    assert f is None, f


async def test_real_chain_dry_runs_without_executing(reg):
    """Every agent's dry_run() (pre_process + parameterize only) succeeds - proves the
    graph is ready to run for real without invoking apptainer/LigandMPNN/pyrosetta/boltz."""
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    f = await _v(reg).dry_run(g)
    assert f is None, f


def test_real_chain_refuses_unproven_gpu_api(reg):
    """None of rfd3_design/ligandmpnn_design/boltz_predict declare a HIP path."""
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    f = _v(reg, gpu_api="hip").validate(g)
    assert f and f.gate == "resource" and "hip" in f.reason


def test_real_chain_refuses_over_budget(reg):
    caps = SiteCaps(gpu_api="cuda", gpus_per_node=4)
    v = Validator(reg, caps, BudgetLedger(limits={"gpu_hours": 0.001}))
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    f = v.validate(g)
    assert f and f.gate == "budget" and "gpu_hours" in str(f.detail)
