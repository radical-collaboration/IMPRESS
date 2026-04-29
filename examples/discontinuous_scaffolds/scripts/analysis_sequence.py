#!/usr/bin/env python3
"""Parse LigandMPNN per-sequence metrics for a campaign analysis."""

import argparse
import csv
import re
import sys
from pathlib import Path

# Filename stem pattern: {example_id}_model_{rfd3_model_idx}-{seq_id}
FILE_PATTERN = re.compile(
    r"^(?P<example_id>.+)_model_(?P<rfd3_model_idx>\d+)-(?P<seq_id>\d+)$"
)

FIELDNAMES = [
    "run_dir",
    "experiment",
    "rfd3_model_idx",
    "seq_id",
    "seed",
    "model_name",
    "T",
    "overall_confidence",
    "ligand_confidence",
    "seq_rec",
]

# Path to motif JSON relative to this script
_SCRIPT_DIR = Path(__file__).parent
MOTIF_JSON_PATH = _SCRIPT_DIR / "mcsa_41_rfd3.json"


def load_motif_data(json_path):
    import json
    with open(json_path) as f:
        return json.load(f)


def find_model_name(experiment: str, motif_data: dict) -> str | None:
    """Return the JSON key that is a substring of experiment, or None."""
    for key in motif_data:
        if key in experiment:
            return key
    return None


def _parse_header(header_line: str) -> dict:
    """Parse FA header (with leading '>' already stripped) into a dict."""
    tokens = header_line.split(", ")
    kv = {}
    for token in tokens[1:]:
        if "=" in token:
            k, v = token.split("=", 1)
            kv[k] = v
    return kv


def iter_rows(input_dir: Path, motif_data: dict):
    seqs_split = input_dir / "outputs_lmpnn" / "seqs_split"
    if not seqs_split.is_dir():
        print(
            f"Warning: outputs_lmpnn/seqs_split not found in {input_dir}",
            file=sys.stderr,
        )
        print(f"Defaulting to current dir.")
        seqs_split = input_dir
#        return

    for fa_path in sorted(seqs_split.glob("*.fa")):
        m = FILE_PATTERN.match(fa_path.stem)
        if not m:
            print(
                f"Warning: skipping {fa_path.name}: unrecognized filename pattern",
                file=sys.stderr,
            )
            continue

        example_id = m.group("example_id")
        rfd3_model_idx = int(m.group("rfd3_model_idx"))
        seq_id = int(m.group("seq_id"))
        experiment = example_id
        model_name = find_model_name(experiment, motif_data) or ""

        try:
            lines = fa_path.read_text().splitlines()
        except OSError as e:
            print(f"Warning: failed to read {fa_path}: {e}", file=sys.stderr)
            continue

        if not lines or not lines[0].startswith(">"):
            print(f"Warning: unexpected FA format in {fa_path.name}", file=sys.stderr)
            continue

        kv = _parse_header(lines[0][1:])

        def get_float(key):
            try:
                return float(kv[key])
            except (KeyError, ValueError):
                return ""

        def get_int(key):
            try:
                return int(kv[key])
            except (KeyError, ValueError):
                return ""

        yield {
            "run_dir": input_dir.name,
            "experiment": experiment,
            "rfd3_model_idx": rfd3_model_idx,
            "seq_id": seq_id,
            "seed": get_int("seed"),
            "model_name": model_name,
            "T": get_float("T"),
            "overall_confidence": get_float("overall_confidence"),
            "ligand_confidence": get_float("ligand_confidence"),
            "seq_rec": get_float("seq_rec"),
        }


def main():
    parser = argparse.ArgumentParser(
        description="Parse LigandMPNN per-sequence metrics for campaign analysis."
    )
    parser.add_argument(
        "input_dirs",
        nargs="+",
        type=Path,
        help="Campaign directories, each expected to contain an outputs_lmpnn/seqs_split/ subdir.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./campaign_analysis_sequence.csv"),
        help="Output CSV path (default: ./campaign_analysis_sequence.csv)",
    )
    args = parser.parse_args()

    motif_data = load_motif_data(MOTIF_JSON_PATH)

    rows = []
    for input_dir in args.input_dirs:
        dir_rows = list(iter_rows(input_dir, motif_data))
        if not dir_rows:
            print(f"Warning: no rows from {input_dir}", file=sys.stderr)
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
