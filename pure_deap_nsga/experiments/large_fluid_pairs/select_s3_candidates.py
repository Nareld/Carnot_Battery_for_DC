#!/usr/bin/env python3
"""Pool accepted S2 fronts and select reproducible candidates for S4.

S3 is a deterministic post-processing stage.  It accepts only the canonical
S2 registry, verifies every certified front, pools fronts by working point and
configuration, preserves the three objective extremes, and fills the remaining
slots by exact normalized-hypervolume gain.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Iterable

from deap.tools._hypervolume import hv as deap_hv
import numpy as np
import pandas as pd


OBJECTIVES = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]
REGISTRY_KEY = ["wp", "cfg", "fluid_hp", "fluid_he", "seed"]
PAIR_KEY = ["wp", "cfg", "fluid_hp", "fluid_he"]
ALGORITHM_VERSION = "s3_exact_hv_extreme_coverage_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_to_csv(frame: pd.DataFrame, path: Path) -> None:
    atomic_write_text(path, frame.to_csv(index=False, lineterminator="\n"))


def git_state(repository: Path) -> tuple[str, bool]:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repository, text=True
    ).strip())
    return commit, dirty


def _truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin({"true", "1", "yes"})


def _candidate_key(row: pd.Series | object) -> str:
    def value(name: str):
        if hasattr(row, name):
            return getattr(row, name)
        return row[name]
    return "|".join(str(value(name)) for name in PAIR_KEY)


def validate_accepted_registry(registry_path: Path) -> tuple[pd.DataFrame, dict, Path]:
    """Validate the canonical S2 registry and its acceptance manifest."""
    registry_path = registry_path.resolve()
    accepted_manifest_path = registry_path.parent / "accepted_manifest.json"
    if not accepted_manifest_path.is_file():
        raise ValueError(f"S3_ACCEPTED_MANIFEST_MISSING: {accepted_manifest_path}")
    accepted_manifest = json.loads(accepted_manifest_path.read_text(encoding="utf-8"))
    if accepted_manifest.get("status") != "ACCEPTED_FOR_S3":
        raise ValueError("S3_INPUT_NOT_ACCEPTED_FOR_S3")
    expected_registry_hash = accepted_manifest.get("accepted_registry_sha256")
    actual_registry_hash = sha256_file(registry_path)
    if expected_registry_hash != actual_registry_hash:
        raise ValueError(
            "S3_ACCEPTED_REGISTRY_HASH_MISMATCH: "
            f"expected={expected_registry_hash} actual={actual_registry_hash}"
        )

    registry = pd.read_csv(registry_path)
    required = set(REGISTRY_KEY + [
        "run_id", "stage", "scheduler_status", "terminal_status", "exit_code",
        "hv_converged", "accepted_for_s3", "pareto_size", "run_dir",
        "manifest_path", "run_manifest_sha256", "run_checksums_sha256",
        "final_normalized_hypervolume", "evaluation_count", "feasible_count",
        "failure_count", "revalidation_quarantined_count",
    ])
    missing = sorted(required - set(registry.columns))
    if missing:
        raise ValueError(f"S3_REGISTRY_COLUMNS_MISSING: {missing}")
    if len(registry) != int(accepted_manifest.get("task_count", -1)):
        raise ValueError("S3_REGISTRY_TASK_COUNT_MISMATCH")
    if registry.duplicated(REGISTRY_KEY).any() or registry["run_id"].duplicated().any():
        raise ValueError("S3_REGISTRY_DUPLICATE_TASK_OR_RUN_ID")
    gates = (
        registry["stage"].eq("S2")
        & registry["scheduler_status"].eq("FINISHED")
        & registry["terminal_status"].eq("COMPLETED")
        & registry["exit_code"].eq(0)
        & _truthy(registry["hv_converged"])
        & _truthy(registry["accepted_for_s3"])
        & registry["pareto_size"].gt(0)
    )
    if not gates.all():
        failed = registry.loc[~gates, "run_id"].tolist()
        raise ValueError(f"S3_REGISTRY_GATE_FAILED: {failed[:10]}")
    return registry.sort_values(REGISTRY_KEY).reset_index(drop=True), accepted_manifest, accepted_manifest_path


def _checksum_entry(checksum_path: Path, relative_path: str) -> str | None:
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) == 2 and fields[1].lstrip("*") == relative_path:
            return fields[0]
    return None


def load_certified_front(row: object, lower: np.ndarray, upper: np.ndarray,
                         tolerance: float) -> pd.DataFrame:
    """Load one certified Pareto CSV after provenance and bounds checks."""
    run_dir = Path(row.run_dir).resolve()
    manifest_path = Path(row.manifest_path).resolve()
    checksum_path = run_dir / "metadata" / "checksums.sha256"
    pareto_path = run_dir / "outputs" / "pareto.csv"
    for path, code in [
        (manifest_path, "S3_RUN_MANIFEST_MISSING"),
        (checksum_path, "S3_RUN_CHECKSUMS_MISSING"),
        (pareto_path, "S3_CERTIFIED_PARETO_MISSING"),
    ]:
        if not path.is_file():
            raise ValueError(f"{code}: {row.run_id}: {path}")
    if sha256_file(manifest_path) != row.run_manifest_sha256:
        raise ValueError(f"S3_RUN_MANIFEST_HASH_MISMATCH: {row.run_id}")
    if sha256_file(checksum_path) != row.run_checksums_sha256:
        raise ValueError(f"S3_RUN_CHECKSUMS_HASH_MISMATCH: {row.run_id}")
    expected_pareto_hash = _checksum_entry(checksum_path, "outputs/pareto.csv")
    actual_pareto_hash = sha256_file(pareto_path)
    if expected_pareto_hash is None or expected_pareto_hash != actual_pareto_hash:
        raise ValueError(f"S3_CERTIFIED_PARETO_HASH_MISMATCH: {row.run_id}")

    run_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_identity = {
        "run_id": row.run_id, "wp": row.wp, "cfg": row.cfg,
        "fluid_hp": row.fluid_hp, "fluid_he": row.fluid_he,
        "seed": int(row.seed), "status": "COMPLETED",
    }
    for field, expected in manifest_identity.items():
        if str(run_manifest.get(field)) != str(expected):
            raise ValueError(
                f"S3_RUN_MANIFEST_PROVENANCE_MISMATCH: {row.run_id}: {field}"
            )
    if "certified_normalized_hypervolume" not in run_manifest:
        raise ValueError(f"S3_CERTIFIED_HV_MISSING: {row.run_id}")

    frame = pd.read_csv(pareto_path)
    required = set(OBJECTIVES + ["wp", "cb_config", "fluid_hp", "fluid_he", "seed", "run_id"])
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"S3_PARETO_COLUMNS_MISSING: {row.run_id}: {missing}")
    if len(frame) != int(row.pareto_size):
        raise ValueError(
            f"S3_PARETO_SIZE_MISMATCH: {row.run_id}: registry={row.pareto_size} csv={len(frame)}"
        )
    identity_checks = {
        "wp": row.wp, "cb_config": row.cfg, "fluid_hp": row.fluid_hp,
        "fluid_he": row.fluid_he, "seed": row.seed, "run_id": row.run_id,
    }
    for column, expected in identity_checks.items():
        if not frame[column].astype(str).eq(str(expected)).all():
            raise ValueError(f"S3_PARETO_PROVENANCE_MISMATCH: {row.run_id}: {column}")

    values = frame[OBJECTIVES].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"S3_PARETO_NONFINITE_OBJECTIVE: {row.run_id}")
    bad = (values < lower - tolerance) | (values > upper + tolerance)
    if bad.any():
        point, objective = np.argwhere(bad)[0]
        raise ValueError(
            "S3_OBJECTIVE_OUT_OF_NORMALIZATION_BOUNDS: "
            f"run={row.run_id} row={point} objective={OBJECTIVES[int(objective)]} "
            f"value={values[point, objective]}"
        )
    frame = frame.copy()
    frame["cfg"] = frame.pop("cb_config")
    frame["candidate_key"] = _candidate_key(row)
    frame["source_pareto_sha256"] = actual_pareto_hash
    frame.attrs["certified_normalized_hypervolume"] = float(
        run_manifest["certified_normalized_hypervolume"]
    )
    return frame


class _FenwickMaximum:
    def __init__(self, size: int):
        self.values = np.full(size + 1, -np.inf, dtype=float)

    def update(self, index: int, value: float) -> None:
        while index < len(self.values):
            if value > self.values[index]:
                self.values[index] = value
            index += index & -index

    def query(self, index: int) -> float:
        result = -np.inf
        while index > 0:
            if self.values[index] > result:
                result = self.values[index]
            index -= index & -index
        return float(result)


def nondominated_mask_3d(values: Iterable[Iterable[float]]) -> np.ndarray:
    """Return the exact maximization non-dominated mask for finite 3-D rows.

    Complexity is O(n log n). Exact duplicate rows are all retained; callers
    may canonicalize them first when unique provenance is required.
    """
    points = np.asarray(values, dtype=float)
    if points.size == 0:
        return np.zeros(0, dtype=bool)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError("S3_NONDOMINATED_INPUT_MUST_BE_FINITE_N_BY_3")

    y_values = sorted(set(points[:, 1]), reverse=True)
    y_rank = {value: rank + 1 for rank, value in enumerate(y_values)}
    order = np.lexsort((-points[:, 2], -points[:, 1], -points[:, 0]))
    dominated = np.zeros(len(points), dtype=bool)
    tree = _FenwickMaximum(len(y_values))
    start = 0
    while start < len(order):
        x_value = points[order[start], 0]
        stop = start + 1
        while stop < len(order) and points[order[stop], 0] == x_value:
            stop += 1
        same_x_max_z = -np.inf
        position = start
        while position < stop:
            index = int(order[position])
            y_value, z_value = points[index, 1], points[index, 2]
            duplicate_stop = position + 1
            while duplicate_stop < stop:
                duplicate_index = int(order[duplicate_stop])
                if (
                    points[duplicate_index, 1] != y_value
                    or points[duplicate_index, 2] != z_value
                ):
                    break
                duplicate_stop += 1
            is_dominated = (
                tree.query(y_rank[y_value]) >= z_value
                or same_x_max_z >= z_value
            )
            if is_dominated:
                dominated[order[position:duplicate_stop]] = True
            # Update only after the exact-duplicate group is classified, so
            # duplicate rows do not strictly dominate one another.
            same_x_max_z = max(same_x_max_z, z_value)
            position = duplicate_stop
        for position in range(start, stop):
            index = int(order[position])
            tree.update(y_rank[points[index, 1]], points[index, 2])
        start = stop
    return ~dominated


def normalized_hypervolume(values: Iterable[Iterable[float]], lower: np.ndarray,
                           upper: np.ndarray, reference: np.ndarray,
                           tolerance: float) -> float:
    points = np.asarray(values, dtype=float)
    if points.size == 0:
        return 0.0
    if points.ndim != 2 or points.shape[1] != len(lower) or not np.isfinite(points).all():
        raise ValueError("S3_HV_INPUT_MUST_BE_FINITE_N_BY_OBJECTIVES")
    bad = (points < lower - tolerance) | (points > upper + tolerance)
    if bad.any():
        row, column = np.argwhere(bad)[0]
        raise ValueError(
            "S3_OBJECTIVE_OUT_OF_NORMALIZATION_BOUNDS: "
            f"{OBJECTIVES[int(column)]}={points[row, column]}"
        )
    normalized = (np.clip(points, lower, upper) - lower) / (upper - lower)
    normalized = np.unique(normalized, axis=0)
    contributes = np.all(normalized > reference, axis=1)
    if not contributes.any():
        return 0.0
    return float(deap_hv.hypervolume(-normalized[contributes], -reference))


def canonical_front(frame: pd.DataFrame) -> pd.DataFrame:
    """Create an input-order-invariant unique pooled front."""
    tie_columns = ["candidate_key", "run_id"]
    decision_columns = sorted(
        column for column in frame.columns
        if column not in set(OBJECTIVES + tie_columns)
    )
    ordered = frame.sort_values(
        OBJECTIVES + tie_columns + decision_columns,
        ascending=[False] * len(OBJECTIVES) + [True] * (len(tie_columns) + len(decision_columns)),
        kind="mergesort",
    )
    unique = ordered.drop_duplicates(OBJECTIVES, keep="first").reset_index(drop=True)
    return unique.loc[nondominated_mask_3d(unique[OBJECTIVES].to_numpy())].sort_values(
        OBJECTIVES + tie_columns,
        ascending=[False] * len(OBJECTIVES) + [True, True],
        kind="mergesort",
    ).reset_index(drop=True)


def select_unit(candidate_frames: dict[str, pd.DataFrame], config_front: pd.DataFrame,
                top_k: int, lower: np.ndarray, upper: np.ndarray,
                reference: np.ndarray, tolerance: float,
                front_counts: dict[str, int], candidate_hv: dict[str, float]) -> tuple[list[dict], list[dict]]:
    """Select extremes first, then greedily maximize exact incremental HV."""
    candidates = sorted(candidate_frames)
    if len(candidates) < top_k:
        raise ValueError(f"S3_INSUFFICIENT_CANDIDATES: need={top_k} have={len(candidates)}")
    reasons: dict[str, set[str]] = {}
    selected: list[str] = []
    extremes: list[dict] = []
    owner_sets: dict[str, set[str]] = {}
    for objective in OBJECTIVES:
        maximum = float(config_front[objective].max())
        tied = config_front.loc[config_front[objective].eq(maximum)]
        owners = set(tied["candidate_key"].astype(str))
        owner_sets[objective] = owners
        extremes.append({
            "objective": objective,
            "extreme_value": maximum,
            "tied_owner_count": len(owners),
            "tied_candidate_keys": ";".join(sorted(owners)),
            "requires_s5_review": True,
        })

    # Cover all three labels with the smallest deterministic owner set.  Ties
    # prefer stronger pooled-front representation, then standalone HV and key.
    cover_options = set()
    for choices in itertools.product(*(sorted(owner_sets[name]) for name in OBJECTIVES)):
        cover_options.add(frozenset(choices))
    mandatory = min(
        cover_options,
        key=lambda keys: (
            len(keys), -sum(front_counts.get(key, 0) for key in keys),
            -sum(candidate_hv.get(key, 0.0) for key in keys), tuple(sorted(keys)),
        ),
    )
    selected.extend(sorted(
        mandatory,
        key=lambda key: (-front_counts.get(key, 0), -candidate_hv.get(key, 0.0), key),
    ))
    for objective in OBJECTIVES:
        owner = min(
            mandatory & owner_sets[objective],
            key=lambda key: (-front_counts.get(key, 0), -candidate_hv.get(key, 0.0), key),
        )
        reasons.setdefault(owner, set()).add(f"extreme_{objective}")
        row = next(item for item in extremes if item["objective"] == objective)
        point = config_front.loc[
            config_front["candidate_key"].eq(owner) &
            config_front[objective].eq(row["extreme_value"])
        ].sort_values("run_id", kind="mergesort").iloc[0]
        row["candidate_key"] = owner
        row["source_run_id"] = point["run_id"]
    if len(selected) > top_k:
        raise ValueError("S3_EXTREME_COVERAGE_EXCEEDS_TOP_K")

    selected_values = [candidate_frames[key][OBJECTIVES].to_numpy(dtype=float) for key in selected]
    current = np.vstack(selected_values) if selected_values else np.empty((0, 3))
    current_hv = normalized_hypervolume(current, lower, upper, reference, tolerance)
    while len(selected) < top_k:
        trials = []
        for key in candidates:
            if key in selected:
                continue
            trial = np.vstack([current, candidate_frames[key][OBJECTIVES].to_numpy(dtype=float)])
            hv_value = normalized_hypervolume(trial, lower, upper, reference, tolerance)
            gain = max(0.0, hv_value - current_hv)
            trials.append((key, gain, hv_value))
        best_gain = max(item[1] for item in trials)
        tied_trials = [
            item for item in trials
            if math.isclose(item[1], best_gain, rel_tol=1e-12, abs_tol=1e-14)
        ]
        key, gain, hv_value = min(
            tied_trials,
            key=lambda item: (
                -front_counts.get(item[0], 0), -candidate_hv.get(item[0], 0.0), item[0],
            ),
        )
        selected.append(key)
        reasons.setdefault(key, set()).add("greedy_incremental_hypervolume")
        current = np.vstack([current, candidate_frames[key][OBJECTIVES].to_numpy(dtype=float)])
        current_hv = hv_value

    rows = []
    step_values = np.empty((0, 3))
    step_hv = 0.0
    for rank, key in enumerate(selected, start=1):
        before_hv = step_hv
        step_values = np.vstack([
            step_values, candidate_frames[key][OBJECTIVES].to_numpy(dtype=float)
        ])
        step_hv = normalized_hypervolume(
            step_values, lower, upper, reference, tolerance
        )
        rows.append({
            "candidate_key": key,
            "selection_rank": rank,
            "selected_reason": ";".join(sorted(reasons[key])),
            "selected_union_hv_before_step": before_hv,
            "selection_incremental_hv": max(0.0, step_hv - before_hv),
            "selected_union_hv_after_step": step_hv,
            "requires_s5_review": any(reason.startswith("extreme_") for reason in reasons[key]),
        })
    return rows, extremes


def run_selection(registry_path: Path, config_path: Path, output_dir: Path,
                  top_k: int = 5, require_clean_git: bool = True) -> dict:
    repository = Path(__file__).resolve().parents[3]
    commit, dirty = git_state(repository)
    if require_clean_git and dirty:
        raise ValueError("S3_FORMAL_RUN_REQUIRES_CLEAN_GIT_WORKTREE")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"S3_OUTPUT_DIRECTORY_NOT_EMPTY: {output_dir}")

    registry, accepted_manifest, accepted_manifest_path = validate_accepted_registry(registry_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    s3_profile = config["experiment"]["profiles"].get("S3_selection", {})
    if s3_profile.get("algorithm") != ALGORITHM_VERSION:
        raise ValueError("S3_CONFIG_ALGORITHM_VERSION_MISMATCH")
    if int(s3_profile.get("pairs_per_unit", -1)) != top_k:
        raise ValueError(
            "S3_CONFIG_TOP_K_MISMATCH: "
            f"configured={s3_profile.get('pairs_per_unit')} requested={top_k}"
        )
    if s3_profile.get("selection_unit") != "working_point_x_observed_configuration":
        raise ValueError("S3_CONFIG_SELECTION_UNIT_MISMATCH")
    hv_spec = config["optimization"]["hypervolume"]
    if hv_spec["objectives"] != OBJECTIVES:
        raise ValueError("S3_OBJECTIVE_ORDER_MISMATCH")
    bounds = hv_spec["normalization_bounds"]
    lower = np.asarray([bounds[name][0] for name in OBJECTIVES], dtype=float)
    upper = np.asarray([bounds[name][1] for name in OBJECTIVES], dtype=float)
    reference = np.asarray(hv_spec["reference_point_normalized"], dtype=float)
    tolerance = float(hv_spec["bounds_tolerance"])
    seeds = list(config["experiment"]["profiles"]["S4_confirmation"]["seeds"])

    output_dir.mkdir(parents=True, exist_ok=True)
    pooled_dir = output_dir / "pooled_fronts"
    selected_rows: list[dict] = []
    ranking_rows: list[dict] = []
    extreme_rows: list[dict] = []
    verified_front_rows = 0
    unit_summaries: list[dict] = []

    for wp, wp_registry in registry.groupby("wp", sort=True):
        frames: dict[str, pd.DataFrame] = {}
        registry_by_key: dict[str, object] = {}
        certified_hv_by_key: dict[str, float] = {}
        for row in wp_registry.sort_values(REGISTRY_KEY).itertuples(index=False):
            key = _candidate_key(row)
            frame = load_certified_front(row, lower, upper, tolerance)
            computed_hv = normalized_hypervolume(
                frame[OBJECTIVES].to_numpy(dtype=float), lower, upper, reference, tolerance
            )
            certified_hv = frame.attrs["certified_normalized_hypervolume"]
            if not math.isclose(
                computed_hv, certified_hv, rel_tol=1e-12, abs_tol=1e-12
            ):
                raise ValueError(
                    f"S3_CERTIFIED_HV_RECOMPUTE_MISMATCH: {row.run_id}: "
                    f"certified={certified_hv} computed={computed_hv}"
                )
            frames[key] = frame
            registry_by_key[key] = row
            certified_hv_by_key[key] = certified_hv
            verified_front_rows += len(frame)

        wp_pool = pd.concat(list(frames.values()), ignore_index=True)
        wp_front = canonical_front(wp_pool)
        atomic_to_csv(wp_front, pooled_dir / f"{wp}_global_pareto.csv")
        wp_counts = wp_front["candidate_key"].value_counts().to_dict()

        for cfg, cfg_registry in wp_registry.groupby("cfg", sort=True):
            unit_keys = sorted(_candidate_key(row) for row in cfg_registry.itertuples(index=False))
            unit_frames = {key: frames[key] for key in unit_keys}
            config_pool = pd.concat(list(unit_frames.values()), ignore_index=True)
            config_front = canonical_front(config_pool)
            atomic_to_csv(config_front, pooled_dir / f"{wp}__{cfg}_pareto.csv")
            config_counts = config_front["candidate_key"].value_counts().to_dict()
            candidate_hv = {
                key: normalized_hypervolume(
                    unit_frames[key][OBJECTIVES].to_numpy(dtype=float),
                    lower, upper, reference, tolerance,
                ) for key in unit_keys
            }
            selections, extremes = select_unit(
                unit_frames, config_front, top_k, lower, upper, reference,
                tolerance, config_counts, candidate_hv,
            )
            selection_by_key = {row["candidate_key"]: row for row in selections}
            for row in selections:
                source = registry_by_key[row["candidate_key"]]
                selected_rows.append({
                    "wp": wp, "cfg": cfg, "fluid_hp": source.fluid_hp,
                    "fluid_he": source.fluid_he, "source_s2_seed": source.seed,
                    "source_s2_run_id": source.run_id, **row,
                    "config_front_point_count": int(config_counts.get(row["candidate_key"], 0)),
                    "wp_global_front_point_count": int(wp_counts.get(row["candidate_key"], 0)),
                    "candidate_normalized_hv": candidate_hv[row["candidate_key"]],
                })
            for row in extremes:
                source = registry_by_key[row["candidate_key"]]
                extreme_rows.append({
                    "wp": wp, "cfg": cfg, "fluid_hp": source.fluid_hp,
                    "fluid_he": source.fluid_he,
                    "selection_rank": selection_by_key[row["candidate_key"]]["selection_rank"],
                    **row,
                })

            ranking_order = sorted(
                unit_keys,
                key=lambda key: (-config_counts.get(key, 0), -candidate_hv[key], key),
            )
            for rank, key in enumerate(ranking_order, start=1):
                source = registry_by_key[key]
                selected = selection_by_key.get(key)
                maxima = unit_frames[key][OBJECTIVES].max()
                ranking_rows.append({
                    "wp": wp, "cfg": cfg, "fluid_hp": source.fluid_hp,
                    "fluid_he": source.fluid_he, "candidate_key": key,
                    "source_s2_run_id": source.run_id,
                    "front_contribution_rank": rank,
                    "config_front_point_count": int(config_counts.get(key, 0)),
                    "config_front_point_share": config_counts.get(key, 0) / len(config_front),
                    "wp_global_front_point_count": int(wp_counts.get(key, 0)),
                    "candidate_normalized_hv": candidate_hv[key],
                    "registry_final_normalized_hv_before_certification": (
                        float(source.final_normalized_hypervolume)
                    ),
                    "manifest_certified_normalized_hv": certified_hv_by_key[key],
                    "certified_hv_recompute_difference": (
                        candidate_hv[key] - certified_hv_by_key[key]
                    ),
                    "front_certification_hv_change": (
                        certified_hv_by_key[key] - float(source.final_normalized_hypervolume)
                    ),
                    **{f"{objective}_max": float(maxima[objective]) for objective in OBJECTIVES},
                    **{
                        f"{objective}_gap_to_unit_extreme": (
                            float(config_front[objective].max()) - float(maxima[objective])
                        ) for objective in OBJECTIVES
                    },
                    "evaluation_count": int(source.evaluation_count),
                    "feasible_count": int(source.feasible_count),
                    "failure_count": int(source.failure_count),
                    "failure_rate": float(source.failure_count) / float(source.evaluation_count),
                    "revalidation_quarantined_count": int(source.revalidation_quarantined_count),
                    "selected_for_s4": selected is not None,
                    "selection_rank": selected["selection_rank"] if selected else pd.NA,
                    "selected_reason": selected["selected_reason"] if selected else "",
                })
            unit_summaries.append({
                "wp": wp, "cfg": cfg, "candidate_count": len(unit_keys),
                "input_point_count": len(config_pool),
                "pooled_front_point_count": len(config_front),
                "pooled_normalized_hv": normalized_hypervolume(
                    config_front[OBJECTIVES].to_numpy(dtype=float), lower, upper,
                    reference, tolerance,
                ),
                "selected_count": len(selections),
                "selected_union_normalized_hv": selections[-1]["selected_union_hv_after_step"],
                "selected_to_pooled_hv_ratio": (
                    selections[-1]["selected_union_hv_after_step"] /
                    normalized_hypervolume(
                        config_front[OBJECTIVES].to_numpy(dtype=float), lower, upper,
                        reference, tolerance,
                    )
                ),
            })

    selected = pd.DataFrame(selected_rows).sort_values(["wp", "cfg", "selection_rank"])
    rankings = pd.DataFrame(ranking_rows).sort_values(["wp", "cfg", "front_contribution_rank"])
    extremes = pd.DataFrame(extreme_rows).sort_values(["wp", "cfg", "objective"])
    units = pd.DataFrame(unit_summaries).sort_values(["wp", "cfg"])
    atomic_to_csv(selected, output_dir / "s3_selected_candidates.csv")
    atomic_to_csv(rankings, output_dir / "candidate_ranking.csv")
    atomic_to_csv(extremes, output_dir / "extreme_coverage.csv")
    atomic_to_csv(units, output_dir / "selection_units.csv")

    task_rows = []
    for row in selected.itertuples(index=False):
        for seed in seeds:
            task_rows.append({
                "wp": row.wp, "cfg": row.cfg, "fluid_hp": row.fluid_hp,
                "fluid_he": row.fluid_he, "seed": seed,
                "source_s2_run_id": row.source_s2_run_id,
                "s3_selection_rank": row.selection_rank,
                "s3_selected_reason": row.selected_reason,
                "requires_s5_review": row.requires_s5_review,
            })
    tasks = pd.DataFrame(task_rows).sort_values(["wp", "cfg", "s3_selection_rank", "seed"])
    if tasks.duplicated(REGISTRY_KEY).any():
        raise ValueError("S3_S4_TASK_LIST_DUPLICATE")
    atomic_to_csv(tasks, output_dir / "s4_task_list.csv")

    observed_configurations = sorted(registry["cfg"].unique())
    unobserved_configurations = sorted(
        set(config["configurations"]) - set(observed_configurations)
    )
    selected_per_unit = selected.groupby(["wp", "cfg"]).size()
    extreme_per_unit = extremes.groupby(["wp", "cfg"])["objective"].nunique()
    gates = {
        "all_s2_runs_verified": verified_front_rows == int(registry["pareto_size"].sum()),
        "top_k_per_observed_wp_configuration": bool((selected_per_unit == top_k).all()),
        "three_objective_extremes_covered": bool((extreme_per_unit == len(OBJECTIVES)).all()),
        "s4_task_keys_unique": not tasks.duplicated(REGISTRY_KEY).any(),
        "git_clean_requirement_satisfied": (not require_clean_git) or (not dirty),
    }
    if not all(gates.values()):
        raise ValueError(f"S3_ACCEPTANCE_GATE_FAILED: {gates}")

    outputs = [
        output_dir / "s3_selected_candidates.csv",
        output_dir / "candidate_ranking.csv",
        output_dir / "extreme_coverage.csv",
        output_dir / "selection_units.csv",
        output_dir / "s4_task_list.csv",
        *sorted(pooled_dir.glob("*.csv")),
    ]
    manifest = {
        "schema_version": "1.0",
        "algorithm": ALGORITHM_VERSION,
        "status": "S3_COMPLETED_CANDIDATES_UNCONFIRMED",
        "created_from_accepted_s2": str(Path(registry_path).resolve()),
        "accepted_s2_registry_sha256": sha256_file(Path(registry_path).resolve()),
        "accepted_s2_manifest": str(accepted_manifest_path),
        "accepted_s2_manifest_sha256": sha256_file(accepted_manifest_path),
        "accepted_s2_dataset_id": accepted_manifest.get("accepted_dataset_id"),
        "config": str(config_path.resolve()),
        "config_sha256": sha256_file(config_path.resolve()),
        "git_commit": commit,
        "git_dirty": dirty,
        "selection_unit": "working_point_x_observed_configuration",
        "selection_top_k": top_k,
        "selection_policy": [
            "minimum deterministic candidate set covering each objective maximum",
            "greedy exact normalized-hypervolume gain fill",
            "HV tie band rel=1e-12 abs=1e-14, then pooled-front points, candidate HV, candidate key",
        ],
        "hypervolume_spec": {
            "algorithm": hv_spec["algorithm"], "objectives": OBJECTIVES,
            "lower": lower.tolist(), "upper": upper.tolist(),
            "reference_point_normalized": reference.tolist(),
            "bounds_tolerance": tolerance,
        },
        "input_run_count": len(registry),
        "verified_certified_front_point_count": verified_front_rows,
        "working_points": sorted(registry["wp"].unique()),
        "observed_configurations": observed_configurations,
        "unobserved_configurations": unobserved_configurations,
        "selection_unit_count": len(units),
        "selected_candidate_count": len(selected),
        "s4_confirmation_seeds": seeds,
        "s4_task_count": len(tasks),
        "acceptance_gates": gates,
        "scientific_scope": (
            "Exploratory thermodynamic candidate selection only; extremes require S5 review "
            "and no S4-unconfirmed row is an engineering recommendation."
        ),
        "output_sha256": {
            str(path.relative_to(output_dir)): sha256_file(path) for path in outputs
        },
    }
    atomic_write_text(
        output_dir / "s3_manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    report = f"""# S3 Candidate Selection Report

Status: **S3 completed; candidates are unconfirmed until S4**

- Accepted S2 runs verified: {len(registry)}
- Certified S2 Pareto points verified: {verified_front_rows}
- Selection units: {len(units)} (`WP × observed configuration`)
- Selected candidates: {len(selected)} ({top_k} per unit)
- Generated S4 tasks: {len(tasks)} ({len(seeds)} independent seeds per candidate)
- Observed configurations: {', '.join(observed_configurations)}
- Unobserved configurations (not inferred): {', '.join(unobserved_configurations) or 'none'}

## Method and gates

Each unit pools only certified `pareto.csv` rows from the canonical accepted S2 registry.
The three objective maxima are covered first. Remaining slots maximize incremental exact
hypervolume under the frozen S2 normalization; deterministic tie-breaking makes the result
independent of registry/file ordering. All acceptance gates in `s3_manifest.json` passed.

## Scientific limitation

This is an exploratory thermodynamic shortlist, not an engineering recommendation. Extreme
owners are explicitly marked for S5 physical review. S4 must establish five-seed stability
before any pair can be called a stable recommendation.
"""
    atomic_write_text(output_dir / "S3_ACCEPTANCE_REPORT.md", report)
    manifest["report_sha256"] = sha256_file(output_dir / "S3_ACCEPTANCE_REPORT.md")
    # Rewrite once so the report checksum is part of the final manifest.
    atomic_write_text(
        output_dir / "s3_manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-registry", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--allow-dirty", action="store_true",
        help="Development only; formal S3 requires a clean Git worktree.",
    )
    args = parser.parse_args()
    manifest = run_selection(
        args.accepted_registry, args.config, args.output_dir,
        top_k=args.top_k, require_clean_git=not args.allow_dirty,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
