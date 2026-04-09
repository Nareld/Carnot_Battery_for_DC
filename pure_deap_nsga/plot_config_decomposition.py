"""
四种 CB 构型的流体对贡献分解图（2×2 布局）

每个子图展示：
  - 该构型的汇总 pooled 前沿（粗彩色线，与主图一致）
  - 各流体对的个别前沿（颜色编码 HP 流体，线型编码 ORC 流体）
  - 标注达到各极值的最优流体对
"""

import glob, os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
from matplotlib.ticker import MultipleLocator

RESULTS_DIR = '/Users/a1234/Carnot_Battery_for_DC/pure_deap_nsga/results'
OUT_DIR     = '/Users/a1234/Carnot_Battery_for_DC/pure_deap_nsga/plots/global_pareto'
os.makedirs(OUT_DIR, exist_ok=True)

OBJ_X, OBJ_Y = 'eta_p2p', 'energy_density_thermal'

CFG_STYLE = {
    'SBVCHP_SBORC': dict(color='#2166ac', label='SBVCHP + SBORC'),
    'SRVCHP_SBORC': dict(color='#1a9641', label='SRVCHP + SBORC'),
    'SBVCHP_SRORC': dict(color='#d95f02', label='SBVCHP + SRORC'),
    'SRVCHP_SRORC': dict(color='#b2182b', label='SRVCHP + SRORC'),
}

# HP 流体颜色 / ORC 流体线型
HP_COLOR = {
    'R1233zd(E)': '#1f77b4',
    'R245fa':     '#ff7f0e',
    'R600':       '#2ca02c',
}
HE_STYLE = {
    'R1234ze(E)': '-',
    'R134a':      '--',
    'R152a':      ':',
    'R227ea':     '-.',
}

def nondom_2d(df):
    F = df[[OBJ_X, OBJ_Y]].values
    n = len(F)
    is_nd = np.ones(n, dtype=bool)
    for i in range(n):
        dom = np.all(F >= F[i], axis=1) & np.any(F > F[i], axis=1)
        dom[i] = False
        if dom.any():
            is_nd[i] = False
    return df[is_nd].copy()

def front_line(df_nd):
    s = df_nd.sort_values(OBJ_X)
    return s[OBJ_X].values * 100, s[OBJ_Y].values

# ── load ──────────────────────────────────────────────────────────────────────
files = sorted(glob.glob(f'{RESULTS_DIR}/pareto_DC-A_*.csv'))
all_items = []
for f in files:
    stem  = os.path.basename(f).replace('pareto_DC-A_','').replace('.csv','')
    parts = stem.split('_')
    cb = parts[0] + '_' + parts[1]
    fhp = parts[2]; fhe = parts[3] if len(parts) > 3 else '?'
    df  = pd.read_csv(f)
    df['cb_config'] = cb; df['fluid_hp'] = fhp; df['fluid_he'] = fhe
    all_items.append({'cb': cb, 'fhp': fhp, 'fhe': fhe, 'df': df})

pool = pd.concat([x['df'] for x in all_items], ignore_index=True)

# ── pooled front per config ───────────────────────────────────────────────────
cfg_pool_nd = {}
for cb in CFG_STYLE:
    df_cb = pool[pool['cb_config'] == cb]
    cfg_pool_nd[cb] = nondom_2d(df_cb)

# ── figure: 2×2 ──────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(14, 11), constrained_layout=True)
fig.suptitle(
    'DC-A  |  Fluid pair contributions within each CB configuration\n'
    r'Color = HP fluid  ·  Line style = ORC fluid  ·  '
    r'Thick line = config pooled front',
    fontsize=10.5, fontweight='bold'
)

for ax, cb in zip(axes.flat, CFG_STYLE):
    cb_st  = CFG_STYLE[cb]
    items  = [x for x in all_items if x['cb'] == cb]
    nd_pool = cfg_pool_nd[cb]
    px, py  = front_line(nd_pool)

    # ── identify which fluid pairs actually contribute to pooled front ─────────
    contrib_pairs = set(zip(nd_pool['fluid_hp'], nd_pool['fluid_he']))

    # axis limits
    x_lo = max(0,  px.min() - 2)
    x_hi = px.max() + 5
    y_lo = max(0,  py.min() - 1)
    y_hi = py.max() + 2.5

    # ── layer 0: non-contributing fluid pair fronts (thin gray) ──────────────
    for item in items:
        if (item['fhp'], item['fhe']) in contrib_pairs:
            continue                     # handled in layer 1
        nd  = nondom_2d(item['df'])
        if len(nd) < 2: continue
        xs, ys = front_line(nd)
        ax.plot(xs, ys, color='#bbbbbb', lw=0.7, alpha=0.45, ls='-',
                solid_capstyle='round', zorder=2)

    # ── layer 1: contributing fluid pair fronts (colored, full opacity) ───────
    drawn = {}
    for item in items:
        if (item['fhp'], item['fhe']) not in contrib_pairs:
            continue
        nd  = nondom_2d(item['df'])
        if len(nd) < 2: continue
        xs, ys = front_line(nd)
        color = HP_COLOR.get(item['fhp'], '#888')
        ls    = HE_STYLE.get(item['fhe'], '-')
        line, = ax.plot(xs, ys, color=color, ls=ls, lw=1.5, alpha=0.88,
                         solid_capstyle='round', zorder=4)
        ax.scatter(xs[-1], ys[-1], color=color, s=25, zorder=6,
                   edgecolors='white', linewidths=0.5)
        key = (item['fhp'], item['fhe'])
        if key not in drawn:
            drawn[key] = line

    # ── pooled config front (thick) ───────────────────────────────────────────
    ax.plot(px, py, color=cb_st['color'], lw=2.6, ls='-',
            zorder=8, solid_capstyle='round', label='Pooled config front')

    # mark max η_p2p and max e_th on pooled front
    ax.scatter(px[-1], py[-1], color=cb_st['color'], s=70, zorder=10,
               edgecolors='white', linewidths=1.0)
    idx_eth = np.argmax(py)
    ax.scatter(px[idx_eth], py[idx_eth], color=cb_st['color'], s=70,
               marker='D', zorder=10, edgecolors='white', linewidths=1.0)

    # annotate best fluid pair at max η_p2p end
    best_row = nd_pool.loc[nd_pool[OBJ_X].idxmax()]
    fhp_best = best_row['fluid_hp']; fhe_best = best_row['fluid_he']
    ax.annotate(
        f'max $\\eta_{{p2p}}$:\n{fhp_best}/{fhe_best}',
        xy=(px[-1], py[-1]),
        xytext=(px[-1] - 3.5, py[-1] + 1.8),
        fontsize=7, color=cb_st['color'], fontweight='bold',
        arrowprops=dict(arrowstyle='->', color=cb_st['color'], lw=0.8),
        ha='right', va='bottom',
        bbox=dict(boxstyle='round,pad=0.2', fc='white',
                  ec=cb_st['color'], alpha=0.88, lw=0.6),
        zorder=11
    )
    # annotate best fluid pair at max e_th end
    best_eth = nd_pool.loc[nd_pool[OBJ_Y].idxmax()]
    fhp_eth  = best_eth['fluid_hp']; fhe_eth = best_eth['fluid_he']
    ax.annotate(
        f'max $e_{{th}}$:\n{fhp_eth}/{fhe_eth}',
        xy=(px[idx_eth], py[idx_eth]),
        xytext=(px[idx_eth] + 3.0, py[idx_eth] - 1.5),
        fontsize=7, color=cb_st['color'], fontweight='bold',
        arrowprops=dict(arrowstyle='->', color=cb_st['color'], lw=0.8),
        ha='left', va='top',
        bbox=dict(boxstyle='round,pad=0.2', fc='white',
                  ec=cb_st['color'], alpha=0.88, lw=0.6),
        zorder=11
    )

    # ── formatting ────────────────────────────────────────────────────────────
    ax.set_xlim(x_lo, x_hi)
    ax.set_ylim(y_lo, y_hi)
    ax.set_xlabel(r'$\eta_{p2p}$ [%]', fontsize=9)
    ax.set_ylabel(r'$e_{th}$ [kWh m$^{-3}$]', fontsize=9)
    ax.xaxis.set_minor_locator(MultipleLocator(2))
    ax.yaxis.set_minor_locator(MultipleLocator(1))
    ax.grid(lw=0.35, alpha=0.45, which='major')
    ax.grid(lw=0.15, alpha=0.2,  which='minor')

    # ── per-subplot legend ────────────────────────────────────────────────────
    # HP fluid colors (contributing only)
    hp_fluids_contrib = sorted({fhp for fhp, _ in contrib_pairs})
    hp_handles = [
        mlines.Line2D([], [], color=HP_COLOR[f], lw=1.8, label=f'HP: {f}')
        for f in hp_fluids_contrib
    ]
    # ORC fluid linestyles (contributing only)
    he_fluids_contrib = sorted({fhe for _, fhe in contrib_pairs})
    he_handles = [
        mlines.Line2D([], [], color='#444', ls=HE_STYLE.get(f,'-'), lw=1.5,
                      label=f'ORC: {f}')
        for f in he_fluids_contrib
    ]
    # pooled front + non-contributing indicator
    pooled_h = mlines.Line2D([], [], color=cb_st['color'], lw=2.6,
                              label='Config pooled front')
    nc_h = mlines.Line2D([], [], color='#bbbbbb', lw=0.8,
                          label='Non-contributing pairs')
    ax.legend(handles=hp_handles + he_handles + [pooled_h, nc_h],
              fontsize=7, loc='lower left', ncol=2,
              framealpha=0.90, edgecolor='#cccccc', borderpad=0.6,
              columnspacing=0.8, handlelength=1.8)

    # ── subtitle: n contributing / n total ────────────────────────────────────
    n_contrib = len(contrib_pairs)
    n_total   = len({(x['fhp'], x['fhe']) for x in items})
    ax.set_title(f"{cb_st['label']}\n"
                 f"Contributing fluid pairs: {n_contrib} / {n_total}",
                 fontsize=9.5, fontweight='bold',
                 color=cb_st['color'], pad=5)

out = os.path.join(OUT_DIR, 'config_fluid_decomposition_DCA.png')
fig.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig)
print(f'Saved → {out}')
