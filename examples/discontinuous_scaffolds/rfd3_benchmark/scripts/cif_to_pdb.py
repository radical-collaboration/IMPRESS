#!/usr/bin/env python3
import argparse
import gzip
import glob
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Convert RFDiffusion3 CIF.GZ outputs to PDB format")
    parser.add_argument("modelname", help="Model name prefix (e.g. mcsa_41_oneinput_M0209_1lij)")
    parser.add_argument("--input-dir", default="outputs_rfd3/", help="Directory containing .cif.gz files")
    parser.add_argument("--output-dir", default=None, help="Output directory for PDB files (default: same as input)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir) if args.output_dir else input_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    pattern = str(input_dir / f"{args.modelname}_0_model_[0-9]*.cif.gz")
    matches = sorted(glob.glob(pattern))

    if not matches:
        print(f"No files found matching: {pattern}", file=sys.stderr)
        sys.exit(1)

    converted = []
    for gz_path in matches:
        gz_path = Path(gz_path)
        stem = gz_path.name.removesuffix(".cif.gz")
        temp_cif = output_dir / f"{stem}.cif"
        out_pdb = output_dir / f"{stem}.pdb"

        with gzip.open(gz_path, "rb") as f_in, open(temp_cif, "wb") as f_out:
            f_out.write(f_in.read())

        result = subprocess.run(
            ["obabel", "-icif", str(temp_cif), "-opdb", "-O", str(out_pdb)],
            capture_output=True,
            text=True,
        )

        temp_cif.unlink()

        if result.returncode != 0:
            print(f"obabel failed for {gz_path.name}:\n{result.stderr}", file=sys.stderr)
        else:
            converted.append(out_pdb)
            print(f"Converted: {gz_path.name} -> {out_pdb.name}")

    print(f"\nDone: {len(converted)}/{len(matches)} files converted.")
    if len(converted) < len(matches):
        sys.exit(1)


if __name__ == "__main__":
    main()
