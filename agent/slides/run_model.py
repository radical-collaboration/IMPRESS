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
  analysis  the twelve-section performance analysis of the Tier A/B jobs, TRANSCRIBED from
            its report: it is recomputable, but only from the run archive, not from a checkout
  baseline  the reference IMPRESS pipeline. Its `code` half is MINED from the reference checkout
            (null when that checkout is absent); its `measured` half is TRANSCRIBED from that
            pipeline's own performance report over its own run archives
  delta     the Delta jobs, TRANSCRIBED from plans/first-real-run.md, plans/backlog.md,
            plans/next-run-promotion.md and plans/next-run-sustained-trust.md. The raw logs live
            under $WORK_DIR/impress_a_runs/<jobid>_<campaign> on Delta, not here; when a copy
            exists locally, read it instead and drop the transcription.
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
    kits = sorted(p.name for p in (ROOT / "toolkits").iterdir()
                  if (p / "SKILL.md").exists())
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    return {"head": head, "packages": dict(sorted(pkgs.items(), key=lambda kv: -kv[1])),
            "src_total": sum(pkgs.values()), "test_lines": tests,
            "tests_collected": int(collected.split()[0]), "tools": tools,
            "n_tools": len(tools), "toolkits": kits, "n_toolkits": len(kits),
            "n_real_toolkits": len([k for k in kits if k != "mock"])}


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
    "source": "plans/first-real-run.md, plans/backlog.md, plans/next-run-promotion.md, "
              "plans/next-run-sustained-trust.md - transcribed, raw logs on Delta",
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
        # The three trust runs. Per-stage durations were not transcribed for these - only per-run
        # wall times - so they carry no "stages" and must not be drawn on slide 12's bar axis.
        {"job": "22702568", "date": None, "storage": "nvme",
         "outcome": "5 runs, 30/30 tasks ok, promoted NOTHING under the all-gates rule "
                    "(decision 0013)",
         "stages": {}},
        {"job": "22726105", "date": "2026-10-07", "storage": "nvme",
         "outcome": "5 runs, 30/30 ok in 13m41s; promoted after r0002, the trusted path "
                    "executed, r0004 demoted",
         "stages": {}},
        {"job": "22728140", "date": "2026-10-07", "storage": "nvme",
         "outcome": "5 runs, 30/30 ok in 13m37s; three consecutive trusted cycles, no demotion, "
                    "no integrity failure",
         "stages": {}},
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
    # The trusted path, per run. Transcribed from the outcome tables in
    # plans/next-run-promotion.md (22726105) and plans/next-run-sustained-trust.md (22728140);
    # the per-task metrics behind them are in tests/test_validation.py, which replays both jobs.
    "trust": {
        "promote_after": 3,
        "carried_in": "22702568's last ledger event was `clean`, so the site ledger folded to "
                      "clean_runs=1 and promotion came after r0002 rather than r0003",
        "22702568": {
            "wall": None, "runs": 5, "tasks": "30/30",
            "ledger": ["failure", "clean", "failure", "failure", "clean"],
            "promoted": None,
            "note": "every tool worked in every cycle; three designs merely scored short, and "
                    "the all-gates rule counted that against the pattern",
        },
        "22726105": {
            "wall": "13m41s", "commit": "5629a9a", "runs": 5, "promoted": "r0002",
            "rows": [
                ("r0001", "provisional", "6/6", "suspect", "none", "clean"),
                ("r0002", "provisional", "6/6", "fail",
                 "Boltz pLDDT 0.475, ipTM 0.389 (acceptance)", "clean, PROMOTED"),
                ("r0003", "trusted", "6/6", "fail",
                 "LigandMPNN confidence 0.377 (acceptance)", "-"),
                ("r0004", "trusted", "6/6", "fail",
                 "packmin total_score 1064.5 (INTEGRITY), pLDDT 0.498", "failure, DEMOTED"),
                ("r0005", "provisional", "6/6", "fail",
                 "pLDDT 0.417, ipTM 0.382 (acceptance)", "clean"),
            ],
        },
        "22728140": {
            "wall": "13m37s", "commit": "e9f44cd", "runs": 5, "promoted": "r0002",
            "rows": [
                ("r0001", "provisional", "6/6", "suspect", "none", "clean"),
                ("r0002", "provisional", "6/6", "fail", "ipTM 0.395", "clean, PROMOTED"),
                ("r0003", "trusted", "6/6", "fail",
                 "LigandMPNN confidence 0.394/0.391, shape complementarity 0.471", "-"),
                ("r0004", "trusted", "6/6", "fail", "pLDDT 0.364, ipTM 0.349", "-"),
                ("r0005", "trusted", "6/6", "fail",
                 "LigandMPNN confidence 0.397, pLDDT 0.494, ipTM 0.360", "-"),
            ],
            "trusted_cycles": 3, "demotions": 0, "integrity_failures": 0,
        },
        # The two defects the trusted path itself found.
        "packmin_bound": {"was": "total_score <= 1000.0", "tripped_on": 1064.5,
                          "relaxed_to": -336.0, "fa_rep": 119.1, "deleted_in": "d668838",
                          "now": "metrics_reported, and fastrelax converging is the judgement"},
        "cycle_off_by_one": {"asked": 6, "ran": 5, "fixed_in": "76594d4",
                             "why": "the driver counted a Backtrack as a cycle"},
        "acceptance_rate": {"passed": 5, "of": 16, "pct": 31},
        "packmin_range": [-95.8, 1064.5], "fastrelax_range": [-503.1, -200.1],
        "fa_rep_range": [71, 196],
    },
}


# ---------------------------------------------------------------------------- the baseline
# The reference IMPRESS pipeline, in two halves kept apart for the same reason DELTA is kept
# apart from `code`: one is re-derived from a checkout, the other cannot be.
#
#   baseline["code"]      MINED from the reference checkout when it is present. Absent ⇒ None,
#                         and the slide says the checkout was not there - never a zero.
#   baseline["measured"]  TRANSCRIBED from that pipeline's own performance report, which reads
#                         run archives no checkout can reproduce. Every slide showing one of
#                         these repeats the source in its footer.
# The reference pipeline is this repository's own example once impress_a lives in IMPRESS
# under agent/; IMPRESS_ROOT points elsewhere if the deck is built from another checkout.
REF = Path(os.environ.get("IMPRESS_ROOT") or Path(__file__).resolve().parents[2]) \
    / "examples" / "small_molecule_binding"


def baseline_code() -> dict | None:
    """Mine what it costs to CHANGE the reference pipeline, from the reference pipeline.

    The comparison the deck makes is not about throughput - it is about where a pipeline's
    shape lives. Here it lives in a hand-written state machine: `next_step` assignments inside
    one decision function, over a fixed set of STEP_ constants, with the thresholds in a
    dataclass in the runner. So those are the things counted, and they are counted rather than
    asserted because the authors of the file are in the room.
    """
    pipeline, runner = REF / "small_molecule_binding.py", REF / "run_small_molecule_binding.py"
    nonadaptive = REF / "run_nonadaptive.py"
    if not pipeline.exists() or not runner.exists():
        return None
    body = runner.read_text(errors="replace").splitlines()
    start = next(i for i, l in enumerate(body) if l.startswith("def _adaptive_decision_sync"))
    end = next(i for i, l in enumerate(body[start + 1:], start + 1)
               if l.startswith(("def ", "async def ", "@")))
    decision = body[start:end]
    text = pipeline.read_text(errors="replace")
    prod = {}
    m = re.search(r"^PROD = RunConfig\((.*?)^\)", runner.read_text(errors="replace"),
                  re.S | re.M)
    # Strip the trailing comments first: several carry their own figures (`# p75 = -8.8`),
    # and a parser that reads those reports a threshold the runner does not have.
    block = re.sub(r"#.*", "", m.group(1)) if m else ""
    for k, v in re.findall(r"(\w+)\s*=\s*([-\d.]+|None)", block):
        prod[k] = None if v == "None" else float(v)
    return {
        "lines": {"pipeline": _lines(pipeline), "runner": _lines(runner),
                  "nonadaptive": _lines(nonadaptive) if nonadaptive.exists() else None},
        "decision_fn_lines": len(decision),
        "next_step_sites": sum(1 for l in decision if re.search(r"next_step\s*=", l)),
        "steps": re.findall(r"^STEP_(\w+)\s*=", text, re.M),
        # Only what is actually registered as a task: the file also defines a decorator
        # wrapper, `run` and helper coroutines, and counting those inflates the stage count.
        "tool_stages": [n for n in re.findall(
            r"auto_register_task\([^)]*\)\s*(?:@[^\n]*\n\s*)*async def (\w+)\(", text)
            if not n.startswith("analysis_")],
        "analysis_stages": re.findall(r"async def (analysis_\w+)\(", text),
        "prod": prod,
        "head": sh_ref(),
    }


def our_rosetta_gates() -> dict:
    """Our own thresholds on the two stages we share with the reference pipeline.

    Mined, not quoted, because the deck makes a comparison in which WE are the weaker side
    (backlog G4/G5) - and a hand-copied number in that direction is the one nobody checks.
    """
    import yaml

    out: dict[str, dict] = {}
    for tool in ("packmin", "fastrelax"):
        spec = yaml.safe_load((ROOT / "toolkits" / "rosetta" / "tools" / tool
                               / "spec.yaml").read_text())
        out[tool] = {g["params"]["metric"]: {k: v for k, v in g["params"].items()
                                             if k in ("min", "max")}
                     for g in spec["qc_gates"] if g["id"] == "metric_in_range"}
    return out


def sh_ref() -> str:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REF.parent.parent,
                       capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


# Transcribed from the reference pipeline's own performance report over
# impress_runs_export_nvme_2026-10-08.tar.gz (jobs 22692293, 22701168, 22718758, 22726386).
# A40 nodes, 1-8 nodes, 8-256 pipelines - a different machine and a different scale from every
# IMPRESS-A figure in DELTA, which is why no slide divides one by the other.
BASELINE_MEASURED = {
    "source": "IMPRESS small-molecule performance report (impress-smallmol-performance/"
              "report.md), over impress_runs_export_nvme_2026-10-08.tar.gz",
    "hardware": "A40, 1-8 nodes, 8-256 pipelines",
    "scale": {"task_dirs": 24026, "metric_values": 1208591, "gpu_h_billed": 267.9,
              "passing_folds_clean": 913, "jobs": 4, "task_failures_clean": 0},
    # per packing: GPU utilisation mean, GPU-h per passing fold, rfd3 per node-hour
    "packing": {"k1": {"gpu": [0.114, 0.122], "gpu_h_per_fold": 0.159, "rfd3_node_h": 63.0},
                "k8": {"gpu": 0.705, "gpu_h_per_fold": 0.053, "rfd3_node_h": 316.5}},
    "busy_share": [0.955, 0.979],
    "manager": {"occupancy": [0.0049, 0.0177], "p99_s": [0.065, 0.287],
                "dispatch_median_s": 0.001,
                "regression": {"job": "22534628", "occupancy": 0.67, "p99_s": 56}},
    "depth": {"plddt_terciles": [90.7, 95.2, 95.0], "iptm_terciles": [0.845, 0.889, 0.896],
              "reached_4h": 280, "reached_1h": 42.5},
    "guided": {"pairs": 602, "d_plddt": 0.011, "better_share": 0.505, "p": 0.85,
               "by_parent": {"weak": 1.44, "mid": 0.02, "strong": -0.17},
               "tasks_per_fold": {"guided": 8.1, "scratch": 34.8}},
    "novelty": {"folds": 804, "distinct_seqs": 794, "clusters_90pct": 596,
                "folds_per_cluster": 1.3, "cross_pipeline_identity": [0.110, 0.125]},
    "routing": {"decisions": 13074, "retry_seq": 0.320, "backbone_reject": 0.055,
                "fastrelax_escalate": 0.131, "interface": 0.031},
    "quota_failure": {"job": "22726386", "pipelines": 256, "killed": 245, "quota": 174,
                      "oom": 59, "gpu_h_billed": 128.0, "gpu_h_wasted": 108},
    # This one is transcribed from OUR docs, not theirs: docs/limitations.md:133-136.
    "teardown": {"job": "22491438", "pipelines": 16, "minutes": 60, "gpu_h": 64,
                 "share_of_billed": 0.37, "source": "docs/limitations.md"},
}

# Transcribed from the off-cluster reproduction of performance_analysis/ (twelve sections) over
# impress_a_runs_2026-10-08.tar.gz. Recomputable - but only from the archive, not the checkout,
# so it is labelled like DELTA rather than mined like `code`.
ANALYSIS = {
    "source": "performance_analysis report 2026-10-09 over impress_a_runs_2026-10-08.tar.gz "
              "(22702568, 22726105, 22728140 trust; 22684607, 22692304 smoke), code at d3c20ca",
    "n_timed_tasks": 101,
    # tool -> [n, median, q1, q3, min, max]
    "stage_s": {"rfd3_design": [17, 41.0, 40.7, 45.1, 40.1, 145.7],
                "ligandmpnn_design": [17, 7.1, 6.6, 14.6, 6.0, 18.1],
                "packmin": [17, 6.0, 5.2, 15.2, 5.1, 16.4],
                "fastrelax": [17, 25.9, 22.4, 35.2, 13.1, 48.0],
                "filter_shape": [17, 10.2, 10.0, 10.5, 9.5, 13.1],
                "boltz_predict": [16, 52.1, 51.7, 60.1, 49.6, 64.8]},
    "rfd3_tight": {"n": 15, "of": 17, "band": [40, 45], "others": [48.0, 145.7]},
    "warmup_s": {"packmin": 10.5, "ligandmpnn_design": 8.6, "boltz_predict": 7.8,
                 "rfd3_design": 4.3},
    "cost": {"declared_per_chain": 0.17, "measured_median": 0.0285, "measured_max": 0.0337,
             "recommended_per_chain": 0.105, "min_declared_over_max": 2.25,
             "untrusted_cap": 0.6, "lineages_admissible": 3},
    "allocation": {"partition": "gpuA100x4-interactive", "gpus": 4, "cpus": 64,
                   "gpu_share_max": [0.154, 0.167], "task_share_trust": [0.948, 0.954],
                   "cpu_eff": [0.369, 0.424], "maxrss_gb": 16.3, "mem_gb": 240,
                   "queue_s": [12269, 26626, 25278, 478, 184],
                   "elapsed_s": [245, 191, 805, 821, 817]},
    # [median_untrusted, median_trusted, difference, ci95] over 11 untrusted and 5 trusted runs
    "scrutiny": {"n_untrusted": 11, "n_trusted": 5,
                 "run_s": [167.0, 159.1, 7.9, [-17.9, 30.2]],
                 "overhead_s": [2.9, 2.8, 0.0, [-0.9, 1.2]]},
    "diversity": {"designs": 17, "seeds": 5, "tm_same_seed": 0.82, "tm_other": 0.28,
                  "identical_backbones": 0, "ca_rmsd": 2.39},
}


def main() -> int:
    run = {"code": code_stats(), "mock": mock_campaign(), "patterns": pattern_census(),
           "shape": shape_signatures(), "delta": DELTA, "analysis": ANALYSIS,
           "baseline": {"code": baseline_code(), "measured": BASELINE_MEASURED,
                        "our_rosetta_gates": our_rosetta_gates()}}
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
    bc = run["baseline"]["code"]
    print(f"  baseline: {bc['lines']['pipeline']}+{bc['lines']['runner']} lines, "
          f"{bc['next_step_sites']} next_step sites in {bc['decision_fn_lines']} lines, "
          f"{len(bc['steps'])} steps, {len(bc['tool_stages'])} tool stages @ {bc['head']}"
          if bc else "  baseline: reference checkout absent - code half is null")
    return 0


if __name__ == "__main__":
    sys.exit(main())
