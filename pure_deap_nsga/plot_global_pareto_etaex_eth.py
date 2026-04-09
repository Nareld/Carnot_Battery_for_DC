"""
DC-A | η_ex vs e_th 目标对的全局帕累托前沿贡献可视化

两张图：
  1. 总图：全局前沿 + 各构型 pooled 前沿（Laterre Fig.4.3 风格）
  2. 分解图：各构型内不同流体对的贡献（2×2，散点 + 平滑包络线）
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

OBJ_X = 'exergy_efficiency'       # x 轴：η_ex
OBJ_Y = 'energy_density_thermal'  # y 轴：e_th
X_SCALE = 100   # → %
Y_SCALE = 1     # already kWh/m³

CFG_STYLE = {
    'SBVCHP_SBORC': dict(color='#2166ac', lw=2.0, label='SBVCHP + SBORC'),
    'SRVCHP_SBORC': dict(color='#1a9641', lw=2.0, label='SRVCHP + SBORC'),
    'SBVCHP_SRORC': dict(color='#d95f02', lw=2.0, label='SBVCHP + SRORC'),
    'SRVCHP_SRORC': dict(color='#b2182b', lw=2.0, label='SRVCHP + SRORC'),
}
GLOBAL_STYLE = dict(color='#333333', lw=3.2, ls='-', zorder=12)
HP_COLOR = {'R1233zd(E)': '#1f77b4', 'R245fa': '#ff7f0e', 'R600': '#2ca02c'}
ORC_MARKER = {'R1234ze(E)': 'o', 'R227ea': 's', 'R134a': 'D', 'R152a': '^'}

# ── helpers ───────────────────────────────────────────────────────────────────
def nondom_2d(df):
    F = df[[OBJ_X, OBJ_Y]].values
    n = len(F); is_nd = np.ones(n, dtype=bool)
    for i in range(n):
        dom = np.all(F >= F[i], axis=1) & np.any(F > F[i], axis=1)
        dom[i] = False
        if dom.any(): is_nd[i] = False
    return df[is_nd].copy()

def front_line(df_nd):
    """Sorted (x, y) arrays — smooth Pareto front line."""
    s = df_nd.sort_values(OBJ_X)
    return s[OBJ_X].values * X_SCALE, s[OBJ_Y].values * Y_SCALE

# ── load ──────────────────────────────────────────────────────────────────────
files = sorted(glob.glob(f'{RESULTS_DIR}/pareto_DC-A_*.csv'))
all_items = []
for f in files:
    stem  = os.path.basename(f).replace('pareto_DC-A_','').replace('.csv','')
    parts = stem.split('_')
    cb = parts[0]+'_'+parts[1]; fhp=parts[2]; fhe=parts[3] if len(parts)>3 else '?'
    df = pd.read_csv(f)
    df['cb_config']=cb; df['fluid_hp']=fhp; df['fluid_he']=fhe
    all_items.append({'cb':cb,'fhp':fhp,'fhe':fhe,'df':df})

pool = pd.concat([x['df'] for x in all_items], ignore_index=True)

# ── global & per-config fronts ────────────────────────────────────────────────
global_nd = nondom_2d(pool)
gx_pts, gy_pts = front_line(global_nd)

cfg_pool_nd = {}
for cb in CFG_STYLE:
    cfg_pool_nd[cb] = nondom_2d(pool[pool['cb_config']==cb])

# ── axis limits from ALL config pooled fronts ─────────────────────────────────
all_px = np.concatenate([front_line(cfg_pool_nd[cb])[0] for cb in CFG_STYLE])
all_py = np.concatenate([front_line(cfg_pool_nd[cb])[1] for cb in CFG_STYLE])
x_lo = max(0, all_px.min()-1); x_hi = all_px.max()+5
y_lo = max(0, all_py.min()-0.5); y_hi = all_py.max()+2

print(f"Global (η_ex, e_th) front: {len(global_nd)} sols  "
      f"η_ex [{gx_pts.min():.1f},{gx_pts.max():.1f}]%  "
      f"e_th [{gy_pts.min():.2f},{gy_pts.max():.2f}]")
for cb in CFG_STYLE:
    px,py = front_line(cfg_pool_nd[cb])
    contrib = set(zip(cfg_pool_nd[cb]['fluid_hp'], cfg_pool_nd[cb]['fluid_he']))
    print(f"  {cb}: η_ex [{px.min():.1f},{px.max():.1f}]%  "
          f"e_th [{py.min():.2f},{py.max():.2f}]  n={len(cfg_pool_nd[cb])}")

# ═══════════════════════════════════════════════════════════════════════════════
# FIGURE 1: 总图
# ═══════════════════════════════════════════════════════════════════════════════
label_pos = {                       # (x_pct along front, dx, dy)
    'SBVCHP_SBORC': (0.30, -3.0, -3.0),
    'SRVCHP_SBORC': (0.55,  3.5,  2.5),
    'SBVCHP_SRORC': (0.50, -4.0,  2.5),
    'SRVCHP_SRORC': (0.80,  3.5, -2.0),
}

fig, ax = plt.subplots(figsize=(10, 7))
fig.suptitle(
    r'DC-A  |  Individual and global Pareto fronts''\n'
    r'Objectives: $\eta_{ex}$ vs $e_{th}$  '
    r'(Working point: $T_{hs}$=35°C, $T_{cs}$=5°C, $\Delta T$=30 K)',
    fontsize=10.5, fontweight='bold', y=1.01
)

# layer 0: individual fluid-pair solutions (faded scatter)
for item in all_items:
    nd = nondom_2d(item['df'])
    if len(nd) < 2: continue
    qx, qy = front_line(nd)
    ax.scatter(qx, qy, color=CFG_STYLE[item['cb']]['color'],
               s=7, alpha=0.12, edgecolors='none', zorder=2)

# layer 1: per-config pooled fronts (smooth line)
for cb, nd_cb in cfg_pool_nd.items():
    st = CFG_STYLE[cb]
    px, py = front_line(nd_cb)

    ax.plot(px, py, color=st['color'], lw=st['lw'], zorder=6,
            solid_capstyle='round')
    # max η_ex marker (circle, rightmost)
    ax.scatter(px[-1], py[-1], color=st['color'], s=60, zorder=9,
               edgecolors='white', linewidths=1.0)
    # max e_th marker (diamond, topmost)
    idx_D = np.argmax(py)
    ax.scatter(px[idx_D], py[idx_D], color=st['color'], s=60,
               marker='D', zorder=9, edgecolors='white', linewidths=1.0)

    pct, ox, oy = label_pos[cb]
    x_tgt = px[0] + pct * (px[-1] - px[0])
    idx   = np.argmin(np.abs(px - x_tgt))
    hp_lbl  = 'SBVCHP' if 'SBVCHP' in cb else 'SRVCHP'
    orc_lbl = 'SBORC'  if 'SBORC'  in cb else 'SRORC'
    ax.annotate(f'{hp_lbl}+{orc_lbl}', xy=(px[idx], py[idx]),
                xytext=(px[idx]+ox, py[idx]+oy),
                fontsize=8.5, color=st['color'], fontweight='bold',
                arrowprops=dict(arrowstyle='->', color=st['color'],
                                lw=0.9, alpha=0.85, shrinkA=2, shrinkB=3),
                ha='center', va='center',
                bbox=dict(boxstyle='round,pad=0.3', fc='white',
                          ec=st['color'], alpha=0.92, lw=0.8), zorder=11)

# layer 2: global front
ax.plot(gx_pts, gy_pts, **GLOBAL_STYLE, solid_capstyle='round')
ax.text(gx_pts.max()-0.5, gy_pts[np.argmax(gx_pts)]-1.5,
        'Global Pareto front',
        fontsize=8.5, color='#333333', ha='right', va='top', fontweight='bold')

# reference lines
ax.axvline(gx_pts.max(), color='#888', lw=0.7, ls='--', alpha=0.35)
ax.axhline(gy_pts.max(), color='#888', lw=0.7, ls='--', alpha=0.35)
ax.text(gx_pts.max()+0.2, y_lo+0.3,
        f'max $\\eta_{{ex}}$ = {gx_pts.max():.1f}%', ha='left', va='bottom',
        fontsize=7.5, color='#666')
ax.text(x_lo+0.3, gy_pts.max()+0.3,
        f'max $e_{{th}}$ = {gy_pts.max():.1f} kWh m$^{{-3}}$',
        ha='left', va='bottom', fontsize=7.5, color='#666')

ax.set_xlim(x_lo, x_hi); ax.set_ylim(y_lo, y_hi)
ax.set_xlabel(r'Exergy efficiency $\eta_{ex}$ [%]', fontsize=10)
ax.set_ylabel(r'Thermal energy density $e_{th}$  [kWh m$^{-3}$]', fontsize=10)
ax.xaxis.set_minor_locator(MultipleLocator(2))
ax.yaxis.set_minor_locator(MultipleLocator(1))
ax.grid(lw=0.35, alpha=0.45, which='major')
ax.grid(lw=0.15, alpha=0.2,  which='minor')

handles = [mlines.Line2D([],[],color=st['color'],lw=st['lw'],label=st['label'])
           for cb,st in CFG_STYLE.items()]
handles += [mlines.Line2D([],[],color='#333333',lw=3.0,label='Global Pareto front'),
            mlines.Line2D([],[],color='#aaaaaa',marker='o',linestyle='none',
                          markersize=4,label='Individual fluid pairs')]
ax.legend(handles=handles, fontsize=8, loc='upper right',
          framealpha=0.9, edgecolor='#cccccc', borderpad=0.7)

plt.tight_layout()
out1 = os.path.join(OUT_DIR, 'global_pareto_DCA_etaex_eth_main.png')
fig.savefig(out1, dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig); print(f'\nSaved → {out1}')

# ═══════════════════════════════════════════════════════════════════════════════
# FIGURE 2: 分解图（2×2）
# ═══════════════════════════════════════════════════════════════════════════════
fig2, axes = plt.subplots(2, 2, figsize=(14, 11), constrained_layout=True)
fig2.suptitle(
    r'DC-A  |  Fluid pair contributions within each CB configuration''\n'
    r'Color = HP fluid  ·  Marker shape = ORC fluid  ·  Thick line = config pooled front'
    r'  |  Objective: $\eta_{ex}$ vs $e_{th}$',
    fontsize=10.5, fontweight='bold'
)

for ax2, cb in zip(axes.flat, CFG_STYLE):
    cb_st   = CFG_STYLE[cb]
    items   = [x for x in all_items if x['cb'] == cb]
    nd_pool = cfg_pool_nd[cb]
    px, py  = front_line(nd_pool)
    contrib_pairs = set(zip(nd_pool['fluid_hp'], nd_pool['fluid_he']))

    x_lo2 = max(0, px.min()-1); x_hi2 = px.max()+4
    y_lo2 = max(0, py.min()-0.5); y_hi2 = py.max()+2.5

    # non-contributing: gray scatter
    for item in items:
        if (item['fhp'], item['fhe']) in contrib_pairs: continue
        nd = nondom_2d(item['df'])
        if len(nd) < 2: continue
        qx, qy = front_line(nd)
        ax2.scatter(qx, qy, color='#cccccc', s=12, alpha=0.5,
                    edgecolors='none', zorder=2)

    # contributing: colored scatter (color=HP fluid, marker=ORC fluid)
    for item in items:
        if (item['fhp'], item['fhe']) not in contrib_pairs: continue
        nd = nondom_2d(item['df'])
        if len(nd) < 2: continue
        qx, qy = front_line(nd)
        color  = HP_COLOR.get(item['fhp'], '#888')
        marker = ORC_MARKER.get(item['fhe'], 'o')
        ax2.scatter(qx, qy, color=color, marker=marker,
                    s=28, alpha=0.82, edgecolors='white',
                    linewidths=0.5, zorder=4)

    # pooled config front: smooth line
    ax2.plot(px, py, color=cb_st['color'], lw=2.8, zorder=8,
             solid_capstyle='round')
    ax2.scatter(px[-1], py[-1], color=cb_st['color'], s=70, zorder=10,
                edgecolors='white', linewidths=1.0)
    idx_D = np.argmax(py)
    ax2.scatter(px[idx_D], py[idx_D], color=cb_st['color'], s=70,
                marker='D', zorder=10, edgecolors='white', linewidths=1.0)

    # annotations: best fluid pair at each extreme
    best_ex  = nd_pool.loc[nd_pool[OBJ_X].idxmax()]
    best_eth = nd_pool.loc[nd_pool[OBJ_Y].idxmax()]
    ax2.annotate(f'max $\\eta_{{ex}}$:\n{best_ex["fluid_hp"]}/{best_ex["fluid_he"]}',
                 xy=(px[-1], py[-1]),
                 xytext=(px[-1]-2.0, py[-1]+1.5),
                 fontsize=7, color=cb_st['color'], fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=cb_st['color'], lw=0.8),
                 ha='right', va='bottom',
                 bbox=dict(boxstyle='round,pad=0.2', fc='white',
                           ec=cb_st['color'], alpha=0.88, lw=0.6), zorder=11)
    ax2.annotate(f'max $e_{{th}}$:\n{best_eth["fluid_hp"]}/{best_eth["fluid_he"]}',
                 xy=(px[idx_D], py[idx_D]),
                 xytext=(px[idx_D]+2.0, py[idx_D]-1.0),
                 fontsize=7, color=cb_st['color'], fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=cb_st['color'], lw=0.8),
                 ha='left', va='top',
                 bbox=dict(boxstyle='round,pad=0.2', fc='white',
                           ec=cb_st['color'], alpha=0.88, lw=0.6), zorder=11)

    ax2.set_xlim(x_lo2, x_hi2); ax2.set_ylim(y_lo2, y_hi2)
    ax2.set_xlabel(r'$\eta_{ex}$ [%]', fontsize=9)
    ax2.set_ylabel(r'$e_{th}$ [kWh m$^{-3}$]', fontsize=9)
    ax2.xaxis.set_minor_locator(MultipleLocator(2))
    ax2.yaxis.set_minor_locator(MultipleLocator(1))
    ax2.grid(lw=0.35, alpha=0.45, which='major')
    ax2.grid(lw=0.15, alpha=0.2,  which='minor')
    n_c = len(contrib_pairs); n_t = len({(x['fhp'],x['fhe']) for x in items})
    ax2.set_title(f"{cb_st['label']}\nContributing fluid pairs: {n_c} / {n_t}",
                  fontsize=9.5, fontweight='bold', color=cb_st['color'], pad=5)

    # legend
    hp_f = sorted({fhp for fhp,_ in contrib_pairs})
    he_f = sorted({fhe for _,fhe in contrib_pairs})
    hp_h = [mlines.Line2D([],[],color=HP_COLOR[f],marker='o',linestyle='none',
                           markersize=6,label=f'HP: {f}') for f in hp_f]
    he_h = [mlines.Line2D([],[],color='#555',marker=ORC_MARKER.get(f,'o'),
                           linestyle='none',markersize=6,label=f'ORC: {f}') for f in he_f]
    pool_h = mlines.Line2D([],[],color=cb_st['color'],lw=2.8,label='Config pooled front')
    nc_h   = mlines.Line2D([],[],color='#cccccc',marker='o',linestyle='none',
                            markersize=5,label='Non-contributing pairs')
    ax2.legend(handles=hp_h+he_h+[pool_h,nc_h],
               fontsize=7, loc='upper right', ncol=2,
               framealpha=0.90, edgecolor='#cccccc', borderpad=0.6,
               columnspacing=0.8, handlelength=1.5)

out2 = os.path.join(OUT_DIR, 'config_fluid_decomposition_DCA_etaex_eth.png')
fig2.savefig(out2, dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig2); print(f'Saved → {out2}')
