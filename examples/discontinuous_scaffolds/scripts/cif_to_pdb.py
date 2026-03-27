#!/usr/bin/env python3
import argparse
import gzip
import re
import subprocess
import sys
from pathlib import Path


def convert_model(modelname, input_dir, output_dir):
    """Decompress and convert all .cif.gz files for one model name. Returns (converted, total)."""
    matches = sorted(input_dir.glob(f"{modelname}_*_model_*.cif.gz"))

    if not matches:
        print(f"  No .cif.gz files found for model: {modelname}", file=sys.stderr)
        return 0, 0

    converted = 0
    for gz_path in matches:
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
            print(f"  obabel failed for {gz_path.name}:\n{result.stderr}", file=sys.stderr)
        else:
            converted += 1
            print(f"  Converted: {gz_path.name} -> {out_pdb.name}")

    return converted, len(matches)


def discover_model_names(input_dir):
    """Return sorted unique model name prefixes from *_<digits>_model_<digits>.cif.gz files."""
    suffix_re = re.compile(r"_\d+_model_\d+\.cif\.gz$")
    names = set()
    for p in input_dir.glob("*.cif.gz"):
        if suffix_re.search(p.name):
            names.add(suffix_re.sub("", p.name))
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(description="Convert RFDiffusion3 CIF.GZ outputs to PDB format")
    parser.add_argument("modelname", nargs="?", default=None,
                        help="Model name prefix (e.g. ame_rfd3_first8_M0024_1nzy). "
                             "If omitted, all unique model names in --input-dir are processed.")
    parser.add_argument("--input-dir", default="outputs_rfd3/",
                        help="Directory containing .cif.gz files (default: %(default)s)")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory for PDB files (default: same as input)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir) if args.output_dir else input_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.modelname:
        model_names = [args.modelname]
    else:
        model_names = discover_model_names(input_dir)
        if not model_names:
            print(f"No .cif.gz files found in {input_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(model_names)} unique model name(s) in {input_dir}")

    total_converted = total_files = 0
    for name in model_names:
        print(f"\nProcessing: {name}")
        c, t = convert_model(name, input_dir, output_dir)
        total_converted += c
        total_files += t

    print(f"\nDone: {total_converted}/{total_files} files converted across {len(model_names)} model(s).")
    if total_converted < total_files:
        sys.exit(1)


if __name__ == "__main__":
    main()
