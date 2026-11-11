"""A Stage is one asyncflow block on the campaign's one engine.

`submit` defines a `@flow.block` whose body registers the graph's nodes in topo order - unawaited
futures as arguments are the DAG's edges - and gathers them. It calls the block and returns
without awaiting it, so the executor gets control back before the slowest lineage finishes and
the reasoner can be consulted while work runs.

What the block gives that the two execution loops it replaces did not:

* **Cancellation reaches the work.** Cancelling a block cancels every unfinished member, and
  asyncflow (0.7.0) sends each member's cancel to the backend that runs it. A node's commands
  are members too (`exec/launch.py` submits them in the block's context). The IMPRESS-pipeline
  Runner cancelled only a side-channel future: the run was reaped FAILED and its budget
  released while its tasks kept running.
* **One label per run, from the engine.** Members inherit the block in telemetry, and each is
  also tagged with the run label, so concurrent runs' identically named tasks stay apart.
* **No host process for the framework.** The Runner needed a keep-alive pipeline so
  `ImpressManager` would not exit between Stages, a 0.5 s poll, and a future smuggled into each
  pipeline's config to get results back. A block's future is its result.

**Cancellation is still advisory for a command already running.** The backend decides whether
a running process dies - rhapsody's concurrent backend does not kill it (see
`docs/impress-a/limitations.md`) - so every command also carries its own walltime. A cancelled
Stage's outcome comes from collecting it, which accounts for every node.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..compose.graph import TaskGraph
from ..tools.registry import Registry
from .dispatch import ExecutionResults, gpu_for, host_for, node_task, results_from
from .launch import Launcher
from .resources import Placement, placement_for

#: How long `collect` waits for a cancelled Stage's commands to report back from their backend
#: before accounting for them anyway. A cancel the backend has accepted reports promptly; one
#: it is still acting on must not hold the campaign's reservation forever.
SETTLE_S = 30.0


def command_slots(backend_kind: str, config: dict[str, Any] | None) -> int | None:
    """The concurrent backend's `workers`, as a bound on commands; `None` for any other backend.

    The stopgap `Launcher.slots` describes: rhapsody's concurrent backend bounds only function
    tasks by `workers`, and a campaign that says `workers: 4` means four tools at once. The
    default matches `exec/backend._construct_backend_sync`'s.
    """
    if backend_kind.lower() not in ("concurrent", "local_process", "mock"):
        return None
    return int((config or {}).get("workers", 4))


@dataclass
class StageHandle:
    """One submitted Stage. The executor waits on `gather`, the block's future."""

    run_id: str
    graph_id: str
    graph: TaskGraph
    #: The block's future: `{node_id: payload-or-exception}` once the Stage finishes.
    gather: Any = None
    #: Each node's engine future, filled as the block body registers them.
    futures: dict[str, Any] = field(default_factory=dict)
    #: Each node's command launcher, so a cancel can stop an adapter between commands.
    launchers: list[Launcher] = field(default_factory=list)
    cancelled: bool = False


class StageExecutor:
    """Runs each graph as one block on the campaign's engine."""

    def __init__(self, flow: Any, reg: Registry, backend_kind: str = "concurrent",
                 workdir: str | None = None, gpus_per_node: int = 1, *,
                 threads: int = 1, hosts: tuple[str, ...] = (),
                 command_slots: int | None = None, gpu_offset: int = 0) -> None:
        self.flow, self.reg, self.backend_kind = flow, reg, backend_kind
        #: How many commands may run at once on a backend that does not bound them itself -
        #: see `Launcher.slots`. Shared by every Stage on this engine.
        self.slots = asyncio.Semaphore(command_slots) if command_slots else None
        #: None means "whatever the process CWD is", which is what the launcher sets.
        self.workdir = workdir
        #: Devices per node, from the campaign's `SiteCaps`. 1 means "do not pin", which is
        #: also the honest answer for a laptop.
        self.gpus_per_node = gpus_per_node
        #: Threads one CPU-bound command may take (`exec/resources.thread_share`).
        self.threads = threads
        #: The compute backend's hosts, from its topology. Named only when there are several.
        self.hosts = tuple(hosts)
        #: GPUs at the start of each node that tools must not be given, because the campaign's
        #: own model holds them (`CampaignSpec.inference`). See `_gpu_for`.
        self.gpu_offset = gpu_offset

    def _gpu_for(self, lineage: int) -> int | None:
        """Round-robin over the devices tools may use.

        With a local model holding the first `gpu_offset` devices, tools round-robin over the
        rest - and are pinned even when only one is left, because "do not pin" would let a
        tool land on the model's GPU. ASSUMES Dragon Inference takes the first devices of its
        node: its `HardwareConfig` names a count, not ids. Unverified on hardware (backlog I4).
        """
        if not self.gpu_offset:
            return gpu_for(lineage, self.gpus_per_node)
        usable = self.gpus_per_node - self.gpu_offset
        if usable < 1:
            raise ValueError(f"the local model holds {self.gpu_offset} of "
                             f"{self.gpus_per_node} GPUs per node; no GPU is left for tools")
        return self.gpu_offset + lineage % usable

    def placement(self, tool_id: str, lineage: int) -> Placement:
        """Where one lineage's node of `tool_id` runs: its share of threads and - for a tool
        that declares a GPU - that lineage's device, on that device's host."""
        return placement_for(self.reg.get(tool_id).resources, self.backend_kind,
                             threads=self.threads, gpu_index=self._gpu_for(lineage),
                             host=host_for(lineage, self.gpus_per_node, self.hosts))

    def submit(self, g: TaskGraph, run_id: str = "") -> StageHandle:
        """Define and call the Stage's block; return WITHOUT awaiting it.

        The block is named `stage` for every run, deliberately: names collide across runs, and
        the run label is what separates them - the same rule as for the nodes inside it.
        """
        h = StageHandle(run_id=run_id, graph_id=g.id, graph=g)
        invocation = run_id or g.id
        label = run_id or None
        order = list(g.topo_order())

        async def stage() -> dict[str, Any]:
            for tid in order:
                n = g.nodes[tid]
                task = node_task(
                    self.flow, self.reg, tid, n.tool, n.params,
                    invocation=f"{invocation}:{tid}", seed=n.seed,
                    dep_order=tuple(n.deps),
                    wiring=tuple((port, *ref.split(".", 1)) if "." in ref else (port, ref, "")
                                 for port, ref in n.inputs.items()),
                    workdir=self.workdir, placement=self.placement(n.tool, n.lineage),
                    workflow_id=label, seed_inputs=n.seed_inputs, launchers=h.launchers,
                    slots=self.slots)
                deps = [h.futures[d] for d in n.deps]          # edges via unawaited futures
                h.futures[tid] = task(*deps, workflow_id=label) if label else task(*deps)
            # return_exceptions: one bad node must not cancel its siblings, and an unretrieved
            # exception on a future nobody awaits is a warning nobody sees. Zipped against
            # `h.futures`, which is in topo order like the gather - never against `g.nodes`,
            # whose insertion order differs for anything wider than one lineage.
            raw = await asyncio.gather(*h.futures.values(), return_exceptions=True)
            return dict(zip(h.futures.keys(), raw, strict=True))

        stage.__name__ = "stage"
        block = self.flow.block(stage)
        h.gather = block(workflow_id=label) if label else block()
        return h

    async def collect(self, h: StageHandle) -> ExecutionResults:
        """Wait for a Stage and assemble its typed results - every node accounted for.

        Waited on rather than awaited, so that a block cancelled by `cancel` or by engine
        shutdown is read rather than re-raised: the run still reaches a terminal state, with
        each node's own outcome where it has one.
        """
        await asyncio.wait({h.gather})
        if not h.gather.cancelled() and h.gather.exception() is None:
            return results_from(h.graph_id, h.gather.result())
        await self._settle(h)
        why = (h.gather.exception() if not h.gather.cancelled()
               else asyncio.CancelledError(f"stage {h.run_id or h.graph_id} was cancelled"))
        payloads: dict[str, Any] = {}
        for tid in h.graph.topo_order():
            f = h.futures.get(tid)
            if f is None or not f.done():
                payloads[tid] = why
            elif f.cancelled():
                payloads[tid] = asyncio.CancelledError(f"{tid} was cancelled")
            else:
                payloads[tid] = f.exception() or f.result()
        return results_from(h.graph_id, payloads)

    async def _settle(self, h: StageHandle) -> None:
        """Wait, bounded, until a cancelled or failed Stage's work has actually stopped.

        Its commands' engine futures, any submission still waiting for a slot, and every
        adapter thread. So a run is not reaped - and its reservation released - while its
        backend is still acting on the cancel, and the engine is never shut down under an
        adapter that still needs its loop (`Launcher.idle`). Bounded, because a backend that
        never reports must not hold the campaign; whatever it leaves running is then the
        command's own walltime to end.
        """
        idle = [asyncio.ensure_future(launcher.idle.wait())
                for launcher in h.launchers if not launcher.idle.is_set()]
        waits: set[Any] = set(idle)
        for launcher in h.launchers:
            waits |= set(launcher.inflight) | set(launcher.pending)
        if waits:
            await asyncio.wait(waits, timeout=SETTLE_S)
        for w in idle:
            w.cancel()

    def cancel(self, h: StageHandle) -> None:
        """Cancel the Stage: the block, and through its cascade every unfinished node and
        command. ADVISORY for a command already running - see the module docstring."""
        h.cancelled = True
        for launcher in h.launchers:
            launcher.cancel()
        if h.gather is not None and not h.gather.done():
            h.gather.cancel()

    async def run(self, g: TaskGraph, invocation: str = "") -> ExecutionResults:
        """Submit and wait in one step - the serial path."""
        return await self.collect(self.submit(g, run_id=invocation))
