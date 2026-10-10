# Stub — restore "loading is validating"

**Status:** not started. Backlog items D1-D4.

## Problem

`docs/reference/authoring-tools.md:58` promises: *"A malformed spec, a default outside its own
declared range, an unknown QC gate id, a `P1` tool declaring no GPU, or a `SKILL.md` missing a
required section is a load-time error. A toolkit that fails anywhere registers nothing — never a
partial set."*

Four ways that is not true today:

- **`ToolSpec` has no `model_config = {"extra": "forbid"}`.** Pydantic v2 ignores unknown keys, so a
  misspelled field in a `spec.yaml` is dropped in silence. The tool registers, missing whatever the
  author thought they declared.
- **`entry:` is never resolved at load.** `agent_for` imports it on first use, so a bad dotted path
  surfaces mid-campaign as a `ModuleNotFoundError` out of a task rather than as a refusal to register.
- **Entry-point discovery is documented and absent.** `registry.py` has no `importlib.metadata` call,
  so a third-party toolkit installed as a package cannot be found the way the docs say it can.
- **The SKILL.md integrity check is half-built and soft.** "Every tool mentioned must exist" is not
  implemented. The forward direction is a naive substring test whose failure appends to `errors`
  **without disabling the toolkit** — the one place the all-or-nothing rule is broken, and it is
  broken quietly.

## Watch out for

Tightening validation can disable a currently-working toolkit, and a toolkit that fails registers
*nothing*. Check `impress-a tools` still lists all 11 after each change; `reg.errors` must stay empty.

`extra="forbid"` in particular will reject any spec key that was silently tolerated until now —
that is the point, but run it against all five toolkits before assuming the blast radius is zero.

## Verification

`impress-a tools` lists 11 tools with no errors. New tests: a spec with an unknown key fails to load;
a spec with an unresolvable `entry:` fails at load rather than at call time; a SKILL.md mentioning a
tool that does not exist fails; a toolkit that fails anywhere contributes no tools at all.
