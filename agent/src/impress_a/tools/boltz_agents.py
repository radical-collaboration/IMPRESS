"""Boltz-2 task agent - independent protein+ligand co-folding confirmation.

Adapted from `IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s
`boltz()` step: extracts the sequence from the Rosetta-refined structure, writes a Boltz
YAML spec (protein sequence + ligand SMILES), and calls `boltz predict`.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .agent import TaskAgent, TaskRequest
from ._subprocess import first_dep_output, run_cmd

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


class BoltzPredictAgent(TaskAgent):
    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        cache = os.environ.get("BOLTZ_CACHE")
        if not cache:
            raise RuntimeError("BOLTZ_CACHE is not set - see scripts/delta_env_setup.sh")

        structure = first_dep_output(req.inputs, "structure")
        if not structure:
            raise RuntimeError("boltz_predict: no upstream 'structure' output found")
        sequence = _extract_sequence(structure)

        work = Path(tempfile.mkdtemp(prefix=f"boltz_{req.node_id or 'node'}_"))
        seqs: list[str] = [f"  - protein:\n      id: [A]\n      sequence: {sequence}\n"
                            f"        msa: {'auto' if params['use_msa_server'] else 'empty'}"]
        if params["ligand_smiles"]:
            seqs.append(f"  - ligand:\n      id: [B]\n      smiles: '{params['ligand_smiles']}'")
        spec_path = work / "boltz_input.yaml"
        spec_path.write_text("version: 1\nsequences:\n" + "\n".join(seqs) + "\n")

        cmd = [
            "boltz", "predict", str(spec_path),
            "--out_dir", str(work / "out"),
            "--cache", cache,
            "--devices", "1", "--accelerator", "gpu",
            "--diffusion_samples", str(params["diffusion_samples"]),
            "--output_format", "pdb",
        ]
        if params["use_msa_server"]:
            cmd.append("--use_msa_server")
        await run_cmd(cmd, timeout_s=float(self.spec.resources.walltime_s))

        confidence_files = sorted((work / "out").glob("**/confidence_*.json"))
        pdb_files = sorted((work / "out").glob("**/*.pdb"))
        if not confidence_files or not pdb_files:
            return {"result": None, "count": 0, "outputs": {}, "metrics": {}}

        conf = json.loads(confidence_files[0].read_text())
        return {
            "result": "complex",
            "count": len(pdb_files),
            "outputs": {"complex": str(pdb_files[0])},
            "metrics": {
                "complex_plddt": round(conf.get("complex_plddt", 0.0), 3),
                "ligand_iptm": round(conf.get("ligand_iptm", conf.get("iptm", 0.0)), 3),
            },
        }
