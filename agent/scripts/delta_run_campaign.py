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
campaign that has deadlocked produce byte-identical output - nothing. Four things are set
up here, none of which belong in library code:

  * logging is configured, which un-silences rhapsody's own bring-up lines (the Dragon
    backend logs its worker/manager counts at INFO from its constructor);
  * those lines are ALSO written to `campaign.log` in the job working directory, through
    handlers held on our own loggers rather than on root - see below;
  * stdout/stderr are line-buffered, because Dragon pipes them and Python then
    block-buffers, so output can be many minutes stale;
  * `SIGUSR1` dumps every thread's stack, which answers "where is it stuck" without
    py-spy on a compute node.

GOTCHA - Dragon SILENTLY REMOVES ROOT LOG HANDLERS (jobs 22328172/22328262). Both
`dragon.native.Pool.__init__` and `ProcessGroup.__init__` call `setup_BE_logging`, which
starts by calling `_clear_root_log_handlers()` (dragon/dlogging/util.py): every handler on
the ROOT logger is closed and removed, and handlers are re-added only if the
`DRAGON_LOG_DEVICE_{STDERR,DRAGON_FILE,ACTOR_FILE}` environment variables ask for them.
rhapsody builds `Batch()` inside the Dragon backend constructor, so in those two jobs
every log line emitted after backend bring-up went nowhere: `engine: dragon backend
ready`, the heartbeat liveness line, the provenance mirror, and rhapsody's own worker and
manager counts. The run looked identical to a run that never got that far.

So the handlers here are attached to OUR loggers (`impress_a` and the middleware
packages), each with `propagate = False`, which puts them out of Dragon's reach; the root
handler is a convenience for anything else and is expendable. `_RootHandlersClearedWatch`
notices when root has been cleared out from under us and says so once, at WARNING, naming
`setup_BE_logging`, so this does not have to be rediscovered.

Environment:
  IMPRESS_A_LOG_LEVEL=DEBUG            our own loggers (default INFO)
  IMPRESS_A_MIDDLEWARE_LOG_LEVEL=DEBUG rhapsody/asyncflow/radical (default INFO, which
                                       is where the Dragon backend reports its worker and
                                       manager counts; DEBUG to trace Batch bring-up)
  IMPRESS_A_LOG_FILE=campaign.log      transcript path, relative to the job working
                                       directory; empty disables the file handler
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
_OURS = ("impress_a",)
_FORMAT = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"


def _level(name: str, default: str) -> int:
    lvl = logging.getLevelName(os.environ.get(name, default).upper())
    return lvl if isinstance(lvl, int) else logging.INFO


class _RootHandlersClearedWatch(logging.Filter):
    """Says so, once, when something has emptied the root logger behind our back.

    Dragon's `setup_BE_logging` calls `_clear_root_log_handlers()`, which closes and
    removes every root handler; it re-adds one only if `DRAGON_LOG_DEVICE_*` asks. That is
    what made jobs 22328172/22328262 go quiet after backend bring-up. This rides on our
    own handler - which Dragon cannot reach - so the notice survives the clearing it is
    reporting.
    """

    def __init__(self, installed: list[logging.Handler]) -> None:
        super().__init__()
        self._installed = [id(h) for h in installed]
        self._warned = False

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._warned:
            current = [id(h) for h in logging.getLogger().handlers]
            if current != self._installed:
                self._warned = True     # set BEFORE logging: this filter sees that record
                logging.getLogger("impress_a.launch").warning(
                    "root log handlers were replaced (%d -> %d) - almost certainly "
                    "Dragon's setup_BE_logging(), which calls _clear_root_log_handlers() "
                    "from Pool()/ProcessGroup() construction. Our own loggers keep their "
                    "own handlers (propagate=False), so this transcript is unaffected; "
                    "anything logging to the root logger is now going nowhere.",
                    len(self._installed), len(current))
        return True


def _configure_diagnostics() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except AttributeError:          # not a TextIOWrapper under some launchers
            pass

    ours = _level("IMPRESS_A_LOG_LEVEL", "INFO")
    mw = _level("IMPRESS_A_MIDDLEWARE_LOG_LEVEL", "INFO")

    # force=True: something in the Dragon/rhapsody import chain may have already
    # installed a handler, and basicConfig is otherwise a no-op if one exists. This one is
    # expendable - Dragon removes it the moment it builds a Pool - so it is a convenience
    # for third-party loggers only, never the transcript.
    logging.basicConfig(level=ours, format=_FORMAT, stream=sys.stderr, force=True)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if logfile := os.environ.get("IMPRESS_A_LOG_FILE", "campaign.log"):
        try:
            handlers.append(logging.FileHandler(os.path.abspath(logfile), mode="a"))
        except OSError as e:            # read-only cwd: stderr alone is still better
            print(f"warning: cannot open log file {logfile!r}: {e}", file=sys.stderr)
    watch = _RootHandlersClearedWatch(list(logging.getLogger().handlers))
    for h in handlers:
        h.setFormatter(logging.Formatter(_FORMAT))
        h.addFilter(watch)

    # Handlers on OUR loggers, not root, with propagation off: `_clear_root_log_handlers`
    # walks root's handler list only, so it cannot take these with it.
    for name, level in [(n, ours) for n in _OURS] + [(n, mw) for n in _MIDDLEWARE]:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        for h in handlers:
            logger.addHandler(h)
        logger.propagate = False

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
    for h in logging.getLogger("impress_a").handlers:
        if isinstance(h, logging.FileHandler):
            log.info("transcript=%s  (handler held on our own loggers, so Dragon's "
                     "setup_BE_logging cannot clear it)", h.baseFilename)
    for var in ("FOUNDRY_SIF_PATH", "MPNN_DIR", "BOLTZ_CACHE", "CUDA_VISIBLE_DEVICES",
                "SLURM_JOB_ID", "SLURM_NNODES", "APPTAINER_CACHEDIR"):
        log.info("env %-20s %s", var, os.environ.get(var, "<unset>"))


if __name__ == "__main__":
    _configure_diagnostics()
    sys.exit(main())
