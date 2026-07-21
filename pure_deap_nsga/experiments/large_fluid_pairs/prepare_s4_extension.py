#!/usr/bin/env python3
"""Prepare an auditable checkpoint-resume list for non-converged S4 runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pandas as pd


TASK_KEY = ["wp", "cfg", "fluid_hp", "fluid_he", "seed"]


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


def prepare(base_batch: Path, s3_task_list: Path, config_path: Path,
            output_dir: Path, target_maximum: int,
            require_clean_git: bool = True) -> dict:
    repository = Path(__file__).resolve().parents[3]
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repository, text=True
    ).strip())
    if require_clean_git and dirty:
        raise ValueError("S4_EXTENSION_PREPARATION_REQUIRES_CLEAN_GIT")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"S4_EXTENSION_OUTPUT_NOT_EMPTY: {output_dir}")

    base_batch = base_batch.resolve()
    batch_manifest_path = base_batch / "batch_manifest.json"
    registry_path = base_batch / "run_registry.csv"
    task_plan_path = base_batch / "task_plan.json"
    for path in [batch_manifest_path, registry_path, task_plan_path, s3_task_list, config_path]:
        if not path.is_file():
            raise ValueError(f"S4_EXTENSION_REQUIRED_INPUT_MISSING: {path}")
    batch_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
    if batch_manifest.get("status") != "COMPUTE_COMPLETE" \
    or not batch_manifest.get("accepted_compute"):
        raise ValueError("S4_EXTENSION_BASE_BATCH_NOT_COMPUTE_COMPLETE")
    if batch_manifest.get("stage") != "S4":
        raise ValueError("S4_EXTENSION_BASE_STAGE_MISMATCH")
    if sha256_file(s3_task_list) != batch_manifest.get("task_list_sha256"):
        raise ValueError("S4_EXTENSION_S3_TASK_LIST_HASH_MISMATCH")
    if sha256_file(config_path) != batch_manifest.get("config_sha256"):
        raise ValueError("S4_EXTENSION_CONFIG_HASH_MISMATCH")

    registry = pd.read_csv(registry_path)
    s3 = pd.read_csv(s3_task_list)
    if len(registry) != int(batch_manifest.get("task_count", -1)):
        raise ValueError("S4_EXTENSION_BASE_TASK_COUNT_MISMATCH")
    if registry.duplicated(TASK_KEY).any() or registry["run_id"].duplicated().any():
        raise ValueError("S4_EXTENSION_BASE_DUPLICATE_TASK")
    if s3.duplicated(TASK_KEY).any() or set(map(tuple, s3[TASK_KEY].to_numpy())) != set(
        map(tuple, registry[TASK_KEY].to_numpy())
    ):
        raise ValueError("S4_EXTENSION_S3_LINEAGE_KEY_MISMATCH")
    base_gates = (
        registry["scheduler_status"].eq("FINISHED")
        & registry["terminal_status"].eq("COMPLETED")
        & registry["exit_code"].eq(0)
        & registry["pareto_size"].gt(0)
    )
    if not base_gates.all():
        raise ValueError("S4_EXTENSION_BASE_RUN_GATE_FAILED")

    selected = registry.loc[~registry["hv_converged"].map(truthy)].copy()
    if selected.empty:
        raise ValueError("S4_EXTENSION_NO_NONCONVERGED_RUNS")
    lineage = s3.set_index(TASK_KEY)
    rows = []
    for source in selected.sort_values(TASK_KEY).itertuples(index=False):
        run_dir = Path(source.run_dir).resolve()
        manifest_path = Path(source.manifest_path).resolve()
        checkpoint_path = run_dir / "checkpoints" / "latest.json"
        checksums_path = run_dir / "metadata" / "checksums.sha256"
        for path in [manifest_path, checkpoint_path, checksums_path]:
            if not path.is_file():
                raise ValueError(f"S4_EXTENSION_SOURCE_ARTIFACT_MISSING: {source.run_id}: {path}")
        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        completed = int(source_manifest.get("completed_generations", -1))
        checkpoint_generation = int(checkpoint.get("generation", -1))
        source_maximum = int(
            checkpoint.get("optimizer_signature", {}).get("maximum_generations", -1)
        )
        if completed != checkpoint_generation or completed != source_maximum:
            raise ValueError(
                f"S4_EXTENSION_CHECKPOINT_NOT_TERMINAL: {source.run_id}: "
                f"manifest={completed} checkpoint={checkpoint_generation} maximum={source_maximum}"
            )
        if target_maximum <= source_maximum:
            raise ValueError(
                f"S4_EXTENSION_TARGET_NOT_GREATER: source={source_maximum} target={target_maximum}"
            )
        checkpoint_hash = sha256_file(checkpoint_path)
        expected_hash = checksum_entry(checksums_path, "checkpoints/latest.json")
        if checkpoint_hash != expected_hash:
            raise ValueError(f"S4_EXTENSION_CHECKPOINT_HASH_MISMATCH: {source.run_id}")
        expected_manifest_hash = checksum_entry(
            checksums_path, "metadata/manifest.json"
        )
        if sha256_file(manifest_path) != expected_manifest_hash:
            raise ValueError(f"S4_EXTENSION_MANIFEST_HASH_MISMATCH: {source.run_id}")
        run_signature = checkpoint.get("run_signature", {})
        expected_signature = {
            "config_sha256": batch_manifest["config_sha256"],
            "wp": source.wp, "cfg": source.cfg,
            "fluid_hp": source.fluid_hp, "fluid_he": source.fluid_he,
            "seed": int(source.seed),
        }
        if run_signature != expected_signature:
            raise ValueError(f"S4_EXTENSION_RUN_SIGNATURE_MISMATCH: {source.run_id}")
        lineage_row = lineage.loc[
            (source.wp, source.cfg, source.fluid_hp, source.fluid_he, source.seed)
        ]
        rows.append({
            "wp": source.wp, "cfg": source.cfg,
            "fluid_hp": source.fluid_hp, "fluid_he": source.fluid_he,
            "seed": int(source.seed), "resume_from": str(checkpoint_path),
            "source_checkpoint_sha256": checkpoint_hash,
            "source_s4_run_id": source.run_id,
            "source_s4_run_dir": str(run_dir),
            "source_s4_manifest_sha256": sha256_file(manifest_path),
            "supersedes_run_id": source.run_id,
            "source_s2_run_id": lineage_row["source_s2_run_id"],
            "s3_selection_rank": int(lineage_row["s3_selection_rank"]),
            "s3_selected_reason": lineage_row["s3_selected_reason"],
            "requires_s5_review": truthy(lineage_row["requires_s5_review"]),
            "extension_target_maximum_generations": target_maximum,
            "source_evaluation_count": int(source.evaluation_count),
            "source_feasible_count": int(source.feasible_count),
            "source_failure_count": int(source.failure_count),
            "source_front_revalidation_solver_calls": int(
                source.front_revalidation_solver_calls
            ),
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    task_list_path = output_dir / "s4_extension_task_list.csv"
    frame = pd.DataFrame(rows).sort_values(TASK_KEY).reset_index(drop=True)
    atomic_text(task_list_path, frame.to_csv(index=False, lineterminator="\n"))
    manifest = {
        "schema_version": "1.0",
        "status": "APPROVED_FOR_S4_EXTENSION",
        "selection_rule": "base S4 terminal_status=COMPLETED and hv_converged=false",
        "source_batch": str(base_batch),
        "source_batch_manifest_sha256": sha256_file(batch_manifest_path),
        "source_run_registry_sha256": sha256_file(registry_path),
        "source_task_plan_sha256": sha256_file(task_plan_path),
        "source_s3_task_list": str(s3_task_list.resolve()),
        "source_s3_task_list_sha256": sha256_file(s3_task_list),
        "config": str(config_path.resolve()),
        "config_sha256": sha256_file(config_path),
        "git_commit": commit, "git_dirty": dirty,
        "source_task_count": len(registry),
        "extension_task_count": len(frame),
        "source_maximum_generations": sorted(
            set(int(json.loads(Path(row["resume_from"]).read_text())["optimizer_signature"]["maximum_generations"])
                for row in rows)
        ),
        "target_maximum_generations": target_maximum,
        "resume_policy": "deterministic checkpoint continuation; only maximum_generations may increase",
        "task_list": str(task_list_path.resolve()),
        "task_list_sha256": sha256_file(task_list_path),
    }
    atomic_text(
        output_dir / "extension_manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    report = f"""# S4 Exception Extension Approval

- Base tasks: {len(registry)}
- Approved extension tasks: {len(frame)}
- Selection: only completed S4 runs with `hv_converged=false`
- Source horizon: {manifest['source_maximum_generations']}
- Target horizon: {target_maximum}
- Resume: each source run's checksum-verified terminal checkpoint

All converged S4 runs are excluded from recomputation. The extension preserves S2/S3/S4
lineage and permits no optimizer change other than increasing the maximum generation.
"""
    atomic_text(output_dir / "S4_EXTENSION_APPROVAL.md", report)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-batch", type=Path, required=True)
    parser.add_argument("--s3-task-list", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-maximum-generations", type=int, default=300)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    result = prepare(
        args.base_batch, args.s3_task_list, args.config, args.output_dir,
        args.target_maximum_generations, require_clean_git=not args.allow_dirty,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
