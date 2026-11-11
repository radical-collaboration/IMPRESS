# 0011 — `toolkits/` is top-level and declarative

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1C

## Context
Part A produced 52 tool entities. Their specifications are read by four consumers (composer, validator,
budget guard, task agent) and edited mainly by scientists.

## Decision
Tool specifications live in a **top-level `toolkits/` directory**, discovered from a configurable path, as
**declarative `spec.yaml` plus behavioural `agent.py`** per tool. Skill documents live in their toolkit
directory beside the tools they describe.

## Consequences
- Specs are reviewable in a pull request by someone who does not read Python, and diffable when a parameter
  range changes.
- A site or third party can add a toolkit without forking the package.
- Registration never requires editing the composer, validator or manager — the test of correct factoring.
- Skill-doc drift becomes a CI failure: required sections are checked, and tools and docs must reference
  each other.
- Cost: a non-trivial packaging story for non-package data.
