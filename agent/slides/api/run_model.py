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

There is deliberately NO transcribed section. Every figure in this deck comes from this
checkout or from a run this script performs, because the deck is about the API rather than
about a campaign on Delta - and the one claim that would need a cluster (what the loop
costs at `replicas > 1`) is the claim the deck concedes instead of making. If a Delta
figure is ever added here it goes in its own section with a `source` field, and the slide
that shows it repeats the source in its footer.
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
    from impress_a.cli import POLICIES, SUBCOMMANDS
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
        "cli_subcommands": list(SUBCOMMANDS),
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


def main() -> None:
    doc = {
        "_note": "Generated by slides/api/run_model.py. Do not edit by hand.",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "code": code_stats(),
        "surfaces": surfaces(),
        "mock": mock_campaign(),
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
    print(f"  mock campaign   {doc['mock']['cycles']} cycles, "
          f"front {doc['mock']['front_size']}, {doc['mock']['elapsed_s']}s, "
          f"{doc['mock']['provenance_records']} provenance records")


if __name__ == "__main__":
    main()
