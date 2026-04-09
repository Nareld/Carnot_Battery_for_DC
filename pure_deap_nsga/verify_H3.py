"""
H3 验证：HP 回热器（SRVCHP）通过提高过冷度提升 COP，同时将最优 T_st_ht 上移

推断：HP 回热器在压缩机入口端预热气态制冷剂，将膨胀阀前过冷热量回收利用，
使系统在更高 T_st_ht 下仍能保持高 COP_HP。验证两点：
  (a) 相同 T_st_ht 下 SRVCHP 的 dT_hp_cd_sc（HP 过冷度）并不总是最大，
      而是呈现更宽泛的分布（real choice），而 SBVCHP 则倾向于最大化过冷度
  (b) η_p2p 最优解的 T_st_ht 分布：SRVCHP > SBVCHP（上移约 5°C）
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

def load_by_hp(hp_type):
    frames = []
    for f in sorted(glob.glob(f"{RESULTS_DIR}/pareto_DC-A_{hp_type}*.csv")):
        frames.append(pd.read_csv(f))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

sbvchp = load_by_hp("SBVCHP")
srvchp = load_by_hp("SRVCHP")

print("="*75)
print("H3 VALIDATION: HP recuperator effect on T_st_ht shift and subcooling flexibility")
print("="*75)

# (a) T_st_ht at η_p2p max for each config
def get_best_per_file(hp_type, obj_col="eta_p2p"):
    rows = []
    for f in sorted(glob.glob(f"{RESULTS_DIR}/pareto_DC-A_{hp_type}*.csv")):
        df = pd.read_csv(f)
        idx = df[obj_col].idxmax()
        rows.append({
            "file": os.path.basename(f),
            "T_st_ht": df.loc[idx, "T_st_ht"],
            "dT_st_sp": df.loc[idx, "dT_st_sp"],
            "dT_hp_cd_sc": df.loc[idx, "dT_hp_cd_sc"],
            "eta_p2p_max": df[obj_col].max(),
        })
    return pd.DataFrame(rows)

best_sb = get_best_per_file("SBVCHP")
best_sr = get_best_per_file("SRVCHP")

print(f"\n(a) T_st_ht at η_p2p maximum:")
print(f"    SBVCHP: {best_sb['T_st_ht'].mean():.1f} ± {best_sb['T_st_ht'].std():.1f} °C"
      f"  (range {best_sb['T_st_ht'].min():.1f}–{best_sb['T_st_ht'].max():.1f}°C)")
print(f"    SRVCHP: {best_sr['T_st_ht'].mean():.1f} ± {best_sr['T_st_ht'].std():.1f} °C"
      f"  (range {best_sr['T_st_ht'].min():.1f}–{best_sr['T_st_ht'].max():.1f}°C)")
stat, pval = mannwhitneyu(best_sb["T_st_ht"], best_sr["T_st_ht"], alternative="less")
print(f"    MWU test (SBVCHP < SRVCHP): p = {pval:.4f}  "
      f"{'CONFIRMS' if pval < 0.05 else 'DOES NOT CONFIRM'} T_st_ht upshift (H3)")

print(f"\n(b) η_p2p maximum value:")
print(f"    SBVCHP: {best_sb['eta_p2p_max'].mean():.3f} ± {best_sb['eta_p2p_max'].std():.3f}")
print(f"    SRVCHP: {best_sr['eta_p2p_max'].mean():.3f} ± {best_sr['eta_p2p_max'].std():.3f}")
gain = (best_sr["eta_p2p_max"].mean() - best_sb["eta_p2p_max"].mean()) / best_sb["eta_p2p_max"].mean() * 100
print(f"    Relative gain from HP recuperator: {gain:+.1f}%")

print(f"\n(c) HP subcooling dT_hp_cd_sc at η_p2p max:")
print(f"    SBVCHP: {best_sb['dT_hp_cd_sc'].mean():.1f} ± {best_sb['dT_hp_cd_sc'].std():.1f} K"
      f"  (spread = {best_sb['dT_hp_cd_sc'].std():.2f}K)")
print(f"    SRVCHP: {best_sr['dT_hp_cd_sc'].mean():.1f} ± {best_sr['dT_hp_cd_sc'].std():.1f} K"
      f"  (spread = {best_sr['dT_hp_cd_sc'].std():.2f}K)")
print(f"    Expected: SRVCHP wider spread (real choice) vs SBVCHP narrow (must-have high)")
print(f"    Observed spread ratio (SRVCHP/SBVCHP): {best_sr['dT_hp_cd_sc'].std()/max(best_sb['dT_hp_cd_sc'].std(),0.01):.2f}x")

# (d) Full distribution of dT_hp_cd_sc across all solutions
print(f"\n(d) dT_hp_cd_sc distribution (all Pareto solutions):")
for label, df in [("SBVCHP", sbvchp), ("SRVCHP", srvchp)]:
    q25, med, q75 = df["dT_hp_cd_sc"].quantile([0.25, 0.5, 0.75])
    print(f"    {label}: Q25={q25:.1f}K  median={med:.1f}K  Q75={q75:.1f}K  max={df['dT_hp_cd_sc'].max():.1f}K")

# ── figure ────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), constrained_layout=True)
fig.suptitle("H3 Verification: HP recuperator → T_st,ht upshift + subcooling flexibility\n"
             "DC-A  |  SBVCHP vs SRVCHP", fontsize=10, fontweight="bold")

# Panel 1: T_st_ht at η_p2p max
ax = axes[0]
ax.boxplot([best_sb["T_st_ht"], best_sr["T_st_ht"]],
           labels=["SBVCHP", "SRVCHP"], patch_artist=True,
           boxprops=dict(facecolor="#dddddd"))
ax.set_ylabel("$T_{st,ht}$ at $\\eta_{p2p}$ max [°C]", fontsize=9)
ax.set_title(f"(a) T_st,ht at η_p2p max\nSBVCHP={best_sb['T_st_ht'].mean():.1f}°C  "
             f"SRVCHP={best_sr['T_st_ht'].mean():.1f}°C  p={pval:.3f}", fontsize=8)
ax.grid(axis="y", lw=0.3, alpha=0.5)

# Panel 2: dT_hp_cd_sc at η_p2p max
ax = axes[1]
ax.boxplot([best_sb["dT_hp_cd_sc"], best_sr["dT_hp_cd_sc"]],
           labels=["SBVCHP", "SRVCHP"], patch_artist=True,
           boxprops=dict(facecolor="#dddddd"))
ax.set_ylabel("$\\Delta T_{HP,cd,sc}$ [K]", fontsize=9)
ax.set_title("(b) HP subcooling at η_p2p max\n(wider = more flexible)", fontsize=8)
ax.grid(axis="y", lw=0.3, alpha=0.5)

# Panel 3: full distribution of dT_hp_cd_sc
ax = axes[2]
bins = np.linspace(0, 15, 30)
ax.hist(sbvchp["dT_hp_cd_sc"], bins=bins, alpha=0.55, density=True,
        color="#E24A33", label="SBVCHP")
ax.hist(srvchp["dT_hp_cd_sc"], bins=bins, alpha=0.55, density=True,
        color="#348ABD", label="SRVCHP")
ax.set_xlabel("$\\Delta T_{HP,cd,sc}$ [K]", fontsize=9)
ax.set_ylabel("Density", fontsize=9)
ax.set_title("(c) Full dT_hp_cd_sc distribution\n(all Pareto solutions)", fontsize=8)
ax.legend(fontsize=8)
ax.grid(lw=0.3, alpha=0.4)

out = os.path.join(OUT_DIR, "H3_SRVCHP_Tst_upshift_subcooling.png")
fig.savefig(out, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\nSaved → {out}")
