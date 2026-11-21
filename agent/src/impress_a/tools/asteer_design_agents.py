"""The four `asteer_design` task adapters: Model A's emitter, FK Tier 1, and the two stream
clients.

**One module for three subjects**, because impress-a's convention is one module per toolkit and
`entry:` names it -- `rfd3_agents.py`, `rosetta_agents.py`, `boltz_agents.py`. These arrived from
`asteer.impress.{liganchor,rfd3_steered,stream_clients}` in episode H7 of the re-homing, under the
rule that a file belongs to the repo that would break without it. All four adapters are impress-a
tasks: driven by an impress-a campaign, loaded by impress-a's registry, subclassing `TaskAgent`.

**What did not come with them, and will not.** `asteer.fk` (the FK arithmetic, CON-8),
`asteer.fk_sampler` and `asteer.conditioning` stay in `asteer`, because they run inside the Foundry
apptainer container -- where `impress_a` is not installed -- or on both sides of it. So this module
imports `asteer` at module scope, and that direction is the intended one: `asteer` declares no
dependencies, three repos import its contracts inside Dragon tasks, and none of them imports this.

H9 brought the six mock twins over too (`mock_asd_agents.py`), so nothing outside impress-a
imports this module at all.

The three sections below carry their original module headers verbatim. Read them as three modules
sharing a file, not as one subject.
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from asteer import fk
from asteer.contracts import FKConfig, PotentialKind
from asteer.contracts.surrogate import SurrogateRequest, SurrogateResponse
from asteer.fk_sampler import SAMPLER_KIND

from ._subprocess import input_path
from .agent import TaskAgent, TaskRequest

__all__ = [
    "AffDeltaScoreAgent",
    "anchor_from",
    "anchor_spec_from_params",
    "AnchorSpec",
    "bind_stream",
    "bound_stream",
    "LigAnchorProposeAgent",
    "LigandParseError",
    "MODEL_B",
    "MODEL_C",
    "parse_params",
    "PreorgScoreAgent",
    "render_input_spec",
    "RFD3SteeredDesignAgent",
    "SteeringRefused",
    "stream_for",
    "StreamUnavailable",
    "SurrogateStream",
    "tier1",
    "Tier1Run",
    "unbind_stream",
    "UnknownAtomType",
]


# ================================================================================================
# liganchor_propose -- Model A's emitter
# (was `asteer/impress/liganchor.py`, moved in H7)
# ================================================================================================
#
# **`select_hotspots` is never emitted, and that is the whole reason this module reads the way it
# does.** M0 measured it (job `24155612`): the key *resolves* — all six requested atoms are
# annotated `is_atom_level_hotspot` on `atom_array_input` — and then `build()` drops the
# annotation, so `feats.is_atom_level_hotspot` reaches the network as zeros while the run
# completes and reports success. `infer_ori_strategy: "hotspots"` cannot build at all. So the
# hotspot branch was never a branch; it was a silent no-op. Model A takes the documented fallback:
# the classifier-free-guidance channel plus motif placement (source spec §7.4.1, item 2).
#
# A test asserts no code path here emits the key, because RFD3's own documentation says it should
# and the failure mode is a successful-looking run conditioned on nothing (items 26, 29).
#
# **The chemistry comes out of the file, not out of a table, wherever that is possible.** Donor
# status is read from the params file's own `BOND` graph — a heavy atom bearing a polar hydrogen
# is a donor, which is Rosetta's own definition — and only acceptor status needs a lookup. That
# split matters: on the project's own ligand it is the difference between a guess and a
# measurement. `ALR.params` declares two `OH` oxygens and exactly one `Hpol`, so by the graph it
# has **one** donor, not two. A type table alone would have reported two.
#
# **An atom type this module has not been taught refuses the run.** The alternative is to treat an
# unknown type as apolar, which under-conditions the model silently and is this project's
# recurring failure class. The refusal names the type and the file, so the fix is to add a line
# here with its role stated rather than to wonder why a design was anchored on four atoms instead
# of six.
#
# **What is a placeholder, and what replaces it.** *Which* atoms to anchor and *how buried* each
# should be is Model A's actual job — a trained `LigAnchor` head, ROME item 8, disabled until round
# 2 (source spec §7.3) and resident from M4. Until then this module ranks by |partial charge| and
# interpolates the burial target between two declared bounds. Both rules are deterministic,
# declared in the `ToolSpec`, and measured by `anchor_entropy`, so A's selection can be compared
# against the placeholder's on the same number rather than replacing it blind.
# ================================================================================================

#: The schema tag the artifact carries, so a consumer can refuse a payload from a version of
#: this module it does not know. EI.9 reads this before anything else in the dict.
ANCHOR_SPEC_SCHEMA = "asteer.anchor_spec/1"

#: Rosetta atom type -> its role in hydrogen bonding, for the types this project's ligands
#: actually use (`ALR`, `IND`, `RED`) plus the common ones beside them.
#:
#: **The roles are about ACCEPTOR status only.** Donor status is derived from the `BOND` graph
#: instead, because a heavy atom is a donor exactly when it carries a polar hydrogen, and the
#: file says which ones do. So `Ntrp` is `not_acceptor` and still becomes a donor when its
#: `Hpol` is bonded to it — which is correct, and is why one table is enough.
#:
#: `S` is `not_acceptor` deliberately: Rosetta's standard atom set gives thioether sulfur no
#: ACCEPTOR flag. In this project's ligand the `S` atoms are sulfonate sulfurs, whose acceptors
#: are the `OOC` oxygens bonded to them.
ATOM_ROLES: dict[str, str] = {
    # acceptors
    "OOC": "acceptor",     # carboxylate / sulfonate oxygen
    "OH": "acceptor",      # hydroxyl oxygen (also a donor, via its Hpol in the graph)
    "ONH2": "acceptor",    # amide carbonyl oxygen
    "OCbb": "acceptor",    # backbone carbonyl oxygen
    "Nhis": "acceptor",    # imidazole / aromatic nitrogen
    # polar hydrogen: not anchorable itself, but it makes its neighbour a donor
    "Hpol": "polar_hydrogen",
    # everything else this project has seen, stated rather than defaulted
    "CH0": "not_acceptor",
    "CH1": "not_acceptor",
    "CH2": "not_acceptor",
    "CH3": "not_acceptor",
    "aroC": "not_acceptor",
    "Hapo": "not_acceptor",
    "Haro": "not_acceptor",
    "S": "not_acceptor",
    "SH1": "not_acceptor",  # thiol: a donor through its Hpol, not an acceptor
    "Ntrp": "not_acceptor",
    "Narg": "not_acceptor",
    "Nlys": "not_acceptor",
    "NH2O": "not_acceptor",
    "Nbb": "not_acceptor",
}


class LigandParseError(ValueError):
    """The params file is not one, or carries no atoms."""


class UnknownAtomType(LigandParseError):
    """An atom type with no stated role. Refused rather than assumed apolar."""


@dataclass(frozen=True)
class Atom:
    name: str
    atom_type: str
    charge: float


@dataclass(frozen=True)
class Ligand:
    """What a params file says, which is all this module uses."""

    resname: str
    atoms: tuple[Atom, ...]
    #: heavy atom name -> the polar hydrogens bonded to it, from the `BOND` records
    polar_hydrogens: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def by_name(self, name: str) -> Atom | None:
        return next((a for a in self.atoms if a.name == name), None)

    def is_donor(self, name: str) -> bool:
        """A heavy atom bearing a polar hydrogen. Rosetta's own definition, read off the graph."""
        return bool(self.polar_hydrogens.get(name))

    def is_acceptor(self, name: str) -> bool:
        atom = self.by_name(name)
        return atom is not None and ATOM_ROLES[atom.atom_type] == "acceptor"


def parse_params(path: str | Path) -> Ligand:
    """Read a Rosetta `.params` file: its resname, its atoms, and its polar-hydrogen bonds.

    **The resname is taken verbatim and the colon is never cleaned up.** This project's ligand
    is the literal `A:R`, not `ALR`: RFD3 misresolves the bare code, and the colon is a
    deliberate, verified workaround recorded in `IMPRESS/agent/toolkits/rfd3/SKILL.md`. A test
    pins it, because "A:R" looks like a typo to everyone who meets it for the first time.
    """
    text = Path(path).read_text()
    resname = ""
    atoms: list[Atom] = []
    bonds: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "NAME" and len(parts) >= 2 and not resname:
            resname = parts[1]
        elif parts[0] == "ATOM" and len(parts) >= 5:
            try:
                charge = float(parts[4])
            except ValueError as exc:
                raise LigandParseError(
                    f"{path}: ATOM line has a non-numeric charge: {line!r}") from exc
            atoms.append(Atom(name=parts[1], atom_type=parts[2], charge=charge))
        elif parts[0] == "BOND" and len(parts) >= 3:
            bonds.append((parts[1], parts[2]))

    if not atoms:
        raise LigandParseError(f"{path}: no ATOM records, so there is no ligand to anchor")
    if not resname:
        raise LigandParseError(f"{path}: no NAME record, so the ligand has no resname to key on")

    unknown = sorted({a.atom_type for a in atoms} - set(ATOM_ROLES))
    if unknown:
        raise UnknownAtomType(
            f"{path}: atom types with no stated role: {unknown}. Add each to "
            "impress_a.tools.asteer_design_agents.ATOM_ROLES with its acceptor status; "
            "do NOT let it "
            "default to apolar, which would silently shrink the anchor set and condition the "
            "model on fewer atoms than anyone asked for."
        )

    by_type = {a.name: a.atom_type for a in atoms}
    polar: dict[str, list[str]] = {}
    for left, right in bonds:
        for heavy, maybe_h in ((left, right), (right, left)):
            if ATOM_ROLES.get(by_type.get(maybe_h, ""), "") == "polar_hydrogen" \
                    and ATOM_ROLES.get(by_type.get(heavy, ""), "") != "polar_hydrogen":
                polar.setdefault(heavy, []).append(maybe_h)
    return Ligand(resname=resname, atoms=tuple(atoms),
                  polar_hydrogens={k: tuple(v) for k, v in polar.items()})


@dataclass(frozen=True)
class AnchorSpec:
    """Model A's instruction to the sampler: which atoms, what interaction, how buried.

    Serialised as a plain dict for the artifact, because an `ArtifactRef`'s value crosses a
    process boundary as data. The **type** of the port is `Parameterized`, not a new
    `AnchorSpec` member: `ArtifactType` is a closed enum upstream (`core/types.py:35`) and gate
    1 validates against it, so adding a member is an upstream change (item 31). The existing
    member is also the honest one — an anchor set *is* a parameterisation handed to the sampler,
    which is where the enum's own docstring draws the line.
    """

    resname: str
    engaged_atoms: tuple[str, ...]
    features: dict[str, dict[str, float]]
    cfg_scale: float
    cfg_t_max: float
    #: Which keys in `features` hold the donor, acceptor and burial channels. Carried on the
    #: spec rather than hardcoded in `anchor_entropy`, because the key spelling is a declared
    #: campaign parameter -- the source spec writes this channel two ways and neither is
    #: verifiable off-cluster. The first version of this class did hardcode them, and
    #: `test_the_feature_keys_are_data_so_a_campaign_can_correct_the_spelling` is what found
    #: it: correcting the spelling made the metric raise `KeyError` instead of reporting.
    feature_keys: tuple[str, str, str] = ("active_donor", "active_acceptor",
                                          "ref_atomwise_rasa")

    @property
    def n_engaged_atoms(self) -> int:
        return len(self.engaged_atoms)

    @property
    def anchor_entropy(self) -> float:
        """How spread the anchoring is, as normalised Shannon entropy in [0, 1].

        The weight of an atom is its donor plus acceptor activation, so a donor-and-acceptor
        atom counts double. Normalised by `log(n)` so the number is comparable across anchor
        sets of different sizes: 1.0 is evenly spread, lower is concentrated on a few atoms.
        **Defined as 0.0 for a single atom**, where no spread is possible and `log(1)` is zero —
        returning a bare ratio there would divide by zero, and returning 1.0 would call the most
        concentrated possible anchor set maximally spread.

        This is the number Model A's trained selection should be compared against, which is why
        it is a declared metric rather than a diagnostic.
        """
        donor_key, acceptor_key, _ = self.feature_keys
        weights = [self.features.get(donor_key, {}).get(a, 0.0)
                   + self.features.get(acceptor_key, {}).get(a, 0.0)
                   for a in self.engaged_atoms]
        total = sum(weights)
        if len(weights) < 2 or total <= 0:
            return 0.0
        entropy = -sum((w / total) * math.log(w / total) for w in weights if w > 0)
        return round(entropy / math.log(len(weights)), 4)

    def as_artifact(self) -> dict[str, Any]:
        """The payload the ToolSpec's `anchor_spec` port carries.

        `use_classifier_free_guidance` is stated in the payload rather than assumed by the
        consumer, so a reader of a stored artifact can tell which channel a design was
        conditioned through without re-deriving it from the campaign YAML.
        """
        return {
            "schema": ANCHOR_SPEC_SCHEMA,
            "ligand_resname": self.resname,
            "engaged_atoms": list(self.engaged_atoms),
            "use_classifier_free_guidance": True,
            "cfg_features": {k: dict(v) for k, v in self.features.items()},
            "cfg_scale": self.cfg_scale,
            "cfg_t_max": self.cfg_t_max,
        }


def anchor_spec_from_params(
    path: str | Path,
    *,
    max_anchor_atoms: int = 6,
    feature_keys: tuple[str, str, str] = ("active_donor", "active_acceptor",
                                          "ref_atomwise_rasa"),
    buried_target_rasa: float = 0.15,
    exposed_target_rasa: float = 0.45,
    cfg_scale: float = 1.5,
    cfg_t_max: float = 1.0,
) -> AnchorSpec:
    """Rank the ligand's polar atoms and emit the CFG channel for the top `max_anchor_atoms`.

    **Ranking is by |partial charge|, descending, then by atom name.** The charge is the one
    quantity the file supplies that bears on anchoring strength, and the name breaks ties so two
    runs of the same campaign agree — a selection that moved between runs could not be the thing
    a regression test compares against. It is a placeholder for Model A, and the `ToolSpec` says
    so.

    **The burial target is interpolated between two declared bounds**, most-charged atom at
    `buried_target_rasa` and least-charged at `exposed_target_rasa`. Interpolating over a
    measured quantity is the least invented option available; both ends are parameters because
    neither is derived from anything.
    """
    ligand = parse_params(path)
    donor_key, acceptor_key, rasa_key = feature_keys

    engaged = sorted(
        (a for a in ligand.atoms
         if ligand.is_donor(a.name) or ligand.is_acceptor(a.name)),
        key=lambda a: (-abs(a.charge), a.name),
    )[:max(0, int(max_anchor_atoms))]
    if not engaged:
        raise LigandParseError(
            f"{path}: no donor or acceptor atoms, so there is nothing to anchor on. The ligand "
            f"({ligand.resname}) parsed cleanly, so this is a statement about the molecule "
            "rather than about the file."
        )

    charges = [abs(a.charge) for a in engaged]
    span = max(charges) - min(charges)
    features: dict[str, dict[str, float]] = {donor_key: {}, acceptor_key: {}, rasa_key: {}}
    for atom in engaged:
        features[donor_key][atom.name] = 1.0 if ligand.is_donor(atom.name) else 0.0
        features[acceptor_key][atom.name] = 1.0 if ligand.is_acceptor(atom.name) else 0.0
        # Most charged -> most buried. With no span every engaged atom is equally charged, so
        # they share the buried target rather than being spread over an interval that does not
        # exist.
        fraction = 0.0 if span <= 0 else (max(charges) - abs(atom.charge)) / span
        features[rasa_key][atom.name] = round(
            buried_target_rasa + fraction * (exposed_target_rasa - buried_target_rasa), 4)

    return AnchorSpec(
        resname=ligand.resname,
        engaged_atoms=tuple(a.name for a in engaged),
        features=features,
        cfg_scale=cfg_scale,
        cfg_t_max=cfg_t_max,
        feature_keys=(donor_key, acceptor_key, rasa_key),
    )


class LigAnchorProposeAgent(TaskAgent):
    """`liganchor_propose`: the ligand's params file in, an anchor spec out.

    A root tool — the ligand arrives as a path parameter, exactly as `rfd3_design` takes
    `input_spec_path` — so nothing upstream checks that it arrived
    (`compose/validate.py:79`–`:81` is a literal `pass` for an unsatisfied root input). The
    check is here, before anything else, because the alternative is anchoring on an empty path.
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        path = str(params.get("ligand_params_path") or "").strip()
        if not path:
            raise LigandParseError(
                f"{self.spec.id}: no `ligand_params_path`. This tool is a root, so the ligand "
                "arrives as a path parameter and NOTHING UPSTREAM CHECKS IT -- "
                "compose/validate.py:79-:81 is a literal `pass` for an unsatisfied root input. "
                "Set it in the campaign's `params`."
            )
        keys = [k.strip() for k in str(params.get("cfg_feature_keys") or "").split(",")
                if k.strip()]
        if len(keys) != 3:
            # Two keys would silently drop a channel, which is the shape of item 26's defect.
            raise LigandParseError(
                f"{self.spec.id}: `cfg_feature_keys` must name exactly three features, got "
                f"{keys!r}. Fewer would drop a channel without saying so."
            )
        spec = anchor_spec_from_params(
            path,
            max_anchor_atoms=int(params.get("max_anchor_atoms", 6)),
            feature_keys=(keys[0], keys[1], keys[2]),
            buried_target_rasa=float(params.get("buried_target_rasa", 0.15)),
            exposed_target_rasa=float(params.get("exposed_target_rasa", 0.45)),
            cfg_scale=float(params.get("cfg_scale", 1.5)),
            cfg_t_max=float(params.get("cfg_t_max", 1.0)),
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


# ================================================================================================
# rfd3_steered_design -- FK Tier 1 over partial_t restarts
# (was `asteer/impress/rfd3_steered.py`, moved in H7)
# ================================================================================================
#
# **A new tool, not a change to `rfd3_design`.** That keeps the unsteered control arm intact, so
# M2 can run both at the same N. A control arm that exists only as a preserved capability is not
# a control: without it neither the inertness check nor the outer loop's success criterion can be
# read at all.
#
# **Tier 1 needs no RFD3 internals.** Generate K particles, score the *finished* designs through
# Model B's stream, resample under `G = exp(λ·r)` from `asteer.fk` (CON-8), re-noise the survivors
# with `partial_t`, re-denoise. It is also the RFOptimization-style iteration the source spec's §4
# already budgets for, so it stands on its own even if Tier 2 (EI.17) never lands.
#
# **The burial channel renders to `select_buried` / `select_exposed`, not to the CFG keys, and
# that is a correction to this episode's plan made on evidence in this repo.** The plan has Model A
# emitting `active_donor` / `active_acceptor` / `ref_atomwise_rasa`. Those three appear nowhere in
# impress-a, nowhere in RFD3's documented key list, and nowhere in the project's own input JSON —
# the spelling is not even internally consistent in the source specification. What the committed
# `campaigns/data/alr/ALR_binder_design.json` actually carries is a `partial` block with
# `select_exposed` and `select_buried`, each a per-ligand atom list, and both are in the SKILL.md's
# enumerated `DesignInputSpecification` keys. `ref_atomwise_rasa` is described in the source spec
# as "a direct handle on per-atom burial", which is what that pair expresses.
#
# So the renderer writes the verified keys and treats the CFG trio as **opt-in, default off**
# (`emit_cfg_features`). The evidence is better, not conclusive: M0 measured that
# `select_hotspots` resolves and is then dropped, and it did not test these two. The difference is
# that these are documented, enumerated, and already in use by this project's own target identity,
# where `select_hotspots` is absent from the enumeration entirely. **Whether the annotation
# survives `build()` is an M2 measurement**, and EI.7's `conditioning_applied` gate is what will
# catch it if it does not.
#
# **Two conditioning checks exist at two layers and must not be conflated.** This module reports
# `conditioning_requested` and `conditioning_applied` over *the JSON it renders* — how many atoms
# Model A asked for, and how many reached the file. That is the half we control and it is checkable
# on a laptop. The other half, whether the annotation survives into `feats`, needs the container
# and is what `asteer.conditioning.check_from_pipeline` is for. Passing the gate here does **not**
# mean the model was conditioned; it means we did not drop the atoms on the way out.
# ================================================================================================

#: The mode key in a `DesignInputSpecification`. The committed input uses `partial`, which is
#: the mode Tier 1 needs — every restart re-noises an existing structure.
PARTIAL = "partial"

#: What a particle is, to this loop: whatever the denoiser hands back. An opaque handle on
#: purpose — a path, a dict, a structure object — because Tier 1 never looks inside one. The
#: loop's job is to choose among them, and anything it inspected would couple it to the
#: container's output layout, which it cannot see from here.
Particle = Any

#: `(spec, n, partial_t, seeds) -> particles`. Injected as a plain argument rather than through
#: a registry, because there is exactly one caller and a registry would be a seam nobody asked
#: for. The real one shells out to RFD3's CLI inside the Foundry container; tests pass a fake.
Denoiser = Callable[..., Sequence[Particle]]

#: `particle -> reward`. Model B's score, through the stream (the stream clients below).
Scorer = Callable[[Particle], float]


class SteeringRefused(RuntimeError):
    """The loop cannot run and will not pretend to. Named, so the message is a pointer."""


def anchor_from(req: Any) -> dict[str, Any]:
    """The anchor artifact, resolved by this tool's own declared input port.

    **Through `input_path`, not out of `req.inputs` directly**, and the difference is not
    cosmetic: `req.inputs[port]` is the upstream task's whole payload, so reading it as the
    artifact yields `{"outputs": ..., "metrics": ...}` and every key this tool wants is absent.
    `TaskRequest.input_ref` resolves by the declared port using the wiring the composer computed
    and gate 1 type-checked, and `input_path` then hands back the value or the path. A
    single-stage test passes either way, which is why this was wrong until the mock campaign
    grew a second stage.
    """
    resolved = input_path(req, "anchor_spec")
    if isinstance(resolved, dict):
        return dict(resolved)
    if isinstance(resolved, str) and resolved.strip():
        # A ref carrying a path rather than a value: the artifact was staged to disk.
        return dict(json.loads(Path(resolved).read_text()))
    return {}


# ---------------------------------------------------------------------------
# rendering the input spec
# ---------------------------------------------------------------------------


def render_input_spec(
    template: dict[str, Any],
    anchor: dict[str, Any],
    *,
    partial_t: float | None,
    buried_threshold: float = 0.3,
    emit_cfg_features: bool = False,
    tier: int = 1,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Write Model A's anchor set into a `DesignInputSpecification`, returning it and the counts.

    **`length` is dropped whenever `partial_t` is set, and the drop is reported rather than
    silent.** RFD3's validator rejects the combination outright — *"Length argument must not be
    provided during partial diffusion"*, because length is inferred from the input structure in
    that mode — and the sibling example paid for it: job `21928556`, three of three pipelines
    that reached guided feedback crashed on their first attempt, fixed with
    `partial.pop('length', None)`. Backlog C8, and
    `tests/test_real_toolkits.py::test_rfd3_partial_diffusion_would_have_to_drop_length` is the
    upstream guard that fires the day a `partial_t` port is declared.

    **Dropping rather than refusing is a deliberate deviation from this episode's plan**, whose
    Test asked for both. The project's own `ALR_binder_design.json` carries `partial.input` *and*
    `length: "70-170"`, and that file is target identity — refusing it would mean every guided
    run needs a hand-edited copy of the thing that identifies the target. So the renderer drops
    it and returns `length_dropped` in the counts, which the agent reports as a metric, so
    provenance shows the edit instead of hiding it.
    """
    if anchor.get("schema") != ANCHOR_SPEC_SCHEMA:
        raise SteeringRefused(
            f"anchor spec has schema {anchor.get('schema')!r}, not {ANCHOR_SPEC_SCHEMA!r}: "
            "this tool consumes liganchor_propose's artifact and will not guess at an "
            "unknown payload's layout"
        )
    spec = copy.deepcopy(template)
    block = spec.get(PARTIAL)
    if not isinstance(block, dict):
        raise SteeringRefused(
            f"the input template has no {PARTIAL!r} block; Tier 1 re-noises an existing "
            f"structure every restart, so {PARTIAL!r} is the only mode it can drive. "
            f"Got top-level keys {sorted(spec)}"
        )

    resname = str(anchor.get("ligand_resname") or "")
    if not resname:
        raise SteeringRefused("the anchor spec names no ligand resname to key the atom lists on")
    if resname != block.get("ligand"):
        # A mismatch here conditions the wrong residue, and `A:R` vs `ALR` is the documented
        # way to get it wrong: RFD3 misresolves the bare code, so the colon is deliberate.
        raise SteeringRefused(
            f"the anchor spec is keyed on ligand {resname!r} and the input template on "
            f"{block.get('ligand')!r}. Never 'clean up' the colon in A:R -- RFD3 misresolves "
            "the bare three-letter code, and the spelling is a verified workaround."
        )

    rasa_key = anchor.get("cfg_features") or {}
    burial_name = _feature_names(anchor)[2]
    burial = dict(rasa_key.get(burial_name) or {})
    requested = len(anchor.get("engaged_atoms") or ())
    if not burial:
        raise SteeringRefused(
            f"the anchor spec carries no {burial_name!r} channel, so there is no burial target "
            f"to condition on. Requested atoms: {requested}"
        )

    buried = sorted(a for a, v in burial.items() if float(v) <= buried_threshold)
    exposed = sorted(a for a, v in burial.items() if float(v) > buried_threshold)

    # BOTH KEYS ARE REPLACED, AND AN EMPTY SIDE IS REMOVED RATHER THAN LEFT ALONE. The first
    # cut wrote a side only when it was non-empty, which looked harmless and was not: the
    # committed `ALR_binder_design.json` already carries hand-written `select_buried` and
    # `select_exposed` lists, so a threshold that put every atom on one side left the
    # template's stale list standing on the other -- conditioning the run on a mixture of
    # Model A's instruction and a hand-written one, with nothing to say so. Caught by
    # `test_every_requested_atom_reaches_one_of_the_two_lists`. Model A's anchor set is
    # authoritative for the atoms it names, so the override is total and is reported.
    overrode = sum(1 for k in ("select_buried", "select_exposed") if block.get(k))
    for key, names in (("select_buried", buried), ("select_exposed", exposed)):
        if names:
            block[key] = {resname: ",".join(names)}
        else:
            block.pop(key, None)

    if emit_cfg_features:
        # OPT-IN AND OFF BY DEFAULT. The key spelling is unverified -- the source spec writes
        # `active donor` with a space in two places and `active_donor` elsewhere -- and a wrong
        # key is item 26 exactly: the run completes conditioned on nothing and reports success.
        # Turn this on only once the container has confirmed the names.
        block["use_classifier_free_guidance"] = True
        block["cfg_features"] = {k: dict(v) for k, v in rasa_key.items()}
        block["cfg_scale"] = anchor.get("cfg_scale", 1.5)
        block["cfg_t_max"] = anchor.get("cfg_t_max", 1.0)

    if int(tier) == 2:
        # TIER 2 IS SELECTED IN THE INPUT SPEC, not on the CLI. `inference_sampler.kind` is
        # what RFD3 reads to pick a sampler out of `ConditionalDiffusionSampler._registry`
        # (item 3, job 24155612), and **the registry falls back silently on an unknown key** --
        # so a campaign asking for tier 2 against an unregistered sampler would run the stock
        # one and report success having steered nothing. Writing the key here from the one
        # constant is half the guard; `asteer.fk_sampler.register` returning the key is the
        # other half.
        block["inference_sampler"] = {"kind": SAMPLER_KIND}
    elif "inference_sampler" in block:
        # A template left over from a tier-2 run must not silently steer a tier-1 one.
        block.pop("inference_sampler")

    length_dropped = 0
    if partial_t is not None and "length" in block:
        del block["length"]
        length_dropped = 1

    applied = len(buried) + len(exposed)
    return spec, {
        "conditioning_requested": requested,
        "conditioning_applied": applied,
        "length_dropped": length_dropped,
        "template_lists_overridden": overrode,
        "tier": int(tier),
    }


def _feature_names(anchor: dict[str, Any]) -> tuple[str, str, str]:
    """The three CFG channel names this payload used, in order.

    Read off the payload rather than assumed, because the spelling is a campaign parameter on
    `liganchor_propose` (EI.8) for the reason above. Falls back to the documented defaults for a
    payload written before the keys were carried.
    """
    keys = list(anchor.get("cfg_features") or {})
    if len(keys) == 3:
        return keys[0], keys[1], keys[2]
    return "active_donor", "active_acceptor", "ref_atomwise_rasa"


# ---------------------------------------------------------------------------
# the Tier 1 loop
# ---------------------------------------------------------------------------


@dataclass
class Tier1Run:
    """One steered design pass: every resampling event, and the folds item 12 declares."""

    particles: list[Particle] = field(default_factory=list)
    steps: list[fk.FKStep] = field(default_factory=list)
    rewards: list[list[float]] = field(default_factory=list)

    @property
    def ess_mean(self) -> float:
        """Mean ESS over the resampling events, in particles.

        Over events rather than over the final population: the inertness check at M2 asks
        whether steering ever did anything, and a final-population number cannot distinguish a
        run that never resampled from one that resampled and recovered.
        """
        if not self.steps:
            return 0.0
        return round(sum(s.ess.ess for s in self.steps) / len(self.steps), 4)

    @property
    def n_resamples(self) -> int:
        """Events that actually changed the population.

        `FKStep.resampled` is False when every parent survived exactly once, and counting those
        would overstate how much steering happened — which is the number the inertness check
        is reading.
        """
        return sum(1 for s in self.steps if s.resampled)

    @property
    def particle_diversity(self) -> float:
        """Mean distinct survivors per event, normalised to [0, 1]."""
        if not self.steps:
            return 0.0
        fractions = [s.diversity / len(s.indices) for s in self.steps if s.indices]
        return round(sum(fractions) / len(fractions), 4) if fractions else 0.0

    @property
    def reward_terminal(self) -> float:
        """The best reward in the final population — what the pass is handing downstream."""
        return round(max(self.rewards[-1]), 4) if self.rewards and self.rewards[-1] else 0.0

    @property
    def collapsed(self) -> bool:
        return any(s.ess.collapsed for s in self.steps)


def tier1(
    config: FKConfig,
    *,
    denoise: Denoiser,
    score: Scorer,
    n_restarts: int,
    partial_t: float,
    carry_history: bool = True,
) -> Tier1Run:
    """Generate, score, resample, re-noise, re-denoise — `n_restarts` times.

    **Scoring happens on finished designs, which is what makes Tier 1 CLI-only.** The reward is
    Model B's score of a complete structure, so nothing here needs RFD3's internals; Tier 2
    (EI.17) is the one that scores partial states and therefore needs the sampler.

    **The history is carried by default** because three of the four potentials need it:
    `DIFFERENCE`, `MAX` and `SUM` are folds over the trajectory, and passing `None` would make
    them silently equivalent to `IMMEDIATE`. A config that chose `MAX` and got `IMMEDIATE`
    weights would steer, report plausible numbers, and be steering on the wrong quantity.
    """
    if n_restarts < 1:
        raise SteeringRefused(
            f"n_restarts must be >= 1, got {n_restarts}: a pass with no restart is the "
            "unsteered arm, and that is `rfd3_design`, deliberately a separate tool"
        )
    run = Tier1Run(particles=list(denoise(n=config.n_particles, partial_t=None, seeds=None)))
    if len(run.particles) != config.n_particles:
        raise SteeringRefused(
            f"the denoiser returned {len(run.particles)} particles, not the "
            f"{config.n_particles} the FK config declares. Resampling a population of a "
            "different size than the weights were computed for silently mis-pairs them."
        )
    for _ in range(n_restarts):
        rewards = [float(score(p)) for p in run.particles]
        run.rewards.append(rewards)
        history = run.rewards[:-1] if carry_history else None
        fkstep = fk.step(config, rewards, history=history)
        run.steps.append(fkstep)
        survivors = [run.particles[i] for i in fkstep.indices]
        run.particles = list(denoise(n=config.n_particles, partial_t=partial_t,
                                     seeds=survivors))
    run.rewards.append([float(score(p)) for p in run.particles])
    return run


# ---------------------------------------------------------------------------
# what the pass produced: RFD3's own backbone quality (item 43, EI.31)
# ---------------------------------------------------------------------------


class NoCandidateModels(RuntimeError):
    """A directory with structures in it and no design we can name."""


def candidate_models(work: Path) -> list[Path]:
    """The `.cif.gz` files in `work` that carry a sidecar `*_model_*.json`, sorted.

    **The same discovery rule as `rfd3_design`, copied rather than imported, and the reason it
    cannot be loosened is a measurement.** RFD3 writes its *trajectories* as `.cif.gz` too
    (`*_denoised_model_*`, `*_noisy_model_*`), and `denoised` sorts BEFORE a design's own name —
    so `sorted(work.glob("*.cif.gz"))[0]` picked a multi-frame trajectory and handed it
    downstream as the backbone. Upstream measured that on job 22536706: a 5.7 MB `backbone_0.pdb`
    built from a 1.7 MB trajectory sitting beside the real 19 KB design, with `ss_fraction`
    computed on the stack. The sidecar is the discriminator: rfd3 writes one for every design and
    none for a trajectory.

    It is copied and not imported because upstream's copy is eleven lines inline in
    `RFD3DesignAgent.run` (`rfd3_agents.py:262`–`:271`) rather than a function. The citation is
    the link; `_sidecar_metrics` and `secondary_structure_fraction`, which *are* functions, are
    imported.

    A directory holding `.cif.gz` and no sidecar at all is **refused**, not guessed at — picking
    one would be a guess at which of them is a design.
    """
    models = []
    for meta in sorted(work.glob("*_model_*.json")):
        cif = meta.with_name(meta.name[: -len(".json")] + ".cif.gz")
        if cif.exists():
            models.append(cif)
    if models:
        return models
    stray = sorted(work.glob("*.cif.gz"))
    if stray:
        raise NoCandidateModels(
            f"{len(stray)} .cif.gz in {work} and none carries a sidecar *_model_*.json "
            f"(first: {stray[0].name}). rfd3 writes that JSON for every design and none for a "
            "trajectory, so this is not an out_dir a candidate can be picked from -- check "
            "dump_prediction_metadata_json."
        )
    raise NoCandidateModels(f"no structures at all in {work}")


def backbone_metrics(work: Path, *, out_pdb: str = "backbone_0.pdb") -> dict[str, Any]:
    """The chosen design and the six quality metrics `rfd3_design` reports, from one out_dir.

    **This is the half of item 43 that reuses rather than guesses.** Item 43's own plan said
    *"which metrics are actually readable from a steered run is a measurement, not a guess"* —
    and upstream has already paid for that measurement twice over:

    * `secondary_structure_fraction` computes `ss_fraction` **from the written PDB**, not from
      anything rfd3 reports, so a steered pass computes it the same way with no new science.
    * `SIDECAR_KEYS` (`rfd3_agents.py:71`–`:94`) is an **observed** alias table, settled by jobs
      23670171 and 23670891. Two of its four original guesses were wrong: `ca_deviation` is
      `max_ca_deviation` — a *maximum*, the worst atom in the design rather than the typical one,
      which matters to anything that later gates on it — and `ligand_clashes` is the literal
      dotted key `n_clashing.ligand_clashes`, with no `n_clashing` object to descend into.
      Re-deriving either from the names would have been the third wrong guess.

    Every heavy import is inside this function (CON-4): Biopython for the Ramachandran pass and
    `gemmi` for the conversion, neither of which `Registry.load()` may require.

    **`num_models` is the count of sidecar-carrying models**, which for a steered pass is the
    final population — the same quantity the twin reports as `len(run.particles)`.
    """
    from ._pdbtools import (  # noqa: PLC0415
        cif_gz_to_pdb,
        secondary_structure_fraction,
    )
    from .rfd3_agents import _sidecar_metrics  # noqa: PLC0415

    models = candidate_models(work)
    best = work / out_pdb
    cif_gz_to_pdb(models[0], best)
    metrics: dict[str, float] = {
        "ss_fraction": float(secondary_structure_fraction(best)),
        "num_models": float(len(models)),
    }
    metrics.update(_sidecar_metrics(models[0]))
    return {"backbone": best, "metrics": metrics}


# ---------------------------------------------------------------------------
# the task agent
# ---------------------------------------------------------------------------


class RFD3SteeredDesignAgent(TaskAgent):
    """The steered generator. Refuses off-cluster rather than pretending to diffuse.

    `rfd3_design`'s SKILL.md requires `$FOUNDRY_SIF_PATH` to point at a built or extracted
    Foundry sandbox, and nothing in this loop can produce a structure without it. So the agent
    checks for it first and names the twin — the alternative is a laptop run that returns
    plausible particles, and this tool's output is what the whole steered arm is read from.

    The loop, the rendering and the FK arithmetic are all exercised without the container; it
    is only the denoiser that needs one. `tests/test_tier1_loop.py` drives all three.
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        import os  # noqa: PLC0415

        anchor = anchor_from(req)
        if not anchor:
            raise SteeringRefused(
                f"{self.spec.id}: the `anchor_spec` input is unwired or empty. It comes from "
                "liganchor_propose, and `compose/validate.py:79`-`:81` is a literal `pass` for "
                "an unsatisfied required input on a node with no dependencies -- so a graph "
                "that forgot the edge composes cleanly and would diffuse unconditioned."
            )
        template_path = str(params.get("input_spec_path") or "").strip()
        if not template_path:
            raise SteeringRefused(
                f"{self.spec.id}: no `input_spec_path`. RFD3 has no scaffold or guidance CLI "
                "override -- guided versus unguided is selected entirely by WHICH file this "
                "points at -- so this is target identity and must be campaign-supplied."
            )
        template = json.loads(Path(template_path).read_text())
        # The rendered spec is discarded here on purpose: this agent refuses before it could
        # hand it to RFD3, and the counts are what the refusal reports. The spec is what M2's
        # denoiser will be given, and the twin keeps it so a laptop run's provenance shows it.
        _spec, counts = render_input_spec(
            template, anchor,
            partial_t=float(params.get("partial_t", 0.4)),
            buried_threshold=float(params.get("buried_threshold", 0.3)),
            emit_cfg_features=bool(params.get("emit_cfg_features", False)),
            tier=int(params.get("tier", 1)),
        )
        if counts["conditioning_applied"] < 1:
            # Fails here rather than at the gate, because the gate runs after the task has
            # been billed and this check costs nothing.
            raise SteeringRefused(
                f"{self.spec.id}: {counts['conditioning_requested']} atoms were requested and "
                "none reached the input spec, so this run would diffuse unconditioned while "
                "reporting success -- the failure M0 measured (items 26, 29)."
            )
        if not os.environ.get("FOUNDRY_SIF_PATH"):
            raise SteeringRefused(
                f"{self.spec.id}: $FOUNDRY_SIF_PATH is unset, so there is no RFD3 to drive. "
                f"The input spec rendered cleanly ({counts['conditioning_applied']} of "
                f"{counts['conditioning_requested']} atoms conditioned"
                + (", `length` dropped for partial diffusion" if counts["length_dropped"]
                   else "")
                + "). Use `mock_rfd3_steered_design` for laptop runs -- it is `toolkit: mock`, "
                "so `tool_delivery: real` refuses it. The denoiser lands at M2."
            )
        raise SteeringRefused(
            f"{self.spec.id}: the Tier-1 loop, its input rendering and the backbone-quality "
            "read (`backbone_metrics`) are implemented and tested; the CLI denoiser that runs "
            "inside the container is M2's. It refuses rather than returning particles, because "
            "this tool's output is what the entire steered arm is read from."
        )


def mock_tier1_metrics(run: Tier1Run, counts: dict[str, int]) -> dict[str, float]:
    """The four declared metrics plus the two conditioning counts, from one run.

    Shared by the twin and by whatever drives the real loop at M2, so the two cannot report
    the same names computed differently — the mistake EI.8 found between `anchor_entropy`'s
    twin and its tool.
    """
    return {
        "ess_mean": run.ess_mean,
        "n_resamples": float(run.n_resamples),
        "reward_terminal": run.reward_terminal,
        "particle_diversity": run.particle_diversity,
        "conditioning_requested": float(counts["conditioning_requested"]),
        "conditioning_applied": float(counts["conditioning_applied"]),
        "length_dropped": float(counts["length_dropped"]),
        "template_lists_overridden": float(counts["template_lists_overridden"]),
    }


def default_fk_config(params: dict[str, Any]) -> FKConfig:
    """Build the loop's `FKConfig` from declared parameters, in one place.

    The twin and the real agent both need it, and two copies would be two chances for a
    campaign's `tau` to mean something different on the twin than on the tool.
    """
    n = int(params.get("n_particles", 8))
    return FKConfig(
        n_particles=n,
        potential=PotentialKind(str(params.get("fk_potential", "immediate"))),
        tau=float(params.get("fk_tau", 1.0)),
        # Absolute particle count, so one number means the same thing in both loops. Defaulted
        # to a quarter of the population rather than to 1.0: a threshold of one particle only
        # fires when the population has already collapsed to a single lineage, which is too
        # late to be a signal.
        ess_collapse_threshold=float(params.get("ess_collapse_threshold", max(1.0, n / 4))),
        seed=params.get("seed"),
    )


# ================================================================================================
# preorg_score, affdelta_score -- thin clients onto a resident ROME stream
# (was `asteer/impress/stream_clients.py`, moved in H7)
# ================================================================================================
#
# Models B and C are served from ROME, not from here, and that is structural rather than a
# staging decision. impress-a's `TaskAgent`s are constructed and discarded per invocation and
# `ToolSpec.agent` is inert (backlog H4), so nothing in a task can hold weights between calls;
# a `rome.Stream` is a resident, hot-reloading service and `rome/manager.py:172` makes a
# finished training round *be* the event that swaps inference onto new weights. So residency
# lives there and scoring lives here, over a seam.
#
# **The whole behaviour worth reviewing is what happens when the stream is not there.** A
# scoring client that returned a default on an outage would write a number into the design tree
# that looks exactly like a score, gets ranked on, and trains the next round of the model that
# was supposed to produce it. There is no gate that can catch that, because the payload is
# well-formed. So every absence raises:
#
# * no stream bound for the model -> `StreamUnavailable`, naming the model and how to bind one;
# * the stream raises, times out, or returns the wrong shape -> `StreamUnavailable`, chaining
#   the cause.
#
# **Attribution is by construction, not by checking.** `SurrogateResponse` cannot be built
# without `(model_id, version)` (`asteer.contracts.surrogate`), and both sides of this seam
# import that module, so a score with no model cannot exist to be reported. The
# `surrogate_version_present` gate (EI.7) is the second line of defence, over the payload, and
# `tests/test_stream_clients.py` runs it against what these agents actually emit.
#
# **`dg_lcb` is omitted when `sigma_dg` is missing, never defaulted.** Item 14 ranks on the
# lower confidence bound, so an LCB computed with a missing or zero sigma *is* the posterior
# mean wearing the name of a conservative estimate -- the ranking silently stops accounting for
# uncertainty and nothing downstream can tell. `rosetta/SKILL.md`'s rule is the precedent: a
# value that cannot be read is omitted so `metrics_reported` fails, because 0.0 passes most
# bounds. EI.7's `calibration_in_range` is the other half of this, on sigma itself.
# ================================================================================================

#: The two model ids these clients ask for, named once. A typo in a spec's `model_id`
#: parameter would otherwise route to a stream nobody bound -- which raises
#: `StreamUnavailable` rather than scoring against the wrong model, so the failure is the
#: loud one either way, but naming them here means the common case cannot be mistyped at all.
MODEL_B = "pocket_preorg"
MODEL_C = "aff_delta"


class StreamUnavailable(RuntimeError):
    """No usable stream for a model: unbound, down, or answering the wrong shape.

    One exception for all three because the caller's options are identical and the
    alternative -- a default score -- is what this type exists to make impossible.
    """


class SurrogateStream(Protocol):
    """What a client needs from ROME, which is one method.

    Deliberately narrower than `rome.Stream`: a protocol this small is satisfied by the real
    stream, by `tests/fake_stream.py`, and by whatever phase II's item 9 ends up writing,
    without any of them inheriting from us.
    """

    def score(self, request: SurrogateRequest) -> SurrogateResponse:
        ...


#: model_id -> the stream serving it, in this process. A module-level binding rather than a
#: `ContextVar` because that is what the deployment actually is: QC and tool bodies run on the
#: `local` backend, a thread pool in the engine's own process (`exec/backend.py:40`), and a
#: ContextVar set on the campaign's thread is not visible in a pool worker. One process, one
#: set of resident streams.
_STREAMS: dict[str, SurrogateStream] = {}


def bind_stream(model_id: str, stream: SurrogateStream) -> None:
    """Make a stream reachable by the client tools. Called by the campaign body, not a task."""
    if not model_id:
        raise ValueError("model_id is required")
    _STREAMS[model_id] = stream


def unbind_stream(model_id: str) -> None:
    """Remove a binding. Absent is not an error: unbinding twice is a shutdown, not a bug."""
    _STREAMS.pop(model_id, None)


@contextlib.contextmanager
def bound_stream(model_id: str, stream: SurrogateStream) -> Iterator[None]:
    """A binding for the duration of a block, restoring whatever was there before.

    Tests need this; so does a campaign that swaps a stream mid-run. Restoring the previous
    binding rather than clearing is what makes it safe to nest.
    """
    previous = _STREAMS.get(model_id)
    bind_stream(model_id, stream)
    try:
        yield
    finally:
        if previous is None:
            unbind_stream(model_id)
        else:
            _STREAMS[model_id] = previous


def stream_for(model_id: str) -> SurrogateStream:
    """The stream serving `model_id`, or a refusal that says what to do about it."""
    stream = _STREAMS.get(model_id)
    if stream is None:
        raise StreamUnavailable(
            f"no stream bound for model {model_id!r}; bound: {sorted(_STREAMS) or 'none'}. "
            "Models B and C are served by ROME, not by this task: the campaign body binds a "
            "stream with impress_a.tools.asteer_design_agents.bind_stream(model_id, stream) before "
            "the first scoring stage runs. This refuses rather than returning a default "
            "score, which would enter the design tree indistinguishable from a real one."
        )
    return stream


def _ask(model_id: str, features: Mapping[str, Any], req: TaskRequest | None,
         campaign_id: str | None) -> SurrogateResponse:
    """One round trip, with every failure mode collapsed into `StreamUnavailable`."""
    request = SurrogateRequest(
        request_id=uuid.uuid4().hex,
        model_id=model_id,
        features=dict(features),
        design_campaign_id=campaign_id,
        node_id=getattr(req, "node_id", None),
    )
    stream = stream_for(model_id)
    try:
        response = stream.score(request)
    except StreamUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 -- every transport failure is the same refusal
        raise StreamUnavailable(
            f"the stream for {model_id!r} failed while scoring "
            f"{request.request_id}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(response, SurrogateResponse):
        # A stream answering the wrong shape is an outage with extra steps. Checked because
        # the alternative is an AttributeError three frames later, whose message names a
        # field rather than the seam that broke.
        raise StreamUnavailable(
            f"the stream for {model_id!r} returned {type(response).__name__}, not a "
            "SurrogateResponse: both sides must import asteer.contracts.surrogate"
        )
    if response.model_id != model_id:
        raise StreamUnavailable(
            f"asked {model_id!r} and was answered by {response.model_id!r}: a score "
            "attributed to the wrong model would supersede nothing and train the wrong "
            "corpus (CON-5)"
        )
    return response


def _payload(tool_id: str, response: SurrogateResponse, metrics: Mapping[str, float],
             passthrough: Any) -> dict[str, Any]:
    """The raw payload `post_process` gates and turns into a `TaskResult`.

    `model_versions` is keyed by metric name because that is what
    `surrogate_version_present` reads: the gate asks, per scored metric, whether anyone can
    say which weights produced it. Every entry here comes from one response, so they agree
    by construction -- the gate is checking the payload, not the stream.
    """
    version = f"{response.model_id}@v{response.version}"
    return {
        "result": tool_id,
        "count": 1,
        "outputs": {"structure": passthrough},
        "metrics": dict(metrics),
        "model_versions": {name: version for name in metrics},
    }


class _ScoreAgent(TaskAgent):
    """Shared body: read the design, ask the stream, report metrics, pass the design on.

    The two tools differ only in which model they ask and which metrics they derive, so the
    interesting behaviour -- the outage, the attribution, the omission -- is written and
    tested once. `structure` passes through unchanged, exactly as `filter_shape` and `packmin`
    do: a scoring stage annotates a design rather than producing a new artifact, and keeping
    the port means the chain can be reordered or extended without retyping it.
    """

    model_id: str = ""

    def _features(self, structure: Any, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _metrics(self, response: SurrogateResponse,
                 params: dict[str, Any]) -> dict[str, float]:
        raise NotImplementedError

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        structure = input_path(req, "structure")
        if not structure:
            # Not a root: `structure` is a declared required input, so the composer wired it
            # or gate 1 refused the graph. Checked anyway because a wired port can still
            # arrive empty when an upstream produced a ref with neither path nor value, and
            # scoring an empty path would spend a stream round trip on nothing and report it.
            raise ValueError(
                f"{self.spec.id}: the `structure` input is wired but empty, so there is "
                "nothing to score. The upstream stage produced an artifact ref carrying "
                "neither a path nor a value."
            )
        response = _ask(
            self.model_id,
            self._features(structure, params),
            req,
            params.get("design_campaign_id") or None,
        )
        return _payload(self.spec.id, response, self._metrics(response, params), structure)


class PreorgScoreAgent(_ScoreAgent):
    """Model B's client: the FK potential's score, and the three quantities MD measures.

    B is the one surrogate that must be resident from M2, because it is called once per
    particle per resampling event -- `asteer.fk` consumes exactly this.

    `induced_fit_risk` is **derived here and never measured**, which is decision L2: the
    three raw quantities are what `md_label` measures and what supersedes a prediction, and
    the risk scalar is a judgement over them. B reports it; nothing ingests it as a label.
    """

    model_id = MODEL_B

    def _features(self, structure: Any, params: dict[str, Any]) -> dict[str, Any]:
        return {"structure": str(structure),
                "pocket_selection": params.get("pocket_selection", "")}

    def _metrics(self, response: SurrogateResponse,
                 params: dict[str, Any]) -> dict[str, float]:
        out = {k: float(v) for k, v in response.values.items()}
        if (sigma := response.sigmas.get("preorg_rmsd")) is not None:
            out["sigma_preorg"] = float(sigma)
        return out


class AffDeltaScoreAgent(_ScoreAgent):
    """Model C's client: the corrected ΔG and the bound item 14 ranks on.

    C is a GP posterior update taking seconds, so it can be fitted and scored inside a task
    until its call rate justifies residency (ROME's plan: C resident from M4).
    """

    model_id = MODEL_C

    def _features(self, structure: Any, params: dict[str, Any]) -> dict[str, Any]:
        return {"structure": str(structure),
                "embedding_source": params.get("embedding_source", "")}

    def _metrics(self, response: SurrogateResponse,
                 params: dict[str, Any]) -> dict[str, float]:
        out = {k: float(v) for k, v in response.values.items()}
        sigma = response.sigmas.get("dg_corrected")
        if sigma is not None:
            out["sigma_dg"] = float(sigma)
        mean = out.get("dg_corrected")
        if mean is not None and sigma is not None:
            # Minimising ΔG, so the conservative bound is the UPPER one: mean + k*sigma is
            # the value a ranking should believe when the model is uncertain. Getting this
            # sign wrong would make an uncertain design look like the best in the batch.
            out["dg_lcb"] = mean + float(params.get("lcb_k", 1.0)) * float(sigma)
        # No else. An LCB with no sigma is the posterior mean under another name; omitting it
        # makes `metrics_reported` fail, which is the integrity failure it actually is.
        return out
