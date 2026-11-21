"""Surrogate task agents for this project's own tools.

A laptop stand-in for the design chain `liganchor_propose -> rfd3_steered_design ->
preorg_score -> affdelta_score` and the two label chains `md_label` and `abfe_label`, with the
science replaced by seeded draws. `toolkits/mock/SKILL.md` holds the convention and the gate-6
reasoning; this module holds the draws.

**What is faithful, and what is not.** The ports, patterns, parameter names, metric names and
QC gates are the real specs', so a twin that populates them proves the interface. What
produces each number is a hash of the parameters. These tools model no chemistry.

**Where this came from (episode H9 of the re-homing, 2026-11-21).** It was
`asteer.impress.mock_asd`, and its header used to end *"imports `impress_a` deliberately, and
is the only part of `asteer` that may -- a twin is a `TaskAgent`, and `TaskAgent` is theirs."*
That sentence was the argument for its own move and nobody read it as one: a module whose only
justification is that it is allowed to import another repo belongs in that repo. The six specs
merged into `toolkits/mock/` in the same commit, which retires the `toolkits/mock_asd/`
directory and the field-vs-directory split that existed only because they lived outside this
checkout.

**A separate module from `mock_smb_agents.py`, against this plan's own table, and `_rng` is
why.** The plan called that an *exact* merge. Measured: `mock_agents._rng`, which
`mock_smb_agents` imports, is `sha256(str(parts))[:8]` -- a 32-bit seed -- and this module's is
`sha256(repr(key))[:16]`, 64 bits, off a different repr. **Same name, same job, different
draws.** Concatenating the two modules would have silently rebound one to the other and moved
every twin's numbers, with every test that asserts a value failing for a reason no message
would name. The two live side by side instead, each with its own `_rng`, which is what they
already were.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

from ._subprocess import input_path
from .agent import TaskAgent, TaskRequest
from .asteer_design_agents import MODEL_B, MODEL_C

# Imported rather than redefined as of H9. This module carried its own copy with a docstring
# explaining that "a private cross-repo import would buy nothing and couple the module to a
# name upstream is free to rename" -- correct while the two were in different repos, and moot
# now that they are in one package, two files apart. `_rng` is NOT shared, for the reason in
# the header.
from .mock_smb_agents import _clamp

__all__ = [
    "MockABFELabelAgent",
    "MockAffDeltaScoreAgent",
    "MockLigAnchorProposeAgent",
    "MockMDLabelAgent",
    "MockPreorgScoreAgent",
    "MockRFD3SteeredDesignAgent",
]


def _rng(key: tuple[Any, ...]) -> random.Random:
    """A generator seeded by the request, so a twin is deterministic per node.

    Seeded from a digest of the key rather than `hash()`, which is salted per process: two
    runs of the same campaign would otherwise disagree, and a twin whose draws move between
    runs cannot be the thing a regression test compares against.
    """
    digest = hashlib.sha256(repr(key).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


class MockLigAnchorProposeAgent(TaskAgent):
    """Model A's twin: a ligand becomes an anchor spec on the CFG channel.

    **It builds a real `AnchorSpec` and calls `as_artifact()`**, so the twin cannot emit a
    payload shape or a metric definition the real emitter would not. What it fakes is the
    chemistry: atom names are synthetic and the donor/acceptor assignment is a seeded draw,
    where the real tool reads both out of a Rosetta params file.

    **Its metric definition was wrong and is corrected here (EI.8).** The twin previously
    documented `anchor_entropy` as *falling* as the anchor set widened -- "a wider anchor set is
    a more specific instruction" -- computed from the gap between atoms asked for and atoms
    engaged. The real emitter defines it as the normalised Shannon entropy of the anchoring
    WEIGHTS, which is the quantity Model A's trained selection can be compared on, and which
    rises as a set becomes evenly spread. The two measured different things under one name. This
    is the twin convention working as intended: the twin fixed the interface early and guessed
    one of its semantics, and the real tool is what settles it.

    The `cfg_channel: false` arm is gone with it. Item 2's answer is the CFG channel **plus**
    motif placement, never motif placement alone, so that branch had no consumer -- and motif
    placement itself belongs to EI.9, which is the layer that can verify how it reaches RFD3.
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        from .asteer_design_agents import AnchorSpec  # noqa: PLC0415

        r = _rng((self.spec.id, sorted(params.items()), req.node_id))
        asked = max(1, int(params.get("max_anchor_atoms", 6)))
        # Not every requested atom is engageable on a real ligand, so the twin keeps the
        # distinction the real tool has: `n_engaged_atoms <= max_anchor_atoms`.
        engaged = max(1, asked - r.choice([0, 0, 0, 1]))
        keys = [k.strip() for k in str(params.get("cfg_feature_keys") or "").split(",")
                if k.strip()] or ["active_donor", "active_acceptor", "ref_atomwise_rasa"]
        donor_key, acceptor_key, rasa_key = keys[0], keys[1], keys[2]

        names = tuple(f"O{i + 1}" for i in range(engaged))
        buried = float(params.get("buried_target_rasa", 0.15))
        exposed = float(params.get("exposed_target_rasa", 0.45))
        spec = AnchorSpec(
            resname=str(params.get("ligand_resname") or "A:R"),
            engaged_atoms=names,
            features={
                # Every engaged atom is an acceptor and some are also donors, which is the
                # shape the real ligand has: on ALR.params the graph finds ten acceptors and
                # exactly one donor.
                donor_key: {n: float(r.choice([0.0, 0.0, 0.0, 1.0])) for n in names},
                acceptor_key: {n: 1.0 for n in names},
                rasa_key: {n: round(r.uniform(buried, exposed), 4) for n in names},
            },
            cfg_scale=float(params.get("cfg_scale", 1.5)),
            cfg_t_max=float(params.get("cfg_t_max", 1.0)),
            feature_keys=(donor_key, acceptor_key, rasa_key),
        )
        return {
            "result": self.spec.id,
            "count": 1,
            "outputs": {"anchor_spec": spec.as_artifact()},
            "metrics": {
                "n_engaged_atoms": float(spec.n_engaged_atoms),
                "anchor_entropy": spec.anchor_entropy,
            },
        }


class MockMDLabelAgent(TaskAgent):
    """Twin of `md_label`: apo + holo MD, and a dial that breaks the instrument.

    **It checks the root input, exactly as the real adapter does.** `md_label` is a root -- the
    complex arrives as the `design_dir` parameter -- and `compose/validate.py:79`-`:81` is a
    literal `pass` for an unsatisfied root input. A twin that accepted an empty `design_dir`
    would make the mock chain pass where the real one refuses, which is the one way a twin can
    be actively harmful: it would certify a campaign that cannot run.

    `instability` is the surrogate's own dial. At 0.0 the run equilibrates and the integrity gate
    passes; above ~0.6 `rmsd_plateau_frac` falls under its 0.5 floor, which demotes the pattern's
    trust rather than failing the design. Watching that difference is the point of having a dial.
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        from .asteer_labels_agents import _require_design_dir  # noqa: PLC0415

        _require_design_dir(self.spec.id, params)
        r = _rng((self.spec.id, sorted(params.items()), req.node_id))
        instability = float(params.get("instability", 0.0))
        ns = float(params.get("apo_ns", 15.0)) + float(params.get("holo_ns", 15.0))

        # More sampling settles the trajectory; `instability` takes it away. 0.85 at the defaults,
        # under the 0.5 integrity floor from about 0.6.
        plateau = max(0.0, min(0.98, 0.85 + 0.10 * (ns - 30.0) / 70.0 - 0.60 * instability
                               + r.uniform(-0.02, 0.02)))
        return {
            "result": "md_label",
            "count": 1,
            "outputs": {
                "trajectory": f"traj[{ns:.0f}ns]",
                # The equilibrated holo frame. Its presence is what lets the two-stage chain type
                # at all, so the twin must produce it or the mock chain stops being the real
                # chain's shape.
                "structure": f"holo_frame[{params.get('design_dir', '?')}]",
            },
            "metrics": {
                "preorg_rmsd": round(0.8 + 1.6 * instability + r.uniform(-0.05, 0.05), 3),
                "rotamer_entropy": round(2.4 - 0.8 * instability + r.uniform(-0.1, 0.1), 3),
                "ligand_rmsf": round(0.6 + 1.1 * instability + r.uniform(-0.04, 0.04), 3),
                "rmsd_plateau_frac": round(plateau, 3),
                "energy_drift_kcal_per_ns": round(0.3 + 5.0 * instability, 3),
            },
        }


class MockABFELabelAgent(TaskAgent):
    """Twin of `abfe_label`: ATM alchemical transfer, driven by a real parameter.

    No surrogate dial here, deliberately: `n_lambda_windows` is a **real** parameter and already
    moves the verdict, so dropping it toward 8 puts `min_window_overlap` under its 0.1 floor. The
    honest lab condition is the mistake an operator actually makes, and a second invented knob
    beside it would only be a way to reach the same failure without learning anything.

    **`dg_abfe` is the metric name, not the property name.** The bridge ingests it as
    `dg_corrected`, which is what Model C's prediction carries and therefore what supersession
    matches on (item 36). This twin reports the metric; nothing here ingests anything.
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        from .asteer_labels_agents import _require_structure  # noqa: PLC0415

        # A root under L1 even though the spec declares a port, so the twin refuses exactly as
        # the real adapter does. A twin that accepted an empty structure would certify a label
        # campaign that cannot run -- which is the one way a twin is worse than no twin.
        _require_structure(self.spec.id, req, params)
        r = _rng((self.spec.id, sorted(params.items()), req.node_id))
        windows = int(params.get("n_lambda_windows", 22))
        ns = float(params.get("ns_per_window", 2.0))

        # Overlap is what too few windows destroys: 0.34 at 22 windows, under the 0.1 floor by 10.
        overlap = max(0.0, min(0.9, 0.02 * (windows - 6) + 0.03 * (ns - 2.0)
                               + r.uniform(-0.01, 0.01)))
        # A plausible-looking binding free energy. Deliberately NOT correlated with overlap: a
        # broken run reporting an implausible number would be a kinder failure than the one this
        # models, which is a broken run reporting an ordinary one.
        dg = round(-9.5 + r.uniform(-1.5, 1.5), 2)
        return {
            "result": "abfe_label",
            "count": 1,
            "outputs": {"measurements": f"metrics[dg={dg}]"},
            "metrics": {
                "dg_abfe": dg,
                "dg_sem": round(0.25 + 0.6 * max(0.0, 0.3 - overlap), 3),
                "n_lambda": float(windows),
                "min_window_overlap": round(overlap, 3),
                "cycle_closure_kcal": round(0.2 + 3.0 * max(0.0, 0.2 - overlap), 3),
            },
        }


class _MockScoreAgent(TaskAgent):
    """Shared body for the two stream-client twins.

    **It builds a `SurrogateResponse` and hands it to the real client's own payload builder**,
    rather than assembling a metrics dict directly. That is the point of these two twins: the
    thing being stood in for is not the arithmetic, it is the seam -- so the twin goes through
    `asteer.contracts.surrogate` and `stream_clients._payload`, and therefore cannot report a
    payload shape the real client would not. It also means the contract's own refusal of an
    unversioned response is exercised on the mock chain, not only on the real one.

    What it does *not* do is bind a stream. A twin whose correctness depended on the campaign
    having bound something would be testing the binding, which is the real client's job and
    `tests/test_stream_clients.py`'s subject.
    """

    model_id: str = ""

    def _draw(self, r: random.Random, params: dict[str, Any]
              ) -> tuple[dict[str, float], dict[str, float]]:
        raise NotImplementedError

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        from asteer.contracts.surrogate import SurrogateResponse  # noqa: PLC0415

        from .asteer_design_agents import _payload  # noqa: PLC0415

        structure = input_path(req, "structure")
        if not structure:
            raise ValueError(
                f"{self.spec.id}: the `structure` input is wired but empty, so there is "
                "nothing to score -- the same refusal the real client makes."
            )
        r = _rng((self.spec.id, sorted(params.items()), req.node_id))
        values, sigmas = self._draw(r, params)
        response = SurrogateResponse(
            request_id=f"mock-{self.spec.id}",
            model_id=self.model_id,
            # A declared dial, not a constant: it lets a mock campaign move the version and
            # watch attribution follow, which is what M1's CON-5 row is about.
            version=int(params.get("model_version", 0)),
            values=values,
            sigmas=sigmas,
        )
        metrics = dict(values)
        for name, sigma in sigmas.items():
            metrics["sigma_preorg" if name == "preorg_rmsd" else "sigma_dg"] = sigma
        if self.model_id == MODEL_C and "dg_corrected" in values and "dg_corrected" in sigmas:
            metrics["dg_lcb"] = round(
                values["dg_corrected"] + float(params.get("lcb_k", 1.0))
                * sigmas["dg_corrected"], 3)
        return _payload(self.spec.id, response, metrics, structure)


class MockPreorgScoreAgent(_MockScoreAgent):
    """Twin of `preorg_score` -- Model B, the FK potential.

    The dial is `strain`, a mock-only knob: it moves all three quantities together, because
    that is what a badly preorganised pocket does and it is what makes `induced_fit_risk`
    worth deriving rather than reading.
    """

    model_id = MODEL_B

    def _draw(self, r: random.Random, params: dict[str, Any]
              ) -> tuple[dict[str, float], dict[str, float]]:
        strain = float(params.get("strain", 0.3))
        rmsd = round(0.7 + 1.8 * strain + r.uniform(-0.05, 0.05), 3)
        return (
            {
                "preorg_rmsd": rmsd,
                "rotamer_entropy": round(2.5 - 0.9 * strain + r.uniform(-0.1, 0.1), 3),
                "ligand_rmsf": round(0.5 + 1.2 * strain + r.uniform(-0.04, 0.04), 3),
                # Derived, never measured -- decision L2. B reports the judgement; md_label
                # measures the three quantities above and supersedes those.
                "induced_fit_risk": round(min(1.0, 0.15 + 0.8 * strain), 3),
            },
            {"preorg_rmsd": round(0.18 + 0.25 * strain, 3)},
        )


class MockAffDeltaScoreAgent(_MockScoreAgent):
    """Twin of `affdelta_score` -- Model C, the GP posterior.

    `sigma_floor` is the dial that matters and it is the dangerous direction on purpose:
    driving it toward zero is a collapsed posterior, which turns the bound item 14 ranks on
    into a mean. EI.7's `calibration_in_range` is the gate for it, and this twin is how that
    gate gets a payload to refuse without an allocation.
    """

    model_id = MODEL_C

    def _draw(self, r: random.Random, params: dict[str, Any]
              ) -> tuple[dict[str, float], dict[str, float]]:
        dg = round(-9.0 + r.uniform(-2.0, 2.0), 3)
        sigma = round(max(0.0, float(params.get("sigma_floor", 0.6))
                          + r.uniform(-0.05, 0.05)), 3)
        return {"dg_corrected": dg}, {"dg_corrected": sigma}


class MockRFD3SteeredDesignAgent(TaskAgent):
    """Twin of `rfd3_steered_design`: the REAL Tier-1 loop, a fake denoiser and a fake scorer.

    **Only the two injected callables are faked, and that is the whole design.** The FK
    arithmetic, the resampling, the metric folds and the input-spec rendering are the real
    ones from `asteer.fk` and `impress_a.tools.asteer_design_agents` -- so this twin exercises every
    line that runs off-cluster and fakes exactly the part that needs a GPU inside the Foundry
    container. A twin that reimplemented the loop would be testing a second implementation of
    CON-8's arithmetic, which is the thing `asteer.fk` exists to prevent.

    `reward_spread` is the dial that matters: raising it makes the particle rewards unequal,
    which sharpens the weights and lowers ESS. That is how a laptop campaign reaches the
    collapse signal without a GPU, and it is why there is no `force_collapse` flag -- the
    collapse has to come out of the arithmetic or it proves nothing about the arithmetic.
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        import json  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        from .asteer_design_agents import (  # noqa: PLC0415
            SteeringRefused,
            anchor_from,
            default_fk_config,
            mock_tier1_metrics,
            render_input_spec,
            tier1,
        )

        # Through the shared resolver, so the twin reads the port the same way the tool does.
        anchor = anchor_from(req)
        if not anchor:
            # The same refusal the real tool makes. A twin that accepted an unwired anchor
            # would certify a graph that diffuses unconditioned.
            raise SteeringRefused(
                f"{self.spec.id}: the `anchor_spec` input is unwired or empty, and nothing "
                "upstream checks it (compose/validate.py:79-:81). It comes from "
                "liganchor_propose."
            )
        template_path = str(params.get("input_spec_path") or "").strip()
        if not template_path:
            raise SteeringRefused(
                f"{self.spec.id}: no `input_spec_path`. Guided versus unguided is selected by "
                "WHICH file this points at, so it is target identity and must be supplied "
                "even on a laptop -- the rendering is real code here."
            )
        spec, counts = render_input_spec(
            json.loads(Path(template_path).read_text()), anchor,
            partial_t=float(params.get("partial_t", 0.4)),
            buried_threshold=float(params.get("buried_threshold", 0.3)),
            emit_cfg_features=bool(params.get("emit_cfg_features", False)),
            tier=int(params.get("tier", 1)),
        )

        r = _rng((self.spec.id, sorted(params.items()), req.node_id))
        spread = float(params.get("reward_spread", 0.3))
        config = default_fk_config(params)

        def denoise(*, n: int, partial_t: float | None, seeds: Any) -> list[str]:
            # A particle is an opaque handle to the loop, so a string is a complete
            # stand-in. The generation tag makes survivors distinguishable in a test.
            tag = "r0" if partial_t is None else f"t{partial_t:.2f}"
            return [f"{tag}-p{i}" for i in range(n)]

        # A DETERMINISTIC LADDER, NOT A DRAW. The first version scored with
        # `r.gauss(0.5, spread)`, which left whether the population's rewards were unequal
        # enough to resample up to the draw -- and `n_resamples` has an acceptance floor of 1,
        # so a campaign could fail for a reason that says nothing about the chain. At a spread
        # of 1.5 over four particles that was unlikely rather than likely, and it was never
        # observed: it was found while chasing a different failure and is fixed on its own
        # merits. A twin whose metric outcome depends on a draw cannot be the thing a campaign
        # or a regression test runs against.
        #
        # The ladder spreads the rewards evenly across the population and shuffles WHICH
        # particle gets which, so the spread is guaranteed while the winner still varies per
        # node. `reward_spread: 0` collapses it to a flat population, which is the inert arm on
        # demand rather than by accident.
        ladder = [0.5 + spread * (i / max(1, config.n_particles - 1) - 0.5)
                  for i in range(config.n_particles)]
        r.shuffle(ladder)
        served = 0

        def score(particle: Any) -> float:
            nonlocal served
            value = ladder[served % len(ladder)]
            served += 1
            return value

        run = tier1(config, denoise=denoise, score=score,
                    n_restarts=int(params.get("n_restarts", 3)),
                    partial_t=float(params.get("partial_t", 0.4)))
        metrics = mock_tier1_metrics(run, counts)
        # RFD3's own output quality, item 43. The real tool reads it from what the container
        # wrote (`backbone_metrics`); the twin draws it, calibrated to `mock_rfd3_design`.
        metrics.update(mock_backbone_metrics(r, float(params.get("difficulty", 0.25)),
                                             len(run.particles)))
        return {
            "result": self.spec.id,
            "count": len(run.particles),
            "outputs": {"backbone": f"steered[{len(run.particles)}p]"},
            "metrics": metrics,
            # Not a declared output port: carried so a test can assert the rendered spec
            # without re-rendering it, and so a laptop run's provenance shows what would
            # have been handed to RFD3.
            "rendered_input_spec": spec,
        }


def mock_backbone_metrics(r: random.Random, difficulty: float, n: int) -> dict[str, float]:
    """`mock_rfd3_design`'s six backbone metrics, at `mock_rfd3_design`'s calibration.

    **Copied arithmetic, and the parity is the point rather than an accident** (item 43, EI.31).
    `mock_smb_agents.MockRFD3DesignAgent.run` (`:81`-`:106`) is the chain's head when impress-a
    runs its own mock campaign, and `ss_fraction` is the number `mock_mpnn_design` inherits:
    *"ss_fraction becomes a confidence, the confidence becomes an energy, the energy becomes a
    shape score, and the shape score becomes a pLDDT"*. The chain is a product of slopes, so a
    steered head that reported nothing cost about 0.05 of `complex_plddt` against a bar it had
    to clear -- measured in EI.25, before this existed.

    So this reports **0.60 at the default difficulty**, which is what upstream's twin reports at
    *its* defaults (50 diffusion steps, difficulty 0.25). Upstream's own expression carries a
    `diffusion_steps` term this tool has no parameter for; the constant folds that term at its
    default rather than inventing a knob, and `tests/test_tier1_loop.py` asserts the two twins
    agree instead of trusting the arithmetic to have been copied correctly.

    The slope on `difficulty` is upstream's `-0.60`, unchanged, because its *separation* is what
    decision 0013 needs: ~0.9 lands under the 0.3 integrity floor and ~0.6 between the two bars.

    **Nothing here depends on the steering.** See the parameter's own comment in the spec: a
    twin whose backbone improved with `n_restarts` would make every laptop run show steering
    working, which is M2's question to answer.
    """
    ss = _clamp(0.75 - 0.60 * difficulty + r.uniform(-0.03, 0.03), 0.0, 0.98)
    helix = ss * r.uniform(0.5, 0.7)
    return {
        "ss_fraction": round(ss, 3),
        "num_models": float(n),
        # A MAXIMUM, not a mean -- the name upstream's sidecar table settled on is
        # `max_ca_deviation`, and the twin inherits the semantics along with the formula.
        "ca_deviation": round(_clamp(1.6 * (1.0 - ss) + r.uniform(-0.05, 0.10), 0.0, 5.0), 3),
        "ligand_clashes": float(r.choices([0, 0, 0, 1, 2], weights=[6, 4, 3, 2, 1])[0]),
        "helix_fraction": round(helix, 3),
        "sheet_fraction": round(max(0.0, ss - helix), 3),
    }
