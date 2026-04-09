"""
Pairwise objective conflict analysis for Carnot battery Pareto fronts.

Three metrics per objective pair:
  1. Spearman rank correlation  (direction + magnitude, -1 to +1)
  2. Pay-off degradation rate   (C_ij, 0=no conflict, 1=extreme conflict)
  3. Normalised Euclidean dist  (d_Euclidean, Laterre Eq.3.4 pairwise)

Usage:
    python analyze_conflict.py --wp DC-A [--out-dir plots]
"""

import argparse
import os
import glob
import warnings
from itertools import combinations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import TwoSlopeNorm
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")

# ── objectives ────────────────────────────────────────────────────────────────
OBJECTIVES = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]
OBJ_LABELS = {
    "eta_p2p":                r"$\eta_{p2p}$",
    "energy_density_thermal": r"$e_{th}$",
    "exergy_efficiency":      r"$\eta_{ex}$",
}
PAIRS = list(combinations(OBJECTIVES, 2))          # 3 pairs
PAIR_LABELS = [f"{OBJ_LABELS[a]}–{OBJ_LABELS[b]}" for a, b in PAIRS]

CB_CONFIGS = ["SBVCHP_SBORC", "SBVCHP_SRORC", "SRVCHP_SBORC", "SRVCHP_SRORC"]
CB_COLORS  = {"SBVCHP_SBORC": "#4C72B0", "SBVCHP_SRORC": "#DD8452",
              "SRVCHP_SBORC": "#55A868", "SRVCHP_SRORC": "#C44E52"}


# ── metric functions ──────────────────────────────────────────────────────────

def spearman(df: pd.DataFrame, a: str, b: str) -> float:
    r, _ = spearmanr(df[a].values, df[b].values)
    return float(r)


def payoff_degradation(df: pd.DataFrame, a: str, b: str) -> float:
    """
    C_ab = symmetric pay-off degradation rate ∈ [0, 1].
    δ_{a→b}: when a is at its max, fraction of b's range that is lost.
    C_ab = (δ_{a→b} + δ_{b→a}) / 2
    """
    range_a = df[a].max() - df[a].min()
    range_b = df[b].max() - df[b].min()
    if range_a == 0 or range_b == 0:
        return np.nan

    # solution closest to max(a)
    idx_max_a = df[a].idxmax()
    idx_max_b = df[b].idxmax()

    delta_a2b = (df[b].max() - df.loc[idx_max_a, b]) / range_b
    delta_b2a = (df[a].max() - df.loc[idx_max_b, a]) / range_a

    return float((delta_a2b + delta_b2a) / 2)


def d_euclidean(df: pd.DataFrame, a: str, b: str) -> float:
    """
    Laterre Eq.(3.4) extended to a single objective pair.
    d = sqrt( ((max_a - min_a)/max_a)^2 + ((max_b - min_b)/max_b)^2 )
    Uses max as reference (as in the paper); replaces with range/mean if max≈0.
    """
    def _span(col):
        hi, lo = df[col].max(), df[col].min()
        ref = hi if hi > 1e-9 else (hi - lo)   # guard against zero max
        return (hi - lo) / ref if ref > 1e-9 else 0.0

    return float(np.sqrt(_span(a)**2 + _span(b)**2))


# ── per-file metrics ──────────────────────────────────────────────────────────

def compute_metrics(df: pd.DataFrame) -> dict:
    """Return dict with keys like 'spearman_eta_p2p_energy_density_thermal'."""
    rec = {}
    for a, b in PAIRS:
        key = f"{a}|{b}"
        rec[f"spearman|{key}"]  = spearman(df, a, b)
        rec[f"payoff|{key}"]    = payoff_degradation(df, a, b)
        rec[f"d_eucl|{key}"]    = d_euclidean(df, a, b)
        rec["n_solutions"]      = len(df)
    return rec


def parse_filename(path: str) -> dict:
    """Extract wp / cb_config / fluid_hp / fluid_he from filename."""
    stem = os.path.splitext(os.path.basename(path))[0]
    if stem.startswith("pareto_"):
        stem = stem[7:]
    # format: wp_cbconfig_fluidhp_fluidhe
    parts = stem.split("_", 3)
    return {
        "wp":        parts[0] if len(parts) > 0 else "?",
        "cb_config": parts[1] + "_" + parts[2] if len(parts) > 2 else "?",
        "fluid_hp":  parts[3].split("_")[0] if len(parts) > 3 else "?",
        "fluid_he":  "_".join(parts[3].split("_")[1:]) if len(parts) > 3 else "?",
    }


def load_all(results_dir: str, wp: str) -> pd.DataFrame:
    pattern = os.path.join(results_dir, f"pareto_{wp}_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No files matching {pattern}")

    rows = []
    for f in files:
        df = pd.read_csv(f)
        if not all(o in df.columns for o in OBJECTIVES):
            continue
        meta = parse_filename(f)
        rec  = compute_metrics(df)
        rec.update(meta)
        rec["filepath"] = f
        rows.append(rec)

    return pd.DataFrame(rows)


# ── visualisation ─────────────────────────────────────────────────────────────

def _add_strip_with_mean(ax, data, pos, color, marker="o"):
    """Scatter + mean marker at horizontal position `pos`."""
    jitter = np.random.default_rng(42).uniform(-0.15, 0.15, size=len(data))
    ax.scatter(pos + jitter, data, s=18, alpha=0.55, color=color,
               edgecolors="none", zorder=2)
    ax.hlines(np.nanmean(data), pos - 0.3, pos + 0.3,
              color=color, linewidth=2.2, zorder=3)


def plot_summary(results: pd.DataFrame, wp: str, out_dir: str):
    """
    Figure 1: distribution of each metric × pair across all configs.
    Rows = 3 metrics, cols = 3 pairs.  Strips coloured by CB config.
    """
    METRICS    = ["spearman", "payoff", "d_eucl"]
    METRIC_LBLS = {
        "spearman": "Spearman  $r_s$\n[−1 conflict … +1 synergy]",
        "payoff":   "Pay-off degradation  $C_{ij}$\n[0 = no conflict … 1 = extreme]",
        "d_eucl":   "Normalised Euclidean  $d_{Euclidean}$\n(Laterre Eq. 3.4 pairwise)",
    }
    YLIMS = {
        "spearman": (-1.05, 1.05),
        "payoff":   (-0.05, 1.05),
        "d_eucl":   (0,     None),
    }
    HREFS = {"spearman": 0.0, "payoff": 0.5, "d_eucl": None}

    fig, axes = plt.subplots(3, 3, figsize=(13, 10),
                             constrained_layout=True)
    fig.suptitle(f"Pairwise conflict metrics — Working point {wp}  "
                 f"({len(results)} configurations)",
                 fontsize=12, fontweight="bold")

    for row, metric in enumerate(METRICS):
        for col, (pair, plabel) in enumerate(zip(PAIRS, PAIR_LABELS)):
            ax  = axes[row, col]
            key = f"{metric}|{pair[0]}|{pair[1]}"
            vals_all = results[key].dropna().values

            # strip per CB config
            for xpos, cfg in enumerate(CB_CONFIGS):
                sub = results[results["cb_config"] == cfg][key].dropna().values
                if len(sub):
                    _add_strip_with_mean(ax, sub, xpos, CB_COLORS[cfg])

            ax.set_xticks(range(len(CB_CONFIGS)))
            ax.set_xticklabels(
                [c.replace("_", "\n") for c in CB_CONFIGS],
                fontsize=7)
            ax.set_ylim(YLIMS[metric])
            ax.grid(axis="y", lw=0.4, alpha=0.5)

            href = HREFS[metric]
            if href is not None:
                ax.axhline(href, color="#888", lw=0.9, ls="--", alpha=0.6)

            # colour fill for Spearman
            if metric == "spearman":
                ax.axhspan(-1.05, 0, color="#ffdddd", alpha=0.25, zorder=0)
                ax.axhspan(0, 1.05, color="#ddeeff", alpha=0.25, zorder=0)
                ax.text(0.99, 0.97, "conflict", transform=ax.transAxes,
                        ha="right", va="top", fontsize=7, color="#cc4444", alpha=0.7)
                ax.text(0.99, 0.03, "synergy", transform=ax.transAxes,
                        ha="right", va="bottom", fontsize=7, color="#2266cc", alpha=0.7)

            # global mean annotation
            gmean = np.nanmean(vals_all)
            ax.text(0.01, 0.97,
                    f"mean = {gmean:+.3f}" if metric == "spearman"
                    else f"mean = {gmean:.3f}",
                    transform=ax.transAxes, ha="left", va="top",
                    fontsize=8, color="#333333",
                    bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))

            if row == 0:
                ax.set_title(plabel, fontsize=9, fontweight="bold")
            if col == 0:
                ax.set_ylabel(METRIC_LBLS[metric], fontsize=8)

    # legend
    handles = [plt.Line2D([0], [0], color=CB_COLORS[c], lw=3, label=c)
               for c in CB_CONFIGS]
    fig.legend(handles=handles, loc="lower center",
               ncol=4, fontsize=8, frameon=False,
               bbox_to_anchor=(0.5, -0.02))

    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"conflict_summary_{wp}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")
    return out


def plot_heatmap(results: pd.DataFrame, wp: str, out_dir: str):
    """
    Figure 2: per-config heatmap for each metric.
    Rows = configs sorted by cb_config, cols = objective pairs.
    """
    METRICS = ["spearman", "payoff", "d_eucl"]
    METRIC_TITLES = {
        "spearman": r"Spearman $r_s$",
        "payoff":   r"Pay-off $C_{ij}$",
        "d_eucl":   r"$d_{Euclidean}$",
    }

    # short label per row
    results = results.copy()
    results["config_label"] = (results["cb_config"] + "\n"
                               + results["fluid_hp"] + "/"
                               + results["fluid_he"])

    row_order = sorted(results["config_label"].unique())
    n_rows = len(row_order)

    fig, axes = plt.subplots(1, 3, figsize=(14, max(4, n_rows * 0.28 + 1.2)),
                             constrained_layout=True)
    fig.suptitle(f"Per-configuration conflict heatmaps — {wp}", fontsize=11,
                 fontweight="bold")

    for ax, metric in zip(axes, METRICS):
        # build matrix
        matrix = np.full((n_rows, 3), np.nan)
        for r, rlbl in enumerate(row_order):
            row_data = results[results["config_label"] == rlbl]
            for c, (pa, pb) in enumerate(PAIRS):
                key = f"{metric}|{pa}|{pb}"
                if key in row_data.columns and len(row_data):
                    matrix[r, c] = row_data[key].iloc[0]

        if metric == "spearman":
            cmap  = "RdBu_r"
            norm  = TwoSlopeNorm(vmin=-1, vcenter=0, vmax=1)
            vargs = dict(cmap=cmap, norm=norm)
        else:
            vmax  = np.nanmax(matrix) * 1.05
            vargs = dict(cmap="YlOrRd", vmin=0, vmax=vmax)

        im = ax.imshow(matrix, aspect="auto", **vargs)
        fig.colorbar(im, ax=ax, shrink=0.5, pad=0.01)

        ax.set_xticks(range(3))
        ax.set_xticklabels(PAIR_LABELS, fontsize=7.5)
        ax.set_yticks(range(n_rows))
        ax.set_yticklabels(row_order, fontsize=6.5)
        ax.set_title(METRIC_TITLES[metric], fontsize=9, fontweight="bold")

        # annotate cells
        for r in range(n_rows):
            for c in range(3):
                v = matrix[r, c]
                if not np.isnan(v):
                    ax.text(c, r, f"{v:+.2f}" if metric == "spearman"
                            else f"{v:.2f}",
                            ha="center", va="center", fontsize=5.5,
                            color="white" if abs(v) > 0.6 else "black")

    out = os.path.join(out_dir, f"conflict_heatmap_{wp}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")
    return out


def plot_aggregated_bar(results: pd.DataFrame, wp: str, out_dir: str):
    """
    Figure 3: aggregated mean ± std per objective pair, one panel per metric.
    Clean summary figure suitable for the paper.
    """
    METRICS = ["spearman", "payoff", "d_eucl"]
    METRIC_TITLES = {
        "spearman": r"Spearman $r_s$",
        "payoff":   r"Pay-off degradation $C_{ij}$",
        "d_eucl":   r"Normalised Euclidean $d_{Eucl}$",
    }
    YLIMS = {"spearman": (-1.05, 1.05), "payoff": (-0.05, 1.05), "d_eucl": (0, None)}

    fig, axes = plt.subplots(1, 3, figsize=(11, 4), constrained_layout=True)
    fig.suptitle(f"Aggregated conflict metrics — {wp}  "
                 f"(mean ± std across {len(results)} configs)",
                 fontsize=10, fontweight="bold")

    PAIR_SHORT = [r"$\eta_{p2p}$–$e_{th}$",
                  r"$\eta_{p2p}$–$\eta_{ex}$",
                  r"$e_{th}$–$\eta_{ex}$"]
    PAIR_COLORS = ["#E24A33", "#348ABD", "#988ED5"]

    for ax, metric in zip(axes, METRICS):
        means, stds = [], []
        for pa, pb in PAIRS:
            key  = f"{metric}|{pa}|{pb}"
            vals = results[key].dropna().values
            means.append(np.nanmean(vals))
            stds.append(np.nanstd(vals))

        x   = np.arange(3)
        bars = ax.bar(x, means, yerr=stds, capsize=5,
                      color=PAIR_COLORS, alpha=0.82, width=0.55,
                      error_kw=dict(lw=1.2, ecolor="#444"))

        # value labels
        for xi, (m, s) in enumerate(zip(means, stds)):
            ax.text(xi, m + s + 0.02 * (abs(ax.get_ylim()[1] - ax.get_ylim()[0]) or 1),
                    f"{m:+.3f}" if metric == "spearman" else f"{m:.3f}",
                    ha="center", va="bottom", fontsize=8.5, fontweight="bold",
                    color=PAIR_COLORS[xi])

        if metric == "spearman":
            ax.axhline(0, color="#888", lw=0.9, ls="--")
            ax.axhspan(-1.05, 0, color="#ffeeee", alpha=0.3, zorder=0)
            ax.axhspan(0, 1.05, color="#eef5ff", alpha=0.3, zorder=0)
            ax.text(0.98, 0.97, "conflict region", transform=ax.transAxes,
                    ha="right", va="top", fontsize=7.5, color="#cc4444", alpha=0.8)

        ax.set_xticks(x)
        ax.set_xticklabels(PAIR_SHORT, fontsize=9)
        ax.set_ylim(YLIMS[metric])
        ax.set_title(METRIC_TITLES[metric], fontsize=9.5, fontweight="bold")
        ax.grid(axis="y", lw=0.4, alpha=0.5)
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)

    out = os.path.join(out_dir, f"conflict_aggregated_{wp}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")
    return out


# ── CSV output ────────────────────────────────────────────────────────────────

def save_csv(results: pd.DataFrame, wp: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"conflict_metrics_{wp}.csv")

    # tidy: rename metric columns for readability
    rename = {}
    for metric in ["spearman", "payoff", "d_eucl"]:
        for pa, pb in PAIRS:
            old = f"{metric}|{pa}|{pb}"
            new = f"{metric}_{'_'.join(OBJ_LABELS[pa].strip('$').replace('_','').replace('{','').replace('}',''))}_{'_'.join(OBJ_LABELS[pb].strip('$').replace('_','').replace('{','').replace('}',''))}"
            rename[old] = new

    out_df = results.rename(columns=rename)
    # keep only useful columns
    keep = ["wp", "cb_config", "fluid_hp", "fluid_he", "n_solutions"] + list(rename.values())
    keep = [c for c in keep if c in out_df.columns]
    out_df[keep].to_csv(out, index=False, float_format="%.5f")
    print(f"Saved → {out}")


# ── print summary table ───────────────────────────────────────────────────────

def print_summary(results: pd.DataFrame, wp: str):
    print(f"\n{'='*65}")
    print(f"  Conflict metrics summary — {wp}  ({len(results)} configurations)")
    print(f"{'='*65}")
    print(f"{'Pair':<28} {'Spearman':>10} {'Payoff C':>10} {'d_Eucl':>10}")
    print(f"{'-'*65}")
    for (pa, pb), plabel in zip(PAIRS, PAIR_LABELS):
        r_s  = results[f"spearman|{pa}|{pb}"].dropna()
        c_ij = results[f"payoff|{pa}|{pb}"].dropna()
        d_ij = results[f"d_eucl|{pa}|{pb}"].dropna()
        clean_label = plabel.replace("$", "").replace("\\", "").replace("{", "").replace("}", "")
        print(f"  {clean_label:<26} "
              f"{r_s.mean():>+8.3f}±{r_s.std():.2f}"
              f"  {c_ij.mean():>7.3f}±{c_ij.std():.2f}"
              f"  {d_ij.mean():>7.3f}±{d_ij.std():.2f}")
    print(f"{'='*65}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Quantify pairwise objective conflict in Pareto front results.")
    parser.add_argument("--wp",      default="DC-A",
                        help="Working point prefix (default: DC-A)")
    parser.add_argument("--results", default=None,
                        help="Path to results/ directory (auto-detected if omitted)")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory (default: <script_dir>/plots)")
    args = parser.parse_args()

    script_dir  = os.path.dirname(os.path.abspath(__file__))
    results_dir = args.results or os.path.join(script_dir, "results")
    out_dir     = args.out_dir  or os.path.join(script_dir, "plots")

    print(f"Loading {args.wp} results from {results_dir} …")
    results = load_all(results_dir, args.wp)
    print(f"  → {len(results)} configurations loaded")

    print_summary(results, args.wp)
    save_csv(results, args.wp, out_dir)
    plot_summary(results, args.wp, out_dir)
    plot_heatmap(results, args.wp, out_dir)
    plot_aggregated_bar(results, args.wp, out_dir)
