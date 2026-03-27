#!/usr/bin/env python3
"""
Count the number of residue islands in each RFDiffusion inference task.

A residue island is a maximal contiguous stretch of the input structure used
as scaffold. Two scaffold segments in the contig are part of the same island
only when ALL of the following are true:
  1. 0 free residues between them in the contig string
  2. Same chain
  3. Residue numbers are directly consecutive (end_i + 1 == start_{i+1})
"""

import csv
import json
import re
import sys


def extract_contig(cmd_string):
    """Return the content of contigmap.contigs from a command string."""
    m = re.search(r"contigmap\.contigs=\[.*?'([^']+)'.*?\]", cmd_string)
    if not m:
        raise ValueError(f"Could not parse contigmap.contigs from: {cmd_string!r}")
    return m.group(1)


def parse_tokens(contig):
    """Return list of tokens: integers (free residues) and scaffold specs."""
    return re.findall(r"[A-Z]\d+-\d+|\d+", contig)


def count_islands(contig):
    """Count residue islands in a contig string."""
    tokens = parse_tokens(contig)

    scaffolds = []   # (chain, start, end) for each scaffold segment
    free_between = []  # free-residue count between scaffold[i-1] and scaffold[i]
    last_free = None

    for token in tokens:
        if re.match(r"^[A-Z]\d+-\d+$", token):
            chain = token[0]
            start, end = map(int, token[1:].split("-"))
            if scaffolds:  # record the free count leading into this segment
                free_between.append(last_free if last_free is not None else 0)
            scaffolds.append((chain, start, end))
            last_free = None
        else:
            last_free = int(token)

    if not scaffolds:
        return 0

    islands = 1
    for i in range(1, len(scaffolds)):
        chain_a, _, end_a = scaffolds[i - 1]
        chain_b, start_b, _ = scaffolds[i]
        free = free_between[i - 1]

        # New island unless directly adjacent in output AND in input
        if not (free == 0 and chain_a == chain_b and start_b == end_a + 1):
            islands += 1

    return islands


def main():
    input_path = "mcsa_41.json"
    output_path = "island_counts.csv"

    with open(input_path) as f:
        data = json.load(f)

    rows = []
    for input_id, cmd_string in data.items():
        contig = extract_contig(cmd_string)
        n_islands = count_islands(contig)
        rows.append({"INPUT_ID": input_id, "RESIDUE_ISLAND_COUNT": n_islands})

    rows.sort(key=lambda r: r["INPUT_ID"])

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["INPUT_ID", "RESIDUE_ISLAND_COUNT"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {output_path}")
    for r in rows:
        print(f"  {r['INPUT_ID']}: {r['RESIDUE_ISLAND_COUNT']}")


if __name__ == "__main__":
    main()
