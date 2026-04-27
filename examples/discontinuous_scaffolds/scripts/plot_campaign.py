#!/usr/bin/env python3
"""Plot motif RMSD results and chai-1 score distributions from campaign analysis data.

Produces two RMSD figures (always):
  motif_rmsd_boxplots.png                    -- boxplots pooled by island count and by model
  rmsd_pass_rates.png                        -- scatterplots of three pass-rate derivative metrics

Produces chai-1 score figures (when score columns are present in campaign CSV):
  chai1_scores_histograms.png                -- overall score distributions
  chai1_scores_boxplots_by_island_count.png  -- boxplots per island count
  chai1_scores_boxplots_by_model.png         -- boxplots per model grouped by island count
  chai1_{col}_by_island_count.png            -- per-metric panels by island count (x5)
  chai1_{col}_by_model.png                   -- per-metric panels by model (x5)
"""

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

THRESHOLD_DEFAULT = 1.5  # angstroms

SCORE_COLS = ["aggregate_score", "ptm", "iptm", "has_inter_chain_clashes", "chain_chain_clashes"]
TITLES = {
    "aggregate_score": "Aggregate Score",
    "ptm": "pTM",
    "iptm": "ipTM",
    "has_inter_chain_clashes": "Has Inter-chain Clashes",
    "chain_chain_clashes": "Chain-Chain Clashes",
}
DISCRETE_COLS = {"has_inter_chain_clashes", "chain_chain_clashes"}


def _island_color_map(df):
    """Return dict mapping island count -> tab10 color."""
    island_counts = sorted(df["RESIDUE_ISLAND_COUNT"].dropna().unique().astype(int))
    n = len(island_counts)
    cmap = plt.colormaps["tab10"]
    return {ic: cmap(i / max(n - 1, 1)) for i, ic in enumerate(island_counts)}


def _model_order_and_positions(df):
    """Return (model_order, positions, group_spans) for grouped boxplots."""
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
    """Draw island-count group bracket annotations above the axes."""
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


def make_rmsd_boxplot_figure(df, threshold, output_dir):
    """Two-panel figure: motif_rmsd by island count and by model."""
    island_counts = sorted(df["RESIDUE_ISLAND_COUNT"].dropna().unique().astype(int))
    colors = _island_color_map(df)
    model_order, positions, group_spans, ic_for_model = _model_order_and_positions(df)

    box_width = 0.55
    fig_width = max(20, (positions[-1] - positions[0]) * 0.6 + 8)
    fig, (ax_ic, ax_model) = plt.subplots(1, 2, figsize=(fig_width, 6),
                                           gridspec_kw={"width_ratios": [1, max(2, len(model_order) / 5)]})
    fig.suptitle("Motif RMSD", fontsize=14)

    # Panel 1: pooled by island count
    groups_ic = [df.loc[df["RESIDUE_ISLAND_COUNT"] == ic, "motif_rmsd"].dropna().values
                 for ic in island_counts]
    bp = ax_ic.boxplot(groups_ic, labels=island_counts, patch_artist=True, notch=False)
    for i, patch in enumerate(bp["boxes"]):
        patch.set_facecolor(colors[island_counts[i]])
        patch.set_alpha(0.7)
    ax_ic.axhline(threshold, color="red", linestyle="--", linewidth=1, label=f"{threshold} Å threshold")
    ax_ic.set_xlabel("Residue Island Count")
    ax_ic.set_ylabel("Motif RMSD (Å)")
    ax_ic.set_title("Pooled by Island Count")
    ax_ic.legend(fontsize=8)

    # Panel 2: by model, grouped by island count
    groups_model = [df.loc[df["model_name"] == m, "motif_rmsd"].dropna().values
                    for m in model_order]
    bp2 = ax_model.boxplot(groups_model, positions=positions, widths=box_width,
                            patch_artist=True, notch=False, manage_ticks=False)
    for patch, model_id in zip(bp2["boxes"], model_order):
        patch.set_facecolor(colors[ic_for_model[model_id]])
        patch.set_alpha(0.7)
    ax_model.axhline(threshold, color="red", linestyle="--", linewidth=1, label=f"{threshold} Å threshold")
    ax_model.set_xticks(positions)
    ax_model.set_xticklabels(model_order, rotation=45, ha="right", fontsize=5)
    ax_model.set_xlim(positions[0] - 0.8, positions[-1] + 0.8)
    ax_model.set_xlabel("Model")
    ax_model.set_ylabel("Motif RMSD (Å)")
    ax_model.set_title("By Model (grouped by island count)")
    ax_model.legend(fontsize=8)
    _draw_brackets(ax_model, group_spans)

    plt.tight_layout()
    out = output_dir / "motif_rmsd_boxplots.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved {out}")
    plt.close(fig)


def make_pass_rate_figure(df, per_model, per_ic, threshold, output_dir):
    """Three-panel scatterplot figure of pass-rate derivative metrics."""
    island_counts = sorted(df["RESIDUE_ISLAND_COUNT"].dropna().unique().astype(int))
    colors = _island_color_map(df)
    model_order, positions, group_spans, ic_for_model = _model_order_and_positions(df)

    fig_width = max(18, len(model_order) * 0.4 + 10)
    fig, axes = plt.subplots(1, 3, figsize=(fig_width, 5),
                              gridspec_kw={"width_ratios": [max(2, len(model_order) / 8), 1, 1]})
    fig.suptitle(f"RMSD Pass Rates (threshold = {threshold} Å)", fontsize=13)

    # Panel 1: rmsd_pass_rate_per_model
    ax = axes[0]
    pass_rates = [per_model.loc[per_model["model_name"] == m, "rmsd_pass_rate_per_model"].values[0]
                  for m in model_order]
    point_colors = [colors[ic_for_model[m]] for m in model_order]
    ax.scatter(positions, pass_rates, c=point_colors, s=40, zorder=3)
    ax.set_xticks(positions)
    ax.set_xticklabels(model_order, rotation=45, ha="right", fontsize=5)
    ax.set_xlim(positions[0] - 0.8, positions[-1] + 0.8)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("Model")
    ax.set_ylabel("Pass Rate")
    ax.set_title("RMSD Pass Rate per Model")
    _draw_brackets(ax, group_spans)

    # Panel 2: rmsd_pass_rate_per_island_count
    ax = axes[1]
    ic_vals = per_ic["RESIDUE_ISLAND_COUNT"].astype(int).tolist()
    rate_vals = per_ic["rmsd_pass_rate_per_island_count"].tolist()
    pt_colors = [colors[ic] for ic in ic_vals]
    ax.plot(ic_vals, rate_vals, color="gray", linewidth=1, zorder=1)
    ax.scatter(ic_vals, rate_vals, c=pt_colors, s=60, zorder=3)
    ax.set_xticks(ic_vals)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("Residue Island Count")
    ax.set_ylabel("Pass Rate")
    ax.set_title("RMSD Pass Rate\nper Island Count")

    # Panel 3: rmsd_passing_model_rate_per_island_count
    ax = axes[2]
    model_rate_vals = per_ic["rmsd_passing_model_rate_per_island_count"].tolist()
    ax.plot(ic_vals, model_rate_vals, color="gray", linewidth=1, zorder=1)
    ax.scatter(ic_vals, model_rate_vals, c=pt_colors, s=60, zorder=3)
    ax.set_xticks(ic_vals)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("Residue Island Count")
    ax.set_ylabel("Rate")
    ax.set_title("Passing Model Rate\nper Island Count")

    plt.tight_layout()
    out = output_dir / "rmsd_pass_rates.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved {out}")
    plt.close(fig)


def plot_col(ax, data, col, color="steelblue", title_suffix=""):
    """Plot one column as a histogram or bar chart depending on type."""
    title = TITLES[col] + (f"\n{title_suffix}" if title_suffix else "")
    if col in DISCRETE_COLS:
        if col == "has_inter_chain_clashes":
            counts = data[col].value_counts().reindex([False, True], fill_value=0)
            ax.bar([str(v) for v in counts.index], counts.values,
                   color=["steelblue", "tomato"], edgecolor="white")
        else:
            counts = data[col].value_counts().sort_index()
            ax.bar([str(v) for v in counts.index], counts.values,
                   color=color, edgecolor="white")
        offset = max(counts.values) * 0.02
        for i, v in enumerate(counts.values):
            if v > 0:
                ax.text(i, v + offset, str(v), ha="center", va="bottom", fontsize=7)
    else:
        ax.hist(data[col], bins=30, color=color, edgecolor="white", linewidth=0.4)

    ax.set_xlabel(col)
    ax.set_ylabel("count")
    ax.set_title(title, fontsize=9)


def make_overview_figure(df, output_dir):
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    fig.suptitle(f"Chai-1 Score Distributions (n={len(df)})", fontsize=14)
    for ax, col in zip(axes.flat, SCORE_COLS):
        plot_col(ax, df, col)
    axes.flat[-1].set_visible(False)
    plt.tight_layout()
    out = output_dir / "chai1_scores_histograms.png"
    plt.savefig(out, dpi=150)
    print(f"Saved {out}")
    plt.close(fig)


def make_per_metric_figures(df, output_dir):
    """One figure per metric; each panel is one island count value."""
    island_counts = sorted(df["RESIDUE_ISLAND_COUNT"].dropna().unique().astype(int))
    n = len(island_counts)
    cmap = plt.colormaps["tab10"]
    colors = {ic: cmap(i / max(n - 1, 1)) for i, ic in enumerate(island_counts)}

    for col in SCORE_COLS:
        fig, axes = plt.subplots(1, n, figsize=(4 * n, 4), sharey=False)
        if n == 1:
            axes = [axes]
        fig.suptitle(f"{TITLES[col]} by Residue Island Count", fontsize=13)

        for ax, ic in zip(axes, island_counts):
            subset = df[df["RESIDUE_ISLAND_COUNT"] == ic]
            plot_col(ax, subset, col, color=colors[ic],
                     title_suffix=f"islands={ic} (n={len(subset)})")

        if col not in DISCRETE_COLS:
            ymax = max(ax.get_ylim()[1] for ax in axes)
            for ax in axes:
                ax.set_ylim(0, ymax)

        plt.tight_layout()
        out = output_dir / f"chai1_{col}_by_island_count.png"
        plt.savefig(out, dpi=150)
        print(f"Saved {out}")
        plt.close(fig)


def make_boxplot_figure(df, output_dir):
    """One multipanel figure; each panel is one metric, box per island count."""
    island_counts = sorted(df["RESIDUE_ISLAND_COUNT"].dropna().unique().astype(int))

    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    fig.suptitle("Chai-1 Scores vs Residue Island Count", fontsize=14)

    for ax, col in zip(axes.flat, SCORE_COLS):
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

    axes.flat[-1].set_visible(False)
    plt.tight_layout()
    out = output_dir / "chai1_scores_boxplots_by_island_count.png"
    plt.savefig(out, dpi=150)
    print(f"Saved {out}")
    plt.close(fig)


def make_per_model_figures(df, output_dir):
    """One figure per metric; each panel is one model, ordered by island count."""
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

    for col in SCORE_COLS:
        fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 4 * nrows))
        axes_flat = axes.flat
        fig.suptitle(f"{TITLES[col]} by Model (grouped by island count)", fontsize=13)

        for ax, row in zip(axes_flat, models):
            subset = df[df["model_name"] == row.model_name]
            plot_col(ax, subset, col, color=colors[row.RESIDUE_ISLAND_COUNT],
                     title_suffix=f"{row.model_name}\nislands={row.RESIDUE_ISLAND_COUNT} (n={len(subset)})")

        for ax in list(axes_flat)[n:]:
            ax.set_visible(False)

        if col not in DISCRETE_COLS:
            ymax = max(ax.get_ylim()[1] for ax in list(axes.flat)[:n])
            for ax in list(axes.flat)[:n]:
                ax.set_ylim(0, ymax)

        plt.tight_layout()
        out = output_dir / f"chai1_{col}_by_model.png"
        plt.savefig(out, dpi=150)
        print(f"Saved {out}")
        plt.close(fig)


def make_model_boxplot_figure(df, output_dir):
    """One multipanel figure; each panel is one metric, box per model sorted by island count."""
    model_ic = (
        df[["model_name", "RESIDUE_ISLAND_COUNT"]]
        .dropna()
        .drop_duplicates("model_name")
        .assign(RESIDUE_ISLAND_COUNT=lambda x: x["RESIDUE_ISLAND_COUNT"].astype(int))
        .sort_values(["RESIDUE_ISLAND_COUNT", "model_name"])
    )
    colors = _island_color_map(df)

    within_gap = 0.7
    between_gap = 1.8
    box_width = 0.55

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

    fig_width = max(20, (positions[-1] - positions[0]) * 0.6)
    fig, axes = plt.subplots(2, 3, figsize=(fig_width, 10))
    fig.suptitle("Chai-1 Scores by Model (sorted by island count)", fontsize=14)

    for ax, col in zip(axes.flat, SCORE_COLS):
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

    axes.flat[-1].set_visible(False)
    plt.tight_layout()
    out = output_dir / "chai1_scores_boxplots_by_model.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved {out}")
    plt.close(fig)


def compute_metrics(df, threshold):
    """Return (per_model_df, per_ic_df) with derivative metrics."""
    df = df.copy()
    df["passes"] = (df["motif_rmsd"] < threshold).astype(float)

    per_model = (
        df.groupby("model_name")["passes"]
        .mean()
        .reset_index()
        .rename(columns={"passes": "rmsd_pass_rate_per_model"})
    )

    # Merge island count onto per_model
    ic_lookup = (
        df[["model_name", "RESIDUE_ISLAND_COUNT"]]
        .drop_duplicates("model_name")
        .assign(RESIDUE_ISLAND_COUNT=lambda x: x["RESIDUE_ISLAND_COUNT"].astype(int))
    )
    per_model = per_model.merge(ic_lookup, on="model_name", how="left")

    per_ic_rate = (
        df.groupby("RESIDUE_ISLAND_COUNT")["passes"]
        .mean()
        .reset_index()
        .rename(columns={"passes": "rmsd_pass_rate_per_island_count"})
    )

    # Passing model rate: per island count, fraction of models with >=1 passing rmsd
    model_has_pass = (
        df.groupby("model_name")["passes"]
        .any()
        .reset_index()
        .rename(columns={"passes": "has_any_pass"})
        .merge(ic_lookup, on="model_name", how="left")
    )
    passing_model_rate = (
        model_has_pass.groupby("RESIDUE_ISLAND_COUNT")
        .apply(lambda g: g["has_any_pass"].sum() / len(g), include_groups=False)
        .reset_index()
        .rename(columns={0: "rmsd_passing_model_rate_per_island_count"})
    )

    per_ic = per_ic_rate.merge(passing_model_rate, on="RESIDUE_ISLAND_COUNT")
    per_ic["RESIDUE_ISLAND_COUNT"] = per_ic["RESIDUE_ISLAND_COUNT"].astype(int)
    per_ic = per_ic.sort_values("RESIDUE_ISLAND_COUNT")

    return per_model, per_ic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_csv", type=Path, help="Path to campaign_analysis.csv")
    parser.add_argument("island_counts_csv", type=Path, help="Path to island_counts.csv")
    parser.add_argument("--output-dir", type=Path, default=Path("."),
                        help="Directory for output PNGs (default: current directory)")
    parser.add_argument("--threshold", type=float, default=THRESHOLD_DEFAULT,
                        help=f"Motif RMSD pass threshold in angstroms (default: {THRESHOLD_DEFAULT})")
    args = parser.parse_args()

    campaign = pd.read_csv(args.campaign_csv)
    islands = pd.read_csv(args.island_counts_csv)
    df = campaign.merge(
        islands.rename(columns={"INPUT_ID": "model_name"}),
        on="model_name", how="left",
    )

    if "RESIDUE_ISLAND_COUNT" not in df.columns:
        raise ValueError("RESIDUE_ISLAND_COUNT not found after merge — check island_counts_csv column names")

    df["RESIDUE_ISLAND_COUNT"] = df["RESIDUE_ISLAND_COUNT"].astype(int)

    per_model, per_ic = compute_metrics(df, args.threshold)

    make_rmsd_boxplot_figure(df, args.threshold, args.output_dir)
    make_pass_rate_figure(df, per_model, per_ic, args.threshold, args.output_dir)

    score_cols_present = all(c in df.columns for c in SCORE_COLS)
    if score_cols_present:
        make_overview_figure(df, args.output_dir)
        make_per_metric_figures(df, args.output_dir)
        make_boxplot_figure(df, args.output_dir)
        make_per_model_figures(df, args.output_dir)
        make_model_boxplot_figure(df, args.output_dir)
    else:
        print("Skipping chai-1 score figures (score columns not present in campaign CSV).")


if __name__ == "__main__":
    main()
