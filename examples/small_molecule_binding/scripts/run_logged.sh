#!/bin/bash
# Run a stage script with its combined stdout/stderr written to a per-task log.
# Args: $1=log_file $2...=command and its arguments
#
# The asyncflow backend owns the process; this only keeps the per-stage
# {taskdir}/<stage>.log files that existed when these stages were spawned
# in-process. On failure the log tail goes to stderr, which is what the
# backend reports back in the task's RuntimeError.

log_file="$1"
shift

"$@" > "$log_file" 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
    echo "$* failed with exit code $rc -- see $log_file" >&2
    tail -n 20 "$log_file" >&2
fi
exit "$rc"
