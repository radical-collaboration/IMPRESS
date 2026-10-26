#!/usr/bin/env python3
"""Mine every number the API deck prints into slides/api/run.json.

    python slides/api/run_model.py          # from agent/, with the deps importable

Three sources, each labelled in the output so a slide can say where its number came from:

  code       line counts per package, the collected test count and the tool census, read
             from this checkout
  surfaces   the six API surfaces, measured by INTROSPECTING them rather than by counting
             lines: the Protocol members of `ControlPolicy`, `CampaignSession` and
             `CampaignControlPlane`, the fields of `CampaignSpec` and `ToolSpec`, the
             members of the `Decision` union, the registered QC gates, the HTTP route
             table, and the layering allow-list. A surface that gains an operation changes
             these numbers, which is the point - a deck that quotes a hand-counted
             "ten operations" is wrong one commit later and says nothing when it is.
  mock       a real mock-toolkit campaign (`campaigns/mock-stabilize.yaml --model D`), run
             in a temporary directory so neither `asyncflow.session.*` nor
             `campaigns/_runs` lands in the repo, then mined from its own provenance,
             ledger and trust files.

  live       the agentic small-molecule example next door - the reference IMPRESS pipeline
             with its state machine removed and an LLM calling the tools directly. Its
             `code` half is MINED from examples/agentic_small_molecule_binding; its `runs`
             half is TRANSCRIBED from that example's own CLAUDE.md, which records each
             Delta job. It is the only place in this repository where a model has driven
             real tools on real hardware, and it is NOT IMPRESS-A: no shared code, no
             campaign engine, no gates. The deck shows it because the idea IMPRESS-A is
             built on stopped being hypothetical on 2026-10-22, and because what that
             model did badly is what the engine's gates exist to catch.

Every other figure comes from this checkout or from a run this script performs, because
the deck is about the API rather than about a campaign on Delta - and the one claim that
would need a cluster (what the loop costs at `replicas > 1`) is the claim the deck
concedes instead of making. Transcribed figures live in `live.runs` with a `source` field,
and every slide that shows one repeats the source in its footer.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent              # agent/
SRC = ROOT / "src"
OUT = HERE / "run.json"

sys.path.insert(0, str(SRC))


def _lines(p: Path) -> int:
    return sum(1 for _ in p.open(errors="replace"))


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


# --------------------------------------------------------------------------- code
def code_stats() -> dict:
    pkgs: dict[str, int] = {}
    for f in (SRC / "impress_a").rglob("*.py"):
        rel = f.relative_to(SRC / "impress_a")
        key = rel.parts[0] if len(rel.parts) > 1 else rel.name
        pkgs[key] = pkgs.get(key, 0) + _lines(f)
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--collect-only"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(SRC)}).stdout.strip().splitlines()
    n_tests = int(collected[-1].split()[0]) if collected else 0
    kits = sorted(p.name for p in (ROOT / "toolkits").iterdir()
                  if (p / "SKILL.md").exists())
    fixtures = sorted((ROOT / "toolkits").glob("*/tools/*/tests/*.json"))
    return {
        "head": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "packages": dict(sorted(pkgs.items(), key=lambda kv: -kv[1])),
        "src_total": sum(pkgs.values()),
        "test_lines": sum(_lines(f) for f in (ROOT / "tests").glob("*.py")),
        "test_files": len(list((ROOT / "tests").glob("test_*.py"))),
        "tests_collected": n_tests,
        "toolkits": kits, "n_toolkits": len(kits),
        "n_real_toolkits": len([k for k in kits if k != "mock"]),
        "gate_fixtures": len(fixtures),
        "gate_fixtures_bad": len([f for f in fixtures if f.name.endswith(".bad.json")]),
    }


# ----------------------------------------------------------------------- surfaces
def _protocol_members(cls) -> list[str]:
    """The operations a Protocol actually declares, in declaration order.

    `__annotations__` misses the methods and `dir()` sorts them, which loses the grouping
    the source puts them in - and that grouping is what a slide reproduces.
    """
    src = ast.parse(Path(sys.modules[cls.__module__].__file__).read_text())
    for node in ast.walk(src):
        if isinstance(node, ast.ClassDef) and node.name == cls.__name__:
            return [n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not n.name.startswith("_")]
    return []


def _http_routes() -> list[dict]:
    """The route table, read out of the `head ==` cascade in control/http.py.

    Mined rather than listed because the module's own docstring promises the routes are a
    mechanical rendering of the protocol: if one is added there and not here, the count
    beside the protocol's operation count on the slide stops matching, which is the
    failure worth noticing.
    """
    text = (SRC / "impress_a" / "control" / "http.py").read_text()
    tree = ast.parse(text)
    heads: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name):
            continue
        if node.left.id not in ("head", "tail"):
            continue
        for c in node.comparators:
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value:
                heads.append(c.value)
            elif isinstance(c, (ast.Tuple, ast.List)):
                heads += [e.value for e in c.elts
                          if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    seen: list[str] = []
    for h in heads:
        if h not in seen:
            seen.append(h)
    return seen


def surfaces() -> dict:
    from impress_a.cli import POLICIES
    from impress_a.control.http import MAX_BODY_BYTES, MAX_WAIT_S, _STATUS
    from impress_a.control.plane import CampaignControlPlane
    from impress_a.core.decision import Decision, ExperimentIntent
    from impress_a.core.session import CampaignSession
    from impress_a.core.types import ArtifactType, Pattern
    from impress_a.policy.base import ControlPolicy
    from impress_a.runtime.executor import CampaignSpec
    from impress_a.tools import gates
    from impress_a.tools.registry import REQUIRED_SKILL_SECTIONS, Registry
    from impress_a.tools.spec import ToolSpec

    import dataclasses
    import typing

    reg = Registry().load()
    tools = [{"id": t, "pattern": reg.get(t).pattern.value, "toolkit": reg.get(t).toolkit,
              "gates": len(reg.get(t).qc_gates),
              "integrity": len([g for g in reg.get(t).qc_gates if g.role == "integrity"]),
              "acceptance": len([g for g in reg.get(t).qc_gates if g.role == "acceptance"]),
              "metrics": reg.get(t).metrics,
              "gpus": reg.get(t).resources.gpus,
              "walltime_s": reg.get(t).resources.walltime_s,
              "params": len(reg.get(t).parameters),
              "frozen": len(reg.get(t).frozen_parameters)}
             for t in reg.ids()]

    # The layering allow-list, read out of the test that enforces it.
    lay = ast.parse((ROOT / "tests" / "test_layering.py").read_text())
    allowed: dict[str, list[str]] = {}
    for node in ast.walk(lay):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "ALLOWED" for t in node.targets):
            for k, v in zip(node.value.keys, node.value.values):
                names = [e.value for e in ast.walk(v)
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                allowed[k.value] = sorted(names)

    policy_ops = _protocol_members(ControlPolicy)
    session_ops = _protocol_members(CampaignSession)
    plane_ops = _protocol_members(CampaignControlPlane)
    routes = _http_routes()

    return {
        "cli_subcommands": ["run", "tools", "preflight"],
        "cli_models": sorted(POLICIES),
        "n_cli_models": len(POLICIES),

        "campaign_spec_fields": [f.name for f in dataclasses.fields(CampaignSpec)],
        "n_campaign_spec_fields": len(dataclasses.fields(CampaignSpec)),

        "policy_ops": policy_ops,
        "decision_members": [m.__name__ for m in typing.get_args(Decision)],
        "intent_fields": list(ExperimentIntent.model_fields),

        "session_ops": session_ops,
        "n_session_ops": len(session_ops),

        "plane_ops": plane_ops,
        "n_plane_ops": len(plane_ops),
        "routes": routes,
        "n_routes": len(routes),
        "http_statuses": sorted(_STATUS),
        "max_wait_s": MAX_WAIT_S,
        "max_body_bytes": MAX_BODY_BYTES,

        "tool_spec_fields": list(ToolSpec.model_fields),
        "n_tool_spec_fields": len(ToolSpec.model_fields),
        "patterns": {p.name: p.value for p in Pattern},
        "n_patterns": len(list(Pattern)),
        "patterns_used": sorted({t["pattern"] for t in tools}),
        "artifact_types": [a.value for a in ArtifactType],
        "n_artifact_types": len(list(ArtifactType)),
        "gates_implemented": sorted(gates.known()),
        "n_gates_implemented": len(gates.known()),
        "required_skill_sections": list(REQUIRED_SKILL_SECTIONS),

        "tools": tools, "n_tools": len(tools),
        "registry_errors": reg.errors,
        "layering": allowed,
        "n_layers": len(allowed),
        "core_imports": allowed.get("core", []),
        "policy_imports": allowed.get("policy", []),
    }


# --------------------------------------------------------------------------- mock
def _jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def mock_campaign() -> dict:
    """One real campaign, end to end, on the bundled mock toolkit.

    Run in a temp directory: the campaign writes provenance, a job ledger and a trust
    ledger relative to its root, and a deck build must not leave any of that in the repo.
    """
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="impress-a-api-deck-") as tmp:
        proc = subprocess.run(
            [sys.executable, "-m", "impress_a", "run",
             str(ROOT / "campaigns" / "mock-stabilize.yaml"), "--model", "D"],
            cwd=tmp, capture_output=True, text=True, timeout=900,
            env={**os.environ, "PYTHONPATH": str(SRC)})
        if proc.returncode:
            raise SystemExit(f"mock campaign failed:\n{proc.stdout}\n{proc.stderr}")
        elapsed = time.monotonic() - t0
        runs = Path(tmp) / "campaigns" / "_runs"
        camp = next(p for p in runs.iterdir() if p.name != "_trust")
        prov = camp / "provenance"
        kinds = {p.stem: len(_jsonl(p)) for p in sorted(prov.glob("*.jsonl"))}
        graphs = _jsonl(prov / "graphs.jsonl")
        results = _jsonl(prov / "results.jsonl")
        trans = _jsonl(prov / "transitions.jsonl")
        execs = _jsonl(prov / "executions.jsonl")
        ledger = _jsonl(camp / "jobs" / "ledger.jsonl")
        trust = [t for f in sorted((runs / "_trust").glob("*.jsonl")) for t in _jsonl(f)] \
            if (runs / "_trust").is_dir() else []

    end = next((t for t in trans if t.get("event") == "terminated"), {})
    out = [l for l in proc.stdout.strip().splitlines() if l.strip()]

    # Every provenance record carries its own `ts`, so the campaign times itself. Offsets
    # from the first record are the only per-phase timing in this deck - and they are
    # measured, not estimated, which is why the performance act is allowed to print them.
    # The clock is the campaign's own and the stages are mocks: this measures the ENGINE
    # (compose, validate, dispatch, absorb), never the science.
    from datetime import datetime
    stamped = sorted(
        ((datetime.fromisoformat(r["ts"]), kind, r)
         for kind, recs in (("graphs", graphs), ("executions", execs),
                            ("results", results), ("transitions", trans))
         for r in recs if r.get("ts")),
        key=lambda t: t[0])
    t_first = stamped[0][0] if stamped else None
    timeline = [{
        "at_s": round((ts - t_first).total_seconds(), 3),
        "kind": kind,
        "event": (r.get("event")
                  or ("rejected" if r.get("rejected") else "composed") if kind == "graphs"
                  else r.get("event") or ("absorbed" if kind == "results" else "dispatched")),
        "run": r.get("run") or r.get("job_id") or "",
        "detail": (r.get("graph") or r.get("node") or r.get("reason") or ""),
    } for ts, kind, r in stamped]

    # One row per composed graph. `lineages` is the replica width, counted from the node
    # ids the composer emitted (`r<lineage>_s<stage>_<tool>`), which is the only place the
    # width is recorded per graph - and it is what the pattern signature includes, so it
    # is the number the trust ledger is keyed on.
    composed = [{
        "graph": g["graph"], "run": g["run"], "signature": g["signature"],
        "cycle": g["cycle"], "trusted": g["trusted"],
        "lineages": len({k.split("_")[0] for k in g.get("nodes", {})}),
        "tasks": len(g.get("nodes", {})),
        "estimate": g.get("estimate", {}),
        "scrutiny": g.get("scrutiny", {}),
        "rejected": g.get("rejected"),
    } for g in graphs]
    admitted = [c for c in composed if not c["rejected"]]
    refused = [c for c in composed if c["rejected"]]

    # Signature -> the widths it was composed at. Two widths of the same chain are two
    # signatures, which is the A10 finding stated as data rather than as a claim.
    widths: dict[str, list[int]] = {}
    for c in composed:
        widths.setdefault(c["signature"], []).append(c["lineages"])

    return {
        "campaign": camp.name,
        "spec": "campaigns/mock-stabilize.yaml",
        "model": "D",
        "elapsed_s": round(elapsed, 1),
        "stdout_tail": out[-9:],
        "provenance_kinds": kinds,
        "provenance_records": sum(kinds.values()),
        "composed": composed,
        "n_composed": len(composed),
        "n_admitted": len(admitted),
        "n_refused": len(refused),
        "refusals": [{"gate": c["rejected"]["gate"], "reason": c["rejected"]["reason"],
                      "transient": c["rejected"]["transient"],
                      "lineages": c["lineages"]} for c in refused],
        "widths_per_signature": widths,
        "n_signatures": len(widths),
        "n_results": len(results),
        "qc_verdicts": {v: len([r for r in results if r.get("qc") == v])
                        for v in sorted({r.get("qc") for r in results})},
        "failed_gates": sorted({g for r in results for g in r.get("failed_gates", [])}),
        "metric_names": sorted({m for r in results for m in r.get("metrics", {})}),
        "lineages_absorbed": sorted({r.get("lineage") for r in results}),
        "n_runs_executed": len([e for e in execs if e.get("event") == "run_finished"]),
        "cost": next((e.get("cost", {}) for e in execs if "cost" in e), {}),
        "n_ledger": len(ledger),
        "ledger_statuses": sorted({l.get("status") for l in ledger if l.get("status")}),
        "cycles": end.get("cycles"),
        "stop_reason": end.get("reason"),
        "front": end.get("front", []),
        "front_size": len(end.get("front", [])),
        "tools_used": sorted({t for g in graphs for t in g.get("nodes", {}).values()}),
        "trust_records": len(trust),
        "trust_seen": len([t for t in trust if t.get("event") == "seen"]),
        "trust_clean": len([t for t in trust if t.get("event") == "clean"]),
        "trust_promoted": len([t for t in trust if t.get("event") == "promoted"]),
        "timeline": timeline,
        "span_s": timeline[-1]["at_s"] if timeline else None,
    }



# --------------------------------------------------------------------------- live
# The only section mined from outside agent/, and the only one carrying figures a checkout
# cannot reproduce.
#
# examples/agentic_small_molecule_binding is the reference IMPRESS pipeline with its state
# machine removed: one LLM, the same eight tools, the same asyncflow/Dragon execution. It
# shares no code with IMPRESS-A and has no campaign engine, no gates and no interlock - which
# is exactly why the deck shows it. It is the only place in this repository where a model has
# driven real tools on real hardware.
#
#   live["code"]  MINED from the example on every build. If it grows a ninth tool or stops
#                 overriding exactly one inherited method, these numbers say so.
#   live["runs"]  TRANSCRIBED from that example's CLAUDE.md revision history, which is where
#                 each Delta job is recorded. The raw outputs live under $WORK_DIR on Delta,
#                 not here. Any slide showing one of these repeats the source in its footer.
AGENTIC = ROOT.parent / "examples" / "agentic_small_molecule_binding"
REFERENCE_PIPELINE = ROOT.parent / "examples" / "small_molecule_binding"


def _class_methods(path: Path, name: str) -> list[str]:
    """Every method a class defines, in declaration order."""
    tree = ast.parse(path.read_text(errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return [n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return []


def live_next_door() -> dict | None:
    """Mine the agentic example, then attach the runs nobody can re-derive here."""
    if not (AGENTIC / "tools.py").exists():
        return None
    schemas: list = []
    for node in ast.parse((AGENTIC / "tools.py").read_text()).body:
        target = getattr(node, "target", None)
        if isinstance(target, ast.Name) and target.id == "TOOL_SCHEMAS":
            schemas = ast.literal_eval(node.value)
    import yaml
    profiles = sorted(yaml.safe_load((AGENTIC / "models.yaml").read_text())["profiles"])

    # The example's whole claim is that only the DECISION layer changed. That is one
    # overridden method, and it is worth mining rather than repeating: a second override
    # would mean the two arms no longer place the same demands on an allocation.
    mine = _class_methods(AGENTIC / "agentic_pipeline.py", "AgenticSMBPipeline")
    theirs = _class_methods(REFERENCE_PIPELINE / "small_molecule_binding.py",
                            "SmallMoleculeBindingPipeline")
    overrides = [m for m in mine if m in theirs and not m.startswith("__")]

    files = {p.name: _lines(p) for p in sorted(AGENTIC.glob("*.py"))}
    return {
        "code": {
            "tools": [s["function"]["name"] for s in schemas],
            "n_tools": len(schemas),
            "profiles": profiles,
            "n_profiles": len(profiles),
            "overrides": overrides,
            "n_overrides": len(overrides),
            "files": files,
            "total_lines": sum(files.values()),
        },
        "runs": LIVE_RUNS,
    }


# TRANSCRIBED, every figure below, from the revision history in
# examples/agentic_small_molecule_binding/CLAUDE.md. Kept as one labelled block rather than
# scattered through the slides so that a slide cannot quietly acquire an unsourced number.
LIVE_RUNS = {
    "source": "examples/agentic_small_molecule_binding/CLAUDE.md - transcribed from its "
              "revision history; the run outputs live under $WORK_DIR on Delta, not here",
    "paired_4h": {
        "date": "2026-10-22", "hours": 4, "nodes": 1, "pipelines": 4,
        "partition": "gpuA40x4", "same_inputs": True,
        "reference": {"job": "23114772", "driver": "adaptive_decision()",
                      "rfd3_per_pipeline_h": 15.5, "passing_designs": 53,
                      "designs_per_node_h": 13.25, "gpu_h_per_design": 0.302,
                      "backbones_yielding": [53, 248], "fastrelax": [87, 176],
                      "mpnn_tasks": 858, "median_plddt": 89.6, "usd": None},
        "agentic": {"job": "23114775", "driver": "claude-sonnet-5-5",
                    "rfd3_per_pipeline_h": 16.2, "passing_designs": 176,
                    "designs_per_node_h": 44.0, "gpu_h_per_design": 0.083,
                    "backbones_yielding": [192, 260], "fastrelax": [213, 242],
                    "mpnn_tasks": 349, "median_plddt": 94.2, "usd": 25.40,
                    "usd_per_design": 0.14, "turns": 1462},
        "both": "ran the full 4 h to TIMEOUT, 0 task failures, 0 degraded turns",
        "caveats": [
            "The reference arm came in about 2x worse than its own record (22701168: "
            "0.160 GPU-h per passing fold), so an unknown part of the gap is a weak "
            "baseline rather than agent skill. Do not quote the 3.3x.",
            "The fastrelax gap - 88% against 49% on the same tool with the same "
            "thresholds - is unexplained, and it is where the funnel difference "
            "actually originates.",
        ],
    },
    "first_live_1h": {
        "date": "2026-10-22", "job": "23112484", "model": "claude-sonnet-5-5",
        "turns": 137, "invalid_tool_calls": 0, "degraded": 0,
        "ended": "by itself at 37:54, runner_status ok", "folds": [10, 16],
        "usd": 2.21,
        "chose_to_stop": "3 of 4 pipelines called finish deliberately, with an accurate "
                         "account of what they had produced",
        "unprompted": "one pipeline diagnosed the fa_rep relax bottleneck unprompted",
        "weaknesses": ["score_interface called 13x against 27 relaxes - the cheap CPU gate "
                       "before an expensive fold is being skipped",
                       "inspect_ensemble called once in 137 turns"],
    },
    "hosted_in_allocation": {
        "date": "2026-10-26", "why": "vllm serve runs as an asyncflow task on a node of its "
                                     "own, so the model costs allocation rather than API",
        "qwen_7b": {"job": "23201195", "ready_s": 160,
                    "stamina": "all four pipelines self-terminated after 6/8/10/17 turns, "
                               "spending 2-6 of a 300-entry ensemble budget",
                    "folds": [3, 3]},
        "qwen_72b": {"job": "23207314", "nodes": 2, "ready_s": 360, "turns": 259,
                     "turns_per_pipeline": [67, 62, 62, 68], "invalid_tool_calls": 2,
                     "degraded": 0, "folds": [33, 33], "median_plddt": 92.0,
                     "fastrelax": [34, 45], "usd": 0.0,
                     "still_active": "all four pipelines still working at the final second",
                     "caveat": "two nodes to Sonnet's one, so per billed GPU-hour the "
                               "advantage roughly halves - and 33/33 folds is gating "
                               "discipline, not structure quality"},
        "invalid_run": {"job": "23206285",
                        "what": "its work dir was moved outside $WORK_DIR to dodge a quota, "
                                "and the rfd3 container binds only $WORK_DIR - so every "
                                "write landed in the container overlay and vanished",
                        "why_it_matters": "rfd3 logged success, out/ was empty, analysis "
                                          "returned pass=false, and the model correctly "
                                          "concluded its backbones kept failing. A silent "
                                          "environmental failure that reads exactly like a "
                                          "model failure"},
    },
}


def main() -> None:
    doc = {
        "_note": "Generated by slides/api/run_model.py. Do not edit by hand.",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "code": code_stats(),
        "surfaces": surfaces(),
        "mock": mock_campaign(),
        "live": live_next_door(),
    }
    OUT.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  head            {doc['code']['head']} on {doc['code']['branch']}")
    print(f"  src             {doc['code']['src_total']} lines, "
          f"{doc['code']['tests_collected']} tests")
    print(f"  tools           {doc['surfaces']['n_tools']} in "
          f"{doc['code']['n_toolkits']} toolkits, "
          f"{doc['surfaces']['n_gates_implemented']} gates implemented")
    print(f"  session ops     {doc['surfaces']['n_session_ops']}")
    print(f"  plane ops       {doc['surfaces']['n_plane_ops']}, "
          f"{doc['surfaces']['n_routes']} route heads")
    L = doc["live"]
    print(f"  live next door  {L['code']['n_tools']} tools, {L['code']['n_profiles']} profiles, "
          f"overrides {L['code']['overrides']} - runs TRANSCRIBED"
          if L else "  live next door  absent from this checkout")
    print(f"  mock campaign   {doc['mock']['cycles']} cycles, "
          f"front {doc['mock']['front_size']}, {doc['mock']['elapsed_s']}s, "
          f"{doc['mock']['provenance_records']} provenance records")


if __name__ == "__main__":
    main()
