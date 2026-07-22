#!/usr/bin/env python3
"""Build canonical S4 results and release stable representatives to S5."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import pandas as pd

try:
    from .select_s3_candidates import (
        OBJECTIVES, canonical_front, nondominated_mask_3d,
        normalized_hypervolume,
    )
except ImportError:  # Support direct execution from this directory.
    from select_s3_candidates import (
        OBJECTIVES, canonical_front, nondominated_mask_3d,
        normalized_hypervolume,
    )


TASK_KEY = ["wp", "cfg", "fluid_hp", "fluid_he", "seed"]
CANDIDATE_KEY = ["wp", "cfg", "fluid_hp", "fluid_he"]
VARIABLES = [
    "T_st_ht", "dT_st_sp", "dT_hp_cs_gl", "dT_hp_ev_sh",
    "dT_he_ev_sh", "dT_hp_cd_sc", "eta_max_cp", "eta_max_ex", "eta_pm",
]
ALGORITHM = "s4_canonical_five_seed_acceptance_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def truthy(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def checksum_entry(path: Path, relative: str) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) == 2 and fields[1].lstrip("*") == relative:
            return fields[0]
    return None


def sample_cv(values) -> float:
    array = np.asarray(values, dtype=float)
    if len(array) < 2 or not np.isfinite(array).all():
        raise ValueError("S4_CV_REQUIRES_AT_LEAST_TWO_FINITE_VALUES")
    mean = float(array.mean())
    if abs(mean) <= 1e-15:
        raise ValueError("S4_CV_MEAN_TOO_CLOSE_TO_ZERO")
    return float(array.std(ddof=1) / abs(mean))


def rank_top_with_boundary_ties(values, top_n: int) -> tuple[np.ndarray, np.ndarray]:
    """Competition ranks and top-N mask with scientific boundary ties included."""
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all() \
    or not 1 <= top_n <= len(array):
        raise ValueError("S4_RANK_INPUT_INVALID")
    cutoff = np.sort(array)[::-1][top_n - 1]
    ranks = np.empty(len(array), dtype=int)
    for index, value in enumerate(array):
        tied = np.isclose(array, value, rtol=1e-12, atol=1e-14)
        ranks[index] = 1 + int(np.sum((array > value) & ~tied))
    top = (array > cutoff) | np.isclose(array, cutoff, rtol=1e-12, atol=1e-14)
    return ranks, top


def exact_igd_plus(reference, approximation, chunk_size: int = 128) -> float:
    """Exact normalized IGD+ for maximization, evaluated in bounded chunks."""
    reference = np.asarray(reference, dtype=float)
    approximation = np.asarray(approximation, dtype=float)
    if reference.ndim != 2 or approximation.ndim != 2 \
    or reference.shape[1] != approximation.shape[1] \
    or not len(reference) or not len(approximation) \
    or not np.isfinite(reference).all() or not np.isfinite(approximation).all():
        raise ValueError("S4_IGD_PLUS_INPUT_INVALID")
    total = 0.0
    for start in range(0, len(reference), chunk_size):
        block = reference[start:start + chunk_size]
        # Maximization IGD+: only objective deficits relative to each reference
        # point contribute to distance; over-achievement is not penalized.
        deficit = np.maximum(
            block[:, np.newaxis, :] - approximation[np.newaxis, :, :], 0.0
        )
        squared = np.einsum("ijk,ijk->ij", deficit, deficit)
        total += float(np.sqrt(np.min(squared, axis=1)).sum())
    return total / len(reference)


def objective_union_front(frames: list[pd.DataFrame]) -> np.ndarray:
    values = np.vstack([frame[OBJECTIVES].to_numpy(dtype=float) for frame in frames])
    values = np.unique(values, axis=0)
    mask = nondominated_mask_3d(values)
    front = values[mask]
    order = np.lexsort((-front[:, 2], -front[:, 1], -front[:, 0]))
    return front[order]


def _verified_run(manifest_path: Path, expected: dict) -> tuple[dict, dict]:
    manifest_path = manifest_path.resolve()
    run_dir = manifest_path.parents[1]
    checksums_path = run_dir / "metadata" / "checksums.sha256"
    pareto_path = run_dir / "outputs" / "pareto.csv"
    for path in [manifest_path, checksums_path, pareto_path]:
        if not path.is_file():
            raise ValueError(f"S4_CANONICAL_ARTIFACT_MISSING: {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field, value in expected.items():
        if str(manifest.get(field)) != str(value):
            raise ValueError(
                f"S4_CANONICAL_PROVENANCE_MISMATCH: {manifest_path}: {field}"
            )
    if manifest.get("status") != "COMPLETED" or not manifest.get("hv_converged"):
        raise ValueError(f"S4_CANONICAL_RUN_NOT_CONVERGED: {manifest.get('run_id')}")
    manifest_hash = sha256_file(manifest_path)
    pareto_hash = sha256_file(pareto_path)
    if checksum_entry(checksums_path, "metadata/manifest.json") != manifest_hash:
        raise ValueError(f"S4_CANONICAL_MANIFEST_HASH_MISMATCH: {manifest.get('run_id')}")
    if checksum_entry(checksums_path, "outputs/pareto.csv") != pareto_hash:
        raise ValueError(f"S4_CANONICAL_PARETO_HASH_MISMATCH: {manifest.get('run_id')}")
    required_artifacts = [
        "config/config.snapshot.json", "checkpoints/latest.json",
        "outputs/front_revalidation_repeat_1.csv",
        "outputs/front_revalidation_repeat_2.csv",
        "outputs/front_revalidation_summary.json",
    ]
    for relative in required_artifacts:
        artifact = run_dir / relative
        expected_hash = checksum_entry(checksums_path, relative)
        if not artifact.is_file() or expected_hash != sha256_file(artifact):
            raise ValueError(
                f"S4_CANONICAL_REQUIRED_ARTIFACT_HASH_MISMATCH: "
                f"{manifest.get('run_id')}: {relative}"
            )
    revalidation = json.loads(
        (run_dir / "outputs" / "front_revalidation_summary.json").read_text()
    )
    certified = int(revalidation.get("certified_candidate_count", -1))
    raw_size = int(revalidation.get("raw_archive_size", -1))
    quarantined = int(revalidation.get("quarantined_count", -1))
    if revalidation.get("independent_repeats") != 2 \
    or int(revalidation.get("all_repeats_feasible_count", -2)) != certified \
    or int(revalidation.get("repeat_consistent_count", -2)) != certified \
    or raw_size != certified + quarantined \
    or int(revalidation.get("revalidation_solver_calls", -1)) != 2 * raw_size:
        raise ValueError(f"S4_CANONICAL_REVALIDATION_GATE_FAILED: {manifest.get('run_id')}")
    if float(manifest.get("final_hv_relative_improvement", math.inf)) >= 0.005:
        raise ValueError(f"S4_CANONICAL_HV_WINDOW_GATE_FAILED: {manifest.get('run_id')}")
    transient = (run_dir / ".lock").exists() or any(
        any(directory.glob("*.tmp"))
        for directory in [run_dir / "metadata", run_dir / "outputs", run_dir / "checkpoints"]
    )
    if transient:
        raise ValueError(f"S4_CANONICAL_TRANSIENT_ARTIFACT_PRESENT: {manifest.get('run_id')}")
    return manifest, {
        "manifest_sha256": manifest_hash,
        "checksums_sha256": sha256_file(checksums_path),
        "pareto_sha256": pareto_hash,
    }


def build_canonical_registry(base_batch: Path, extension_batch: Path,
                             s3_task_list: Path) -> pd.DataFrame:
    base_manifest = json.loads((base_batch / "batch_manifest.json").read_text())
    extension_manifest = json.loads((extension_batch / "batch_manifest.json").read_text())
    for label, manifest in [("base", base_manifest), ("extension", extension_manifest)]:
        if manifest.get("status") != "COMPUTE_COMPLETE" or not manifest.get("accepted_compute"):
            raise ValueError(f"S4_CANONICAL_{label.upper()}_BATCH_NOT_COMPLETE")
    base = pd.read_csv(base_batch / "run_registry.csv")
    extension = pd.read_csv(extension_batch / "run_registry.csv")
    s3 = pd.read_csv(s3_task_list)
    if len(base) != 300 or len(extension) == 0 or len(s3) != 300:
        raise ValueError("S4_CANONICAL_INPUT_COUNTS_INVALID")
    for frame, label in [(base, "BASE"), (extension, "EXTENSION"), (s3, "S3")]:
        if frame.duplicated(TASK_KEY).any():
            raise ValueError(f"S4_CANONICAL_{label}_DUPLICATE_TASK")
    if set(map(tuple, base[TASK_KEY].to_numpy())) != set(map(tuple, s3[TASK_KEY].to_numpy())):
        raise ValueError("S4_CANONICAL_S3_TASK_UNIVERSE_MISMATCH")

    extension_by_source = {}
    extension_registry = extension.set_index("run_id")
    for manifest_path in extension["manifest_path"]:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        source = manifest.get("source_s4_run_id")
        if not source or source in extension_by_source:
            raise ValueError("S4_CANONICAL_EXTENSION_SOURCE_DUPLICATE_OR_MISSING")
        extension_by_source[source] = manifest
    expected_sources = set(
        base.loc[~base["hv_converged"].map(truthy), "run_id"]
    )
    if set(extension_by_source) != expected_sources:
        raise ValueError("S4_CANONICAL_EXTENSION_REPLACEMENT_SET_MISMATCH")

    s3_by_key = s3.set_index(TASK_KEY)
    rows = []
    for source in base.sort_values(TASK_KEY).itertuples(index=False):
        replacement = extension_by_source.get(source.run_id)
        if replacement is None:
            chosen_manifest_path = Path(source.manifest_path)
            chosen_run_id = source.run_id
            canonical_source = "base"
            registry_status = source
        else:
            chosen_run_id = replacement["run_id"]
            chosen_manifest_path = Path(
                extension_registry.loc[chosen_run_id, "manifest_path"]
            )
            canonical_source = "extension"
            registry_status = extension_registry.loc[chosen_run_id]
            if replacement.get("supersedes_run_id") != source.run_id:
                raise ValueError(
                    f"S4_CANONICAL_EXTENSION_LINEAGE_MISMATCH: {chosen_run_id}"
                )
        expected = {
            "run_id": chosen_run_id, "wp": source.wp, "cfg": source.cfg,
            "fluid_hp": source.fluid_hp, "fluid_he": source.fluid_he,
            "seed": int(source.seed),
        }
        manifest, hashes = _verified_run(chosen_manifest_path, expected)
        if str(registry_status["terminal_status"] if isinstance(registry_status, pd.Series)
               else registry_status.terminal_status) != "COMPLETED":
            raise ValueError(f"S4_CANONICAL_REGISTRY_STATUS_FAILED: {chosen_run_id}")
        lineage = s3_by_key.loc[
            (source.wp, source.cfg, source.fluid_hp, source.fluid_he, source.seed)
        ]
        if canonical_source == "extension":
            evaluation_count = int(manifest["cumulative_evaluation_count"])
            feasible_count = int(manifest["cumulative_feasible_count"])
            failure_count = int(manifest["cumulative_failure_count"])
            revalidation_calls = int(manifest["cumulative_front_revalidation_solver_calls"])
        else:
            evaluation_count = int(manifest["evaluation_count"])
            feasible_count = int(manifest["feasible_count"])
            failure_count = int(manifest["failure_count"])
            revalidation_calls = int(manifest["front_revalidation_solver_calls"])
        rows.append({
            "wp": source.wp, "cfg": source.cfg,
            "fluid_hp": source.fluid_hp, "fluid_he": source.fluid_he,
            "seed": int(source.seed), "run_id": chosen_run_id,
            "run_dir": manifest["run_dir"], "manifest_path": str(chosen_manifest_path.resolve()),
            "canonical_source": canonical_source,
            "base_s4_run_id": source.run_id,
            "supersedes_run_id": manifest.get("supersedes_run_id", ""),
            "source_s2_run_id": lineage["source_s2_run_id"],
            "s3_selection_rank": int(lineage["s3_selection_rank"]),
            "s3_selected_reason": lineage["s3_selected_reason"],
            "requires_s5_review": truthy(lineage["requires_s5_review"]),
            "git_commit": manifest["git_commit"],
            "config_sha256": manifest["config_sha256"],
            "completed_generations": int(manifest["completed_generations"]),
            "hv_converged": bool(manifest["hv_converged"]),
            "certified_normalized_hypervolume": float(
                manifest["certified_normalized_hypervolume"]
            ),
            "evaluation_count": evaluation_count,
            "feasible_count": feasible_count, "failure_count": failure_count,
            "raw_archive_size": int(manifest["raw_archive_size"]),
            "pareto_size": int(manifest["pareto_size"]),
            "front_revalidation_solver_calls": revalidation_calls,
            "revalidation_quarantined_count": int(
                manifest["revalidation_quarantined_count"]
            ),
            **hashes,
        })
    canonical = pd.DataFrame(rows).sort_values(TASK_KEY).reset_index(drop=True)
    if len(canonical) != 300 or canonical.duplicated(TASK_KEY).any() \
    or not canonical["hv_converged"].all() \
    or not (
        canonical["evaluation_count"]
        == canonical["feasible_count"] + canonical["failure_count"]
    ).all():
        raise ValueError("S4_CANONICAL_FINAL_REGISTRY_GATE_FAILED")
    return canonical


def analyze_stability(canonical: pd.DataFrame, lower: np.ndarray,
                      upper: np.ndarray, reference: np.ndarray,
                      tolerance: float, top_n: int = 3) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    seed_rows = []
    frames_by_candidate: dict[tuple, list[pd.DataFrame]] = {}
    for keys, group in canonical.groupby(CANDIDATE_KEY, sort=True):
        frames = []
        for run in group.sort_values("seed").itertuples(index=False):
            frame = pd.read_csv(Path(run.run_dir) / "outputs" / "pareto.csv")
            if not np.isfinite(frame[VARIABLES + OBJECTIVES].to_numpy(dtype=float)).all():
                raise ValueError(f"S4_CANONICAL_PARETO_NONFINITE: {run.run_id}")
            if frame.duplicated(VARIABLES).any():
                raise ValueError(f"S4_CANONICAL_PARETO_DUPLICATE_DESIGN: {run.run_id}")
            values = frame[OBJECTIVES].to_numpy(dtype=float)
            computed_hv = normalized_hypervolume(
                values, lower, upper, reference, tolerance
            )
            if not math.isclose(
                computed_hv, run.certified_normalized_hypervolume,
                rel_tol=1e-12, abs_tol=1e-12,
            ):
                raise ValueError(f"S4_CANONICAL_HV_RECOMPUTE_MISMATCH: {run.run_id}")
            frame = frame.copy()
            frame["source_pareto_row_index"] = np.arange(len(frame), dtype=int)
            frame["cfg"] = run.cfg
            frame["candidate_key"] = "|".join(map(str, keys))
            frame["source_s2_run_id"] = run.source_s2_run_id
            frame["s3_selection_rank"] = int(run.s3_selection_rank)
            frame["requires_s5_review"] = bool(run.requires_s5_review)
            frame["source_manifest_sha256"] = run.manifest_sha256
            frame["source_pareto_sha256"] = run.pareto_sha256
            frames.append(frame)
            seed_rows.append({
                **dict(zip(CANDIDATE_KEY, keys)), "seed": int(run.seed),
                "run_id": run.run_id, "certified_normalized_hypervolume": computed_hv,
                **{f"{objective}_maximum": float(frame[objective].max()) for objective in OBJECTIVES},
            })
        frames_by_candidate[keys] = frames

    seed_metrics = pd.DataFrame(seed_rows)
    candidate_rows = []
    normalization_span = upper - lower
    for keys, frames in frames_by_candidate.items():
        union = objective_union_front(frames)
        normalized_union = (union - lower) / normalization_span
        group = seed_metrics
        for field, value in zip(CANDIDATE_KEY, keys):
            group = group[group[field] == value]
        igd_values = []
        for frame in frames:
            normalized = (frame[OBJECTIVES].to_numpy(dtype=float) - lower) / normalization_span
            igd_values.append(exact_igd_plus(normalized_union, normalized))
        group_indices = group.sort_values("seed").index
        seed_metrics.loc[group_indices, "igd_plus_to_union"] = igd_values
        row = dict(zip(CANDIDATE_KEY, keys))
        row.update({
            "seed_count": len(group),
            "union_front_size": len(union),
            "hv_cv_sample": sample_cv(group["certified_normalized_hypervolume"]),
            "maximum_igd_plus": max(igd_values),
            "mean_igd_plus": float(np.mean(igd_values)),
        })
        for objective in OBJECTIVES:
            row[f"{objective}_maximum_cv_sample"] = sample_cv(
                group[f"{objective}_maximum"]
            )
        row["hv_cv_pass"] = row["hv_cv_sample"] <= 0.05
        row["igd_plus_pass"] = row["maximum_igd_plus"] <= 0.03
        row["extreme_cv_pass"] = all(
            row[f"{objective}_maximum_cv_sample"] <= 0.03 for objective in OBJECTIVES
        )
        candidate_rows.append(row)
    candidates = pd.DataFrame(candidate_rows)

    ranked_rows = []
    for (wp, seed), group in seed_metrics.groupby(["wp", "seed"], sort=True):
        ordered = group.sort_values(
            ["certified_normalized_hypervolume", "cfg", "fluid_hp", "fluid_he"],
            ascending=[False, True, True, True], kind="mergesort",
        )
        hypervolumes = ordered["certified_normalized_hypervolume"].to_numpy(dtype=float)
        hv_ranks, top_mask = rank_top_with_boundary_ties(hypervolumes, top_n)
        for position, (_, row) in enumerate(ordered.iterrows()):
            value = float(row["certified_normalized_hypervolume"])
            ranked_rows.append({
                **{field: row[field] for field in CANDIDATE_KEY},
                "seed": int(seed), "hv_rank_within_wp_seed": int(hv_ranks[position]),
                "top_rank": bool(top_mask[position]),
            })
    rankings = pd.DataFrame(ranked_rows)
    rank_counts = rankings.groupby(CANDIDATE_KEY, sort=True)["top_rank"].sum().rename(
        "top_rank_seed_count"
    ).reset_index()
    candidates = candidates.merge(rank_counts, on=CANDIDATE_KEY, validate="one_to_one")
    candidates["rank_stability_pass"] = candidates["top_rank_seed_count"] >= 4
    candidates["confirmed_front"] = (
        candidates["hv_cv_pass"] & candidates["igd_plus_pass"]
        & candidates["extreme_cv_pass"]
    )
    candidates["accepted_for_s5"] = (
        candidates["confirmed_front"] & candidates["rank_stability_pass"]
    )
    candidates["s4_status"] = np.where(
        candidates["accepted_for_s5"], "S4_RECOMMENDABLE",
        np.where(candidates["confirmed_front"], "S4_CONFIRMED_FRONT", "S4_UNSTABLE"),
    )
    candidates["failure_codes"] = candidates.apply(
        lambda row: ";".join([
            code for passed, code in [
                (row["hv_cv_pass"], "S4_UNSTABLE_HV"),
                (row["igd_plus_pass"], "S4_UNSTABLE_IGD_PLUS"),
                (row["eta_p2p_maximum_cv_sample"] <= 0.03, "S4_UNSTABLE_ETA_EXTREME"),
                (row["energy_density_thermal_maximum_cv_sample"] <= 0.03,
                 "S4_UNSTABLE_DENSITY_EXTREME"),
                (row["exergy_efficiency_maximum_cv_sample"] <= 0.03,
                 "S4_UNSTABLE_EXERGY_EXTREME"),
                (row["rank_stability_pass"], "S4_RANK_NOT_STABLE"),
            ] if not passed
        ]), axis=1,
    )
    candidates["evidence_status"] = np.where(
        candidates["confirmed_front"], "EVIDENCE_SUFFICIENT", "EVIDENCE_INSUFFICIENT"
    )
    return seed_metrics.sort_values(TASK_KEY), candidates.sort_values(CANDIDATE_KEY), {
        "rankings": rankings.sort_values(["wp", "seed", "hv_rank_within_wp_seed"]),
        "frames_by_candidate": frames_by_candidate,
    }


def select_s5_representatives(candidates: pd.DataFrame, frames_by_candidate: dict) -> pd.DataFrame:
    rows = []
    for wp in sorted(candidates["wp"].unique()):
        accepted = candidates[(candidates["wp"] == wp) & candidates["accepted_for_s5"]]
        if len(accepted) < 1:
            raise ValueError(f"S4_INSUFFICIENT_STABLE_CANDIDATES_FOR_S5: {wp}: {len(accepted)}")
        accepted_keys = set(map(tuple, accepted[CANDIDATE_KEY].to_numpy()))
        frames = [frame for key, values in frames_by_candidate.items()
                  if key in accepted_keys for frame in values]
        pooled = canonical_front(pd.concat(frames, ignore_index=True))
        chosen_indices = []
        eta_index = pooled.sort_values(
            ["eta_p2p", "candidate_key", "run_id"],
            ascending=[False, True, True], kind="mergesort",
        ).index[0]
        chosen_indices.append(("efficiency", eta_index))
        density_candidates = pooled.drop(index=[index for _, index in chosen_indices])
        density_index = density_candidates.sort_values(
            ["energy_density_thermal", "candidate_key", "run_id"],
            ascending=[False, True, True], kind="mergesort",
        ).index[0]
        chosen_indices.append(("density", density_index))
        ideal = pooled[OBJECTIVES].max().to_numpy(dtype=float)
        nadir = pooled[OBJECTIVES].min().to_numpy(dtype=float)
        span = np.where(ideal > nadir, ideal - nadir, 1.0)
        scaled = (pooled[OBJECTIVES].to_numpy(dtype=float) - nadir) / span
        pooled = pooled.copy()
        pooled["compromise_distance_to_local_ideal"] = np.linalg.norm(
            1.0 - scaled, axis=1
        ) / math.sqrt(len(OBJECTIVES))
        compromise_candidates = pooled.drop(index=[index for _, index in chosen_indices])
        compromise_index = compromise_candidates.sort_values(
            ["compromise_distance_to_local_ideal", "candidate_key", "run_id"],
            ascending=[True, True, True], kind="mergesort",
        ).index[0]
        chosen_indices.append(("compromise", compromise_index))
        for representative_type, index in chosen_indices:
            point = pooled.loc[index]
            point_payload = {
                name: float(point[name]) for name in VARIABLES + OBJECTIVES
            }
            point_hash = hashlib.sha256(json.dumps(
                point_payload, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")).hexdigest()
            rows.append({
                "representative_id": f"S5_{wp.replace('-', '')}_{representative_type}",
                "representative_type": representative_type,
                "wp": wp, "cfg": point["cfg"],
                "fluid_hp": point["fluid_hp"], "fluid_he": point["fluid_he"],
                "source_seed": int(point["seed"]), "source_run_id": point["run_id"],
                "candidate_key": point["candidate_key"],
                "source_s2_run_id": point["source_s2_run_id"],
                "s3_selection_rank": int(point["s3_selection_rank"]),
                "requires_s5_review": bool(point["requires_s5_review"]),
                "source_pareto_row_index": int(point["source_pareto_row_index"]),
                "source_manifest_sha256": point["source_manifest_sha256"],
                "source_pareto_sha256": point["source_pareto_sha256"],
                "point_sha256": point_hash,
                **{name: float(point[name]) for name in VARIABLES + OBJECTIVES},
                "compromise_distance_to_local_ideal": (
                    float(point["compromise_distance_to_local_ideal"])
                    if representative_type == "compromise" else math.nan
                ),
            })
    return pd.DataFrame(rows).sort_values(["wp", "representative_type"])


def accept(base_batch: Path, extension_batch: Path, s3_task_list: Path,
           config_path: Path, output_dir: Path, require_clean_git: bool = True) -> dict:
    repository = Path(__file__).resolve().parents[3]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repository, text=True).strip())
    if require_clean_git and dirty:
        raise ValueError("S4_ACCEPTANCE_REQUIRES_CLEAN_GIT")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"S4_ACCEPTANCE_OUTPUT_NOT_EMPTY: {output_dir}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    hv = config["optimization"]["hypervolume"]
    bounds = hv["normalization_bounds"]
    lower = np.asarray([bounds[name][0] for name in OBJECTIVES], dtype=float)
    upper = np.asarray([bounds[name][1] for name in OBJECTIVES], dtype=float)
    reference = np.asarray(hv["reference_point_normalized"], dtype=float)
    tolerance = float(hv["bounds_tolerance"])

    canonical = build_canonical_registry(base_batch, extension_batch, s3_task_list)
    seed_metrics, candidates, extra = analyze_stability(
        canonical, lower, upper, reference, tolerance, top_n=3
    )
    representatives = select_s5_representatives(candidates, extra["frames_by_candidate"])
    rankings = extra["rankings"]
    wp_stable = candidates.groupby("wp")["accepted_for_s5"].sum()
    gates = {
        "canonical_300_unique_tasks": len(canonical) == 300 and not canonical.duplicated(TASK_KEY).any(),
        "exactly_60_candidate_groups": len(candidates) == 60,
        "all_canonical_runs_hv_converged": bool(canonical["hv_converged"].all()),
        "all_candidates_have_five_seeds": bool((seed_metrics.groupby(CANDIDATE_KEY).size() == 5).all()),
        "at_least_one_s5_candidate_per_wp": bool((wp_stable >= 1).all()),
        "three_representatives_per_wp": bool((representatives.groupby("wp").size() == 3).all()),
        "exactly_18_unique_representatives": len(representatives) == 18 and not representatives.duplicated(
            ["source_run_id", *VARIABLES]
        ).any(),
        "git_clean_or_explicitly_allowed": not dirty or not require_clean_git,
    }
    if not all(gates.values()):
        raise ValueError(f"S4_ACCEPTANCE_GATE_FAILED: {gates}")

    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "accepted_run_registry.csv": canonical,
        "seed_stability_metrics.csv": seed_metrics,
        "candidate_stability.csv": candidates,
        "seed_candidate_rankings.csv": rankings,
        "s5_representative_points.csv": representatives,
        "s5_diagnostic_queue.csv": candidates.loc[~candidates["accepted_for_s5"]],
    }
    for name, frame in outputs.items():
        atomic_text(output_dir / name, frame.to_csv(index=False, lineterminator="\n"))
    acceptance_status = "ACCEPTED_FOR_S5" if not dirty else "DEVELOPMENT_ACCEPTANCE"
    manifest = {
        "schema_version": "1.0", "algorithm": ALGORITHM,
        "status": acceptance_status, "git_commit": commit, "git_dirty": dirty,
        "base_batch": str(base_batch.resolve()),
        "base_batch_manifest_sha256": sha256_file(base_batch / "batch_manifest.json"),
        "extension_batch": str(extension_batch.resolve()),
        "extension_batch_manifest_sha256": sha256_file(extension_batch / "batch_manifest.json"),
        "s3_task_list": str(s3_task_list.resolve()),
        "s3_task_list_sha256": sha256_file(s3_task_list),
        "config": str(config_path.resolve()), "config_sha256": sha256_file(config_path),
        "canonical_policy": "218 converged base runs plus 82 extension runs replacing their source runs",
        "cv_definition": "sample standard deviation ddof=1 divided by absolute mean",
        "igd_plus_definition": "exact maximization IGD+ from each seed front to the five-seed nondominated union under frozen bounds",
        "ranking_definition": "certified normalized HV rank among 10 configuration-fluid candidates per WP and seed; top-3 in at least 4/5 seeds",
        "thresholds": {"hv_cv": 0.05, "igd_plus": 0.03, "extreme_kpi_cv": 0.03, "top_rank_n": 3, "top_rank_minimum_seeds": 4},
        "counts": {
            "canonical_runs": len(canonical), "base_runs_retained": int((canonical.canonical_source == "base").sum()),
            "extension_runs": int((canonical.canonical_source == "extension").sum()),
            "candidate_groups": len(candidates), "accepted_s5_candidates": int(candidates.accepted_for_s5.sum()),
            "s5_representatives": len(representatives),
        },
        "canonical_totals": {
            field: int(canonical[field].sum()) for field in [
                "evaluation_count", "feasible_count", "failure_count",
                "raw_archive_size", "pareto_size", "front_revalidation_solver_calls",
                "revalidation_quarantined_count",
            ]
        },
        "acceptance_gates": gates,
        "output_sha256": {
            name: sha256_file(output_dir / name) for name in outputs
        },
        "scientific_scope": "S4-stable thermodynamic candidates approved for S5 independent physical revalidation; not engineering recommendations",
    }
    atomic_text(output_dir / "accepted_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    failures = candidates.loc[~candidates.accepted_for_s5]
    stable_by_wp = candidates.groupby("wp")["accepted_for_s5"].sum()
    extreme_failures = candidates.loc[~candidates.extreme_cv_pass]
    extreme_lines = "\n".join(
        f"- {row.wp} / {row.cfg} / {row.fluid_hp} + {row.fluid_he}: "
        f"{row.failure_codes}"
        for row in extreme_failures.itertuples(index=False)
    )
    report = f"""# S4 Canonical Acceptance Report

Status: **{acceptance_status}**

- Canonical runs: {len(canonical)} (218 base + 82 extension replacements)
- Five-seed candidates: {len(candidates)}
- S5-stable candidates: {int(candidates.accepted_for_s5.sum())}
- Excluded unstable candidates: {len(failures)}
- S5 representative points: {len(representatives)} (3 per WP)
- Maximum HV CV: {candidates.hv_cv_sample.max():.6f}
- Maximum IGD+: {candidates.maximum_igd_plus.max():.6f}
- Candidates failing extreme KPI CV: {int((~candidates.extreme_cv_pass).sum())}
- Recommendable candidates by WP: {', '.join(f'{wp}={int(count)}' for wp, count in stable_by_wp.items())}

## Evidence-insufficient extreme candidates

{extreme_lines}

Passing S4 permits S5 execution only. Engineering recommendation remains blocked until
independent S5 energy, exergy, phase, pinch, pressure and KPI gates pass.
"""
    atomic_text(output_dir / "S4_ACCEPTANCE_REPORT.md", report)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-batch", type=Path, required=True)
    parser.add_argument("--extension-batch", type=Path, required=True)
    parser.add_argument("--s3-task-list", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    result = accept(
        args.base_batch, args.extension_batch, args.s3_task_list,
        args.config, args.output_dir, require_clean_git=not args.allow_dirty,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
