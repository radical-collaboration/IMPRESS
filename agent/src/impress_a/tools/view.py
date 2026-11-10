"""Project the tool registry into the `core` view a reasoner may hold.

One direction only: `tools -> core`. Nothing in `policy` may import this module, and nothing
here may import `policy`; the view is built by the `runtime` layer when it assembles an
observation, which is the one place that can see both sides.
"""
from __future__ import annotations

from ..core.toolkit import GateCard, ParamCard, PortCard, TaskCard, ToolkitView
from .registry import Registry
from .spec import ToolSpec


def card_for(spec: ToolSpec) -> TaskCard:
    """One `ToolSpec` as the card a reasoner sees.

    Frozen parameters are reported under `frozen` and are absent from `parameters`, so a
    reasoner cannot propose one by accident. `ToolSpec` validation already refuses a spec that
    lists a name in both, so the two sets cannot overlap here.

    **An `operator_only` parameter is reported the same way, and this is the only place that
    happens.** It stays in `ToolSpec.parameters`, so gate 3 and the campaign's own `params:`
    see it exactly as before; it arrives here under `frozen`, so everything that reads the
    card - `_knobs.tunable`, `OraclePlanner`'s prompt and its schema check - treats it as a
    parameter a reasoner may not propose. One seam rather than a flag threaded through four
    readers, because a reader that forgot to check it would be a silent hole in the
    distinction (`ParameterSpec.operator_only` records what that hole costs).
    """
    operator_only = {name: p.operator_only for name, p in spec.parameters.items()
                     if p.operator_only}
    return TaskCard(
        id=spec.id,
        toolkit=spec.toolkit,
        pattern=spec.pattern,
        inputs={name: PortCard(name=name, type=p.type, required=p.required)
                for name, p in spec.inputs.items()},
        outputs={name: PortCard(name=name, type=p.type, required=p.required)
                 for name, p in spec.outputs.items()},
        parameters={name: ParamCard(name=name, type=p.type, default=p.default, min=p.min,
                                    max=p.max, choices=p.choices, trades=p.trades)
                    for name, p in spec.parameters.items() if name not in operator_only},
        frozen={**spec.frozen_parameters, **operator_only},
        metrics=list(spec.metrics),
        gates=[GateCard(id=g.id, role=g.role, metric=(g.params or {}).get("metric"))
               for g in spec.qc_gates],
        declared_cost=dict(spec.cost_model.cost),
        burn_rate=dict(spec.cost_model.burn) or None,
        max_commitment=dict(spec.cost_model.max_commitment) or None,
        declared_walltime_s=spec.resources.walltime_s,
        gpus=spec.resources.gpus,
        cores=spec.resources.cores,
    )


def view_of(registry: Registry, enabled: list[str] | None = None) -> ToolkitView:
    """The whole registry, or just the tools a campaign declared.

    `enabled` is the campaign's own stage list. Narrowing to it matters for more than economy:
    a Specifier shown the mock toolkit on a real campaign can map the Goal onto outputs that
    would then execute mocks on a GPU allocation, which is the failure
    `plans/done/02-real-toolkit.md` records as the headline bug of that work. The `tool_delivery`
    gate in phase 10 refuses that graph outright; this keeps it from being proposed.
    """
    ids = [t for t in registry.ids() if enabled is None or t in set(enabled)]
    tools = {t: card_for(registry.get(t)) for t in ids}
    toolkits = sorted({c.toolkit for c in tools.values()})
    skills = {name: registry.skills[name] for name in toolkits if name in registry.skills}
    return ToolkitView(tools=tools, skills=skills)
