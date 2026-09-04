import os
from dataclasses import dataclass, field


@dataclass
class GPUPolicy:
    gpu_affinity: list = field(default_factory=list)


def _find_gpus() -> list:
    cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if cuda_visible:
        return [int(g) for g in cuda_visible.split(",") if g.strip().isdigit()]
    try:
        from dragon.native.machine import System

        sys_info = System()
        return [gpu for node in sys_info.nodes for gpu in node.gpus]
    except Exception:
        pass
    return [0, 1, 2, 3]  # gpuA40x4 default


def _make_policy(all_gpus: list, idx: int, n_gpus: int = 1) -> GPUPolicy:
    assigned = [all_gpus[(idx + j) % len(all_gpus)] for j in range(n_gpus)]
    return GPUPolicy(gpu_affinity=assigned)
