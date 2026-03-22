#!/usr/bin/env python3
"""
卡诺电池多目标优化主脚本 - LHS采样版本（修正版）针对 position3

基于CBSim热力学模型和RHEIA优化框架，实现三目标优化：
1. 卡诺电池效率最大化
2. 热储能密度最大化
3. 㶲效率最大化

使用NSGA-II算法寻找Pareto最优前沿
使用LHS采样生成初始种群，然后进行完整的GA优化

针对 position3 (t_hs=60°C, t_cs=15°C) 和新的设计空间（11个变量）
"""

import os
import sys
import json
import time
import logging
import traceback
import numpy as np
import pandas as pd
from pathlib import Path

# Add RHEIA and CBSim paths
import pathlib as _pathlib
_SCRIPT_DIR = _pathlib.Path(__file__).resolve().parent
_RHEIA_DIR = _SCRIPT_DIR.parent / 'RHEIA'
sys.path.insert(0, str(_RHEIA_DIR))  # cross-platform

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('position3_optimization_lhs_fixed.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class Position3MultiObjectiveOptimizerLHSFixed:
    """多目标优化器类 - LHS采样版本（修正版）针对 position3"""

    def __init__(self, config_file):
        """
        初始化多目标优化器

        Args:
            config_file: 配置文件路径
        """
        self.config = self._load_config(config_file)
        self.results = {}
        self.pareto_front = []

    def _load_config(self, config_file):
        """加载配置文件"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info(f"成功加载配置文件: {config_file}")
            return config
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            raise

    def setup_optimization(self):
        """
        设置多目标优化参数

        Returns:
            dict: RHEIA优化参数字典
        """
        opt_params = {
            'case': 'CBSIM_POSITION_POSITION3',  # 使用 position3 case
            'objectives': {
                'DET': (-1, -1, -1)  # 三目标优化，全部最大化
            },
            'stop': ('BUDGET', 6000),      # 6000次评估（完整优化）
            'population size': 100,       # 种群大小100（完整优化）
            'n jobs': 1,                  # 单进程
            'results dir': 'position3_multi_objective_results_lhs_fixed_test',
            'x0': ('AUTO', 'LHS'),        # 初始种群使用LHS
            'cx prob': 0.9,               # 交叉概率
            'mut prob': 0.1,              # 变异概率
            'eta': 0.2                    # 分布指数
        }

        return opt_params

    def run_optimization(self):
        """运行多目标优化"""
        try:
            logger.info("开始 position3 多目标优化 - LHS采样版本（修正版）")

            # 设置优化参数
            opt_params = self.setup_optimization()
            logger.info(f"优化参数配置: {json.dumps(opt_params, indent=2, ensure_ascii=False)}")

            # 保存当前工作目录
            original_cwd = os.getcwd()

            # 切换到RHEIA目录
            rheia_dir = str(_pathlib.Path(__file__).resolve().parent.parent / 'RHEIA')
            os.chdir(rheia_dir)
            logger.info(f"切换到RHEIA目录: {os.getcwd()}")

            # 检查case目录是否存在
            case_dir = os.path.join(rheia_dir, 'rheia', 'CASES', 'CBSIM_POSITION_POSITION3')
            logger.info(f"检查case目录: {case_dir}")
            logger.info(f"目录存在: {os.path.exists(case_dir)}")
            if os.path.exists(case_dir):
                logger.info(f"目录内容: {os.listdir(case_dir)}")
            else:
                logger.error(f"case目录不存在: {case_dir}")
                raise FileNotFoundError(f"case目录不存在: {case_dir}")


            # 确保RHEIA路径在sys.path中
            if rheia_dir not in sys.path:
                sys.path.insert(0, rheia_dir)

            # 动态导入RHEIA优化模块
            from rheia.OPT.optimization import run_opt

            # 运行优化
            start_time = time.time()
            # 运行RHEIA优化
            logger.info("开始运行RHEIA优化（使用LHS初始种群）...")
            run_opt(opt_params)
            logger.info("RHEIA优化成功完成")

            optimization_time = time.time() - start_time

            # 恢复原始工作目录
            os.chdir(original_cwd)

            # 提取结果
            self._extract_pareto_front(opt_params, optimization_time)

            logger.info(f"position3 多目标优化完成，耗时: {optimization_time:.2f}s")
            logger.info(f"找到 {len(self.pareto_front)} 个Pareto最优解")

            # 保存结果
            self.save_results()

            return True

        except Exception as e:
            logger.error(f"position3 多目标优化失败: {e}")
            logger.error(f"异常堆栈跟踪:\n{traceback.format_exc()}")
            return False

    def _extract_pareto_from_rheia_results(self, fitness_file, population_file):
        """从RHEIA结果文件中提取帕累托前沿"""
        try:
            # 读取适应度文件（无表头），确保数值类型
            fitness_df = pd.read_csv(fitness_file, header=None)
            fitness_df = fitness_df.apply(pd.to_numeric, errors='coerce')

            # 读取种群文件（无表头），确保数值类型
            # position3 有11个设计变量
            population_df = pd.read_csv(population_file, header=None)
            population_df = population_df.apply(pd.to_numeric, errors='coerce')

            # 重命名列以便于访问
            # 3个目标值
            fitness_df.columns = ['f1', 'f2', 'f3']
            # 11个设计变量
            population_df.columns = [f'x{i+1}' for i in range(population_df.shape[1])]

            # 过滤掉无效解（适应度值为1000000.0的个体）
            valid_fitness = fitness_df[(fitness_df['f1'] < 1000000.0) &
                                      (fitness_df['f2'] < 1000000.0) &
                                      (fitness_df['f3'] < 1000000.0)]

            # 获取对应的设计变量
            valid_population = population_df.iloc[valid_fitness.index]

            # 构建帕累托前沿解
            self.pareto_front = []
            for i, (fitness_row, pop_row) in enumerate(zip(valid_fitness.itertuples(), valid_population.itertuples())):
                # 提取目标值（注意：RHEIA中目标值可能是负的，因为默认最小化）
                cb_efficiency = -fitness_row.f1  # 转换为最大化
                E_dens_th = -fitness_row.f2      # 转换为最大化
                eta_cb_exer = -fitness_row.f3    # 转换为最大化

                # 提取11个设计变量
                # 变量顺序应与design_space.csv中的顺序一致：
                # 1. dT_hp_cs_gl, 2. dT_hp_ev_sh, 3. dT_he_ev_sh, 4. dT_hp_cd_sc
                # 5. T_st_ht, 6. dT_st_sp, 7. fluid_hp_idx, 8. fluid_he_idx
                # 9. eta_max_cp, 10. eta_max_ex, 11. eta_pm
                # 处理可能为NaN的值
                def safe_round(value, decimals, default=0):
                    """安全地四舍五入，处理NaN值"""
                    if pd.isna(value):
                        return round(default, decimals)
                    try:
                        return round(float(value), decimals)
                    except (ValueError, TypeError):
                        return round(default, decimals)

                def safe_int(value, default=0):
                    """安全转换为整数，处理NaN值"""
                    if pd.isna(value):
                        return default
                    try:
                        return int(round(float(value)))  # 先四舍五入再转换
                    except (ValueError, TypeError):
                        return default

                solution = {
                    'solution_id': f'sol_{i+1:03d}',
                    'objectives': {
                        'cb_efficiency': safe_round(cb_efficiency, 4),
                        'E_dens_th': safe_round(E_dens_th, 2),
                        'eta_cb_exer': safe_round(eta_cb_exer, 4)
                    },
                    'design_variables': {
                        'dT_hp_cs_gl': safe_round(getattr(pop_row, 'x1', 0), 1),
                        'dT_hp_ev_sh': safe_round(getattr(pop_row, 'x2', 0), 1),
                        'dT_he_ev_sh': safe_round(getattr(pop_row, 'x3', 0), 1),
                        'dT_hp_cd_sc': safe_round(getattr(pop_row, 'x4', 0), 1),
                        'T_st_ht': safe_round(getattr(pop_row, 'x5', 0), 1),
                        'dT_st_sp': safe_round(getattr(pop_row, 'x6', 0), 1),
                        'fluid_hp_idx': safe_int(getattr(pop_row, 'x7', 0)),
                        'fluid_he_idx': safe_int(getattr(pop_row, 'x8', 0)),
                        'eta_max_cp': safe_round(getattr(pop_row, 'x9', 0), 3),
                        'eta_max_ex': safe_round(getattr(pop_row, 'x10', 0), 3),
                        'eta_pm': safe_round(getattr(pop_row, 'x11', 0), 3)
                    }
                }
                self.pareto_front.append(solution)

        except Exception as e:
            logger.error(f"从RHEIA结果提取帕累托前沿失败: {e}")
            self.pareto_front = []

    def _extract_pareto_front(self, opt_params, optimization_time):
        """提取帕累托前沿"""
        try:
            # 从RHEIA结果目录提取帕累托前沿
            rheia_results_dir = _pathlib.Path(__file__).resolve().parent.parent / 'RHEIA' / 'rheia' / 'RESULTS' / 'CBSIM_POSITION_POSITION3' / 'DET' / opt_params['results dir']

            # 检查RHEIA结果文件
            fitness_file = rheia_results_dir / 'fitness.csv'
            population_file = rheia_results_dir / 'population.csv'

            if fitness_file.exists() and population_file.exists():
                logger.info(f"从RHEIA结果目录提取帕累托前沿: {rheia_results_dir}")
                self._extract_pareto_from_rheia_results(fitness_file, population_file)
                logger.info(f"从RHEIA结果中提取到 {len(self.pareto_front)} 个帕累托解")
            else:
                logger.error("RHEIA结果文件不存在，无法提取帕累托前沿")
                raise FileNotFoundError("RHEIA优化结果文件不存在，请检查RHEIA优化是否成功运行")

            # 计算帕累托前沿统计
            self._calculate_pareto_statistics(optimization_time)

        except Exception as e:
            logger.error(f"提取帕累托前沿失败: {e}")
            raise RuntimeError(f"无法提取帕累托前沿: {e}")

    def _calculate_pareto_statistics(self, optimization_time):
        """计算帕累托前沿统计信息"""
        if not self.pareto_front:
            # 如果没有帕累托解，创建空的统计信息
            self.pareto_stats = {
                'optimization_time': optimization_time,
                'number_of_solutions': 0,
                'efficiency_stats': {
                    'min': 0.0,
                    'max': 0.0,
                    'mean': 0.0,
                    'std': 0.0
                },
                'energy_density_stats': {
                    'min': 0.0,
                    'max': 0.0,
                    'mean': 0.0,
                    'std': 0.0
                },
                'exergy_efficiency_stats': {
                    'min': 0.0,
                    'max': 0.0,
                    'mean': 0.0,
                    'std': 0.0
                }
            }
            logger.info("没有找到帕累托解，使用空的统计信息")
            return

        # 提取目标值
        efficiencies = [sol['objectives']['cb_efficiency'] for sol in self.pareto_front]
        energy_densities = [sol['objectives']['E_dens_th'] for sol in self.pareto_front]
        exergy_efficiencies = [sol['objectives']['eta_cb_exer'] for sol in self.pareto_front]

        self.pareto_stats = {
            'optimization_time': optimization_time,
            'number_of_solutions': len(self.pareto_front),
            'efficiency_stats': {
                'min': min(efficiencies),
                'max': max(efficiencies),
                'mean': np.mean(efficiencies),
                'std': np.std(efficiencies)
            },
            'energy_density_stats': {
                'min': min(energy_densities),
                'max': max(energy_densities),
                'mean': np.mean(energy_densities),
                'std': np.std(energy_densities)
            },
            'exergy_efficiency_stats': {
                'min': min(exergy_efficiencies),
                'max': max(exergy_efficiencies),
                'mean': np.mean(exergy_efficiencies),
                'std': np.std(exergy_efficiencies)
            }
        }

        logger.info(f"帕累托前沿统计: {self.pareto_stats}")

    def save_results(self):
        """保存优化结果"""
        try:
            # 创建结果目录
            results_dir = Path('position3_multi_objective_results_lhs_fixed')
            results_dir.mkdir(exist_ok=True)

            # 保存Pareto前沿
            pareto_file = results_dir / 'pareto_front.json'
            with open(pareto_file, 'w', encoding='utf-8') as f:
                json.dump(self.pareto_front, f, indent=2, ensure_ascii=False)

            # 保存统计信息
            stats_file = results_dir / 'pareto_statistics.json'
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.pareto_stats, f, indent=2, ensure_ascii=False)

            # 保存CSV格式的Pareto前沿
            self._save_pareto_csv(results_dir)

            logger.info(f"position3 多目标优化结果已保存到: {results_dir}")

        except Exception as e:
            logger.error(f"保存结果失败: {e}")

    def _save_pareto_csv(self, results_dir):
        """保存Pareto前沿为CSV格式"""
        if not self.pareto_front:
            return

        # 准备数据
        data = []
        for solution in self.pareto_front:
            row = {
                'solution_id': solution['solution_id'],
                'cb_efficiency': solution['objectives']['cb_efficiency'],
                'E_dens_th': solution['objectives']['E_dens_th'],
                'eta_cb_exer': solution['objectives']['eta_cb_exer'],
                'dT_hp_cs_gl': solution['design_variables']['dT_hp_cs_gl'],
                'dT_hp_ev_sh': solution['design_variables']['dT_hp_ev_sh'],
                'dT_he_ev_sh': solution['design_variables']['dT_he_ev_sh'],
                'dT_hp_cd_sc': solution['design_variables']['dT_hp_cd_sc'],
                'T_st_ht': solution['design_variables']['T_st_ht'],
                'dT_st_sp': solution['design_variables']['dT_st_sp'],
                'fluid_hp_idx': solution['design_variables']['fluid_hp_idx'],
                'fluid_he_idx': solution['design_variables']['fluid_he_idx'],
                'eta_max_cp': solution['design_variables']['eta_max_cp'],
                'eta_max_ex': solution['design_variables']['eta_max_ex'],
                'eta_pm': solution['design_variables']['eta_pm']
            }
            data.append(row)

        # 保存为CSV
        df = pd.DataFrame(data)
        csv_file = results_dir / 'pareto_front.csv'
        df.to_csv(csv_file, index=False, encoding='utf-8')


def create_default_config(config_file):
    """创建position3默认配置文件"""
    config = {
        "multi_objective_optimization": {
            "description": "卡诺电池多目标优化配置 - position3 (t_hs=60°C, t_cs=15°C)",
            "author": "CBSim Optimization Team",
            "version": "1.0",
            "date": "2025-12-06",
            "position_id": "position3",
            "position_name": "位置3 (t_hs=60°C, t_cs=15°C, ΔT_hs-cs=45K)"
        },

        "optimization_objectives": {
            "primary_objectives": [
                {
                    "name": "cb_efficiency",
                    "description": "卡诺电池电效率",
                    "type": "maximize",
                    "weight": 1.0,
                    "bounds": [0.0, 1.0],
                    "importance": "high"
                },
                {
                    "name": "E_dens_th",
                    "description": "热储能密度",
                    "type": "maximize",
                    "weight": 0.8,
                    "unit": "J_th/m³",
                    "bounds": [0.0, 1e9],
                    "importance": "medium"
                },
                {
                    "name": "eta_cb_exer",
                    "description": "㶲效率",
                    "type": "maximize",
                    "weight": 0.6,
                    "bounds": [0.0, 1.0],
                    "importance": "medium"
                }
            ],
            "secondary_objectives": [
                {
                    "name": "hp_cop",
                    "description": "热泵COP",
                    "type": "maximize",
                    "weight": 0.3,
                    "bounds": [0.0, 10.0]
                },
                {
                    "name": "he_efficiency",
                    "description": "热机效率",
                    "type": "maximize",
                    "weight": 0.3,
                    "bounds": [0.0, 1.0]
                }
            ]
        },

        "design_variables": {
            "continuous_variables": {
                "dT_hp_cs_gl": {
                    "type": "continuous",
                    "bounds": [0.0, 100.0],
                    "description": "热源温度滑移 ΔT_hs,gl (K)"
                },
                "dT_hp_ev_sh": {
                    "type": "continuous",
                    "bounds": [3.0, 20.0],
                    "description": "热泵蒸气过热度 ΔT_hp,sh (K)"
                },
                "dT_he_ev_sh": {
                    "type": "continuous",
                    "bounds": [3.0, 20.0],
                    "description": "ORC蒸气过热度 ΔT_orc,sh (K)"
                },
                "dT_hp_cd_sc": {
                    "type": "continuous",
                    "bounds": [3.0, 50.0],
                    "description": "热泵液体过冷度 ΔT_hp,sc (K)"
                },
                "T_st_ht": {
                    "type": "continuous",
                    "bounds": [50.0, 150.0],
                    "description": "热罐存储温度 t_st,ht (°C)"
                },
                "dT_st_sp": {
                    "type": "continuous",
                    "bounds": [5.0, 100.0],
                    "description": "存储温度扩散 ΔT_st,sp (K)"
                },
                "eta_max_cp": {
                    "type": "continuous",
                    "bounds": [0.70, 0.80],
                    "description": "压缩机等熵效率 η_is,comp"
                },
                "eta_max_ex": {
                    "type": "continuous",
                    "bounds": [0.70, 0.80],
                    "description": "膨胀机等熵效率 η_is,exp"
                },
                "eta_pm": {
                    "type": "continuous",
                    "bounds": [0.45, 0.55],
                    "description": "泵等熵效率 η_is,pmp"
                }
            },
            "discrete_variables": {
                "fluid_hp_idx": {
                    "type": "integer",
                    "bounds": [0, 33],
                    "description": "热泵工作流体索引 (0-33 对应34种流体)"
                },
                "fluid_he_idx": {
                    "type": "integer",
                    "bounds": [0, 33],
                    "description": "ORC工作流体索引 (0-33 对应34种流体)"
                }
            }
        },

        "operating_conditions": {
            "fixed_parameters": {
                "T_hp_cs": 60.0,
                "T_he_cs": 15.0,
                "dT_he_cs_gl": 10.0,
                "dT_he_cd_sc": 3.0,
                "dT_hp_ev_pp": 3.0,
                "dT_hp_cd_pp": 3.0,
                "dT_he_ev_pp": 3.0,
                "dT_he_cd_pp": 3.0,
                "fluid_st": "H2O",
                "fluid_hp_cs": "H2O",
                "fluid_he_cs": "H2O",
                "p_st": 7.5
            }
        },

        "optimization_algorithm": {
            "name": "NSGA-II",
            "description": "非支配排序遗传算法II",
            "parameters": {
                "population_size": 100,
                "max_generations": 200,
                "crossover_probability": 0.9,
                "mutation_probability": 0.1,
                "crossover_distribution_index": 20,
                "mutation_distribution_index": 20
            },
            "convergence_criteria": {
                "max_stagnation_generations": 50,
                "tolerance": 1e-6,
                "hypervolume_threshold": 0.95
            }
        },

        "constraints": {
            "thermodynamic_constraints": [
                {
                    "name": "temperature_approach",
                    "description": "最小夹点温度",
                    "condition": "dT_hp_ev_pp >= 2.5 and dT_hp_cd_pp >= 2.5 and dT_he_ev_pp >= 2.5 and dT_he_cd_pp >= 2.5",
                    "penalty": 1e6
                },
                {
                    "name": "superheat_limits",
                    "description": "过热度限制",
                    "condition": "dT_hp_ev_sh >= 3.0 and dT_he_ev_sh >= 3.0",
                    "penalty": 1e6
                },
                {
                    "name": "subcooling_limits",
                    "description": "过冷度限制",
                    "condition": "dT_hp_cd_sc >= 3.0 and dT_he_cd_sc >= 3.0",
                    "penalty": 1e6
                },
                {
                    "name": "storage_temperature_consistency",
                    "description": "存储温度一致性",
                    "condition": "T_st_ht - dT_st_sp >= T_hp_cs - dT_hp_cs_gl",
                    "penalty": 1e6
                },
                {
                    "name": "minimum_HP_temperature_rise",
                    "description": "最小热泵温升",
                    "condition": "T_st_ht - (T_hp_cs - dT_hp_cs_gl) >= 5.0",
                    "penalty": 1e6
                },
                {
                    "name": "minimum_ORC_temperature_drop",
                    "description": "最小ORC温降",
                    "condition": "(T_st_ht - dT_st_sp) - T_he_cs >= 5.0",
                    "penalty": 1e6
                }
            ],
            "performance_constraints": [
                {
                    "name": "minimum_efficiency",
                    "description": "最小效率要求",
                    "condition": "cb_efficiency >= 0.1",
                    "penalty": 1e6
                },
                {
                    "name": "minimum_energy_density",
                    "description": "最小储能密度",
                    "condition": "E_dens_th >= 1e7",
                    "penalty": 1e6
                }
            ]
        },

        "evaluation_settings": {
            "parallel_processing": {
                "enabled": True,
                "n_jobs": 4,
                "backend": "multiprocessing"
            },
            "model_evaluation": {
                "timeout": 300,
                "max_retries": 3,
                "fallback_values": {
                    "cb_efficiency": 0.0,
                    "E_dens_th": 0.0,
                    "eta_cb_exer": 0.0
                }
            }
        },

        "output_settings": {
            "results_directory": "position3_multi_objective_results",
            "save_format": ["csv", "json", "pickle"],
            "visualization": {
                "pareto_front": True,
                "convergence_plots": True,
                "parallel_coordinates": True,
                "radar_charts": True
            },
            "performance_metrics": {
                "hypervolume": True,
                "spacing": True,
                "generational_distance": True,
                "inverted_generational_distance": True
            },
            "report_generation": {
                "summary_report": True,
                "detailed_analysis": True,
                "comparison_with_single_objective": True
            }
        },

        "post_processing": {
            "decision_making": {
                "methods": ["TOPSIS", "weighted_sum", "compromise_programming"],
                "criteria_weights": {
                    "cb_efficiency": 0.5,
                    "E_dens_th": 0.3,
                    "eta_cb_exer": 0.2
                }
            },
            "sensitivity_analysis": {
                "enabled": True,
                "parameters": ["T_st_ht", "dT_hp_cs_gl", "dT_st_sp", "eta_max_cp", "eta_max_ex"],
                "variation_range": "±10%"
            }
        }
    }

    # 保存配置文件
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logging.getLogger(__name__).info(f"已创建默认配置文件: {config_file}")


def main():
    """主函数"""
    try:
        # 配置文件路径 - 使用position3专用配置文件
        script_dir = Path(__file__).parent
        config_file = script_dir / 'position3_multi_objective_config.json'

        # 检查配置文件是否存在，如果不存在则使用默认配置
        if not config_file.exists():
            logger.warning(f"配置文件 {config_file} 不存在，将使用默认配置")
            # 创建默认配置文件
            create_default_config(config_file)

        # 创建优化器实例
        optimizer = Position3MultiObjectiveOptimizerLHSFixed(str(config_file))

        # 运行多目标优化
        success = optimizer.run_optimization()

        if success:
            logger.info("position3 多目标优化分析全部完成 - LHS修正版本")
        else:
            logger.error("position3 多目标优化失败")

    except Exception as e:
        logger.error(f"position3 多目标优化分析失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()