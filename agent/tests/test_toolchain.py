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
import tomllib
import types

import impress

import impress_a

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


def test_the_aucam_extra_pins_a_commit_not_a_branch():
    """A branch pin reinstalls something different next week, and moves this tier under us.

    `aucam` has no PyPI release, so the same rule the `agentbridge` extra states applies: pin
    the commit, name the branch in the comment beside it. The branch `aucam-v2` pointed at
    this commit when the extra was written, and that is a fact about a moment, not a version.
    """
    extra = _config()["project"]["optional-dependencies"].get("aucam")
    assert extra, "no `aucam` optional-dependency - the adapter's dependency is undeclared"
    spec = extra[0]
    assert spec.startswith("aucam @ git+"), f"expected a git requirement, got {spec!r}"
    rev = spec.rsplit("@", 1)[1]
    assert len(rev) == 40 and all(c in "0123456789abcdef" for c in rev), (
        f"the aucam pin is {rev!r}, which is not a 40-character commit sha. A branch or tag "
        f"here means `pip install -e .[aucam]` resolves to different code over time.")


def test_aucam_imports_as_src_aucam_and_not_from_this_repository():
    """AuCaM's importable name is the generic `src`, and this repository has two of those.

    Its distribution is named `aucam`, but `[tool.setuptools.packages.find]` upstream declares
    `include = ["src*"]`, so what lands on `sys.path` is a top-level package called `src` -
    which setuptools itself warns about at install time. IMPRESS has `src/` at the root and
    `agent/src/` under it, neither a package, so running from either directory puts a
    same-named namespace portion ahead of AuCaM's on the path. It resolves today because a
    regular package beats a namespace portion; that is a property of the import system worth
    pinning rather than reasoning about again, because the failure mode is an ImportError that
    blames the adapter for a packaging decision made in another repository.
    """
    import pytest
    aucam = pytest.importorskip("src.aucam", reason="the aucam extra is not installed")
    resolved = pathlib.Path(aucam.__file__).resolve()
    assert not resolved.is_relative_to(REPO), (
        f"`src.aucam` resolved to {resolved}, inside this repository - one of our own `src/` "
        f"directories captured the name instead of AuCaM's package")
    for name in ("WorkflowConfig", "WorkflowReporter", "WorkflowResult", "CampaignDecision"):
        assert hasattr(aucam, name), f"src.aucam does not export {name}"


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
    three siblings would make every sentence in `docs/impress-a/decisions/`, `plans/done/` and
    `CLAUDE.md` that names them wrong, for no runtime benefit. `UP042` (`StrEnum`) is declined
    because it changes what `str()` of a member returns, and those strings reach provenance.
    """
    ignored = _config()["tool"]["ruff"]["lint"]["ignore"]
    assert set(ignored) == {"UP007", "UP045", "N818", "UP042"}, (
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
    # A letter, not a placeholder: `--model` is a `choices=` argument, so these are the one
    # kind of value the parser does inspect. `${MODEL}` is the arm; `${_SIDECAR_MODEL}` is
    # the model arm C's caller drives with.
    fragment = re.sub(r"\$\{MODEL\}", "D", fragment)
    fragment = re.sub(r"\$\{_SIDECAR_MODEL(:-[A-Za-z]+)?\}", "B", fragment)
    # An array expansion is the EMPTY case: `"${PROFILE_ARGS[@]}"` contributes no words when
    # no profile is named, which is the form every arm but B and C submits. The populated
    # form is a flag pair the parser sees spelled out in
    # `test_the_launcher_forwards_a_model_profile_to_every_reasoning_surface`, because a
    # placeholder standing in for "zero or two words" could not check either one.
    fragment = re.sub(r'"?\$\{[A-Za-z_][A-Za-z0-9_]*\[[@*]\]\}"?', "", fragment)
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


def test_the_launcher_sends_arm_c_to_serve_and_everything_else_to_run():
    """`impress-a run --model C` is refused, so the launcher must not reach it.

    Model C means an external caller steers the campaign; `run` attaches no control plane and
    the CLI refuses rather than timing out and reporting a model-D campaign as model C
    (backlog C6). The launcher used to default `IMPRESS_A_COMMAND` to `run` with no reference
    to the arm, so `sbatch --array=0-3` would have had argparse kill arm C at launch with the
    other three arms already queued - one submission spent to discover a flag, and the reader
    sent to the environment rather than to the cause.

    An exported command still wins, because that is how `delta_validate_tasks.sh` selects
    `validate-tasks` for any arm.
    """
    import subprocess

    text = pathlib.Path("scripts/delta_gpu_run.sh").read_text()
    # The decision itself, lifted from the file and run, so this cannot pass against a
    # launcher that no longer makes it. Everything between the arm-C guard and the default.
    start = text.index('if [ -z "${IMPRESS_A_COMMAND:-}" ]')
    end = text.index('IMPRESS_A_COMMAND="${IMPRESS_A_COMMAND:-run}"', start)
    block = text[start:end] + 'IMPRESS_A_COMMAND="${IMPRESS_A_COMMAND:-run}"\n'

    def resolved(model: str, exported: str = "") -> str:
        script = (f'MODEL={model}\n'
                  + (f'IMPRESS_A_COMMAND={exported}\n' if exported else "")
                  + block + 'echo "${IMPRESS_A_COMMAND}"\n')
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                             check=True)
        return out.stdout.strip().splitlines()[-1]

    assert resolved("C") == "serve", "arm C must serve; `run --model C` is refused"
    for letter in ("A", "B", "D"):
        assert resolved(letter) == "run", f"arm {letter} has no control plane to serve"
    assert resolved("C", "validate-tasks") == "validate-tasks", \
        "an exported command must still win - delta_validate_tasks.sh depends on it"


def test_the_launcher_forwards_a_model_profile_to_every_reasoning_surface():
    """A profile named for the job must reach the process that does the reasoning.

    Three surfaces take `--model-profile` and all three are reachable from this launcher:
    `run` (arms A and B), `serve` (arm C's executor) and `control` (arm C's caller, which is
    where arm C's reasoning actually happens). Forwarding it to some of them would be the
    quiet failure the flag exists to prevent - a campaign reported as a live arm that ran a
    rehearsal or a rule cascade.
    """
    from impress_a.cli import _parser

    text = pathlib.Path("scripts/delta_gpu_run.sh").read_text()
    assert 'PROFILE_ARGS=( --model-profile "${IMPRESS_A_MODEL_PROFILE}" )' in text, \
        "the launcher must build the flag pair from IMPRESS_A_MODEL_PROFILE"
    for surface in ("run", "serve", "control"):
        assert f'{surface} ' in text and '"${PROFILE_ARGS[@]}"' in text, \
            f"{surface} must receive PROFILE_ARGS"
    # And the populated form parses on each surface, which the launcher's own argv lines
    # cannot show because an unset array expands to nothing.
    _parser().parse_args(["run", "spec.yaml", "--model", "A", "--model-profile", "beam"])
    _parser().parse_args(["serve", "spec.yaml", "--model", "C", "--model-profile", "beam"])
    _parser().parse_args(["control", "--connect", "http://127.0.0.1:1", "--campaign", "c",
                          "--model", "B", "--model-profile", "beam"])


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


def test_the_batch_flag_probe_goes_through_the_shim_and_abstains_on_a_crash(monkeypatch,
                                                                            capsys, tmp_path):
    """A tool that never reached its argument parser has said nothing about its arguments.

    This probe ran `run.py` DIRECTLY while the import probe three lines above it ran the same
    file through `MPNN_SHIM`, so the two disagreed about one binary: the shim exits 0, and the
    raw call dies in LigandMPNN's vendored openfold on `np.int`, removed in numpy 1.24. That
    is the documented reason the shim exists and the adapter never calls `run.py` directly.

    The traceback went to stderr, so `helptext` was non-empty and the flags were "not found"
    in it - and the probe reported `installed run.py does not offer --batch_size,
    --number_of_batches - the adapter passes them and would fail inside the job`. Both flags
    are declared (`run.py:846,852`). A FAIL that blocks the whole smoke on §10's zero-FAIL
    gate, naming the wrong component, from the tool written to stop exactly that.

    Two things pinned: the invocation goes through the shim, and a non-zero exit is `None`
    rather than `False`.
    """
    import subprocess

    from impress_a import cli

    # A real `run.py` on disk, because the old probe gated on `run_py.is_file()` and would
    # otherwise emit no row at all - which would make this test pass against it for the wrong
    # reason. The file's contents never matter: every subprocess here is faked.
    (tmp_path / "run.py").write_text("raise SystemExit(1)\n")
    monkeypatch.setenv("MPNN_DIR", str(tmp_path))
    seen: list[list[str]] = []

    # What the raw call actually prints, and the shape that fooled the old probe: output on
    # stderr, no flag names in it, nothing to do with the flags.
    crash = "AttributeError: module 'numpy' has no attribute 'int'.\n"

    def fake(cmd, *a, **kw):
        seen.append([str(c) for c in cmd])
        # `text=` decides str or bytes, and honouring it is what lets this test run against
        # either spelling of the probe rather than only against the one it was written for.
        empty, err = ("", crash) if kw.get("text") else (b"", crash.encode())
        return types.SimpleNamespace(returncode=1, stdout=empty, stderr=err)

    monkeypatch.setattr(subprocess, "run", fake)
    cli.preflight(cli.load_spec("campaigns/delta-small-molecule-arms-smoke.yaml"))
    out = capsys.readouterr().out

    mpnn_calls = [c for c in seen if any("run.py" in part or "mpnn_run" in part for part in c)]
    assert mpnn_calls, "the probe never invoked LigandMPNN at all"
    for call in mpnn_calls:
        assert any("mpnn_run.py" in part for part in call), \
            f"LigandMPNN invoked outside the shim: {call} - the raw call dies on np.int"

    flags = [ln for ln in out.splitlines() if "ligandmpnn batch flags" in ln]
    assert flags, "the batch-flags row vanished"
    assert "[FAIL]" not in flags[0], \
        "a crash before argparse was reported as a missing flag - the diagnosis names the " \
        "wrong component and blocks the smoke"
    assert "[??" in flags[0] or "undetermined" in flags[0].lower(), \
        f"a crash must read as undetermined, got: {flags[0]}"


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

    # `campaigns/` is here because `campaigns/README.md` is a procedure document too: it
    # tells a reader which `impress-a` lines to run against the laptop surrogate, and a flag
    # argparse refuses there is a first command that fails - cheaper than an allocation, and
    # the same defect.
    docs = (sorted(pathlib.Path("plans").glob("*.md"))
            + sorted(pathlib.Path("campaigns").glob("*.md"))
            + sorted(pathlib.Path(".").glob("*.md")))
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


def test_every_documented_sbatch_entry_point_requests_its_own_resources():
    """`#SBATCH` is parsed out of the file sbatch is handed, and nothing else.

    `delta_validate_tasks.sh` is a wrapper: it sets `IMPRESS_A_COMMAND` and `exec`s
    `delta_gpu_run.sh`, which is the right shape - everything that makes a Delta job work was
    bought one burned allocation at a time and two copies would be two things to keep in step.
    But Slurm reads directives at SUBMIT time, out of the submitted file, and the `exec`
    happens at RUN time. So none of `delta_gpu_run.sh`'s ten directives applied to a job
    submitted through the wrapper, and the documented step-1 command died at submit with

        sbatch: error: Jobs requesting no GPU resources must be submitted under CPU type
        accounts

    - a message about the ACCOUNT, for a missing GPU request, on the one step the entire trust
    assertion cites as its evidence. It had never been submitted.

    So: every script a document tells someone to `sbatch` must itself request what it needs.
    `--time` and `--partition` are deliberately left to the command line in at least one of
    them, and are not checked here; the resource shape and `--output` are not choices - the
    EXIT trap looks for `impress_a_<jobid>.out` by that exact name.
    """
    import re

    texts = {p: p.read_text() for p in
             sorted(pathlib.Path("plans").glob("*.md")) + sorted(pathlib.Path(".").glob("*.md"))
             + sorted(pathlib.Path("scripts").glob("*.sh"))}
    entry_points = set()
    for text in texts.values():
        # Join `\` continuations FIRST. Every documented submission wraps across three lines,
        # so a line-bounded match finds only the one-line examples - and silently passes the
        # wrapper it was written to catch. That is the same shape of mistake as the bug.
        joined = re.sub(r"\\\n\s*", " ", text)
        entry_points.update(re.findall(r"sbatch[^\n|]*?(scripts/[\w.-]+\.sh)", joined))

    assert {"scripts/delta_gpu_run.sh", "scripts/delta_validate_tasks.sh"} <= entry_points, (
        f"the extractor stopped matching the documented submissions; found {entry_points}"
    )
    for rel in sorted(entry_points):
        script = pathlib.Path(rel)
        assert script.is_file(), f"{rel} is documented for sbatch but does not exist"
        directives = "\n".join(ln for ln in script.read_text().splitlines()
                               if ln.startswith("#SBATCH"))
        for needed in ("--gpus-per-node", "--mem", "--cpus-per-task", "--output"):
            assert needed in directives, (
                f"{rel} is documented as `sbatch {rel} ...` but declares no {needed}. "
                f"Directives are not inherited through `exec` - Slurm has finished parsing "
                f"before this script runs a line."
            )


def test_the_validate_wrapper_refuses_the_same_disagreement_as_the_launcher():
    """The guard has to hold at the hop that reaches the launcher, not only inside it.

    C11 was recorded resolved on the strength of "the wrapper resolves its sibling the same
    way". It did not. `delta_validate_tasks.sh` tried `$IMPRESS_A_DIR` BEFORE
    `$SLURM_SUBMIT_DIR`, so on job 23680592 a stale `IMPRESS_A_DIR=/work/hdd/...` inherited
    through `sbatch --export=ALL` won, and the wrapper exec'd THAT tree's
    `delta_gpu_run.sh` - a copy predating the `validate-tasks` branch, which ignored the
    exported `IMPRESS_A_COMMAND`, fell back to its own `run`/`MODEL=D` defaults, and spent
    19m49s on four A40s running an arm-D campaign where a validation pass was asked for.

    The launcher's own refusal could not help: it lives in the file the wrapper declined to
    run. **A check that only exists in the file you failed to reach is not a check**, which is
    the general lesson and the reason this test exists beside the other one rather than
    inside it.
    """
    import subprocess
    import tempfile

    path = pathlib.Path("scripts/delta_validate_tasks.sh")
    text = path.read_text()
    repo = str(pathlib.Path.cwd())
    # The real script, with only the `exec` replaced - so the resolution under test is the
    # shipped one rather than a copy of it that could drift.
    block = text.replace('exec "${HERE}/delta_gpu_run.sh" "$@"',
                         'echo "RESOLVED=${HERE}"')
    assert "RESOLVED=" in block, "the exec line this test rewrites has moved"

    def run(env: dict[str, str], cwd: str = repo):
        # Written to a file in a directory with no `delta_gpu_run.sh` beside it, which is
        # exactly the position sbatch puts it in: `${BASH_SOURCE[0]}` is the spool copy, the
        # sibling is not there, and the fallback loop is what decides. `bash -c` would leave
        # BASH_SOURCE unset and make the test pass without reaching that loop.
        with tempfile.TemporaryDirectory() as spool:
            script = pathlib.Path(spool) / "slurm_script"
            script.write_text(block)
            return subprocess.run(["bash", str(script), "campaigns/x.yaml"],
                                  capture_output=True, text=True, cwd=cwd,
                                  env={"PATH": "/usr/bin:/bin", **env})

    stale = run({"IMPRESS_A_DIR": "/nonexistent/other-checkout", "SLURM_SUBMIT_DIR": repo})
    assert stale.returncode == 1, (
        "the wrapper accepted an IMPRESS_A_DIR naming another tree - this is job 23680592 "
        f"again: {stale.stdout}")
    assert "different checkout" in stale.stdout

    clean = run({"SLURM_SUBMIT_DIR": repo})
    assert clean.returncode == 0 and f"RESOLVED={repo}/scripts" in clean.stdout, \
        f"the submission directory must win when nothing is inherited: {clean.stdout}"

    agreeing = run({"IMPRESS_A_DIR": repo, "SLURM_SUBMIT_DIR": repo})
    assert agreeing.returncode == 0, "an IMPRESS_A_DIR naming the submitted tree is fine"


def test_the_launcher_refuses_a_checkout_that_is_not_the_one_submitted():
    """A job that cannot say which tree it is running must not run.

    Two things conspired. `${BASH_SOURCE[0]}` is not the repo under sbatch - Slurm copies the
    submitted script to `/var/spool/slurmd/job<ID>/slurm_script` - so the computed fallback
    resolves to the node's spool directory. And `sbatch` exports the submitting environment,
    so an `IMPRESS_A_DIR` in `~/.bashrc` wins over that fallback. The second hid the first:
    every job took the inherited value, which named a DIFFERENT CHECKOUT. Job 22692304's own
    log records `dragon -s /work/hdd/bdyk/hooten1/impress_a/scripts/delta_run_campaign.py` -
    that tree's launcher, runner, campaign spec and package, under this project's name.

    Nothing warned. `git_sha` in the manifest is the other repo's HEAD, which is detectable
    afterwards only by a reader who already suspects it. For a four-arm comparison - an
    argument about code - an arm that ran another tree is not a result to be corrected later.

    So the launcher refuses a disagreement rather than picking a winner, and refuses equally
    when it can locate no checkout at all.
    """
    import subprocess

    text = pathlib.Path("scripts/delta_gpu_run.sh").read_text()
    start = text.index('_from_source="$(cd ')
    block = text[start:text.index('echo "Checkout:', start)] + 'echo "RESOLVED=${IMPRESS_A_DIR}"'
    repo = str(pathlib.Path.cwd())

    def run(env: dict[str, str], cwd: str = repo):
        return subprocess.run(["bash", "-c", block], capture_output=True, text=True,
                              cwd=cwd, env={"PATH": "/usr/bin:/bin", **env})

    stale = run({"IMPRESS_A_DIR": "/nonexistent/other-checkout", "SLURM_SUBMIT_DIR": repo})
    assert stale.returncode == 1, "an inherited IMPRESS_A_DIR from another tree was accepted"
    assert "different checkout" in stale.stdout

    clean = run({"SLURM_SUBMIT_DIR": repo})
    assert clean.returncode == 0 and f"RESOLVED={repo}" in clean.stdout, \
        f"the submission directory must be used when nothing is inherited: {clean.stdout}"

    agreeing = run({"IMPRESS_A_DIR": repo, "SLURM_SUBMIT_DIR": repo})
    assert agreeing.returncode == 0, "an IMPRESS_A_DIR naming the submitted tree is fine"

    lost = run({}, cwd="/tmp")
    assert lost.returncode == 1 and "cannot locate" in lost.stdout, \
        "with no submission dir and no repo under BASH_SOURCE, the launcher must refuse"
