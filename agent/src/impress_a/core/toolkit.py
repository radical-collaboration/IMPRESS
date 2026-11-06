"""The Toolkit, as a reasoner is allowed to see it.

A `core` projection of the tool registry, so a Specifier and a Planner can choose work without
importing `tools`. That import is forbidden - `tests/test_layering.py` asserts it - and the
reason is not tidiness: a reasoner that can reach a tool adapter stops emitting abstract intent
and starts naming adapters, and the control models stop being swappable, which is the whole
point of having four of them.

It replaces `CampaignObservation.available_tools`, which was a list of bare ids. A Planner given
only ids cannot choose by output type, cannot see a parameter's range, and cannot know which
parameters are frozen - so it either guesses or hardcodes, and backlog H3 is what that looked
like in practice: every policy emitted params keyed to `mock_generate` and `mock_design`, the
composer dropped them silently because no such tool was in the graph, and no policy could vary a
real tool's parameters at all.

What is deliberately carried, beyond types and ranges:

* **`trades`** - the one sentence a spec gives about what a parameter costs
  ("coverage vs GPU-hours", "quality vs wall-clock"). It is the only prose a reasoner gets, and
  a Planner that cannot see it is choosing `diffusion_steps` blind.
* **`frozen`**, with its reason. A frozen parameter is one the composer may not propose, and
  gate 3 refuses a graph that tries; surfacing the reason means a reasoner is told why rather
  than discovering it as a rejection.
* **The skill documents.** `Registry.toolkit_skills()` has had no caller since it was written
  (backlog H4), so the guidance written for an agent has never reached one.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .types import ArtifactType, Pattern


class PortCard(BaseModel):
    name: str
    type: ArtifactType
    required: bool = True


class ParamCard(BaseModel):
    name: str
    type: str                       # int | float | str | bool
    default: Any = None
    min: float | None = None
    max: float | None = None
    choices: list[Any] | None = None
    #: What raising this parameter buys and what it costs, in the spec's own words.
    trades: str = ""


class GateCard(BaseModel):
    id: str
    role: str = "integrity"         # integrity | acceptance - decision 0013
    metric: str | None = None


class TaskCard(BaseModel):
    """One Task in the Toolkit: its entry points, interface, outputs and budget demands."""

    id: str
    toolkit: str
    pattern: Pattern
    inputs: dict[str, PortCard] = Field(default_factory=dict)
    outputs: dict[str, PortCard] = Field(default_factory=dict)
    parameters: dict[str, ParamCard] = Field(default_factory=dict)
    #: parameter name -> why it may not be proposed.
    frozen: dict[str, str] = Field(default_factory=dict)
    metrics: list[str] = Field(default_factory=list)
    gates: list[GateCard] = Field(default_factory=list)
    #: Declared, per invocation. Phase 5 adds the measured figures beside these, and phase 8
    #: re-derives them at the eight-sample setting - these feed gates that REFUSE graphs, so
    #: they are deliberately conservative rather than accurate.
    declared_cost: dict[str, float] = Field(default_factory=dict)
    declared_walltime_s: int = 0
    gpus: int = 0
    cores: int = 1

    def produces(self, want: ArtifactType) -> bool:
        """Whether some output port of this tool can satisfy a requirement for `want`.

        Uses the same unification rule the composer and gate 1 use, so a Complex satisfying a
        Backbone requirement reads the same way to a Planner as it does to the validator.
        """
        return any(p.type.unifies_with(want) for p in self.outputs.values())

    def accepts(self, have: ArtifactType) -> bool:
        return any(have.unifies_with(p.type) for p in self.inputs.values())

    @property
    def required_inputs(self) -> list[PortCard]:
        return [p for p in self.inputs.values() if p.required]

    @property
    def acceptance_metrics(self) -> list[str]:
        """Metrics this tool is judged on rather than merely reports (decision 0013)."""
        return sorted({g.metric for g in self.gates
                       if g.role == "acceptance" and g.metric} - {None})


class ToolkitView(BaseModel):
    """Every Task a campaign may use, plus the toolkits' own guidance."""

    tools: dict[str, TaskCard] = Field(default_factory=dict)
    #: toolkit name -> its SKILL.md text.
    skills: dict[str, str] = Field(default_factory=dict)

    def __contains__(self, tool_id: object) -> bool:
        return tool_id in self.tools

    @property
    def ids(self) -> list[str]:
        return sorted(self.tools)

    def producers_of(self, want: ArtifactType) -> list[TaskCard]:
        """Tasks whose output can satisfy a requirement for `want`, in a stable order."""
        return [self.tools[t] for t in self.ids if self.tools[t].produces(want)]

    def reporting(self, metric: str) -> list[TaskCard]:
        """Tasks that declare they report `metric`. How an objective finds its producer."""
        return [self.tools[t] for t in self.ids if metric in self.tools[t].metrics]
