#!/usr/bin/env python
"""Thin, real .py entrypoint for `dragon -s`/`dragon -m`.

`impress-a` is a setuptools console-script shim; whether Dragon's launcher correctly execs
one is unverified (the old IMPRESS Delta scripts always launched a plain `.py` file, e.g.
`dragon -s run_small_molecule_binding.py`). This file exists purely to remove that risk -
`dragon ${DRAGON_MODE} scripts/delta_run_campaign.py run campaigns/... --model D` mirrors
the old invocation shape exactly.
"""
import sys

from impress_a.cli import main

if __name__ == "__main__":
    sys.exit(main())
