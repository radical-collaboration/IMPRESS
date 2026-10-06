"""Command line entry point."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
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

# Module logger, never configured here: a library that calls basicConfig steals the
# root handler from whoever embedded it. `scripts/delta_run_campaign.py` configures it,
# and everything below is silent by default - including under pytest.
log = logging.getLogger(__name__)

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
        backend_startup_timeout_s=float(d.get("backend_startup_timeout_s", 0) or 0),
        backend_shutdown_timeout_s=float(d.get("backend_shutdown_timeout_s", 0) or 0),
        backend_startup_heartbeat_s=float(d.get("backend_startup_heartbeat_s", 30) or 30),
        root=d.get("root", "campaigns/_runs"),
        # Env, not YAML, because the right value is machine-specific: on Delta it has to be
        # outside the per-job working directory the launcher cds into, and YAML carries no
        # env expansion. Set beside MPNN_DIR/BOLTZ_CACHE in scripts/delta_gpu_run.sh.
        trust_root=d.get("trust_root") or os.environ.get("IMPRESS_A_TRUST_DIR", ""),
        stages=d.get("stages", []) or [],
        params=d.get("params", {}) or {},
        # 0, not 1: `replicas` is a CAP, and defaulting it to 1 would silently
        # narrow every campaign that never mentioned it.
        replicas=int(d.get("replicas", 0)),
        concurrency=int(d.get("concurrency", 1)),
        max_runs=int(d.get("max_runs", 0)))


def _check_ligand_smiles(spec: CampaignSpec) -> str | None:
    """`boltz_predict` with an empty `ligand_smiles` doesn't fail - it silently models no
    ligand, so the campaign's Pareto front optimizes the wrong objective. Backlog A2.
    """
    if "boltz_predict" not in spec.stages:
        return None
    if (spec.params.get("boltz_predict") or {}).get("ligand_smiles"):
        return None
    return ("boltz_predict is a stage but params.boltz_predict.ligand_smiles is empty - "
            "Boltz will silently model no ligand. Set it to the real target's SMILES.")


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


def _hms(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def _prov_heartbeat(campaign: str, kind: str, record: dict[str, Any]) -> None:
    """Mirror every provenance record to the log as it is written.

    `prov_sink` exists for the control plane; pointing it at a logger turns the campaign's
    own append-only record into a live progress feed, so a batch run reports what it is
    doing without the package printing anything of its own.
    """
    body = json.dumps({k: v for k, v in record.items() if k != "ts"}, default=str)
    log.info("prov %-12s %s", kind, body if len(body) <= 600 else body[:600] + "...")


async def _heartbeat(mgr: CampaignManager, period: float, t0: float) -> None:
    """Prove liveness while work is outstanding.

    Nothing between submission and completion produces output, and the longest real task
    is capped at 900s (rfd3's `walltime_s`), so a campaign doing exactly what it should
    and one deadlocked in the backend are indistinguishable from outside for a quarter of
    an hour. This is the line that tells them apart: `inflight=` with run ids means the
    executor is waiting on Dragon, `inflight=0` means it is waiting on the reasoner.

    Reads only the executor's synchronous snapshot API. Its mutating blocks are await-free
    by invariant, so a heartbeat scheduled between them can never see a torn state.
    """
    ex = mgr.executor
    while True:
        await asyncio.sleep(period)
        try:
            running = ex.inflight()
        except Exception as e:                     # noqa: BLE001 - diagnostics only
            log.warning("heartbeat: could not snapshot executor: %r", e)
            continue
        log.info("heartbeat +%s cycle=%d dispatched=%d nodes=%d inflight=%d%s",
                 _hms(time.monotonic() - t0), ex.cycle, ex.dispatched, len(ex.tree),
                 len(running),
                 "".join(f" [{r.run_id} {r.state.value} {r.graph_id}"
                         f"{'' if r.trusted else ' untrusted'}]" for r in running))


def _thread_caps(spec: CampaignSpec) -> dict[str, str]:
    """How many threads each CPU-bound child may take, sized from what this process was
    actually given rather than from the machine.

    `os.cpu_count()` reports the node, not the allocation, so on anything less than a
    whole node every Rosetta stage would claim every core on the box and the stages
    would fight each other. `sched_getaffinity` reports the cgroup we were placed in.
    The divisor is the number of pipelines that can be in flight at once - concurrent
    experiments times replica lineages, each of which can be running a CPU-bound P2
    stage - halved again, which is upstream's sizing
    (`run_small_molecule_binding.py:134-143`) and leaves headroom for the GPU stages'
    host-side work.

    Computed here rather than in an adapter because this is the only layer that knows
    both numbers: a `TaskRequest` carries no concurrency information, and an agent
    cannot see how many siblings it has. Applied with `setdefault`, so an operator who
    exported their own value keeps it.
    """
    if hasattr(os, "sched_getaffinity"):
        ncpu = len(os.sched_getaffinity(0))
    else:  # not Linux; the campaign path is, but the test tier need not be
        ncpu = os.cpu_count() or 1
    pipelines = max(1, spec.concurrency) * max(1, spec.replicas)
    per = max(1, ncpu // (pipelines * 2))
    caps = {v: str(per) for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS",
                                  "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")}
    # Spinning idle threads burn a core each while a stage waits on the GPU stages.
    caps["OMP_WAIT_POLICY"] = "PASSIVE"
    return caps


async def run_campaign(spec_path: str, model: str = "D", guard: bool = True,
                       heartbeat_s: float | None = None) -> int:
    t0 = time.monotonic()
    log.info("loading campaign spec %s", spec_path)
    spec = load_spec(spec_path)
    if err := _check_ligand_smiles(spec):
        log.error("%s", err)
        return 1
    for var, val in _thread_caps(spec).items():
        os.environ.setdefault(var, val)
        # The effective value, not the computed one: an operator who exported their own
        # keeps it, and a log that reported our suggestion instead would be describing a
        # run that is not the one happening.
        actual = os.environ[var]
        log.info("thread cap %-22s %s%s", var, actual,
                 "" if actual == val else f"  (kept from the environment, not {val})")
    spec.campaign_id = f"{spec.campaign_id}-{model}"
    policy = build_policy(model, spec, guard)
    reg = Registry().load()
    log.info("registry: %d tools (%s)%s", len(reg.ids()), ", ".join(reg.ids()),
             f" ERRORS: {reg.errors}" if reg.errors else "")
    mgr = CampaignManager(spec, policy, reg)
    mgr.prov_sink = _prov_heartbeat
    if heartbeat_s is None:
        heartbeat_s = float(os.environ.get("IMPRESS_A_HEARTBEAT_S", "60") or 0)
    log.info("campaign %s: model=%s backend=%s root=%s stages=%s replicas=%d",
             spec.campaign_id, model, spec.backend, mgr.root,
             ",".join(spec.stages) or "<policy default>", spec.replicas)
    # Absolute, and with a count. Trust accumulated inside each job's working directory for
    # three allocations without anyone noticing, because nothing ever named the file - a
    # ledger that silently reset looked exactly like one that had not earned promotion yet.
    _trust = mgr.executor.trust
    _known = _trust.patterns
    log.info("trust ledger %s (%d pattern%s known, %d trusted)",
             Path(_trust.path).resolve() if _trust.path else "<in-memory, nothing persists>",
             len(_known), "" if len(_known) == 1 else "s",
             sum(1 for r in _known.values() if r.trusted))
    hb = (asyncio.create_task(_heartbeat(mgr, heartbeat_s, t0))
          if heartbeat_s > 0 else None)
    try:
        res = await mgr.run()
    finally:
        if hb is not None:
            hb.cancel()
            await asyncio.gather(hb, return_exceptions=True)
        log.info("campaign returned after %s", _hms(time.monotonic() - t0))
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


def preflight(spec: CampaignSpec | None = None) -> int:
    """Check a real toolkit's environment BEFORE anything is queued.

    Every real adapter raises on a missing env var - but only once a task is running,
    which on HPC means inside the allocation, after the queue wait. Run this on the
    login node instead.
    """
    import shutil
    import subprocess
    import tempfile

    stages = spec.stages if spec else None
    # `ok` is tri-state. None means UNDETERMINED - the probe could not be run to a
    # conclusion - which is not the same as the check failing. Every probe here that shells
    # out to import a heavy science stack can take minutes on a busy login node, and
    # reporting that as FAIL trains the reader to ignore the FAIL column.
    #
    # The rule, and it must not erode: None is ONLY for a probe that did not produce an
    # answer - a timeout, an OSError, a check that does not apply. A deterministic negative
    # is always False. A missing $MPNN_DIR is a FAIL forever; a pyrosetta *import error* is
    # a FAIL, while a pyrosetta *timeout* is undetermined. The moment `warn` starts meaning
    # "a failure we would rather not block on", this column is worth nothing.
    checks: list[tuple[str, bool | None, str]] = []
    if spec is not None and (err := _check_ligand_smiles(spec)):
        checks.append(("ligand_smiles", False, err))

    for var, what in (("WORK_DIR", "every default path, and the rfd3 container bind"),
                      ("FOUNDRY_SIF_PATH", "rfd3_design (Apptainer image)"),
                      ("MPNN_DIR", "ligandmpnn_design (checkout + checkpoints)"),
                      ("BOLTZ_CACHE", "boltz_predict (pre-warmed weights)")):
        val = os.environ.get(var)
        if not val:
            checks.append((f"${var}", False, f"unset - needed by {what}"))
        elif not Path(val).exists():
            checks.append((f"${var}", False, f"set but does not exist: {val}"))
        elif var == "MPNN_DIR" and not (Path(val) / "run.py").is_file():
            # `exists()` only proved a directory. What stage 2 opens is run.py and the
            # checkpoints, and `delta_env_setup.sh` clones the first but has never
            # downloaded the second (LigandMPNN ships get_model_params.sh for that).
            checks.append((f"${var}", False, f"no run.py under {val} - not a checkout"))
        elif var == "MPNN_DIR" and not (Path(val) / "model_params").is_dir():
            checks.append((f"${var}", False,
                           f"{val} has no model_params/ - run its get_model_params.sh"))
        else:
            checks.append((f"${var}", True, val))

    # Presence of the weights is not completeness of the CCD dictionary, and the two
    # fail very differently: missing weights fail on the login node, a half-extracted
    # CCD fails inside the allocation, per-lineage, as `CCD component ... not found!`.
    if cache := os.environ.get("BOLTZ_CACHE"):
        marked = (Path(cache) / ".mols_complete").exists()
        checks.append(("boltz CCD cache", marked,
                       "extraction proven complete" if marked else
                       "no .mols_complete marker - re-run scripts/delta_env_setup.sh "
                       "step 11 HERE, where there is still internet to repair it"))

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
    except subprocess.TimeoutExpired:
        checks.append(("pyrosetta", None, ("timed out after 120s - a loaded login node "
                                           "can take that long to import it; re-run")))
    except (OSError, subprocess.SubprocessError) as e:
        checks.append(("pyrosetta", False, f"could not check: {e}"))

    # $WORK_DIR must be on NVMe, not HDD. This is the whole point of the migration and it
    # is invisible otherwise: an HDD path works perfectly, just ~8x slower, and the cost
    # lands as an unexplained task timeout inside an allocation (job 22675512, packmin).
    # Checked against the venv rather than $WORK_DIR itself, because the venv is what
    # holds the 598 MB rosetta.so and torch - it is the read that actually hurts.
    # sys.prefix, NOT sys.executable: inside a venv `bin/python` is a symlink to the base
    # interpreter, so resolving it walks straight out of the venv and reports wherever
    # CPython was installed. The first version of this check did that and cheerfully
    # passed a venv sitting on HDD. sys.prefix is the venv root, and site-packages - the
    # 598 MB rosetta.so and torch - is what actually gets read.
    venv_root = str(Path(sys.prefix).resolve())
    on_hdd = "/work/hdd/" in venv_root or venv_root.startswith("/scratch/")
    checks.append(("venv on fast storage", not on_hdd,
                   venv_root if not on_hdd
                   else f"HDD-backed: {venv_root} - PyRosetta and torch are read from "
                        "here every task; move it under a /work/nvme $WORK_DIR "
                        "(scripts/delta_env_setup.sh)"))

    # Tier 1, ~1s, always: the one package `delta_env_setup.sh` was missing. Nothing of ours
    # imports it - LigandMPNN's bundled openfold does, at run.py import time - so it is
    # invisible until stage 2 of a campaign. Cheap enough to never be worth skipping.
    try:
        out = subprocess.run([sys.executable, "-c", "import ml_collections"],
                             capture_output=True, timeout=60, check=False)
        checks.append(("ml_collections", out.returncode == 0,
                       "importable - LigandMPNN's openfold needs it" if out.returncode == 0
                       else "missing; re-run scripts/delta_env_setup.sh step 6"))
    except (OSError, subprocess.SubprocessError) as e:
        # Including TimeoutExpired. A preflight that raises tells the operator nothing
        # about the other eight checks, which is the opposite of what it is for.
        checks.append(("ml_collections", None, f"could not check: {e}"))

    # Tier 2, MINUTES, and only for a campaign that actually runs it: the whole import
    # chain, through the same shim the adapter uses. `run.py` does its work under an
    # `if __name__ == "__main__"` guard, so `--help` runs every module-level import and
    # then exits 0 without touching a GPU or a checkpoint. That chain is what failed on
    # job 22669509, twice for two unrelated reasons, both only visible from inside an
    # allocation.
    #
    # The bound is 900s because the probe is genuinely slow: ~280s of it is `import torch`
    # paging off Lustre (measured ~360s wall for 9s of CPU on a login node). That is also
    # why the elapsed time is printed - it is the early warning for ligandmpnn_design's
    # walltime_s, which this measurement is what set.
    deep = stages is None or "ligandmpnn_design" in stages
    if (mpnn := os.environ.get("MPNN_DIR")) and deep:
        from ..tools.ligandmpnn_agents import MPNN_SHIM
        t0 = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as td:
                shim = Path(td) / "mpnn_run.py"
                shim.write_text(MPNN_SHIM)
                out = subprocess.run([sys.executable, "-P", str(shim), mpnn, "--help"],
                                     capture_output=True, timeout=900, check=False)
            took = time.monotonic() - t0
            ok = out.returncode == 0
            checks.append(("ligandmpnn imports", ok,
                           f"run.py --help exited 0 in {took:.0f}s" if ok
                           else out.stderr.decode().strip().splitlines()[-1:][0]
                           if out.stderr else f"exited {out.returncode} after {took:.0f}s"))
        except subprocess.TimeoutExpired:
            checks.append(("ligandmpnn imports", None,
                           ("no result in 900s - undetermined, NOT a pass; a loaded "
                            "Lustre mount can do this. Re-run before submitting")))
        except (OSError, subprocess.SubprocessError) as e:
            checks.append(("ligandmpnn imports", False, f"could not check: {e}"))

    reg = Registry().load()
    checks.append(("toolkits", not reg.errors, "; ".join(reg.errors) or "all registered"))

    print("\n  preflight\n")
    for name, ok, detail in checks:
        mark = "ok  " if ok else "warn" if ok is None else "FAIL"
        print(f"    [{mark}] {name:20s} {detail}")
    failed = [n for n, ok, _ in checks if ok is False]
    unknown = [n for n, ok, _ in checks if ok is None]
    print(f"\n  {len(checks) - len(failed) - len(unknown)}/{len(checks)} ok"
          + (f", {len(unknown)} undetermined ({', '.join(unknown)})" if unknown else "")
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
    r.add_argument("--heartbeat", type=float, default=None, metavar="SECONDS",
                   help="liveness log cadence (default $IMPRESS_A_HEARTBEAT_S or 60; "
                        "0 disables). Only visible once logging is configured - see "
                        "scripts/delta_run_campaign.py")
    t = sub.add_parser("tools", help="list registered tools")
    t.add_argument("--toolkits", default=None)
    pf = sub.add_parser("preflight",
                        help="check the real-toolkit environment before submitting")
    pf.add_argument("spec", nargs="?", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return asyncio.run(run_campaign(a.spec, a.model, not a.no_guard,
                                        a.heartbeat))
    if a.cmd == "preflight":
        return preflight(load_spec(a.spec) if a.spec else None)
    reg = Registry().load(a.toolkits)
    for tid in reg.ids():
        s = reg.get(tid)
        print(f"  {tid:16s} {s.pattern.value}  {s.toolkit:8s} gates={len(s.qc_gates)}")
    if reg.errors:
        print("  errors:", reg.errors)
    return 0
