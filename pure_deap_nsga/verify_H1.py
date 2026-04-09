"""
H1 验证：SBORC 构型下 η_p2p 与 η_ex 通过 ΔT_sp 协同变化

推断：在基本 ORC（SBORC）构型中，η_p2p 和 η_ex 共享小 ΔT_sp 的最优方向，
因此两者在帕累托前沿上呈正相关。ΔT_sp 是驱动两者协同的中间变量。

验证思路：
- 对所有 DC-A SBORC 构型，绘制 η_p2p vs η_ex 散点图，用 ΔT_sp 着色
- 若 ΔT_sp 沿前沿方向单调变化（小 ΔT_sp 对应高 η_p2p + 高 η_ex），
  则证明两者共享同一设计方向，不是直接耦合而是通过 ΔT_sp 间接协同
- 对比 SRORC 构型的同类图，观察颜色梯度是否变得不规则（解耦信号）
"""

import glob
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.stats import spearmanr

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
OUT_DIR     = os.path.join(os.path.dirname(__file__), "plots", "verification")
T_HS = 35.0  # DC-A heat source temperature [°C]
os.makedirs(OUT_DIR, exist_ok=True)

PYTHON = "/opt/homebrew/anaconda3/envs/oemof-heat-pump-tutorial-env/bin/python"

# ── load ──────────────────────────────────────────────────────────────────────
def load_group(orc_type):
    pattern = f"{RESULTS_DIR}/pareto_DC-A_*{orc_type}*.csv"
    frames = []
    for f in sorted(glob.glob(pattern)):
        df = pd.read_csv(f)
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

sborc = load_group("SBORC")
srorc = load_group("SRORC")
print(f"SBORC solutions: {len(sborc)}   SRORC solutions: {len(srorc)}")

# ── correlation by ΔT_sp quartile ─────────────────────────────────────────────
print("\n=== H1 VALIDATION: ΔT_sp as mediator of η_p2p–η_ex co-variation ===\n")

for label, df in [("SBORC (η_p2p–η_ex expected POSITIVE)", sborc),
                  ("SRORC (η_p2p–η_ex expected WEAK/NEGATIVE)", srorc)]:
    if df.empty:
        continue
    rs_p2p_ex, _ = spearmanr(df["eta_p2p"], df["exergy_efficiency"])
    rs_p2p_dT, _ = spearmanr(df["eta_p2p"], df["dT_st_sp"])
    rs_ex_dT,  _ = spearmanr(df["exergy_efficiency"], df["dT_st_sp"])
    print(f"  {label}")
    print(f"    r_s(η_p2p, η_ex)   = {rs_p2p_ex:+.3f}")
    print(f"    r_s(η_p2p, ΔT_sp)  = {rs_p2p_dT:+.3f}  ← should be negative for SBORC")
    print(f"    r_s(η_ex,  ΔT_sp)  = {rs_ex_dT:+.3f}  ← should be negative for SBORC")
    # verify: if both η_p2p and η_ex decrease when ΔT_sp increases,
    # they co-vary through ΔT_sp
    same_sign = (rs_p2p_dT < 0) == (rs_ex_dT < 0)
    print(f"    Both decrease with ΔT_sp? → {same_sign}  "
          f"({'CONFIRMS' if same_sign else 'CONTRADICTS'} H1 for {label.split()[0]})\n")

# ── figure ────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
fig.suptitle("H1 Verification: ΔT_sp as mediator of η_p2p–η_ex co-variation\n"
             "DC-A working point", fontsize=11, fontweight="bold")

for ax, (label, df, title) in zip(axes, [
    ("SBORC", sborc, "SBORC  (basic ORC)\nExpected: positive correlation via shared ΔT_sp"),
    ("SRORC", srorc, "SRORC  (recuperated ORC)\nExpected: decoupled / negative correlation"),
]):
    if df.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        continue

    sc = ax.scatter(df["eta_p2p"] * 100, df["exergy_efficiency"] * 100,
                    c=df["dT_st_sp"], cmap="RdYlBu_r",
                    s=8, alpha=0.6, edgecolors="none",
                    vmin=df["dT_st_sp"].min(), vmax=df["dT_st_sp"].max())
    cb = fig.colorbar(sc, ax=ax, shrink=0.8)
    cb.set_label("ΔT_st,sp [K]", fontsize=8)

    rs, _ = spearmanr(df["eta_p2p"], df["exergy_efficiency"])
    ax.set_xlabel(r"$\eta_{p2p}$ [%]", fontsize=9)
    ax.set_ylabel(r"$\eta_{ex}$ [%]", fontsize=9)
    ax.set_title(title + f"\n$r_s$(η_p2p, η_ex) = {rs:+.3f}", fontsize=8.5)
    ax.grid(lw=0.3, alpha=0.4)

    # annotate low/high ΔT_sp regions
    low_dT  = df[df["dT_st_sp"] < df["dT_st_sp"].quantile(0.2)]
    high_dT = df[df["dT_st_sp"] > df["dT_st_sp"].quantile(0.8)]
    ax.text(0.98, 0.95, f"Low ΔT_sp zone\nη_p2p↑ + η_ex↑?",
            transform=ax.transAxes, ha="right", va="top", fontsize=7.5,
            color="#2166ac",
            bbox=dict(fc="white", ec="#2166ac", alpha=0.7, pad=2))

out = os.path.join(OUT_DIR, "H1_dTsp_mediator_SBORC_vs_SRORC.png")
fig.savefig(out, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\nSaved → {out}")
