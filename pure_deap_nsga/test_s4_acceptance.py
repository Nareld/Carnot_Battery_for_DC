#!/usr/bin/env python3
"""Deterministic numerical tests for S4 multi-seed acceptance."""

import numpy as np
import pandas as pd

from experiments.large_fluid_pairs.accept_s4_results import (
    exact_igd_plus, objective_union_front, rank_top_with_boundary_ties, sample_cv,
)


def brute_igd_plus(reference, approximation):
    distances = []
    for point in reference:
        distances.append(min(
            np.linalg.norm(np.maximum(point - candidate, 0.0))
            for candidate in approximation
        ))
    return float(np.mean(distances))


def test_exact_igd_plus_matches_brute_force():
    rng = np.random.default_rng(20260721)
    for reference_size in range(1, 18):
        reference = rng.random((reference_size, 3))
        approximation = rng.random((reference_size + 3, 3))
        expected = brute_igd_plus(reference, approximation)
        actual = exact_igd_plus(reference, approximation, chunk_size=4)
        assert abs(actual - expected) < 1e-15
        assert abs(exact_igd_plus(reference[::-1], approximation[::-1], chunk_size=1)
                   - expected) < 1e-15
    assert exact_igd_plus([[0.5, 0.5, 0.5]], [[0.6, 0.6, 0.6]]) == 0.0


def test_sample_cv_and_union_are_order_invariant():
    assert abs(sample_cv([1.0, 2.0, 3.0]) - 0.5) < 1e-15
    columns = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]
    first = pd.DataFrame([
        [0.8, 10.0, 0.3], [0.7, 20.0, 0.4], [0.5, 5.0, 0.2],
    ], columns=columns)
    second = pd.DataFrame([
        [0.6, 25.0, 0.2], [0.8, 10.0, 0.3], [0.4, 4.0, 0.1],
    ], columns=columns)
    forward = objective_union_front([first, second])
    backward = objective_union_front([
        second.sample(frac=1, random_state=2),
        first.sample(frac=1, random_state=3),
    ])
    assert np.array_equal(forward, backward)
    assert not any(np.all(row == [0.5, 5.0, 0.2]) for row in forward)


def test_rank_boundary_ties_are_included():
    ranks, top = rank_top_with_boundary_ties(
        [0.9, 0.8, 0.7, 0.7 * (1.0 - 5e-13), 0.6], 3
    )
    assert ranks.tolist() == [1, 2, 3, 3, 5]
    assert top.tolist() == [True, True, True, True, False]


def main():
    test_exact_igd_plus_matches_brute_force()
    test_sample_cv_and_union_are_order_invariant()
    test_rank_boundary_ties_are_included()
    print("S4 acceptance tests: 3/3 PASS")


if __name__ == "__main__":
    main()
