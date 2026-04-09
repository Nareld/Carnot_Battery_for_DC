"""
Interface I & II: 全局帕累托前沿构建 + ΔT_sp 中介作用可视化 + 降维判断

步骤：
  1. 池化 DC-A 全部 42 种构型的帕累托解（4200 个点）
  2. 三维非支配排序 → 全局帕累托前沿
  3. 可视化：ΔT_sp 在全局前沿上的分布（双走廊假设验证）
  4. 全局前沿层面重新计算冲突指标 → 降维判断
"""

import glob, os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.colors import Normalize
from scipy.stats import spearmanr

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
OUT_DIR     = os.path.join(os.path.dirname(__file__), "plots", "global_pareto")
os.makedirs(OUT_DIR, exist_ok=True)

PYTHON_ENV = "/opt/homebrew/anaconda3/envs/oemof-heat-pump-tutorial-env/bin/python"
OBJS = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]
OBJ_LABELS = {
    "eta_p2p":                r"$\eta_{p2p}$ [%]",
    "energy_density_thermal": r"$e_{th}$ [kWh m$^{-3}$]",
    "exergy_efficiency":      r"$\eta_{ex}$ [%]",
}
CB_COLORS = {
    "SBVCHP_SBORC": "#4C72B0", "SBVCHP_SRORC": "#DD8452",
    "SRVCHP_SBORC": "#55A868", "SRVCHP_SRORC": "#C44E52",
}

# ── 1. 池化 ───────────────────────────────────────────────────────────────────
files = sorted(glob.glob(f"{RESULTS_DIR}/pareto_DC-A_*.csv"))
frames = []
for f in files:
    df = pd.read_csv(f)
    stem = os.path.basename(f).replace("pareto_DC-A_","").replace(".csv","")
    parts = stem.split("_")
    df["cb_config"] = parts[0] + "_" + parts[1]
    df["orc_type"]  = "SRORC" if "SRORC" in parts[1] else "SBORC"
    df["hp_type"]   = "SRVCHP" if "SRVCHP" in parts[0] else "SBVCHP"
    frames.append(df)
pool = pd.concat(frames, ignore_index=True)
print(f"Pooled: {len(pool)} solutions from {len(files)} configs")

# ── 2. 三维非支配排序 ─────────────────────────────────────────────────────────
def fast_nondom_3d(F):
    """Return boolean mask of non-dominated solutions (all objectives maximized)."""
    n = len(F)
    dominated = np.zeros(n, dtype=bool)
    # vectorised: for each point i, check if any j dominates it
    for i in range(n):
        if dominated[i]:
            continue
        # j dominates i if F[j] >= F[i] everywhere and > somewhere
        diff = F - F[i]               # (n, 3)
        dom  = np.all(diff >= 0, axis=1) & np.any(diff > 0, axis=1)
        dom[i] = False
        if dom.any():
            dominated[i] = True
    return ~dominated

F = pool[OBJS].values
print("Running 3-D non-dominated sorting …")
mask = fast_nondom_3d(F)
global_front = pool[mask].copy().reset_index(drop=True)
print(f"Global Pareto front: {mask.sum()} solutions "
      f"({mask.mean()*100:.1f}% of pool)")

# config composition of global front
print("\nConfig composition of global front:")
comp = global_front["cb_config"].value_counts()
for cfg, cnt in comp.items():
    print(f"  {cfg:<20} {cnt:>4}  ({cnt/len(global_front)*100:.1f}%)")

# ── 3. 冲突指标（全局前沿层面）────────────────────────────────────────────────
def payoff(df, a, b):
    ra = df[a].max() - df[a].min()
    rb = df[b].max() - df[b].min()
    if ra < 1e-9 or rb < 1e-9:
        return np.nan
    d_a2b = (df[b].max() - df.loc[df[a].idxmax(), b]) / rb
    d_b2a = (df[a].max() - df.loc[df[b].idxmax(), a]) / ra
    return (d_a2b + d_b2a) / 2

from itertools import combinations
PAIRS = list(combinations(OBJS, 2))
PAIR_LABELS_SHORT = {
    ("eta_p2p","energy_density_thermal"): r"$\eta_{p2p}$–$e_{th}$",
    ("eta_p2p","exergy_efficiency"):      r"$\eta_{p2p}$–$\eta_{ex}$",
    ("energy_density_thermal","exergy_efficiency"): r"$e_{th}$–$\eta_{ex}$",
}

print("\n" + "="*65)
print("Global Pareto front conflict metrics")
print("="*65)
print(f"{'Pair':<30} {'Spearman':>10} {'Payoff C':>10} {'d_Eucl':>10}")
print("-"*65)
gf_metrics = {}
for a, b in PAIRS:
    rs, _ = spearmanr(global_front[a], global_front[b])
    C     = payoff(global_front, a, b)
    span_a = (global_front[a].max()-global_front[a].min()) / global_front[a].max()
    span_b = (global_front[b].max()-global_front[b].min()) / global_front[b].max()
    d     = np.sqrt(span_a**2 + span_b**2)
    lbl   = PAIR_LABELS_SHORT[(a,b)]
    print(f"  {lbl:<28} {rs:>+9.3f}  {C:>9.3f}  {d:>9.3f}")
    gf_metrics[(a,b)] = {"rs": rs, "C": C, "d": d}

# compare with per-config averages (from earlier analysis)
PER_CFG = {
    ("eta_p2p","energy_density_thermal"):       {"rs": -0.923, "C": 0.979},
    ("eta_p2p","exergy_efficiency"):             {"rs": +0.191, "C": 0.459},
    ("energy_density_thermal","exergy_efficiency"): {"rs": -0.398, "C": 0.873},
}
print("\nComparison: per-config average vs global front")
print(f"{'Pair':<30} {'rs(per-cfg)':>12} {'rs(global)':>12} {'C(per-cfg)':>12} {'C(global)':>12}")
print("-"*80)
for pair in PAIRS:
    pc = PER_CFG[pair]
    gf = gf_metrics[pair]
    lbl = PAIR_LABELS_SHORT[pair]
    print(f"  {lbl:<28}  {pc['rs']:>+10.3f}  {gf['rs']:>+10.3f}  "
          f"{pc['C']:>10.3f}  {gf['C']:>10.3f}")

# ── 4. Dimension reduction judgment ──────────────────────────────────────────
print("\n" + "="*65)
print("DIMENSION REDUCTION JUDGMENT")
print("="*65)
rs_p2p_eth = gf_metrics[("eta_p2p","energy_density_thermal")]["rs"]
C_p2p_eth  = gf_metrics[("eta_p2p","energy_density_thermal")]["C"]
rs_p2p_ex  = gf_metrics[("eta_p2p","exergy_efficiency")]["rs"]
C_p2p_ex   = gf_metrics[("eta_p2p","exergy_efficiency")]["C"]
rs_eth_ex  = gf_metrics[("energy_density_thermal","exergy_efficiency")]["rs"]
C_eth_ex   = gf_metrics[("energy_density_thermal","exergy_efficiency")]["C"]

print(f"\n  η_p2p–e_th:   r_s={rs_p2p_eth:+.3f}  C={C_p2p_eth:.3f}  → MAIN CONFLICT AXIS")
print(f"  η_p2p–η_ex:   r_s={rs_p2p_ex:+.3f}  C={C_p2p_ex:.3f}")
print(f"  e_th–η_ex:    r_s={rs_eth_ex:+.3f}  C={C_eth_ex:.3f}")

if C_p2p_ex < 0.55 and abs(rs_p2p_ex) < 0.5:
    decision = "RETAIN (η_p2p, e_th) as primary 2-objective pair for near-optimal analysis.\n" \
               "  η_ex to be retained as supplementary evaluation indicator."
else:
    decision = "All three pairs show significant conflict — consider retaining 3-objective framework."
print(f"\n  → Dimension reduction decision:\n    {decision}")

# ── 5. 可视化 ─────────────────────────────────────────────────────────────────
fig = plt.figure(figsize=(18, 11))
fig.suptitle(
    f"DC-A Global Pareto Front  |  {len(global_front)} non-dominated solutions "
    f"from {len(pool)} pooled\n"
    r"Interface I: $\Delta T_{sp}$ corridors  ·  Interface II: Dimension reduction judgment",
    fontsize=11, fontweight="bold", y=0.99
)
gs = gridspec.GridSpec(3, 4, figure=fig, hspace=0.52, wspace=0.36,
                       left=0.06, right=0.97, top=0.93, bottom=0.06,
                       height_ratios=[1.1, 1.0, 1.0])

# ── Row 0: three pairwise Pareto projections coloured by ΔT_sp ───────────────
cmap_dT  = plt.cm.RdYlBu_r
vmin_dT  = global_front["dT_st_sp"].min()
vmax_dT  = global_front["dT_st_sp"].max()
norm_dT  = Normalize(vmin=vmin_dT, vmax=vmax_dT)

for col, (a, b) in enumerate(PAIRS):
    ax = fig.add_subplot(gs[0, col])
    sc = ax.scatter(
        global_front[a] * (100 if "efficiency" in a or a=="eta_p2p" else 1),
        global_front[b] * (100 if "efficiency" in b or b=="eta_p2p" else 1),
        c=global_front["dT_st_sp"], cmap=cmap_dT, norm=norm_dT,
        s=18, alpha=0.82, edgecolors="none"
    )
    ax.set_xlabel(OBJ_LABELS[a], fontsize=8.5)
    ax.set_ylabel(OBJ_LABELS[b], fontsize=8.5)
    lbl = PAIR_LABELS_SHORT[(a,b)]
    rs_gf = gf_metrics[(a,b)]["rs"]
    C_gf  = gf_metrics[(a,b)]["C"]
    ax.set_title(f"{lbl}\n$r_s$={rs_gf:+.3f}  $C_{{ij}}$={C_gf:.3f}", fontsize=9)
    ax.grid(lw=0.3, alpha=0.4)

# shared colorbar (4th column of row 0)
cb_ax = fig.add_subplot(gs[0, 3])
cb_ax.axis("off")
sm = plt.cm.ScalarMappable(cmap=cmap_dT, norm=norm_dT)
cb = fig.colorbar(sm, ax=cb_ax, fraction=0.55, pad=0.02, aspect=18)
cb.set_label(r"$\Delta T_{st,sp}$ [K]", fontsize=9)
cb.ax.tick_params(labelsize=8)
cb.ax.axhline(20, color="#2166ac", lw=1.5, ls="--")
cb.ax.axhline(55, color="#d73027", lw=1.5, ls="--")
cb.ax.text(2.5, 17, "Efficiency\ncorridor", fontsize=7, color="#2166ac",
           transform=cb.ax.get_yaxis_transform(), ha="left", va="center", clip_on=False)
cb.ax.text(2.5, 57, "Density\ncorridor", fontsize=7, color="#d73027",
           transform=cb.ax.get_yaxis_transform(), ha="left", va="center", clip_on=False)

# ── Row 1: ΔT_sp histogram + T_st_ht + conflict bar + dim-reduction text ─────
# ΔT_sp distribution
ax_dT = fig.add_subplot(gs[1, 0:2])
ax_dT.hist(global_front["dT_st_sp"], bins=40, color="#888", alpha=0.75, edgecolor="white", lw=0.3)
ax_dT.axvline(20, color="#2166ac", lw=1.5, ls="--", label="Efficiency corridor boundary (~20K)")
ax_dT.axvline(55, color="#d73027", lw=1.5, ls="--", label="Density corridor boundary (~55K)")
ax_dT.set_xlabel(r"$\Delta T_{st,sp}$ [K]", fontsize=9)
ax_dT.set_ylabel("Count", fontsize=9)
ax_dT.set_title(r"$\Delta T_{sp}$ distribution on global Pareto front"
                "\n(bimodal = two design corridors)", fontsize=8.5)
ax_dT.legend(fontsize=7.5, loc="upper center")
ax_dT.grid(axis="y", lw=0.3, alpha=0.4)

# T_st_ht distribution split by ORC type
ax_T = fig.add_subplot(gs[1, 2:4])
for orc, color in [("SBORC","#4C72B0"), ("SRORC","#DD8452")]:
    sub = global_front[global_front["orc_type"] == orc]
    ax_T.hist(sub["T_st_ht"], bins=30, alpha=0.55, color=color,
              edgecolor="white", lw=0.3, label=f"{orc} (n={len(sub)})", density=True)
ax_T.set_xlabel(r"$T_{st,ht}$ [°C]", fontsize=9)
ax_T.set_ylabel("Density", fontsize=9)
ax_T.set_title(r"$T_{st,ht}$ distribution by ORC type"
               "\n(SRORC needs higher temperature)", fontsize=8.5)
ax_T.legend(fontsize=8)
ax_T.grid(axis="y", lw=0.3, alpha=0.4)

# ── Row 2: CB config composition + conflict metrics comparison ────────────────
ax_comp = fig.add_subplot(gs[2, 0])
comp_pct = (global_front["cb_config"].value_counts() / len(global_front) * 100)
bars = ax_comp.barh(comp_pct.index, comp_pct.values,
                    color=[CB_COLORS.get(c,"gray") for c in comp_pct.index],
                    alpha=0.8, edgecolor="white")
for bar, val in zip(bars, comp_pct.values):
    ax_comp.text(val+0.5, bar.get_y()+bar.get_height()/2,
                 f"{val:.0f}%", va="center", fontsize=8)
ax_comp.set_xlabel("Share of global front [%]", fontsize=8.5)
ax_comp.set_title("Configuration composition\nof global Pareto front", fontsize=8.5)
ax_comp.grid(axis="x", lw=0.3, alpha=0.4)
ax_comp.set_xlim(0, comp_pct.max()*1.25)

# conflict metrics: per-config avg vs global front
ax_cf = fig.add_subplot(gs[2, 1:3])
pair_lbls_short = [r"$\eta_{p2p}$–$e_{th}$", r"$\eta_{p2p}$–$\eta_{ex}$", r"$e_{th}$–$\eta_{ex}$"]
x = np.arange(3)
w = 0.35
pc_C = [PER_CFG[p]["C"] for p in PAIRS]
gf_C = [gf_metrics[p]["C"] for p in PAIRS]
bars1 = ax_cf.bar(x - w/2, pc_C, w, label="Per-config avg", color="#888", alpha=0.75)
bars2 = ax_cf.bar(x + w/2, gf_C, w, label="Global front",   color="#E24A33", alpha=0.75)
for bars in [bars1, bars2]:
    for bar in bars:
        ax_cf.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.01,
                   f"{bar.get_height():.3f}", ha="center", va="bottom", fontsize=7.5)
ax_cf.axhline(0.5, color="#888", lw=0.8, ls="--", alpha=0.6)
ax_cf.set_xticks(x)
ax_cf.set_xticklabels(pair_lbls_short, fontsize=9)
ax_cf.set_ylabel("Pay-off $C_{ij}$", fontsize=9)
ax_cf.set_ylim(0, 1.1)
ax_cf.set_title("Conflict intensity: per-config vs global front\n"
                "(governs dimension reduction decision)", fontsize=8.5)
ax_cf.legend(fontsize=8)
ax_cf.grid(axis="y", lw=0.3, alpha=0.4)

# dimension reduction summary panel
ax_dr = fig.add_subplot(gs[2, 3])
ax_dr.axis("off")
dr_text = (
    "DIMENSION REDUCTION\nJUDGMENT\n"
    "─────────────────────\n"
    f"Global front\n"
    f"n = {len(global_front)} solutions\n\n"
    f"η_p2p–e_th\n"
    f"  $r_s$ = {gf_metrics[('eta_p2p','energy_density_thermal')]['rs']:+.3f}\n"
    f"  C = {gf_metrics[('eta_p2p','energy_density_thermal')]['C']:.3f}  ← PRIMARY\n\n"
    f"η_p2p–η_ex\n"
    f"  $r_s$ = {gf_metrics[('eta_p2p','exergy_efficiency')]['rs']:+.3f}\n"
    f"  C = {gf_metrics[('eta_p2p','exergy_efficiency')]['C']:.3f}\n\n"
    f"e_th–η_ex\n"
    f"  $r_s$ = {gf_metrics[('energy_density_thermal','exergy_efficiency')]['rs']:+.3f}\n"
    f"  C = {gf_metrics[('energy_density_thermal','exergy_efficiency')]['C']:.3f}\n\n"
    "─────────────────────\n"
    "→ RETAIN (η_p2p, e_th)\n"
    "  η_ex = supplementary"
    if (gf_metrics[('eta_p2p','exergy_efficiency')]['C'] < 0.55) else
    "→ THREE objectives\n  may be needed"
)
ax_dr.text(0.05, 0.97, dr_text, transform=ax_dr.transAxes,
           va="top", ha="left", fontsize=8, family="monospace",
           bbox=dict(boxstyle="round,pad=0.5", fc="#f5f5f5", ec="#aaaaaa", lw=0.8))

# save
out = os.path.join(OUT_DIR, "global_pareto_DCA_interface_I_II.png")
fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(f"\nSaved → {out}")

# also save global front CSV
gf_out = os.path.join(OUT_DIR, "global_pareto_DC-A.csv")
global_front.to_csv(gf_out, index=False, float_format="%.6f")
print(f"Saved → {gf_out}")
