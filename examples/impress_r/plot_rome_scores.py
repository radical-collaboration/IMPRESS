"""
IMPRESS-R ROME score analysis.

Produces three plots:
  1. Per-pipeline avg_pLDDT trajectory over passes (depth-0 pipelines only, one line each)
  2. Box plot of avg_pLDDT distribution per pass across all pipelines and depths
  3. Global mean per pass (all depths) with linear regression trend

Usage:
    python plot_rome_scores.py [--csv-dir DIR] [--log FILE] [--out-dir DIR]

Defaults:
    --csv-dir  /scratch/bblj/$USER/IMPRESS_outputs
    --log      logs/impress_21736435.out   (relative to script dir)
    --out-dir  .   (saves next to this script)
"""

import argparse
import csv
import os
import re
import statistics
from collections import defaultdict
from itertools import groupby

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── Argument parsing ──────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
_user   = os.environ.get("USER", "mgoliyad1")
_scratch = os.environ.get("SCRATCH", f"/scratch/bblj/{_user}")
parser.add_argument("--csv-dir",  default=f"{_scratch}/IMPRESS_outputs")
parser.add_argument("--log",      default=os.path.join(os.path.dirname(__file__), "logs", "impress_21736435.out"))
parser.add_argument("--out-dir",  default=os.path.dirname(__file__))
args = parser.parse_args()

os.makedirs(args.out_dir, exist_ok=True)

# ── Load pLDDT data ───────────────────────────────────────────────────────────
# records: list of (root, pipeline, depth, pass_num, mean_plddt, [values])
records = []
pattern = re.compile(r"af_stats_(p\d+(?:_sub\d+)*?)_pass_(\d+)\.csv")

for fname in os.listdir(args.csv_dir):
    m = pattern.match(fname)
    if not m:
        continue
    pipeline, pass_num = m.group(1), int(m.group(2))
    depth = pipeline.count("_sub")
    root  = pipeline.split("_sub")[0]
    path  = os.path.join(args.csv_dir, fname)
    with open(path) as f:
        vals = [float(r["avg_plddt"]) for r in csv.DictReader(f) if r.get("avg_plddt")]
    if vals:
        records.append((root, pipeline, depth, pass_num, statistics.mean(vals), vals))

# depth_pass: (depth, pass_num) -> [values]  — used for depth-stratified plot
depth_pass = defaultdict(list)
for root, pipeline, depth, pass_num, mean, vals in records:
    depth_pass[(depth, pass_num)].extend(vals)

# ── Load ROME training events from log ───────────────────────────────────────
# Extract unique (round, timestamp) from log lines like:
#   12:02:36.532 [INFO] [ROME-TRAINER] submitting training round 1 (3 designs ...) -> v1
rome_rounds = {}  # round_num -> HH:MM as float minutes-since-start
log_start = None

if os.path.exists(args.log):
    rome_pat = re.compile(r"(\d{2}):(\d{2}):\d{2}\.\d+.*ROME-TRAINER.*submitting training round (\d+)")
    with open(args.log) as f:
        for line in f:
            clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
            m = rome_pat.search(clean)
            if m:
                h, mi, rnd = int(m.group(1)), int(m.group(2)), int(m.group(3))
                t = h * 60 + mi
                if log_start is None:
                    log_start = t
                if rnd not in rome_rounds:
                    rome_rounds[rnd] = t - log_start  # minutes since job start

# ── Palette ───────────────────────────────────────────────────────────────────
PIPELINES = sorted({r[0] for r in records})
cmap = matplotlib.colormaps["tab20"].resampled(len(PIPELINES))
COLORS = {p: cmap(i) for i, p in enumerate(PIPELINES)}

ACCENT   = "#E05C3A"   # warm orange-red for trend / mean
GRID_COL = "#E8E8E8"

plt.rcParams.update({
    "font.family": "sans-serif",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID_COL,
    "grid.linewidth": 0.7,
})

# ═══════════════════════════════════════════════════════════════════════════════
# Plot 1 — Per-pipeline trajectory (depth-0 only)
# ═══════════════════════════════════════════════════════════════════════════════
fig1, ax1 = plt.subplots(figsize=(11, 6))

depth0 = [(root, pass_num, mean) for root, pipeline, depth, pass_num, mean, _ in records if depth == 0]

pipe_data = defaultdict(dict)   # root -> {pass_num: mean}
for root, pass_num, mean in depth0:
    pipe_data[root][pass_num] = mean

for pipe in sorted(pipe_data):
    xs = sorted(pipe_data[pipe])
    ys = [pipe_data[pipe][x] for x in xs]
    ax1.plot(xs, ys, marker="o", markersize=4, linewidth=1.5,
             color=COLORS[pipe], label=pipe, alpha=0.85)

ax1.set_xlabel("Pass", fontsize=11)
ax1.set_ylabel("avg_pLDDT", fontsize=11)
ax1.set_title("Per-pipeline avg_pLDDT over passes  (root pipelines only)", fontsize=13, pad=10)
ax1.set_ylim(40, 100)
ax1.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
ax1.legend(ncol=4, fontsize=8, loc="lower right", framealpha=0.7)
ax1.axhline(75, color="#999999", linewidth=0.8, linestyle="--", label="threshold 75")

fig1.tight_layout()
out1 = os.path.join(args.out_dir, "rome_pipeline_trajectories.png")
fig1.savefig(out1, dpi=150)
print(f"Saved: {out1}")

# ═══════════════════════════════════════════════════════════════════════════════
# Plot 2 — Box plot per pass (all depths)
# ═══════════════════════════════════════════════════════════════════════════════
pass_vals = defaultdict(list)
for root, pipeline, depth, pass_num, mean, vals in records:
    pass_vals[pass_num].extend(vals)

all_passes = sorted(pass_vals)
box_data   = [pass_vals[p] for p in all_passes]
counts     = [len(pass_vals[p]) for p in all_passes]

fig2, ax2 = plt.subplots(figsize=(11, 6))
bp = ax2.boxplot(box_data, positions=all_passes, widths=0.6,
                 patch_artist=True, showfliers=True,
                 flierprops=dict(marker=".", markersize=3, alpha=0.4, color="#AAAAAA"),
                 medianprops=dict(color=ACCENT, linewidth=2),
                 boxprops=dict(facecolor="#D6E8F5", alpha=0.85))

# Annotate n per pass
for x, n in zip(all_passes, counts):
    ax2.text(x, 38.5, f"n={n}", ha="center", fontsize=7, color="#666666")

ax2.set_xlabel("Pass", fontsize=11)
ax2.set_ylabel("avg_pLDDT", fontsize=11)
ax2.set_title("avg_pLDDT distribution per pass  (all pipelines and depths)", fontsize=13, pad=10)
ax2.set_ylim(36, 100)
ax2.axhline(75, color="#999999", linewidth=0.8, linestyle="--")
ax2.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

fig2.tight_layout()
out2 = os.path.join(args.out_dir, "rome_pass_distribution.png")
fig2.savefig(out2, dpi=150)
print(f"Saved: {out2}")

# ═══════════════════════════════════════════════════════════════════════════════
# Plot 3 — Mean per pass stratified by sub-pipeline depth + global trend
# ═══════════════════════════════════════════════════════════════════════════════
DEPTH_COLORS = {0: "#4C72B0", 1: "#DD8452", 2: "#55A868", 3: "#C44E52"}
DEPTH_LABELS = {0: "depth 0 (root)", 1: "depth 1 (sub1)",
                2: "depth 2 (sub1_sub2)", 3: "depth 3 (sub1_sub2_sub3)"}

fig3, ax3 = plt.subplots(figsize=(12, 6))

all_depths = sorted({d for d, p in depth_pass})
for depth in all_depths:
    xs = sorted(p for d, p in depth_pass if d == depth)
    ys = [statistics.mean(depth_pass[(depth, p)]) for p in xs]
    ns = [len(depth_pass[(depth, p)]) for p in xs]
    color = DEPTH_COLORS.get(depth, "#888888")
    ax3.plot(xs, ys, marker="o", markersize=5, linewidth=1.8,
             color=color, label=DEPTH_LABELS.get(depth, f"depth {depth}"), zorder=3)
    for x, y, n in zip(xs, ys, ns):
        ax3.text(x, y + 0.5, f"{y:.1f}", ha="center", fontsize=6.5,
                 color=color, alpha=0.85)

# Global mean + regression
pass_means = {p: statistics.mean(v) for p, v in pass_vals.items()}
xs_all = sorted(pass_means)
ys_all = [pass_means[x] for x in xs_all]
coef = np.polyfit(xs_all, ys_all, 1)
trend_y = np.polyval(coef, xs_all)

ax3.plot(xs_all, ys_all, linewidth=2.2, linestyle="--",
         color=ACCENT, alpha=0.6,
         label=f"global mean  (slope {coef[0]:+.3f}/pass)", zorder=2)

# ROME round markers
if rome_rounds:
    max_t = max(rome_rounds.values())
    for rnd in sorted(rome_rounds)[:10]:
        t_frac = rome_rounds[rnd] / max_t if max_t > 0 else 0
        x_pos = xs_all[0] + t_frac * (xs_all[-1] - xs_all[0])
        ax3.axvline(x_pos, color="#99AACC", linewidth=0.55, linestyle=":", alpha=0.65)
        ax3.text(x_pos, 79.5, f"v{rnd}", fontsize=6, color="#667799",
                 ha="center", rotation=90, va="bottom")

ax3.set_xlabel("Pass", fontsize=11)
ax3.set_ylabel("Mean avg_pLDDT", fontsize=11)
ax3.set_title("avg_pLDDT per pass by sub-pipeline depth  (ROME training markers in blue)", fontsize=13, pad=10)
ax3.set_ylim(78, 100)
ax3.axhline(75, color="#CCCCCC", linewidth=0.7, linestyle=":")
ax3.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
ax3.legend(fontsize=9, loc="lower right")

fig3.tight_layout()
out3 = os.path.join(args.out_dir, "rome_global_trend.png")
fig3.savefig(out3, dpi=150)
print(f"Saved: {out3}")

# ── Text summary ──────────────────────────────────────────────────────────────
print("\n=== Per-pass global mean (all depths) ===")
print(f"{'Pass':>4}  {'Mean':>7}  {'Median':>7}  {'n (designs)':>11}")
for p in xs_all:
    vals = pass_vals[p]
    print(f"  {p:2d}    {statistics.mean(vals):7.2f}  {statistics.median(vals):7.2f}  {len(vals):>11}")

print("\n=== Per-depth per-pass mean ===")
print(f"{'Depth':>5}  {'Pass':>4}  {'Mean':>7}  {'Median':>7}  {'n':>4}")
for (depth, pass_num) in sorted(depth_pass):
    vals = depth_pass[(depth, pass_num)]
    print(f"  {depth:3d}    {pass_num:2d}    {statistics.mean(vals):7.2f}  {statistics.median(vals):7.2f}  {len(vals):>4}")

slope = coef[0]
print(f"\nGlobal linear trend slope: {slope:+.4f} pLDDT / pass")
if slope > 0.2:
    print("  → Positive trend: ROME appears to be improving sequence quality.")
elif slope < -0.2:
    print("  → Negative trend: scores declining — may reflect harder proteins in later passes.")
else:
    print("  → Flat trend: no clear improvement signal yet.")
