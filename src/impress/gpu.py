import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Protocol, Union, runtime_checkable


@dataclass
class GPUPolicy:
    gpu_affinity: list = field(default_factory=list)


@runtime_checkable
class GpuDiscovery(Protocol):
    """Protocol for GPU discovery strategies.

    Implement this to support a new execution backend.  Return an empty list
    when the strategy cannot discover GPUs in the current environment so the
    next strategy in the chain is tried.
    """

    def discover(self) -> list[int]: ...


class EnvVarGpuDiscovery:
    """Read GPU IDs from CUDA_VISIBLE_DEVICES (works for every backend)."""

    def discover(self) -> list[int]:
        val = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        return [int(g) for g in val.split(",") if g.strip().isdigit()]


class NvidiaSmiGpuDiscovery:
    """Query nvidia-smi for available GPU indices (works for every backend)."""

    def discover(self) -> list[int]:
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode == 0:
                return [
                    int(ln.strip())
                    for ln in out.stdout.splitlines()
                    if ln.strip().isdigit()
                ]
        except Exception:
            pass
        return []


_DEFAULT_DISCOVERY_CHAIN: list[GpuDiscovery] = [
    EnvVarGpuDiscovery(),
    NvidiaSmiGpuDiscovery(),
]


def find_gpus(
    discovery: Optional[Union[GpuDiscovery, list[GpuDiscovery]]] = None,
) -> list[int]:
    """Discover available GPU IDs using the given strategy or the default chain.

    Discovery order (default):
        1. CUDA_VISIBLE_DEVICES env var  — reflects scheduler-allocated GPUs
        2. nvidia-smi                    — enumerates all GPUs on the node

    The first strategy that returns a non-empty list wins.  Pass a custom
    ``GpuDiscovery`` implementation (or a list of them) to support a new
    backend without modifying this file.

    Args:
        discovery: A single :class:`GpuDiscovery` instance, an ordered list of
            them, or ``None`` to use the default chain.

    Returns:
        List of integer GPU indices.  Falls back to ``[0]`` with a
        :class:`RuntimeWarning` when no strategy succeeds.
    """
    if discovery is None:
        chain: list[GpuDiscovery] = _DEFAULT_DISCOVERY_CHAIN
    elif isinstance(discovery, list):
        chain = discovery
    else:
        chain = [discovery]

    for strategy in chain:
        result = strategy.discover()
        if result:
            return result

    return []


def _find_gpus() -> list[int]:
    """Backward-compatible alias for :func:`find_gpus`."""
    return find_gpus()


def find_dragon_gpus() -> list[tuple]:
    """Return (hostname, gpu_id) pairs for all GPUs visible to the Dragon runtime.

    Under ``dragon -s`` (single-node) node.hostname returns ``'localhost'``;
    the real hostname is substituted so Dragon's HOST_NAME placement resolves.
    """
    import socket

    from dragon.native.machine import Node, System

    real_hostname = socket.gethostname()
    result = []
    for huid in System().nodes:
        node = Node(huid)
        hostname = node.hostname if node.hostname != "localhost" else real_hostname
        for gpu_id in node.gpus or []:
            result.append((hostname, gpu_id))
    return result


def _make_policy(all_gpus: list, idx: int, n_gpus: int = 1):
    """Build a GPU placement policy for the pipeline at position idx.

    When *all_gpus* contains ``(hostname, gpu_id)`` tuples (Dragon mode) a
    ``dragon.infrastructure.policy.Policy`` is returned so the execution
    backend can route the task to the correct node and GPU.  When it contains
    plain integers a :class:`GPUPolicy` is returned for
    ``CUDA_VISIBLE_DEVICES``-based placement.
    """
    if not all_gpus:
        return GPUPolicy()

    if isinstance(all_gpus[0], tuple):
        from dragon.infrastructure.policy import Policy

        assigned = [all_gpus[(idx + j) % len(all_gpus)] for j in range(n_gpus)]
        hostname, _ = assigned[0]
        unique_hosts = {g[0] for g in all_gpus}
        if len(unique_hosts) > 1:
            # Multi-node: route to the specific node that owns the GPU.
            return Policy(
                placement=Policy.Placement.HOST_NAME,
                host_name=hostname,
                gpu_affinity=[g[1] for g in assigned],
            )
        # Single-node (dragon -s): HOST_NAME routing is unavailable; set GPU
        # affinity only so Dragon picks the right device without node routing.
        return Policy(
            placement=Policy.Placement.DEFAULT,
            gpu_affinity=[g[1] for g in assigned],
        )

    assigned = [all_gpus[(idx + j) % len(all_gpus)] for j in range(n_gpus)]
    return GPUPolicy(gpu_affinity=assigned)
