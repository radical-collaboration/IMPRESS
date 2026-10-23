# Academy for Task Agents — Standing Notes

**Status:** roadmap note, not a decision.

LangGraph owns the main loop and campaign state. Academy was deliberately left open for the
*task-agent* layer. This records the evidence relevant to that future evaluation so it is not
re-derived, and the three properties of the current design that keep the option available.

---

## 1. What was decided, and what was not

| Layer | Decision | Status |
|---|---|---|
| Outer loop and campaign state | **LangGraph** | Decided |
| Control model A's four-node loop | **LangGraph** `StateGraph` | Implemented — `src/impress_a/policy/agentic.py` |
| **Task agents** (per-tool: pre-process → parameterize → execute → post-process) | **Open** | Currently plain Python classes (`src/impress_a/tools/agent.py`) |

The task-agent layer is where Academy would attach, if anywhere. It is deliberately the
part of the design with the least framework commitment: `TaskAgent` is an ordinary class
with four overridable phases and no dependency on LangGraph, asyncflow, or anything else.

## 2. What Academy is

Argonne's actor-based framework for distributed multi-agent systems — persistent logical
agents that communicate peer-to-peer, as opposed to LangGraph's graph-of-nodes-over-shared-
state model. The two solve different problems and are not substitutes.

## 3. Evidence gathered

### ChemGraph — the strongest working reference
A survey of adjacent projects found `ChemGraph`'s `src/chemgraph/academy/` to be a complete actor-based runtime
layered *above* its LangGraph agent: `academy/core/agent.py` defines a
`ChemGraphLogicalAgent` using `from academy.agent import Agent, action, loop`, which
internally calls ChemGraph's LangGraph single-agent turn logic (`run_academy_turn`) while
communicating peer-to-peer via `academy/peer_protocol.py`, with its own event log,
observability and dashboard. ChemGraph declares both `academy-py` and `parsl` as extras.

**The transferable point:** ChemGraph does not choose between LangGraph and Academy. It
uses LangGraph for *reasoning within an agent* and Academy for *distribution across
agents* — precisely the split this project has left open.

### flowgentic — imports it, but the path does not work
flowgentic depends on `academy-py` and imports `academy.agent` (6 occurrences), but its
Academy path is **broken or dead**: examples do not run and the module is effectively
unimported. Its `src/flowgentic/academy.py` nonetheless
shows a workable, if unpolished, direct pattern for **Academy-agent-action-as-asyncflow-
task** that could be adapted without depending on the package.

### No prior art drives real work with Academy
No reviewed codebase on this stack demonstrates Academy driving real work. Adopting it
would be pathfinding.

## 4. What would make Academy worth adopting

Concrete triggers, in rough order of likelihood:

1. **Task agents need to be long-lived and stateful.** Today they are constructed per
   invocation and discarded. A task agent that holds an expensive resource across
   invocations — a loaded model checkpoint, a warm MSA cache, a persistent tool session —
   is an actor, and Academy models actors natively.
2. **Task agents need to talk to each other.** The current design routes everything
   through the manager. If, say, a ligand-parameterization agent needed to negotiate
   directly with an MD-setup agent, peer-to-peer messaging becomes the natural shape.
3. **Campaigns need to span allocations or sites.** Academy's distribution story is its
   reason for existing. A campaign coordinating agents across Polaris *and* an ACCESS
   machine is the case LangGraph does not address at all.
4. **Many concurrent campaigns need supervision.** A fleet-level supervisor over many
   `CampaignManager` instances is an actor-system problem, not a graph problem.

## 5. What would argue against it

- **The current layer is not complex enough to need it.** Four phases, no inter-agent
  communication, no persistence between invocations. Academy would add a runtime for
  capability we do not use.
- **No working precedent on our stack** (§3). ChemGraph's is the only real one, and it is
  computational chemistry on Parsl, not asyncflow.
- **It is a second concurrency model.** We already have asyncio + asyncflow's scheduler +
  rhapsody's backends. Adding an actor runtime is a third, and the boundaries between the
  existing three are already where the integration friction lives.
- **The import contract** (`policy ↛ tools`, `compose ↛ exec`) exists to keep layers
  swappable. An actor runtime that spans layers would erode it.

## 6. How the current design keeps the door open

Three properties, all deliberate and all currently true:

1. **`TaskAgent` has no framework dependency.** It is a plain class; `execute()` dispatch
   lives in the execution layer, not in the adapter.
2. **`ToolSpec.agent` already declares the agent *kind*** (`deterministic` | `llm`).
   Adding `academy` is a third value, not a new mechanism.
3. **`ToolSpec.entry` resolves a dotted path at runtime**, so an Academy-backed agent is
   registered exactly like any other — no composer, validator or manager change.

## 7. Recommended evaluation, when the time comes

1. Install `academy-py` and establish whether flowgentic's Academy bridge can be revived
   or must be rewritten. Static analysis suggests rewritten; confirm by running it.
2. Read `ChemGraph/src/chemgraph/academy/` in full. It is the only working reference.
3. Prototype **one** long-lived task agent — a model-serving agent holding a checkpoint
   across invocations is the clearest candidate — and measure against the current
   construct-per-invocation approach.
4. Decide on evidence from that prototype, not on architectural preference.

**Do not** adopt Academy for the outer loop. That question is settled: LangGraph owns the
main loop and state.
