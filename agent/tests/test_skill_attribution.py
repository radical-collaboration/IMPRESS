"""Which SKILL.md a spec is checked against: the directory it was staged from.

`_load_toolkit`'s referential-integrity check attributed a spec to a directory by the spec's
`toolkit` **field**, which is not the directory and -- because of gate 6 -- must not be. A
surrogate twin declares `toolkit: mock` so that `compose/validate.py:_g6_delivery` classifies
it as mock (it matches that string exactly, never a directory name), while living in its own
directory so its ids cannot collide with this package's. The old filter therefore told
`toolkits/mock/SKILL.md` that it had to mention every twin anywhere declaring `toolkit: mock`.

**Jointly unsatisfiable with gate 6 for any toolkit outside `toolkits/mock/`, and measured: six
such lines on every load of one downstream project.** It was order-dependent too -- a foreign
twin shows up in `self.specs` only if its root was searched first -- which is the kind of bug
that reads as flaky rather than wrong.

Cosmetic, in that it appends to `errors` and never refuses. That is the argument *for* fixing
it: `errors` was permanently non-empty for anyone using the documented extension mechanism, and
a signal that is always on is not a signal.
"""
from __future__ import annotations

from pathlib import Path

from impress_a.tools.registry import Registry

#: The four sections `REQUIRED_SKILL_SECTIONS` demands, plus the tool list. Spelled out
#: rather than minimal, because a SKILL.md missing one raises `ToolkitLoadError` and the
#: toolkit registers nothing -- which would make every assertion below pass for the wrong
#: reason. The first draft of this file left two out and did exactly that.
SKILL = """# {name}

## Purpose
p

## Canonical sequences
{tools}

## Cost posture
c

## Pitfalls
p
"""

SPEC = """id: {tid}
toolkit: {toolkit}
version: "0.1"
pattern: P2
entry: impress_a.tools.mock_agents.MockAgent
resources: {{cores: 1, walltime_s: 10}}
inputs: {{}}
outputs: {{thing: {{type: Backbone}}}}
parameters: {{}}
metrics: [m]
qc_gates:
  - {{id: output_present, params: {{key: result}}}}
cost_model: {{unit: invocation, cost: {{cpu_hours: 0.001}}}}
"""


def _toolkit(root: Path, name: str, tools: dict[str, str], mention: list[str] | None = None):
    """One toolkit directory. `tools` maps tool id -> the `toolkit` FIELD it declares."""
    d = root / name
    (d / "tools").mkdir(parents=True)
    for tid, field in tools.items():
        (d / "tools" / tid).mkdir()
        (d / "tools" / tid / "spec.yaml").write_text(SPEC.format(tid=tid, toolkit=field))
    listed = tools if mention is None else mention
    (d / "SKILL.md").write_text(
        SKILL.format(name=name, tools="\n".join(f"- `{t}`" for t in listed)))
    return d


def _errors(root: Path, monkeypatch) -> list[str]:
    """Load only `root`, with the package's own default root suppressed.

    `candidate_paths` always appends a root relative to `tools/registry.py`, so a test that
    did not suppress it would load this package's real toolkits too and measure them.
    """
    monkeypatch.setattr(Registry, "candidate_paths",
                        staticmethod(lambda explicit=None: [Path(explicit)]))
    return Registry().load(root).errors


def test_a_twin_in_another_directory_is_not_charged_to_this_ones_skill_md(tmp_path,
                                                                         monkeypatch):
    """The measured false positive, reproduced at its smallest.

    Two directories, both staging specs that declare `toolkit: mock`, each SKILL.md mentioning
    only its own.

    **`aa_surrogate`, and the name is load-bearing.** Toolkits load in sorted order and the old
    filter read `self.specs`, so a surrogate sorting AFTER `mock/` was not yet registered when
    `mock/` was checked and produced no error at all. The first draft of this test used
    `zz_surrogate` and passed against the bug. Which is the bug's other half -- see the next
    test -- and the reason a downstream project saw six lines rather than none: its own root
    was searched first.
    """
    root = tmp_path / "toolkits"
    _toolkit(root, "aa_surrogate", {"mock_foreign": "mock"})
    _toolkit(root, "mock", {"mock_native": "mock"})

    errors = _errors(root, monkeypatch)
    assert errors == [], errors


def test_the_order_the_roots_load_in_cannot_change_the_answer(tmp_path, monkeypatch):
    """The old filter read `self.specs`, so it saw only what had already loaded.

    `aa_surrogate` sorts before `mock` and `zz_surrogate` after it, so under the old code the
    first produced an error and the second did not -- same two toolkits, same declarations.
    """
    root = tmp_path / "toolkits"
    _toolkit(root, "aa_surrogate", {"mock_early": "mock"})
    _toolkit(root, "mock", {"mock_native": "mock"})
    _toolkit(root, "zz_surrogate", {"mock_late": "mock"})

    errors = _errors(root, monkeypatch)
    assert errors == [], errors


def test_a_tool_missing_from_its_own_skill_md_still_errors(tmp_path, monkeypatch):
    """The check is a good check; only its attribution was wrong.

    A guard rather than a demonstration: this passes before the change too, which is the
    point of having it.
    """
    root = tmp_path / "toolkits"
    _toolkit(root, "mock", {"mock_a": "mock", "mock_b": "mock"}, mention=["mock_a"])

    errors = _errors(root, monkeypatch)
    assert len(errors) == 1, errors
    assert "mock_b" in errors[0]
    assert errors[0].startswith("mock: SKILL.md does not mention tool"), errors[0]


def test_a_toolkit_whose_ids_are_foreign_is_now_checked_against_its_own_skill_md(tmp_path,
                                                                                monkeypatch):
    """What the field filter could never do, rather than merely what it did wrongly.

    A directory named `zz_surrogate` holding specs that declare `toolkit: mock` matched the old
    filter for no directory at all, so its own SKILL.md was never checked. One downstream
    project wrote a replacement test for exactly this gap.
    """
    root = tmp_path / "toolkits"
    _toolkit(root, "zz_surrogate", {"mock_x": "mock", "mock_y": "mock"}, mention=["mock_x"])

    errors = _errors(root, monkeypatch)
    assert len(errors) == 1, errors
    assert "mock_y" in errors[0]
    assert errors[0].startswith("zz_surrogate: SKILL.md does not mention tool"), errors[0]


def test_the_packages_own_toolkits_load_without_a_referential_error():
    """Against the real tree, because the point is that `errors` is a usable signal now.

    Also a guard rather than a demonstration -- this package ships no toolkit whose `toolkit`
    field disagrees with its directory, which is exactly why the defect was invisible here and
    was found by someone using the documented extension mechanism.
    """
    reg = Registry().load()
    assert reg.specs, "the default root resolved nothing; this test would prove nothing"
    assert [e for e in reg.errors if "does not mention tool" in e] == [], reg.errors
