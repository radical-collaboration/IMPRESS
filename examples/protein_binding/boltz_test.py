import asyncio
import glob
import logging
import os

import rhapsody
from rhapsody.api import ComputeTask
from rhapsody.api import Session
from rhapsody.backends import DragonExecutionBackend

from rhapsody.telemetry import define_event
from rhapsody.telemetry.events import make_event

rhapsody.enable_logging(level=logging.DEBUG)

IMPRESS_OUTPUTS = os.environ.get(
    "IMPRESS_OUTPUT_DIR",
    "/work/nvme/bdyk/mgoliyad1/IMPRESS_outputs",
)
BOLTZ_CACHE_DIR = os.environ["BOLTZ_CACHE_DIR"]
BOLTZ_VENV      = os.environ["BOLTZ_VENV"]

FASTA_FILES = sorted(glob.glob(os.path.join(IMPRESS_OUTPUTS, "*.fa")))

PRED_FILES = []
for _fa in FASTA_FILES:
    _pred = os.path.join(IMPRESS_OUTPUTS, "predictions", os.path.splitext(os.path.basename(_fa))[0])
    os.makedirs(_pred, exist_ok=True)
    PRED_FILES.append(_pred)

print(f"[INFO] Found {len(FASTA_FILES)} FASTA files, output dirs created under {IMPRESS_OUTPUTS}/predictions/")

async def main():
    # Initialize backend
    backend = await DragonExecutionBackend()
    session = Session(backends=[backend])

    telemetry = None

    tasks = [
        ComputeTask(
            capture_stdio=True,
            executable="/work/nvme/bdyk/mgoliyad1/IMPRESS/examples/protein_binding/scripts/s4_boltz.sh",
            arguments=[
                fasta_file,
                PRED_FILES[FASTA_FILES.index(fasta_file)],
                BOLTZ_CACHE_DIR,
                BOLTZ_VENV,
            ],
            task_backend_specific_kwargs={"process_template": {}},
        )
        for fasta_file in FASTA_FILES
    ]

    async with session:
        # returns futures
        futures = await session.submit_tasks(tasks)

        print(f"Submitted {len(tasks)} tasks. Received {len(futures)} futures.", flush=True)

        try:
            await asyncio.gather(*futures)
        except RuntimeError as exc:
            #if "not in state State.DEAD" in str(exc):
            print(f"[WARN] Dragon spurious backend error (tasks may have completed): {exc}", flush=True)
            #else:
            #    raise

        print(f"Waited for {len(futures)} futures.", flush=True)

        for t in tasks:
            result = t.return_value if t.function else t.stdout
            exit_code = getattr(t, "exit_code", "n/a")
            pred_dir = PRED_FILES[FASTA_FILES.index(t.arguments[0])] if hasattr(t, "arguments") else "?"
            stem = os.path.basename(pred_dir)
            pdb = os.path.join(pred_dir, f"boltz_results_{stem}", "predictions", stem, f"{stem}_model_0.pdb")
            pdb_ok = "pdb=OK" if os.path.isfile(pdb) else "pdb=MISSING"
            print(f"Task {t.uid}: {t.state}  exit={exit_code}  {pdb_ok}  (output: {result})", flush=True)

    if telemetry:
        summary = telemetry.summary()
        print(f"[TELEMETRY] tasks={summary.get('tasks', {})}")
        dur = summary.get("duration")
        if dur:
            print(f"[TELEMETRY] mean task time: {dur['mean_seconds'] * 1000:.1f} ms")
        await telemetry.stop()

if __name__ == "__main__":
    asyncio.run(main())