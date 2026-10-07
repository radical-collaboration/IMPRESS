#!/usr/bin/env python3
"""Mine every number the deck prints into slides/run.json.

    python slides/run_model.py          # with the project venv active

Five sources, each labelled in the output so a slide can say where its number came from:

  code      line counts per package and the collected test count, read from this checkout
  mock      a real mock-toolkit campaign (`campaigns/mock-stabilize.yaml --model D`), run in a
            temporary directory so neither `asyncflow.session.*` nor `campaigns/_runs` lands in
            the repo, then mined from its own provenance, ledger and trust files
  patterns  which of the eight compute patterns the registered tools actually declare, and every
            site in src/ that consults one - the census and the claim on slide 11
  shape     the real six-stage chain composed at 1, 2 and 4 replicas, and its pattern signature
            for each - the evidence for the A10 finding on slide 14
  delta     the four Delta jobs, TRANSCRIBED from plans/first-real-run.md and plans/backlog.md.
            The raw logs live under $WORK_DIR/impress_a_runs/<job> on Delta, not here; when a
            copy exists locally, read it instead and drop the transcription.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
OUT = Path(__file__).resolve().parent / "run.json"
CHAIN = ["rfd3_design", "ligandmpnn_design", "packmin", "fastrelax", "filter_shape",
         "boltz_predict"]


def _lines(p: Path) -> int:
    return sum(1 for _ in p.open(errors="replace"))


def code_stats() -> dict:
    pkgs: dict[str, int] = {}
    for f in (SRC / "impress_a").rglob("*.py"):
        rel = f.relative_to(SRC / "impress_a")
        key = rel.parts[0] if len(rel.parts) > 1 else rel.name
        pkgs[key] = pkgs.get(key, 0) + _lines(f)
    tests = sum(_lines(f) for f in (ROOT / "tests").glob("*.py"))
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--collect-only"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(SRC)}).stdout.strip().splitlines()[-1]
    tools = sorted(p.parent.name for p in (ROOT / "toolkits").glob("*/tools/*/spec.yaml"))
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    return {"head": head, "packages": dict(sorted(pkgs.items(), key=lambda kv: -kv[1])),
            "src_total": sum(pkgs.values()), "test_lines": tests,
            "tests_collected": int(collected.split()[0]), "tools": tools,
            "n_tools": len(tools)}


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def mock_campaign() -> dict:
    with tempfile.TemporaryDirectory(prefix="impress-a-deck-") as tmp:
        proc = subprocess.run(
            [sys.executable, "-m", "impress_a", "run",
             str(ROOT / "campaigns" / "mock-stabilize.yaml"), "--model", "D"],
            cwd=tmp, capture_output=True, text=True, timeout=600,
            env={**os.environ, "PYTHONPATH": str(SRC)})
        if proc.returncode:
            raise SystemExit(f"mock campaign failed:\n{proc.stdout}\n{proc.stderr}")
        runs = Path(tmp) / "campaigns" / "_runs"
        camp = next(p for p in runs.iterdir() if p.name != "_trust")
        prov = camp / "provenance"
        graphs = _jsonl(prov / "graphs.jsonl")
        results = _jsonl(prov / "results.jsonl")
        trans = _jsonl(prov / "transitions.jsonl")
        trust = _jsonl(runs / "_trust" / "cuda.jsonl")
        ledger = _jsonl(camp / "jobs" / "ledger.jsonl")
    end = next(t for t in trans if t["event"] == "terminated")
    return {
        "campaign": camp.name,
        "stdout_tail": proc.stdout.strip().splitlines()[-10:],
        "admissions": [{"run": g["run"], "signature": g["signature"],
                        "nodes": len(g["nodes"]), "estimate": g["estimate"],
                        "trusted": g["trusted"], "rejected": g["rejected"]} for g in graphs],
        "nodes": [{"node": r["node"], "run": r["run"], "lineage": r["lineage"],
                   "qc": r["qc"], "metrics": r["metrics"]} for r in results],
        "front": end["front"], "stop": end["reason"], "cycles": end["cycles"],
        "promoted": [t["signature"] for t in trans if t["event"] == "pattern_promoted"],
        "trust_events": [{"event": t["event"], "signature": t["signature"]} for t in trust],
        "ledger_records": len(ledger),
    }


def pattern_census() -> dict:
    """Which compute patterns the eleven registered tools actually declare, and who asks.

    Both halves of slide 11 are mined rather than remembered. The census exists because the
    taxonomy has eight members and the registry exercises two of them, and a slide that lists
    eight patterns without saying so reads as if all eight were in service. `consulted_in` is
    the other half: it is the complete set of places that branch on a pattern, which is how
    the slide can claim nothing in exec/ or runtime/ does.
    """
    sys.path.insert(0, str(SRC))
    from impress_a.core.types import Pattern
    from impress_a.tools.registry import Registry

    reg = Registry().load()
    members: dict[str, list[str]] = {p.value: [] for p in Pattern}
    for tid in reg.ids():
        members[reg.get(tid).pattern.value].append(tid)

    consulted: list[dict] = []
    for f in sorted((SRC / "impress_a").rglob("*.py")):
        rel = f.relative_to(SRC / "impress_a").as_posix()
        if rel == "core/types.py":          # the definition, not a consumer
            continue
        hits = [i + 1 for i, line in enumerate(f.read_text(errors="replace").splitlines())
                if re.search(r"\bPattern\.P[1-8]\b|\.is_inline\b|\.is_external\b", line)]
        if hits:
            consulted.append({"file": rel, "lines": hits})

    return {
        "declared": [p.value for p in Pattern],
        "members": {k: sorted(v) for k, v in members.items()},
        "counts": {k: len(v) for k, v in members.items()},
        "in_use": sorted(k for k, v in members.items() if v),
        "unused": sorted(k for k, v in members.items() if not v),
        "inline": [p.value for p in Pattern if p.is_inline],
        "external": [p.value for p in Pattern if p.is_external],
        "consulted_in": consulted,
    }


def shape_signatures() -> dict:
    sys.path.insert(0, str(SRC))
    from impress_a.compose.composer import Composer
    from impress_a.core.decision import ExperimentIntent
    from impress_a.tools.registry import Registry

    reg = Registry().load()
    out = {}
    for r in (1, 2, 4):
        g = Composer(reg).compose(ExperimentIntent(goal="deck", stages=CHAIN, replicas=r))
        out[str(r)] = {"signature": g.pattern_signature(), "nodes": len(g.nodes)}
    tuned = Composer(reg).compose(ExperimentIntent(
        goal="deck", stages=CHAIN, replicas=1, params={"rfd3_design": {"num_designs": 3}}))
    out["1_tuned_params"] = {"signature": tuned.pattern_signature(), "nodes": len(tuned.nodes)}
    return out


# Transcribed. Source for every figure: plans/first-real-run.md and plans/backlog.md (A1, A6,
# A7, A11). None is None, never 0: a stage that did not run has no duration.
DELTA = {
    "source": "plans/first-real-run.md, plans/backlog.md - transcribed, raw logs on Delta",
    "jobs": [
        {"job": "22536706", "date": "2026-09-29", "storage": "hdd",
         "outcome": "rfd3 ok; ligandmpnn failed, stderr lost (G6); hung at inflight=1",
         "stages": {"rfd3_design": 180.0}},
        {"job": "22669509", "date": "2026-10-04", "storage": "hdd",
         "outcome": "rfd3 ok; ligandmpnn FAILED loudly at import (A6) after 276s",
         "stages": {"rfd3_design": None, "ligandmpnn_design": 276.0}},
        {"job": "22684607", "date": "2026-10-05", "storage": "nvme",
         "outcome": "5/5 ok in 3m44s; boltz truncated off by the cost cap (A7)",
         "stages": {"rfd3_design": 145.7, "ligandmpnn_design": 18.1, "packmin": 15.9,
                    "fastrelax": 25.9, "filter_shape": 10.2}},
        {"job": "22692304", "date": "2026-10-06", "storage": "nvme",
         "outcome": "6/6 ok in 2m53s, first attempt, one-node front",
         "stages": {"rfd3_design": 45.0, "ligandmpnn_design": 14.6, "packmin": 15.2,
                    "fastrelax": 22.4, "filter_shape": 10.0, "boltz_predict": 57.8}},
    ],
    "hdd_baseline_22675512": {"rfd3_design": 137.2, "ligandmpnn_design": 292.6,
                              "packmin": "could not finish import pyrosetta in 300s"},
    "import_cost_s": {"pyrosetta_hdd": 471, "torch_hdd": 280},
    "completed": {
        "job": "22692304", "wall": "2m53s", "cost": {"gpu_hours": 0.27, "cpu_hours": 0.06},
        "qc": "suspect", "front": ["n000001-4101"],
        "metrics": {"ss_fraction": 0.827, "overall_confidence": 0.448,
                    "ligand_confidence": 0.424, "total_score": -272.0, "fa_rep": 109.4,
                    "shape_complementarity": 0.591, "complex_plddt": 0.507,
                    "ligand_iptm": 0.752},
    },
    "filter_shape_sc": {"22684607": 0.524, "22692304": 0.591, "bound": 0.55},
    "cost_guess_over_measured": [6, 69],
    "boltz_cost": {"declared": 0.15, "measured": 0.0160, "now": 0.05},
    "untrusted_cap": {"replicas4_gpu_h": 0.68, "cap": 0.60},
}


def main() -> int:
    run = {"code": code_stats(), "mock": mock_campaign(), "patterns": pattern_census(),
           "shape": shape_signatures(), "delta": DELTA}
    OUT.write_text(json.dumps(run, indent=1) + "\n")
    m = run["mock"]
    print(f"wrote {OUT}")
    print(f"  code: {run['code']['src_total']} src lines, {run['code']['tests_collected']} tests,"
          f" {run['code']['n_tools']} tools @ {run['code']['head']}")
    print(f"  mock: {len(m['admissions'])} admissions, {len(m['nodes'])} nodes, "
          f"front {len(m['front'])}, promoted {m['promoted']}")
    pat = run["patterns"]
    print("  patterns: " + ", ".join(f"{k}={pat['counts'][k]}" for k in pat["declared"])
          + f"  ({len(pat['in_use'])}/8 in use; consulted in "
          + ", ".join(c["file"] for c in pat["consulted_in"]) + ")")
    print("  shape: " + ", ".join(f"r{k}={v['signature']}" for k, v in run["shape"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
