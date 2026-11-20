"""`$IMPRESS_A_GATE_MODULES` - a site's own QC gates, registered in time to be resolved.

`$IMPRESS_A_TOOLKITS` lets a site add a toolkit without forking this package, and
`reference/authoring-tools.md` shows how to write a gate with `@gates.gate`. Those two
together did not work, and the way they failed is the reason this hook exists rather than a
note in the docs:

* `_REGISTRY` is filled by the decorator at **import** time, so an out-of-tree gate exists
  only once its module has run;
* `Registry._load_toolkit` resolves every gate id a spec declares **before** it registers
  anything, and is all-or-nothing;
* `impress-a run` constructs `Registry().load()` with no opportunity for a caller to import
  anything first.

So an out-of-tree toolkit declaring its own gate did not get a gate error - it got **no
toolkit**, including the tools in it that declared nothing unusual, reported as one line in
`reg.errors` with no refusal anywhere. `test_without_the_hook_the_whole_toolkit_is_lost`
pins that, and is the reason the other tests are worth having.

**Every test here spawns a cold interpreter, deliberately.** `_REGISTRY` is module-level
state and the whole question is what is in it *before* the registry loads; a same-process
test would be asserting against a registry some earlier test's import had already filled.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from impress_a.tools import gates

GATE_MODULE = '''\
"""A site's gate, defined outside impress_a - the shape authoring-tools.md documents."""
from impress_a.core.qc import GateOutcome, GateResult
from impress_a.tools import gates


@gates.gate("external_check")
def _external_check(out: dict, params: dict) -> GateResult:
    v = (out.get("metrics") or {}).get("thing")
    ok = v is not None and v >= params.get("min", 0)
    return GateResult(gate="external_check",
                      outcome=GateOutcome.PASS if ok else GateOutcome.FAIL,
                      observed=v, threshold=params.get("min"))
'''

SKILL = """\
# Ext Toolkit

## Purpose
A fixture toolkit outside the package, for `test_gate_modules.py`. It ships `ext_tool`,
which declares the out-of-tree gate `external_check`, and `plain_tool`, which declares only
built-in gates.

## Canonical sequences
    ext_tool
    plain_tool

## Cost posture
Free. Neither tool is ever executed by these tests; only loaded.

## Pitfalls
`external_check` resolves only when `$IMPRESS_A_GATE_MODULES` names the module that
registers it.
"""

SPEC = """\
id: {tid}
toolkit: extkit
version: "0.1"
pattern: P1
resources: {{gpus: 1, cores: 4, walltime_s: 30}}
gpu_portability: {{cuda: proven, hip: unproven, sycl_xpu: plausible}}
outputs:
  designs: {{type: Backbone}}
metrics: [thing]
qc_gates:
{gate_lines}
cost_model: {{unit: invocation, cost: {{gpu_hours: 0.01}}}}
"""

#: Builds a `Registry` in a cold interpreter and reports what it got, so a failure to load
#: is data rather than a traceback. Printed as JSON on the last line of stdout.
DRIVER = """\
import json, sys
from impress_a.tools.registry import Registry
try:
    reg = Registry().load()
except Exception as exc:
    print(json.dumps({"raised": type(exc).__name__, "message": str(exc)}))
    sys.exit(0)
print(json.dumps({"ids": reg.ids(), "errors": reg.errors}))
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A gate module and a two-tool toolkit, neither of them inside this package."""
    (tmp_path / "mods").mkdir()
    (tmp_path / "mods" / "extgates.py").write_text(GATE_MODULE)

    tk = tmp_path / "toolkits" / "extkit"
    (tk / "tools").mkdir(parents=True)
    (tk / "SKILL.md").write_text(SKILL)
    for tid, gate_lines in (
        ("ext_tool", "  - {id: external_check, params: {min: 0.5}}"),
        ("plain_tool", "  - {id: output_present, params: {key: result}}"),
    ):
        (tk / "tools" / tid).mkdir()
        (tk / "tools" / tid / "spec.yaml").write_text(SPEC.format(tid=tid, gate_lines=gate_lines))

    (tmp_path / "driver.py").write_text(DRIVER)
    return tmp_path


def _load(tree: Path, **env: str) -> dict:
    """Run the driver in a cold interpreter with `tree` on the toolkit path.

    The variable name is spelled out here rather than read from `gates`, so that the two
    tests describing the *old* behaviour run unchanged against a tree without this hook -
    which is how they were checked.
    """
    environ = {k: v for k, v in os.environ.items() if k != "IMPRESS_A_GATE_MODULES"}
    environ["IMPRESS_A_TOOLKITS"] = str(tree / "toolkits")
    environ["PYTHONPATH"] = os.pathsep.join(
        [str(tree / "mods"), *([p] if (p := os.environ.get("PYTHONPATH")) else [])])
    environ.update(env)
    proc = subprocess.run([sys.executable, str(tree / "driver.py")], env=environ,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_spec_may_declare_a_gate_this_package_does_not_ship(tree: Path) -> None:
    got = _load(tree, IMPRESS_A_GATE_MODULES="extgates")
    assert "ext_tool" in got["ids"]
    assert not [e for e in got["errors"] if "extkit" in e], got["errors"]


def test_without_the_hook_the_whole_toolkit_is_lost(tree: Path) -> None:
    """The defect this closes, measured: `plain_tool` declared nothing out of the ordinary."""
    got = _load(tree)
    assert "ext_tool" not in got["ids"]
    assert "plain_tool" not in got["ids"], "all-or-nothing: an innocent sibling went too"
    assert [e for e in got["errors"] if "external_check" in e], got["errors"]


def test_the_lost_toolkit_was_only_ever_reported_as_an_error_line(tree: Path) -> None:
    """Why this is a hook and not a docs note: nothing refuses, so nothing stops."""
    got = _load(tree)
    assert "raised" not in got
    assert len([e for e in got["errors"] if "extkit" in e]) == 1


def test_an_unimportable_module_raises_rather_than_losing_a_toolkit(tree: Path) -> None:
    got = _load(tree, IMPRESS_A_GATE_MODULES="no_such_gate_module")
    assert got.get("raised") == "GateModuleError"
    assert "no_such_gate_module" in got["message"]
    assert gates.GATE_MODULES_ENV in got["message"]


def test_a_module_that_raises_on_import_names_the_cause(tree: Path) -> None:
    """The failure a typo in the module's own body produces, which is not a missing module."""
    (tree / "mods" / "brokengates.py").write_text("raise RuntimeError('half-written')\n")
    got = _load(tree, IMPRESS_A_GATE_MODULES="brokengates")
    assert got.get("raised") == "GateModuleError"
    assert "RuntimeError: half-written" in got["message"]


def test_several_modules_load_and_the_separator_is_the_path_separator(tree: Path) -> None:
    (tree / "mods" / "moregates.py").write_text(GATE_MODULE.replace("external_check", "other"))
    got = _load(tree, IMPRESS_A_GATE_MODULES=os.pathsep.join(["extgates", "moregates"]))
    assert "ext_tool" in got["ids"]


# -- the parsing, which does not need a process ----------------------------------------

def test_an_unset_variable_names_nothing() -> None:
    assert gates.load_modules(explicit="") == []
    assert gates.load_modules(explicit=os.pathsep) == []


def test_whitespace_and_empty_entries_are_dropped() -> None:
    assert gates.load_modules(explicit=f" json {os.pathsep}{os.pathsep} math ") == ["json", "math"]


def test_importing_twice_is_harmless() -> None:
    """`Registry().load()` is called from a dozen places; `sys.modules` makes this a no-op."""
    before = set(gates.known())
    for _ in range(3):
        gates.load_modules(explicit="json")
    assert set(gates.known()) == before


def test_an_unknown_gate_id_says_where_an_out_of_tree_gate_comes_from() -> None:
    with pytest.raises(KeyError, match=gates.GATE_MODULES_ENV):
        gates.get("definitely_not_a_gate")
