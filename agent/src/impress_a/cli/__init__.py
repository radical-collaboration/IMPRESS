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
from ..policy.wrappers import StageGuard
from ..runtime.roles import RolesDriver
from ..tools.registry import Registry

# Module logger, never configured here: a library that calls basicConfig steals the
# root handler from whoever embedded it. `scripts/delta_run_campaign.py` configures it,
# and everything below is silent by default - including under pytest.
log = logging.getLogger(__name__)

# Derived, not restated. The taxonomy lives in `policy/registry.py` so that it is not a
# CLI detail; this name is kept because `slides/api/run_model.py` reads it to generate the
# deck's model count, and a deck that disagrees with the code is the drift this avoids.
#
# `LETTERS` rather than the old `CLASSES`: a model is no longer a `ControlPolicy` class, so
# there is no class to name. It is two builders, and the letter is what selects them.
POLICIES = reasoners.LETTERS

#: The subcommands `main` registers. Declared once because `slides/api/run_model.py` reads
#: it to generate the deck, and had the list hardcoded - so adding `models` here would
#: otherwise have left the deck claiming three subcommands against the code's four.
#: `tests/test_reasoner_registry.py` asserts the parser accepts every name in it.
SUBCOMMANDS = ("run", "serve", "control", "tools", "models", "preflight",
               "trust", "validate-tasks", "compare", "mock-lab")


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


#: Which real tool each environment check exists for. Every entry names tools, never
#: toolkits, because what a campaign declares is a stage list.
_CHECK_OWNERS: dict[str, tuple[str, ...]] = {
    "$WORK_DIR": ("rfd3_design", "ligandmpnn_design", "packmin", "fastrelax",
                  "filter_shape", "boltz_predict"),
    "$FOUNDRY_SIF_PATH": ("rfd3_design",),
    "$MPNN_DIR": ("ligandmpnn_design",),
    "$BOLTZ_CACHE": ("boltz_predict",),
    "boltz CCD cache": ("boltz_predict",),
    "apptainer": ("rfd3_design",),
    "boltz": ("boltz_predict",),
    "pyrosetta": ("packmin", "fastrelax", "filter_shape"),
    "ml_collections": ("ligandmpnn_design",),
}


def _check_applies(stages: list[str] | None, owners: tuple[str, ...]) -> bool:
    """Does any tool this check exists for appear in the campaign?

    `stages` is `None` when preflight was given no campaign at all, and then every check
    applies: the question there is what this machine can run, not what one spec needs.

    Scoping matters because of the surrogate chain. `campaigns/mock-small-molecule-binding.yaml`
    runs six `toolkit: mock` stand-ins on a laptop and needs no Apptainer image, no LigandMPNN
    checkout, no Boltz weights and no PyRosetta - and before this, preflight reported five
    FAILs against it and then printed "a campaign using mock_rfd3_design, ... needs the
    entries above", which is false. A FAIL the reader cannot act on, under a sentence that is
    wrong, is how the FAIL column stops being read - the same erosion the `warn` column's
    rule guards against.
    """
    return stages is None or any(tool in stages for tool in owners)


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


def build_roles(model: str, spec: CampaignSpec, guard: bool = True,
                records: list[dict[str, Any]] | None = None,
                specifier: str | None = None, planner: str | None = None,
                spec_records: list[dict[str, Any]] | None = None,
                stage_records: list[dict[str, Any]] | None = None,
                profile: str | None = None, caller_timeout_s: float | None = None,
                sink: Any = None):
    """Adapt a `CampaignSpec` into the registry's options, and build the two halves.

    This function is the adapter and nothing more. `policy/registry.py` owns which models
    exist and how each half is built; it cannot do this part itself, because `CampaignSpec`
    lives in `runtime/` and `policy` may import `core` only (ADR 0010, asserted by
    `tests/test_layering.py`). Putting the spec on the other side of that line is what would
    make control models stop being swappable.

    `stages` has to reach the halves or a model falls back to its built-in default, which is
    the mock chain - so a real campaign would validate the real toolkits and then execute
    mocks.

    The guard is `StageGuard` on the planner, and it is narrower than the policy-level
    wrapper it replaces: the replica cap now binds in the executor and a task serving no
    objective is refused by the Reviewer, so what is left to wrap is `forbid_tools` until
    gate 6 takes that over too. `--no-guard` therefore cannot switch off either of the two
    checks that matter, which it never should have been able to.
    """
    # `max_cycles` and `target_front` are forwarded, and the reasoning for once withholding
    # them was half right (backlog X1). Withholding avoided bounding the same thing from two
    # places, which is how an off-by-one went invisible for three Delta jobs. But it left every
    # model carrying `ReasonerOptions.max_cycles`'s default of 6, which does not merely
    # duplicate the campaign's bound - it is TIGHTER than it: a four-hour arm declaring
    # `max_cycles: 200` would have decided six times in about twenty minutes, stopped itself,
    # and reported a clean campaign on 8% of its allocation. That is the worse of the two
    # failures, and the silent one. `target_front` is the same shape with nothing else behind
    # it at all, and 0 keeps the model's own number.
    opts = _options_for(spec, records, spec_records, stage_records, profile,
                        caller_timeout_s, sink)
    pair = reasoners.build_roles(specifier or model, planner or model, opts)
    if guard:
        pair.planner = StageGuard(pair.planner, forbid_tools=("mock_noodle",))
    # Handed back on the pair so the caller can `bind` it to the manager it is about to
    # build. An attribute rather than a `RolePair` field: which sink a pair writes to is a
    # property of how the CLI assembled it, not of the two-half contract that `policy`
    # defines and that `impress-a control` honours across a socket.
    pair.reasoner_sink = opts.sink
    return pair


class ReasonerSink:
    """Where a reasoner's own records go, bound after the manager that will hold them exists.

    Late-bound because of an ordering that is not going to change: the halves are built
    before the `CampaignManager`, since the manager takes the pair as an argument. A sink
    that needed the manager at construction would mean building the halves twice or passing
    a half-built manager, and both are worse than one small indirection.

    **Records before `bind` are counted, not written, and not raised over.** A half built by
    a test, or by `impress-a control` before it has a plane, has nowhere to put a transcript
    row; losing the row is a bad day and taking the campaign down over bookkeeping is a worse
    one. `dropped` is there so a caller can say so rather than discover silence.
    """

    def __init__(self) -> None:
        self._write: Any = None
        self.dropped = 0
        self.written = 0

    def bind(self, manager: Any) -> None:
        self._write = manager.record_reasoning

    def __call__(self, kind: str, record: dict[str, Any]) -> None:
        if self._write is None:
            self.dropped += 1
            return
        self._write(kind, record)
        self.written += 1


def _options_for(spec: CampaignSpec,
                 records: list[dict[str, Any]] | None = None,
                 spec_records: list[dict[str, Any]] | None = None,
                 stage_records: list[dict[str, Any]] | None = None,
                 profile: str | None = None,
                 caller_timeout_s: float | None = None,
                 sink: Any = None) -> reasoners.ReasonerOptions:
    """A `CampaignSpec` as the registry's plain-data options. The whole adapter, named.

    Named so a test can assert what reaches the halves without building them, which is what
    backlog X1 is about: the bound a model carries must not be tighter than the campaign's.

    **One client, two slots, and that is deliberate** (backlog H1's last half). `_client_for`
    is built once and reaches `oracle` - model B's single-call seam - and `reasoner` - model
    A's four per-node calls - because `OpenAICompatOracle` implements `NodeReasoner` and the
    same bounded corrective retry in `policy/reasoning.ask` serves both. No campaign uses both
    slots: a letter picks one shape or the other, so a second client would only be a second
    connection to the same endpoint. Before this, `reasoner` was left `None` and
    `--model-profile` reached model B alone, so `--model A --model-profile X` ran the rule
    cascade and reported no error - the quiet form of the failure the profile was named to
    prevent.
    """
    client = _client_for(profile, spec)
    return reasoners.ReasonerOptions(
        stages=list(spec.stages) or None, records=records,
        spec_records=spec_records, stage_records=stage_records,
        oracle=client, reasoner=client,
        # The subscriber `ReasonerOptions.sink` never had. Every writer existed - the
        # transcript in `reasoning.ask`, `reasoner_degraded`, the external-directive
        # events - and nothing was listening, so a live campaign recorded nothing at all
        # about the model that drove it. `bind` happens in `run_campaign` once the manager
        # is built; see `ReasonerSink`.
        sink=sink if sink is not None else ReasonerSink(),
        timeout_s=caller_timeout_s or reasoners.ReasonerOptions().timeout_s,
        max_cycles=spec.max_cycles,
        replicas=spec.replicas,
        target_front=spec.target_front or reasoners.ReasonerOptions().target_front)


def _client_for(profile: str | None, spec: CampaignSpec) -> Any:
    """The model a live arm talks to, from `--model-profile`.

    Named for the client rather than for model B's slot because it now fills model A's too:
    `OpenAICompatOracle` implements `policy/reasoning.NodeReasoner`, which is the protocol
    model A's four nodes call, so one object serves both shapes and `_options_for` puts it in
    both slots.

    `None` leaves the registry to build `RehearsalOracle` with the campaign's chain, which is
    what `--model B` runs with no profile named - and `impress-a models` reports `llm_calls: 0`
    for exactly that reason. Model A with no profile falls to its rule cascade the same way.
    Loaded here rather than in `policy/` because `policy` may import `core` only and reading a
    YAML file is not `core`'s business either; the same reason `_replay_records` lives here.
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
        # Printed AND written to a file, because the port is ephemeral by default and that is
        # the hardening rather than an inconvenience: a fixed port is guessable, collides with
        # a second `serve` on the same node, and is the one piece of this arrangement an
        # unrelated process could find without looking. A sidecar reads the URL; it is not
        # told a number.
        #
        # 0600, and the directory is the job's own run root. The plane has no auth and no TLS
        # (backlog C7), so loopback plus a URL only the owner can read is the whole boundary -
        # and a token would add nothing against the one threat that remains, another process
        # of the same user, since that process could read the token too.
        url_file = Path(spec.root) / spec.campaign_id / "control_plane.url"
        url_file.parent.mkdir(parents=True, exist_ok=True)
        url_file.write_text(f"{server.base_url}\n")
        url_file.chmod(0o600)
        print(f"campaign {cid} serving on {server.base_url}", flush=True)
        print(f"url written to {url_file}", flush=True)
        log.info("serving campaign %s on %s (liveness timeout %.0fs, url in %s)", cid,
                 server.base_url, spec.control_liveness_timeout_s, url_file)
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
        # `target_front` from the observation, which is the only thing a remote caller has.
        # Dropping it here would make the served arm stop at one design while the in-process
        # arms ran to ten - a difference between arms that is not the model (backlog G11).
        goal = Goal(text=obs.goal, objectives=list(obs.objectives),
                    target_front=obs.target_front)
        pair = _role_pair(model, specifier, planner, list(obs.stages), guard, profile,
                          replicas=obs.replicas)
        log.info("control: driving campaign %s at %s with %s", campaign_id, url, pair.name)
        # The campaign's OWN bounds, from the observation. `max_turns=10_000` was here, and
        # it is not a neutral default: every in-process arm is driven through
        # `spec.max_cycles` by `manager.py`, so a remotely driven arm ran until its budget or
        # its wall clock stopped it while the others stopped at six cycles - the same
        # observation gap as G11's, in the half that says how the campaign is driven rather
        # than what it is for. 0 means the served campaign declared nothing, and then the old
        # numbers stand.
        driver = RolesDriver(goal, pair.specifier, pair.planner,
                             max_turns=obs.max_cycles or 10_000,
                             max_attempts=obs.max_attempts or 4, concurrency=1)
        try:
            await driver.conduct(session)
        except CampaignStopped as stopped:
            log.info("control: campaign ended (%s)", stopped)
        if (sink := getattr(pair, "reasoner_sink", None)) is not None and sink.dropped:
            log.warning(
                "control: %d reasoner record(s) had nowhere to go - this side hosts no "
                "provenance and the plane carries no operation for them, so this arm's "
                "transcript and timing are not on disk anywhere (backlog H8)",
                sink.dropped)
    return 0


def _role_pair(model: str, specifier: str | None, planner: str | None,
               stages: list[str], guard: bool, profile: str | None = None,
               replicas: int = 0):
    """Build the two halves for a remote driver, from the served campaign's own chain.

    `stages` comes from `CampaignObservation.stages` - the campaign's declaration in its own
    order - and not from `toolkit.ids`, which holds the same tools sorted by id. A Planner
    wires each port to the nearest preceding producer, so under alphabetical order
    `mock_design` precedes `mock_generate` and the sequence step would be planned before the
    backbone it consumes.
    """
    client = _client_for(profile, CampaignSpec(campaign_id="", goal="", objectives=[],
                                               stages=list(stages)))
    # Both slots, for the reason `_options_for` gives: a remote driver may be `--model A` as
    # easily as `--model B`, and filling only one would make `--model-profile` silently
    # inert for half the letters it is offered for.
    # A sink here too, and it stays UNBOUND on purpose. The control process drives a
    # campaign it does not host: the executor writing `provenance/` is on the other side of
    # a socket, and there is no plane operation for "append this to your decisions log" -
    # ADR 0007 says an adapter may not carry one the core protocol lacks. So a caller-side
    # half has its records counted and dropped, and `control_campaign` says how many rather
    # than leaving the silence to be read as "the model made no calls" (backlog H8).
    opts = reasoners.ReasonerOptions(
        stages=stages or None, oracle=client, reasoner=client, replicas=replicas,
        sink=ReasonerSink())
    pair = reasoners.build_roles(specifier or model, planner or model, opts)
    if guard:
        pair.planner = StageGuard(pair.planner, forbid_tools=("mock_noodle",))
    pair.reasoner_sink = opts.sink
    return pair


def compare_command(dirs: list[str], control: str = "D", theta: float | None = None,
                    t_cut_h: float | None = None, chain: str | None = None,
                    json_out: str | None = None) -> int:
    """`impress-a compare <dir>...`: the four-arm comparison, scored and reported.

    Exits non-zero when the comparison must not be published - an arm that ran a mock tool,
    an arm that degraded to a fallback, or arms that disagree on the spec, the seed salt or
    the git sha. Those are not caveats for the discussion: each one means the figures measure
    two things at once, and the exit code is what stops a script publishing them anyway.
    """
    import dataclasses

    from ..analysis.compare_arms import T_CUT_H, compare, load_arm, mde

    arms = [load_arm(d) for d in dirs]
    tools = tuple(t.strip() for t in chain.split(",")) if chain else ()
    result = compare(arms, tools, control, theta, t_cut_h or T_CUT_H)

    print(result.report())
    counts = [f.distinct_t2 for f in result.figures]
    if (smallest := mde(counts)) is not None:
        print(f"\n  smallest detectable rate ratio at these counts: {smallest:.2f}x. "
              f"The honest claim is the interval, not the p-value; one allocation per arm "
              f"gives no degrees of freedom for overdispersion.")
    if json_out:
        Path(json_out).write_text(
            json.dumps({"figures": [dataclasses.asdict(f) for f in result.figures],
                        "contrasts": [dataclasses.asdict(c) for c in result.contrasts],
                        "blocked": result.blocked}, indent=2, default=str) + "\n")
        print(f"  figures: {json_out}")
    if not result.publishable:
        print("\n  NOT PUBLISHABLE - see the reasons above")
    return 0 if result.publishable else 1


async def validate_tasks_command(spec_path: str, out: str | None = None) -> int:
    """`impress-a validate-tasks <spec>`: run each Task once and report every check.

    Exits non-zero if any Task fails an **integrity** row, because that is the exit code the
    experiment's step 1 gates on: `impress-a trust --assert` cites this run as its reason, and
    asserting trust on the strength of a run nobody checked would be asserting trust on
    untested Tasks.

    An acceptance row that fails does NOT fail the run. A weak design is not a broken Task
    (decision 0013), and a validation pass that demanded good designs would refuse a working
    chain on its first mediocre draw.
    """
    from ..analysis.validate_tasks import validate_tasks

    spec = load_spec(spec_path)
    if err := _check_ligand_smiles(spec):
        log.error("%s", err)
        return 1
    for var, val in _thread_caps(spec).items():
        os.environ.setdefault(var, val)

    out_dir = Path(out) if out else Path(spec.root) / spec.campaign_id / "validation"
    log.info("validating %d task(s) of %s; writing to %s",
             len(spec.stages), spec.campaign_id, out_dir)
    report = await validate_tasks(spec, Registry().load(), out_dir)

    print(report.table())
    failed = [t.tool for t in report.tasks if not t.ok]
    weak = [t.tool for t in report.tasks if t.ok and any(not r.ok for r in t.rows)]
    print(f"\n  {len(report.tasks) - len(failed)}/{len(report.tasks)} task(s) clean on "
          f"every integrity row")
    if weak:
        print(f"  acceptance rows fell short on: {', '.join(weak)} - a weak design is not a "
              f"broken Task, so this does not fail the run")
    if failed:
        print(f"  FAILED: {', '.join(failed)}")
    print(f"  report: {out_dir / 'validate_tasks.json'}")
    return 0 if report.ok else 1


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


def _replay_role_records(path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """`(specs, stages)` from a recorded campaign, for the two replay halves.

    Two files rather than one, and executor-written rather than reasoner-written - which is
    why the halves can replay a campaign run by a model that kept no notes of its own, where
    `decisions.jsonl` only holds what a model chose to record about itself.

    Read here rather than in the policy layer: a reasoner that touches the filesystem is one
    that can reach past `core`, which is the import contract `tests/test_layering.py`
    asserts.
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
                f"replayed at all - the `decisions.jsonl` path was deleted with "
                f"the `decide` contract in phase 11")
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
                       replay_from: str | None = None,
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
    label = model if not (specifier or planner) else f"{specifier or model}/{planner or model}"
    spec.campaign_id = f"{spec.campaign_id}-{label}"
    try:
        # The replay halves read the executor's own `specs.jsonl` and `stages.jsonl`. The
        # `decisions.jsonl` each model used to write for itself is no longer a replay source:
        # `ReplayPolicy` and the `decide` contract it replayed were deleted in phase 11, and
        # the executor-written records are strictly better anyway - they exist for every model
        # whether or not it kept notes, and a reasoner cannot write a flattering one.
        spec_records, stage_records = (
            _replay_role_records(replay_from) if replay_from else (None, None))
        policy = build_roles(model, spec, guard, None, specifier, planner,
                             spec_records, stage_records, profile)
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
    log.info("halves: specifier=%s planner=%s", specifier or model, planner or model)
    reg = Registry().load()
    log.info("registry: %d tools (%s)%s", len(reg.ids()), ", ".join(reg.ids()),
             f" ERRORS: {reg.errors}" if reg.errors else "")
    mgr = CampaignManager(spec, policy, reg)
    mgr.prov_sink = _prov_heartbeat
    # The halves were built before the manager existed, so their sink has had nowhere to
    # write until now. Everything a reasoner records - its prompts, its replies, the model
    # id that answered, how long each call took and whether it degraded - reaches
    # `provenance/decisions.jsonl` and `provenance/transitions.jsonl` from here.
    if (reasoner_sink := getattr(policy, "reasoner_sink", None)) is not None:
        reasoner_sink.bind(mgr)
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


def preflight(spec: CampaignSpec | None = None, quick: bool = False) -> int:
    """Check a real toolkit's environment BEFORE anything is queued.

    Every real adapter raises on a missing env var - but only once a task is running,
    which on HPC means inside the allocation, after the queue wait. Run this on the
    login node instead.

    `quick` keeps the tier-1 checks - env vars, paths, executables, storage, the registry,
    `ml_collections` - and skips every probe that shells out to import a heavy science stack
    (pyrosetta, and LigandMPNN's import chain and `--help` contract), which together bound at
    1320s. That is the form `scripts/delta_gpu_run.sh` runs inside the allocation before
    Dragon comes up: the question there is whether `$MPNN_DIR` is unset, not whether torch can
    page off Lustre, and the answer has to arrive in seconds. The deep form runs once on a
    login node, where the 900s probe is free and its printed elapsed time is the early warning
    for `ligandmpnn_design`'s declared `walltime_s`.

    A skipped probe is reported as skipped and never as `ok` or as undetermined - `None` means
    a probe ran and reached no conclusion, and letting it also mean "not attempted" is how the
    warn column stops being worth reading.
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
    skipped: list[str] = []
    #: Checks this campaign's stages do not reach. Reported as a count rather than as rows,
    #: because a run of nine `n/a` lines is what the reader would learn to skip past.
    not_applicable: list[str] = []

    def wanted(name: str) -> bool:
        if _check_applies(stages, _CHECK_OWNERS[name]):
            return True
        not_applicable.append(name)
        return False

    if spec is not None and (err := _check_ligand_smiles(spec)):
        checks.append(("ligand_smiles", False, err))

    for var, what in (("WORK_DIR", "every default path, and the rfd3 container bind"),
                      ("FOUNDRY_SIF_PATH", "rfd3_design (Apptainer image)"),
                      ("MPNN_DIR", "ligandmpnn_design (checkout + checkpoints)"),
                      ("BOLTZ_CACHE", "boltz_predict (pre-warmed weights)")):
        if not wanted(f"${var}"):
            continue
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
    if (cache := os.environ.get("BOLTZ_CACHE")) and wanted("boltz CCD cache"):
        marked = (Path(cache) / ".mols_complete").exists()
        checks.append(("boltz CCD cache", marked,
                       "extraction proven complete" if marked else
                       "no .mols_complete marker - re-run scripts/delta_env_setup.sh "
                       "step 11 HERE, where there is still internet to repair it"))

    for exe, what in (("apptainer", "rfd3_design"), ("boltz", "boltz_predict")):
        if not wanted(exe):
            continue
        found = shutil.which(exe)
        checks.append((exe, bool(found), found or f"not on PATH - needed by {what}"))

    # Tier 2. PyRosetta in a subprocess: importing it here would initialise a process-global
    # singleton in the very interpreter that has to stay clean for P2 fan-out.
    if not _check_applies(stages, _CHECK_OWNERS["pyrosetta"]):
        not_applicable.append("pyrosetta")
    elif quick:
        skipped.append("pyrosetta")
    else:
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
    if wanted("ml_collections"):
        try:
            out = subprocess.run([sys.executable, "-c", "import ml_collections"],
                                 capture_output=True, timeout=60, check=False)
            checks.append(("ml_collections", out.returncode == 0,
                           "importable - LigandMPNN's openfold needs it"
                           if out.returncode == 0
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
    deep = (stages is None or "ligandmpnn_design" in stages) and not quick
    if quick and os.environ.get("MPNN_DIR"):
        skipped.append("ligandmpnn imports")
    # `--batch_size` is new, and A3's lesson is that a tool's contract was not merely
    # unverified but WRONG: RFD3 was invoked with `--config`/`--out`, flags its real Hydra CLI
    # does not have, and that survived review because nobody had run it. So the flags are
    # checked against the installed `run.py --help` rather than trusted.
    #
    # ONE invocation, two checks, and THROUGH THE SHIM - which is the whole of what went wrong
    # before. The flags probe ran `run.py` directly while this probe ran it through
    # `MPNN_SHIM`, so the two disagreed about the same binary: the shim exits 0 in 15s and the
    # raw call dies in its vendored openfold on `np.int`, removed in numpy 1.24. That is the
    # documented reason the shim exists and the adapter never calls run.py directly, so a probe
    # that bypasses it is not probing what runs. The traceback then went to stderr, `helptext`
    # was non-empty, and the probe concluded "installed run.py does not offer --batch_size,
    # --number_of_batches - the adapter passes them and would fail inside the job". Both flags
    # are declared (`run.py:846,852`). So a FAIL that blocks the smoke, naming the wrong
    # component, from a probe whose neighbour three lines up had already passed - A4's lesson
    # arriving from inside the tool meant to prevent it.
    #
    # A non-zero exit is now UNDETERMINED rather than a missing flag: a program that did not
    # reach its argument parser has said nothing about its arguments. `None` is for a probe
    # that ran and reached no conclusion, which is exactly this.
    mpnn_flags = ("--batch_size", "--number_of_batches")
    want_flags = bool(stages) and "ligandmpnn_design" in (stages or ()) \
        and bool(os.environ.get("MPNN_DIR"))
    if quick and want_flags:
        skipped.append("ligandmpnn batch flags")
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
            if want_flags:
                helptext = out.stdout.decode(errors="replace") + \
                    out.stderr.decode(errors="replace")
                missing = [f for f in mpnn_flags if f not in helptext]
                if not ok:
                    checks.append(("ligandmpnn batch flags", None,
                                   "run.py never reached its argument parser - undetermined; "
                                   "see the import row above, which is the same invocation"))
                elif missing:
                    checks.append(("ligandmpnn batch flags", False,
                                   f"installed run.py does not offer {', '.join(missing)} - "
                                   f"the adapter passes them and would fail inside the job"))
                else:
                    checks.append(("ligandmpnn batch flags", True,
                                   "--batch_size and --number_of_batches both offered"))
        except subprocess.TimeoutExpired:
            undetermined = ("no result in 900s - undetermined, NOT a pass; a loaded "
                            "Lustre mount can do this. Re-run before submitting")
            checks.append(("ligandmpnn imports", None, undetermined))
            if want_flags:
                checks.append(("ligandmpnn batch flags", None, undetermined))
        except (OSError, subprocess.SubprocessError) as e:
            checks.append(("ligandmpnn imports", False, f"could not check: {e}"))
            if want_flags:
                checks.append(("ligandmpnn batch flags", None, f"could not check: {e}"))

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

    print(f"\n  preflight{' (quick)' if quick else ''}\n")
    for name, ok, detail in checks:
        mark = "ok  " if ok else "warn" if ok is None else "FAIL"
        print(f"    [{mark}] {name:20s} {detail}")
    failed = [n for n, ok, _ in checks if ok is False]
    unknown = [n for n, ok, _ in checks if ok is None]
    print(f"\n  {len(checks) - len(failed) - len(unknown)}/{len(checks)} ok"
          + (f", {len(unknown)} undetermined ({', '.join(unknown)})" if unknown else "")
          + (f" - missing: {', '.join(failed)}" if failed else ""))
    if skipped:
        print(f"  {len(skipped)} skipped by --quick ({', '.join(skipped)})"
              f" - not checked here, and NOT a pass; run the deep form on a login node")
    if not_applicable:
        print(f"  {len(not_applicable)} n/a for these stages ({', '.join(not_applicable)})"
              f" - no stage of this campaign uses them")
    if stages:
        # Scoped, not universal: with a spec the rows above are this campaign's
        # requirements, and `n/a` above says which ones it does not have. Without a spec
        # every check runs and the question is what this machine can do.
        print(f"  (scoped to this campaign's stages: {', '.join(stages)})")
    return 1 if failed else 0


def _parser() -> argparse.ArgumentParser:
    """The command line, built apart from `main` so it can be parsed without being run.

    Two committed documents spell out the Delta procedure as shell, and a flag that argparse
    refuses turns a documented step into exit code 2 at the point where an allocation is
    already held. `test_documented_command_lines_parse` walks those documents through this
    parser, which it can only do if building it executes nothing.
    """
    ap = argparse.ArgumentParser(prog="impress-a")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a campaign")
    r.add_argument("spec")
    r.add_argument("--model", default="D", choices=sorted(POLICIES))
    # The two halves. `--model X` takes both from one row, which keeps a four-arm comparison
    # one-variable; naming them separately takes one from each, which is what makes it
    # measurable whether specification or planning is where a model earns its cost.
    #
    # `--control` is gone (phase 11). It chose between the `decide` vocabulary and the role
    # one, and there is only one now.
    r.add_argument("--specifier", default=None, choices=sorted(POLICIES),
                   help="Specifier half, when it should come from a different model")
    r.add_argument("--planner", default=None, choices=sorted(POLICIES),
                   help="Planner half, when it should come from a different model")
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
    pf.add_argument("--quick", action="store_true",
                    help="tier-1 checks only - skip the pyrosetta and LigandMPNN import "
                         "probes, which bound at 1320s together. What the Delta launcher runs "
                         "inside the allocation before Dragon comes up")
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
    cp = sub.add_parser("compare",
                        help="score several arms of one experiment against the control")
    cp.add_argument("dirs", nargs="+", metavar="DIR",
                    help="one campaign run directory per arm")
    cp.add_argument("--control", default="D",
                    help="the model every other arm's cost is justified against")
    cp.add_argument("--theta", type=float, default=None, metavar="F",
                    help="amino-acid identity above which two designs are one cluster "
                         "(default: the pre-registered 0.90)")
    cp.add_argument("--t-cut", type=float, default=None, metavar="HOURS",
                    help="the common scoring window, from each arm's FIRST TASK START")
    cp.add_argument("--chain", default=None, metavar="T1,T2,...",
                    help="tools a complete design must have run; a lineage missing one "
                         "cannot reach T1 on the gates of the stages it did run")
    cp.add_argument("--json", default=None, metavar="FILE",
                    help="also write every figure as JSON")
    vt = sub.add_parser("validate-tasks",
                        help="execute each Task in a campaign's chain once and check it")
    vt.add_argument("spec")
    vt.add_argument("--out", default=None, metavar="DIR",
                    help="where to write validate_tasks.json and the per-Task table "
                         "(default: <root>/<campaign>/validation)")
    ml = sub.add_parser("mock-lab",
                        help="run the mock chain across a knob grid and draw the figures")
    ml.add_argument("--out", default="campaigns/_runs/_analysis", metavar="DIR",
                    help="where the run directories, tables and figures go "
                         "(default: under the gitignored campaign run root)")
    ml.add_argument("--stage", default="all",
                    choices=("all", "sweep", "collect", "figures"),
                    help="run one stage only; `collect` and `figures` re-read an existing "
                         "lab, so a figure can be fixed without re-running 90 campaigns")
    ml.add_argument("--repeats", type=int, default=3, metavar="N",
                    help="independent seed salts per sweep point. The arms are never "
                         "repeated: they are what the activity runs by hand")
    ml.add_argument("--only", action="append", default=None, metavar="NAME",
                    help="`arms`, `sweeps`, an arm name or a knob name; repeatable")
    ml.add_argument("--model", default="",
                    help="drive every cell with this one reasoner (default: D). "
                         "`--reasoners` is the axis; this is the single-model shorthand")
    ml.add_argument("--reasoners", action="append", default=None, metavar="LETTER",
                    help="a control model to put on the axis, repeatable: D, null, A, B. "
                         "The four knob arms are run under each. A and B make LLM calls "
                         "and are REFUSED without --model-profile, because without one "
                         "they run their rule cascades and report zero calls - which is "
                         "what a degraded live arm reports too")
    ml.add_argument("--model-profile", dest="profile", default="", metavar="NAME",
                    help="a models.yaml profile for the live reasoners (e.g. beam)")
    ml.add_argument("--reasoner-repeats", type=int, default=3, metavar="N",
                    help="runs per live cell. A model at temperature 0 is still not a "
                         "function, so one draw of a live arm is an anecdote")
    ml.add_argument("--max-llm-calls", type=int, default=400, metavar="N",
                    help="stop launching live cells once this many calls have been "
                         "recorded. Counted from what each cell actually made, not "
                         "estimated; skipped cells are named in the manifest")
    ml.add_argument("--jobs", type=int, default=4, metavar="N",
                    help="sweep cells at a time. The four arms always run one at a time, "
                         "because every wall-clock figure comes from them")
    ml.add_argument("--base-spec", default=None, metavar="FILE",
                    help="the campaign each cell overrides (default: "
                         "campaigns/mock-small-molecule-binding.yaml)")
    tr = sub.add_parser("trust", help="grant, list or withdraw trust for a campaign's patterns")
    tr.add_argument("spec", nargs="?", default=None)
    tr.add_argument("--assert", dest="do_assert", action="store_true",
                    help="grant trust to the patterns this campaign composes")
    tr.add_argument("--list", dest="do_list", action="store_true",
                    help="list what this site knows. The listing is printed either way; the "
                         "flag exists so the documented procedure runs verbatim")
    tr.add_argument("--revoke", default=None, metavar="SIGNATURE")
    tr.add_argument("--reason", default="",
                    help="why (required for --assert; it is the record)")
    tr.add_argument("--replicas", type=int, action="append", default=None, metavar="N",
                    help="replica width to assert at, repeatable. The signature includes "
                         "replica multiplicity, so width 1 does not cover width 4 "
                         "(backlog A10). Default: EVERY width from 1 to the campaign's own "
                         "`replicas`, because a width nobody asserted runs under the "
                         "untrusted interlock (backlog G13)")
    return ap


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    if a.cmd == "run":
        return asyncio.run(run_campaign(a.spec, a.model, not a.no_guard,
                                        a.heartbeat, a.replay_from,
                                        specifier=a.specifier, planner=a.planner,
                                        profile=a.model_profile))
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
    if a.cmd == "compare":
        return compare_command(a.dirs, a.control, a.theta, a.t_cut, a.chain, a.json)
    if a.cmd == "mock-lab":
        # Imported here rather than at module scope: the figures stage pulls in matplotlib,
        # which is an optional extra, and `impress-a run` must not need it.
        from ..analysis.mock_lab import BASE_SPEC
        from ..analysis.mock_lab import main as mock_lab_main
        return mock_lab_main(a.out, a.stage, a.repeats, a.only, a.model, a.jobs,
                             a.base_spec or BASE_SPEC, a.reasoners, a.profile,
                             a.reasoner_repeats, a.max_llm_calls)
    if a.cmd == "validate-tasks":
        return asyncio.run(validate_tasks_command(a.spec, a.out))
    if a.cmd == "trust":
        widths = a.replicas
        if widths is None:
            # EVERY width an arm of this campaign can compose, not just the declared one.
            # Replica multiplicity is part of the pattern signature, so a width nobody
            # asserted runs under forced dry-run and a 10% cost cap - and on array 23680876
            # that is exactly what happened to the control arm, which composed 2 against a
            # campaign declaring 4 and spent three cycles untrusted while the other three
            # arms ran trusted throughout (backlog G13). A planner reduced to one lineage by
            # a refinement, or a model naming a narrower draw, lands in the same hole.
            # Asserting the whole range costs one composed graph per width and nothing else.
            declared = max(1, load_spec(a.spec).replicas) if a.spec else 1
            widths = list(range(1, declared + 1))
        return trust(a.spec, a.do_assert, a.revoke, a.reason, widths)
    if a.cmd == "preflight":
        return preflight(load_spec(a.spec) if a.spec else None, a.quick)
    reg = Registry().load(a.toolkits)
    for tid in reg.ids():
        s = reg.get(tid)
        print(f"  {tid:16s} {s.pattern.value}  {s.toolkit:8s} gates={len(s.qc_gates)}")
    if reg.errors:
        print("  errors:", reg.errors)
    return 0
