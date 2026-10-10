# flowgentic (v0.1.0) — Phase 2 middleware exploration

Refcode root (read-only): `<workspace>/impress-a-refcodes/middleware/flowgentic/`
HEAD examined: `6c63601` (2026-01-26)

## 1. What it is

flowgentic is a small "execution bridge" library: it wraps individual LangGraph nodes, tools, and
persistent services so that their bodies execute as `radical.asyncflow` tasks instead of running
in-process. Its own description (`pyproject.toml`): *"A library to enable running agentic frameworks
on HPC environments."* The README is blunter about scope: *"As of now, the only supported path is
LangGraph → RADICAL AsyncFlow."* (`README.md`)

It is not a control loop, not an agent framework, and not an orchestrator in its own right — it is a
decorator/adapter layer that sits between LangGraph (which owns the graph, the state, and the LLM
calls) and `radical.asyncflow.WorkflowEngine` (which owns task submission and the execution backend).

### Actual public API (verified from source)

- `flowgentic.langGraph.main.LangraphIntegration` — the async-context-manager façade. Construct with
  a `BaseExecutionBackend`; on `__aenter__` it creates a `WorkflowEngine` and exposes
  `.execution_wrappers`, `.utils`, `.memory_manager`. (`src/flowgentic/langGraph/main.py:62-96`)
- `flowgentic.langGraph.execution_wrappers.ExecutionWrappersLangraph.asyncflow(...)` — the core
  decorator, parameterized by `AsyncFlowType` (`AGENT_TOOL_AS_FUNCTION`, `FUNCTION_TASK`,
  `SERVICE_TASK`, `EXECUTION_BLOCK`; docs also mention `AGENT_TOOL_AS_MCP`, not in the enum in code —
  see §7/§8). (`src/flowgentic/langGraph/execution_wrappers.py:81-241`)
- `flowgentic.langGraph.base_components.BaseToolRegistry` — abstract base for a per-project tool/task
  registry (`_register_agent_tools`, `_register_function_tasks`, `get_tool_by_name`,
  `get_function_task_by_name`). (`src/flowgentic/langGraph/base_components.py`)
- `flowgentic.langGraph.fault_tolerance.{RetryConfig, LangraphToolFaultTolerance}` — retry/backoff
  wrapper applied uniformly inside `asyncflow(...)`. (`src/flowgentic/langGraph/fault_tolerance.py`)
- `flowgentic.langGraph.memory.{MemoryConfig, MemoryManager, ShortTermMemoryManager,
  LangraphMemoryManager, MemoryEnabledState}` — LangGraph conversation-memory trimming/summarization,
  not HPC/campaign state. (`src/flowgentic/langGraph/memory.py`, 723 lines)
- `flowgentic.langGraph.mutable_graph.MutableGraph` — abstract base for runtime graph
  expand/reduce/update of a `CompiledStateGraph`. (`src/flowgentic/langGraph/mutable_graph.py`)
- `flowgentic.utils.telemetry.introspection.GraphIntrospector` and `report_generator` — records
  supervisor hand-off events and node timings, emits a Markdown execution report + graph PNG.
- `flowgentic.utils.llm_providers.ChatLLMProvider` — thin OpenRouter/Ollama chat-model factory.
- `flowgentic.academy.AcademyIntegration` — a **separate, standalone** bridge from Academy agents to
  `radical.asyncflow`, **not wired into `LangraphIntegration` at all** (see §3, §8).

## 2. Relationship to asyncflow

Direct, hard dependency — not aspirational. `pyproject.toml`:

```
dependencies = [
    "langgraph>=0.6.6",
    "radical.asyncflow @ git+https://github.com/radical-cybertools/radical.asyncflow.git@main",
    ...
    "radical-asyncflow",
    ...
]
```

flowgentic does not extend or subclass `WorkflowEngine`; it **wraps** one instance of it. The
integration point (`src/flowgentic/langGraph/main.py:76-86`):

```python
async def __aenter__(self):
    logger.info("Creating WorkflowEngine for LangGraphIntegration")
    self.flow = await WorkflowEngine.create(backend=self.backend)
    self.execution_wrappers: ExecutionWrappersLangraph = ExecutionWrappersLangraph(
        flow=self.flow, instrospector=self.agent_introspector
    )
    ...
```

`LangraphIntegration.__init__` takes a `BaseExecutionBackend` (the same base class IMPRESS-A would use
for `DragonExecutionBackend` / `ConcurrentExecutionBackend`) and hands it straight to
`WorkflowEngine.create`. Every `asyncflow(...)`-decorated function ultimately calls
`self.flow.function_task(f)` or `self.flow.block(f)` — i.e. it is a pass-through to asyncflow's own
task/block decorators, with a retry wrapper and, for tools, a LangChain `@tool` wrapper stacked on top
(`src/flowgentic/langGraph/execution_wrappers.py:135-141`). So: flowgentic sits **alongside/on top of**
one `WorkflowEngine` instance per `LangraphIntegration` context, not beside it as an independent peer,
and not as a modification of asyncflow itself.

## 3. Which agent framework does it target

`grep` results across `src/` and `pyproject.toml`:

- `langgraph`, `langchain*` — pervasive, the load-bearing dependency. `pyproject.toml` pins
  `langgraph>=0.6.6` plus `langchain`, `langchain-openai`, `langchain-ollama`, `langchain-core`,
  `langchain-community`, `langchain-mcp-adapters`.
- `academy-py` (git dependency on `proxystore/academy`) — present in `pyproject.toml` and imported in
  `src/flowgentic/academy.py`, but **that module is never imported by anything under
  `src/flowgentic/langGraph/`**, and grepping the whole tree for
  `from flowgentic.academy` / `import flowgentic.academy` returns zero hits outside the module itself.
  It is dead code from the package's own perspective — a standalone, unintegrated bridge.
- No hits at all for `autogen`, `smolagents`, `pydantic_ai`. `openai`/`anthropic` appear only
  transitively through `langchain-openai`/OpenRouter, not as first-class targets.

The README's own support matrix confirms this is not an oversight but the stated state:

```
| Agent Framework \ HPC Engine | RADICAL AsyncFlow | Pegasus | Parsl | Academy |
| LangGraph                    |                 ✅ |      🚧 |    🚧 |      🟡 |
| CrewAI                       |                 🚧 |      🚧 |    🚧 |      🚧 |
| AG2                          |                 🚧 |      🚧 |    🚧 |      🚧 |
| OpenAI Agents SDK            |                 🚧 |      🚧 |    🚧 |      🚧 |
```
*"Note: As of now, the only supported path is LangGraph → RADICAL AsyncFlow."* (`README.md`,
also repeated verbatim in `docs/phased_rollout.md`)

**This is a major finding for Part B / Phase 4's LangGraph-vs-Academy question.** flowgentic's
*integrated, tested, documented* path commits to LangGraph. Academy support exists as a separate,
untested module (`src/flowgentic/academy.py`) with **broken example code**: both files under
`examples/academy-integration/` import
`from flowcademy.academy import AcademyIntegrationAcademyIntegration` — a nonexistent package name
(`flowcademy` instead of `flowgentic`) and a mangled, doubled class name
(`AcademyIntegrationAcademyIntegration`) that does not exist anywhere in the source
(`examples/academy-integration/01-actor-client/run.py:16`,
`examples/academy-integration/02-agent-loop/run.py:16`). These examples cannot run as committed. There
is no Makefile target for them (contrast with the LangGraph examples, which all have
`examples-*` targets in `Makefile`), and `tests/integration/test_integration.py` only exercises the
LangGraph examples. Academy integration in flowgentic is aspirational/abandoned-in-progress, not a
working, exercised path — it does **not** "settle" the LangGraph-vs-Academy question in Academy's
favor; if anything it weakly favors LangGraph, since that's the only path with working code, docs, and
tests behind it.

Depth of the LangGraph integration itself: it is a **thin adapter**, not a re-implementation. It does
not touch LangGraph's graph compiler, state machine, or `create_react_agent`; it only wraps individual
node/tool callables before they're handed to `StateGraph` / `create_react_agent`. LangGraph still owns
graph structure, conditional routing, message state, and checkpointing.

## 4. What is an "agent task" here — the actual mechanism

This is the crux question, and the example code shows it precisely. A LangChain **tool** — something
an LLM inside a `create_react_agent` can call — is registered like this
(`examples/.../research_agent/components/utils/actions.py:15-24`):

```python
@self.agents_manager.execution_wrappers.asyncflow(
    flow_type=AsyncFlowType.AGENT_TOOL_AS_FUNCTION
)
async def web_search_tool(query: str) -> str:
    """Search the web for information."""
    await asyncio.sleep(1)
    return f"Search results for '{query}': ..."
```

Registration/invocation/result-return mechanism, from
`src/flowgentic/langGraph/execution_wrappers.py:147-177`:

```python
elif flow_type == AsyncFlowType.EXECUTION_BLOCK: ...
if flow_type in [AsyncFlowType.AGENT_TOOL_AS_FUNCTION]:
    @wraps(f)
    async def tool_wrapper(*args, **kwargs):
        async def _call():
            future = asyncflow_func(*args, **kwargs)   # asyncflow_func = self.flow.function_task(f)
            result = await future
            return result
        return await self.fault_tolerance_mechanism.retry_async(_call, retry_cfg, name=f.__name__)

    langraph_tool = tool(tool_wrapper, description=kwargs.get("tool_description"))
    return langraph_tool
```

So: the decorator (1) registers `f` as an asyncflow `function_task` (`self.flow.function_task(f)`,
`main.py:140`), (2) wraps that in a LangChain `tool(...)` so the LLM can call it by name/schema, and
(3) when the LLM's tool call fires, `tool_wrapper` submits the underlying asyncflow task, awaits its
future (with retry/backoff), and returns the plain result back into the LangGraph message stream. This
tool is then handed to `create_react_agent(model=..., tools=[web_search_tool, ...])`
(`examples/.../nodes.py:86-96`) — i.e. LangGraph's own ReAct loop does the LLM reasoning and tool
selection; flowgentic only intercepts the moment a selected tool executes and reroutes that execution
through `WorkflowEngine`. **Yes — an LLM agent's tool call does become an asyncflow task executed via
the configured execution backend**, with the result value returned straight back into the agent's
message state. That is a real, working mechanism (exercised by the `examples-sequential-research`
Makefile target and `tests/integration/test_integration.py`), not just a sketch.

Separately, whole **LangGraph nodes** (not just tools) can be wrapped as `EXECUTION_BLOCK`, which
similarly offloads the entire node body — including one that itself spins up a `create_react_agent`
and makes several tool calls — as a single asyncflow task/block
(`examples/.../nodes.py:44-72`, `execution_wrappers.py:212-235`). And non-LLM deterministic work is
registered as plain `FUNCTION_TASK`s with no `@tool` wrapper at all (e.g. `validate_input_task`,
`prepare_context_task`, `format_final_output_task` in `actions.py:94-239`) — these are never
LLM-callable; they're invoked directly by node code via
`self.tools_registry.get_function_task_by_name(...)`.

## 5. Mapping onto our design: control policies vs. task agents

flowgentic maps cleanly onto **neither** of Part B's two "agent task" concepts as a whole — it serves
a piece of one of them:

- **Control policies (models A/B/D, the outer-loop decision-maker)**: flowgentic has *no* concept of
  campaign state, decision objects (`ComposeAndRun | Backtrack | RequestHuman | Stop`), a
  `ControlPolicy` protocol, or cycle boundaries. It has no notion of "decide" at all. The closest thing
  — LangGraph's own conditional routing / `create_react_agent` ReAct loop — is LangGraph's job, used
  as-is; flowgentic does not augment or replace it. **flowgentic does not implement or assist with our
  outer control loop.**
- **Task agents (per-tool pre-process → parameterize → execute → post-process)**: this is the closer
  match, but only for the **execute** phase, and only for tools that are (a) LLM-invoked and (b)
  expressed as a LangGraph/LangChain tool. `AGENT_TOOL_AS_FUNCTION` is exactly "make a tool call run as
  an HPC task and return its result to the agent" — i.e. it is a mechanism for the *execute* leg of a
  task agent, wired specifically for the case where an LLM (not our own deterministic/hybrid dispatch
  logic) is the caller. It has no built-in concept of pre-process/parameterize/post-process phases,
  QC gates, `ToolSpec`, or the five validation gates from Part B's composition step — those would all
  have to be built by us, either inside the wrapped function body or around flowgentic's decorator.
  `FUNCTION_TASK` (no `@tool`, no LLM involvement) is closer to our **hybrid/deterministic** task-agent
  case, but again it's just "run this coroutine as an asyncflow task" with retry — no phase structure.

**Conclusion for §5**: flowgentic is not a task-agent framework; it is a narrow execution-routing
utility that a task-agent layer could sit on top of (specifically for the LLM-driven half of hybrid
tool dispatch), but it implements none of the pre/parameterize/post-process phases, none of composition
validation, and nothing about control policies. Treating "agent tasks via flowgentic" as covering
*Part B's task-agent abstraction* would overstate what's here; treating it as covering *control
policies* would be a straightforward category error — there is no code path in flowgentic that composes
a DAG at runtime, evaluates a decision object, or manages campaign state. Conflating flowgentic with
either full concept would be exactly the design error the task description warns about.

## 6. State, memory, checkpointing, HITL

- **Memory** (`src/flowgentic/langGraph/memory.py`, 723 lines, the largest source file): a
  conversation/message-history manager — trimming strategies (`trim_last`, `trim_middle`,
  `importance_based`, `summarize`), LLM-based summarization, importance scoring, "memory health"
  stats. This is **LLM context-window management**, not campaign/provenance state. It has nothing to
  do with our append-only lineage tree, Pareto front, or budget ledger.
- **Checkpointing**: flowgentic adds none of its own. The chatbot/sequential design-pattern docs and
  example `main.py` (`examples/.../research_agent/main.py:19`) use LangGraph's native
  `InMemorySaver` directly (`from langgraph.checkpoint.memory import InMemorySaver`); flowgentic
  doesn't wrap, extend, or persist it beyond what LangGraph itself provides. `docs/features/fault_tolerance.md`
  mentions "persisting workflow state to maintain idempotency" as a bullet point, but there is no
  corresponding code — it's an aspirational line in a one-paragraph doc page with no implementation
  behind it in `fault_tolerance.py` (which contains only `RetryConfig` and retry/backoff logic, no
  persistence).
- **Human-in-the-loop**: no interrupt/escalation primitive anywhere in `src/flowgentic/`. `grep` for
  `human|interrupt|HITL|resume|pause` across `src/` turns up only memory-stats bookkeeping
  (`"human_messages"` counters) and prose in design-pattern docs (e.g. `docs/design_patterns/hierachical.md`
  says a router "requires human intervention to fix routing mistakes" as a *known limitation*, not a
  feature). There is no `RequestHuman`-equivalent. Any HITL escalation path would have to be built by
  us, most likely using LangGraph's own `interrupt`/`Command` primitives directly (flowgentic already
  imports `langgraph.types.Command` in `execution_wrappers.py` for its supervisor hand-off tool,
  `create_task_description_handoff_tool`, `execution_wrappers.py:243-281` — so the underlying LangGraph
  primitive is reachable through the same codebase, just not packaged as a control-policy-level
  `RequestHuman`).

## 7. Examples and tests — most complete worked example

The most complete, actually-runnable example is
`examples/langgraph-integration/design_patterns/sequential/research_agent/` (driven by
`make examples-sequential-research`, and exercised by `tests/integration/test_integration.py:5-9`).
End to end:

1. `main.py` opens `async with LangraphIntegration(backend=ConcurrentExecutionBackend(ThreadPoolExecutor()))`.
2. `ActionsRegistry` (`components/utils/actions_registry.py`, subclassing `BaseToolRegistry`) registers
   two `AGENT_TOOL_AS_FUNCTION` tools (`web_search`, `data_analysis`) and several `FUNCTION_TASK`
   deterministic tasks (`validate_input`, `prepare_context`, `format_final_output`, ...).
3. `WorkflowNodes` builds LangGraph nodes, each wrapped as `EXECUTION_BLOCK`: `preprocess` (calls the
   `validate_input` function task directly), `research_agent` (builds a `create_react_agent` with the
   two agent tools and lets the LLM decide when to call them — each call routes through asyncflow),
   `context_preparation` (deterministic function task), `synthesis_agent` (another ReAct agent with a
   `document_generator` tool), `finalize_output` (deterministic formatting task).
4. `WorkflowBuilder` assembles these into a `StateGraph`, compiled with LangGraph's `InMemorySaver`
   checkpointer.
5. The graph is streamed with `app.astream(...)`, and on completion/failure
   `agents_manager.generate_execution_artifacts(app, __file__, final_state=...)` writes a Markdown
   execution report and a graph PNG via `GraphIntrospector`.

This example demonstrates the full intended shape of the library: LangGraph owns structure/state/
routing/checkpointing; flowgentic owns "make this node or tool's execution go through
`radical.asyncflow`, with retries."

**Test coverage** (`tests/`): `tests/unit/test_memory.py` (285 lines, memory trimming/config),
`tests/unit/test_introspection.py` (111 lines), `tests/unit/test_generator.py` (119 lines, report
generation). **No unit tests exist for `execution_wrappers.py` (the asyncflow bridge itself),
`fault_tolerance.py`, `mutable_graph.py`, or `academy.py`** — i.e. the actual "agent task" mechanism
described in §4 has zero unit-test coverage. `tests/integration/test_integration.py` is 16 lines that
shell out to two Makefile example targets (`examples-sequential-research`, `examples-supervisor-toy`);
these require a live `OPEN_ROUTER_API_KEY` and network access to run, so they don't run in a typical
sandboxed CI check without secrets.

## 8. Maturity, honestly

- **Version 0.1.0**, first PyPI release not yet published (`README.md`: *"PyPI: Not Available"*),
  installed only via git URL.
- Core bridge logic (~2000 lines across `src/flowgentic/`) is functional and exercised by one
  integration test path, but that path needs external LLM credentials to actually run — it is not
  verified in this exploration to execute successfully, only read.
- **Documented-but-not-implemented features**: `AGENT_TOOL_AS_MCP` is documented at length in
  `docs/features/mcp.md` with worked examples, but `AsyncFlowType` in
  `src/flowgentic/langGraph/execution_wrappers.py:81-88` only defines `AGENT_TOOL_AS_FUNCTION`,
  `FUNCTION_TASK`, `SERVICE_TASK`, `EXECUTION_BLOCK` — **no `AGENT_TOOL_AS_MCP` member exists in the
  code**, so any example using it would raise `AttributeError`. This is a doc/code mismatch, not a
  minor omission — MCP support is aspirational.
- **Academy integration** (`src/flowgentic/academy.py`) is unimported dead code with broken examples
  (§3) — pre-release ("🟡") is an accurate self-assessment.
- Loose ends visible directly in source: `execution_wrappers.py`'s own module docstring carries a
  `TBD:` block (*"block for executing the agents in parallel!"*, `execution_wrappers.py:11-13`);
  `fault_tolerance.py:71-84`'s optional-import guards for `httpx`/`aiohttp` `except Exception: raise`
  unconditionally re-raise on `ImportError`, which defeats the "keep imports optional" comment
  immediately above it — a real (if minor) bug in code that ships as the default retry path.
  `main.py` has duplicate imports of `BaseExecutionBackend, WorkflowEngine` (lines 43-44 and 54)
  suggesting an unreviewed merge. Debug `print()` statements remain in shipped wrapper code
  (`execution_wrappers.py:170-172`).
- API stability: the git history (`ec77698 refactor: renamed to MutableGraph instead of DynamicGraph`,
  `84c2d1d feat: docs updated based on wrappers API changes`) shows renames and wrapper-API churn
  within recent history — consistent with 0.1.0, not yet stable.

**At 0.1.0, would depending on this be reasonable or premature?** Premature as a hard dependency for
anything beyond the LangGraph-tool-as-HPC-task pattern it actually implements and tests. Reasonable to
study/borrow the *pattern* (task-wrapping decorator + retry + LangChain `@tool` glue around
`WorkflowEngine.function_task`), and reasonable to depend on narrowly and only if we commit to
LangGraph for the relevant piece of our stack, treating it as an unstable, actively-changing adapter
we'd need to vendor or pin tightly and monitor closely (no PyPI release, git-URL install only).

## Verdict on the hypothesis

The user's hypothesis — "agent tasks via flowgentic" — is **partially supported, but needs a precise
scope, and conflates two different things in Part B's design**:

- flowgentic **does** give a real, working (if lightly tested) mechanism for routing an LLM tool call
  (or a whole LangGraph node) through `radical.asyncflow` as an execution task, with the result
  returned to the agent. If "agent tasks" means *"the execute phase of an LLM-driven task agent, when
  that task agent is expressed as a LangGraph tool,"* the hypothesis holds, with evidence quoted in §4.
- flowgentic **does not** implement or assist with our **control policies** (models A/B/D) at all —
  no decision object, no `ControlPolicy` protocol, no cycle/backtrack/stop semantics. If "agent tasks"
  in the hypothesis was meant to cover the outer-loop decision-maker (e.g. control model A's four-node
  hypothesize→parameterize→run→analyze loop), that is **not** what flowgentic does, and treating it as
  such would be a design error.
- flowgentic **does not** implement pre-process/parameterize/post-process phasing, QC gates, or any of
  the five composition validation gates from Part B — those remain entirely our responsibility whether
  or not we adopt flowgentic.
- flowgentic **commits to LangGraph**, not Academy, as its only working integration — directly relevant
  to Phase 4's open LangGraph-vs-Academy question for control model A. This weakly favors LangGraph
  (working code + tests + docs) over Academy (broken examples, unimported module) *if* we were to reuse
  flowgentic's execution-bridge pattern, but it is weak evidence, not a determination — Academy remains
  fully viable to choose independently of flowgentic, since flowgentic's Academy path was never
  finished.
- `radical.asyncflow` dependency is genuine and direct (not inferred), confirming the "task execution
  via asyncflow" leg of the hypothesis is architecturally consistent with what flowgentic itself relies
  on — flowgentic is a client of asyncflow, same layer relationship IMPRESS-A would have.

## Risks if we adopt flowgentic as-is

1. **No PyPI release; git-URL dependency on a 0.1.0 package with recent API churn** (renames,
   wrapper-API changes) — pin to a commit, not a branch, and expect breakage on updates.
2. **Zero unit-test coverage on the exact code path we'd depend on** (`execution_wrappers.py`,
   `fault_tolerance.py`) — bugs like the `except Exception: raise` guard in `fault_tolerance.py:71-84`
   would ship silently.
3. **MCP support is documented but not implemented** (`AGENT_TOOL_AS_MCP` missing from the actual
   `AsyncFlowType` enum) — if our tool registry design leans on MCP-style dynamic tool discovery,
   flowgentic does not currently deliver it despite the docs page.
4. **Academy path is broken/dead** — do not treat flowgentic as offering an Academy integration in
   practice; if Phase 4 picks Academy for control model A, flowgentic's Academy bridge would need to be
   rewritten essentially from scratch (or bypassed, using `radical.asyncflow` directly as
   `src/flowgentic/academy.py` itself does — that module already shows a workable, if unpolished,
   direct pattern for Academy-agent-action-as-asyncflow-task that we could adapt without depending on
   the package).
5. **No campaign-state, checkpointing, or HITL primitives** — adopting flowgentic buys us nothing
   toward cycle-boundary checkpointing or `RequestHuman`; those must be designed independently,
   probably directly against LangGraph's own `interrupt`/checkpointer primitives (already reachable in
   the same dependency stack) rather than through flowgentic.

**What we'd lose by not depending on it**: mainly convenience — the `asyncflow(...)` decorator pattern
(tool → LangChain `@tool` → asyncflow `function_task` → retry/backoff, ~40 lines,
`execution_wrappers.py:147-177`) is small enough to reimplement directly against
`radical.asyncflow.WorkflowEngine` ourselves, with our own `ToolSpec`/phase structure built in from the
start rather than bolted on. Given the immaturity findings above, reimplementing the narrow pattern
we need (with our own composition/validation/QC-gate semantics) is likely lower-risk than taking a
0.1.0, untested, git-only dependency for it.
