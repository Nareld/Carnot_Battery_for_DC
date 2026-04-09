"""
H4 验证：DC-A 处于 Laterre 30K 临界点——η_p2p 最优解的 T_st_ht 呈中间值

推断：ΔT_hs-cs = 30K 是 TI-PTES 的设计临界点：
  - ΔT < 30K：最大化 T_st_ht（高 η_ORC 效益 > HP lift 代价）
  - ΔT ≥ 30K：最小化 T_st_ht（HP lift 代价 > η_ORC 效益），极端时 HP 退化
  - ΔT = 30K（DC-A）：过渡区，相对 HP lift ΔT_HP_rel 应处于 (0, 1) 中间段

验证指标：
  ΔT_HP_rel = (T_st_ht - T_hs) / (T_st_ht_max - T_hs) ∈ [0, 1]
  - ≈ 0：HP 完全退化（T_st_ht → 最小），不应出现在 DC-A
  - ≈ 1：完全最大化温度（ΔT < 30K 的行为），不应出现在 DC-A 的 η_p2p 最优解
  - 中间值（预期约 0.3–0.7）：过渡行为，支持 H4
"""

import glob
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import mannwhitneyu

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
OUT_DIR     = os.path.join(os.path.dirname(__file__), "plots", "verification")
os.makedirs(OUT_DIR, exist_ok=True)

T_HS      = 35.0   # DC-A heat source [°C]
T_ST_MAX  = 120.0  # optimization upper bound for T_st_ht [°C]
T_ST_MIN  = 50.0   # optimization lower bound [°C]  (DC-A config)

def rel_hp_lift(T_st_ht):
    return (T_st_ht - T_HS) / (T_ST_MAX - T_HS)

# Load all DC-A files
all_rows = []
for f in sorted(glob.glob(f"{RESULTS_DIR}/pareto_DC-A_*.csv")):
    df = pd.read_csv(f)
    stem = os.path.basename(f).replace("pareto_DC-A_","").replace(".csv","")
    parts = stem.split("_")
    cb  = parts[0] + "_" + parts[1]
    # η_p2p max solution
    idx_p2p = df["eta_p2p"].idxmax()
    # η_ex max solution
    idx_ex  = df["exergy_efficiency"].idxmax()
    # e_th max solution
    idx_eth = df["energy_density_thermal"].idxmax()

    all_rows.append({
        "cb_config": cb,
        # at η_p2p max
        "T_p2p":    df.loc[idx_p2p, "T_st_ht"],
        "dT_p2p":   df.loc[idx_p2p, "dT_st_sp"],
        "rel_lift_p2p": rel_hp_lift(df.loc[idx_p2p, "T_st_ht"]),
        # at η_ex max
        "T_ex":     df.loc[idx_ex, "T_st_ht"],
        "rel_lift_ex": rel_hp_lift(df.loc[idx_ex, "T_st_ht"]),
        # at e_th max
        "T_eth":    df.loc[idx_eth, "T_st_ht"],
        "rel_lift_eth": rel_hp_lift(df.loc[idx_eth, "T_st_ht"]),
        # full distribution of T_st_ht in file
        "T_mean":   df["T_st_ht"].mean(),
        "T_min_obs": df["T_st_ht"].min(),
        "T_max_obs": df["T_st_ht"].max(),
    })

results = pd.DataFrame(all_rows)

print("="*75)
print("H4 VALIDATION: DC-A at Laterre 30K tipping point")
print(f"  T_hs = {T_HS}°C,  T_st_ht bounds = [{T_ST_MIN}, {T_ST_MAX}]°C")
print(f"  ΔT_HP_rel = (T_st_ht - T_hs) / (T_st_ht_max - T_hs)")
print("="*75)

for cb, g in results.groupby("cb_config"):
    rl = g["rel_lift_p2p"]
    print(f"\n  {cb}  (n={len(g)})")
    print(f"    ΔT_HP_rel at η_p2p max:  {rl.mean():.3f} ± {rl.std():.3f}"
          f"  [range {rl.min():.3f}–{rl.max():.3f}]")
    regime = ("DEGENERATED (lift→0)"   if rl.mean() < 0.15 else
              "FULLY_MAXIMISED (Δ<30K)" if rl.mean() > 0.85 else
              "TRANSITIONAL (at tipping point)")
    print(f"    → Regime: {regime}")
    T_abs = g["T_p2p"].mean()
    print(f"    T_st_ht at η_p2p max: {T_abs:.1f}°C  "
          f"(HP lift above T_hs = {T_abs - T_HS:.1f}°C)")

print("\n\n=== Summary across all 42 configs ===")
print(f"  ΔT_HP_rel at η_p2p max:   {results['rel_lift_p2p'].mean():.3f} ± {results['rel_lift_p2p'].std():.3f}")
print(f"  ΔT_HP_rel at η_ex  max:   {results['rel_lift_ex'].mean():.3f} ± {results['rel_lift_ex'].std():.3f}")
print(f"  ΔT_HP_rel at e_th  max:   {results['rel_lift_eth'].mean():.3f} ± {results['rel_lift_eth'].std():.3f}")
print(f"\n  Any η_p2p-max solution with rel_lift < 0.1 (degeneration)?  "
      f"{(results['rel_lift_p2p'] < 0.1).sum()} / {len(results)}")
print(f"  Any η_p2p-max solution with rel_lift > 0.9 (fully maximised)? "
      f"{(results['rel_lift_p2p'] > 0.9).sum()} / {len(results)}")

# ── figure ────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), constrained_layout=True)
fig.suptitle("H4 Verification: DC-A at Laterre 30 K tipping point\n"
             "Relative HP lift ΔT_HP_rel = (T_st,ht − T_hs) / (T_st,ht_max − T_hs)",
             fontsize=10, fontweight="bold")

CB_ORDER  = ["SBVCHP_SBORC","SBVCHP_SRORC","SRVCHP_SBORC","SRVCHP_SRORC"]
CB_COLORS = {"SBVCHP_SBORC":"#4C72B0","SBVCHP_SRORC":"#DD8452",
             "SRVCHP_SBORC":"#55A868","SRVCHP_SRORC":"#C44E52"}

for ax, (obj_col, title) in zip(axes, [
    ("rel_lift_p2p", "At $\\eta_{p2p}$ maximum\n(expected: intermediate ≈ 0.4–0.6)"),
    ("rel_lift_ex",  "At $\\eta_{ex}$ maximum"),
    ("rel_lift_eth", "At $e_{th}$ maximum"),
]):
    for xi, cb in enumerate(CB_ORDER):
        g = results[results["cb_config"] == cb][obj_col]
        if g.empty:
            continue
        jitter = np.random.default_rng(42).uniform(-0.15, 0.15, size=len(g))
        ax.scatter([xi] * len(g) + jitter, g, s=25, alpha=0.7,
                   color=CB_COLORS[cb], edgecolors="none")
        ax.hlines(g.mean(), xi - 0.35, xi + 0.35,
                  color=CB_COLORS[cb], lw=2.2)

    # reference lines
    ax.axhspan(0,    0.15, color="#ffcccc", alpha=0.3, zorder=0)
    ax.axhspan(0.85, 1.0,  color="#ccddff", alpha=0.3, zorder=0)
    ax.axhspan(0.15, 0.85, color="#ddffdd", alpha=0.15, zorder=0)
    ax.text(3.5, 0.08, "Degenerated\n(lift→0)", ha="right", va="center",
            fontsize=7, color="#cc4444", alpha=0.8)
    ax.text(3.5, 0.92, "Fully maximised\n(ΔT<30K behavior)", ha="right", va="center",
            fontsize=7, color="#2244cc", alpha=0.8)
    ax.text(3.5, 0.50, "Transitional\n(tipping point)", ha="right", va="center",
            fontsize=7.5, color="#226622", alpha=0.9)
    ax.set_xticks(range(4))
    ax.set_xticklabels([c.replace("_","\n") for c in CB_ORDER], fontsize=7.5)
    ax.set_ylim(-0.05, 1.05)
    ax.set_ylabel("ΔT_HP_rel [–]", fontsize=8)
    ax.set_title(title, fontsize=8.5)
    ax.grid(axis="y", lw=0.3, alpha=0.4)

out = os.path.join(OUT_DIR, "H4_tipping_point_rel_HP_lift.png")
fig.savefig(out, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\nSaved → {out}")
