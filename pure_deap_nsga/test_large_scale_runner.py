#!/usr/bin/env python3
"""Fast optimizer-state tests for the large-scale runner."""

import numpy as np

from deap_optimizer import NSGAOptimizer


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


def normalized(front):
    return sorted(
        (tuple(round(float(value), 14) for value in ind),
         tuple(round(float(value), 14) for value in ind.fitness.values))
        for ind in front
    )


def main():
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
