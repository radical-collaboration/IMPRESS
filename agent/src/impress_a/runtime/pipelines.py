"""IMPRESS pipelines, as IMPRESS-A's execution loop.

One of the two modules allowed to import the root `impress` package; the other is
`runner.py`, and `tests/test_layering.py::test_only_the_runner_imports_impress` asserts it.
Keeping the surface to two files is what makes this a dependency rather than a fork: a `policy`
or `core` module reaching for `ImpressBasePipeline` would put a framework type into the
reasoner contract, and that type cannot cross the `CampaignSession` boundary.

**One Stage is one pipeline.** `register_pipeline_tasks()` is called once, from
`ImpressBasePipeline.__init__`, so a pipeline's task set is frozen at construction - a Stage's
graph is known by then and a Spec revision produces a *new* Stage, which is the one place the
outline's "the Spec may change at runtime" does not reach.

Three traps in the base class, each worth knowing before editing:

* `register_pipeline_tasks()` runs at `impress_pipeline.py:61`, **two lines before
  `self.logger` is assigned**. Anything registration needs must already exist. `**config` is
  stashed into `self.config` at `:52`, so reading from there is safe where reading an attribute
  a subclass sets after `super().__init__()` is not.
* `auto_register_task` has exactly two branches - `wrap_local_task`, or
  `flow.executable_task` - and an executable task must return a non-empty command string that
  asyncflow `shlex.split`s. A `TaskAgent` call is neither, so these register through
  `flow.function_task` directly. That is the one documented extension, chosen over
  `local_task=True` because that would run every task in the agent's own process and stop the
  laptop tier proving a task closure is picklable.
* `ImpressManager.start()` breaks its poll loop the moment `pipeline_tasks`,
  `new_pipeline_buffer` and `adaptive_tasks` are all empty - so without something alive it
  exits in the first idle gap between Stages. `ControlPipeline` is that keep-alive, and it is
  structural rather than decorative.

We never use `run_adaptive_step`: the outer loop is ours (ADR 0001), and
`ImpressManager._run_adaptive_fn` swallows every exception while still releasing the barrier,
so a failed decision there is indistinguishable from a made one.
"""
from __future__ import annotations

import asyncio
from typing import Any

from impress import ImpressBasePipeline

from ..exec.dispatch import node_task


class ControlPipeline(ImpressBasePipeline):
    """A pipeline that does nothing until told to stop, so the manager stays alive.

    `ImpressManager.start()` exits as soon as nothing is in flight. A campaign deploys Stages
    with gaps between them - that is the whole point of a control plane - so the manager has to
    outlive the gaps.
    """

    def register_pipeline_tasks(self) -> None:
        @self.auto_register_task(local_task=True)
        async def hold(*_: Any, **__: Any) -> str:
            await self.config["halt"].wait()
            return "released"

    async def run(self) -> None:
        await self.hold()


class StagePipeline(ImpressBasePipeline):
    """One Stage's DAG, as an IMPRESS pipeline.

    `config` carries `graph`, `registry`, `invocation`, `workdir` and `done` - a future the
    Runner awaits. Passing the future in is what lets the Runner collect results it did not
    construct the pipeline for: `ImpressManager.submit_new_pipelines` builds the instance
    internally and hands it back only as a dict key.
    """

    def register_pipeline_tasks(self) -> None:
        graph = self.config["graph"]
        reg = self.config["registry"]
        invocation = self.config.get("invocation") or graph.id
        workdir = self.config.get("workdir")
        self._order = graph.topo_order()
        for tid, node in graph.nodes.items():
            # The SAME factory the Dispatcher uses, deliberately. Two implementations of the
            # typed input wiring would be two things to keep in step, and that wiring is
            # exactly what phase 4 had to fix once already.
            task = node_task(
                self.flow, reg, tid, node.tool, node.params,
                invocation=f"{invocation}:{tid}", seed=node.seed,
                dep_order=tuple(node.deps),
                wiring=tuple((port, *ref.split(".", 1)) if "." in ref else (port, ref, "")
                             for port, ref in node.inputs.items()),
                workdir=workdir, seed_inputs=node.seed_inputs)
            setattr(self, tid, task)

    async def run(self) -> None:
        graph = self.config["graph"]
        done: asyncio.Future = self.config["done"]
        futures: dict[str, Any] = {}
        try:
            for tid in self._order:
                # Unawaited futures as positional arguments express DAG EDGES; `gather` awaits
                # independent work. The two idioms are not interchangeable, and this is the
                # edge one.
                deps = [futures[d] for d in graph.nodes[tid].deps]
                futures[tid] = getattr(self, tid)(*deps, workflow_id=self.name)
            # return_exceptions: one bad task must not cancel its siblings, and an unretrieved
            # exception on a future nobody awaits is a warning nobody sees.
            raw = await asyncio.gather(*futures.values(), return_exceptions=True)
            if not done.done():
                # Zip against `futures`, NOT against `graph.nodes`. `futures` is built in topo
                # order and `graph.nodes` is in insertion order, and for anything wider than
                # one lineage those differ - Kahn's algorithm emits every root first, so with
                # two replicas the second lineage's first task lands where the first
                # lineage's second task sits. The result was each node carrying the metrics of
                # whichever task happened to occupy its position, which is a silent
                # misattribution rather than a failure. `Dispatcher.collect` zips against its
                # own `futures` for exactly this reason.
                done.set_result(dict(zip(futures.keys(), raw, strict=True)))
        except BaseException as exc:          # noqa: BLE001 - the Runner owns the decision
            if not done.done():
                done.set_exception(exc)
            raise
