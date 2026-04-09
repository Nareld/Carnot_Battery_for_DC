"""
DC-A | η_p2p vs η_ex 目标对的全局帕累托前沿贡献可视化  (v2: staircase + full axis)

修复：
  1. 主图坐标轴范围覆盖所有构型 pooled 前沿（不只全局前沿）
  2. 所有构型前沿改用阶梯线（staircase）绘制，正确体现包络关系
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

OBJ_X, OBJ_Y = 'eta_p2p', 'exergy_efficiency'
X_SCALE = Y_SCALE = 100   # → %

CFG_STYLE = {
    'SBVCHP_SBORC': dict(color='#2166ac', lw=2.0, label='SBVCHP + SBORC'),
    'SRVCHP_SBORC': dict(color='#1a9641', lw=2.0, label='SRVCHP + SBORC'),
    'SBVCHP_SRORC': dict(color='#d95f02', lw=2.0, label='SBVCHP + SRORC'),
    'SRVCHP_SRORC': dict(color='#b2182b', lw=2.0, label='SRVCHP + SRORC'),
}
GLOBAL_STYLE = dict(color='#333333', lw=3.2, ls='-', zorder=12)
HP_COLOR = {'R1233zd(E)': '#1f77b4', 'R245fa': '#ff7f0e', 'R600': '#2ca02c'}
HE_STYLE = {'R1234ze(E)': '-', 'R134a': '--', 'R152a': ':', 'R227ea': '-.'}

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
    """Sorted (x, y) arrays — for scatter markers."""
    s = df_nd.sort_values(OBJ_X)
    return s[OBJ_X].values * X_SCALE, s[OBJ_Y].values * Y_SCALE

def front_staircase(df_nd, x_lo=None, x_hi=None):
    """
    Extended staircase Pareto front (both objectives maximised, front monotone).
    Extends leftward from the first point at max-η_ex height,
    and rightward from the last point at min-η_ex height,
    so the full dominated region is visually bounded in BOTH objective directions.
    """
    s  = df_nd.sort_values(OBJ_X)
    xs = s[OBJ_X].values * X_SCALE
    ys = s[OBJ_Y].values * Y_SCALE

    # leftward extension at height of highest η_ex point
    sx = ([x_lo, xs[0]] if x_lo is not None else [xs[0]])
    sy = ([ys[0], ys[0]] if x_lo is not None else [ys[0]])

    # main staircase: horizontal right then vertical down
    for i in range(1, len(xs)):
        sx += [xs[i], xs[i]]
        sy += [ys[i - 1], ys[i]]

    # rightward extension at height of lowest η_ex point
    if x_hi is not None:
        sx.append(x_hi)
        sy.append(ys[-1])

    return np.array(sx), np.array(sy)

# ── load ──────────────────────────────────────────────────────────────────────
files = sorted(glob.glob(f'{RESULTS_DIR}/pareto_DC-A_*.csv'))
all_items = []
for f in files:
    stem  = os.path.basename(f).replace('pareto_DC-A_','').replace('.csv','')
    parts = stem.split('_')
    cb = parts[0]+'_'+parts[1]; fhp=parts[2]; fhe=parts[3] if len(parts)>3 else '?'
    df = pd.read_csv(f)
    df['cb_config']=cb; df['fluid_hp']=fhp; df['fluid_he']=fhe
    all_items.append({'cb': cb, 'fhp': fhp, 'fhe': fhe, 'df': df})

pool = pd.concat([x['df'] for x in all_items], ignore_index=True)

# ── global & per-config fronts ────────────────────────────────────────────────
global_nd   = nondom_2d(pool)
gx_pts, gy_pts = front_line(global_nd)

cfg_pool_nd = {}
for cb in CFG_STYLE:
    cfg_pool_nd[cb] = nondom_2d(pool[pool['cb_config']==cb])

# ── axis limits: ALL config pooled fronts ─────────────────────────────────────
all_px = np.concatenate([front_line(cfg_pool_nd[cb])[0] for cb in CFG_STYLE])
all_py = np.concatenate([front_line(cfg_pool_nd[cb])[1] for cb in CFG_STYLE])
x_lo = max(0, all_px.min() - 2);  x_hi = all_px.max() + 6
y_lo = max(0, all_py.min() - 2);  y_hi = all_py.max() + 4

print(f"Global front: {len(global_nd)} sols  "
      f"η_p2p [{gx_pts.min():.1f},{gx_pts.max():.1f}]%  "
      f"η_ex [{gy_pts.min():.1f},{gy_pts.max():.1f}]%")
for cb in CFG_STYLE:
    px,py = front_line(cfg_pool_nd[cb])
    print(f"  {cb}: η_p2p [{px.min():.1f},{px.max():.1f}]%  η_ex [{py.min():.1f},{py.max():.1f}]%")

# recompute gx,gy with correct axis limits
gx, gy = front_staircase(global_nd, x_lo=x_lo, x_hi=x_hi)

# ═══════════════════════════════════════════════════════════════════════════════
# FIGURE 1: 总图
# ═══════════════════════════════════════════════════════════════════════════════
label_pos = {
    'SBVCHP_SBORC': (0.45, -4.5,  3.0),
    'SRVCHP_SBORC': (0.55,  3.5,  2.5),
    'SBVCHP_SRORC': (0.40, -4.5, -3.5),
    'SRVCHP_SRORC': (0.85,  4.0,  0.5),
}

fig, ax = plt.subplots(figsize=(10, 7))
fig.suptitle(
    r'DC-A  |  Individual and global Pareto fronts''\n'
    r'Objectives: $\eta_{p2p}$ vs $\eta_{ex}$  '
    r'(Working point: $T_{hs}$=35°C, $T_{cs}$=5°C, $\Delta T$=30 K)',
    fontsize=10.5, fontweight='bold', y=1.01
)

# layer 0: individual fluid-pair solutions (faded scatter, no lines)
for item in all_items:
    nd = nondom_2d(item['df'])
    if len(nd) < 2: continue
    qx, qy = front_line(nd)
    ax.scatter(qx, qy, color=CFG_STYLE[item['cb']]['color'],
               s=7, alpha=0.15, edgecolors='none', zorder=2)

# layer 1: pooled config fronts (staircase)
for cb, nd_cb in cfg_pool_nd.items():
    st      = CFG_STYLE[cb]
    sx, sy  = px, py   # smooth line through sorted pooled front points
    px, py  = front_line(nd_cb)

    ax.plot(sx, sy, color=st['color'], lw=st['lw'], zorder=6,
            solid_capstyle='round')
    ax.scatter(px[-1], py[-1], color=st['color'], s=60, zorder=9,
               edgecolors='white', linewidths=1.0)
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

# layer 2: global front (staircase)
ax.plot(gx, gy, **GLOBAL_STYLE, solid_capstyle='round')
ax.text(gx_pts.max() - 0.5, gy_pts[np.argmax(gx_pts)] - 2.0,
        'Global Pareto front\n(SRVCHP+SRORC only)',
        fontsize=8, color='#333333', ha='right', va='top', fontweight='bold')

ax.axvline(gx_pts.max(), color='#888', lw=0.7, ls='--', alpha=0.35, zorder=0)
ax.axhline(gy_pts.max(), color='#888', lw=0.7, ls='--', alpha=0.35, zorder=0)
ax.text(gx_pts.max()+0.2, y_lo+0.5,
        f'max $\\eta_{{p2p}}$ = {gx_pts.max():.1f}%', ha='left', va='bottom', fontsize=7.5, color='#666')
ax.text(x_lo+0.5, gy_pts.max()+0.4,
        f'max $\\eta_{{ex}}$ = {gy_pts.max():.1f}%', ha='left', va='bottom', fontsize=7.5, color='#666')

ax.set_xlim(x_lo, x_hi); ax.set_ylim(y_lo, y_hi)
ax.set_xlabel(r'Round-trip efficiency $\eta_{p2p}$ [%]', fontsize=10)
ax.set_ylabel(r'Exergy efficiency $\eta_{ex}$ [%]', fontsize=10)
ax.xaxis.set_minor_locator(MultipleLocator(2))
ax.yaxis.set_minor_locator(MultipleLocator(1))
ax.grid(lw=0.35, alpha=0.45, which='major'); ax.grid(lw=0.15, alpha=0.2, which='minor')

handles = [mlines.Line2D([],[],color=st['color'],lw=st['lw'],label=st['label'])
           for cb,st in CFG_STYLE.items()]
handles += [mlines.Line2D([],[],color='#333333',lw=3.0,label='Global Pareto front'),
            mlines.Line2D([],[],color='#aaaaaa',lw=0.7,label='Individual fluid pairs')]
ax.legend(handles=handles, fontsize=8, loc='upper left',
          framealpha=0.9, edgecolor='#cccccc', borderpad=0.7)

plt.tight_layout()
out1 = os.path.join(OUT_DIR, 'global_pareto_DCA_etaex_main.png')
fig.savefig(out1, dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig); print(f'Saved → {out1}')

# ═══════════════════════════════════════════════════════════════════════════════
# FIGURE 2: 分解图（2×2）
# ═══════════════════════════════════════════════════════════════════════════════
fig2, axes = plt.subplots(2, 2, figsize=(14, 11), constrained_layout=True)
fig2.suptitle(
    r'DC-A  |  Fluid pair contributions within each CB configuration''\n'
    r'Color = HP fluid  ·  Marker shape = ORC fluid  ·  Thick line = config pooled front'
    r'  |  Objective: $\eta_{p2p}$ vs $\eta_{ex}$',
    fontsize=10.5, fontweight='bold'
)

for ax2, cb in zip(axes.flat, CFG_STYLE):
    cb_st   = CFG_STYLE[cb]
    items   = [x for x in all_items if x['cb'] == cb]
    nd_pool = cfg_pool_nd[cb]
    px, py  = front_line(nd_pool)
    contrib_pairs = set(zip(nd_pool['fluid_hp'], nd_pool['fluid_he']))

    # subplot axis from this config's data
    x_lo2 = max(0, px.min() - 2);  x_hi2 = px.max() + 5
    y_lo2 = max(0, py.min() - 2);  y_hi2 = py.max() + 4

    # non-contributing: light gray scatter (no lines)
    for item in items:
        if (item['fhp'], item['fhe']) in contrib_pairs: continue
        nd = nondom_2d(item['df'])
        if len(nd) < 2: continue
        qx, qy = front_line(nd)
        ax2.scatter(qx, qy, color='#cccccc', s=12, alpha=0.5,
                    edgecolors='none', zorder=2)

    # contributing: colored scatter by (HP fluid, ORC fluid), no connecting line
    for item in items:
        if (item['fhp'], item['fhe']) not in contrib_pairs: continue
        nd = nondom_2d(item['df'])
        if len(nd) < 2: continue
        qx, qy = front_line(nd)
        color  = HP_COLOR.get(item['fhp'], '#888')
        marker = {'R1234ze(E)': 'o', 'R227ea': 's',
                  'R134a': 'D', 'R152a': '^'}.get(item['fhe'], 'o')
        ax2.scatter(qx, qy, color=color, marker=marker,
                    s=28, alpha=0.82, edgecolors='white',
                    linewidths=0.5, zorder=4)

    # pooled config front: smooth line only (sorted by η_p2p, no staircase)
    ax2.plot(px, py, color=cb_st['color'], lw=2.8, zorder=8,
             solid_capstyle='round')
    ax2.scatter(px[-1], py[-1], color=cb_st['color'], s=70, zorder=10,
                edgecolors='white', linewidths=1.0)
    idx_D = np.argmax(py)
    ax2.scatter(px[idx_D], py[idx_D], color=cb_st['color'], s=70,
                marker='D', zorder=10, edgecolors='white', linewidths=1.0)

    # annotations
    best_p2p = nd_pool.loc[nd_pool[OBJ_X].idxmax()]
    best_ex  = nd_pool.loc[nd_pool[OBJ_Y].idxmax()]
    ax2.annotate(f'max $\\eta_{{p2p}}$:\n{best_p2p["fluid_hp"]}/{best_p2p["fluid_he"]}',
                 xy=(px[-1], py[-1]), xytext=(px[-1]-2.5, py[-1]+2.0),
                 fontsize=7, color=cb_st['color'], fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=cb_st['color'], lw=0.8),
                 ha='right', va='bottom',
                 bbox=dict(boxstyle='round,pad=0.2', fc='white',
                           ec=cb_st['color'], alpha=0.88, lw=0.6), zorder=11)
    ax2.annotate(f'max $\\eta_{{ex}}$:\n{best_ex["fluid_hp"]}/{best_ex["fluid_he"]}',
                 xy=(px[idx_D], py[idx_D]), xytext=(px[idx_D]+2.5, py[idx_D]-1.5),
                 fontsize=7, color=cb_st['color'], fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color=cb_st['color'], lw=0.8),
                 ha='left', va='top',
                 bbox=dict(boxstyle='round,pad=0.2', fc='white',
                           ec=cb_st['color'], alpha=0.88, lw=0.6), zorder=11)

    ax2.set_xlim(x_lo2, x_hi2); ax2.set_ylim(y_lo2, y_hi2)
    ax2.set_xlabel(r'$\eta_{p2p}$ [%]', fontsize=9)
    ax2.set_ylabel(r'$\eta_{ex}$ [%]', fontsize=9)
    ax2.xaxis.set_minor_locator(MultipleLocator(2))
    ax2.yaxis.set_minor_locator(MultipleLocator(1))
    ax2.grid(lw=0.35, alpha=0.45, which='major')
    ax2.grid(lw=0.15, alpha=0.2,  which='minor')
    n_c = len(contrib_pairs); n_t = len({(x['fhp'],x['fhe']) for x in items})
    ax2.set_title(f"{cb_st['label']}\nContributing fluid pairs: {n_c} / {n_t}",
                  fontsize=9.5, fontweight='bold', color=cb_st['color'], pad=5)

    hp_f = sorted({fhp for fhp,_ in contrib_pairs})
    he_f = sorted({fhe for _,fhe in contrib_pairs})
    MARKERS = {'R1234ze(E)': 'o', 'R227ea': 's', 'R134a': 'D', 'R152a': '^'}
    hp_h = [mlines.Line2D([],[],color=HP_COLOR[f],marker='o',linestyle='none',
                           markersize=6, label=f'HP: {f}') for f in hp_f]
    he_h = [mlines.Line2D([],[],color='#555',marker=MARKERS.get(f,'o'),linestyle='none',
                           markersize=6, label=f'ORC: {f}') for f in he_f]
    pool_h = mlines.Line2D([],[],color=cb_st['color'],lw=2.8,label='Config pooled front')
    nc_h   = mlines.Line2D([],[],color='#cccccc',marker='o',linestyle='none',
                            markersize=5, label='Non-contributing pairs')
    ax2.legend(handles=hp_h+he_h+[pool_h,nc_h],
               fontsize=7, loc='upper right', ncol=2,
               framealpha=0.90, edgecolor='#cccccc', borderpad=0.6,
               columnspacing=0.8, handlelength=1.5)

out2 = os.path.join(OUT_DIR, 'config_fluid_decomposition_DCA_etaex.png')
fig2.savefig(out2, dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig2); print(f'Saved → {out2}')
