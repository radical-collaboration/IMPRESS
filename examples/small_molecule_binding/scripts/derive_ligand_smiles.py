"""One-time SMILES derivation for a Rosetta-params-defined ligand.

Rosetta `.params` files give exact atom identity and bond *connectivity*
(which atoms are bonded to which) but no bond order and no explicit
hydrogens beyond whatever is literally listed as an ATOM record. To hand a
ligand to Boltz-2 (which wants a SMILES string) we need real bond orders,
aromaticity, and formal charges -- RDKit's `rdDetermineBonds.DetermineBondOrders`
is built exactly for this: given known connectivity plus a 3D conformer, it
solves for a chemically sensible Lewis structure.

This is a one-time, offline tool -- not part of the per-cycle pipeline.

Usage:
    derive_ligand_smiles.py <lig>.params <reference>.pdb [--charge N] [--out PATH]

Implementation note (found empirically against ALR.params + scaffold-with-ALR.pdb,
a fused-bicyclic (naphthalene) + monocyclic aromatic azo-linked bis-sulfonate):
DetermineBondOrders on a *heavy-atom-only* skeleton (no explicit hydrogens at
all, relying on RDKit's implicit-H valence fill) reliably failed or returned
chemically nonsensical structures (cumulated double/triple bonds, absurd
formal charges) across a wide charge sweep -- for both the full molecule and
the fused-ring "core" with the sulfonate groups excluded. Adding placeholder
explicit hydrogens (approximate, not chemically precise, positions -- one per
params BOND record referencing an atom absent from the reference PDB) gave
DetermineBondOrders a fully-specified valence at every atom and immediately
produced the correct aromatic, charge-balanced structure. This script
therefore reconstructs those hydrogens with approximate 3D placeholder
coordinates (never claimed to be chemically accurate bond geometry -- just
distinct, non-degenerate positions) rather than dropping them outright.
"""

import argparse
import pathlib
import re

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdDetermineBonds
from rdkit.Geometry import Point3D


# Fallback table keyed on Rosetta atom TYPE prefix, used only when the atom
# NAME's leading alphabetic run doesn't parse to a valid element symbol.
# Verified only against ALR's atom set (C/N/O/S/H). NOT verified for 2-letter
# elements (Cl/Br/Zn, etc.) -- extend this table if IND/RED (or any future
# ligand) ever need it. Nothing ALR-specific is hardcoded into the matching
# logic itself, only into the table's contents.
_ROSETTA_TYPE_ELEMENT_FALLBACK = {
    "Nhis": "N", "Nlys": "N",
    "CH1": "C", "CH2": "C", "CH3": "C", "COO": "C", "aroC": "C",
    "OH": "O", "OOC": "O", "ONH2": "O",
    "Hapo": "H", "Hpol": "H",
    "S": "S", "SH1": "S",
}

_PERIODIC_TABLE = Chem.GetPeriodicTable()


def _parse_params(params_path):
    """Parse a Rosetta .params file.

    Returns (resname, {atom_name: rosetta_type}, [(atom1, atom2), ...]) from
    the file's NAME, ATOM, and BOND records. Includes hydrogens (both in the
    atom-type map and the bond list) -- callers that want a heavy-atom-only
    view filter separately.
    """
    resname = None
    atom_types = {}
    bonds = []

    with open(params_path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            fields = line.split()
            record = fields[0]

            if record == "NAME":
                resname = fields[1]
            elif record == "ATOM":
                # ATOM <name> <rosetta_type> <mm_type> <partial_charge>
                atom_name, rosetta_type = fields[1], fields[2]
                atom_types[atom_name] = rosetta_type
            elif record == "BOND" or record == "BOND_TYPE":
                # BOND <atom1> <atom2> [bond order, for BOND_TYPE]
                a1, a2 = fields[1], fields[2]
                bonds.append((a1, a2))

    if resname is None:
        raise ValueError(f"{params_path}: no NAME record found")
    if not atom_types:
        raise ValueError(f"{params_path}: no ATOM records found")

    return resname, atom_types, bonds


def _infer_element(atom_name, rosetta_type):
    """Infer the element symbol for a params ATOM entry.

    Primary rule: the leading alphabetic run of the atom NAME field is
    literally the PDB-style element-derived atom name (e.g. "N11" -> "N",
    "C13" -> "C", "S1" -> "S"). If that run isn't a valid element symbol
    (e.g. it's empty, or the atom-naming convention doesn't follow this
    pattern), fall back to a table keyed on the Rosetta atom TYPE prefix.

    Verified only for ALR's C/N/O/S/H atom set. NOT verified for 2-letter
    elements (Cl/Br/Zn, ...) -- IND/RED ligands exist in this repo but have
    no reference PDB, so they're out of scope until one is added; extending
    this function for them should not require touching ALR's behavior.
    """
    match = re.match(r"[A-Za-z]+", atom_name)
    if match:
        candidate = match.group(0)
        # Try progressively shorter prefixes (handles e.g. "Cl1" correctly
        # while still falling back cleanly for made-up multi-letter runs).
        for length in (2, 1):
            if len(candidate) >= length:
                symbol = candidate[:length].capitalize()
                if _PERIODIC_TABLE.GetAtomicNumber(symbol) > 0:
                    return symbol

    # Name-based inference failed -- fall back to the Rosetta TYPE prefix table.
    for prefix, element in _ROSETTA_TYPE_ELEMENT_FALLBACK.items():
        if rosetta_type.startswith(prefix):
            return element

    raise ValueError(
        f"could not infer element for atom name={atom_name!r} type={rosetta_type!r}"
    )


def _load_reference_coords(pdb_path, resname):
    """Read {atom_name: (x, y, z)} from the first HETATM residue in pdb_path
    whose residue name matches `resname`.

    PDB fixed-column parsing is used for the residue-name field (columns
    18-20) since names like "A:R" contain a colon that a naive whitespace
    split would otherwise mangle.
    """
    coords = {}
    found_residue = False
    target_resseq = None

    with open(pdb_path) as fh:
        for line in fh:
            if not (line.startswith("HETATM") or line.startswith("ATOM  ")):
                continue

            line_resname = line[17:20].strip()
            if line_resname != resname:
                if found_residue:
                    # We've moved past the matching residue's contiguous block.
                    break
                continue

            resseq = line[22:26].strip()
            if target_resseq is None:
                target_resseq = resseq
            elif resseq != target_resseq:
                # A different residue instance with the same name -- stop at
                # the first one, per the docstring contract.
                break

            found_residue = True
            atom_name = line[12:16].strip()
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            coords[atom_name] = (x, y, z)

    if not coords:
        raise ValueError(f"{pdb_path}: no HETATM residue named {resname!r} found")

    return coords


def _placeholder_h_coords(h_names, atom_names_by_parent, ref_coords, bonds):
    """Approximate (not chemically precise) 3D positions for hydrogens absent
    from the reference PDB, so DetermineBondOrders sees a fully-specified
    valence at every heavy atom instead of guessing implicit H counts.

    Each H is placed near its (single) bonded heavy-atom parent, offset in a
    direction generally pointing away from that parent's other heavy
    neighbors -- distinct per-H when several hydrogens share one parent
    (e.g. a methyl group) by fanning out around an arbitrary perpendicular
    axis. Precise bond lengths/angles are not the goal (empirically,
    DetermineBondOrders's bond-order search doesn't depend on them once
    connectivity is fixed) -- only non-degenerate, distinguishable positions.
    """
    # parent heavy atom for each H (H atoms have exactly one bond in a
    # correctly-formed params file)
    parent_of = {}
    for a, b in bonds:
        if a in h_names and b in ref_coords:
            parent_of[a] = b
        elif b in h_names and a in ref_coords:
            parent_of[b] = a

    h_coords = {}
    for parent, h_list in atom_names_by_parent.items():
        parent_pos = np.array(ref_coords[parent], dtype=float)

        other_heavy_neighbors = [
            ref_coords[nb] for a, b in bonds
            for nb in ((b,) if a == parent else (a,) if b == parent else ())
            if nb in ref_coords and nb != parent
        ]
        if other_heavy_neighbors:
            centroid = np.mean(np.array(other_heavy_neighbors, dtype=float), axis=0)
            base_dir = parent_pos - centroid
        else:
            base_dir = np.array([1.0, 0.0, 0.0])
        norm = np.linalg.norm(base_dir)
        base_dir = base_dir / norm if norm > 1e-6 else np.array([1.0, 0.0, 0.0])

        # arbitrary axis perpendicular to base_dir, for fanning out multiple H's
        arbitrary = np.array([0.0, 0.0, 1.0]) if abs(base_dir[2]) < 0.9 else np.array([0.0, 1.0, 0.0])
        perp_axis = np.cross(base_dir, arbitrary)
        perp_axis /= np.linalg.norm(perp_axis)

        n_h = len(h_list)
        for i, h_name in enumerate(h_list):
            angle = np.radians((360.0 / n_h) * i) if n_h > 1 else 0.0
            # Rodrigues' rotation of base_dir around perp_axis by `angle`
            rotated = (
                base_dir * np.cos(angle)
                + np.cross(perp_axis, base_dir) * np.sin(angle)
                + perp_axis * np.dot(perp_axis, base_dir) * (1 - np.cos(angle))
            )
            pos = parent_pos + rotated * 1.0  # arbitrary ~1 Angstrom offset
            h_coords[h_name] = tuple(pos)

    return h_coords


def derive_smiles(params_path, reference_pdb_path, net_charge=0):
    """Derive a SMILES string for the ligand described by params_path,
    using 3D coordinates from reference_pdb_path (heavy atoms) plus
    reconstructed placeholder coordinates for hydrogens absent from that PDB
    to resolve bond orders.

    Atoms: every params heavy atom found in the reference PDB, plus every
    params hydrogen bonded to one of those heavy atoms (given a placeholder
    position -- see _placeholder_h_coords). Params ATOM/BOND entries for
    atoms that are neither in the PDB nor a hydrogen bonded to a kept heavy
    atom are dropped.

    Bonds are wired as single bonds initially; rdDetermineBonds.DetermineBondOrders
    then infers real bond order/aromaticity/formal charges from connectivity
    and valence. The hydrogens are stripped from the final returned molecule
    (Chem.RemoveHs) so the SMILES reflects only the ligand's heavy-atom
    skeleton, same as a normal canonical SMILES.

    net_charge defaults to 0 because ALR.params's per-atom partial charges
    happen to sum to roughly zero -- this is a convenient heuristic, not a
    rigorous formal-charge derivation. If charge=0 fails, +1/-1 are tried
    next; if those also fail, the search widens further (+/-2, +/-3, +/-4)
    since a real bis-sulfonic-acid ligand is, in practice, virtually always
    doubly deprotonated (net charge -2) at neutral pH -- found empirically
    for ALR, not assumed a priori.
    """
    resname, atom_types, bond_pairs = _parse_params(params_path)
    ref_coords = _load_reference_coords(reference_pdb_path, resname)

    heavy_names = [name for name in atom_types if name in ref_coords]
    if not heavy_names:
        raise ValueError(
            f"no overlap between params atoms and reference PDB atoms for {resname!r}"
        )
    heavy_set = set(heavy_names)

    # Hydrogens (or any other atom not in the PDB) bonded to a kept heavy atom.
    h_names = [
        name for name in atom_types
        if name not in heavy_set
        and any(name in pair and (pair[0] in heavy_set or pair[1] in heavy_set) for pair in bond_pairs)
    ]
    h_set = set(h_names)

    kept_names = heavy_names + h_names
    kept_set = set(kept_names)
    kept_bonds = [
        (a1, a2) for (a1, a2) in bond_pairs
        if a1 in kept_set and a2 in kept_set
    ]

    # Group H names by their heavy-atom parent, for placeholder placement.
    atom_names_by_parent = {}
    for a, b in kept_bonds:
        if a in h_set and b in heavy_set:
            atom_names_by_parent.setdefault(b, []).append(a)
        elif b in h_set and a in heavy_set:
            atom_names_by_parent.setdefault(a, []).append(b)

    h_coords = _placeholder_h_coords(h_set, atom_names_by_parent, ref_coords, kept_bonds)
    all_coords = {**ref_coords, **h_coords}

    # Build the RWMol: atoms first (recording an index map), then bonds.
    mol = Chem.RWMol()
    name_to_idx = {}
    for name in kept_names:
        element = _infer_element(name, atom_types[name])
        atom = Chem.Atom(element)
        idx = mol.AddAtom(atom)
        name_to_idx[name] = idx

    for a1, a2 in kept_bonds:
        i, j = name_to_idx[a1], name_to_idx[a2]
        if mol.GetBondBetweenAtoms(i, j) is None:
            mol.AddBond(i, j, Chem.BondType.SINGLE)

    # Attach the 3D conformer (real PDB coords for heavy atoms, placeholder
    # coords for reconstructed hydrogens).
    conformer = Chem.Conformer(mol.GetNumAtoms())
    for name, idx in name_to_idx.items():
        x, y, z = all_coords[name]
        conformer.SetAtomPosition(idx, Point3D(x, y, z))
    mol.AddConformer(conformer, assignId=True)

    # Sanitize NONE first -- DetermineBondOrders operates on the raw graph
    # and will itself figure out valence/order/aromaticity/charges.
    Chem.SanitizeMol(mol, sanitizeOps=Chem.SanitizeFlags.SANITIZE_NONE)

    charge_ladder = [net_charge, net_charge + 1, net_charge - 1,
                      net_charge + 2, net_charge - 2,
                      net_charge + 3, net_charge - 3,
                      net_charge + 4, net_charge - 4]
    last_error = None
    for charge in charge_ladder:
        trial_mol = Chem.RWMol(mol)
        try:
            rdDetermineBonds.DetermineBondOrders(trial_mol, charge=charge)
            Chem.SanitizeMol(trial_mol)
        except Exception as exc:  # noqa: BLE001 -- want to try every charge in the ladder
            last_error = exc
            continue
        heavy_only = Chem.RemoveHs(trial_mol)
        return Chem.MolToSmiles(heavy_only)

    raise RuntimeError(
        f"DetermineBondOrders failed across charge ladder {charge_ladder}; "
        f"last error: {last_error}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Derive a SMILES string for a Rosetta-params ligand from its "
                    "params connectivity + a reference PDB's 3D coordinates."
    )
    parser.add_argument("params_path", help="Rosetta .params file (e.g. ALR.params)")
    parser.add_argument("reference_pdb_path", help="Reference PDB containing the ligand's HETATM block")
    parser.add_argument("--charge", type=int, default=0, help="Net formal charge to try first (default 0)")
    parser.add_argument("--out", default=None, help="Output .smiles path (default: <params_dir>/<params_stem>.smiles)")
    args = parser.parse_args()

    params_path = pathlib.Path(args.params_path)
    out_path = pathlib.Path(args.out) if args.out else params_path.with_suffix(".smiles")

    smiles = derive_smiles(str(params_path), args.reference_pdb_path, net_charge=args.charge)

    # Round-trip through Chem.MolFromSmiles() before writing -- abort if it
    # doesn't parse back to a valid molecule.
    round_trip_mol = Chem.MolFromSmiles(smiles)
    if round_trip_mol is None:
        raise RuntimeError(
            f"derived SMILES failed to round-trip through Chem.MolFromSmiles(): {smiles!r}"
        )

    out_path.write_text(smiles + "\n")
    print(smiles)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
