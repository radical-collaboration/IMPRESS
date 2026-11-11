"""What counts as a passing design, how many of them are distinct, and the contrast.

Three pure functions' worth of definitions, kept away from the file reading in
`compare_arms.py` so that each can be checked against a hand-computed value.

**The tiers are frozen before any run, and they are tiered because the Goal is not reachable.**
`T1` is plumbing - every tool ran, no integrity gate failed, every declared metric reported.
`T2` is physics - `T1` plus every `PROD` threshold except the fold. `T3` is the Goal itself -
`T2` plus the fold bar and the ligand interface. The primary endpoint is distinct `T2` designs
per node-hour; `C_T3` is reported as the Goal's literal answer with a pre-registered
expectation of zero, because across every run this project has recorded `complex_plddt` is
0.426 / 0.486 / 0.507 against a 0.75 bound.

**Distinctness is clustered, not counted.** G7 measured that same-seed designs share length
exactly, have median Cα RMSD 2.4 Å between them, and are never byte-identical - so counting
unique sequences over-counts by roughly 3x. Clustering at an identity threshold collapses what
a re-draw of one seed can produce; the exact-identity count is reported beside it as the upper
bound, and the gap between the two is the figure that says how much of a yield is re-draws.

**The structural merge is honest about what it measures.** The pre-registration says "TM >= 0.8
on their Boltz complexes". There is no TM-score implementation here that could be validated, so
the merge takes a pluggable similarity and ships a Cα RMSD one - Kabsch-superposed, the same
measure `examples/small_molecule_binding` uses for its own ensemble work. `Clustering.criterion`
records which was applied, and a report that merged on RMSD must not be described as having
merged on TM.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: Tier 2: upstream's own calibrated `PROD` values, minus the fold. Verified against
#: `examples/small_molecule_binding/run_small_molecule_binding.py`'s PROD instance rather than
#: against a copy of it. `(metric, lower, upper)`; None is unbounded on that side.
T2_THRESHOLDS: tuple[tuple[str, float | None, float | None], ...] = (
    ("total_score", None, -250.0),
    ("fa_rep", None, 100.0),
    ("interaction_energy", None, -8.0),
    ("shape_complementarity", 0.55, None),
    ("ss_fraction", 0.5, None),
)

#: Tier 3 adds the fold. `complex_plddt` is PROD's `fold_min_plddt: 75.0` rescaled, because
#: that is a 0-100 figure and this metric is the 0-1 one. `ligand_iptm` is **stricter than
#: PROD**, which leaves that gate off entirely - every T3 figure has to say so.
T3_THRESHOLDS: tuple[tuple[str, float | None, float | None], ...] = (
    ("complex_plddt", 0.75, None),
    ("ligand_iptm", 0.4, None),
)

#: Default amino-acid identity above which two designs are the same cluster. The
#: pre-registration sets this from the smoke, as the 95th percentile of the pairwise identity
#: of SAME-SEED pairs, so that anything a re-draw of one seed can produce collapses to one
#: cluster. 0.90 until that measurement exists.
THETA = 0.90

#: Cα RMSD (Å) below which two equal-length designs are merged as one structure. Stands in for
#: the pre-registration's TM >= 0.8, and is NOT the same measure - see the module docstring.
#: G7 measured same-seed median Cα RMSD at 2.4 Å, so 2.5 collapses a re-draw of one seed.
MAX_CA_RMSD = 2.5


@dataclass
class Design:
    """One candidate: where it came from, what it measured, and its sequence."""

    run: str
    lineage: int
    metrics: dict[str, float] = field(default_factory=dict)
    sequence: str = ""
    #: Cα coordinates of the folded complex, when a structure was found on disk.
    ca: list[tuple[float, float, float]] = field(default_factory=list)
    integrity_ok: bool = True
    tools: tuple[str, ...] = ()
    #: Seconds from the arm's first task start to this design's last task finishing. The
    #: time-to-Nth figure is computed from these, and it is right-censored.
    finished_s: float = 0.0

    @property
    def key(self) -> tuple[str, int]:
        return (self.run, self.lineage)


def _within(value: Any, lo: float | None, hi: float | None) -> bool:
    """A finite value inside the bounds. A missing or non-finite one is never inside.

    `None` fails rather than passes, which is the whole point: a design the chain did not
    measure is not a design that met the threshold, and `interaction_energy` was missing from
    every run this project recorded.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if not math.isfinite(value):
        return False
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def tier_of(design: Design, chain: tuple[str, ...]) -> int:
    """0, 1, 2 or 3. Computed from the metrics on disk, never from a cached property.

    `chain` is the tools a complete design must have run, so a truncated lineage cannot reach
    T1 by having passed the gates of the three stages it did run.
    """
    if not design.integrity_ok:
        return 0
    if chain and not set(chain) <= set(design.tools):
        return 0
    declared = {m for m, _, _ in T2_THRESHOLDS + T3_THRESHOLDS}
    if any(not isinstance(design.metrics.get(m), (int, float))
           or not math.isfinite(design.metrics[m]) for m in declared):
        # NOT T1, and that is the frozen definition rather than a harsh reading: T1 is
        # "every tool ran, no integrity gate failed, **every declared metric reported**".
        # A design missing one has not finished being measured, and job 22692304 - this
        # project's best run, `6/6 tasks ok` - is exactly that case, because
        # `interaction_energy` was computed by nothing. Scoring it T1 would report the chain
        # as plumbed when the metric that measures binding was absent.
        return 0
    if not all(_within(design.metrics.get(m), lo, hi) for m, lo, hi in T2_THRESHOLDS):
        return 1
    if not all(_within(design.metrics.get(m), lo, hi) for m, lo, hi in T3_THRESHOLDS):
        return 2
    return 3


def identity(a: str, b: str) -> float:
    """Fraction of matching residues over the shorter sequence.

    The reference's own measure (`_seq_identity`), so a figure here and a figure there mean
    the same thing. Position-wise rather than aligned: these are designs for one fixed
    scaffold, so a gap would be a different experiment.
    """
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    return sum(1 for i in range(n) if a[i] == b[i]) / n


def ca_rmsd(p: list[tuple[float, float, float]],
            q: list[tuple[float, float, float]]) -> float | None:
    """Kabsch-superposed Cα RMSD, or None when the two cannot be compared.

    `None` for unequal lengths rather than a truncating comparison: two designs of different
    length are different designs, and comparing their first N atoms would merge a 60-mer into
    an 80-mer. Ported from the reference's `_kabsch_rmsd`, with numpy because it is already a
    transitive dependency and a hand-rolled SVD would be the thing to get wrong.
    """
    if not p or len(p) != len(q):
        return None
    import numpy as np

    a = np.asarray(p, dtype=float)
    b = np.asarray(q, dtype=float)
    a = a - a.mean(axis=0)
    b = b - b.mean(axis=0)
    u, _, vt = np.linalg.svd(a.T @ b)
    d = np.sign(np.linalg.det(u @ vt))
    rot = u @ np.diag([1.0, 1.0, d]) @ vt
    diff = a @ rot - b
    return float(np.sqrt((diff * diff).sum() / len(a)))


@dataclass
class Clustering:
    """Distinct designs, and how the count was arrived at."""

    clusters: list[list[Design]]
    theta: float
    criterion: str
    #: Designs that were merged into another, so the gap between `exact` and `distinct` is
    #: visible rather than inferred.
    exact: int = 0

    @property
    def distinct(self) -> int:
        return len(self.clusters)

    @property
    def merged(self) -> int:
        return self.exact - self.distinct


def cluster(designs: list[Design], theta: float = THETA,
            structural: Callable[[Design, Design], bool] | None = None) -> Clustering:
    """Single-linkage clusters at amino-acid identity >= `theta`, then a structural merge.

    Single linkage, which is the pre-registration's choice and the conservative one for this
    purpose: it merges a chain of near-identical designs that no single pair would merge, so
    it cannot over-count a lineage of small edits.

    `structural` merges two designs the identity test kept apart. Default: equal-length pairs
    within `MAX_CA_RMSD`, which stands in for the pre-registration's TM >= 0.8 and is not the
    same measure - `Clustering.criterion` records which ran.
    """
    criterion = "identity"
    if structural is None:
        def structural(a: Design, b: Design) -> bool:
            value = ca_rmsd(a.ca, b.ca)
            return value is not None and value <= MAX_CA_RMSD
        criterion = f"identity>={theta} or ca_rmsd<={MAX_CA_RMSD}A"

    exact = len({d.sequence for d in designs if d.sequence})
    parent = list(range(len(designs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(designs)):
        for j in range(i + 1, len(designs)):
            same = identity(designs[i].sequence, designs[j].sequence) >= theta
            if not same:
                same = structural(designs[i], designs[j])
            if same:
                parent[find(i)] = find(j)

    groups: dict[int, list[Design]] = {}
    for i, design in enumerate(designs):
        groups.setdefault(find(i), []).append(design)
    return Clustering(clusters=list(groups.values()), theta=theta,
                      criterion=criterion, exact=exact or len(designs))


# ---------------------------------------------------------------------------
# The contrast. Hand-computable on purpose: scipy is not a dependency.
# ---------------------------------------------------------------------------

@dataclass
class RateRatio:
    """One arm against the control, as a rate ratio with a confidence interval."""

    arm: str
    count: int
    exposure: float
    control_count: int
    control_exposure: float
    ratio: float
    low: float
    high: float
    p: float
    p_holm: float = 1.0

    @property
    def wins(self) -> bool:
        """The pre-registered decision rule, stated once and applied here.

        An arm wins iff its Holm-adjusted 95% interval lies **entirely above 1.3** and its
        point estimate is at least 1.5. Both, because an interval that clears 1.3 with a
        point estimate of 1.35 is a detection of something too small to act on at this
        allocation size.
        """
        return self.low > 1.3 and self.ratio >= 1.5 and self.p_holm < 0.05


def _normal_sf(z: float) -> float:
    """Upper-tail standard normal probability, from `math.erfc`. No scipy."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def rate_ratio(arm: str, count: int, exposure: float,
               control_count: int, control_exposure: float,
               z: float = 1.959964) -> RateRatio:
    """Poisson log rate ratio with a Wald interval.

    For two arms this is exactly the contrast the pre-registration's
    `log mu = b0 + b_arm + log(node_h)` reduces to, and it is three lines rather than a GLM:
    `log RR = log(c1/t1) - log(c0/t0)`, `se = sqrt(1/c1 + 1/c0)`.

    A zero count makes the interval undefined, so it is widened to the standard continuity
    correction of 0.5 rather than returning an infinity - and `count` keeps the raw value, so
    a reader can see that the correction applied.
    """
    c1 = count + (0.5 if count == 0 or control_count == 0 else 0.0)
    c0 = control_count + (0.5 if count == 0 or control_count == 0 else 0.0)
    if exposure <= 0 or control_exposure <= 0:
        return RateRatio(arm, count, exposure, control_count, control_exposure,
                         float("nan"), float("nan"), float("nan"), float("nan"))
    log_rr = math.log((c1 / exposure) / (c0 / control_exposure))
    se = math.sqrt(1.0 / c1 + 1.0 / c0)
    p = 2.0 * _normal_sf(abs(log_rr) / se) if se > 0 else 1.0
    return RateRatio(arm=arm, count=count, exposure=exposure,
                     control_count=control_count, control_exposure=control_exposure,
                     ratio=math.exp(log_rr), low=math.exp(log_rr - z * se),
                     high=math.exp(log_rr + z * se), p=p, p_holm=p)


def holm(ratios: list[RateRatio]) -> list[RateRatio]:
    """Holm-Bonferroni over the family, in place of a raw p per contrast.

    Three contrasts against one control is a family, and reporting three unadjusted p-values
    is how a 5% test becomes a 14% one. Holm rather than Bonferroni because it is uniformly
    more powerful and no harder to compute, and the adjusted values are kept **monotone**,
    which the textbook step-down requires and a naive loop gets wrong.
    """
    ordered = sorted(ratios, key=lambda r: r.p)
    n = len(ordered)
    running = 0.0
    for i, r in enumerate(ordered):
        running = max(running, min(1.0, (n - i) * r.p))
        r.p_holm = running
    return ratios


__all__ = ["MAX_CA_RMSD", "T2_THRESHOLDS", "T3_THRESHOLDS", "THETA", "Clustering", "Design",
           "RateRatio", "ca_rmsd", "cluster", "holm", "identity", "rate_ratio", "tier_of"]
