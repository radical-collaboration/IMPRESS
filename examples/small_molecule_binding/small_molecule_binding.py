
import asyncio
import copy
import gzip
import json
import os
import pathlib
import shutil
from functools import lru_cache

from impress.pipelines.impress_pipeline import ImpressBasePipeline


# Step constants for the outer state machine
STEP_DONE      = 0   # pipeline complete
STEP_RFD3      = 1   # backbone diffusion
STEP_MPNN      = 2   # mpnn + packmin refinement cycle
STEP_FASTRELAX = 3   # Rosetta FastRelax
STEP_INTERFACE = 4   # filter_shape (PyRosetta, gates fold prediction)
STEP_AF2       = 5   # fold prediction (Boltz-2 co-folding; name kept for compatibility)
STEP_RETRY_SEQ = 6   # internal: retry sequence prediction without backbone restart

# Ensemble transformation type labels
ETYPE_BACKBONE = 'generate backbone'
ETYPE_SEQUENCE = 'predict sequence'
ETYPE_FOLD     = 'fold decoy'


# ── Ensemble utility functions ─────────────────────────────────────────────

@lru_cache(maxsize=512)
def _parse_pdb_ca_coords(pdb_path: str) -> tuple:
    coords = []
    with open(pdb_path) as f:
        for line in f:
            if line.startswith('ATOM') and line[12:16].strip() == 'CA':
                coords.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
    return tuple(coords)


def _kabsch_rmsd(coords1, coords2) -> float:
    import numpy as np
    n = min(len(coords1), len(coords2))
    P = np.array(coords1[:n], dtype=float)
    Q = np.array(coords2[:n], dtype=float)
    P -= P.mean(axis=0)
    Q -= Q.mean(axis=0)
    H = P.T @ Q
    U, _, Vt = np.linalg.svd(H)
    d = np.linalg.det(Vt.T @ U.T)
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    diff = (P @ R.T) - Q
    return float(np.sqrt((diff ** 2).sum() / n))


def _ca_rmsd(path1: str, path2: str):
    """CA RMSD between two PDB files. Returns None for non-.pdb paths or empty coord sets."""
    if not (isinstance(path1, str) and isinstance(path2, str)):
        return None
    if not (path1.endswith('.pdb') and path2.endswith('.pdb')):
        return None
    c1 = _parse_pdb_ca_coords(path1)
    c2 = _parse_pdb_ca_coords(path2)
    if not c1 or not c2:
        return None
    return _kabsch_rmsd(c1, c2)


def _read_fasta_seq(fasta_path: str) -> str:
    if not fasta_path:
        return ''
    seq = []
    try:
        with open(fasta_path) as f:
            for line in f:
                if not line.startswith('>'):
                    seq.append(line.strip())
    except FileNotFoundError:
        return ''
    return ''.join(seq)


def _seq_identity(fasta1: str, fasta2: str):
    """Fraction of matching residues over shorter sequence. Returns None on empty."""
    s1 = _read_fasta_seq(fasta1)
    s2 = _read_fasta_seq(fasta2)
    if not s1 or not s2:
        return None
    n = min(len(s1), len(s2))
    return sum(a == b for a, b in zip(s1[:n], s2[:n])) / n


def _ensemble_selective_avg(
    current_output: str,
    prior_entries: list,
    sim_fn,
    similar_if_low: bool,
):
    """
    Returns (overall_avg, selective_avg, has_data: bool).
    selective_avg = average score of entries whose similarity to current is on the
    'similar' side of the mean pairwise similarity.
    has_data=False when prior_entries is empty or all similarity calls return None.
    """
    if not prior_entries:
        return None, None, False
    scores  = [t[1] for t in prior_entries]
    sims    = [sim_fn(current_output, t[3]) for t in prior_entries]
    valid   = [(s, sc) for s, sc in zip(sims, scores) if s is not None]
    overall_avg = sum(scores) / len(scores)
    if not valid:
        return overall_avg, None, False
    avg_sim = sum(s for s, _ in valid) / len(valid)
    if similar_if_low:
        sel_scores = [sc for s, sc in valid if s <= avg_sim]
    else:
        sel_scores = [sc for s, sc in valid if s >= avg_sim]
    if not sel_scores:
        return overall_avg, overall_avg, True
    return overall_avg, sum(sel_scores) / len(sel_scores), True


def _stage_metrics_improving(
    current: dict,
    previous: dict | None,
    specs: list,
    rel_tolerance: float = 0.05,
) -> bool:
    """Metric-agnostic "is this retry attempt actually helping" check, shared by
    adaptive_decision()'s 'fastrelax' and 'interface' short-circuit logic.

    `specs` is a list of (metric_key, lower_is_better, threshold) triples. For
    each metric present in both `current` and `previous` that was still failing
    on the previous attempt (gap > 0), checks whether its gap-to-threshold
    shrank by more than `rel_tolerance` of the previous gap. Returns True (an
    improvement was found) if any tracked metric improved; False if every
    still-failing metric stayed flat or got worse.

    Returns True (never short-circuit) when `previous` is None/empty -- there is
    no prior attempt on this backbone to compare against yet, so the first
    failure always gets one retry regardless of this check."""
    if not previous:
        return True
    for key, lower_is_better, threshold in specs:
        cur_val, prev_val = current.get(key), previous.get(key)
        if cur_val is None or prev_val is None:
            continue
        cur_gap  = (cur_val - threshold) if lower_is_better else (threshold - cur_val)
        prev_gap = (prev_val - threshold) if lower_is_better else (threshold - prev_val)
        if prev_gap <= 0:
            continue  # this metric already passed on the previous attempt
        if (prev_gap - cur_gap) > rel_tolerance * prev_gap:
            return True
    return False


# ── RFD3 guided-input utilities ────────────────────────────────────────────

def _ligand_resname_from_params(params_path: str) -> str:
    """Reads the 'NAME <resname>' record from a Rosetta .params file and returns
    the exact literal residue name (e.g. 'A:R' for ALR.params). This is the
    literal PDB/Rosetta residue name used in HETATM records for this ligand and
    is NOT always equal to the params filename stem -- never assume otherwise,
    and never hardcode a specific ligand's resname here or in any caller."""
    with open(params_path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == 'NAME':
                return parts[1]
    raise ValueError(f"no NAME record found in {params_path}")


def _find_ligand_hetatm_residue(st, ligand_chain_id: str = "B"):
    """Locates the ligand HETATM residue in a gemmi Structure. Tries
    ligand_chain_id first; if Boltz didn't honor the requested chain letter,
    falls back to the first HETATM residue found anywhere in the structure.
    Returns None if no HETATM residue exists at all. Shared by
    _normalize_ligand_id and _normalize_ligand_atom_names so both agree on
    exactly which residue is "the ligand"."""
    for model in st:
        for chain in model:
            if chain.name != ligand_chain_id:
                continue
            for res in chain:
                if res.het_flag == 'H':
                    return res

    for model in st:
        for chain in model:
            for res in chain:
                if res.het_flag == 'H':
                    return res

    return None


def _normalize_ligand_id(fold_pdb_path: str, ligand_resname: str, out_pdb_path: str,
                          ligand_chain_id: str = "B") -> bool:
    """Rewrites a Boltz co-folded PDB's ligand HETATM residue name (via gemmi) to
    match ligand_resname, so RFD3's ligand/select_exposed/select_buried selectors
    (which key off the literal resname) resolve against it. Purely a string edit
    -- no coordinate transform, since Boltz already places the ligand correctly
    relative to the protein it just folded. Writes out_pdb_path and returns True
    on success. Returns False (writing nothing) if no HETATM residue is found at
    all, so the caller can fall back to unguided diffusion instead of crashing.

    NOTE: this only fixes the residue name. Boltz also assigns its own,
    unrelated atom names within that residue -- see _normalize_ligand_atom_names
    for why those need fixing too before the guided spec is usable."""
    import gemmi
    st = gemmi.read_structure(fold_pdb_path)

    target_res = _find_ligand_hetatm_residue(st, ligand_chain_id)
    if target_res is None:
        return False

    target_res.name = ligand_resname
    st.write_pdb(out_pdb_path)
    return True


# Fallback table keyed on Rosetta atom TYPE prefix, used only when a params
# ATOM name's leading alphabetic run doesn't parse to a valid element symbol.
# Mirrors scripts/derive_ligand_smiles.py's _ROSETTA_TYPE_ELEMENT_FALLBACK
# (duplicated, not imported -- see _params_heavy_atom_graph). Verified only
# against ALR's C/N/O/S/H atom set; extend if a future ligand needs 2-letter
# elements (Cl/Br/Zn, etc.).
_ROSETTA_TYPE_ELEMENT_FALLBACK = {
    "Nhis": "N", "Nlys": "N",
    "CH1": "C", "CH2": "C", "CH3": "C", "COO": "C", "aroC": "C",
    "OH": "O", "OOC": "O", "ONH2": "O",
    "Hapo": "H", "Hpol": "H",
    "S": "S", "SH1": "S",
}


def _infer_ligand_element(atom_name: str, rosetta_type: str) -> str:
    """Infers an element symbol from a params ATOM record's name/type. Primary
    rule: the atom NAME's leading alphabetic run is the element itself (e.g.
    'C18' -> 'C', 'N11' -> 'N'); falls back to _ROSETTA_TYPE_ELEMENT_FALLBACK
    keyed on the Rosetta TYPE prefix. Mirrors
    scripts/derive_ligand_smiles.py's _infer_element (duplicated, not
    imported -- that script is a standalone offline tool, not part of this
    per-cycle pipeline path; scripts/ isn't an importable package)."""
    import re
    from rdkit import Chem
    periodic_table = Chem.GetPeriodicTable()

    match = re.match(r'[A-Za-z]+', atom_name)
    if match:
        candidate = match.group(0)
        for length in (2, 1):
            if len(candidate) >= length:
                symbol = candidate[:length].capitalize()
                if periodic_table.GetAtomicNumber(symbol) > 0:
                    return symbol

    for prefix, element in _ROSETTA_TYPE_ELEMENT_FALLBACK.items():
        if rosetta_type.startswith(prefix):
            return element

    raise ValueError(
        f"could not infer element for atom name={atom_name!r} type={rosetta_type!r}"
    )


def _params_heavy_atom_graph(params_path: str):
    """Parses a Rosetta .params file's ATOM/BOND records into a heavy-atom-only
    connectivity graph: ({atom_name: element}, [(atom1, atom2), ...]) where
    both bond endpoints are heavy atoms. Hydrogens are dropped entirely --
    unlike scripts/derive_ligand_smiles.py (which needs them to resolve bond
    order via DetermineBondOrders), _infer_ligand_atom_mapping only needs
    connectivity for graph-isomorphism matching, so no bond-order solving or
    placeholder hydrogen placement is needed here."""
    atom_types = {}
    bonds = []
    with open(params_path) as fh:
        for line in fh:
            fields = line.split()
            if not fields:
                continue
            record = fields[0]
            if record == 'ATOM':
                atom_types[fields[1]] = fields[2]
            elif record in ('BOND', 'BOND_TYPE'):
                bonds.append((fields[1], fields[2]))

    elements = {name: _infer_ligand_element(name, rtype) for name, rtype in atom_types.items()}
    heavy_names = {name for name, el in elements.items() if el != 'H'}
    heavy_elements = {name: elements[name] for name in heavy_names}
    heavy_bonds = [(a, b) for a, b in bonds if a in heavy_names and b in heavy_names]
    return heavy_elements, heavy_bonds


def _resolve_reference_pdb_path(base_json_path: str) -> str:
    """Reads partial.input from the base RFD3 design spec and resolves it
    relative to the spec's own directory (always pipeline_inputs). This is
    the correctly-named, real-coordinate reference ligand structure already
    shipped alongside every pipeline's inputs -- used as ground truth for
    atom identity/connectivity/geometry in _infer_ligand_atom_mapping."""
    with open(base_json_path) as fh:
        base = json.load(fh)
    ref = base['partial']['input']
    if os.path.isabs(ref):
        return ref
    return os.path.join(os.path.dirname(base_json_path), ref)


def _iter_ligand_atom_names(pdb_path: str, resname: str):
    """Atom names (fixed-column PDB parsing) of every HETATM record in
    pdb_path whose resname matches exactly. Fixed-column parsing (not a
    whitespace split) is required because names like 'A:R' contain a colon
    -- see _ligand_resname_from_params's docstring."""
    names = []
    with open(pdb_path) as fh:
        for line in fh:
            if line.startswith('HETATM') and line[17:20].strip() == resname:
                names.append(line[12:16].strip())
    return names


def _load_reference_ligand_coords(pdb_path: str, resname: str):
    """Reads {atom_name: (x, y, z)} for the first HETATM residue named
    exactly resname in pdb_path. Mirrors
    scripts/derive_ligand_smiles.py's _load_reference_coords (duplicated,
    not imported -- see _params_heavy_atom_graph); uses the same
    fixed-column parsing for the same reason (resnames like 'A:R' contain a
    colon a whitespace split would mangle)."""
    coords = {}
    target_resseq = None
    with open(pdb_path) as fh:
        for line in fh:
            if not (line.startswith('HETATM') or line.startswith('ATOM  ')):
                continue
            if line[17:20].strip() != resname:
                if coords:
                    break  # moved past the matching residue's contiguous block
                continue
            resseq = line[22:26].strip()
            if target_resseq is None:
                target_resseq = resseq
            elif resseq != target_resseq:
                break  # a different residue instance with the same name
            atom_name = line[12:16].strip()
            coords[atom_name] = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
    return coords


def _infer_ligand_atom_mapping(boltz_atoms: dict, params_path: str, reference_pdb_path: str):
    """Maps Boltz's arbitrarily-named ligand atom names onto the canonical
    names read from params_path, via element+connectivity graph isomorphism
    with a Kabsch-RMSD tie-break. boltz_atoms is
    {boltz_atom_name: (element, (x, y, z))} for one ligand residue.

    Boltz co-folding assigns its own atom names to the ligand (unrelated to
    the params file's canonical names), so select_exposed/select_buried
    (copied verbatim from the base RFD3 spec, keyed by canonical names) never
    match a Boltz-derived PDB's atom names without this step. Bond order is
    ignored throughout (the .params file has none) -- only element identity
    and heavy-atom connectivity establish correspondence:
      - reference graph: heavy atoms + bonds parsed straight from
        params_path's ATOM/BOND records (exact, no perception needed)
      - reference coordinates: the real 3D structure at reference_pdb_path
        (already correctly named -- see _resolve_reference_pdb_path)
      - query graph: boltz_atoms' connectivity, perceived from 3D distances
        via rdkit's DetermineConnectivity (Boltz's ligand output carries no
        CONECT records)
    Local topological symmetry (e.g. a sulfonate's three interchangeable
    terminal oxygens) can produce more than one graph-valid isomorphism; both
    structures carry real, roughly comparable 3D coordinates for the same
    ligand pose, so each candidate mapping is Kabsch-superposed against the
    reference and the lowest-RMSD one wins -- deterministic, and grounded in
    actual geometry rather than an arbitrary tiebreak. When more than one
    isomorphism exists, the best-vs-next-best RMSD gap is logged so a
    suspiciously close tie (a symmetry case this heuristic can't actually
    distinguish) is visible after the fact rather than silently accepted.

    Returns {boltz_name: canonical_name}, or None (never raises) if: heavy
    atom counts or element multisets differ, the reference PDB is missing
    coordinates for a params heavy atom, Boltz connectivity perception fails
    or yields a disconnected graph, or no isomorphism exists at all --
    callers must treat None exactly like _normalize_ligand_id returning
    False (fall back to unguided diffusion)."""
    from rdkit import Chem
    from rdkit.Chem import rdDetermineBonds
    from rdkit.Geometry import Point3D

    ref_elements, ref_bonds = _params_heavy_atom_graph(params_path)
    ref_resname = _ligand_resname_from_params(params_path)
    ref_coords = _load_reference_ligand_coords(reference_pdb_path, ref_resname)
    ref_names = [name for name in ref_elements if name in ref_coords]
    if len(ref_names) != len(ref_elements):
        return None  # reference PDB is missing coordinates for a params heavy atom

    if len(boltz_atoms) != len(ref_names):
        return None
    if sorted(element for element, _ in boltz_atoms.values()) != sorted(ref_elements[n] for n in ref_names):
        return None

    ref_mol = Chem.RWMol()
    ref_idx = {}
    for name in ref_names:
        ref_idx[name] = ref_mol.AddAtom(Chem.Atom(ref_elements[name]))
    for a, b in ref_bonds:
        if a in ref_idx and b in ref_idx:
            i, j = ref_idx[a], ref_idx[b]
            if ref_mol.GetBondBetweenAtoms(i, j) is None:
                ref_mol.AddBond(i, j, Chem.BondType.SINGLE)
    ref_conf = Chem.Conformer(ref_mol.GetNumAtoms())
    for name, idx in ref_idx.items():
        ref_conf.SetAtomPosition(idx, Point3D(*ref_coords[name]))
    ref_mol.AddConformer(ref_conf, assignId=True)
    Chem.SanitizeMol(ref_mol, sanitizeOps=Chem.SanitizeFlags.SANITIZE_NONE)

    boltz_names = list(boltz_atoms)
    boltz_mol = Chem.RWMol()
    boltz_idx = {}
    for name in boltz_names:
        element, _ = boltz_atoms[name]
        boltz_idx[name] = boltz_mol.AddAtom(Chem.Atom(element))
    boltz_conf = Chem.Conformer(boltz_mol.GetNumAtoms())
    for name, idx in boltz_idx.items():
        _, xyz = boltz_atoms[name]
        boltz_conf.SetAtomPosition(idx, Point3D(*xyz))
    boltz_mol.AddConformer(boltz_conf, assignId=True)
    Chem.SanitizeMol(boltz_mol, sanitizeOps=Chem.SanitizeFlags.SANITIZE_NONE)

    try:
        rdDetermineBonds.DetermineConnectivity(boltz_mol)
    except Exception:
        return None
    if len(Chem.GetMolFrags(boltz_mol)) != 1:
        return None

    matches = boltz_mol.GetSubstructMatches(ref_mol, uniquify=False, useChirality=False, maxMatches=10000)
    if not matches:
        return None

    ref_coord_list = [ref_coords[name] for name in ref_names]  # order == ref_mol atom order
    best_mapping, best_rmsd, second_best_rmsd = None, None, None
    for match in matches:
        # match[i] is the boltz_mol atom index matched to ref_mol atom i (ref_names[i]).
        query_coord_list = [boltz_atoms[boltz_names[qi]][1] for qi in match]
        rmsd = _kabsch_rmsd(ref_coord_list, query_coord_list)
        if best_rmsd is None or rmsd < best_rmsd:
            second_best_rmsd = best_rmsd
            best_rmsd = rmsd
            best_mapping = {boltz_names[qi]: ref_names[i] for i, qi in enumerate(match)}
        elif second_best_rmsd is None or rmsd < second_best_rmsd:
            second_best_rmsd = rmsd

    if len(matches) > 1:
        gap = (second_best_rmsd - best_rmsd) if second_best_rmsd is not None else float('inf')
        print(
            f"[rfd3 guided] ligand atom-name mapping: {len(matches)} candidate "
            f"isomorphisms, best RMSD={best_rmsd:.4f} vs next-best={second_best_rmsd:.4f} "
            f"(gap={gap:.4f}) -- a small gap means the tie-break may not be decisive"
        )

    return best_mapping


def _normalize_ligand_atom_names(pdb_path: str, params_path: str, base_json_path: str,
                                  out_pdb_path: str, ligand_chain_id: str = "B") -> bool:
    """Rewrites a resname-normalized guided PDB's ligand HETATM *atom* names
    (not just its residue name -- see _normalize_ligand_id) to match the
    canonical names read from params_path, via _infer_ligand_atom_mapping.
    Required because select_exposed/select_buried in the guided RFD3 spec are
    copied verbatim from the base spec and are keyed by those canonical
    names, but Boltz assigns its own arbitrary atom names during co-folding
    -- without this, RFD3's input validator rejects every guided run.

    Writes out_pdb_path (may be the same path as pdb_path) and returns True
    on success. Returns False (writing nothing) if no ligand residue is
    found, or no full atom-name mapping could be established, so the caller
    falls back to unguided diffusion instead of producing a guided spec RFD3
    will reject."""
    import gemmi
    st = gemmi.read_structure(pdb_path)

    target_res = _find_ligand_hetatm_residue(st, ligand_chain_id)
    if target_res is None:
        return False

    boltz_atoms = {
        atom.name: (atom.element.name, (atom.pos.x, atom.pos.y, atom.pos.z))
        for atom in target_res
    }
    reference_pdb_path = _resolve_reference_pdb_path(base_json_path)
    mapping = _infer_ligand_atom_mapping(boltz_atoms, params_path, reference_pdb_path)
    if mapping is None:
        return False

    for atom in target_res:
        atom.name = mapping[atom.name]
    st.write_pdb(out_pdb_path)
    return True


def _write_guided_rfd3_json(base_json_path: str, guided_pdb_path: str, partial_t: float,
                             out_json_path: str) -> bool:
    """Loads the base per-pipeline RFD3 InputSpecification JSON, copies its
    ligand/select_exposed/select_buried fields verbatim, drops 'length',
    replaces 'input' with guided_pdb_path, adds partial_t, and writes the
    result to out_json_path. Only 'input'/'partial_t' differ from the base
    file (besides the dropped 'length').

    'length' is dropped because RFD3's DesignInputSpecification validator
    rejects it outright when partial.input/partial_t (partial diffusion) are
    set -- length is inferred from the input structure in that mode. The
    base file's 'length' is only valid for from-scratch (non-partial)
    diffusion.

    Before writing, verifies every atom name referenced by select_exposed/
    select_buried is actually present in guided_pdb_path's ligand residue --
    fails safe (returns False, writes nothing) on a stale/mismatched base
    spec or an atom-mapping bug, rather than reproducing RFD3's
    ComponentValidationError in a new form. Returns True on success."""
    with open(base_json_path) as fh:
        base = json.load(fh)
    partial = dict(base.get('partial', {}))
    partial.pop('length', None)

    ligand_key = partial.get('ligand')
    expected_names = set()
    for field in ('select_exposed', 'select_buried'):
        names_csv = partial.get(field, {}).get(ligand_key, '')
        expected_names.update(name for name in names_csv.split(',') if name)
    present_names = set(_iter_ligand_atom_names(guided_pdb_path, ligand_key))
    if not expected_names <= present_names:
        return False

    partial['input']     = guided_pdb_path
    partial['partial_t'] = partial_t
    guided = dict(base)
    guided['partial'] = partial
    with open(out_json_path, 'w') as fh:
        json.dump(guided, fh, indent=4)
    return True


def _prepare_guided_rfd3_inputs(base_json_path: str, fold_pdb_path: str, ligand_resname: str,
                                 params_path: str, partial_t: float, taskdir: str):
    """Orchestrates _normalize_ligand_id + _normalize_ligand_atom_names +
    _write_guided_rfd3_json: writes {taskdir}/in/guided_scaffold.pdb and
    {taskdir}/in/guided_binder_design.json. Returns the guided JSON path, or
    None if any step failed (no ligand found in fold_pdb_path, no full
    atom-name mapping could be established, or the select_exposed/
    select_buried coverage check failed) -- callers should fall back to
    unguided diffusion in that case."""
    guided_pdb  = f"{taskdir}/in/guided_scaffold.pdb"
    guided_json = f"{taskdir}/in/guided_binder_design.json"
    if not _normalize_ligand_id(fold_pdb_path, ligand_resname, guided_pdb):
        return None
    if not _normalize_ligand_atom_names(guided_pdb, params_path, base_json_path, guided_pdb):
        return None
    if not _write_guided_rfd3_json(base_json_path, guided_pdb, partial_t, guided_json):
        return None
    return guided_json


class SmallMoleculeBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, configs=None, **kwargs):
        if configs is None:
            configs = {}

        # Legacy / bookkeeping attrs
        self.passes     = kwargs.get("passes",     1)
        self.step_id    = kwargs.get("step_id",    1)
        self.seq_rank   = kwargs.get("seq_rank",   0)
        self.num_seqs   = kwargs.get("num_seqs",   4)
        self.sub_order  = kwargs.get("sub_order",  0)
        self.max_passes = kwargs.get("max_passes", 1)
        self.mock       = kwargs.get("mock",       False)

        self.current_scores  = {}
        self.iter_seqs       = kwargs.get("iter_seqs",      {})
        self.previous_scores = kwargs.get("previous_score", {})

        super().__init__(name, flow, **configs, **kwargs)

        # Paths
        self.base_path    = kwargs.get("base_path", os.getcwd())
        self.scripts_path = kwargs.get(
            "scripts_path", os.path.join(self.base_path, "scripts")
        )
        # input_dir: explicit input directory name (relative to base_path) or
        # absolute path.  Falls back to "<name>_in" when not provided.
        _input_dir = kwargs.get("input_dir", "")
        if _input_dir and os.path.isabs(_input_dir):
            self.pipeline_inputs = _input_dir
        elif _input_dir:
            self.pipeline_inputs = os.path.join(self.base_path, _input_dir)
        else:
            self.pipeline_inputs = os.path.join(self.base_path, f"{self.name}_in")
        self.mpnn_dir        = kwargs.get("mpnn_dir") or os.environ.get("MPNN_DIR")
        if not self.mpnn_dir:
            raise ValueError("mpnn_dir must be supplied via kwarg or MPNN_DIR env var")

        # Configurable tool paths and ensemble sizes
        self.foundry_sif_path   = kwargs.get("foundry_sif_path") or os.environ.get("FOUNDRY_SIF_PATH")
        if not self.foundry_sif_path:
            raise ValueError("foundry_sif_path must be supplied via kwarg or FOUNDRY_SIF_PATH env var")
        self.boltz_cache_path   = kwargs.get("boltz_cache_path") or os.environ.get("BOLTZ_CACHE")
        if not self.boltz_cache_path:
            raise ValueError("boltz_cache_path must be supplied via kwarg or BOLTZ_CACHE env var")
        self.ligand_params      = kwargs.get("ligand_params",      "ALR.params")
        self.mpnn_ensemble_size = kwargs.get("mpnn_ensemble_size", 1)
        self.num_refine_cycles  = kwargs.get("num_refine_cycles",  3)
        self.diffusion_batch_size = kwargs.get("diffusion_batch_size", 2)
        self.rfd3_partial_t      = kwargs.get("rfd3_partial_t", 10.0)

        # Quality thresholds (overridable at construction time)
        self.backbone_max_ca_deviation = kwargs.get("backbone_max_ca_deviation", 2.0)
        self.backbone_min_ss_fraction  = kwargs.get("backbone_min_ss_fraction",  0.2)
        self.fastrelax_max_interact    = kwargs.get("fastrelax_max_interact",    0.0)
        self.fastrelax_max_total_score = kwargs.get("fastrelax_max_total_score", 0.0)
        self.fastrelax_max_fa_rep      = kwargs.get("fastrelax_max_fa_rep",      150.0)
        self.interface_min_sc          = kwargs.get("interface_min_sc",          0.5)
        self.fold_min_plddt            = kwargs.get("fold_min_plddt",            70.0)
        self.fold_min_ligand_iptm      = kwargs.get("fold_min_ligand_iptm",      None)
        self.max_tasks                 = kwargs.get("max_tasks",                 300)
        self.gpu_id                    = kwargs.get("gpu_id",                    None)

        # Output paths (legacy)
        self.output_path         = os.path.join(self.base_path, "myoutputs", self.name)
        self.output_path_packmin = os.path.join(self.output_path, "packmin")
        self.output_path_lmpnn   = os.path.join(self.output_path, "lmpnn")

        # Task tracking
        self.taskcount     = 0
        self.previous_task = "START"

        # State machine
        self.state            = {}   # written by analysis tasks, read by adaptive_fn
        self.next_step        = STEP_RFD3
        self._current_cycle_i = 0   # set by run() before each mpnn call

    def _gpu_env(self) -> dict:
        env = {**os.environ}
        if self.gpu_id is not None:
            env["CUDA_VISIBLE_DEVICES"] = str(self.gpu_id)
        return env

    # ── Task registration ──────────────────────────────────────────────────

    def register_pipeline_tasks(self):
        if self.mock:
            self._register_mock_tasks()
        else:
            self._register_real_tasks()

    # ── MOCK tasks ─────────────────────────────────────────────────────────

    def _register_mock_tasks(self):
        from mock import register_mock_tasks
        register_mock_tasks(self)

    # ── REAL tasks ─────────────────────────────────────────────────────────

    def _register_real_tasks(self):
        """Register real HPC tasks that return shell command strings."""
        @self.auto_register_task(capture_stdio=True)
        async def rfd3():
            self.taskcount += 1
            taskname = "rfd3"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.name}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            base_inputs = f"{self.pipeline_inputs}/ALR_binder_design.json"
            output_dir  = f"{taskdir}/out"

            fold_pdb = self.state.get('rfd3_input_pdb')
            inputs   = base_inputs
            if fold_pdb:
                params_path = f"{self.pipeline_inputs}/{self.ligand_params}"
                ligand_resname = _ligand_resname_from_params(params_path)
                guided_json = _prepare_guided_rfd3_inputs(
                    base_json_path=base_inputs,
                    fold_pdb_path=fold_pdb,
                    ligand_resname=ligand_resname,
                    params_path=params_path,
                    partial_t=self.rfd3_partial_t,
                    taskdir=taskdir,
                )
                if guided_json:
                    inputs = guided_json

            cmd = (
                f"bash {self.scripts_path}/rfd3.sh"
                f" {self.foundry_sif_path}"
                f" {output_dir}"
                f" {inputs}"
                f" {self.diffusion_batch_size}"
            )
            return cmd

        @self.auto_register_task(local_task=True)
        async def analysis_backbone():
            out_dir    = f"{self.base_path}/{self.name}/{self.taskcount}_rfd3/out"
            json_files = [
                f for f in os.listdir(out_dir)
                if f.endswith('.json') and '_model_' in f
            ]

            best = None
            for jf in json_files:
                with open(f"{out_dir}/{jf}") as fh:
                    data = json.load(fh)
                m = data.get('metrics', {})
                # RFD3's partial-diffusion (guided-backbone-feedback) mode never
                # computes ligand-clash or secondary-structure metrics -- the
                # 'n_clashing.ligand_clashes' key is absent entirely and
                # helix_fraction/sheet_fraction come back as literal JSON NaN
                # (so ss = NaN + NaN, and NaN > threshold is always False in
                # Python) -- only max_ca_deviation and the interresidue clash
                # counts are populated there. Unguided mode has all of these.
                guided = 'n_clashing.ligand_clashes' not in m
                if guided:
                    clashes = (
                        m.get('n_clashing.interresidue_clashes_w_sidechain', float('inf'))
                        + m.get('n_clashing.interresidue_clashes_w_backbone', float('inf'))
                    )
                else:
                    clashes = m.get('n_clashing.ligand_clashes', float('inf'))
                dev = m.get('max_ca_deviation', float('inf'))
                ss  = m.get('helix_fraction', 0) + m.get('sheet_fraction', 0)

                if best is None or clashes < best['clashes'] or (
                    clashes == best['clashes'] and dev < best['dev']
                ):
                    best = {'file': jf, 'clashes': clashes, 'dev': dev, 'ss': ss, 'guided': guided}

            if best is None:
                self.state.update({
                    'last_analysis_step':    'backbone',
                    'last_analysis_metrics': {'pass': False},
                })
                self.state['ensemble'].append((
                    ETYPE_BACKBONE, 0.0, self.state.get('rfd3_input_pdb'), None,
                ))
                return

            backbone_path = os.path.join(out_dir, best['file'].replace('.json', '.cif.gz'))
            self.state['best_backbone_path'] = backbone_path
            passed = (
                best['clashes'] == 0
                and best['dev'] < self.backbone_max_ca_deviation
                # SS fraction isn't computable in guided mode (see above) --
                # skip that check there rather than fail unconditionally.
                and (best['guided'] or best['ss'] > self.backbone_min_ss_fraction)
            )
            self.state.update({
                'last_analysis_step': 'backbone',
                'last_analysis_metrics': {
                    'pass':             passed,
                    'best_model':       best['file'],
                    'guided':           best['guided'],
                    'ligand_clashes':   best['clashes'],
                    'max_ca_deviation': best['dev'],
                    'ss_fraction':      best['ss'],
                },
            })
            self.state['ensemble'].append((
                ETYPE_BACKBONE, best['ss'], self.state.get('rfd3_input_pdb'), backbone_path,
            ))

        @self.auto_register_task(local_task=True)
        async def mpnn(
            fixed_residues_file: str | None = None):
            self.taskcount += 1
            taskname = "mpnn"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.name}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            cycle_i   = self._current_cycle_i
            pdb_path  = self.state['best_backbone_path'] if cycle_i == 0 else self.state['best_packed_pdb']
            n_batches = self.mpnn_ensemble_size if cycle_i == 0 else 1
            batch_size = self.num_seqs
            output_dir = f"{taskdir}/out"

            # Copy input to a short fixed name to prevent filename accumulation
            # across MPNN+packmin cycles (avoids 255-char limit in AF2 result zips)
            pdb_path_orig = pdb_path
            if pathlib.Path(pdb_path_orig).name.endswith('.cif.gz'):
                short_name = 'binder.cif.gz'
            else:
                short_name = f'binder{pathlib.Path(pdb_path_orig).suffix}'
            short_pdb = f"{taskdir}/in/{short_name}"
            shutil.copy(pdb_path_orig, short_pdb)
            pdb_path = short_pdb

            # LigandMPNN (ProDy parsePDB) only reads PDB format; convert CIF.GZ.
            if pdb_path.endswith('.cif.gz'):
                import gemmi as _gemmi
                pdb_for_mpnn = f"{taskdir}/in/binder.pdb"
                with gzip.open(pdb_path, 'rb') as _f:
                    _cif_data = _f.read().decode()
                _doc = _gemmi.cif.read_string(_cif_data)
                _st = _gemmi.make_structure_from_block(_doc.sole_block())
                _st.write_pdb(pdb_for_mpnn)
                pdb_path = pdb_for_mpnn

            if fixed_residues_file:
                with open(fixed_residues_file) as f:
                    fixed_residues = f.read().strip()
            else:
                fixed_residues = ""

            cmd = (
                f"bash {self.scripts_path}/mpnn.sh"
                f" {self.mpnn_dir}"
                f" {pdb_path}"
                f" {output_dir}"
                f" {n_batches}"
                f" {batch_size}"
                f' "{fixed_residues}"'
            )
            log_file = f"{taskdir}/mpnn.log"
            with open(log_file, "wb") as _lf:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=_lf,
                    stderr=asyncio.subprocess.STDOUT,
                    env=self._gpu_env(),
                )
                await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"mpnn failed with exit code {proc.returncode}\nSee {log_file}")

        @self.auto_register_task(local_task=True)
        async def analysis_sequence():
            out_dir  = f"{self.base_path}/{self.name}/{self.taskcount}_mpnn/out"
            seqs_dir = f"{out_dir}/seqs"
            self.state['last_mpnn_seqs_dir'] = seqs_dir
            self.state['last_analysis_step'] = 'sequence'

            best_conf     = -1.0
            best_lig_conf = 0.0
            best_id       = None
            best_seq      = None

            for fa_file in [f for f in os.listdir(seqs_dir) if f.endswith('.fa')]:
                with open(f"{seqs_dir}/{fa_file}") as fh:
                    content = fh.read()
                # LigandMPNN writes ONE file per input structure containing MULTIPLE
                # records: a template record (echo of the input, no 'id=' field)
                # followed by 'batch_size' real designed candidates ('id=1'..'id=N',
                # each with overall_confidence/ligand_confidence). Evaluate every
                # id= record across every file -- do not assume one candidate per file.
                for record in content.split('>')[1:]:
                    lines = record.splitlines()
                    if not lines:
                        continue
                    header, seq = lines[0], ''.join(lines[1:]).strip()
                    try:
                        parts = {
                            kv.split('=')[0].strip(): kv.split('=')[1].strip()
                            for kv in header.split(',')
                            if '=' in kv
                        }
                        if 'id' not in parts:
                            continue  # template record, not a real candidate
                        cand_id  = parts['id']
                        conf     = float(parts.get('overall_confidence', 0))
                        lig_conf = float(parts.get('ligand_confidence',  0))
                    except (ValueError, IndexError):
                        continue

                    if conf > best_conf:
                        best_conf     = conf
                        best_lig_conf = lig_conf
                        best_id       = cand_id
                        best_seq      = seq

            # Always update best_packed_pdb so packmin reads the current mpnn output
            if best_id is not None:
                self.state['best_packed_pdb'] = f"{out_dir}/packed/binder_packed_{best_id}_1.pdb"
                best_fasta_path = f"{seqs_dir}/best_candidate.fa"
                with open(best_fasta_path, 'w') as fh:
                    fh.write(f">binder_id_{best_id}\n{best_seq}\n")
                self.state['last_seq_fasta'] = best_fasta_path
            else:
                self.state['last_seq_fasta'] = None

            self.state['last_analysis_metrics'] = {
                'pass':                    True,
                'best_overall_confidence': best_conf,
                'best_ligand_confidence':  best_lig_conf,
            }
            self.state['ensemble'].append((
                ETYPE_SEQUENCE, best_conf,
                self.state.get('best_backbone_path'), self.state.get('last_seq_fasta'),
            ))

        @self.auto_register_task(local_task=True)
        async def packmin():
            self.taskcount += 1
            taskname = "packmin"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.name}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            pdb_path   = self.state['best_packed_pdb']
            pdb_stem   = pathlib.Path(pdb_path).stem
            output_dir = f"{taskdir}/out"
            lig_path   = f"{self.pipeline_inputs}/{self.ligand_params}"

            # Predict output path so the next mpnn can read from it
            self.state['best_packed_pdb'] = f"{output_dir}/{pdb_stem}_minimized.pdb"

            cmd = (
                f"bash {self.scripts_path}/packmin.sh"
                f" {pdb_path}"
                f" {lig_path}"
                f" {output_dir}"
            )
            log_file = f"{taskdir}/packmin.log"
            with open(log_file, "wb") as _lf:
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=_lf, stderr=asyncio.subprocess.STDOUT, env=self._gpu_env(),
                )
                await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"packmin failed with exit code {proc.returncode}\nSee {log_file}")

        @self.auto_register_task(local_task=True)
        async def analysis_packmin():
            out_dir     = f"{self.base_path}/{self.name}/{self.taskcount}_packmin/out"
            score_files = [f for f in os.listdir(out_dir) if f.endswith('_packmin_score.json')]

            total_score = None
            if score_files:
                with open(f"{out_dir}/{score_files[0]}") as fh:
                    total_score = json.load(fh).get('total_score')

            self.state['last_analysis_step']    = 'packmin'
            self.state['last_analysis_metrics'] = {'pass': True, 'total_score': total_score}

        @self.auto_register_task(local_task=True)
        async def fastrelax():
            self.taskcount += 1
            taskname = "fastrelax"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.name}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            pdb_path   = self.state['best_packed_pdb']
            lig_path   = f"{self.pipeline_inputs}/{self.ligand_params}"
            output_dir = f"{taskdir}/out"

            cmd = (
                f"bash {self.scripts_path}/fastrelax.sh"
                f" {pdb_path}"
                f" {lig_path}"
                f" {output_dir}"
            )
            log_file = f"{taskdir}/fastrelax.log"
            with open(log_file, "wb") as _lf:
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=_lf, stderr=asyncio.subprocess.STDOUT, env=self._gpu_env(),
                )
                await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"fastrelax failed with exit code {proc.returncode}\nSee {log_file}")

        @self.auto_register_task(local_task=True)
        async def analysis_fastrelax():
            out_dir    = f"{self.base_path}/{self.name}/{self.taskcount}_fastrelax/out"
            fasc_files = [f for f in os.listdir(out_dir) if f.endswith('.fasc')]

            total_score = fa_rep = rmsd = interact = None
            if fasc_files:
                with open(f"{out_dir}/{fasc_files[0]}") as fh:
                    data = json.load(fh)
                total_score = data.get('total_score')
                interact    = data.get('interaction_energy')
                fa_rep      = data.get('fa_rep')
                rmsd        = data.get('rmsd')

            passed = (
                interact      is not None and interact      < self.fastrelax_max_interact
                and total_score is not None and total_score < self.fastrelax_max_total_score
                and fa_rep     is not None and fa_rep       < self.fastrelax_max_fa_rep
            )
            self.state['last_analysis_step']    = 'fastrelax'
            self.state['last_analysis_metrics'] = {
                'pass':        passed,
                'total_score': total_score,
                'interact':    interact,
                'fa_rep':      fa_rep,
                'rmsd':        rmsd,
            }

        @self.auto_register_task(local_task=True)
        async def filter_shape(ligand_name: str = "ALR"):
            taskname = "filter_shape"
            taskdir  = f"{self.base_path}/{self.name}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            pdb_directory = f"{self.base_path}/{self.name}/{self.taskcount}_fastrelax/out"

            cmd = (
                f"bash {self.scripts_path}/filter_shape.sh"
                f" {pdb_directory}"
                f" {taskdir}/out/shape_complementarity_values.txt"
                f" {self.pipeline_inputs}/{ligand_name}"
                f" {taskdir}/out/interface_values.txt"
            )
            log_file = f"{taskdir}/filter_shape.log"
            with open(log_file, "wb") as _lf:
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=_lf, stderr=asyncio.subprocess.STDOUT, env=self._gpu_env(),
                )
                await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"filter_shape failed with exit code {proc.returncode}\nSee {log_file}")

        @self.auto_register_task(local_task=True)
        async def analysis_interface():
            sc_file = (
                f"{self.base_path}/{self.name}/{self.taskcount}_filter_shape/out/"
                "shape_complementarity_values.txt"
            )
            max_sc = 0.0
            try:
                with open(sc_file) as fh:
                    for line in fh:
                        parts = line.strip().split('\t')
                        if len(parts) >= 2:
                            try:
                                max_sc = max(max_sc, float(parts[1].split(': ')[-1]))
                            except ValueError:
                                pass
            except FileNotFoundError:
                pass

            self.state['last_analysis_step']    = 'interface'
            self.state['last_analysis_metrics'] = {
                'pass':   max_sc >= self.interface_min_sc,
                'max_sc': max_sc,
            }

        @self.auto_register_task(capture_stdio=True)
        async def boltz():
            self.taskcount += 1
            taskname = "boltz"
            self.previous_task = taskname
            taskdir    = f"{self.base_path}/{self.name}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            seq = _read_fasta_seq(self.state['last_seq_fasta'])
            if not seq:
                raise RuntimeError(f"boltz: no usable sequence in {self.state['last_seq_fasta']}")

            ligand_stem = pathlib.Path(self.ligand_params).stem
            with open(f"{self.pipeline_inputs}/{ligand_stem}.smiles") as fh:
                ligand_smiles = fh.read().strip()

            yaml_path = f"{taskdir}/in/boltz_input.yaml"
            with open(yaml_path, "w") as fh:
                fh.write(
                    "version: 1\nsequences:\n  - protein:\n      id: [A]\n"
                    f"      sequence: {seq}\n      msa: empty\n"
                    "  - ligand:\n      id: [B]\n"
                    f"      smiles: '{ligand_smiles}'\n"
                )

            output_dir = f"{taskdir}/out"
            cmd = (
                f"bash {self.scripts_path}/boltz.sh"
                f" {yaml_path}"
                f" {output_dir}"
                f" {self.boltz_cache_path}"
            )
            return cmd

        @self.auto_register_task(local_task=True)
        async def analysis_fold():
            # Boltz nests its own output under out_dir/boltz_results_<yaml_stem>/
            # (see boltz/main.py: `out_dir = out_dir / f"boltz_results_{data.stem}"`)
            # before the documented predictions/<record_id>/ layout -- confirmed
            # empirically against a real `boltz predict` run, not just the docs.
            pred_dir = (
                f"{self.base_path}/{self.name}/{self.taskcount}_boltz/out/"
                "boltz_results_boltz_input/predictions/boltz_input"
            )
            conf_files = [
                f for f in os.listdir(pred_dir)
                if f.startswith('confidence_') and f.endswith('.json')
            ] if os.path.isdir(pred_dir) else []

            if not conf_files:
                raise RuntimeError(
                    f"boltz produced no confidence files in {pred_dir} — "
                    "GPU/predict failure"
                )

            best_complex_plddt = -1.0
            best_model         = None
            best_ligand_iptm   = None
            for cf in conf_files:
                with open(f"{pred_dir}/{cf}") as fh:
                    data = json.load(fh)
                score = data.get('complex_plddt', 0.0)
                if score > best_complex_plddt:
                    best_complex_plddt = score
                    best_model         = cf.replace('confidence_', '', 1).replace('.json', '.pdb')
                    best_ligand_iptm   = data.get('ligand_iptm')

            # Rescale 0-1 -> 0-100 to preserve fold_min_plddt's existing semantics.
            best_plddt_100 = best_complex_plddt * 100.0
            passed = best_plddt_100 >= self.fold_min_plddt
            if self.fold_min_ligand_iptm is not None:
                passed = passed and (
                    best_ligand_iptm is not None
                    and best_ligand_iptm >= self.fold_min_ligand_iptm
                )

            if best_model:
                full_model_path = f"{pred_dir}/{best_model}"
                self.state['best_fold_model'] = full_model_path
                self.state['ensemble'].append((
                    ETYPE_FOLD, best_plddt_100, self.state.get('last_seq_fasta'), full_model_path,
                ))

            self.state['last_analysis_step']    = 'fold'
            self.state['last_analysis_metrics'] = {
                'pass':               passed,
                'best_complex_plddt': best_plddt_100,
                'best_ligand_iptm':   best_ligand_iptm,
                'best_model':         best_model,
            }

        @self.auto_register_task(local_task=True)
        async def filter_energy(ligand_name: str = "ALR"):
            taskname = "filter_energy"
            taskdir  = f"{self.base_path}/{self.name}/{self.taskcount}_{taskname}"
            os.makedirs(f"{taskdir}/in",  exist_ok=True)
            os.makedirs(f"{taskdir}/out", exist_ok=True)

            pdb_directory         = f"{self.base_path}/{self.name}/{self.taskcount}_fastrelax/out"
            outputs_dir           = f"{taskdir}/out"
            output_file           = f"{outputs_dir}/negative_ligand_filenames.txt"
            output_energy_file    = f"{outputs_dir}/negative_ligand_energies.txt"
            common_filenames_file = f"{self.pipeline_inputs}/common_filenames.txt"

            cmd = (
                f"bash {self.scripts_path}/filter_energy.sh"
                f" {pdb_directory}"
                f" {output_file}"
                f" {output_energy_file}"
                f" {common_filenames_file}"
                f" {ligand_name}"
            )
            log_file = f"{taskdir}/filter_energy.log"
            with open(log_file, "wb") as _lf:
                proc = await asyncio.create_subprocess_shell(
                    cmd, stdout=_lf, stderr=asyncio.subprocess.STDOUT, env=self._gpu_env(),
                )
                await proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"filter_energy failed with exit code {proc.returncode}\nSee {log_file}")

    # ── Score utils ────────────────────────────────────────────────────────

    async def get_scores_map(self):
        return {"c_scores": self.current_scores, "p_scores": self.previous_scores}

    def finalize(self, sub_iter_seqs=None):
        self.previous_scores = copy.deepcopy(self.current_scores)

    # ── Inner refinement cycle ─────────────────────────────────────────────

    async def _run_refine_cycle(self):
        """MPNN + PackMin refinement cycle with per-cycle sequence retry support."""
        for cycle_i in range(self.num_refine_cycles):
            self._current_cycle_i = cycle_i

            while True:  # sequence retry loop — exited by STEP_MPNN (pass) or non-STEP_RETRY_SEQ
                if len(self.state.get('ensemble', [])) >= self.max_tasks:
                    self.logger.pipeline_log(
                        f"Task budget exhausted ({self.max_tasks} ensemble entries). Stopping."
                    )
                    self.next_step = STEP_DONE
                    return

                self.logger.pipeline_log(f"running mpnn [cycle {cycle_i}]")
                await self.mpnn()
                self.logger.pipeline_log(f"mpnn [cycle {cycle_i}] finished")
                await self.analysis_sequence()
                await self.run_adaptive_step()

                if self.next_step == STEP_MPNN:
                    break                  # ensemble check passed — continue to packmin
                elif self.next_step == STEP_RETRY_SEQ:
                    continue               # ensemble check failed — retry mpnn same cycle
                else:
                    return                 # STEP_RFD3 (retry exhausted) or STEP_FASTRELAX

            if cycle_i < self.num_refine_cycles - 1:
                if len(self.state.get('ensemble', [])) >= self.max_tasks:
                    self.logger.pipeline_log(
                        f"Task budget exhausted ({self.max_tasks} ensemble entries). Stopping."
                    )
                    self.next_step = STEP_DONE
                    return
                self.logger.pipeline_log(f"running packmin [cycle {cycle_i}]")
                await self.packmin()
                self.logger.pipeline_log(f"packmin [cycle {cycle_i}] finished")
                await self.analysis_packmin()
                await self.run_adaptive_step()
                if self.next_step != STEP_MPNN:
                    return

        # Natural completion — outer run() auto-advances to STEP_FASTRELAX

    # ── Main state-machine run loop ────────────────────────────────────────

    async def run(self):
        self.next_step = STEP_RFD3
        self.state.setdefault('ensemble', [])
        self.state.setdefault('rfd3_input_pdb', None)
        self.state.setdefault('seq_retry_count', 0)
        self.state.setdefault('last_seq_fasta', None)
        self.state.setdefault('fastrelax_prev_metrics', None)
        self.state.setdefault('interface_prev_metrics', None)
        self.state.setdefault('backbone_guided_fail_count', 0)
        self.logger.pipeline_log("SmallMoleculeBindingPipeline starting (state machine)")

        while self.next_step != STEP_DONE:
            if len(self.state['ensemble']) >= self.max_tasks:
                self.logger.pipeline_log(
                    f"Task budget exhausted ({self.max_tasks} ensemble entries). Stopping."
                )
                break


            if self.next_step == STEP_RFD3:
                self.logger.pipeline_log("running rfd3")
                await self.rfd3()
                self.logger.pipeline_log("rfd3 finished")
                await self.analysis_backbone()
                await self.run_adaptive_step()

            elif self.next_step == STEP_MPNN:
                await self._run_refine_cycle()
                if self.next_step == STEP_MPNN:
                    # All cycles completed normally — advance to fastrelax
                    self.next_step = STEP_FASTRELAX

            elif self.next_step == STEP_FASTRELAX:
                self.logger.pipeline_log("running fastrelax")
                await self.fastrelax()
                self.logger.pipeline_log("fastrelax finished")
                await self.analysis_fastrelax()
                await self.run_adaptive_step()

            elif self.next_step == STEP_INTERFACE:
                self.logger.pipeline_log("running filter_shape")
                await self.filter_shape()
                self.logger.pipeline_log("filter_shape finished")
                await self.analysis_interface()
                await self.run_adaptive_step()

            elif self.next_step == STEP_AF2:
                self.logger.pipeline_log("running boltz")
                await self.boltz()
                self.logger.pipeline_log("boltz finished")
                await self.analysis_fold()
                await self.run_adaptive_step()

            else:
                self.logger.pipeline_log(f"Unknown next_step={self.next_step}, stopping")
                break

        self.logger.pipeline_log("Pipeline complete")
