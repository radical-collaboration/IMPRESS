"""The toolchain, asserted rather than documented.

Two things this package's own notes claimed and the tree did not support:

* **The lint gate did not exist.** There was no `[tool.ruff]` table in `agent/pyproject.toml`,
  so ruff walked up to IMPRESS's own config, which sets `fix = true`. The documented
  `ruff check src tests` therefore *rewrote the working tree* rather than reporting on it, and
  the ceiling of 41 that `CLAUDE.md` quoted did not reproduce against the config that actually
  resolved: 449 findings there, 9 under ruff's own defaults. CI ran only the test suite.
* **The dependency on `impress` is new and unreleased.** IMPRESS-A's execution loop is built on
  the framework at the repository root, which exists on no index - so pip must be handed it as
  a local editable install before it resolves this project, or it goes looking for the name
  `impress` on PyPI and installs whatever is there. That failure is silent until an import
  returns the wrong module.

Neither is checkable by reading; both are cheap to assert.
"""
from __future__ import annotations

import pathlib
import sys

import impress

import impress_a

if sys.version_info >= (3, 11):
    import tomllib
else:  # tomllib landed in 3.11; `tomli` is the dev-extra backport for the 3.10 floor
    import tomli as tomllib

#: `<repo>/agent/src/impress_a/__init__.py` -> impress_a, src, agent, repo
REPO = pathlib.Path(impress_a.__file__).resolve().parents[3]
PYPROJECT = REPO / "agent" / "pyproject.toml"


def _config() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def test_impress_is_importable_and_pinned():
    """The three-name public API this project designs against, unchanged.

    `impress/__init__.py` exports exactly `ImpressManager`, `ImpressBasePipeline` and
    `PipelineSetup`. The execution loop is written against those three and nothing else -
    `ImpressLogger` and the telemetry helpers are reached through `impress.utils.*` - so a
    change to this list is a change to the surface we build on and should be seen.
    """
    assert impress.__all__ == ["ImpressManager", "ImpressBasePipeline", "PipelineSetup"]


def test_the_installed_impress_is_the_one_in_this_repository():
    """Not a package of the same name from an index.

    This is the failure the two-step install in `scripts/dev_setup.sh` and
    `.github/workflows/agent-tests.yml` exists to prevent, and it fails by returning a
    *working* module that is simply the wrong one.
    """
    got = pathlib.Path(impress.__file__).resolve()
    assert got == REPO / "src" / "impress" / "__init__.py", (
        f"`impress` resolved to {got}, not this repository's src/impress - install it "
        f"editable from the root first: see scripts/dev_setup.sh")


def test_impress_is_a_declared_dependency():
    """Importable by accident is not the same as declared."""
    deps = _config()["project"]["dependencies"]
    assert any(d == "impress" or d.startswith("impress ") or d.startswith("impress=")
               for d in deps), f"`impress` missing from dependencies: {deps}"


def test_ruff_config_is_local():
    """A `[tool.ruff]` table here, so ruff can never resolve to the root project's again.

    Without this table ruff walks up and finds `fix = true`, and a linter that edits the tree
    cannot be a gate: a clean run and a run that silently rewrote 36 files look identical
    afterwards.
    """
    ruff = _config().get("tool", {}).get("ruff")
    assert ruff is not None, (
        "no [tool.ruff] in agent/pyproject.toml - ruff would walk up to the root config, "
        "which sets fix = true")
    assert ruff.get("fix") is False, (
        "[tool.ruff] fix must be false: `ruff check` is the gate, and a gate that rewrites "
        "the tree reports nothing. Use `ruff check --fix` explicitly when fixing.")


def test_the_declined_lint_rules_say_why():
    """Each ignored rule is a decision, so it carries its reason in the file.

    `N818` is declined rather than satisfied: an `Error` suffix on `CampaignStopped` and its
    three siblings would make every sentence in `docs/decisions/`, `plans/done/` and
    `CLAUDE.md` that names them wrong, for no runtime benefit.
    """
    ignored = _config()["tool"]["ruff"]["lint"]["ignore"]
    assert set(ignored) == {"UP007", "UP045", "N818"}, (
        f"the ignore list changed to {ignored}; add the reason beside it in pyproject.toml "
        f"and update this test, so a growing list stays a set of decisions")
