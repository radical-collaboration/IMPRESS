#!/usr/bin/env python
"""
Wrapper for LigandMPNN run.py that restores deprecated numpy aliases removed
in NumPy 1.24+. LigandMPNN's bundled openfold uses np.int, np.object, np.bool.

Usage (from mpnn.sh):
    python mpnn_run.py <mpnn_dir> [run.py args...]
The mpnn_dir is stripped from sys.argv before run.py sees it.
"""
import sys
import os

import numpy as np
for _alias, _builtin in [('int', int), ('float', float), ('bool', bool),
                          ('complex', complex), ('object', object), ('str', str)]:
    if not hasattr(np, _alias):
        setattr(np, _alias, _builtin)

mpnn_dir = sys.argv[1]
sys.argv = [os.path.join(mpnn_dir, 'run.py')] + sys.argv[2:]
sys.path.insert(0, mpnn_dir)
os.chdir(mpnn_dir)

import runpy
runpy.run_path(os.path.join(mpnn_dir, 'run.py'), run_name='__main__')
