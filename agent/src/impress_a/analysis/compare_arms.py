"""Score four arms of one experiment, from the executor's own record and the files on disk.

**Never from an arm's own bookkeeping**, and that is sound here for a structural reason:
IMPRESS-A's provenance is written by the *executor*, not by a reasoner - `specs`, `stages`,
`graphs`, `tasks`, `results` and `transitions` all come from the single writer of campaign
state. A model cannot write a flattering record of itself. For a live model-B arm the LLM
transcript is read for decision-layer timing only, never for a yield, a cost or a quality
figure.

Two bugs in the sibling example's harness are regression-tested here rather than described,
because both flattered a multi-node arm and neither was visible in the output:

* it **charged every arm for one node**, so a two-node arm's cost per design read half what it
  was. Always charge the model's node to the experiment: `AllocNodes x gpus_per_node x
  Elapsed_h`, from `sacct`, never from the campaign's own clock.
* it divided a tool's task count by a **hardcoded 4 pipelines**, so a 32-pipeline run read
  126.2 rfd3 per pipeline-hour instead of 15.8.

And one lesson about reporting a number nobody measured: it once printed "at most nan% of the
billed GPU time had a GPU task running" as a finding, because `sacct` was unavailable and the
division went ahead anyway. A missing input is reported as missing.

**What the harness refuses to publish.** An arm that executed a mock tool, degraded to a
fallback, or disagrees with its siblings on the spec, the seed salt or the git sha is not
scored - it is named and dropped. Those are the two silent failures the four-arm design says
it most needs to exclude: a mock chain completes `6/6 tasks ok` with plausible metrics, and a
fallen-back model-C arm is byte-for-byte a model-D campaign.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tiers import Clustering, Design, RateRatio, cluster, holm, rate_ratio, tier_of

log = logging.getLogger(__name__)

#: The scoring window, from each arm's FIRST TASK START rather than from submission, so
#: unequal Dragon startup cannot bias an arm. The full-allocation figure is reported beside it.
T_CUT_H = 3.25

#: The reference's own `fastrelax` pass-rate band, from two scorings of the same workflow at
#: different commits: 64% healthy (job 22701168) and 49% degraded (23114772). A figure outside
#: it is worth a sentence either way.
FASTRELAX_BAND = (0.49, 0.64)

#: MPNN tasks per fold attempted, measured on the reference: 6.8 healthy, 13.0 degraded. This
#: project does no MPNN screening, so ~1.0 is expected - and THAT is the finding, not a defect.
MPNN_PER_FOLD_REFERENCE = (6.8, 13.0)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    """Every record in a JSONL file, skipping a truncated final line.

    A campaign killed by a wall clock leaves a half-written line, and a harness that raised on
    it could not score the run that most needs scoring.
    """
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("%s: skipping a truncated record", path.name)
    return out


@dataclass
class Allocation:
    """What the scheduler billed. From `sacct`, never from the campaign's own clock."""

    nodes: int = 0
    gpus_per_node: int = 0
    elapsed_h: float = 0.0
    source: str = "missing"

    @property
    def gpu_hours(self) -> float | None:
        """Billed GPU-hours, charging every node the arm held.

        `None` rather than 0.0 when the allocation is unknown: a cost per design divided by
        zero is an infinity, and divided by a guess is a figure nobody measured.
        """
        if self.nodes <= 0 or self.gpus_per_node <= 0 or self.elapsed_h <= 0:
            return None
        return self.nodes * self.gpus_per_node * self.elapsed_h


@dataclass
class Arm:
    """One campaign directory, loaded."""

    name: str
    root: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    graphs: list[dict[str, Any]] = field(default_factory=list)
    stages: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    ledger: list[dict[str, Any]] = field(default_factory=list)
    allocation: Allocation = field(default_factory=Allocation)

    @property
    def model(self) -> str:
        return str(self.manifest.get("model") or "?")


def load_arm(root: Path | str, name: str | None = None) -> Arm:
    """One arm from its run directory. Missing files are absent, never fatal."""
    root = Path(root)
    prov = root / "provenance"
    arm = Arm(
        name=name or root.name,
        root=root,
        manifest=json.loads((root / "manifest.json").read_text())
        if (root / "manifest.json").is_file() else {},
        tasks=_jsonl(prov / "tasks.jsonl"),
        results=_jsonl(prov / "results.jsonl"),
        graphs=_jsonl(prov / "graphs.jsonl"),
        stages=_jsonl(prov / "stages.jsonl"),
        transitions=_jsonl(prov / "transitions.jsonl"),
        decisions=_jsonl(prov / "decisions.jsonl"),
        ledger=_jsonl(root / "jobs" / "ledger.jsonl"),
    )
    arm.allocation = _allocation(root, arm.manifest)
    return arm


def _allocation(root: Path, manifest: dict[str, Any]) -> Allocation:
    """Billed nodes and elapsed time, from `sacct --json` written inside the job.

    Written inside the job deliberately: querying `sacct` afterwards is how a day was lost to
    a figure nobody could reproduce, and a job's own record of what it was given cannot drift.
    """
    gpus = int(manifest.get("gpus_per_node") or 4)
    path = root / "sacct.json"
    if not path.is_file():
        return Allocation(nodes=int(manifest.get("nodes") or 0), gpus_per_node=gpus,
                          source="missing")
    try:
        doc = json.loads(path.read_text())
        job = (doc.get("jobs") or [{}])[0]
        nodes = int(job.get("allocation_nodes") or job.get("nodes") or 0)
        seconds = float((job.get("time") or {}).get("elapsed") or 0)
    except (ValueError, KeyError, IndexError, TypeError) as bad:
        log.warning("%s: unreadable (%s)", path.name, bad)
        return Allocation(gpus_per_node=gpus, source=f"unreadable: {bad}")
    return Allocation(nodes=nodes, gpus_per_node=gpus, elapsed_h=seconds / 3600.0,
                      source="sacct")


# ---------------------------------------------------------------------------
# Designs: one per (run, lineage), measured from the executor's own task record.
# ---------------------------------------------------------------------------

def designs_of(arm: Arm, chain: tuple[str, ...] = ()) -> list[Design]:
    """One `Design` per (run, lineage), built from `tasks` provenance.

    `tasks` rather than `results` because it carries the per-task detail - which tools ran,
    which gates failed, when each finished - and the join is the executor's own `lineage`
    field rather than an inference from a task id's shape.
    """
    by_key: dict[tuple[str, int], Design] = {}
    t0 = _first_start(arm)
    for row in arm.tasks:
        if row.get("lineage") is None:
            continue
        key = (str(row.get("run")), int(row["lineage"]))
        design = by_key.setdefault(key, Design(run=key[0], lineage=key[1]))
        if row.get("failed"):
            design.integrity_ok = False
            continue
        design.tools = tuple(sorted(set(design.tools) | {str(row.get("tool"))}))
        design.metrics.update({k: v for k, v in (row.get("metrics") or {}).items()
                               if isinstance(v, (int, float))})
        # An INTEGRITY failure only. An acceptance failure is a weak design, which is what
        # the tiers are for - counting it here would make every sub-threshold design a
        # broken one and T1 would measure nothing.
        if row.get("qc") == "fail" and _integrity_failed(row):
            design.integrity_ok = False
        if (finished := _epoch(row.get("finished_at"))) and t0:
            design.finished_s = max(design.finished_s, finished - t0)
    for design in by_key.values():
        design.sequence, design.ca = _sequence_and_structure(arm, design)
    return [by_key[k] for k in sorted(by_key)]


def _integrity_failed(row: dict[str, Any]) -> bool:
    """Whether a task's failed gates include an integrity one.

    Read from the gate LABELS, which `gates.evaluate` suffixes with the role only when two
    gates would share a name - so an unsuffixed `metric_in_range[x]` may be either. Anything
    that is not unambiguously an acceptance label counts as integrity, which is the
    conservative reading and the one decision 0013 asks for.
    """
    return any("(acceptance)" not in g and not g.startswith("metric_in_range[")
               or "(integrity)" in g
               for g in (row.get("failed_gates") or []))


def _first_start(arm: Arm) -> float:
    starts = [s for row in arm.tasks if (s := _epoch(row.get("started_at")))]
    return min(starts) if starts else 0.0


def _epoch(value: Any) -> float:
    if not value:
        return 0.0
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return 0.0


def _sequence_and_structure(arm: Arm, design: Design
                            ) -> tuple[str, list[tuple[float, float, float]]]:
    """A design's sequence from the LigandMPNN FASTA on disk, and its folded Cα coordinates.

    From the FILE, which is the pre-registration's requirement: an arm's own count of distinct
    sequences is the one figure it could inflate without lying about anything else. The paths
    come from the executor's job ledger, so the harness is not guessing a directory layout.

    **Matched by (run, LINEAGE), not by run.** Matching on the run alone gave every lineage of
    a width-N run the first lineage's sequence, so N independent designs clustered as one and
    every arm's distinct count was understated by up to its own width - a bug in the direction
    that makes a comparison look tighter than it is. The lineage comes from the executor's own
    `tasks` field rather than from parsing a task id's shape.
    """
    mine = {row["task"] for row in arm.tasks
            if row.get("run") == design.run and row.get("lineage") == design.lineage
            and row.get("task")}
    sequence, ca = "", []
    for entry in arm.ledger:
        outcome = entry.get("outcome") or {}
        if outcome.get("run_id") != design.run:
            continue
        for task in outcome.get("tasks") or []:
            if task.get("task_id") not in mine:
                continue
            for ref in (task.get("outputs") or {}).values():
                path = (ref or {}).get("path") if isinstance(ref, dict) else None
                if not path:
                    continue
                p = Path(path)
                if not p.is_file():
                    continue
                if p.suffix in (".fa", ".fasta") and not sequence:
                    sequence = _best_fasta_record(p)
                elif p.suffix == ".pdb" and not ca:
                    ca = _ca_coords(p)
    return sequence, ca


def _best_fasta_record(path: Path) -> str:
    """The highest-confidence record in a LigandMPNN FASTA.

    Every record, not the first line: real LigandMPNN writes the template record plus every
    designed candidate into one file, and reading line one was the reference's own recorded
    bug - `analysis_sequence` "silently never compared MPNN candidates against each other".
    """
    best, best_score = "", None
    header, seq = "", []
    for line in path.read_text().splitlines():
        if line.startswith(">"):
            if seq and best_score is None or (seq and _confidence(header) is not None
                                              and (best_score is None
                                                   or _confidence(header) > best_score)):
                best, best_score = "".join(seq), _confidence(header)
            header, seq = line, []
        elif line.strip():
            seq.append(line.strip())
    if seq:
        score = _confidence(header)
        if best_score is None or (score is not None and score > best_score):
            best = "".join(seq)
    return best


def _confidence(header: str) -> float | None:
    import re
    m = re.search(r"overall_confidence=([0-9.]+)", header)
    return float(m.group(1)) if m else None


def _ca_coords(path: Path) -> list[tuple[float, float, float]]:
    out = []
    for line in path.read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")) and line[12:16].strip() == "CA":
            try:
                out.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------
# The figures.
# ---------------------------------------------------------------------------

@dataclass
class Figures:
    """Everything published for one arm. `None` means "not measured", never 0.0."""

    arm: str
    model: str
    draws: int = 0
    t1: int = 0
    t2: int = 0
    t3: int = 0
    distinct_t2: int = 0
    distinct_t3: int = 0
    exact_sequences: int = 0
    merged_by_clustering: int = 0
    cluster_criterion: str = ""
    gpu_hours: float | None = None
    gpu_hours_per_t2: float | None = None
    t2_per_node_hour: float | None = None
    time_to_tenth_h: float | None = None
    censored_at_h: float | None = None
    integrity_pass_rate: float | None = None
    acceptance_pass_rate: float | None = None
    fastrelax_pass_rate: float | None = None
    mpnn_per_fold: float | None = None
    cost_ratio: dict[str, float] = field(default_factory=dict)
    refusals_by_gate: dict[str, int] = field(default_factory=dict)
    admissions_under_scrutiny: int = 0
    trust_events: dict[str, int] = field(default_factory=dict)
    stagnation_trace: list[int] = field(default_factory=list)
    decision_share: float | None = None
    mock_tasks: int = 0
    degraded_events: int = 0
    directives: int = 0
    cycles: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        """Whether a yield figure from this arm may be reported at all.

        A mock task or a degraded decision voids it. Both are silent in a campaign log: a mock
        chain completes with plausible metrics, and a fallen-back arm is byte-for-byte a
        model-D campaign.
        """
        return self.mock_tasks == 0 and self.degraded_events == 0


MOCK_TOOLKIT_TOOLS = ("mock_generate", "mock_design", "mock_fold", "mock_score",
                      "mock_noodle", "mock_join")


def score(arm: Arm, chain: tuple[str, ...] = (), theta: float | None = None,
          t_cut_h: float = T_CUT_H) -> Figures:
    """Every published figure for one arm."""
    from .tiers import THETA

    f = Figures(arm=arm.name, model=arm.model)
    all_designs = designs_of(arm, chain)
    f.draws = len(all_designs)
    f.cycles = len({row.get("cycle") for row in arm.tasks if row.get("cycle") is not None})

    tiers = {d.key: tier_of(d, chain) for d in all_designs}
    f.t1 = sum(1 for t in tiers.values() if t >= 1)
    f.t2 = sum(1 for t in tiers.values() if t >= 2)
    f.t3 = sum(1 for t in tiers.values() if t >= 3)

    t2_designs = [d for d in all_designs if tiers[d.key] >= 2]
    t3_designs = [d for d in all_designs if tiers[d.key] >= 3]
    clustering = cluster(t2_designs, theta if theta is not None else THETA)
    f.distinct_t2 = clustering.distinct
    f.distinct_t3 = cluster(t3_designs, theta if theta is not None else THETA).distinct
    f.exact_sequences = clustering.exact
    f.merged_by_clustering = max(0, clustering.merged)
    f.cluster_criterion = clustering.criterion

    f.gpu_hours = arm.allocation.gpu_hours
    if f.gpu_hours is None:
        f.notes.append(
            f"allocation unknown ({arm.allocation.source}): no cost-per-design or "
            f"per-node-hour figure can be computed, and none is reported")
    else:
        node_hours = arm.allocation.nodes * arm.allocation.elapsed_h
        f.gpu_hours_per_t2 = (f.gpu_hours / f.distinct_t2) if f.distinct_t2 else None
        f.t2_per_node_hour = (f.distinct_t2 / node_hours) if node_hours > 0 else None

    f.time_to_tenth_h, f.censored_at_h = _time_to_nth(t2_designs, 10, t_cut_h)
    f.integrity_pass_rate, f.acceptance_pass_rate = _pass_rates(arm)
    f.fastrelax_pass_rate = _tool_pass_rate(arm, "fastrelax")
    f.mpnn_per_fold = _mpnn_per_fold(arm)
    f.cost_ratio = _cost_ratio(arm)
    f.refusals_by_gate = _refusals(arm)
    f.admissions_under_scrutiny = sum(1 for g in arm.graphs
                                      if g.get("rejected") is None
                                      and g.get("trusted") is False)
    f.trust_events = _counts(arm.transitions, ("pattern_promoted", "pattern_demoted"))
    f.stagnation_trace = [int(t["stagnant"]) for t in arm.transitions
                          if isinstance(t.get("stagnant"), int)]
    f.decision_share = _decision_share(arm)
    f.mock_tasks = sum(1 for row in arm.tasks if row.get("tool") in MOCK_TOOLKIT_TOOLS)
    f.degraded_events = sum(
        1 for t in arm.transitions
        if t.get("event") in ("oracle_degraded", "reasoner_degraded", "caller_timeout"))
    f.directives = sum(1 for t in arm.transitions if t.get("event") == "steered")

    if f.mock_tasks:
        f.notes.append(
            f"{f.mock_tasks} task(s) ran a MOCK tool: this arm is not published. A mock chain "
            f"completes `6/6 tasks ok` with plausible metrics and invented designs")
    if f.degraded_events:
        f.notes.append(
            f"{f.degraded_events} degraded decision(s): this arm's yield is void. A fallen-back "
            f"arm is byte-for-byte a model-D campaign and invisible in the campaign log")
    return f


def _time_to_nth(designs: list[Design], n: int,
                 t_cut_h: float) -> tuple[float | None, float | None]:
    """Hours to the Nth passing design, RIGHT-CENSORED at the common window.

    `(None, t_cut)` when fewer than N arrived - never 0.0 and never null. "No tenth design"
    and "the tenth design arrived instantly" are opposite findings and a null would be read
    as either.
    """
    times = sorted(d.finished_s / 3600.0 for d in designs if d.finished_s)
    if len(times) >= n and times[n - 1] <= t_cut_h:
        return times[n - 1], None
    return None, t_cut_h


def _pass_rates(arm: Arm) -> tuple[float | None, float | None]:
    """Stage pass rates, split by what a failure means (decision 0013)."""
    ran = [row for row in arm.tasks if not row.get("failed") and row.get("tool")]
    if not ran:
        return None, None
    integrity = sum(1 for row in ran if not _integrity_failed(row))
    accepted = sum(1 for row in ran if row.get("qc") == "pass")
    return integrity / len(ran), accepted / len(ran)


def _tool_pass_rate(arm: Arm, tool: str) -> float | None:
    rows = [row for row in arm.tasks if row.get("tool") == tool and not row.get("failed")]
    if not rows:
        return None
    return sum(1 for row in rows if row.get("qc") == "pass") / len(rows)


def _mpnn_per_fold(arm: Arm) -> float | None:
    """MPNN tasks per fold ATTEMPTED. No hardcoded divisor - that was the sibling's bug.

    The reference spent 6.8 healthy and 13.0 degraded; this project does no MPNN screening, so
    ~1.0 is expected and that is the finding rather than a defect.
    """
    mpnn = sum(1 for row in arm.tasks if row.get("tool") == "ligandmpnn_design")
    folds = sum(1 for row in arm.tasks if row.get("tool") == "boltz_predict")
    return (mpnn / folds) if folds else None


def _cost_ratio(arm: Arm) -> dict[str, float]:
    """Sum measured over sum declared, per tool and dimension. The figure that closes G8."""
    out: dict[str, float] = {}
    sums: dict[str, tuple[float, float]] = {}
    for row in arm.tasks:
        tool = row.get("tool")
        for dim, est in (row.get("cost_estimated") or {}).items():
            measured = float((row.get("cost_measured") or {}).get(dim, 0.0))
            key = f"{tool}.{dim}"
            got, want = sums.get(key, (0.0, 0.0))
            sums[key] = (got + measured, want + float(est))
    for key, (measured, declared) in sums.items():
        if declared > 0:
            out[key] = round(measured / declared, 4)
    return out


def _refusals(arm: Arm) -> dict[str, int]:
    out: dict[str, int] = {}
    for record in arm.graphs + arm.stages:
        rejected = record.get("rejected")
        if isinstance(rejected, dict) and rejected.get("gate"):
            gate = str(rejected["gate"])
            out[gate] = out.get(gate, 0) + 1
    return out


def _counts(records: list[dict[str, Any]], events: tuple[str, ...]) -> dict[str, int]:
    return {e: sum(1 for r in records if r.get("event") == e) for e in events}


def _decision_share(arm: Arm) -> float | None:
    """Decision-layer share of wall clock, when the decisions were timed.

    `None` when they were not. The sibling could not measure this at all - no `local`-backend
    spans were identifiable in its telemetry - and reporting a zero would say the decisions
    were free.
    """
    spans = [float(d["elapsed_s"]) for d in arm.decisions
             if isinstance(d.get("elapsed_s"), (int, float))]
    if not spans or arm.allocation.elapsed_h <= 0:
        return None
    return sum(spans) / (arm.allocation.elapsed_h * 3600.0)


# ---------------------------------------------------------------------------
# The comparison.
# ---------------------------------------------------------------------------

@dataclass
class Comparison:
    figures: list[Figures] = field(default_factory=list)
    contrasts: list[RateRatio] = field(default_factory=list)
    control: str = "D"
    blocked: list[str] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return not self.blocked and all(f.publishable for f in self.figures)

    def report(self) -> str:
        lines = ["arm  model  draws   T1   T2   T3  distinct  GPU-h/T2  T2/node-h  "
                 "time-to-10th"]
        for f in self.figures:
            lines.append(
                f"{f.arm[:4]:4s} {f.model:>5s} {f.draws:6d} {f.t1:4d} {f.t2:4d} {f.t3:4d} "
                f"{f.distinct_t2:9d}  {_num(f.gpu_hours_per_t2):>8s}  "
                f"{_num(f.t2_per_node_hour):>9s}  {_censored(f):>12s}")
        if self.contrasts:
            lines.append("")
            lines.append(f"contrast vs {self.control}: rate ratio [95% CI]  p(Holm)  verdict")
            for c in self.contrasts:
                lines.append(
                    f"  {c.arm:4s} {c.ratio:6.2f} [{c.low:5.2f}, {c.high:6.2f}]  "
                    f"{c.p_holm:7.3f}  {'WINS' if c.wins else 'no'}")
        for f in self.figures:
            for note in f.notes:
                lines.append(f"  [{f.arm}] {note}")
        for reason in self.blocked:
            lines.append(f"  BLOCKED: {reason}")
        return "\n".join(lines)


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _censored(f: Figures) -> str:
    if f.time_to_tenth_h is not None:
        return f"{f.time_to_tenth_h:.2f} h"
    return f"> {f.censored_at_h:.2f} h (cens)"


def one_variable_guard(arms: list[Arm]) -> list[str]:
    """Reasons the arms are not comparable. Empty means they are.

    Every one of these is something the experiment holds identical by design, so a difference
    is not a caveat to note in the discussion - it means the comparison is measuring two
    things at once and must not be published.
    """
    blocked = []
    for key, what in (("git_sha", "git commit"), ("seed_salt", "seed salt"),
                      ("campaign_path", "campaign spec"), ("prereg_sha", "pre-registration")):
        values = {a.name: a.manifest.get(key) for a in arms}
        distinct = {v for v in values.values() if v}
        if len(distinct) > 1:
            blocked.append(f"arms disagree on {what}: {values}")
        elif not distinct:
            blocked.append(f"no arm records its {what}, so one-variable cannot be checked")
    if any(a.manifest.get("git_dirty") in (True, "true", "True") for a in arms):
        blocked.append("an arm ran from a dirty working tree, so its code is unrecoverable")
    return blocked


def compare(arms: list[Arm], chain: tuple[str, ...] = (), control: str = "D",
            theta: float | None = None, t_cut_h: float = T_CUT_H) -> Comparison:
    """Score every arm and contrast each against the control."""
    figures = [score(a, chain, theta, t_cut_h) for a in arms]
    comparison = Comparison(figures=figures, control=control,
                            blocked=one_variable_guard(arms))

    base = next((f for f in figures if f.model == control), None)
    if base is None:
        comparison.blocked.append(
            f"no arm ran the control model {control!r}, so there is nothing to contrast "
            f"against - the control is what every other arm's cost is justified by")
        return comparison
    base_exposure = _node_hours(arms, base)
    if base_exposure is None:
        comparison.blocked.append(
            "the control arm's allocation is unknown, so no rate ratio is defined")
        return comparison

    contrasts = []
    for f in figures:
        if f.model == control or not f.publishable:
            continue
        exposure = _node_hours(arms, f)
        if exposure is None:
            f.notes.append("allocation unknown: no contrast computed")
            continue
        contrasts.append(rate_ratio(f.arm, f.distinct_t2, exposure,
                                    base.distinct_t2, base_exposure))
    comparison.contrasts = holm(contrasts)
    return comparison


def _node_hours(arms: list[Arm], f: Figures) -> float | None:
    arm = next((a for a in arms if a.name == f.arm), None)
    if arm is None or arm.allocation.gpu_hours is None:
        return None
    value = arm.allocation.nodes * arm.allocation.elapsed_h
    return value if value > 0 else None


def mde(counts: list[int]) -> float | None:
    """The smallest rate ratio this experiment could detect, from the counts it got.

    Stated because the design's own analysis says it must be: at an expected `C_T2` near 14 the
    interval spans roughly x/÷ 2.0, so only a >= 2.2x difference is detectable, one allocation
    per arm gives zero degrees of freedom for overdispersion, and A11's measured 3.2x wall-time
    swing means between-allocation variance is not estimable here. The honest claim is the
    interval, not the p-value.
    """
    usable = [c for c in counts if c > 0]
    if len(usable) < 2:
        return None
    se = math.sqrt(sum(1.0 / c for c in usable[:2]))
    return math.exp(1.959964 * se)


__all__ = ["FASTRELAX_BAND", "MOCK_TOOLKIT_TOOLS", "MPNN_PER_FOLD_REFERENCE", "T_CUT_H",
           "Allocation", "Arm", "Clustering", "Comparison", "Figures", "compare",
           "designs_of", "load_arm", "mde", "one_variable_guard", "score"]
