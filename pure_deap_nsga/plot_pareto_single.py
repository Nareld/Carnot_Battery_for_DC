"""
Pareto front visualization for a single optimization scenario.
Usage: python plot_pareto_single.py <csv_path> [--config <config_path>]
"""

import argparse
import json
import math
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd

# ── objective display metadata ────────────────────────────────────────────────
OBJ_META = {
    "eta_p2p":                 {"label": "Round-trip efficiency η_p2p",  "unit": "–",    "scale": 1.0},
    "energy_density_thermal":  {"label": "Thermal energy density",        "unit": "kWh/m³","scale": 1.0},
    "exergy_efficiency":       {"label": "Exergy efficiency",             "unit": "–",    "scale": 1.0},
    "energy_density_electric": {"label": "Electric energy density",       "unit": "kWh/m³","scale": 1.0},
    "cop_hp":                  {"label": "COP (heat pump)",               "unit": "–",    "scale": 1.0},
    "eta_he":                  {"label": "ORC efficiency η_he",           "unit": "–",    "scale": 1.0},
    "carnot_ratio":            {"label": "Carnot ratio",                  "unit": "–",    "scale": 1.0},
    "neg_lcos":                {"label": "LCOS",                          "unit": "€/kWh","scale": -1.0},
    "neg_specific_capex":      {"label": "Specific CAPEX",                "unit": "€/kW", "scale": -1.0},
}

# ── known non-objective columns ───────────────────────────────────────────────
META_COLS = {"wp", "cb_config", "fluid_hp", "fluid_he", "label"}


def load_config(config_path: str) -> dict:
    if config_path and os.path.isfile(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def detect_objectives(df: pd.DataFrame, config: dict) -> list[str]:
    """Return objective columns: from config if available, else intersect with known OBJ_META."""
    cfg_objs = config.get("optimization", {}).get("objectives", [])
    if cfg_objs:
        present = [o for o in cfg_objs if o in df.columns]
        if present:
            return present
    # fallback: any column that matches OBJ_META keys
    return [c for c in df.columns if c in OBJ_META]


def build_scenario_text(df: pd.DataFrame, config: dict) -> str:
    """Build a multi-line scenario description from metadata columns + config."""
    row = df.iloc[0]
    wp_id   = row.get("wp",        "?")
    cfg_key = row.get("cb_config", "?")
    f_hp    = row.get("fluid_hp",  "?")
    f_he    = row.get("fluid_he",  "?")
    label   = row.get("label",     "")

    # config lookups
    wp_info  = config.get("working_points", {}).get(str(wp_id), {})
    cfg_info = config.get("configurations", {}).get(str(cfg_key), {})

    T_hs = wp_info.get("T_hs", "?")
    T_cs = wp_info.get("T_cs", "?")
    dT   = wp_info.get("delta_T", "?")

    cfg_label = cfg_info.get("label", cfg_key)
    wp_label  = wp_info.get("label", label) or label

    lines = [
        f"Working point : {wp_id}  –  {wp_label}",
        f"Configuration : {cfg_label}",
        f"HP fluid / ORC fluid : {f_hp} / {f_he}",
        f"T_source = {T_hs} °C,  T_sink = {T_cs} °C,  ΔT = {dT} K",
        f"Pareto solutions : {len(df)}",
    ]
    return "\n".join(lines)


def axis_label(obj: str) -> str:
    meta = OBJ_META.get(obj, {})
    lbl  = meta.get("label", obj)
    unit = meta.get("unit", "")
    return f"{lbl}  [{unit}]" if unit and unit != "–" else lbl


def apply_scale(df: pd.DataFrame, objectives: list[str]) -> pd.DataFrame:
    """Flip sign for 'neg_*' objectives so all axes are 'higher = better'."""
    df = df.copy()
    for obj in objectives:
        scale = OBJ_META.get(obj, {}).get("scale", 1.0)
        if scale != 1.0:
            df[obj] = df[obj] * scale
    return df


def plot_pareto(csv_path: str, config_path: str | None = None, out_dir: str | None = None):
    df = pd.read_csv(csv_path)
    config = load_config(config_path or "")

    objectives = detect_objectives(df, config)
    if len(objectives) < 2:
        sys.exit(f"Need at least 2 objective columns; found: {objectives}")

    df = apply_scale(df, objectives)
    scenario_text = build_scenario_text(df, config)

    # ── layout ────────────────────────────────────────────────────────────────
    n_obj  = len(objectives)
    n_pairs = n_obj * (n_obj - 1) // 2
    n_cols = min(3, n_pairs)
    n_rows = math.ceil(n_pairs / n_cols)

    fig_w = 4.5 * n_cols
    fig_h = 4.0 * n_rows + 1.6          # extra space for scenario text

    fig = plt.figure(figsize=(fig_w, fig_h))
    gs  = gridspec.GridSpec(
        n_rows + 1, n_cols,
        figure=fig,
        height_ratios=[0.32] + [1.0] * n_rows,
        hspace=0.55, wspace=0.38,
    )

    # scenario info panel (top row, full width)
    ax_info = fig.add_subplot(gs[0, :])
    ax_info.axis("off")
    ax_info.text(
        0.02, 0.95, scenario_text,
        transform=ax_info.transAxes,
        va="top", ha="left",
        fontsize=9, family="monospace",
        bbox=dict(boxstyle="round,pad=0.5", fc="#f5f5f5", ec="#cccccc", lw=0.8),
    )

    # pairwise scatter plots
    pairs = [(objectives[i], objectives[j])
             for i in range(n_obj) for j in range(i + 1, n_obj)]

    cmap   = plt.cm.viridis
    colors = cmap(np.linspace(0.15, 0.85, len(df)))

    for idx, (ox, oy) in enumerate(pairs):
        row = idx // n_cols + 1
        col = idx % n_cols
        ax  = fig.add_subplot(gs[row, col])

        # sort by x for a cleaner front line
        order = df[ox].argsort().values
        xs = df[ox].values[order]
        ys = df[oy].values[order]

        ax.plot(xs, ys, color="#cccccc", lw=0.8, zorder=1)
        sc = ax.scatter(xs, ys, c=np.arange(len(df)), cmap=cmap,
                        vmin=0, vmax=len(df), s=22, zorder=2, edgecolors="none")

        ax.set_xlabel(axis_label(ox), fontsize=8)
        ax.set_ylabel(axis_label(oy), fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(True, lw=0.4, alpha=0.5)

    # ── file name from CSV stem ───────────────────────────────────────────────
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    # strip leading "pareto_" if present
    if stem.startswith("pareto_"):
        stem = stem[len("pareto_"):]

    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plot")
    os.makedirs(out_dir, exist_ok=True)

    out_path = os.path.join(out_dir, f"pareto_{stem}.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out_path}")
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualise a single Pareto-front CSV.")
    parser.add_argument("csv", help="Path to the Pareto-front CSV file")
    parser.add_argument("--config", default=None,
                        help="Path to optimization_config.json (auto-detected if omitted)")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory for the figure (default: <script_dir>/plot)")
    args = parser.parse_args()

    # auto-detect config next to the script
    cfg = args.config
    if cfg is None:
        candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "optimization_config.json")
        if os.path.isfile(candidate):
            cfg = candidate

    plot_pareto(args.csv, config_path=cfg, out_dir=args.out_dir)
