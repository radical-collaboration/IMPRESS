"""Wiring to systems outside IMPRESS-A.

A second composition root, in the sense `cli` already is: these modules build a whole campaign
on behalf of an owner that is not a person at a terminal. Nothing in the package imports them
unless a caller asks, and nothing in them is imported by any other layer - the dependency runs
one way, outward, so an integration can name another project's types without any of IMPRESS-A
needing to know that project exists.

`reporting` is transport-neutral and names no superstrate. The adapters beside it are the ones
allowed to import somebody else's package, and each is the only module that does.
"""
from .reporting import PAUSE, RESUME, Bridge, CycleSink, JsonlSink, run_with_sink

__all__ = ["PAUSE", "RESUME", "Bridge", "CycleSink", "JsonlSink", "run_with_sink"]
