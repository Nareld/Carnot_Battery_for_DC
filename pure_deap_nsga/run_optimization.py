#!/usr/bin/env python3
"""
Main runner: DEAP-based Pareto optimization for DC Carnot Battery systems.

Reads config from optimization_config.json, runs NSGA-II/NSGA-III for each
(working_point × configuration × fluid_combo), saves results to results/.

Usage:
    python3 run_optimization.py [--config optimization_config.json]
                                [--wp DC-A]          # single working point
                                [--cfg SBVCHP_SBORC] # single CB config
                                [--seed 42]
                                [--verbose]
"""

import os
import sys
import json
import time
import logging
import argparse
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product

SCRIPT_DIR = Path(__file__).resolve().parent
CBSIM_ROOT = SCRIPT_DIR.parent
SRC_DIR    = CBSIM_ROOT / 'src'
sys.path.insert(0, str(SRC_DIR))

from deap_optimizer import CBEvaluator, NSGAOptimizer, OBJECTIVE_MAP

RESULTS_DIR = SCRIPT_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(SCRIPT_DIR / 'optimization.log'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


def load_config(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def get_fluid_combos(wp_cfg: dict, fluid_candidates: dict) -> list:
    """
    Filter valid fluid combinations for a working point.
    HP fluid: Tc > T_st_ht_max + 20 K
    HE fluid: Tc > T_he_cs + 20 K  (T_he_cs = T_cs)
    """
    T_st_ht_max = wp_cfg['T_st_ht_max']
    T_he_cs     = wp_cfg['T_cs']

    valid = []
    for hp_name, hp_info in fluid_candidates['hp_fluids'].items():
        if hp_info['Tc_C'] < T_st_ht_max + 20.0:
            continue
        for he_name, he_info in fluid_candidates['he_fluids'].items():
            if he_info['Tc_C'] < T_he_cs + 20.0:
                continue
            valid.append((hp_name, he_name))
    return valid


def run_single(wp_key: str, wp_cfg: dict,
               cb_key: str, cb_cfg: dict,
               fluid_hp: str, fluid_he: str,
               opt_cfg: dict, fluid_candidates: dict,
               algorithm: str, seed: int,
               verbose: bool) -> pd.DataFrame:
    """Run optimization for one (wp, cb_config, fluid_combo) combination."""

    label = f'{wp_key}_{cb_key}_{fluid_hp}+{fluid_he}'
    logger.info(f'\n{"="*65}')
    logger.info(f'  {label}')
    logger.info(f'  T_hs={wp_cfg["T_hs"]}°C  T_cs={wp_cfg["T_cs"]}°C  '
                f'ΔT={wp_cfg["delta_T"]}K')
    logger.info(f'  CB class: {cb_cfg["class"]}')
    logger.info(f'  Fluids: HP={fluid_hp}  HE={fluid_he}')
    logger.info(f'{"="*65}')

    evaluator = CBEvaluator(
        wp            = wp_cfg,
        cfg           = opt_cfg,
        cb_class_name = cb_cfg['class'],
        fluid_hp      = fluid_hp,
        fluid_he      = fluid_he,
        objectives    = opt_cfg['objectives'],
        economic_params = opt_cfg.get('economic_params'),
    )

    optimizer = NSGAOptimizer(
        evaluator  = evaluator,
        algorithm  = algorithm,
        pop_size   = opt_cfg['population_size'],
        n_gen      = opt_cfg['n_generations'],
        cx_prob    = opt_cfg.get('crossover_prob', 0.9),
        mut_prob   = opt_cfg.get('mutation_prob', 0.1),
        seed       = seed,
    )

    t0 = time.time()
    pareto_front, logbook = optimizer.run(verbose=verbose)
    elapsed = time.time() - t0

    logger.info(f'  Done in {elapsed:.1f}s | Pareto front size: {len(pareto_front)}')

    if not pareto_front:
        logger.warning(f'  No feasible solutions found for {label}')
        return pd.DataFrame()

    df = optimizer.results_to_dataframe(pareto_front)
    df['wp']       = wp_key
    df['cb_config']= cb_key
    df['fluid_hp'] = fluid_hp
    df['fluid_he'] = fluid_he
    df['label']    = wp_cfg.get('label', wp_key)

    return df


def main():
    parser = argparse.ArgumentParser(description='DEAP NSGA optimizer for CBSim')
    parser.add_argument('--config',  default='optimization_config.json',
                        help='Path to config JSON')
    parser.add_argument('--wp',      default=None,
                        help='Single working point key (e.g. DC-A)')
    parser.add_argument('--cfg',     default=None,
                        help='Single CB config key (e.g. SBVCHP_SBORC)')
    parser.add_argument('--seed',    type=int, default=None)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    config_path = SCRIPT_DIR / args.config
    if not config_path.exists():
        config_path = CBSIM_ROOT / 'simulation_notes' / 'dc_config.json'
    config = load_config(config_path)

    opt_cfg          = config['optimization']
    fluid_candidates = config['fluid_candidates']
    algorithm        = opt_cfg.get('algorithm', 'NSGA2')
    seed             = args.seed if args.seed is not None else opt_cfg.get('seed', 42)

    # Select working points
    wp_keys = [args.wp] if args.wp else list(config['working_points'].keys())
    cb_keys = [args.cfg] if args.cfg else list(config['configurations'].keys())

    all_results = []
    t_total = time.time()

    for wp_key in wp_keys:
        wp_cfg = config['working_points'][wp_key]
        fluid_combos = get_fluid_combos(wp_cfg, fluid_candidates)

        if not fluid_combos:
            logger.warning(f'No valid fluid combos for {wp_key}, skipping.')
            continue

        for cb_key in cb_keys:
            cb_cfg = config['configurations'][cb_key]

            for fluid_hp, fluid_he in fluid_combos:
                df = run_single(
                    wp_key, wp_cfg, cb_key, cb_cfg,
                    fluid_hp, fluid_he,
                    opt_cfg, fluid_candidates,
                    algorithm, seed, args.verbose,
                )
                if not df.empty:
                    all_results.append(df)
                    # Save per-combination result
                    fname = f'pareto_{wp_key}_{cb_key}_{fluid_hp}_{fluid_he}.csv'
                    df.to_csv(RESULTS_DIR / fname, index=False)

    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        combined.to_csv(RESULTS_DIR / 'all_pareto_combined.csv', index=False)
        logger.info(f'\nTotal solutions: {len(combined)} across '
                    f'{len(all_results)} combinations')

    logger.info(f'Total time: {time.time()-t_total:.1f}s')


if __name__ == '__main__':
    main()
