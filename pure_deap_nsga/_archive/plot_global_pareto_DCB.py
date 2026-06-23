"""
DC-B | 三目标两两全局帕累托前沿可视化（6 张图）
对应三组目标对：
  Pair 1: η_p2p  vs e_th
  Pair 2: η_p2p  vs η_ex
  Pair 3: η_ex   vs e_th
每对输出：
  ① _main.png  — 总图（各构型 pooled 前沿 + 全局前沿）
  ② _decomp.png — 分解图（2×2，各构型内流体对贡献）
"""

import glob, os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
from matplotlib.ticker import MultipleLocator
from scipy.stats import spearmanr

RESULTS_DIR = '/Users/a1234/Carnot_Battery_for_DC/pure_deap_nsga/results'
OUT_DIR     = '/Users/a1234/Carnot_Battery_for_DC/pure_deap_nsga/plots/global_pareto'
os.makedirs(OUT_DIR, exist_ok=True)

# ── 工况参数 ──────────────────────────────────────────────────────────────────
WP_LABEL = r'DC-B  |  Air-cooled (Summer)  $T_{hs}$=40°C, $T_{cs}$=25°C, $\Delta T$=15 K'

# ── 构型样式 ──────────────────────────────────────────────────────────────────
CFG_STYLE = {
    'SBVCHP_SBORC': dict(color='#2166ac', lw=2.0, label='SBVCHP + SBORC'),
    'SRVCHP_SBORC': dict(color='#1a9641', lw=2.0, label='SRVCHP + SBORC'),
    'SBVCHP_SRORC': dict(color='#d95f02', lw=2.0, label='SBVCHP + SRORC'),
    'SRVCHP_SRORC': dict(color='#b2182b', lw=2.0, label='SRVCHP + SRORC'),
}
GLOBAL_STYLE = dict(color='#111111', lw=3.2, ls='-', zorder=12)
HP_COLOR  = {'R1233zd(E)': '#1f77b4', 'R245fa': '#ff7f0e', 'R600': '#2ca02c'}
ORC_LS    = {'R1234ze(E)': '-', 'R227ea': '-.', 'R134a': '--', 'R152a': ':'}
ORC_MK    = {'R1234ze(E)': 'o', 'R227ea': 's', 'R134a': 'D', 'R152a': '^'}

# ── 三组目标对配置 ────────────────────────────────────────────────────────────
PAIRS = [
    dict(
        xc='eta_p2p', yc='energy_density_thermal',
        xn=r'$\eta_{p2p}$', yn=r'$e_{th}$',
        xlabel=r'Round-trip efficiency $\eta_{p2p}$ [%]',
        ylabel=r'Thermal energy density $e_{th}$  [kWh m$^{-3}$]',
        xscale=100, yscale=1,
        xunit='%', yunit='kWh/m³',
        tag='p2p_eth',
        title_pair=r'$\eta_{p2p}$ vs $e_{th}$',
        label_pos={
            'SBVCHP_SBORC': (0.20, -3.0, -2.5),
            'SRVCHP_SBORC': (0.30,  3.5,  2.5),
            'SBVCHP_SRORC': (0.50,  3.5, -2.5),
            'SRVCHP_SRORC': (0.75,  3.5,  2.5),
        },
    ),
    dict(
        xc='eta_p2p', yc='exergy_efficiency',
        xn=r'$\eta_{p2p}$', yn=r'$\eta_{ex}$',
        xlabel=r'Round-trip efficiency $\eta_{p2p}$ [%]',
        ylabel=r'Exergy efficiency $\eta_{ex}$ [%]',
        xscale=100, yscale=100,
        xunit='%', yunit='%',
        tag='p2p_etaex',
        title_pair=r'$\eta_{p2p}$ vs $\eta_{ex}$',
        label_pos={
            'SBVCHP_SBORC': (0.20, -3.0, -2.5),
            'SRVCHP_SBORC': (0.35,  3.5,  2.5),
            'SBVCHP_SRORC': (0.55, -3.5,  2.5),
            'SRVCHP_SRORC': (0.70,  3.5, -2.5),
        },
    ),
    dict(
        xc='exergy_efficiency', yc='energy_density_thermal',
        xn=r'$\eta_{ex}$', yn=r'$e_{th}$',
        xlabel=r'Exergy efficiency $\eta_{ex}$ [%]',
        ylabel=r'Thermal energy density $e_{th}$  [kWh m$^{-3}$]',
        xscale=100, yscale=1,
        xunit='%', yunit='kWh/m³',
        tag='etaex_eth',
        title_pair=r'$\eta_{ex}$ vs $e_{th}$',
        label_pos={
            'SBVCHP_SBORC': (0.20, -3.5, -2.5),
            'SRVCHP_SBORC': (0.35,  3.5,  2.5),
            'SBVCHP_SRORC': (0.55, -3.5,  2.5),
            'SRVCHP_SRORC': (0.75,  3.5, -2.5),
        },
    ),
]

# ── helpers ───────────────────────────────────────────────────────────────────
def nondom_2d(df, xc, yc):
    F = df[[xc, yc]].values; n = len(F); nd = np.ones(n, bool)
    for i in range(n):
        dom = np.all(F >= F[i], axis=1) & np.any(F > F[i], axis=1)
        dom[i] = False
        if dom.any(): nd[i] = False
    return df[nd].copy()

def front_xy(df_nd, xc, yc, xs, ys):
    s = df_nd.sort_values(xc)
    return s[xc].values * xs, s[yc].values * ys

def hv2d(df_nd, xc, yc, rx, ry):
    s = df_nd.sort_values(xc, ascending=False)
    xs = s[xc].values * 100; ys = s[yc].values
    hv = 0.0; yp = ry
    for xi, yi in zip(xs, ys):
        if xi > rx and yi > ry:
            hv += (xi - rx) * max(yi - yp, 0)
            yp = max(yp, yi)
    return hv

# ── 数据加载 ──────────────────────────────────────────────────────────────────
files = sorted(glob.glob(f'{RESULTS_DIR}/pareto_DC-B_*.csv'))
all_items = []
for f in files:
    stem  = os.path.basename(f).replace('pareto_DC-B_', '').replace('.csv', '')
    parts = stem.split('_')
    cb = parts[0] + '_' + parts[1]
    fhp = parts[2]
    fhe = parts[3] if len(parts) > 3 else '?'
    df  = pd.read_csv(f)
    df['cb_config'] = cb; df['fluid_hp'] = fhp; df['fluid_he'] = fhe
    all_items.append({'cb': cb, 'fhp': fhp, 'fhe': fhe, 'df': df})

pool = pd.concat([x['df'] for x in all_items], ignore_index=True)
print(f'DC-B pool: {len(pool)} solutions, {len(files)} files')

# ══════════════════════════════════════════════════════════════════════════════
# 对每组目标对生成两张图
# ══════════════════════════════════════════════════════════════════════════════
for P in PAIRS:
    xc, yc   = P['xc'], P['yc']
    xs, ys   = P['xscale'], P['yscale']
    tag      = P['tag']
    lpos     = P['label_pos']

    # ── 计算各层前沿 ──────────────────────────────────────────────────────────
    global_nd  = nondom_2d(pool, xc, yc)
    gx, gy     = front_xy(global_nd, xc, yc, xs, ys)
    r_g, p_g   = spearmanr(global_nd[xc], global_nd[yc])

    cfg_pool_nd = {}
    for cb in CFG_STYLE:
        cfg_pool_nd[cb] = nondom_2d(pool[pool['cb_config'] == cb], xc, yc)

    # 轴范围
    all_px = np.concatenate([front_xy(cfg_pool_nd[cb], xc, yc, xs, ys)[0]
                              for cb in CFG_STYLE if len(cfg_pool_nd[cb]) > 0])
    all_py = np.concatenate([front_xy(cfg_pool_nd[cb], xc, yc, xs, ys)[1]
                              for cb in CFG_STYLE if len(cfg_pool_nd[cb]) > 0])
    x_lo = max(0, all_px.min() - 1); x_hi = gx.max() + 5
    y_lo = max(0, all_py.min() - 0.5); y_hi = gy.max() + 2

    n_global = len(global_nd)
    contrib_cfg = {cb: (global_nd['cb_config'] == cb).sum() for cb in CFG_STYLE}

    print(f'\n[{tag}] global front: n={n_global}, r={r_g:.3f}')
    print(f'  config counts: {contrib_cfg}')

    # ── 最优流体对（按 HV） ───────────────────────────────────────────────────
    best_fluid = {}
    ref_x_hv = gx.min() - 1; ref_y_hv = gy.min() - 1
    for item in all_items:
        nd_i = nondom_2d(item['df'], xc, yc)
        if len(nd_i) == 0: continue
        hv = hv2d(nd_i, xc, yc, ref_x_hv, ref_y_hv)
        cb = item['cb']
        if cb not in best_fluid or hv > best_fluid[cb]['hv']:
            best_fluid[cb] = {'item': item, 'hv': hv, 'nd': nd_i}

    # ══════════════════════════════════════════════════════════════════════════
    # FIGURE 1: 总图（Laterre Fig.4.3 风格）
    # ══════════════════════════════════════════════════════════════════════════
    fig, ax = plt.subplots(figsize=(10, 7))
    fig.suptitle(
        f'DC-B  |  Individual and global Pareto fronts\n'
        f'Objectives: {P["title_pair"]}  '
        r'(Air-cooled Summer, $T_{hs}$=40°C, $T_{cs}$=25°C, $\Delta T$=15 K)',
        fontsize=10.5, fontweight='bold', y=1.01
    )

    # 层 0：个别流体对（淡化细线）
    for item in all_items:
        nd_i = nondom_2d(item['df'], xc, yc)
        if len(nd_i) < 2: continue
        qx, qy = front_xy(nd_i, xc, yc, xs, ys)
        # 稀疏前沿（η_p2p–η_ex）用步进函数，其余用折线
        if n_global < 30:
            ax.step(qx, qy, where='post',
                    color=CFG_STYLE[item['cb']]['color'],
                    lw=0.5, alpha=0.15, zorder=2)
        else:
            ax.plot(qx, qy, color=CFG_STYLE[item['cb']]['color'],
                    lw=0.55, alpha=0.18, solid_capstyle='round', zorder=2)

    # 层 1：构型 pooled 前沿
    for cb, nd_cb in cfg_pool_nd.items():
        if len(nd_cb) < 2: continue
        st = CFG_STYLE[cb]
        px, py = front_xy(nd_cb, xc, yc, xs, ys)
        n_c = contrib_cfg[cb]
        lw_eff = st['lw'] * (1.4 if n_c > 0 else 0.8)
        ls_eff = '-' if n_c > 0 else '--'

        ax.plot(px, py, color=st['color'], lw=lw_eff, ls=ls_eff, zorder=6,
                solid_capstyle='round')
        # max x 端点
        ax.scatter(px[-1], py[-1], color=st['color'], s=60, zorder=9,
                   edgecolors='white', linewidths=1.0)
        # max y 端点
        idx_D = np.argmax(py)
        ax.scatter(px[idx_D], py[idx_D], color=st['color'], s=60,
                   marker='D', zorder=9, edgecolors='white', linewidths=1.0)

        pct, ox, oy = lpos[cb]
        x_tgt = px[0] + pct * (px[-1] - px[0])
        idx   = np.argmin(np.abs(px - x_tgt))
        hp_l  = 'SBVCHP' if 'SBVCHP' in cb else 'SRVCHP'
        orc_l = 'SBORC'  if 'SBORC'  in cb else 'SRORC'
        # 标注中含 global 贡献解数
        lbl = f'{hp_l}+{orc_l}\n(n={n_c}/{n_global})'
        ax.annotate(lbl, xy=(px[idx], py[idx]),
                    xytext=(px[idx] + ox, py[idx] + oy),
                    fontsize=8, color=st['color'], fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=st['color'],
                                   lw=0.9, alpha=0.85, shrinkA=2, shrinkB=3),
                    ha='center', va='center',
                    bbox=dict(boxstyle='round,pad=0.3', fc='white',
                              ec=st['color'], alpha=0.92, lw=0.8), zorder=11)

    # 层 2：全局前沿
    if n_global < 30:
        ax.step(gx, gy, where='post', **GLOBAL_STYLE)
        # 背景散点：效率走廊的全部解
        eff_mask = pool['dT_st_sp'] <= 25
        sub = pool[eff_mask]
        ax.scatter(sub[xc] * xs, sub[yc] * ys,
                   s=8, color='#444', alpha=0.12, zorder=1,
                   edgecolors='none', label='_nolegend_')
    else:
        ax.plot(gx, gy, **GLOBAL_STYLE, solid_capstyle='round')

    ax.text(gx.max() - 0.3, gy[np.argmax(gx)] - 1.5,
            'Global Pareto front', fontsize=8.5, color='#111',
            ha='right', va='top', fontweight='bold')

    # 参考线 + 数值标注
    ax.axvline(gx.max(), color='#888', lw=0.7, ls='--', alpha=0.35)
    ax.axhline(gy.max(), color='#888', lw=0.7, ls='--', alpha=0.35)
    unit_x = P['xunit']; unit_y = P['yunit']
    ax.text(gx.max() + 0.2, y_lo + 0.3,
            f'max={gx.max():.1f} {unit_x}', ha='left', va='bottom',
            fontsize=7.5, color='#666')
    ax.text(x_lo + 0.3, gy.max() + 0.3,
            f'max={gy.max():.2f} {unit_y}', ha='left', va='bottom',
            fontsize=7.5, color='#666')

    # 右上角统计注释
    stat_txt = (f'Global front: n={n_global}\n'
                f'Spearman r = {r_g:.3f}')
    ax.text(0.98, 0.02, stat_txt, transform=ax.transAxes,
            fontsize=8, ha='right', va='bottom',
            bbox=dict(boxstyle='round,pad=0.4', fc='#f8f8f8',
                      ec='#cccccc', alpha=0.9))

    ax.set_xlim(x_lo, x_hi); ax.set_ylim(y_lo, y_hi)
    ax.set_xlabel(P['xlabel'], fontsize=10)
    ax.set_ylabel(P['ylabel'], fontsize=10)
    ax.xaxis.set_minor_locator(MultipleLocator(2))
    ax.yaxis.set_minor_locator(MultipleLocator(1))
    ax.grid(lw=0.35, alpha=0.45, which='major')
    ax.grid(lw=0.15, alpha=0.20, which='minor')

    handles = [mlines.Line2D([], [], color=st['color'], lw=st['lw'],
                             label=st['label'])
               for cb, st in CFG_STYLE.items()]
    handles += [mlines.Line2D([], [], color='#111', lw=3.0,
                              label='Global Pareto front'),
                mlines.Line2D([], [], color='#aaa',
                              marker='o' if n_global >= 30 else None,
                              lw=0.6 if n_global < 30 else 0,
                              markersize=4, linestyle='none' if n_global >= 30 else '-',
                              label='Individual fluid pairs')]
    ax.legend(handles=handles, fontsize=8, loc='upper right',
              framealpha=0.9, edgecolor='#ccc', borderpad=0.7)

    plt.tight_layout()
    out1 = os.path.join(OUT_DIR, f'global_pareto_DCB_{tag}_main.png')
    fig.savefig(out1, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  Saved → {out1}')

    # ══════════════════════════════════════════════════════════════════════════
    # FIGURE 2: 分解图（2×2）
    # ══════════════════════════════════════════════════════════════════════════
    fig2, axes = plt.subplots(2, 2, figsize=(14, 11), constrained_layout=True)
    fig2.suptitle(
        f'DC-B  |  Fluid pair contributions within each CB configuration\n'
        f'Color = HP fluid  ·  Line style = ORC fluid  ·  Thick line = config pooled front'
        f'  |  Objectives: {P["title_pair"]}',
        fontsize=10.5, fontweight='bold'
    )

    for ax2, cb in zip(axes.flat, CFG_STYLE):
        cb_st    = CFG_STYLE[cb]
        items_cb = [x for x in all_items if x['cb'] == cb]
        nd_pool  = cfg_pool_nd[cb]
        n_contrib_global = contrib_cfg[cb]

        if len(nd_pool) < 2:
            ax2.set_title(f"{cb_st['label']}\n(no solutions)", fontsize=9.5,
                          color='#aaa')
            ax2.axis('off')
            continue

        px, py = front_xy(nd_pool, xc, yc, xs, ys)
        contrib_pairs = set(zip(nd_pool['fluid_hp'], nd_pool['fluid_he']))

        x_lo2 = max(0, px.min() - 1); x_hi2 = px.max() + 4
        y_lo2 = max(0, py.min() - 0.5); y_hi2 = py.max() + 2.5

        # 叠加全局前沿（灰色虚线，帮助对比支配关系）
        ax2.plot(gx, gy, color='#888', lw=1.2, ls='--', alpha=0.5,
                 zorder=1, label='Global Pareto front')

        # 非贡献流体对（灰线）
        for item in items_cb:
            if (item['fhp'], item['fhe']) in contrib_pairs: continue
            nd_i = nondom_2d(item['df'], xc, yc)
            if len(nd_i) < 2: continue
            qx, qy = front_xy(nd_i, xc, yc, xs, ys)
            ax2.plot(qx, qy, color='#cccccc', lw=0.6, alpha=0.5,
                     solid_capstyle='round', zorder=2)

        # 贡献流体对（彩色）
        for item in items_cb:
            if (item['fhp'], item['fhe']) not in contrib_pairs: continue
            nd_i = nondom_2d(item['df'], xc, yc)
            if len(nd_i) < 2: continue
            qx, qy = front_xy(nd_i, xc, yc, xs, ys)
            color = HP_COLOR.get(item['fhp'], '#888')
            ls    = ORC_LS.get(item['fhe'], '-')
            ax2.plot(qx, qy, color=color, ls=ls, lw=1.4, alpha=0.85,
                     solid_capstyle='round', zorder=4)
            ax2.scatter(qx[-1], qy[-1], color=color, s=22, zorder=5,
                        edgecolors='white', linewidths=0.5)

        # 构型 pooled 前沿（粗线）
        ax2.plot(px, py, color=cb_st['color'], lw=2.8, zorder=8,
                 solid_capstyle='round')
        ax2.scatter(px[-1], py[-1], color=cb_st['color'], s=70, zorder=10,
                    edgecolors='white', linewidths=1.0)
        idx_D = np.argmax(py)
        ax2.scatter(px[idx_D], py[idx_D], color=cb_st['color'], s=70,
                    marker='D', zorder=10, edgecolors='white', linewidths=1.0)

        # 两端最优流体对标注
        best_ex_row  = nd_pool.loc[nd_pool[xc].idxmax()]
        best_eth_row = nd_pool.loc[nd_pool[yc].idxmax()]
        ax2.annotate(
            f'max {P["xn"]}:\n{best_ex_row["fluid_hp"]}/{best_ex_row["fluid_he"]}',
            xy=(px[-1], py[-1]),
            xytext=(px[-1] - 2.0, py[-1] + 1.5),
            fontsize=7, color=cb_st['color'], fontweight='bold',
            arrowprops=dict(arrowstyle='->', color=cb_st['color'], lw=0.8),
            ha='right', va='bottom',
            bbox=dict(boxstyle='round,pad=0.2', fc='white',
                      ec=cb_st['color'], alpha=0.88, lw=0.6), zorder=11)
        ax2.annotate(
            f'max {P["yn"]}:\n{best_eth_row["fluid_hp"]}/{best_eth_row["fluid_he"]}',
            xy=(px[idx_D], py[idx_D]),
            xytext=(px[idx_D] + 2.0, py[idx_D] - 1.0),
            fontsize=7, color=cb_st['color'], fontweight='bold',
            arrowprops=dict(arrowstyle='->', color=cb_st['color'], lw=0.8),
            ha='left', va='top',
            bbox=dict(boxstyle='round,pad=0.2', fc='white',
                      ec=cb_st['color'], alpha=0.88, lw=0.6), zorder=11)

        ax2.set_xlim(x_lo2, x_hi2); ax2.set_ylim(y_lo2, y_hi2)
        ax2.set_xlabel(P['xlabel'], fontsize=9)
        ax2.set_ylabel(P['ylabel'], fontsize=9)
        ax2.xaxis.set_minor_locator(MultipleLocator(2))
        ax2.yaxis.set_minor_locator(MultipleLocator(1))
        ax2.grid(lw=0.35, alpha=0.45, which='major')
        ax2.grid(lw=0.15, alpha=0.20, which='minor')

        n_c = len(contrib_pairs)
        n_t = len({(x['fhp'], x['fhe']) for x in items_cb})
        ax2.set_title(
            f"{cb_st['label']}\n"
            f"Contributing fluid pairs: {n_c}/{n_t}  |  "
            f"Global front: {n_contrib_global}/{n_global} pts",
            fontsize=9.0, fontweight='bold', color=cb_st['color'], pad=5)

        # 图例
        hp_f = sorted({fhp for fhp, _ in contrib_pairs})
        he_f = sorted({fhe for _, fhe in contrib_pairs})
        hp_h = [mlines.Line2D([], [], color=HP_COLOR[f], lw=1.8,
                               label=f'HP: {f}') for f in hp_f if f in HP_COLOR]
        he_h = [mlines.Line2D([], [], color='#555', ls=ORC_LS.get(f, '-'),
                               lw=1.5, label=f'ORC: {f}') for f in he_f]
        pool_h = mlines.Line2D([], [], color=cb_st['color'], lw=2.8,
                                label='Config pooled front')
        gf_h   = mlines.Line2D([], [], color='#888', lw=1.2, ls='--',
                                label='Global front (ref)')
        nc_h   = mlines.Line2D([], [], color='#ccc', lw=0.8,
                                label='Non-contributing pairs')
        ax2.legend(handles=hp_h + he_h + [pool_h, gf_h, nc_h],
                   fontsize=7, loc='upper right', ncol=2,
                   framealpha=0.90, edgecolor='#ccc', borderpad=0.6,
                   columnspacing=0.8, handlelength=1.8)

    out2 = os.path.join(OUT_DIR, f'config_fluid_decomposition_DCB_{tag}.png')
    fig2.savefig(out2, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig2)
    print(f'  Saved → {out2}')

print('\nDone. All 6 figures saved.')
