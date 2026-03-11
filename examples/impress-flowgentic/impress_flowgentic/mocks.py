from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import random
import shutil
from pathlib import Path

from .state import SequenceScore

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
PEPTIDE_SEQUENCE = "EGYQDYEPEA"


def stable_hash(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16)


def _build_sequence(seed: str, length: int) -> str:
    values = []
    for idx in range(length):
        aa_index = stable_hash(f"{seed}-{idx}") % len(AMINO_ACIDS)
        values.append(AMINO_ACIDS[aa_index])
    return "".join(values)


def generate_mock_backbone(target: str, pass_index: int) -> str:
    """Return a deterministic backbone structure reference identifier (stub)."""
    seed = stable_hash(f"{target}-{pass_index}-backbone") % (2**32)
    rng = random.Random(seed)
    return f"backbone_{target}_pass{pass_index}_{rng.randint(1000, 9999)}"


def generate_mock_sequences(target: str, pass_index: int, num_seqs: int) -> list[SequenceScore]:
    seqs: list[SequenceScore] = []
    length = 95 + pass_index * 2
    base = 0.75 + (stable_hash(target) % 20) / 100.0

    for rank in range(num_seqs):
        sequence = _build_sequence(seed=f"{target}-{pass_index}-{rank}", length=length)
        score = round(base + rank * 0.08 + pass_index * 0.02, 4)
        seqs.append(SequenceScore(sequence=sequence, score=score))

    seqs.sort(key=lambda item: item.score)
    return seqs


def write_mpnn_sequences_file(file_path: Path, sequences: list[SequenceScore]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)

    rows = ["# mock mpnn output", "# sequence candidates"]
    for idx, seq in enumerate(sequences):
        rows.append(f">seq_{idx}, sample, score={seq.score}")
        rows.append(seq.sequence)

    file_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def parse_mpnn_sequences(job_seqs_dir: Path) -> dict[str, list[SequenceScore]]:
    parsed: dict[str, list[SequenceScore]] = {}

    for file_path in sorted(job_seqs_dir.glob("*.fa")):
        entries: list[SequenceScore] = []
        lines = file_path.read_text(encoding="utf-8").splitlines()[2:]

        score: float | None = None
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                score_text = line.split(",")[2].replace(" score=", "").strip()
                score = float(score_text)
            else:
                entries.append(SequenceScore(sequence=line, score=score if score is not None else 999.0))

        entries.sort(key=lambda item: item.score)
        parsed[file_path.stem] = entries

    return parsed


async def write_mock_alphafold_for_target(
    *,
    target: str,
    pass_index: int,
    sequence: str,
    output_path: Path,
    output_path_mpnn: Path,
) -> None:
    await asyncio.sleep(0.03)

    dimer_target_dir = output_path / "af/prediction/dimer_models" / target
    dimer_target_dir.mkdir(parents=True, exist_ok=True)

    rank_label = f"model_{pass_index}"
    ranked_pdb = dimer_target_dir / f"{target}_ranked_0_{rank_label}.pdb"
    ranking_json = dimer_target_dir / f"{target}_ranking_debug.json"

    ranked_pdb.write_text(
        "\n".join(
            [
                "HEADER    MOCK ALPHAFOLD OUTPUT",
                f"TITLE     {target} PASS {pass_index}",
                f"REMARK    DESIGN_SEQ {sequence[:40]}",
                "ATOM      1  N   GLY A   1      11.104  13.207  10.947  1.00 84.00           N",
                "ATOM      2  CA  GLY A   1      12.560  13.282  10.721  1.00 84.00           C",
                "TER",
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ranking_json.write_text(
        json.dumps({"iptm+ptm": {rank_label: round(0.55 + pass_index * 0.05, 3)}, "order": [rank_label]}, indent=2),
        encoding="utf-8",
    )

    best_model = output_path / "af/prediction/best_models" / f"{target}.pdb"
    best_ptm = output_path / "af/prediction/best_ptm" / f"{target}.json"
    mpnn_pdb = output_path_mpnn / f"job_{pass_index}" / f"{target}.pdb"

    best_model.parent.mkdir(parents=True, exist_ok=True)
    best_ptm.parent.mkdir(parents=True, exist_ok=True)
    mpnn_pdb.parent.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(ranked_pdb, best_model)
    shutil.copyfile(ranking_json, best_ptm)
    shutil.copyfile(ranked_pdb, mpnn_pdb)


def compute_mock_metrics(
    targets: list[str],
    pass_index: int,
    pipeline_name: str,
) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}

    for target in targets:
        target_hash = stable_hash(target)
        base_pae = 8.2 + (target_hash % 25) / 100.0

        if "_sub" in pipeline_name:
            trend = -0.16 * (pass_index - 1)
        else:
            degrade_fast = target_hash % 2 == 0
            trend = (0.24 if degrade_fast else 0.03) * (pass_index - 1)

        avg_pae = round(base_pae + trend, 4)
        avg_plddt = round(88.0 - avg_pae * 1.2, 4)
        ptm = round(0.9 - avg_pae / 25.0, 4)

        metrics[target] = {
            "avg_plddt": avg_plddt,
            "ptm": ptm,
            "avg_pae": avg_pae,
        }

    return metrics


def write_score_csv(csv_path: Path, metrics: dict[str, dict[str, float]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ID", "avg_plddt", "ptm", "avg_pae"])
        for target in sorted(metrics.keys()):
            row = metrics[target]
            writer.writerow([f"{target}.pdb", row["avg_plddt"], row["ptm"], row["avg_pae"]])
