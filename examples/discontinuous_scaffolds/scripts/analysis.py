#!/usr/bin/env python3
"""Parse chai1 scores and compute motif RMSD for a campaign analysis."""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import gemmi
import numpy as np

# Directory name pattern: {experiment}_model_{rfd3_model_idx}-{seed}
DIR_PATTERN = re.compile(
    r"^(?P<experiment>.+)_model_(?P<rfd3_model_idx>\d+)-(?P<seed>\d+)$"
)

BACKBONE_ATOMS = {"N", "CA", "C", "O"}

FIELDNAMES = [
    "run_dir",
    "experiment",
    "rfd3_model_idx",
    "seed",
    "chai1_model_idx",
    "model_name",
    "aggregate_score",
    "ptm",
    "iptm",
    "has_inter_chain_clashes",
    "chain_chain_clashes",
    "motif_rmsd",
    "anchor_residues",
    "anchor_sequences",
    "anchor_ref_residues",
]

# Path to motif JSON relative to this script
_SCRIPT_DIR = Path(__file__).parent
MOTIF_JSON_PATH = _SCRIPT_DIR / "mcsa_41_rfd3.json"

# Protein residue key format: single chain letter + residue number (e.g. A244, B1029)
_PROTEIN_RES_RE = re.compile(r"^([A-Z])(\d+)$")


def load_motif_data(json_path: Path) -> dict:
    with open(json_path) as f:
        return json.load(f)


def find_model_name(experiment: str, motif_data: dict) -> str | None:
    """Return the JSON key that is a substring of experiment, or None."""
    for key in motif_data:
        if key in experiment:
            return key
    return None


def parse_contig(contig_str: str) -> dict:
    """Parse contig and return {(chain, resnum): chai1_seq_pos} (1-indexed)."""
    mapping = {}
    pos = 1
    for token in contig_str.split(","):
        token = token.strip()
        if not token:
            continue
        if token[0].isalpha():
            chain = token[0]
            rest = token[1:]
            if "-" in rest:
                start_s, end_s = rest.split("-", 1)
                for resnum in range(int(start_s), int(end_s) + 1):
                    mapping[(chain, resnum)] = pos
                    pos += 1
            else:
                mapping[(chain, int(rest))] = pos
                pos += 1
        else:
            pos += int(token)
    return mapping


def get_pdb_atoms(pdb_path: Path) -> dict:
    """Return {(chain_id, resnum, atom_name): np.ndarray} for ATOM records only."""
    atoms = {}
    with open(pdb_path) as f:
        for line in f:
            if not line.startswith("ATOM  "):
                continue
            atom_name = line[12:16].strip()
            chain_id = line[21]
            resnum = int(line[22:26])
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            element = line[76:78].strip() if len(line) > 76 else ""
            if element == "H" or (not element and atom_name.startswith("H")):
                continue
            atoms[(chain_id, resnum, atom_name)] = np.array([x, y, z])
    return atoms


def get_cif_atoms(cif_path: Path) -> dict:
    """Return {(auth_seq_num, atom_name): np.ndarray} for polymer ATOM records."""
    atoms = {}
    st = gemmi.read_structure(str(cif_path))
    model = st[0]
    for chain in model:
        for residue in chain:
            seq_pos = residue.seqid.num
            for atom in residue:
                if atom.element == gemmi.Element("H"):
                    continue
                atoms[(seq_pos, atom.name)] = np.array(
                    [atom.pos.x, atom.pos.y, atom.pos.z]
                )
    return atoms


def kabsch_transform(ref_bb: np.ndarray, mob_bb: np.ndarray):
    """Kabsch alignment: return (R, t) such that R @ mob + t ≈ ref."""
    ref_c = ref_bb.mean(axis=0)
    mob_c = mob_bb.mean(axis=0)
    H = (mob_bb - mob_c).T @ (ref_bb - ref_c)
    U, _, Vt = np.linalg.svd(H)
    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    t = ref_c - R @ mob_c
    return R, t


def compute_motif_rmsd(
    run_dir: str,
    chai1_model_idx: int,
    experiment: str,
    motif_data: dict,
    pdb_dir: Path,
    chai1_outputs_dir: Path,
) -> tuple[float, dict] | None:
    """Return (rmsd, motif_displacements) or None on failure.

    motif_displacements maps each select_fixed_atoms protein residue key to a
    dict of {atom_name: displacement_angstroms, "refid": residue_key}.
    Only backbone atoms present in both ref and cif are included.
    """
    model_name = find_model_name(experiment, motif_data)
    if model_name is None:
        return None

    motif_info = motif_data[model_name]
    contig_map = parse_contig(motif_info["contig"])

    # Collect protein residue keys (chain, resnum) from select_fixed_atoms
    protein_res_keys = []
    for key in motif_info["select_fixed_atoms"]:
        m = _PROTEIN_RES_RE.match(key)
        if m:
            protein_res_keys.append((key, m.group(1), int(m.group(2))))

    if not protein_res_keys:
        return None

    pdb_path = pdb_dir / f"{model_name}.pdb"
    if not pdb_path.exists():
        print(f"Warning: reference PDB not found: {pdb_path}", file=sys.stderr)
        return None

    cif_path = (
        chai1_outputs_dir
        / run_dir
        / "prediction"
        / f"pred.model_idx_{chai1_model_idx}.cif"
    )
    if not cif_path.exists():
        print(f"Warning: CIF not found: {cif_path}", file=sys.stderr)
        return None

    try:
        ref_atoms = get_pdb_atoms(pdb_path)
        cif_atoms = get_cif_atoms(cif_path)
    except Exception as e:
        print(f"Warning: failed to load structures for {run_dir}: {e}", file=sys.stderr)
        return None

    ref_bb_list, mob_bb_list = [], []
    ref_all_list, mob_all_list = [], []
    # Track (res_key, atom_name) for each entry in ref_all / mob_all
    atom_labels: list[tuple[str, str]] = []

    for res_key, chain, resnum in protein_res_keys:
        chai1_pos = contig_map.get((chain, resnum))
        if chai1_pos is None:
            continue
        for (c, r, atom_name), ref_coords in ref_atoms.items():
            if c != chain or r != resnum:
                continue
            cif_key = (chai1_pos, atom_name)
            if cif_key not in cif_atoms:
                continue
            mob_coords = cif_atoms[cif_key]
            ref_all_list.append(ref_coords)
            mob_all_list.append(mob_coords)
            atom_labels.append((res_key, atom_name))
            if atom_name in BACKBONE_ATOMS:
                ref_bb_list.append(ref_coords)
                mob_bb_list.append(mob_coords)

    if len(ref_bb_list) < 3:
        print(
            f"Warning: insufficient backbone atoms for {run_dir} model_idx {chai1_model_idx}",
            file=sys.stderr,
        )
        return None

    ref_bb = np.array(ref_bb_list)
    mob_bb = np.array(mob_bb_list)
    ref_all = np.array(ref_all_list)
    mob_all = np.array(mob_all_list)

    try:
        R, t = kabsch_transform(ref_bb, mob_bb)
    except np.linalg.LinAlgError as e:
        print(f"Warning: SVD failed for {run_dir}: {e}", file=sys.stderr)
        return None

    mob_all_transformed = (R @ mob_all.T).T + t
    diff = ref_all - mob_all_transformed
    per_atom_disp = np.linalg.norm(diff, axis=1)
    rmsd = float(np.sqrt((diff ** 2).sum(axis=1).mean()))

    # Build per-residue per-atom displacement dict (backbone atoms only)
    motif_displacements: dict[str, dict] = {}
    for (res_key, atom_name), disp in zip(atom_labels, per_atom_disp):
        if atom_name not in BACKBONE_ATOMS:
            continue
        entry = motif_displacements.setdefault(res_key, {"refid": res_key})
        entry[atom_name] = float(disp)

    return rmsd, motif_displacements


def compute_anchor_info(
    displacements: dict,
    rmsd_threshold: float,
    contig_str: str,
    select_fixed_atoms: dict,
) -> tuple[list[str], list[tuple[int, int]], list[tuple[str, int, int]]]:
    """Classify motif residues as anchors and identify consecutive anchor runs.

    Returns:
        anchor_residues:  residue keys where all backbone atoms are below threshold
        anchor_sequences: list of (chai_start, chai_end) for each consecutive anchor run
        anchor_ref_ranges: list of (chain, ref_start, ref_end) for each run
    """
    contig_map = parse_contig(contig_str)

    # Build ordered list of protein motif residues sorted by contig position
    ordered: list[tuple[str, str, int]] = []  # (res_key, chain, resnum)
    for key in select_fixed_atoms:
        m = _PROTEIN_RES_RE.match(key)
        if not m:
            continue
        chain, resnum = m.group(1), int(m.group(2))
        ordered.append((key, chain, resnum))
    ordered.sort(key=lambda x: contig_map.get((x[1], x[2]), 0))

    # Classify each residue as anchor (all backbone atoms below threshold)
    anchor_set: set[str] = set()
    for res_key, chain, resnum in ordered:
        entry = displacements.get(res_key, {})
        bb_disps = [v for k, v in entry.items() if k in BACKBONE_ATOMS]
        if bb_disps and all(d < rmsd_threshold for d in bb_disps):
            anchor_set.add(res_key)

    # Find consecutive anchor runs (adjacent in ordered list, both anchors)
    anchor_sequences: list[tuple[int, int]] = []
    anchor_ref_ranges: list[tuple[str, int, int]] = []

    i = 0
    while i < len(ordered):
        res_key, chain, resnum = ordered[i]
        if res_key not in anchor_set:
            i += 1
            continue
        # Start of a potential run
        run_start = i
        j = i + 1
        while j < len(ordered) and ordered[j][0] in anchor_set:
            j += 1
        run_end = j - 1  # inclusive
        if run_end > run_start:  # run of >= 2
            first = ordered[run_start]
            last = ordered[run_end]
            chai_start = contig_map.get((first[1], first[2]))
            chai_end = contig_map.get((last[1], last[2]))
            if chai_start is not None and chai_end is not None:
                anchor_sequences.append((chai_start, chai_end))
                anchor_ref_ranges.append((first[1], first[2], last[2]))
        i = j

    return sorted(anchor_set), anchor_sequences, anchor_ref_ranges


def parse_run_dir(name: str) -> dict:
    m = DIR_PATTERN.match(name)
    if not m:
        return {"experiment": name, "rfd3_model_idx": "", "seed": ""}
    return {
        "experiment": m.group("experiment"),
        "rfd3_model_idx": int(m.group("rfd3_model_idx")),
        "seed": int(m.group("seed")),
    }


def iter_rows(chai1_outputs_dir: Path, motif_data: dict, pdb_dir: Path, rmsd_threshold: float = 1.5):
    run_dirs = sorted(chai1_outputs_dir.iterdir())
    if not run_dirs:
        print(f"No directories found in {chai1_outputs_dir}", file=sys.stderr)
        return

    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue
        meta = parse_run_dir(run_dir.name)
        experiment = meta["experiment"]
        model_name = find_model_name(experiment, motif_data) or ""
        motif_info = motif_data.get(model_name, {}) if model_name else {}

        npz_files = sorted((run_dir / "prediction").glob("scores.model_idx_*.npz"))
        for npz_path in npz_files:
            idx_match = re.search(r"scores\.model_idx_(\d+)\.npz", npz_path.name)
            chai1_model_idx = int(idx_match.group(1)) if idx_match else -1

            d = np.load(npz_path)
            clashes = int(d["chain_chain_clashes"].sum())

            result = compute_motif_rmsd(
                run_dir.name,
                chai1_model_idx,
                experiment,
                motif_data,
                pdb_dir,
                chai1_outputs_dir,
            )

            if result is None:
                motif_rmsd = ""
                displacements = {}
            else:
                motif_rmsd, displacements = result

            if displacements and motif_info:
                anchors, seq_ranges, ref_ranges = compute_anchor_info(
                    displacements,
                    rmsd_threshold,
                    motif_info["contig"],
                    motif_info["select_fixed_atoms"],
                )
            else:
                anchors, seq_ranges, ref_ranges = [], [], []

            yield {
                "run_dir": run_dir.name,
                **meta,
                "chai1_model_idx": chai1_model_idx,
                "model_name": model_name,
                "aggregate_score": float(d["aggregate_score"].item()),
                "ptm": float(d["ptm"].item()),
                "iptm": float(d["iptm"].item()),
                "has_inter_chain_clashes": bool(d["has_inter_chain_clashes"].item()),
                "chain_chain_clashes": clashes,
                "motif_rmsd": motif_rmsd,
                "anchor_residues":     ",".join(sorted(anchors)),
                "anchor_sequences":    ";".join(f"{s}-{e}" for s, e in seq_ranges),
                "anchor_ref_residues": ";".join(f"{c}{s}-{c}{e}" for c, s, e in ref_ranges),
            }


def main():
    parser = argparse.ArgumentParser(
        description="Parse chai1 scores and compute motif RMSD for campaign analysis."
    )
    parser.add_argument(
        "input_dirs",
        nargs="+",
        type=Path,
        help="Campaign directories, each expected to contain a chai1_outputs/ subdir.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./campaign_analysis.csv"),
        help="Output CSV path (default: ./campaign_analysis.csv)",
    )
    parser.add_argument(
        "--input-pdb-dir",
        type=Path,
        default=Path("../mcsa_41"),
        help="Directory containing reference PDB files (default: ../mcsa_41)",
    )
    parser.add_argument(
        "--rmsd-threshold",
        type=float,
        default=1.5,
        help="Per-atom backbone displacement threshold for anchor residue classification (default: 1.5)",
    )
    args = parser.parse_args()

    motif_data = load_motif_data(MOTIF_JSON_PATH)

    rows = []
    for input_dir in args.input_dirs:
        chai1_outputs_dir = input_dir
        dir_rows = list(iter_rows(chai1_outputs_dir, motif_data, args.input_pdb_dir, args.rmsd_threshold))
        if not dir_rows:
            print(f"Warning: no rows from {chai1_outputs_dir}", file=sys.stderr)
        rows.extend(dir_rows)

    if not rows:
        print("No data found.", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
