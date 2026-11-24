"""Boltz-2 task agent - independent protein+ligand co-folding confirmation.

Adapted from `IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s
`boltz()` step: extracts the sequence from the Rosetta-refined structure, writes a Boltz
YAML spec (protein sequence + ligand SMILES), and calls `boltz predict`.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
from typing import Any

import yaml

from ._ensemble import pair_by_index, select_best
from ._subprocess import child_env, input_path, run_cmd, workdir_for
from .agent import TaskAgent, TaskRequest

#: Written beside the cache once a `boltz predict` against it has completed. Presence
#: means the CCD component dictionary was fully extracted at least once.
_CACHE_COMPLETE = ".mols_complete"

_THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q", "GLU": "E",
    "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F",
    "PRO": "P", "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def _extract_sequence(pdb_path: str) -> str:
    from Bio.PDB import PDBParser

    structure = PDBParser(QUIET=True).get_structure("m", pdb_path)
    chain = next(iter(next(iter(structure))))
    return "".join(_THREE_TO_ONE.get(r.get_resname(), "X")
                    for r in chain if r.get_resname() in _THREE_TO_ONE)


def _boltz_metrics(conf: dict[str, Any]) -> dict[str, float]:
    """The metrics a Boltz confidence JSON actually reports - nothing filled in.

    `ligand_iptm` used to fall back to `iptm` and then to 0.0. With no ligand chain in
    the input, Boltz writes no `ligand_iptm` at all, and the fallback turned "the ligand
    was never modelled" into "the ligand binds badly" - a broken run reported as a weak
    design. Omitted, it is caught by the integrity gate `metrics_reported` instead.
    """
    return {k: round(conf[k], 3) for k in ("complex_plddt", "ligand_iptm") if k in conf}


def _claim_cache(cache: Path) -> int | None:
    """Blocking. Return an fd holding an exclusive lock on `cache`, or None if some
    earlier run already proved the cache complete.

    Boltz's own `download_boltz2()` guards extraction with `mols.exists()` - presence,
    not completeness - so a second lineage starting while the first is mid-extraction
    sees the directory, skips the download, and dies on `CCD component <resname> not
    found!`. We run `replicas: 4` against one shared `$BOLTZ_CACHE` and the login-node
    warm-up (`scripts/delta_env_setup.sh` step 11) is non-fatal, so an unextracted cache
    reaching a compute node is reachable, not hypothetical. Measured upstream, which
    fixes it the same way: `flock -x` across the whole check-and-repair plus a marker
    file (`scripts/boltz.sh:15-31`).

    Deliberately never deletes a partial cache, which is where this departs from
    upstream's repair. Compute nodes have no egress - that is why the warm-up runs on a
    login node at all - so removing a cache that turned out to be fine would take the
    whole campaign down with no way to refetch. Serialising until one run succeeds is
    the conservative half of the fix; `impress-a preflight` checks the marker so an
    unproven cache is caught on the login node, where it can still be repaired.
    """
    import fcntl

    cache.mkdir(parents=True, exist_ok=True)
    if (cache / _CACHE_COMPLETE).exists():
        return None
    fd = os.open(str(cache / ".mols.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        # No flock on this filesystem. Better to race than to refuse to run: the
        # failure this guards against is loud (`CCD component ... not found!`), and a
        # campaign that cannot start is worse than one that might hit it.
        os.close(fd)
        return None
    if (cache / _CACHE_COMPLETE).exists():
        # Someone completed it while we were waiting for the lock.
        os.close(fd)
        return None
    return fd


#: The chain id `boltz_input` gives the ligand, and therefore the only id an affinity
#: `binder` may name. One constant rather than two string literals in two functions: upstream
#: refuses a binder that is not a ligand chain in the same document ("Could not find binder
#: with name ... in the input!", `boltz/data/parse/schema.py:1061-1063`), so the two have to
#: agree, and until this existed they agreed only by eye.
LIGAND_CHAIN = "B"


class AffinityWithoutLigand(RuntimeError):
    """`predict_affinity` with no `ligand_smiles`.

    Refused here rather than left to `boltz predict`, which would parse a one-entity document,
    find no chain named `B`, and abort with a parse error after the task has already been
    scheduled onto a GPU. It is also the exact shape of backlog A2's silent wrong answer: an
    empty `ligand_smiles` does not fail, it models no ligand - and asking for the affinity of a
    ligand that is not in the input is that mistake made twice.
    """


def boltz_input(params: dict[str, Any], sequence: str) -> dict[str, Any]:
    """The body of `boltz_input.yaml` - where `ligand_smiles`, (half of) `use_msa_server` and
    the affinity request reach `boltz predict`, which takes them from this file rather than
    from flags."""
    # Built as data and dumped, never assembled as text. The hand-indented version
    # this replaces put `msa:` one level too deep, under the `sequence:` scalar, so
    # `boltz predict` aborted on spec parse before any model loaded.
    sequences: list[dict[str, Any]] = [{
        "protein": {
            "id": ["A"],
            "sequence": sequence,
            "msa": "auto" if params["use_msa_server"] else "empty",
        }
    }]
    if params["ligand_smiles"]:
        sequences.append({"ligand": {"id": [LIGAND_CHAIN],
                                     "smiles": params["ligand_smiles"]}})
    doc: dict[str, Any] = {"version": 1, "sequences": sequences}
    if params.get("predict_affinity"):
        if not params["ligand_smiles"]:
            raise AffinityWithoutLigand(
                "boltz_predict: predict_affinity is set but ligand_smiles is empty, so there "
                f"is no chain {LIGAND_CHAIN!r} for the affinity head to score")
        # A LIST of property blocks, one key each, and `binder` a bare string rather than the
        # one-element list the ligand's own `id` takes - upstream refuses a non-string binder
        # outright ("Binder must be a single chain.", schema.py:1056-1059). Only one affinity ligand
        # is supported per input, which costs this project nothing: there has been exactly one
        # ligand across its whole campaign history (ALR, 30 heavy atoms, identical SMILES in
        # 267/267, 112/112, 182/182 and 423/423 archived inputs). 30 is comfortably inside
        # upstream's 128-atom refusal and its 56-atom accuracy warning, both of which fire in
        # `schema.py:1217-1224` rather than silently.
        doc["properties"] = [{"affinity": {"binder": LIGAND_CHAIN}}]
    return doc


def boltz_command(params: dict[str, Any], *, input_yaml: Any, out_dir: Any,
                  cache: Any) -> list[str]:
    """THE command `boltz_predict` runs. Pure: every path is an argument.

        boltz predict <input_yaml> --out_dir ... --cache ... --diffusion_samples N ...

    `boltz` comes from PATH (the campaign's venv) and `cache` from `$BOLTZ_CACHE`; neither
    is in the spec. `input_yaml` holds `boltz_input(...)`.
    """
    cmd = [
        "boltz", "predict", str(input_yaml),
        "--out_dir", str(out_dir),
        "--cache", str(cache),
        "--devices", "1", "--accelerator", "gpu",
        "--diffusion_samples", str(params["diffusion_samples"]),
        "--output_format", "pdb",
        # Required, not optional: cuequivariance_ops_torch's fused kernel needs
        # cublasGemmGroupedBatchedEx, absent from the nvidia-cublas-cu12 version
        # torch==2.5.1+cu121 pins and loads first (present only from 12.5.3.2+), so
        # the kernel import fails every time until that's reconciled. Verified in
        # IMPRESS/examples/small_molecule_binding/scripts/boltz.sh - don't drop this
        # without re-checking the installed torch/cuequivariance-ops-cu12 versions.
        "--no_kernels",
    ]
    if params.get("seed") is not None:
        cmd += ["--seed", str(params["seed"])]
    if params["use_msa_server"]:
        cmd.append("--use_msa_server")
    # The affinity pass is requested by the INPUT DOCUMENT, not by a flag: `main.py:1336`
    # runs it when `any(r.affinity for r in manifest.records)`, which comes from
    # `properties:`. These flags only size it, so they are appended only when the document
    # asked, and an argv carrying them with no `properties:` block would be a lie about what
    # ran. `--affinity_mw_correction` is `is_flag=True` upstream, so it is present or absent
    # and never `--affinity_mw_correction false`.
    if params.get("predict_affinity"):
        cmd += ["--sampling_steps_affinity", str(params["sampling_steps_affinity"]),
                "--diffusion_samples_affinity", str(params["diffusion_samples_affinity"])]
        if params.get("affinity_mw_correction"):
            cmd.append("--affinity_mw_correction")
    return cmd


def _affinity_metrics(payload: dict[str, Any]) -> dict[str, float]:
    """The two numbers `affinity_<id>.json` reports, and nothing filled in.

    Same rule as `_boltz_metrics`: a key that is absent is omitted rather than defaulted. A
    fabricated 0.0 here would read as `log10(IC50/1uM) == 0`, i.e. a 1 micromolar binder -
    a plausible, publishable, entirely invented number. The ensemble members
    (`affinity_pred_value1/2`) are deliberately not reported: they are the two heads whose mean
    is the value above, and a corpus carrying all three invites a residual fitted against one
    head and served against the mean.
    """
    return {k: float(payload[k])
            for k in ("affinity_pred_value", "affinity_probability_binary")
            if k in payload and isinstance(payload[k], (int, float))
            and math.isfinite(float(payload[k]))}


def affinity_on_reported_sample(structure: Any) -> float:
    """1.0 if the structure being carried forward is the one the affinity head actually scored.

    **The two selections do not use the same key, and that is a defect of this adapter, not of
    Boltz.** Boltz ranks its diffusion samples by `confidence_score` and writes
    `pre_affinity_<id>.npz` - the single input to the whole affinity pass - from rank 0 only
    (`data/write/writer.py:177-180`, `idx_to_rank[model_idx] == 0`). This adapter selects what
    to carry forward by `complex_plddt`, which is a different number: `confidence_score` is a
    weighted blend of iptm and ptm, and on job 22692304's own output it was 0.556 where
    `complex_plddt` was 0.507. So with `diffusion_samples > 1` the affinity value can describe
    a *different* co-fold than the pLDDT reported beside it and the pdb handed downstream.

    Reported as a metric rather than fixed, and reported rather than ignored, because both of
    the fixes are worse at this stage: re-ranking by `confidence_score` would silently change
    which design every existing campaign carries forward, and dropping the affinity when the
    ranks disagree would throw away the measurement this episode exists to produce. A flag
    beside the value lets J14's fit take `affinity_on_reported_sample == 1` rows and lets a
    reader of the corpus see how often they disagree - which nobody can currently predict,
    because this is the first run in which the two rankings have both existed.
    """
    return 1.0 if "_model_0." in Path(structure).name else 0.0


def _qualified(affinity: dict[str, float], structure: Any) -> dict[str, float]:
    """The affinity metrics plus the flag that says which co-fold they describe, or nothing.

    Nothing when no affinity value was read, so that with `predict_affinity` unset the reported
    metric set is exactly what it was before this parameter existed - and so that the flag never
    appears without a value for it to qualify.
    """
    if not affinity:
        return {}
    return {**affinity,
            "affinity_on_reported_sample": affinity_on_reported_sample(structure)}


class BoltzPredictAgent(TaskAgent):
    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        cache = os.environ.get("BOLTZ_CACHE")
        if not cache:
            raise RuntimeError("BOLTZ_CACHE is not set - see scripts/delta_env_setup.sh")

        structure = input_path(req, "structure")
        if not structure:
            raise RuntimeError("boltz_predict: no upstream 'structure' output found")
        sequence = _extract_sequence(structure)

        work = workdir_for(req, "boltz")
        spec_path = work / "boltz_input.yaml"
        spec_path.write_text(yaml.safe_dump(boltz_input(params, sequence), sort_keys=False))
        cmd = boltz_command(params, input_yaml=spec_path, out_dir=work / "out", cache=cache)

        # Held across this whole call, not just a check: the extraction we are
        # serialising against happens *inside* `boltz predict`. Only the first run pays
        # for it - once the marker exists every later lineage takes the fast path and
        # they proceed in parallel. `to_thread` because flock blocks, and a blocked
        # event loop here would stall the executor's heartbeat exactly the way Dragon's
        # synchronous `Batch()` did (see docs/impress-a/limitations.md).
        cache_lock = await asyncio.to_thread(_claim_cache, Path(cache))
        try:
            await run_cmd(cmd, env=child_env(req),
                          timeout_s=float(self.spec.resources.walltime_s))
            if cache_lock is not None:
                (Path(cache) / _CACHE_COMPLETE).write_text(
                    "written by impress_a after a boltz predict completed against this "
                    "cache; delete to force the next run to re-prove it\n")
        finally:
            if cache_lock is not None:
                os.close(cache_lock)  # releases the flock

        # ONE PER RECORD, not one per diffusion sample. Boltz writes
        # `predictions/<id>/affinity_<id>.json` once, from the affinity pass that re-samples
        # the structure the first pass predicted (`data/write/writer.py:331`), so there is
        # nothing here to select between and nothing to pair with a pdb. Read before the
        # confidence files and merged into whichever result this call returns: the affinity
        # pass can succeed while the structure selection finds nothing to report, and a
        # measurement that exists on disk must not be dropped because a different one is
        # missing.
        affinity: dict[str, float] = {}
        for path in sorted((work / "out").glob("**/affinity_*.json")):
            try:
                affinity.update(_affinity_metrics(json.loads(path.read_text())))
            except (OSError, ValueError):
                # Unreadable or truncated. Omitted, like every other unreadable metric here;
                # `metrics_reported` is what notices a value that should have been there.
                continue

        confidence_files = sorted((work / "out").glob("**/confidence_*.json"))
        pdb_files = sorted((work / "out").glob("**/*.pdb"))
        if not confidence_files or not pdb_files:
            return {"result": None, "count": 0, "outputs": {}, "metrics": dict(affinity)}

        # The best sample, not the first. `diffusion_samples` asks Boltz for N co-folds and
        # this adapter kept `[0]`, so N were computed, N were paid for, and one was reported -
        # chosen by sort order rather than by confidence.
        scored = [(p, _boltz_metrics(json.loads(p.read_text()))) for p in confidence_files]
        choice = select_best(scored, lambda row: row[1].get("complex_plddt"))
        if choice is None:
            # Every confidence file unreadable or missing the metric. Omit rather than report
            # a zero: `metrics_reported` is the integrity gate that catches it, and a
            # fabricated 0.0 would read as a weak design instead of a broken tool.
            return {"result": "complex", "count": len(pdb_files),
                    "outputs": {"complex": pdb_files[0]},
                    "metrics": {"ensemble_size": float(len(confidence_files)),
                                "ensemble_paired": 0.0,
                                **_qualified(affinity, pdb_files[0])}}

        idx, (conf_path, metrics) = choice
        metrics = dict(metrics)
        metrics["ensemble_size"] = float(len(confidence_files))

        # Pair the chosen confidence file with its own structure by member number. Boltz writes
        # `confidence_<name>_model_<n>.json` beside `<name>_model_<n>.pdb`, so the number is
        # there - but the two globs are sorted independently, and matching by position is how
        # a confidence gets attributed to the wrong structure.
        pairs = pair_by_index(confidence_files, pdb_files)
        if pairs is not None:
            chosen_conf = conf_path
            structure = next(pdb for conf, pdb in pairs if conf == chosen_conf)
            metrics["ensemble_paired"] = 1.0
        else:
            structure = pdb_files[idx] if idx < len(pdb_files) else pdb_files[0]
            metrics["ensemble_paired"] = 1.0 if len(pdb_files) == 1 else 0.0

        metrics.update(_qualified(affinity, structure))

        return {
            "result": "complex",
            "count": len(pdb_files),
            "outputs": {"complex": structure},
            "metrics": metrics,
        }
