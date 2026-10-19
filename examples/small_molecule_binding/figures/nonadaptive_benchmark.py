"""Adaptive vs pass-through routing, 1 node / 32 pipelines / 1 h (smb 23).

usage: python figures/nonadaptive_benchmark.py   (from examples/small_molecule_binding)
writes figures/nonadaptive_benchmark.png
"""
import glob
import json
import os

import matplotlib.pyplot as plt
import numpy as np

import plot_style as ps

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "..", "logs")
RUNS = ["22927576", "22967619", "22999614"]
WARMUP_MIN = 10
PASS_PLDDT, HQ_PLDDT, HQ_IPTM = 75.0, 90.0, 0.8
STAGES = ["rfd3", "mpnn", "packmin", "fastrelax", "filter_shape", "boltz"]


def load(job):
    """Session start, tool completions (min, stage), and folds (min, plddt, iptm)."""
    d = os.path.join(LOGS, job)
    tel = glob.glob(os.path.join(d, "telemetry", "*.jsonl"))[0]
    t0, last, comp = None, 0.0, []
    for line in open(tel):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        t = e.get("event_time") or e.get("checkpoint_time")
        if t:
            last = max(last, t)
        if e.get("event_type") == "SessionStarted":
            t0 = e["event_time"]
        elif e.get("event_type") == "TaskCompleted":
            stage = e["attributes"].get("asyncflow.workflow_id", "").split(":")[-1]
            comp.append((e["event_time"], stage))
    folds = []
    for bd in glob.glob(os.path.join(d, "p*", "*_boltz")):
        best = None
        for c in glob.glob(os.path.join(bd, "out", "boltz_results_*", "predictions",
                                        "*", "confidence_*.json")):
            data = json.load(open(c))
            if best is None or data.get("complex_plddt", 0) > best[1]:
                best = (os.path.getmtime(c), data.get("complex_plddt", 0),
                        data.get("ligand_iptm") or 0.0)
        if best:
            folds.append(((best[0] - t0) / 60, best[1] * 100, best[2]))
    end_min = min((last - t0) / 60, ps.WINDOW_MIN)
    comp = [((t - t0) / 60, s) for t, s in comp]
    folds = sorted(f for f in folds if 0 <= f[0] <= end_min)
    return dict(end=end_min, comp=comp, folds=folds)


def main():
    ps.apply_rcparams()
    data = {j: load(j) for j in RUNS}

    fig, axes = plt.subplots(2, 2, figsize=(15, 12))
    fig.subplots_adjust(left=0.12, right=0.97, top=0.91, bottom=0.14,
                        hspace=0.36, wspace=0.28)
    (ax_pass, ax_hq), (ax_rate, ax_q) = axes

    # (a, b) cumulative passing and high-quality folds over the equal window
    for ax, keep, ylabel, title in (
        (ax_pass, lambda f: f[1] >= PASS_PLDDT, "folds passed (cumulative)",
         "a  Passing folds"),
        (ax_hq, lambda f: f[1] >= HQ_PLDDT and f[2] >= HQ_IPTM,
         "high-quality folds (cumulative)",
         "b  High-quality folds"),
    ):
        totals = []
        for j in RUNS:
            st = ps.style_for(j)
            t = [f[0] for f in data[j]["folds"] if keep(f)]
            x = np.concatenate([[0], np.repeat(t, 2), [data[j]["end"]]])
            y = np.concatenate([[0, 0], np.repeat(np.arange(1, len(t) + 1), 2)])
            ax.plot(x, y, **ps.line_kw(j))
            totals.append((len(t), st))
        # Totals as a stacked block in axes coordinates, ordered like the curves.
        # pass-through and naive finish within 2 folds of each other, so a label
        # on each line's end would overlap however it is offset.
        for n, (count, st) in enumerate(sorted(totals, reverse=True,
                                               key=lambda c: c[0])):
            ax.annotate(f"{st.short} {count}", xy=(0.97, 0.94 - 0.075 * n),
                        xycoords="axes fraction", ha="right", va="top",
                        fontsize="medium", fontweight="bold", color=st.color,
                        zorder=ps.Z["annot"],
                        bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                                  edgecolor="none", alpha=0.85))
        ax.axvspan(0, WARMUP_MIN, color=ps.GRID, alpha=0.35, linewidth=0,
                   zorder=ps.Z["band"])
        ax.set_xlim(0, ps.WINDOW_MIN)
        ax.set_ylim(0, ax.get_ylim()[1] * 1.18)
        ax.set_xlabel("minutes since session start")
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc="left")

    # (c) tool completions per node-hour, minute 10 to the end of the window
    y = np.arange(len(STAGES))
    h = 0.27
    for k, j in enumerate(RUNS):
        st = ps.style_for(j)
        d = data[j]
        hours = (d["end"] - WARMUP_MIN) / 60
        rate = [sum(1 for t, s in d["comp"] if s == stg and WARMUP_MIN <= t <= d["end"])
                / hours for stg in STAGES]
        yy = y + (k - (len(RUNS) - 1) / 2) * h
        ax_rate.barh(yy, rate, height=h * 0.9, color=st.color, label=st.label,
                     zorder=ps.Z["bar"])
        for yi, r in zip(yy, rate):
            ax_rate.annotate(f"{r:.0f}", xy=(r, yi), xytext=(4, 0),
                             textcoords="offset points", va="center",
                             fontsize="x-small", color=ps.INK_SECONDARY,
                             zorder=ps.Z["annot"])
    ax_rate.set_yticks(y, STAGES, fontsize="medium")
    ax_rate.invert_yaxis()
    ax_rate.set_xlabel("completions per node-hour (minute 10 to end)")
    ax_rate.set_title("c  Tool throughput", loc="left")
    ax_rate.legend(loc="lower right", fontsize="medium")
    ax_rate.set_xlim(0, ax_rate.get_xlim()[1] * 1.08)
    ax_rate.grid(axis="y", visible=False)

    # (d) per-fold quality
    for j in RUNS:
        st = ps.style_for(j)
        f = np.array([(p, i) for _, p, i in data[j]["folds"]])
        ax_q.scatter(f[:, 0], f[:, 1], s=24, marker=st.marker, facecolor="white",
                     edgecolor=st.color, linewidth=1.0, alpha=0.7, zorder=ps.Z["line"],
                     label=f"{st.short} (n={len(f)})")
    ax_q.axvline(PASS_PLDDT, color=ps.NEUTRAL_SERIES, linewidth=1, linestyle="--",
                 zorder=ps.Z["band"])
    ax_q.axvline(HQ_PLDDT, color=ps.NEUTRAL_SERIES, linewidth=1, linestyle=":",
                 zorder=ps.Z["band"])
    ax_q.axhline(HQ_IPTM, color=ps.NEUTRAL_SERIES, linewidth=1, linestyle=":",
                 zorder=ps.Z["band"])
    ax_q.text(PASS_PLDDT, 1.0, " pass", color=ps.INK_SECONDARY, fontsize="small",
              va="top", transform=ax_q.get_xaxis_transform())
    ax_q.text(HQ_PLDDT, 1.0, " high quality", color=ps.INK_SECONDARY,
              fontsize="small", va="top", transform=ax_q.get_xaxis_transform())
    ax_q.set_xlabel("Boltz complex pLDDT (best model)")
    ax_q.set_ylabel("ligand ipTM")
    ax_q.set_title("d  Fold quality", loc="left")
    ax_q.legend(loc="lower right", scatterpoints=1, markerscale=1.6,
                fontsize="medium")

    fig.suptitle("Adaptive vs pass-through vs open-loop — 1 node, 32 pipelines, 1 h",
                 x=0.12, ha="left", fontsize="x-large", fontweight="bold")
    ps.caption(fig, (
        "One run per configuration; no spread is shown, so small differences are "
        "not meaningful. All three share a branch, inputs, thresholds, GPU pinning "
        "and the 60 s staggered start, and each removes one more feedback path: "
        "pass-through drops adaptive routing (no retries, escalation or guided rfd3), "
        "and naive additionally takes the first candidate at every stage instead of "
        f"the best-scoring one. Time series cut to the first {ps.WINDOW_MIN} min of "
        "each session; the shaded first 10 min is the stagger ramp and is excluded "
        "from (c). Folds are timed by their Boltz confidence file. Pass: complex "
        "pLDDT ≥ 75; high quality: pLDDT ≥ 90 and ligand ipTM ≥ 0.8 (best model per "
        "fold). Colour is fixed per run and is not a ranking: pass-through and naive "
        "are within 1 % of each other on passing folds per GPU-hour."),
        bottom=0.17)
    out = os.path.join(HERE, "nonadaptive_benchmark.png")
    fig.savefig(out)
    print(out)


if __name__ == "__main__":
    main()
