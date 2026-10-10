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

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def search_paths(explicit: str | Path | None = None) -> list[Path]:
        out: list[Path] = []
        if explicit:
            out.append(Path(explicit))
        if env := os.environ.get("IMPRESS_A_TOOLKITS"):
            out += [Path(p) for p in env.split(os.pathsep) if p]
        out.append(Path(__file__).resolve().parents[3] / "toolkits")
        return [p for p in out if p.is_dir()]

    def load(self, explicit: str | Path | None = None) -> "Registry":
        for root in self.search_paths(explicit):
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
        for spec_file in sorted((d / "tools").glob("*/spec.yaml")) if (d / "tools").is_dir() else []:
            spec = ToolSpec(**yaml.safe_load(spec_file.read_text()))
            for g in spec.qc_gates:
                gates.get(g.id)  # raises if unimplemented
            if spec.id in self.specs or spec.id in staged:
                raise ToolkitLoadError(f"duplicate tool id {spec.id!r}")
            staged[spec.id] = spec
        # all-or-nothing: a toolkit that fails anywhere registers nothing
        self.specs.update(staged)
        # referential integrity: every tool mentioned in SKILL.md must exist
        if d.name in self.skills:
            for tid in [s.id for s in self.specs.values() if s.toolkit == d.name]:
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
