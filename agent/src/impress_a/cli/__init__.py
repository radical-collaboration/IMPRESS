"""Command line entry point."""
from __future__ import annotations

import argparse
import asyncio
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
        root=d.get("root", "campaigns/_runs"))


def build_policy(model: str, spec: CampaignSpec, guard: bool = True):
    cls = POLICIES[model]
    if model == "C":
        pol = cls(timeout_s=5.0, on_timeout="fallback", fallback=ThresholdPolicy())
    elif model == "B":
        # A declared fallback is mandatory for the oracle: an API outage must degrade
        # explicitly, never stall a multi-GPU allocation (Part A risk R7).
        pol = cls(fallback=ThresholdPolicy())
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="impress-a")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a campaign")
    r.add_argument("spec")
    r.add_argument("--model", default="D", choices=sorted(POLICIES))
    r.add_argument("--no-guard", action="store_true")
    t = sub.add_parser("tools", help="list registered tools")
    t.add_argument("--toolkits", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return asyncio.run(run_campaign(a.spec, a.model, not a.no_guard))
    reg = Registry().load(a.toolkits)
    for tid in reg.ids():
        s = reg.get(tid)
        print(f"  {tid:16s} {s.pattern.value}  {s.toolkit:8s} gates={len(s.qc_gates)}")
    if reg.errors:
        print("  errors:", reg.errors)
    return 0
