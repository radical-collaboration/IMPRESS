from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from impress_flowgentic.runner import run_impress_flowgentic


async def _main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    workspace = project_root / "workspace"

    summary = await run_impress_flowgentic(base_path=workspace)

    print("IMPress-Flowgentic run completed.")
    print(json.dumps(summary, indent=2))
    print(f"Artifacts root: {workspace}")


if __name__ == "__main__":
    asyncio.run(_main())
