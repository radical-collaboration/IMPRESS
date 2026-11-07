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

from ..compose.composer import Composer
from ..compose.interlock import TrustLedger
from ..compose.validate import SiteCaps
from ..control.http import ControlPlaneClient, ControlPlaneServer
from ..control.plane import InProcessControlPlane
from ..control.session import RemoteSession
from ..core.decision import ExperimentIntent
from ..core.goal import Goal
from ..core.pareto import Objective
from ..core.session import CampaignStopped
from ..manager import CampaignManager, CampaignSpec
from ..policy import registry as reasoners
from ..policy.wrappers import RuleCorrectionsPolicy, StageGuard
from ..runtime.roles import RolesDriver
from ..tools.registry import Registry

# Module logger, never configured here: a library that calls basicConfig steals the
# root handler from whoever embedded it. `scripts/delta_run_campaign.py` configures it,
# and everything below is silent by default - including under pytest.
log = logging.getLogger(__name__)

# Derived, not restated. The taxonomy lives in `policy/registry.py` so that it is not a
# CLI detail; this name is kept because `slides/api/run_model.py` reads it to generate the
# deck's model count, and a deck that disagrees with the code is the drift this avoids.
POLICIES = reasoners.CLASSES

#: The subcommands `main` registers. Declared once because `slides/api/run_model.py` reads
#: it to generate the deck, and had the list hardcoded - so adding `models` here would
#: otherwise have left the deck claiming three subcommands against the code's four.
#: `tests/test_reasoner_registry.py` asserts the parser accepts every name in it.
SUBCOMMANDS = ("run", "serve", "control", "tools", "models", "preflight",
               "trust")


def _resolve_path_params(params: dict[str, Any], base: Path) -> dict[str, Any]:
    """A relative `*_path` tool parameter is relative to the campaign YAML, not the CWD.

    The launcher cds into a per-job directory before loading the spec, so a CWD-relative
    path breaks there; an absolute one ties the spec to one checkout on one machine.
    """
    out: dict[str, Any] = {}
    for tool, p in params.items():
        if isinstance(p, dict):
            p = {k: (str(base / v) if k.endswith("_path") and isinstance(v, str)
                     and v and not Path(v).is_absolute() else v)
                 for k, v in p.items()}
        out[tool] = p
    return out


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
        # Env for the same reason as trust_root below: the launcher points this at the job's
        # own directory so provenance (and asyncflow's session dir, which the executor puts
        # under root) sits beside campaign.log rather than three levels down.
        root=d.get("root") or os.environ.get("IMPRESS_A_RUN_ROOT", "campaigns/_runs"),
        # Env, not YAML, because the right value is machine-specific: on Delta it has to be
        # outside the per-job working directory the launcher cds into, and YAML carries no
        # env expansion. Set beside MPNN_DIR/BOLTZ_CACHE in scripts/delta_gpu_run.sh.
        trust_root=d.get("trust_root") or os.environ.get("IMPRESS_A_TRUST_DIR", ""),
        # Env, not YAML: one experiment's salt has to be shared across several submissions
        # of the same spec, and differ between experiments. `scripts/delta_gpu_run.sh` records
        # it in the job manifest.
        seed_salt=d.get("seed_salt") or os.environ.get("IMPRESS_A_SEED_SALT", ""),
        # Every field below is read from YAML, deliberately exhaustively. A key a spec file
        # sets and the loader ignores does nothing and says nothing - which is exactly what
        # `sites/*.yaml`'s `tool_delivery` switch has been doing since it was written (E1),
        # and what `control_liveness_timeout_s: 120` did in all three Delta specs until this
        # line existed.
        control=d.get("control", "legacy"),
        runner=d.get("runner", "dispatcher"),
        control_liveness_timeout_s=float(d.get("control_liveness_timeout_s", 0) or 0),
        max_unproductive_runs=int(d.get("max_unproductive_runs", 8)),
        target_front=int(d.get("target_front", 0)),
        tool_delivery=d.get("tool_delivery", "any"),
        stages=d.get("stages", []) or [],
        params=_resolve_path_params(d.get("params", {}) or {}, Path(path).resolve().parent),
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


def build_policy(model: str, spec: CampaignSpec, guard: bool = True,
                 records: list[dict[str, Any]] | None = None,
                 profile: str | None = None):
    """Adapt a `CampaignSpec` into the registry's options, and construct the reasoner.

    This function is the adapter and nothing more. `policy/registry.py` owns which models
    exist and how each is built; it cannot do this part itself, because `CampaignSpec`
    lives in `runtime/` and `policy` may import `core` only (ADR 0010, asserted by
    `tests/test_layering.py`). Putting the spec on the other side of that line is what
    would make control models stop being swappable.

    `stages` has to reach the policy or every model falls back to its built-in default,
    which is the mock chain - so a real campaign would validate the real toolkits and
    then execute mocks.
    """
    # `max_cycles` IS forwarded now, and the earlier reasoning for withholding it was half
    # right. Withholding avoided bounding the same thing from two places, which is how an
    # off-by-one became invisible (the driver counted a Backtrack as a cycle for three Delta
    # jobs). But it left every model carrying `ReasonerOptions.max_cycles`'s default of 6,
    # which does not merely duplicate the campaign's bound - it is TIGHTER than it. A 4-hour
    # arm with `max_cycles: 200` would have made six decisions in about twenty minutes and then
    # stopped itself, spending roughly 8% of the allocation. That is the worse of the two
    # failures, and it is silent.
    #
    # Forwarding the spec's own value makes the policy's self-stop no tighter than the
    # campaign's, so the driver remains the authority and a policy can still stop early for its
    # own reasons. `target_front` comes from the spec for the same reason: 3 is a sensible
    # default for a demo and an arbitrary cap on a campaign asked for ten designs, and a
    # campaign that declares neither keeps the model's own number.
    pol = reasoners.build(model, reasoners.ReasonerOptions(
        stages=list(spec.stages) or None,
        oracle=_oracle_for(profile, spec),
        max_cycles=spec.max_cycles,
        target_front=spec.target_front or reasoners.ReasonerOptions().target_front,
        records=records,
    ))
    if guard:
        pol = RuleCorrectionsPolicy(pol, max_replicas=8, forbid_tools=("mock_noodle",))
    return pol


def build_roles(model: str, spec: CampaignSpec, guard: bool = True,
                records: list[dict[str, Any]] | None = None,
                specifier: str | None = None, planner: str | None = None,
                spec_records: list[dict[str, Any]] | None = None,
                stage_records: list[dict[str, Any]] | None = None,
                profile: str | None = None, caller_timeout_s: float | None = None):
    """The same adapter, for the two halves.

    Two guard shapes, because there are two kinds of half. A pair derived from a
    `ControlPolicy` is guarded by wrapping that policy once - it is the thing making the
    decisions, so wrapping it is wrapping both halves. A model with real halves is guarded by
    `StageGuard` on the planner, which is narrower than its predecessor on purpose: the
    replica cap now binds in the executor and a task serving no objective is refused by the
    Reviewer, so what is left to wrap is `forbid_tools` until phase 10's gate 6 takes it over.

    `--no-guard` therefore stops being able to switch off either of the two checks that
    matter, which it never should have been able to do.
    """
    opts = reasoners.ReasonerOptions(
        stages=list(spec.stages) or None, records=records,
        spec_records=spec_records, stage_records=stage_records,
        oracle=_oracle_for(profile, spec),
        timeout_s=caller_timeout_s or reasoners.ReasonerOptions().timeout_s,
        max_cycles=spec.max_cycles,
        target_front=spec.target_front or reasoners.ReasonerOptions().target_front)
    if specifier or planner or _declares_halves(specifier or model, planner or model):
        pair = reasoners.build_roles(specifier or model, planner or model, opts)
        if guard:
            pair.planner = StageGuard(pair.planner, forbid_tools=("mock_noodle",))
        return pair
    pol = build_policy(model, spec, guard, records)
    return reasoners.RolePair(*_halves_of(pol), label=model)


def _oracle_for(profile: str | None, spec: CampaignSpec) -> Any:
    """The model model B talks to, from `--model-profile`.

    `None` leaves the registry to build `RehearsalOracle` with the campaign's chain, which is
    what `--model B` runs with no profile named - and `impress-a models` reports `llm_calls: 0`
    for exactly that reason. Loaded here rather than in `policy/` because `policy` may import
    `core` only and reading a YAML file is not `core`'s business either; the same reason
    `_replay_records` lives here.
    """
    if not profile:
        return None
    from ..policy.llm import build_oracle, load_profiles
    # The PACKAGED file, unless an operator names another one explicitly. It used to try the
    # current working directory first, and that is a credential path rather than a
    # convenience: a profile's `base_url` is where the request goes and its `api_key_env`
    # names the key that goes with it, so a `models.yaml` in whatever directory a job happened
    # to start in could point the operator's own key at someone else's endpoint. On a shared
    # filesystem, with a launcher that cd's into a per-job directory, that is not a remote
    # hazard. `IMPRESS_A_MODELS` stays, because an operator choosing a file is a decision and
    # a directory a process was started in is not.
    path = Path(__file__).resolve().parents[3] / "models.yaml"
    if override := os.environ.get("IMPRESS_A_MODELS"):
        path = Path(override)
        log.warning("control model: reading profiles from $IMPRESS_A_MODELS=%s rather than "
                    "the packaged models.yaml", path)
    profiles = load_profiles(path)
    if profile not in profiles:
        raise ValueError(f"unknown model profile {profile!r}; {path} declares "
                         f"{sorted(profiles)}")
    chosen = profiles[profile]
    # The endpoint and the key variable together, because provenance should record which
    # credential was sent where. A figure attributed to a model is only as good as the record
    # of what answered.
    log.info("control model: profile %s from %s (kind=%s, model=%s, endpoint=%s, key=%s)",
             profile, path, chosen.kind, chosen.model, chosen.base_url or "-",
             chosen.api_key_env or "none")
    return build_oracle(chosen, stages=list(spec.stages) or None)


def _declares_halves(spec_letter: str, plan_letter: str) -> bool:
    """Whether both requested halves are the model's own rather than derived from `decide`.

    While the strangler is in place most models have no halves of their own, and
    `DecideAsRoles` presents their `ControlPolicy` as a pair - which is what made
    `--control roles` a change of vocabulary rather than of behaviour. Model D now has real
    halves, so the derivation has to stop being unconditional: taking the adapter when a
    model declares a `ThresholdPlanner` would run the legacy decision cascade under a flag
    that says otherwise, and the campaign log would name a planner that never planned.

    Both halves, not either: a pair with one real and one derived half would mean a
    `ThresholdPlanner` planning against a Spec the `LegacySpecifier` wrote, which is a
    combination nothing has tested and nobody asked for. `--specifier X --planner Y` is the
    supported way to mix, and it is checked first by the caller.
    """
    models = reasoners.MODELS
    return (spec_letter in models and plan_letter in models
            and models[spec_letter].specifier is not None
            and models[plan_letter].planner is not None)


def _halves_of(policy: Any):
    from ..policy.legacy import DecideAsRoles
    pair = DecideAsRoles(policy)
    return pair.specifier, pair.planner


def _git_sha() -> str:
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=5, cwd=str(Path(__file__).resolve().parents[3]))
        sha = out.stdout.strip() if out.returncode == 0 else ""
        dirty = subprocess.run(["git", "status", "--porcelain", "-uno"], capture_output=True,
                               text=True, timeout=5,
                               cwd=str(Path(__file__).resolve().parents[3]))
        return f"{sha}{'-dirty' if dirty.stdout.strip() else ''}" if sha else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _signatures_for(spec: CampaignSpec, widths: list[int]) -> list[tuple[str, list[str], int]]:
    """The pattern signatures a campaign will actually compose, one per replica width.

    Computed by composing the campaign's own chain rather than guessed, because the signature
    is a hash of graph shape and **includes replica multiplicity** - asserting at width 1 does
    not trust width 4, which is the whole of backlog A10. `--replicas` therefore takes the
    widths the campaign will run, and a campaign that will fan out to 4 must say so here.
    """
    reg = Registry().load()
    composer = Composer(reg)
    out = []
    for width in widths:
        intent = ExperimentIntent(goal=spec.goal, stages=list(spec.stages),
                                  params=dict(spec.params), replicas=width)
        graph = composer.compose(intent, run_label="trust-assert")
        tools = sorted({n.tool for n in graph.nodes.values()})
        out.append((graph.pattern_signature(), tools, width))
    return out


def trust(spec_path: str | None, do_assert: bool, revoke: str | None, reason: str,
          widths: list[int]) -> int:
    """Grant, list or withdraw trust for the composition patterns a campaign runs.

    A pre-loaded Toolkit of Tasks proven elsewhere should not spend an allocation re-earning
    trust at runtime, and for a wide pattern it *cannot*: promotion counts consecutive clean
    runs, and replica multiplicity is part of the signature, so width 4 can never reach three
    clean runs under a realistic budget while the one-instance-in-flight rule serialises it.

    What this does not do is pretend the trust was earned. The ledger records an `asserted`
    event with who, why and the commit, and every listing distinguishes it - because a figure
    derived from an asserted admission has to be reportable as such.
    """
    ledger_dir = Path(os.environ.get("IMPRESS_A_TRUST_DIR", "")
                      or (Path(load_spec(spec_path).root) / "_trust" if spec_path
                          else "campaigns/_runs/_trust"))
    api = os.environ.get("IMPRESS_A_GPU_API", "cuda")
    led = TrustLedger.load(ledger_dir / f"{api}.jsonl")
    print(f"\n  trust ledger: {(ledger_dir / f'{api}.jsonl').resolve()}")

    if revoke:
        ok = led.revoke(revoke, reason=reason or "revoked from the command line")
        print(f"  {'revoked' if ok else 'not trusted, nothing to revoke'}: {revoke}")
        return 0 if ok else 1

    if do_assert:
        if not spec_path:
            print("  --assert needs a campaign spec: the signature is computed from its chain")
            return 1
        if not reason.strip():
            print("  --assert needs --reason: it is the justification on the record, and what "
                  "a later reader will ask for")
            return 1
        spec = load_spec(spec_path)
        if not spec.stages:
            print("  that campaign declares no stages, so there is no chain to assert")
            return 1
        sha = _git_sha()
        for sig, tools, width in _signatures_for(spec, widths):
            led.assert_trusted(sig, tools, reason=reason, by=os.environ.get("USER", ""),
                               git_sha=sha)
            print(f"  asserted {sig}  replicas={width}  ({', '.join(tools)})")
        print(f"  reason: {reason}")
        if sha:
            print(f"  git:    {sha}")

    rows = [("signature", "trust", "clean", "demotions", "tools")]
    for sig in sorted(led.patterns):
        r = led.patterns[sig]
        rows.append((sig, "asserted" if r.asserted else "earned" if r.trusted else "-",
                     str(r.clean_runs), str(r.demotions), ",".join(r.tools)))
    widths_ = [max(len(c) for c in col) for col in zip(*rows, strict=True)]
    print()
    for n, row in enumerate(rows):
        print("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths_, strict=True)).rstrip())
        if n == 0:
            print("  " + "  ".join("-" * w for w in widths_))
    if len(rows) == 1:
        print("  (no patterns known at this site yet)")
    return 0


class _Idle:
    """A reasoner that is not there, for the execution process.

    `impress-a serve` runs the executor, the Reviewer, the Deployer, the Runner and the one
    asyncflow engine, and NO reasoner - the control process supplies that over the session. The
    manager races a reasoner's `conduct` against the executor's pump, so the execution side
    needs something that stays out of the way rather than something that decides.

    Not `NullPolicy`: that stops the campaign on its first decision, which is the opposite of
    what a served campaign wants.
    """

    name = "served"

    async def conduct(self, session: Any) -> None:
        await asyncio.Event().wait()


async def serve_campaign(spec_path: str, host: str = "127.0.0.1", port: int = 0,
                         heartbeat_s: float | None = None, model: str | None = None,
                         guard: bool = True, profile: str | None = None,
                         caller_timeout_s: float | None = None) -> int:
    """Run the execution process and serve it over HTTP.

    Backlog C5: the out-of-process split has been reachable from `tests/` and from no shell
    since it was written, so `docs/reference/frontends.md` described as "implemented" something
    nobody could run. These are those entry points.

    Loopback by default, and that is the security boundary this configuration can defend: the
    plane has no auth and no TLS, both ends sit on the same compute node, and backlog C7 - where
    it may be reachable from - stays answered by "nowhere else" rather than by a token nobody
    rotates.

    **`--model` is what makes arm C runnable, and leaving it out is the two-process split.**
    Without it the served campaign has no reasoner, which is right for `impress-a control` to
    attach to. But `plane.steer` reaches `manager.policy`, which lives in THIS process - so a
    third party steering a campaign served with no reasoner reaches nothing, and gets
    `campaign is not under external control` for a campaign whose whole arrangement is
    external control. That is not a transport problem to fix in the plane: decision 0002 says
    model C *is* the headless mode, and the headless mode is one process serving a campaign
    whose halves are its inboxes. So `impress-a serve <spec> --model C` registers the pair
    here and a caller steers it over HTTP; `impress-a serve <spec>` alone keeps the split for
    A, B and D, whose halves have no inbox and want a control process instead.
    """
    spec = load_spec(spec_path)
    if err := _check_ligand_smiles(spec):
        log.error("%s", err)
        return 1
    for var, val in _thread_caps(spec).items():
        os.environ.setdefault(var, val)
    spec.control = "roles"
    reg = Registry().load()
    reasoner: Any = _Idle()
    if model:
        reasoner = build_roles(model, spec, guard, profile=profile,
                               caller_timeout_s=caller_timeout_s)
        log.info("serving campaign with %s attached: an external caller steers it in place, "
                 "rather than a control process attaching to it", reasoner.name)
    mgr = CampaignManager(spec, reasoner, reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)
    if heartbeat_s is None:
        heartbeat_s = float(os.environ.get("IMPRESS_A_HEARTBEAT_S", "60") or 0)

    async with ControlPlaneServer(plane, host=host, port=port) as server:
        # Printed, not only logged: a control process needs the URL, and on Delta the two are
        # started by the same script from the same job.
        print(f"campaign {cid} serving on {server.base_url}", flush=True)
        log.info("serving campaign %s on %s (liveness timeout %.0fs)", cid,
                 server.base_url, spec.control_liveness_timeout_s)
        res = await mgr.run()
    print(f"\n  campaign : {res.campaign_id}\n  cycles   : {res.cycles}"
          f"\n  stop     : {res.stop_reason}\n  nodes    : {len(res.tree)}"
          f"  front: {len(res.front)}")
    return 0


async def control_campaign(url: str, campaign_id: str, model: str = "D",
                           specifier: str | None = None, planner: str | None = None,
                           guard: bool = True, profile: str | None = None) -> int:
    """Run the Spec Loop and Planning Loop in their own process, over the session.

    The same `RolesDriver` the in-process path uses, against `RemoteSession` instead of
    `InProcessSession` - which is the whole reason phase 1 wrote the roles against
    `CampaignSession` rather than against the executor.

    **This is also why `--model C` can no longer fail open.** A control process IS the
    reasoner, so "no reasoner attached" is not a state that exists here; under `impress-a run`
    it is refused outright rather than timing out every five seconds and silently running D
    while reporting C (backlog C6).
    """
    client = ControlPlaneClient(url)
    async with client:
        session = RemoteSession(client, campaign_id)
        obs = await session.observe()
        goal = Goal(text=obs.goal, objectives=list(obs.objectives))
        pair = _role_pair(model, specifier, planner, list(obs.stages), guard, profile)
        log.info("control: driving campaign %s at %s with %s", campaign_id, url, pair.name)
        driver = RolesDriver(goal, pair.specifier, pair.planner,
                             max_turns=10_000, concurrency=1)
        try:
            await driver.conduct(session)
        except CampaignStopped as stopped:
            log.info("control: campaign ended (%s)", stopped)
    return 0


def _role_pair(model: str, specifier: str | None, planner: str | None,
               stages: list[str], guard: bool, profile: str | None = None):
    """Build the two halves for a remote driver, from the served campaign's own chain.

    `stages` comes from `CampaignObservation.stages` - the campaign's declaration in its own
    order - and not from `toolkit.ids`, which holds the same tools sorted by id. A Planner
    wires each port to the nearest preceding producer, so under alphabetical order
    `mock_design` precedes `mock_generate` and the sequence step would be planned before the
    backbone it consumes.
    """
    opts = reasoners.ReasonerOptions(
        stages=stages or None,
        oracle=_oracle_for(profile, CampaignSpec(campaign_id="", goal="", objectives=[],
                                                 stages=list(stages))))
    if specifier or planner or _declares_halves(specifier or model, planner or model):
        pair = reasoners.build_roles(specifier or model, planner or model, opts)
        if guard:
            pair.planner = StageGuard(pair.planner, forbid_tools=("mock_noodle",))
        return pair
    pol = reasoners.build(model, opts)
    if guard:
        pol = RuleCorrectionsPolicy(pol, max_replicas=8, forbid_tools=("mock_noodle",))
    return reasoners.RolePair(*_halves_of(pol), label=model)


def print_models() -> int:
    """Print the control models, their shape and their real status.

    This exists so the status column cannot go stale unnoticed. `docs/` claimed four
    working control models while two of them had no LLM behind them at all, and nothing
    in the tool contradicted it. A reader can now ask the code.
    """
    rows = reasoners.table()
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    print()
    for n, row in enumerate(rows):
        print("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip())
        if n == 0:
            print("  " + "  ".join("-" * w for w in widths))
    print()
    for letter in sorted(reasoners.MODELS):
        m = reasoners.MODELS[letter]
        if m.note:
            print(f"  {m.letter}: {m.note}")
            if m.spec_ref:
                print(f"     specified in {m.spec_ref}")
    print("\n  `llm` is what the specification asks for; `calls` is what runs today.")
    print("  Reference: docs/reference/frontends.md\n")
    return 0


def _replay_records(path: str) -> list[dict[str, Any]]:
    """Load a recorded decision sequence from a campaign's provenance directory.

    `provenance/decisions.jsonl` is what `LoggingPolicy` and the models that carry their
    own sink write. Reading it here rather than in `ReplayPolicy` keeps the policy layer
    off the filesystem, which is the same reason policies never touch `tools`.
    """
    p = Path(path)
    if p.is_dir():
        p = p / "provenance" / "decisions.jsonl" if (p / "provenance").is_dir() \
            else p / "decisions.jsonl"
    if not p.is_file():
        raise FileNotFoundError(f"no decisions.jsonl under {path}")
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def _replay_role_records(path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`(specs, stages)` from a recorded campaign, for the two replay halves.

    Two files rather than one, and executor-written rather than reasoner-written - which is
    why the halves can replay a campaign run by a model that kept no notes of its own, where
    `decisions.jsonl` only holds what a model chose to record about itself.

    Read here rather than in the policy layer, for the reason `_replay_records` gives: a
    policy that touches the filesystem is a policy that can reach past `core`.
    """
    root = Path(path)
    prov = root / "provenance" if (root / "provenance").is_dir() else root
    out = []
    for name in ("specs.jsonl", "stages.jsonl"):
        f = prov / name
        if not f.is_file():
            raise FileNotFoundError(
                f"no {name} under {path}. The replay halves read the executor's own record; "
                f"a campaign recorded before `specs`/`stages` provenance existed can only be "
                f"replayed with `--control legacy`")
        out.append([json.loads(line) for line in f.read_text().splitlines() if line.strip()])
    return out[0], out[1]


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
                       heartbeat_s: float | None = None,
                       replay_from: str | None = None, control: str | None = None,
                       specifier: str | None = None, planner: str | None = None,
                       profile: str | None = None) -> int:
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
    # Naming either half implies the role pipeline: a Specifier has nowhere to run in the
    # single-`decide` path. Stated as an implication rather than an error so that
    # `--specifier B --planner D` is one flag pair rather than three.
    # Backlog C6, closed by refusing rather than by detecting. `impress-a run` attaches no
    # control plane, so model C's `decide` blocked on an inbox nothing fed, timed out every
    # five seconds and ran its declared fallback - a model-D campaign reported as model C. The
    # entry points that make C real exist now, so "no caller attached" is an operator error
    # with an answer rather than a mode to degrade into.
    if "C" in {model, specifier, planner}:
        log.error(
            "--model C means an external caller steers the campaign, and `impress-a run` "
            "attaches no control plane - it would time out every %.0fs and silently run its "
            "fallback, reporting a model-D campaign as model C (backlog C6). Use two "
            "processes instead:\n"
            "    impress-a serve %s\n"
            "    impress-a control --connect <url> --campaign <id> --model C",
            reasoners.ReasonerOptions().timeout_s, spec_path)
        return 1
    if specifier or planner:
        control = "roles"
    if control:
        spec.control = control
    label = model if not (specifier or planner) else f"{specifier or model}/{planner or model}"
    spec.campaign_id = f"{spec.campaign_id}-{label}"
    try:
        # Only the record the chosen path will actually use is loaded. The halves read the
        # executor's own `specs.jsonl` and `stages.jsonl`; the legacy path reads the
        # `decisions.jsonl` each model wrote for itself. Loading both would mean a campaign
        # recorded before `specs`/`stages` provenance existed could not be replayed even
        # under `--control legacy`, which is the one path that needs nothing from them.
        if spec.control == "roles":
            spec_records, stage_records = (
                _replay_role_records(replay_from) if replay_from else (None, None))
            policy = build_roles(model, spec, guard, None, specifier, planner,
                                 spec_records, stage_records, profile)
        else:
            policy = build_policy(model, spec, guard,
                                  _replay_records(replay_from) if replay_from else None,
                                  profile)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        # A model that cannot be constructed is an operator error, not a crash: report it
        # the way preflight reports a missing binary. `--model replay` used to raise
        # TypeError from a positional argument nobody had a flag for.
        log.error("cannot build control model %s: %s", model, exc)
        return 1
    # Which reasoner actually ran has to be in the log, not inferable from it. A model-B
    # campaign that degraded to its fallback and one that deliberately ran the rehearsal
    # stand-in both report zero LLM calls; on the sibling example's job 23219379 that
    # ambiguity let 144 degraded turns read as a frontier-model result for a full day.
    # Which reasoner actually ran, and under which control vocabulary. Both halves are named
    # even when they come from one model, because "model B" and "B's specifier with D's
    # planner" produce different campaigns and a log that cannot tell them apart is how a
    # degraded arm gets read as a frontier-model result.
    for letter in dict.fromkeys([specifier or model, planner or model]):
        _m = reasoners.MODELS[letter]
        log.info("control model %s (%s): %s, %s llm shape, status=%s",
                 _m.letter, _m.name, _m.mode, _m.llm_shape, _m.status)
        if _m.note:
            log.info("control model %s caveat: %s", _m.letter, _m.note)
    log.info("control vocabulary: %s%s", spec.control,
             f" (specifier={specifier or model}, planner={planner or model})"
             if spec.control == "roles" else "")
    reg = Registry().load()
    log.info("registry: %d tools (%s)%s", len(reg.ids()), ", ".join(reg.ids()),
             f" ERRORS: {reg.errors}" if reg.errors else "")
    mgr = CampaignManager(spec, policy, reg)
    mgr.prov_sink = _prov_heartbeat
    if heartbeat_s is None:
        heartbeat_s = float(os.environ.get("IMPRESS_A_HEARTBEAT_S", "60") or 0)
    log.info("campaign %s: model=%s backend=%s root=%s stages=%s replicas=%d",
             spec.campaign_id, label, spec.backend, mgr.root,
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
                out = subprocess.run([sys.executable, str(shim), mpnn, "--help"],
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

    # `--batch_size` is new, and A3's lesson is that a tool's contract was not merely
    # unverified but WRONG: RFD3 was invoked with `--config`/`--out`, flags its real Hydra CLI
    # does not have, and that survived review because nobody had run it. So the flag is checked
    # against the installed `run.py --help` rather than trusted.
    mpnn_dir = os.environ.get("MPNN_DIR")
    if stages and "ligandmpnn_design" in stages and mpnn_dir:
        run_py = Path(mpnn_dir) / "run.py"
        if run_py.is_file():
            try:
                helped = subprocess.run(
                    [sys.executable, str(run_py), "--help"], capture_output=True, text=True,
                    timeout=300, cwd=mpnn_dir)
                helptext = helped.stdout + helped.stderr
                missing = [f for f in ("--batch_size", "--number_of_batches")
                           if f not in helptext]
                if not helptext.strip():
                    checks.append(("ligandmpnn batch flags", None,
                                   "`run.py --help` produced no output - undetermined"))
                elif missing:
                    checks.append(("ligandmpnn batch flags", False,
                                   f"installed run.py does not offer {', '.join(missing)} - "
                                   f"the adapter passes them and would fail inside the job"))
                else:
                    checks.append(("ligandmpnn batch flags", True,
                                   "--batch_size and --number_of_batches both offered"))
            except subprocess.TimeoutExpired:
                checks.append(("ligandmpnn batch flags", None,
                               "`run.py --help` did not answer in 300s - undetermined"))
            except (OSError, subprocess.SubprocessError) as e:
                checks.append(("ligandmpnn batch flags", False, f"could not check: {e}"))

    # The `impress` dependency is published on no index, so if pip ever went looking for that
    # name it installed something else - and the failure is silent, because the import succeeds
    # and hands back a working module that is simply not ours. Both installers put the root
    # editable install first to prevent that; this proves the result on the machine that will
    # run the campaign. Deterministic either way, so never undetermined.
    # `find_spec`, not `import`: this resolves the name without executing the module, so
    # preflight stays cheap and the import surface for the root package stays at exactly the two
    # modules `tests/test_layering.py` allows. Checking where a dependency resolves to does not
    # require depending on it.
    try:
        import importlib.util

        import impress_a as _ia
        found = importlib.util.find_spec("impress")
        origin = Path(found.origin).resolve() if found and found.origin else None
        want = Path(_ia.__file__).resolve().parents[3] / "src" / "impress" / "__init__.py"
        if origin is None:
            checks.append(("impress package", False,
                           "not installed - run scripts/dev_setup.sh (or step 3 of "
                           "scripts/delta_env_setup.sh), which installs it from the root"))
        else:
            checks.append(("impress package", origin == want,
                           f"{origin}" if origin == want else
                           f"resolved to {origin}, not {want} - a package of that name came "
                           f"from an index; `pip uninstall impress` and re-run "
                           f"scripts/dev_setup.sh"))
    except (ImportError, ValueError) as e:
        checks.append(("impress package", False, f"could not resolve: {e!r}"))

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
    # The two halves. `--model X` takes both from one row, which keeps a four-arm comparison
    # one-variable; naming them separately takes one from each, which is what makes it
    # measurable whether specification or planning is where a model earns its cost. Either
    # form implies `--control roles`, because a Specifier has nowhere to run in the legacy
    # single-`decide` path.
    r.add_argument("--specifier", default=None, choices=sorted(POLICIES),
                   help="Specifier half (implies --control roles)")
    r.add_argument("--planner", default=None, choices=sorted(POLICIES),
                   help="Planner half (implies --control roles)")
    r.add_argument("--control", default=None, choices=("legacy", "roles"),
                   help="control vocabulary (default: the campaign spec's, which is legacy)")
    r.add_argument("--no-guard", action="store_true")
    r.add_argument("--heartbeat", type=float, default=None, metavar="SECONDS",
                   help="liveness log cadence (default $IMPRESS_A_HEARTBEAT_S or 60; "
                        "0 disables). Only visible once logging is configured - see "
                        "scripts/delta_run_campaign.py")
    r.add_argument("--replay-from", default=None, metavar="DIR",
                   help="provenance directory to replay (--model replay only)")
    r.add_argument("--model-profile", default=None, metavar="NAME",
                   help="models.yaml profile naming a live endpoint (--model B). Omitted, B "
                        "runs the deterministic rehearsal and `impress-a models` says so")
    t = sub.add_parser("tools", help="list registered tools")
    t.add_argument("--toolkits", default=None)
    sub.add_parser("models", help="list the control models and their status")
    pf = sub.add_parser("preflight",
                        help="check the real-toolkit environment before submitting")
    pf.add_argument("spec", nargs="?", default=None)
    sv = sub.add_parser("serve", help="run the execution process and serve it over HTTP")
    sv.add_argument("spec")
    sv.add_argument("--model", default=None, choices=sorted(POLICIES),
                    help="attach a reasoner IN this process, so an external caller steers it "
                         "here (`--model C`). Omitted, the campaign is served with no "
                         "reasoner for `impress-a control` to attach to")
    sv.add_argument("--no-guard", action="store_true")
    sv.add_argument("--model-profile", default=None, metavar="NAME",
                    help="models.yaml profile naming a live endpoint (--model B)")
    sv.add_argument("--caller-timeout", type=float, default=None, metavar="SECONDS",
                    help="how long each half waits for an external directive (--model C). "
                         "The default suits a scripted sidecar; raise it for a person")
    sv.add_argument("--host", default="127.0.0.1",
                    help="loopback by default: the plane has no auth and no TLS, and both "
                         "ends belong on the same compute node (backlog C7)")
    sv.add_argument("--port", type=int, default=0)
    sv.add_argument("--heartbeat", type=float, default=None, metavar="SECONDS")
    ct = sub.add_parser("control", help="run the Spec and Planning loops against a served "
                                        "campaign")
    ct.add_argument("--connect", required=True, metavar="URL")
    ct.add_argument("--campaign", required=True, metavar="ID")
    ct.add_argument("--model", default="D", choices=sorted(POLICIES))
    ct.add_argument("--specifier", default=None, choices=sorted(POLICIES))
    ct.add_argument("--planner", default=None, choices=sorted(POLICIES))
    ct.add_argument("--no-guard", action="store_true")
    ct.add_argument("--model-profile", default=None, metavar="NAME",
                    help="models.yaml profile naming a live endpoint (--model B)")
    tr = sub.add_parser("trust", help="grant, list or withdraw trust for a campaign's patterns")
    tr.add_argument("spec", nargs="?", default=None)
    tr.add_argument("--assert", dest="do_assert", action="store_true",
                    help="grant trust to the patterns this campaign composes")
    tr.add_argument("--revoke", default=None, metavar="SIGNATURE")
    tr.add_argument("--reason", default="",
                    help="why (required for --assert; it is the record)")
    tr.add_argument("--replicas", type=int, action="append", default=None, metavar="N",
                    help="replica width to assert at, repeatable. The signature includes "
                         "replica multiplicity, so width 1 does not cover width 4 "
                         "(backlog A10). Default: the campaign's own `replicas`")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return asyncio.run(run_campaign(a.spec, a.model, not a.no_guard,
                                        a.heartbeat, a.replay_from,
                                        control=a.control, specifier=a.specifier,
                                        planner=a.planner, profile=a.model_profile))
    if a.cmd == "models":
        return print_models()
    if a.cmd == "serve":
        return asyncio.run(serve_campaign(a.spec, a.host, a.port, a.heartbeat,
                                          a.model, not a.no_guard, a.model_profile,
                                          a.caller_timeout))
    if a.cmd == "control":
        return asyncio.run(control_campaign(a.connect, a.campaign, a.model,
                                            a.specifier, a.planner, not a.no_guard,
                                            a.model_profile))
    if a.cmd == "trust":
        widths = a.replicas
        if widths is None:
            widths = [max(1, load_spec(a.spec).replicas)] if a.spec else [1]
        return trust(a.spec, a.do_assert, a.revoke, a.reason, widths)
    if a.cmd == "preflight":
        return preflight(load_spec(a.spec) if a.spec else None)
    reg = Registry().load(a.toolkits)
    for tid in reg.ids():
        s = reg.get(tid)
        print(f"  {tid:16s} {s.pattern.value}  {s.toolkit:8s} gates={len(s.qc_gates)}")
    if reg.errors:
        print("  errors:", reg.errors)
    return 0
