"""Toolkit discovery and registration.

Loading is VALIDATING: a malformed spec, a parameter range excluding its own default, a
gate referencing an unimplemented check, or a skill doc missing required sections is a
load-time error, not a runtime surprise. A toolkit that does not load is reported and
disabled rather than silently half-registered.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

import yaml

from . import gates
from .spec import ToolSpec

REQUIRED_SKILL_SECTIONS = ("Purpose", "Canonical sequences", "Cost posture", "Pitfalls")


class ToolkitLoadError(Exception):
    pass


class Registry:
    def __init__(self) -> None:
        self.specs: dict[str, ToolSpec] = {}
        self.skills: dict[str, str] = {}
        self.errors: list[str] = []
        #: Where `load()` looked, and where it would have looked. Both, because an empty
        #: registry's only useful diagnosis is the difference between them: a root that does
        #: not exist and a root that exists and held nothing are different mistakes.
        self.attempted: list[Path] = []
        self.searched: list[Path] = []

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def candidate_paths(explicit: str | Path | None = None) -> list[Path]:
        """Every root `load()` would look in, **whether or not it exists**.

        Kept beside `search_paths` because the filtered list cannot answer the one question an
        empty registry raises: *where did you look?* The last entry is relative to this file,
        so it exists only in a source checkout and is absent from a wheel install -- which is
        exactly how a deployment ends up with no tools and no idea why.
        """
        out: list[Path] = []
        if explicit:
            out.append(Path(explicit))
        if env := os.environ.get("IMPRESS_A_TOOLKITS"):
            out += [Path(p) for p in env.split(os.pathsep) if p]
        out.append(Path(__file__).resolve().parents[3] / "toolkits")
        return out

    @staticmethod
    def search_paths(explicit: str | Path | None = None) -> list[Path]:
        return [p for p in Registry.candidate_paths(explicit) if p.is_dir()]

    def load(self, explicit: str | Path | None = None) -> Registry:
        # Before anything resolves a gate id, because `_load_toolkit` resolves every id a
        # spec declares and is all-or-nothing: a toolkit naming a gate this package does not
        # ship registers NOTHING. `$IMPRESS_A_GATE_MODULES` is how such a gate gets into the
        # registry in time, and an unimportable name there raises rather than reading as a
        # toolkit that quietly went missing.
        gates.load_modules()
        # Recorded rather than recomputed: `$IMPRESS_A_TOOLKITS` can change under a long-lived
        # process, and a refusal that re-reads the environment would name roots other than the
        # ones it actually searched.
        self.attempted = self.candidate_paths(explicit)
        self.searched = [p for p in self.attempted if p.is_dir()]
        for root in self.searched:
            for tk_dir in sorted(p for p in root.iterdir() if p.is_dir()):
                try:
                    self._load_toolkit(tk_dir)
                except Exception as exc:  # a bad toolkit is disabled, not fatal
                    self.errors.append(f"{tk_dir.name}: {exc}")
        return self

    def _load_toolkit(self, d: Path) -> None:
        staged: dict[str, ToolSpec] = {}
        skill = d / "SKILL.md"
        if skill.exists():
            text = skill.read_text()
            missing = [s for s in REQUIRED_SKILL_SECTIONS if s.lower() not in text.lower()]
            if missing:
                raise ToolkitLoadError(f"SKILL.md missing sections {missing}")
            self.skills[d.name] = text
        tool_specs = sorted((d / "tools").glob("*/spec.yaml")) if (d / "tools").is_dir() else []
        for spec_file in tool_specs:
            spec = ToolSpec(**yaml.safe_load(spec_file.read_text()))
            for g in spec.qc_gates:
                gates.get(g.id)  # raises if unimplemented
            if spec.id in self.specs or spec.id in staged:
                raise ToolkitLoadError(f"duplicate tool id {spec.id!r}")
            staged[spec.id] = spec
        # all-or-nothing: a toolkit that fails anywhere registers nothing
        self.specs.update(staged)
        # Referential integrity: every tool THIS DIRECTORY staged must be mentioned in its
        # own SKILL.md.
        #
        # Over `staged`, not over `self.specs` filtered by the spec's `toolkit` FIELD, which
        # is what this did. The field is not the directory, and gate 6 requires that it not
        # be: a surrogate twin must declare `toolkit: mock` to be classified mock
        # (`compose/validate.py:_g6_delivery` matches that string exactly), while living in
        # its own directory so its ids do not collide. The old filter therefore demanded that
        # `toolkits/mock/SKILL.md` mention every twin anywhere in the world declaring
        # `toolkit: mock` -- jointly unsatisfiable with gate 6 for any toolkit outside this
        # one, and measured: six such lines in `errors` on every load of one downstream
        # project. It was also order-dependent, since a foreign twin only appears in
        # `self.specs` if its root was searched first.
        #
        # Cosmetic, in that it appends to `errors` and never refuses -- which is the argument
        # for fixing it rather than against. `errors` was permanently non-empty for anyone
        # using the documented extension mechanism, and a signal that is always on is not a
        # signal. The narrower loop also means a toolkit whose ids are foreign is now checked
        # against its OWN SKILL.md for the first time, which the field filter never did.
        if d.name in self.skills:
            for tid in sorted(staged):
                if tid not in self.skills[d.name]:
                    self.errors.append(f"{d.name}: SKILL.md does not mention tool {tid!r}")

    # -- access ------------------------------------------------------------
    def get(self, tool_id: str) -> ToolSpec:
        if tool_id not in self.specs:
            raise KeyError(f"unknown tool {tool_id!r}; known: {sorted(self.specs)}")
        return self.specs[tool_id]

    def ids(self) -> list[str]:
        return sorted(self.specs)

    def toolkit_skills(self, enabled: list[str] | None = None) -> str:
        names = enabled or sorted(self.skills)
        return "\n\n---\n\n".join(self.skills[n] for n in names if n in self.skills)

    def agent_for(self, tool_id: str):
        """Resolve the task-agent class named by ToolSpec.entry."""
        spec = self.get(tool_id)
        if not spec.entry:
            from .agent import EchoTaskAgent
            return EchoTaskAgent
        mod, _, cls = spec.entry.rpartition(".")
        return getattr(importlib.import_module(mod), cls)
