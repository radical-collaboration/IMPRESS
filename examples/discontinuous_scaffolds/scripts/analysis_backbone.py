#!/usr/bin/env python3
"""Parse RFD3 backbone metrics for a campaign analysis."""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

# Filename stem pattern: {example_id}_model_{rfd3_model_idx}
FILE_PATTERN = re.compile(r"^(?P<example_id>.+)_model_(?P<rfd3_model_idx>\d+)$")

FIELDNAMES = [
    "run_dir",
    "experiment",
    "rfd3_model_idx",
    "model_name",
    "max_ca_deviation",
    "n_chainbreaks",
    "n_clashing.interresidue_clashes_w_sidechain",
    "n_clashing.interresidue_clashes_w_backbone",
    "n_clashing.ligand_clashes",
    "n_clashing.ligand_min_distance",
    "non_loop_fraction",
    "loop_fraction",
    "helix_fraction",
    "sheet_fraction",
    "num_ss_elements",
    "radius_of_gyration",
    "alanine_content",
    "glycine_content",
    "num_residues",
    "diffused_com",
    "fixed_com",
]

_SCALAR_METRIC_FIELDS = [f for f in FIELDNAMES if f not in (
    "run_dir", "experiment", "rfd3_model_idx", "model_name", "diffused_com", "fixed_com"
)]

# Path to motif JSON relative to this script
_SCRIPT_DIR = Path(__file__).parent
MOTIF_JSON_PATH = _SCRIPT_DIR / "mcsa_41_rfd3.json"


def load_motif_data(json_path: Path) -> dict:
    with open(json_path) as f:
        return json.load(f)


def find_model_name(experiment: str, motif_data: dict) -> str | None:
    """Return the JSON key that is a substring of experiment, or None."""
    for key in motif_data:
        if key in experiment:
            return key
    return None


def iter_rows(input_dir: Path, motif_data: dict):
    outputs_rfd3 = input_dir / "outputs_rfd3"
    if not outputs_rfd3.is_dir():
        print(f"Warning: outputs_rfd3 not found in {input_dir}", file=sys.stderr)
        print(f"Defaulting to current dir.")
        outputs_rfd3 = input_dir
#        return

    for json_path in sorted(outputs_rfd3.glob("*.json")):
        m = FILE_PATTERN.match(json_path.stem)
        if not m:
            print(
                f"Warning: skipping {json_path.name}: unrecognized filename pattern",
                file=sys.stderr,
            )
            continue

        rfd3_model_idx = int(m.group("rfd3_model_idx"))

        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: failed to read {json_path}: {e}", file=sys.stderr)
            continue

        try:
            experiment = data["specification"]["extra"]["example_id"]
        except KeyError:
            experiment = m.group("example_id")

        model_name = find_model_name(experiment, motif_data) or ""
        metrics = data.get("metrics", {})

        yield {
            "run_dir": input_dir.name,
            "experiment": experiment,
            "rfd3_model_idx": rfd3_model_idx,
            "model_name": model_name,
            **{k: metrics.get(k, "") for k in _SCALAR_METRIC_FIELDS},
            "diffused_com": json.dumps(metrics.get("diffused_com")),
            "fixed_com": json.dumps(metrics.get("fixed_com")),
        }


def main():
    parser = argparse.ArgumentParser(
        description="Parse RFD3 backbone metrics for campaign analysis."
    )
    parser.add_argument(
        "input_dirs",
        nargs="+",
        type=Path,
        help="Campaign directories, each expected to contain an outputs_rfd3/ subdir.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./campaign_analysis_backbone.csv"),
        help="Output CSV path (default: ./campaign_analysis_backbone.csv)",
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
