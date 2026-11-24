"""Assign a scaffold cluster to every design in a campaign tree.

**This is the half of J20 that does not exist anywhere else.** Model B is validated by a
leave-one-group-out over scaffold clusters; the cluster is a *property of the corpus*, so nothing
that sees one design at a time can compute it; and until this pass there was no corpus-level step
in the system at all. The consequence was measured rather than guessed: `_group_of` returned
`None` for every label ever written, `scaffold_split` returned `([], [])`, and the promotion gate
read *"holdout groups unknown"* as `INSUFFICIENT_EVIDENCE` (item 71).

**The rule lives in `asteer.grouping` and not here.** Single linkage at 0.80 over the design
sequence, with the measurement behind it in that module's docstring. Three repos have to agree on
it -- impress-a assigns it, ROME splits by it, AuCaM holds out by it -- and a rule implemented
where it is used is a rule that drifts across three checkouts invisibly (item 50).

**The sequence comes from the design's own structure**, through
`asteer.grouping.sequence_of_structure`, and that is a decision rather than a convenience:

* a live design has no sequence column. The historical corpus has `mpnn_best_sequence` because an
  analysis script wrote one; LigandMPNN's adapter selects the best candidate and records its
  *confidences*, not its sequence;
* the `.fa` the tool writes holds **every** candidate, and which one the design *is* was decided
  by the adapter's selection. The packed structure is the selected one, so it is the only source
  that cannot name the wrong candidate;
* and two derivations of "the sequence of this design" would digest to two cluster ids for one
  molecule, which is the class of silent disagreement the metric map and the embedding key
  already exist to prevent.

**It writes the property directly rather than through `ingest_measurement`.** A scaffold is not a
measurement: it is bookkeeping derived from the structure, nothing competes for the name, and
`ingest_measurement` would refuse the second pass as an authority tie -- so a re-run would
silently keep stale cluster ids, which is exactly what this pass exists to avoid.

**Re-running it is expected and is not idempotent in the ids.** A single-linkage component changes
as designs are added, so a cluster that gains a member gets a new content-addressed id. The pass
reports how many nodes were reassigned; every label row carries the sequence it was grouped from,
so an old row can be re-grouped rather than being stranded under an id nothing reproduces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from asteer.grouping import (
    DEFAULT_THRESHOLD,
    SCAFFOLD_PROPERTY,
    SEQUENCE_PROPERTY,
    group_sequences,
    sequence_of_structure,
)

from .artifacts import AUTHORITY_WEAK_PROXY, ArtifactRef, Property, PropertySource, SourceKind
from .types import ArtifactType

if TYPE_CHECKING:  # pragma: no cover
    from .tree import CampaignTree, DesignNode

__all__ = ["MEMBERS_FOR_A_FOLD", "ScaffoldPass", "assign_scaffolds"]

#: A cluster with fewer members than this cannot carry a fold: a group of two held out measures
#: a pair. J2's bar, restated here because this is where the number is reported.
MEMBERS_FOR_A_FOLD = 8

#: Which artifact a design's sequence is read from, in order of preference. A `Complex` is the
#: binder *and* its ligand, which is what a design is; a `Backbone` is accepted because an early
#: cycle may not have reached packing yet, and the protein chain of either reads the same.
STRUCTURE_TYPES = (ArtifactType.COMPLEX, ArtifactType.BACKBONE)

#: Where the two derived properties come from, for the provenance line. Not `SourceKind.MEASURED`
#: and not a high band: nothing measured a cluster, and nothing competes for these names.
_SOURCE = PropertySource(name="scaffold-pass", kind=SourceKind.PREDICTED,
                         authority=AUTHORITY_WEAK_PROXY, latency_class="inline")


@dataclass(frozen=True)
class ScaffoldPass:
    """What one pass over a tree did, in numbers a caller can refuse on.

    `unreadable` is a mapping rather than a count because a design with no structure is a
    *different* problem from a design whose structure would not parse, and the two are fixed in
    different places. Returned rather than logged: a caller that ignores it has silently
    declined to group part of its corpus, and that is the failure this whole episode is about.
    """

    rule: str
    threshold: float
    nodes: int
    sequenced: int
    groups: int
    usable_groups: int
    reassigned: int
    unreadable: dict[str, str] = field(default_factory=dict)

    @property
    def can_validate_a_round(self) -> bool:
        """Whether this grouping could produce a holdout the promotion gate accepts.

        Necessary and **not** sufficient: the gate counts groups *in the holdout*, and
        `holdout_indices` takes whole clusters largest-first, so four usable clusters in the
        corpus do not guarantee four in the holdout. A pass that reports `False` guarantees the
        round cannot return a verdict, which is the half worth knowing before a label is bought.
        """
        return self.usable_groups >= 4


def assign_scaffolds(tree: CampaignTree, *, threshold: float = DEFAULT_THRESHOLD,
                     members_for_a_fold: int = MEMBERS_FOR_A_FOLD) -> ScaffoldPass:
    """Cluster every design in `tree` and write the cluster and the sequence onto each node.

    Two properties per node, and both are needed. `scaffold` is what ROME's `_group_of` reads;
    `design_sequence` is what makes the grouping *recomputable* when the corpus grows, and
    `MeasurementBridge` refuses to copy a cluster onto a label without it.

    A node that already carries a sequence is believed rather than re-read: re-deriving it from
    a file that may have moved would be a second derivation of the same quantity, and the point
    of reading the structure is that there is exactly one.
    """
    nodes = list(tree)
    sequences: dict[str, str] = {}
    unreadable: dict[str, str] = {}

    for node in nodes:
        existing = _string_property(node, SEQUENCE_PROPERTY)
        if existing:
            sequences[node.id] = existing
            continue
        ref = _structure_of(node)
        if ref is None or not ref.path:
            unreadable[node.id] = (
                f"no {' or '.join(t.value for t in STRUCTURE_TYPES)} artifact with a path, so "
                "this design has no sequence to group by"
            )
            continue
        try:
            sequences[node.id] = sequence_of_structure(ref.path)
        except Exception as exc:  # noqa: BLE001 -- the reason is the deliverable, per node
            unreadable[node.id] = f"{ref.path}: {exc}"

    grouping = group_sequences(sequences.values(), threshold=threshold)
    assignment = grouping.assignment()

    reassigned = 0
    for node_id, sequence in sequences.items():
        cluster = assignment[sequence]
        node = tree.nodes[node_id]
        if _string_property(node, SCAFFOLD_PROPERTY) not in (cluster, ""):
            reassigned += 1
        node.properties[SEQUENCE_PROPERTY] = _property(SEQUENCE_PROPERTY, sequence)
        node.properties[SCAFFOLD_PROPERTY] = _property(SCAFFOLD_PROPERTY, cluster)

    return ScaffoldPass(
        rule=grouping.rule,
        threshold=threshold,
        nodes=len(nodes),
        sequenced=len(sequences),
        groups=grouping.n_groups,
        usable_groups=len(grouping.groups_of_at_least(members_for_a_fold)),
        reassigned=reassigned,
        unreadable=unreadable,
    )


def _structure_of(node: DesignNode) -> ArtifactRef | None:
    """The design's structure, preferring a `Complex` over a `Backbone`.

    By artifact *type* and never by port name: a port is named by whichever tool produced it
    (`structure`, `packed`, `result`), and a pass over a tree sees every tool's naming at once.
    """
    for wanted in STRUCTURE_TYPES:
        for ref in node.artifacts.values():
            if ref.type is wanted and ref.path:
                return ref
    return None


def _string_property(node: DesignNode, name: str) -> str:
    prop = node.properties.get(name)
    value: Any = prop.value if prop is not None else None
    return value.strip() if isinstance(value, str) else ""


def _property(name: str, value: str) -> Property:
    return Property(name=name, value=value, source=_SOURCE)
