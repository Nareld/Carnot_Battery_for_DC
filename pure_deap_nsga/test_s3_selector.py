#!/usr/bin/env python3
"""Fast deterministic tests for the S3 candidate selector."""

import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from experiments.large_fluid_pairs.select_s3_candidates import (
    OBJECTIVES, canonical_front, nondominated_mask_3d, normalized_hypervolume,
    select_unit, validate_accepted_registry,
)


def brute_mask(values):
    points = np.asarray(values, dtype=float)
    result = []
    for index, point in enumerate(points):
        dominated = any(
            other_index != index
            and np.all(other >= point)
            and np.any(other > point)
            for other_index, other in enumerate(points)
        )
        result.append(not dominated)
    return np.asarray(result, dtype=bool)


def test_nondominated_3d_matches_bruteforce():
    fixture = np.asarray([
        [1, 0, 0], [0, 1, 0], [0, 0, 1], [0.5, 0.5, 0.5],
        [0.4, 0.4, 0.4], [0.5, 0.5, 0.5], [0.5, 0.4, 0.5],
        [0.5, 0.5, 0.4], [0.5, 0.4, 0.6],
    ], dtype=float)
    assert np.array_equal(nondominated_mask_3d(fixture), brute_mask(fixture))
    rng = np.random.default_rng(20260720)
    for size in range(1, 61):
        values = rng.integers(0, 9, size=(size, 3)).astype(float) / 8.0
        assert np.array_equal(nondominated_mask_3d(values), brute_mask(values))
        shuffled = rng.permutation(size)
        assert np.array_equal(
            nondominated_mask_3d(values[shuffled]), brute_mask(values[shuffled])
        )


def candidate_frame(key, values):
    wp, cfg, fluid_hp, fluid_he = key.split("|")
    rows = []
    for index, value in enumerate(values):
        rows.append({
            **dict(zip(OBJECTIVES, value)), "wp": wp, "cfg": cfg,
            "fluid_hp": fluid_hp, "fluid_he": fluid_he,
            "candidate_key": key, "run_id": f"run_{fluid_hp}_{index}",
        })
    return pd.DataFrame(rows)


def test_selection_is_order_invariant_and_covers_extremes():
    keys_and_values = {
        "DC-A|CFG|A|he": [[0.95, 0.10, 0.10], [0.80, 0.15, 0.15]],
        "DC-A|CFG|B|he": [[0.10, 0.95, 0.10]],
        "DC-A|CFG|C|he": [[0.10, 0.10, 0.95]],
        "DC-A|CFG|D|he": [[0.62, 0.62, 0.62]],
        "DC-A|CFG|E|he": [[0.72, 0.42, 0.52]],
        "DC-A|CFG|F|he": [[0.52, 0.72, 0.42]],
        "DC-A|CFG|G|he": [[0.42, 0.52, 0.72]],
    }
    frames = {key: candidate_frame(key, values) for key, values in keys_and_values.items()}
    lower, upper, reference = np.zeros(3), np.ones(3), np.zeros(3)

    def execute(candidate_frames):
        pooled = canonical_front(pd.concat(list(candidate_frames.values()), ignore_index=True))
        counts = pooled["candidate_key"].value_counts().to_dict()
        hvs = {
            key: normalized_hypervolume(
                frame[OBJECTIVES], lower, upper, reference, 1e-12
            ) for key, frame in candidate_frames.items()
        }
        return select_unit(
            candidate_frames, pooled, 5, lower, upper, reference, 1e-12,
            counts, hvs,
        )

    selected, extremes = execute(frames)
    shuffled = {
        key: frames[key].sample(frac=1, random_state=index).reset_index(drop=True)
        for index, key in enumerate(reversed(list(frames)))
    }
    selected_again, extremes_again = execute(shuffled)
    identity = lambda rows: [
        (row["candidate_key"], row["selection_rank"], row["selected_reason"])
        for row in rows
    ]
    assert identity(selected) == identity(selected_again)
    assert [(row["objective"], row["candidate_key"]) for row in extremes] == [
        (row["objective"], row["candidate_key"]) for row in extremes_again
    ]
    assert len(selected) == 5
    assert {row["selection_rank"] for row in selected} == set(range(1, 6))
    selected_keys = {row["candidate_key"] for row in selected}
    assert {"DC-A|CFG|A|he", "DC-A|CFG|B|he", "DC-A|CFG|C|he"} <= selected_keys
    reasons = ";".join(row["selected_reason"] for row in selected)
    for objective in OBJECTIVES:
        assert f"extreme_{objective}" in reasons
    assert sum("greedy_incremental_hypervolume" in row["selected_reason"] for row in selected) == 2


def test_hypervolume_domain_gate():
    lower, upper, reference = np.zeros(3), np.asarray([1.0, 50.0, 1.0]), np.zeros(3)
    assert normalized_hypervolume(
        [[0.0, 0.0, 0.0], [1.0, 50.0, 1.0]], lower, upper, reference, 1e-12
    ) == 1.0
    invalid_rows = [
        [np.nan, 1.0, 0.5], [np.inf, 1.0, 0.5], [-1e-6, 1.0, 0.5],
        [1.000001, 1.0, 0.5], [0.5, 50.000001, 0.5], [0.5, 1.0, -1e-6],
    ]
    for row in invalid_rows:
        try:
            normalized_hypervolume([row], lower, upper, reference, 1e-12)
        except ValueError as exc:
            assert str(exc).startswith("S3_")
        else:
            raise AssertionError(f"invalid objective row accepted: {row}")


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_accepted_registry_gate():
    columns = {
        "run_id": "run1", "stage": "S2", "wp": "DC-A", "cfg": "CFG",
        "fluid_hp": "A", "fluid_he": "B", "seed": 42,
        "scheduler_status": "FINISHED", "terminal_status": "COMPLETED",
        "exit_code": 0, "hv_converged": True, "accepted_for_s3": True,
        "pareto_size": 1, "run_dir": "/tmp/run1", "manifest_path": "/tmp/manifest1",
        "run_manifest_sha256": "a", "run_checksums_sha256": "b",
        "final_normalized_hypervolume": 0.1, "evaluation_count": 10,
        "feasible_count": 9, "failure_count": 1,
        "revalidation_quarantined_count": 0,
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        registry_path = root / "accepted_run_registry.csv"
        pd.DataFrame([columns]).to_csv(registry_path, index=False)
        manifest = {
            "status": "ACCEPTED_FOR_S3", "task_count": 1,
            "accepted_registry_sha256": _hash(registry_path),
        }
        (root / "accepted_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        registry, _, _ = validate_accepted_registry(registry_path)
        assert len(registry) == 1

        rejected = dict(columns, accepted_for_s3=False)
        pd.DataFrame([rejected]).to_csv(registry_path, index=False)
        manifest["accepted_registry_sha256"] = _hash(registry_path)
        (root / "accepted_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        try:
            validate_accepted_registry(registry_path)
        except ValueError as exc:
            assert "S3_REGISTRY_GATE_FAILED" in str(exc)
        else:
            raise AssertionError("unaccepted S2 row passed the S3 gate")


def main():
    test_nondominated_3d_matches_bruteforce()
    test_selection_is_order_invariant_and_covers_extremes()
    test_hypervolume_domain_gate()
    test_accepted_registry_gate()
    print("S3 selector tests: 4/4 PASS")


if __name__ == "__main__":
    main()
