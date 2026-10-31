"""The decision frontend: one `ControlPolicy` contract, several control models.

This file stays empty of re-exports on purpose. `registry.py` imports every model, and
importing `agentic` costs langgraph - so re-exporting here would make
`import impress_a.policy` pay for a graph library that `impress-a tools` never uses.

Where things are:

* `base.py`      - the `ControlPolicy` contract: `decide` / `interpret` / `on_rejected`
* `registry.py`  - **which models exist**, their status, and how each is built
* `agentic.py`   - model A, the four-node LangGraph loop
* `oracle.py`    - model B, the heavyweight LLM oracle
* `external.py`  - model C, external caller steering; this is the headless mode
* `explicit.py`  - model D, explicit policies, and `ReplayPolicy`
* `driver.py`    - runs a `decide`-style policy as a `conduct` reasoner
* `wrappers.py`  - composable decorators, and `NullPolicy`
"""
