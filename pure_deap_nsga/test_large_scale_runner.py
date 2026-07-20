#!/usr/bin/env python3
"""Fast optimizer-state and remediation tests for the large-scale runner."""

import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from deap_optimizer import CBEvaluator, INFEASIBLE_PENALTY, NSGAOptimizer
from experiments.large_fluid_pairs.run_large_scale import (
    nondominated_mask, pair_gate, revalidate_archive, stage_for_code,
)
from experiments.large_fluid_pairs.select_s2_candidates import summarize_pairs
from _module_heat_engine import _bounded_least_squares


HERE = Path(__file__).resolve().parent


class SyntheticEvaluator:
    objectives = ["f1", "f2"]
    n_vars = 2
    lb = np.array([0.0, 0.0])
    ub = np.array([1.0, 1.0])
    cfg = {
        "hypervolume": {
            "enabled": True, "schema_version": "test",
            "algorithm": "deap_exact_max_v1",
            "objectives": ["f1", "f2"],
            "normalization_bounds": {"f1": [0.0, 1.0], "f2": [0.0, 1.01]},
            "reference_point_normalized": [0.0, 0.0],
            "window_generations": 1, "relative_tolerance": 0.005,
            "minimum_generations": 1, "consecutive_generations": 1,
            "stop_on_convergence": False,
        }
    }

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


class HVFixtureEvaluator:
    objectives = ["f1", "f2", "f3"]
    n_vars = 1
    lb = np.array([0.0])
    ub = np.array([1.0])
    cfg = {
        "hypervolume": {
            "enabled": True, "schema_version": "test",
            "algorithm": "deap_exact_max_v1",
            "objectives": ["f1", "f2", "f3"],
            "normalization_bounds": {
                "f1": [0.0, 1.0], "f2": [0.0, 1.0], "f3": [0.0, 1.0],
            },
            "reference_point_normalized": [0.0, 0.0, 0.0],
            "window_generations": 1, "relative_tolerance": 0.005,
            "minimum_generations": 1, "consecutive_generations": 1,
            "stop_on_convergence": False,
        }
    }

    @staticmethod
    def evaluate(x):
        return float(x[0]), float(x[0]), float(x[0])

    @staticmethod
    def decode(x):
        return {"x0": x[0]}


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
    saturation_message = (
        'Saturation pressure [250000 Pa] corresponding to T [400.561 K] '
        'is within 1e-4 % of given p [250000 Pa]'
    )
    assert CBEvaluator._property_failure_code(saturation_message) == (
        "COOLPROP_SATURATION_BOUNDARY_AMBIGUITY"
    )
    evaluator = object.__new__(CBEvaluator)
    normalized = evaluator._normalize_issues([{
        "code": "EVALUATE_CYCLE_EXCEPTION",
        "component": "CB",
        "severity": "error",
        "message": saturation_message,
    }])
    assert normalized[0]["code"] == (
        "COOLPROP_SATURATION_BOUNDARY_AMBIGUITY"
    )
    assert normalized[0]["values"]["wrapped_code"] == (
        "EVALUATE_CYCLE_EXCEPTION"
    )
    assert evaluator._primary_from_issues(
        normalized, "EVALUATE_CYCLE_EXCEPTION"
    ) == "COOLPROP_SATURATION_BOUNDARY_AMBIGUITY"
    assert stage_for_code(
        "COOLPROP_SATURATION_BOUNDARY_AMBIGUITY",
        "property", "evaluate", saturation_message,
    ) == "PROPERTY_INPUT_BUILD"
    extension = config["experiment"]["profiles"]["S2_exception_extension"]
    assert extension["maximum_generations"] == 450
    assert extension["resume_from_previous_checkpoint"] is False
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


def test_fixed_hypervolume_and_rescreening():
    optimizer = NSGAOptimizer(HVFixtureEvaluator(), pop_size=4, n_gen=1, seed=2)
    point = optimizer.toolbox.individual()
    point[:] = [0.5]
    point.fitness.values = (0.5, 0.5, 0.5)
    assert abs(optimizer.normalized_hypervolume([point]) - 0.125) < 1e-12
    dominated = optimizer.toolbox.individual()
    dominated[:] = [0.2]
    dominated.fitness.values = (0.2, 0.2, 0.2)
    assert abs(optimizer.normalized_hypervolume([dominated, point]) - 0.125) < 1e-12
    assert abs(optimizer.normalized_hypervolume([point, dominated, point]) - 0.125) < 1e-12
    assert nondominated_mask([[0.5, 0.5], [0.4, 0.4], [0.6, 0.3]]) == [True, False, True]
    try:
        optimizer.normalized_hypervolume_values([[1.1, 0.5, 0.5]])
    except ValueError as exc:
        assert "HV_OBJECTIVE_OUT_OF_NORMALIZATION_BOUNDS" in str(exc)
    else:
        raise AssertionError("HV normalization must reject real out-of-domain values")

    stopping_evaluator = HVFixtureEvaluator()
    stopping_evaluator.cfg = json.loads(json.dumps(HVFixtureEvaluator.cfg))
    stopping_evaluator.cfg["hypervolume"].update({
        "minimum_generations": 2, "consecutive_generations": 2,
        "stop_on_convergence": True,
    })
    stopping = NSGAOptimizer(
        stopping_evaluator, pop_size=4, n_gen=10,
        cx_prob=0.0, mut_prob=0.0, seed=5,
    )
    stopping.run(verbose=False)
    assert stopping.completed_generations == 3
    assert stopping.stopping_reason == "hypervolume_converged"


def test_isolated_front_revalidation():
    config_path = (
        HERE / "experiments" / "large_fluid_pairs" /
        "optimization_config_large_pairs.json"
    ).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    wp = config["working_points"]["DC-A"]
    opt = dict(config["optimization"])
    evaluator = CBEvaluator(
        wp, opt, "SBVCHP_SBORC_STES2T", "R1233zd(E)", "R227EA",
        opt["objectives"],
    )
    good = [80.0, 30.0, 10.0, 5.0, 1.0, 5.0, 0.8, 0.8, 0.5]
    good_values = evaluator.evaluate(good)
    assert evaluator.last_eval_info["feasible"]
    invalid = [50.0, 60.0, 10.0, 5.0, 1.0, 5.0, 0.8, 0.8, 0.5]
    raw = pd.DataFrame([
        {**evaluator.decode(good), **dict(zip(opt["objectives"], good_values))},
        {**evaluator.decode(invalid), **dict(zip(opt["objectives"], good_values))},
    ])
    optimizer = NSGAOptimizer(evaluator, pop_size=4, n_gen=1, seed=1)
    with tempfile.TemporaryDirectory() as temporary:
        run_dir = Path(temporary)
        task = {
            "run_id": "front_revalidation_test", "stage": "TEST",
            "wp": "DC-A", "cfg": "SBVCHP_SBORC",
            "cb_class": "SBVCHP_SBORC_STES2T",
            "fluid_hp": "R1233zd(E)", "fluid_he": "R227EA", "seed": 42,
            "population_size": 4, "n_generations": 1,
            "checkpoint_every": 1, "archive_tol": 1e-9,
            "mode": "optimize", "screening_samples": 256,
            "config_path": str(config_path), "config_sha256": "test",
            "run_dir": str(run_dir), "resume_from": None,
        }
        certified, summary = revalidate_archive(
            task, raw, optimizer, config, run_dir
        )
        ledger = pd.read_csv(run_dir / "outputs" / "front_revalidation.csv")
        assert summary["raw_archive_size"] == 2
        assert summary["quarantined_count"] == 1
        assert len(certified) == 1
        assert len(ledger) == 2
        assert ledger["kept_in_certified_pareto"].sum() == 1
        assert np.allclose(
            certified.iloc[0][opt["objectives"]].to_numpy(dtype=float),
            np.asarray(good_values), rtol=1e-8, atol=1e-10,
        )


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
    test_fixed_hypervolume_and_rescreening()
    test_isolated_front_revalidation()
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
        SyntheticEvaluator(), pop_size=8, n_gen=3,
        cx_prob=0.9, mut_prob=0.2, seed=19,
    )
    first.run(
        verbose=False, checkpoint_every=1,
        checkpoint_callback=lambda payload: (
            checkpoint.update(payload) if payload["generation"] == 1 else None
        ),
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
    clean_resumed = [
        {key: value for key, value in row.items() if key != "elapsed_s"}
        for row in resumed.generation_metrics
    ]
    clean_full = [
        {key: value for key, value in row.items() if key != "elapsed_s"}
        for row in full.generation_metrics
    ]
    assert clean_resumed == clean_full
    hvs = [row["normalized_hypervolume"] for row in full.generation_metrics]
    assert all(right + 1e-12 >= left for left, right in zip(hvs, hvs[1:]))
    print("large-scale optimizer tests: PASS")


if __name__ == "__main__":
    main()
