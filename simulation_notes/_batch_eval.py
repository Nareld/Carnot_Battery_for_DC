"""
_batch_eval.py  –  standalone batch evaluator for dc_pareto_scan.py
====================================================================
Called as a subprocess by dc_pareto_scan.py on macOS to isolate
CoolProp TTSE segfaults from the main process.

Usage (internal):
    python3 _batch_eval.py <input_json_path> <output_json_path>

Input JSON schema:
    {
        "fluid_hp": str,
        "fluid_he": str,
        "cb_class_key": str,
        "samples": [[T_st_ht, dT_st_sp, dT_hp_cs_gl, dT_hp_ev_sh,
                     dT_he_ev_sh, dT_hp_cd_sc, eta_max_cp, eta_max_ex, eta_pm], ...],
        "T_hp_cs": float,
        "T_he_cs": float,
        "src_dir": str,
        "opt_params": {...}
    }

Output JSON schema:
    [result_dict_or_null, ...]   (same length as samples)

NOTE: This script must stay in sync with evaluate_cb() in dc_pareto_scan.py.
"""

import sys
import os
import json
import warnings


def main():
    if len(sys.argv) != 3:
        sys.exit(1)

    input_path  = sys.argv[1]
    output_path = sys.argv[2]

    with open(input_path, 'r') as f:
        args = json.load(f)

    fluid_hp     = args['fluid_hp']
    fluid_he     = args['fluid_he']
    cb_class_key = args['cb_class_key']
    samples      = args['samples']
    T_hp_cs      = args['T_hp_cs']
    T_he_cs      = args['T_he_cs']
    src_dir      = args['src_dir']
    opt_params   = args['opt_params']

    sys.path.insert(0, src_dir)

    import CoolProp.CoolProp as CP
    import _module_carnot_battery as CB
    warnings.filterwarnings('ignore')

    cb_class_map = {
        'SBVCHP_SBORC_STES2T': CB.SBVCHP_SBORC_STES2T,
        'SBVCHP_SRORC_STES2T': CB.SBVCHP_SRORC_STES2T,
        'SRVCHP_SBORC_STES2T': CB.SRVCHP_SBORC_STES2T,
        'SRVCHP_SRORC_STES2T': CB.SRVCHP_SRORC_STES2T,
    }
    cb_class = cb_class_map[cb_class_key]

    results = []
    for s in samples:
        (T_st_ht, dT_st_sp, dT_hp_cs_gl, dT_hp_ev_sh,
         dT_he_ev_sh, dT_hp_cd_sc, eta_max_cp, eta_max_ex, eta_pm) = s

        try:
            # ── Heat source (HP cold side = data center coolant) ──────────
            p_hp_cs_su = 1e+5
            T_hp_cs_su = T_hp_cs + 273.15
            T_hp_cs_ex = max(T_hp_cs_su - dT_hp_cs_gl, 275.15)
            i_hp_cs_su = CP.PropsSI('H', 'T', T_hp_cs_su, 'P', p_hp_cs_su, 'H2O')
            i_hp_cs_ex = CP.PropsSI('H', 'T', T_hp_cs_ex, 'P', p_hp_cs_su, 'H2O')

            # ── Heat sink (HE cold side = ambient / cooling tower) ────────
            p_he_cs_su = 1e+5
            T_he_cs_su = T_he_cs + 273.15
            T_he_cs_ex = T_he_cs_su + opt_params['dT_he_cs_gl']
            i_he_cs_su = CP.PropsSI('H', 'T', T_he_cs_su, 'P', p_he_cs_su, 'H2O')
            i_he_cs_ex = CP.PropsSI('H', 'T', T_he_cs_ex, 'P', p_he_cs_su, 'H2O')

            T_st_ht_K = T_st_ht + 273.15

            # ── Parameters dict (must match main script exactly) ──────────
            params = {
                'p_hp_cs_su': p_hp_cs_su, 'i_hp_cs_su': i_hp_cs_su, 'i_hp_cs_ex': i_hp_cs_ex,
                'p_he_cs_su': p_he_cs_su, 'i_he_cs_su': i_he_cs_su, 'i_he_cs_ex': i_he_cs_ex,
                'm_hp_cs': 1.0, 'm_he_cs': 1.0,
                'p_st_ht': opt_params['p_st_ht'], 'p_st_lt': opt_params['p_st_lt'],
                'T_st_ht': T_st_ht_K, 'dT_st_sp': dT_st_sp,
                'eta_max_cp': eta_max_cp, 'eta_max_ex': eta_max_ex, 'eta_pm': eta_pm,
                'dT_hp_ev_pp': opt_params['dT_hp_ev_pp'],
                'dT_hp_cd_pp': opt_params['dT_hp_cd_pp'],
                'dT_he_ev_pp': opt_params['dT_he_ev_pp'],
                'dT_he_cd_pp': opt_params['dT_he_cd_pp'],
                'dT_he_ev_sh': dT_he_ev_sh, 'dT_hp_ev_sh': dT_hp_ev_sh,
                'dT_he_cd_sc': opt_params['dT_he_cd_sc'], 'dT_hp_cd_sc': dT_hp_cd_sc,
                'dp_hp_ev': 0.0, 'dp_hp_cd': 0.0, 'dp_hp_rg_lq': 0.0, 'dp_hp_rg_vp': 0.0,
                'epsilon_hp': opt_params['epsilon_hp'],
                'dp_he_ev': 0.0, 'dp_he_cd': 0.0, 'dp_he_rg_lq': 0.0, 'dp_he_rg_vp': 0.0,
                'epsilon_he': opt_params['epsilon_he'],
                'm_hp_st_max': 0.0, 'm_he_st_max': 0.0,
                'version': opt_params['version'],
                'mode_hp': True, 'mode_he': True, 'mode': 'source',
                'p_ref': p_he_cs_su, 'T_ref': T_he_cs_su,
                'p_0': p_he_cs_su, 'T_0': T_he_cs_su,
                'fluid_hp': fluid_hp, 'fluid_he': fluid_he,
                'fluid_st': opt_params['fluid_st'],
                'wet_ex': 0, 'm_rat_hp': 0, 'm_rat_he': 0,
            }
            options = {'plot_flag': False, 'print_flag': False, 'debug': False, 'exergy': True}
            # !! inputs tuple must have exactly 14 elements (same as main script)
            inputs = (
                p_hp_cs_su, i_hp_cs_su, p_hp_cs_su, i_hp_cs_ex, 1.0, 'H2O',
                p_he_cs_su, i_he_cs_su, p_he_cs_su, i_he_cs_ex, 1.0, 'H2O',
                1e+3, 1e+3
            )

            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                my_CB = cb_class(inputs, params, options)
                my_CB.evaluate()

            if my_CB.error:
                results.append(None)
                continue

            eta_P2P   = float(my_CB.eta_cb_elec)
            E_dens_th = float(my_CB.E_dens_th) / 3.6e6   # J/m³ → kWh/m³
            eta_II    = float(my_CB.eta_cb_exer)

            if not (0.01 < eta_P2P < 2.0) or not (0.5 < E_dens_th < 5000) or not (0.001 < eta_II < 2.0):
                results.append(None)
                continue

            results.append({
                'eta_P2P':   eta_P2P,
                'E_dens_th': E_dens_th,
                'eta_II':    eta_II,
                'T_st_ht':   T_st_ht,
                'dT_st_sp':  dT_st_sp,
            })

        except Exception:
            results.append(None)

    with open(output_path, 'w') as f:
        json.dump(results, f)


if __name__ == '__main__':
    main()
