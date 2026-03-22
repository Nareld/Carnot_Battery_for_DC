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
    import _module_carnot_battery as CB
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
        Set model parameters with constraint checking

        Args:
            **kwargs: Model parameters
        """
        # 检查参数约束
        if not self._check_parameter_constraints(kwargs):
            self.logger.warning("Parameter constraints violated, using constrained values")
            kwargs = self._apply_parameter_constraints(kwargs)

        self.parameters.update(kwargs)

    def _check_parameter_constraints(self, parameters):
        """
        Check parameter constraints

        Args:
            parameters: Parameter dictionary

        Returns:
            bool: True if all constraints are satisfied
        """
        constraints = {
            'dT_hp_ev_sh': (4.0, 8.0),
            'dT_hp_cd_sc': (20.0, 45.0),
            'dT_he_ev_sh': (0.7, 1.5),
            'dT_he_cd_sc': (2.5, 4.0),
            'dT_hp_ev_pp': (3.0, 7.0),
            'dT_hp_cd_pp': (2.0, 5.0),
            'T_st_ht': (80.0, 160.0),
            'T_hp_cs': (5.0, 25.0),
            'T_he_cs': (5.0, 25.0)
        }

        for param, (min_val, max_val) in constraints.items():
            if param in parameters:
                value = parameters[param]
                if not (min_val <= value <= max_val):
                    self.logger.warning(f"Parameter {param}={value} violates constraint [{min_val}, {max_val}]")
                    return False

        return True

    def _apply_parameter_constraints(self, parameters):
        """
        Apply parameter constraints by clamping values

        Args:
            parameters: Parameter dictionary

        Returns:
            dict: Constrained parameters
        """
        constraints = {
            'dT_hp_ev_sh': (4.0, 8.0),
            'dT_hp_cd_sc': (20.0, 45.0),
            'dT_he_ev_sh': (0.7, 1.5),
            'dT_he_cd_sc': (2.5, 4.0),
            'dT_hp_ev_pp': (3.0, 7.0),
            'dT_hp_cd_pp': (2.0, 5.0),
            'T_st_ht': (80.0, 160.0),
            'T_hp_cs': (5.0, 25.0),
            'T_he_cs': (5.0, 25.0)
        }

        constrained_params = parameters.copy()
        for param, (min_val, max_val) in constraints.items():
            if param in constrained_params:
                value = constrained_params[param]
                if value < min_val:
                    constrained_params[param] = min_val
                elif value > max_val:
                    constrained_params[param] = max_val

        return constrained_params

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

            # 准备热泵输入
            p_hp_cs_su = 1e+5
            T_hp_cs_su = inputs['T_hp_cs'] + 273.15
            T_hp_cs_ex = T_hp_cs_su - inputs['dT_hp_cs_gl']
            m_hp_cs = 1.0
            i_hp_cs_su = CP.PropsSI('H', 'T', T_hp_cs_su, 'P', p_hp_cs_su, inputs['fluid_hp_cs'])
            i_hp_cs_ex = CP.PropsSI('H', 'T', T_hp_cs_ex, 'P', p_hp_cs_su, inputs['fluid_hp_cs'])
            P_hp = 1e+3

            # 准备热机输入
            p_he_cs_su = 1e+5
            T_he_cs_su = inputs['T_he_cs'] + 273.15
            T_he_cs_ex = T_he_cs_su + inputs['dT_he_cs_gl']
            m_he_cs = 1.0
            i_he_cs_su = CP.PropsSI('H', 'T', T_he_cs_su, 'P', p_he_cs_su, inputs['fluid_he_cs'])
            i_he_cs_ex = CP.PropsSI('H', 'T', T_he_cs_ex, 'P', p_he_cs_su, inputs['fluid_he_cs'])
            P_he = 1e+3

            T_st_ht_k = inputs['T_st_ht'] + 273.15

            # 完整参数字典
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

            # 准备选项
            print_flag, plot_flag = False, False
            debug = False
            exergy = True
            options = {'plot_flag': plot_flag,
                       'print_flag': print_flag,
                       'debug': debug,
                       'exergy': exergy}

            # 准备输入元组
            input_tuple = (p_hp_cs_su, i_hp_cs_su, p_hp_cs_su, i_hp_cs_ex, m_hp_cs, inputs['fluid_hp_cs'],
                          p_he_cs_su, i_he_cs_su, p_he_cs_su, i_he_cs_ex, m_he_cs, inputs['fluid_he_cs'],
                          P_hp, P_he)

            # 运行仿真
            self.model = CB.SRVCHP_SRORC_STES2T(input_tuple, my_CB_params, options)
            self.model.evaluate()

            # Extract performance metrics
            self.results = self._extract_results(start_time)

            self.logger.info(f"Evaluation successful - CB efficiency: {self.results['cb_efficiency']:.4f}")
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

    def get_multi_objective_values(self):
        """
        Get multi-objective values for DEAP optimization

        Returns:
            tuple: Three objective values (cb_efficiency, E_dens_th, eta_cb_exer)
        """
        # Get the three objective values according to config
        cb_efficiency = self.results.get('cb_efficiency', 0.0)
        E_dens_th = self.results.get('E_dens_th', 0.0)
        eta_cb_exer = self.results.get('eta_cb_exer', 0.0)

        # Debug logging - show what values are being returned
        self.logger.info(f"DEBUG - Returning multi-objective values:")
        self.logger.info(f"  cb_efficiency: {cb_efficiency:.6f}")
        self.logger.info(f"  E_dens_th: {E_dens_th:.6f}")
        self.logger.info(f"  eta_cb_exer: {eta_cb_exer:.6f}")

        # 返回三个目标值的元组，符合DEAP格式要求
        return (cb_efficiency, E_dens_th, eta_cb_exer)

    def get_all_results(self):
        """Get all performance results"""
        return self.results.copy()

    def _extract_results(self, start_time):
        """
        Extract performance metrics from CBSim model

        Returns:
            dict: Results including performance metrics
        """
        try:
            results = {}

            # Extract performance metrics from CBSim model
            if self.model is not None:
                # Carnot battery efficiency
                cb_efficiency = getattr(self.model, 'eta_cb_elec', 0.0)
                results['cb_efficiency'] = cb_efficiency

                # Heat pump performance
                hp_cop = getattr(self.model.my_HP, 'eta_hp_cyclen', 0.0)
                results['hp_cop'] = hp_cop
                results['hp_power'] = getattr(self.model, 'P_hp', 0.0)

                # Heat engine performance
                he_efficiency = getattr(self.model.my_HE, 'eta_he_cyclen', 0.0)
                results['he_efficiency'] = he_efficiency
                results['he_power'] = getattr(self.model, 'P_he', 0.0)

                # Multi-objective optimization metrics
                E_dens_th = getattr(self.model, 'E_dens_th', 0.0)
                results['E_dens_th'] = E_dens_th
                eta_cb_exer = getattr(self.model, 'eta_cb_exer', 0.0)
                results['eta_cb_exer'] = eta_cb_exer

                # Debug logging - show all three objective values
                self.logger.info(f"DEBUG - Multi-objective values extracted:")
                self.logger.info(f"  cb_efficiency: {cb_efficiency:.6f}")
                self.logger.info(f"  E_dens_th: {E_dens_th:.6f}")
                self.logger.info(f"  eta_cb_exer: {eta_cb_exer:.6f}")

                # Also log the actual model attributes for debugging
                self.logger.info(f"DEBUG - Model attributes:")
                self.logger.info(f"  model.eta_cb_elec: {getattr(self.model, 'eta_cb_elec', 'NOT_FOUND')}")
                self.logger.info(f"  model.E_dens_th: {getattr(self.model, 'E_dens_th', 'NOT_FOUND')}")
                self.logger.info(f"  model.eta_cb_exer: {getattr(self.model, 'eta_cb_exer', 'NOT_FOUND')}")
            else:
                # Fallback values if model results not available
                results['cb_efficiency'] = 0.0
                results['hp_cop'] = 0.0
                results['he_efficiency'] = 0.0
                results['hp_power'] = 0.0
                results['he_power'] = 0.0
                results['E_dens_th'] = 0.0
                results['eta_cb_exer'] = 0.0

            # Evaluation time
            results['evaluation_time'] = time.time() - start_time

            # Success flag
            results['success'] = True

            return results

        except Exception as e:
            self.logger.error(f"Error extracting results: {e}")
            return self._build_failure_results(e, start_time)


    def _build_failure_results(self, error, start_time):
        """
        Build failure results

        Args:
            error: Exception that caused the failure
            start_time: Evaluation start time

        Returns:
            dict: Failure results
        """
        results = {}

        # Set failure results
        results['cb_efficiency'] = 0.0
        results['hp_cop'] = 0.0
        results['he_efficiency'] = 0.0
        results['hp_power'] = 0.0
        results['he_power'] = 0.0
        results['E_dens_th'] = 0.0
        results['eta_cb_exer'] = 0.0
        results['evaluation_time'] = time.time() - start_time
        results['success'] = False
        results['error_message'] = str(error)

        self.logger.warning(f"Evaluation failed: {error}")

        return results


if __name__ == "__main__":
    """Test the model wrapper"""
    print("Testing CBSim model wrapper...")

    # Create model instance
    model = CBSimModel()

    # Set parameters (using values that worked in feasibility analysis)
    model.set_parameters(
        dT_hp_ev_sh=5.0,
        dT_hp_cd_sc=40.0,
        dT_he_ev_sh=1.0,
        dT_he_cd_sc=3.0,
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