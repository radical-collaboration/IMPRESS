#!/usr/bin/env python3
"""Regenerate slides/DECK_SCRIPT.md from the addNotes blocks in build_deck.js.

The deck is the single source of the spoken prose, so a presenter reading the notes pane
and a presenter reading DECK_SCRIPT.md can never diverge. Run this after editing any
slide's notes:

    python3 slides/make_script.py

Word counts are the spoken prose only: anything in [brackets] is a stage direction or a
per-slide budget and is excluded. 155 wpm is a realistic rate for technical material
delivered with pauses.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK = HERE / "build_deck.js"
OUT = HERE / "DECK_SCRIPT.md"
WPM = 155
# Slides that may be dropped for a shorter running order, by leading number.
CUT_B = {"6", "10", "11"}      # the designated cuts: typed dataflow, and the tools pair
CUT_C = CUT_B | {"15"}         # and the how-to-run slide, for a hard 20


def spoken_words(notes: str) -> int:
    clean = re.sub(r"\[[^\]]*\]", " ", notes)
    return len([w for w in clean.split() if re.search(r"\w", w)])


def main() -> int:
    src = DECK.read_text()
    slides = re.findall(r"// =+ (.+?)\n(.*?)(?=\n// =+ |\npres\.writeFile)", src, re.S)
    if not slides:
        print("no slides found in build_deck.js", file=sys.stderr)
        return 1

    entries = []
    for name, body in slides:
        match = re.search(r"s\.addNotes\(\s*`(.*?)`\);", body, re.S)
        notes = match.group(1).strip() if match else ""
        entries.append((name, notes, spoken_words(notes)))

    main_entries = [e for e in entries if not e[0].startswith("B")]
    backups = [e for e in entries if e[0].startswith("B")]
    total = sum(e[2] for e in main_entries)
    cut_b = total - sum(e[2] for e in main_entries if e[0].split(".")[0] in CUT_B)
    cut_c = total - sum(e[2] for e in main_entries if e[0].split(".")[0] in CUT_C)

    head: list[str] = ["# IMPRESS-A code walk — speaking script\n"]
    head.append(
        """Companion to [`DECK_OUTLINE.md`](DECK_OUTLINE.md) (slide structure) and
[`CODE_FOR_DECK.md`](CODE_FOR_DECK.md) (the staged code blocks). Slide numbers and snippet IDs match
across all three.

**This file is generated from the `addNotes` blocks in `build_deck.js`.** The deck is the single
source of the spoken prose, so a presenter reading from the notes pane and a presenter reading from
this file never diverge. Regenerate after editing the deck — the command is at the bottom.

**How to read it.** Plain prose is meant to be *said*. Anything in `[brackets]` is a stage direction
or that slide's budget, and is excluded from the word counts.

**Pacing — measured, not estimated.** Counts are the actual spoken prose at 155 words/minute, a
realistic rate for technical material delivered with pauses.
"""
    )
    head.append("| Slide | Spoken | | Slide | Spoken |")
    head.append("|---|---|---|---|---|")
    half = (len(main_entries) + 1) // 2
    for i in range(half):
        left = main_entries[i]
        right = main_entries[i + half] if i + half < len(main_entries) else None
        unit = " min" if i == 0 else ""
        row = f"| {left[0]} | {left[2] / WPM:.1f}{unit} |"
        row += f" | {right[0]} | {right[2] / WPM:.1f} |" if right else " | | |"
        head.append(row)

    head.append("")
    head.append(
        f"**Main path: {total} words = {total / WPM:.1f} minutes of speech.** "
        f"Backups add {sum(e[2] for e in backups) / WPM:.1f} min if used.\n"
    )
    head.append("| Order | What's in | Speech | Fits |")
    head.append("|---|---|---|---|")
    head.append(
        f"| **A · full** | every main slide | **{total / WPM:.1f}** | "
        "a 25-minute slot, or 20 with questions strictly held to the end |"
    )
    head.append(
        f"| **B · default** | drop 6 (typed dataflow) and 10-11 (the tools pair) | "
        f"**{cut_b / WPM:.1f}** | a 20-minute slot with a few questions taken inline |"
    )
    head.append(
        f"| **C · hard twenty** | B, and drop 15 (how to run it — it is in the README) | "
        f"**{cut_c / WPM:.1f}** | a hard 20 that leaves real room for discussion |"
    )
    head.append(
        """
**Protect 8, 9, 14 and 17.** Those are the two seam slides, the trust findings and the asks, and
they are what this room came for. Slides 6, 10 and 11 are the designated cuts: the typed-dataflow
strip is recoverable in one sentence on slide 4, the tool-spec slide is recoverable on slide 7, and
the pattern taxonomy is recoverable in the one sentence on slide 10 that reads the `pattern:` field.
Order C drops 15 as well — how to run it is in the README, and this audience will read that rather
than watch it.

Do **not** compress 16 (status). An audience that catches you overclaiming stops believing the rest,
and this deck's credibility rests on the caveats being volunteered rather than extracted.

**Three things to say out loud even if nothing prompts them:** `replicas > 1` has never executed
(slide 16), nothing has ever been promoted by the trust ledger so the trusted path has never run
(slide 14), and the Delta durations on slide 12 are transcribed from `plans/first-real-run.md`
rather than read from a log on this machine.
"""
    )

    parts = ["\n".join(head), "---\n"]
    for name, notes, words in entries:
        parts.append(f"## {name} — *{words / WPM:.1f} min*\n")
        parts.append(notes + "\n")
    parts.append(
        """---

## Regenerating this file

The prose lives in `build_deck.js`. After editing a slide's `addNotes`:

```sh
python3 slides/make_script.py        # rewrites DECK_SCRIPT.md from build_deck.js
```
"""
    )
    OUT.write_text("\n".join(parts))
    print(f"wrote {OUT}")
    print(f"  main path: {total} words = {total / WPM:.1f} min  ·  "
          f"order B = {cut_b / WPM:.1f} min  ·  order C = {cut_c / WPM:.1f} min  ·  "
          f"backups {sum(e[2] for e in backups) / WPM:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
