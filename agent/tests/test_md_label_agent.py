"""K6: the adapter that stopped refusing, and the three refusals it kept.

`md_label`'s body exists as of K6, so the interesting tests are no longer "does it refuse" but
*which* refusals survived and in what order, and whether the result it hands back has the shape
the gates read. None of this needs MD: `as_task_result` is a pure function of a `Measured`, which
is the reason it is a separate function rather than a block inside `run`.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")

from impress_a.md import protocol  # noqa: E402
from impress_a.tools.asteer_labels_agents import (  # noqa: E402
    LabelAdapterNotImplemented,
    MDLabelAgent,
    MissingRootInput,
)

REPO = Path(__file__).resolve().parents[1]
PARAMS = REPO / "campaigns" / "data" / "alr" / "md"
SPEC = REPO / "toolkits" / "asteer_labels" / "tools" / "md_label" / "spec.yaml"


def _spec_stub(tool_id: str = "md_label"):
    return SimpleNamespace(id=tool_id, parameters={}, metrics=[], qc_gates=[])


def _run(params, req=None):
    return asyncio.run(MDLabelAgent(spec=_spec_stub()).run(req, params))


# -- the three refusals, in the order they fire ------------------------------------------


def test_the_design_dir_is_still_checked_first_because_nothing_upstream_does():
    with pytest.raises(MissingRootInput, match="literal"):
        _run({})


def test_a_run_without_k1s_parameter_artifact_is_refused_and_told_which_path_is_not_it():
    """**The refusal that is about meaning rather than plumbing.**

    `ligand_params_path` is a Rosetta `.params`; nothing transfers from it to an MD force
    field. The artifact this needs is what records that ALR is GAFF2/AM1-BCC and not CGenFF,
    and defaulting it would let a run inherit a force field by accident.
    """
    with pytest.raises(MissingRootInput) as exc:
        _run({"design_dir": "/runs/d0", "ligand_params_path": "/runs/d0/ALR.params"})
    message = str(exc.value)
    assert "md_params_dir" in message
    assert "force field is part of what a measured number means" in message
    assert "ligand_params_path` is NOT it" in message or "NOT it" in message


def test_a_params_dir_that_is_not_a_directory_is_refused(tmp_path):
    bogus = tmp_path / "ligand_parameters.json"
    bogus.write_text("{}")
    with pytest.raises(MissingRootInput, match="is not a directory"):
        _run({"design_dir": "/runs/d0", "md_params_dir": str(bogus)})


def test_a_missing_tleap_is_refused_by_name_before_any_physics_runs(monkeypatch, tmp_path):
    """The one dependency `pip install` cannot supply, so it is worth a sentence.

    Forced rather than observed: tleap may or may not be on the machine running this test, and
    a refusal test whose outcome depends on that is a test that passes for the wrong reason.
    """
    monkeypatch.delenv("AMBERHOME", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    design = tmp_path / "d0"
    design.mkdir()
    (design / "fastrelax.pdb").write_text("ATOM\n")
    with pytest.raises(LabelAdapterNotImplemented) as exc:
        _run({"design_dir": str(design), "md_params_dir": str(PARAMS)})
    message = str(exc.value)
    assert "tleap" in message and "mock_md_label" in message
    assert "not installable from PyPI" in message


# -- what the design complex is, and which file was used --------------------------------


def test_the_complex_is_found_by_the_declared_order_and_the_name_is_reported(tmp_path):
    design = tmp_path / "d0"
    design.mkdir()
    (design / "packmin.pdb").write_text("ATOM\n")
    assert protocol.resolve_complex(str(design))[1] == "packmin.pdb"
    # fastrelax is later in the chain and more refined, so it wins when both exist.
    (design / "fastrelax.pdb").write_text("ATOM\n")
    path, name = protocol.resolve_complex(str(design))
    assert name == "fastrelax.pdb" and path.endswith("/fastrelax.pdb")


def test_a_design_dir_with_no_complex_names_every_file_it_looked_for(tmp_path):
    design = tmp_path / "d0"
    design.mkdir()
    (design / "notes.txt").write_text("")
    with pytest.raises(protocol.ProtocolFailed) as exc:
        protocol.resolve_complex(str(design))
    for name in protocol.COMPLEX_NAMES:
        assert name in str(exc.value)


def test_a_design_dir_that_is_not_a_directory_is_refused(tmp_path):
    with pytest.raises(protocol.ProtocolFailed, match="not a directory"):
        protocol.resolve_complex(str(tmp_path / "nowhere"))


def test_the_replicate_count_is_checked_against_the_specs_own_ceiling(tmp_path):
    design = tmp_path / "d0"
    design.mkdir()
    (design / "fastrelax.pdb").write_text("ATOM\n")
    with pytest.raises(protocol.ProtocolFailed, match="md_replicates=9"):
        protocol.measure(design_dir=str(design), params_dir=str(PARAMS),
                         out_dir=str(tmp_path / "out"), md_replicates=9)


def test_a_measurement_with_no_parameter_directory_is_refused_by_the_protocol_too(tmp_path):
    """Refused in both places on purpose: the agent is one caller of the protocol, not the only
    one, and the reason the artifact cannot be defaulted is a property of the measurement."""
    with pytest.raises(protocol.ProtocolFailed, match="force field is part of what"):
        protocol.measure(design_dir=str(tmp_path), params_dir="", out_dir=str(tmp_path))


# -- the result's shape, which is what the gates read ------------------------------------


def _measured():
    return protocol.Measured(
        design_dir="/runs/d0", out_dir="/work/md", complex_pdb="/runs/d0/fastrelax.pdb",
        complex_name="fastrelax.pdb", platform="CPU",
        metrics={
            "preorg_rmsd": {"name": "preorg_rmsd", "value": 0.697, "sigma": 0.043},
            "rotamer_entropy": {"name": "rotamer_entropy", "value": 0.068, "sigma": 0.020},
            "ligand_rmsf": {"name": "ligand_rmsf", "value": 0.539, "sigma": 0.041},
            "rmsd_plateau_frac": {"name": "rmsd_plateau_frac", "value": 0.108, "sigma": 0.074},
            # Measured on one log point, so it has no slope. The gate must not see it.
            "energy_drift_kcal_per_ns": {"name": "energy_drift_kcal_per_ns", "value": None,
                                         "sigma": None},
            "pocket_residues": {"name": "pocket_residues", "value": 18.0, "sigma": None},
        },
        free_energy={"metric": "dg_mmgbsa", "value": -28.96, "sigma": 3.95},
        trajectory="/work/md/holo/rep0/trajectory.dcd",
        structure="/work/md/holo/equilibrated.pdb",
    )


def test_a_metric_that_was_not_measured_is_absent_rather_than_null():
    """A `None` under a metric name is read by `metrics_reported` as present.

    That is how a gate passes on a measurement nobody made, and it is the same class of defect
    as `boltz_agents`' old `ligand_iptm` fallback: a missing number turned into a bad score.
    """
    result = protocol.as_task_result(_measured())
    assert "energy_drift_kcal_per_ns" not in result["metrics"]
    assert result["metrics"]["preorg_rmsd"] == 0.697


def test_the_pocket_size_is_provenance_and_not_a_metric():
    """18 residues says whether the label and Model B's prediction are about the same residues.

    That makes it provenance about the selection rather than a quantity of the molecule — so it
    travels with the label and not among the metrics a gate reads.
    """
    result = protocol.as_task_result(_measured())
    assert "pocket_residues" not in result["metrics"]
    assert result["provenance"]["pocket_residues"] == 18.0


def test_the_result_carries_the_artifacts_path_and_not_its_payload():
    """A task result is carried in campaign state and written into provenance lines; the full
    record is every replica's seeds, frame counts and paths."""
    result = protocol.as_task_result(_measured())
    assert isinstance(result["artifact"], str)
    assert result["artifact"].endswith(protocol.ARTIFACT_NAME)


def test_the_sigmas_travel_beside_the_values_and_not_as_metrics():
    result = protocol.as_task_result(_measured())
    assert set(result["sigmas"]) == {"preorg_rmsd", "rotamer_entropy", "ligand_rmsf",
                                     "rmsd_plateau_frac"}
    assert not any(name.startswith("sigma_") for name in result["metrics"])


def test_the_free_energy_is_reported_under_its_own_name():
    result = protocol.as_task_result(_measured())
    assert result["metrics"]["dg_mmgbsa"] == -28.96
    assert "dg_abfe" not in result["metrics"] and "dg_corrected" not in result["metrics"]


def test_a_free_energy_that_was_not_sampled_costs_the_sample_and_not_the_measurement():
    measured = _measured()
    measured.free_energy = {"metric": "dg_mmgbsa", "value": None,
                            "reason": "not sampled: the dry build failed"}
    result = protocol.as_task_result(measured)
    assert "dg_mmgbsa" not in result["metrics"]
    assert set(result["metrics"]) >= {"preorg_rmsd", "rotamer_entropy", "ligand_rmsf"}, (
        "the three labels are what this tool exists to measure; losing the second product must "
        "not lose them"
    )


def test_both_declared_ports_are_produced():
    result = protocol.as_task_result(_measured())
    assert result["outputs"]["trajectory"].endswith(".dcd")
    assert result["outputs"]["structure"].endswith("equilibrated.pdb"), (
        "the `structure` port is the equilibrated holo frame, and without it "
        "[md_label, abfe_label] does not pass gate 1"
    )


# -- the cost model ----------------------------------------------------------------------


def test_the_commitment_ceiling_is_derived_from_this_specs_own_resources():
    """Not a guess: one GPU for the declared walltime is the most one invocation can spend,
    because the scheduler kills it there. The declared 8.1 is 90% of that."""
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load(SPEC.read_text())
    ceiling = spec["resources"]["gpus"] * spec["resources"]["walltime_s"] / 3600.0
    assert spec["cost_model"]["max_commitment"]["gpu_hours"] == pytest.approx(ceiling)
    assert spec["cost_model"]["cost"]["gpu_hours"] <= ceiling


def test_the_declared_cost_is_still_the_unmeasured_one_and_the_protocol_reports_what_replaces_it():
    """**K6 did not refresh 8.1, and that is deliberate.**

    It derives from a 3.6 that was never measured; a CPU figure extrapolated to an A100 would
    be the same defect with a newer date. What the protocol emits instead is the measurement:
    `ns_per_day` and `gpu_hours_observed`, beside the platform they were observed on.
    """
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load(SPEC.read_text())
    assert spec["cost_model"]["cost"]["gpu_hours"] == 8.1
    fields = protocol.Measured().as_dict()
    for name in ("ns_per_day", "gpu_hours_observed", "wall_seconds", "platform"):
        assert name in fields


def test_the_artifact_is_written_where_the_measurement_ran(tmp_path):
    measured = _measured()
    measured.out_dir = str(tmp_path)
    path = measured.save()
    assert os.path.basename(path) == protocol.ARTIFACT_NAME
    import json

    payload = json.loads(Path(path).read_text())
    assert payload["complex_name"] == "fastrelax.pdb"
    assert payload["free_energy"]["metric"] == "dg_mmgbsa"


# -- one default, not three (the baseline determination, 2026-11-24) ---------------------


def test_the_replicate_default_is_spelled_once_and_the_spec_agrees_with_it():
    """Both specs, the code constant and the agent must say the same thing.

    They did not until 2026-11-24: `md.ensemble.DEFAULT_REPLICATES` had been 3 since K3 with
    the comment *"how many replicas a measurement uses when nothing says otherwise"*, while
    both specs declared 1 and the agent wrote `or 1` of its own. Three defaults for one
    meaning, and the smallest of them won — which is the setting under which the ensemble
    produces no σ at all.
    """
    yaml = pytest.importorskip("yaml")
    from impress_a.md.ensemble import DEFAULT_REPLICATES, MAX_REPLICATES

    assert DEFAULT_REPLICATES == 3
    for path in (SPEC, REPO / "toolkits" / "mock" / "tools" / "mock_md_label" / "spec.yaml"):
        spec = yaml.safe_load(path.read_text())
        param = spec["parameters"]["md_replicates"]
        assert param["default"] == DEFAULT_REPLICATES, (
            f"{path.name} declares {param['default']} and the code defaults to "
            f"{DEFAULT_REPLICATES}; two defaults for one meaning is how a label batch "
            "silently becomes a different experiment"
        )
        assert param["max"] == MAX_REPLICATES
    source = (REPO / "src" / "impress_a" / "tools" / "asteer_labels_agents.py").read_text()
    assert 'params.get("md_replicates") or 1' not in source, (
        "the agent must not carry a default of its own; the protocol's constant is the one"
    )


def test_the_md_campaign_asks_for_the_baseline_ensemble():
    """The campaign is where a baseline is chosen, and 3 x 5 ns is the row that was chosen.

    Same 30 ns per design as the 1 x 15 ns it replaces, so the same required sampling rate and
    the same walltime — and a σ instead of none. Asserted because a campaign that drifted back
    to one replica would produce labels `acquisition.rank` refuses to rank on, and nothing else
    would say so.
    """
    yaml = pytest.importorskip("yaml")
    from impress_a.md.ensemble import DEFAULT_REPLICATES

    for name in ("asd-labels-md.yaml", "asd-labels-md-mock.yaml"):
        spec = yaml.safe_load((REPO / "campaigns" / name).read_text())
        tool = "md_label" if "mock" not in name else "mock_md_label"
        params = spec["params"][tool]
        assert params["md_replicates"] == DEFAULT_REPLICATES, name
        if tool == "md_label":
            total = (params["apo_ns"] + params["holo_ns"]) * params["md_replicates"]
            assert total == pytest.approx(30.0), (
                f"{name} asks for {total} ns per design; the baseline is 30, which is what the "
                "single-replica default it replaced also cost"
            )


def test_the_hmr_default_is_spelled_once_too_and_is_the_measured_one():
    """**4 fs with HMR, on by default, and the default is a measurement.**

    283 s at 2 fs against 154 s at 4 fs + HMR for the same 20 ps of this system -- 1.83x -- and
    it is free for these three labels in particular, because HMR changes masses rather than the
    potential: the Boltzmann distribution is untouched and only kinetics shift, while
    `preorg_rmsd`, `ligand_rmsf` and `rotamer_entropy` are all configurational averages.
    """
    import inspect

    yaml = pytest.importorskip("yaml")
    from impress_a.md.system import DEFAULT_HMR, HMR_TIMESTEP_FS, TIMESTEP_FS

    assert DEFAULT_HMR is True
    assert (HMR_TIMESTEP_FS, TIMESTEP_FS) == (4.0, 2.0)
    for path in (SPEC, REPO / "toolkits" / "mock" / "tools" / "mock_md_label" / "spec.yaml"):
        spec = yaml.safe_load(path.read_text())
        assert spec["parameters"]["hmr"]["default"] is DEFAULT_HMR, path.name
    # `None` and not `False` from the agent, so "nothing said" is distinguishable from "2 fs was
    # asked for" -- otherwise the constant could never be reached through a campaign at all.
    source = (REPO / "src" / "impress_a" / "tools" / "asteer_labels_agents.py").read_text()
    assert 'hmr=params.get("hmr")' in source
    assert inspect.signature(protocol.measure).parameters["hmr"].default is None
