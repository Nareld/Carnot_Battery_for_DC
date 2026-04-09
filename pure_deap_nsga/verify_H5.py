"""
H5 验证：ORC 制冷剂（R134a）的临界温度约束限制了 ΔT_sp 的实际上限，
从而减小了 e_th max 和 e_th–η_ex 冲突强度。

推断：R134a 的临界温度（101.1°C）在 DC-A 工况下可能与 T_st_ht + ΔT_sp
的组合发生接近临界的限制，使 SBORC+R134a 无法达到与其他制冷剂相同的
最大 ΔT_sp，从而降低 e_th max 和 e_th–η_ex 的冲突强度。

关键物理约束：亚临界 ORC 中蒸发温度必须低于制冷剂临界温度一定裕量（防止
near-critical 操作困难）。当 ΔT_sp 过大时，hot tank 温度 T_st_ht 需要更高
以维持足够的 ORC 蒸发压力，而这可能推动蒸发温度接近 T_crit。

验证指标：
  - 不同 ORC 制冷剂下 ΔT_sp 的最大值分布
  - e_th max 与 ΔT_sp max 的对应关系
  - R134a vs 其他制冷剂的 C_ij(e_th-η_ex) 对比
"""

import glob
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import mannwhitneyu, spearmanr

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
OUT_DIR     = os.path.join(os.path.dirname(__file__), "plots", "verification")
os.makedirs(OUT_DIR, exist_ok=True)

# CoolProp critical temperatures of HE fluids used in DC-A [°C]
T_CRIT = {
    "R1234ze(E)": 109.4,
    "R134a":      101.1,
    "R152a":      113.3,
    "R227ea":     101.7,
}

# Payoff degradation helper
def payoff(df, a, b):
    ra = df[a].max() - df[a].min()
    rb = df[b].max() - df[b].min()
    if ra < 1e-9 or rb < 1e-9:
        return np.nan
    d_a2b = (df[b].max() - df.loc[df[a].idxmax(), b]) / rb
    d_b2a = (df[a].max() - df.loc[df[b].idxmax(), a]) / ra
    return (d_a2b + d_b2a) / 2

# Load per-file data
rows = []
for f in sorted(glob.glob(f"{RESULTS_DIR}/pareto_DC-A_*.csv")):
    df  = pd.read_csv(f)
    stem = os.path.basename(f).replace("pareto_DC-A_","").replace(".csv","")
    parts = stem.split("_")
    cb    = parts[0] + "_" + parts[1]
    fhp   = parts[2]
    fhe   = parts[3] if len(parts) > 3 else "?"

    idx_eth = df["energy_density_thermal"].idxmax()
    T_crit_he = T_CRIT.get(fhe, np.nan)
    T_st_at_eth_max = df.loc[idx_eth, "T_st_ht"]
    dT_sp_at_eth_max = df.loc[idx_eth, "dT_st_sp"]

    # near-critical margin: how far is the ORC hot side from T_crit?
    # ORC evaporation ≈ T_st_ht - ΔT_sp - pinch (cold tank side)
    # rough estimate: ORC evap temp ~ (T_st_ht - dT_sp) since ORC evaporates from cold tank side up
    # Actually: ORC evaporates at the hot tank side, so T_evap_ORC ≈ T_st_ht - pinch (~3K)
    T_evap_est = T_st_at_eth_max - 3.0
    margin = T_crit_he - T_evap_est if not np.isnan(T_crit_he) else np.nan

    rows.append({
        "cb_config": cb, "fluid_hp": fhp, "fluid_he": fhe,
        "T_crit_he": T_crit_he,
        "dT_sp_max": df["dT_st_sp"].max(),
        "dT_sp_at_eth_max": dT_sp_at_eth_max,
        "T_st_ht_at_eth_max": T_st_at_eth_max,
        "eth_max": df["energy_density_thermal"].max(),
        "eth_range": df["energy_density_thermal"].max() - df["energy_density_thermal"].min(),
        "C_eth_ex": payoff(df, "energy_density_thermal", "exergy_efficiency"),
        "T_evap_est": T_evap_est,
        "near_crit_margin": margin,
        "ex_range": df["exergy_efficiency"].max() - df["exergy_efficiency"].min(),
    })

results = pd.DataFrame(rows)

print("="*75)
print("H5 VALIDATION: ORC fluid critical temperature constraint on ΔT_sp upper limit")
print("="*75)

print(f"\n{'Fluid':<14} {'T_crit':>8} {'dT_sp_max':>10} {'dT_sp@eth_max':>14} "
      f"{'eth_max':>10} {'C(eth-ex)':>11} {'near-crit_margin':>18}")
print("-"*90)
for fhe, g in results.groupby("fluid_he"):
    tc = T_CRIT.get(fhe, np.nan)
    print(f"  {fhe:<12} {tc:>8.1f}°C"
          f"  {g['dT_sp_max'].mean():>9.1f}K"
          f"  {g['dT_sp_at_eth_max'].mean():>13.1f}K"
          f"  {g['eth_max'].mean():>9.2f} kWh/m³"
          f"  {g['C_eth_ex'].mean():>10.3f}"
          f"  {g['near_crit_margin'].mean():>16.1f}K")

# Statistical test: R134a vs others for dT_sp and eth_max
r134a = results[results["fluid_he"] == "R134a"]
others = results[results["fluid_he"] != "R134a"]

print(f"\n=== R134a vs others (statistical test) ===")
for col, label in [("dT_sp_max", "Max ΔT_sp"),
                   ("dT_sp_at_eth_max", "ΔT_sp at e_th max"),
                   ("eth_max", "e_th max"),
                   ("C_eth_ex", "C_ij(e_th–η_ex)"),
                   ("near_crit_margin", "Near-crit margin")]:
    m_r = r134a[col].mean()
    m_o = others[col].mean()
    stat, pval = mannwhitneyu(r134a[col], others[col], alternative="two-sided")
    sig = "***" if pval < 0.001 else ("**" if pval < 0.01 else ("*" if pval < 0.05 else "n.s."))
    print(f"  {label:<22}: R134a={m_r:.3f}  others={m_o:.3f}  Δ={m_r-m_o:+.3f}  p={pval:.4f} {sig}")

# ── figure ────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(13, 5), constrained_layout=True)
fig.suptitle("H5 Verification: ORC fluid critical temperature → ΔT_sp upper limit constraint\n"
             "DC-A  |  R134a (T_crit=101.1°C) vs other HE fluids",
             fontsize=10, fontweight="bold")

FLUID_COLORS = {"R1234ze(E)": "#4C72B0", "R134a": "#E24A33",
                "R152a": "#55A868", "R227ea": "#8172B2"}

# Panel 1: ΔT_sp distribution by fluid
ax = axes[0]
for xi, (fhe, g) in enumerate(results.groupby("fluid_he")):
    jitter = np.random.default_rng(42).uniform(-0.15, 0.15, size=len(g))
    ax.scatter([xi]*len(g) + jitter, g["dT_sp_max"],
               color=FLUID_COLORS.get(fhe, "gray"), s=22, alpha=0.7, edgecolors="none")
    ax.hlines(g["dT_sp_max"].mean(), xi-0.3, xi+0.3,
              color=FLUID_COLORS.get(fhe, "gray"), lw=2)
ax.set_xticks(range(4))
ax.set_xticklabels(list(results.groupby("fluid_he").groups.keys()), fontsize=8.5)
ax.set_ylabel("Max ΔT_st,sp [K]", fontsize=9)
ax.set_title("(a) Maximum observed ΔT_sp\nby ORC fluid", fontsize=8.5)
ax.grid(axis="y", lw=0.3, alpha=0.4)

# Panel 2: e_th max by fluid
ax = axes[1]
for xi, (fhe, g) in enumerate(results.groupby("fluid_he")):
    jitter = np.random.default_rng(42).uniform(-0.15, 0.15, size=len(g))
    ax.scatter([xi]*len(g) + jitter, g["eth_max"],
               color=FLUID_COLORS.get(fhe, "gray"), s=22, alpha=0.7, edgecolors="none")
    ax.hlines(g["eth_max"].mean(), xi-0.3, xi+0.3,
              color=FLUID_COLORS.get(fhe, "gray"), lw=2)
ax.set_xticks(range(4))
ax.set_xticklabels(list(results.groupby("fluid_he").groups.keys()), fontsize=8.5)
ax.set_ylabel("$e_{th}$ max [kWh m$^{-3}$]", fontsize=9)
ax.set_title("(b) Maximum thermal energy density\nby ORC fluid", fontsize=8.5)
ax.grid(axis="y", lw=0.3, alpha=0.4)

# Panel 3: near-critical margin vs e_th max (scatter)
ax = axes[2]
for fhe, g in results.groupby("fluid_he"):
    ax.scatter(g["near_crit_margin"], g["eth_max"],
               c=[FLUID_COLORS.get(fhe,"gray")]*len(g),
               s=30, alpha=0.7, edgecolors="none", label=fhe)
rs, _ = spearmanr(results["near_crit_margin"].dropna(),
                  results["eth_max"][results["near_crit_margin"].notna()])
ax.set_xlabel("Near-critical margin (T_crit − T_evap_est) [K]", fontsize=8.5)
ax.set_ylabel("$e_{th}$ max [kWh m$^{-3}$]", fontsize=9)
ax.set_title(f"(c) Near-crit margin vs e_th max\n$r_s$ = {rs:+.3f}", fontsize=8.5)
ax.legend(fontsize=7.5, loc="upper right")
ax.grid(lw=0.3, alpha=0.4)
# annotate T_crit reference lines
for fhe, tc in T_CRIT.items():
    ax.axvline(tc - 3, color=FLUID_COLORS.get(fhe, "gray"),
               lw=0.8, ls=":", alpha=0.5)

out = os.path.join(OUT_DIR, "H5_ORC_fluid_Tcrit_dTsp_constraint.png")
fig.savefig(out, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\nSaved → {out}")
