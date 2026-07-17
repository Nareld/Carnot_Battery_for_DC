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
import math
import ast
import re
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import random
import base64
import pickle

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
        return cb.my_HP.eta_hp_cyclen

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
        try:
            self.Ttriple_he_K = float(CP.PropsSI('Ttriple', self.fluid_he))
        except Exception:
            self.Ttriple_he_K = None

        # ── Diagnostics (non-intrusive) ──────────────────────────────────
        self.diagnostics_enabled = cfg.get('diagnostics_enabled', False)
        self.last_eval_info: Dict = {}
        self.diagnostics_records: List[Dict] = []

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
            'isolated_property_queries_hp': self.fluid_hp.casefold() in {
                name.casefold() for name in self.cfg.get(
                    'isolated_property_query_hp_fluids', []
                )
            },
            'isolated_property_queries_he': self.fluid_he.casefold() in {
                name.casefold() for name in self.cfg.get(
                    'isolated_property_query_he_fluids', []
                )
            },
            'fluid_st': self.cfg.get('fluid_st', 'H2O'),
            'wet_ex': 0, 'm_rat_hp': 0, 'm_rat_he': 0,
        }
        options = {'plot_flag': False, 'print_flag': False,
                   'debug': False, 'exergy': True}
        return inputs, params, options

    @staticmethod
    def _property_failure_code(message: str) -> Optional[str]:
        text = str(message).lower()
        if 'solver_pressure_interval_degenerate' in text:
            return 'SOLVER_PRESSURE_INTERVAL_DEGENERATE'
        if 'solver_initial_guess_out_of_bounds' in text \
        or ('x0' in text and 'infeasible' in text):
            return 'SOLVER_INITIAL_GUESS_OUT_OF_BOUNDS'
        if 'p,t with ttse cannot be two-phase' in text:
            return 'COOLPROP_BACKEND_TWOPHASE_UNSUPPORTED'
        if 'coolprop_property_nonfinite' in text:
            return 'COOLPROP_PROPERTY_NONFINITE'
        property_markers = (
            'coolprop_property_input_out_of_range',
            'inputs are not in range',
            'input pair variable is invalid',
            'unable to solve 1phase',
            'unable to solve 1phase py flash',
            'hmolar is below',
            'hmolar is greater than',
            'p is not a valid number',
            'temperature to qt_flash',
        )
        if any(marker in text for marker in property_markers):
            return 'COOLPROP_PROPERTY_INPUT_OUT_OF_RANGE'
        return None

    def _normalize_issues(self, issues: List[Dict]) -> List[Dict]:
        """Promote property-domain exceptions above generic wrapper codes."""
        normalized = []
        wrapper_codes = {
            'EVALUATE_CYCLE_EXCEPTION', 'UNKNOWN_EXCEPTION',
            'CB_SOLVER_ERROR', 'CB_CHILD_HP_ERROR', 'CB_CHILD_HE_ERROR',
        }
        for raw_issue in issues:
            issue = dict(raw_issue)
            code = self._property_failure_code(issue.get('message', ''))
            if code and issue.get('code') in wrapper_codes:
                values = dict(issue.get('values') or {})
                values['wrapped_code'] = issue.get('code')
                if code in {
                    'SOLVER_PRESSURE_INTERVAL_DEGENERATE',
                    'SOLVER_INITIAL_GUESS_OUT_OF_BOUNDS',
                }:
                    message = str(issue.get('message', ''))
                    extracted = {}
                    for label in ('x0', 'lower', 'upper', 'width'):
                        match = re.search(rf'{label}=(\[[^\]]*\])', message)
                        if match:
                            try:
                                extracted[label] = list(ast.literal_eval(match.group(1)))
                            except (SyntaxError, ValueError, TypeError):
                                pass
                    if 'x0' in extracted:
                        values['x0'] = extracted['x0']
                    if 'lower' in extracted and 'upper' in extracted:
                        values['bounds'] = {
                            'lower': extracted['lower'],
                            'upper': extracted['upper'],
                        }
                    if 'width' in extracted:
                        values['interval_width'] = extracted['width']
                if code == 'SOLVER_PRESSURE_INTERVAL_DEGENERATE':
                    values['interval_degenerate'] = True
                issue.update({
                    'code': code,
                    'component': (
                        'solver' if code.startswith('SOLVER_') else 'property'
                    ),
                    'severity': 'error',
                    'values': values,
                })
            normalized.append(issue)
        return normalized

    @staticmethod
    def _primary_from_issues(issues: List[Dict], fallback: Optional[str]) -> Optional[str]:
        wrappers = {
            'EVALUATE_CYCLE_EXCEPTION', 'UNKNOWN_EXCEPTION',
            'CB_SOLVER_ERROR', 'CB_CHILD_HP_ERROR', 'CB_CHILD_HE_ERROR',
        }
        for issue in issues:
            if issue.get('severity', 'error') == 'error' \
            and issue.get('code') not in wrappers:
                return issue.get('code')
        return fallback

    @staticmethod
    def _issue_constraint_violation(issue: Dict) -> float:
        """Return a finite, dimensionless proximity measure for one failed check.

        This value is used only to guide an all-infeasible population toward a
        boundary.  It never turns an infeasible evaluation into a feasible one
        and does not relax any thermodynamic constraint.
        """
        code = str(issue.get('code') or 'UNKNOWN_EXCEPTION')
        values = issue.get('values') or {}
        numeric = [
            abs(float(value)) for value in values.values()
            if isinstance(value, (int, float, np.integer, np.floating))
            and np.isfinite(value)
        ]
        if code == 'OPT_PRECHECK_STORAGE_TEMP_TOO_LOW':
            gap = float(values.get('threshold', 0.0)) - float(values.get('T_st_ht', 0.0))
            return 1.0 + max(0.0, gap) / 10.0
        if code == 'OPT_PRECHECK_HE_REFERENCE_BELOW_TRIPLE':
            gap = float(values.get('threshold_K', 0.0)) - float(values.get('T_ref_K', 0.0))
            return 1.0 + max(0.0, gap) / 10.0
        if code == 'KPI_SANITY_ETA_P2P_RANGE':
            eta = float(values.get('eta_cb_elec', 0.0))
            return 1.0 + max(0.01 - eta, eta - 1.0, 0.0)
        if code == 'PHASE_WET_EXPANSION':
            quality = float(values.get('quality', 0.5))
            return 1.0 + max(0.0, min(quality, 1.0 - quality))
        if code.startswith('SOLVER_'):
            residual = values.get('residual_linf', values.get('residual'))
            tolerance = values.get('residual_tol')
            if isinstance(residual, (int, float)) and np.isfinite(residual):
                ratio = abs(float(residual))
                if isinstance(tolerance, (int, float)) and tolerance > 0:
                    ratio /= float(tolerance)
                return 1.0 + math.log1p(min(ratio, 1.0e12))
            return 20.0
        if code.startswith('COOLPROP_') or code == 'UPSTREAM_NONFINITE_STATE':
            return 100.0
        if code.startswith('STATE_') or 'RECUPERATOR' in code:
            if len(numeric) >= 2:
                spread = max(numeric) - min(numeric)
                scale = max(max(numeric), 1.0)
                return 1.0 + spread / scale
            return 2.0
        if code.startswith('HX_PINCH_'):
            # Existing checks short-circuit at the first pinch violation.  Use
            # the reported target to distinguish near-boundary and severe
            # failures until all model checks expose an explicit signed margin.
            target = abs(float(values.get('min_pinch', 1.0)))
            temperatures = [
                abs(float(value)) for key, value in values.items()
                if key.startswith('T_') and isinstance(value, (int, float))
                and np.isfinite(value)
            ]
            spread = max(temperatures) - min(temperatures) if len(temperatures) >= 2 else 0.0
            return 1.0 + min(abs(spread - target) / max(target, 1.0), 20.0)
        return 10.0

    def _constraint_violation(self, info: Dict) -> float:
        wrappers = {
            'EVALUATE_CYCLE_EXCEPTION', 'UNKNOWN_EXCEPTION',
            'CB_SOLVER_ERROR', 'CB_CHILD_HP_ERROR', 'CB_CHILD_HE_ERROR',
        }
        issues = [
            issue for issue in info.get('issues', [])
            if issue.get('severity', 'error') == 'error'
            and issue.get('code') not in wrappers
        ]
        primary = info.get('primary_code')
        primary_issues = [issue for issue in issues if issue.get('code') == primary]
        selected = primary_issues or issues[:1]
        if not selected:
            return 10.0
        value = sum(self._issue_constraint_violation(issue) for issue in selected)
        return float(value) if np.isfinite(value) and value > 0 else 10.0

    def evaluate(self, x: List[float]) -> Tuple[float, ...]:
        """
        Evaluate objectives for decision vector x.
        Returns tuple of objective values (all maximized).
        Infeasible → all INFEASIBLE_PENALTY.
        Diagnostics recorded when cfg['diagnostics_enabled']=True.
        """
        diag_on = self.diagnostics_enabled
        decoded = self.decode(x) if hasattr(self, 'decode') else {}
        base_info = {
            'feasible': False, 'penalized': True,
            'primary_code': None, 'issues': [],
            'decoded': decoded,
            'cb_class': self.cb_class.__name__,
            'fluid_hp': self.fluid_hp, 'fluid_he': self.fluid_he,
        }

        # Quick feasibility pre-check
        T_st_ht = x[0]
        if T_st_ht <= self.T_hp_cs + 5.0:
            base_info['primary_code'] = 'OPT_PRECHECK_STORAGE_TEMP_TOO_LOW'
            if diag_on:
                base_info['issues'] = [{
                    'code': 'OPT_PRECHECK_STORAGE_TEMP_TOO_LOW',
                    'component': 'optimizer', 'cls': 'CBEvaluator', 'method': 'evaluate',
                    'message': f'T_st_ht={T_st_ht} <= T_hp_cs+5={self.T_hp_cs+5.0}',
                    'severity': 'error',
                    'values': {'T_st_ht': T_st_ht, 'threshold': self.T_hp_cs + 5.0},
                }]
            self._record_eval(base_info)
            return tuple(INFEASIBLE_PENALTY for _ in self.objectives)

        # The HE exergy reference is the low-temperature storage state.  Unlike
        # the HP reference this depends on the design vector, so guard it here
        # and expose a continuous distance instead of letting CoolProp fail.
        T_st_lt_K = x[0] - x[1] + 273.15
        if self.Ttriple_he_K is not None \
        and T_st_lt_K <= self.Ttriple_he_K + 1.0:
            base_info['primary_code'] = 'OPT_PRECHECK_HE_REFERENCE_BELOW_TRIPLE'
            if diag_on:
                base_info['issues'] = [{
                    'code': 'OPT_PRECHECK_HE_REFERENCE_BELOW_TRIPLE',
                    'component': 'optimizer', 'cls': 'CBEvaluator',
                    'method': 'evaluate',
                    'message': 'HE storage reference is below/too close to Ttriple',
                    'severity': 'error',
                    'values': {
                        'T_ref_K': T_st_lt_K,
                        'Ttriple_K': self.Ttriple_he_K,
                        'threshold_K': self.Ttriple_he_K + 1.0,
                    },
                }]
            self._record_eval(base_info)
            return tuple(INFEASIBLE_PENALTY for _ in self.objectives)

        my_cb = None
        try:
            inputs, params, options = self._build_inputs_params(x)

            if diag_on:
                with warnings.catch_warnings(record=True) as caught_warnings:
                    warnings.simplefilter('always')
                    my_cb = self.cb_class(inputs, params, options)
                    my_cb.evaluate()
                # Summarize warnings when diagnostics enabled
                if caught_warnings:
                    warn_counts = {}
                    for w in caught_warnings:
                        if 'fsolve' in str(w.message) or 'least_squares' in str(w.message):
                            key = 'SOLVER_FSOLVE_FAILED'
                        elif 'minimize' in str(w.message):
                            key = 'SOLVER_MINIMIZE_FAILED'
                        else:
                            key = 'SOLVER_WARNING'
                        warn_counts[key] = warn_counts.get(key, 0) + 1
                    # Store summarized warning counts
                    base_info['warning_summary'] = warn_counts
                    # Only store first 3 distinct warnings as issues
                    seen = set()
                    for w in caught_warnings:
                        wmsg_short = str(w.message)[:80]
                        if wmsg_short not in seen:
                            seen.add(wmsg_short)
                            code = 'SOLVER_FSOLVE_FAILED' if 'fsolve' in str(w.message) or 'least_squares' in str(w.message) else \
                                   'SOLVER_MINIMIZE_FAILED' if 'minimize' in str(w.message) else 'SOLVER_WARNING'
                            base_info['issues'].append({
                                'code': code, 'component': 'optimizer',
                                'cls': self.cb_class.__name__, 'method': 'evaluate',
                                'message': str(w.message)[:200], 'severity': 'warning',
                                'values': {},
                            })
                        if len(seen) >= 3:
                            break
            else:
                # Lightweight: suppress warnings, no capture
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    my_cb = self.cb_class(inputs, params, options)
                    my_cb.evaluate()

            if my_cb.error:
                if diag_on and hasattr(my_cb, 'get_diagnostics'):
                    cb_diag = my_cb.get_diagnostics()
                    # Recompute primary to prioritize cause codes over wrappers
                    cb_diag.recompute_primary()
                    normalized = self._normalize_issues(
                        cb_diag.to_dict().get('issues', [])
                    )
                    base_info['issues'].extend(normalized)
                    base_info['primary_code'] = self._primary_from_issues(
                        normalized, cb_diag.primary_code
                    )
                else:
                    if diag_on:
                        base_info['primary_code'] = 'CB_SOLVER_ERROR'
                        base_info['issues'].append({
                            'code': 'CB_SOLVER_ERROR', 'component': 'CB',
                            'cls': self.cb_class.__name__, 'method': 'evaluate',
                            'message': 'CBSim solver returned error=True',
                            'severity': 'error', 'values': {},
                        })
                self._record_eval(base_info)
                return tuple(INFEASIBLE_PENALTY for _ in self.objectives)

            # Sanity check on key outputs
            if not (0.01 < my_cb.eta_cb_elec < 1.0):
                base_info['primary_code'] = 'KPI_SANITY_ETA_P2P_RANGE'
                if diag_on:
                    base_info['issues'].append({
                        'code': 'KPI_SANITY_ETA_P2P_RANGE', 'component': 'optimizer',
                        'cls': 'CBEvaluator', 'method': 'evaluate',
                        'message': f'eta_cb_elec={my_cb.eta_cb_elec} outside (0.01, 1.0)',
                        'severity': 'error',
                        'values': {'eta_cb_elec': my_cb.eta_cb_elec},
                    })
                self._record_eval(base_info)
                return tuple(INFEASIBLE_PENALTY for _ in self.objectives)

            results = []
            for obj_name in self.objectives:
                fn = OBJECTIVE_MAP[obj_name]
                if obj_name in ECONOMIC_OBJECTIVES:
                    val = fn(my_cb, self.economic_params)
                else:
                    val = fn(my_cb)
                results.append(float(val))

            base_info['feasible'] = True
            base_info['penalized'] = False
            self._record_eval(base_info)
            return tuple(results)

        except Exception as e:
            if diag_on and my_cb is not None and hasattr(my_cb, 'get_diagnostics'):
                cb_diag = my_cb.get_diagnostics()
                cb_diag.recompute_primary()
                if cb_diag.primary_code:
                    normalized = self._normalize_issues(
                        cb_diag.to_dict().get('issues', [])
                    )
                    base_info['issues'].extend(normalized)
                    base_info['primary_code'] = self._primary_from_issues(
                        normalized, cb_diag.primary_code
                    )
            if base_info['primary_code'] is None:
                base_info['primary_code'] = (
                    self._property_failure_code(str(e)) or 'UNKNOWN_EXCEPTION'
                )
            if diag_on:
                exception_code = (
                    self._property_failure_code(str(e)) or 'UNKNOWN_EXCEPTION'
                )
                base_info['issues'].append({
                    'code': exception_code,
                    'component': (
                        'property' if exception_code.startswith('COOLPROP_')
                        else 'solver' if exception_code.startswith('SOLVER_')
                        else 'optimizer'
                    ),
                    'cls': 'CBEvaluator', 'method': 'evaluate',
                    'message': f'{type(e).__name__}: {str(e)[:200]}',
                    'severity': 'error',
                    'values': {'exception_type': type(e).__name__},
                })
            self._record_eval(base_info)
            return tuple(INFEASIBLE_PENALTY for _ in self.objectives)

    def _record_eval(self, info: Dict):
        """Record evaluation info if diagnostics enabled."""
        info = dict(info)
        info['constraint_violation'] = (
            0.0 if info.get('feasible') else self._constraint_violation(info)
        )
        self.last_eval_info = info
        if self.diagnostics_enabled:
            self.diagnostics_records.append(info)


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
                 seed: Optional[int] = None,
                 archive_tol: float = 1e-9):
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
        if pop_size < 4:
            raise ValueError('pop_size must be >= 4')
        self.pop_size  = ((pop_size + 3) // 4) * 4
        self.n_gen     = n_gen
        self.cx_prob   = cx_prob
        self.mut_prob  = mut_prob
        self.eta_cx    = eta_cx
        self.eta_mut   = eta_mut
        self.seed      = seed
        self.archive_tol = float(archive_tol)
        if self.archive_tol < 0:
            raise ValueError('archive_tol must be >= 0')
        self.generation_metrics: List[Dict] = []

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
        self.toolbox.register('mutate', tools.mutPolynomialBounded,
                              low=self.lb, up=self.ub,
                              eta=self.eta_mut,
                              indpb=1.0 / self.n_vars)

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

    def _fitness_is_feasible(self, fitness) -> bool:
        values = tuple(fitness)
        return (
            len(values) == self.n_obj
            and all(np.isfinite(value) for value in values)
            and all(value > INFEASIBLE_PENALTY / 2 for value in values)
        )

    def _evaluate_invalid(self, individuals) -> None:
        """Evaluate individuals and retain a gradient inside infeasible space."""
        for individual in individuals:
            raw_fitness = tuple(self.toolbox.evaluate(individual))
            if self._fitness_is_feasible(raw_fitness):
                individual.fitness.values = raw_fitness
                continue
            info = getattr(self.evaluator, 'last_eval_info', {}) or {}
            violation = float(info.get('constraint_violation', 10.0))
            if not np.isfinite(violation) or violation <= 0:
                violation = 10.0
            guided_penalty = INFEASIBLE_PENALTY - min(violation, 1.0e5)
            individual.fitness.values = tuple(
                guided_penalty for _ in range(self.n_obj)
            )

    def _archive_similar(self, left, right) -> bool:
        return bool(np.allclose(
            np.asarray(left, dtype=float),
            np.asarray(right, dtype=float),
            rtol=0.0, atol=self.archive_tol,
        ))

    @staticmethod
    def _encode_state(value) -> str:
        return base64.b64encode(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)).decode('ascii')

    @staticmethod
    def _decode_state(value: str):
        return pickle.loads(base64.b64decode(value.encode('ascii')))

    def export_checkpoint(self, generation: int, population, archive) -> Dict:
        """Return a JSON-serializable optimizer checkpoint."""
        def crowding_value(individual):
            value = getattr(individual.fitness, 'crowding_dist', None)
            if value is None:
                return None
            if np.isposinf(value):
                return 'inf'
            if np.isneginf(value):
                return '-inf'
            return float(value)

        return {
            'schema_version': '0.1',
            'optimizer_signature': {
                'algorithm': self.algorithm,
                'population_size': self.pop_size,
                'n_objectives': self.n_obj,
                'n_variables': self.n_vars,
                'lower_bounds': self.lb,
                'upper_bounds': self.ub,
                'crossover_probability': self.cx_prob,
                'mutation_probability': self.mut_prob,
                'eta_crossover': self.eta_cx,
                'eta_mutation': self.eta_mut,
                'archive_tolerance': self.archive_tol,
                'seed': self.seed,
                'constraint_handling': 'normalized_penalty_v1',
            },
            'generation': generation,
            'population': [
                {
                    'x': list(map(float, ind)),
                    'fitness': list(map(float, ind.fitness.values)),
                    'crowding_dist': crowding_value(ind),
                }
                for ind in population
            ],
            'archive': [
                {'x': list(map(float, ind)), 'fitness': list(map(float, ind.fitness.values))}
                for ind in archive
            ],
            'random_state': self._encode_state(random.getstate()),
            'numpy_random_state': self._encode_state(np.random.get_state()),
            'generation_metrics': list(self.generation_metrics),
        }

    def _individual_from_record(self, record: Dict):
        individual = self._ind_cls(record['x'])
        individual.fitness.values = tuple(record['fitness'])
        if record.get('crowding_dist') is not None:
            crowding = record['crowding_dist']
            individual.fitness.crowding_dist = (
                math.inf if crowding == 'inf'
                else -math.inf if crowding == '-inf'
                else float(crowding)
            )
        return individual

    def run(self, verbose: bool = True, resume_state: Optional[Dict] = None,
            checkpoint_every: int = 0, checkpoint_callback=None) -> Tuple[List, tools.Logbook]:
        """
        Run the optimization.

        Returns
        -------
        pareto_front : list of non-dominated individuals
        logbook      : DEAP logbook with statistics per generation
        """
        if resume_state is None and self.seed is not None:
            random.seed(self.seed)
            np.random.seed(self.seed)

        archive = tools.ParetoFront(similar=self._archive_similar)
        start_generation = 0
        if resume_state is None:
            pop = self.toolbox.population(n=self.pop_size)
            self.generation_metrics = []
        else:
            expected_signature = self.export_checkpoint(0, [], [])['optimizer_signature']
            if resume_state.get('optimizer_signature') != expected_signature:
                raise ValueError('checkpoint optimizer signature does not match current configuration')
            pop = [self._individual_from_record(record)
                   for record in resume_state['population']]
            if len(pop) != self.pop_size:
                raise ValueError(
                    f'checkpoint population {len(pop)} != configured {self.pop_size}'
                )
            for record in resume_state.get('archive', []):
                archive.insert(self._individual_from_record(record))
            random.setstate(self._decode_state(resume_state['random_state']))
            np.random.set_state(self._decode_state(resume_state['numpy_random_state']))
            self.generation_metrics = list(resume_state.get('generation_metrics', []))
            start_generation = int(resume_state['generation'])

        # Statistics
        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register('min', lambda vals: np.min(
            [v for v in vals if self._fitness_is_feasible(v)], axis=0
        ) if any(self._fitness_is_feasible(v) for v in vals)
        else [INFEASIBLE_PENALTY] * self.n_obj)
        stats.register('max', lambda vals: np.max(
            [v for v in vals if self._fitness_is_feasible(v)], axis=0
        ) if any(self._fitness_is_feasible(v) for v in vals)
        else [INFEASIBLE_PENALTY] * self.n_obj)
        stats.register('n_feasible', lambda vals: sum(
            1 for v in vals if self._fitness_is_feasible(v)
        ))

        logbook = tools.Logbook()
        logbook.header = ['gen', 'n_feasible'] + [f'max_obj{i}' for i in range(self.n_obj)]

        if resume_state is None:
            self._evaluate_invalid(pop)
            archive.update(ind for ind in pop if self._fitness_is_feasible(ind.fitness.values))

        # Apply selection once to assign crowding distance. A checkpoint stores
        # the selected population order and crowding distances verbatim.
        if resume_state is None:
            pop = self.toolbox.select(pop, len(pop))

        t0 = time.time()
        for gen in range(start_generation + 1, self.n_gen + 1):
            # Generate offspring via tournament + crossover + mutation
            offspring = tools.selTournamentDCD(pop, len(pop))
            offspring = [self.toolbox.clone(ind) for ind in offspring]

            for i in range(0, len(offspring) - 1, 2):
                if random.random() < self.cx_prob:
                    self.toolbox.mate(offspring[i], offspring[i + 1])
                    del offspring[i].fitness.values
                    del offspring[i + 1].fitness.values

            for ind in offspring:
                if random.random() < self.mut_prob:
                    self.toolbox.mutate(ind)
                    if ind.fitness.valid:
                        del ind.fitness.values

            # Evaluate invalid individuals
            invalid = [ind for ind in offspring if not ind.fitness.valid]
            self._evaluate_invalid(invalid)

            # Combine and select next generation
            combined = pop + offspring
            pop = self.toolbox.select(combined, self.pop_size)
            archive.update(ind for ind in combined
                           if self._fitness_is_feasible(ind.fitness.values))

            # Log statistics
            record = stats.compile(pop)
            n_feas = record['n_feasible']
            max_vals = record['max']
            logbook.record(gen=gen, n_feasible=n_feas,
                           **{f'max_obj{i}': max_vals[i] if hasattr(max_vals, '__len__') else max_vals
                              for i in range(self.n_obj)})
            unique_population = {
                tuple(np.round(np.asarray(ind, dtype=float), 12)) for ind in pop
            }
            infeasible_violations = [
                max(0.0, INFEASIBLE_PENALTY - float(ind.fitness.values[0]))
                for ind in pop
                if not self._fitness_is_feasible(ind.fitness.values)
            ]
            metric = {
                'generation': gen,
                'n_evaluated': len(invalid),
                'n_feasible': int(n_feas),
                'population_size': len(pop),
                'front_size': len(tools.sortNondominated(
                    pop, len(pop), first_front_only=True
                )[0]),
                'archive_size': len(archive),
                'unique_ratio': len(unique_population) / len(pop) if pop else 0.0,
                'min_constraint_violation': (
                    min(infeasible_violations) if infeasible_violations else 0.0
                ),
                'elapsed_s': time.time() - t0,
            }
            self.generation_metrics.append(metric)
            if checkpoint_every > 0 and checkpoint_callback is not None \
            and gen % checkpoint_every == 0:
                checkpoint_callback(self.export_checkpoint(gen, pop, archive))

            if verbose and gen % 10 == 0:
                elapsed = time.time() - t0
                logger.info(f'  Gen {gen:4d}/{self.n_gen} | '
                            f'feasible={n_feas}/{self.pop_size} | '
                            f'time={elapsed:.1f}s')

        pareto_front = [
            ind for ind in archive
            if self._fitness_is_feasible(ind.fitness.values)
        ]

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
