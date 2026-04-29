#!/usr/bin/env python3
"""Split mcsa_41_rfd3.json into chunks and generate LigandMPNN batch input JSONs.

Outputs per chunk i (1-indexed):
  mcsa_mod{chunk_size}-{i}.json
  batch_pdbs_mod{chunk_size}-{i}.json
  batch_fixed_res_mod{chunk_size}-{i}.json
"""

import argparse
import json
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", default="./mcsa_41_rfd3.json",
                   help="Source model config JSON (default: %(default)s)")
    p.add_argument("--chunk-size", type=int, default=8,
                   help="Models per chunk (default: %(default)s)")
    p.add_argument("--n-models", type=int, default=10,
                   help="Diffusion outputs per design, i.e. model_0..model_N-1 (default: %(default)s)")
    p.add_argument("--prefix", default="ame_rfd3_first8",
                   help="Run name prefix embedded in PDB path keys (default: %(default)s)")
    p.add_argument("--pdb-dir", default="./outputs_rfd3",
                   help="Output directory encoded in PDB path keys (default: %(default)s)")
    p.add_argument("--out-dir", default=".",
                   help="Directory to write output JSON files (default: %(default)s)")
    return p.parse_args()


def chunks(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def main():
    args = parse_args()

    src = Path(args.input)
    with src.open() as f:
        models = json.load(f)

    model_ids = list(models.keys())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks(model_ids, args.chunk_size), start=1):
        batch_pdbs = {}
        batch_fixed_res = {}

        for model_id in chunk:
            fixed_keys = " ".join(models[model_id]["select_fixed_atoms"].keys())
            for j in range(args.n_models):
                path = f"{args.pdb_dir}/{args.prefix}-{i}_{model_id}_0_model_{j}.pdb"
                batch_pdbs[path] = ""
                batch_fixed_res[path] = fixed_keys

        tag = f"mod{args.chunk_size}-{i}"
        chunk_models_out = out_dir / f"mcsa_{tag}.json"
        pdbs_out = out_dir / f"batch_pdbs_{tag}.json"
        fixed_out = out_dir / f"batch_fixed_res_{tag}.json"

        with chunk_models_out.open("w") as f:
            json.dump({k: models[k] for k in chunk}, f, indent=4)
        with pdbs_out.open("w") as f:
            json.dump(batch_pdbs, f, indent=4)
        with fixed_out.open("w") as f:
            json.dump(batch_fixed_res, f, indent=4)

        print(f"Chunk {i}: {len(chunk)} models × {args.n_models} = {len(batch_pdbs)} entries"
              f"  →  {chunk_models_out.name}, {pdbs_out.name}, {fixed_out.name}")

    n_chunks = -(-len(model_ids) // args.chunk_size)  # ceiling division
    print(f"\nDone. {len(model_ids)} models → {n_chunks} chunks in {out_dir}/")


if __name__ == "__main__":
    main()
