#!/usr/bin/env python3
"""Verify every code anchor cited in the deck still points where it claims.

Anchors are load-bearing: a slide that says `executor.py:304` and shows code from somewhere
else is worse than no citation at all, and this audience will check from a laptop while you
talk. Run before presenting, and after any edit to src/:

    python3 slides/check_anchors.py

Each entry is (path, line, expected first line of the snippet). The check is a prefix match
on the stripped line, so indentation changes are tolerated and real movement is not. When an
anchor has drifted, the script reports where the line actually is, so `build_deck.js` and
`CODE_FOR_DECK.md` get corrected rather than papered over.

Every `file:line` the deck PRINTS belongs here, whether it appears in a code block's anchor
label, a table cell or body text — a citation is a citation wherever it is rendered.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "impress_a"

# (path relative to src/impress_a, line, expected first line) — keep in sync with the deck.
ANCHORS: list[tuple[str, int, str]] = [
    # S3 — the constraint, cited in the table's "where" column
    ("core/decision.py", 21, "class ExperimentIntent"),
    ("compose/validate.py", 30, "def validate"),
    ("compose/validate.py", 143, "async def dry_run"),
    ("compose/interlock.py", 146, "def for_pattern"),
    ("tools/agent.py", 110, "async def post_process"),
    ("core/pareto.py", 56, "def feasible"),
    ("runtime/executor.py", 242, "def _absorb"),
    # S4 — the two lanes
    ("runtime/executor.py", 215, "def observe"),
    ("policy/driver.py", 84, "async def _submit_with_retry"),
    ("runtime/executor.py", 304, "async def _admit_once"),
    ("exec/dispatch.py", 165, "def submit"),
    ("runtime/executor.py", 744, "async def pump"),
    ("runtime/executor.py", 629, "async def _reap"),
    # S6 — typed dataflow
    ("compose/composer.py", 36, "def compose"),
    ("exec/dispatch.py", 91, "def to_outcome"),
    # S7 — the five gates, the interlock, the reservation
    ("compose/validate.py", 38, "def _g1_types"),
    ("compose/validate.py", 70, "def _g2_structure"),
    ("compose/validate.py", 86, "def _g3_params"),
    ("compose/validate.py", 103, "def _g4_resources"),
    ("compose/validate.py", 134, "def _g5_budget"),
    ("runtime/executor.py", 331, "if failure is None and not scrutiny.trusted"),
    ("runtime/executor.py", 337, "if failure is None and scrutiny.cost_cap_fraction"),
    ("runtime/executor.py", 355, "if blown := self.budget.reserve"),
    # S8 — the generic factory and the non-blocking submit
    ("exec/dispatch.py", 144, "def _make_task"),
    ("exec/dispatch.py", 153, "async def _run"),
    ("exec/dispatch.py", 162, "_run.__name__ = node_id"),
    ("exec/dispatch.py", 182, "for tid in g.topo_order()"),
    ("exec/dispatch.py", 188, "gather = asyncio.gather"),
    ("exec/dispatch.py", 207, "def cancel"),
    # S9 — building the engine on the right loop
    ("exec/backend.py", 128, "async def make_engine_bounded"),
    ("exec/backend.py", 140, "if timeout_s <= 0 or kind.lower() in _CHEAP_KINDS"),
    ("exec/backend.py", 144, "threading.Thread(target=_construct_backend_in_thread"),
    ("exec/backend.py", 160, "be = await asyncio.wait_for"),
    ("exec/backend.py", 172, "async def _finish"),
    # S10 — the four phases
    ("tools/agent.py", 55, "async def pre_process"),
    ("tools/agent.py", 58, "def parameterize"),
    ("tools/agent.py", 79, "async def run"),
    # S11 — the taxonomy and the three enforcement sites the slide quotes. The slide also
    # states a COUNT of consulting sites, which run_model.py's pattern census greps out of
    # src/ rather than asserting here — so a new one appearing under exec/ or runtime/
    # falsifies the slide's claim loudly instead of letting these four anchors stay green.
    ("core/types.py", 12, "class Pattern(str, Enum)"),
    ("compose/composer.py", 45, "stages = [t for t in intent.stages"),
    ("compose/validate.py", 106, "if spec.pattern is Pattern.P6"),
    ("tools/spec.py", 107, "if self.pattern is Pattern.P1"),
    # S14 — the pattern signature
    ("compose/graph.py", 51, "def pattern_signature"),
    ("runtime/executor.py", 155, "trust_dir = Path(spec.trust_root)"),
]

# Files outside src/impress_a that a slide quotes, checked the same way.
OTHER: list[tuple[str, int, str]] = [
    ("toolkits/rosetta/tools/filter_shape/spec.yaml", 1, "id: filter_shape"),
]


def check(rel: str, line_no: int, expected: str, base: Path) -> bool:
    path = base / rel
    if not path.exists():
        print(f"MISSING  {rel}")
        return False
    lines = path.read_text(errors="replace").splitlines()
    actual = lines[line_no - 1].strip() if line_no - 1 < len(lines) else "<past EOF>"
    if actual.startswith(expected.strip()):
        return True
    real = next((i + 1 for i, line in enumerate(lines)
                 if line.strip().startswith(expected.strip())), None)
    print(f"DRIFT    {rel}:{line_no}")
    print(f"         expected {expected!r}")
    print(f"         found    {actual!r}")
    print(f"         now at   {real if real else 'NOT FOUND — the snippet may be gone'}")
    return False


def main() -> int:
    results = [check(rel, n, exp, SRC) for rel, n, exp in ANCHORS]
    results += [check(rel, n, exp, ROOT) for rel, n, exp in OTHER]
    ok, total = sum(results), len(results)
    print(f"\n{ok}/{total} anchors verified" + ("" if ok == total else ""))
    if ok != total:
        print("Fix build_deck.js and CODE_FOR_DECK.md; do not present a drifted anchor.")
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
