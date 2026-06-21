#!/usr/bin/env python3
"""
interface_analysis.py — Protein-ligand interface geometry analysis

Given a two-chain PDB file (binder + ligand), this script:
  1.  Loads the structure into a DataFrame (binder = chain 1, ligand = chain 2)
  2.  Computes per-residue rSASA (Shrake-Rupley / Tien 2013 reference values)
  3.  Identifies buried residues (rSASA == 0)
  4.  Computes the full intermolecular atom-pair distance matrix
  5.  Identifies contact residues (min intermolecular dist < 3.5 Å)
  6.  Derives interface residues  = buried ∩ contact
  7.  Derives interface frontier residues = rSASA > 0  AND  contact
  8.  Fits the interface plane (PCA/SVD, minimises Σ orthogonal distance²)
  9.  Computes the interface origin (centroid of interface atoms → plane)
 10.  Defines the interface pole (⊥ to plane through origin) and azimuth
      reference vector (largest frontier intermolecular distance projected
      onto plane)
 11.  Computes cylindrical coordinates for candidate targets and binder
      frontier residues relative to the interface reference frame
 12.  Selects a random candidate target near median height and finds the
      two binder frontier residues angularly closest to it

Usage
-----
    python interface_analysis.py <complex.pdb> [random_seed]
"""

import sys
import random
import numpy as np
import pandas as pd
import warnings

from Bio import PDB
from Bio.PDB.SASA import ShrakeRupley

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

# Tien et al. 2013 – PLoS ONE 8(11): e80635 – Table 2 (theoretical max ASA, Å²)
TIEN_MAX_ASA = {
    "ALA": 129.0, "ARG": 274.0, "ASN": 195.0, "ASP": 193.0,
    "CYS": 167.0, "GLN": 225.0, "GLU": 223.0, "GLY": 104.0,
    "HIS": 224.0, "ILE": 197.0, "LEU": 201.0, "LYS": 236.0,
    "MET": 224.0, "PHE": 240.0, "PRO": 159.0, "SER": 155.0,
    "THR": 172.0, "TRP": 285.0, "TYR": 263.0, "VAL": 174.0,
}

# Non-standard residue name aliases → canonical 3-letter code
RESIDUE_ALIASES = {
    "HIE": "HIS", "HID": "HIS", "HIP": "HIS",
    "HSE": "HIS", "HSD": "HIS", "HSP": "HIS",
    "GLH": "GLU", "ASH": "ASP", "LYN": "LYS",
    "CYX": "CYS", "CYM": "CYS", "MSE": "MET",
}

CONTACT_CUTOFF = 5.0  # Å


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 – Load PDB into a DataFrame
# ──────────────────────────────────────────────────────────────────────────────

def load_pdb(pdb_path: str):
    """
    Parse a PDB file into an atom-level DataFrame.

    Verifies that exactly (or at least) two chains are present.
    The first chain is labelled the *binder*; the second the *ligand*.

    Returns
    -------
    df        : pd.DataFrame  — one row per atom
    structure : Bio.PDB structure object  (used for SASA calculation)
    binder    : str  — chain ID of the binder
    ligand    : str  — chain ID of the ligand
    """
    parser = PDB.PDBParser(QUIET=True)
    structure = parser.get_structure("cx", pdb_path)

    rows = []
    for model in structure:
        for chain in model:
            for residue in chain:
                _, seq, icode = residue.get_id()
                res_name = residue.get_resname().strip()
                for atom in residue:
                    x, y, z = atom.get_coord()
                    rows.append({
                        "chain_id":       chain.get_id(),
                        "residue_index":  seq,
                        "insertion_code": icode.strip(),
                        "residue_name":   res_name,
                        "atom_name":      atom.get_name(),
                        "atom_serial":    atom.get_serial_number(),
                        "x": x, "y": y, "z": z,
                    })

    df = pd.DataFrame(rows)
    chains = df["chain_id"].unique().tolist()

    if len(chains) < 2:
        raise ValueError(
            f"Found only {len(chains)} chain(s) ({chains}). "
            "The PDB must contain at least a binder and a ligand chain."
        )
    if len(chains) > 2:
        print(f"  WARNING: {len(chains)} chains detected — "
              f"using '{chains[0]}' as binder and '{chains[1]}' as ligand.")

    binder, ligand = chains[0], chains[1]
    print(f"  Binder chain : {binder}  "
          f"({(df.chain_id == binder).sum()} atoms, "
          f"{df[df.chain_id == binder]['residue_index'].nunique()} residues)")
    print(f"  Ligand chain : {ligand}  "
          f"({(df.chain_id == ligand).sum()} atoms, "
          f"{df[df.chain_id == ligand]['residue_index'].nunique()} residues)")

    return df, structure, binder, ligand


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 – Relative SASA per residue  (Shrake-Rupley + Tien 2013)
# ──────────────────────────────────────────────────────────────────────────────

def compute_rsasa(structure) -> dict:
    """
    Run the Shrake-Rupley algorithm (BioPython, probe radius = 1.4 Å) and
    normalise each residue's ASA by the Tien 2013 theoretical maximum.

    Returns
    -------
    dict mapping (chain_id, residue_index) → rSASA (float).
    Residues without a reference value (non-standard, small-molecule)
    receive rSASA = NaN.
    """
    sr = ShrakeRupley()
    sr.compute(structure, level="R")   # sets residue.sasa for every residue

    rsasa = {}
    for model in structure:
        for chain in model:
            cid = chain.get_id()
            for residue in chain:
                seq   = residue.get_id()[1]
                rname = RESIDUE_ALIASES.get(
                    residue.get_resname().strip(),
                    residue.get_resname().strip()
                )
                max_asa = TIEN_MAX_ASA.get(rname)
                if max_asa and max_asa > 0:
                    rsasa[(cid, seq)] = residue.sasa / max_asa
                else:
                    rsasa[(cid, seq)] = float("nan")
    return rsasa


# ──────────────────────────────────────────────────────────────────────────────
# Step 3 – Buried residues  (rSASA == 0)
# ──────────────────────────────────────────────────────────────────────────────

def get_buried(rsasa: dict, threshold: float = 0.0) -> set:
    """Return set of (chain_id, residue_index) pairs where rSASA <= threshold."""
    return {k for k, v in rsasa.items() if not np.isnan(v) and v <= threshold}


# ──────────────────────────────────────────────────────────────────────────────
# Step 4 – Intermolecular atom-pair distance matrix
# ──────────────────────────────────────────────────────────────────────────────

def intermolecular_matrix(df: pd.DataFrame, binder: str, ligand: str):
    """
    Compute the (n_binder_atoms × n_ligand_atoms) Euclidean distance matrix.

    Returns
    -------
    dist : np.ndarray, shape (n_binder, n_ligand)
    bdf  : DataFrame of binder atoms with *reset integer index* matching dist rows
    ldf  : DataFrame of ligand atoms with *reset integer index* matching dist cols
    """
    bdf = df[df["chain_id"] == binder].reset_index(drop=True)
    ldf = df[df["chain_id"] == ligand].reset_index(drop=True)

    bc = bdf[["x", "y", "z"]].values   # (n_b, 3)
    lc = ldf[["x", "y", "z"]].values   # (n_l, 3)

    diff = bc[:, None] - lc[None]       # (n_b, n_l, 3)
    dist = np.sqrt((diff * diff).sum(-1))

    return dist, bdf, ldf


# ──────────────────────────────────────────────────────────────────────────────
# Step 5 – Contact residues  (min intermolecular distance < cutoff)
# ──────────────────────────────────────────────────────────────────────────────

def get_contacts(dist: np.ndarray, bdf: pd.DataFrame, ldf: pd.DataFrame,
                 cutoff: float = CONTACT_CUTOFF) -> set:
    """
    Return set of (chain_id, residue_index) for residues in either chain
    that have at least one atom within `cutoff` Å of any atom in the other chain.
    """
    contacts = set()
    for res, grp in bdf.groupby("residue_index"):
        if dist[grp.index].min() < cutoff:
            contacts.add((grp["chain_id"].iloc[0], res))
    for res, grp in ldf.groupby("residue_index"):
        if dist[:, grp.index].min() < cutoff:
            contacts.add((grp["chain_id"].iloc[0], res))
    return contacts


# ──────────────────────────────────────────────────────────────────────────────
# Step 6 – Interface residues  (buried ∩ contact)
# ──────────────────────────────────────────────────────────────────────────────

def get_interface(buried: set, contacts: set) -> set:
    """Return residues that are both buried (rSASA=0) and in contact."""
    return buried & contacts


# ──────────────────────────────────────────────────────────────────────────────
# Step 7 – Interface frontier residues  (rSASA > 0  AND  contact)
# ──────────────────────────────────────────────────────────────────────────────

def get_frontier(rsasa: dict, dist: np.ndarray,
                 bdf: pd.DataFrame, ldf: pd.DataFrame,
                 cutoff: float = CONTACT_CUTOFF,
                 threshold: float = 0.0) -> set:
    """
    Return residues (from either chain) that are surface-exposed
    (rSASA > threshold) and have at least one atom within `cutoff` Å
    of the opposing chain.
    """
    frontier = set()
    for res, grp in bdf.groupby("residue_index"):
        cid = grp["chain_id"].iloc[0]
        v   = rsasa.get((cid, res), float("nan"))
        if not np.isnan(v) and v > threshold and dist[grp.index].min() < cutoff:
            frontier.add((cid, res))
    for res, grp in ldf.groupby("residue_index"):
        cid = grp["chain_id"].iloc[0]
        v   = rsasa.get((cid, res), float("nan"))
        if not np.isnan(v) and v > threshold and dist[:, grp.index].min() < cutoff:
            frontier.add((cid, res))
    return frontier


# ──────────────────────────────────────────────────────────────────────────────
# Shared helper: extract atom coordinates for a set of residues
# ──────────────────────────────────────────────────────────────────────────────

def _residue_atoms(df: pd.DataFrame, residue_set: set) -> np.ndarray:
    """Return (N, 3) float array of all atom coordinates in `residue_set`."""
    chains  = df["chain_id"].values
    seqnums = df["residue_index"].values
    mask    = np.zeros(len(df), dtype=bool)
    for (c, r) in residue_set:
        mask |= (chains == c) & (seqnums == r)
    return df.loc[mask, ["x", "y", "z"]].values.astype(float)


def _residue_centroid(df: pd.DataFrame, chain_id: str, res_num: int) -> np.ndarray:
    """Return (3,) centroid of a single residue's atoms."""
    mask = (df["chain_id"] == chain_id) & (df["residue_index"] == res_num)
    return df.loc[mask, ["x", "y", "z"]].values.mean(axis=0)


# ──────────────────────────────────────────────────────────────────────────────
# Step 8 – Interface plane  (SVD / PCA)
# ──────────────────────────────────────────────────────────────────────────────

def fit_plane(df: pd.DataFrame, residue_set: set):
    """
    Fit a plane to the atoms of `residue_set` by minimising the sum of
    squared orthogonal distances (equivalent to PCA).

    The plane is defined by its centroid and unit normal:
      - centroid: mean position of all atoms (plane passes through this point)
      - normal:   right-singular vector corresponding to the *smallest*
                  singular value of the centred coordinate matrix

    Returns (centroid [3], unit_normal [3]).
    """
    pts = _residue_atoms(df, residue_set)
    if len(pts) < 3:
        raise ValueError(
            f"Only {len(pts)} atom(s) in interface residue set — "
            "need ≥3 to fit a plane."
        )
    centroid = pts.mean(axis=0)
    _, _, Vt = np.linalg.svd(pts - centroid, full_matrices=False)
    normal   = Vt[-1]
    normal  /= np.linalg.norm(normal)
    return centroid, normal


# ──────────────────────────────────────────────────────────────────────────────
# Step 9 – Interface origin  (centroid of interface atoms projected onto plane)
# ──────────────────────────────────────────────────────────────────────────────

def compute_origin(df: pd.DataFrame, residue_set: set,
                   plane_pt: np.ndarray, plane_n: np.ndarray) -> np.ndarray:
    """
    Compute the centroid of all atoms in `residue_set`, then project it
    orthogonally onto the interface plane defined by (plane_pt, plane_n).

    Because the SVD plane passes through the centroid by construction, the
    projection is a no-op for interface atoms — but the explicit computation
    is retained for generality and clarity.

    Returns the interface origin as a (3,) array.
    """
    pts      = _residue_atoms(df, residue_set)
    centroid = pts.mean(axis=0)
    d        = np.dot(centroid - plane_pt, plane_n)
    return centroid - d * plane_n


# ──────────────────────────────────────────────────────────────────────────────
# Step 10 – Interface pole + azimuth reference vector
# ──────────────────────────────────────────────────────────────────────────────

def compute_azimuth(dist: np.ndarray,
                    bdf: pd.DataFrame, ldf: pd.DataFrame,
                    frontier: set,
                    origin: np.ndarray, normal: np.ndarray):
    """
    Among the interface frontier residues, find the binder–ligand atom pair
    with the *largest* intermolecular distance.  Project the atom–atom vector
    onto the interface plane and normalise to obtain the azimuth reference.

    Falls back to all atoms if no frontier atoms are found in a chain.

    Returns
    -------
    azimuth : (3,) unit vector in the interface plane at angle = 0°
    atom_a  : Series — the binder atom of the max-distance pair
    atom_b  : Series — the ligand atom of the max-distance pair
    max_d   : float  — the maximum distance (Å)
    """
    b_keys  = list(zip(bdf["chain_id"], bdf["residue_index"]))
    l_keys  = list(zip(ldf["chain_id"], ldf["residue_index"]))
    b_idx   = np.where([k in frontier for k in b_keys])[0]
    l_idx   = np.where([k in frontier for k in l_keys])[0]

    if len(b_idx) == 0 or len(l_idx) == 0:
        print("  WARNING: no frontier atoms in one chain; using all atoms for azimuth.")
        b_idx = bdf.index.values
        l_idx = ldf.index.values

    sub      = dist[np.ix_(b_idx, l_idx)]
    bi, li   = np.unravel_index(np.argmax(sub), sub.shape)
    max_d    = float(sub[bi, li])
    atom_a   = bdf.loc[b_idx[bi]]
    atom_b   = ldf.loc[l_idx[li]]

    coord_a  = np.array([atom_a.x, atom_a.y, atom_a.z], dtype=float)
    coord_b  = np.array([atom_b.x, atom_b.y, atom_b.z], dtype=float)
    vec      = coord_b - coord_a

    # Project onto interface plane (remove normal component)
    in_plane = vec - np.dot(vec, normal) * normal
    norm_len = np.linalg.norm(in_plane)
    if norm_len < 1e-9:
        raise ValueError(
            "Azimuth direction collapses to zero after projection onto the "
            "interface plane (atom-atom vector is parallel to plane normal)."
        )
    azimuth = in_plane / norm_len
    return azimuth, atom_a, atom_b, max_d


# ──────────────────────────────────────────────────────────────────────────────
# Cylindrical coordinate utility
# ──────────────────────────────────────────────────────────────────────────────

def to_cylindrical(point: np.ndarray,
                   origin: np.ndarray,
                   normal: np.ndarray,
                   azimuth: np.ndarray) -> tuple:
    """
    Convert a 3-D Cartesian point to cylindrical coordinates in the
    interface reference frame.

    Parameters
    ----------
    point   : (3,) Cartesian coordinates of the point
    origin  : (3,) interface origin (lies on the interface plane)
    normal  : (3,) unit normal of the interface plane  (= pole direction)
    azimuth : (3,) unit in-plane vector at angle = 0°  (azimuth reference)

    Returns
    -------
    height    : signed distance from the interface plane along the pole
                (positive = on the side the normal points toward)
    radius    : distance from the pole axis projected into the plane
    angle_deg : azimuthal angle in [0°, 360°), measured counter-clockwise
                from `azimuth` when viewed from the positive-normal side
    """
    vec      = point - origin
    height   = float(np.dot(vec, normal))
    in_plane = vec - height * normal
    radius   = float(np.linalg.norm(in_plane))

    if radius < 1e-9:
        angle = 0.0
    else:
        perp  = np.cross(normal, azimuth)   # 90° CCW from azimuth in the plane
        perp /= np.linalg.norm(perp)
        unit  = in_plane / radius
        cos_t = float(np.clip(np.dot(unit, azimuth), -1.0, 1.0))
        sin_t = float(np.dot(unit, perp))
        angle = float(np.degrees(np.arctan2(sin_t, cos_t)) % 360)

    return height, radius, angle


# ──────────────────────────────────────────────────────────────────────────────
# Step 11 – Cylindrical coordinates of candidate targets and frontier residues
# ──────────────────────────────────────────────────────────────────────────────

def compute_cylindrical(df: pd.DataFrame, rsasa: dict, frontier: set,
                        binder: str, ligand: str,
                        origin: np.ndarray, normal: np.ndarray,
                        azimuth: np.ndarray):
    """
    For each residue of interest, compute:
      (a) the centroid of its atoms
      (b) the cylindrical coordinates of that centroid in the interface frame

    Candidate targets  : ligand residues with rSASA > 0
    Binder frontier    : interface frontier residues belonging to the binder

    Returns (targets, binder_frontier) — each a list of dicts with keys:
        chain, residue, height, radius, angle, [rsasa for targets]
    """
    def _cyl(c, r):
        ctr          = _residue_centroid(df, c, r)
        h, rad, ang  = to_cylindrical(ctr, origin, normal, azimuth)
        return {"chain": c, "residue": r,
                "centroid": ctr, "height": h, "radius": rad, "angle": ang}

    # Candidate targets: surface-accessible ligand residues
    targets = []
    for res in sorted(df[df["chain_id"] == ligand]["residue_index"].unique()):
        v = rsasa.get((ligand, res), float("nan"))
        if not np.isnan(v) and v > 0:
            d = _cyl(ligand, res)
            d["rsasa"] = v
            targets.append(d)

    # Binder frontier residues
    bfront = []
    for (c, r) in sorted(frontier):
        if c != binder:
            continue
        bfront.append(_cyl(c, r))

    return targets, bfront


# ──────────────────────────────────────────────────────────────────────────────
# Step 12 – Select design residues
# ──────────────────────────────────────────────────────────────────────────────

def select_design_residues(targets: list, binder_frontier: list,
                           seed=None,
                           target_h: float = 1.0,
                           return_all: bool = True):
    """
    For each candidate target, identify its two angularly nearest binder
    frontier residues to form a (target, neighbor_1, neighbor_2) triple.

    Parameters
    ----------
    target_h   : float in [0, 1] — quantile of |target heights| used as the
                 reference height for the random draw (return_all=False only).
    return_all : if True, return all triples sorted by |target height|
                 descending (furthest from the interface plane first).
                 if False, randomly draw one target near the target_h quantile
                 and return its single triple.

    Returns
    -------
    (triples, ref_h) where
      triples : list of (target, n1, n2) when return_all=True,
                or a single (target, n1, n2) tuple when return_all=False.
      ref_h   : the |height| quantile value used as the reference.
    """
    if not targets:
        raise ValueError(
            "No candidate targets found (ligand residues with rSASA > 0). "
            "Check that the ligand chain contains standard amino acids or "
            "that rSASA was computed correctly for non-standard residues."
        )
    if len(binder_frontier) < 2:
        raise ValueError(
            f"Only {len(binder_frontier)} binder frontier residue(s) — "
            "need ≥2 to form a pair."
        )

    if seed is not None:
        random.seed(seed)

    ref_h = float(np.quantile([abs(t["height"]) for t in targets], target_h))

    def angular_dist(a1, a2):
        d = abs(a1 - a2) % 360
        return min(d, 360 - d)

    def two_neighbors(target):
        sf = sorted(binder_frontier,
                    key=lambda r: angular_dist(r["angle"], target["angle"]))
        return sf[0], sf[1]

    if return_all:
        sorted_targets = sorted(targets, key=lambda t: abs(t["height"]),
                                reverse=True)
        triples = [(t, *two_neighbors(t)) for t in sorted_targets]
        return triples, ref_h
    else:
        sorted_t = sorted(targets, key=lambda t: abs(abs(t["height"]) - ref_h))
        n_near   = max(1, len(sorted_t) // 4)
        chosen   = random.choice(sorted_t[:n_near])
        return (chosen, *two_neighbors(chosen)), ref_h


# ──────────────────────────────────────────────────────────────────────────────
# Main driver
# ──────────────────────────────────────────────────────────────────────────────

def main(pdb_path: str, contact_cutoff: float = CONTACT_CUTOFF,
         rsasa_cutoff: float = 0.3, seed=None):
    bar = "─" * 64
    print(f"\n{bar}")
    print("  Protein-Ligand Interface Analysis")
    print(f"  Input : {pdb_path}")
    print(bar)

    # ── 1 ── Load PDB ────────────────────────────────────────────────────────
    print("\n[1] Loading PDB …")
    df, structure, binder, ligand = load_pdb(pdb_path)

    # ── 2 ── rSASA ───────────────────────────────────────────────────────────
    print("\n[2] Computing relative SASA (Shrake-Rupley / Tien 2013) …")
    rsasa = compute_rsasa(structure)
    n_std = sum(1 for v in rsasa.values() if not np.isnan(v))
    print(f"  Residues with Tien 2013 reference : {n_std} / {len(rsasa)}")

    # ── 3 ── Buried residues ─────────────────────────────────────────────────
    print(f"\n[3] Identifying buried residues (rSASA ≤ {rsasa_cutoff}) …")
    buried = get_buried(rsasa, threshold=rsasa_cutoff)
    print(f"  Buried residues : {len(buried)}")
    for cr in sorted(buried):
        rname = df[(df.chain_id == cr[0]) & (df.residue_index == cr[1])][
            "residue_name"].iloc[0]
        print(f"    [{cr[0]}, {cr[1]:4d}]  {rname}")

    # ── 4 ── Distance matrix ─────────────────────────────────────────────────
    print("\n[4] Computing intermolecular distance matrix …")
    dist, bdf, ldf = intermolecular_matrix(df, binder, ligand)
    print(f"  Matrix : {dist.shape[0]} binder atoms × {dist.shape[1]} ligand atoms")
    print(f"  Distance range : {dist.min():.2f} – {dist.max():.2f} Å")

    # ── 5 ── Contact residues ────────────────────────────────────────────────
    print(f"\n[5] Identifying contact residues (< {contact_cutoff} Å) …")
    contacts = get_contacts(dist, bdf, ldf, contact_cutoff)
    print(f"  Contact residues : {len(contacts)}")
    for cr in sorted(contacts):
        rname = df[(df.chain_id == cr[0]) & (df.residue_index == cr[1])][
            "residue_name"].iloc[0]
        print(f"    [{cr[0]}, {cr[1]:4d}]  {rname}")

    # ── 6 ── Interface residues ──────────────────────────────────────────────
    print("\n[6] Interface residues (buried ∩ contact) …")
    iface = get_interface(buried, contacts)
    print(f"  Interface residues : {len(iface)}")
    for cr in sorted(iface):
        rname = df[(df.chain_id == cr[0]) & (df.residue_index == cr[1])][
            "residue_name"].iloc[0]
        print(f"    [{cr[0]}, {cr[1]:4d}]  {rname}")

    # ── 7 ── Frontier residues ───────────────────────────────────────────────
    print(f"\n[7] Interface frontier residues (rSASA > {rsasa_cutoff} AND contact) …")
    frontier = get_frontier(rsasa, dist, bdf, ldf, contact_cutoff,
                            threshold=rsasa_cutoff)
    print(f"  Frontier residues : {len(frontier)}")
    for cr in sorted(frontier):
        rname = df[(df.chain_id == cr[0]) & (df.residue_index == cr[1])][
            "residue_name"].iloc[0]
        v     = rsasa.get(cr, float("nan"))
        print(f"    [{cr[0]}, {cr[1]:4d}]  {rname}  rSASA = {v:.3f}")

    # ── 8 ── Interface plane ─────────────────────────────────────────────────
    print("\n[8] Fitting interface plane (SVD) …")
    if iface:
        iface_for_plane = iface
    else:
        # No residue is simultaneously buried (rSASA=0) AND in contact — this
        # happens when the interface is not tightly packed enough to completely
        # occlude any single residue in the complex SASA calculation.
        # Fall back to using all contact residues for plane / origin fitting.
        iface_for_plane = contacts
        print("  NOTE: buried ∩ contact is empty; falling back to all contact "
              "residues for plane and origin fitting.")
    plane_pt, plane_n = fit_plane(df, iface_for_plane)
    print(f"  Plane centroid : [{plane_pt[0]:.3f}, {plane_pt[1]:.3f}, {plane_pt[2]:.3f}]")
    print(f"  Plane normal   : [{plane_n[0]:.4f}, {plane_n[1]:.4f}, {plane_n[2]:.4f}]")

    # ── 9 ── Interface origin ────────────────────────────────────────────────
    print("\n[9] Computing interface origin …")
    origin = compute_origin(df, iface_for_plane, plane_pt, plane_n)
    print(f"  Interface origin : [{origin[0]:.3f}, {origin[1]:.3f}, {origin[2]:.3f}]")

    # ── 10 ── Pole + azimuth ─────────────────────────────────────────────────
    print("\n[10] Interface pole and azimuth reference …")
    print(f"  Pole direction (= plane normal) : "
          f"[{plane_n[0]:.4f}, {plane_n[1]:.4f}, {plane_n[2]:.4f}]")
    azimuth, atom_a, atom_b, max_d = compute_azimuth(
        dist, bdf, ldf, frontier, origin, plane_n
    )
    print(f"  Largest frontier intermolecular distance : {max_d:.3f} Å")
    print(f"    Atom A : [{atom_a.chain_id}, {atom_a.residue_index}] {atom_a.atom_name}")
    print(f"    Atom B : [{atom_b.chain_id}, {atom_b.residue_index}] {atom_b.atom_name}")
    print(f"  Azimuth reference vector : "
          f"[{azimuth[0]:.4f}, {azimuth[1]:.4f}, {azimuth[2]:.4f}]")

    # ── 11 ── Cylindrical coordinates ────────────────────────────────────────
    print("\n[11] Computing cylindrical coordinates …")
    targets, bfront = compute_cylindrical(
        df, rsasa, frontier, binder, ligand, origin, plane_n, azimuth
    )
    print(f"  Candidate targets (ligand rSASA > 0) : {len(targets)}")
    print(f"  Binder frontier residues              : {len(bfront)}")

    if targets:
        print("\n  Candidate targets (sorted by height):")
        for t in sorted(targets, key=lambda x: x["height"]):
            print(f"    [{t['chain']}, {t['residue']:4d}]  "
                  f"h = {t['height']:+7.2f} Å   "
                  f"r = {t['radius']:6.2f} Å   "
                  f"θ = {t['angle']:6.1f}°   "
                  f"rSASA = {t['rsasa']:.3f}")

    if bfront:
        print("\n  Binder frontier residues (sorted by angle):")
        for r in sorted(bfront, key=lambda x: x["angle"]):
            print(f"    [{r['chain']}, {r['residue']:4d}]  "
                  f"h = {r['height']:+7.2f} Å   "
                  f"r = {r['radius']:6.2f} Å   "
                  f"θ = {r['angle']:6.1f}°")

    # ── 12 ── Selection ──────────────────────────────────────────────────────
    print("\n[12] Selecting design residues …")
    result, ref_h = select_design_residues(targets, bfront, seed=seed)

    def _fmt_target(t):
        rname = df[(df.chain_id == t["chain"]) & (df.residue_index == t["residue"])][
            "residue_name"].iloc[0]
        return (f"  target   [{t['chain']}, {t['residue']}]  {rname}  "
                f"h = {t['height']:+.2f} Å   r = {t['radius']:.2f} Å   "
                f"θ = {t['angle']:.1f}°   rSASA = {t['rsasa']:.3f}")

    def _fmt_neighbor(r, target_angle, label):
        rname  = df[(df.chain_id == r["chain"]) & (df.residue_index == r["residue"])][
            "residue_name"].iloc[0]
        dtheta = abs(r["angle"] - target_angle) % 360
        dtheta = min(dtheta, 360 - dtheta)
        return (f"  {label}  [{r['chain']}, {r['residue']}]  {rname}  "
                f"θ = {r['angle']:.1f}°   Δθ = {dtheta:.1f}°   "
                f"h = {r['height']:+.2f} Å   r = {r['radius']:.2f} Å")

    print(f"\n{bar}")
    print("  DESIGN OUTPUT")
    print(bar)
    print(f"  Reference |height| (target_h quantile) : {ref_h:.3f} Å")

    if isinstance(result, list):
        # return_all=True: one block per target, ranked by |height| descending
        for i, (t, n1, n2) in enumerate(result, 1):
            print(f"\n  [{i}]")
            print(_fmt_target(t))
            print(_fmt_neighbor(n1, t["angle"], "neighbor_1"))
            print(_fmt_neighbor(n2, t["angle"], "neighbor_2"))
    else:
        # return_all=False: single randomly drawn triple
        t, n1, n2 = result
        print(f"\n  (random draw near reference height)")
        print(_fmt_target(t))
        print(_fmt_neighbor(n1, t["angle"], "neighbor_1"))
        print(_fmt_neighbor(n2, t["angle"], "neighbor_2"))

    print(bar)

    return {
        "binder":           binder,
        "ligand":           ligand,
        "rsasa":            rsasa,
        "buried":           buried,
        "contacts":         contacts,
        "interface":        iface,
        "frontier":         frontier,
        "plane_centroid":   plane_pt,
        "plane_normal":     plane_n,
        "origin":           origin,
        "azimuth":          azimuth,
        "targets":          targets,
        "binder_frontier":  bfront,
        "result":           result,
        "ref_h":            ref_h,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <complex.pdb> [random_seed]")
        sys.exit(1)
    _seed = int(sys.argv[2]) if len(sys.argv) > 2 else None
    main(sys.argv[1], seed=_seed)
