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


def test_no_campaign_spec_sets_a_key_the_loader_ignores():
    """A key a spec file sets and the loader drops does nothing and says nothing.

    This is a recurring shape here rather than a hypothetical. `sites/*.yaml` has carried a
    `tool_delivery: {real|mock}` switch read by no code since it was written (backlog E1) - the
    very switch that would have prevented a documented mock-chain-on-a-GPU run - and
    `control_liveness_timeout_s: 120` sat in all three Delta specs doing nothing until
    `cli.load_spec` was taught to read it.

    Checks both directions of the gap: a key `CampaignSpec` has no field for, and a field the
    loader never populates from YAML.
    """
    import dataclasses

    import yaml

    from impress_a.cli import load_spec
    from impress_a.runtime.executor import CampaignSpec

    fields = {f.name for f in dataclasses.fields(CampaignSpec)}
    campaigns = sorted((REPO / "agent" / "campaigns").glob("*.yaml"))
    assert campaigns, "no campaign specs found; this test would pass vacuously"

    for path in campaigns:
        doc = yaml.safe_load(path.read_text()) or {}
        unknown = sorted(set(doc) - fields)
        assert not unknown, (
            f"{path.name} sets {unknown}, which `CampaignSpec` has no field for - so the "
            f"value is read, parsed, and dropped")

        # And every key it sets must survive the loader, not merely be a known field name.
        spec = load_spec(str(path))
        for key, value in doc.items():
            if key in ("params", "objectives", "site", "budget", "backend_config"):
                continue      # structured, and transformed on the way in
            got = getattr(spec, key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                assert float(got) == float(value), (
                    f"{path.name}: {key}={value} did not reach the spec (got {got!r})")
            else:
                assert got == value, (
                    f"{path.name}: {key}={value!r} did not reach the spec (got {got!r})")


def _documented_command_lines(doc: pathlib.Path) -> list[tuple[int, list[str]]]:
    """Every `impress-a` invocation inside a ```bash block, as argv.

    Line continuations are joined first, then a leading run of `NAME=value` environment
    assignments is dropped - the procedure sets `IMPRESS_A_TRUST_DIR` that way on the same
    line as the command. Only fenced blocks are read: prose names commands in fragments
    (`impress-a run --model C`, `impress-a compare`) that were never meant to be complete.
    """
    import shlex

    text, fenced, joined = doc.read_text(), False, []
    for n, raw in enumerate(text.splitlines(), start=1):
        if raw.strip().startswith("```"):
            fenced = raw.strip().startswith("```bash")
            continue
        if not fenced:
            continue
        line = raw.split("#", 1)[0].rstrip()
        if joined and joined[-1][1].endswith("\\"):
            prev_n, prev = joined.pop()
            joined.append((prev_n, prev[:-1] + " " + line.strip()))
        else:
            joined.append((n, line.strip()))

    out = []
    for n, line in joined:
        if "impress-a" not in line:
            continue
        toks = shlex.split(line.rstrip("\\"), comments=False)
        while toks and "=" in toks[0] and not toks[0].startswith("-"):
            toks.pop(0)
        if toks and toks[0] == "impress-a":
            out.append((n, toks[1:]))
    return out


def _launcher_command_lines(script: pathlib.Path) -> list[tuple[int, list[str]]]:
    """Every argv the launcher hands the CLI, in both the forms it uses.

    `impress-a preflight --quick "${CAMPAIGN}"` is invoked directly; `RUNNER_ARGS=( run ... )`
    is passed to `delta_run_campaign.py`, which forwards it to the same parser. Both are argv
    the CLI has to accept, and a `${VAR}` stands in for a value the parser never inspects.
    """
    import re
    import shlex

    text = script.read_text()
    out: list[tuple[int, list[str]]] = []

    joined, lines = [], text.splitlines()
    for n, raw in enumerate(lines, start=1):
        line = raw.split("#", 1)[0].rstrip()
        if joined and joined[-1][1].rstrip().endswith("\\"):
            prev_n, prev = joined.pop()
            joined.append((prev_n, prev.rstrip()[:-1] + " " + line.strip()))
        else:
            joined.append((n, line))

    # A RUNNER_ARGS=( ... ) array may span lines; close it before parsing.
    buf: list[str] = []
    buf_n = 0
    for n, line in joined:
        if buf:
            buf.append(line)
            if ")" in line:
                merged = " ".join(buf)
                body = merged.split("(", 1)[1].rsplit(")", 1)[0]
                out.append((buf_n, shlex.split(_placeholders(body))))
                buf = []
            continue
        if re.match(r"\s*RUNNER_ARGS=\(", line):
            if ")" in line.split("(", 1)[1]:
                body = line.split("(", 1)[1].rsplit(")", 1)[0]
                out.append((n, shlex.split(_placeholders(body))))
            else:
                buf, buf_n = [line], n
            continue
        if "impress-a " in line:
            frag = line[line.index("impress-a "):]
            # The call sits inside shell syntax - `if ! impress-a ... ; then`, `cmd && cmd`.
            # Cut at the first operator, or the argv picks up `; then` as a positional.
            for op in (";", "&&", "||", "|", ">"):
                frag = frag.split(op, 1)[0]
            out.append((n, shlex.split(_placeholders(frag))[1:]))
    return out


def _placeholders(fragment: str) -> str:
    """`${CAMPAIGN}` -> a value. The parser type-checks ints, so widths must stay numeric."""
    import re

    fragment = re.sub(r"\$\{IMPRESS_A_CALLER_TIMEOUT:-(\d+)\}", r"\1", fragment)
    fragment = re.sub(r"\$\{MODEL\}", "D", fragment)
    return re.sub(r"\$\{[A-Za-z_][A-Za-z0-9_]*(:-[^}]*)?\}", "placeholder", fragment)


def test_the_delta_launcher_command_lines_parse():
    """The launcher gates every Delta job on a command line the CLI must accept.

    `scripts/delta_gpu_run.sh` ran `impress-a preflight --quick "${CAMPAIGN}"` and `--quick`
    did not exist, so argparse exited 2, the `if !` caught it, and the script printed
    "preflight failed" and exited 1 - aborting EVERY arm at launch, before Dragon, for a
    reason that named the environment rather than the flag. It would have burned a submission
    per arm to discover, and the message would have sent the reader to `delta_env_setup.sh`.

    The markdown procedure and this launcher are two separate surfaces; only this one holds
    `RUNNER_ARGS`, and only this one runs unattended.
    """
    from impress_a.cli import _parser

    script = pathlib.Path("scripts/delta_gpu_run.sh")
    found = _launcher_command_lines(script)
    assert len(found) >= 4, f"extractor matched only {len(found)} launcher argv lines"
    for line_no, argv in found:
        try:
            _parser().parse_args(argv)
        except SystemExit as exc:
            raise AssertionError(
                f"{script}:{line_no} hands the CLI `{' '.join(argv)}`, which it refuses "
                f"(SystemExit {exc.code}) - every job using this branch would abort at launch"
            ) from None


def test_quick_preflight_skips_the_heavy_probes_and_calls_them_skipped(capsys, monkeypatch):
    """A skipped probe must not read as a pass, and must not shell out.

    The bound matters: pyrosetta 120s + LigandMPNN's import chain 900s + its `--help` 300s is
    1320s of subprocess inside an allocation whose whole purpose for this call is to fail in
    seconds. So the test asserts no subprocess ran, rather than that it ran quickly.
    """
    import subprocess

    from impress_a import cli

    monkeypatch.setenv("MPNN_DIR", str(pathlib.Path.cwd()))
    calls = []
    real = subprocess.run

    def spy(cmd, *a, **kw):
        calls.append(cmd)
        return real(cmd, *a, **kw)

    # `preflight` does `import subprocess` in its own body, which binds the module object -
    # so patching the attribute on the stdlib module is what the function actually sees.
    monkeypatch.setattr(subprocess, "run", spy)
    cli.preflight(cli.load_spec("campaigns/delta-small-molecule-arms-smoke.yaml"), quick=True)
    out = capsys.readouterr().out

    assert "(quick)" in out
    for heavy in ("import pyrosetta", "mpnn_run.py", "run.py"):
        assert not any(heavy in " ".join(map(str, c)) for c in calls), \
            f"--quick shelled out to {heavy}"
    assert "skipped by --quick" in out
    for probe in ("pyrosetta", "ligandmpnn imports"):
        assert probe in out.split("skipped by --quick")[1], f"{probe} not named as skipped"
        assert f"[ok  ] {probe}" not in out, f"{probe} was skipped but reported ok"


def test_documented_command_lines_parse():
    """A documented step that argparse refuses is exit code 2 with an allocation held.

    `impress-a trust --list` appeared in both the plan and the pre-registration - the frozen
    document whose sha goes into every arm's `manifest.json` - and the flag did not exist. The
    listing was printed unconditionally, so the behaviour was right and only the command line
    was wrong, which is precisely the kind of gap no test was looking at: the CLI's own tests
    call `trust()` directly and never go through the parser.

    Checked by parsing, not running: `_parser()` builds the command line and executes nothing.
    """
    from impress_a.cli import _parser

    docs = sorted(pathlib.Path("plans").glob("*.md")) + sorted(pathlib.Path(".").glob("*.md"))
    seen = 0
    for doc in docs:
        for line_no, argv in _documented_command_lines(doc):
            seen += 1
            try:
                _parser().parse_args(argv)
            except SystemExit as exc:  # argparse exits 2 on an unknown flag
                raise AssertionError(
                    f"{doc}:{line_no} documents `impress-a {' '.join(argv)}`, which the CLI "
                    f"refuses (SystemExit {exc.code})"
                ) from None
    assert seen >= 4, (
        f"only {seen} documented command lines found; the extractor has stopped matching the "
        f"procedure blocks rather than the procedure having shrunk"
    )
