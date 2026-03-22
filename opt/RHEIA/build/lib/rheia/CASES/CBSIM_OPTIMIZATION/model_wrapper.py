#!/usr/bin/env python3
"""
CBSim Model Wrapper for RHEIA Integration

This module provides a wrapper for the CBSim thermal model to integrate
with the RHEIA optimization framework.
"""

import sys
import os
import time
import logging
import CoolProp.CoolProp as CP

# Add CBSim module path
import pathlib
cbsim_src_path = str(pathlib.Path(__file__).resolve().parents[5] / 'src')  # cross-platform
sys.path.insert(0, cbsim_src_path)

# Import CBSim model
try:
    from _module_carnot_battery import SBVCHP_SBORC_STES2T as CBSim
except ImportError as e:
    print(f"Warning: Could not import CBSim module: {e}")
    print("Make sure the CBSim source code is available in the src directory")


class CBSimModel:
    """Wrapper class for CBSim thermal model"""

    def __init__(self):
        """Initialize the CBSim model wrapper"""
        self.model = None
        self.results = {}
        self.parameters = {}

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def set_parameters(self, **kwargs):
        """
        Set model parameters

        Args:
            **kwargs: Model parameters
        """
        self.parameters.update(kwargs)

    def evaluate(self):
        """
        Run CBSim evaluation with constraint violation tracking

        Returns:
            dict: Evaluation results including constraint violations
        """
        try:
            start_time = time.time()

            # Build complete parameter dictionary
            inputs = self._build_inputs()

            # Prepare heat pump inputs
            p_hp_cs_su = 1e+5
            T_hp_cs_su = inputs['T_hp_cs'] + 273.15
            T_hp_cs_ex = T_hp_cs_su - inputs['dT_hp_cs_gl']
            m_hp_cs = 1.0
            i_hp_cs_su = CP.PropsSI('H', 'T', T_hp_cs_su, 'P', p_hp_cs_su, inputs['fluid_hp_cs'])
            i_hp_cs_ex = CP.PropsSI('H', 'T', T_hp_cs_ex, 'P', p_hp_cs_su, inputs['fluid_hp_cs'])
            P_hp = 1e+3

            # Prepare heat engine inputs
            p_he_cs_su = 1e+5
            T_he_cs_su = inputs['T_he_cs'] + 273.15
            T_he_cs_ex = T_he_cs_su + inputs['dT_he_cs_gl']
            m_he_cs = 1.0
            i_he_cs_su = CP.PropsSI('H', 'T', T_he_cs_su, 'P', p_he_cs_su, inputs['fluid_he_cs'])
            i_he_cs_ex = CP.PropsSI('H', 'T', T_he_cs_ex, 'P', p_he_cs_su, inputs['fluid_he_cs'])
            P_he = 1e+3

            T_st_ht_k = inputs['T_st_ht'] + 273.15

            # Complete parameter dictionary
            dp_hp_ev = 0.00e+5
            dp_hp_cd = 0.00e+5
            dp_he_ev = 0.00e+5
            dp_he_cd = 0.00e+5
            epsilon = 0.80

            my_CB_params = {
                'p_hp_cs_su': p_hp_cs_su,
                'i_hp_cs_su': i_hp_cs_su,
                'i_hp_cs_ex': i_hp_cs_ex,
                'p_he_cs_su': p_he_cs_su,
                'i_he_cs_su': i_he_cs_su,
                'i_he_cs_ex': i_he_cs_ex,
                'm_hp_cs': m_hp_cs,
                'm_he_cs': m_he_cs,
                'p_st_ht': 2.5e+5,
                'p_st_lt': 2.5e+5,
                'T_st_ht': T_st_ht_k,
                'dT_st_sp': inputs['dT_st_sp'],
                'eta_max_cp': inputs['eta_max_cp'],
                'eta_max_ex': inputs['eta_max_ex'],
                'eta_pm': inputs['eta_pm'],
                'dT_hp_ev_pp': inputs['dT_hp_ev_pp'],
                'dT_hp_cd_pp': inputs['dT_hp_cd_pp'],
                'dT_he_ev_pp': inputs['dT_he_ev_pp'],
                'dT_he_cd_pp': inputs['dT_he_cd_pp'],
                'dT_he_ev_sh': inputs['dT_he_ev_sh'],
                'dT_hp_ev_sh': inputs['dT_hp_ev_sh'],
                'dT_he_cd_sc': inputs['dT_he_cd_sc'],
                'dT_hp_cd_sc': inputs['dT_hp_cd_sc'],
                'dp_hp_ev': dp_hp_ev,
                'dp_hp_cd': dp_hp_cd,
                'dp_hp_rg_lq': (dp_hp_ev+dp_hp_cd)/2,
                'dp_hp_rg_vp': (dp_hp_ev+dp_hp_cd)/2,
                'epsilon_hp': epsilon,
                'dp_he_ev': dp_he_ev,
                'dp_he_cd': dp_he_cd,
                'dp_he_rg_lq': (dp_he_ev+dp_he_cd)/2,
                'dp_he_rg_vp': (dp_he_ev+dp_he_cd)/2,
                'epsilon_he': epsilon,
                'm_hp_st_max': 0e+0,
                'm_he_st_max': 0e+0,
                'version': inputs['version'],
                'mode_hp': True,
                'mode_he': True,
                'mode': 'source',
                'p_ref': p_he_cs_su,
                'T_ref': T_he_cs_su,
                'p_0': p_he_cs_su,
                'T_0': T_he_cs_su,
                'fluid_hp': inputs['fluid_hp'],
                'fluid_he': inputs['fluid_he'],
                'fluid_st': inputs['fluid_st'],
                'wet_ex': 0,
                'm_rat_hp': 0,
                'm_rat_he': 0,
            }

            # Prepare options
            print_flag, plot_flag = False, False
            debug = False
            exergy = True
            options = {'plot_flag': plot_flag,
                       'print_flag': print_flag,
                       'debug': debug,
                       'exergy': exergy}

            # Prepare input tuple
            input_tuple = (p_hp_cs_su, i_hp_cs_su, p_hp_cs_su, i_hp_cs_ex, m_hp_cs, inputs['fluid_hp_cs'],
                          p_he_cs_su, i_he_cs_su, p_he_cs_su, i_he_cs_ex, m_he_cs, inputs['fluid_he_cs'],
                          P_hp, P_he)

            # Run simulation
            self.model = CBSim(input_tuple, my_CB_params, options)
            self.model.evaluate()

            # Extract performance metrics and constraint violations
            self.results = self._extract_results_with_constraints(start_time)

            self.logger.info(f"Evaluation successful - CB efficiency: {self.results['cb_efficiency']:.4f}, "
                           f"Constraint violation: {self.results['constraint_violation']:.4f}")
            return True

        except Exception as e:
            self.logger.error(f"Evaluation failed: {e}")
            self.results = self._build_failure_results(e, start_time)
            return False

    def _build_inputs(self):
        """Build complete input dictionary from parameters"""
        inputs = {
            'T_hp_cs': self.parameters.get('T_hp_cs', 15.0),
            'T_he_cs': self.parameters.get('T_he_cs', 15.0),
            'T_st_ht': self.parameters.get('T_st_ht', 120.0),
            'dT_hp_cs_gl': 10.0,
            'dT_he_cs_gl': 10.0,
            'dT_st_sp': 60.0,
            'fluid_hp': 'R1233zd(E)',
            'fluid_he': 'R227ea',
            'fluid_hp_cs': 'H2O',
            'fluid_he_cs': 'H2O',
            'fluid_st': 'H2O',
            'cb_type': 3,
            'version': 'thermodynamic_full',
            'eta_max_cp': self.parameters.get('eta_max_cp', 0.75),
            'eta_max_ex': self.parameters.get('eta_max_ex', 0.75),
            'eta_pm': 0.60,
            'dT_hp_ev_pp': self.parameters.get('dT_hp_ev_pp', 5.0),
            'dT_hp_cd_pp': self.parameters.get('dT_hp_cd_pp', 3.0),
            'dT_he_ev_pp': 3.0,
            'dT_he_cd_pp': 5.0,
            'dT_hp_ev_sh': self.parameters.get('dT_hp_ev_sh', 6.0),
            'dT_hp_cd_sc': self.parameters.get('dT_hp_cd_sc', 30.0),
            'dT_he_ev_sh': self.parameters.get('dT_he_ev_sh', 1.0),
            'dT_he_cd_sc': self.parameters.get('dT_he_cd_sc', 3.0)
        }
        return inputs

    def get_cb_efficiency(self):
        """Get Carnot battery efficiency"""
        return self.results.get('cb_efficiency', 0.0)

    def get_hp_cop(self):
        """Get heat pump COP"""
        return self.results.get('hp_cop', 0.0)

    def get_he_efficiency(self):
        """Get heat engine efficiency"""
        return self.results.get('he_efficiency', 0.0)

    def get_all_results(self):
        """Get all performance results"""
        return self.results.copy()

    def _extract_results_with_constraints(self, start_time):
        """
        Extract results with constraint violation tracking

        Returns:
            dict: Results including constraint violations and performance metrics
        """
        try:
            results = {}

            # Extract performance metrics from CBSim model
            if hasattr(self.model, 'results') and self.model.results:
                # Carnot battery efficiency
                results['cb_efficiency'] = getattr(self.model, 'eta_cb', 0.0)

                # Heat pump performance
                results['hp_cop'] = getattr(self.model, 'COP_hp', 0.0)
                results['hp_power'] = getattr(self.model, 'P_hp', 0.0)

                # Heat engine performance
                results['he_efficiency'] = getattr(self.model, 'eta_he', 0.0)
                results['he_power'] = getattr(self.model, 'P_he', 0.0)

                # Temperature constraints
                results['T_hp_ev'] = getattr(self.model, 'T_hp_ev', 0.0)
                results['T_hp_cd'] = getattr(self.model, 'T_hp_cd', 0.0)
                results['T_he_ev'] = getattr(self.model, 'T_he_ev', 0.0)
                results['T_he_cd'] = getattr(self.model, 'T_he_cd', 0.0)
            else:
                # Fallback values if model results not available
                results['cb_efficiency'] = 0.0
                results['hp_cop'] = 0.0
                results['he_efficiency'] = 0.0
                results['hp_power'] = 0.0
                results['he_power'] = 0.0
                results['T_hp_ev'] = 0.0
                results['T_hp_cd'] = 0.0
                results['T_he_ev'] = 0.0
                results['T_he_cd'] = 0.0

            # Calculate constraint violations
            constraint_violation = self._calculate_constraint_violations(results)
            results['constraint_violation'] = constraint_violation

            # Evaluation time
            results['evaluation_time'] = time.time() - start_time

            # Success flag
            results['success'] = True

            return results

        except Exception as e:
            self.logger.error(f"Error extracting results with constraints: {e}")
            return self._build_failure_results(e, start_time)

    def _calculate_constraint_violations(self, results):
        """
        Calculate constraint violations for the current solution

        Args:
            results: Dictionary containing model results

        Returns:
            float: Total constraint violation (0 = feasible, >0 = infeasible)
        """
        constraint_violation = 0.0

        # 1. Thermodynamic feasibility constraints
        # Carnot battery efficiency should be positive
        if results['cb_efficiency'] <= 0:
            constraint_violation += abs(results['cb_efficiency']) + 0.1

        # Heat pump COP should be > 1
        if results['hp_cop'] <= 1.0:
            constraint_violation += (1.0 - results['hp_cop']) + 0.1

        # Heat engine efficiency should be positive
        if results['he_efficiency'] <= 0:
            constraint_violation += abs(results['he_efficiency']) + 0.1

        # 2. Temperature feasibility constraints
        # Evaporator temperatures should be above freezing
        if results['T_hp_ev'] < 273.15:  # 0°C in Kelvin
            constraint_violation += (273.15 - results['T_hp_ev']) / 10.0

        if results['T_he_ev'] < 273.15:
            constraint_violation += (273.15 - results['T_he_ev']) / 10.0

        # 3. Power constraints (should be positive)
        if results['hp_power'] <= 0:
            constraint_violation += abs(results['hp_power']) + 0.1

        if results['he_power'] <= 0:
            constraint_violation += abs(results['he_power']) + 0.1

        # 4. Physical range constraints
        # Efficiency should be within reasonable bounds
        if results['cb_efficiency'] > 0.5:  # Unrealistically high
            constraint_violation += (results['cb_efficiency'] - 0.5) * 10

        if results['hp_cop'] > 10.0:  # Unrealistically high
            constraint_violation += (results['hp_cop'] - 10.0) * 10

        return constraint_violation

    def _build_failure_results(self, error, start_time):
        """
        Build failure results with error categorization

        Args:
            error: Exception that caused the failure
            start_time: Evaluation start time

        Returns:
            dict: Failure results with constraint violation
        """
        results = {}

        # Categorize failure types
        error_str = str(error).lower()

        if 'fsolve' in error_str or 'converge' in error_str:
            # Numerical convergence failure
            failure_type = 'numerical_convergence'
            constraint_violation = 1.0  # Moderate violation
        elif 'cycle' in error_str or 'inconsistent' in error_str:
            # Thermodynamic cycle inconsistency
            failure_type = 'thermodynamic_inconsistency'
            constraint_violation = 2.0  # High violation
        elif 'index' in error_str or 'range' in error_str:
            # Index or range error
            failure_type = 'data_access_error'
            constraint_violation = 3.0  # High violation
        elif 'import' in error_str or 'module' in error_str:
            # Import error
            failure_type = 'import_error'
            constraint_violation = 10.0  # Critical violation
        else:
            # Generic failure
            failure_type = 'generic_failure'
            constraint_violation = 1.5  # Moderate violation

        # Set failure results
        results['cb_efficiency'] = 0.0
        results['hp_cop'] = 0.0
        results['he_efficiency'] = 0.0
        results['hp_power'] = 0.0
        results['he_power'] = 0.0
        results['T_hp_ev'] = 0.0
        results['T_hp_cd'] = 0.0
        results['T_he_ev'] = 0.0
        results['T_he_cd'] = 0.0
        results['constraint_violation'] = constraint_violation
        results['evaluation_time'] = time.time() - start_time
        results['success'] = False
        results['failure_type'] = failure_type
        results['error_message'] = str(error)

        self.logger.warning(f"Evaluation failed - Type: {failure_type}, Violation: {constraint_violation}")

        return results


if __name__ == "__main__":
    """Test the model wrapper"""
    print("Testing CBSim model wrapper...")

    # Create model instance
    model = CBSimModel()

    # Set parameters (using values that worked in previous sampling)
    model.set_parameters(
        dT_hp_ev_sh=5.0,
        dT_hp_cd_sc=25.0,
        dT_he_ev_sh=1.2,
        dT_he_cd_sc=3.5,
        T_hp_cs=15.0,
        T_he_cs=15.0,
        T_st_ht=120.0,
        eta_max_cp=0.75,
        eta_max_ex=0.75,
        dT_hp_ev_pp=5.0,
        dT_hp_cd_pp=3.0
    )

    # Run evaluation
    success = model.evaluate()

    if success:
        results = model.get_all_results()
        print(f"Evaluation successful!")
        print(f"Carnot battery efficiency: {results['cb_efficiency']:.4f}")
        print(f"Heat pump COP: {results['hp_cop']:.4f}")
        print(f"Heat engine efficiency: {results['he_efficiency']:.4f}")
        print(f"Evaluation time: {results['evaluation_time']:.3f}s")
    else:
        print("Evaluation failed")