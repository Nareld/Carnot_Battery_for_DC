#!/usr/bin/env python3
"""Fast optimizer-state and remediation tests for the large-scale runner."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from deap_optimizer import INFEASIBLE_PENALTY, NSGAOptimizer
from experiments.large_fluid_pairs.run_large_scale import pair_gate, stage_for_code
from experiments.large_fluid_pairs.select_s2_candidates import summarize_pairs
from _module_heat_engine import _bounded_least_squares


HERE = Path(__file__).resolve().parent


class SyntheticEvaluator:
    objectives = ["f1", "f2"]
    n_vars = 2
    lb = np.array([0.0, 0.0])
    ub = np.array([1.0, 1.0])

    def __init__(self):
        self.calls = 0

    def evaluate(self, x):
        self.calls += 1
        return float(x[0]), float(1.0 - x[0] + 0.01 * x[1])

    @staticmethod
    def decode(x):
        return {"x0": x[0], "x1": x[1]}


class ConstraintGradientEvaluator:
    objectives = ["f1", "f2"]
    n_vars = 1
    lb = np.array([0.0])
    ub = np.array([1.0])

    def evaluate(self, x):
        self.last_eval_info = {
            "feasible": False,
            "constraint_violation": 1.0 - float(x[0]),
        }
        return INFEASIBLE_PENALTY, INFEASIBLE_PENALTY


def test_constraint_guidance():
    optimizer = NSGAOptimizer(
        ConstraintGradientEvaluator(), pop_size=4, n_gen=1, seed=3
    )
    far = optimizer.toolbox.individual()
    near = optimizer.toolbox.individual()
    far[:] = [0.1]
    near[:] = [0.9]
    optimizer._evaluate_invalid([far, near])
    assert near.fitness.values[0] > far.fitness.values[0]
    assert not optimizer._fitness_is_feasible(near.fitness.values)


def test_reference_gate_and_stage_mapping():
    config = json.loads((
        HERE / "experiments" / "large_fluid_pairs" /
        "optimization_config_large_pairs.json"
    ).read_text(encoding="utf-8"))
    result = pair_gate(config, "DC-E", "CycloHexane", "R236ea")
    assert not result["passed"]
    assert any(
        issue["code"] == "FLUID_FILTER_REFERENCE_STATE_BELOW_TRIPLE"
        for issue in result["issues"]
    )
    assert stage_for_code(
        "SOLVER_RESIDUAL_TOO_HIGH", "HP", "check_consistency", ""
    ) == "HP_CONSISTENCY"
    assert stage_for_code(
        "SOLVER_PRESSURE_INTERVAL_DEGENERATE", "solver", "evaluate",
        "SBORC.find_p.fallback",
    ) == "HE_PRESSURE_SOLVE"
    assert stage_for_code(
        "COOLPROP_PROPERTY_INPUT_OUT_OF_RANGE", "property", "evaluate", ""
    ) == "PROPERTY_INPUT_BUILD"
    try:
        _bounded_least_squares(
            lambda x: x, [1.0], [1.0], [1.0], "test.degenerate"
        )
    except ValueError as exc:
        assert "SOLVER_PRESSURE_INTERVAL_DEGENERATE" in str(exc)
    else:
        raise AssertionError("degenerate solver interval must be rejected")


def test_configuration_aware_summary():
    config = json.loads((
        HERE / "experiments" / "large_fluid_pairs" /
        "optimization_config_large_pairs.json"
    ).read_text(encoding="utf-8"))
    samples = pd.DataFrame([
        {"wp": "DC-B", "cb_config": "SBVCHP_SBORC",
         "fluid_hp": "R245fa", "fluid_he": "R152A", "feasible": True,
         "primary_code": None, "eta_p2p": .2,
         "energy_density_thermal": 30., "exergy_efficiency": .15},
        {"wp": "DC-B", "cb_config": "SRVCHP_SRORC",
         "fluid_hp": "R245fa", "fluid_he": "R152A", "feasible": False,
         "primary_code": "STATE_ENTROPY_ORDER", "eta_p2p": np.nan,
         "energy_density_thermal": np.nan, "exergy_efficiency": np.nan},
    ])
    summary = summarize_pairs(samples, config)
    assert len(summary) == 2
    rates = summary.set_index("cb_config")["feasible_rate"].to_dict()
    assert rates["SBVCHP_SBORC"] == 1.0
    assert rates["SRVCHP_SRORC"] == 0.0


def normalized(front):
    return sorted(
        (tuple(round(float(value), 14) for value in ind),
         tuple(round(float(value), 14) for value in ind.fitness.values))
        for ind in front
    )


def main():
    test_constraint_guidance()
    test_reference_gate_and_stage_mapping()
    test_configuration_aware_summary()
    evaluator = SyntheticEvaluator()
    optimizer = NSGAOptimizer(
        evaluator, pop_size=101, n_gen=2, cx_prob=0.0, mut_prob=1.0, seed=7
    )
    assert optimizer.pop_size == 104
    optimizer.run(verbose=False)
    assert evaluator.calls == 104 * 3, (
        "mutation-only offspring must be invalidated and evaluated every generation"
    )
    assert all(metric["n_evaluated"] == 104 for metric in optimizer.generation_metrics)

    checkpoint = {}
    first = NSGAOptimizer(
        SyntheticEvaluator(), pop_size=8, n_gen=1,
        cx_prob=0.9, mut_prob=0.2, seed=19,
    )
    first.run(
        verbose=False, checkpoint_every=1,
        checkpoint_callback=lambda payload: checkpoint.update(payload),
    )

    resumed = NSGAOptimizer(
        SyntheticEvaluator(), pop_size=8, n_gen=3,
        cx_prob=0.9, mut_prob=0.2, seed=19,
    )
    resumed_front, _ = resumed.run(verbose=False, resume_state=checkpoint)

    full = NSGAOptimizer(
        SyntheticEvaluator(), pop_size=8, n_gen=3,
        cx_prob=0.9, mut_prob=0.2, seed=19,
    )
    full_front, _ = full.run(verbose=False)
    assert normalized(resumed_front) == normalized(full_front)
    print("large-scale optimizer tests: PASS")


if __name__ == "__main__":
    main()
