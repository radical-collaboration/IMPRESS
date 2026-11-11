#!/usr/bin/env python3
"""Fail on a broken internal documentation link or a missing nav target.

This exists because `mkdocs build --strict` cannot be used yet, and the reason is worth
stating: strict mode escalates *every* warning, and the build currently emits 46 of them
from griffe - "No type or annotation for parameter ..." against `src/impress/utils/logger.py`
and `src/impress/pipelines/impress_pipeline.py`. Those are real documentation gaps, but
they are unrelated to whether a link resolves, and gating on them would mean the docs job
stays red until someone annotates two unrelated modules.

Zero of those 46 warnings are about links or nav. So this script takes the half of
`--strict` that the consolidation actually needed - a build that fails when a page
disappears or a link rots - and leaves the other half to be switched on later by deleting
this file and adding `--strict` back, once the griffe warnings are gone.

Run via `tox -e docs`, which builds the site first.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MKDOCS = ROOT / "mkdocs.yml"

# A markdown inline link, minus its anchor or query: [text](target#anchor)
LINK = re.compile(r"\[[^\]]*\]\(([^)#?\s]+)(?:[#?][^)]*)?\)")
EXTERNAL = ("http://", "https://", "mailto:", "tel:")


def _nav_targets(node, out: list[str]) -> None:
    """Collect every page path in mkdocs.yml's nav, at any nesting depth."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, list):
        for item in node:
            _nav_targets(item, out)
    elif isinstance(node, dict):
        for value in node.values():
            _nav_targets(value, out)


def main() -> int:
    # mkdocs.yml carries `!!python/name:` tags for the emoji extensions, which safe_load
    # refuses. Only `nav` and `docs_dir` are needed here, so neutralise those tags to
    # plain strings textually and keep using safe_load - a custom loader that constructs
    # tagged objects is the thing not to do, even when the tag looks harmless.
    text = re.sub(r"!!python/name:\S+", "'<python-name>'", MKDOCS.read_text())
    cfg = yaml.safe_load(text)
    docs = ROOT / cfg.get("docs_dir", "docs")

    problems: list[str] = []

    nav: list[str] = []
    _nav_targets(cfg.get("nav", []), nav)
    for target in nav:
        if target.startswith(EXTERNAL):
            continue
        if not (docs / target).exists():
            problems.append(f"nav entry has no file: {target}")

    for md in sorted(docs.rglob("*.md")):
        for match in LINK.finditer(md.read_text()):
            target = match.group(1).strip()
            if target.startswith(EXTERNAL) or target.startswith("/"):
                continue
            if not (md.parent / target).exists():
                problems.append(f"{md.relative_to(ROOT)} -> {target}")

    pages = sum(1 for _ in docs.rglob("*.md"))
    if problems:
        print(f"docs link check FAILED: {len(problems)} problem(s)")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"docs link check ok: {pages} pages, {len(nav)} nav entries, no broken links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
