"""Core vocabulary: compute patterns and the artifact type lattice.

Both come from Phase 1. `Pattern` is Part A's taxonomy, organised by *scheduling
implication*. `ArtifactType` is Part B's scientific type lattice, which is what makes
runtime graph composition checkable (Part B doc 05, gate 1).
"""
from __future__ import annotations

from enum import Enum


class Pattern(str, Enum):
    """Compute patterns. Dispatch depends on these, not on what a tool computes."""

    P1 = "P1"  # GPU-node-local, in-job
    P2 = "P2"  # CPU-parallel fan-out, in-job
    P3 = "P3"  # MPI multi-node, in-job
    P4 = "P4"  # external HPC job - durable ledger, outlives the agent
    P5 = "P5"  # network service over HTTPS
    P6 = "P6"  # in-process - MUST NEVER be scheduled
    P7 = "P7"  # composite pipeline
    P8 = "P8"  # external experiment (robotic lab) - forward-declared, unused

    @property
    def is_inline(self) -> bool:
        """P6 is inlined by the composer; scheduling it is a composer bug."""
        return self is Pattern.P6

    @property
    def is_external(self) -> bool:
        """P4/P8 outlive the agent and need a durable ledger entry."""
        return self in (Pattern.P4, Pattern.P8)


class ArtifactType(str, Enum):
    """Scientific artifact types.

    Deliberately scientific rather than file-format-based. Two distinctions carry real
    weight (Part B doc 04):
      * SMALL_MOLECULE vs PARAMETERIZED - so an unparameterised ligand reaching a
        force field is a *type error at composition time*, not silent corruption.
      * BACKBONE vs COMPLEX - so an interface scorer cannot be handed a monomer.
    """

    BACKBONE = "Backbone"
    COMPLEX = "Complex"
    ENSEMBLE = "Ensemble"
    PROTEIN_SEQUENCE = "ProteinSequence"
    SEQUENCE_SET = "SequenceSet"
    SMALL_MOLECULE = "SmallMolecule"
    PARAMETERIZED = "Parameterized"
    MSA = "MSA"
    STRUCTURAL_HIT = "StructuralHit"
    METRIC = "Metric"
    METRIC_SET = "MetricSet"
    TRAJECTORY = "Trajectory"

    def unifies_with(self, other: "ArtifactType") -> bool:
        """Can a value of type `self` be consumed where `other` is required?"""
        if self is other:
            return True
        # A Complex satisfies a Backbone requirement (it contains one); not the reverse.
        if self is ArtifactType.COMPLEX and other is ArtifactType.BACKBONE:
            return True
        if self is ArtifactType.METRIC_SET and other is ArtifactType.METRIC:
            return True
        return False


class Verdict(str, Enum):
    CORE = "Core"
    RECOMMENDED = "Recommended"
    DEFER = "Defer"
    REJECT = "Reject"
