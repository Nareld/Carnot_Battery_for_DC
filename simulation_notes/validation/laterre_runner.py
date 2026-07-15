#!/usr/bin/env python3
"""
Laterre 2024 Appendix B 构造点运行器 v0.1

## 验证层级标注：interface_check / constructed_point_runner
## 不是：single_point_validation（不满足 G1a 输入完整性要求）
## 不是：optimization_reproduction（未运行优化搜索）

不经过 DEAP 优化层，直接调用 CBSim 核心 SBVCHP_SBORC_STES2T，
验证两组 Laterre 约束下构造点是否可运行：
  - 原始约束：p_st=7.5 bar, T_st_ht_max=150°C, T_hp_max=180°C
  - 松弛约束：p_st=20 bar, T_st_ht_max=200°C, T_hp_max=300°C

## 与文献值的关系
Laterre 2024 Appendix B 报告 eta_P2P = 39.7%（原始）/ 43.0%（松弛）是
**重新优化后的结果**，不是文献给定完整设计变量后的单点 benchmark。
因此，这些数值属于 G1b（优化复现目标），不属于 G1a（单点模型验证）。
本 runner 仅验证 CBSim 接口在 Laterre 边界下的可调用性，不宣称复现。

设计原则：
  - 绕过 main_cb.eval_CB（硬编码/无返回问题）
  - 直调 src/_module_carnot_battery.py 中 SBVCHP_SBORC_STES2T(inputs, params, options)
  - 本轮只做"构造点可运行"检查，不要求找到文献最优点

运行方式：
  .venv/bin/python simulation_notes/validation/laterre_runner.py
"""

import sys
import os
import json
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────────────────
_project_root = Path(__file__).resolve().parents[2]
_src_dir = _project_root / "src"
sys.path.insert(0, str(_src_dir))

import CoolProp.CoolProp as CP
from _module_carnot_battery import SBVCHP_SBORC_STES2T


# ═══════════════════════════════════════════════════════════════════════════
# 0. 基准参数定义
# ═══════════════════════════════════════════════════════════════════════════

# 通用固定参数（来自 optimization_config.json + Laterre Appendix B 对齐项）
FIXED_PARAMS = {
    # 换热器 pinch points [K]
    'dT_hp_ev_pp': 5.0,
    'dT_hp_cd_pp': 3.0,
    'dT_he_ev_pp': 3.0,
    'dT_he_cd_pp': 5.0,
    # 过冷度
    'dT_he_cd_sc': 3.0,
    # ORC 冷侧滑移
    'dT_he_cs_gl': 10.0,
    # 回热器效能
    'epsilon_hp': 0.8,
    'epsilon_he': 0.8,
    # 压降 [Pa]
    'dp_hp_ev': 0.0, 'dp_hp_cd': 0.0,
    'dp_hp_rg_lq': 0.0, 'dp_hp_rg_vp': 0.0,
    'dp_he_ev': 0.0, 'dp_he_cd': 0.0,
    'dp_he_rg_lq': 0.0, 'dp_he_rg_vp': 0.0,
    # 储热流体
    'fluid_st': 'H2O',
    # 版本与模式
    'version': 'thermodynamic_full',
    'mode_hp': True, 'mode_he': True, 'mode': 'source',
    # 质量流量（由 max 模式控制）
    'm_hp_st_max': 0.0, 'm_he_st_max': 0.0,
    'm_rat_hp': 0, 'm_rat_he': 0,
    'wet_ex': 0,
}


def build_laterre_inputs_params(
    T_hp_cs_C: float,   # HP 冷源供温 [°C] = t_hs (数据废热)
    T_he_cs_C: float,   # ORC 冷汇供温 [°C] = t_cs (环境)
    T_st_ht_C: float,   # 高温罐温度 [°C]
    dT_st_sp_K: float,  # 储热温差 [K]
    dT_hp_cs_gl_K: float,    # HP 冷源滑移 [K]
    dT_hp_ev_sh_K: float,    # HP 蒸发过热度 [K]
    dT_he_ev_sh_K: float,    # ORC 蒸发过热度 [K]
    dT_hp_cd_sc_K: float,    # HP 冷凝过冷度 [K]
    eta_max_cp: float,       # 压缩机等熵效率
    eta_max_ex: float,       # 膨胀机等熵效率
    eta_pm: float,           # 泵/马达机械效率
    p_st_ht_Pa: float,       # 高温罐压力 [Pa]
    p_st_lt_Pa: float,       # 低温罐压力 [Pa]
    fluid_hp: str,           # HP 工质
    fluid_he: str,           # ORC 工质
):
    """构建 CBSim inputs (14-tuple) 和 params (dict)，模仿 CBEvaluator._build_inputs_params 但不依赖 DEAP。"""

    T_hp_cs_su_K = T_hp_cs_C + 273.15
    T_hp_cs_ex_K = max(T_hp_cs_su_K - dT_hp_cs_gl_K, 275.15)
    p_hp_cs = 1e5  # [Pa] 冷水回路常压

    T_he_cs_su_K = T_he_cs_C + 273.15
    T_he_cs_ex_K = T_he_cs_su_K + FIXED_PARAMS['dT_he_cs_gl']
    p_he_cs = 1e5  # [Pa] 冷水回路常压

    i_hp_cs_su = CP.PropsSI('H', 'T', T_hp_cs_su_K, 'P', p_hp_cs, 'H2O')
    i_hp_cs_ex = CP.PropsSI('H', 'T', T_hp_cs_ex_K, 'P', p_hp_cs, 'H2O')
    i_he_cs_su = CP.PropsSI('H', 'T', T_he_cs_su_K, 'P', p_he_cs, 'H2O')
    i_he_cs_ex = CP.PropsSI('H', 'T', T_he_cs_ex_K, 'P', p_he_cs, 'H2O')

    # 14-element inputs tuple
    inputs = (
        p_hp_cs, i_hp_cs_su, p_hp_cs, i_hp_cs_ex, 1.0, 'H2O',   # HP 冷源
        p_he_cs, i_he_cs_su, p_he_cs, i_he_cs_ex, 1.0, 'H2O',   # ORC 冷汇
        1e3, 1e3,  # P_hp, P_he (占位 — 由 mode='source' 覆盖)
    )

    params = {
        'p_hp_cs_su': p_hp_cs, 'i_hp_cs_su': i_hp_cs_su, 'i_hp_cs_ex': i_hp_cs_ex,
        'p_he_cs_su': p_he_cs, 'i_he_cs_su': i_he_cs_su, 'i_he_cs_ex': i_he_cs_ex,
        'm_hp_cs': 1.0, 'm_he_cs': 1.0,
        'p_st_ht': p_st_ht_Pa,
        'p_st_lt': p_st_lt_Pa,
        'T_st_ht': T_st_ht_C + 273.15,
        'dT_st_sp': dT_st_sp_K,
        'eta_max_cp': eta_max_cp,
        'eta_max_ex': eta_max_ex,
        'eta_pm': eta_pm,
        'dT_hp_ev_pp': FIXED_PARAMS['dT_hp_ev_pp'],
        'dT_hp_cd_pp': FIXED_PARAMS['dT_hp_cd_pp'],
        'dT_he_ev_pp': FIXED_PARAMS['dT_he_ev_pp'],
        'dT_he_cd_pp': FIXED_PARAMS['dT_he_cd_pp'],
        'dT_hp_ev_sh': dT_hp_ev_sh_K,
        'dT_he_ev_sh': dT_he_ev_sh_K,
        'dT_he_cd_sc': FIXED_PARAMS['dT_he_cd_sc'],
        'dT_hp_cd_sc': dT_hp_cd_sc_K,
        'dp_hp_ev': FIXED_PARAMS['dp_hp_ev'], 'dp_hp_cd': FIXED_PARAMS['dp_hp_cd'],
        'dp_hp_rg_lq': FIXED_PARAMS['dp_hp_rg_lq'], 'dp_hp_rg_vp': FIXED_PARAMS['dp_hp_rg_vp'],
        'epsilon_hp': FIXED_PARAMS['epsilon_hp'],
        'dp_he_ev': FIXED_PARAMS['dp_he_ev'], 'dp_he_cd': FIXED_PARAMS['dp_he_cd'],
        'dp_he_rg_lq': FIXED_PARAMS['dp_he_rg_lq'], 'dp_he_rg_vp': FIXED_PARAMS['dp_he_rg_vp'],
        'epsilon_he': FIXED_PARAMS['epsilon_he'],
        'm_hp_st_max': FIXED_PARAMS['m_hp_st_max'],
        'm_he_st_max': FIXED_PARAMS['m_he_st_max'],
        'version': FIXED_PARAMS['version'],
        'mode_hp': FIXED_PARAMS['mode_hp'], 'mode_he': FIXED_PARAMS['mode_he'],
        'mode': FIXED_PARAMS['mode'],
        'p_ref': p_he_cs, 'T_ref': T_he_cs_su_K,
        'p_0': p_he_cs, 'T_0': T_he_cs_su_K,
        'fluid_hp': fluid_hp,
        'fluid_he': fluid_he,
        'fluid_st': FIXED_PARAMS['fluid_st'],
        'wet_ex': FIXED_PARAMS['wet_ex'],
        'm_rat_hp': FIXED_PARAMS['m_rat_hp'],
        'm_rat_he': FIXED_PARAMS['m_rat_he'],
    }

    options = {'plot_flag': False, 'print_flag': False,
               'debug': False, 'exergy': True}

    return inputs, params, options


def run_single_point(label: str, T_hp_cs_C: float, T_he_cs_C: float,
                     T_st_ht_C: float, dT_st_sp_K: float,
                     dT_hp_cs_gl_K: float, dT_hp_ev_sh_K: float,
                     dT_he_ev_sh_K: float, dT_hp_cd_sc_K: float,
                     eta_max_cp: float, eta_max_ex: float, eta_pm: float,
                     p_st_ht_Pa: float, p_st_lt_Pa: float,
                     fluid_hp: str, fluid_he: str,
                     target_eta_p2p: float = None):
    """运行单个 CBSim 点并返回结果字典。"""
    inputs, params, options = build_laterre_inputs_params(
        T_hp_cs_C, T_he_cs_C,
        T_st_ht_C, dT_st_sp_K,
        dT_hp_cs_gl_K, dT_hp_ev_sh_K, dT_he_ev_sh_K, dT_hp_cd_sc_K,
        eta_max_cp, eta_max_ex, eta_pm,
        p_st_ht_Pa, p_st_lt_Pa,
        fluid_hp, fluid_he)

    result = {
        'label': label,
        'T_hp_cs_C': T_hp_cs_C, 'T_he_cs_C': T_he_cs_C,
        'T_st_ht_C': T_st_ht_C, 'dT_st_sp_K': dT_st_sp_K,
        'p_st_ht_bar': p_st_ht_Pa / 1e5,
        'fluid_hp': fluid_hp, 'fluid_he': fluid_he,
        'target_eta_p2p': target_eta_p2p,
        'success': False,
        'error_msg': None,
    }

    try:
        cb = SBVCHP_SBORC_STES2T(inputs, params, options)
        cb.evaluate()

        # --- 基础性能指标 ---
        result['success'] = True
        result['eta_cb_elec'] = round(cb.eta_cb_elec, 6)  # eta_P2P
        result['eta_cb_exer'] = round(cb.eta_cb_exer, 6)  # exergy efficiency
        result['E_dens_th'] = round(cb.E_dens_th, 2)  # thermal energy density [J/m³]
        result['E_dens_el'] = round(cb.E_dens_el, 2)  # electric energy density [J/m³]
        result['COP_HP'] = round(cb.my_HP.eta_hp_cyclen, 4)  # HP cycle COP
        result['eta_ORC'] = round(cb.my_HE.eta_he_cyclen, 6)  # ORC cycle efficiency
        result['T_hs_su_HP_C'] = round(cb.my_HP.T_hp_hs_su - 273.15, 2)
        result['T_hs_ex_HP_C'] = round(cb.my_HP.T_hp_hs_ex - 273.15, 2)
        result['T_cs_su_HP_C'] = round(cb.my_HP.T_hp_cs_su - 273.15, 2)
        result['T_cs_ex_HP_C'] = round(cb.my_HP.T_hp_cs_ex - 273.15, 2)
        result['v_st_ht'] = round(cb.v_st_ht, 6)  # 储罐体积 [m³]
        result['m_hp_cs'] = round(cb.m_hp_cs, 4)
        result['m_he_cs'] = round(cb.m_he_cs, 4)

        if target_eta_p2p is not None:
            result['delta_eta'] = round(result['eta_cb_elec'] - target_eta_p2p, 6)
            result['delta_pct'] = round(100 * (result['eta_cb_elec'] - target_eta_p2p) / target_eta_p2p, 2)

    except Exception as e:
        result['error_msg'] = str(e)[:200]

    return result


def print_result(r: dict):
    """格式化打印单个点的结果。"""
    print(f"\n{'─'*60}")
    print(f"  {r['label']}")
    print(f"{'─'*60}")
    print(f"  工质: HP={r['fluid_hp']}, ORC={r['fluid_he']}")
    print(f"  边界: T_hs={r['T_hp_cs_C']}°C, T_cs={r['T_he_cs_C']}°C")
    print(f"  设计: T_st_ht={r['T_st_ht_C']}°C, dT_st_sp={r['dT_st_sp_K']}K, p_st={r['p_st_ht_bar']} bar")
    if r['target_eta_p2p'] is not None:
        print(f"  目标: η_P2P = {r['target_eta_p2p']*100:.1f}% (Laterre 2024 App B)")

    if not r['success']:
        print(f"  ❌ 失败: {r['error_msg']}")
        return

    print(f"  ✅ 运行成功")
    print(f"  η_P2P   = {r['eta_cb_elec']*100:.2f}%")
    if r.get('delta_pct') is not None:
        print(f"            偏离目标: {r['delta_pct']:+.2f}%")
    print(f"  η_ex    = {r['eta_cb_exer']*100:.2f}%")
    print(f"  COP_HP  = {r['COP_HP']:.3f}")
    print(f"  η_ORC   = {r['eta_ORC']*100:.3f}%")
    print(f"  E_dens_th= {r['E_dens_th']/1e6:.3f} MJ/m³")
    print(f"  E_dens_el= {r['E_dens_el']/1e6:.3f} MJ/m³")
    print(f"  T_hs HP in/out = {r['T_hs_su_HP_C']:.1f}°C / {r['T_hs_ex_HP_C']:.1f}°C")
    print(f"  T_cs HP in/out = {r['T_cs_su_HP_C']:.1f}°C / {r['T_cs_ex_HP_C']:.1f}°C")
    print(f"  v_st_ht = {r['v_st_ht']:.6f} m³")


# ═══════════════════════════════════════════════════════════════════════════
# 1. 运行两组约束
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 60)
    print("  Laterre 2024 Appendix B — CBSim 单点复现 Runner")
    print("  SBVCHP_SBORC_STES2T | Python 3.11 | CoolProp | scipy 1.11.x")
    print("=" * 60)

    # 共同边界
    T_HS = 50     # [°C] 数据废热 = Laterre t_hs
    T_CS = 30     # [°C] 环境冷汇 = Laterre t_cs

    # 共同工质（论文中最常用对）
    FLUID_HP = 'R1233zd(E)'
    FLUID_HE = 'R1234ze(E)'

    results = []

    # ── 约束集 1：原始约束 (可运行点) ──────────────────────────────────
    # p_st = 7.5 bar, T_st_ht^max = 150°C, T_hp^max = 180°C
    # 经扫参确认：T_st_ht ≤ 110°C 可运行，超过则 ORC 求解器收敛失败
    # Laterre 目标: eta_P2P = 39.7%
    results.append(run_single_point(
        label='Laterre Original — 可运行构造点 (7.5 bar, T_st_ht=110°C)',
        T_hp_cs_C=T_HS, T_he_cs_C=T_CS,
        T_st_ht_C=110.0,       # 经测试，120°C+ 失败，110°C 是最高可运行点
        dT_st_sp_K=30.0,
        dT_hp_cs_gl_K=10.0,
        dT_hp_ev_sh_K=5.0,
        dT_he_ev_sh_K=1.5,
        dT_hp_cd_sc_K=5.0,
        eta_max_cp=0.80,
        eta_max_ex=0.80,
        eta_pm=0.50,
        p_st_ht_Pa=7.5e5,      # Laterre 原始: 7.5 bar
        p_st_lt_Pa=7.5e5,
        fluid_hp=FLUID_HP, fluid_he=FLUID_HE,
        target_eta_p2p=0.397,  # 39.7%
    ))

    # ── 约束集 2：松弛约束 (可运行构造点) ──────────────────────────────
    # p_st = 2.5 bar (项目默认), T_st_ht^max = 200°C
    # Laterre 20 bar 导致 ORC fsolve 失败，暂用项目默认 2.5 bar
    # 经测试：高 eta (0.85+) 反而导致收敛失败，使用中等值
    # Laterre 目标: eta_P2P = 43.0%
    results.append(run_single_point(
        label='Laterre Relaxed — 可运行构造点 (2.5 bar, T_st_ht=100°C, eta=0.80)',
        T_hp_cs_C=T_HS, T_he_cs_C=T_CS,
        T_st_ht_C=100.0,       # 高储热温度在此边界不可行
        dT_st_sp_K=35.0,
        dT_hp_cs_gl_K=10.0,
        dT_hp_ev_sh_K=5.0,
        dT_he_ev_sh_K=1.5,
        dT_hp_cd_sc_K=5.0,
        eta_max_cp=0.80,
        eta_max_ex=0.80,
        eta_pm=0.50,
        p_st_ht_Pa=2.5e5,      # 项目默认值 (Laterre 20 bar 不收敛)
        p_st_lt_Pa=2.5e5,
        fluid_hp=FLUID_HP, fluid_he=FLUID_HE,
        target_eta_p2p=0.430,  # 43.0%
    ))

    # ── 补充：DC-A 基准对比点 ──────────────────────────────────────────
    results.append(run_single_point(
        label='DC-A 基准 (T_hs=35°C, T_cs=5°C) — 验证已知可运行',
        T_hp_cs_C=35, T_he_cs_C=5,
        T_st_ht_C=80.0,
        dT_st_sp_K=30.0,
        dT_hp_cs_gl_K=10.0,
        dT_hp_ev_sh_K=5.0,
        dT_he_ev_sh_K=1.5,
        dT_hp_cd_sc_K=5.0,
        eta_max_cp=0.80,
        eta_max_ex=0.80,
        eta_pm=0.50,
        p_st_ht_Pa=2.5e5, p_st_lt_Pa=2.5e5,
        fluid_hp=FLUID_HP, fluid_he=FLUID_HE,
        target_eta_p2p=None,   # 基准对比，非复现目标
    ))

    # ── 打印结果 ──────────────────────────────────────────────────────────
    for r in results:
        print_result(r)

    # ── 汇总 ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  汇总")
    print(f"{'='*60}")
    for r in results:
        status = "✅" if r['success'] else "❌"
        p2p_str = f"η_P2P={r['eta_cb_elec']*100:.2f}%" if r['success'] else r.get('error_msg', 'failed')[:60]
        print(f"  {status} {r['label']}")
        print(f"     {p2p_str}")
    n_ok = sum(1 for r in results if r['success'])
    n_total = len(results)
    print(f"\n  结论：{n_ok}/{n_total} 个构造点可运行")
    if n_ok == n_total:
        print(f"  G1 状态：接口已通，Laterre 边界 (t_hs=50°C, t_cs=30°C) 在受限 T_st_ht 范围内可运行")
        print(f"  阻塞项：高 T_st_ht (>110°C) ORC fsolve 不收敛，20 bar 约束不可行，高 eta (0.90) 反致失败")
        print(f"  下一步：需要单目标/多目标搜索才能接近 Laterre 39.7%/43.0% 目标")
    else:
        print(f"  G1 状态：部分可运行 — 接口已通但 Laterre 边界受限，需排查 ORC 收敛")
