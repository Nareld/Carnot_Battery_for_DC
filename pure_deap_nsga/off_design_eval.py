#!/usr/bin/env python3
"""
Part III: Off-design robustness evaluation for Carnot battery representative designs.

Takes the 3 representative designs (D_eff, D_den, D_bal) from M3 near-optimal analysis
and evaluates their performance under deviating boundary conditions (seasonal pairs).

Core question: Which design strategy is most robust to seasonal T_hs/T_cs variation?

Method:
  1. Load M3 representative designs for each WP
  2. Fix all 9 design parameters, change only T_hs and T_cs (off-design WP)
  3. Run CBSim at off-design boundary conditions
  4. Compute performance retention: R = f(off-design) / f(nominal) × 100%
  5. Compare R across design strategies and season pairs

Outputs:
  - results/off_design_eval.csv           — all evaluation points
  - results/off_design_retention.csv      — retention ratios
  - plots/off_design/                     — figures (Fig 5.1–5.3)

Usage:
  python3 off_design_eval.py                           # all 3 season pairs
  python3 off_design_eval.py --pair DC-A_DC-B          # single pair
  python3 off_design_eval.py --sweep dT_st_sp          # real-choice parameter sweep
"""

import argparse, json, os, sys, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import FancyArrowPatch
import CoolProp.CoolProp as CP

warnings.filterwarnings("ignore")

# ── Paths ────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CBSIM_ROOT = os.path.dirname(SCRIPT_DIR)
SRC_DIR    = os.path.join(CBSIM_ROOT, "src")
sys.path.insert(0, str(SRC_DIR))
import _module_carnot_battery as CB

RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
PLOT_DIR    = os.path.join(SCRIPT_DIR, "plots", "off_design")
os.makedirs(PLOT_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(SCRIPT_DIR, "optimization_config.json")

# ── Season pairs (winter ↔ summer) ──────────────────────────────────────────────
SEASON_PAIRS = [("DC-A", "DC-B"), ("DC-C", "DC-D"), ("DC-E", "DC-F")]

OBJS = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]
OBJ_LABELS = {
    "eta_p2p":                r"$\eta_{p2p}$",
    "energy_density_thermal": r"$e_{th}$ [kWh/m³]",
    "exergy_efficiency":      r"$\eta_{ex}$",
}
OBJ_UNITS = {"eta_p2p": "[-]", "energy_density_thermal": "[kWh/m³]", "exergy_efficiency": "[-]"}

DESIGN_NAMES = ["D_eff", "D_den", "D_bal"]
DESIGN_COLORS = {"D_eff": "#4C72B0", "D_den": "#E24A33", "D_bal": "#55A868"}
DESIGN_MARKERS = {"D_eff": "o", "D_den": "s", "D_bal": "D"}

# Lighter shades for summer/baseline
PAIR_COLORS = {"winter": "#2166AC", "summer": "#B2182B"}


# ══════════════════════════════════════════════════════════════════════════════════
# 1. Load config and designs
# ══════════════════════════════════════════════════════════════════════════════════

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def load_designs(wp):
    """Load the 3 representative designs for a given WP from M3 CSV."""
    path = os.path.join(RESULTS_DIR, f"near_optimal_{wp}_designs.csv")
    if not os.path.exists(path):
        print(f"  [WARN] No designs file for {wp}, skipping.")
        return None
    return pd.read_csv(path)


def load_all_designs():
    """Load designs for all 6 WPs, return dict wp → DataFrame."""
    all_wps = []
    for pair in SEASON_PAIRS:
        all_wps.extend(pair)
    designs = {}
    for wp in set(all_wps):
        df = load_designs(wp)
        if df is not None:
            designs[wp] = df
    return designs


# ══════════════════════════════════════════════════════════════════════════════════
# 2. CBSim off-design evaluator
# ══════════════════════════════════════════════════════════════════════════════════

def build_cb_inputs(design_row, T_hs, T_cs, cfg):
    """Build CBSim inputs/params/options tuple from a design row and boundary T."""
    d = design_row

    T_hp_cs_su_K = T_hs + 273.15
    dT_gl = float(d.get("dT_hp_cs_gl", 0))
    T_hp_cs_ex_K = max(T_hp_cs_su_K - dT_gl, 275.15)
    p_hp_cs = 1e5

    T_he_cs_su_K = T_cs + 273.15
    T_he_cs_ex_K = T_he_cs_su_K + cfg["dT_he_cs_gl"]
    p_he_cs = 1e5

    i_hp_cs_su = CP.PropsSI("H", "T", T_hp_cs_su_K, "P", p_hp_cs, "H2O")
    i_hp_cs_ex = CP.PropsSI("H", "T", T_hp_cs_ex_K, "P", p_hp_cs, "H2O")
    i_he_cs_su = CP.PropsSI("H", "T", T_he_cs_su_K, "P", p_he_cs, "H2O")
    i_he_cs_ex = CP.PropsSI("H", "T", T_he_cs_ex_K, "P", p_he_cs, "H2O")

    inputs = (
        p_hp_cs, i_hp_cs_su, p_hp_cs, i_hp_cs_ex, 1.0, "H2O",
        p_he_cs, i_he_cs_su, p_he_cs, i_he_cs_ex, 1.0, "H2O",
        1e3, 1e3,
    )

    params = {
        "p_hp_cs_su": p_hp_cs, "i_hp_cs_su": i_hp_cs_su, "i_hp_cs_ex": i_hp_cs_ex,
        "p_he_cs_su": p_he_cs, "i_he_cs_su": i_he_cs_su, "i_he_cs_ex": i_he_cs_ex,
        "m_hp_cs": 1.0, "m_he_cs": 1.0,
        "p_st_ht": cfg["p_st_ht"], "p_st_lt": cfg["p_st_lt"],
        "T_st_ht": float(d["T_st_ht"]) + 273.15,
        "dT_st_sp": float(d["dT_st_sp"]),
        "eta_max_cp": float(d["eta_max_cp"]),
        "eta_max_ex": float(d["eta_max_ex"]),
        "eta_pm": float(d["eta_pm"]),
        "dT_hp_ev_pp": cfg["dT_hp_ev_pp"],
        "dT_hp_cd_pp": cfg["dT_hp_cd_pp"],
        "dT_he_ev_pp": cfg["dT_he_ev_pp"],
        "dT_he_cd_pp": cfg["dT_he_cd_pp"],
        "dT_hp_ev_sh": float(d["dT_hp_ev_sh"]),
        "dT_he_ev_sh": float(d["dT_he_ev_sh"]),
        "dT_he_cd_sc": cfg["dT_he_cd_sc"],
        "dT_hp_cd_sc": float(d["dT_hp_cd_sc"]),
        "dp_hp_ev": 0.0, "dp_hp_cd": 0.0,
        "dp_hp_rg_lq": 0.0, "dp_hp_rg_vp": 0.0,
        "epsilon_hp": cfg["epsilon_hp"],
        "dp_he_ev": 0.0, "dp_he_cd": 0.0,
        "dp_he_rg_lq": 0.0, "dp_he_rg_vp": 0.0,
        "epsilon_he": cfg["epsilon_he"],
        "m_hp_st_max": 0.0, "m_he_st_max": 0.0,
        "version": "thermodynamic_full",
        "mode_hp": True, "mode_he": True, "mode": "source",
        "p_ref": p_he_cs, "T_ref": T_he_cs_su_K,
        "p_0": p_he_cs, "T_0": T_he_cs_su_K,
        "fluid_hp": d["fluid_hp"],
        "fluid_he": d["fluid_he"],
        "fluid_st": cfg.get("fluid_st", "H2O"),
        "wet_ex": 0, "m_rat_hp": 0, "m_rat_he": 0,
    }
    options = {"plot_flag": False, "print_flag": False, "debug": False, "exergy": True}
    return inputs, params, options


def run_cb_point(design_row, T_hs, T_cs, cb_class_name, cfg):
    """Run a single CBSim evaluation. Returns (success, result_dict)."""
    cb_class = getattr(CB, cb_class_name)

    # Pre-check
    T_st_ht = float(design_row["T_st_ht"])
    if T_st_ht <= T_hs + 5.0:
        return False, {"error": "T_st_ht too close to T_hs"}

    try:
        inputs, params, options = build_cb_inputs(design_row, T_hs, T_cs, cfg)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            my_cb = cb_class(inputs, params, options)
            my_cb.evaluate()

        if my_cb.error:
            return False, {"error": "CB solver error"}

        if not (0.01 < my_cb.eta_cb_elec < 1.0):
            return False, {"error": "eta_p2p out of valid range"}

        result = {
            "eta_p2p": float(my_cb.eta_cb_elec),
            "energy_density_thermal": float(my_cb.E_dens_th / 3.6e6),
            "exergy_efficiency": float(my_cb.eta_cb_exer),
            "cop_hp": float(my_cb.my_HP.eta_hp_cyclen),
            "eta_he": float(my_cb.my_HE.eta_he_cyclen),
            "P_hp_kW": float(my_cb.P_hp / 1e3),
            "P_he_kW": float(my_cb.P_he / 1e3),
            "V_total_m3": float(my_cb.v_st_ht + my_cb.v_st_lt),
        }
        return True, result

    except Exception as e:
        return False, {"error": str(e)[:80]}


# ══════════════════════════════════════════════════════════════════════════════════
# 3. Off-design evaluation pipeline
# ══════════════════════════════════════════════════════════════════════════════════

def evaluate_season_pair(wp_winter, wp_summer, wps_config, cfg, designs):
    """
    Evaluate all designs from winter WP at both nominal (winter) and off-design
    (summer) boundary conditions. Also evaluate summer designs at winter conditions
    for reciprocal comparison.
    """
    wp_w = wps_config[wp_winter]
    wp_s = wps_config[wp_summer]

    rows = []
    directions = [
        ("winter→summer", wp_winter, wp_w, wp_s, designs.get(wp_winter)),
        ("summer→winter", wp_summer, wp_s, wp_w, designs.get(wp_summer)),
    ]

    for direction, source_wp, src_wp_cfg, dst_wp_cfg, src_designs in directions:
        if src_designs is None:
            print(f"  [SKIP] No designs for {source_wp}")
            continue

        T_nom_hs = src_wp_cfg["T_hs"]
        T_nom_cs = src_wp_cfg["T_cs"]
        T_off_hs = dst_wp_cfg["T_hs"]
        T_off_cs = dst_wp_cfg["T_cs"]

        for _, design in src_designs.iterrows():
            dname = design["design_name"]
            cb_class = design["cb_config"] + "_STES2T"

            # Nominal evaluation
            ok_nom, res_nom = run_cb_point(design, T_nom_hs, T_nom_cs, cb_class, cfg)
            # Off-design evaluation
            ok_off, res_off = run_cb_point(design, T_off_hs, T_off_cs, cb_class, cfg)

            for label, ok, res, T_hs, T_cs, wp_label in [
                ("nominal", ok_nom, res_nom, T_nom_hs, T_nom_cs, source_wp),
                ("off-design", ok_off, res_off, T_off_hs, T_off_cs, dst_wp_cfg["name"]),
            ]:
                row = {
                    "source_wp": source_wp,
                    "design_name": dname,
                    "eval_type": label,
                    "eval_wp": wp_label,
                    "direction": direction,
                    "T_hs": T_hs,
                    "T_cs": T_cs,
                    "cb_config": design["cb_config"],
                    "fluid_hp": design["fluid_hp"],
                    "fluid_he": design["fluid_he"],
                    "converged": ok,
                }
                if ok:
                    for obj in OBJS:
                        row[obj] = res[obj]
                    row["cop_hp"] = res["cop_hp"]
                    row["eta_he"] = res["eta_he"]
                else:
                    for obj in OBJS:
                        row[obj] = np.nan
                    row["cop_hp"] = np.nan
                    row["eta_he"] = np.nan
                    row["error"] = res.get("error", "unknown")
                rows.append(row)

    return pd.DataFrame(rows)


def compute_retention(df):
    """Compute performance retention ratios: R = f(off-design) / f(nominal)."""
    retention_rows = []
    for (source_wp, design_name), group in df.groupby(["source_wp", "design_name"]):
        nom = group[group["eval_type"] == "nominal"]
        off = group[group["eval_type"] == "off-design"]
        if len(nom) == 0 or len(off) == 0:
            continue
        nom_row = nom.iloc[0]
        off_row = off.iloc[0]
        if not nom_row["converged"]:
            continue

        r = {
            "source_wp": source_wp,
            "design_name": design_name,
            "direction": off_row["direction"],
            "T_hs_nom": nom_row["T_hs"],
            "T_cs_nom": nom_row["T_cs"],
            "T_hs_off": off_row["T_hs"],
            "T_cs_off": off_row["T_cs"],
            "converged_off": off_row["converged"],
        }
        for obj in OBJS:
            if off_row["converged"] and not np.isnan(off_row.get(obj, np.nan)):
                r[f"R_{obj}"] = off_row[obj] / nom_row[obj] if nom_row[obj] != 0 else np.nan
                r[f"Δ_{obj}"] = off_row[obj] - nom_row[obj]
            else:
                r[f"R_{obj}"] = np.nan
                r[f"Δ_{obj}"] = np.nan
        retention_rows.append(r)

    return pd.DataFrame(retention_rows)


# ══════════════════════════════════════════════════════════════════════════════════
# 4. Visualization
# ══════════════════════════════════════════════════════════════════════════════════

def plot_off_design_shift(df_retention, out_dir):
    """Fig 5.1: Performance shift from nominal to off-design (grouped bar)."""
    # Focus on winter→summer direction
    df_plot = df_retention[df_retention["direction"] == "winter→summer"].copy()
    if df_plot.empty:
        print("  [WARN] No winter→summer data for shift plot.")
        return

    wp_order = ["DC-A", "DC-C", "DC-E"]
    wp_labels = ["Air-cooled\n(DC-A→DC-B)", "Liquid cooling\n(DC-C→DC-D)", "HPC\n(DC-E→DC-F)"]
    design_order = ["D_eff", "D_den", "D_bal"]

    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))
    fig.suptitle("Off-Design Performance Shift (Winter → Summer)",
                 fontsize=12, fontweight="bold")

    for ax_idx, obj in enumerate(OBJS):
        ax = axes[ax_idx]
        x = np.arange(len(wp_order))
        width = 0.22

        for j, dname in enumerate(design_order):
            vals = []
            for i, wp in enumerate(wp_order):
                subset = df_plot[(df_plot["source_wp"] == wp) & (df_plot["design_name"] == dname)]
                if len(subset) > 0:
                    vals.append(subset[f"R_{obj}"].values[0] * 100)
                else:
                    vals.append(np.nan)
            bars = ax.bar(x + (j - 1) * width, vals, width,
                         label=dname, color=DESIGN_COLORS[dname],
                         alpha=0.85, edgecolor="white")

        ax.axhline(y=100, color="black", lw=0.8, ls="--", alpha=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(wp_labels, fontsize=8.5)
        ax.set_ylabel(f"Retention R({OBJ_LABELS[obj]}) [%]", fontsize=9)
        ax.set_title(f"Off-design retention: {OBJ_LABELS[obj]}", fontsize=10)
        ax.legend(fontsize=8)
        ax.grid(axis="y", lw=0.3, alpha=0.4)
        ax.set_ylim(bottom=0)

    fig.tight_layout()
    out = os.path.join(out_dir, "off_design_shift.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


def plot_robustness_heatmap(df_eval, designs_dict, out_dir):
    """Fig 5.2: Robustness heatmap — η_p2p of each design at each WP."""
    # Build a matrix: rows = (source_wp, design_name), cols = eval_wp
    # Use only converged nominal evaluations

    # Collect all evaluation points: each design evaluated at its nominal WP
    nom = df_eval[df_eval["eval_type"] == "nominal"].copy()
    if nom.empty:
        print("  [WARN] No nominal data for heatmap.")
        return

    # Pivot: each design × its η_p2p
    # For a richer heatmap: also evaluate each design at ALL 6 WPs
    # Use existing off-design evaluations + nominal
    all_eval = df_eval.copy()
    piv = all_eval.pivot_table(
        index=["source_wp", "design_name"],
        columns="eval_wp",
        values="eta_p2p",
        aggfunc="first",
    )

    # Reorder rows and columns
    wp_order = ["DC-A", "DC-B", "DC-C", "DC-D", "DC-E", "DC-F"]
    piv = piv.reindex(columns=[w for w in wp_order if w in piv.columns])

    # Sort rows by source_wp then design
    row_order = []
    for wp in ["DC-A", "DC-C", "DC-E", "DC-B", "DC-D", "DC-F"]:
        for dname in ["D_eff", "D_den", "D_bal"]:
            if (wp, dname) in piv.index:
                row_order.append((wp, dname))
    piv = piv.reindex(row_order)

    fig, ax = plt.subplots(figsize=(12, 7))
    im = ax.imshow(piv.values, aspect="auto", cmap="RdYlBu_r",
                   vmin=piv.values.min() * 0.95, vmax=piv.values.max() * 1.02)

    # Annotate cells
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            val = piv.values[i, j]
            if not np.isnan(val):
                text_color = "white" if val < piv.values.mean() else "black"
                ax.text(j, i, f"{val:.3f}", ha="center", va="center",
                       fontsize=8, fontweight="bold", color=text_color)

    row_labels = [f"{wp} {dn}" for wp, dn in piv.index]
    ax.set_xticks(range(len(piv.columns)))
    ax.set_xticklabels(piv.columns, fontsize=9, rotation=0)
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=8, family="monospace")
    ax.set_title("Robustness heatmap: η_p2p of each design at each WP\n"
                 "(rows = source design, cols = evaluation WP)",
                 fontsize=11, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label(r"$\eta_{p2p}$ [-]", fontsize=10)

    fig.tight_layout()
    out = os.path.join(out_dir, "robustness_heatmap.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


def plot_retention_summary(df_retention, out_dir):
    """Compact summary: retention scatter by design type across season pairs."""
    df_plot = df_retention[df_retention["direction"] == "winter→summer"].copy()
    if df_plot.empty:
        return

    fig, ax = plt.subplots(figsize=(8, 5.5))

    # Plot: R(η_p2p) vs R(e_th) for each design
    for _, row in df_plot.iterrows():
        dname = row["design_name"]
        if pd.isna(row.get("R_eta_p2p")) or pd.isna(row.get("R_energy_density_thermal")):
            continue
        ax.scatter(row["R_eta_p2p"] * 100, row["R_energy_density_thermal"] * 100,
                  s=180, c=DESIGN_COLORS[dname], marker=DESIGN_MARKERS[dname],
                  edgecolors="black", lw=1.2, zorder=5, alpha=0.9)
        ax.annotate(f"{row['source_wp']} {dname}",
                   (row["R_eta_p2p"] * 100, row["R_energy_density_thermal"] * 100),
                   textcoords="offset points", xytext=(7, 4), fontsize=7.5)

    ax.axhline(y=100, color="gray", lw=0.8, ls="--", alpha=0.5)
    ax.axvline(x=100, color="gray", lw=0.8, ls="--", alpha=0.5)
    ax.fill_between([0, 100], 0, 100, alpha=0.03, color="red")
    ax.fill_between([100, 200], 100, 200, alpha=0.03, color="green")

    ax.set_xlabel(r"Retention $R(\eta_{p2p})$ [%]", fontsize=10)
    ax.set_ylabel(r"Retention $R(e_{th})$ [%]", fontsize=10)
    ax.set_title("Off-design retention: η_p2p vs e_th\n"
                 "(winter designs evaluated at summer conditions)",
                 fontsize=11, fontweight="bold")
    ax.set_xlim(0, 200)
    ax.set_ylim(0, 200)

    legend_elements = [
        plt.Line2D([0], [0], marker="o", color="w", markeredgecolor="black",
                   markerfacecolor=DESIGN_COLORS["D_eff"], label="D_eff"),
        plt.Line2D([0], [0], marker="s", color="w", markeredgecolor="black",
                   markerfacecolor=DESIGN_COLORS["D_den"], label="D_den"),
        plt.Line2D([0], [0], marker="D", color="w", markeredgecolor="black",
                   markerfacecolor=DESIGN_COLORS["D_bal"], label="D_bal"),
    ]
    ax.legend(handles=legend_elements, fontsize=9, loc="lower right")
    ax.grid(lw=0.3, alpha=0.4)

    fig.tight_layout()
    out = os.path.join(out_dir, "retention_scatter.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


# ══════════════════════════════════════════════════════════════════════════════════
# 5. Real-choice parameter sweep (optional, §5.3)
# ══════════════════════════════════════════════════════════════════════════════════

def sweep_parameter(design_row, T_hs, T_cs, cb_class_name, cfg,
                    param_name, sweep_range):
    """Sweep a single real-choice parameter at fixed boundary conditions."""
    results = []
    base_val = float(design_row[param_name])
    for val in sweep_range:
        row = design_row.copy()
        row[param_name] = val
        ok, res = run_cb_point(row, T_hs, T_cs, cb_class_name, cfg)
        results.append({
            "param_name": param_name,
            "param_value": val,
            "base_value": base_val,
            "converged": ok,
            **{obj: res.get(obj, np.nan) for obj in OBJS},
        })
    return pd.DataFrame(results)


def run_parameter_sweep(cfg, designs):
    """Run real-choice parameter sweeps for key designs.

    NOTE: CBSim is a design-point solver — perturbing a single parameter while
    keeping others fixed may break cycle closure. Sweep feasibility is limited.
    This section (§5.3) is marked optional in the paper v3.0.
    """
    wps_config = cfg["working_points"]
    all_sweeps = []

    # Use DC-A D_eff (known to converge) instead of D_bal
    for src_wp in ["DC-A"]:
        if src_wp not in designs:
            continue
        d_eff = designs[src_wp][designs[src_wp]["design_name"] == "D_eff"]
        if len(d_eff) == 0:
            continue
        design = d_eff.iloc[0]
        cb_class = design["cb_config"] + "_STES2T"
        wp_src = wps_config[src_wp]

        dT_min = wp_src["dT_st_sp_min"]
        dT_max = wp_src["dT_st_sp_max"]
        sweep_vals = np.linspace(dT_min, dT_max, 12)

        for label, T_hs, T_cs in [
            (f"{src_wp} (nominal)", wp_src["T_hs"], wp_src["T_cs"]),
        ]:
            df_sweep = sweep_parameter(design, T_hs, T_cs, cb_class, cfg,
                                       "dT_st_sp", sweep_vals)
            df_sweep["eval_label"] = label
            df_sweep["design_name"] = f"D_eff ({src_wp})"
            all_sweeps.append(df_sweep)
            n_conv = df_sweep["converged"].sum()
            print(f"  Swept dT_st_sp at {label}: {n_conv}/{len(df_sweep)} converged")

    if all_sweeps:
        combined = pd.concat(all_sweeps, ignore_index=True)
        plot_parameter_sweep_fig(combined)
        return combined
    return None


def plot_parameter_sweep_fig(df_sweep):
    """Fig 5.3: Real-choice parameter sweep showing optimal trajectory."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    for ax, obj in zip(axes, OBJS):
        for label in df_sweep["eval_label"].unique():
            subset = df_sweep[df_sweep["eval_label"] == label]
            conv = subset[subset["converged"]]
            if len(conv) > 0:
                ax.plot(conv["param_value"], conv[obj], "o-", lw=1.5, ms=5,
                       label=label, alpha=0.8)
        ax.set_xlabel(r"$\Delta T_{st,sp}$ [K]", fontsize=9)
        ax.set_ylabel(OBJ_LABELS[obj], fontsize=9)
        ax.set_title(f"{OBJ_LABELS[obj]} vs ΔT_st_sp", fontsize=10)
        ax.legend(fontsize=7.5)
        ax.grid(lw=0.3, alpha=0.4)

    fig.suptitle("Real-choice parameter sweep: dT_st_sp (DC-A D_bal)",
                 fontsize=11, fontweight="bold")
    fig.tight_layout()
    out = os.path.join(PLOT_DIR, "parameter_sweep_dT_st_sp.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


# ══════════════════════════════════════════════════════════════════════════════════
# 6. Main
# ══════════════════════════════════════════════════════════════════════════════════

def run_off_design_analysis(pairs=None, run_sweep=False):
    """Full Part III off-design evaluation."""
    cfg = load_config()
    wps_config = cfg["working_points"]
    opt_cfg = cfg["optimization"]

    if pairs is None:
        pairs = SEASON_PAIRS

    print(f"\n{'='*70}")
    print(f"OFF-DESIGN ROBUSTNESS ANALYSIS")
    print(f"{'='*70}")

    # Load designs
    all_wps = set()
    for wp_w, wp_s in pairs:
        all_wps.update([wp_w, wp_s])
    designs = {}
    for wp in all_wps:
        df = load_designs(wp)
        if df is not None:
            designs[wp] = df
            print(f"  Loaded {wp}: {len(df)} designs")

    # Evaluate each season pair
    all_eval = []
    all_retention = []
    for wp_w, wp_s in pairs:
        if wp_w not in designs or wp_s not in designs:
            print(f"  [SKIP] {wp_w}↔{wp_s}: missing designs")
            continue
        print(f"\n  Evaluating {wp_w} ↔ {wp_s}...")
        df_eval = evaluate_season_pair(wp_w, wp_s, wps_config, opt_cfg, designs)
        df_ret = compute_retention(df_eval)
        print(f"    Evaluations: {len(df_eval)}  |  Retention pairs: {len(df_ret)}")
        print(f"    Converged nominal:  {df_eval[(df_eval.eval_type=='nominal') & df_eval.converged].shape[0]}")
        print(f"    Converged off-des:  {df_eval[(df_eval.eval_type=='off-design') & df_eval.converged].shape[0]}")

        all_eval.append(df_eval)
        all_retention.append(df_ret)

    df_eval_all = pd.concat(all_eval, ignore_index=True)
    df_ret_all = pd.concat(all_retention, ignore_index=True)

    # Save tables
    df_eval_all.to_csv(os.path.join(RESULTS_DIR, "off_design_eval.csv"),
                       index=False, float_format="%.6f")
    df_ret_all.to_csv(os.path.join(RESULTS_DIR, "off_design_retention.csv"),
                      index=False, float_format="%.6f")
    print(f"\n  Saved → results/off_design_eval.csv ({len(df_eval_all)} rows)")
    print(f"  Saved → results/off_design_retention.csv ({len(df_ret_all)} rows)")

    # Print summary
    for direction_label, direction_filter in [
        ("winter→summer", "winter→summer"),
        ("summer→winter", "summer→winter"),
    ]:
        subset = df_ret_all[df_ret_all["direction"] == direction_filter]
        if subset.empty:
            continue
        print(f"\n  Retention summary ({direction_label}, converged only):")
        for _, row in subset.iterrows():
            status = "✓" if row["converged_off"] else "✗"
            r_vals = []
            for obj in OBJS:
                r_key = f"R_{obj}"
                if not pd.isna(row.get(r_key)):
                    r_vals.append(f"{OBJ_LABELS[obj]}={row[r_key]*100:.1f}%")
            print(f"    {row['source_wp']} {row['design_name']:6s} {status}  " +
                  "  ".join(r_vals))

    # Plots
    plot_off_design_shift(df_ret_all, PLOT_DIR)
    plot_robustness_heatmap(df_eval_all, designs, PLOT_DIR)
    plot_retention_summary(df_ret_all, PLOT_DIR)

    # Optional parameter sweep
    if run_sweep:
        print(f"\n  Running real-choice parameter sweep...")
        run_parameter_sweep(cfg, designs)

    print(f"\n{'='*70}")
    print(f"DONE. Outputs in: {PLOT_DIR}")
    print(f"{'='*70}")

    return df_eval_all, df_ret_all


# ══════════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Off-design robustness evaluation")
    parser.add_argument("--pair", default=None,
                        help="Single season pair, e.g. DC-A_DC-B")
    parser.add_argument("--sweep", action="store_true", default=False,
                        help="Run real-choice parameter sweep (§5.3)")
    args = parser.parse_args()

    if args.pair:
        wp_w, wp_s = args.pair.split("_")
        pairs = [(wp_w, wp_s)]
    else:
        pairs = SEASON_PAIRS

    df_eval, df_ret = run_off_design_analysis(pairs=pairs, run_sweep=args.sweep)
