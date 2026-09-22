# Done — decoupling the reasoner from the execution graph

Five stages, all shipped. The originating request: *a federation of task agents invoked for the
parallel generation of a data ensemble* was not expressible, because task execution blocked return
to the reasoner.

## The diagnosis, corrected

The premise given was that the reasoner was "a node in the execution graph". It was not:
`function_task` had exactly one call site, fed only by composer output, and `exec/`, `compose/` and
`tools/` contained zero references to `policy`. The reasoner was the **loop body** of a serial
cycle, and three awaits on one coroutine serialised it — the worst being a `gather` over every node
of a graph, with no per-node callback and no streaming.

The fix was therefore to break the awaits, not to remove a node. Worth recording because the wrong
diagnosis would have led to restructuring the DAG layer, which was already correct.

It also turned out this was a **stated requirement that was never implemented**, not a new idea:
`planning/phase1-partB-architecture/07-execution-layer-seam.md:24` asks for "async, non-blocking
submission — the outer loop must observe and remain steerable while work runs", and `:31` notes
"cancellation is why submission handles are retained per graph". No handles were ever kept.

## What was built

| Stage | |
|---|---|
| 0 | Budget reservations; run-label and per-replica seeds; append-only trust ledger; `cycle` decomposed into turn / run / cursor; dead `JobLedger` and `prov_sink` wired |
| 1 | `Dispatcher.submit`/`collect`/`cancel` with retained handles; in-flight run table; drain before shutdown |
| 2 | `CampaignExecutor` (sole state owner) split from the reasoner; `core/session.py`; `SequentialPolicyDriver` so A-D work unchanged; `manager.py` became a facade |
| 3 | Durable `RunService`, ledger with outcome payloads, `reattach()`, control-plane run operations, real `pause`/`stop` |
| 4 | `ArtifactRef` contract; `DesignNode.artifacts` populated; HTTP+SSE adapter with loopback tests |

## Rulings worth keeping

**An untrusted pattern may have only one instance in flight.** Promotion counts *consecutive* clean
runs, so N concurrent instances of one provisional shape are a single draw sampled N times — the
pattern would promote without the first result ever informing the second launch. Distinct shapes may
fan out freely, which is the parallelism actually wanted. This later became the template for the
stagnation fix (see `03-stagnation-under-fanout.md`).

**The executor decides termination; the reasoner may only request it.** Budget, stagnation and
repeated failure are facts about state a reasoner cannot see.

**Single-writer is a discipline, not a guarantee.** Every mutating block in the executor is
`await`-free, which is the only reason an observation can never be taken mid-absorb. Adding an
`await` inside `observe` or `_absorb` reintroduces torn reads, and they are close to undiagnosable
from provenance afterwards.

**Admission stays synchronous, everywhere, including over HTTP.** `submit` returns a run id or
raises/409s with the failure. Accept-then-reject-later would sever a rejection from the request that
caused it and leave nothing to bound retries against. It also cannot work: `dry_run` instantiates
task agents, so admission must happen where the toolkit is installed.

**`policy → core` forced the shape of the API.** A reasoner may hold a result, so `RunOutcome` could
not live in `exec/` beside the `ExecutionResults` it projects from. That is why `core/session.py` and
`core/results.py` exist, and why `interpret`'s argument was unannotated for so long.

## Things that were claimed and turned out false

- Task-**name** collisions across concurrent graphs were reported as a hard blocker. They are not:
  asyncflow keys components by a unique uid and resolves dependencies by future *identity*. Names are
  labels. Verified in 0.5.1 before building on it.
- `workflow_scope` was initially overstated as giving a `workflow_id → tasks` index. It gives the
  tag; there is no lookup API. The run table remains the index.
- Cancellation was overstated as "the surface exists". It exists and is **advisory**: queued work is
  reclaimed, running work is not, and the boolean saying which is discarded.

## The deadlock this split made possible

A reasoner blocked on `session.result(rid)` when the executor terminated was cancelled rather than
woken — the future was never set. `result()` now races the run against the halt event and raises
`CampaignStopped`. It was silent, and it is the characteristic hazard of two coroutines where there
was one. There is a test for it.
