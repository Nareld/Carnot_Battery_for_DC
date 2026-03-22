#!/usr/bin/env python3
"""
卡诺电池多目标优化主脚本 - LHS采样版本（修正版）针对 position2

基于CBSim热力学模型和RHEIA优化框架，实现三目标优化：
1. 卡诺电池效率最大化
2. 热储能密度最大化
3. 㶲效率最大化

使用NSGA-II算法寻找Pareto最优前沿
使用LHS采样生成初始种群，然后进行完整的GA优化

针对 position2 (t_hs=40°C, t_cs=30°C) 和新的设计空间（11个变量）
支持快速测试模式（10次评估）和完整优化模式（6000次评估）
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
        logging.FileHandler('position2_optimization_lhs_fixed.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class Position2MultiObjectiveOptimizerLHSFixed:
    """多目标优化器类 - LHS采样版本（修正版）针对 position2"""

    def __init__(self, config_file=None, test_mode=False):
        """
        初始化多目标优化器

        Args:
            config_file: 配置文件路径（可选）
            test_mode: 测试模式标志，True时使用快速测试参数
        """
        self.test_mode = test_mode
        if config_file and os.path.exists(config_file):
            self.config = self._load_config(config_file)
        else:
            self.config = self._get_default_config()
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

    def _get_default_config(self):
        """获取默认配置"""
        config = {
            "position_id": "position2",
            "operating_conditions": {
                "fixed_parameters": {
                    "T_hp_cs": 40.0,
                    "T_he_cs": 30.0
                }
            },
            "optimization": {
                "algorithm": "NSGA-II",
                "population_size": 100,
                "generations": 60,
                "crossover_probability": 0.9,
                "mutation_probability": 0.1,
                "seed": 42
            }
        }
        logger.info("使用默认配置")
        return config

    def setup_optimization(self):
        """
        设置多目标优化参数

        Returns:
            dict: RHEIA优化参数字典
        """
        if self.test_mode:
            # 快速测试参数（10次评估）
            logger.info("使用快速测试参数：10次评估，种群大小20")
            opt_params = {
                'case': 'CBSIM_POSITION_POSITION2',  # 使用 position2 case
                'objectives': {
                    'DET': (-1, -1, -1)  # 三目标优化，全部最大化
                },
                'stop': ('BUDGET', 10),      # 10次评估（快速测试）
                'population size': 20,       # 种群大小20（快速测试）
                'n jobs': 1,                 # 单进程
                'results dir': 'position2_multi_objective_results_lhs_fixed_test',
                'x0': ('AUTO', 'LHS'),       # 初始种群使用LHS
                'cx prob': 0.9,              # 交叉概率
                'mut prob': 0.1,             # 变异概率
                'eta': 0.2                   # 分布指数
            }
        else:
            # 完整优化参数（6000次评估）
            logger.info("使用完整优化参数：6000次评估，种群大小100")
            opt_params = {
                'case': 'CBSIM_POSITION_POSITION2',  # 使用 position2 case
                'objectives': {
                    'DET': (-1, -1, -1)  # 三目标优化，全部最大化
                },
                'stop': ('BUDGET', 6000),    # 6000次评估（完整优化）
                'population size': 100,      # 种群大小100（完整优化）
                'n jobs': 1,                 # 单进程
                'results dir': 'position2_multi_objective_results_lhs_fixed',
                'x0': ('AUTO', 'LHS'),       # 初始种群使用LHS
                'cx prob': 0.9,              # 交叉概率
                'mut prob': 0.1,             # 变异概率
                'eta': 0.2                   # 分布指数
            }

        return opt_params

    def run_optimization(self):
        """运行多目标优化"""
        try:
            logger.info("开始 position2 多目标优化 - LHS采样版本（修正版）")
            if self.test_mode:
                logger.info("模式：快速测试（10次评估）")
            else:
                logger.info("模式：完整优化（6000次评估）")

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
            case_dir = os.path.join(rheia_dir, 'rheia', 'CASES', 'CBSIM_POSITION_POSITION2')
            logger.info(f"检查case目录: {case_dir}")
            if os.path.exists(case_dir):
                logger.info(f"目录存在，内容: {os.listdir(case_dir)}")
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
            logger.info("开始运行RHEIA优化（使用LHS初始种群）...")
            run_opt(opt_params)
            logger.info("RHEIA优化成功完成")

            optimization_time = time.time() - start_time

            # 恢复原始工作目录
            os.chdir(original_cwd)

            # 提取结果
            self._extract_pareto_front(opt_params, optimization_time)

            logger.info(f"position2 多目标优化完成，耗时: {optimization_time:.2f}s")
            logger.info(f"找到 {len(self.pareto_front)} 个Pareto最优解")

            # 保存结果
            self._save_results(opt_params, optimization_time)

            return True

        except Exception as e:
            logger.error(f"优化运行失败: {e}")
            logger.error(traceback.format_exc())
            return False

    def _extract_pareto_front(self, opt_params, optimization_time):
        """从RHEIA结果中提取Pareto前沿"""
        try:
            # 构建结果目录路径 - RHEIA将结果保存在 rheia/RESULTS/{case}/DET/{results_dir}
            # 注意：此时工作目录在 RHEIA 目录（动态路径，跨平台）
            case_name = opt_params['case']
            results_dir_name = opt_params['results dir']
            results_dir = os.path.join(
                'rheia', 'RESULTS', case_name, 'DET', results_dir_name
            )

            logger.info(f"查找结果目录: {results_dir}")
            logger.info(f"当前工作目录: {os.getcwd()}")

            if not os.path.exists(results_dir):
                logger.error(f"结果目录不存在: {results_dir}")
                # 列出可能的结果目录
                rheia_results_base = os.path.join('rheia', 'RESULTS', case_name, 'DET')
                if os.path.exists(rheia_results_base):
                    logger.info(f"DET目录存在，内容: {os.listdir(rheia_results_base)}")
                return

            # 读取适应度值
            fitness_file = os.path.join(results_dir, 'fitness.csv')
            if os.path.exists(fitness_file):
                fitness_df = pd.read_csv(fitness_file, header=None)
                # 转换为数值
                fitness_array = fitness_df.values
                logger.info(f"读取适应度值，形状: {fitness_array.shape}")

                # 过滤掉惩罚值（1000000）
                valid_mask = (fitness_array[:, 0] < 1e5) & (fitness_array[:, 1] < 1e5) & (fitness_array[:, 2] < 1e5)
                valid_fitness = fitness_array[valid_mask]
                logger.info(f"有效评估数量: {valid_fitness.shape[0]}/{fitness_array.shape[0]}")

                # 存储Pareto前沿（所有有效解）
                self.pareto_front = valid_fitness.tolist()
            else:
                logger.warning(f"适应度文件不存在: {fitness_file}")

            # 读取种群
            population_file = os.path.join(results_dir, 'population.csv')
            if os.path.exists(population_file):
                population_df = pd.read_csv(population_file, header=None)
                logger.info(f"读取种群数据，形状: {population_df.shape}")
                self.results['population'] = population_df.values.tolist()

        except Exception as e:
            logger.error(f"提取Pareto前沿失败: {e}")
            logger.error(traceback.format_exc())

    def _save_results(self, opt_params, optimization_time):
        """保存优化结果"""
        try:
            # 创建结果目录
            results_dir = Path('position2_multi_objective_results_lhs_fixed')
            results_dir.mkdir(exist_ok=True)

            # 保存Pareto前沿
            pareto_file = os.path.join(results_dir, 'pareto_front.csv')
            if self.pareto_front:
                pareto_df = pd.DataFrame(self.pareto_front)
                pareto_df.to_csv(pareto_file, index=False, header=False)
                logger.info(f"Pareto前沿已保存: {pareto_file}")

            # 保存优化摘要
            summary_file = os.path.join(results_dir, 'optimization_summary.json')

            # 创建可序列化的opt_params副本
            serializable_params = {}
            for key, value in opt_params.items():
                try:
                    # 尝试序列化值
                    json.dumps(value)
                    serializable_params[key] = value
                except (TypeError, ValueError):
                    # 如果无法序列化，转换为字符串
                    serializable_params[key] = str(value)

            summary = {
                "position_id": "position2",
                "optimization_mode": "test" if self.test_mode else "full",
                "optimization_time": optimization_time,
                "pareto_front_size": len(self.pareto_front),
                "parameters": serializable_params,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            logger.info(f"优化摘要已保存: {summary_file}")

        except Exception as e:
            logger.error(f"保存结果失败: {e}")
            logger.error(traceback.format_exc())


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Position2 多目标优化脚本')
    parser.add_argument('--test', action='store_true', help='快速测试模式（10次评估）')
    parser.add_argument('--config', type=str, help='配置文件路径（可选）')
    parser.add_argument('--full', action='store_true', help='完整优化模式（6000次评估）')

    args = parser.parse_args()

    # 确定模式
    test_mode = args.full   # 覆盖为完整优化模式
    try:
        optimizer = Position2MultiObjectiveOptimizerLHSFixed(
            config_file=args.config,
            test_mode=test_mode
        )

        success = optimizer.run_optimization()

        if success:
            logger.info("position2 优化成功完成")
            sys.exit(0)
        else:
            logger.error("position2 优化失败")
            sys.exit(1)

    except Exception as e:
        logger.error(f"优化过程异常: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()