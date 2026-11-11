"""The execution loop, on `impress`'s manager.

What the architecture outline calls the Workflow Engine. Named the **Runner** here, because
`WorkflowEngine` already means `radical.asyncflow.WorkflowEngine` - a distinct object this role
*owns* - and one name for two things in a system whose central hazard is loop ownership would
be a poor trade for matching a diagram.

**One engine, on one loop, and this does not create it.** `WorkflowEngine.__init__` captures
the running loop and schedules its dispatch on exactly that loop; an engine built elsewhere
looks healthy and dispatches nothing, which cost jobs 22328172 and 22328262 their full
allocations. The executor builds the engine and hands it here, and `ImpressManager` is
explicitly a caller-owns-the-engine design - it never constructs or shuts one - so the
bounded-teardown rule stays exactly where it was.

**Opt-in, and the default is still the Dispatcher.** `CampaignSpec.runner` selects. The Runner
is tested against `ConcurrentExecutionBackend` locally, but the component it replaces is the
one whose failure modes have cost two allocations, and a Delta smoke has not run. Replacing a
dispatcher that works with one that has never seen Dragon would be exactly the move this
project's records argue against; phase 6's Delta smoke is what flips the default.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from impress import ImpressManager, PipelineSetup

from ..compose.graph import TaskGraph
from ..exec.dispatch import results_from
from .pipelines import ControlPipeline, StagePipeline

log = logging.getLogger(__name__)


@dataclass
class StageHandle:
    """Structurally a `DispatchHandle`, so the executor's reap path needs no change.

    Kept separate rather than shared because `exec/` must not import `runtime/`, and a handle
    is a runtime concern. The fields are the ones `_reap`, `cancel` and `drain` read.
    """

    run_id: str
    graph_id: str
    futures: dict[str, Any] = field(default_factory=dict)
    gather: Any = None
    cancelled: bool = False
    pipeline_name: str = ""


class StageRunner:
    """Deploys Stages as IMPRESS pipelines on one `ImpressManager`."""

    def __init__(self, flow: Any, reg: Any, backend_kind: str = "concurrent", *,
                 workdir: str | None = None, gpus_per_node: int = 1, threads: int = 1,
                 telemetry_config: dict[str, Any] | None = None,
                 telemetry_subscribers: list[Any] | None = None) -> None:
        self.flow = flow
        self.reg = reg
        self.workdir = workdir
        #: Both carried only to be handed to each `StagePipeline`, which is where a node's
        #: GPU pinning is resolved. Positional `backend_kind` mirrors `Dispatcher.__init__`,
        #: so the two execution loops are constructed the same way.
        self.backend_kind = backend_kind
        self.gpus_per_node = gpus_per_node
        self.threads = threads
        self._halt = asyncio.Event()
        self.manager = ImpressManager(
            flow, telemetry_config=telemetry_config or {},
            telemetry_subscribers=telemetry_subscribers or [])
        self._loop_task: asyncio.Task | None = None
        self._seq = 0

    async def start(self) -> None:
        """Bring the manager up with the keep-alive pipeline already in it.

        The keep-alive goes in the FIRST batch rather than being added later: `start()` drains
        and exits the moment nothing is in flight, so a manager started empty can finish before
        the first Stage arrives.
        """
        setup = PipelineSetup(name="control", type=ControlPipeline,
                              config={"halt": self._halt})
        self._loop_task = asyncio.create_task(self.manager.start(pipeline_setups=[setup]))
        # Yield once so the manager's loop and the keep-alive pipeline are actually running
        # before the first deploy; `submit_new_pipelines` is synchronous but the task it
        # creates is not.
        await asyncio.sleep(0)

    def submit(self, g: TaskGraph, run_id: str = "") -> StageHandle:
        """Register one graph as a pipeline and return WITHOUT awaiting it.

        Synchronous, like `Dispatcher.submit`, and for the same reason: the outer loop must get
        control back before the slowest lineage finishes, or the reasoner cannot be consulted
        again until the graph is done.

        Uses `manager.submit_new_pipelines` directly rather than
        `submit_child_pipeline_request`, because that is a SINGLE-SLOT mailbox - a second
        request before the manager's 0.5 s poll silently overwrites the first - and this path
        creates the pipeline task immediately on the caller's own loop with no polling latency.
        """
        self._seq += 1
        name = f"{run_id or g.id}"
        done: asyncio.Future = asyncio.get_running_loop().create_future()
        setup = PipelineSetup(
            name=name, type=StagePipeline,
            config={"graph": g, "registry": self.reg, "invocation": run_id or g.id,
                    "workdir": self.workdir, "done": done,
                    "gpus_per_node": self.gpus_per_node, "threads": self.threads,
                    "backend_kind": self.backend_kind})
        self.manager.submit_new_pipelines([setup])
        log.info("runner: deployed %s as pipeline %r (%d tasks)",
                 run_id or g.id, name, len(g.nodes))
        return StageHandle(run_id=run_id, graph_id=g.id, futures={}, gather=done,
                           pipeline_name=name)

    async def collect(self, h: StageHandle) -> Any:
        """Await one deployed Stage and assemble the same `ExecutionResults` as the Dispatcher.

        Through the shared `results_from`, so the two paths cannot drift on the
        declared-versus-measured cost split or on how a failed task is recorded.
        """
        return results_from(h.graph_id, await h.gather)

    def cancel(self, h: StageHandle) -> None:
        """Ask a deployed Stage to stop. ADVISORY, and more so than the Dispatcher's.

        `impress`'s own cancellation is `kill_parent`, which cancels a pipeline's asyncio Task
        and never reaches the backend, so a running tool keeps its GPU. Queued work inside the
        pipeline's own gather is reclaimable; work already handed to the backend is not.
        Reclaiming it is backlog C4 and unsolved either way.
        """
        h.cancelled = True
        if h.gather is not None and not h.gather.done():
            h.gather.cancel()

    async def shutdown(self) -> None:
        """Release the keep-alive and let the manager drain.

        The manager does not own the engine, so it is not shut down here - `flow.shutdown()`
        stays the executor's, bounded by `backend_shutdown_timeout_s`. Teardown is the
        expensive end: on job 22491438 `flow.shutdown()` never returned and the job sat 60
        minutes, about 64 GPU-hours, after the science was already done.
        """
        self._halt.set()
        if self._loop_task is not None:
            try:
                await asyncio.wait_for(self._loop_task, timeout=30.0)
            except TimeoutError:
                log.warning("runner: manager loop did not drain in 30s; abandoning it")
                self._loop_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as exc:          # noqa: BLE001 - draining must not mask results
                log.warning("runner: manager loop ended with %r", exc)
