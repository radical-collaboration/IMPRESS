import os
import subprocess


def find_gpus() -> list[int]:
    """Return GPU IDs visible to this process.

    Checks CUDA_VISIBLE_DEVICES first, then nvidia-smi.
    Falls back to an empty list when neither yields results.

    Standalone diagnostic helper only. GPU placement is the execution
    backend's responsibility; this is not a supported way to pin work to
    devices. It was previously used to hand-assign a `gpu_id` per pipeline
    as an application-level workaround for a backend that ignored GPU
    placement hints. That backend has since been fixed, so nothing in the
    framework calls this.
    """
    val = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    ids = [int(g) for g in val.split(",") if g.strip().isdigit()]
    if ids:
        return ids

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
