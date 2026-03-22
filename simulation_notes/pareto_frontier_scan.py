#!/usr/bin/env python3
"""
Carnot Battery Pareto Frontier Scanning Script
================================================
Latin Hypercube Sampling + Non-Dominated Sorting for Pareto frontier analysis.

This script performs Pareto frontier scanning for a Carnot Battery (CB) system
using Latin Hypercube Sampling (LHS) followed by non-dominated sorting to
extract the Pareto front. This approach is more robust than NSGA-II when
dealing with thermodynamic models that may fail for certain parameter combinations.

Three objectives (all maximized):
    1. Round-trip efficiency (eta_P2P)
    2. Thermal energy density (E_dens_th) [kWh/m³]
    3. Second-law (exergy) efficiency (eta_II)

Four operating positions:
    Position 1: T_hs=15°C, T_cs=15°C  (ΔT=0 K)
    Position 2: T_hs=40°C, T_cs=30°C  (ΔT=10 K)
    Position 3: T_hs=60°C, T_cs=15°C  (ΔT=45 K)
    Position 4: T_hs=100°C, T_cs=15°C (ΔT=85 K)

Usage:
    python3 pareto_frontier_scan.py [--n_samples N] [--seed SEED]

Requirements:
    CoolProp >= 7.2.0, scipy >= 1.11, numpy, pandas, matplotlib
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
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from scipy.stats import qmc

# ── Path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR  = pathlib.Path(__file__).resolve().parent
CBSIM_ROOT  = SCRIPT_DIR.parent
SRC_DIR     = CBSIM_ROOT / 'src'
RESULTS_DIR = SCRIPT_DIR / 'results'
FIGS_DIR    = SCRIPT_DIR / 'figs'

sys.path.insert(0, str(SRC_DIR))
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
FIGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(SCRIPT_DIR / 'pareto_frontier_scan.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

import CoolProp.CoolProp as CP
import _module_carnot_battery as CB

# ── Validated fluid combinations ──────────────────────────────────────────────
# These fluid pairs have been validated to work stably with CBSim.
# HP fluid: must have Tc > T_st_ht + 20K
# HE fluid: must have Tc > T_he_cs + 20K
#
# Fluid selection rationale:
# - R1233zd(E): HCFO, Tc=166.5°C, low-GWP (GWP=1), excellent HP fluid for T_st<140°C
# - R245fa:     HFC,  Tc=153.9°C, widely used in ORC/HP applications
# - R1234ze(E): HFO,  Tc=109.4°C, low-GWP (GWP<1), excellent ORC fluid
# - R227ea:     HFC,  Tc=101.8°C, suitable for low-temperature ORC
# - R134a:      HFC,  Tc=101.1°C, reference fluid, widely characterized
# - R152a:      HFC,  Tc=113.3°C, lower GWP than R134a
# - R600a:      HC,   Tc=134.7°C, natural refrigerant (isobutane)

FLUID_COMBOS = {
    'position1': [  # T_hs=15°C, T_st_max=120°C → HP Tc>140°C
        ('R1233zd(E)', 'R1234ze(E)'),
        ('R1233zd(E)', 'R227ea'),
        ('R1233zd(E)', 'R134a'),
        ('R245fa',     'R1234ze(E)'),
        ('R245fa',     'R227ea'),
        ('R245fa',     'R134a'),
    ],
    'position2': [  # T_hs=40°C, T_st_max=130°C → HP Tc>150°C
        ('R1233zd(E)', 'R1234ze(E)'),
        ('R1233zd(E)', 'R227ea'),
        ('R1233zd(E)', 'R134a'),
        ('R245fa',     'R1234ze(E)'),
        ('R245fa',     'R227ea'),
    ],
    'position3': [  # T_hs=60°C, T_st_max=130°C → HP Tc>150°C
        ('R1233zd(E)', 'R1234ze(E)'),
        ('R1233zd(E)', 'R227ea'),
        ('R1233zd(E)', 'R134a'),
        ('R245fa',     'R1234ze(E)'),
        ('R245fa',     'R227ea'),
    ],
    'position4': [  # T_hs=100°C, T_st_max=120°C → HP Tc>140°C
        ('R1233zd(E)', 'R1234ze(E)'),
        ('R1233zd(E)', 'R227ea'),
        ('R1233zd(E)', 'R134a'),
        ('R245fa',     'R1234ze(E)'),
        ('R245fa',     'R227ea'),
    ],
}

# ── Operating positions ────────────────────────────────────────────────────────
POSITIONS = {
    'position1': {
        'name': 'Position 1',
        'T_hp_cs': 15.0,
        'T_he_cs': 15.0,
        'description': 'T_hs=15°C, T_cs=15°C (ΔT=0 K)',
        'T_st_ht_min': 40.0,
        'T_st_ht_max': 120.0,
        'dT_st_sp_min': 20.0,
        'dT_st_sp_max': 70.0,
    },
    'position2': {
        'name': 'Position 2',
        'T_hp_cs': 40.0,
        'T_he_cs': 30.0,
        'description': 'T_hs=40°C, T_cs=30°C (ΔT=10 K)',
        'T_st_ht_min': 55.0,
        'T_st_ht_max': 130.0,
        'dT_st_sp_min': 20.0,
        'dT_st_sp_max': 70.0,
    },
    'position3': {
        'name': 'Position 3',
        'T_hp_cs': 60.0,
        'T_he_cs': 15.0,
        'description': 'T_hs=60°C, T_cs=15°C (ΔT=45 K)',
        'T_st_ht_min': 75.0,
        'T_st_ht_max': 130.0,
        'dT_st_sp_min': 20.0,
        'dT_st_sp_max': 70.0,
    },
    'position4': {
        'name': 'Position 4',
        'T_hp_cs': 100.0,
        'T_he_cs': 15.0,
        'description': 'T_hs=100°C, T_cs=15°C (ΔT=85 K)',
        'T_st_ht_min': 110.0,
        'T_st_ht_max': 120.0,
        'dT_st_sp_min': 10.0,
        'dT_st_sp_max': 40.0,
    },
}

# ── Fixed parameters ──────────────────────────────────────────────────────────
FIXED = {
    'dT_he_cs_gl': 10.0,
    'dT_hp_ev_pp': 5.0,
    'dT_hp_cd_pp': 3.0,
    'dT_he_ev_pp': 3.0,
    'dT_he_cd_pp': 5.0,
    'dT_he_cd_sc': 3.0,
    'p_st_ht': 2.5e+5,
    'p_st_lt': 2.5e+5,
    'epsilon': 0.80,
    'fluid_hp_cs': 'H2O',
    'fluid_he_cs': 'H2O',
    'fluid_st': 'H2O',
    'version': 'thermodynamic_full',
}


def evaluate_single(T_hp_cs, T_he_cs, T_st_ht, dT_st_sp,
                    dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, dT_hp_cd_sc,
                    eta_max_cp, eta_max_ex, eta_pm,
                    fluid_hp, fluid_he):
    """
    Evaluate a single CB configuration.
    Returns dict with results, or None on failure.
    """
    try:
        p_hp_cs_su = 1e+5
        T_hp_cs_su = T_hp_cs + 273.15
        T_hp_cs_ex = max(T_hp_cs_su - dT_hp_cs_gl, 275.15)
        i_hp_cs_su = CP.PropsSI('H', 'T', T_hp_cs_su, 'P', p_hp_cs_su, 'H2O')
        i_hp_cs_ex = CP.PropsSI('H', 'T', T_hp_cs_ex, 'P', p_hp_cs_su, 'H2O')

        p_he_cs_su = 1e+5
        T_he_cs_su = T_he_cs + 273.15
        T_he_cs_ex = T_he_cs_su + FIXED['dT_he_cs_gl']
        i_he_cs_su = CP.PropsSI('H', 'T', T_he_cs_su, 'P', p_he_cs_su, 'H2O')
        i_he_cs_ex = CP.PropsSI('H', 'T', T_he_cs_ex, 'P', p_he_cs_su, 'H2O')

        T_st_ht_K = T_st_ht + 273.15

        params = {
            'p_hp_cs_su': p_hp_cs_su, 'i_hp_cs_su': i_hp_cs_su, 'i_hp_cs_ex': i_hp_cs_ex,
            'p_he_cs_su': p_he_cs_su, 'i_he_cs_su': i_he_cs_su, 'i_he_cs_ex': i_he_cs_ex,
            'm_hp_cs': 1.0, 'm_he_cs': 1.0,
            'p_st_ht': FIXED['p_st_ht'], 'p_st_lt': FIXED['p_st_lt'],
            'T_st_ht': T_st_ht_K, 'dT_st_sp': dT_st_sp,
            'eta_max_cp': eta_max_cp, 'eta_max_ex': eta_max_ex, 'eta_pm': eta_pm,
            'dT_hp_ev_pp': FIXED['dT_hp_ev_pp'], 'dT_hp_cd_pp': FIXED['dT_hp_cd_pp'],
            'dT_he_ev_pp': FIXED['dT_he_ev_pp'], 'dT_he_cd_pp': FIXED['dT_he_cd_pp'],
            'dT_he_ev_sh': dT_he_ev_sh, 'dT_hp_ev_sh': dT_hp_ev_sh,
            'dT_he_cd_sc': FIXED['dT_he_cd_sc'], 'dT_hp_cd_sc': dT_hp_cd_sc,
            'dp_hp_ev': 0.0, 'dp_hp_cd': 0.0, 'dp_hp_rg_lq': 0.0, 'dp_hp_rg_vp': 0.0,
            'epsilon_hp': FIXED['epsilon'],
            'dp_he_ev': 0.0, 'dp_he_cd': 0.0, 'dp_he_rg_lq': 0.0, 'dp_he_rg_vp': 0.0,
            'epsilon_he': FIXED['epsilon'],
            'm_hp_st_max': 0.0, 'm_he_st_max': 0.0, 'version': FIXED['version'],
            'mode_hp': True, 'mode_he': True, 'mode': 'source',
            'p_ref': p_he_cs_su, 'T_ref': T_he_cs_su, 'p_0': p_he_cs_su, 'T_0': T_he_cs_su,
            'fluid_hp': fluid_hp, 'fluid_he': fluid_he, 'fluid_st': FIXED['fluid_st'],
            'wet_ex': 0, 'm_rat_hp': 0, 'm_rat_he': 0,
        }
        options = {'plot_flag': False, 'print_flag': False, 'debug': False, 'exergy': True}
        inputs = (p_hp_cs_su, i_hp_cs_su, p_hp_cs_su, i_hp_cs_ex, 1.0, 'H2O',
                  p_he_cs_su, i_he_cs_su, p_he_cs_su, i_he_cs_ex, 1.0, 'H2O',
                  1e+3, 1e+3)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            my_CB = CB.SBVCHP_SBORC_STES2T(inputs, params, options)
            my_CB.evaluate()

        if my_CB.error:
            return None

        eta_P2P   = float(my_CB.eta_cb_elec)
        E_dens_th = float(my_CB.E_dens_th) / 3.6e6
        eta_II    = float(my_CB.eta_cb_exer)

        if not (0.01 < eta_P2P < 1.0) or not (0.1 < E_dens_th < 5000) or not (0.01 < eta_II < 1.0):
            return None

        return {
            'eta_P2P': eta_P2P,
            'E_dens_th': E_dens_th,
            'eta_II': eta_II,
        }

    except Exception:
        return None


def non_dominated_sort(df, obj_cols):
    """
    Extract Pareto front using non-dominated sorting.
    Returns DataFrame with only non-dominated solutions.
    """
    n = len(df)
    dominated = np.zeros(n, dtype=bool)
    obj = df[obj_cols].values

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            # j dominates i if j is >= i in all objectives and > in at least one
            if np.all(obj[j] >= obj[i]) and np.any(obj[j] > obj[i]):
                dominated[i] = True
                break

    return df[~dominated].copy()


def scan_position(position_key, n_samples=1000, seed=42):
    """
    Scan a position using LHS + non-dominated sorting.
    Returns DataFrame with Pareto-optimal solutions.
    """
    pos = POSITIONS[position_key]
    T_hp_cs     = pos['T_hp_cs']
    T_he_cs     = pos['T_he_cs']
    T_st_ht_min = pos['T_st_ht_min']
    T_st_ht_max = pos['T_st_ht_max']
    dT_st_sp_min = pos['dT_st_sp_min']
    dT_st_sp_max = pos['dT_st_sp_max']
    fluid_combos = FLUID_COMBOS[position_key]

    logger.info(f"\n{'='*65}")
    logger.info(f"  {pos['name']} | n_samples={n_samples} × {len(fluid_combos)} combos")
    logger.info(f"  {pos['description']}")
    logger.info(f"  T_st_ht: [{T_st_ht_min:.0f}, {T_st_ht_max:.0f}] °C")
    logger.info(f"  Fluid combos: {fluid_combos}")
    logger.info(f"{'='*65}")

    t0 = time.time()
    all_records = []
    n_total = 0
    n_valid = 0
    n_error = 0

    # LHS sampling for continuous parameters
    # Variables: T_st_ht, dT_st_sp, dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh,
    #            dT_hp_cd_sc, eta_max_cp, eta_max_ex, eta_pm
    sampler = qmc.LatinHypercube(d=9, seed=seed)
    lhs = sampler.random(n=n_samples)

    # Scale to parameter bounds
    lb = np.array([T_st_ht_min, dT_st_sp_min, 0.0,  3.0,  0.5, 15.0, 0.70, 0.70, 0.45])
    ub = np.array([T_st_ht_max, dT_st_sp_max, 20.0, 15.0, 3.0, 50.0, 0.80, 0.80, 0.55])
    samples = lb + lhs * (ub - lb)

    for fhp, fhe in fluid_combos:
        combo_valid = 0
        for i, s in enumerate(samples):
            T_st_ht, dT_st_sp, dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, \
            dT_hp_cd_sc, eta_max_cp, eta_max_ex, eta_pm = s

            # Quick pre-check: T_st_ht must be > T_hp_cs + 5K
            if T_st_ht <= T_hp_cs + 5.0:
                n_error += 1
                n_total += 1
                continue

            n_total += 1
            result = evaluate_single(
                T_hp_cs, T_he_cs, T_st_ht, dT_st_sp,
                dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, dT_hp_cd_sc,
                eta_max_cp, eta_max_ex, eta_pm, fhp, fhe
            )

            if result is not None:
                n_valid += 1
                combo_valid += 1
                all_records.append({
                    **result,
                    'T_st_ht':      T_st_ht,
                    'dT_st_sp':     dT_st_sp,
                    'dT_hp_cs_gl':  dT_hp_cs_gl,
                    'dT_hp_ev_sh':  dT_hp_ev_sh,
                    'dT_he_ev_sh':  dT_he_ev_sh,
                    'dT_hp_cd_sc':  dT_hp_cd_sc,
                    'eta_max_cp':   eta_max_cp,
                    'eta_max_ex':   eta_max_ex,
                    'eta_pm':       eta_pm,
                    'fluid_hp':     fhp,
                    'fluid_he':     fhe,
                    'position':     position_key,
                    'T_hp_cs':      T_hp_cs,
                    'T_he_cs':      T_he_cs,
                })
            else:
                n_error += 1

        logger.info(f"  {fhp:15s} + {fhe:15s}: {combo_valid}/{n_samples} valid")

    logger.info(f"  Total: {n_total} evals, {n_valid} valid ({n_valid/n_total*100:.1f}%), "
                f"{n_error} errors, {time.time()-t0:.1f}s")

    if len(all_records) == 0:
        logger.warning(f"  No valid solutions for {position_key}!")
        return pd.DataFrame()

    df_all = pd.DataFrame(all_records)

    # Extract Pareto front
    obj_cols = ['eta_P2P', 'E_dens_th', 'eta_II']
    df_pareto = non_dominated_sort(df_all, obj_cols)
    logger.info(f"  Pareto front: {len(df_pareto)} solutions (from {len(df_all)} valid)")

    return df_pareto


def plot_pareto_2d(all_results, output_dir):
    """2D Pareto front projections."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Carnot Battery Pareto Frontier Analysis\n'
                 'LHS Sampling + Non-Dominated Sorting (3 Objectives)',
                 fontsize=13, fontweight='bold')

    colors  = {'position1': '#2196F3', 'position2': '#4CAF50',
               'position3': '#FF9800', 'position4': '#F44336'}
    markers = {'position1': 'o', 'position2': 's', 'position3': '^', 'position4': 'D'}

    def scatter_all(ax, xcol, ycol, xlabel, ylabel, title, xscale=1, yscale=1):
        for pk, df in all_results.items():
            if len(df) > 0:
                ax.scatter(df[xcol]*xscale, df[ycol]*yscale,
                           c=colors[pk], marker=markers[pk], alpha=0.75, s=50,
                           label=POSITIONS[pk]['name'])
        ax.set_xlabel(xlabel, fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_title(title, fontsize=12)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    scatter_all(axes[0,0], 'eta_P2P', 'E_dens_th',
                'η$_{P2P}$ [%]', 'E$_{th}$ [kWh/m³]',
                'Round-trip Efficiency vs Energy Density', xscale=100)
    scatter_all(axes[0,1], 'eta_P2P', 'eta_II',
                'η$_{P2P}$ [%]', 'η$_{II}$ [%]',
                'Round-trip Efficiency vs Exergy Efficiency',
                xscale=100, yscale=100)
    scatter_all(axes[1,0], 'E_dens_th', 'eta_II',
                'E$_{th}$ [kWh/m³]', 'η$_{II}$ [%]',
                'Energy Density vs Exergy Efficiency', yscale=100)

    # Summary bar chart
    ax = axes[1, 1]
    pos_labels = [POSITIONS[pk]['name'] for pk in all_results]
    eta_p2p_max = [all_results[pk]['eta_P2P'].max()*100 if len(all_results[pk]) > 0 else 0
                   for pk in all_results]
    eta_ii_max  = [all_results[pk]['eta_II'].max()*100  if len(all_results[pk]) > 0 else 0
                   for pk in all_results]
    e_dens_max  = [all_results[pk]['E_dens_th'].max()   if len(all_results[pk]) > 0 else 0
                   for pk in all_results]

    x = np.arange(len(pos_labels))
    w = 0.25
    ax.bar(x - w, eta_p2p_max, w, label='Max η$_{P2P}$ [%]', color='#2196F3', alpha=0.8)
    ax.bar(x,     eta_ii_max,  w, label='Max η$_{II}$ [%]',  color='#4CAF50', alpha=0.8)
    ax2 = ax.twinx()
    ax2.bar(x + w, e_dens_max, w, label='Max E$_{th}$ [kWh/m³]', color='#FF9800', alpha=0.8)
    ax2.set_ylabel('Max E$_{th}$ [kWh/m³]', color='#FF9800', fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(pos_labels, fontsize=9)
    ax.set_title('Maximum Achievable Performance per Position', fontsize=11)
    ax.grid(True, alpha=0.3)
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8)

    plt.tight_layout()
    fig_path = output_dir / 'pareto_frontier_main.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved: {fig_path}")


def plot_fluid_distribution(all_results, output_dir):
    """Working fluid distribution in Pareto solutions."""
    fig, axes = plt.subplots(2, 4, figsize=(18, 8))
    fig.suptitle('Working Fluid Distribution in Pareto Front Solutions',
                 fontsize=12, fontweight='bold')

    for col, (pk, df) in enumerate(all_results.items()):
        pos = POSITIONS[pk]
        for row, (fluid_col, title) in enumerate([('fluid_hp', 'HP Fluid'),
                                                   ('fluid_he', 'HE Fluid')]):
            ax = axes[row, col]
            if len(df) > 0 and fluid_col in df.columns:
                counts = df[fluid_col].value_counts().head(6)
                colors_bar = plt.cm.Blues(np.linspace(0.4, 0.9, len(counts)))
                ax.barh(range(len(counts)), counts.values, color=colors_bar, alpha=0.85)
                ax.set_yticks(range(len(counts)))
                ax.set_yticklabels(counts.index, fontsize=8)
                ax.set_xlabel('Count', fontsize=8)
                ax.set_title(f"{pos['name']}\n{title}", fontsize=9)
                ax.grid(True, alpha=0.3, axis='x')
            else:
                ax.text(0.5, 0.5, 'No data', ha='center', va='center',
                        transform=ax.transAxes)
                ax.set_title(f"{pos['name']}\n{title}", fontsize=9)

    plt.tight_layout()
    fig_path = output_dir / 'pareto_fluid_distribution.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved: {fig_path}")


def plot_conflict_analysis(all_results, output_dir):
    """Objective conflict intensity analysis."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle('Pareto Frontier Conflict Analysis\n'
                 'Trade-off between η$_{P2P}$, E$_{th}$, and η$_{II}$',
                 fontsize=12, fontweight='bold')

    pos_names = [POSITIONS[pk]['name'] for pk in all_results]
    delta_T   = [POSITIONS[pk]['T_hp_cs'] - POSITIONS[pk]['T_he_cs'] for pk in all_results]
    n_pareto  = [len(all_results[pk]) for pk in all_results]
    colors_bar = ['#2196F3', '#4CAF50', '#FF9800', '#F44336']

    ax = axes[0]
    bars = ax.bar(pos_names, n_pareto, color=colors_bar, alpha=0.8)
    ax2 = ax.twinx()
    ax2.plot(pos_names, delta_T, 'k--o', linewidth=2, markersize=8, label='ΔT [K]')
    ax2.set_ylabel('ΔT = T$_{hs}$ - T$_{cs}$ [K]', fontsize=10)
    ax2.legend(loc='upper right', fontsize=9)
    ax.set_ylabel('Pareto Front Size', fontsize=11)
    ax.set_title('Pareto Front Size vs Temperature Difference', fontsize=11)
    ax.grid(True, alpha=0.3)
    for bar, size in zip(bars, n_pareto):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                str(size), ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax = axes[1]
    obj_ranges = {'η_P2P [%]': [], 'E_th [kWh/m³]': [], 'η_II [%]': []}
    for pk, df in all_results.items():
        if len(df) > 0:
            obj_ranges['η_P2P [%]'].append((df['eta_P2P'].max() - df['eta_P2P'].min()) * 100)
            obj_ranges['E_th [kWh/m³]'].append(df['E_dens_th'].max() - df['E_dens_th'].min())
            obj_ranges['η_II [%]'].append((df['eta_II'].max() - df['eta_II'].min()) * 100)
        else:
            for k in obj_ranges:
                obj_ranges[k].append(0)

    x = np.arange(len(pos_names))
    w = 0.25
    obj_colors = ['#2196F3', '#FF9800', '#4CAF50']
    for i, (label, values) in enumerate(obj_ranges.items()):
        ax.bar(x + (i-1)*w, values, w, label=label, alpha=0.8, color=obj_colors[i])
    ax.set_xticks(x)
    ax.set_xticklabels(pos_names, fontsize=9)
    ax.set_ylabel('Objective Range', fontsize=11)
    ax.set_title('Objective Spread in Pareto Front\n(Conflict Intensity Indicator)', fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig_path = output_dir / 'pareto_conflict_analysis.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved: {fig_path}")


def plot_temperature_effect(all_results, output_dir):
    """Effect of source temperature on Pareto front."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle('Effect of Heat Source Temperature on Pareto Front Performance',
                 fontsize=12, fontweight='bold')

    T_hs_vals = [POSITIONS[pk]['T_hp_cs'] for pk in all_results]
    metrics = [
        ('eta_P2P', 100, 'η$_{P2P}$ [%]', 'Round-trip Efficiency'),
        ('E_dens_th', 1, 'E$_{th}$ [kWh/m³]', 'Thermal Energy Density'),
        ('eta_II', 100, 'η$_{II}$ [%]', 'Exergy Efficiency'),
    ]

    for ax, (col, scale, ylabel, title) in zip(axes, metrics):
        max_vals  = [all_results[pk][col].max()*scale  if len(all_results[pk]) > 0 else 0 for pk in all_results]
        mean_vals = [all_results[pk][col].mean()*scale if len(all_results[pk]) > 0 else 0 for pk in all_results]
        min_vals  = [all_results[pk][col].min()*scale  if len(all_results[pk]) > 0 else 0 for pk in all_results]

        ax.fill_between(T_hs_vals, min_vals, max_vals, alpha=0.2, color='steelblue')
        ax.plot(T_hs_vals, max_vals,  'o-',  color='#2196F3', lw=2, ms=8, label='Max',
                markerfacecolor='white', markeredgewidth=2)
        ax.plot(T_hs_vals, mean_vals, 's--', color='#FF9800', lw=2, ms=7, label='Mean')
        ax.plot(T_hs_vals, min_vals,  '^:',  color='#F44336', lw=1.5, ms=7, label='Min')
        ax.set_xlabel('T$_{hs}$ [°C]', fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_title(title, fontsize=11)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.set_xticks(T_hs_vals)
        ax.set_xticklabels([f'{t:.0f}°C' for t in T_hs_vals])

    plt.tight_layout()
    fig_path = output_dir / 'pareto_temperature_effect.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved: {fig_path}")


def plot_design_space(all_results, output_dir):
    """Design variable distributions in Pareto solutions."""
    fig, axes = plt.subplots(2, 4, figsize=(16, 8))
    fig.suptitle('Design Variable Distribution in Pareto Solutions',
                 fontsize=12, fontweight='bold')

    colors = ['#2196F3', '#4CAF50', '#FF9800', '#F44336']
    design_vars = ['T_st_ht', 'dT_st_sp', 'dT_hp_cs_gl', 'dT_hp_cd_sc',
                   'dT_hp_ev_sh', 'dT_he_ev_sh', 'eta_max_cp', 'eta_pm']
    labels = ['T$_{st,ht}$ [°C]', 'ΔT$_{st}$ [K]', 'ΔT$_{hp,cs}$ [K]', 'ΔT$_{hp,cd,sc}$ [K]',
              'ΔT$_{hp,ev,sh}$ [K]', 'ΔT$_{he,ev,sh}$ [K]', 'η$_{max,cp}$ [-]', 'η$_{pm}$ [-]']

    for i, (var, label) in enumerate(zip(design_vars, labels)):
        ax = axes[i // 4, i % 4]
        for j, (pk, df) in enumerate(all_results.items()):
            if len(df) > 0 and var in df.columns:
                ax.hist(df[var], bins=12, alpha=0.5, color=colors[j],
                        label=POSITIONS[pk]['name'], density=True)
        ax.set_xlabel(label, fontsize=9)
        ax.set_ylabel('Density', fontsize=8)
        ax.set_title(label, fontsize=9)
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend(fontsize=7)

    plt.tight_layout()
    fig_path = output_dir / 'pareto_design_space.png'
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved: {fig_path}")


def main(n_samples=500, seed=42):
    logger.info("=" * 68)
    logger.info("  Carnot Battery Pareto Frontier Scan")
    logger.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 68)
    logger.info(f"Config: n_samples={n_samples}, seed={seed}")

    all_results = {}
    for pos_key in POSITIONS:
        try:
            df = scan_position(pos_key, n_samples=n_samples, seed=seed)
            all_results[pos_key] = df
            if len(df) > 0:
                csv_path = RESULTS_DIR / f'{pos_key}_pareto.csv'
                df.to_csv(csv_path, index=False)
                logger.info(f"  Saved: {csv_path}")
        except Exception as e:
            logger.error(f"  Failed {pos_key}: {e}")
            logger.error(traceback.format_exc())
            all_results[pos_key] = pd.DataFrame()

    # Summary
    logger.info("\n" + "=" * 68)
    logger.info("  OPTIMIZATION SUMMARY")
    logger.info("=" * 68)
    summary = {}
    for pk, df in all_results.items():
        pos = POSITIONS[pk]
        if len(df) > 0:
            summary[pk] = {
                'name': pos['name'],
                'description': pos['description'],
                'T_hp_cs': pos['T_hp_cs'],
                'T_he_cs': pos['T_he_cs'],
                'delta_T': pos['T_hp_cs'] - pos['T_he_cs'],
                'n_pareto': len(df),
                'eta_P2P_max':  float(df['eta_P2P'].max()),
                'eta_P2P_min':  float(df['eta_P2P'].min()),
                'eta_P2P_mean': float(df['eta_P2P'].mean()),
                'E_dens_max':   float(df['E_dens_th'].max()),
                'E_dens_min':   float(df['E_dens_th'].min()),
                'E_dens_mean':  float(df['E_dens_th'].mean()),
                'eta_II_max':   float(df['eta_II'].max()),
                'eta_II_min':   float(df['eta_II'].min()),
                'eta_II_mean':  float(df['eta_II'].mean()),
                'top_fluid_hp': df['fluid_hp'].mode()[0] if 'fluid_hp' in df.columns else 'N/A',
                'top_fluid_he': df['fluid_he'].mode()[0] if 'fluid_he' in df.columns else 'N/A',
            }
            logger.info(f"\n{pos['name']} ({pos['description']})")
            logger.info(f"  Pareto solutions: {len(df)}")
            logger.info(f"  η_P2P:  [{df['eta_P2P'].min()*100:.2f}%, {df['eta_P2P'].max()*100:.2f}%]")
            logger.info(f"  E_th:   [{df['E_dens_th'].min():.2f}, {df['E_dens_th'].max():.2f}] kWh/m³")
            logger.info(f"  η_II:   [{df['eta_II'].min()*100:.2f}%, {df['eta_II'].max()*100:.2f}%]")
            if 'fluid_hp' in df.columns:
                logger.info(f"  Top HP fluid: {df['fluid_hp'].mode()[0]}")
                logger.info(f"  Top HE fluid: {df['fluid_he'].mode()[0]}")
        else:
            summary[pk] = {'name': pos['name'], 'n_pareto': 0}
            logger.warning(f"\n{pos['name']}: No valid solutions found")

    with open(RESULTS_DIR / 'optimization_summary.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    # Generate plots
    logger.info("\nGenerating plots...")
    for plot_fn in [plot_pareto_2d, plot_fluid_distribution,
                    plot_conflict_analysis, plot_design_space, plot_temperature_effect]:
        try:
            plot_fn(all_results, FIGS_DIR)
        except Exception as e:
            logger.error(f"Plot error ({plot_fn.__name__}): {e}")

    # Combined CSV
    non_empty = [df for df in all_results.values() if len(df) > 0]
    if non_empty:
        combined = pd.concat(non_empty, ignore_index=True)
        combined.to_csv(RESULTS_DIR / 'all_positions_pareto.csv', index=False)
        logger.info(f"\nSaved combined CSV: {RESULTS_DIR / 'all_positions_pareto.csv'}")
        logger.info(f"Total Pareto solutions: {len(combined)}")

    logger.info(f"\nScan complete: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return all_results, summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Carnot Battery Pareto Frontier Scan')
    parser.add_argument('--n_samples', type=int, default=500,
                        help='LHS samples per fluid combination (default: 500)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed (default: 42)')
    args = parser.parse_args()

    all_results, summary = main(n_samples=args.n_samples, seed=args.seed)
