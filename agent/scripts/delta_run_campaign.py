#!/usr/bin/env python
"""Thin, real .py entrypoint for `dragon -s`/`dragon -m`.

`impress-a` is a setuptools console-script shim; whether Dragon's launcher correctly execs
one is unverified (the old IMPRESS Delta scripts always launched a plain `.py` file, e.g.
`dragon -s run_small_molecule_binding.py`). This file exists purely to remove that risk -
`dragon ${DRAGON_MODE} scripts/delta_run_campaign.py run campaigns/... --model D` mirrors
the old invocation shape exactly.

It is also where a batch run gets its diagnostics, because the package deliberately has
none: `impress_a` calls `logging.basicConfig` nowhere and prints nothing between
submission and the final summary, so under `dragon` a campaign that is progressing and a
campaign that has deadlocked produce byte-identical output - nothing. Three things are set
up here, none of which belong in library code:

  * logging is configured, which un-silences rhapsody's own bring-up lines (the Dragon
    backend logs its worker/manager counts at INFO from its constructor);
  * stdout/stderr are line-buffered, because Dragon pipes them and Python then
    block-buffers, so output can be many minutes stale;
  * `SIGUSR1` dumps every thread's stack, which answers "where is it stuck" without
    py-spy on a compute node.

Environment:
  IMPRESS_A_LOG_LEVEL=DEBUG            our own loggers (default INFO)
  IMPRESS_A_MIDDLEWARE_LOG_LEVEL=DEBUG rhapsody/asyncflow/radical (default INFO, which
                                       is where the Dragon backend reports its worker and
                                       manager counts; DEBUG to trace Batch bring-up)
  IMPRESS_A_HEARTBEAT_S=60             liveness line cadence; 0 disables
  IMPRESS_A_DUMP_AFTER_S=0             if >0, dump all thread stacks every N seconds

  kill -USR1 <pid>                     dump all thread stacks on demand
"""
import faulthandler
import logging
import os
import signal
import socket
import sys

from impress_a.cli import main

_MIDDLEWARE = ("rhapsody", "radical", "dragon")


def _level(name: str, default: str) -> int:
    lvl = logging.getLevelName(os.environ.get(name, default).upper())
    return lvl if isinstance(lvl, int) else logging.INFO


def _configure_diagnostics() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except AttributeError:          # not a TextIOWrapper under some launchers
            pass

    # force=True: something in the Dragon/rhapsody import chain may have already
    # installed a handler, and basicConfig is otherwise a no-op if one exists.
    logging.basicConfig(
        level=_level("IMPRESS_A_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        stream=sys.stderr, force=True)
    mw = _level("IMPRESS_A_MIDDLEWARE_LOG_LEVEL", "INFO")
    for name in _MIDDLEWARE:
        logging.getLogger(name).setLevel(mw)

    faulthandler.enable()
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True, chain=True)
    if (after := float(os.environ.get("IMPRESS_A_DUMP_AFTER_S", "0") or 0)) > 0:
        # repeat=True, exit=False: a periodic stack dump of a hung run, not a kill.
        faulthandler.dump_traceback_later(after, repeat=True, exit=False)

    log = logging.getLogger("impress_a.launch")
    log.info("host=%s pid=%d python=%s", socket.gethostname(), os.getpid(),
             sys.version.split()[0])
    log.info("cwd=%s  (campaign root, asyncflow session dir and tool workdirs are "
             "all relative to this)", os.getcwd())
    log.info("stack dump on demand: kill -USR1 %d", os.getpid())
    for var in ("FOUNDRY_SIF_PATH", "MPNN_DIR", "BOLTZ_CACHE", "CUDA_VISIBLE_DEVICES",
                "SLURM_JOB_ID", "SLURM_NNODES", "APPTAINER_CACHEDIR"):
        log.info("env %-20s %s", var, os.environ.get(var, "<unset>"))


if __name__ == "__main__":
    _configure_diagnostics()
    sys.exit(main())
