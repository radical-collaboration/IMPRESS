# Code for the deck — staging file

Every code block that appears on a slide, keyed by snippet ID, anchored, and marked for fidelity.
Companion to [`DECK_OUTLINE.md`](DECK_OUTLINE.md) and `build_deck.js`; slide numbers and snippet IDs
match across all three.

**Derived against `main` @ `a810d67`.** Every anchor below is checked mechanically:

```sh
python3 slides/check_anchors.py      # 40/40
```

**Fidelity marking, on every block:**

| Mark | Meaning |
|---|---|
| **VERBATIM** | byte-identical to the source at the cited lines — safe to present as "this is the code" |
| **TRIMMED** | verbatim lines with whole lines removed; nothing rewritten |
| **EDITED** | restructured for legibility — **the slide says so**, and the real file is one grep away |
| **MINED** | real output from a real run, not source — `run.json` says which run |

A slide is 13.3 inches wide and the back of the room is far away, so roughly 12 lines at 70 columns
is the legible maximum. That is why most of the blocks here are EDITED rather than VERBATIM: the
real signatures carry full type annotations and do not fit. **What is never edited is behaviour** —
no block says the code does something it does not do.

| ID | Slide | Source | Fidelity | What changed |
|---|---|---|---|---|
| S6-A | 6 | a real `--model D` run | **MINED** | stdout of the run `run_model.py` performs; nothing retyped |
| S8-A | 8 | `exec/dispatch.py:144–163` | **EDITED** | type annotations dropped from the signature; the body of `_run` elided to its shape. `_run.__name__` and the decorator call are verbatim |
| S8-B | 8 | `exec/dispatch.py:182–190` | **EDITED** | the `workflow_id` conditional collapsed to its taken branch; comments shortened. The `topo_order` loop and the unawaited `gather` are verbatim |
| S9-A | 9 | `exec/backend.py:128–176` | **EDITED** | condensed: the `Future`/`wrap_future` setup, the heartbeat task and both `BackendConstructionTimeout` messages are elided. Control flow and ordering are exact |
| S10-A | 10 | `toolkits/rosetta/tools/filter_shape/spec.yaml` | **EDITED** | comments and `toolkit:`/`version:` dropped; `inputs`/`outputs` folded to one line each |
| S10-B | 10 | `tools/mock_agents.py:73–84` | **EDITED** | annotations dropped, docstring shortened, one dict key elided as `...` |
| S10-C | 10 | `tests/test_campaign.py:81–83` | **EDITED** | one assertion message wrapped across two lines to fit |
| S13-A | 13 | — | **ILLUSTRATIVE** | the two ledger paths, reconstructed as a comment. The paths themselves are the real ones from jobs 22684607 and 22692304 |
| S13-B | 13 | `compose/graph.py:51–61` | **VERBATIM** + one added comment (`# ONE string per NODE`) |
| S14-A | 14 | — (shell) | **VERBATIM** | the commands from `CLAUDE.md` |

---

## The three blocks that carry the argument

Quoted in full here because the slide text must not be the only record of them.

### S13-B — the pattern signature · **VERBATIM**

`src/impress_a/compose/graph.py:51–61`. The only thing added on the slide is the trailing comment
on the first line.

```python
    def pattern_signature(self) -> str:
        """Identity for the interlock: SHAPE ONLY - tool ids plus typed edges.

        Parameter values are excluded deliberately, otherwise every parameter change
        would reset a pattern's accumulated trust.
        """
        parts = sorted(
            f"{n.tool}<-{','.join(sorted(self.nodes[d].tool for d in n.deps))}"
            for n in self.nodes.values()
        )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
```

**Why it is on a slide.** One string per *node*, so N lineages contribute N duplicate parts and the
hash moves with the replica count — while the docstring's stated intent is that only *shape* counts.
Parameters are excluded on purpose; breadth is not, and nothing says whether that was a decision.
Verified against this checkout by `run_model.py`, which composes the real six-stage chain at 1, 2 and
4 replicas and records the three signatures in `run.json` under `shape`.

### S8-A / S8-B — the generic factory and the non-blocking submit

`src/impress_a/exec/dispatch.py:144–190`. The two lines that must never be cut from either block are
`_run.__name__ = node_id` and the unawaited `gather`.

```python
    def _make_task(self, node_id: str, tool_id: str, params: dict[str, Any],
                   invocation: str = "", seed: int | None = None):
        """ONE generic factory for every node in every graph."""
        reg, spec = self.reg, self.reg.get(tool_id)
        agent_cls = reg.agent_for(tool_id)
        # Bind to a local: the closure is pickled to the process pool, and reaching
        # `self` would drag the Dispatcher - and the engine's asyncio futures - with it.
        workdir = self.workdir

        async def _run(*deps: Any) -> dict[str, Any]:
            agent = agent_cls(spec)
            req = TaskRequest(tool=tool_id, params=params,
                              node_id=invocation, seed=seed, workdir=workdir,
                              inputs={f"dep{i}": d for i, d in enumerate(deps)})
            res = await agent(req)
            return {"tool": res.tool, "outputs": res.outputs, "metrics": res.metrics,
                    "qc": res.qc.model_dump(), "cost": res.cost}

        _run.__name__ = node_id   # asyncflow reads the name from __name__
        return self.flow.function_task(_run)
```

```python
        futures: dict[str, Any] = {}
        for tid in g.topo_order():                       # edges via unawaited futures
            deps = [futures[d] for d in g.nodes[tid].deps]
            futures[tid] = (tasks[tid](*deps, workflow_id=run_id) if run_id
                            else tasks[tid](*deps))
        # return_exceptions=True: one bad task must not cancel its siblings, and the
        # gather is not awaited yet, so a raising task would otherwise go unretrieved.
        gather = asyncio.gather(*futures.values(), return_exceptions=True)
        return DispatchHandle(run_id=run_id, graph_id=g.id, futures=futures,
                              gather=gather)
```

**If challenged on the `workflow_id` conditional** the slide collapses: it is there because a graph
run outside a campaign has no run id, and asyncflow rejects `workflow_id=""`. It changes nothing
about the argument.

### S9-A — construction, and which loop it happens on

`src/impress_a/exec/backend.py:128–176`, condensed on the slide. The ordering is the content: the
daemon thread does *only* `_construct_backend_sync`, and both `_init_backend` (which is what
triggers `__await__` and registers task states) and `WorkflowEngine.create` happen on the caller's
loop.

```python
    fut: Future = Future()
    threading.Thread(target=_construct_backend_in_thread, args=(kind, config, fut),
                     daemon=True, name="backend-construct").start()
    async_fut = asyncio.wrap_future(fut)
    ...
        be = await asyncio.wait_for(asyncio.shield(async_fut), timeout=timeout_s)
    ...
        async def _finish():
            from radical.asyncflow import WorkflowEngine
            backend = await _init_backend(be)
            return await WorkflowEngine.create(backend=backend), backend
```

The docstring on `_construct_backend_in_thread` is worth reading aloud if anyone asks why not
`loop.run_in_executor`: a pooled worker thread is joined at interpreter shutdown, so a genuinely
stuck `Batch()` would hang process exit even after the awaiting coroutine gave up. A dedicated
daemon thread is abandoned for free.

---

## Re-deriving before you present

```sh
python3 slides/run_model.py          # regenerate run.json from this checkout
python3 slides/check_anchors.py      # 40/40 — do not present a drifted anchor
python3 slides/make_script.py        # regenerate DECK_SCRIPT.md from the deck's notes
NODE_PATH=<dir with pptxgenjs> node slides/build_deck.js
```

Add an entry to `ANCHORS` in `check_anchors.py` whenever a snippet is added here. A slide citing
`executor.py:304` while showing code from somewhere else is worse than a slide with no citation at
all — this audience can grep.
