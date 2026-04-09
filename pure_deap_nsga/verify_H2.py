"""
H2 验证：SRORC 高 η_ex 解与高 η_p2p 解在 ORC 蒸发器过热度和储罐温度上存在差异

推断：ORC 回热器为 η_ex 提供了一条独立的改善路径（回收膨胀机出口显热），
这条路径依赖不同的 dT_he_ev_sh 和 T_st_ht 配置，与 η_p2p 的最优配置不同。
这种路径分离导致 SRORC 中 η_p2p 与 η_ex 的正相关减弱甚至变负。

验证思路：
- 对 SRORC 构型的帕累托解，将解按 η_p2p 和 η_ex 分别排序，提取各自的
  "高性能解集"（top 25%）
- 比较两组解在 dT_he_ev_sh（ORC 过热度，直接影响回热器可用热量）
  和 T_st_ht 上的分布差异
- 若差异显著：说明两个目标的最优设计路径不同，支持 H2
- 对比 SBORC（预期无差异，两者共享设计路径）
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

def load_by_orc(orc_type):
    frames = []
    for f in sorted(glob.glob(f"{RESULTS_DIR}/pareto_DC-A_*{orc_type}*.csv")):
        frames.append(pd.read_csv(f))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

sborc = load_by_orc("SBORC")
srorc = load_by_orc("SRORC")

def top_bottom_comparison(df, label, q=0.25):
    """Compare design variables between top-q η_p2p and top-q η_ex solutions."""
    thr_p2p = df["eta_p2p"].quantile(1 - q)
    thr_ex  = df["exergy_efficiency"].quantile(1 - q)
    high_p2p = df[df["eta_p2p"]  >= thr_p2p]
    high_ex  = df[df["exergy_efficiency"] >= thr_ex]

    dvars = ["T_st_ht", "dT_st_sp", "dT_he_ev_sh", "dT_hp_cd_sc"]
    print(f"\n  {label}  (N={len(df)}, top {int(q*100)}%: n_p2p={len(high_p2p)}, n_ex={len(high_ex)})")
    print(f"  {'Variable':<18} {'High η_p2p':>14} {'High η_ex':>14} {'Δ (ex−p2p)':>12} {'p-value':>10}")
    print(f"  {'-'*72}")

    results = {}
    for dv in dvars:
        if dv not in df.columns:
            continue
        m_p2p = high_p2p[dv].mean()
        m_ex  = high_ex[dv].mean()
        s_p2p = high_p2p[dv].std()
        s_ex  = high_ex[dv].std()
        stat, pval = mannwhitneyu(high_p2p[dv], high_ex[dv], alternative="two-sided")
        sig = "***" if pval < 0.001 else ("**" if pval < 0.01 else ("*" if pval < 0.05 else ""))
        print(f"  {dv:<18} {m_p2p:>7.2f}±{s_p2p:<5.2f}  {m_ex:>7.2f}±{s_ex:<5.2f}  "
              f"{m_ex-m_p2p:>+10.2f}  {pval:>9.4f} {sig}")
        results[dv] = {"m_p2p": m_p2p, "m_ex": m_ex, "pval": pval}
    return results, high_p2p, high_ex

print("="*75)
print("H2 VALIDATION: Design variable divergence between high-η_p2p and high-η_ex solutions")
print("="*75)

r_sborc, hp_p2p_sb, hp_ex_sb = top_bottom_comparison(sborc, "SBORC (expected: no divergence)")
r_srorc, hp_p2p_sr, hp_ex_sr = top_bottom_comparison(srorc, "SRORC (expected: divergence in dT_he_ev_sh and T_st_ht)")

# ── figure ────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 4, figsize=(15, 8), constrained_layout=True)
fig.suptitle("H2 Verification: Design variable distributions for high-η_p2p vs high-η_ex solutions\n"
             "DC-A  |  Top 25% solutions of each objective", fontsize=10, fontweight="bold")

dvars_plot = ["T_st_ht", "dT_st_sp", "dT_he_ev_sh", "dT_hp_cd_sc"]
dvar_lbls  = ["$T_{st,ht}$ [°C]", "$\\Delta T_{sp}$ [K]",
              "$\\Delta T_{he,ev,sh}$ [K]\n(ORC superheat)", "$\\Delta T_{hp,cd,sc}$ [K]\n(HP subcooling)"]

for row, (label, df, h_p2p, h_ex) in enumerate([
    ("SBORC", sborc, hp_p2p_sb, hp_ex_sb),
    ("SRORC", srorc, hp_p2p_sr, hp_ex_sr),
]):
    if df.empty:
        continue
    for col, (dv, dvlbl) in enumerate(zip(dvars_plot, dvar_lbls)):
        ax = axes[row, col]
        if dv not in df.columns:
            ax.axis("off")
            continue
        bins = np.linspace(df[dv].min(), df[dv].max(), 25)
        ax.hist(h_p2p[dv], bins=bins, alpha=0.55, color="#E24A33", label="High $\\eta_{p2p}$", density=True)
        ax.hist(h_ex[dv],  bins=bins, alpha=0.55, color="#348ABD", label="High $\\eta_{ex}$",  density=True)
        ax.axvline(h_p2p[dv].mean(), color="#E24A33", lw=1.8, ls="--")
        ax.axvline(h_ex[dv].mean(),  color="#348ABD", lw=1.8, ls="--")
        _, pval = mannwhitneyu(h_p2p[dv], h_ex[dv], alternative="two-sided")
        sig = "***" if pval < 0.001 else ("**" if pval < 0.01 else ("*" if pval < 0.05 else "n.s."))
        ax.set_title(f"{label}  {dvlbl}\np={pval:.4f} {sig}", fontsize=8)
        ax.set_xlabel(dvlbl, fontsize=7.5)
        if col == 0:
            ax.set_ylabel("Density", fontsize=8)
        if row == 0 and col == 0:
            ax.legend(fontsize=7.5, loc="upper right")
        ax.tick_params(labelsize=7)
        ax.grid(lw=0.3, alpha=0.4)

out = os.path.join(OUT_DIR, "H2_SRORC_design_path_divergence.png")
fig.savefig(out, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\nSaved → {out}")
