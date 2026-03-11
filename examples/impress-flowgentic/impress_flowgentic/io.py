from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_pipeline_layout(base_path: Path, pipeline_name: str, max_passes: int) -> None:
    output_root = base_path / "af_pipeline_outputs_multi" / pipeline_name
    input_dir = base_path / f"{pipeline_name}_in"

    subdirs = [
        "af/fasta",
        "af/prediction",
        "af/prediction/best_models",
        "af/prediction/best_ptm",
        "af/prediction/dimer_models",
        "af/prediction/logs",
        "mpnn",
    ]

    paths = [input_dir, output_root]
    paths.extend(output_root / subdir for subdir in subdirs)
    for job_index in range(1, max_passes + 2):
        paths.append(output_root / f"mpnn/job_{job_index}")
        paths.append(output_root / f"mpnn/job_{job_index}/seqs")

    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def seed_initial_inputs(
    base_path: Path,
    pipeline_name: str,
    protein_ids: list[str],
    max_passes: int,
) -> None:
    ensure_pipeline_layout(base_path=base_path, pipeline_name=pipeline_name, max_passes=max_passes)

    input_dir = base_path / f"{pipeline_name}_in"
    for protein in protein_ids:
        pdb_path = input_dir / f"{protein}.pdb"
        if pdb_path.exists():
            continue

        pdb_content = (
            "HEADER    MOCK PDB FOR FLOWGENTIC IMPRESS\n"
            f"TITLE     {protein}\n"
            "ATOM      1  N   ALA A   1      11.104  13.207  10.947  1.00 80.00           N\n"
            "ATOM      2  CA  ALA A   1      12.560  13.282  10.721  1.00 80.00           C\n"
            "TER\n"
            "END\n"
        )
        pdb_path.write_text(pdb_content, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Ensemble store
# ---------------------------------------------------------------------------

def ensure_ensemble_store(base_path: Path, pipeline_name: str) -> Path:
    """Create the ensemble directory and return the path to the pipeline's JSONL store."""
    store_dir = base_path / "ensemble"
    store_dir.mkdir(parents=True, exist_ok=True)
    return store_dir / f"{pipeline_name}_records.jsonl"


def append_ensemble_records(store_path: Path, records: list[dict[str, Any]]) -> None:
    """Append ensemble records to the pipeline's JSONL file (one JSON object per line)."""
    with store_path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def load_ensemble(store_path: Path) -> list[dict[str, Any]]:
    """Load all ensemble records from a pipeline's JSONL store."""
    try:
        with store_path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []
