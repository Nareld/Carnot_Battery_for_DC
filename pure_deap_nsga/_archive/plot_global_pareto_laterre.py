"""
仿照 Laterre Fig.4.3 风格（单图版）：
  - 全局 2D 帕累托前沿（粗灰线）作为背景参照
  - 四种 CB 构型用四种颜色区分
  - 每种构型中"最贴近全局前沿"的流体对用全色实线并标注工质名
  - 同构型其他流体对用淡化同色线铺底
目标轴：x = η_p2p [%]，y = e_th [kWh m⁻³]
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
X_SCALE = 100

# ── palette ────────────────────────────────────────────────────────────────────
CFG_STYLE = {
    'SBVCHP_SBORC': dict(color='#2166ac', lw=2.0, label='SBVCHP + SBORC'),
    'SRVCHP_SBORC': dict(color='#1a9641', lw=2.0, label='SRVCHP + SBORC'),
    'SBVCHP_SRORC': dict(color='#d95f02', lw=2.0, label='SBVCHP + SRORC'),
    'SRVCHP_SRORC': dict(color='#b2182b', lw=2.0, label='SRVCHP + SRORC'),
}
GLOBAL_STYLE = dict(color='#333333', lw=3.2, ls='-', zorder=12, label='Global Pareto front')

# ── helpers ────────────────────────────────────────────────────────────────────
def nondom_2d(df, obj_x=OBJ_X, obj_y=OBJ_Y):
    F = df[[obj_x, obj_y]].values
    n = len(F)
    is_nd = np.ones(n, dtype=bool)
    for i in range(n):
        dominates_i = np.all(F >= F[i], axis=1) & np.any(F > F[i], axis=1)
        dominates_i[i] = False
        if dominates_i.any():
            is_nd[i] = False
    return df[is_nd].copy()

def front_line(df_nd):
    s = df_nd.sort_values(OBJ_X)
    return s[OBJ_X].values * X_SCALE, s[OBJ_Y].values

def hypervolume_2d(df_nd, ref_x=0.0, ref_y=0.0):
    """2D hypervolume indicator: area dominated by the front above ref point."""
    s = df_nd.sort_values(OBJ_X, ascending=False)
    xs = s[OBJ_X].values * X_SCALE
    ys = s[OBJ_Y].values
    hv = 0.0
    y_prev = ref_y
    for xi, yi in zip(xs, ys):
        if xi > ref_x and yi > ref_y:
            hv += (xi - ref_x) * max(yi - y_prev, 0)
            y_prev = max(y_prev, yi)
    return hv

# ── load all DC-A files ────────────────────────────────────────────────────────
files = sorted(glob.glob(f'{RESULTS_DIR}/pareto_DC-A_*.csv'))
all_items = []
for f in files:
    stem  = os.path.basename(f).replace('pareto_DC-A_','').replace('.csv','')
    parts = stem.split('_')
    cb    = parts[0] + '_' + parts[1]
    fhp   = parts[2]
    fhe   = parts[3] if len(parts) > 3 else '?'
    df    = pd.read_csv(f)
    df['cb_config'] = cb; df['fluid_hp'] = fhp; df['fluid_he'] = fhe
    all_items.append({'cb': cb, 'fhp': fhp, 'fhe': fhe, 'df': df})

pool = pd.concat([x['df'] for x in all_items], ignore_index=True)

# ── global 2D Pareto front ─────────────────────────────────────────────────────
global_nd = nondom_2d(pool)
gx, gy    = front_line(global_nd)
ref_x, ref_y = gx.min() - 1, gy.min() - 1
print(f'Global 2D front: {len(global_nd)} solutions  '
      f'η_p2p [{gx.min():.1f}, {gx.max():.1f}]%  '
      f'e_th [{gy.min():.2f}, {gy.max():.2f}] kWh/m³')

# ── per-CB-config POOLED 2D Pareto fronts ─────────────────────────────────────
# (non-dominated across all fluid pairs within each config)
cfg_pool_nd = {}
for cb in CFG_STYLE:
    df_cb = pool[pool['cb_config'] == cb]
    nd_cb = nondom_2d(df_cb)
    cfg_pool_nd[cb] = nd_cb
    xs, ys = front_line(nd_cb)
    print(f'{cb}: pooled front {len(nd_cb)} pts  '
          f'η_p2p_max={xs.max():.1f}%  e_th_max={ys.max():.2f}')

# For labelling: best fluid pair at each extreme per config
def best_at_extreme(df_nd_config, extreme='p2p'):
    """Return (fhp, fhe) of the fluid pair achieving the extreme point."""
    if extreme == 'p2p':
        row = df_nd_config.loc[df_nd_config[OBJ_X].idxmax()]
    else:
        row = df_nd_config.loc[df_nd_config[OBJ_Y].idxmax()]
    return row['fluid_hp'], row['fluid_he']

# ── single plot ────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(9, 7))
fig.suptitle(
    'DC-A  |  Individual and global Pareto fronts\n'
    r'Objectives: $\eta_{p2p}$ vs $e_{th}$  '
    r'(Working point: $T_{hs}$=35°C, $T_{cs}$=5°C, $\Delta T$=30 K)',
    fontsize=10.5, fontweight='bold', y=1.01
)

# ── layer 0: faded fluid-pair lines per CB config ─────────────────────────────
for item in all_items:
    cb     = item['cb']
    color  = CFG_STYLE[cb]['color']
    nd     = nondom_2d(item['df'])
    if len(nd) < 2: continue
    xs, ys = front_line(nd)
    ax.plot(xs, ys, color=color, lw=0.6, alpha=0.18,
            solid_capstyle='round', zorder=2)

# ── layer 1: pooled config fronts (prominent colored lines) ──────────────────
label_pos = {               # (x_pct along front, dx_offset, dy_offset)
    'SBVCHP_SBORC': (0.35, -7.0, -4.5),
    'SRVCHP_SBORC': (0.25,  2.5,  4.5),
    'SBVCHP_SRORC': (0.22, -7.0, -4.0),
    'SRVCHP_SRORC': (0.90,  5.0,  0.5),
}

for cb, nd_cb in cfg_pool_nd.items():
    st     = CFG_STYLE[cb]
    xs, ys = front_line(nd_cb)

    # pooled config front
    ax.plot(xs, ys, color=st['color'], lw=st['lw'], ls='-',
            zorder=6, solid_capstyle='round')

    # endpoint dots
    ax.scatter(xs[-1], ys[-1], color=st['color'], s=60, zorder=9,
               edgecolors='white', linewidths=1.0)
    idx_max_e = np.argmax(ys)
    ax.scatter(xs[idx_max_e], ys[idx_max_e], color=st['color'], s=60,
               marker='D', zorder=9, edgecolors='white', linewidths=1.0)

    # label: config name + fluid pair achieving max η_p2p
    fhp_p2p, fhe_p2p = best_at_extreme(nd_cb, 'p2p')
    hp_lbl  = 'SBVCHP' if 'SBVCHP' in cb else 'SRVCHP'
    orc_lbl = 'SBORC'  if 'SBORC'  in cb else 'SRORC'

    pct, ox, oy = label_pos[cb]
    x_range = xs[-1] - xs[0]
    x_tgt   = xs[0] + pct * x_range
    idx_ann = np.argmin(np.abs(xs - x_tgt))
    x_ann, y_ann = xs[idx_ann], ys[idx_ann]

    ax.annotate(
        f'{hp_lbl}+{orc_lbl}',
        xy=(x_ann, y_ann),
        xytext=(x_ann + ox, y_ann + oy),
        fontsize=8.5, color=st['color'], fontweight='bold',
        arrowprops=dict(arrowstyle='->', color=st['color'],
                        lw=0.9, alpha=0.85, shrinkA=2, shrinkB=3),
        ha='center', va='center',
        bbox=dict(boxstyle='round,pad=0.3', fc='white',
                  ec=st['color'], alpha=0.92, lw=0.8),
        zorder=11
    )

# ── layer 2: global 2D Pareto front ───────────────────────────────────────────
ax.plot(gx, gy, **GLOBAL_STYLE, solid_capstyle='round')
# label at upper-right
ax.text(gx.max() - 0.4, gy[np.argmax(gx)] + 1.8,
        'Global Pareto front', fontsize=8.5, color='#333333',
        ha='right', va='bottom', fontweight='bold', zorder=13)

# ── reference lines ────────────────────────────────────────────────────────────
ax.axvline(gx.max(), color='#888', lw=0.7, ls='--', alpha=0.35, zorder=0)
ax.axhline(gy.max(), color='#888', lw=0.7, ls='--', alpha=0.35, zorder=0)
ax.text(gx.max() + 0.3, gy.min() + 0.3,
        f'max $\\eta_{{p2p}}$ = {gx.max():.1f}%',
        ha='left', va='bottom', fontsize=7.5, color='#666')
ax.text(ref_x + 2.5, gy.max() + 0.4,
        f'max $e_{{th}}$ = {gy.max():.1f} kWh m$^{{-3}}$',
        ha='left', va='bottom', fontsize=7.5, color='#666')

# ── axes & legend ──────────────────────────────────────────────────────────────
x_lo = max(0, gx.min() - 2)
x_hi = gx.max() + 6
y_lo = max(0, gy.min() - 1)
y_hi = gy.max() + 2.5
ax.set_xlim(x_lo, x_hi)
ax.set_ylim(y_lo, y_hi)
ax.set_xlabel(r'Round-trip efficiency $\eta_{p2p}$ [%]', fontsize=10)
ax.set_ylabel(r'Thermal energy density $e_{th}$  [kWh m$^{-3}$]', fontsize=10)
ax.xaxis.set_minor_locator(MultipleLocator(2))
ax.yaxis.set_minor_locator(MultipleLocator(1))
ax.grid(lw=0.35, alpha=0.45, which='major')
ax.grid(lw=0.15, alpha=0.2,  which='minor')

handles = []
for cb, st in CFG_STYLE.items():
    handles.append(mlines.Line2D([], [], color=st['color'], lw=st['lw'],
                                 label=st['label']))
handles.append(mlines.Line2D([], [], color='#333333', lw=3.0,
                              label='Global Pareto front'))
handles.append(mlines.Line2D([], [], color='#aaaaaa', lw=0.7,
                              label='Individual fluid pairs (same config)'))
ax.legend(handles=handles, fontsize=8, loc='lower left',
          framealpha=0.9, edgecolor='#cccccc', borderpad=0.7)

plt.tight_layout()
out = os.path.join(OUT_DIR, 'global_pareto_DCA_laterre_style.png')
fig.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig)
print(f'\nSaved → {out}')
