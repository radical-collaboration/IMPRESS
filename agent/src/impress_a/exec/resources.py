"""Placement: where one tool command runs, expressed in each backend's own vocabulary.

Resource shapes are NOT portable (phase 2 finding M2): the concurrent backend takes an
environment and a working directory, Dragon takes a process template whose `Policy` places the
process. There is no common vocabulary, so translating a node's needs into a
`task_description` is ours to own - and this is the one module that does it.

What a node needs is decided once, when its graph is submitted (`Placement`), and rendered per
command (`Placement.describe`), because a tool's commands differ in their environment and
working directory but share their GPU and their thread share.

This module holds the package's only `dragon` import, and it is lazy: nothing here imports
Dragon unless a Dragon placement is actually rendered, so the laptop tier, CI and the knob-lab
notebook never need it installed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ..tools.spec import ResourceShape

#: The variables that hold a CPU-bound child to its share of threads. The same five the
#: reference pipeline sets, for the same measured reason: uncapped, one tool took about 30
#: cores of the Dragon primary on smoke job 22670942.
THREAD_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
               "NUMEXPR_NUM_THREADS")

#: Seconds a command may outlive its walltime after SIGTERM before it is killed. Long enough
#: for a tool to flush what it has; short enough not to hold a GPU for a dead stage.
KILL_GRACE_S = 10


def thread_caps(threads: int) -> dict[str, str]:
    """Environment that holds a CPU-bound child to `threads`.

    `OMP_WAIT_POLICY=PASSIVE` because spinning idle threads burn a core each while a stage
    waits on the GPU stages.

    An operator who exported one of these keeps their value: the cap is our suggestion, not a
    fact about the machine. This used to be done by `setdefault` on the campaign process's own
    environment, which every child then inherited; it is per command now, which also stops one
    workflow's caps leaking into its siblings under an enclosing manager.
    """
    caps = {v: str(max(1, threads)) for v in THREAD_VARS}
    caps["OMP_WAIT_POLICY"] = "PASSIVE"
    return {k: os.environ.get(k, v) for k, v in caps.items()}


def thread_share(ncpu: int | None, concurrency: int, replicas: int) -> int:
    """Threads one CPU-bound child may take: the cores this campaign was given, divided by the
    pipelines that can run at once (concurrent experiments x replica lineages), halved again.

    Upstream's sizing (`run_small_molecule_binding.py:134-143`), leaving headroom for the GPU
    stages' host-side work. `ncpu=None` reads the cgroup this process was placed in -
    `os.cpu_count()` reports the node, not the allocation - which is the right answer except
    under an enclosing campaign manager, whose caller passes its own grant instead.
    """
    if ncpu is None:
        ncpu = (len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity")
                else os.cpu_count() or 1)
    pipelines = max(1, concurrency) * max(1, replicas)
    return max(1, ncpu // (pipelines * 2))


def _dragon_policy(host: str | None, gpu_index: int | None) -> Any:
    """`Policy(host_name=..., gpu_affinity=[g])` - Dragon sets `CUDA_VISIBLE_DEVICES` itself.

    Setting the variable in the template's env does NOT work under Dragon: local services
    merges the template env and applies the policy layout afterwards, and a policy with no
    `gpu_affinity` resolves to every GPU on the node (rhapsody's resource-specification guide,
    "GPU affinity with Policy"). The one place this package names Dragon.
    """
    from dragon.infrastructure.policy import Policy  # noqa: PLC0415 - optional extra

    kwargs: dict[str, Any] = {}
    if host:
        kwargs.update(placement=Policy.Placement.HOST_NAME, host_name=host)
    if gpu_index is not None:
        kwargs["gpu_affinity"] = [gpu_index]
    return Policy(**kwargs)


@dataclass(frozen=True)
class Placement:
    """Where one node's commands run. Decided at submission; rendered per command.

    `gpu_index` is set only for a tool that declares a GPU - a CPU stage pinned to a device
    would hold nothing on it, and under Dragon its policy would restrict it for no reason.
    """

    backend_kind: str
    threads: int
    gpu_index: int | None = None
    host: str | None = None
    #: Extra environment for every command of this node, beyond the thread caps.
    env: dict[str, str] = field(default_factory=dict)

    @property
    def dragon(self) -> bool:
        return self.backend_kind.lower() == "dragon"

    def placement_env(self) -> dict[str, str]:
        """What this placement adds to a command's environment.

        Under the concurrent backend the env is what pins a GPU, so it carries
        `CUDA_VISIBLE_DEVICES`; under Dragon the policy pins and the variable must NOT be set
        here, or it would name a device Dragon never gave the process.
        """
        env = {**thread_caps(self.threads), **self.env}
        if self.gpu_index is not None and not self.dragon:
            env["CUDA_VISIBLE_DEVICES"] = str(self.gpu_index)
        return env

    def describe(self, env: dict[str, str] | None = None, cwd: str | None = None,
                 timeout_s: float | None = None) -> dict[str, Any]:
        """The `task_description` for one command of this node.

        `env` is what the adapter asked its child to run with, which is a whole environment
        (adapters build it from `os.environ`, because `create_subprocess_exec` replaces rather
        than extends). The concurrent backend REPLACES the child's environment too, so it gets
        the whole thing. Dragon MERGES a template's env into the target node's own, so it gets
        only what differs from ours - sending the head node's whole environment would
        overwrite the remote node's.
        """
        if self.dragon:
            base = os.environ
            delta = {k: v for k, v in (env or {}).items() if base.get(k) != v}
            template: dict[str, Any] = {"env": {**delta, **self.placement_env()}}
            if cwd:
                template["cwd"] = str(cwd)
            if self.gpu_index is not None or self.host:
                template["policy"] = _dragon_policy(self.host, self.gpu_index)
            out: dict[str, Any] = {"process_template": template}
            if timeout_s:
                # Dragon enforces this one itself; no `timeout` wrapper runs under Dragon
                # (`exec/launch.py` says why).
                out["timeout"] = float(timeout_s) + KILL_GRACE_S
            return out
        out = {"env": {**(env if env is not None else os.environ), **self.placement_env()}}
        if cwd:
            out["cwd"] = str(cwd)
        return out


def placement_for(shape: ResourceShape, backend_kind: str, *, threads: int,
                  gpu_index: int | None = None, host: str | None = None) -> Placement:
    """One node's placement, from its tool's declared shape and the lineage's GPU."""
    return Placement(backend_kind=backend_kind, threads=threads,
                     gpu_index=gpu_index if shape.gpus > 0 else None, host=host)
