"""The decision frontend: two contracts - Specifier and Planner - and several control models.

This file stays empty of re-exports on purpose. `registry.py` imports every model, and
importing the agentic halves costs langgraph - so re-exporting here would make
`import impress_a.policy` pay for a graph library that `impress-a tools` never uses.

The single `ControlPolicy` contract and everything that implemented it were deleted in
phase 11: `decide(obs) -> Decision` answered "what should the campaign be trying to achieve"
and "which tool should run next" in one call, which is exactly what made it impossible to say
which half a control model was good at.

Where things are:

* `specifier.py` - the `Specifier` contract: `initial_spec` / `revise` / `satisfied`
* `planner.py`   - the `Planner` contract: `plan` / `replan`
* `registry.py`  - **which models exist**, their status, and how each half is built
* `specifiers/`  - one module per model: `agentic` (A), `oracle` (B), `external` (C),
                   `explicit` (D), `replay`
* `planners/`    - the same, plus `_knobs.py`, which reads what a tool's parameters are for
* `reasoning.py` - the seam a half calls a model through: bounded, schema-checked, corrective
* `llm.py`       - the live OpenAI-compatible client, and the profiles that name a model
* `oracle.py`    - `RehearsalOracle`, the network-free stand-in model B runs by default
* `wrappers.py`  - `LoggingSpecifier`, `StageGuard`, and the null halves
"""
