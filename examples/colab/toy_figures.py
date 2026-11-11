"""Figures for the Colab quickstart.

Separate from `impress_toy.py` so that module imports without a plotting stack,
the way IMPRESS-A keeps matplotlib in its `figures` extra. Nothing here runs at
import time and nothing calls `plt.show()`: each function returns a figure, so
a notebook displays it and a test can assert on it.

**Style.** The constants below are copied from
`agent/src/impress_a/analysis/plot_style.py`, which the `campaign-plot-style`
skill generated and which carries the validator command the four hues passed.
They are copied rather than imported on purpose: importing `impress_a` here
would invert the dependency between the two packages and would break the lean
install this notebook uses, which has no IMPRESS-A in it at all.

One deliberate departure from that module's meaning. There, a hue names a knob
setting and the blue slot means "best performing". Nothing in these figures is
a performance comparison, so here a hue names **generation depth** -- an
ordered quantity, root first -- and in the score plot it names a target's
state. Cross-figure colour identity is kept; the tier reading is not claimed.
"""

from __future__ import annotations

from typing import Optional

# -- Ink, surface, grid. Copied; see the module docstring. -------------------
SURFACE = "#ffffff"
INK = "#1a1a1a"
INK_SECONDARY = "#444444"
GRID = "#DCD7CC"
NEUTRAL_SERIES = "#5b5b55"

# Validated against a white surface, adjacent pairs and all pairs:
#   node validate_palette.js "#2176c7,#ae8a16,#9e3f1c,#993284" \
#       --mode light --surface "#ffffff" --pairs all
# Worst all-pairs separation is magenta-blue at deutan dE 10.9. A fifth hue
# means re-running that command, so generation 3 and deeper share the last one.
GEN_COLORS = ("#2176c7", "#ae8a16", "#9e3f1c", "#993284")

FRAGILE = "#9e3f1c"
STURDY = NEUTRAL_SERIES
IN_CHILD = "#2176c7"

RCPARAMS = {
    "font.size": 11,
    "axes.titlesize": "large",
    "axes.labelsize": "large",
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "text.color": INK,
    "axes.labelcolor": INK,
    "axes.titlecolor": INK,
    "xtick.color": INK_SECONDARY,
    "ytick.color": INK_SECONDARY,
    "axes.edgecolor": INK_SECONDARY,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": True,
    "legend.framealpha": 0.9,
    "legend.edgecolor": GRID,
    "figure.dpi": 110,
}

LINE_KW = dict(linewidth=1.8, solid_capstyle="round", zorder=6)
MARKER_KW = dict(markersize=5, markerfacecolor="white", markeredgewidth=1.2, zorder=6)


def apply_style():
    """Set the house rcParams. Call once per notebook."""
    import matplotlib.pyplot as plt

    plt.rcParams.update(RCPARAMS)


def gen_color(generation: int) -> str:
    return GEN_COLORS[min(generation, len(GEN_COLORS) - 1)]


# Inches one 8pt character occupies, measured from the rendered figures.
# Used to wrap a caption to whatever width its figure actually has.
_CAPTION_IN_PER_CHAR = 0.072


def _caption(fig, text: str, width: Optional[int] = None) -> None:
    """A caveat along the bottom, hard-wrapped to the figure's own width.

    matplotlib's own `wrap=True` measures against the figure edge and still
    clips a long line at this font size, so the wrapping is done here.
    """
    import textwrap

    if width is None:
        width = max(40, int(fig.get_figwidth() * 0.98 / _CAPTION_IN_PER_CHAR))
    fig.text(
        0.01,
        0.01,
        "\n".join(textwrap.wrap(text, width)),
        fontsize=8,
        color=INK_SECONDARY,
        ha="left",
        va="bottom",
    )


# --------------------------------------------------------------------------
# Deriving spans from the event log
# --------------------------------------------------------------------------


def task_spans(result) -> list:
    """Pair every `task_start` with its `task_end`.

    Keyed on pipeline, task name, targets and pass, which is unique within a
    run: a pipeline runs each stage once per pass per target.
    """
    open_spans: dict = {}
    spans = []
    for event in result.events:
        if event["kind"] not in ("task_start", "task_end"):
            continue
        key = (
            event["pipeline"],
            event["task"],
            tuple(event["targets"]),
            event["detail"].get("pass"),
        )
        if event["kind"] == "task_start":
            open_spans[key] = event
            continue
        start = open_spans.pop(key, None)
        if start is None:
            continue
        spans.append(
            {
                "pipeline": event["pipeline"],
                "generation": event["generation"],
                "task": event["task"],
                "targets": event["targets"],
                "pass": event["detail"].get("pass"),
                "t0": start["t"],
                "t1": event["t"],
            }
        )
    return spans


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------


def plot_gantt(result):
    """When every task ran, grouped by pipeline.

    What to look for: the bars within one pass overlap, because the pipeline
    collects its futures before awaiting any of them. A child pipeline's row
    starts where the parent spawned it.
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    spans = task_spans(result)
    rows = result.pipelines
    index = {name: i for i, name in enumerate(rows)}

    fig, ax = plt.subplots(figsize=(10, 0.9 * len(rows) + 2.2))
    for span in spans:
        y = index[span["pipeline"]]
        width = max(span["t1"] - span["t0"], 0.02)
        hatch = "///" if span["task"] == "score_extraction" else None
        ax.broken_barh(
            [(span["t0"], width)],
            (y - 0.3, 0.6),
            facecolors=gen_color(span["generation"]),
            edgecolor=SURFACE,
            linewidth=0.5,
            hatch=hatch,
            zorder=3,
        )

    for event in result.events:
        if event["kind"] != "spawn":
            continue
        ax.axvline(event["t"], color=INK_SECONDARY, linestyle=":", linewidth=1.2)
        # Axes-fraction y, so the label sits just under the title whatever the
        # y-axis is doing -- this one is inverted, which sent it off-canvas.
        ax.annotate(
            f"spawn {event['detail']['child']}",
            xy=(event["t"], 1.0),
            xycoords=("data", "axes fraction"),
            xytext=(3, -4),
            textcoords="offset points",
            fontsize=8,
            color=INK_SECONDARY,
            ha="left",
            va="top",
        )

    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows)
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.invert_yaxis()
    ax.set_xlabel("seconds since run start")
    ax.set_title("Tasks over time, by pipeline")
    ax.grid(axis="y", visible=False)
    ax.legend(
        handles=[
            Patch(facecolor=gen_color(g), label=f"generation {g}")
            for g in sorted({s["generation"] for s in spans})
        ]
        + [Patch(facecolor=NEUTRAL_SERIES, hatch="///", label="local task")],
        loc="lower right",
        fontsize=8,
    )
    _caption(
        fig,
        "A bar runs from task submission to its future resolving. The gaps "
        "between passes are the manager's 0.5s adaptive poll, not task work.",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    return fig


def plot_genealogy(result):
    """Who spawned whom, and which targets moved.

    Drawn with plain matplotlib: the tree is a handful of nodes, so a graph
    library would be a dependency bought for nothing.
    """
    import matplotlib.pyplot as plt

    depth: dict = {}
    for name in result.pipelines:
        depth[name] = 0
    for row in result.genealogy:
        depth[row["child"]] = depth.get(row["parent"], 0) + 1

    by_depth: dict = {}
    for name in result.pipelines:
        by_depth.setdefault(depth[name], []).append(name)
    pos = {}
    for d, names in by_depth.items():
        for i, name in enumerate(names):
            pos[name] = (i - (len(names) - 1) / 2.0, -d)

    depth_max = max(by_depth)
    widest = max(len(names) for names in by_depth.values())
    # The floor is set by the caption, not by the tree: a narrower canvas wraps
    # it into four lines under two circles.
    fig, ax = plt.subplots(
        figsize=(max(7.0, 2.6 * widest), 1.35 * (depth_max + 1) + 1.1)
    )
    for row in result.genealogy:
        if row["parent"] not in pos or row["child"] not in pos:
            continue
        x0, y0 = pos[row["parent"]]
        x1, y1 = pos[row["child"]]
        ax.annotate(
            "",
            xy=(x1, y1 + 0.18),
            xytext=(x0, y0 - 0.18),
            arrowprops=dict(arrowstyle="-|>", color=INK_SECONDARY, linewidth=1.4),
        )
        ax.text(
            (x0 + x1) / 2 + 0.06,
            (y0 + y1) / 2,
            " ".join(row["migrated"]),
            fontsize=9,
            color=FRAGILE,
            ha="left",
            va="center",
        )

    for name, (x, y) in pos.items():
        ax.scatter(
            [x], [y], s=1500, color=gen_color(-int(y)), zorder=5, edgecolors=SURFACE
        )
        ax.text(x, y, name, ha="center", va="center", color=SURFACE, fontsize=9,
                zorder=6)

    span = max(0.6, widest / 2.0)
    ax.set_xlim(-span - 0.5, span + 0.9)
    ax.set_ylim(-depth_max - 0.5, 0.5)
    ax.axis("off")
    ax.set_title("Pipeline genealogy")
    _caption(
        fig,
        "An arrow is one `submit_child_pipeline_request`. The label names the "
        "targets the parent handed over and stopped working on.",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    return fig


def plot_scores(result):
    """Each target's score per pass, and the threshold that judges the drop.

    What to look for: the dark red lines are the targets the simulation makes
    fragile. Where one of them crosses into a child pipeline it turns blue and
    its slope flattens -- a child buys time, it does not fix the target.
    """
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from toy_science import fragile_targets

    fragile = fragile_targets(result.cfg)
    by_target: dict = {}
    for row in result.scores:
        by_target.setdefault(row["target"], []).append(row)

    fig, ax = plt.subplots(figsize=(10, 5.2))
    for target, rows in sorted(by_target.items()):
        rows = sorted(rows, key=lambda r: r["pass"])
        for a, b in zip(rows, rows[1:]):
            in_child = b["generation"] > 0
            color = IN_CHILD if in_child else (FRAGILE if target in fragile else STURDY)
            ax.plot(
                [a["pass"], b["pass"]],
                [a["score"], b["score"]],
                color=color,
                **LINE_KW,
            )
        for row in rows:
            color = (
                IN_CHILD
                if row["generation"] > 0
                else (FRAGILE if target in fragile else STURDY)
            )
            ax.plot(
                [row["pass"]], [row["score"]], marker="o", color=color, **MARKER_KW
            )
        last = rows[-1]
        ax.annotate(
            f" {target}",
            xy=(last["pass"], last["score"]),
            fontsize=9,
            color=INK_SECONDARY,
            va="center",
        )

    for event in result.events:
        if event["kind"] != "spawn":
            continue
        ax.axvline(
            _pass_of_spawn(result, event),
            color=INK_SECONDARY,
            linestyle=":",
            linewidth=1.2,
        )

    ax.set_xlabel("pass")
    ax.set_ylabel("simulated score")
    ax.set_title(
        f"Score trajectories (a drop of more than "
        f"{result.cfg.degradation_threshold} marks a target degraded)"
    )
    ax.set_xticks(sorted({r["pass"] for r in result.scores}))
    ax.legend(
        handles=[
            Line2D([], [], color=FRAGILE, label="fragile target", **LINE_KW),
            Line2D([], [], color=STURDY, label="sturdy target", **LINE_KW),
            Line2D([], [], color=IN_CHILD, label="in a child pipeline", **LINE_KW),
        ],
        loc="lower left",
        fontsize=9,
    )
    _caption(
        fig,
        "Every score is a seeded pseudo-random draw. It says nothing about any "
        "protein; what is being shown is when the framework reacts.",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return fig


def _pass_of_spawn(result, spawn_event) -> float:
    """Which pass a spawn landed in, for a vertical marker on a pass axis."""
    candidates = [
        r["pass"] for r in result.scores if r["t"] <= spawn_event["t"]
    ]
    return max(candidates) + 0.5 if candidates else 0.0


def plot_concurrency(result):
    """How many tasks were in flight at once.

    What to look for: the peaks are one pass's targets running together. The
    flat stretches at zero are the adaptive poll -- the run is waiting on a
    decision, not on compute.
    """
    import matplotlib.pyplot as plt

    spans = task_spans(result)
    edges = sorted({t for s in spans for t in (s["t0"], s["t1"])})
    times, counts = [], []
    for t in edges:
        times.append(t)
        counts.append(sum(1 for s in spans if s["t0"] <= t < s["t1"]))

    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.step(times, counts, where="post", color=NEUTRAL_SERIES, **LINE_KW)
    ax.fill_between(times, counts, step="post", color=NEUTRAL_SERIES, alpha=0.15)
    ax.axhline(
        result.cfg.max_workers,
        color=FRAGILE,
        linestyle="--",
        linewidth=1.2,
        label=f"max_workers = {result.cfg.max_workers}",
    )
    ax.set_xlabel("seconds since run start")
    ax.set_ylabel("tasks in flight")
    ax.set_title("Task concurrency")
    ax.legend(loc="upper right", fontsize=9)
    _caption(
        fig,
        "The max_workers line is drawn for reference only: executable tasks "
        "are subprocesses started on the event loop, so the thread pool does "
        "not bound them. It bounds function tasks and the adaptive callback.",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    return fig


def plot_sweep(rows: list, param: str = "degradation_threshold"):
    """What one knob did to spawning and to makespan.

    A swept line is a measure rather than one of the compared entities, so it
    is drawn in the neutral series -- the same rule the campaign figures use.
    """
    import matplotlib.pyplot as plt

    values = sorted({r[param] for r in rows})
    spawns = [
        sum(r["spawns"] for r in rows if r[param] == v)
        / max(1, sum(1 for r in rows if r[param] == v))
        for v in values
    ]
    makespans = [
        sum(r["makespan_s"] for r in rows if r[param] == v)
        / max(1, sum(1 for r in rows if r[param] == v))
        for v in values
    ]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, series, label in (
        (axes[0], spawns, "children spawned"),
        (axes[1], makespans, "makespan (s)"),
    ):
        # LINE_KW and MARKER_KW both carry zorder, so merge rather than splat.
        kw = dict(LINE_KW)
        kw.update(MARKER_KW)
        ax.plot(
            values,
            series,
            color=NEUTRAL_SERIES,
            marker="o",
            markeredgecolor=NEUTRAL_SERIES,
            **kw,
        )
        ax.set_xlabel(param.replace("_", " "))
        ax.set_ylabel(label)
        ax.set_title(label)

    fig.suptitle(f"Sweeping {param.replace('_', ' ')}")
    _caption(
        fig,
        "One run per point unless the sweep was given repeats; with repeats "
        "the marker is their mean.",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    return fig


def print_table(rows: list, columns: Optional[list] = None) -> None:
    """A plain monospace table, so the notebook needs no pandas."""
    if not rows:
        print("(no rows)")
        return
    columns = columns or list(rows[0])
    widths = {
        c: max(len(str(c)), *(len(str(r.get(c, ""))) for r in rows)) for c in columns
    }
    print("  ".join(str(c).ljust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for row in rows:
        print("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))
