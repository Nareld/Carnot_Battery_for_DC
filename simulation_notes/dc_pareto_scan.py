#!/usr/bin/env python3
"""
Data Center Carnot Battery Multi-Configuration Pareto Frontier Scan
====================================================================
Performs Pareto frontier analysis for:
  - 6 DC operating points (DC-A to DC-F)
  - 4 CB configurations (SBVCHP+SBORC, SBVCHP+SRORC, SRVCHP+SBORC, SRVCHP+SRORC)
  = 24 Pareto frontiers total

Then performs:
  1. Global non-dominated sorting across all 24 frontiers
  2. Configuration frequency analysis (r_j)
  3. Dimensionless parameter calculation (ΔT_HP,rel, ΔT_TES,rel^sp)

Three objectives (all maximized):
  1. Round-trip efficiency (η_P2P)
  2. Thermal energy density (E_th) [kWh/m³]
  3. Exergy efficiency (η_II)

Usage:
    python3 dc_pareto_scan.py [--n_samples N] [--seed S]

Author: CBSim project
"""

import os
import sys
import json
import time
import logging
import warnings
import argparse
import traceback
import pathlib
import platform
import subprocess
import tempfile
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import Patch
from datetime import datetime
from scipy.stats import qmc

# ── Platform detection ────────────────────────────────────────────────────────
IS_MACOS = platform.system() == 'Darwin'
# On macOS, CoolProp TTSE backend can segfault in certain edge cases.
# Subprocess isolation uses subprocess.run to call _batch_eval.py in a
# completely separate Python interpreter, so any crash (segfault or otherwise)
# only affects the child process.
# This is automatically enabled on macOS; use --no_subprocess to disable.
USE_SUBPROCESS_DEFAULT = IS_MACOS

# Path to the standalone batch evaluator script
BATCH_EVAL_SCRIPT = pathlib.Path(__file__).resolve().parent / '_batch_eval.py'

# ── Path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR  = pathlib.Path(__file__).resolve().parent
CBSIM_ROOT  = SCRIPT_DIR.parent
SRC_DIR     = CBSIM_ROOT / 'src'
RESULTS_DIR = SCRIPT_DIR / 'results'
FIGS_DIR    = SCRIPT_DIR / 'figs'
CONFIG_FILE = SCRIPT_DIR / 'dc_config.json'

sys.path.insert(0, str(SRC_DIR))
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
FIGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(SCRIPT_DIR / 'dc_pareto_scan.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

import CoolProp.CoolProp as CP
import _module_carnot_battery as CB

# ── Load configuration ────────────────────────────────────────────────────────
with open(CONFIG_FILE, 'r') as f:
    CONFIG = json.load(f)

WORKING_POINTS = CONFIG['working_points']
CONFIGURATIONS = CONFIG['configurations']
OPT_PARAMS     = CONFIG['optimization']

# ── Configuration class mapping ───────────────────────────────────────────────
CB_CLASS_MAP = {
    'SBVCHP_SBORC_STES2T': CB.SBVCHP_SBORC_STES2T,
    'SBVCHP_SRORC_STES2T': CB.SBVCHP_SRORC_STES2T,
    'SRVCHP_SBORC_STES2T': CB.SRVCHP_SBORC_STES2T,
    'SRVCHP_SRORC_STES2T': CB.SRVCHP_SRORC_STES2T,
}

# ── Fluid combinations per working point ──────────────────────────────────────
# HP fluid: Tc > T_st_ht_max + 20K
# HE fluid: Tc > T_he_cs + 20K (always satisfied for T_cs <= 25°C)
FLUID_TC = {
    'R1233zd(E)': 166.5,
    'R245fa':     153.9,
    'R600':       152.0,
    'R600a':      134.7,
    'R1234ze(E)': 109.4,
    'R227ea':     101.8,
    'R134a':      101.1,
    'R152a':      113.3,
}

HP_FLUIDS_ALL = ['R1233zd(E)', 'R245fa', 'R600', 'R600a']
HE_FLUIDS_ALL = ['R1234ze(E)', 'R227ea', 'R134a', 'R152a']

def get_fluid_combos(T_st_ht_max, T_he_cs, margin_hp=20.0, margin_he=20.0):
    """Return valid (hp_fluid, he_fluid) pairs for given temperatures."""
    valid_hp = [f for f in HP_FLUIDS_ALL if FLUID_TC[f] > T_st_ht_max + margin_hp]
    valid_he = [f for f in HE_FLUIDS_ALL if FLUID_TC[f] > T_he_cs + margin_he]
    combos = [(hp, he) for hp in valid_hp for he in valid_he]
    if not combos:
        # Relax margin if no combos found
        valid_hp = [f for f in HP_FLUIDS_ALL if FLUID_TC[f] > T_st_ht_max + 5.0]
        valid_he = [f for f in HE_FLUIDS_ALL if FLUID_TC[f] > T_he_cs + 5.0]
        combos = [(hp, he) for hp in valid_hp for he in valid_he]
    return combos

# ── Core evaluation function ──────────────────────────────────────────────────
def _evaluate_cb_worker(args):
    """
    Worker function for subprocess isolation.
    Receives a tuple of all arguments (cb_class is passed as string key).
    Returns result dict or None.
    """
    (T_hp_cs, T_he_cs, T_st_ht, dT_st_sp,
     dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, dT_hp_cd_sc,
     eta_max_cp, eta_max_ex, eta_pm,
     fluid_hp, fluid_he, cb_class_key,
     src_dir_str, opt_params) = args

    # Re-import inside subprocess (each subprocess has its own memory space)
    import sys
    sys.path.insert(0, src_dir_str)
    import CoolProp.CoolProp as CP
    import _module_carnot_battery as CB
    import warnings

    cb_class_map = {
        'SBVCHP_SBORC_STES2T': CB.SBVCHP_SBORC_STES2T,
        'SBVCHP_SRORC_STES2T': CB.SBVCHP_SRORC_STES2T,
        'SRVCHP_SBORC_STES2T': CB.SRVCHP_SBORC_STES2T,
        'SRVCHP_SRORC_STES2T': CB.SRVCHP_SRORC_STES2T,
    }
    cb_class = cb_class_map[cb_class_key]

    return evaluate_cb(
        T_hp_cs, T_he_cs, T_st_ht, dT_st_sp,
        dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, dT_hp_cd_sc,
        eta_max_cp, eta_max_ex, eta_pm,
        fluid_hp, fluid_he, cb_class,
        _CP=CP, _OPT_PARAMS=opt_params
    )


def evaluate_cb(T_hp_cs, T_he_cs, T_st_ht, dT_st_sp,
                dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, dT_hp_cd_sc,
                eta_max_cp, eta_max_ex, eta_pm,
                fluid_hp, fluid_he,
                cb_class, _CP=None, _OPT_PARAMS=None):
    """
    Evaluate a single CB configuration.
    Returns dict with results, or None on failure.
    """
    # Allow dependency injection for subprocess mode
    if _CP is None:
        import CoolProp.CoolProp as _CP
    if _OPT_PARAMS is None:
        _OPT_PARAMS = OPT_PARAMS

    try:
        p_hp_cs_su = 1e+5
        T_hp_cs_su = T_hp_cs + 273.15
        T_hp_cs_ex = max(T_hp_cs_su - dT_hp_cs_gl, 275.15)
        i_hp_cs_su = _CP.PropsSI('H', 'T', T_hp_cs_su, 'P', p_hp_cs_su, 'H2O')
        i_hp_cs_ex = _CP.PropsSI('H', 'T', T_hp_cs_ex, 'P', p_hp_cs_su, 'H2O')

        p_he_cs_su = 1e+5
        T_he_cs_su = T_he_cs + 273.15
        T_he_cs_ex = T_he_cs_su + _OPT_PARAMS['dT_he_cs_gl']
        i_he_cs_su = _CP.PropsSI('H', 'T', T_he_cs_su, 'P', p_he_cs_su, 'H2O')
        i_he_cs_ex = _CP.PropsSI('H', 'T', T_he_cs_ex, 'P', p_he_cs_su, 'H2O')

        T_st_ht_K = T_st_ht + 273.15

        params = {
            'p_hp_cs_su': p_hp_cs_su, 'i_hp_cs_su': i_hp_cs_su, 'i_hp_cs_ex': i_hp_cs_ex,
            'p_he_cs_su': p_he_cs_su, 'i_he_cs_su': i_he_cs_su, 'i_he_cs_ex': i_he_cs_ex,
            'm_hp_cs': 1.0, 'm_he_cs': 1.0,
            'p_st_ht': _OPT_PARAMS['p_st_ht'], 'p_st_lt': _OPT_PARAMS['p_st_lt'],
            'T_st_ht': T_st_ht_K, 'dT_st_sp': dT_st_sp,
            'eta_max_cp': eta_max_cp, 'eta_max_ex': eta_max_ex, 'eta_pm': eta_pm,
            'dT_hp_ev_pp': _OPT_PARAMS['dT_hp_ev_pp'],
            'dT_hp_cd_pp': _OPT_PARAMS['dT_hp_cd_pp'],
            'dT_he_ev_pp': _OPT_PARAMS['dT_he_ev_pp'],
            'dT_he_cd_pp': _OPT_PARAMS['dT_he_cd_pp'],
            'dT_he_ev_sh': dT_he_ev_sh, 'dT_hp_ev_sh': dT_hp_ev_sh,
            'dT_he_cd_sc': _OPT_PARAMS['dT_he_cd_sc'], 'dT_hp_cd_sc': dT_hp_cd_sc,
            'dp_hp_ev': 0.0, 'dp_hp_cd': 0.0, 'dp_hp_rg_lq': 0.0, 'dp_hp_rg_vp': 0.0,
            'epsilon_hp': _OPT_PARAMS['epsilon_hp'],
            'dp_he_ev': 0.0, 'dp_he_cd': 0.0, 'dp_he_rg_lq': 0.0, 'dp_he_rg_vp': 0.0,
            'epsilon_he': _OPT_PARAMS['epsilon_he'],
            'm_hp_st_max': 0.0, 'm_he_st_max': 0.0,
            'version': _OPT_PARAMS['version'],
            'mode_hp': True, 'mode_he': True, 'mode': 'source',
            'p_ref': p_he_cs_su, 'T_ref': T_he_cs_su,
            'p_0': p_he_cs_su, 'T_0': T_he_cs_su,
            'fluid_hp': fluid_hp, 'fluid_he': fluid_he,
            'fluid_st': _OPT_PARAMS['fluid_st'],
            'wet_ex': 0, 'm_rat_hp': 0, 'm_rat_he': 0,
        }
        options = {'plot_flag': False, 'print_flag': False, 'debug': False, 'exergy': True}
        inputs = (
            p_hp_cs_su, i_hp_cs_su, p_hp_cs_su, i_hp_cs_ex, 1.0, 'H2O',
            p_he_cs_su, i_he_cs_su, p_he_cs_su, i_he_cs_ex, 1.0, 'H2O',
            1e+3, 1e+3
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            my_CB = cb_class(inputs, params, options)
            my_CB.evaluate()

        if my_CB.error:
            return None

        eta_P2P   = float(my_CB.eta_cb_elec)
        E_dens_th = float(my_CB.E_dens_th) / 3.6e6  # J/m³ → kWh/m³
        eta_II    = float(my_CB.eta_cb_exer)

        if not (0.01 < eta_P2P < 2.0) or not (0.5 < E_dens_th < 5000) or not (0.001 < eta_II < 2.0):
            return None

        return {
            'eta_P2P':   eta_P2P,
            'E_dens_th': E_dens_th,
            'eta_II':    eta_II,
            'T_st_ht':   T_st_ht,
            'dT_st_sp':  dT_st_sp,
            'T_st_lt':   T_st_ht - dT_st_sp,
        }
    except Exception:
        return None

# ── Non-dominated sorting ─────────────────────────────────────────────────────
def non_dominated_sort(df, obj_cols):
    """Extract Pareto front (non-dominated solutions). All objectives maximized."""
    n = len(df)
    if n == 0:
        return df
    dominated = np.zeros(n, dtype=bool)
    obj = df[obj_cols].values
    for i in range(n):
        if dominated[i]:
            continue
        for j in range(n):
            if i == j or dominated[j]:
                continue
            # j dominates i: j >= i in all, j > i in at least one
            if np.all(obj[j] >= obj[i]) and np.any(obj[j] > obj[i]):
                dominated[i] = True
                break
    return df[~dominated].copy()

# ── Subprocess-based batch evaluator (macOS CoolProp TTSE safety) ────────────
def run_batch_subprocess(fluid_hp, fluid_he, cb_class_key, feasible_samples,
                         T_hp_cs, T_he_cs):
    """
    Run all feasible samples for one fluid combo in a completely separate
    Python interpreter via subprocess.run + _batch_eval.py.

    This is the safest isolation strategy:
    - No fork/spawn issues with multiprocessing
    - CoolProp segfault kills only the child process
    - Works correctly under nohup, redirected stdout, etc.

    Returns list of result dicts (or None for failed samples).
    """
    if not feasible_samples:
        return []

    # Write input JSON to a temp file
    input_data = {
        'fluid_hp':    fluid_hp,
        'fluid_he':    fluid_he,
        'cb_class_key': cb_class_key,
        'samples':     feasible_samples,
        'T_hp_cs':     T_hp_cs,
        'T_he_cs':     T_he_cs,
        'src_dir':     str(SRC_DIR),
        'opt_params':  OPT_PARAMS,
    }

    with tempfile.NamedTemporaryFile(
            mode='w', suffix='_in.json', delete=False) as fin:
        json.dump(input_data, fin)
        input_path = fin.name

    output_path = input_path.replace('_in.json', '_out.json')

    try:
        timeout = max(len(feasible_samples) * 5, 60)
        proc = subprocess.run(
            [sys.executable, str(BATCH_EVAL_SCRIPT), input_path, output_path],
            timeout=timeout,
            capture_output=True,
            text=True
        )
        if proc.returncode != 0 and not os.path.exists(output_path):
            # Child crashed (segfault returns non-zero)
            return [None] * len(feasible_samples)

        if os.path.exists(output_path):
            with open(output_path, 'r') as f:
                results = json.load(f)
            return results
        else:
            return [None] * len(feasible_samples)

    except subprocess.TimeoutExpired:
        return [None] * len(feasible_samples)
    except Exception:
        return [None] * len(feasible_samples)
    finally:
        # Clean up temp files
        for p in [input_path, output_path]:
            try:
                os.unlink(p)
            except Exception:
                pass


# ── LHS sampling + evaluation ─────────────────────────────────────────────────
def scan_one(wp_key, cfg_key, n_samples, seed, use_subprocess=False):
    """
    Scan one (working_point, configuration) combination.
    Returns DataFrame of Pareto-optimal solutions.
    """
    wp  = WORKING_POINTS[wp_key]
    cfg = CONFIGURATIONS[cfg_key]
    cb_class     = CB_CLASS_MAP[cfg['class']]
    cb_class_key = cfg['class']

    T_hp_cs = wp['T_hs']
    T_he_cs = wp['T_cs']
    T_st_ht_min = wp['T_st_ht_min']
    T_st_ht_max = wp['T_st_ht_max']
    dT_st_sp_min = wp['dT_st_sp_min']
    dT_st_sp_max = wp['dT_st_sp_max']

    fluid_combos = get_fluid_combos(T_st_ht_max, T_he_cs)
    if not fluid_combos:
        logger.warning(f"  [{wp_key}/{cfg_key}] No valid fluid combos found!")
        return pd.DataFrame()

    # LHS design: 9 continuous variables
    # [T_st_ht, dT_st_sp, dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh,
    #  dT_hp_cd_sc, eta_max_cp, eta_max_ex, eta_pm]
    bounds_lo = np.array([T_st_ht_min, dT_st_sp_min,  5.0,  2.0,  1.0,  5.0, 0.65, 0.65, 0.50])
    bounds_hi = np.array([T_st_ht_max, dT_st_sp_max, 20.0, 15.0, 10.0, 30.0, 0.85, 0.85, 0.75])

    n_combos = len(fluid_combos)
    n_per_combo = max(n_samples // n_combos, 50)

    all_rows = []
    n_total = 0
    n_valid = 0

    for fluid_hp, fluid_he in fluid_combos:
        rng = np.random.default_rng(seed + hash(fluid_hp + fluid_he) % 10000)
        sampler = qmc.LatinHypercube(d=9, seed=int(rng.integers(0, 99999)))
        lhs = sampler.random(n=n_per_combo)
        samples_raw = qmc.scale(lhs, bounds_lo, bounds_hi)

        # Apply feasibility pre-checks
        feasible_samples = []
        for s in samples_raw:
            T_st_ht, dT_st_sp = s[0], s[1]
            if T_st_ht - dT_st_sp < T_he_cs + 10.0:
                continue
            if T_st_ht > FLUID_TC[fluid_hp] - 10.0:
                continue
            feasible_samples.append(s.tolist())

        if use_subprocess:
            # subprocess.run mode: call _batch_eval.py in a fresh Python interpreter
            # This is the safest isolation: no fork/spawn issues, works under nohup
            batch_results = run_batch_subprocess(
                fluid_hp, fluid_he, cb_class_key,
                feasible_samples, T_hp_cs, T_he_cs
            )

            for s, result in zip(feasible_samples, batch_results):
                T_st_ht, dT_st_sp, dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, \
                    dT_hp_cd_sc, eta_max_cp, eta_max_ex, eta_pm = s
                n_total += 1
                if result is not None:
                    n_valid += 1
                    all_rows.append({
                        'wp': wp_key, 'config': cfg_key,
                        'fluid_hp': fluid_hp, 'fluid_he': fluid_he,
                        **result,
                        'T_hp_cs': T_hp_cs, 'T_he_cs': T_he_cs,
                        'dT_hp_cs_gl': dT_hp_cs_gl,
                        'dT_hp_ev_sh': dT_hp_ev_sh, 'dT_he_ev_sh': dT_he_ev_sh,
                        'dT_hp_cd_sc': dT_hp_cd_sc,
                        'eta_max_cp': eta_max_cp, 'eta_max_ex': eta_max_ex, 'eta_pm': eta_pm,
                    })
        else:
            # Direct mode (Linux): evaluate in-process
            for s in feasible_samples:
                T_st_ht, dT_st_sp, dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, \
                    dT_hp_cd_sc, eta_max_cp, eta_max_ex, eta_pm = s
                result = evaluate_cb(
                    T_hp_cs, T_he_cs, T_st_ht, dT_st_sp,
                    dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, dT_hp_cd_sc,
                    eta_max_cp, eta_max_ex, eta_pm,
                    fluid_hp, fluid_he, cb_class
                )
                n_total += 1
                if result is not None:
                    n_valid += 1
                    all_rows.append({
                        'wp': wp_key, 'config': cfg_key,
                        'fluid_hp': fluid_hp, 'fluid_he': fluid_he,
                        **result,
                        'T_hp_cs': T_hp_cs, 'T_he_cs': T_he_cs,
                        'dT_hp_cs_gl': dT_hp_cs_gl,
                        'dT_hp_ev_sh': dT_hp_ev_sh, 'dT_he_ev_sh': dT_he_ev_sh,
                        'dT_hp_cd_sc': dT_hp_cd_sc,
                        'eta_max_cp': eta_max_cp, 'eta_max_ex': eta_max_ex, 'eta_pm': eta_pm,
                    })

    logger.info(f"  [{wp_key}/{cfg_key}] {n_total} evals, {n_valid} valid ({100*n_valid/max(n_total,1):.1f}%)")

    if not all_rows:
        return pd.DataFrame()

    df_valid = pd.DataFrame(all_rows)
    df_pareto = non_dominated_sort(df_valid, ['eta_P2P', 'E_dens_th', 'eta_II'])
    logger.info(f"  [{wp_key}/{cfg_key}] Pareto front: {len(df_pareto)} solutions")
    return df_pareto

# ── Dimensionless parameter calculation ──────────────────────────────────────
def compute_dimensionless(df):
    """
    Compute dimensionless parameters for each solution:
      ΔT_HP,rel = (T_st_ht - T_hs) / (T_st_ht - T_cs)
      ΔT_TES,rel^sp = (T_st_ht - T_st_lt) / ΔT_ORC
    where ΔT_ORC = T_st_ht - T_he_cs (ORC temperature span)
    """
    df = df.copy()
    df['T_st_lt'] = df['T_st_ht'] - df['dT_st_sp']
    df['dT_HP_rel'] = (df['T_st_ht'] - df['T_hp_cs']) / (df['T_st_ht'] - df['T_he_cs'])
    df['dT_ORC']    = df['T_st_ht'] - df['T_he_cs']
    df['dT_TES_rel_sp'] = df['dT_st_sp'] / df['dT_ORC']
    return df

# ── Main scan ─────────────────────────────────────────────────────────────────
def main(n_samples=2000, seed=42, use_subprocess=None):
    # Auto-detect subprocess mode
    if use_subprocess is None:
        use_subprocess = USE_SUBPROCESS_DEFAULT

    logger.info("=" * 70)
    logger.info("DC Carnot Battery Multi-Configuration Pareto Frontier Scan")
    logger.info(f"Start: {datetime.now()}")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"Subprocess isolation: {'ENABLED' if use_subprocess else 'DISABLED'}")
    logger.info(f"Working points: {list(WORKING_POINTS.keys())}")
    logger.info(f"Configurations: {list(CONFIGURATIONS.keys())}")
    logger.info(f"Samples per combo: {n_samples}")
    logger.info("=" * 70)

    all_pareto = []
    summary = {}

    for wp_key in WORKING_POINTS:
        wp = WORKING_POINTS[wp_key]
        logger.info(f"\n{'─'*60}")
        logger.info(f"Working point: {wp_key} | {wp['label']}")
        logger.info(f"  T_hs={wp['T_hs']}°C, T_cs={wp['T_cs']}°C, ΔT={wp['delta_T']}K")
        logger.info(f"  Critical point relation: {wp['critical_point_relation']}")

        summary[wp_key] = {}

        for cfg_key in CONFIGURATIONS:
            t0 = time.time()
            df_pareto = scan_one(wp_key, cfg_key, n_samples, seed, use_subprocess=use_subprocess)
            elapsed = time.time() - t0

            if df_pareto.empty:
                logger.warning(f"  [{wp_key}/{cfg_key}] No Pareto solutions found!")
                summary[wp_key][cfg_key] = {'n_pareto': 0}
                continue

            # Compute dimensionless parameters
            df_pareto = compute_dimensionless(df_pareto)

            # Save individual Pareto front
            fname = RESULTS_DIR / f'pareto_{wp_key}_{cfg_key}.csv'
            df_pareto.to_csv(fname, index=False)

            summary[wp_key][cfg_key] = {
                'n_pareto':     len(df_pareto),
                'eta_P2P_max':  float(df_pareto['eta_P2P'].max()),
                'eta_P2P_mean': float(df_pareto['eta_P2P'].mean()),
                'E_dens_max':   float(df_pareto['E_dens_th'].max()),
                'eta_II_max':   float(df_pareto['eta_II'].max()),
                'elapsed_s':    round(elapsed, 1),
            }
            all_pareto.append(df_pareto)

    # ── Global non-dominated sorting ──────────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info("GLOBAL NON-DOMINATED SORTING")
    logger.info(f"{'='*60}")

    if not all_pareto:
        logger.error("No Pareto solutions found across all combinations!")
        return

    df_all = pd.concat(all_pareto, ignore_index=True)
    logger.info(f"Total solutions before global NDS: {len(df_all)}")

    df_global = non_dominated_sort(df_all, ['eta_P2P', 'E_dens_th', 'eta_II'])
    logger.info(f"Global Pareto front size: {len(df_global)}")

    # Save global Pareto front
    df_global.to_csv(RESULTS_DIR / 'global_pareto.csv', index=False)
    df_all.to_csv(RESULTS_DIR / 'all_pareto_combined.csv', index=False)

    # ── Configuration frequency analysis ─────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info("CONFIGURATION FREQUENCY ANALYSIS")
    logger.info(f"{'='*60}")

    config_counts = df_global['config'].value_counts()
    total_global  = len(df_global)
    config_ratio  = {}

    for cfg_key in CONFIGURATIONS:
        count = config_counts.get(cfg_key, 0)
        ratio = count / total_global if total_global > 0 else 0
        config_ratio[cfg_key] = {'count': int(count), 'ratio': float(ratio)}
        logger.info(f"  {cfg_key:20s}: {count:3d} / {total_global} = {ratio*100:.1f}%")

    # ── Working point frequency analysis ─────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info("WORKING POINT FREQUENCY ANALYSIS")
    logger.info(f"{'='*60}")

    wp_counts = df_global['wp'].value_counts()
    wp_ratio  = {}
    for wp_key in WORKING_POINTS:
        count = wp_counts.get(wp_key, 0)
        ratio = count / total_global if total_global > 0 else 0
        wp_ratio[wp_key] = {'count': int(count), 'ratio': float(ratio)}
        logger.info(f"  {wp_key:6s}: {count:3d} / {total_global} = {ratio*100:.1f}%")

    # ── Save summary ──────────────────────────────────────────────────────────
    result_summary = {
        'n_global_pareto': total_global,
        'config_ratio': config_ratio,
        'wp_ratio': wp_ratio,
        'per_wp_config': summary,
    }
    with open(RESULTS_DIR / 'dc_optimization_summary.json', 'w') as f:
        json.dump(result_summary, f, indent=2, ensure_ascii=False)

    logger.info(f"\nScan complete: {datetime.now()}")
    logger.info(f"Results saved to: {RESULTS_DIR}")

    # ── Generate plots ────────────────────────────────────────────────────────
    logger.info("\nGenerating plots...")
    generate_plots(df_all, df_global, config_ratio, wp_ratio, summary)
    logger.info("Done.")

# ── Plotting ──────────────────────────────────────────────────────────────────
CONFIG_COLORS = {
    'SBVCHP_SBORC': '#2196F3',   # Blue
    'SBVCHP_SRORC': '#4CAF50',   # Green
    'SRVCHP_SBORC': '#FF9800',   # Orange
    'SRVCHP_SRORC': '#E91E63',   # Pink/Red
}
CONFIG_MARKERS = {
    'SBVCHP_SBORC': 'o',
    'SBVCHP_SRORC': 's',
    'SRVCHP_SBORC': '^',
    'SRVCHP_SRORC': 'D',
}
WP_COLORS = {
    'DC-A': '#1565C0',
    'DC-B': '#42A5F5',
    'DC-C': '#2E7D32',
    'DC-D': '#66BB6A',
    'DC-E': '#E65100',
    'DC-F': '#FFA726',
}

def generate_plots(df_all, df_global, config_ratio, wp_ratio, summary):
    """Generate all analysis plots."""

    # ── Plot 1: Global Pareto front (3 projections) ───────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle('Global Pareto Frontier — All 24 Combinations\n'
                 '(6 DC Working Points × 4 Configurations)', fontsize=14, fontweight='bold')

    obj_pairs = [
        ('eta_P2P', 'E_dens_th', 'η$_{P2P}$ [%]', 'E$_{th}$ [kWh/m³]'),
        ('eta_P2P', 'eta_II',    'η$_{P2P}$ [%]', 'η$_{II}$ [%]'),
        ('E_dens_th', 'eta_II',  'E$_{th}$ [kWh/m³]', 'η$_{II}$ [%]'),
    ]

    for ax, (xc, yc, xl, yl) in zip(axes, obj_pairs):
        # Background: all valid solutions (grey)
        ax.scatter(df_all[xc]*100 if 'eta' in xc else df_all[xc],
                   df_all[yc]*100 if 'eta' in yc else df_all[yc],
                   c='lightgrey', s=8, alpha=0.3, zorder=1, label='All valid')

        # Global Pareto front colored by configuration
        for cfg_key in CONFIGURATIONS:
            mask = df_global['config'] == cfg_key
            sub  = df_global[mask]
            if sub.empty:
                continue
            xv = sub[xc] * 100 if 'eta' in xc else sub[xc]
            yv = sub[yc] * 100 if 'eta' in yc else sub[yc]
            ax.scatter(xv, yv,
                       c=CONFIG_COLORS[cfg_key],
                       marker=CONFIG_MARKERS[cfg_key],
                       s=60, alpha=0.85, zorder=3,
                       label=CONFIGURATIONS[cfg_key]['label'])

        ax.set_xlabel(xl, fontsize=11)
        ax.set_ylabel(yl, fontsize=11)
        ax.grid(True, alpha=0.3)

    handles = [Patch(facecolor=CONFIG_COLORS[k], label=CONFIGURATIONS[k]['label'])
               for k in CONFIGURATIONS]
    fig.legend(handles=handles, loc='lower center', ncol=4, fontsize=10,
               bbox_to_anchor=(0.5, -0.04))
    plt.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(FIGS_DIR / 'dc_global_pareto.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    logger.info(f"Saved: {FIGS_DIR / 'dc_global_pareto.png'}")

    # ── Plot 2: Per-working-point Pareto fronts (η_P2P vs E_th) ──────────────
    fig, axes = plt.subplots(2, 3, figsize=(18, 11))
    fig.suptitle('Pareto Frontiers per DC Working Point\n'
                 'Colored by Configuration', fontsize=14, fontweight='bold')

    for ax, wp_key in zip(axes.flat, WORKING_POINTS.keys()):
        wp = WORKING_POINTS[wp_key]
        wp_data = df_all[df_all['wp'] == wp_key]
        if wp_data.empty:
            ax.set_title(f'{wp_key} — No data')
            continue

        for cfg_key in CONFIGURATIONS:
            mask = wp_data['config'] == cfg_key
            sub  = wp_data[mask]
            if sub.empty:
                continue
            # Get Pareto front for this wp+config
            sub_p = non_dominated_sort(sub, ['eta_P2P', 'E_dens_th', 'eta_II'])
            ax.scatter(sub_p['eta_P2P']*100, sub_p['E_dens_th'],
                       c=CONFIG_COLORS[cfg_key],
                       marker=CONFIG_MARKERS[cfg_key],
                       s=50, alpha=0.85,
                       label=CONFIGURATIONS[cfg_key]['label'])

        ax.set_title(f'{wp_key}: {wp["label"]}\n'
                     f'T$_{{hs}}$={wp["T_hs"]}°C, T$_{{cs}}$={wp["T_cs"]}°C, '
                     f'ΔT={wp["delta_T"]}K ({wp["critical_point_relation"]})',
                     fontsize=9)
        ax.set_xlabel('η$_{P2P}$ [%]', fontsize=9)
        ax.set_ylabel('E$_{th}$ [kWh/m³]', fontsize=9)
        ax.grid(True, alpha=0.3)

    handles = [Patch(facecolor=CONFIG_COLORS[k], label=CONFIGURATIONS[k]['label'])
               for k in CONFIGURATIONS]
    fig.legend(handles=handles, loc='lower center', ncol=4, fontsize=10,
               bbox_to_anchor=(0.5, -0.02))
    plt.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(FIGS_DIR / 'dc_per_wp_pareto.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    logger.info(f"Saved: {FIGS_DIR / 'dc_per_wp_pareto.png'}")

    # ── Plot 3: Configuration frequency in global Pareto front ───────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('Configuration Dominance in Global Pareto Frontier', fontsize=14, fontweight='bold')

    # Pie chart: config ratio
    ax = axes[0]
    cfg_labels  = [CONFIGURATIONS[k]['label'] for k in CONFIGURATIONS]
    cfg_ratios  = [config_ratio.get(k, {}).get('ratio', 0) for k in CONFIGURATIONS]
    cfg_colors  = [CONFIG_COLORS[k] for k in CONFIGURATIONS]
    wedges, texts, autotexts = ax.pie(
        cfg_ratios, labels=None, colors=cfg_colors,
        autopct=lambda p: f'{p:.1f}%' if p > 1 else '',
        startangle=90, pctdistance=0.75,
        wedgeprops=dict(edgecolor='white', linewidth=1.5)
    )
    ax.legend(wedges, cfg_labels, loc='lower center', ncol=2,
              bbox_to_anchor=(0.5, -0.12), fontsize=9)
    ax.set_title('Configuration Ratio r_j\nin Global Pareto Front', fontsize=11)

    # Bar chart: config × working point heatmap
    ax = axes[1]
    wp_keys  = list(WORKING_POINTS.keys())
    cfg_keys = list(CONFIGURATIONS.keys())
    matrix   = np.zeros((len(cfg_keys), len(wp_keys)))

    for i, cfg_key in enumerate(cfg_keys):
        for j, wp_key in enumerate(wp_keys):
            sub = df_global[(df_global['config'] == cfg_key) & (df_global['wp'] == wp_key)]
            matrix[i, j] = len(sub)

    im = ax.imshow(matrix, cmap='YlOrRd', aspect='auto')
    ax.set_xticks(range(len(wp_keys)))
    ax.set_xticklabels(wp_keys, fontsize=10)
    ax.set_yticks(range(len(cfg_keys)))
    ax.set_yticklabels([CONFIGURATIONS[k]['label'] for k in cfg_keys], fontsize=9)
    ax.set_title('Global Pareto Solutions\nby Config × Working Point', fontsize=11)
    for i in range(len(cfg_keys)):
        for j in range(len(wp_keys)):
            ax.text(j, i, f'{int(matrix[i,j])}', ha='center', va='center',
                    fontsize=10, color='black' if matrix[i,j] < matrix.max()*0.7 else 'white')
    plt.colorbar(im, ax=ax, label='# Pareto solutions')
    plt.tight_layout()
    fig.savefig(FIGS_DIR / 'dc_config_dominance.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    logger.info(f"Saved: {FIGS_DIR / 'dc_config_dominance.png'}")

    # ── Plot 4: Dimensionless parameter analysis ──────────────────────────────
    if 'dT_HP_rel' in df_global.columns and 'dT_TES_rel_sp' in df_global.columns:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle('Dimensionless Parameter Analysis\n'
                     'Global Pareto Front Solutions', fontsize=14, fontweight='bold')

        ax = axes[0]
        for cfg_key in CONFIGURATIONS:
            mask = df_global['config'] == cfg_key
            sub  = df_global[mask]
            if sub.empty:
                continue
            ax.scatter(sub['dT_HP_rel'], sub['eta_P2P']*100,
                       c=CONFIG_COLORS[cfg_key], marker=CONFIG_MARKERS[cfg_key],
                       s=60, alpha=0.8, label=CONFIGURATIONS[cfg_key]['label'])
        ax.set_xlabel('ΔT$_{HP,rel}$ = (T$_{st,ht}$ − T$_{hs}$) / (T$_{st,ht}$ − T$_{cs}$)', fontsize=10)
        ax.set_ylabel('η$_{P2P}$ [%]', fontsize=10)
        ax.set_title('Round-trip Efficiency vs ΔT$_{HP,rel}$', fontsize=11)
        ax.grid(True, alpha=0.3)

        ax = axes[1]
        for cfg_key in CONFIGURATIONS:
            mask = df_global['config'] == cfg_key
            sub  = df_global[mask]
            if sub.empty:
                continue
            ax.scatter(sub['dT_TES_rel_sp'], sub['E_dens_th'],
                       c=CONFIG_COLORS[cfg_key], marker=CONFIG_MARKERS[cfg_key],
                       s=60, alpha=0.8, label=CONFIGURATIONS[cfg_key]['label'])
        ax.set_xlabel('ΔT$_{TES,rel}^{sp}$ = ΔT$_{TES}$ / ΔT$_{ORC}$', fontsize=10)
        ax.set_ylabel('E$_{th}$ [kWh/m³]', fontsize=10)
        ax.set_title('Energy Density vs ΔT$_{TES,rel}^{sp}$', fontsize=11)
        ax.grid(True, alpha=0.3)

        handles = [Patch(facecolor=CONFIG_COLORS[k], label=CONFIGURATIONS[k]['label'])
                   for k in CONFIGURATIONS]
        fig.legend(handles=handles, loc='lower center', ncol=4, fontsize=10,
                   bbox_to_anchor=(0.5, -0.04))
        plt.tight_layout(rect=[0, 0.06, 1, 1])
        fig.savefig(FIGS_DIR / 'dc_dimensionless_params.png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        logger.info(f"Saved: {FIGS_DIR / 'dc_dimensionless_params.png'}")

    # ── Plot 5: Performance vs ΔT (heat source temperature effect) ───────────
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle('Performance vs Heat Source–Cold Source Temperature Difference\n'
                 'Global Pareto Front Solutions', fontsize=13, fontweight='bold')

    delta_T_vals = [WORKING_POINTS[k]['delta_T'] for k in WORKING_POINTS]
    wp_keys_sorted = sorted(WORKING_POINTS.keys(), key=lambda k: WORKING_POINTS[k]['delta_T'])

    metrics = [
        ('eta_P2P',   'η$_{P2P}$ [%]',    100),
        ('E_dens_th', 'E$_{th}$ [kWh/m³]', 1),
        ('eta_II',    'η$_{II}$ [%]',       100),
    ]

    for ax, (metric, ylabel, scale) in zip(axes, metrics):
        for wp_key in wp_keys_sorted:
            wp  = WORKING_POINTS[wp_key]
            sub = df_global[df_global['wp'] == wp_key]
            if sub.empty:
                continue
            dT = wp['delta_T']
            vals = sub[metric].values * scale
            ax.scatter([dT]*len(vals), vals,
                       c=WP_COLORS[wp_key], s=50, alpha=0.7,
                       label=f'{wp_key} (ΔT={dT}K)')
            ax.plot([dT, dT], [vals.min(), vals.max()],
                    c=WP_COLORS[wp_key], lw=2, alpha=0.5)
            ax.scatter([dT], [vals.mean()],
                       c=WP_COLORS[wp_key], s=120, marker='*', zorder=5)

        ax.set_xlabel('ΔT$_{hs-cs}$ [K]', fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.grid(True, alpha=0.3)

    handles = [Patch(facecolor=WP_COLORS[k],
                     label=f'{k}: {WORKING_POINTS[k]["label"]} (ΔT={WORKING_POINTS[k]["delta_T"]}K)')
               for k in wp_keys_sorted]
    fig.legend(handles=handles, loc='lower center', ncol=3, fontsize=9,
               bbox_to_anchor=(0.5, -0.06))
    plt.tight_layout(rect=[0, 0.1, 1, 1])
    fig.savefig(FIGS_DIR / 'dc_performance_vs_deltaT.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    logger.info(f"Saved: {FIGS_DIR / 'dc_performance_vs_deltaT.png'}")

    # ── Plot 6: Fluid distribution in global Pareto ───────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('Working Fluid Distribution in Global Pareto Front', fontsize=13, fontweight='bold')

    for ax, fluid_col, title in zip(axes,
                                     ['fluid_hp', 'fluid_he'],
                                     ['HP Fluid Distribution', 'HE Fluid Distribution']):
        counts = df_global[fluid_col].value_counts()
        bars = ax.bar(counts.index, counts.values,
                      color=plt.cm.Set2(np.linspace(0, 1, len(counts))))
        ax.set_title(title, fontsize=11)
        ax.set_ylabel('Count in Global Pareto', fontsize=10)
        ax.set_xlabel('Fluid', fontsize=10)
        for bar, val in zip(bars, counts.values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                    f'{val}\n({100*val/len(df_global):.0f}%)',
                    ha='center', va='bottom', fontsize=9)
        ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    fig.savefig(FIGS_DIR / 'dc_fluid_distribution.png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    logger.info(f"Saved: {FIGS_DIR / 'dc_fluid_distribution.png'}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='DC Carnot Battery Pareto Frontier Scan',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Linux (fast, direct evaluation):
  python dc_pareto_scan.py

  # macOS (subprocess isolation, slower but crash-safe):
  python dc_pareto_scan.py  # auto-detects macOS

  # macOS with fewer samples for quick test:
  python dc_pareto_scan.py --n_samples 100

  # Force disable subprocess isolation:
  python dc_pareto_scan.py --no_subprocess
"""
    )
    parser.add_argument('--n_samples', type=int, default=OPT_PARAMS['n_samples'],
                        help='Number of LHS samples per fluid combo (default: %(default)s)')
    parser.add_argument('--seed', type=int, default=OPT_PARAMS['seed'],
                        help='Random seed (default: %(default)s)')
    parser.add_argument('--no_subprocess', action='store_true',
                        help='Disable subprocess isolation (faster but may crash on macOS)')
    parser.add_argument('--subprocess', action='store_true',
                        help='Force enable subprocess isolation (default on macOS)')
    args = parser.parse_args()

    # Determine subprocess mode
    if args.no_subprocess:
        use_subprocess = False
    elif args.subprocess:
        use_subprocess = True
    else:
        use_subprocess = USE_SUBPROCESS_DEFAULT

    if use_subprocess:
        logger.info(f"macOS detected ({platform.machine()}): subprocess isolation ENABLED")
        logger.info("Note: subprocess mode is ~3-5x slower but crash-safe.")
        logger.info("Use --no_subprocess to disable (risk: segfault on some fluid combos).")
    else:
        logger.info("Subprocess isolation DISABLED (Linux/direct mode).")

    main(n_samples=args.n_samples, seed=args.seed, use_subprocess=use_subprocess)
