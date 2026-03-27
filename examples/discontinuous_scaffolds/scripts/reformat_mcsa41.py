#!/usr/bin/env python3
"""Reformat mcsa_41.json from rfdaa flat CLI strings to rfd3 per-entry dicts."""

import ast
import json
import re
import sys

INPUT_FILE = "mcsa_41.json"
OUTPUT_FILE = "mcsa_41_rfd3.json"

# Params we explicitly handle — used for the unrecognized-param warning
KNOWN_PARAM_PREFIXES = [
    "inference.input_pdb=",
    "inference.ligand=",
    "contigmap.contigs=",
    "contigmap.contig_atoms=",
    "contigmap.length=",
    "++inference.partially_fixed_ligand=",
]


def extract_input(s: str) -> str:
    m = re.search(r"inference\.input_pdb=(\S+)", s)
    if not m:
        raise ValueError(f"No inference.input_pdb found in: {s!r}")
    path = m.group(1)
    return "./" + path


def extract_ligand(s: str) -> str:
    m = re.search(r"inference\.ligand=\\?'([^']+)\\?'", s)
    if not m:
        raise ValueError(f"No inference.ligand found in: {s!r}")
    return m.group(1).rstrip("\\")


def extract_contig(s: str) -> str:
    m = re.search(r"contigmap\.contigs=\[.*?'([^']+)'.*?\]", s)
    if not m:
        raise ValueError(f"No contigmap.contigs found in: {s!r}")
    raw = m.group(1).rstrip("\\")
    tokens = raw.split(",")

    # Strip leading tokens that are "0"
    while tokens and tokens[0] == "0":
        tokens.pop(0)
    # Strip trailing tokens that are "0"
    while tokens and tokens[-1] == "0":
        tokens.pop()

    # Collapse single-residue scaffold specs AXX-XX → AXX
    def collapse(tok: str) -> str:
        m2 = re.fullmatch(r"([A-Za-z]\d+)-(\d+)", tok)
        if m2:
            start = m2.group(1)  # e.g. "A136"
            end = m2.group(2)    # e.g. "136"
            # Extract numeric part of start
            start_num = re.search(r"\d+", start).group()
            if start_num == end:
                return start  # single residue
        return tok

    tokens = [collapse(t) for t in tokens]
    return ",".join(tokens)


def extract_contig_atoms(s: str) -> dict:
    m = re.search(r'contigmap\.contig_atoms="([^"]*)"', s)
    if not m:
        return {}
    atoms_raw = m.group(1)
    atoms_clean = atoms_raw.replace("\\'", "'").strip("'")
    try:
        atoms_dict = ast.literal_eval(atoms_clean)
    except Exception as e:
        raise ValueError(f"Failed to parse contig_atoms {atoms_clean!r}: {e}")
    # Strip leading/trailing spaces from keys
    return {k.strip(): v for k, v in atoms_dict.items()}


def extract_partially_fixed_ligand(s: str) -> dict:
    m = re.search(r'\+\+inference\.partially_fixed_ligand="(\{.*\})"', s)
    if not m:
        return {}
    pfl_raw = m.group(1)
    entries = re.findall(r"(\w+):\[([^\]]*)\]", pfl_raw)
    result = {}
    for name, atoms_str in entries:
        atom_list = [a.strip().strip('\\"').strip('"') for a in atoms_str.split(",")]
        result[name] = ",".join(atom_list)
    return result


def extract_fixed_atoms(s: str) -> dict:
    residue_atoms = extract_contig_atoms(s)
    ligand_atoms = extract_partially_fixed_ligand(s)
    return {**residue_atoms, **ligand_atoms}


def warn_unrecognized(key: str, s: str) -> None:
    # Remove known params and check what's left
    remaining = s
    for prefix in KNOWN_PARAM_PREFIXES:
        # Remove the token that starts with this prefix
        if prefix.endswith("="):
            pattern = re.escape(prefix[:-1]) + r"=\S+"
        else:
            pattern = re.escape(prefix) + r"\S+"
        remaining = re.sub(pattern, "", remaining)
    # Also remove quoted-value params
    remaining = re.sub(r'contigmap\.contig_atoms="[^"]*"', "", remaining)
    remaining = re.sub(r'\+\+inference\.partially_fixed_ligand="[^"]*"', "", remaining)
    remaining = remaining.strip()
    if remaining:
        print(f"WARNING [{key}]: unrecognized tokens: {remaining!r}", file=sys.stderr)


def parse_entry(key: str, flat_str: str) -> dict:
    warn_unrecognized(key, flat_str)
    return {
        "input": extract_input(flat_str),
        "ligand": extract_ligand(flat_str),
        "contig": extract_contig(flat_str),
        "select_fixed_atoms": extract_fixed_atoms(flat_str),
    }


def main():
    with open(INPUT_FILE) as f:
        data = json.load(f)

    output = {}
    for key, flat_str in data.items():
        try:
            output[key] = parse_entry(key, flat_str)
        except Exception as e:
            print(f"ERROR [{key}]: {e}", file=sys.stderr)
            sys.exit(1)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=4)

    print(f"Wrote {len(output)} entries to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
