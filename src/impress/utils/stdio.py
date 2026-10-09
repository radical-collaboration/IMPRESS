"""Helpers for the stdout/stderr of executable tasks.

With `capture_stdio=True` (the IMPRESS default), the Concurrent and Dragon
backends write each task's output to `{backend work dir}/{task uid}.stdout`
and `.stderr`. A failed task then raises an exception that does not say what
went wrong: Concurrent raises `RuntimeError(<stderr path>)`, and Dragon raises
`SystemExit(<exit code>)`. `stderr_tail` finds that file so the error can
carry its last lines.
"""

import os
import shlex
from typing import Any, Optional

TAIL_LINES = 20
_TAIL_BYTES = 16 * 1024


def logged_command(log_file: str, cmd: str, tail_lines: int = TAIL_LINES) -> str:
    """Wrap a command so its combined stdout/stderr lands in `log_file`.

    Use this for a per-task log next to the task's outputs. On a non-zero exit
    the log's last lines are copied to stderr, so they also reach the backend's
    captured stderr and the task's error. `cmd` is inserted into the bash
    script verbatim, so its own quoting is kept.
    """
    log = shlex.quote(log_file)
    # A subshell, not a { } group, so an `exit` inside cmd cannot skip the tail.
    script = (
        f"( {cmd} ) > {log} 2>&1; rc=$?; "
        f'if [ "$rc" -ne 0 ]; then '
        f'echo "command failed with exit code $rc -- see "{log} >&2; '
        f"tail -n {int(tail_lines)} {log} >&2; fi; "
        f'exit "$rc"'
    )
    return f"bash -c {shlex.quote(script)}"


def _read_tail(path: str, lines: int) -> Optional[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - _TAIL_BYTES))
            data = fh.read().decode(errors="replace")
    except OSError:
        return None
    tail = "\n".join(data.splitlines()[-lines:])
    return tail or None


def _stderr_path(flow: Any, fut: Any, exc: BaseException) -> Optional[str]:
    # Concurrent backend: the exception message is the stderr path itself.
    msg = str(exc)
    if msg.endswith(".stderr") and os.path.isfile(msg):
        return msg
    # Otherwise rebuild it the way both backends name it. These are private
    # asyncflow/rhapsody attributes, so every lookup is guarded.
    desc = getattr(fut, "task", None)
    if not isinstance(desc, dict) or not desc.get("capture_stdio"):
        return None
    backends = getattr(flow, "_backends", None) or {}
    name = desc.get("target_backend") or getattr(flow, "_default_backend_name", None)
    work_dir = getattr(backends.get(name), "_work_dir", None)
    uid = desc.get("uid")
    if not work_dir or not uid:
        return None
    return os.path.join(work_dir, f"{uid}.stderr")


def stderr_tail(
    flow: Any, fut: Any, exc: BaseException, lines: int = TAIL_LINES
) -> Optional[str]:
    """Last `lines` lines of a failed task's captured stderr, or None."""
    path = _stderr_path(flow, fut, exc)
    if path is None:
        return None
    tail = _read_tail(path, lines)
    if tail is None:
        return None
    return f"stderr ({path}), last {lines} lines:\n{tail}"
