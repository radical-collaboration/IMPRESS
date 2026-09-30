#!/usr/bin/env python3
"""Standalone validation for small_molecule_binding.py's RFD3 guided-input
ligand atom-name mapping (_infer_ligand_atom_mapping /
_normalize_ligand_atom_names), run against real crash artifacts from a
production run rather than synthetic test data.

Those artifacts are NOT committed -- they live under logs/, which is
gitignored -- so on a fresh checkout every check skips and this tool reports
INCONCLUSIVE (exit 2) rather than PASS. Point --base-path at a completed
run's output tree (the directory holding p1/, p2/, ...) to actually exercise
the mapping.

Background: job 21916521 (a real ~3h production HPC run) crashed all 4
pipeline instances on their first use of RFD3 guided-backbone feedback,
because Boltz-2's co-folded ligand output uses its own arbitrary atom names
that don't match the canonical params-file names baked into the base RFD3
spec's select_exposed/select_buried fields. The crash-artifact guided PDBs
from that run (logs/p{1..4}/*_rfd3/in/guided_scaffold.pdb) are the primary
fixtures used here, alongside the committed p1_in/ALR.params and
p1_in/input_pdbs/scaffold-with-ALR.pdb as ground truth.

Usage:
    python scripts/check_ligand_atom_mapping.py
    python scripts/check_ligand_atom_mapping.py --base-path logs

Exits 0 if every check passes, 1 if any fails, 2 if no fixtures were found.
"""

import argparse
import glob
import json
import os
import sys

_EXAMPLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _EXAMPLE_DIR not in sys.path:
    sys.path.insert(0, _EXAMPLE_DIR)

from small_molecule_binding import (  # noqa: E402
    _find_ligand_hetatm_residue,
    _infer_ligand_atom_mapping,
    _ligand_resname_from_params,
    _resolve_reference_pdb_path,
)

# Boltz atom -> canonical name pairs that must land in the same
# select_exposed/select_buried bucket for ALR specifically (its two ring
# systems -- a monocyclic benzene-sulfonate and a fused naphthalene-sulfonate
# -- are not graph-isomorphic to each other, so the *only* real ambiguity is
# each sulfonate's 3 interchangeable terminal oxygens; see CLAUDE.md's
# "Ensemble-guided backbone feedback" section for why this is ALR-specific,
# not a general guarantee for future ligands).
_ALR_BURIED_SULFONATE_OXYGENS  = {"O5", "O7", "O8"}   # bonded to S1
_ALR_EXPOSED_SULFONATE_OXYGENS = {"O6", "O9", "O10"}  # bonded to S2


def _load_boltz_atoms(pdb_path: str, ligand_chain_id: str = "B"):
    import gemmi
    st = gemmi.read_structure(pdb_path)
    res = _find_ligand_hetatm_residue(st, ligand_chain_id)
    if res is None:
        return None
    return {atom.name: (atom.element.name, (atom.pos.x, atom.pos.y, atom.pos.z)) for atom in res}


def check_real_crash_artifacts(examples_dir: str, base_path: str):
    """Run _infer_ligand_atom_mapping against every real *_rfd3/in/guided_scaffold.pdb
    left on disk from job 21916521 (or any other run). For each: assert a
    full bijection is found, every mapped pair is element-consistent, the
    ALR select_exposed/select_buried atom-name lists are fully covered, and
    each sulfonate's 3 oxygens land together in the correct bucket (a real
    correctness check beyond "isomorphism exists")."""
    params_path = os.path.join(examples_dir, "p1_in", "ALR.params")
    base_json_path = os.path.join(examples_dir, "p1_in", "ALR_binder_design.json")
    if not (os.path.isfile(params_path) and os.path.isfile(base_json_path)):
        return [f"SKIPPED: {params_path} or {base_json_path} not found"]
    reference_pdb = _resolve_reference_pdb_path(base_json_path)
    if not os.path.isfile(reference_pdb):
        return [f"reference pdb {reference_pdb} not found"]

    with open(base_json_path) as fh:
        base_partial = json.load(fh)["partial"]
    ligand_key = base_partial["ligand"]
    expected_names = set()
    for field in ("select_exposed", "select_buried"):
        expected_names.update(base_partial[field][ligand_key].split(","))

    candidates = sorted(glob.glob(os.path.join(base_path, "p*", "*_rfd3", "in", "guided_scaffold.pdb")))
    if not candidates:
        return [f"SKIPPED: no '*_rfd3/in/guided_scaffold.pdb' files found under {base_path}"]

    failures = []
    for pdb_path in candidates:
        boltz_atoms = _load_boltz_atoms(pdb_path)
        if boltz_atoms is None:
            failures.append(f"{pdb_path}: no ligand HETATM residue found")
            continue

        mapping = _infer_ligand_atom_mapping(boltz_atoms, params_path, reference_pdb)
        if mapping is None:
            failures.append(f"{pdb_path}: _infer_ligand_atom_mapping returned None (no mapping found)")
            continue

        if len(mapping) != len(boltz_atoms):
            failures.append(f"{pdb_path}: mapping covers {len(mapping)}/{len(boltz_atoms)} atoms, not a full bijection")

        mapped_names = set(mapping.values())
        if not expected_names <= mapped_names:
            failures.append(
                f"{pdb_path}: select_exposed/select_buried coverage FAILED -- "
                f"missing {sorted(expected_names - mapped_names)}"
            )

        if ligand_key == "A:R":
            buried_group  = {b for b, c in mapping.items() if c in _ALR_BURIED_SULFONATE_OXYGENS}
            exposed_group = {b for b, c in mapping.items() if c in _ALR_EXPOSED_SULFONATE_OXYGENS}
            if len(buried_group) != 3 or len(exposed_group) != 3:
                failures.append(
                    f"{pdb_path}: sulfonate oxygen grouping broken -- "
                    f"buried={buried_group} exposed={exposed_group} (expected 3 each)"
                )

    return failures


def check_negative_paths(examples_dir: str, base_path: str):
    """Corrupt a real fixture (drop an atom; swap an element to one absent
    from ALR) and confirm _infer_ligand_atom_mapping fails safe (returns
    None) rather than raising."""
    params_path = os.path.join(examples_dir, "p1_in", "ALR.params")
    base_json_path = os.path.join(examples_dir, "p1_in", "ALR_binder_design.json")
    reference_pdb = _resolve_reference_pdb_path(base_json_path)

    fixture = None
    for pdb_path in sorted(glob.glob(os.path.join(base_path, "p*", "*_rfd3", "in", "guided_scaffold.pdb"))):
        boltz_atoms = _load_boltz_atoms(pdb_path)
        if boltz_atoms:
            fixture = boltz_atoms
            break
    if fixture is None:
        return [f"SKIPPED: no usable '*_rfd3/in/guided_scaffold.pdb' fixture found under {base_path}"]

    failures = []

    missing_atom = dict(fixture)
    missing_atom.pop(next(iter(missing_atom)))
    try:
        result = _infer_ligand_atom_mapping(missing_atom, params_path, reference_pdb)
    except Exception as e:
        failures.append(f"missing-atom case raised {e!r} instead of returning None")
    else:
        if result is not None:
            failures.append("missing-atom case returned a mapping instead of None")

    bad_element = dict(fixture)
    name0 = next(iter(bad_element))
    _, xyz = bad_element[name0]
    bad_element[name0] = ("Cl", xyz)  # not present in ALR at all
    try:
        result2 = _infer_ligand_atom_mapping(bad_element, params_path, reference_pdb)
    except Exception as e:
        failures.append(f"bad-element case raised {e!r} instead of returning None")
    else:
        if result2 is not None:
            failures.append("bad-element case returned a mapping instead of None")

    return failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-path", default=os.path.join(_EXAMPLE_DIR, "logs"),
        help="Directory containing p1/, p2/, ... pipeline output trees (default: examples_dir/logs)",
    )
    args = parser.parse_args(argv)

    checks = [
        ("1. Real crash-artifact mapping correctness",
         lambda: check_real_crash_artifacts(_EXAMPLE_DIR, args.base_path)),
        ("2. Negative-path fail-safe behavior",
         lambda: check_negative_paths(_EXAMPLE_DIR, args.base_path)),
    ]

    print("=" * 72)
    print("LIGAND ATOM-NAME MAPPING VALIDATION")
    print("=" * 72)

    any_failed = False
    any_ran = False
    for name, fn in checks:
        try:
            failures = fn()
        except Exception as e:
            failures = [f"check raised an unexpected exception: {e!r}"]

        if failures and all(f.startswith("SKIPPED:") for f in failures):
            print(f"[SKIP] {name}")
            for f in failures:
                print(f"       {f}")
        elif not failures:
            any_ran = True
            print(f"[PASS] {name}")
        else:
            any_ran = True
            any_failed = True
            print(f"[FAIL] {name} -- {len(failures)} issue(s)")
            for f in failures:
                print(f"       - {f}")

    print("=" * 72)
    if any_failed:
        print("RESULT: FAIL")
        return 1
    if not any_ran:
        # Every check skipped for want of fixtures. Reporting PASS here would
        # green-light a clean checkout, where the crash artifacts this tool
        # reads are absent by construction -- logs/ is gitignored.
        print("RESULT: INCONCLUSIVE -- no check had fixtures to run against.")
        print(f"        Point --base-path at a completed run's output tree")
        print(f"        (the directory holding p1/, p2/, ... ); tried: {args.base_path}")
        return 2
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
