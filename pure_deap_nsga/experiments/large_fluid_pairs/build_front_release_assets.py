#!/usr/bin/env python3
"""Build deterministic, WP-sharded Pareto-front assets for a GitHub release."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


REGISTRIES = {
    "S2": Path("/home/oxford/cbsim-runs/S2_ACCEPTED/ACCEPTED_S2_20260720T022648Z/accepted_run_registry.csv"),
    "S4": Path("/home/oxford/cbsim-runs/S4_ACCEPTED/ACCEPTED_S4_20260721T101316Z/accepted_run_registry.csv"),
}
WORKING_POINTS = ["DC-A", "DC-B", "DC-C", "DC-D", "DC-E", "DC-F"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_shard(stage: str, wp: str, registry_rows: list[dict[str, str]], target: Path) -> dict[str, object]:
    selected = [row for row in registry_rows if row["wp"] == wp]
    target.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    header: bytes | None = None
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as compressed:
            for registry_row in selected:
                pareto = Path(registry_row["run_dir"]) / "outputs" / "pareto.csv"
                with pareto.open("rb") as source:
                    current_header = source.readline().rstrip(b"\r\n")
                    if header is None:
                        header = current_header
                        compressed.write(header + b"\n")
                    elif current_header != header:
                        raise ValueError(f"header mismatch: {pareto}")
                    for line in source:
                        if line.strip():
                            compressed.write(line.rstrip(b"\r\n") + b"\n")
                            row_count += 1
    return {
        "stage": stage,
        "working_point": wp,
        "asset": target.name,
        "run_count": len(selected),
        "front_row_count": row_count,
        "size_bytes": target.stat().st_size,
        "sha256": sha256(target),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/home/oxford/cbsim-runs/releases/CBSIM_S0_S5_20260722/fronts"),
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    assets = []
    registry_hashes = {}
    for stage, registry in REGISTRIES.items():
        registry_hashes[stage] = sha256(registry)
        registry_rows = rows(registry)
        for wp in WORKING_POINTS:
            name = f"{stage.lower()}_{wp.lower().replace('-', '')}_accepted_fronts.csv.gz"
            assets.append(build_shard(stage, wp, registry_rows, output / name))

    manifest = {
        "schema_version": "1.0",
        "format": "Deterministic gzip (level 9, mtime 0), one CSV header, accepted registry order",
        "source_registries": {stage: {"path": str(path), "sha256": registry_hashes[stage]} for stage, path in REGISTRIES.items()},
        "asset_count": len(assets),
        "total_size_bytes": sum(int(asset["size_bytes"]) for asset in assets),
        "total_front_rows": sum(int(asset["front_row_count"]) for asset in assets),
        "assets": assets,
    }
    manifest_path = output.parent / "front_assets_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checksum_lines = [f"{asset['sha256']}  fronts/{asset['asset']}" for asset in assets]
    checksum_lines.append(f"{sha256(manifest_path)}  front_assets_manifest.json")
    (output.parent / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output.parent), "assets": len(assets), "bytes": manifest["total_size_bytes"], "rows": manifest["total_front_rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
