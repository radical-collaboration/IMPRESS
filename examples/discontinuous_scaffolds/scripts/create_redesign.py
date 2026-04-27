#!/usr/bin/env python3
"""Build redesign_scaffold.cif and redesign.json for failing fold models.

For each failing model in best_fold.json:
  1. Identify anchor sequences (well-predicted chai regions) from stored anchor info.
  2. Kabsch-align the anchor sequence atoms from the best Chai-1 CIF into the
     reference coordinate frame.
  3. Combine aligned anchor residues with non-anchor reference residues (renumbered
     starting at 900) into redesign_scaffold.cif.
  4. Rewrite the RFD3 design config (contig + select_fixed_atoms) to match the
     new numbering scheme and write redesign.json.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import gemmi
import numpy as np

# ── Shared constants / helpers (mirrors analysis.py) ──────────────────────────

BACKBONE_ATOMS = {"N", "CA", "C", "O"}
_PROTEIN_RES_RE = re.compile(r"^([A-Z])(\d+)$")

NON_ANCHOR_START = 900  # renumber non-anchor reference residues starting here


def _parse_contig(contig_str: str) -> dict:
    """Return {(chain, resnum): chai1_seq_pos} (1-indexed)."""
    mapping: dict[tuple[str, int], int] = {}
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


def _parse_anchor_sequences(anchor_seq_str: str) -> list[tuple[int, int]]:
    """Parse '50-76;100-123' into [(50,76),(100,123)]."""
    if not anchor_seq_str:
        return []
    result = []
    for span in anchor_seq_str.split(";"):
        span = span.strip()
        if not span:
            continue
        parts = span.split("-")
        result.append((int(parts[0]), int(parts[1])))
    return result


def _parse_anchor_ref_residues(anchor_ref_str: str) -> list[tuple[str, int, int]]:
    """Parse 'A64-A90;B10-B20' into [('A',64,90),('B',10,20)]."""
    if not anchor_ref_str:
        return []
    result = []
    for span in anchor_ref_str.split(";"):
        span = span.strip()
        if not span:
            continue
        # Format: ChainStart-ChainEnd e.g. A64-A90
        # Split on '-' but the second part starts with a letter
        m = re.match(r"^([A-Z])(\d+)-[A-Z](\d+)$", span)
        if m:
            result.append((m.group(1), int(m.group(2)), int(m.group(3))))
    return result


def _kabsch_transform(ref_bb: np.ndarray, mob_bb: np.ndarray):
    """Return (R, t) s.t. R @ mob + t ≈ ref."""
    ref_c = ref_bb.mean(axis=0)
    mob_c = mob_bb.mean(axis=0)
    H = (mob_bb - mob_c).T @ (ref_bb - ref_c)
    U, _, Vt = np.linalg.svd(H)
    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    t = ref_c - R @ mob_c
    return R, t


def _get_ref_backbone_atoms(ref_st: gemmi.Structure, protein_res_keys: list, contig_map: dict):
    """Extract backbone atom coordinates for motif residues from a gemmi Structure.

    Returns list of (chain, resnum, atom_name, coords) for backbone atoms only.
    """
    atoms = []
    model = ref_st[0]
    for chain in model:
        for residue in chain:
            seqnum = residue.seqid.num
            for res_key, ch, rn in protein_res_keys:
                if ch == chain.name and rn == seqnum:
                    for atom in residue:
                        if atom.name in BACKBONE_ATOMS and atom.element != gemmi.Element("H"):
                            atoms.append((ch, rn, atom.name,
                                          np.array([atom.pos.x, atom.pos.y, atom.pos.z])))
    return atoms


def _get_cif_backbone_atoms(cif_st: gemmi.Structure, protein_res_keys: list, contig_map: dict):
    """Extract backbone atom coordinates for motif residues from a chai CIF gemmi Structure.

    Maps reference (chain, resnum) → chai seq pos via contig_map.
    Returns list of (res_key, atom_name, coords).
    """
    # Build {seqid_num: atom_name → coords} from cif
    cif_atoms: dict[tuple[int, str], np.ndarray] = {}
    model = cif_st[0]
    for chain in model:
        for residue in chain:
            seq_pos = residue.seqid.num
            for atom in residue:
                if atom.element != gemmi.Element("H"):
                    cif_atoms[(seq_pos, atom.name)] = np.array(
                        [atom.pos.x, atom.pos.y, atom.pos.z]
                    )

    result = []
    for res_key, chain_id, resnum in protein_res_keys:
        chai_pos = contig_map.get((chain_id, resnum))
        if chai_pos is None:
            continue
        for atom_name in BACKBONE_ATOMS:
            key = (chai_pos, atom_name)
            if key in cif_atoms:
                result.append((res_key, atom_name, cif_atoms[key]))
    return result


def _compute_kabsch_from_model(
    ref_st: gemmi.Structure,
    cif_st: gemmi.Structure,
    protein_res_keys: list,
    contig_map: dict,
):
    """Compute Kabsch (R, t) aligning chai backbone to reference backbone."""
    ref_data = _get_ref_backbone_atoms(ref_st, protein_res_keys, contig_map)
    cif_data = _get_cif_backbone_atoms(cif_st, protein_res_keys, contig_map)

    # Build correspondence: (res_key, atom_name) → (ref_coords, cif_coords)
    ref_lookup = {(ch, rn, an): coords for ch, rn, an, coords in ref_data}
    cif_lookup = {}
    for res_key, an, coords in cif_data:
        m = _PROTEIN_RES_RE.match(res_key)
        if m:
            cif_lookup[(m.group(1), int(m.group(2)), an)] = coords

    ref_bb, mob_bb = [], []
    for k, ref_c in ref_lookup.items():
        if k in cif_lookup:
            ref_bb.append(ref_c)
            mob_bb.append(cif_lookup[k])

    if len(ref_bb) < 3:
        raise ValueError(f"Too few backbone atom pairs for Kabsch ({len(ref_bb)})")

    return _kabsch_transform(np.array(ref_bb), np.array(mob_bb))


# ── Structure building ─────────────────────────────────────────────────────────

def _extract_anchor_chain(cif_st: gemmi.Structure, anchor_spans: list[tuple[int, int]], R, t) -> list:
    """Return list of (seqid_num, residue_name, list_of_(atom_name, transformed_coords))
    for all residues in the anchor chai position spans, with Kabsch transform applied.
    """
    span_set: set[int] = set()
    for start, end in anchor_spans:
        span_set.update(range(start, end + 1))

    result = []
    model = cif_st[0]
    for chain in model:
        for residue in chain:
            seqnum = residue.seqid.num
            if seqnum not in span_set:
                continue
            atoms_out = []
            for atom in residue:
                if atom.element == gemmi.Element("H"):
                    continue
                pos = np.array([atom.pos.x, atom.pos.y, atom.pos.z])
                pos_t = R @ pos + t
                atoms_out.append((atom.name, pos_t, atom.element))
            result.append((seqnum, residue.name, atoms_out))
    result.sort(key=lambda x: x[0])
    return result


def _extract_non_anchor_ref(
    ref_st: gemmi.Structure,
    anchor_ref_ranges: list[tuple[str, int, int]],
    protein_only: bool = True,
) -> tuple[list, list]:
    """Return (protein_residues, ligand_residues) from reference excluding anchor ranges.

    protein_residues: list of (chain_id, seqnum, res_name, list_of_(atom_name, coords, element))
    ligand_residues: same format, for HETATM-equivalent records (non-standard residues / het groups)
    """
    # Build set of (chain, resnum) to exclude
    exclude: set[tuple[str, int]] = set()
    for chain_id, ref_start, ref_end in anchor_ref_ranges:
        for rn in range(ref_start, ref_end + 1):
            exclude.add((chain_id, rn))

    protein_residues = []
    ligand_residues = []
    model = ref_st[0]
    for chain in model:
        for residue in chain:
            seqnum = residue.seqid.num
            if (chain.name, seqnum) in exclude:
                continue
            atoms_out = []
            for atom in residue:
                if atom.element == gemmi.Element("H"):
                    continue
                pos = np.array([atom.pos.x, atom.pos.y, atom.pos.z])
                atoms_out.append((atom.name, pos, atom.element))
            # Treat as ligand if residue is a hetero group (non-polymer)
            is_het = residue.entity_type == gemmi.EntityType.NonPolymer or \
                     residue.entity_type == gemmi.EntityType.Unknown
            if is_het:
                ligand_residues.append((chain.name, seqnum, residue.name, atoms_out))
            else:
                protein_residues.append((chain.name, seqnum, residue.name, atoms_out))

    return protein_residues, ligand_residues


def _build_redesign_structure(
    anchor_residues_data: list,
    non_anchor_protein: list,
    ligand_residues: list,
) -> gemmi.Structure:
    """Combine anchor residues (from chai, aligned) + non-anchor reference residues into one Structure."""
    st = gemmi.Structure()
    st.name = "redesign"
    model = gemmi.Model("1")

    chain_a = gemmi.Chain("A")

    # Anchor residues: use their chai seqid numbers as-is
    for seqnum, res_name, atoms_out in anchor_residues_data:
        res = gemmi.Residue()
        res.name = res_name
        res.seqid = gemmi.SeqId(seqnum, " ")
        res.entity_type = gemmi.EntityType.Polymer
        for atom_name, pos, element in atoms_out:
            atom = gemmi.Atom()
            atom.name = atom_name
            atom.pos = gemmi.Position(pos[0], pos[1], pos[2])
            atom.element = element
            atom.occ = 1.0
            atom.b_iso = 0.0
            res.add_atom(atom)
        chain_a.add_residue(res)

    # Non-anchor reference residues: renumbered starting at NON_ANCHOR_START
    for i, (orig_chain, orig_seqnum, res_name, atoms_out) in enumerate(non_anchor_protein):
        new_seqnum = NON_ANCHOR_START + i
        res = gemmi.Residue()
        res.name = res_name
        res.seqid = gemmi.SeqId(new_seqnum, " ")
        res.entity_type = gemmi.EntityType.Polymer
        for atom_name, pos, element in atoms_out:
            atom = gemmi.Atom()
            atom.name = atom_name
            atom.pos = gemmi.Position(pos[0], pos[1], pos[2])
            atom.element = element
            atom.occ = 1.0
            atom.b_iso = 0.0
            res.add_atom(atom)
        chain_a.add_residue(res)

    model.add_chain(chain_a)

    # Ligand residues: one chain per ligand molecule (gemmi convention)
    for lig_chain_id, seqnum, res_name, atoms_out in ligand_residues:
        lig_chain = gemmi.Chain(lig_chain_id)
        res = gemmi.Residue()
        res.name = res_name
        res.seqid = gemmi.SeqId(seqnum, " ")
        res.entity_type = gemmi.EntityType.NonPolymer
        for atom_name, pos, element in atoms_out:
            atom = gemmi.Atom()
            atom.name = atom_name
            atom.pos = gemmi.Position(pos[0], pos[1], pos[2])
            atom.element = element
            atom.occ = 1.0
            atom.b_iso = 0.0
            res.add_atom(atom)
        lig_chain.add_residue(res)
        model.add_chain(lig_chain)

    st.add_model(model)
    return st


# ── Contig + select_fixed_atoms rewriting ─────────────────────────────────────

def _rebuild_contig_and_sfa(
    original_contig: str,
    original_sfa: dict,
    anchor_set: set[str],
    contig_map: dict,
    anchor_sequences: list[tuple[int, int]],
) -> tuple[str, dict]:
    """Rewrite contig string and select_fixed_atoms for the redesign scaffold.

    Anchor motif residues are replaced by their chai position range (e.g. 'A50-76').
    Non-anchor protein residues are renumbered A900, A901, ...
    Ligand entries in select_fixed_atoms are kept unchanged.
    """
    tokens = [t.strip() for t in original_contig.split(",") if t.strip()]

    # Classify each token
    # tag: 'gap', 'anchor', 'non_anchor'  (for residue tokens)
    tagged: list[tuple[str, str]] = []  # (tag, original_token)
    for tok in tokens:
        if tok[0].isalpha():
            m = _PROTEIN_RES_RE.match(tok)
            if m and tok in anchor_set:
                tagged.append(("anchor", tok))
            elif m:
                tagged.append(("non_anchor", tok))
            else:
                # e.g. multi-residue motif token like A64-A86 (shouldn't appear in inputs)
                tagged.append(("gap", tok))
        else:
            tagged.append(("gap", tok))

    # Walk tagged list; merge consecutive anchors (including intervening gaps) into one token
    new_tokens: list[str] = []
    non_anchor_i = 0
    i = 0
    while i < len(tagged):
        tag, tok = tagged[i]
        if tag == "gap":
            new_tokens.append(tok)
            i += 1
        elif tag == "non_anchor":
            new_tokens.append(f"A{NON_ANCHOR_START + non_anchor_i}")
            non_anchor_i += 1
            i += 1
        else:  # anchor — find the extent of the consecutive anchor run
            run_start = i
            j = i + 1
            # Consume alternating gaps and anchors as long as the run continues with anchors
            while j < len(tagged):
                if tagged[j][0] == "anchor":
                    j += 1
                elif tagged[j][0] == "gap" and j + 1 < len(tagged) and tagged[j + 1][0] == "anchor":
                    j += 2
                else:
                    break
            run_end = j - 1

            # Collect anchor tokens in this run
            run_anchor_toks = [tagged[k][1] for k in range(run_start, run_end + 1) if tagged[k][0] == "anchor"]
            if len(run_anchor_toks) >= 2:
                # Get chai positions for first and last anchor in run
                first_m = _PROTEIN_RES_RE.match(run_anchor_toks[0])
                last_m = _PROTEIN_RES_RE.match(run_anchor_toks[-1])
                chai_start = contig_map.get((first_m.group(1), int(first_m.group(2))))
                chai_end = contig_map.get((last_m.group(1), int(last_m.group(2))))
                new_tokens.append(f"A{chai_start}-{chai_end}")
            else:
                # Single anchor residue in this run — emit it with its chai position
                m = _PROTEIN_RES_RE.match(run_anchor_toks[0])
                chai_pos = contig_map.get((m.group(1), int(m.group(2))))
                new_tokens.append(f"A{chai_pos}")
            i = run_end + 1

    new_contig = ",".join(new_tokens)

    # Rebuild select_fixed_atoms.
    # Non-anchor protein residues must be numbered in contig order (same order
    # as the contig token walk above) to keep the two numbering schemes in sync.
    protein_sfa_keys = [
        (key, contig_map.get((_PROTEIN_RES_RE.match(key).group(1), int(_PROTEIN_RES_RE.match(key).group(2))), 0))
        for key in original_sfa
        if _PROTEIN_RES_RE.match(key)
    ]
    protein_sfa_keys.sort(key=lambda x: x[1])
    non_anchor_order = [k for k, _ in protein_sfa_keys if k not in anchor_set]

    new_sfa: dict = {}
    non_anchor_i = 0
    # First pass: emit anchor entries (in their original order within SFA)
    # and ligand entries; collect non-anchor positions
    sfa_ordered = {}
    for key, atoms in original_sfa.items():
        m = _PROTEIN_RES_RE.match(key)
        if not m:
            new_sfa[key] = atoms  # ligand — unchanged
            continue
        chain_id, resnum = m.group(1), int(m.group(2))
        if key in anchor_set:
            chai_pos = contig_map.get((chain_id, resnum))
            new_sfa[f"{chain_id}{chai_pos}"] = atoms
        else:
            sfa_ordered[key] = atoms  # defer; number in contig order below

    # Second pass: emit non-anchor entries in contig order
    for key in non_anchor_order:
        new_sfa[f"A{NON_ANCHOR_START + non_anchor_i}"] = sfa_ordered[key]
        non_anchor_i += 1

    return new_contig, new_sfa


# ── Main ───────────────────────────────────────────────────────────────────────

def process_model(
    model_name: str,
    entry: dict,
    design_config: dict,
    ref_pdb_dir: Path,
    output_dir: Path,
    rmsd_threshold: float,
) -> dict:
    """Build redesign_scaffold.cif for one model. Return updated design config entry."""

    if model_name not in design_config:
        print(f"Warning: {model_name} not found in design config; skipping", file=sys.stderr)
        return {}

    cfg = design_config[model_name]
    contig_str = cfg["contig"]
    original_sfa = cfg["select_fixed_atoms"]
    contig_map = _parse_contig(contig_str)

    # Anchor info from best_fold entry
    anchor_sequences = _parse_anchor_sequences(entry.get("anchor_sequences", ""))
    anchor_ref_ranges = _parse_anchor_ref_residues(entry.get("anchor_ref_residues", ""))
    anchor_residues_str = entry.get("anchor_residues", "")
    anchor_set = set(anchor_residues_str.split(",")) if anchor_residues_str else set()

    # Locate best CIF
    run_dir = Path(entry["run_dir"])
    chai_idx = entry["chai1_model_idx"]
    best_cif = run_dir / "prediction" / f"pred.model_idx_{chai_idx}.cif"
    if not best_cif.exists():
        print(f"Warning: best CIF not found: {best_cif}", file=sys.stderr)
        return {}

    # Locate reference PDB (resolve relative path from design config if needed)
    ref_input = cfg.get("input", "")
    if Path(ref_input).is_absolute():
        ref_pdb_path = Path(ref_input)
    else:
        # Fall back to mcsa_pdb_dir/<model_name>.pdb
        ref_pdb_path = ref_pdb_dir / f"{model_name}.pdb"
    if not ref_pdb_path.exists():
        print(f"Warning: reference structure not found: {ref_pdb_path}", file=sys.stderr)
        return {}

    # Load structures
    cif_st = gemmi.read_structure(str(best_cif))
    ref_st = gemmi.read_structure(str(ref_pdb_path))

    # Ordered protein motif residues for Kabsch alignment
    protein_res_keys: list[tuple[str, str, int]] = []  # (res_key, chain, resnum)
    for key in original_sfa:
        m = _PROTEIN_RES_RE.match(key)
        if m:
            protein_res_keys.append((key, m.group(1), int(m.group(2))))
    protein_res_keys.sort(key=lambda x: contig_map.get((x[1], x[2]), 0))

    # Compute Kabsch transform
    try:
        R, t = _compute_kabsch_from_model(ref_st, cif_st, protein_res_keys, contig_map)
    except Exception as e:
        print(f"Warning: Kabsch alignment failed for {model_name}: {e}", file=sys.stderr)
        return {}

    # Extract anchor residues from chai CIF (transformed to reference frame)
    anchor_residues_data = _extract_anchor_chain(cif_st, anchor_sequences, R, t)

    # Extract non-anchor reference residues and ligand
    non_anchor_protein, ligand_residues = _extract_non_anchor_ref(ref_st, anchor_ref_ranges)

    # Write redesign_scaffold.cif
    model_out_dir = output_dir / model_name
    model_out_dir.mkdir(parents=True, exist_ok=True)
    scaffold_path = model_out_dir / "redesign_scaffold.cif"
    redesign_st = _build_redesign_structure(anchor_residues_data, non_anchor_protein, ligand_residues)
    redesign_st.make_mmcif_document().write_file(str(scaffold_path))
    print(f"  [{model_name}] wrote {scaffold_path}")

    # Rebuild contig and select_fixed_atoms
    new_contig, new_sfa = _rebuild_contig_and_sfa(
        contig_str, original_sfa, anchor_set, contig_map, anchor_sequences
    )

    # Build updated design config entry
    new_entry = dict(cfg)
    new_entry["input"] = str(scaffold_path.resolve())
    new_entry["contig"] = new_contig
    new_entry["select_fixed_atoms"] = new_sfa
    return new_entry


def main():
    parser = argparse.ArgumentParser(
        description="Build redesign_scaffold.cif and redesign.json for failing fold models."
    )
    parser.add_argument("--best-fold", type=Path, required=True,
                        help="Path to best_fold.json (model_name → {motif_rmsd, run_dir, seed, chai1_model_idx, ...})")
    parser.add_argument("--design-config", type=Path, required=True,
                        help="Original RFD3 design config JSON")
    parser.add_argument("--reference-pdb-dir", type=Path, required=True,
                        help="Directory containing reference PDB files")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Branch output directory; per-model subdirs are created here")
    parser.add_argument("--rmsd-threshold", type=float, default=1.5,
                        help="Anchor residue displacement threshold (default: 1.5)")
    args = parser.parse_args()

    with open(args.best_fold) as fh:
        best_fold: dict = json.load(fh)
    with open(args.design_config) as fh:
        design_config: dict = json.load(fh)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    redesign_json: dict = {}
    for model_name, entry in best_fold.items():
        print(f"Processing {model_name} ...")
        new_entry = process_model(
            model_name, entry, design_config,
            args.reference_pdb_dir, args.output_dir, args.rmsd_threshold,
        )
        if new_entry:
            redesign_json[model_name] = new_entry

    if not redesign_json:
        print("No models processed; redesign.json not written.", file=sys.stderr)
        sys.exit(1)

    out_json = args.output_dir / "redesign.json"
    with open(out_json, "w") as fh:
        json.dump(redesign_json, fh, indent=2)
    print(f"Wrote redesign.json with {len(redesign_json)} model(s) to {out_json}")


if __name__ == "__main__":
    main()
