#!/usr/bin/env python3
"""Plot LigandMPNN per-sequence metric distributions from campaign analysis data.

Produces the following figures:
  sequence_metrics_overview.png                  -- pooled histograms for all metrics
  sequence_metrics_boxplots_by_island_count.png  -- boxplots per metric, x = island count
  sequence_metrics_boxplots_by_model.png         -- boxplots per metric, x = model grouped by IC
  sequence_{col}_by_island_count.png             -- per-metric panels by island count (x3)
  sequence_{col}_by_model.png                    -- per-metric panels by model (x3)
"""

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

METRIC_COLS = ["overall_confidence", "ligand_confidence", "seq_rec"]

TITLES = {
    "overall_confidence": "Overall Confidence",
    "ligand_confidence":  "Ligand Confidence",
    "seq_rec":            "Sequence Recovery",
}

DISCRETE_COLS = set()


# ---------------------------------------------------------------------------
# Layout helpers (identical logic to plot_campaign.py)
# ---------------------------------------------------------------------------

def _island_color_map(df):
    island_counts = sorted(df["RESIDUE_ISLAND_COUNT"].dropna().unique().astype(int))
    n = len(island_counts)
    cmap = plt.colormaps["tab10"]
    return {ic: cmap(i / max(n - 1, 1)) for i, ic in enumerate(island_counts)}


def _model_order_and_positions(df):
    model_ic = (
        df[["model_name", "RESIDUE_ISLAND_COUNT"]]
        .dropna()
        .drop_duplicates("model_name")
        .assign(RESIDUE_ISLAND_COUNT=lambda x: x["RESIDUE_ISLAND_COUNT"].astype(int))
        .sort_values(["RESIDUE_ISLAND_COUNT", "model_name"])
    )
    within_gap = 0.7
    between_gap = 1.8
    positions = []
    model_order = []
    group_spans = {}
    x = 1.0
    for ic, grp in model_ic.groupby("RESIDUE_ISLAND_COUNT"):
        group_models = list(grp["model_name"])
        gpos = [x + i * within_gap for i in range(len(group_models))]
        positions.extend(gpos)
        model_order.extend(group_models)
        group_spans[ic] = (gpos[0], gpos[-1])
        x = gpos[-1] + between_gap
    ic_for_model = dict(zip(model_ic["model_name"], model_ic["RESIDUE_ISLAND_COUNT"]))
    return model_order, positions, group_spans, ic_for_model


def _draw_brackets(ax, group_spans):
    trans = ax.get_xaxis_transform()
    bracket_y = 1.03
    cap_h = 0.025
    for ic, (x_lo, x_hi) in group_spans.items():
        ax.plot([x_lo, x_hi], [bracket_y, bracket_y],
                transform=trans, color="black", lw=1.2, clip_on=False)
        ax.plot([x_lo, x_lo], [bracket_y - cap_h, bracket_y],
                transform=trans, color="black", lw=1.2, clip_on=False)
        ax.plot([x_hi, x_hi], [bracket_y - cap_h, bracket_y],
                transform=trans, color="black", lw=1.2, clip_on=False)
        ax.text((x_lo + x_hi) / 2, bracket_y + 0.01,
                f"islands={ic}", transform=trans,
                ha="center", va="bottom", fontsize=7, fontweight="bold",
                clip_on=False)


def plot_col(ax, data, col, color="steelblue", title_suffix=""):
    title = TITLES[col] + (f"\n{title_suffix}" if title_suffix else "")
    ax.hist(data[col].dropna().astype(float), bins=30,
            color=color, edgecolor="white", linewidth=0.4)
    ax.set_xlabel(col)
    ax.set_ylabel("count")
    ax.set_title(title, fontsize=9)


# ---------------------------------------------------------------------------
# Figure functions
# ---------------------------------------------------------------------------

def make_overview_figure(df, output_dir):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    fig.suptitle(f"LigandMPNN Sequence Metric Distributions (n={len(df)})", fontsize=14)
    for ax, col in zip(axes.flat, METRIC_COLS):
        plot_col(ax, df, col)
    plt.tight_layout()
    out = output_dir / "sequence_metrics_overview.png"
    plt.savefig(out, dpi=150)
    print(f"Saved {out}")
    plt.close(fig)


def make_boxplot_figure(df, output_dir):
    island_counts = sorted(df["RESIDUE_ISLAND_COUNT"].dropna().unique().astype(int))
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    fig.suptitle("LigandMPNN Sequence Metrics vs Residue Island Count", fontsize=14)
    for ax, col in zip(axes.flat, METRIC_COLS):
        groups = [df.loc[df["RESIDUE_ISLAND_COUNT"] == ic, col].dropna().astype(float).values
                  for ic in island_counts]
        bp = ax.boxplot(groups, labels=island_counts, patch_artist=True, notch=False)
        cmap = plt.colormaps["tab10"]
        for i, patch in enumerate(bp["boxes"]):
            patch.set_facecolor(cmap(i / max(len(island_counts) - 1, 1)))
            patch.set_alpha(0.7)
        ax.set_xlabel("Residue Island Count")
        ax.set_ylabel(col)
        ax.set_title(TITLES[col])
    plt.tight_layout()
    out = output_dir / "sequence_metrics_boxplots_by_island_count.png"
    plt.savefig(out, dpi=150)
    print(f"Saved {out}")
    plt.close(fig)


def make_model_boxplot_figure(df, output_dir):
    model_order, positions, group_spans, ic_for_model = _model_order_and_positions(df)
    colors = _island_color_map(df)
    box_width = 0.55
    fig_width = max(16, (positions[-1] - positions[0]) * 0.6)
    fig, axes = plt.subplots(1, 3, figsize=(fig_width, 5))
    fig.suptitle("LigandMPNN Sequence Metrics by Model (sorted by island count)", fontsize=14)

    for ax, col in zip(axes.flat, METRIC_COLS):
        groups = [df.loc[df["model_name"] == m, col].dropna().astype(float).values
                  for m in model_order]
        bp = ax.boxplot(groups, positions=positions, widths=box_width,
                        patch_artist=True, notch=False, manage_ticks=False)
        for patch, model_id in zip(bp["boxes"], model_order):
            patch.set_facecolor(colors[ic_for_model[model_id]])
            patch.set_alpha(0.7)
        ax.set_xticks(positions)
        ax.set_xticklabels(model_order, rotation=45, ha="right", fontsize=5)
        ax.set_xlim(positions[0] - 0.8, positions[-1] + 0.8)
        ax.set_xlabel("Model")
        ax.set_ylabel(col)
        ax.set_title(TITLES[col])
        _draw_brackets(ax, group_spans)

    plt.tight_layout()
    out = output_dir / "sequence_metrics_boxplots_by_model.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved {out}")
    plt.close(fig)


def make_per_metric_figures(df, output_dir):
    island_counts = sorted(df["RESIDUE_ISLAND_COUNT"].dropna().unique().astype(int))
    n = len(island_counts)
    cmap = plt.colormaps["tab10"]
    colors = {ic: cmap(i / max(n - 1, 1)) for i, ic in enumerate(island_counts)}

    for col in METRIC_COLS:
        fig, axes = plt.subplots(1, n, figsize=(4 * n, 4), sharey=False)
        if n == 1:
            axes = [axes]
        fig.suptitle(f"{TITLES[col]} by Residue Island Count", fontsize=13)
        for ax, ic in zip(axes, island_counts):
            subset = df[df["RESIDUE_ISLAND_COUNT"] == ic]
            plot_col(ax, subset, col, color=colors[ic],
                     title_suffix=f"islands={ic} (n={len(subset)})")
        ymax = max(ax.get_ylim()[1] for ax in axes)
        for ax in axes:
            ax.set_ylim(0, ymax)
        plt.tight_layout()
        out = output_dir / f"sequence_{col}_by_island_count.png"
        plt.savefig(out, dpi=150)
        print(f"Saved {out}")
        plt.close(fig)


def make_per_model_figures(df, output_dir):
    model_ic = (
        df[["model_name", "RESIDUE_ISLAND_COUNT"]]
        .dropna()
        .drop_duplicates("model_name")
        .assign(RESIDUE_ISLAND_COUNT=lambda x: x["RESIDUE_ISLAND_COUNT"].astype(int))
        .sort_values(["RESIDUE_ISLAND_COUNT", "model_name"])
    )
    models = list(model_ic.itertuples(index=False))
    n = len(models)
    ncols = 7
    nrows = math.ceil(n / ncols)
    colors = _island_color_map(df)

    for col in METRIC_COLS:
        fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 4 * nrows))
        axes_flat = axes.flat
        fig.suptitle(f"{TITLES[col]} by Model (grouped by island count)", fontsize=13)
        for ax, row in zip(axes_flat, models):
            subset = df[df["model_name"] == row.model_name]
            plot_col(ax, subset, col, color=colors[row.RESIDUE_ISLAND_COUNT],
                     title_suffix=f"{row.model_name}\nislands={row.RESIDUE_ISLAND_COUNT} (n={len(subset)})")
        for ax in list(axes_flat)[n:]:
            ax.set_visible(False)
        ymax = max(ax.get_ylim()[1] for ax in list(axes.flat)[:n])
        for ax in list(axes.flat)[:n]:
            ax.set_ylim(0, ymax)
        plt.tight_layout()
        out = output_dir / f"sequence_{col}_by_model.png"
        plt.savefig(out, dpi=150)
        print(f"Saved {out}")
        plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence_csv", type=Path,
                        help="Path to campaign_analysis_sequence.csv")
    parser.add_argument("island_counts_csv", type=Path,
                        help="Path to island_counts.csv (columns: INPUT_ID, RESIDUE_ISLAND_COUNT)")
    parser.add_argument("--output-dir", type=Path, default=Path("."),
                        help="Directory for output PNGs (default: current directory)")
    args = parser.parse_args()

    df = pd.read_csv(args.sequence_csv)
    islands = pd.read_csv(args.island_counts_csv)
    df = df.merge(
        islands.rename(columns={"INPUT_ID": "model_name"}),
        on="model_name", how="left",
    )

    if "RESIDUE_ISLAND_COUNT" not in df.columns:
        raise ValueError(
            "RESIDUE_ISLAND_COUNT not found after merge — check island_counts_csv column names"
        )
    df["RESIDUE_ISLAND_COUNT"] = df["RESIDUE_ISLAND_COUNT"].astype(int)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    make_overview_figure(df, args.output_dir)
    make_boxplot_figure(df, args.output_dir)
    make_model_boxplot_figure(df, args.output_dir)
    make_per_metric_figures(df, args.output_dir)
    make_per_model_figures(df, args.output_dir)


if __name__ == "__main__":
    main()
