"""
DC-A | η_ex vs e_th — Laterre Fig.4.3 风格前沿贡献图

结构（仿照 plot_global_pareto_laterre.py）：
  - 铺底：各流体对个别 2D 前沿（淡化同构型色细线）
  - 彩色粗线：各 CB 构型的汇总 pooled 2D 前沿，标注最优流体对
  - 粗黑线：全局 2D 帕累托前沿
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

OBJ_X = 'exergy_efficiency'       # → % on plot
OBJ_Y = 'energy_density_thermal'  # kWh/m³

CFG_STYLE = {
    'SBVCHP_SBORC': dict(color='#2166ac', lw=2.0, label='SBVCHP + SBORC'),
    'SRVCHP_SBORC': dict(color='#1a9641', lw=2.0, label='SRVCHP + SBORC'),
    'SBVCHP_SRORC': dict(color='#d95f02', lw=2.0, label='SBVCHP + SRORC'),
    'SRVCHP_SRORC': dict(color='#b2182b', lw=2.0, label='SRVCHP + SRORC'),
}
GLOBAL_STYLE = dict(color='#333333', lw=3.2, zorder=12)

# ── helpers ───────────────────────────────────────────────────────────────────
def nondom_2d(df):
    F = df[[OBJ_X, OBJ_Y]].values
    n = len(F); is_nd = np.ones(n, dtype=bool)
    for i in range(n):
        dom = np.all(F >= F[i], axis=1) & np.any(F > F[i], axis=1)
        dom[i] = False
        if dom.any(): is_nd[i] = False
    return df[is_nd].copy()

def front_xy(df_nd):
    """Sorted (x%, y) for smooth line."""
    s = df_nd.sort_values(OBJ_X)
    return s[OBJ_X].values * 100, s[OBJ_Y].values

def hv2d(df_nd, rx, ry):
    """2D hypervolume indicator."""
    s  = df_nd.sort_values(OBJ_X, ascending=False)
    xs = s[OBJ_X].values * 100
    ys = s[OBJ_Y].values
    hv = 0.0; yp = ry
    for xi, yi in zip(xs, ys):
        if xi > rx and yi > ry:
            hv += (xi - rx) * max(yi - yp, 0)
            yp = max(yp, yi)
    return hv

# ── load ──────────────────────────────────────────────────────────────────────
files = sorted(glob.glob(f'{RESULTS_DIR}/pareto_DC-A_*.csv'))
all_items = []
for f in files:
    stem = os.path.basename(f).replace('pareto_DC-A_','').replace('.csv','')
    parts = stem.split('_')
    cb = parts[0]+'_'+parts[1]; fhp=parts[2]; fhe=parts[3] if len(parts)>3 else '?'
    df = pd.read_csv(f)
    df['cb_config']=cb; df['fluid_hp']=fhp; df['fluid_he']=fhe
    all_items.append({'cb':cb,'fhp':fhp,'fhe':fhe,'df':df})

pool = pd.concat([x['df'] for x in all_items], ignore_index=True)

# ── fronts ────────────────────────────────────────────────────────────────────
global_nd = nondom_2d(pool)
gx, gy    = front_xy(global_nd)

cfg_pool_nd = {cb: nondom_2d(pool[pool['cb_config']==cb]) for cb in CFG_STYLE}

# axis from all pooled fronts
all_x = np.concatenate([front_xy(cfg_pool_nd[cb])[0] for cb in CFG_STYLE])
all_y = np.concatenate([front_xy(cfg_pool_nd[cb])[1] for cb in CFG_STYLE])
x_lo = max(0, all_x.min()-1); x_hi = gx.max()+5
y_lo = max(0, all_y.min()-0.5); y_hi = gy.max()+2

# best fluid pair per config (by 2D hypervolume)
best_fluid = {}
ref_x, ref_y = gx.min()-1, gy.min()-1
for item in all_items:
    nd = nondom_2d(item['df'])
    hv = hv2d(nd, ref_x, ref_y)
    cb = item['cb']
    if cb not in best_fluid or hv > best_fluid[cb]['hv']:
        best_fluid[cb] = {'item': item, 'hv': hv, 'nd': nd}

print("Best fluid pair per config (by HV):")
for cb, v in best_fluid.items():
    it = v['item']
    xs, ys = front_xy(v['nd'])
    print(f"  {cb}: {it['fhp']}/{it['fhe']}  "
          f"η_ex_max={xs.max():.1f}%  e_th_max={ys.max():.2f}")

# label positions: (x_pct along pooled front, dx, dy)
label_pos = {
    'SBVCHP_SBORC': (0.25, -4.0, -3.5),
    'SRVCHP_SBORC': (0.60,  3.5,  2.5),
    'SBVCHP_SRORC': (0.40, -4.5,  2.5),
    'SRVCHP_SRORC': (0.80,  3.5, -2.5),
}

# ── plot ──────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 7))
fig.suptitle(
    r'DC-A  |  Individual and global Pareto fronts''\n'
    r'Objectives: $\eta_{ex}$ vs $e_{th}$  '
    r'(Working point: $T_{hs}$=35°C, $T_{cs}$=5°C, $\Delta T$=30 K)',
    fontsize=10.5, fontweight='bold', y=1.01
)

# layer 0: individual fluid-pair fronts (faded colored thin lines)
for item in all_items:
    nd = nondom_2d(item['df'])
    if len(nd) < 2: continue
    xs, ys = front_xy(nd)
    ax.plot(xs, ys, color=CFG_STYLE[item['cb']]['color'],
            lw=0.55, alpha=0.18, solid_capstyle='round', zorder=2)

# layer 1: per-config pooled fronts
for cb, nd_cb in cfg_pool_nd.items():
    st = CFG_STYLE[cb]
    px, py = front_xy(nd_cb)

    ax.plot(px, py, color=st['color'], lw=st['lw'], zorder=6,
            solid_capstyle='round')

    # endpoint markers
    ax.scatter(px[-1], py[-1], color=st['color'], s=60, zorder=9,
               edgecolors='white', linewidths=1.0)            # max η_ex
    ax.scatter(px[0], py[0], color=st['color'], s=60,
               marker='D', zorder=9, edgecolors='white', linewidths=1.0)  # max e_th

    # label at characteristic point
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
ax.plot(gx, gy, **GLOBAL_STYLE, solid_capstyle='round')
# label near the high-η_ex end
ax.text(gx.max()-0.5, gy[np.argmax(gx)]-1.5,
        'Global Pareto front', fontsize=8.5, color='#333333',
        ha='right', va='top', fontweight='bold')

# reference lines
ax.axvline(gx.max(), color='#888', lw=0.7, ls='--', alpha=0.35)
ax.axhline(gy.max(), color='#888', lw=0.7, ls='--', alpha=0.35)
ax.text(gx.max()+0.2, y_lo+0.3,
        f'max $\\eta_{{ex}}$ = {gx.max():.1f}%',
        ha='left', va='bottom', fontsize=7.5, color='#666')
ax.text(x_lo+0.3, gy.max()+0.3,
        f'max $e_{{th}}$ = {gy.max():.1f} kWh m$^{{-3}}$',
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
            mlines.Line2D([],[],color='#aaaaaa',lw=0.8,label='Individual fluid pairs')]
ax.legend(handles=handles, fontsize=8, loc='lower left',
          framealpha=0.9, edgecolor='#cccccc', borderpad=0.7)

plt.tight_layout()
out = os.path.join(OUT_DIR, 'global_pareto_DCA_etaex_eth_laterre.png')
fig.savefig(out, dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig)
print(f'\nSaved → {out}')
