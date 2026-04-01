#!/usr/bin/env python3
"""
DEAP-based Multi-Objective Optimization for Carnot Battery Systems
===================================================================
Direct NSGA-II/NSGA-III implementation using DEAP, without RHEIA.

Decision variables (9 continuous):
    x[0]: T_st_ht      - Hot storage temperature [°C]
    x[1]: dT_st_sp     - Storage temperature span [K]
    x[2]: dT_hp_cs_gl  - HP cold source glide [K]
    x[3]: dT_hp_ev_sh  - HP evaporator superheat [K]
    x[4]: dT_he_ev_sh  - HE evaporator superheat [K]
    x[5]: dT_hp_cd_sc  - HP condenser subcooling [K]
    x[6]: eta_max_cp   - HP compressor isentropic efficiency [-]
    x[7]: eta_max_ex   - HE expander isentropic efficiency [-]
    x[8]: eta_pm       - Pump/motor mechanical efficiency [-]

Thermodynamic hard constraint: CB solver must converge (error=False).
Infeasible solutions are penalized with large negative fitness values.

Author: CBSim project
Date: March 2026
"""

import os
import sys
import json
import time
import logging
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import random

from deap import base, creator, tools, algorithms
import CoolProp.CoolProp as CP

# ── Path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CBSIM_ROOT = SCRIPT_DIR.parent
SRC_DIR    = CBSIM_ROOT / 'src'
sys.path.insert(0, str(SRC_DIR))

import _module_carnot_battery as CB

logger = logging.getLogger(__name__)

# Penalty value for infeasible solutions
INFEASIBLE_PENALTY = -1e6


# ============================================================================
# OBJECTIVE FUNCTIONS
# ============================================================================

class Objectives:
    """
    All available objective functions.
    Each function takes a CB result object and returns a float.
    All objectives are defined as MAXIMIZATION (negate to minimize).
    """

    # ── Thermodynamic objectives ─────────────────────────────────────────────

    @staticmethod
    def eta_p2p(cb) -> float:
        """Round-trip (P2P) efficiency η_P2P = η_HP_cycle × η_HE_cycle"""
        return cb.eta_cb_elec

    @staticmethod
    def energy_density_thermal(cb) -> float:
        """Thermal energy density [kWh/m³]"""
        return cb.E_dens_th / 3.6e6

    @staticmethod
    def exergy_efficiency(cb) -> float:
        """Second-law (exergy) efficiency η_II"""
        return cb.eta_cb_exer

    @staticmethod
    def energy_density_electric(cb) -> float:
        """Electric energy density [kWh_el/m³] = E_dens_th × η_HE"""
        return cb.E_dens_el / 3.6e6

    @staticmethod
    def cop_hp(cb) -> float:
        """Heat pump coefficient of performance COP_HP"""
        return cb.my_HP.COP_hp

    @staticmethod
    def eta_he(cb) -> float:
        """Heat engine thermal efficiency η_HE"""
        return cb.my_HE.eta_he_cyclen

    @staticmethod
    def carnot_ratio(cb) -> float:
        """
        Ratio of actual P2P efficiency to Carnot limit.
        Measures how close the system is to the thermodynamic ideal.
        η_P2P / η_Carnot,  where η_Carnot = 1 - T_lt/T_ht
        """
        T_h = cb.T_st_ht  # [K]
        T_c = cb.T_st_lt  # [K]
        if T_h <= T_c:
            return INFEASIBLE_PENALTY
        eta_carnot = 1.0 - T_c / T_h
        if eta_carnot <= 1e-6:
            return INFEASIBLE_PENALTY
        return cb.eta_cb_elec / eta_carnot

    @staticmethod
    def storage_exergy_density(cb) -> float:
        """
        Exergy density of the storage [kWh_ex/m³].
        Accounts for quality of stored energy, not just quantity.
        ex = (i_ht - i_lt) - T_0*(s_ht - s_lt)
        """
        T_0 = 298.15  # Reference temperature [K]
        fluid = 'H2O'
        try:
            p_st = 2.5e5
            s_ht = CP.PropsSI('S', 'T', cb.T_st_ht, 'P', p_st, fluid)
            s_lt = CP.PropsSI('S', 'T', cb.T_st_lt, 'P', p_st, fluid)
            ex_density = (cb.i_st_ht - cb.i_st_lt) - T_0 * (s_ht - s_lt)
            V_total = cb.v_st_ht + cb.v_st_lt
            if V_total <= 0:
                return INFEASIBLE_PENALTY
            return ex_density / V_total / 3.6e6  # kWh_ex/m³
        except Exception:
            return INFEASIBLE_PENALTY

    @staticmethod
    def neg_storage_volume(cb) -> float:
        """
        Negative total storage volume [m³] — minimize volume.
        Returns -V_total so that maximizing this minimizes volume.
        """
        V_total = cb.v_st_ht + cb.v_st_lt
        if V_total <= 0:
            return INFEASIBLE_PENALTY
        return -V_total

    # ── Economic objectives (interface — requires economic_params) ────────────

    @staticmethod
    def neg_lcos(cb, econ: Dict) -> float:
        """
        Negative Levelized Cost of Storage [$/kWh] — minimize LCOS.

        Required keys in econ:
            capex_hp_per_kw    [$/kW_HP]
            capex_he_per_kw    [$/kW_HE]
            capex_storage_per_m3 [$/m³]
            opex_fraction      annual OPEX as fraction of CAPEX
            lifetime_years     system lifetime
            cycles_per_year    charge/discharge cycles per year
            discount_rate      nominal discount rate
        """
        try:
            P_hp_kw = cb.P_hp / 1e3
            P_he_kw = cb.P_he / 1e3
            V_st    = cb.v_st_ht + cb.v_st_lt

            capex = (P_hp_kw * econ['capex_hp_per_kw'] +
                     P_he_kw * econ['capex_he_per_kw'] +
                     V_st    * econ['capex_storage_per_m3'])

            r  = econ['discount_rate']
            n  = econ['lifetime_years']
            # Capital recovery factor
            crf = r * (1 + r)**n / ((1 + r)**n - 1) if r > 0 else 1.0 / n

            opex_annual = capex * econ['opex_fraction']
            annual_cost = capex * crf + opex_annual

            # Annual energy throughput [kWh_el]
            E_cycle = cb.E_dens_th * V_st / 3.6e6 * cb.eta_cb_elec
            E_annual = E_cycle * econ['cycles_per_year']
            if E_annual <= 0:
                return INFEASIBLE_PENALTY

            lcos = annual_cost / E_annual
            return -lcos  # negate: maximize → minimize cost
        except Exception:
            return INFEASIBLE_PENALTY

    @staticmethod
    def neg_specific_capex(cb, econ: Dict) -> float:
        """
        Negative specific CAPEX [$/kWh_storage] — minimize cost per kWh.
        """
        try:
            P_hp_kw = cb.P_hp / 1e3
            P_he_kw = cb.P_he / 1e3
            V_st    = cb.v_st_ht + cb.v_st_lt

            capex = (P_hp_kw * econ['capex_hp_per_kw'] +
                     P_he_kw * econ['capex_he_per_kw'] +
                     V_st    * econ['capex_storage_per_m3'])

            E_storage = cb.E_dens_th * V_st / 3.6e6  # kWh_th
            if E_storage <= 0:
                return INFEASIBLE_PENALTY

            return -(capex / E_storage)
        except Exception:
            return INFEASIBLE_PENALTY


# Map objective name → function
OBJECTIVE_MAP = {
    'eta_p2p':                Objectives.eta_p2p,
    'energy_density_thermal': Objectives.energy_density_thermal,
    'exergy_efficiency':      Objectives.exergy_efficiency,
    'energy_density_electric':Objectives.energy_density_electric,
    'cop_hp':                 Objectives.cop_hp,
    'eta_he':                 Objectives.eta_he,
    'carnot_ratio':           Objectives.carnot_ratio,
    'storage_exergy_density': Objectives.storage_exergy_density,
    'neg_storage_volume':     Objectives.neg_storage_volume,
    # Economic objectives require extra args — handled separately
    'neg_lcos':               Objectives.neg_lcos,
    'neg_specific_capex':     Objectives.neg_specific_capex,
}

ECONOMIC_OBJECTIVES = {'neg_lcos', 'neg_specific_capex'}


# ============================================================================
# CB EVALUATOR
# ============================================================================

class CBEvaluator:
    """
    Wraps the CBSim thermodynamic solver for use as an optimization oracle.
    Handles input construction, solver call, and objective extraction.
    """

    def __init__(self, wp: Dict, cfg: Dict, cb_class_name: str,
                 fluid_hp: str, fluid_he: str,
                 objectives: List[str],
                 economic_params: Optional[Dict] = None):
        """
        Parameters
        ----------
        wp : working point dict (T_hs, T_cs, T_st_ht_min/max, dT_st_sp_min/max)
        cfg : optimization fixed parameters dict
        cb_class_name : e.g. 'SBVCHP_SBORC_STES2T'
        fluid_hp / fluid_he : working fluid names
        objectives : list of objective names from OBJECTIVE_MAP
        economic_params : dict with economic parameters (for economic objectives)
        """
        self.wp             = wp
        self.cfg            = cfg
        self.cb_class       = getattr(CB, cb_class_name)
        self.fluid_hp       = fluid_hp
        self.fluid_he       = fluid_he
        self.objectives     = objectives
        self.economic_params = economic_params or {}

        self.T_hp_cs = wp['T_hs']   # °C
        self.T_he_cs = wp['T_cs']   # °C

        # Decision variable bounds
        self.lb = np.array([
            wp['T_st_ht_min'],   # T_st_ht [°C]
            wp['dT_st_sp_min'],  # dT_st_sp [K]
            0.0,                 # dT_hp_cs_gl [K]
            3.0,                 # dT_hp_ev_sh [K]
            0.5,                 # dT_he_ev_sh [K]
            0.0,                 # dT_hp_cd_sc [K]
            0.70,                # eta_max_cp [-]
            0.70,                # eta_max_ex [-]
            0.45,                # eta_pm [-]
        ])
        self.ub = np.array([
            wp['T_st_ht_max'],   # T_st_ht [°C]
            wp['dT_st_sp_max'],  # dT_st_sp [K]
            20.0,                # dT_hp_cs_gl [K]
            15.0,                # dT_hp_ev_sh [K]
            3.0,                 # dT_he_ev_sh [K]
            15.0,                # dT_hp_cd_sc [K]
            0.90,                # eta_max_cp [-]
            0.90,                # eta_max_ex [-]
            0.55,                # eta_pm [-]
        ])
        self.n_vars = len(self.lb)

    def decode(self, x: List[float]) -> Dict:
        """Decode individual vector to named parameters."""
        return {
            'T_st_ht':     x[0],
            'dT_st_sp':    x[1],
            'dT_hp_cs_gl': x[2],
            'dT_hp_ev_sh': x[3],
            'dT_he_ev_sh': x[4],
            'dT_hp_cd_sc': x[5],
            'eta_max_cp':  x[6],
            'eta_max_ex':  x[7],
            'eta_pm':      x[8],
        }

    def _build_inputs_params(self, x: List[float]):
        """Build CBSim inputs tuple and parameters dict from decision vector."""
        d = self.decode(x)

        T_hp_cs_su_K = self.T_hp_cs + 273.15
        T_hp_cs_ex_K = max(T_hp_cs_su_K - d['dT_hp_cs_gl'], 275.15)
        p_hp_cs = 1e5

        T_he_cs_su_K = self.T_he_cs + 273.15
        T_he_cs_ex_K = T_he_cs_su_K + self.cfg['dT_he_cs_gl']
        p_he_cs = 1e5

        i_hp_cs_su = CP.PropsSI('H', 'T', T_hp_cs_su_K, 'P', p_hp_cs, 'H2O')
        i_hp_cs_ex = CP.PropsSI('H', 'T', T_hp_cs_ex_K, 'P', p_hp_cs, 'H2O')
        i_he_cs_su = CP.PropsSI('H', 'T', T_he_cs_su_K, 'P', p_he_cs, 'H2O')
        i_he_cs_ex = CP.PropsSI('H', 'T', T_he_cs_ex_K, 'P', p_he_cs, 'H2O')

        inputs = (
            p_hp_cs, i_hp_cs_su, p_hp_cs, i_hp_cs_ex, 1.0, 'H2O',
            p_he_cs, i_he_cs_su, p_he_cs, i_he_cs_ex, 1.0, 'H2O',
            1e3, 1e3,
        )

        params = {
            'p_hp_cs_su': p_hp_cs, 'i_hp_cs_su': i_hp_cs_su, 'i_hp_cs_ex': i_hp_cs_ex,
            'p_he_cs_su': p_he_cs, 'i_he_cs_su': i_he_cs_su, 'i_he_cs_ex': i_he_cs_ex,
            'm_hp_cs': 1.0, 'm_he_cs': 1.0,
            'p_st_ht': self.cfg['p_st_ht'], 'p_st_lt': self.cfg['p_st_lt'],
            'T_st_ht': d['T_st_ht'] + 273.15,
            'dT_st_sp': d['dT_st_sp'],
            'eta_max_cp': d['eta_max_cp'],
            'eta_max_ex': d['eta_max_ex'],
            'eta_pm':     d['eta_pm'],
            'dT_hp_ev_pp': self.cfg['dT_hp_ev_pp'],
            'dT_hp_cd_pp': self.cfg['dT_hp_cd_pp'],
            'dT_he_ev_pp': self.cfg['dT_he_ev_pp'],
            'dT_he_cd_pp': self.cfg['dT_he_cd_pp'],
            'dT_hp_ev_sh': d['dT_hp_ev_sh'],
            'dT_he_ev_sh': d['dT_he_ev_sh'],
            'dT_he_cd_sc': self.cfg['dT_he_cd_sc'],
            'dT_hp_cd_sc': d['dT_hp_cd_sc'],
            'dp_hp_ev': 0.0, 'dp_hp_cd': 0.0,
            'dp_hp_rg_lq': 0.0, 'dp_hp_rg_vp': 0.0,
            'epsilon_hp': self.cfg['epsilon_hp'],
            'dp_he_ev': 0.0, 'dp_he_cd': 0.0,
            'dp_he_rg_lq': 0.0, 'dp_he_rg_vp': 0.0,
            'epsilon_he': self.cfg['epsilon_he'],
            'm_hp_st_max': 0.0, 'm_he_st_max': 0.0,
            'version': 'thermodynamic_full',
            'mode_hp': True, 'mode_he': True, 'mode': 'source',
            'p_ref': p_he_cs, 'T_ref': T_he_cs_su_K,
            'p_0':   p_he_cs, 'T_0':   T_he_cs_su_K,
            'fluid_hp': self.fluid_hp,
            'fluid_he': self.fluid_he,
            'fluid_st': self.cfg.get('fluid_st', 'H2O'),
            'wet_ex': 0, 'm_rat_hp': 0, 'm_rat_he': 0,
        }
        options = {'plot_flag': False, 'print_flag': False,
                   'debug': False, 'exergy': True}
        return inputs, params, options

    def evaluate(self, x: List[float]) -> Tuple[float, ...]:
        """
        Evaluate objectives for decision vector x.
        Returns tuple of objective values (all maximized).
        Infeasible → all INFEASIBLE_PENALTY.
        """
        # Quick feasibility pre-check
        T_st_ht = x[0]
        if T_st_ht <= self.T_hp_cs + 5.0:
            return tuple(INFEASIBLE_PENALTY for _ in self.objectives)

        try:
            inputs, params, options = self._build_inputs_params(x)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                my_cb = self.cb_class(inputs, params, options)
                my_cb.evaluate()

            if my_cb.error:
                return tuple(INFEASIBLE_PENALTY for _ in self.objectives)

            # Sanity check on key outputs
            if not (0.01 < my_cb.eta_cb_elec < 1.0):
                return tuple(INFEASIBLE_PENALTY for _ in self.objectives)

            results = []
            for obj_name in self.objectives:
                fn = OBJECTIVE_MAP[obj_name]
                if obj_name in ECONOMIC_OBJECTIVES:
                    val = fn(my_cb, self.economic_params)
                else:
                    val = fn(my_cb)
                results.append(float(val))
            return tuple(results)

        except Exception:
            return tuple(INFEASIBLE_PENALTY for _ in self.objectives)


# ============================================================================
# DEAP OPTIMIZER
# ============================================================================

class NSGAOptimizer:
    """
    NSGA-II / NSGA-III optimizer wrapping DEAP.

    Handles:
    - DEAP creator/toolbox setup (per-instance, avoids global state conflicts)
    - SBX crossover + polynomial mutation
    - Constraint handling via penalty (infeasible → dominated)
    - Result extraction and export
    """

    def __init__(self, evaluator: CBEvaluator,
                 algorithm: str = 'NSGA2',
                 pop_size: int = 100,
                 n_gen: int = 100,
                 cx_prob: float = 0.9,
                 mut_prob: float = 0.1,
                 eta_cx: float = 20.0,
                 eta_mut: float = 20.0,
                 seed: Optional[int] = None):
        """
        Parameters
        ----------
        evaluator   : CBEvaluator instance
        algorithm   : 'NSGA2' or 'NSGA3'
        pop_size    : population size (must be multiple of 4 for NSGA-II)
        n_gen       : number of generations
        cx_prob     : crossover probability
        mut_prob    : mutation probability per individual
        eta_cx      : SBX crossover distribution index
        eta_mut     : polynomial mutation distribution index
        seed        : random seed
        """
        self.evaluator = evaluator
        self.algorithm = algorithm.upper()
        self.pop_size  = pop_size + (pop_size % 4)  # ensure divisible by 4
        self.n_gen     = n_gen
        self.cx_prob   = cx_prob
        self.mut_prob  = mut_prob
        self.eta_cx    = eta_cx
        self.eta_mut   = eta_mut
        self.seed      = seed

        self.n_obj  = len(evaluator.objectives)
        self.n_vars = evaluator.n_vars
        self.lb     = evaluator.lb.tolist()
        self.ub     = evaluator.ub.tolist()

        self._setup_deap()

    def _setup_deap(self):
        """Configure DEAP creator and toolbox."""
        # Use unique names to avoid conflicts when running multiple instances
        fit_name = f'FitnessMax_{id(self)}'
        ind_name = f'Individual_{id(self)}'

        if fit_name not in dir(creator):
            creator.create(fit_name, base.Fitness,
                           weights=tuple(1.0 for _ in range(self.n_obj)))
        if ind_name not in dir(creator):
            creator.create(ind_name, list,
                           fitness=getattr(creator, fit_name))

        self._fit_cls = getattr(creator, fit_name)
        self._ind_cls = getattr(creator, ind_name)

        self.toolbox = base.Toolbox()

        # Individual initializer: uniform random in [lb, ub]
        def make_individual():
            return self._ind_cls(
                random.uniform(lo, hi)
                for lo, hi in zip(self.lb, self.ub)
            )

        self.toolbox.register('individual', make_individual)
        self.toolbox.register('population', tools.initRepeat,
                              list, self.toolbox.individual)

        # Evaluation
        self.toolbox.register('evaluate', self.evaluator.evaluate)

        # SBX crossover
        self.toolbox.register('mate', tools.cxSimulatedBinaryBounded,
                              low=self.lb, up=self.ub, eta=self.eta_cx)

        # Polynomial mutation
        mut_prob_per_gene = self.mut_prob / self.n_vars
        self.toolbox.register('mutate', tools.mutPolynomialBounded,
                              low=self.lb, up=self.ub,
                              eta=self.eta_mut,
                              indpb=mut_prob_per_gene)

        # Selection
        if self.algorithm == 'NSGA3':
            ref_points = tools.uniform_reference_points(
                nobj=self.n_obj,
                p=max(4, self.pop_size // 10)
            )
            self.toolbox.register('select', tools.selNSGA3,
                                  ref_points=ref_points)
        else:  # NSGA2
            self.toolbox.register('select', tools.selNSGA2)

    def run(self, verbose: bool = True) -> Tuple[List, tools.Logbook]:
        """
        Run the optimization.

        Returns
        -------
        pareto_front : list of non-dominated individuals
        logbook      : DEAP logbook with statistics per generation
        """
        if self.seed is not None:
            random.seed(self.seed)
            np.random.seed(self.seed)

        # Initialize population
        pop = self.toolbox.population(n=self.pop_size)

        # Statistics
        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register('min',  lambda vals: np.min([v for v in vals if v[0] > INFEASIBLE_PENALTY/2], axis=0) if any(v[0] > INFEASIBLE_PENALTY/2 for v in vals) else [INFEASIBLE_PENALTY]*self.n_obj)
        stats.register('max',  lambda vals: np.max([v for v in vals if v[0] > INFEASIBLE_PENALTY/2], axis=0) if any(v[0] > INFEASIBLE_PENALTY/2 for v in vals) else [INFEASIBLE_PENALTY]*self.n_obj)
        stats.register('n_feasible', lambda vals: sum(1 for v in vals if v[0] > INFEASIBLE_PENALTY/2))

        logbook = tools.Logbook()
        logbook.header = ['gen', 'n_feasible'] + [f'max_obj{i}' for i in range(self.n_obj)]

        # Evaluate initial population
        fitnesses = list(map(self.toolbox.evaluate, pop))
        for ind, fit in zip(pop, fitnesses):
            ind.fitness.values = fit

        # Apply NSGA-II selection to assign crowding distance
        pop = self.toolbox.select(pop, len(pop))

        t0 = time.time()
        for gen in range(1, self.n_gen + 1):
            # Generate offspring via tournament + crossover + mutation
            offspring = tools.selTournamentDCD(pop, len(pop))
            offspring = [self.toolbox.clone(ind) for ind in offspring]

            for i in range(0, len(offspring) - 1, 2):
                if random.random() < self.cx_prob:
                    self.toolbox.mate(offspring[i], offspring[i + 1])
                    del offspring[i].fitness.values
                    del offspring[i + 1].fitness.values

            for ind in offspring:
                if not ind.fitness.valid:
                    self.toolbox.mutate(ind)
                    del ind.fitness.values

            # Evaluate invalid individuals
            invalid = [ind for ind in offspring if not ind.fitness.valid]
            fitnesses = list(map(self.toolbox.evaluate, invalid))
            for ind, fit in zip(invalid, fitnesses):
                ind.fitness.values = fit

            # Combine and select next generation
            combined = pop + offspring
            pop = self.toolbox.select(combined, self.pop_size)

            # Log statistics
            record = stats.compile(pop)
            n_feas = record['n_feasible']
            max_vals = record['max']
            logbook.record(gen=gen, n_feasible=n_feas,
                           **{f'max_obj{i}': max_vals[i] if hasattr(max_vals, '__len__') else max_vals
                              for i in range(self.n_obj)})

            if verbose and gen % 10 == 0:
                elapsed = time.time() - t0
                logger.info(f'  Gen {gen:4d}/{self.n_gen} | '
                            f'feasible={n_feas}/{self.pop_size} | '
                            f'time={elapsed:.1f}s')

        # Extract Pareto front (rank-0 individuals)
        pareto_front = tools.sortNondominated(pop, len(pop), first_front_only=True)[0]
        # Filter out infeasible
        pareto_front = [ind for ind in pareto_front
                        if ind.fitness.values[0] > INFEASIBLE_PENALTY / 2]

        return pareto_front, logbook

    def results_to_dataframe(self, pareto_front: List) -> pd.DataFrame:
        """Convert Pareto front individuals to a DataFrame."""
        records = []
        for ind in pareto_front:
            d = self.evaluator.decode(ind)
            row = {**d}
            for i, obj_name in enumerate(self.evaluator.objectives):
                row[obj_name] = ind.fitness.values[i]
            records.append(row)
        return pd.DataFrame(records)
