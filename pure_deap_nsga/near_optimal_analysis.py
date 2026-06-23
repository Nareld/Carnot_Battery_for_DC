#!/usr/bin/env python3
"""
Part II: Near-optimal design analysis for Carnot battery Pareto fronts.

Steps:
  1. Pool all (config × fluid pair) Pareto solutions for a given WP
  2. 3-D non-dominated sort → global Pareto front
  3. Dimension reduction judgment (conflict metrics on global front)
  4. Define near-optimal region (top-10% in retained objectives)
  5. Parameter CV analysis → must-have / gray / real-choice classification
  6. Config / fluid competition in near-optimal space
  7. Representative design selection (efficiency / density / balanced)
  8. Visualization (Fig 6–8 in paper v3.0)

Outputs:
  - results/near_optimal_{WP}_params.csv     — parameter CV classification
  - results/near_optimal_{WP}_designs.csv    — representative design parameters
  - plots/near_optimal/                      — figures

Usage:
  python3 near_optimal_analysis.py --wp DC-A
  python3 near_optimal_analysis.py --wp DC-A --top-frac 0.10 --cv-low 0.10 --cv-high 0.20
"""

import argparse, glob, os, sys, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import Normalize
from matplotlib.patches import Patch
from scipy.stats import spearmanr, gaussian_kde
from itertools import combinations

warnings.filterwarnings("ignore")

# ── Paths ────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
PLOT_DIR    = os.path.join(SCRIPT_DIR, "plots", "near_optimal")
os.makedirs(PLOT_DIR, exist_ok=True)

OBJS = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]
OBJ_LABELS = {
    "eta_p2p":                r"$\eta_{p2p}$",
    "energy_density_thermal": r"$e_{th}$ [kWh/m³]",
    "exergy_efficiency":      r"$\eta_{ex}$",
}
DECISION_VARS = [
    "T_st_ht", "dT_st_sp", "dT_hp_cs_gl", "dT_hp_ev_sh", "dT_he_ev_sh",
    "dT_hp_cd_sc", "eta_max_cp", "eta_max_ex", "eta_pm",
]
VAR_LABELS = {
    "T_st_ht":       r"$T_{st,ht}$ [°C]",
    "dT_st_sp":      r"$\Delta T_{st,sp}$ [K]",
    "dT_hp_cs_gl":   r"$\Delta T_{hp,cs,gl}$ [K]",
    "dT_hp_ev_sh":   r"$\Delta T_{hp,ev,sh}$ [K]",
    "dT_he_ev_sh":   r"$\Delta T_{he,ev,sh}$ [K]",
    "dT_hp_cd_sc":   r"$\Delta T_{hp,cd,sc}$ [K]",
    "eta_max_cp":    r"$\eta_{max,cp}$ [-]",
    "eta_max_ex":    r"$\eta_{max,ex}$ [-]",
    "eta_pm":        r"$\eta_{pm}$ [-]",
    "T_st_lt":       r"$T_{st,lt}$ [°C]",
    "dT_HP_rel":     r"$\Delta T_{HP,rel}$ [-]",
}
CB_COLORS = {
    "SBVCHP_SBORC": "#4C72B0", "SBVCHP_SRORC": "#DD8452",
    "SRVCHP_SBORC": "#55A868", "SRVCHP_SRORC": "#C44E52",
}
PAIRS = list(combinations(OBJS, 2))


# ══════════════════════════════════════════════════════════════════════════════════
# 1. Data loading & pooling
# ══════════════════════════════════════════════════════════════════════════════════

def pool_results(wp):
    """Load all Pareto CSV files for a working point, add metadata columns."""
    pattern = os.path.join(RESULTS_DIR, f"pareto_{wp}_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No result files found for {wp} in {RESULTS_DIR}")

    frames = []
    for f in files:
        df = pd.read_csv(f)
        stem = os.path.basename(f).replace(f"pareto_{wp}_", "").replace(".csv", "")
        parts = stem.split("_")
        df["cb_config"] = parts[0] + "_" + parts[1]
        df["orc_type"]  = "SRORC" if "SRORC" in parts[1] else "SBORC"
        df["hp_type"]   = "SRVCHP" if "SRVCHP" in parts[0] else "SBVCHP"
        if len(parts) >= 3:
            df["fluid_hp"] = parts[2]
            df["fluid_he"] = parts[3] if len(parts) >= 4 else parts[2]
        frames.append(df)

    pool = pd.concat(frames, ignore_index=True)
    # Derived quantities
    pool["T_st_lt"] = pool["T_st_ht"] - pool["dT_st_sp"]
    # dT_HP_rel: ratio of HP temperature lift to max possible lift
    # (T_st_ht - T_cs) / (T_hs - T_cs) approximation — uses dT_st_sp and wp temps
    pool["dT_HP_rel"] = np.nan  # filled later per WP if needed

    print(f"[{wp}] Pooled: {len(pool):,} solutions from {len(files)} config×fluid pairs")
    return pool


# ══════════════════════════════════════════════════════════════════════════════════
# 2. Non-dominated sorting
# ══════════════════════════════════════════════════════════════════════════════════

def fast_nondom_3d(F):
    """Return boolean mask of non-dominated solutions (all objectives maximized)."""
    n = len(F)
    dominated = np.zeros(n, dtype=bool)
    for i in range(n):
        if dominated[i]:
            continue
        diff = F - F[i]
        dom  = np.all(diff >= 0, axis=1) & np.any(diff > 0, axis=1)
        dom[i] = False
        if dom.any():
            dominated[i] = True
    return ~dominated


# ══════════════════════════════════════════════════════════════════════════════════
# 3. Conflict metrics
# ══════════════════════════════════════════════════════════════════════════════════

def payoff(df, a, b):
    """Pay-off degradation rate C_ij (0 = no conflict, 1 = extreme conflict)."""
    ra = df[a].max() - df[a].min()
    rb = df[b].max() - df[b].min()
    if ra < 1e-9 or rb < 1e-9:
        return np.nan
    d_a2b = (df[b].max() - df.loc[df[a].idxmax(), b]) / rb
    d_b2a = (df[a].max() - df.loc[df[b].idxmax(), a]) / ra
    return (d_a2b + d_b2a) / 2


def compute_conflict_metrics(df):
    """Compute Spearman r_s, pay-off C, and d_Euclidean for all objective pairs."""
    metrics = {}
    for a, b in PAIRS:
        rs, _ = spearmanr(df[a], df[b])
        C     = payoff(df, a, b)
        sa = (df[a].max() - df[a].min()) / (df[a].max() + 1e-9)
        sb = (df[b].max() - df[b].min()) / (df[b].max() + 1e-9)
        d  = np.sqrt(sa**2 + sb**2)
        metrics[(a, b)] = {"rs": rs, "C": C, "d": d}
    return metrics


def dimension_reduction_judgment(metrics):
    """Determine whether (η_p2p, e_th) is a sufficient 2-objective reduction."""
    C_p2p_ex = metrics[("eta_p2p", "exergy_efficiency")]["C"]
    rs_p2p_ex = metrics[("eta_p2p", "exergy_efficiency")]["rs"]
    C_eth_ex = metrics[("energy_density_thermal", "exergy_efficiency")]["C"]
    rs_eth_ex = metrics[("energy_density_thermal", "exergy_efficiency")]["rs"]

    # 2-obj reduction valid if: (1) pay-off C is low (< 0.55), AND
    # (2) Spearman r_s is not strongly negative (> -0.5).
    # Strongly positive r_s (>> 0.5) means η_ex MOVES WITH η_p2p →
    # they are aligned, not competing — reduction is even more justified.
    # Strongly negative r_s (<< -0.5) means there IS a real trade-off even
    # if C looks moderate.
    if (C_p2p_ex is not None and not np.isnan(C_p2p_ex) and
        C_p2p_ex < 0.55 and rs_p2p_ex > -0.5):
        reason = ("aligned (r_s>0.5)" if rs_p2p_ex > 0.5 else
                  "weakly conflicting")
        decision = (
            f"RETAIN (η_p2p, e_th) as primary 2-objective pair. "
            f"η_p2p–η_ex is {reason} — dimension reduction justified."
        )
        retain_2obj = True
    else:
        reason = (f"strong conflict (r_s={rs_p2p_ex:+.3f})" if rs_p2p_ex < -0.5 else
                  f"non-negligible pay-off (C={C_p2p_ex:.3f})")
        decision = (
            f"η_p2p–η_ex shows {reason} — "
            "3-objective framework may be needed."
        )
        retain_2obj = False

    report = {
        "decision": decision,
        "retain_2obj": retain_2obj,
        "C_p2p_ex": C_p2p_ex,
        "rs_p2p_ex": rs_p2p_ex,
        "C_eth_ex": C_eth_ex,
        "rs_eth_ex": rs_eth_ex,
    }
    return report


# ══════════════════════════════════════════════════════════════════════════════════
# 4. Near-optimal region
# ══════════════════════════════════════════════════════════════════════════════════

def define_near_optimal(gf, obj_a="eta_p2p", obj_b="energy_density_thermal",
                        top_frac=0.10):
    """
    Near-optimal = solutions on the global front closest to the utopia point
    (ideal point = max of each objective, normalized).

    Uses normalized Euclidean distance to the ideal point — works correctly
    even when objectives are strongly conflicting (r_s ≈ -1).

    Returns the near-optimal subset of the global front.
    """
    # Normalize each objective to [0, 1] within the global front
    a_min, a_max = gf[obj_a].min(), gf[obj_a].max()
    b_min, b_max = gf[obj_b].min(), gf[obj_b].max()
    a_norm = (gf[obj_a] - a_min) / (a_max - a_min + 1e-9)
    b_norm = (gf[obj_b] - b_min) / (b_max - b_min + 1e-9)

    # Distance to utopia point (1, 1) in normalized space
    dist = np.sqrt((1 - a_norm)**2 + (1 - b_norm)**2)

    # Select top_frac with smallest distance
    cutoff = np.quantile(dist, top_frac)
    mask = dist <= cutoff
    no = gf[mask].copy().reset_index(drop=True)

    # Also report the objective thresholds
    thresh_a = no[obj_a].min()
    thresh_b = no[obj_b].min()
    print(f"  Near-optimal threshold (distance-to-utopia method):")
    print(f"    Distance cutoff: {cutoff:.4f}  →  {len(no)} solutions ({len(no)/len(gf)*100:.1f}%)")
    print(f"    {obj_a} range: [{no[obj_a].min():.4f}, {no[obj_a].max():.4f}]")
    print(f"    {obj_b} range: [{no[obj_b].min():.2f}, {no[obj_b].max():.2f}]")
    return no


# ══════════════════════════════════════════════════════════════════════════════════
# 5. Parameter classification
# ══════════════════════════════════════════════════════════════════════════════════

def classify_parameters(no_df, vars_to_analyze=None,
                        cv_must_have=0.10, cv_real_choice=0.20):
    """
    Compute CV for each variable in the near-optimal subset.
    Classify: CV < cv_must_have → must-have, CV > cv_real_choice → real-choice.
    """
    if vars_to_analyze is None:
        vars_to_analyze = DECISION_VARS + ["T_st_lt"]

    rows = []
    for var in vars_to_analyze:
        if var not in no_df.columns:
            continue
        vals = no_df[var].dropna()
        if len(vals) == 0:
            continue
        mean_v = vals.mean()
        std_v  = vals.std()
        cv     = std_v / mean_v if mean_v > 1e-9 else np.nan
        if np.isnan(cv):
            cls = "undefined"
        elif cv < cv_must_have:
            cls = "must-have"
        elif cv > cv_real_choice:
            cls = "real-choice"
        else:
            cls = "gray"

        rows.append({
            "variable": var,
            "label":    VAR_LABELS.get(var, var),
            "mean":     mean_v,
            "std":      std_v,
            "cv":       cv,
            "min":      vals.min(),
            "max":      vals.max(),
            "classification": cls,
        })

    param_table = pd.DataFrame(rows).sort_values("cv", ascending=True, na_position="last")
    return param_table


# ══════════════════════════════════════════════════════════════════════════════════
# 6. Representative design selection
# ══════════════════════════════════════════════════════════════════════════════════

def select_representative_designs(no_df, obj_a="eta_p2p", obj_b="energy_density_thermal"):
    """
    Select 3 representative designs from the near-optimal subset:
      D_eff : max obj_a (efficiency-oriented)
      D_den : max obj_b (density-oriented)
      D_bal : closest to ideal point in normalized (obj_a, obj_b) space
    """
    # Normalize objectives to [0, 1]
    a_min, a_max = no_df[obj_a].min(), no_df[obj_a].max()
    b_min, b_max = no_df[obj_b].min(), no_df[obj_b].max()
    a_norm = (no_df[obj_a] - a_min) / (a_max - a_min + 1e-9)
    b_norm = (no_df[obj_b] - b_min) / (b_max - b_min + 1e-9)

    idx_eff = no_df[obj_a].idxmax()
    idx_den = no_df[obj_b].idxmax()
    # Ideal point = (1, 1) in normalized space
    dist_to_ideal = np.sqrt((1 - a_norm)**2 + (1 - b_norm)**2)
    idx_bal = dist_to_ideal.idxmin()

    designs = []
    for name, idx in [("D_eff", idx_eff), ("D_den", idx_den), ("D_bal", idx_bal)]:
        row = no_df.loc[idx].to_dict()
        row["design_name"] = name
        row["design_description"] = {
            "D_eff": "Efficiency-oriented: maximize η_p2p",
            "D_den": "Density-oriented: maximize e_th",
            "D_bal": "Balanced: closest to ideal point (knee)",
        }[name]
        designs.append(row)

    designs_df = pd.DataFrame(designs)
    cols = ["design_name", "design_description"] + \
           [c for c in designs_df.columns if c not in ["design_name", "design_description"]]
    designs_df = designs_df[cols]

    print(f"\n  Representative designs selected:")
    for _, d in designs_df.iterrows():
        print(f"    {d['design_name']:6s}  "
              f"η_p2p={d[obj_a]:.4f}  e_th={d[obj_b]:.2f}  "
              f"T_st_ht={d['T_st_ht']:.1f}°C  ΔT_sp={d['dT_st_sp']:.1f}K  "
              f"cfg={d['cb_config']}")

    return designs_df


# ══════════════════════════════════════════════════════════════════════════════════
# 7. Visualization
# ══════════════════════════════════════════════════════════════════════════════════

def plot_near_optimal_region(pool, gf, no, designs_df, wp, metrics, dr_report, out_dir):
    """Fig 6: Near-optimal region on η_p2p–e_th global Pareto front."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.8))
    fig.suptitle(
        f"{wp} Near-Optimal Region  |  Global front: {len(gf)} solutions  |  "
        f"Near-optimal: {len(no)} solutions ({len(no)/len(gf)*100:.1f}%)",
        fontsize=11, fontweight="bold")

    # Panel (a): η_p2p–e_th with near-optimal highlighted
    ax = axes[0]
    ax.scatter(pool["eta_p2p"]*100, pool["energy_density_thermal"],
               c="#e0e0e0", s=5, alpha=0.3, label="All pooled")
    ax.scatter(gf["eta_p2p"]*100, gf["energy_density_thermal"],
               c="#4C72B0", s=18, alpha=0.6, edgecolors="none", label="Global front")
    ax.scatter(no["eta_p2p"]*100, no["energy_density_thermal"],
               c="#E24A33", s=35, alpha=0.85, edgecolors="white", lw=0.5,
               label="Near-optimal")
    # Mark representative designs
    for _, d in designs_df.iterrows():
        ax.scatter(d["eta_p2p"]*100, d["energy_density_thermal"],
                   s=180, marker="*", edgecolors="black", lw=1.2, zorder=10)
        offset = 0.3 if d["design_name"] != "D_eff" else -0.5
        ax.annotate(d["design_name"], (d["eta_p2p"]*100, d["energy_density_thermal"]),
                    textcoords="offset points", xytext=(8, 8+offset*10),
                    fontsize=9, fontweight="bold")
    ax.set_xlabel(r"$\eta_{p2p}$ [%]", fontsize=10)
    ax.set_ylabel(r"$e_{th}$ [kWh/m³]", fontsize=10)
    ax.set_title("Near-optimal region on global front\n"
                 rf"$r_s$={metrics[('eta_p2p','energy_density_thermal')]['rs']:+.3f}  "
                 rf"$C_{{ij}}$={metrics[('eta_p2p','energy_density_thermal')]['C']:.3f}",
                 fontsize=9)
    ax.legend(fontsize=7.5, loc="lower left")
    ax.grid(lw=0.3, alpha=0.4)

    # Panel (b): η_p2p–η_ex showing near-optimal projected
    ax = axes[1]
    ax.scatter(pool["eta_p2p"]*100, pool["exergy_efficiency"]*100,
               c="#e0e0e0", s=5, alpha=0.3)
    ax.scatter(gf["eta_p2p"]*100, gf["exergy_efficiency"]*100,
               c="#4C72B0", s=18, alpha=0.6, edgecolors="none")
    ax.scatter(no["eta_p2p"]*100, no["exergy_efficiency"]*100,
               c="#E24A33", s=35, alpha=0.85, edgecolors="white", lw=0.5)
    ax.set_xlabel(r"$\eta_{p2p}$ [%]", fontsize=10)
    ax.set_ylabel(r"$\eta_{ex}$ [%]", fontsize=10)
    ax.set_title("Near-optimal projected on η_p2p–η_ex\n"
                 rf"$r_s$={metrics[('eta_p2p','exergy_efficiency')]['rs']:+.3f}  "
                 rf"$C_{{ij}}$={metrics[('eta_p2p','exergy_efficiency')]['C']:.3f}",
                 fontsize=9)
    ax.grid(lw=0.3, alpha=0.4)

    # Panel (c): e_th–η_ex
    ax = axes[2]
    ax.scatter(pool["energy_density_thermal"], pool["exergy_efficiency"]*100,
               c="#e0e0e0", s=5, alpha=0.3)
    ax.scatter(gf["energy_density_thermal"], gf["exergy_efficiency"]*100,
               c="#4C72B0", s=18, alpha=0.6, edgecolors="none")
    ax.scatter(no["energy_density_thermal"], no["exergy_efficiency"]*100,
               c="#E24A33", s=35, alpha=0.85, edgecolors="white", lw=0.5)
    ax.set_xlabel(r"$e_{th}$ [kWh/m³]", fontsize=10)
    ax.set_ylabel(r"$\eta_{ex}$ [%]", fontsize=10)
    ax.set_title("Near-optimal projected on e_th–η_ex\n"
                 rf"$r_s$={metrics[('energy_density_thermal','exergy_efficiency')]['rs']:+.3f}  "
                 rf"$C_{{ij}}$={metrics[('energy_density_thermal','exergy_efficiency')]['C']:.3f}",
                 fontsize=9)
    ax.grid(lw=0.3, alpha=0.4)

    # Dimension reduction textbox
    dr_text = (
        f"DIMENSION REDUCTION\n"
        f"─────────────────────\n"
        f"C_p2p_ex = {dr_report['C_p2p_ex']:.3f}\n"
        f"r_s,p2p_ex = {dr_report['rs_p2p_ex']:+.3f}\n"
        f"→ {dr_report['decision'][:60]}...\n"
    )
    fig.text(0.02, 0.02, dr_text, fontsize=8, family="monospace",
             bbox=dict(boxstyle="round", fc="#f5f5f5", ec="#aaa"), va="bottom")

    out = os.path.join(out_dir, f"near_optimal_region_{wp}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


def plot_parameter_violins(no_df, param_table, wp, out_dir):
    """Fig 7: Violin/box plots of decision variables in near-optimal space."""
    # Sort by CV (from must-have to real-choice)
    ordered_vars = param_table["variable"].tolist()
    ordered_labels = [VAR_LABELS.get(v, v) for v in ordered_vars]
    n_vars = len(ordered_vars)

    fig, axes = plt.subplots(2, 5, figsize=(20, 8))
    axes = axes.flatten()
    fig.suptitle(f"{wp} Near-Optimal Parameter Distributions  (n={len(no_df)})",
                 fontsize=12, fontweight="bold")

    colors = {"must-have": "#4C72B0", "gray": "#AAAAAA", "real-choice": "#E24A33"}

    for i, (var, label) in enumerate(zip(ordered_vars, ordered_labels)):
        ax = axes[i]
        cls = param_table.loc[param_table["variable"] == var, "classification"].values[0]
        vals = no_df[var].dropna()

        # Violin
        parts = ax.violinplot(vals, positions=[0], vert=True, showmeans=True,
                              showmedians=True)
        for pc in parts["bodies"]:
            pc.set_facecolor(colors.get(cls, "#888"))
            pc.set_alpha(0.5)

        ax.set_title(f"{label}\nCV={no_df[var].std()/no_df[var].mean():.3f}  [{cls}]",
                     fontsize=8.5, color=colors.get(cls, "black"))
        ax.set_ylabel("")
        ax.set_xticks([])
        ax.grid(axis="y", lw=0.3, alpha=0.4)

    # Hide unused subplots
    for j in range(n_vars, len(axes)):
        axes[j].set_visible(False)

    fig.tight_layout()
    out = os.path.join(out_dir, f"parameter_violins_{wp}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


def plot_config_competition(gf, no, wp, out_dir):
    """Config / fluid composition: global front vs near-optimal."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Config composition
    ax = axes[0]
    gf_comp = (gf["cb_config"].value_counts() / len(gf) * 100)
    no_comp = (no["cb_config"].value_counts() / len(no) * 100)
    all_cfgs = sorted(set(gf_comp.index) | set(no_comp.index))
    x = np.arange(len(all_cfgs))
    w = 0.35
    gf_vals = [gf_comp.get(c, 0) for c in all_cfgs]
    no_vals = [no_comp.get(c, 0) for c in all_cfgs]
    colors_gf  = [CB_COLORS.get(c, "gray") for c in all_cfgs]
    colors_no  = [CB_COLORS.get(c, "gray") for c in all_cfgs]

    ax.bar(x - w/2, gf_vals, w, label="Global front", color=colors_gf, alpha=0.7, edgecolor="white")
    ax.bar(x + w/2, no_vals, w, label="Near-optimal", color=colors_no, alpha=1.0, edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(all_cfgs, rotation=15, ha="right", fontsize=8)
    ax.set_ylabel("Share [%]", fontsize=9)
    ax.set_title(f"Config composition: global front vs near-optimal\n{wp}", fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(axis="y", lw=0.3, alpha=0.4)

    # Fluid pair composition in near-optimal
    ax = axes[1]
    no["fluid_pair"] = no["fluid_hp"] + " / " + no["fluid_he"]
    fluid_comp = no["fluid_pair"].value_counts().head(12)
    bars = ax.barh(range(len(fluid_comp)), fluid_comp.values,
                   color="#55A868", alpha=0.8, edgecolor="white")
    ax.set_yticks(range(len(fluid_comp)))
    ax.set_yticklabels(fluid_comp.index, fontsize=7.5)
    ax.set_xlabel("Count in near-optimal", fontsize=9)
    ax.set_title("Fluid pairs in near-optimal subset", fontsize=9)
    ax.invert_yaxis()
    ax.grid(axis="x", lw=0.3, alpha=0.4)

    fig.tight_layout()
    out = os.path.join(out_dir, f"config_competition_{wp}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


# ══════════════════════════════════════════════════════════════════════════════════
# 8. Main analysis pipeline
# ══════════════════════════════════════════════════════════════════════════════════

def run_near_optimal_analysis(wp, top_frac=0.10, cv_low=0.10, cv_high=0.20):
    """Full near-optimal analysis for a given working point."""
    print(f"\n{'='*70}")
    print(f"NEAR-OPTIMAL ANALYSIS: {wp}")
    print(f"{'='*70}")

    # 1. Pool & global Pareto
    pool = pool_results(wp)
    F = pool[OBJS].values
    mask = fast_nondom_3d(F)
    gf = pool[mask].copy().reset_index(drop=True)
    print(f"  Global Pareto front: {len(gf)} solutions ({len(gf)/len(pool)*100:.1f}% of pool)")

    # 2. Conflict metrics & dimension reduction
    metrics = compute_conflict_metrics(gf)
    dr_report = dimension_reduction_judgment(metrics)
    print(f"\n  Conflict metrics (global front):")
    for (a, b), m in metrics.items():
        print(f"    {a:>22}–{b:<22}  r_s={m['rs']:+.3f}  C={m['C']:.3f}  d={m['d']:.3f}")
    print(f"\n  Dimension reduction: {dr_report['decision']}")

    # 3. Near-optimal region
    no = define_near_optimal(gf, top_frac=top_frac)

    # 4. Parameter classification
    param_table = classify_parameters(no, cv_must_have=cv_low, cv_real_choice=cv_high)
    print(f"\n  Parameter classification (CV < {cv_low}: must-have, CV > {cv_high}: real-choice):")
    for _, row in param_table.iterrows():
        print(f"    {row['variable']:<18s}  CV={row['cv']:.4f}  →  {row['classification']}")

    # 5. Representative design selection
    designs_df = select_representative_designs(no)

    # 6. Config / fluid competition
    print(f"\n  Config composition (global front → near-optimal):")
    gf_comp = (gf["cb_config"].value_counts() / len(gf) * 100)
    no_comp = (no["cb_config"].value_counts() / len(no) * 100)
    for cfg in sorted(set(gf_comp.index) | set(no_comp.index)):
        print(f"    {cfg:<20s}  GF: {gf_comp.get(cfg,0):5.1f}%  →  NO: {no_comp.get(cfg,0):5.1f}%")

    # 7. Save tables
    param_table.to_csv(os.path.join(RESULTS_DIR, f"near_optimal_{wp}_params.csv"),
                       index=False, float_format="%.6f")
    designs_df.to_csv(os.path.join(RESULTS_DIR, f"near_optimal_{wp}_designs.csv"),
                      index=False, float_format="%.6f")
    print(f"\n  Saved → results/near_optimal_{wp}_params.csv")
    print(f"  Saved → results/near_optimal_{wp}_designs.csv")

    # 8. Plots
    plot_near_optimal_region(pool, gf, no, designs_df, wp, metrics, dr_report, PLOT_DIR)
    plot_parameter_violins(no, param_table, wp, PLOT_DIR)
    plot_config_competition(gf, no, wp, PLOT_DIR)

    return {
        "pool": pool, "gf": gf, "no": no,
        "metrics": metrics, "dr_report": dr_report,
        "param_table": param_table, "designs": designs_df,
    }


# ══════════════════════════════════════════════════════════════════════════════════
# 9. Cross-WP comparison
# ══════════════════════════════════════════════════════════════════════════════════

def run_cross_wp_comparison(wps, top_frac=0.10, cv_low=0.10, cv_high=0.20):
    """Fig 9: Cross-working-point comparison of near-optimal characteristics."""
    all_results = {}
    summary_rows = []
    all_params = []

    for wp in wps:
        print(f"\n  Processing {wp}...")
        res = run_near_optimal_analysis(wp, top_frac=top_frac,
                                        cv_low=cv_low, cv_high=cv_high)
        all_results[wp] = res

        # Summary row
        m = res["metrics"]
        dr = res["dr_report"]
        summary_rows.append({
            "wp": wp,
            "n_pool": len(res["pool"]),
            "n_gf": len(res["gf"]),
            "n_no": len(res["no"]),
            "rs_p2p_eth": m[("eta_p2p", "energy_density_thermal")]["rs"],
            "C_p2p_eth": m[("eta_p2p", "energy_density_thermal")]["C"],
            "C_p2p_ex": dr["C_p2p_ex"],
            "rs_p2p_ex": dr["rs_p2p_ex"],
            "dim_reduce": dr["retain_2obj"],
            "T_st_ht_no_min": res["no"]["T_st_ht"].min(),
            "T_st_ht_no_max": res["no"]["T_st_ht"].max(),
            "dT_st_sp_no_mean": res["no"]["dT_st_sp"].mean(),
            "eta_p2p_range": f"{res['no']['eta_p2p'].min():.3f}–{res['no']['eta_p2p'].max():.3f}",
            "e_th_range": f"{res['no']['energy_density_thermal'].min():.1f}–{res['no']['energy_density_thermal'].max():.1f}",
        })

        # Accumulate param tables with WP label
        pt = res["param_table"].copy()
        pt["wp"] = wp
        all_params.append(pt)

    # Save summary table
    summary_df = pd.DataFrame(summary_rows)
    summary_path = os.path.join(RESULTS_DIR, "near_optimal_cross_wp_summary.csv")
    summary_df.to_csv(summary_path, index=False)
    print(f"\n  Saved → {summary_path}")

    # Fig 9a: CV comparison heatmap
    combined_params = pd.concat(all_params, ignore_index=True)
    plot_cv_comparison(combined_params, wps)

    # Fig 9b: Config composition side-by-side
    plot_config_cross_wp(all_results, wps)

    # Fig 9c: Dimension reduction landscape
    plot_dimension_reduction_landscape(summary_df)

    return all_results, summary_df


def plot_cv_comparison(combined_params, wps):
    """CV comparison across WPs — grouped bar chart."""
    vars_ordered = (combined_params.groupby("variable")["cv"]
                    .median().sort_values().index.tolist())
    n_vars = len(vars_ordered)

    fig, ax = plt.subplots(figsize=(14, 5.5))
    x = np.arange(n_vars)
    width = 0.25
    wp_colors = {"DC-A": "#4C72B0", "DC-C": "#55A868", "DC-E": "#E24A33"}

    for i, wp in enumerate(wps):
        wp_data = combined_params[combined_params["wp"] == wp]
        wp_cv = [wp_data.loc[wp_data["variable"] == v, "cv"].values[0]
                 if v in wp_data["variable"].values else np.nan
                 for v in vars_ordered]
        bars = ax.bar(x + i * width, wp_cv, width, label=wp,
                      color=wp_colors.get(wp, "gray"), alpha=0.85, edgecolor="white")

    # Threshold lines
    ax.axhline(y=0.10, color="gray", ls="--", lw=0.8, alpha=0.6)
    ax.axhline(y=0.20, color="gray", ls=":", lw=0.8, alpha=0.6)
    ax.text(n_vars - 0.5, 0.10, "must-have (0.10)", fontsize=6.5, va="bottom", ha="right", color="gray")
    ax.text(n_vars - 0.5, 0.20, "real-choice (0.20)", fontsize=6.5, va="bottom", ha="right", color="gray")

    ax.set_xticks(x + width)
    ax.set_xticklabels([VAR_LABELS.get(v, v) for v in vars_ordered],
                       rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("Coefficient of Variation (CV)", fontsize=10)
    ax.set_title("Parameter CV comparison across working points\n"
                 "(near-optimal subsets, top-10% by utopia distance)",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(axis="y", lw=0.3, alpha=0.4)

    fig.tight_layout()
    out = os.path.join(PLOT_DIR, "cross_wp_cv_comparison.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


def plot_config_cross_wp(all_results, wps):
    """Config composition side-by-side across WPs."""
    fig, ax = plt.subplots(figsize=(10, 5))
    all_cfgs = ["SBVCHP_SBORC", "SBVCHP_SRORC", "SRVCHP_SBORC", "SRVCHP_SRORC"]
    x = np.arange(len(wps))
    width = 0.18
    bottom = np.zeros(len(wps))

    for i, cfg in enumerate(all_cfgs):
        vals = []
        for wp in wps:
            no = all_results[wp]["no"]
            vals.append((no["cb_config"] == cfg).sum() / len(no) * 100 if len(no) > 0 else 0)
        ax.bar(x + (i - 1.5) * width, vals, width, label=cfg,
               color=CB_COLORS.get(cfg, "gray"), alpha=0.85, edgecolor="white")

    ax.set_xticks(x)
    ax.set_xticklabels(wps, fontsize=10)
    ax.set_ylabel("Share in near-optimal [%]", fontsize=9)
    ax.set_title("Config composition in near-optimal across working points",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=7.5, ncol=2)
    ax.grid(axis="y", lw=0.3, alpha=0.4)

    fig.tight_layout()
    out = os.path.join(PLOT_DIR, "cross_wp_config_comparison.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


def plot_dimension_reduction_landscape(summary_df):
    """Dimension reduction landscape: C vs r_s for η_p2p–η_ex across WPs."""
    fig, ax = plt.subplots(figsize=(6, 5))
    wp_colors = {"DC-A": "#4C72B0", "DC-B": "#4C72B0", "DC-C": "#55A868",
                 "DC-D": "#55A868", "DC-E": "#E24A33", "DC-F": "#E24A33"}

    for _, row in summary_df.iterrows():
        wp = row["wp"]
        ax.scatter(row["rs_p2p_ex"], row["C_p2p_ex"],
                   s=180, c=wp_colors.get(wp, "gray"), edgecolors="black",
                   lw=1.2, zorder=5, alpha=0.9)
        ax.annotate(wp, (row["rs_p2p_ex"], row["C_p2p_ex"]),
                    textcoords="offset points", xytext=(8, 5),
                    fontsize=9, fontweight="bold")

    # Threshold regions
    ax.axhline(y=0.55, color="gray", ls="--", lw=0.8, alpha=0.5)
    ax.axvline(x=0.0, color="gray", ls="--", lw=0.8, alpha=0.5)

    # Label regions
    ax.annotate("2-obj\nsufficient", xy=(0.3, 0.2), fontsize=9, color="#4C72B0",
                ha="center", va="center", bbox=dict(boxstyle="round", fc="white", alpha=0.6))
    ax.annotate("3-obj\nneeded", xy=(0.0, 0.8), fontsize=9, color="#E24A33",
                ha="center", va="center", bbox=dict(boxstyle="round", fc="white", alpha=0.6))

    ax.set_xlabel(r"Spearman $r_s$ ($\eta_{p2p}$ vs $\eta_{ex}$)", fontsize=10)
    ax.set_ylabel(r"Pay-off $C_{ij}$ ($\eta_{p2p}$ vs $\eta_{ex}$)", fontsize=10)
    ax.set_title("Dimension reduction landscape\n"
                 r"(threshold: $C_{ij}$ < 0.55 and $|r_s|$ < 0.5)",
                 fontsize=10)
    ax.grid(lw=0.3, alpha=0.4)

    fig.tight_layout()
    out = os.path.join(PLOT_DIR, "dimension_reduction_landscape.png")
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved → {out}")


# ══════════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Near-optimal design analysis")
    parser.add_argument("--wp", required=False, help="Working point, e.g. DC-A")
    parser.add_argument("--compare", nargs="+", default=None,
                        help="Multiple WPs for cross-comparison, e.g. --compare DC-A DC-C DC-E")
    parser.add_argument("--top-frac", type=float, default=0.10,
                        help="Near-optimal quantile threshold (default 0.10)")
    parser.add_argument("--cv-low", type=float, default=0.10,
                        help="CV threshold for must-have (default 0.10)")
    parser.add_argument("--cv-high", type=float, default=0.20,
                        help="CV threshold for real-choice (default 0.20)")
    args = parser.parse_args()

    if args.compare:
        results, summary = run_cross_wp_comparison(
            wps=args.compare,
            top_frac=args.top_frac,
            cv_low=args.cv_low,
            cv_high=args.cv_high,
        )
        print(f"\n{'='*70}")
        print("CROSS-WP SUMMARY")
        print(f"{'='*70}")
        print(summary.to_string(index=False))
    elif args.wp:
        results = run_near_optimal_analysis(
            wp=args.wp,
            top_frac=args.top_frac,
            cv_low=args.cv_low,
            cv_high=args.cv_high,
        )
        print(f"\n{'='*70}")
        print(f"DONE. Outputs in: {PLOT_DIR}")
        print(f"{'='*70}")
    else:
        parser.error("Either --wp or --compare must be specified")
