"""Drive the mock small-molecule chain across a knob grid, then flatten what it wrote.

Three stages, each runnable on its own so a failure in one does not cost the others:

* **sweep** - generate one campaign spec per cell, run it, keep the run directory.
* **collect** - read the executor's own provenance and write four tidy CSVs.
* **figures** - `mock_figures.py`, which is a separate module because it needs matplotlib
  and these two do not.

`impress-a mock-lab` runs all three.

**Every cell is a SUBPROCESS, not an import.** `analysis` may not reach `policy` or `control`
(`tests/test_layering.py`), and a sweep that built reasoners in-process would have to. Going
through the installed `impress-a run` also means the sweep exercises the command a person
types rather than a path only the sweep has, which is the whole point of a surrogate meant for
user testing.

**Every cell gets its own run root AND its own trust directory.** `IMPRESS_A_TRUST_DIR` is not
a tidiness flag here: the trust ledger is cross-run state, so a cell that promoted a pattern
changes the interlock every later cell runs under - the same graph admitted trusted in one cell
and capped in the next, from nothing the cell itself did. Sharing one ledger across a sweep
makes the sweep a function of its own iteration order. Each cell also gets its own
`IMPRESS_A_SEED_SALT`, which is what makes `--repeat` draw independent lineages rather than the
same ones again (backlog G7).

**What a number from here is.** Nothing. Every metric the six surrogates report is a seeded
random draw (`toolkits/mock/SKILL.md`). What this pipeline measures honestly is the campaign's
*behaviour* - how many cycles, which gate refused what, where the wall clock went, how the
front moved - plus the surrogate's own response surface, which is a statement about the
surrogate and not about any molecule. The figures say so on their faces, and `mock_figures`
writes that caption from this module's own constant rather than from a string a reader could
drop.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

#: Printed on every figure and written into the manifest. One sentence, in one place, because
#: a surrogate's plot that escapes into a slide deck without it is the failure mode the whole
#: mock toolkit is built to make hard.
DISCLAIMER = ("Mock surrogate: every metric is a seeded random draw and says nothing about "
              "any molecule. What is measured is campaign behaviour.")

#: The campaign the lab drives. Relative to the repository's `agent/` directory.
BASE_SPEC = Path("campaigns/mock-small-molecule-binding.yaml")

#: Applied to EVERY cell, arms and sweeps alike, so the arms stay comparable to each other.
#: `replicas` is what gives a cell an ensemble at all - one lineage per cycle is not a
#: distribution - and raising it changes the pattern signature, so every cell runs untrusted
#: under the 10% cost cap. That is deliberate: it is the same interlock for all of them.
LAB_BASE: dict[str, Any] = {"replicas": 4, "concurrency": 1}

#: Arm overrides. The four settings the ten-minute activity walks through, and the four hues
#: in `plot_style.RUN_STYLES`. Tiered by what the campaign DOES, not by what the surrogate
#: reports: `hard` and `rescued` carry the same `difficulty` and differ only in the three
#: knobs raised to buy it back.
ARMS: dict[str, dict[str, Any]] = {
    "baseline": {},
    "rescued": {"params": {"mock_rfd3_design": {"difficulty": 0.55, "diffusion_steps": 200},
                           "mock_packmin": {"cycles": 5},
                           "mock_boltz_predict": {"diffusion_samples": 25}}},
    "hard": {"params": {"mock_rfd3_design": {"difficulty": 0.55}}},
    "hopeless": {"params": {"mock_rfd3_design": {"difficulty": 0.85}}},
}

#: Arms run several cycles so there is a decision sequence to time and a front to watch move.
#: `target_front: 4` asks for four readings over every bounded objective, which is what stops
#: `baseline` satisfying itself at cycle 0 and leaving one point to plot.
ARM_BASE: dict[str, Any] = {"target_front": 4, "max_cycles": 6, "stagnation_limit": 4}

#: A sweep cell runs exactly ONE cycle, and that is a measurement decision rather than a
#: saving. `ThresholdSpecifier.revise` adds a refinement objective once the front is non-empty,
#: so a multi-cycle cell mixes the knob's response with the planner's escalation away from it -
#: and a sweep that cannot tell those apart is not a response surface. `target_front` is set
#: above anything one cycle can reach so the Spec cannot be satisfied early either.
SWEEP_BASE: dict[str, Any] = {"target_front": 99, "max_cycles": 1, "stagnation_limit": 99,
                              "replicas": 8}

#: The swept knobs: the tool, the parameter, and the values. `difficulty` is the surrogate's
#: own dial and has no real counterpart; the other four exist on the real tools under these
#: names. Values are the ranges the specs declare, walked coarsely enough that a sweep is
#: seconds rather than minutes.
SWEEPS: dict[str, tuple[str, list[float]]] = {
    "difficulty": ("mock_rfd3_design", [0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85]),
    "diffusion_steps": ("mock_rfd3_design", [20, 50, 100, 150, 200]),
    "temperature": ("mock_mpnn_design", [0.0, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0]),
    "batch_size": ("mock_mpnn_design", [1, 2, 8, 32, 64]),
    "diffusion_samples": ("mock_boltz_predict", [1, 2, 8, 16, 25]),
}

@dataclass(frozen=True)
class Reasoner:
    """One control model as the lab drives it."""

    letter: str
    #: True when this model makes LLM calls, so the lab must be given a profile for it and
    #: must count what it spends.
    live: bool
    note: str


#: The reasoner axis. The tools below are mocked in every one of these; what varies is the
#: control plane, which is the half the four-model taxonomy is actually about.
#:
#: **A live model with no profile is REFUSED, never quietly run.** `--model A` with no
#: `--model-profile` runs its rule cascades and reports nothing wrong, and `--model B` runs
#: `RehearsalOracle` - both report zero LLM calls exactly as a degraded live arm does. On the
#: sibling example's job 23219379 that ambiguity let 144 degraded turns read as a
#: frontier-model result for a full day, and the pre-registration makes a silently-degraded
#: arm a void outcome (§8). A lab that produced a figure labelled "model B" from the
#: rehearsal would be manufacturing exactly that.
#:
#: C is absent: it needs `impress-a serve` plus an `impress-a control` sidecar waiting on the
#: 0600 `control_plane.url`, which is two processes per cell, and its caller-side reasoner
#: records have nowhere to land (backlog H8).
REASONERS: dict[str, Reasoner] = {
    "D": Reasoner("D", live=False,
                  note="the deterministic control; rules end to end, no model anywhere"),
    "null": Reasoner("null", live=False,
                     note="stops at cycle 0 with an empty Spec; the floor"),
    "A": Reasoner("A", live=True,
                  note="four nodes, two of which call the model: hypothesize, select_tasks"),
    "B": Reasoner("B", live=True,
                  note="two schemas, one call each: SPEC_SCHEMA and STAGE_SCHEMA"),
}

#: The lab's own default axis. D alone reproduces the knob lab exactly as it shipped.
DEFAULT_REASONERS = ("D",)

#: Calls per cycle per live model, measured on a login node 2026-11-08 and corrected in
#: backlog H1: TWO for both A and B, not A's four. Used only to print an estimate before a
#: live run, never to bound anything - the cap counts what was actually recorded.
CALLS_PER_CYCLE = 2

#: Which objective each figure reads a sweep against, and the acceptance bar the campaign
#: declares for it. Copied from the campaign spec on load rather than written twice - see
#: `_objective_bars`.
OBJECTIVES = ("total_score", "shape_complementarity", "complex_plddt", "ligand_iptm")

#: `l0_s3_mock_fastrelax` -> lineage 0, stage 3, tool mock_fastrelax. The composer's own node
#: naming, which is the only place a task's POSITION IN THE CHAIN is recorded: provenance
#: carries the lineage as a field but not the stage, and the funnel figure is about nothing
#: else. `r` is accepted too because that was the prefix before the composer renamed it, and a
#: lab that silently reported stage -1 for every task is how this was found.
NODE_RE = re.compile(r"^[lr](\d+)_s(\d+)_(.+)$")


# -- cells -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Cell:
    """One campaign to run, and everything a figure needs to place its rows."""

    cell: str                   # directory-safe id, unique in a lab
    kind: str                   # "arm" | "sweep"
    arm: str                    # arm key for kind="arm", else ""
    knob: str                   # swept parameter for kind="sweep", else ""
    value: float                # its value, else 0.0
    salt: str                   # $IMPRESS_A_SEED_SALT for this cell
    rep: int                    # which repeat this is
    #: Which control model drives this cell: the `--model` letter, not the tools. The tool
    #: surrogates are mocked in every cell; this is what sits above them.
    model: str = "D"
    #: `--model-profile`, for the cells whose model talks to an endpoint. Empty otherwise.
    profile: str = ""
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def live(self) -> bool:
        """Whether this cell will spend real calls on a real endpoint."""
        return bool(self.profile) and REASONERS[self.model].live

    @property
    def keys(self) -> dict[str, Any]:
        return {"cell": self.cell, "kind": self.kind, "arm": self.arm,
                "knob": self.knob, "value": self.value, "rep": self.rep, "salt": self.salt,
                "model": self.model, "profile": self.profile}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge. `params` is two levels deep, so a flat update would drop the
    other tools' parameters and silently run the sweep at a different chain than the one the
    campaign declares."""
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def cells(repeats: int, only: list[str] | None = None,
          models: list[str] | None = None, profile: str = "",
          reasoner_repeats: int = 3) -> list[Cell]:
    """Every cell this lab runs.

    Three families, and which axis each varies:

    * **arms x models** - the four knob settings under each control model. The knob arms are
      never repeated under a deterministic model: each is one reproducible campaign a reader
      re-runs by hand and gets back. A LIVE model is repeated `reasoner_repeats` times,
      because a model at temperature 0 is still not a function - a single draw of a
      nondeterministic arm is an anecdote, and the figures draw its spread.
    * **sweeps** - each knob point `repeats` times under a different salt, on model D only.
      They measure the SURROGATE's response surface, which no reasoner changes, so running
      them under four models would buy four readings of the same arithmetic.

    `models` defaults to `DEFAULT_REASONERS`, which is D alone - so a lab run with no new
    flags is byte-for-byte the lab that shipped.
    """
    want = set(only or [])
    chosen = list(models or DEFAULT_REASONERS)
    out: list[Cell] = []
    for model in chosen:
        reps = reasoner_repeats if (profile and REASONERS[model].live) else 1
        for arm, over in ARMS.items():
            if want and arm not in want and "arms" not in want:
                continue
            for rep in range(max(1, reps)):
                # The model is in the cell id only when the axis has more than one, so a
                # default lab keeps the directory names - and the figures' labels, and the
                # deck's - exactly as they were.
                tag = f"arm-{arm}" if len(chosen) == 1 else f"arm-{arm}-{model}"
                out.append(Cell(
                    cell=tag if reps == 1 else f"{tag}-r{rep}",
                    kind="arm", arm=arm, knob="", value=0.0,
                    salt=f"arm-{arm}" if reps == 1 else f"arm-{arm}-r{rep}", rep=rep,
                    model=model, profile=profile if REASONERS[model].live else "",
                    overrides=_merge(_merge(LAB_BASE, ARM_BASE), over)))
    for knob, (tool, values) in SWEEPS.items():
        if want and knob not in want and "sweeps" not in want:
            continue
        for v in values:
            for rep in range(max(1, repeats)):
                tag = f"{v:g}".replace(".", "p").replace("-", "m")
                out.append(Cell(
                    cell=f"sweep-{knob}-{tag}-r{rep}", kind="sweep", arm="", knob=knob,
                    value=float(v), salt=f"{knob}-{tag}-r{rep}", rep=rep,
                    overrides=_merge(_merge(LAB_BASE, SWEEP_BASE),
                                     {"params": {tool: {knob: v}}})))
    return out


# -- stage 1: sweep ----------------------------------------------------------------------

def _write_spec(cell: Cell, base: dict[str, Any], out: Path) -> Path:
    spec = _merge(base, cell.overrides)
    # The campaign id names the cell, so provenance written by the executor says which cell
    # it came from without the collector having to trust a directory name. It is not part of
    # any seed - the draws key on the graph node id and the salt - so renaming it moves
    # nothing (`compose/composer._replica_seed`, `tools/mock_agents._rng`).
    spec["campaign_id"] = cell.cell
    path = out / "specs" / f"{cell.cell}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    return path


def run_cell(cell: Cell, base: dict[str, Any], out: Path, model: str = "",
             timeout_s: float = 600.0) -> dict[str, Any]:
    """Run one campaign in its own run root, trust ledger and seed salt.

    A non-zero exit is RECORDED, never raised. `difficulty: 0.85` is a cell whose campaign
    aborts by design, and a sweep that stopped there would be unable to draw the one arm that
    shows what an integrity failure costs.

    `model` overrides the cell's own letter and exists for the callers that drive one model
    across every cell; the cell's letter is what a reasoner-axis lab uses.
    """
    model = model or cell.model
    spec = _write_spec(cell, base, out)
    root = out / "runs" / cell.cell
    env = dict(os.environ,
               IMPRESS_A_RUN_ROOT=str(root),
               IMPRESS_A_TRUST_DIR=str(out / "trust" / cell.cell),
               IMPRESS_A_SEED_SALT=cell.salt)
    # `sys.executable -m impress_a`, never `impress-a` off PATH. The console script
    # resolved to a user-site one with no `impress_a` in it - every cell exited 1 with
    # `ModuleNotFoundError` while the lab itself was running inside the project venv. The
    # interpreter running this module is the one environment known to have the package, and
    # CLAUDE.md's whole "Environment" section is about PATH drifting out from under a run.
    argv = [sys.executable, "-m", "impress_a", "run", str(spec), "--model", model]
    if cell.profile:
        argv += ["--model-profile", cell.profile]
    t0 = datetime.now()
    try:
        proc = subprocess.run(argv, env=env, capture_output=True, text=True,
                              timeout=timeout_s, check=False)
        rc, tail = proc.returncode, (proc.stdout or "")[-4000:] + (proc.stderr or "")[-4000:]
    except subprocess.TimeoutExpired:
        rc, tail = 124, f"timed out after {timeout_s}s"
    rec = dict(cell.keys, exit_code=rc, model=model,
               spec=str(spec), run_dir=str(root / f"{cell.cell}-{model}"),
               launch_wall_s=round((datetime.now() - t0).total_seconds(), 3))
    rec["live"] = cell.live
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "logs" / f"{cell.cell}.log").write_text(tail)
    log.info("%s exit=%d in %.1fs", cell.cell, rc, rec["launch_wall_s"])
    return rec


def probe_endpoint(profile: str, out: Path) -> str:
    """One cheap call before any live cell. Returns "" when the endpoint answered.

    `cli._client_for` opens no socket, so without this the first failure lands inside a
    campaign cycle - where `reasoning.ask` retries twice, gives up, writes
    `reasoner_degraded` and runs model D's cascade. The campaign then exits 0. Every live
    cell would do the same, and the lab would produce a full set of figures labelled with a
    model that never answered. One round trip up front is the difference between "the
    endpoint is down" and twenty-four quietly degraded arms.
    """
    code = (
        "import asyncio, json, sys\n"
        "from impress_a.policy.llm import build_oracle, load_profiles\n"
        "from impress_a.cli import _client_for\n"
        "from impress_a.manager import CampaignSpec\n"
        "client = _client_for(sys.argv[1], CampaignSpec(campaign_id='probe', goal='',\n"
        "                                               objectives=[]))\n"
        "out = asyncio.run(client.think('spec', 'Reply with {\"ok\": true}.',\n"
        "                               {'ok': 'boolean'}))\n"
        "print(json.dumps({'model_id': client.model_id, 'reply': out}))\n")
    proc = subprocess.run([sys.executable, "-c", code, profile],
                          capture_output=True, text=True, timeout=300, check=False)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "logs" / "_probe.log").write_text((proc.stdout or "") + (proc.stderr or ""))
    if proc.returncode == 0:
        log.info("lab: endpoint probe ok - %s", (proc.stdout or "").strip()[:200])
        return ""
    reason = ((proc.stderr or proc.stdout or "").strip().splitlines() or ["no output"])[-1]
    log.error("lab: endpoint probe FAILED for profile %s: %s", profile, reason)
    return reason


def _count_calls(run_dir: str) -> int:
    """LLM calls a finished cell actually made, from its own `decisions.jsonl`.

    Counted from the record rather than predicted from the cycle count, because a corrective
    retry is a second call and a degraded node is two calls that bought nothing. A cap built
    on an estimate would be a cap on the wrong number.
    """
    return sum(1 for rec in _jsonl(Path(run_dir) / "provenance" / "decisions.jsonl")
               if rec.get("model_id") and rec.get("model_id") != "rehearsal")


def sweep(out: Path, repeats: int = 3, only: list[str] | None = None, model: str = "",
          jobs: int = 4, base_spec: Path = BASE_SPEC, models: list[str] | None = None,
          profile: str = "", reasoner_repeats: int = 3,
          max_llm_calls: int = 400) -> Path:
    """Run every cell and write the manifest the collector joins against."""
    base = yaml.safe_load(Path(base_spec).read_text())
    chosen = list(models or ([model] if model else list(DEFAULT_REASONERS)))
    for letter in chosen:
        if letter not in REASONERS:
            raise ValueError(f"unknown reasoner {letter!r}; the axis is {sorted(REASONERS)}")
    todo = cells(repeats, only, chosen, profile, reasoner_repeats)
    out.mkdir(parents=True, exist_ok=True)

    # A LIVE MODEL WITH NO PROFILE IS REFUSED, NOT QUIETLY RUN. `--model A` without one runs
    # its rule cascades and `--model B` runs the rehearsal; both report zero LLM calls, which
    # is also what a degraded live arm reports. A figure labelled "model B" drawn from the
    # rehearsal is the pre-registration's §8 void outcome manufactured on purpose.
    unprofiled = sorted({c.model for c in todo if REASONERS[c.model].live and not c.profile})
    if unprofiled:
        raise ValueError(
            f"{', '.join(unprofiled)} "
            f"{'makes' if len(unprofiled) == 1 else 'make'} LLM calls and no "
            "--model-profile was given. "
            "Without one they run their rule cascades and report zero calls, which is "
            "indistinguishable from a live arm that degraded - so the lab will not label "
            "a figure with a model that was never asked. Name a profile, or drop them "
            "from --reasoners.")

    live = [c for c in todo if c.live]
    if live:
        est = len(live) * CALLS_PER_CYCLE * ARM_BASE["max_cycles"]
        log.info("lab: %d live cells on profile %s - at most ~%d calls "
                 "(%d cells x %d per cycle x %d cycles), capped at %d",
                 len(live), profile, est, len(live), CALLS_PER_CYCLE,
                 ARM_BASE["max_cycles"], max_llm_calls)
        if (reason := probe_endpoint(profile, out)):
            raise RuntimeError(
                f"the endpoint for profile {profile!r} did not answer a one-call probe "
                f"({reason}). Every live cell would degrade to model D's cascade and exit "
                "0, and the lab would draw a full set of figures for a model that never "
                "answered.")

    # THE ARMS RUN ONE AT A TIME, whatever `--jobs` says, and the sweeps run in parallel.
    # The arms are where every wall-clock figure comes from, and a cell that shared four
    # cores with seven others is not a timing measurement: run eight-wide, one arm's first
    # cycle came back at 0.10s against 1.10s for the other three, which is scheduling noise
    # presented as a property of the knob setting. The sweep cells are only read for the
    # metrics their tools drew, which no amount of CPU contention changes. A live cell is
    # serial for a second reason: one request at a time to one endpoint.
    arms = [c for c in todo if c.kind == "arm"]
    rest = [c for c in todo if c.kind != "arm"]
    log.info("lab: reasoners %s, %d arm cells one at a time, %d sweep cells %d at a time",
             "+".join(chosen), len(arms), len(rest), jobs)

    records: list[dict[str, Any]] = []
    spent = 0
    for cell in arms:
        if cell.live and spent >= max_llm_calls:
            # Skipped, and SAID so in the manifest. A cell silently missing from a figure
            # reads as a model that had nothing to show rather than one the lab stopped
            # paying for.
            log.warning("lab: %s skipped - %d calls already spent, cap is %d",
                        cell.cell, spent, max_llm_calls)
            records.append(dict(cell.keys, exit_code=None, model=cell.model, spec="",
                                run_dir="", launch_wall_s=0.0, live=True,
                                skipped=f"llm call cap reached ({spent} >= {max_llm_calls})"))
            continue
        rec = run_cell(cell, base, out)
        if cell.live:
            rec["llm_calls"] = _count_calls(rec["run_dir"])
            spent += rec["llm_calls"]
            log.info("lab: %s made %d calls (%d of %d spent)",
                     cell.cell, rec["llm_calls"], spent, max_llm_calls)
        records.append(rec)

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        # Threads, not processes: every cell is a `subprocess.run`, so the work is in another
        # process already and the pool only needs to wait on it. Cells are independent by
        # construction - separate run root, separate trust ledger, separate salt - so the
        # only shared state is the manifest, written once below.
        records += list(pool.map(lambda c: run_cell(c, base, out), rest))
    manifest = {"ts": datetime.now().astimezone().isoformat(),
                "disclaimer": DISCLAIMER,
                "base_spec": str(base_spec),
                "objectives": _objective_bars(base),
                "lab_base": LAB_BASE, "arm_base": ARM_BASE, "sweep_base": SWEEP_BASE,
                "arms": ARMS, "sweeps": {k: v[1] for k, v in SWEEPS.items()},
                "repeats": repeats, "reasoners": chosen, "profile": profile,
                "reasoner_repeats": reasoner_repeats, "llm_calls": spent,
                "max_llm_calls": max_llm_calls, "cells": records}
    path = out / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, default=str))
    bad = [r["cell"] for r in records if r.get("exit_code") not in (0, None)]
    # Named, not just counted: `arm-hopeless` is SUPPOSED to exit non-zero, and a reader who
    # cannot see which cell it was has no way to tell the designed abort from a broken cell.
    log.info("lab: wrote %s%s%s", path,
             f"; {spent} llm calls" if spent else "",
             f"; {len(bad)} cells exited non-zero: {', '.join(bad)}" if bad else "")
    return path


def _objective_bars(base: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The campaign's own objectives, read from the spec rather than restated here.

    The acceptance thresholds appear twice in the system already - on the objective and as a
    QC gate on the tool - and a third copy in a figure script is one that can disagree with
    the campaign a reader just ran.
    """
    return {o["name"]: {"direction": o.get("direction", "maximize"),
                        "min": o.get("min"), "max": o.get("max")}
            for o in base.get("objectives", [])}


# -- stage 2: collect --------------------------------------------------------------------

def _jsonl(path: Path) -> list[dict[str, Any]]:
    """Every record in a JSONL file, skipping a truncated final line.

    Same rule as `compare_arms._jsonl` and for the same reason: an aborted campaign leaves a
    half-written line, and the cells that abort are the ones most worth reading.
    """
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            log.debug("%s: skipping truncated line", path)
    return out


#: `CampaignAborted: 3 consecutive all-failed runs` in a captured traceback.
ABORT_RE = re.compile(r"(CampaignAborted|CampaignStopped|Error|Exception):\s*(.+)$")


def _abort_reason(log_path: Path) -> str:
    """Why a cell exited non-zero, from the stderr this lab captured.

    The last matching exception line, because a traceback chains: the innermost `raise` is
    printed first and the one that actually left the process is printed last.
    """
    if not log_path.exists():
        return "exited non-zero (no log)"
    hits = [m for line in log_path.read_text(errors="replace").splitlines()
            if (m := ABORT_RE.search(line.strip()))]
    return f"aborted: {hits[-1].group(2).strip()}" if hits else "exited non-zero"


#: The parameter no reasoner may propose, and the string a refusal names it in. Checked
#: rather than trusted: `operator_only` is enforced in one place and a mechanism with one
#: enforcement point deserves one check that it fired.
OPERATOR_ONLY_DIAL = "difficulty"


def _difficulty_proposed(params: list[dict[str, Any]], graphs: list[dict[str, Any]],
                         stages: list[dict[str, Any]], cell: str) -> str:
    """Evidence that a reasoner tried to set the experiment's own dial, or "".

    Two places it could show. In `mappings`, if it somehow reached a deployed stage - the
    loud failure, because the arm then ran at a difficulty nobody declared. And in a
    rejection reason, which is the quiet and expected one: `OraclePlanner`'s schema check
    refuses a reply naming a frozen parameter, so a model that reached for it is corrected
    inside the retry and the campaign carries on. Worth recording either way: the second
    says the model wanted to, which is a finding about the model.
    """
    breach = [r for r in params
              if r["cell"] == cell and r["parameter"] == OPERATOR_ONLY_DIAL
              and r["source"] == "reasoner"]
    if breach:
        return f"set to {breach[0]['value']} in a deployed stage, not by the campaign"
    for rec in (*graphs, *stages):
        reason = str((rec.get("rejected") or {}).get("reason") or "")
        if OPERATOR_ONLY_DIAL in reason and "frozen" in reason:
            return reason
    return ""


def _registry() -> Any:
    """The tool registry, for the declared ranges a parameter value is read against.

    Imported inside the function: `analysis` may import `tools` (`tests/test_layering.py`
    allows it) but loading the toolkits costs a directory walk, and `collect` is the only
    stage that needs them - the sweep stage shells out and the figures read CSVs.
    """
    from ..tools.registry import Registry
    return Registry().load()


def _fraction_of_range(reg: Any, tool: str | None, name: str, value: Any) -> float | None:
    """Where a chosen value sits between a parameter's declared min and max.

    `None` when the spec declares no bounds, when the value is not a number, or when the
    tool is not in the registry - all three are "this cannot be placed on a scale", and a
    0.0 there would read as "the planner chose the minimum".
    """
    try:
        spec = reg.get(tool)
    except Exception:                      # noqa: BLE001 - an unknown tool is not an error
        return None
    param = spec.parameters.get(name)
    if param is None or param.min is None or param.max is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    span = float(param.max) - float(param.min)
    return round((float(value) - float(param.min)) / span, 4) if span else None


def _gate_names(gates: list[Any]) -> list[str]:
    """Gate names from either shape provenance writes them in.

    A node's `failed_gates` are full `GateResult` dicts - gate, role, observed, threshold,
    detail - and a task's are bare names. Both are read here, so both shapes are handled in
    one place rather than guessed at per call site.
    """
    out: list[str] = []
    for g in gates:
        out.append(str(g.get("gate", "")) if isinstance(g, dict) else str(g))
    return [g for g in out if g]


def _ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _union_busy(spans: list[tuple[float, float]]) -> float:
    """Seconds in which at least one task was running.

    Not the sum of task wall times, which double-counts whenever `workers > 1` overlaps two
    tasks, and not `wall - sum(wall)`, which can go negative and then reads as negative
    overhead. The union is correct at any concurrency, which matters because `workers: 4` is
    in the shipped campaign and a sweep cell runs four or eight lineages.
    """
    merged: list[list[float]] = []
    for a, b in sorted(s for s in spans if s[0] is not None and s[1] is not None):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return sum(b - a for a, b in merged)


def _write_csv(path: Path, rows: list[dict[str, Any]], order: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        log.warning("%s: no rows", path)
        return
    seen: list[str] = list(order or [])
    for r in rows:
        for k in r:
            if k not in seen:
                seen.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=seen, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log.info("%s: %d rows", path, len(rows))


def collect(out: Path) -> dict[str, Path]:
    """Flatten every cell's provenance into four tables.

    * `lineages.csv` - one row per `DesignNode`: the whole chain's metrics, merged, with the
      QC verdict the node ended on. This is the design-level ensemble.
    * `tasks.csv` - one row per task: its stage in the chain, its verdict, its gates, its
      timing and both sides of its cost.
    * `cycles.csv` - one row per composed graph: the signature, the interlock's scrutiny, the
      estimate, and the gate that refused it if one did.
    * `campaigns.csv` - one row per cell: how it stopped, how many decisions it took, how long
      they took, and where the wall clock went.
    """
    manifest = json.loads((out / "manifest.json").read_text())
    lineages: list[dict[str, Any]] = []
    # Gate -> role, learned from the node-level records, which carry it. The per-TASK records
    # carry gate names only, so a task row cannot say on its own whether it fell short of a
    # quality bar or broke - and that is the one thing the funnel figure has to say.
    gate_role: dict[str, str] = {}
    tasks: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    camps: list[dict[str, Any]] = []
    phases: list[dict[str, Any]] = []
    # `calls`, not `decisions`: the per-cell block below already binds `decisions` to the
    # graph count, and the accumulator was being replaced by an int on the first cell.
    calls: list[dict[str, Any]] = []
    params: list[dict[str, Any]] = []
    # Read once, for `fraction_of_range`. A parameter's declared min and max live in the
    # tool spec and nowhere in provenance, and "the planner set diffusion_steps to 170" says
    # much less than "85% of the way up its declared range".
    reg = _registry()

    for rec in manifest["cells"]:
        keys = {k: rec.get(k) for k in ("cell", "kind", "arm", "knob", "value", "rep",
                                        "salt", "model", "profile")}
        if rec.get("skipped"):
            # A cell the cap stopped the lab paying for. One row in `campaigns.csv` saying
            # so, and no attempt to read provenance it never wrote: a cell silently missing
            # reads as a model that had nothing to show rather than one nobody ran.
            camps.append(dict(keys, exit_code=None, skipped=rec["skipped"], aborted=False,
                              live=rec.get("live", False)))
            continue
        prov = Path(rec["run_dir"]) / "provenance"
        results = _jsonl(prov / "results.jsonl")
        task_rows = _jsonl(prov / "tasks.jsonl")
        graphs = _jsonl(prov / "graphs.jsonl")
        stages = _jsonl(prov / "stages.jsonl")
        specs = _jsonl(prov / "specs.jsonl")
        trans = _jsonl(prov / "transitions.jsonl")
        camp = _jsonl(prov / "campaign.jsonl")
        decided = _jsonl(prov / "decisions.jsonl")

        # -- what the reasoner was asked, and what it cost ---------------------------
        # Two shapes share `decisions.jsonl`: `reasoning.ask`'s per-call transcript, keyed
        # by `node`, and each agentic half's own summary of what it concluded, keyed by
        # `policy`. Only the first says a MODEL was called, so only the first is a call.
        asked = [d for d in decided if d.get("node") and d.get("model_id")]
        for d in asked:
            calls.append(dict(
                keys, node=d.get("node"), cycle=d.get("cycle"), attempt=d.get("attempt"),
                ok=bool(d.get("ok", True)), model_id=d.get("model_id"),
                elapsed_s=d.get("elapsed_s"),
                prompt_tokens=d.get("prompt_tokens"),
                completion_tokens=d.get("completion_tokens"),
                # The bodies stay in the JSONL. A prompt is thousands of characters and a
                # CSV is for counting, not for reading a transcript out of.
                prompt_chars=len(str(d.get("prompt") or "")),
                error=d.get("error", ""), ts=d.get("ts")))

        # -- the parameter vector each Planner chose ---------------------------------
        # From `stages.jsonl` `mappings`, which the executor writes for exactly this
        # (`executor.py`: "without it the parameter vector a Planner chose is recorded
        # nowhere"). It is the only evidence of WHICH knobs a reasoner moved, and the
        # pre-registration names it as the source for Planner attribution.
        # `mappings` holds the EFFECTIVE vector, so the campaign's own `params:` are in it
        # too - `_apply_campaign_defaults` merges them into the intent before composition.
        # Without separating them, every cell would read as a planner that set `difficulty`.
        # The cell's spec is what it declared, so a value equal to the declared one is
        # credited to the campaign and anything else to the reasoner. A reasoner that chose
        # exactly the declared value is credited to the campaign, which provenance cannot
        # distinguish and which is the conservative direction: it under-credits a model
        # rather than inventing a decision for it.
        declared = (yaml.safe_load(Path(rec["spec"]).read_text()).get("params") or {}
                    if rec.get("spec") and Path(rec["spec"]).exists() else {})
        cycle_of = {g.get("run"): g.get("cycle") for g in graphs}
        for st in stages:
            if st.get("event") != "deployed":
                continue
            for m in st.get("mappings") or []:
                tool = m.get("tool")
                for name, value in (m.get("params") or {}).items():
                    from_campaign = (declared.get(tool, {}).get(name) == value)
                    params.append(dict(
                        keys, run=st.get("run"), stage=st.get("stage"),
                        cycle=cycle_of.get(st.get("run")), task=m.get("task_id"),
                        tool=tool, lineage=m.get("lineage"), parameter=name, value=value,
                        source="campaign" if from_campaign else "reasoner",
                        declared=declared.get(tool, {}).get(name),
                        fraction_of_range=_fraction_of_range(reg, tool, name, value),
                        rationale=st.get("rationale", "")))

        for r in results:
            gates = r.get("failed_gates") or []
            roles = [str(g.get("role", "")) for g in gates if isinstance(g, dict)]
            for g in gates:
                if isinstance(g, dict) and g.get("gate"):
                    gate_role.setdefault(str(g["gate"]), str(g.get("role", "")))
            lineages.append(dict(
                keys, node=r.get("node"), cycle=r.get("cycle"),
                run=r.get("run"), lineage=r.get("lineage"), qc=r.get("qc"),
                failed_gates=";".join(_gate_names(gates)),
                # Split, because the split is the ruling (decision 0013): an ACCEPTANCE
                # shortfall fails the node and leaves the pattern's trust alone, while an
                # INTEGRITY failure demotes it. A figure that counted "failures" would draw
                # the `hard` arm and the `hopeless` arm as the same thing, and the whole
                # point of the `difficulty` dial is that they are not.
                failed_integrity=roles.count("integrity"),
                failed_acceptance=roles.count("acceptance"),
                fail_role=("integrity" if "integrity" in roles
                           else "acceptance" if "acceptance" in roles else ""),
                ts=r.get("ts"), **(r.get("metrics") or {})))

        spans: list[tuple[float, float]] = []
        for t in task_rows:
            m = NODE_RE.match(str(t.get("task", "")))
            start, end = _ts(t.get("started_at")), _ts(t.get("finished_at"))
            if start is not None and end is not None:
                spans.append((start, end))
            row = dict(keys, run=t.get("run"), cycle=t.get("cycle"), task=t.get("task"),
                       tool=t.get("tool"),
                       stage_index=int(m.group(2)) if m else -1,
                       lineage=t.get("lineage") if t.get("lineage") is not None
                       else (int(m.group(1)) if m else None),
                       qc=t.get("qc"),
                       failed_gates=";".join(t.get("failed_gates") or []),
                       seed=t.get("seed"), wall_s=t.get("wall_s"),
                       started_at=t.get("started_at"), finished_at=t.get("finished_at"),
                       gpu_h_est=(t.get("cost_estimated") or {}).get("gpu_hours"),
                       cpu_h_est=(t.get("cost_estimated") or {}).get("cpu_hours"),
                       gpu_h_measured=(t.get("cost_measured") or {}).get("gpu_hours"),
                       cpu_h_measured=(t.get("cost_measured") or {}).get("cpu_hours"))
            for name, value in (t.get("metrics") or {}).items():
                row[f"m_{name}"] = value
            tasks.append(row)

        for g in graphs:
            rej = g.get("rejected") or {}
            scr = g.get("scrutiny") or {}
            cycles.append(dict(
                keys, cycle=g.get("cycle"), graph=g.get("graph"), run=g.get("run"),
                signature=g.get("signature"), trusted=bool(g.get("trusted")),
                force_dry_run=bool(scr.get("force_dry_run")),
                mark_suspect=bool(scr.get("mark_suspect")),
                cost_cap_fraction=scr.get("cost_cap_fraction"),
                nodes=len(g.get("nodes") or {}),
                gpu_h_est=(g.get("estimate") or {}).get("gpu_hours"),
                cpu_h_est=(g.get("estimate") or {}).get("cpu_hours"),
                rejected_gate=rej.get("gate") or "",
                rejected_reason=rej.get("reason") or "",
                unproducible=";".join(g.get("unproducible_objectives") or []),
                ts=g.get("ts")))

        phases.extend(_phases(keys, camp, graphs, stages, task_rows, results, trans))

        term = next((t for t in reversed(trans) if t.get("event") == "terminated"), {})
        # An ABORTED campaign leaves no `terminated` record, and its `campaign_ended` record
        # says `reason: completed` - `Executor.stop_reason` was never set, so it reports its
        # default. So provenance ALONE cannot tell an aborted campaign from a finished one,
        # and the `hopeless` arm is the cell that proves it: `CampaignAborted: 3 consecutive
        # all-failed runs` appears nowhere but the process's stderr. Recorded in the backlog
        # as G15; until it is fixed the reason is recovered from the log this lab captured,
        # and the `aborted` column is derived from the EXIT CODE rather than from any record
        # the campaign wrote about itself.
        aborted = bool(rec.get("exit_code"))
        reason = term.get("reason", "")
        if aborted and not reason:
            reason = _abort_reason(out / "logs" / f"{rec['cell']}.log")
        t_start = _ts(camp[0].get("ts")) if camp else None
        t_end = _ts(term.get("ts")) or (max((_ts(t.get("ts")) or 0 for t in trans),
                                            default=None) if trans else None)
        wall = (t_end - t_start) if (t_start and t_end) else None
        busy = _union_busy(spans)
        deployed = [s for s in stages if s.get("event") == "deployed"]
        verdicts = [str(r.get("qc")) for r in results]
        # "Decisions" is deliberately the count of graphs the composer was asked for, not of
        # cycles: a rejected graph IS a decision, and the arm that spends its cycles being
        # refused at the interlock is exactly the one a cycle count would flatter.
        decisions = len(graphs)
        # `reasoner_degraded` and `oracle_degraded` share a name on purpose, so one query
        # finds every degraded decision whatever model made it. A non-zero count here means
        # the arm fell back to model D's cascade and its yield is NOT that model's - the
        # pre-registration's void rule, enforceable for the first time now that anything
        # writes these events (§8, and `compare_arms.Figures.degraded_events`).
        degraded = sum(1 for t in trans
                       if t.get("event") in ("reasoner_degraded", "oracle_degraded",
                                             "caller_timeout"))
        llm_s = sum(float(d.get("elapsed_s") or 0.0) for d in asked)
        model_ids = sorted({str(d["model_id"]) for d in asked if d.get("model_id")})
        camps.append(dict(
            keys, exit_code=rec.get("exit_code"), model=rec.get("model"),
            live=rec.get("live", False), skipped="",
            # Which model actually answered, from the records rather than from the flag the
            # lab passed. A cell that asked for `beam` and was answered by a rehearsal is
            # the failure the whole refusal rule exists to prevent, and this is where it
            # would show.
            model_id=";".join(model_ids),
            llm_calls=len(asked), llm_retries=sum(1 for d in asked if not d["ok"]),
            llm_s=round(llm_s, 4),
            prompt_tokens=sum(int(d.get("prompt_tokens") or 0) for d in asked) or None,
            completion_tokens=sum(int(d.get("completion_tokens") or 0) for d in asked)
            or None,
            s_per_llm_call=round(llm_s / len(asked), 4) if asked else None,
            degraded_events=degraded,
            # The freeze check. `difficulty` is `operator_only`, so no reasoner may propose
            # it; this is what says the mechanism held rather than assuming it did.
            difficulty_proposed=_difficulty_proposed(params, graphs, stages, rec["cell"]),
            stop_reason=reason, aborted=aborted,
            cycles=term.get("cycles") if not aborted else len(graphs),
            front=len(term.get("front") or []),
            nodes=len(results), tasks=len(task_rows),
            graphs=len(graphs), rejected_graphs=sum(1 for g in graphs if g.get("rejected")),
            stages_deployed=len(deployed), spec_events=len(specs),
            decisions=decisions,
            n_pass=verdicts.count("pass"), n_suspect=verdicts.count("suspect"),
            n_fail=verdicts.count("fail"),
            wall_s=round(wall, 4) if wall else None,
            busy_s=round(busy, 4),
            overhead_s=round(wall - busy, 4) if wall else None,
            decisions_per_s=round(decisions / wall, 2) if wall else None,
            tasks_per_s=round(len(task_rows) / wall, 2) if wall else None,
            s_per_decision=round(wall / decisions, 4) if (wall and decisions) else None,
            launch_wall_s=rec.get("launch_wall_s"),
            llm_share=round(llm_s / wall, 4) if (wall and llm_s) else None,
            gpu_h_measured=round(sum((t.get("cost_measured") or {}).get("gpu_hours") or 0.0
                                     for t in task_rows), 6),
            gpu_h_est=round(sum((t.get("cost_estimated") or {}).get("gpu_hours") or 0.0
                                for t in task_rows), 6)))

    for row in tasks:
        names = [n for n in str(row.get("failed_gates") or "").split(";") if n]
        roles = [gate_role.get(n, "") for n in names]
        row["fail_role"] = ("integrity" if "integrity" in roles
                            else "acceptance" if "acceptance" in roles else "")

    tables = out / "tables"
    _write_csv(tables / "lineages.csv", lineages,
               ["cell", "kind", "arm", "model", "knob", "value", "rep", "salt", "node",
                "cycle", "run", "lineage", "qc", "failed_gates", *OBJECTIVES])
    _write_csv(tables / "tasks.csv", tasks,
               ["cell", "kind", "arm", "model", "knob", "value", "rep", "salt", "run",
                "cycle", "lineage", "stage_index", "tool", "task", "qc", "failed_gates",
                "wall_s"])
    _write_csv(tables / "cycles.csv", cycles)
    _write_csv(tables / "campaigns.csv", camps)
    _write_csv(tables / "phases.csv", phases)
    _write_csv(tables / "decisions.csv", calls,
               ["cell", "kind", "arm", "model", "profile", "rep", "node", "cycle",
                "attempt", "ok", "model_id", "elapsed_s", "prompt_tokens",
                "completion_tokens"])
    _write_csv(tables / "params.csv", params,
               ["cell", "kind", "arm", "model", "rep", "run", "cycle", "tool", "parameter",
                "value", "source", "declared", "fraction_of_range"])
    return {"lineages": tables / "lineages.csv", "tasks": tables / "tasks.csv",
            "cycles": tables / "cycles.csv", "campaigns": tables / "campaigns.csv",
            "phases": tables / "phases.csv", "decisions": tables / "decisions.csv",
            "params": tables / "params.csv"}


#: The control plane's segments inside one cycle, in the order a cycle walks them, and the
#: pair of timestamps each is measured between. `plan` carries backend construction and
#: registry load on the FIRST cycle, which is why `first_cycle` is a column rather than a
#: thing a reader has to infer from a suspiciously fat first bar.
PHASE_SEGMENTS = ("plan", "admit", "dispatch", "execute", "absorb")


def _phases(keys: dict[str, Any], camp: list[dict[str, Any]], graphs: list[dict[str, Any]],
            stages: list[dict[str, Any]], task_rows: list[dict[str, Any]],
            results: list[dict[str, Any]], trans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per cycle: where that cycle's wall clock went.

    Worth having its own table because of what the arms measure: a surrogate task returns in
    microseconds, so `execute` is ~0.1% of a cycle and everything else is the agent. A figure
    of "campaign wall time" against these tools would otherwise be a figure of Python import
    cost wearing a campaign's name, and the point of the breakdown is to say so out loud.

    Every segment is a DIFFERENCE BETWEEN TWO RECORDS THE EXECUTOR WROTE, never an estimate:

    * `plan`     - the previous cycle's last result to this cycle's composed graph. On cycle 0
                   it runs from the campaign's first record, so it also holds engine and
                   backend construction and the toolkit load.
    * `admit`    - composed to deployed: the five gates, then the trust interlock.
    * `dispatch` - deployed to the first task actually starting.
    * `execute`  - first task start to last task finish. The only segment that is the science.
    * `absorb`   - last task finish to the node's result record: QC, ingest, the front.

    A cycle whose graph was REJECTED has no deploy and no tasks, so everything after `admit`
    is None rather than 0.0 - a zero there would read as "the gates admitted it instantly".
    """
    t0 = _ts(camp[0].get("ts")) if camp else None
    end = max((_ts(t.get("ts")) or 0.0 for t in trans), default=None)
    by_run_deploy = {s.get("run"): _ts(s.get("ts")) for s in stages
                     if s.get("event") == "deployed"}
    out: list[dict[str, Any]] = []
    prev = t0
    for order, g in enumerate(sorted(graphs, key=lambda g: _ts(g.get("ts")) or 0.0)):
        run = g.get("run")
        g_ts = _ts(g.get("ts"))
        d_ts = by_run_deploy.get(run)
        spans = [(_ts(t.get("started_at")), _ts(t.get("finished_at")))
                 for t in task_rows if t.get("run") == run]
        spans = [(a, b) for a, b in spans if a is not None and b is not None]
        first = min((a for a, _ in spans), default=None)
        last = max((b for _, b in spans), default=None)
        r_ts = max((_ts(r.get("ts")) or 0.0 for r in results if r.get("run") == run),
                   default=None) or None
        def seg(a: float | None, b: float | None) -> float | None:
            return round(b - a, 6) if (a is not None and b is not None) else None
        row = dict(keys, run=run, graph=g.get("graph"), cycle=g.get("cycle"), order=order,
                   first_cycle=(order == 0),
                   rejected_gate=(g.get("rejected") or {}).get("gate") or "",
                   plan=seg(prev, g_ts), admit=seg(g_ts, d_ts),
                   dispatch=seg(d_ts, first), execute=seg(first, last),
                   absorb=seg(last, r_ts),
                   tasks=len(spans), busy=round(_union_busy(spans), 6))
        # How much of the execute window had a tool running in it. Measured on these
        # surrogates it is around 2%: the window is 0.11s per cycle and the six tools inside
        # it return in about 2ms. The rest is the dispatcher's own scheduling, which is a
        # real cost and is NOT the science - so the breakdown reports it separately rather
        # than letting "execute" stand for work done.
        row["exec_wait"] = (round(row["execute"] - row["busy"], 6)
                            if row["execute"] is not None else None)
        row["busy_share"] = (round(row["busy"] / row["execute"], 4)
                             if row["execute"] else None)
        row["cycle_s"] = round(sum(v for k in PHASE_SEGMENTS
                                   if (v := row[k]) is not None), 6)
        out.append(row)
        prev = r_ts or d_ts or g_ts or prev
    if out and end is not None and prev is not None:
        # Whatever the campaign spent AFTER its last result - stop decision, drain, teardown.
        # Attached to the last cycle rather than dropped, because on these tools it is not
        # small and a breakdown that does not add up to the wall clock invites the reader to
        # assume the gap is execution.
        out[-1]["teardown"] = round(end - prev, 6)
    return out


def read_table(path: Path) -> list[dict[str, Any]]:
    """A CSV back as rows, with numbers parsed and the empty string kept as None.

    `float("")` raises and `float("nan")` does not, so a missing metric has to be None rather
    than NaN here: a tool that could not report a metric OMITS it (the `metrics_reported`
    invariant), and turning that absence into a number is the fabricated-zero failure the
    invariant exists to prevent.
    """
    rows: list[dict[str, Any]] = []
    if not path.exists() or not path.stat().st_size:
        return rows
    with path.open(newline="") as fh:
        for raw in csv.DictReader(fh):
            row: dict[str, Any] = {}
            for k, v in raw.items():
                if v is None or v == "":
                    row[k] = None
                elif v in ("True", "False"):
                    row[k] = v == "True"
                else:
                    try:
                        row[k] = float(v) if ("." in v or "e" in v.lower()) else int(v)
                    except ValueError:
                        row[k] = v
            rows.append(row)
    return rows


# -- entry point -------------------------------------------------------------------------

def _progress() -> None:
    """Make this package's own log visible, without touching the root handler.

    A library that calls `logging.basicConfig` steals the root handler from whoever embedded
    it, which is why `cli/__init__.py` never configures logging. A lab that runs for half a
    minute and says nothing is unusable, so the handler goes on THIS package's logger and
    stops propagating - the embedder's configuration is untouched either way.
    """
    pkg = logging.getLogger("impress_a.analysis")
    if not pkg.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        pkg.addHandler(handler)
        pkg.setLevel(logging.INFO)
        pkg.propagate = False


def main(out: str | Path, stage: str = "all", repeats: int = 3, only: list[str] | None = None,
         model: str = "", jobs: int = 4, base_spec: str | Path = BASE_SPEC,
         reasoners: list[str] | None = None, profile: str = "",
         reasoner_repeats: int = 3, max_llm_calls: int = 400) -> int:
    _progress()
    out = Path(out)
    if stage in ("all", "sweep"):
        try:
            sweep(out, repeats=repeats, only=only, model=model, jobs=jobs,
                  base_spec=Path(base_spec), models=reasoners, profile=profile,
                  reasoner_repeats=reasoner_repeats, max_llm_calls=max_llm_calls)
        except (ValueError, RuntimeError) as refused:
            # An unknown letter, a live model with no profile, an endpoint that did not
            # answer: all operator errors, and all reported the way preflight reports a
            # missing binary rather than as a traceback. Nothing has been spent at this
            # point - the refusals run before the first cell.
            log.error("%s", refused)
            return 2
    if stage in ("all", "collect"):
        if not (out / "manifest.json").exists():
            log.error("%s: no manifest.json - run the sweep stage first", out)
            return 2
        collect(out)
    if stage in ("all", "figures"):
        from .mock_figures import draw_all
        draw_all(out)
    return 0


def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the mock small-molecule knob lab")
    ap.add_argument("--out", default="campaigns/_runs/_analysis")
    ap.add_argument("--stage", default="all", choices=("all", "sweep", "collect", "figures"))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--only", action="append", default=None)
    ap.add_argument("--model", default="")
    ap.add_argument("--reasoners", action="append", default=None)
    ap.add_argument("--model-profile", dest="profile", default="")
    ap.add_argument("--reasoner-repeats", type=int, default=3)
    ap.add_argument("--max-llm-calls", type=int, default=400)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--base-spec", default=str(BASE_SPEC))
    a = ap.parse_args(argv)
    return main(a.out, a.stage, a.repeats, a.only, a.model, a.jobs, a.base_spec,
                a.reasoners, a.profile, a.reasoner_repeats, a.max_llm_calls)


if __name__ == "__main__":
    raise SystemExit(_cli())
