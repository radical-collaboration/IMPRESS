import argparse
import os


def main():
    parser = argparse.ArgumentParser(description="Split LigandMPNN FASTA output into per-sequence files")
    parser.add_argument("--input_dir", required=True, help="Directory containing .fa files")
    parser.add_argument("--output_dir", required=True, help="Destination directory (created if absent)")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    fa_files = [f for f in os.listdir(args.input_dir) if f.endswith(".fa")]
    seen = set()
    count = 0

    for fa_file in sorted(fa_files):
        path = os.path.join(args.input_dir, fa_file)
        with open(path) as f:
            lines = f.readlines()

        # Skip first 2 lines (file-level metadata header + its sequence)
        remaining = lines[2:]

        for i in range(0, len(remaining), 2):
            header_line = remaining[i]
            seq_line = remaining[i + 1]

            parts = header_line.split(",")
            system_name = parts[0].lstrip(">").strip()
            id_field = parts[1].strip()  # "id=1"
            seq_id = id_field.split("=")[1].strip()

            filename = f"{system_name}-{seq_id}.fa"
            if filename in seen:
                raise ValueError(f"Duplicate output filename detected: {filename}")
            seen.add(filename)

            out_path = os.path.join(args.output_dir, filename)
            with open(out_path, "w") as out:
                out.write(header_line)
                out.write(seq_line)

            count += 1

    print(f"{count} files written to {args.output_dir}")


if __name__ == "__main__":
    main()
