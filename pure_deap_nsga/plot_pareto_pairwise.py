"""
Pairwise Pareto front visualization for a single optimization scenario.

Usage:
    python plot_pareto_pairwise.py <csv_path> [--out-dir <dir>] [--config <json>]

Each subplot shows the Pareto front projected onto one pair of objectives.
Points are coloured by their rank along the first listed objective so you can
trace the trade-off across panels.
"""

import argparse
import json
import math
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

# ── objective display metadata ────────────────────────────────────────────────
OBJ_META = {
    "eta_p2p": {
        "label": r"Round-trip efficiency $\eta_{p2p}$",
        "short": r"$\eta_{p2p}$",
        "unit": "–",
        "scale": 1.0,
        "pct": True,        # display as percentage
    },
    "energy_density_thermal": {
        "label": "Thermal energy density",
        "short": r"$e_{th}$",
        "unit": r"kWh m$^{-3}$",
        "scale": 1.0,
        "pct": False,
    },
    "exergy_efficiency": {
        "label": r"Exergy efficiency $\eta_{ex}$",
        "short": r"$\eta_{ex}$",
        "unit": "–",
        "scale": 1.0,
        "pct": True,
    },
    "energy_density_electric": {
        "label": "Electric energy density",
        "short": r"$e_{el}$",
        "unit": r"kWh m$^{-3}$",
        "scale": 1.0,
        "pct": False,
    },
    "cop_hp": {
        "label": "COP (heat pump)",
        "short": "COP",
        "unit": "–",
        "scale": 1.0,
        "pct": False,
    },
    "eta_he": {
        "label": r"ORC efficiency $\eta_{ORC}$",
        "short": r"$\eta_{ORC}$",
        "unit": "–",
        "scale": 1.0,
        "pct": True,
    },
    "neg_lcos": {
        "label": "LCOS",
        "short": "LCOS",
        "unit": r"€ kWh$^{-1}$",
        "scale": -1.0,
        "pct": False,
    },
    "neg_specific_capex": {
        "label": "Specific CAPEX",
        "short": "CAPEX",
        "unit": r"€ kW$^{-1}$",
        "scale": -1.0,
        "pct": False,
    },
}

META_COLS = {"wp", "cb_config", "fluid_hp", "fluid_he", "label"}

# ── colour palette ─────────────────────────────────────────────────────────────
CMAP      = plt.cm.plasma
SCATTER_S = 30
LINE_LW   = 0.9
LINE_COLOR = "#c0c0c0"
GRID_ALPHA = 0.35


# ─────────────────────────────────────────────────────────────────────────────
def load_config(path: str | None) -> dict:
    if path and os.path.isfile(path):
        with open(path) as f:
            return json.load(f)
    return {}


def detect_objectives(df: pd.DataFrame, config: dict) -> list[str]:
    cfg_objs = config.get("optimization", {}).get("objectives", [])
    if cfg_objs:
        present = [o for o in cfg_objs if o in df.columns]
        if present:
            return present
    return [c for c in df.columns if c in OBJ_META]


def apply_scale(df: pd.DataFrame, objectives: list[str]) -> pd.DataFrame:
    df = df.copy()
    for obj in objectives:
        s = OBJ_META.get(obj, {}).get("scale", 1.0)
        if s != 1.0:
            df[obj] = df[obj] * s
    return df


def axis_label(obj: str) -> str:
    meta = OBJ_META.get(obj, {})
    lbl  = meta.get("label", obj)
    unit = meta.get("unit", "–")
    if unit and unit != "–":
        return f"{lbl}\n[{unit}]"
    return lbl


def pct_fmt(val, _pos):
    return f"{val*100:.0f}%"


def configure_axis_fmt(ax, ox: str, oy: str):
    """Apply percentage formatter where appropriate."""
    if OBJ_META.get(ox, {}).get("pct", False):
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(pct_fmt))
    if OBJ_META.get(oy, {}).get("pct", False):
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(pct_fmt))


def build_info_text(df: pd.DataFrame, config: dict) -> str:
    row    = df.iloc[0]
    wp_id  = row.get("wp", "?")
    cfg_k  = row.get("cb_config", "?")
    f_hp   = row.get("fluid_hp", "?")
    f_he   = row.get("fluid_he", "?")
    label  = row.get("label", "")

    wp_info  = config.get("working_points", {}).get(str(wp_id), {})
    cfg_info = config.get("configurations", {}).get(str(cfg_k), {})

    T_hs     = wp_info.get("T_hs", "–")
    T_cs     = wp_info.get("T_cs", "–")
    dT       = wp_info.get("delta_T", "–")
    wp_lbl   = wp_info.get("label", label) or label
    cfg_lbl  = cfg_info.get("label", cfg_k)

    return (
        f"Working point : {wp_id}  —  {wp_lbl}\n"
        f"Configuration : {cfg_lbl}\n"
        f"HP fluid / ORC fluid : {f_hp} / {f_he}\n"
        f"T_source = {T_hs} °C,  T_sink = {T_cs} °C,  ΔT = {dT} K\n"
        f"Pareto solutions : {len(df)}"
    )


# ─────────────────────────────────────────────────────────────────────────────
def plot_pareto(csv_path: str,
                config_path: str | None = None,
                out_dir: str | None = None) -> str:

    df     = pd.read_csv(csv_path)
    config = load_config(config_path)
    objs   = detect_objectives(df, config)

    if len(objs) < 2:
        sys.exit(f"Need ≥2 objective columns; found: {objs}")

    df = apply_scale(df, objs)

    # ── layout ────────────────────────────────────────────────────────────────
    n_obj   = len(objs)
    pairs   = [(objs[i], objs[j])
               for i in range(n_obj) for j in range(i + 1, n_obj)]
    n_pairs = len(pairs)
    n_cols  = min(3, n_pairs)
    n_rows  = math.ceil(n_pairs / n_cols)

    FIG_COL_W = 4.8
    FIG_ROW_H = 4.4
    INFO_H    = 0.80          # inches for info row

    fig_w = FIG_COL_W * n_cols
    fig_h = FIG_ROW_H * n_rows + INFO_H

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=150)
    fig.patch.set_facecolor("#fafafa")

    # GridSpec: first row = info banner; rest = scatter plots
    hs     = [INFO_H / fig_h] + [1.0] * n_rows
    gs     = gridspec.GridSpec(
        n_rows + 1, n_cols,
        figure=fig,
        height_ratios=hs,
        hspace=0.62,
        wspace=0.42,
        left=0.07, right=0.97,
        top=0.97, bottom=0.07,
    )

    # ── info banner ───────────────────────────────────────────────────────────
    ax_info = fig.add_subplot(gs[0, :])
    ax_info.axis("off")
    info_text = build_info_text(df, config)
    ax_info.text(
        0.5, 0.5, info_text,
        transform=ax_info.transAxes,
        va="center", ha="center",
        fontsize=9.5,
        fontfamily="monospace",
        linespacing=1.55,
        bbox=dict(boxstyle="round,pad=0.6",
                  facecolor="#efefef",
                  edgecolor="#bbbbbb",
                  linewidth=0.9),
    )

    # ── colour mapping: use η_p2p (or first obj) as colour dimension ──────────
    color_obj = objs[0]
    c_vals    = df[color_obj].values
    c_norm    = (c_vals - c_vals.min()) / (np.ptp(c_vals) + 1e-12)

    # ── pairwise scatter plots ────────────────────────────────────────────────
    sc_ref = None    # keep one scatter for the colorbar

    for idx, (ox, oy) in enumerate(pairs):
        row = idx // n_cols + 1
        col = idx % n_cols
        ax  = fig.add_subplot(gs[row, col])
        ax.set_facecolor("white")

        # sort by x for a cleaner step-line on the front
        order = np.argsort(df[ox].values)
        xs    = df[ox].values[order]
        ys    = df[oy].values[order]
        cs    = c_norm[order]

        # step-line connecting consecutive Pareto points
        ax.plot(xs, ys,
                color=LINE_COLOR, lw=LINE_LW, zorder=1,
                solid_capstyle="round")

        # scatter coloured by colour_obj
        sc = ax.scatter(xs, ys,
                        c=cs, cmap=CMAP,
                        vmin=0, vmax=1,
                        s=SCATTER_S, zorder=2,
                        edgecolors="none",
                        alpha=0.88)
        if sc_ref is None:
            sc_ref = sc

        ax.set_xlabel(axis_label(ox), fontsize=8.5, labelpad=4)
        ax.set_ylabel(axis_label(oy), fontsize=8.5, labelpad=4)
        ax.tick_params(labelsize=7.5)
        ax.grid(True, lw=0.5, alpha=GRID_ALPHA, color="#888888")
        for spine in ax.spines.values():
            spine.set_linewidth(0.6)
            spine.set_color("#aaaaaa")

        configure_axis_fmt(ax, ox, oy)

        # subtle title per panel
        ox_s = OBJ_META.get(ox, {}).get("short", ox)
        oy_s = OBJ_META.get(oy, {}).get("short", oy)
        ax.set_title(f"{oy_s}  vs  {ox_s}", fontsize=8, pad=4, color="#444444")

    # ── hide unused subplot slots ─────────────────────────────────────────────
    for idx in range(n_pairs, n_rows * n_cols):
        row = idx // n_cols + 1
        col = idx % n_cols
        fig.add_subplot(gs[row, col]).axis("off")

    # ── colorbar ──────────────────────────────────────────────────────────────
    if sc_ref is not None:
        cbar_ax = fig.add_axes([0.92, 0.10, 0.012, 0.45])  # [left, bottom, w, h]
        cb = fig.colorbar(sc_ref, cax=cbar_ax)
        cb.set_label(
            f"Colour: {OBJ_META.get(color_obj, {}).get('label', color_obj)}",
            fontsize=7.5, labelpad=6,
        )
        cb.ax.tick_params(labelsize=7)

        # remap colorbar ticks to real values
        real_min = c_vals.min()
        real_max = c_vals.max()
        tick_pos  = np.linspace(0, 1, 5)
        tick_vals = real_min + tick_pos * (real_max - real_min)
        cb.set_ticks(tick_pos)
        if OBJ_META.get(color_obj, {}).get("pct", False):
            cb.set_ticklabels([f"{v*100:.1f}%" for v in tick_vals])
        else:
            cb.set_ticklabels([f"{v:.3g}" for v in tick_vals])

    # ── save ──────────────────────────────────────────────────────────────────
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    if stem.startswith("pareto_"):
        stem = stem[len("pareto_"):]

    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plots")
    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(out_dir, f"pareto_{stem}.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved → {out_path}")
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pairwise Pareto-front visualisation for a single scenario CSV.")
    parser.add_argument("csv",
                        help="Path to the Pareto-front CSV file")
    parser.add_argument("--config", default=None,
                        help="Path to optimization_config.json (auto-detected if omitted)")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory (default: <script_dir>/plots)")
    args = parser.parse_args()

    cfg = args.config
    if cfg is None:
        candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "optimization_config.json")
        if os.path.isfile(candidate):
            cfg = candidate

    plot_pareto(args.csv, config_path=cfg, out_dir=args.out_dir)
