"""Five figures from one mock lab, in the group's house style.

`mock_lab.py` runs the campaigns and flattens them; this module only reads its CSVs, so a
figure can be redrawn without re-running anything and a broken figure never costs a sweep.
matplotlib lives here and nowhere else in the package - it is an optional extra
(`pip install -e ".[figures]"`), and the sweep and collect stages must work without it.

**Two kinds of entity, two colour rules, and mixing them would be a lie.** The four ARMS are
the compared entities: each owns one hue from `plot_style.RUN_STYLES` and keeps it across
every figure, including where the ranking inverts. A SWEEP is not an entity - it is one
measure of the surrogate walked along a knob - so it is drawn in `NEUTRAL_SERIES`, with the
arms marked on it where they happen to sit. Drawing a sweep in an arm's hue would claim the
line was that arm.

**What these figures are licensed to claim.** The response surfaces are statements about the
surrogate's own arithmetic, not about chemistry: every metric is a seeded draw. The campaign
behaviour - cycles taken, gate that refused what, where the wall clock went, whether the
front filled - is measured from the executor's own provenance and is as real here as on a
GPU, because it is the same executor. `mock_lab.DISCLAIMER` goes on every figure for that
reason, from the module rather than from a caption a reader could lose in a slide.

The bands are **population spread, +/- 2 sigma over lineages**, never a standard error. At 24
lineages a cell the two differ by about five times, and a band read as a confidence interval
would make two adjacent knob settings look separated when they are not.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from . import plot_style as ps
from .mock_lab import DISCLAIMER, OBJECTIVES, SWEEPS, read_table

log = logging.getLogger(__name__)

#: The six stages of the chain, in order, with the short labels a stage axis can carry.
CHAIN = [("mock_rfd3_design", "rfd3\ndesign"), ("mock_mpnn_design", "mpnn\ndesign"),
         ("mock_packmin", "pack\nmin"), ("mock_fastrelax", "fast\nrelax"),
         ("mock_filter_shape", "filter\nshape"), ("mock_boltz_predict", "boltz\npredict")]

#: Which arm's `difficulty` sits where on the swept axis. `rescued` is deliberately absent:
#: it carries the same 0.55 as `hard` and differs only in three other knobs, so marking it on
#: this line would put it at a point the line does not describe.
ARMS_ON_DIFFICULTY = {"baseline": 0.25, "hard": 0.55, "hopeless": 0.85}

#: The control plane's segments, outermost first, and how to name them on a legend.
PHASES = [("plan", "plan"), ("admit", "validate"), ("dispatch", "dispatch"),
          ("busy", "tools running"), ("exec_wait", "scheduling wait"),
          ("absorb", "QC + ingest"), ("teardown", "stop + teardown")]


# -- helpers -----------------------------------------------------------------------------

#: House line + marker geometry in one dict. Both `LINE_KW` and `MARKER_KW` set `zorder`, so
#: passing them as two `**` expansions is a TypeError; merged once here rather than at each of
#: the call sites that draws the neutral sweep line.
NEUTRAL_KW = dict({**ps.LINE_KW, **ps.MARKER_KW}, color=ps.NEUTRAL_SERIES, marker="o",
                  markeredgecolor=ps.NEUTRAL_SERIES)


def _band(values: list[float]) -> tuple[float, float, float]:
    """Mean and +/- 2 sigma POPULATION spread. Fewer than two readings has no spread, which
    is reported as a zero-width band rather than as a NaN that silently drops the point."""
    arr = np.asarray(values, dtype=float)
    m = float(arr.mean())
    sd = float(arr.std(ddof=0)) if arr.size > 1 else 0.0
    return m, m - 2 * sd, m + 2 * sd


def _curve(rows: list[dict[str, Any]], knob: str, metric: str
           ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[int]]:
    """x, mean, lo, hi, n for one knob against one metric, over the sweep rows only."""
    sub = [r for r in rows if r.get("knob") == knob and r.get(metric) is not None]
    xs = sorted({float(r["value"]) for r in sub})
    mean, lo, hi, n = [], [], [], []
    for x in xs:
        vals = [float(r[metric]) for r in sub if float(r["value"]) == x]
        m, a, b = _band(vals)
        mean.append(m)
        lo.append(a)
        hi.append(b)
        n.append(len(vals))
    return np.array(xs), np.array(mean), np.array(lo), np.array(hi), n


def _bars(manifest_objectives: dict[str, Any], metric: str) -> float | None:
    """The campaign's acceptance threshold for one objective, or None if it ranks."""
    o = (manifest_objectives or {}).get(metric) or {}
    return o.get("min") if o.get("min") is not None else o.get("max")


def _arm_legend(fig, arms: list[str], y: float = 0.925) -> None:
    """One legend for the arms, at figure level.

    Inside an axes it landed on the data in three of the four figures - on `hopeless`'s trace,
    on the funnel's floor - and every alternative corner was occupied in at least one arm's
    data. At figure level it is in nobody's way and it serves every panel at once, which a
    per-axes legend repeated four times does not.
    """
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=ps.style_for(a).color, marker=ps.style_for(a).marker,
                      markerfacecolor="white", markeredgecolor=ps.style_for(a).color,
                      markeredgewidth=1.2, linewidth=1.8, label=ps.style_for(a).label)
               for a in arms]
    # Two columns, not four. The four labels carry their knob settings, and on one row they
    # were wider than a 15-inch canvas and clipped at both ends.
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, y),
               ncol=2, fontsize="small", frameon=True,
               edgecolor=ps.GRID, framealpha=0.9)


def _neutral_patches(entries: list[tuple[str, dict[str, Any]]]):
    """Legend proxies in the NEUTRAL grey for a distinction that is not an entity.

    Drawn in an arm's hue, a "solid vs hatched" key reads as "this is the blue arm", which is
    the one thing the palette's colour-follows-the-entity rule forbids.
    """
    from matplotlib.patches import Patch
    return [Patch(facecolor=ps.NEUTRAL_SERIES, edgecolor="white", label=label, **kw)
            for label, kw in entries]


def _save(fig, out: Path, name: str, note: str) -> Path:
    # Wrapped by hand. `fig.text(wrap=True)` wraps to the FIGURE width, and at 16.5 inches
    # that is one line running off both edges before it ever breaks.
    ps.caption(fig, _wrap(f"{note}  |  {DISCLAIMER}", 150), y=0.006, bottom=0.17)
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    fig.savefig(path)
    log.info("wrote %s", path)
    return path


# -- F1: the science metric ensembles, against the surrogate's own dial -------------------

def fig_metric_ensembles(lin: list[dict[str, Any]], objectives: dict[str, Any],
                         out: Path) -> Path:
    """Each campaign objective's ensemble against `difficulty`, with its acceptance bar.

    Four panels rather than four lines, because the four objectives are four measures on
    three different scales and one axis for all of them would be the two-scales mistake with
    extra steps. Each panel keeps its own y-label for the same reason.
    """
    import matplotlib.pyplot as plt
    ps.apply_rcparams()
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.6), sharex=True)
    for ax, metric in zip(axes.flat, OBJECTIVES, strict=True):
        x, m, lo, hi, n = _curve(lin, "difficulty", metric)
        if not len(x):
            continue
        ax.fill_between(x, lo, hi, color=ps.NEUTRAL_SERIES, alpha=ps.BAND_ALPHA,
                        linewidth=0, zorder=ps.Z["band"])
        ax.plot(x, m, **NEUTRAL_KW)
        bar = _bars(objectives, metric)
        if bar is not None:
            ax.axhline(bar, color=ps.INK_SECONDARY, linestyle=(0, (5, 3)), linewidth=1.2,
                       zorder=ps.Z["line"] - 1)
            ax.annotate(f"acceptance {bar:g}", xy=(x[0], bar), xytext=(2, 4),
                        textcoords="offset points", fontsize="small",
                        color=ps.INK_SECONDARY, zorder=ps.Z["annot"])
        for arm, dv in ARMS_ON_DIFFICULTY.items():
            if dv not in set(x):
                continue
            st = ps.style_for(arm)
            y = float(m[list(x).index(dv)])
            ax.plot([dv], [y], marker=st.marker, color=st.color, markersize=11,
                    markerfacecolor="white", markeredgewidth=2.2, zorder=ps.Z["annot"])
            if metric == "complex_plddt":
                ps.direct_label(ax, dv, y, st.short, st.color, dx=0, dy=16, ha="center")
        # The y-label already names the measure; a panel title repeating it is one more
        # claim on margins that are already carrying a suptitle and a footer.
        ax.set_ylabel(metric)
    for ax in axes[1]:
        ax.set_xlabel("mock_rfd3_design.difficulty")
    fig.suptitle("The chain's objectives against the surrogate's own difficulty dial",
                 y=0.985)
    # Explicit margins: a suptitle, four titles and a footer caption resolved by
    # `tight_layout` overlap the y-labels at this type scale.
    fig.subplots_adjust(left=0.085, right=0.985, top=0.915, bottom=0.17, hspace=0.26,
                        wspace=0.25)
    return _save(fig, out, "f1-metric-ensembles.png",
                 f"mean +/- 2 sigma POPULATION spread over {max(n) if n else 0} lineages per "
                 f"point ({len(SWEEPS['difficulty'][1])} settings). Markers are the activity's "
                 "arms; `rescued` shares `hard`'s 0.55 and is off this line by three other knobs")


# -- F2: which knobs move the stage that carries the tightest bar -------------------------

def fig_knob_response(lin: list[dict[str, Any]], objectives: dict[str, Any],
                      out: Path) -> Path:
    """`complex_plddt` against each of the four knobs that have a real counterpart.

    One measure across four panels, so ONE y-label on the left and a shared y range: the
    comparison the figure is for is how far each knob moves the same number, and a per-panel
    y range would flatten the ones that barely move.
    """
    import matplotlib.pyplot as plt
    ps.apply_rcparams()
    knobs = [k for k in SWEEPS if k != "difficulty"]
    fig, axes = plt.subplots(1, len(knobs), figsize=(16.5, 6.2), sharey=True)
    bar = _bars(objectives, "complex_plddt")
    for ax, knob in zip(np.atleast_1d(axes), knobs, strict=True):
        x, m, lo, hi, n = _curve(lin, knob, "complex_plddt")
        if not len(x):
            continue
        ax.fill_between(x, lo, hi, color=ps.NEUTRAL_SERIES, alpha=ps.BAND_ALPHA,
                        linewidth=0, zorder=ps.Z["band"])
        ax.plot(x, m, **NEUTRAL_KW)
        if bar is not None:
            ax.axhline(bar, color=ps.INK_SECONDARY, linestyle=(0, (5, 3)), linewidth=1.2)
            if ax is np.atleast_1d(axes)[0]:
                ax.annotate(f"acceptance {bar:g}", xy=(x[0], bar), xytext=(2, 5),
                            textcoords="offset points", fontsize="small",
                            color=ps.INK_SECONDARY, zorder=ps.Z["annot"])
        # Log x for the three knobs that are ensemble sizes or step counts - picking the best
        # of N buys sublinearly, so a linear axis crowds every useful setting against the
        # left spine. `temperature` is a rate, and `diffusion_steps` is close enough to
        # evenly spaced that a log axis only collided its 150 and 200 tick labels.
        if knob in ("batch_size", "diffusion_samples"):
            ax.set_xscale("log")
            ax.set_xticks(list(x))
            ax.set_xticklabels([f"{v:g}" for v in x])
            ax.minorticks_off()
        span = float(m[-1] - m[0])
        ax.set_title(f"{knob}\n{span:+.2f} over the range", fontsize="medium", loc="left",
                     color=ps.INK_SECONDARY)
        ax.set_xlabel(knob)
        ps.direct_label(ax, x[-1], m[-1], f"{m[-1]:.2f}", ps.NEUTRAL_SERIES, dx=-4, dy=10,
                        ha="right")
    np.atleast_1d(axes)[0].set_ylabel("complex_plddt")
    fig.suptitle("Four knobs against the bar the campaign is hardest to pass "
                 f"(complex_plddt >= {bar:g})" if bar else "Four knobs against complex_plddt",
                 y=0.985)
    fig.subplots_adjust(left=0.065, right=0.99, top=0.84, bottom=0.26, wspace=0.12)
    return _save(fig, out, "f2-knob-response.png",
                 "mean +/- 2 sigma population spread over 24 lineages per point; dashed rule "
                 "is the campaign's own acceptance threshold. One y-axis across all four "
                 "panels, so the spans are comparable")


# -- F3: where the chain loses lineages, and to which kind of failure ---------------------

def fig_stage_funnel(tasks: list[dict[str, Any]], out: Path) -> Path:
    """Per-stage pass rate per arm, and the failures split by the role that decides trust.

    The split is the ruling, not a nicety: an ACCEPTANCE shortfall fails the node and leaves
    the pattern's trust alone, an INTEGRITY failure demotes it (decision 0013). An arm that
    misses a quality bar and an arm whose backbone came out disordered are drawn as different
    things here because the engine treats them as different things.
    """
    import matplotlib.pyplot as plt
    ps.apply_rcparams()
    arm_rows = [r for r in tasks if r.get("kind") == "arm"]
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(15.5, 6.8),
                                 gridspec_kw={"width_ratios": [1.35, 1.0]})
    xs = np.arange(len(CHAIN))
    for arm in ps.ORDER:
        sub = [r for r in arm_rows if r.get("arm") == arm]
        if not sub:
            continue
        share, labels = [], []
        for tool, _ in CHAIN:
            at = [r for r in sub if r.get("tool") == tool]
            share.append(sum(1 for r in at if r.get("qc") != "fail") / len(at) if at else
                         np.nan)
            labels.append(len(at))
        ax.plot(xs, share, **ps.line_kw(arm, marker=True))
        # Staggered: `baseline` and `rescued` both end at 1.0, and two labels at the same
        # point printed one exactly on top of the other.
        ps.direct_label(ax, xs[-1], share[-1], ps.style_for(arm).short,
                        ps.style_for(arm).color, dx=8,
                        dy=12 * (1 - 2 * (ps.ORDER.index(arm) % 2)))
    ax.set_xticks(xs)
    ax.set_xticklabels([lbl for _, lbl in CHAIN])
    ax.set_ylim(-0.05, 1.08)
    ax.set_ylabel("share of tasks that did not FAIL")
    ax.set_xlabel("stage, in chain order")
    ax.set_title("every stage runs, whatever the one before it returned", fontsize="medium",
                 loc="left", color=ps.INK_SECONDARY)

    # Failures by role. The bar is the arm's hue; the hatched part is the integrity share,
    # so role never rests on a second hue that would compete with the arm's own.
    width = 0.62
    pos = np.arange(len(ps.ORDER))
    for i, arm in enumerate(ps.ORDER):
        sub = [r for r in arm_rows if r.get("arm") == arm]
        acc = sum(1 for r in sub if r.get("fail_role") == "acceptance")
        integ = sum(1 for r in sub if r.get("fail_role") == "integrity")
        st = ps.style_for(arm)
        bx.bar(pos[i], acc, width, color=st.color, zorder=ps.Z["bar"])
        bx.bar(pos[i], integ, width, bottom=acc, color=st.color, alpha=0.55,
               hatch="///", edgecolor="white", linewidth=0.8, zorder=ps.Z["bar"])
        total = acc + integ
        bx.annotate(f"{total} of {len(sub)}", xy=(pos[i], total), xytext=(0, 6),
                    textcoords="offset points", ha="center", fontsize="small",
                    color=ps.INK_SECONDARY, zorder=ps.Z["annot"])
    bx.set_xticks(pos)
    bx.set_xticklabels([ps.style_for(a).short for a in ps.ORDER])
    bx.set_ylabel("failed tasks")
    bx.set_title("only the hatched part costs the pattern its trust", fontsize="medium",
                 loc="left", color=ps.INK_SECONDARY)
    bx.legend(handles=_neutral_patches([("acceptance shortfall", {}),
                                        ("integrity failure (trust demoted)",
                                         {"hatch": "///", "alpha": 0.55})]),
              loc="upper left", fontsize="medium")
    fig.suptitle("Where each arm loses its lineages, and what the loss costs", y=0.99)
    _arm_legend(fig, ps.ORDER, y=0.945)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.80, bottom=0.235, wspace=0.26)
    return _save(fig, out, "f3-stage-funnel.png",
                 "one task per lineage per stage, pooled over each arm's cycles. A FAIL does "
                 "not halt the chain, so the pass rate is per stage rather than cumulative")


# -- F4: the agent's own rate ------------------------------------------------------------

def fig_decision_rate(camps: list[dict[str, Any]], phases: list[dict[str, Any]],
                      out: Path) -> Path:
    """How fast the control plane decides, and how fast it is at anything else.

    The left panel puts the DECISION INDEX on x and elapsed seconds on y, rather than the
    other way round. Drawn the usual way it would be a cross-arm time series and would need
    cutting to one equal window; drawn this way the depth of each arm's search is a visible
    axis instead of a hidden one, and the slope is the rate.

    `hopeless` appears on the left, where it is a trace, and NOT on the right, where it would
    be a rate. It aborted; an aborted run is evidence, never a per-second figure.
    """
    import matplotlib.pyplot as plt
    ps.apply_rcparams()
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(15.0, 6.4))
    camp_by_arm = {r["arm"]: r for r in camps if r.get("kind") == "arm"}
    for arm in ps.ORDER:
        rows = sorted((r for r in phases if r.get("arm") == arm),
                      key=lambda r: r.get("order") or 0)
        if not rows:
            continue
        xs = np.arange(1, len(rows) + 1)
        cum = np.cumsum([sum(v for k, _ in PHASES
                             if (v := r.get(k)) is not None) for r in rows])
        # Distinct dashes per arm, because overlapping solid lines in four hues render as
        # whichever was drawn last and the reader cannot tell that the others are under it.
        ax.plot(xs, cum, drawstyle="steps-post",
                **ps.line_kw(arm, marker=True, markersize=9, alpha=0.9,
                             dashes=[(1, 0), (6, 2), (2, 2), (8, 2, 2, 2)][
                                 ps.ORDER.index(arm) % 4]))
        st = ps.style_for(arm)
        tail = " - aborted" if camp_by_arm.get(arm, {}).get("aborted") else ""
        # Right-anchored, because the longest arm's label is at the last x and a
        # left-anchored one ran off the panel.
        # Staggered for the same reason as the funnel's: at the default settings the arms'
        # traces lie almost exactly on top of one another - which IS the finding, a cycle
        # costs what it costs whatever it returns - and unstaggered the labels did too.
        ps.direct_label(ax, xs[-1], cum[-1], f"{st.short}{tail}", st.color, dx=-8,
                        ha="right", dy=14 * (1 - 2 * (ps.ORDER.index(arm) % 2)))
    ax.set_xlabel("decision (graph composed), in order")
    ax.set_ylabel("elapsed seconds")
    ax.set_xticks(np.arange(1, 1 + max((len([r for r in phases if r.get("arm") == a])
                                        for a in ps.ORDER), default=1)))
    ax.set_title("slope is seconds per decision - the arms nearly coincide",
                 fontsize="medium", loc="left", color=ps.INK_SECONDARY)

    clean = [a for a in ps.CLEAN_ORDER if a in camp_by_arm]
    pos = np.arange(len(clean))
    width = 0.38
    for i, arm in enumerate(clean):
        r = camp_by_arm[arm]
        st = ps.style_for(arm)
        d, t = r.get("decisions_per_s") or 0.0, r.get("tasks_per_s") or 0.0
        bx.bar(pos[i] - width / 2, d, width, color=st.color, zorder=ps.Z["bar"])
        bx.bar(pos[i] + width / 2, t, width, color=st.color, alpha=0.45,
               edgecolor=st.color, linewidth=1.2, zorder=ps.Z["bar"])
        for x, v in ((pos[i] - width / 2, d), (pos[i] + width / 2, t)):
            bx.annotate(f"{v:.3g}", xy=(x, v), xytext=(0, 5), textcoords="offset points",
                        ha="center", fontsize="small", color=ps.INK_SECONDARY,
                        zorder=ps.Z["annot"])
    bx.set_xticks(pos)
    bx.set_xticklabels([ps.style_for(a).short for a in clean])
    # One log axis rather than two linear ones: both series are per-second counts, so they
    # are the same unit, and they are two orders of magnitude apart. Only when there is
    # something positive to put on it: the `null` model stops at cycle 0, so an axis of all
    # zeros is not drawable on a log scale and matplotlib warns and silently draws nothing.
    if any((r.get("decisions_per_s") or 0) > 0 or (r.get("tasks_per_s") or 0) > 0
           for r in (camp_by_arm.get(a, {}) for a in clean)):
        bx.set_yscale("log")
    bx.set_ylabel("per second (log)" if bx.get_yscale() == "log" else "per second")
    bx.set_title("both are counts per second, so one axis - two decades apart",
                 fontsize="medium", loc="left", color=ps.INK_SECONDARY)
    bx.legend(handles=_neutral_patches([("decisions / s", {}),
                                        ("tasks / s", {"alpha": 0.45})]),
              loc="upper left", fontsize="medium")
    fig.suptitle("The control plane's rate, and what it spends it on", y=0.99)
    _arm_legend(fig, ps.ORDER, y=0.945)
    fig.subplots_adjust(left=0.075, right=0.985, top=0.80, bottom=0.215, wspace=0.24)
    return _save(fig, out, "f4-decision-rate.png",
                 "elapsed is summed from the executor's own phase records. `hopeless` "
                 "aborted, so it is drawn as a trace on the left and omitted from the rates "
                 "on the right. A first step near 1.1s rather than 0.1s is the intermittent "
                 "asyncflow dispatch stall, not the knob setting")


# -- F5: where a cycle's second actually goes ---------------------------------------------

def fig_control_time(phases: list[dict[str, Any]], out: Path) -> Path:
    """The control plane's own segments, cycle 0 against every cycle after it.

    The reason this figure exists: on these surrogates the six tools return in about two
    milliseconds a cycle, so a chart of "campaign wall time" would be a chart of the agent's
    own scheduling wearing the campaign's name. Splitting the execute window into the part
    with a tool running in it (`tools running`) and the part without (`scheduling wait`)
    says which is which, and the answer is that the tools are 0.2% of the first cycle.

    **Cycle 0 gets its own panel rather than its own bar.** It carries engine construction,
    the backend and the toolkit load - about 1.1s against 0.11s for every cycle after it -
    and a shared axis would compress the steady-state cycles into one pixel. Two panels on a
    shared LOG x instead: the units are identical (seconds), which is the only condition
    under which the house style allows two magnitudes on one axis.

    Bars are grouped by arm in the arms' own hues; a phase with no reading in a panel is a
    GAP, not a zero - `teardown` happens once per campaign, so it exists in whichever panel
    holds that campaign's last cycle and nowhere else.
    """
    import matplotlib.pyplot as plt
    ps.apply_rcparams()
    arms = [a for a in ps.ORDER if any(r.get("arm") == a for r in phases)]
    fig, axes = plt.subplots(1, 2, figsize=(15.5, 7.4), sharey=True, sharex=True)
    rows_for = {a: sorted((r for r in phases if r.get("arm") == a),
                          key=lambda r: r.get("order") or 0) for a in arms}
    panels = [("cycle 0 - the engine is built here", lambda rows: rows[:1]),
              ("every cycle after it (mean)", lambda rows: rows[1:])]
    ys = np.arange(len(PHASES))
    height = 0.78 / max(1, len(arms))
    for ax, (title, pick) in zip(axes, panels, strict=True):
        for i, arm in enumerate(arms):
            chosen = pick(rows_for[arm])
            st = ps.style_for(arm)
            vals = []
            for key, _ in PHASES:
                xs = [float(r[key]) for r in chosen if r.get(key) is not None]
                vals.append(float(np.mean(xs)) if xs else np.nan)
            offset = (i - (len(arms) - 1) / 2) * height
            ax.barh(ys + offset, vals, height, color=st.color, zorder=ps.Z["bar"],
                    edgecolor="white", linewidth=0.5)
        ax.set_title(title, fontsize="medium", loc="left", color=ps.INK_SECONDARY)
        ax.set_xscale("log")
        ax.set_xlabel("seconds (log)")
    axes[0].set_yticks(ys)
    axes[0].set_yticklabels([label for _, label in PHASES])
    # Once, not once per axes: `sharey` propagates the inversion, so inverting inside the
    # panel loop inverted it twice and put `plan` at the bottom.
    axes[0].invert_yaxis()
    for ax in axes:
        for y in ys:
            ax.axhline(y + 0.5, color=ps.GRID, linewidth=0.6, zorder=ps.Z["grid"])
    # Computed, not asserted. The share moves with the machine and with an intermittent
    # ~1s stall (see the caption), and a title carrying a number the figure might not show
    # is the kind of claim this project does not make.
    shares = [r["busy_share"] for r in phases
              if r.get("kind") == "arm" and r.get("busy_share") is not None]
    worst = f"{min(shares) * 100:.1f}%" if shares else "a fraction of a percent"
    fig.suptitle(f"A cycle is almost all agent: the tools hold {worst} of its slowest one",
                 y=0.99)
    _arm_legend(fig, arms, y=0.955)
    fig.subplots_adjust(left=0.185, right=0.985, top=0.80, bottom=0.215, wspace=0.07)
    return _save(fig, out, "f5-control-time.png",
                 "every segment is the gap between two records the executor wrote; "
                 "'tools running' is the union of task spans, so it is correct at any "
                 "concurrency. A missing bar is a gap, not a zero. About one first cycle in "
                 "eight pays an extra ~1.0s of scheduling wait - asyncflow's run-component "
                 "loop waits on its component-change event with a 1.0s timeout")


# -- F6: the stop reason is not the result -----------------------------------------------

def fig_stop_vs_front(camps: list[dict[str, Any]], out: Path) -> Path:
    """What each arm's campaign SAID, against what it actually had on the front.

    Drawn because the lab found it, not to illustrate it: `hard` stops on "every spec
    objective satisfied" with an EMPTY Pareto front. `DataRegistry.ingest` records a task's
    metrics whatever the QC verdict and `SatisfactionRule` counts those readings, while
    `core/pareto` correctly refuses a FAIL node a place on the front - so a campaign can
    satisfy its Spec on numbers from designs none of which it would hand anyone. Backlog G14.
    The figure's job is to make the gap unmissable to whoever runs the activity.
    """
    import matplotlib.pyplot as plt
    ps.apply_rcparams()
    rows = [r for r in camps if r.get("kind") == "arm"]
    rows = [r for a in ps.ORDER for r in rows if r.get("arm") == a]
    fig, ax = plt.subplots(figsize=(13.0, 6.4))
    pos = np.arange(len(rows))
    width = 0.38
    for i, r in enumerate(rows):
        st = ps.style_for(r["arm"])
        clean = int(r.get("n_pass") or 0) + int(r.get("n_suspect") or 0)
        ax.bar(pos[i] - width / 2, int(r.get("nodes") or 0), width, color=st.color,
               alpha=0.35, edgecolor=st.color, linewidth=1.4, zorder=ps.Z["bar"])
        ax.bar(pos[i] + width / 2, int(r.get("front") or 0), width, color=st.color,
               zorder=ps.Z["bar"])
        ax.annotate(f"{clean} clean / {r.get('nodes')}",
                    xy=(pos[i] - width / 2, int(r.get("nodes") or 0)), xytext=(0, 6),
                    textcoords="offset points", ha="center", fontsize="small",
                    color=ps.INK_SECONDARY, zorder=ps.Z["annot"])
        ax.annotate(f"{r.get('front')}", xy=(pos[i] + width / 2, int(r.get("front") or 0)),
                    xytext=(0, 6), textcoords="offset points", ha="center",
                    fontsize="small", color=st.color, fontweight="bold",
                    zorder=ps.Z["annot"])
        reason = str(r.get("stop_reason") or "")
        ax.annotate(_wrap(reason, 26), xy=(pos[i], 0), xytext=(0, -58),
                    textcoords="offset points", ha="center", va="top", fontsize="small",
                    color=st.color, zorder=ps.Z["annot"],
                    annotation_clip=False)
    ax.set_xticks(pos)
    ax.set_xticklabels([ps.style_for(r["arm"]).short for r in rows])
    ax.set_ylabel("lineages")
    ax.set_ylim(0, max((int(r.get("nodes") or 0) for r in rows), default=1) * 1.25)
    ax.legend(handles=_neutral_patches([("lineages run", {"alpha": 0.35}),
                                        ("on the Pareto front", {})]),
              loc="upper left", fontsize="medium")
    fig.suptitle("The stop reason is not the result: read the front", y=0.985)
    fig.subplots_adjust(left=0.085, right=0.985, top=0.9, bottom=0.34)
    return _save(fig, out, "f6-stop-vs-front.png",
                 "'clean' is pass or suspect - a suspect node passed every gate and belongs "
                 "to an untrusted pattern. `hard` reports its Spec satisfied with nothing on "
                 "the front (backlog G14)")


def _wrap(text: str, width: int) -> str:
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    out.append(line)
    return "\n".join(out)



# -- F7-F9: the reasoner axis -------------------------------------------------------------
#
# The entity in these three is the CONTROL MODEL, and it does not get a hue. The four
# validated colours are spent on the four knob arms and colour follows the entity, so a model
# takes the fill channel instead - hatch and face alpha, inside the arm's own colour
# (`plot_style.MODEL_FILLS`). An arm a reader learned in f1-f6 is the same colour here.


def _models(rows: list[dict[str, Any]]) -> list[str]:
    """The models present, in the axis's own order rather than alphabetical."""
    seen = {str(r.get("model")) for r in rows if r.get("model")}
    return [m for m in ps.MODEL_FILLS if m in seen]


def _model_legend(ax, models: list[str], **over):
    """A key for the fill channel, in neutral grey - the fill names a MODEL, not an arm."""
    from matplotlib.patches import Patch
    # The KEY is drawn opaque whatever the fill's own alpha. `null` sits at 0.30 so its
    # zero-height bars do not shout, and at 0.30 its legend swatch was very nearly the
    # page - a key the reader cannot see is not a key.
    handles = [Patch(facecolor=ps.NEUTRAL_SERIES, edgecolor=ps.INK_SECONDARY,
                     linewidth=0.8, label=f"model {m}",
                     hatch=ps.model_fill(m)["hatch"]) for m in models]
    ax.legend(handles=handles, fontsize="small", **over)


def fig_reasoner_yield(camps: list[dict[str, Any]], out: Path) -> Path:
    """What each control model got out of each knob arm.

    The question the reasoner axis exists for: `hard` is a campaign model D stops on "every
    spec objective satisfied" with an empty front. Does a model that can read the tool cards
    and move the knobs get anything onto it?

    Front size rather than lineages, because lineages are what a campaign SPENT and the front
    is what it has to show. The run count is annotated beside each bar so a model that bought
    its front with four times the work cannot read as a free win.
    """
    import matplotlib.pyplot as plt
    ps.apply_rcparams()
    rows = [r for r in camps if r.get("kind") == "arm" and not r.get("skipped")]
    models = _models(rows)
    arms = [a for a in ps.ORDER if any(r.get("arm") == a for r in rows)]
    fig, ax = plt.subplots(figsize=(14.0, 6.8))
    width = 0.8 / max(1, len(models))
    pos = np.arange(len(arms))
    for i, model in enumerate(models):
        offset = (i - (len(models) - 1) / 2) * width
        for j, arm in enumerate(arms):
            cells = [r for r in rows if r.get("arm") == arm and r.get("model") == model]
            if not cells:
                continue
            fronts = [int(c.get("front") or 0) for c in cells]
            nodes = [int(c.get("nodes") or 0) for c in cells]
            st = ps.style_for(arm)
            # Mean over repeats, and the spread drawn as a range bar rather than a band: a
            # live model is repeated because it is not a function, and three draws is too
            # few for a sigma to mean anything.
            mean = float(np.mean(fronts))
            ax.bar(pos[j] + offset, mean, width * 0.9, color=st.color,
                   edgecolor=st.color, linewidth=1.2, zorder=ps.Z["bar"],
                   **ps.model_fill(model))
            if len(fronts) > 1:
                ax.plot([pos[j] + offset] * 2, [min(fronts), max(fronts)],
                        color=ps.INK, linewidth=1.6, zorder=ps.Z["annot"])
            ax.annotate(f"{model}\n{mean:.0f}/{int(np.mean(nodes))}",
                        xy=(pos[j] + offset, mean), xytext=(0, 6),
                        textcoords="offset points", ha="center", fontsize="small",
                        color=ps.INK_SECONDARY, zorder=ps.Z["annot"])
    ax.set_xticks(pos)
    ax.set_xticklabels([ps.style_for(a).short for a in arms])
    ax.set_ylabel("designs on the Pareto front")
    ax.set_xlabel("knob arm (colour) x control model (fill)")
    # A front is a COUNT, so its axis has no halves on it.
    top = max(1.0, ax.get_ylim()[1])
    ax.set_yticks(np.arange(0, np.ceil(top) + 1))
    ax.set_ylim(0, np.ceil(top) * 1.18)
    _model_legend(ax, models, loc="upper right")
    fig.suptitle("Does a reasoner rescue a campaign the rules cannot?", y=0.985)
    fig.subplots_adjust(left=0.08, right=0.985, top=0.9, bottom=0.21)
    return _save(fig, out, "f7-reasoner-yield.png",
                 "bar is the mean over repeats and the vertical rule its full range; the "
                 "label is front/lineages. A live model is repeated because it is not a "
                 "function - three draws is too few for a sigma, so the range is drawn")


def fig_decision_cost(camps: list[dict[str, Any]], decisions: list[dict[str, Any]],
                      out: Path) -> Path:
    """What a decision costs each model, in seconds and in tokens.

    Two panels because the units differ and one axis for both would be the two-scales
    mistake. `null` and `D` carry no tokens at all and that is drawn as absence, not as
    zero - a zero would say the call was free rather than that no call was made.
    """
    import matplotlib.pyplot as plt
    ps.apply_rcparams()
    rows = [r for r in camps if r.get("kind") == "arm" and not r.get("skipped")]
    models = _models(rows)
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(15.0, 6.4))
    pos = np.arange(len(models))

    for i, model in enumerate(models):
        cells = [r for r in rows if r.get("model") == model]
        secs = [float(c["s_per_decision"]) for c in cells if c.get("s_per_decision")]
        if not secs:
            # `null` composes no graph at all, so it has no seconds-per-decision. Said
            # rather than left as a gap, which would read as a measurement of zero.
            ax.annotate("no decision\nto time", xy=(pos[i], 0), xytext=(0, 12),
                        textcoords="offset points", ha="center", fontsize="small",
                        color=ps.INK_SECONDARY, zorder=ps.Z["annot"])
        if secs:
            ax.bar(pos[i], float(np.mean(secs)), 0.6, color=ps.NEUTRAL_SERIES,
                   edgecolor=ps.NEUTRAL_SERIES, linewidth=1.2, zorder=ps.Z["bar"],
                   **ps.model_fill(model))
            if len(secs) > 1:
                ax.plot([pos[i]] * 2, [min(secs), max(secs)], color=ps.INK, linewidth=1.6,
                        zorder=ps.Z["annot"])
            ax.annotate(f"{np.mean(secs):.2f}s", xy=(pos[i], float(np.mean(secs))),
                        xytext=(0, 6), textcoords="offset points", ha="center",
                        fontsize="small", color=ps.INK_SECONDARY, zorder=ps.Z["annot"])
    ax.set_xticks(pos)
    ax.set_xticklabels([f"model {m}" for m in models])
    ax.set_ylabel("seconds per decision (wall clock)")
    ax.set_title("every model, from the campaign's own clock", fontsize="medium",
                 loc="left", color=ps.INK_SECONDARY)

    live = [m for m in models
            if any(d.get("model") == m for d in decisions)]
    if live:
        for i, model in enumerate(live):
            calls = [d for d in decisions if d.get("model") == model]
            toks = [float(d["completion_tokens"]) for d in calls
                    if d.get("completion_tokens") is not None]
            secs = [float(d["elapsed_s"]) for d in calls if d.get("elapsed_s") is not None]
            if toks:
                m, lo, hi = _band(toks)
                bx.bar(i, m, 0.6, color=ps.NEUTRAL_SERIES, edgecolor=ps.NEUTRAL_SERIES,
                       linewidth=1.2, zorder=ps.Z["bar"], **ps.model_fill(model))
                bx.plot([i] * 2, [max(0.0, lo), hi], color=ps.INK, linewidth=1.6,
                        zorder=ps.Z["annot"])
                bx.annotate(f"{m:.0f} tok\n{np.mean(secs):.1f}s/call",
                            xy=(i, m), xytext=(0, 6), textcoords="offset points",
                            ha="center", fontsize="small", color=ps.INK_SECONDARY,
                            zorder=ps.Z["annot"])
        bx.set_xticks(np.arange(len(live)))
        bx.set_xticklabels([f"model {m}" for m in live])
        bx.set_ylabel("completion tokens per call")
    else:
        # Said, not left blank. An empty panel reads as "the models were free".
        bx.set_xticks([])
        bx.set_yticks([])
        # No frame either: an empty ruled box reads as a panel whose data came out at zero.
        for side in bx.spines.values():
            side.set_visible(False)
        bx.grid(False)
        bx.annotate("no live cell in this lab - run with --model-profile\n"
                    "to put A or B on a real endpoint",
                    xy=(0.5, 0.5), xycoords="axes fraction", ha="center", va="center",
                    fontsize="large", color=ps.INK_SECONDARY)
    bx.set_title("only a model that called an endpoint has tokens", fontsize="medium",
                 loc="left", color=ps.INK_SECONDARY)
    # Upper RIGHT: the tallest bar is the first model, and at upper left the key landed on
    # its own annotation.
    _model_legend(ax, models, loc="upper right")
    ax.set_ylim(0, max(ax.get_ylim()[1], 1e-9) * 1.22)
    fig.suptitle("What one decision costs, by who made it", y=0.985)
    # A wider left margin: "seconds per decision (wall clock)" at this type scale is a long
    # y-label and at 0.075 it ran off the canvas.
    fig.subplots_adjust(left=0.105, right=0.985, top=0.885, bottom=0.2, wspace=0.26)
    return _save(fig, out, "f8-decision-cost.png",
                 "left is wall clock per composed graph, which every model has; right is "
                 "mean +/- 2 sigma over individual calls. A model with no tokens made no "
                 "call - absence, not zero")


def fig_knobs_moved(params: list[dict[str, Any]], out: Path) -> Path:
    """Which knobs each model actually moved, and how far up their declared ranges.

    From `stages.jsonl`'s `mappings`, the only record of the parameter vector a Planner
    chose. `source` separates the campaign's declared values from the reasoner's: the
    campaign's are in `mappings` too, because `_apply_campaign_defaults` merges them before
    composition, and counting them would credit every model with setting every knob.

    `difficulty` must appear for nobody. It is `operator_only`, so no reasoner may propose
    it, and this figure is where a leak would show.
    """
    import matplotlib.pyplot as plt
    ps.apply_rcparams()
    chosen = [r for r in params if r.get("source") == "reasoner"
              and r.get("fraction_of_range") is not None]
    models = _models(chosen)
    names = sorted({str(r["parameter"]) for r in chosen})
    fig, ax = plt.subplots(figsize=(14.0, 6.8))
    if not names:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.annotate("no reasoner moved a parameter in this lab",
                    xy=(0.5, 0.5), xycoords="axes fraction", ha="center", va="center",
                    fontsize="large", color=ps.INK_SECONDARY)
    else:
        ys = np.arange(len(names))
        height = 0.8 / max(1, len(models))
        for i, model in enumerate(models):
            offset = (i - (len(models) - 1) / 2) * height
            for j, name in enumerate(names):
                vals = [float(r["fraction_of_range"]) for r in chosen
                        if r["parameter"] == name and r.get("model") == model]
                if not vals:
                    continue
                ax.barh(ys[j] + offset, float(np.mean(vals)), height * 0.9,
                        color=ps.NEUTRAL_SERIES, edgecolor=ps.NEUTRAL_SERIES,
                        linewidth=1.2, zorder=ps.Z["bar"], **ps.model_fill(model))
                ax.plot([min(vals), max(vals)], [ys[j] + offset] * 2, color=ps.INK,
                        linewidth=1.4, zorder=ps.Z["annot"])
                ax.annotate(f"{model} x{len(vals)}",
                            xy=(float(np.mean(vals)), ys[j] + offset), xytext=(6, 0),
                            textcoords="offset points", va="center", fontsize="small",
                            color=ps.INK_SECONDARY, zorder=ps.Z["annot"])
        ax.set_yticks(ys)
        ax.set_yticklabels(names)
        ax.set_xlim(0, 1.18)
        ax.set_xlabel("where the chosen value sits in the parameter's own declared range")
        ax.invert_yaxis()
        _model_legend(ax, models, loc="lower right")
    assert not [r for r in chosen if r["parameter"] == "difficulty"], (
        "a reasoner set the experiment's own dial - `operator_only` did not hold")
    fig.suptitle("Which knobs each model moved, and how far", y=0.985)
    fig.subplots_adjust(left=0.19, right=0.985, top=0.9, bottom=0.22)
    return _save(fig, out, "f9-knobs-moved.png",
                 "the reasoner's own choices only; a value equal to the campaign's declared "
                 "one is credited to the campaign, which under-credits a model rather than "
                 "inventing a decision for it. `difficulty` is operator_only and appears for "
                 "nobody")


# -- entry point -------------------------------------------------------------------------

def draw_all(lab: Path) -> list[Path]:
    """Every figure, from one lab directory's tables. Returns what it wrote."""
    import json
    lab = Path(lab)
    tables = lab / "tables"
    objectives = json.loads((lab / "manifest.json").read_text()).get("objectives", {})
    lin = read_table(tables / "lineages.csv")
    tasks = read_table(tables / "tasks.csv")
    camps = read_table(tables / "campaigns.csv")
    phases = read_table(tables / "phases.csv")
    decisions = read_table(tables / "decisions.csv")
    params = read_table(tables / "params.csv")
    out = lab / "figures"
    written = [
        fig_metric_ensembles(lin, objectives, out),
        fig_knob_response(lin, objectives, out),
        fig_stage_funnel(tasks, out),
        fig_decision_rate(camps, phases, out),
        fig_control_time(phases, out),
        fig_stop_vs_front(camps, out),
        fig_reasoner_yield(camps, out),
        fig_decision_cost(camps, decisions, out),
        fig_knobs_moved(params, out),
    ]
    log.info("%d figures in %s", len(written), out)
    return written
