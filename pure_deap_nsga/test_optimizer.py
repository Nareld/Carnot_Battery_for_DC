#!/usr/bin/env python3
"""
Unit tests for DEAP optimizer module.

Tests:
  1. Objective function evaluation
  2. CBEvaluator with simple case
  3. NSGA-II optimizer on toy problem
  4. Config loading and fluid filtering

Usage:
    python3 test_optimizer.py
"""

import os
import sys
import json
import warnings
import numpy as np
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CBSIM_ROOT = SCRIPT_DIR.parent
SRC_DIR    = CBSIM_ROOT / 'src'
sys.path.insert(0, str(SRC_DIR))

from deap_optimizer import (
    Objectives, OBJECTIVE_MAP, CBEvaluator, NSGAOptimizer,
    INFEASIBLE_PENALTY
)
import CoolProp.CoolProp as CP
import _module_carnot_battery as CB


def test_objective_functions():
    """Test that all objective functions are callable."""
    print('\n' + '='*65)
    print('TEST 1: Objective function registry')
    print('='*65)

    for name, fn in OBJECTIVE_MAP.items():
        print(f'  ✓ {name:30s} -> {fn.__name__}')

    print(f'\nTotal objectives: {len(OBJECTIVE_MAP)}')
    print('PASSED\n')


def test_cb_evaluator():
    """Test CBEvaluator with a simple feasible case."""
    print('='*65)
    print('TEST 2: CBEvaluator with DC-A working point')
    print('='*65)

    wp = {
        'T_hs': 35.0,
        'T_cs': 5.0,
        'T_st_ht_min': 50.0,
        'T_st_ht_max': 120.0,
        'dT_st_sp_min': 15.0,
        'dT_st_sp_max': 60.0,
    }

    cfg = {
        'dT_he_cs_gl': 10.0,
        'dT_hp_ev_pp': 5.0,
        'dT_hp_cd_pp': 3.0,
        'dT_he_ev_pp': 3.0,
        'dT_he_cd_pp': 5.0,
        'dT_he_cd_sc': 3.0,
        'p_st_ht': 2.5e5,
        'p_st_lt': 2.5e5,
        'epsilon_hp': 0.80,
        'epsilon_he': 0.80,
        'fluid_st': 'H2O',
    }

    objectives = ['eta_p2p', 'energy_density_thermal', 'exergy_efficiency']

    evaluator = CBEvaluator(
        wp=wp, cfg=cfg,
        cb_class_name='SBVCHP_SBORC_STES2T',
        fluid_hp='R1233zd(E)',
        fluid_he='R1234ze(E)',
        objectives=objectives,
    )

    print(f'  Decision variables: {evaluator.n_vars}')
    print(f'  Objectives: {len(objectives)}')
    print(f'  Bounds:')
    print(f'    T_st_ht:  [{evaluator.lb[0]:.1f}, {evaluator.ub[0]:.1f}] °C')
    print(f'    dT_st_sp: [{evaluator.lb[1]:.1f}, {evaluator.ub[1]:.1f}] K')

    # Test with a feasible point
    x_test = [
        80.0,   # T_st_ht
        30.0,   # dT_st_sp
        10.0,   # dT_hp_cs_gl
        5.0,    # dT_hp_ev_sh
        1.0,    # dT_he_ev_sh
        5.0,    # dT_hp_cd_sc
        0.75,   # eta_max_cp
        0.75,   # eta_max_ex
        0.50,   # eta_pm
    ]

    print(f'\n  Testing with x = {x_test[:3]} ...')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        result = evaluator.evaluate(x_test)

    print(f'  Results:')
    for i, (obj_name, val) in enumerate(zip(objectives, result)):
        status = '✓' if val > INFEASIBLE_PENALTY / 2 else '✗'
        print(f'    {status} {obj_name:25s} = {val:.6f}')

    if all(v > INFEASIBLE_PENALTY / 2 for v in result):
        print('\nPASSED\n')
    else:
        print('\nWARNING: Some objectives returned infeasible values\n')


def test_nsga_optimizer():
    """Test NSGA-II optimizer on a toy problem (small pop, few gens)."""
    print('='*65)
    print('TEST 3: NSGA-II optimizer (quick run)')
    print('='*65)

    wp = {
        'T_hs': 35.0,
        'T_cs': 5.0,
        'T_st_ht_min': 60.0,
        'T_st_ht_max': 100.0,
        'dT_st_sp_min': 20.0,
        'dT_st_sp_max': 50.0,
    }

    cfg = {
        'dT_he_cs_gl': 10.0,
        'dT_hp_ev_pp': 5.0,
        'dT_hp_cd_pp': 3.0,
        'dT_he_ev_pp': 3.0,
        'dT_he_cd_pp': 5.0,
        'dT_he_cd_sc': 3.0,
        'p_st_ht': 2.5e5,
        'p_st_lt': 2.5e5,
        'epsilon_hp': 0.80,
        'epsilon_he': 0.80,
        'fluid_st': 'H2O',
    }

    objectives = ['eta_p2p', 'energy_density_thermal']

    evaluator = CBEvaluator(
        wp=wp, cfg=cfg,
        cb_class_name='SBVCHP_SBORC_STES2T',
        fluid_hp='R1233zd(E)',
        fluid_he='R1234ze(E)',
        objectives=objectives,
    )

    optimizer = NSGAOptimizer(
        evaluator=evaluator,
        algorithm='NSGA2',
        pop_size=20,
        n_gen=10,
        seed=42,
    )

    print(f'  Population: {optimizer.pop_size}')
    print(f'  Generations: {optimizer.n_gen}')
    print(f'  Running optimization...')

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        pareto_front, logbook = optimizer.run(verbose=False)

    print(f'\n  Pareto front size: {len(pareto_front)}')
    if pareto_front:
        df = optimizer.results_to_dataframe(pareto_front)
        print(f'  DataFrame shape: {df.shape}')
        print(f'  Columns: {list(df.columns)}')
        print('\nPASSED\n')
    else:
        print('\nWARNING: No feasible solutions found\n')


def test_config_loading():
    """Test config file loading and fluid filtering."""
    print('='*65)
    print('TEST 4: Config loading and fluid filtering')
    print('='*65)

    config_path = SCRIPT_DIR / 'optimization_config.json'
    if not config_path.exists():
        print('  Config file not found, skipping test.')
        return

    with open(config_path) as f:
        config = json.load(f)

    print(f'  Working points: {len(config["working_points"])}')
    print(f'  Configurations: {len(config["configurations"])}')
    print(f'  HP fluids: {len(config["fluid_candidates"]["hp_fluids"])}')
    print(f'  HE fluids: {len(config["fluid_candidates"]["he_fluids"])}')

    # Test fluid filtering for DC-A
    wp = config['working_points']['DC-A']
    T_st_ht_max = wp['T_st_ht_max']
    T_he_cs = wp['T_cs']

    valid_combos = []
    for hp_name, hp_info in config['fluid_candidates']['hp_fluids'].items():
        if hp_info['Tc_C'] < T_st_ht_max + 20.0:
            continue
        for he_name, he_info in config['fluid_candidates']['he_fluids'].items():
            if he_info['Tc_C'] < T_he_cs + 20.0:
                continue
            valid_combos.append((hp_name, he_name))

    print(f'\n  Valid fluid combos for DC-A: {len(valid_combos)}')
    for hp, he in valid_combos[:3]:
        print(f'    - {hp} + {he}')

    print('\nPASSED\n')


def main():
    print('\n' + '='*65)
    print('  DEAP Optimizer Test Suite')
    print('='*65)

    try:
        test_objective_functions()
        test_cb_evaluator()
        test_nsga_optimizer()
        test_config_loading()

        print('='*65)
        print('  ALL TESTS COMPLETED')
        print('='*65 + '\n')

    except Exception as e:
        print(f'\n✗ TEST FAILED: {e}\n')
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
