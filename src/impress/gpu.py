import os
import subprocess


def find_gpus() -> list[int]:
    """Return GPU IDs available to this process.

    Checks CUDA_VISIBLE_DEVICES first, then nvidia-smi.
    Falls back to an empty list when neither yields results.
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
