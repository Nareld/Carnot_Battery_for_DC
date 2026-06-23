"""
通用模板：DC-E / DC-F 三目标两两全局帕累托前沿可视化（6 张图）
调用方式：WP_KEY = 'DC-E' 或 'DC-F'
"""

import glob, os, sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
from matplotlib.ticker import MultipleLocator
from scipy.stats import spearmanr

# ── 工况配置 ──────────────────────────────────────────────────────────────────
WP_KEY = sys.argv[1] if len(sys.argv) > 1 else 'DC-E'
WP_TAG = WP_KEY.replace('-', '')

WP_META = {
    'DC-E': dict(sub=r'High-perf liquid (Winter), $T_{hs}$=65°C, $T_{cs}$=5°C, $\Delta T$=60 K'),
    'DC-F': dict(sub=r'High-perf liquid (Summer), $T_{hs}$=75°C, $T_{cs}$=25°C, $\Delta T$=50 K'),
}
WP_SUB = WP_META[WP_KEY]['sub']

RESULTS_DIR = '/Users/a1234/Carnot_Battery_for_DC/pure_deap_nsga/results'
OUT_DIR     = '/Users/a1234/Carnot_Battery_for_DC/pure_deap_nsga/plots/global_pareto'
os.makedirs(OUT_DIR, exist_ok=True)

CFG_STYLE = {
    'SBVCHP_SBORC': dict(color='#2166ac', lw=2.0, label='SBVCHP + SBORC'),
    'SRVCHP_SBORC': dict(color='#1a9641', lw=2.0, label='SRVCHP + SBORC'),
    'SBVCHP_SRORC': dict(color='#d95f02', lw=2.0, label='SBVCHP + SRORC'),
    'SRVCHP_SRORC': dict(color='#b2182b', lw=2.0, label='SRVCHP + SRORC'),
}
GLOBAL_STYLE = dict(color='#111111', lw=3.2, ls='-', zorder=12)
HP_COLOR = {'R1233zd(E)': '#1f77b4', 'R245fa': '#ff7f0e', 'R600': '#2ca02c'}
ORC_LS   = {'R1234ze(E)': '-', 'R227ea': '-.', 'R134a': '--', 'R152a': ':'}

PAIRS = [
    dict(xc='eta_p2p', yc='energy_density_thermal',
         xlabel=r'Round-trip efficiency $\eta_{p2p}$ [%]',
         ylabel=r'Thermal energy density $e_{th}$  [kWh m$^{-3}$]',
         xscale=100, yscale=1, xunit='%', yunit='kWh/m³',
         tag='p2p_eth', title_pair=r'$\eta_{p2p}$ vs $e_{th}$',
         xn=r'$\eta_{p2p}$', yn=r'$e_{th}$',
         label_pos={
             'SBVCHP_SBORC': (0.15, -5.0, -3.0),
             'SRVCHP_SBORC': (0.32,  5.0,  3.0),
             'SBVCHP_SRORC': (0.55,  5.0, -3.0),
             'SRVCHP_SRORC': (0.75,  5.0,  3.0),
         }),
    dict(xc='eta_p2p', yc='exergy_efficiency',
         xlabel=r'Round-trip efficiency $\eta_{p2p}$ [%]',
         ylabel=r'Exergy efficiency $\eta_{ex}$ [%]',
         xscale=100, yscale=100, xunit='%', yunit='%',
         tag='p2p_etaex', title_pair=r'$\eta_{p2p}$ vs $\eta_{ex}$',
         xn=r'$\eta_{p2p}$', yn=r'$\eta_{ex}$',
         label_pos={
             'SBVCHP_SBORC': (0.15, -5.0, -2.5),
             'SRVCHP_SBORC': (0.40,  5.0,  2.5),
             'SBVCHP_SRORC': (0.55, -5.0,  2.5),
             'SRVCHP_SRORC': (0.78,  5.0, -2.5),
         }),
    dict(xc='exergy_efficiency', yc='energy_density_thermal',
         xlabel=r'Exergy efficiency $\eta_{ex}$ [%]',
         ylabel=r'Thermal energy density $e_{th}$  [kWh m$^{-3}$]',
         xscale=100, yscale=1, xunit='%', yunit='kWh/m³',
         tag='etaex_eth', title_pair=r'$\eta_{ex}$ vs $e_{th}$',
         xn=r'$\eta_{ex}$', yn=r'$e_{th}$',
         label_pos={
             'SBVCHP_SBORC': (0.15, -4.0, -3.0),
             'SRVCHP_SBORC': (0.38,  4.5,  3.0),
             'SBVCHP_SRORC': (0.58,  4.5, -3.0),
             'SRVCHP_SRORC': (0.78,  4.5,  3.0),
         }),
]

# ── helpers ───────────────────────────────────────────────────────────────────
def nondom_2d(df, xc, yc):
    F = df[[xc,yc]].values; n=len(F); nd=np.ones(n,bool)
    for i in range(n):
        dom = np.all(F>=F[i],axis=1)&np.any(F>F[i],axis=1); dom[i]=False
        if dom.any(): nd[i]=False
    return df[nd].copy()

def front_xy(df_nd, xc, yc, xs, ys):
    s = df_nd.sort_values(xc)
    return s[xc].values*xs, s[yc].values*ys

def hv2d(df_nd, xc, yc, rx, ry):
    s=df_nd.sort_values(xc,ascending=False)
    xs=s[xc].values*100; ys=s[yc].values
    hv=0.0; yp=ry
    for xi,yi in zip(xs,ys):
        if xi>rx and yi>ry:
            hv+=(xi-rx)*max(yi-yp,0); yp=max(yp,yi)
    return hv

# ── 数据加载 ──────────────────────────────────────────────────────────────────
files = sorted(glob.glob(f'{RESULTS_DIR}/pareto_{WP_KEY}_*.csv'))
all_items = []
for f in files:
    stem  = os.path.basename(f).replace(f'pareto_{WP_KEY}_','').replace('.csv','')
    parts = stem.split('_')
    cb=parts[0]+'_'+parts[1]; fhp=parts[2]
    fhe=parts[3] if len(parts)>3 else '?'
    df=pd.read_csv(f); df['cb_config']=cb; df['fluid_hp']=fhp; df['fluid_he']=fhe
    all_items.append({'cb':cb,'fhp':fhp,'fhe':fhe,'df':df})

pool = pd.concat([x['df'] for x in all_items], ignore_index=True)
print(f'{WP_KEY} pool: {len(pool)} solutions, {len(files)} files')

# ══════════════════════════════════════════════════════════════════════════════
for P in PAIRS:
    xc,yc = P['xc'],P['yc']
    xs,ys = P['xscale'],P['yscale']
    tag   = P['tag']
    lpos  = P['label_pos']

    global_nd = nondom_2d(pool,xc,yc)
    gx,gy     = front_xy(global_nd,xc,yc,xs,ys)
    r_g,_     = spearmanr(global_nd[xc],global_nd[yc])
    n_global  = len(global_nd)

    cfg_pool_nd = {cb: nondom_2d(pool[pool['cb_config']==cb],xc,yc) for cb in CFG_STYLE}

    non_empty = [cb for cb in CFG_STYLE if len(cfg_pool_nd[cb])>0]
    all_px = np.concatenate([front_xy(cfg_pool_nd[cb],xc,yc,xs,ys)[0] for cb in non_empty])
    all_py = np.concatenate([front_xy(cfg_pool_nd[cb],xc,yc,xs,ys)[1] for cb in non_empty])
    x_lo=max(0,all_px.min()-1); x_hi=min(gx.max()+5, gx.max()*1.08)
    y_lo=max(0,all_py.min()-0.5); y_hi=gy.max()+2.5

    contrib_cfg = {cb: int((global_nd['cb_config']==cb).sum()) for cb in CFG_STYLE}
    print(f'\n[{tag}] n={n_global}, r={r_g:.3f}  {contrib_cfg}')

    best_fluid={}; rx_hv=gx.min()-1; ry_hv=gy.min()-1
    for item in all_items:
        nd_i=nondom_2d(item['df'],xc,yc)
        if len(nd_i)==0: continue
        hv=hv2d(nd_i,xc,yc,rx_hv,ry_hv); cb=item['cb']
        if cb not in best_fluid or hv>best_fluid[cb]['hv']:
            best_fluid[cb]={'item':item,'hv':hv,'nd':nd_i}

    # ── FIGURE 1 总图 ──────────────────────────────────────────────────────────
    fig,ax = plt.subplots(figsize=(10,7))
    fig.suptitle(f'{WP_KEY}  |  Individual and global Pareto fronts\n'
                 f'Objectives: {P["title_pair"]}  ({WP_SUB})',
                 fontsize=10.5, fontweight='bold', y=1.01)

    for item in all_items:
        nd_i=nondom_2d(item['df'],xc,yc)
        if len(nd_i)<2: continue
        qx,qy=front_xy(nd_i,xc,yc,xs,ys)
        ax.plot(qx,qy,color=CFG_STYLE[item['cb']]['color'],
                lw=0.55,alpha=0.18,solid_capstyle='round',zorder=2)

    for cb,nd_cb in cfg_pool_nd.items():
        if len(nd_cb)<2: continue
        st=CFG_STYLE[cb]; px,py=front_xy(nd_cb,xc,yc,xs,ys)
        n_c=contrib_cfg[cb]
        ax.plot(px,py,color=st['color'],lw=st['lw']*(1.4 if n_c>0 else 0.8),
                ls='-' if n_c>0 else '--',zorder=6,solid_capstyle='round')
        ax.scatter(px[-1],py[-1],color=st['color'],s=60,zorder=9,
                   edgecolors='white',linewidths=1.0)
        idx_D=np.argmax(py)
        ax.scatter(px[idx_D],py[idx_D],color=st['color'],s=60,marker='D',
                   zorder=9,edgecolors='white',linewidths=1.0)
        pct,ox,oy = lpos[cb]
        x_tgt=px[0]+pct*(px[-1]-px[0])
        idx=np.argmin(np.abs(px-x_tgt))
        hp_l='SBVCHP' if 'SBVCHP' in cb else 'SRVCHP'
        orc_l='SBORC' if 'SBORC' in cb else 'SRORC'
        ax.annotate(f'{hp_l}+{orc_l}\n(n={n_c}/{n_global})',
                    xy=(px[idx],py[idx]),xytext=(px[idx]+ox,py[idx]+oy),
                    fontsize=8,color=st['color'],fontweight='bold',
                    arrowprops=dict(arrowstyle='->',color=st['color'],
                                   lw=0.9,alpha=0.85,shrinkA=2,shrinkB=3),
                    ha='center',va='center',
                    bbox=dict(boxstyle='round,pad=0.3',fc='white',
                              ec=st['color'],alpha=0.92,lw=0.8),zorder=11)

    ax.plot(gx,gy,**GLOBAL_STYLE,solid_capstyle='round')
    ax.text(gx.max()-0.5,gy[np.argmax(gx)]-1.5,'Global Pareto front',
            fontsize=8.5,color='#111',ha='right',va='top',fontweight='bold')
    ax.axvline(gx.max(),color='#888',lw=0.7,ls='--',alpha=0.35)
    ax.axhline(gy.max(),color='#888',lw=0.7,ls='--',alpha=0.35)
    ax.text(gx.max()+0.3,y_lo+0.3,f'max={gx.max():.1f} {P["xunit"]}',
            ha='left',va='bottom',fontsize=7.5,color='#666')
    ax.text(x_lo+0.3,gy.max()+0.3,f'max={gy.max():.2f} {P["yunit"]}',
            ha='left',va='bottom',fontsize=7.5,color='#666')
    ax.text(0.98,0.02,f'Global front: n={n_global}\nSpearman r = {r_g:.3f}',
            transform=ax.transAxes,fontsize=8,ha='right',va='bottom',
            bbox=dict(boxstyle='round,pad=0.4',fc='#f8f8f8',ec='#cccccc',alpha=0.9))

    # η_p2p=100% 特殊参考线（仅 DC-E 的 p2p_eth / p2p_etaex）
    if WP_KEY=='DC-E' and xc=='eta_p2p' and gx.max()>=99.9:
        ax.axvline(100.0,color='#cc3300',lw=1.0,ls=':',alpha=0.6,zorder=3)
        ax.text(99.8,y_hi-0.5,r'$\eta_{p2p}$=100%',ha='right',va='top',
                fontsize=7.5,color='#cc3300',style='italic')

    ax.set_xlim(x_lo,x_hi); ax.set_ylim(y_lo,y_hi)
    ax.set_xlabel(P['xlabel'],fontsize=10); ax.set_ylabel(P['ylabel'],fontsize=10)
    ax.xaxis.set_minor_locator(MultipleLocator(5))
    ax.yaxis.set_minor_locator(MultipleLocator(1))
    ax.grid(lw=0.35,alpha=0.45,which='major')
    ax.grid(lw=0.15,alpha=0.20,which='minor')
    handles=[mlines.Line2D([],[],color=st['color'],lw=st['lw'],label=st['label'])
             for cb,st in CFG_STYLE.items()]
    handles+=[mlines.Line2D([],[],color='#111',lw=3.0,label='Global Pareto front'),
              mlines.Line2D([],[],color='#aaa',lw=0.6,label='Individual fluid pairs')]
    ax.legend(handles=handles,fontsize=8,loc='upper right',
              framealpha=0.9,edgecolor='#ccc',borderpad=0.7)
    plt.tight_layout()
    out1=os.path.join(OUT_DIR,f'global_pareto_{WP_TAG}_{tag}_main.png')
    fig.savefig(out1,dpi=150,bbox_inches='tight',facecolor='white')
    plt.close(fig); print(f'  Saved → {out1}')

    # ── FIGURE 2 分解图（2×2） ────────────────────────────────────────────────
    fig2,axes=plt.subplots(2,2,figsize=(14,11),constrained_layout=True)
    fig2.suptitle(f'{WP_KEY}  |  Fluid pair contributions within each CB configuration\n'
                  f'Color = HP fluid  ·  Line style = ORC fluid  ·  Thick = config pooled front'
                  f'  |  Objectives: {P["title_pair"]}',
                  fontsize=10.5,fontweight='bold')

    for ax2,cb in zip(axes.flat,CFG_STYLE):
        cb_st=CFG_STYLE[cb]; items_cb=[x for x in all_items if x['cb']==cb]
        nd_pool=cfg_pool_nd[cb]; n_cg=contrib_cfg[cb]
        if len(nd_pool)<2:
            ax2.set_title(f"{cb_st['label']}\n(no solutions / not available for {WP_KEY})",
                          fontsize=9.5,color='#aaa')
            ax2.axis('off'); continue
        px,py=front_xy(nd_pool,xc,yc,xs,ys)
        contrib_pairs=set(zip(nd_pool['fluid_hp'],nd_pool['fluid_he']))
        x_lo2=max(0,px.min()-1); x_hi2=px.max()+6
        y_lo2=max(0,py.min()-0.5); y_hi2=py.max()+2.5

        ax2.plot(gx,gy,color='#888',lw=1.2,ls='--',alpha=0.5,zorder=1)

        for item in items_cb:
            if (item['fhp'],item['fhe']) in contrib_pairs: continue
            nd_i=nondom_2d(item['df'],xc,yc)
            if len(nd_i)<2: continue
            qx,qy=front_xy(nd_i,xc,yc,xs,ys)
            ax2.plot(qx,qy,color='#cccccc',lw=0.6,alpha=0.5,solid_capstyle='round',zorder=2)

        for item in items_cb:
            if (item['fhp'],item['fhe']) not in contrib_pairs: continue
            nd_i=nondom_2d(item['df'],xc,yc)
            if len(nd_i)<2: continue
            qx,qy=front_xy(nd_i,xc,yc,xs,ys)
            color=HP_COLOR.get(item['fhp'],'#888'); ls=ORC_LS.get(item['fhe'],'-')
            ax2.plot(qx,qy,color=color,ls=ls,lw=1.4,alpha=0.85,solid_capstyle='round',zorder=4)
            ax2.scatter(qx[-1],qy[-1],color=color,s=22,zorder=5,edgecolors='white',linewidths=0.5)

        ax2.plot(px,py,color=cb_st['color'],lw=2.8,zorder=8,solid_capstyle='round')
        ax2.scatter(px[-1],py[-1],color=cb_st['color'],s=70,zorder=10,
                    edgecolors='white',linewidths=1.0)
        idx_D=np.argmax(py)
        ax2.scatter(px[idx_D],py[idx_D],color=cb_st['color'],s=70,marker='D',
                    zorder=10,edgecolors='white',linewidths=1.0)

        bx=nd_pool.loc[nd_pool[xc].idxmax()]; by=nd_pool.loc[nd_pool[yc].idxmax()]
        ax2.annotate(f'max {P["xn"]}:\n{bx["fluid_hp"]}/{bx["fluid_he"]}',
                     xy=(px[-1],py[-1]),xytext=(px[-1]-3.0,py[-1]+1.5),
                     fontsize=7,color=cb_st['color'],fontweight='bold',
                     arrowprops=dict(arrowstyle='->',color=cb_st['color'],lw=0.8),
                     ha='right',va='bottom',
                     bbox=dict(boxstyle='round,pad=0.2',fc='white',
                               ec=cb_st['color'],alpha=0.88,lw=0.6),zorder=11)
        ax2.annotate(f'max {P["yn"]}:\n{by["fluid_hp"]}/{by["fluid_he"]}',
                     xy=(px[idx_D],py[idx_D]),xytext=(px[idx_D]+3.0,py[idx_D]-1.5),
                     fontsize=7,color=cb_st['color'],fontweight='bold',
                     arrowprops=dict(arrowstyle='->',color=cb_st['color'],lw=0.8),
                     ha='left',va='top',
                     bbox=dict(boxstyle='round,pad=0.2',fc='white',
                               ec=cb_st['color'],alpha=0.88,lw=0.6),zorder=11)

        ax2.set_xlim(x_lo2,x_hi2); ax2.set_ylim(y_lo2,y_hi2)
        ax2.set_xlabel(P['xlabel'],fontsize=9); ax2.set_ylabel(P['ylabel'],fontsize=9)
        ax2.xaxis.set_minor_locator(MultipleLocator(5))
        ax2.yaxis.set_minor_locator(MultipleLocator(1))
        ax2.grid(lw=0.35,alpha=0.45,which='major')
        ax2.grid(lw=0.15,alpha=0.20,which='minor')
        n_c=len(contrib_pairs); n_t=len({(x['fhp'],x['fhe']) for x in items_cb})
        ax2.set_title(f"{cb_st['label']}\n"
                      f"Contributing fluid pairs: {n_c}/{n_t}  |  "
                      f"Global front: {n_cg}/{n_global} pts",
                      fontsize=9.0,fontweight='bold',color=cb_st['color'],pad=5)
        hp_f=sorted({fhp for fhp,_ in contrib_pairs})
        he_f=sorted({fhe for _,fhe in contrib_pairs})
        hp_h=[mlines.Line2D([],[],color=HP_COLOR.get(f,'#888'),lw=1.8,label=f'HP: {f}')
              for f in hp_f]
        he_h=[mlines.Line2D([],[],color='#555',ls=ORC_LS.get(f,'-'),lw=1.5,label=f'ORC: {f}')
              for f in he_f]
        ax2.legend(handles=hp_h+he_h+[
            mlines.Line2D([],[],color=cb_st['color'],lw=2.8,label='Config pooled front'),
            mlines.Line2D([],[],color='#888',lw=1.2,ls='--',label='Global front (ref)'),
            mlines.Line2D([],[],color='#ccc',lw=0.8,label='Non-contributing pairs')],
            fontsize=7,loc='upper right',ncol=2,framealpha=0.90,edgecolor='#ccc',
            borderpad=0.6,columnspacing=0.8,handlelength=1.8)

    out2=os.path.join(OUT_DIR,f'config_fluid_decomposition_{WP_TAG}_{tag}.png')
    fig2.savefig(out2,dpi=150,bbox_inches='tight',facecolor='white')
    plt.close(fig2); print(f'  Saved → {out2}')

print(f'\nDone. All 6 figures saved for {WP_KEY}.')
