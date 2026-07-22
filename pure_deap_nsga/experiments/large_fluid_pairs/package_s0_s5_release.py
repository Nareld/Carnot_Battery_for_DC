#!/usr/bin/env python3
"""Build a compact, auditable S0-S5 data release from external run storage.

The full run tree remains outside git.  This script copies only batch summaries,
accepted registries, pooled fronts, and S5 independent-revalidation evidence.
Text artifacts are made portable by replacing machine-local roots while the
manifest retains SHA-256 hashes of both the source and packaged bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


RELEASE_NAME = "CBSIM_S0_S5_20260722"

STAGES = {
    "S0": "S0_REMEDIATION",
    "S1": "S1_FORMAL/BATCH_S1_20260716T121618Z",
    "S2": "S2_ACCEPTED/ACCEPTED_S2_20260720T022648Z",
    "S3": "S3_FORMAL/S3_20260720T031411Z",
    "S4": "S4_ACCEPTED/ACCEPTED_S4_20260721T101316Z",
    "S5": "S5_FORMAL/S5_20260721T102425Z",
}

ROOT_FILES = {
    "S0": [
        "REMEDIATION_REPORT.md",
        "all_124.csv",
        "native_15.csv",
        "wrapper_109.csv",
        "BATCH_S0NATIVEFIX_20260716T105913Z/batch_manifest.json",
        "BATCH_S0NATIVEFIX_20260716T105913Z/run_registry.csv",
        "BATCH_S0WRAPPERFIX_20260716T105954Z/batch_manifest.json",
        "BATCH_S0WRAPPERFIX_20260716T105954Z/run_registry.csv",
        "BATCH_S0FINALFIX_20260716T110657Z/batch_manifest.json",
        "BATCH_S0FINALFIX_20260716T110657Z/run_registry.csv",
    ],
    "S1": [
        "ACCEPTANCE_REPORT.md",
        "batch_manifest.json",
        "failure_spectrum.csv",
        "filtered_cases.json",
        "run_registry.csv",
        "s1_batch_summary.json",
        "sampling_feasibility.parquet",
        "sampling_task_summary.csv",
        "task_plan.json",
    ],
    "S2": [
        "S2_ACCEPTANCE_REPORT.md",
        "accepted_manifest.json",
        "accepted_run_registry.csv",
        "replacement_map.csv",
    ],
    "S3": [
        "S3_ACCEPTANCE_REPORT.md",
        "candidate_ranking.csv",
        "extreme_coverage.csv",
        "s3_manifest.json",
        "s3_selected_candidates.csv",
        "s4_task_list.csv",
        "selection_units.csv",
    ],
    "S4": [
        "S4_ACCEPTANCE_REPORT.md",
        "accepted_manifest.json",
        "accepted_run_registry.csv",
        "candidate_stability.csv",
        "s5_diagnostic_queue.csv",
        "s5_representative_points.csv",
        "seed_candidate_rankings.csv",
        "seed_stability_metrics.csv",
    ],
    "S5": [
        "S5_REVALIDATION_REPORT.md",
        "balance_evidence.csv",
        "diagnostic_issues.csv",
        "phase_path.csv",
        "pinch_evidence.csv",
        "representative_evidence.csv",
        "s5_evidence_summary.csv",
        "s5_manifest.json",
        "s5_run_registry.csv",
        "state_points.csv",
    ],
}

EXTRA_TREES = {
    "S5": ["evidence"],
}

TEXT_SUFFIXES = {".csv", ".json", ".md", ".txt", ".yaml", ".yml"}
ENGINEERING_FILES = [
    "P2_ENGINEERING_REVIEW.md",
    "p2_candidate_gate.csv",
    "p2_fluid_screening.csv",
    "p2_s5_gate.csv",
    "p2_summary.json",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def copy_portable(source: Path, target: Path, replacements: dict[str, str]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() not in TEXT_SUFFIXES:
        shutil.copy2(source, target)
        return
    data = source.read_text(encoding="utf-8")
    for old, new in replacements.items():
        data = data.replace(old, new)
    had_final_newline = data.endswith("\n")
    data = "\n".join(line.rstrip() for line in data.splitlines())
    if had_final_newline:
        data += "\n"
    target.write_text(data, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, default=Path("/home/oxford/cbsim-runs"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--assets-root",
        type=Path,
        default=Path("/home/oxford/cbsim-runs/releases/CBSIM_S0_S5_20260722"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    runs_root = args.runs_root.resolve()
    output = (args.output or repo_root / "data" / "releases" / RELEASE_NAME).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    replacements = {
        str(runs_root): "${CBSIM_RUNS_ROOT}",
        str(repo_root): "${CBSIM_REPO_ROOT}",
    }
    records: list[dict[str, object]] = []

    def add(source: Path, packaged_relative: Path, stage: str, category: str) -> None:
        if not source.is_file():
            raise FileNotFoundError(source)
        target = output / packaged_relative
        source_hash = sha256(source)
        copy_portable(source, target, replacements)
        records.append(
            {
                "stage": stage,
                "category": category,
                "source_relative_to_runs_root": (
                    str(source.relative_to(runs_root)) if source.is_relative_to(runs_root) else None
                ),
                "source_relative_to_repo_root": (
                    str(source.relative_to(repo_root)) if source.is_relative_to(repo_root) else None
                ),
                "packaged_path": packaged_relative.as_posix(),
                "source_sha256": source_hash,
                "packaged_sha256": sha256(target),
                "size_bytes": target.stat().st_size,
                "portable_text_rewrite": source_hash != sha256(target),
            }
        )

    for stage, stage_relative in STAGES.items():
        source_root = runs_root / stage_relative
        for filename in ROOT_FILES[stage]:
            add(source_root / filename, Path(stage) / filename, stage, "summary")
        for tree_name in EXTRA_TREES.get(stage, []):
            for source in sorted((source_root / tree_name).rglob("*")):
                if source.is_file():
                    add(
                        source,
                        Path(stage) / tree_name / source.relative_to(source_root / tree_name),
                        stage,
                        "pooled_front" if tree_name == "pooled_fronts" else "revalidation_evidence",
                    )

    pair_eligibility = runs_root / "VALIDATION_20260716T025220Z/outputs/pair_eligibility.csv"
    add(pair_eligibility, Path("S0") / "pair_eligibility.csv", "S0", "property_domain_precheck")

    config = repo_root / "pure_deap_nsga/experiments/large_fluid_pairs/optimization_config_large_pairs.json"
    add(config, Path("frozen") / config.name, "CODE", "configuration")
    engineering_root = repo_root / "pure_deap_nsga/experiments/large_fluid_pairs/engineering_review"
    for filename in ENGINEERING_FILES:
        add(engineering_root / filename, Path("engineering") / filename, "P2", "engineering_review")
    for filename in ["front_assets_manifest.json", "checksums.sha256"]:
        add(args.assets_root.resolve() / filename, Path("assets") / filename, "DATA", "release_asset_index")

    manifest = {
        "schema_version": "1.0",
        "release_name": RELEASE_NAME,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repository_commit": git(repo_root, "rev-parse", "HEAD"),
        "repository_remote": git(repo_root, "remote", "get-url", "origin"),
        "scope": "Compact S0-S5 summaries, accepted registries, engineering review, and S5 evidence; raw run directories and checkpoints excluded.",
        "path_policy": "Machine-local roots in text files are replaced by CBSIM_RUNS_ROOT and CBSIM_REPO_ROOT placeholders.",
        "source_stage_roots": STAGES,
        "file_count": len(records),
        "total_size_bytes": sum(int(record["size_bytes"]) for record in records),
        "files": records,
    }
    manifest_path = output / "release_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    readme = f"""# CBSim S0-S5 compact data release

This directory is the GitHub-sized audit package for the formal large-fluid-pair campaign.
It contains S1-S5 summary/acceptance records, S3 pooled Pareto fronts, the accepted S4
candidate/stability tables, and all 36 S5 independent-revalidation task/evidence records.

## Accepted stage chain

- S0: historical failed-batch evidence plus the 15 native / 109 wrapper remediation chain
- S1: formal feasibility sampling and failure spectrum
- S2: accepted coarse optimization registry
- S3: 60 selected candidates and pooled fronts
- S4: 300 canonical five-seed runs; 17 candidates accepted for S5
- S5: 18 representative points, two independent repeats each; 36/36 passed

S0 is historical remediation evidence and is not claimed as byte-reproducible from a
clean commit. S5 acceptance is a thermodynamic/numerical result, not an engineering recommendation.
Use `P2_ENGINEERING_REVIEW.md` and `p2_fluid_screening.csv` when present for the separate
safety, environmental, regulatory, materials, and equipment review.

## Integrity and portability

`release_manifest.json` records the source and packaged SHA-256 for every copied file.
`checksums.sha256` verifies the complete packaged tree. Machine-local text paths were
replaced with `${{CBSIM_RUNS_ROOT}}` and `${{CBSIM_REPO_ROOT}}`; source hashes remain in
the manifest. Raw per-run archives, failure records, logs, and checkpoints are excluded
in accordance with `COMPUTE_RUN_DATA_MANAGEMENT_SPEC.md`.

The 12 deterministic S2/S4 accepted-front shards are indexed under `assets/` and are
intended for GitHub Release assets, not git history.

Files: {manifest['file_count']}
Payload: {manifest['total_size_bytes']} bytes
Source code commit: `{manifest['repository_commit']}`
"""
    (output / "README.md").write_text(readme, encoding="utf-8")

    checksum_lines = []
    for path in sorted(p for p in output.rglob("*") if p.is_file() and p != output / "checksums.sha256"):
        checksum_lines.append(f"{sha256(path)}  {path.relative_to(output).as_posix()}")
    (output / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print(json.dumps({"output": str(output), "files": len(records), "bytes": manifest["total_size_bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
