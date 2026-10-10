"""The import contract, asserted rather than reviewed.

`CLAUDE.md` lists three layering rules as invariants and records their enforcement as
"review". They are the load-bearing ones:

  * `policy` must not import `tools`, `exec` or `runtime` - a policy that can reach a tool
    adapter stops emitting abstract intent, and control models stop being swappable;
  * `compose` must not import `exec` - this is what keeps the whole validation path
    testable with no backend, which is the entire laptop test tier;
  * `core` imports nothing internal.

This file walks the source with `ast` and checks all three, plus every other edge, against
one table that mirrors `docs/reference/architecture.md`. `ast.walk` is used deliberately
rather than a scan of module-level imports: the real adapters defer their science imports
into `run()` bodies on purpose (see `tools/_pdbtools.py`), and a deferred
`from ..exec import ...` inside a `compose` function would be exactly as fatal as one at
the top of the file.

One honest blind spot: a dynamic `importlib.import_module("impress_a.x")` is invisible
here. `Registry.agent_for` uses one, legitimately, and within its own layer.
"""
from __future__ import annotations

import ast
import pathlib

import impress_a

SRC = pathlib.Path(impress_a.__file__).resolve().parent

#: layer -> the internal layers it MAY import. Mirrors docs/reference/architecture.md.
#: An allow-list, not a deny-list: a NEW cross-layer import fails by default, which is the
#: direction that matters. A new layer is one line here, and an unlisted layer fails
#: `test_every_layer_is_in_the_table`, so this cannot silently fall out of step.
#:
#: When a row here conflicts with the code, reconcile the DOC up to the code and fix this
#: table only if the edge is genuinely allowed. Loosening a row to make a failure go away
#: is how the contract dies.
#:
#: Three allowances are documented but not currently exercised - `control -> runtime`,
#: `runtime -> policy` and `tools -> exec`. They are kept because the doc grants them; the
#: table is a mirror of the contract, not a snapshot of today's edges.
ALLOWED = {
    "core": frozenset(),
    "compose": frozenset({"tools", "core"}),
    "tools": frozenset({"exec", "core"}),
    "exec": frozenset({"compose", "tools", "core"}),
    "policy": frozenset({"core"}),
    "runtime": frozenset({"policy", "compose", "exec", "tools", "core"}),
    # `manager -> tools` is real (manager.py:39 imports Registry) and was missing from
    # architecture.md until this test surfaced it. Doc corrected, table records the code.
    "manager": frozenset({"runtime", "policy", "tools", "core"}),
    "control": frozenset({"manager", "runtime", "core"}),
    # cli/ and __main__ appeared in no layer of the doc's table at all.
    "cli": frozenset({"manager", "policy", "compose", "tools", "core"}),
    "__main__": frozenset({"cli"}),
}


def _layer(dotted: str | None) -> str | None:
    """"impress_a.tools.gates" -> "tools". Anything not inside the package -> None."""
    if not dotted:
        return None
    parts = dotted.split(".")
    if parts[0] != "impress_a" or len(parts) < 2:
        return None
    return parts[1]


def _package_of(path: pathlib.Path) -> tuple[str, ...]:
    """The dotted package CONTAINING `path`, as parts relative to the package root.

    Correct for `foo/bar.py` and `foo/__init__.py` alike - both live in package `foo`,
    which is what a relative import resolves against.
    """
    rel = path.relative_to(SRC)
    return ("impress_a",) + rel.parts[:-1]


def _resolve(node: ast.ImportFrom, pkg: tuple[str, ...]) -> str | None:
    """The absolute dotted name an `ImportFrom` refers to, relative levels included."""
    if node.level == 0:
        return node.module
    base = pkg[:len(pkg) - (node.level - 1)] if node.level > 1 else pkg
    return ".".join(base + ((node.module,) if node.module else ()))


def _edges() -> list[tuple[pathlib.Path, int, str, str]]:
    """(file, lineno, importer_layer, imported_layer) for every internal import."""
    out: list[tuple[pathlib.Path, int, str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        pkg = _package_of(path)
        importer = _layer(".".join(pkg)) or (
            path.stem if path.parent == SRC else None)
        if importer is None:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _layer(_resolve(node, pkg))
            elif isinstance(node, ast.Import):
                imported = next(
                    (lay for a in node.names if (lay := _layer(a.name))), None)
            else:
                continue
            if imported and imported != importer:
                out.append((path, node.lineno, importer, imported))
    return out


def test_core_imports_nothing_internal():
    """`core` is the vocabulary every other layer shares, so it may depend on none of them.

    Its own files say why they exist there: `core/session.py` and `core/results.py` hold
    the shapes a reasoner in another process needs, precisely so that reaching for them
    does not drag in `runtime`.
    """
    bad = [f"{p.relative_to(SRC.parent)}:{ln}: core must not import {b}"
           for p, ln, a, b in _edges() if a == "core"]
    assert bad == [], "\n".join(bad)


def test_the_import_contract_holds():
    """Every internal import, against the table. All violations reported in one run."""
    # Guard the TABLE first. The realistic failure is not someone adding a bad import and
    # ignoring the test - it is someone hitting the failure and editing the row.
    assert ALLOWED["policy"].isdisjoint({"tools", "exec", "runtime"}), \
        "a policy that can reach a tool adapter stops emitting abstract intent"
    assert "exec" not in ALLOWED["compose"], \
        "compose reaching exec would make the validation path need a backend"

    bad = [f"{p.relative_to(SRC.parent)}:{ln}: {a} must not import {b}"
           for p, ln, a, b in _edges() if b not in ALLOWED[a]]
    assert bad == [], "\n".join(bad)


def test_every_layer_is_in_the_table():
    """A new package under `impress_a/` must be placed in the contract, not skipped.

    Without this, adding a layer means it is silently unchecked - the table would still
    pass while saying nothing about the new code.
    """
    layers = {p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    layers |= {p.stem for p in SRC.glob("*.py") if p.stem != "__init__"}
    missing = sorted(layers - set(ALLOWED))
    assert missing == [], f"not in ALLOWED: {missing}"
