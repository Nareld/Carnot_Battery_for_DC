"""
六工况冲突强度演化图（Figure A）
展示三个目标上限 + η_p2p–η_ex 前沿规模随工况 ΔT 的演化
2×2 面板布局：
  [0,0] η_p2p 上限 vs ΔT
  [0,1] e_th 上限 vs ΔT
  [1,0] η_ex 上限 vs ΔT
  [1,1] η_p2p–η_ex 前沿规模（解数 + 跨度）vs ΔT
区分冬季（T_cs=5°C）和夏季（T_cs=25°C）两组
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
from matplotlib.ticker import MultipleLocator

OUT = '/Users/a1234/Carnot_Battery_for_DC/pure_deap_nsga/plots/global_pareto/six_wp_evolution.png'

# ── 数据 ──────────────────────────────────────────────────────────────────────
# 按 ΔT 升序，冬/夏分组标记
DATA = [
    # label  ΔT   T_cs  η_p2p_max  e_th_max  η_ex_max  n_front  span_pp  season
    ('DC-B',  15,  25,   40.2,      34.05,    32.8,     9,       3.5,    'summer'),
    ('DC-A',  30,   5,   56.9,      34.32,    36.3,    20,      12.0,    'winter'),
    ('DC-D',  30,  25,   50.8,      39.61,    31.8,    29,      11.5,    'summer'),
    ('DC-C',  45,   5,   78.6,      39.93,    34.5,    35,      27.1,    'winter'),
    ('DC-F',  50,  25,   80.6,      45.14,    28.6,    29,      30.0,    'summer'),
    ('DC-E',  60,   5,  100.0,      45.51,    30.4,    27,      39.8,    'winter'),
]

labels   = [d[0] for d in DATA]
dTs      = np.array([d[1] for d in DATA])
seasons  = [d[8] for d in DATA]
p2p_max  = np.array([d[3] for d in DATA])
eth_max  = np.array([d[4] for d in DATA])
ex_max   = np.array([d[5] for d in DATA])
n_front  = np.array([d[6] for d in DATA])
span_pp  = np.array([d[7] for d in DATA])

# 冬/夏分离
w_idx = [i for i,s in enumerate(seasons) if s == 'winter']
s_idx = [i for i,s in enumerate(seasons) if s == 'summer']

# 颜色
C_WIN = '#1a6faf'   # 蓝 — 冬季
C_SUM = '#d62728'   # 红 — 夏季
C_BOX_WIN = '#d0e8f8'
C_BOX_SUM = '#fde0d0'
MS = 9  # marker size

# ── 图形布局 ──────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(13, 10), constrained_layout=True)
fig.suptitle(
    'Six DC working points: Pareto conflict intensity evolution with $\\Delta T$\n'
    r'$\bullet$ Winter ($T_{cs}$=5°C)  $\bullet$ Summer ($T_{cs}$=25°C)',
    fontsize=12, fontweight='bold'
)

# ── helper: 绘制一个面板 ──────────────────────────────────────────────────────
def plot_panel(ax, y_win, y_sum, ylabel, ylim=None,
               ytick_major=None, ytick_minor=None,
               hline=None, hline_label=None,
               annotate_100=False):
    """绘制冬/夏两条折线 + 标注工况名。"""
    # 冬季线
    ax.plot(dTs[w_idx], y_win, 'o-', color=C_WIN, lw=2.0, ms=MS,
            markerfacecolor='white', markeredgewidth=2.0, zorder=5)
    # 夏季线
    ax.plot(dTs[s_idx], y_sum, 's-', color=C_SUM, lw=2.0, ms=MS,
            markerfacecolor='white', markeredgewidth=2.0, zorder=5)

    # 工况标注
    # 每工况的 (水平偏移, 垂直偏移) 微调，避免重叠
    annot_offsets = {
        'DC-B': ( 0,  3.5), 'DC-A': (-3,  3.5), 'DC-D': ( 3, -4.5),
        'DC-C': (-3,  3.5), 'DC-F': ( 3, -4.5), 'DC-E': ( 0,  3.5),
    }
    for i, (lbl, dT, season) in enumerate(zip(labels, dTs, seasons)):
        yval = y_win[w_idx.index(i)] if season == 'winter' else y_sum[s_idx.index(i)]
        col  = C_WIN if season == 'winter' else C_SUM
        dx, dy = annot_offsets.get(lbl, (0, 3.5))
        ax.annotate(lbl, xy=(dT, yval), xytext=(dT + dx, yval + dy),
                    fontsize=8.5, color=col, fontweight='bold', ha='center',
                    arrowprops=dict(arrowstyle='-', color=col, lw=0.6, alpha=0.5),
                    bbox=dict(boxstyle='round,pad=0.2', fc='white',
                              ec=col, alpha=0.85, lw=0.7))

    if hline is not None:
        ax.axhline(hline, color='#666', lw=0.8, ls='--', alpha=0.5)
        if hline_label:
            ax.text(62, hline + 0.5, hline_label, fontsize=7.5, color='#666',
                    ha='right', va='bottom')

    if annotate_100:
        ax.axhline(100, color='#cc3300', lw=1.0, ls=':', alpha=0.7)
        ax.text(61.5, 101, r'$\eta_{p2p}$=100%', fontsize=8, color='#cc3300',
                ha='right', va='bottom', style='italic')

    ax.set_xlabel(r'Working point temperature difference $\Delta T$ [K]', fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_xlim(8, 66)
    if ylim: ax.set_ylim(*ylim)
    ax.xaxis.set_major_locator(MultipleLocator(15))
    ax.xaxis.set_minor_locator(MultipleLocator(5))
    if ytick_major: ax.yaxis.set_major_locator(MultipleLocator(ytick_major))
    if ytick_minor: ax.yaxis.set_minor_locator(MultipleLocator(ytick_minor))
    ax.grid(lw=0.35, alpha=0.45, which='major')
    ax.grid(lw=0.15, alpha=0.20, which='minor')

# ── 面板 (0,0): η_p2p 上限 ────────────────────────────────────────────────────
ax = axes[0, 0]
plot_panel(
    ax,
    y_win = p2p_max[w_idx],
    y_sum = p2p_max[s_idx],
    ylabel = r'Max round-trip efficiency $\eta_{p2p,\max}$ [%]',
    ylim   = (30, 110),
    ytick_major=20, ytick_minor=5,
    annotate_100=True
)
# 趋势标注：同 ΔT 比较
ax.annotate('', xy=(30, 56.9), xytext=(30, 50.8),
            arrowprops=dict(arrowstyle='<->', color='#555', lw=1.0))
ax.text(31.5, 53.5, r'$\Delta T_{cs}$ effect', fontsize=7.5, color='#555',
        ha='left', va='center')
ax.set_title(r'(a)  $\eta_{p2p,\max}$: governed by $\Delta T$',
             fontsize=10, fontweight='bold', pad=6)

# ── 面板 (0,1): e_th 上限 ─────────────────────────────────────────────────────
ax = axes[0, 1]
plot_panel(
    ax,
    y_win  = eth_max[w_idx],
    y_sum  = eth_max[s_idx],
    ylabel = r'Max thermal energy density $e_{th,\max}$ [kWh m$^{-3}$]',
    ylim   = (30, 50),
    ytick_major=5, ytick_minor=1,
    hline=34.5,  hline_label=r'$\Delta T_{sp}^{max}$=60K plateau'
)
# 阶梯标注
ax.axhspan(33, 35.5, alpha=0.10, color=C_WIN)
ax.axhspan(43.5, 47,  alpha=0.10, color='#888')
ax.text(35, 34.3, r'$\Delta T_{sp}^{max}$=60 K', fontsize=8, color='#555',
        ha='center', va='bottom', style='italic')
ax.text(35, 45.8, r'$\Delta T_{sp}^{max}$=80 K', fontsize=8, color='#555',
        ha='center', va='bottom', style='italic')
ax.set_title(r'(b)  $e_{th,\max}$: governed by $\Delta T_{sp}^{max}$ (not $\Delta T$)',
             fontsize=10, fontweight='bold', pad=6)

# ── 面板 (1,0): η_ex 上限 ─────────────────────────────────────────────────────
ax = axes[1, 0]
plot_panel(
    ax,
    y_win  = ex_max[w_idx],
    y_sum  = ex_max[s_idx],
    ylabel = r'Max exergy efficiency $\eta_{ex,\max}$ [%]',
    ylim   = (25, 42),
    ytick_major=5, ytick_minor=1,
)
ax.text(34, 38.5,
        'Non-monotonic with $\\Delta T$\n'
        r'($T_{cs}$ co-determines $\eta_{ex,\max}$)',
        fontsize=8, color='#555', ha='center', va='bottom',
        bbox=dict(boxstyle='round,pad=0.3', fc='#f5f5f5', ec='#aaa', alpha=0.9))
ax.set_title(r'(c)  $\eta_{ex,\max}$: non-monotonic, jointly governed by $\Delta T$ and $T_{cs}$',
             fontsize=10, fontweight='bold', pad=6)

# ── 面板 (1,1): η_p2p–η_ex 前沿规模（解数 + 跨度）────────────────────────────
ax = axes[1, 1]
ax2 = ax.twinx()

# 左轴：解数
ax.plot(dTs[w_idx], n_front[w_idx], 'o-', color=C_WIN, lw=2.0, ms=MS,
        markerfacecolor='white', markeredgewidth=2.0, zorder=5, label='Winter (n)')
ax.plot(dTs[s_idx], n_front[s_idx], 's-', color=C_SUM, lw=2.0, ms=MS,
        markerfacecolor='white', markeredgewidth=2.0, zorder=5, label='Summer (n)')

# 右轴：跨度（虚线，同色）
ax2.plot(dTs[w_idx], span_pp[w_idx], 'o--', color=C_WIN, lw=1.5, ms=7,
         alpha=0.6, zorder=4, label='Winter (span)')
ax2.plot(dTs[s_idx], span_pp[s_idx], 's--', color=C_SUM, lw=1.5, ms=7,
         alpha=0.6, zorder=4, label='Summer (span)')

# 标注每个点（固定偏移避免 ΔT=30K 处重叠）
annot_n = {
    'DC-B': ( 0, 3), 'DC-A': (-3, 3), 'DC-D': ( 3,-5),
    'DC-C': ( 0, 3), 'DC-F': ( 4,-5), 'DC-E': ( 0, 3),
}
for i, (lbl, dT, s) in enumerate(zip(labels, dTs, seasons)):
    n   = n_front[i]
    col = C_WIN if s == 'winter' else C_SUM
    dx, dy = annot_n.get(lbl, (0, 3))
    ax.annotate(lbl, xy=(dT, n), xytext=(dT + dx, n + dy),
                fontsize=8, color=col, fontweight='bold', ha='center',
                bbox=dict(boxstyle='round,pad=0.2', fc='white',
                          ec=col, alpha=0.85, lw=0.7))

# DC-E 四构型特殊标注
ax.annotate('All 4 configs\nenter front',
            xy=(60, 27), xytext=(52, 32),
            fontsize=7.5, color=C_WIN, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color=C_WIN, lw=0.9),
            bbox=dict(boxstyle='round,pad=0.3', fc='white',
                      ec=C_WIN, alpha=0.9, lw=0.8))

ax.set_xlabel(r'Working point temperature difference $\Delta T$ [K]', fontsize=10)
ax.set_ylabel(r'$\eta_{p2p}$–$\eta_{ex}$ front size  [# solutions]', fontsize=10)
ax2.set_ylabel(r'$\eta_{p2p}$–$\eta_{ex}$ front span  [pp $\eta_{p2p}$]',
               fontsize=10, color='#555')
ax.set_xlim(8, 66)
ax.set_ylim(0, 45)
ax2.set_ylim(0, 50)
ax.xaxis.set_major_locator(MultipleLocator(15))
ax.xaxis.set_minor_locator(MultipleLocator(5))
ax.yaxis.set_major_locator(MultipleLocator(10))
ax2.yaxis.set_major_locator(MultipleLocator(10))
ax.grid(lw=0.35, alpha=0.45, which='major')
ax.grid(lw=0.15, alpha=0.20, which='minor')

ax.set_title(r'(d)  $\eta_{p2p}$–$\eta_{ex}$ conflict intensity vs $\Delta T$',
             fontsize=10, fontweight='bold', pad=6)

# 合并图例（面板 d）
h1 = mlines.Line2D([], [], color=C_WIN, marker='o', ms=7,
                   markerfacecolor='white', markeredgewidth=1.8,
                   lw=2.0, label='Winter group ($T_{cs}$=5°C)')
h2 = mlines.Line2D([], [], color=C_SUM, marker='s', ms=7,
                   markerfacecolor='white', markeredgewidth=1.8,
                   lw=2.0, label='Summer group ($T_{cs}$=25°C)')
h3 = mlines.Line2D([], [], color='#555', lw=1.5, ls='-',
                   label='Solid = front size (left axis)')
h4 = mlines.Line2D([], [], color='#555', lw=1.5, ls='--',
                   label='Dashed = front span (right axis)')
ax.legend(handles=[h1, h2, h3, h4], fontsize=8, loc='upper left',
          framealpha=0.92, edgecolor='#ccc', borderpad=0.7)

# 全局图例（前三个面板共用）
for ax_top in [axes[0,0], axes[0,1], axes[1,0]]:
    h_w = mlines.Line2D([], [], color=C_WIN, marker='o', ms=7,
                        markerfacecolor='white', markeredgewidth=1.8,
                        lw=2.0, label=r'Winter ($T_{cs}$=5°C)')
    h_s = mlines.Line2D([], [], color=C_SUM, marker='s', ms=7,
                        markerfacecolor='white', markeredgewidth=1.8,
                        lw=2.0, label=r'Summer ($T_{cs}$=25°C)')
    ax_top.legend(handles=[h_w, h_s], fontsize=8.5, loc='upper left',
                  framealpha=0.92, edgecolor='#ccc', borderpad=0.7)

fig.savefig(OUT, dpi=150, bbox_inches='tight', facecolor='white')
plt.close(fig)
print(f'Saved → {OUT}')
