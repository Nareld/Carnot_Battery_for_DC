#!/usr/bin/env python3
"""
CBSim Carnot Battery Multi-Objective Optimization - Position position4

Three-objective optimization for position:
- t_hs = 100.0°C
- t_cs = 15.0°C
- ΔT_hs-cs = 85.0K

Three objectives:
1. cb_efficiency (maximize) - Carnot battery efficiency (η_P2P)
2. E_dens_th (maximize) - Thermal energy density (J/m³)
3. eta_cb_exer (maximize) - Exergy efficiency (η_II)
"""

import sys
import os

# Add CBSim module path
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[5] / 'src'))  # cross-platform

# Import CBSim model wrapper
from model_wrapper import CBSimModel


def set_params():
    """
    Set fixed parameters for each model evaluation

    Returns:
        list: List of fixed parameters
    """
    # Fixed parameters for CBSim model - Position position4
    # Note: Most parameters are defined in design_space.csv as either 'var' or 'par'
    # Only return parameters that are not in design_space.csv
    # In this case, all parameters are in design_space.csv, so return empty list
    params = []
    return params


def evaluate(x_in, params=[]):
    """
    Evaluation of system objectives for one design

    Args:
        x_in: Design variables array or tuple (index, design_dict)
        params: Fixed parameters array

    Returns:
        tuple: Three objectives (negative for maximization)
    """
    try:
        # Initialize all parameters with default values
        design_vars = {}

        # Extract design variables - handle both formats
        if isinstance(x_in, tuple) and len(x_in) == 2:
            # RHEIA format: (index, design_dict)
            # design_dict contains all variables (both 'var' and 'par' from design_space.csv)
            design_vars = x_in[1]
        else:
            # Simple array format: variables in order from design_space.csv
            # design_space.csv has 11 variables (7 continuous + 2 integer + 3 efficiency)
            if len(x_in) >= 11:
                # Map array indices to variable names according to design_space.csv order
                design_vars = {
                    'dT_hp_cs_gl': x_in[0],   # Heat source glide (K)
                    'dT_hp_ev_sh': x_in[1],    # HP superheat (K)
                    'dT_he_ev_sh': x_in[2],    # ORC superheat (K)
                    'dT_hp_cd_sc': x_in[3],    # HP subcooling (K)
                    'T_st_ht': x_in[4],        # Hot storage temperature (°C)
                    'dT_st_sp': x_in[5],       # Storage temperature spread (K)
                    'fluid_hp_idx': int(x_in[6]),  # HP fluid index (integer)
                    'fluid_he_idx': int(x_in[7]),  # ORC fluid index (integer)
                    'eta_max_cp': x_in[8],     # Compressor isentropic efficiency
                    'eta_max_ex': x_in[9],     # Expander isentropic efficiency
                    'eta_pm': x_in[10]         # Pump isentropic efficiency
                }
            else:
                # Not enough variables, return penalty
                print(f"Error: Expected 11 design variables, got {len(x_in)}")
                return (1e6, 1e6, 1e6)

        # Extract parameters from design_vars (includes both var and par types)
        # Parameters defined as 'par' in design_space.csv are also in design_vars
        dT_hp_cs_gl = design_vars.get('dT_hp_cs_gl', 10.0)
        dT_hp_ev_sh = design_vars.get('dT_hp_ev_sh', 6.0)
        dT_he_ev_sh = design_vars.get('dT_he_ev_sh', 5.0)
        dT_hp_cd_sc = design_vars.get('dT_hp_cd_sc', 30.0)
        T_st_ht = design_vars.get('T_st_ht', 120.0)
        dT_st_sp = design_vars.get('dT_st_sp', 60.0)
        fluid_hp_idx = int(design_vars.get('fluid_hp_idx', 0))
        fluid_he_idx = int(design_vars.get('fluid_he_idx', 1))
        eta_max_cp = design_vars.get('eta_max_cp', 0.75)
        eta_max_ex = design_vars.get('eta_max_ex', 0.75)
        eta_pm = design_vars.get('eta_pm', 0.50)

        # Fixed parameters for position4 (from design_space.csv 'par' entries)
        T_hp_cs = design_vars.get('T_hp_cs', 100.0)      # Heat source temperature (°C)
        T_he_cs = design_vars.get('T_he_cs', 15.0)       # Heat sink temperature (°C)
        dT_he_cs_gl = design_vars.get('dT_he_cs_gl', 10.0)  # Heat sink glide (K)
        dT_he_cd_sc = design_vars.get('dT_he_cd_sc', 3.0)   # ORC subcooling (K)
        dT_hp_ev_pp = design_vars.get('dT_hp_ev_pp', 3.0)   # HP evaporator pinch point (K)
        dT_hp_cd_pp = design_vars.get('dT_hp_cd_pp', 3.0)   # HP condenser pinch point (K)
        dT_he_ev_pp = design_vars.get('dT_he_ev_pp', 3.0)   # ORC evaporator pinch point (K)
        dT_he_cd_pp = design_vars.get('dT_he_cd_pp', 3.0)   # ORC condenser pinch point (K)

        # Create model instance
        model = CBSimModel()

        # Set model parameters
        model.set_parameters(
            # Design variables
            dT_hp_cs_gl=dT_hp_cs_gl,
            dT_hp_ev_sh=dT_hp_ev_sh,
            dT_he_ev_sh=dT_he_ev_sh,
            dT_hp_cd_sc=dT_hp_cd_sc,
            T_st_ht=T_st_ht,
            dT_st_sp=dT_st_sp,
            fluid_hp_idx=fluid_hp_idx,
            fluid_he_idx=fluid_he_idx,
            eta_max_cp=eta_max_cp,
            eta_max_ex=eta_max_ex,
            eta_pm=eta_pm,
            # Fixed parameters
            T_hp_cs=T_hp_cs,
            T_he_cs=T_he_cs,
            dT_he_cs_gl=dT_he_cs_gl,
            dT_he_cd_sc=dT_he_cd_sc,
            dT_hp_ev_pp=dT_hp_ev_pp,
            dT_hp_cd_pp=dT_hp_cd_pp,
            dT_he_ev_pp=dT_he_ev_pp,
            dT_he_cd_pp=dT_he_cd_pp
        )

        # Run simulation
        success = model.evaluate()

        if success:
            # Get multi-objective values from model
            cb_efficiency, E_dens_th, eta_cb_exer = model.get_multi_objective_values()

            # RHEIA minimizes objectives, so we return negative values to maximize them
            return (-cb_efficiency, -E_dens_th, -eta_cb_exer)
        else:
            # Return penalty values for failed evaluations
            return (1e6, 1e6, 1e6)

    except Exception as e:
        # Return penalty values for failed evaluations
        print(f"Multi-objective evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        return (1e6, 1e6, 1e6)


if __name__ == "__main__":
    """Test the multi-objective case description"""
    print("Testing CBSim multi-objective case description for position4...")

    # Test parameters (empty since all in design_space.csv)
    params = set_params()
    print(f"Fixed parameters: {params} (empty - all in design_space.csv)")

    # Test design point - 11 variables matching design_space.csv order
    x_test = [
        10.0,   # dT_hp_cs_gl: Heat source glide (K)
        6.0,    # dT_hp_ev_sh: HP superheat (K)
        5.0,    # dT_he_ev_sh: ORC superheat (K)
        30.0,   # dT_hp_cd_sc: HP subcooling (K)
        120.0,  # T_st_ht: Hot storage temperature (°C)
        60.0,   # dT_st_sp: Storage temperature spread (K)
        0,      # fluid_hp_idx: HP fluid index (R1233zd(E))
        1,      # fluid_he_idx: ORC fluid index (R227ea)
        0.75,   # eta_max_cp: Compressor isentropic efficiency
        0.75,   # eta_max_ex: Expander isentropic efficiency
        0.50    # eta_pm: Pump isentropic efficiency
    ]
    print(f"Test design variables (11): {x_test}")

    # Test evaluation
    result = evaluate(x_test, params)
    print(f"Multi-objective evaluation result: {result}")

    if result[0] < 1e5:  # Not penalty value
        print(f"Carnot battery efficiency: {-result[0]:.4f}")
        print(f"Thermal energy density: {-result[1]:.2e} J/m³")
        print(f"Exergy efficiency: {-result[2]:.4f}")
    else:
        print("Evaluation failed - penalty values returned")
