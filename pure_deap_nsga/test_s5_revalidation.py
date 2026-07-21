#!/usr/bin/env python3
"""Numerical unit tests for S5 physical evidence helpers."""

import math

from experiments.large_fluid_pairs.run_s5_revalidation import (
    relative_closure, repeat_consistent,
)


def test_relative_closure():
    residual, relative = relative_closure([7.0, 3.0], [4.0, 6.0])
    assert residual == 0.0
    assert relative == 0.0
    residual, relative = relative_closure([8.0], [6.0])
    assert residual == 2.0
    assert math.isclose(relative, 2.0 / 14.0)


def test_repeat_consistency():
    row = {
        "status": "PASS",
        "computed_kpis": {
            "eta_p2p": 0.5, "energy_density_thermal": 20.0,
            "exergy_efficiency": 0.2,
        },
    }
    assert repeat_consistent([row, dict(row)])
    changed = {**row, "computed_kpis": {**row["computed_kpis"], "eta_p2p": 0.51}}
    assert not repeat_consistent([row, changed])
    assert not repeat_consistent([row])


def main():
    test_relative_closure()
    test_repeat_consistency()
    print("S5 revalidation tests: 2/2 PASS")


if __name__ == "__main__":
    main()
