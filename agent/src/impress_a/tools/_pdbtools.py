"""Small, dependency-light PDB helpers shared by the real (non-mock) task agents.

Deliberately lazy-imports Biopython/gemmi INSIDE each function, not at module scope, so
`Registry.load()` and `Validator.dry_run()` work in a dev venv that has neither installed
(see `docs/reference/authoring-tools.md`'s spirit: loading must not require the heavy
science stack).
"""
from __future__ import annotations

from pathlib import Path

# Rough Ramachandran boxes for a DSSP-free approximation. Real DSSP/STRIDE is more
# accurate; this exists so `has_secondary_structure` can be evaluated without requiring
# the `mkdssp` binary to be present on the cluster.
_ALPHA_HELIX = (-100.0, -30.0, -67.0, -7.0)     # phi_lo, phi_hi, psi_lo, psi_hi
_BETA_SHEET = (-180.0, -45.0, 90.0, 180.0)


def secondary_structure_fraction(pdb_path: str | Path) -> float:
    """Fraction of residues whose (phi, psi) fall in a helix or sheet Ramachandran
    region. An approximation, not a DSSP replacement - see the rfd3 toolkit's Pitfalls."""
    from Bio.PDB import PDBParser, PPBuilder

    structure = PDBParser(QUIET=True).get_structure("m", str(pdb_path))
    total = ordered = 0
    for model in structure:
        for chain in model:
            for pp in PPBuilder().build_peptides(chain):
                for phi, psi in pp.get_phi_psi_list():
                    if phi is None or psi is None:
                        continue
                    import math
                    phi_d, psi_d = math.degrees(phi), math.degrees(psi)
                    total += 1
                    if (_ALPHA_HELIX[0] <= phi_d <= _ALPHA_HELIX[1]
                            and _ALPHA_HELIX[2] <= psi_d <= _ALPHA_HELIX[3]):
                        ordered += 1
                    elif (_BETA_SHEET[0] <= phi_d <= _BETA_SHEET[1]
                          and (psi_d >= _BETA_SHEET[2] or psi_d <= -165.0)):
                        ordered += 1
        break  # first model only
    return round(ordered / total, 3) if total else 0.0


def cif_gz_to_pdb(cif_gz_path: str | Path, out_pdb_path: str | Path) -> None:
    """RFD3 emits `.cif.gz`; downstream tools (LigandMPNN) want PDB. Mirrors the old
    IMPRESS `cif_to_pdb.py` conversion using gemmi."""
    import gzip

    import gemmi

    with gzip.open(str(cif_gz_path), "rt") as fh:
        text = fh.read()
    doc = gemmi.cif.read_string(text)
    block = doc.sole_block()
    st = gemmi.make_structure_from_block(block)
    st.setup_entities()
    st.write_pdb(str(out_pdb_path))
