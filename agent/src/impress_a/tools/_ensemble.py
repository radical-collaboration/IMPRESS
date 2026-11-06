"""Choosing the best member of a tool's own ensemble.

Every adapter here kept index `[0]`: `cif_models[0]`, `packed[0]`, `confidence_files[0]`, and a
FASTA parser that read the first header carrying a confidence. So a tool asked for N candidates
produced N, was charged for N, and the campaign saw one - chosen by sort order. The declared
`num_designs`/`num_seqs`/`diffusion_samples` parameters were therefore inert, which is why
`plans/done/02-real-toolkit.md` could say "breadth comes from `replicas`, not from each tool's
internal sampling": not a design principle, a consequence of this.

The reference pipeline hit the same thing and recorded it: `analysis_sequence` "silently never
compared MPNN candidates against each other - it only ever read a `.fa` file's first line", and
real LigandMPNN writes every candidate for a design into one file. Fixing it there is what made
`mpnn_ensemble_size: 10` mean something.

Two rules, both from this project's own records:

**Select, do not fan out.** The reference takes the best member of a wide batch and carries it
forward; it does not turn 8 samples into 8 downstream chains. Breadth across *lineages* is
still `replicas`, and conflating the two would multiply GPU cost by the sample count at every
stage.

**A pairing it cannot make is a failure, not a guess.** Where a member's metric file and its
structure file have to be matched up, an adapter that cannot match them keeps index 0 and says
so in a metric, rather than selecting confidently from a mismatched pair. `rfd3_agents` already
states the principle for its trajectory bug: a confident guess is worse than a loud failure.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

#: `..._model_3.pdb`, `confidence_..._model_3.json`, `backbone_0_packed_1_2.pdb`. The LAST
#: integer in the stem, which is how every tool here numbers a member.
_INDEX_RE = re.compile(r"(\d+)(?!.*\d)")


def member_index(path: Path | str) -> int | None:
    """The member number in a filename, or None when it carries none.

    None rather than 0: "this file is member zero" and "this filename does not say" are
    different, and only one of them is safe to pair on.
    """
    stem = Path(path).name
    for suffix in (".gz", ".json", ".pdb", ".cif", ".fa", ".fasta"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    m = _INDEX_RE.search(stem)
    return int(m.group(1)) if m else None


def pair_by_index(a: list[Path], b: list[Path]) -> list[tuple[Path, Path]] | None:
    """Pair two lists of per-member files by their member number.

    `None` when the pairing is not one-to-one, which the caller must treat as "cannot select"
    rather than falling through to position. Position is what produced the mismatch this
    module exists to stop: two independently-sorted globs agree only by luck.
    """
    left = {member_index(p): p for p in a}
    right = {member_index(p): p for p in b}
    if None in left or None in right:
        return None
    if set(left) != set(right) or len(left) != len(a) or len(right) != len(b):
        return None
    return [(left[i], right[i]) for i in sorted(left)]


def select_best(members: list[Any], metric: Any, higher_is_better: bool = True
                ) -> tuple[int, Any] | None:
    """`(index, member)` of the best member by `metric`, or None if none has a value.

    `metric` is a callable returning a float or None. A member whose metric cannot be read is
    skipped rather than treated as zero - the same rule the gates use, where an unreadable
    value is an omission and a fabricated 0.0 would make a broken tool look like a weak design.
    """
    scored = [(i, m, value) for i, m in enumerate(members)
              if (value := metric(m)) is not None]
    if not scored:
        return None
    best = (max if higher_is_better else min)(scored, key=lambda row: row[2])
    return best[0], best[1]
