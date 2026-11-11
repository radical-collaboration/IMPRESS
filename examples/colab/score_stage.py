#!/usr/bin/env python3
"""One simulated analysis stage, as a real process.

The pipeline's tasks exec this script, so the scores the adaptive rule reacts
to genuinely come back out of a subprocess, through the real execution backend,
as that task's stdout. Nothing is faked in the pipeline's own address space.

    python3 score_stage.py T3 2 0 0 7 1.5 1 0.2
                           |  | | | |  |  | |
                           |  | | | |  |  | task duration, seconds
                           |  | | | |  |  fragile (1/0)
                           |  | | | |  noise sd
                           |  | | | master seed
                           |  | | migrated into a child pipeline (1/0)
                           |  | generation
                           |  pass index
                           target

Prints one float on stdout and nothing else.

Every argument is a bare token on purpose. `LocalExecutionBackend` receives the
command string, `shlex.split`s it and re-joins the parts with spaces, so any
quoting is lost: `'two words'` arrives as two separate arguments. That is
backlog F15. A command built for this backend must never rely on quotes.

Python puts a script's own directory on `sys.path[0]`, so the `toy_science`
import below resolves however this file is invoked.
"""

from __future__ import annotations

import sys
import time

from toy_science import simulate_score

ARG_COUNT = 8

USAGE = (
    "usage: score_stage.py TARGET PASS GENERATION MIGRATED SEED "
    "NOISE_SD FRAGILE DURATION_S"
)


def main(argv: list) -> int:
    if len(argv) != ARG_COUNT:
        print(USAGE, file=sys.stderr)
        return 2

    target = argv[0]
    pass_index = int(argv[1])
    generation = int(argv[2])
    migrated = bool(int(argv[3]))
    seed = int(argv[4])
    noise_sd = float(argv[5])
    fragile = bool(int(argv[6]))
    duration_s = float(argv[7])

    # Stands in for the minutes a structure prediction would take. It is what
    # gives the Gantt chart bars with any width, so it is load-bearing for the
    # figures rather than decoration.
    if duration_s > 0:
        time.sleep(duration_s)

    print(
        simulate_score(
            target=target,
            pass_index=pass_index,
            generation=generation,
            migrated=migrated,
            seed=seed,
            noise_sd=noise_sd,
            fragile=fragile,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
