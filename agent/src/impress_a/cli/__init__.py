"""Command line entry point."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from ..compose.validate import SiteCaps
from ..core.pareto import Objective
from ..manager import CampaignManager, CampaignSpec
from ..policy.agentic import FourNodePolicy
from ..policy.explicit import ReplayPolicy, ThresholdPolicy
from ..policy.external import ExternalPolicy
from ..policy.oracle import OraclePolicy
from ..policy.wrappers import LoggingPolicy, NullPolicy, RuleCorrectionsPolicy
from ..tools.registry import Registry

POLICIES = {"D": ThresholdPolicy, "B": OraclePolicy, "A": FourNodePolicy,
            "C": ExternalPolicy, "null": NullPolicy, "replay": ReplayPolicy}


def load_spec(path: str | Path) -> CampaignSpec:
    d: dict[str, Any] = yaml.safe_load(Path(path).read_text())
    return CampaignSpec(
        campaign_id=d["campaign_id"], goal=d["goal"],
        objectives=[Objective(**o) for o in d["objectives"]],
        budget=d.get("budget", {}), max_cycles=d.get("max_cycles", 10),
        stagnation_limit=d.get("stagnation_limit", 3),
        site=SiteCaps(**d.get("site", {})),
        backend=d.get("backend", "concurrent"),
        backend_config=d.get("backend_config", {}),
        root=d.get("root", "campaigns/_runs"),
        stages=d.get("stages", []) or [],
        params=d.get("params", {}) or {},
        # 0, not 1: `replicas` is a CAP, and defaulting it to 1 would silently
        # narrow every campaign that never mentioned it.
        replicas=int(d.get("replicas", 0)),
        concurrency=int(d.get("concurrency", 1)),
        max_runs=int(d.get("max_runs", 0)))


def build_policy(model: str, spec: CampaignSpec, guard: bool = True):
    """Construct the campaign's control model, pointed at the campaign's own chain.

    `stages` has to reach the policy or every model falls back to its built-in default,
    which is the mock chain - so a real campaign would validate the real toolkits and
    then execute mocks.
    """
    cls = POLICIES[model]
    stages = list(spec.stages) or None
    if model == "C":
        pol = cls(timeout_s=5.0, on_timeout="fallback",
                  fallback=ThresholdPolicy(stages=stages))
    elif model == "B":
        # A declared fallback is mandatory for the oracle: an API outage must degrade
        # explicitly, never stall a multi-GPU allocation (Part A risk R7).
        pol = cls(fallback=ThresholdPolicy(stages=stages))
    elif model in ("A", "D"):
        pol = cls(stages=stages)
    else:
        pol = cls()
    if guard:
        pol = RuleCorrectionsPolicy(pol, max_replicas=8, forbid_tools=("mock_noodle",))
    return pol


async def run_campaign(spec_path: str, model: str = "D", guard: bool = True) -> int:
    spec = load_spec(spec_path)
    spec.campaign_id = f"{spec.campaign_id}-{model}"
    policy = build_policy(model, spec, guard)
    mgr = CampaignManager(spec, policy, Registry().load())
    res = await mgr.run()
    print(f"\n  campaign : {res.campaign_id}")
    print(f"  policy   : {getattr(policy,'name','?')}")
    print(f"  cycles   : {res.cycles}")
    print(f"  stop     : {res.stop_reason}")
    print(f"  nodes    : {len(res.tree)}  front: {len(res.front)}")
    for n in res.front:
        print(f"    {n.id} qc={n.qc.verdict.value:8s} "
              + " ".join(f"{o.name}={n.metric(o.name)}" for o in spec.objectives))
    if res.corrections:
        print(f"  guard corrections: {res.corrections}")
    return 0


def preflight(stages: list[str] | None = None) -> int:
    """Check a real toolkit's environment BEFORE anything is queued.

    Every real adapter raises on a missing env var - but only once a task is running,
    which on HPC means inside the allocation, after the queue wait. Run this on the
    login node instead.
    """
    import shutil
    import subprocess

    checks: list[tuple[str, bool, str]] = []

    for var, what in (("FOUNDRY_SIF_PATH", "rfd3_design (Apptainer image)"),
                      ("MPNN_DIR", "ligandmpnn_design (checkout + checkpoints)"),
                      ("BOLTZ_CACHE", "boltz_predict (pre-warmed weights)")):
        val = os.environ.get(var)
        if not val:
            checks.append((f"${var}", False, f"unset - needed by {what}"))
        elif not Path(val).exists():
            checks.append((f"${var}", False, f"set but does not exist: {val}"))
        else:
            checks.append((f"${var}", True, val))

    for exe, what in (("apptainer", "rfd3_design"), ("boltz", "boltz_predict")):
        found = shutil.which(exe)
        checks.append((exe, bool(found), found or f"not on PATH - needed by {what}"))

    # PyRosetta in a subprocess: importing it here would initialise a process-global
    # singleton in the very interpreter that has to stay clean for P2 fan-out.
    try:
        out = subprocess.run([sys.executable, "-c", "import pyrosetta"],
                             capture_output=True, timeout=120, check=False)
        ok = out.returncode == 0
        checks.append(("pyrosetta", ok,
                       "importable" if ok
                       else out.stderr.decode().strip().splitlines()[-1:][0]
                       if out.stderr else "import failed"))
    except (OSError, subprocess.SubprocessError) as e:
        checks.append(("pyrosetta", False, f"could not check: {e}"))

    reg = Registry().load()
    checks.append(("toolkits", not reg.errors, "; ".join(reg.errors) or "all registered"))

    print("\n  preflight\n")
    for name, ok, detail in checks:
        print(f"    [{'ok ' if ok else 'FAIL'}] {name:20s} {detail}")
    failed = [n for n, ok, _ in checks if not ok]
    print(f"\n  {len(checks) - len(failed)}/{len(checks)} ok"
          + (f" - missing: {', '.join(failed)}" if failed else ""))
    if stages:
        print(f"  (a campaign using {', '.join(stages)} needs the entries above)")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="impress-a")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a campaign")
    r.add_argument("spec")
    r.add_argument("--model", default="D", choices=sorted(POLICIES))
    r.add_argument("--no-guard", action="store_true")
    t = sub.add_parser("tools", help="list registered tools")
    t.add_argument("--toolkits", default=None)
    pf = sub.add_parser("preflight",
                        help="check the real-toolkit environment before submitting")
    pf.add_argument("spec", nargs="?", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return asyncio.run(run_campaign(a.spec, a.model, not a.no_guard))
    if a.cmd == "preflight":
        return preflight(load_spec(a.spec).stages if a.spec else None)
    reg = Registry().load(a.toolkits)
    for tid in reg.ids():
        s = reg.get(tid)
        print(f"  {tid:16s} {s.pattern.value}  {s.toolkit:8s} gates={len(s.qc_gates)}")
    if reg.errors:
        print("  errors:", reg.errors)
    return 0
