#!/usr/bin/env python3
"""Select reproducible S2 fluid-pair candidates from an accepted S1 dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


PAIRING = {"DC-B": ["DC-A", "DC-B"], "DC-D": ["DC-C", "DC-D"], "DC-F": ["DC-E", "DC-F"]}
KPI_COLUMNS = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]
SEVERE_CODES = {
    "COOLPROP_PROPERTY_INPUT_OUT_OF_RANGE": 3.0,
    "COOLPROP_BACKEND_TWOPHASE_UNSUPPORTED": 3.0,
    "SOLVER_INITIAL_GUESS_OUT_OF_BOUNDS": 2.0,
    "SOLVER_RESIDUAL_TOO_HIGH": 2.0,
    "KPI_SANITY_ETA_P2P_RANGE": 2.0,
}


def normalize(series: pd.Series) -> pd.Series:
    lo, hi = float(series.min()), float(series.max())
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return pd.Series(0.0, index=series.index)
    return (series - lo) / (hi - lo)


def summarize_pairs(samples: pd.DataFrame, config: dict) -> pd.DataFrame:
    rows = []
    config_column = "cb_config" if "cb_config" in samples.columns else "cfg"
    group_keys = ["wp", config_column, "fluid_hp", "fluid_he"]
    for keys, group in samples.groupby(group_keys, sort=True):
        feasible = group[group["feasible"]]
        failure_weights = group.loc[~group["feasible"], "primary_code"].map(
            lambda code: SEVERE_CODES.get(code, 1.0)
        )
        row = dict(zip(group_keys, keys))
        row.update({
            "sample_count": len(group),
            "feasible_count": len(feasible),
            "feasible_rate": len(feasible) / len(group),
            "failure_severity": (
                float(failure_weights.sum()) / len(group)
                if len(failure_weights) and len(group) else 0.0
            ),
        })
        for kpi in KPI_COLUMNS:
            row[f"{kpi}_p95"] = (
                float(feasible[kpi].quantile(0.95)) if len(feasible) else np.nan
            )
            row[f"{kpi}_max"] = (
                float(feasible[kpi].max()) if len(feasible) else np.nan
            )
        row["cb_config"] = row.pop(config_column)
        hp_meta = config["fluid_candidates"]["hp_fluids"][row["fluid_hp"]]
        he_meta = config["fluid_candidates"]["he_fluids"][row["fluid_he"]]
        row["hp_pool"] = hp_meta.get("pool", "unspecified")
        row["he_pool"] = he_meta.get("pool", "unspecified")
        row["baseline_pair"] = (
            row["hp_pool"] == "baseline" and row["he_pool"] == "baseline"
        )
        rows.append(row)
    summary = pd.DataFrame(rows)
    scored = []
    for (_, _), group in summary.groupby(["wp", "cb_config"], sort=True):
        group = group.copy()
        group["feasible_score"] = normalize(group["feasible_rate"])
        for kpi in KPI_COLUMNS:
            group[f"{kpi}_score"] = normalize(
                group[f"{kpi}_p95"].fillna(group[f"{kpi}_p95"].min())
            )
        group["reliability_score"] = 1.0 - normalize(group["failure_severity"])
        group["selection_score"] = (
            0.40 * group["feasible_score"]
            + 0.15 * group["eta_p2p_score"]
            + 0.15 * group["energy_density_thermal_score"]
            + 0.15 * group["exergy_efficiency_score"]
            + 0.15 * group["reliability_score"]
        )
        scored.append(group)
    return pd.concat(scored, ignore_index=True)


def select_for_wp(group: pd.DataFrame, limit: int) -> pd.DataFrame:
    eligible = group[group["feasible_count"] > 0].copy()
    selected: dict[tuple[str, str], set[str]] = {}

    def add(rows: pd.DataFrame, reason: str):
        for row in rows.itertuples():
            key = (row.fluid_hp, row.fluid_he)
            selected.setdefault(key, set()).add(reason)

    add(eligible.nlargest(max(limit - 8, 1), "selection_score"), "composite_score")
    for kpi in KPI_COLUMNS:
        add(eligible.nlargest(2, f"{kpi}_p95"), f"{kpi}_extreme")
    add(
        eligible[eligible["baseline_pair"]].nlargest(4, "selection_score"),
        "baseline_coverage",
    )

    ranked = eligible.sort_values("selection_score", ascending=False)
    for row in ranked.itertuples():
        if len(selected) >= limit:
            break
        selected.setdefault((row.fluid_hp, row.fluid_he), set()).add("score_fill")

    chosen = eligible[
        eligible.apply(lambda row: (row["fluid_hp"], row["fluid_he"]) in selected, axis=1)
    ].copy()
    chosen["selected_reason"] = chosen.apply(
        lambda row: ";".join(sorted(selected[(row["fluid_hp"], row["fluid_he"])])),
        axis=1,
    )
    return chosen.sort_values(
        ["selection_score", "fluid_hp", "fluid_he"], ascending=[False, True, True]
    ).head(limit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--s1-parquet", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pairs-per-wp", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    samples = pd.read_parquet(args.s1_parquet)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    summary = summarize_pairs(samples, config)
    selections = []
    task_rows = []
    observed_configs = sorted(summary["cb_config"].unique())
    for source_wp in ["DC-B", "DC-D", "DC-F"]:
        for source_cfg in observed_configs:
            source = summary[
                (summary["wp"] == source_wp)
                & (summary["cb_config"] == source_cfg)
            ]
            if source.empty:
                continue
            chosen = select_for_wp(source, args.pairs_per_wp)
            chosen["source_screening_wp"] = source_wp
            chosen["source_screening_cfg"] = source_cfg
            selections.append(chosen)
            for row in chosen.itertuples():
                for target_wp in PAIRING[source_wp]:
                    task_rows.append({
                        "wp": target_wp, "cfg": source_cfg,
                        "fluid_hp": row.fluid_hp, "fluid_he": row.fluid_he,
                        "seed": args.seed,
                        "source_screening_wp": source_wp,
                        "source_screening_cfg": source_cfg,
                        "selection_score": row.selection_score,
                        "selected_reason": row.selected_reason,
                    })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = pd.concat(selections, ignore_index=True)
    selected.to_csv(args.output_dir / "s2_selected_pairs.csv", index=False)
    summary.to_csv(args.output_dir / "s1_pair_scores.csv", index=False)
    tasks = pd.DataFrame(task_rows).drop_duplicates(
        ["wp", "cfg", "fluid_hp", "fluid_he", "seed"]
    )
    tasks.to_csv(args.output_dir / "s2_task_list.csv", index=False)
    report = {
        "pairs_per_screening_wp": args.pairs_per_wp,
        # Backward-compatible alias; candidates are now configuration-specific.
        "selected_pair_count": len(selected),
        "selected_task_candidate_count": len(selected),
        "task_count": len(tasks),
        "source_working_points": ["DC-B", "DC-D", "DC-F"],
        "target_working_points": sorted(tasks["wp"].unique()),
        "configurations": sorted(tasks["cfg"].unique()),
        "unobserved_configurations": sorted(
            set(config["configurations"]) - set(observed_configs)
        ),
        "selection_unit": "wp_x_configuration_x_fluid_pair",
        "seed": args.seed,
        "selection_weights": {
            "feasible_rate": 0.40, "eta_p2p_p95": 0.15,
            "energy_density_thermal_p95": 0.15,
            "exergy_efficiency_p95": 0.15, "failure_reliability": 0.15,
        },
    }
    (args.output_dir / "selection_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
