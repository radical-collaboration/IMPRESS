"""Planner halves, one module per control model.

Imports `core` only, like everything else under `policy/` - asserted by
`tests/test_layering.py`. What a Planner may know about the Toolkit arrives as a
`core.toolkit.ToolkitView`, never as a registry.
"""
from .explicit import ThresholdPlanner

__all__ = ["ThresholdPlanner"]
