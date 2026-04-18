#!/usr/bin/env python3
"""
parse_partial_diffusion.py

Produce a partial-diffusion RFDiffusion input JSON for models that failed
the RMSD threshold after fold prediction.

Usage:
    python parse_partial_diffusion.py \
        --best_fold      best_fold.json \
        --rfd_input      original_rfd_input.json \
        --rmsd_threshold 1.5 \
        --output         partial.json

Inputs:
    best_fold.json   — dict of {model_name: {motif_rmsd, run_dir, seed}}
                       produced by check_fold_results(); run_dir values are
                       absolute paths to the best Chai prediction directory.
    rfd_input.json   — RFDiffusion input spec (top-level keys are model names).
    rmsd_threshold   — models with motif_rmsd >= this value are failing.

Output:
    partial.json     — filtered RFDiffusion input spec for failing models, with
                       "input" set to the best predicted structure directory and
                       "partial_t" added for partial diffusion conditioning.
"""

import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--best_fold',      required=True,
                        help='Path to best_fold.json')
    parser.add_argument('--rfd_input',      required=True,
                        help='Path to the RFDiffusion input JSON')
    parser.add_argument('--rmsd_threshold', type=float, required=True,
                        help='RMSD threshold; models at or above this value are failing')
    parser.add_argument('--output',         required=True,
                        help='Output path for partial.json')
    args = parser.parse_args()

    with open(args.best_fold) as fh:
        best_fold = json.load(fh)

    failing_models = [
        m for m, v in best_fold.items()
        if v['motif_rmsd'] >= args.rmsd_threshold
    ]

    with open(args.rfd_input) as fh:
        rfd_input = json.load(fh)

    partial_input = {}
    for model in failing_models:
        if model not in rfd_input:
            continue
        entry = dict(rfd_input[model])
        entry['input']     = best_fold[model]['run_dir']   # already absolute
        entry['partial_t'] = 10
        partial_input[model] = entry

    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as fh:
        json.dump(partial_input, fh, indent=2)

    print(
        f"Wrote partial diffusion spec for {len(partial_input)} model(s) "
        f"to {output_path}"
    )


if __name__ == '__main__':
    main()
