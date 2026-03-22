#!/usr/bin/env python3
"""
CBSim Carnot Battery Optimization Case Description

This module defines the case description for CBSim optimization in RHEIA framework.
Single-objective optimization targeting cb_efficiency.
"""

import sys
import os
import numpy as np

# Add CBSim module path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'src'))

# Import CBSim model wrapper
from model_wrapper import CBSimModel


def set_params():
    """
    Set fixed parameters for each model evaluation

    Returns:
        list: List of fixed parameters
    """
    # Fixed parameters for CBSim model
    params = [
        15.0,    # T_hp_cs: Heat pump cold source temperature (°C)
        15.0,    # T_he_cs: Heat engine cold source temperature (°C)
        120.0,   # T_st_ht: Storage heat temperature (°C)
        0.75,    # eta_max_cp: Maximum compressor efficiency
        0.75,    # eta_max_ex: Maximum expander efficiency
        5.0,     # dT_hp_ev_pp: Heat pump evaporator pinch point (°C)
        3.0      # dT_hp_cd_pp: Heat pump condenser pinch point (°C)
    ]
    return params


def evaluate(x_in, params=[]):
    """
    Evaluation of system objectives for one design

    Args:
        x_in: Design variables array or tuple (index, design_dict)
        params: Fixed parameters array

    Returns:
        tuple: Single objective (negative cb_efficiency for maximization)
    """
    try:
        # Extract design variables - handle both formats
        if isinstance(x_in, tuple) and len(x_in) == 2:
            # RHEIA format: (index, design_dict)
            design_vars = x_in[1]
            dT_hp_ev_sh = design_vars['dT_hp_ev_sh']  # Heat pump evaporator superheat (°C)
            dT_hp_cd_sc = design_vars['dT_hp_cd_sc']  # Heat pump condenser subcooling (°C)
            dT_he_ev_sh = design_vars['dT_he_ev_sh']  # Heat engine evaporator superheat (°C)
            dT_he_cd_sc = design_vars['dT_he_cd_sc']  # Heat engine condenser subcooling (°C)
        else:
            # Simple array format: [dT_hp_ev_sh, dT_hp_cd_sc, dT_he_ev_sh, dT_he_cd_sc]
            dT_hp_ev_sh = x_in[0]  # Heat pump evaporator superheat (°C)
            dT_hp_cd_sc = x_in[1]  # Heat pump condenser subcooling (°C)
            dT_he_ev_sh = x_in[2]  # Heat engine evaporator superheat (°C)
            dT_he_cd_sc = x_in[3]  # Heat engine condenser subcooling (°C)

        # Extract fixed parameters
        T_hp_cs = params[0]
        T_he_cs = params[1]
        T_st_ht = params[2]
        eta_max_cp = params[3]
        eta_max_ex = params[4]
        dT_hp_ev_pp = params[5]
        dT_hp_cd_pp = params[6]

        # Create model instance
        model = CBSimModel()

        # Set model parameters
        model.set_parameters(
            dT_hp_ev_sh=dT_hp_ev_sh,
            dT_hp_cd_sc=dT_hp_cd_sc,
            dT_he_ev_sh=dT_he_ev_sh,
            dT_he_cd_sc=dT_he_cd_sc,
            T_hp_cs=T_hp_cs,
            T_he_cs=T_he_cs,
            T_st_ht=T_st_ht,
            eta_max_cp=eta_max_cp,
            eta_max_ex=eta_max_ex,
            dT_hp_ev_pp=dT_hp_ev_pp,
            dT_hp_cd_pp=dT_hp_cd_pp
        )

        # Run simulation
        success = model.evaluate()

        # Extract single objective
        results = model.get_all_results()
        cb_efficiency = results.get('cb_efficiency', 0.0)

        # For single-objective optimization, return tuple with one element
        # RHEIA minimizes objectives, so we return negative efficiency to maximize it
        return (-cb_efficiency,)

    except Exception as e:
        # Return penalty value for failed evaluations
        print(f"Evaluation failed: {e}")
        return 1e6


if __name__ == "__main__":
    """Test the case description"""
    print("Testing CBSim case description...")

    # Test parameters
    params = set_params()
    print(f"Fixed parameters: {params}")

    # Test design point
    x_test = [6.0, 30.0, 1.0, 3.0]  # Typical design point
    print(f"Test design variables: {x_test}")

    # Test evaluation
    result = evaluate(x_test, params)
    print(f"Evaluation result: {result}")

    if result < 1e5:  # Not penalty value
        print(f"Carnot battery efficiency: {-result:.4f}")
    else:
        print("Evaluation failed - penalty value returned")