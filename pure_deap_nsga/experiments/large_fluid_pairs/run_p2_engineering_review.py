#!/usr/bin/env python3
"""Generate a conservative P2 engineering gate from accepted S4/S5 evidence.

This review intentionally does not infer charge limits, material compatibility,
thermal lifetime, ventilation, or legal permission from CoolProp feasibility.
Missing standard safety evidence blocks design freeze.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


SOURCES = {
    "safety_gwp": "https://www.dcceew.gov.au/environment/protection/ozone/rac/global-warming-potential-values-hfc-refrigerants",
    "ashrae_designations": "https://www.ashrae.org/technical-resources/standards-and-guidelines/ashrae-refrigerant-designations",
    "eu_fgas": "https://eur-lex.europa.eu/eli/reg/2024/573/2024-02-20/eng",
    "china_hfc_2026": "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk05/202510/W020251024653086234356.pdf",
    "acetone_niosh": "https://www.cdc.gov/niosh/npg/npgd0004.html",
    "cyclopentane_niosh": "https://www.cdc.gov/niosh/npg/npgd0171.html",
    "unep_odp": "https://ozone.unep.org/20-questions-and-answers",
    "ipcc_ar6": "https://www.ipcc.ch/report/ar6/wg3/downloads/report/IPCC_AR6_WGIII_Annex-II.pdf",
}

# AR4 GWP100 values are retained because they are the regulatory accounting
# values used by the cited government table and EU Annex I. Do not mix them
# with the AR6 GWP20 column or silently substitute AR6 GWP100 values.
FLUIDS = {
    "Acetone": {
        "standard_safety_class": "NOT_FOUND_IN_PUBLIC_STANDARD_TABLE",
        "gwp100_ar4": "not_assessed",
        "odp": "not_controlled_as_ODS; individual numeric value not verified",
        "gate": "CONDITIONAL",
        "basis": "NIOSH: flash point 0 F, LFL 2.5%, REL 250 ppm; charge and occupational controls required",
        "source": "acetone_niosh;ashrae_designations",
    },
    "Cyclopentane": {
        "standard_safety_class": "NOT_FOUND_IN_PUBLIC_STANDARD_TABLE",
        "gwp100_ar4": "not_assessed",
        "odp": "not_controlled_as_ODS; individual numeric value not verified",
        "gate": "CONDITIONAL",
        "basis": "NIOSH: flash point -35 F, LFL 1.1%, REL 600 ppm; high flammability controls required",
        "source": "cyclopentane_niosh;ashrae_designations",
    },
    "R600": {
        "standard_safety_class": "A3",
        "gwp100_ar4": "<5",
        "odp": "not_controlled_as_ODS",
        "gate": "CONDITIONAL",
        "basis": "Higher flammability; charge, zoning, ventilation, detection and shutdown design required",
        "source": "safety_gwp",
    },
    "R601a": {
        "standard_safety_class": "A3",
        "gwp100_ar4": "<5",
        "odp": "not_controlled_as_ODS",
        "gate": "CONDITIONAL",
        "basis": "Higher flammability; source supports <5, not an exact GWP value",
        "source": "safety_gwp",
    },
    "R227EA": {
        "standard_safety_class": "A1",
        "gwp100_ar4": "3220",
        "odp": "0",
        "gate": "CONDITIONAL",
        "basis": "High-GWP controlled HFC; quota, leak checking, recovery and local-use review required",
        "source": "safety_gwp;eu_fgas;china_hfc_2026;unep_odp",
    },
    "R236ea": {
        "standard_safety_class": "n/a",
        "gwp100_ar4": "1370",
        "odp": "0",
        "gate": "REJECT",
        "basis": "No standard safety classification in cited table; blocks equipment design freeze",
        "source": "safety_gwp;eu_fgas;china_hfc_2026;unep_odp",
    },
    "R245fa": {
        "standard_safety_class": "B1",
        "gwp100_ar4": "1030",
        "odp": "0",
        "gate": "CONDITIONAL",
        "basis": "Higher chronic-toxicity group and controlled HFC; exposure, leak and recovery controls required",
        "source": "safety_gwp;eu_fgas;china_hfc_2026;unep_odp",
    },
    "R365MFC": {
        "standard_safety_class": "n/a",
        "gwp100_ar4": "794",
        "odp": "0",
        "gate": "REJECT",
        "basis": "No standard safety classification in cited table (listed mainly as foaming agent); blocks design freeze",
        "source": "safety_gwp;eu_fgas;china_hfc_2026;unep_odp",
    },
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def pair_gate(fluid_hp: str, fluid_he: str) -> tuple[str, str]:
    gates = {FLUIDS[fluid_hp]["gate"], FLUIDS[fluid_he]["gate"]}
    if "REJECT" in gates:
        rejected = [fluid for fluid in (fluid_hp, fluid_he) if FLUIDS[fluid]["gate"] == "REJECT"]
        return "REJECT", "missing_standard_safety_class:" + ";".join(rejected)
    return "CONDITIONAL", "engineering_controls_and_site_specific_evidence_required"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--s4-root",
        type=Path,
        default=Path("/home/oxford/cbsim-runs/S4_ACCEPTED/ACCEPTED_S4_20260721T101316Z"),
    )
    parser.add_argument(
        "--s5-root",
        type=Path,
        default=Path("/home/oxford/cbsim-runs/S5_FORMAL/S5_20260721T102425Z"),
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    states = read_csv(args.s5_root / "state_points.csv")
    max_temp_c: dict[str, float] = defaultdict(lambda: float("-inf"))
    rep_min_pressure: dict[str, float] = defaultdict(lambda: float("inf"))
    for row in states:
        fluid = row["fluid"]
        max_temp_c[fluid] = max(max_temp_c[fluid], float(row["temperature_K"]) - 273.15)
        rep_min_pressure[row["representative_id"]] = min(
            rep_min_pressure[row["representative_id"]], float(row["pressure_Pa"]) / 100_000.0
        )

    fluid_rows = []
    for fluid, evidence in FLUIDS.items():
        fluid_rows.append(
            {
                "fluid": fluid,
                **evidence,
                "s5_max_temperature_C": round(max_temp_c.get(fluid, float("nan")), 3),
            }
        )
    fluid_columns = ["fluid", "standard_safety_class", "gwp100_ar4", "odp", "gate", "basis", "source", "s5_max_temperature_C"]
    write_csv(output / "p2_fluid_screening.csv", fluid_rows, fluid_columns)

    candidates = read_csv(args.s4_root / "candidate_stability.csv")
    candidate_rows = []
    for row in candidates:
        if row["accepted_for_s5"].lower() != "true":
            continue
        gate, reason = pair_gate(row["fluid_hp"], row["fluid_he"])
        candidate_rows.append(
            {
                "wp": row["wp"],
                "cfg": row["cfg"],
                "fluid_hp": row["fluid_hp"],
                "fluid_he": row["fluid_he"],
                "union_front_size": row["union_front_size"],
                "thermodynamic_status": row["s4_status"],
                "p2_engineering_gate": gate,
                "p2_reason": reason,
            }
        )
    candidate_columns = ["wp", "cfg", "fluid_hp", "fluid_he", "union_front_size", "thermodynamic_status", "p2_engineering_gate", "p2_reason"]
    write_csv(output / "p2_candidate_gate.csv", candidate_rows, candidate_columns)

    fallback_reps = set()
    warning_records = 0
    for path in sorted((args.s5_root / "evidence").glob("*.json")):
        evidence = json.loads(path.read_text(encoding="utf-8"))
        warnings = evidence.get("warnings", [])
        hits = [warning for warning in warnings if "least_squares" in warning]
        if hits:
            fallback_reps.add(evidence["task"]["representative"]["representative_id"])
            warning_records += len(hits)

    representatives = read_csv(args.s5_root / "representative_evidence.csv")
    representative_rows = []
    for row in representatives:
        gate, reason = pair_gate(row["fluid_hp"], row["fluid_he"])
        rep = row["representative_id"]
        pressure = rep_min_pressure[rep]
        risk_flags = []
        if pressure < 1.01325:
            risk_flags.append("below_standard_atmosphere")
        if pressure < 0.5:
            risk_flags.append("below_0.5_bar")
        if rep in fallback_reps:
            risk_flags.append("solver_fallback_observed")
        representative_rows.append(
            {
                "representative_id": rep,
                "wp": row["wp"],
                "representative_type": row["representative_type"],
                "fluid_hp": row["fluid_hp"],
                "fluid_he": row["fluid_he"],
                "s5_status": row["status"],
                "minimum_pressure_bar": round(pressure, 6),
                "solver_fallback": rep in fallback_reps,
                "p2_engineering_gate": gate,
                "p2_reason": reason,
                "risk_flags": ";".join(risk_flags),
            }
        )
    representative_columns = ["representative_id", "wp", "representative_type", "fluid_hp", "fluid_he", "s5_status", "minimum_pressure_bar", "solver_fallback", "p2_engineering_gate", "p2_reason", "risk_flags"]
    write_csv(output / "p2_s5_gate.csv", representative_rows, representative_columns)

    candidate_counts = Counter(row["p2_engineering_gate"] for row in candidate_rows)
    representative_counts = Counter(row["p2_engineering_gate"] for row in representative_rows)
    below_05 = [row for row in representative_rows if float(row["minimum_pressure_bar"]) < 0.5]
    below_10 = [row for row in representative_rows if float(row["minimum_pressure_bar"]) < 1.0]
    below_atm = [row for row in representative_rows if float(row["minimum_pressure_bar"]) < 1.01325]
    report = f"""# P2 engineering review

Status: **ENGINEERING_DESIGN_FREEZE_BLOCKED**

Thermodynamic/numerical acceptance remains valid, but no candidate has enough
site-specific evidence for an unconditional engineering recommendation.

## Gate result

- S4 stable candidates: {len(candidate_rows)} total; PASS 0, CONDITIONAL {candidate_counts['CONDITIONAL']}, REJECT {candidate_counts['REJECT']}.
- S5 representatives: {len(representative_rows)} total; PASS 0, CONDITIONAL {representative_counts['CONDITIONAL']}, REJECT {representative_counts['REJECT']}.
- `REJECT` means blocked from design freeze because required evidence is absent; it does not claim a universal legal ban.

All R236ea and R365MFC pairs are blocked because the cited government/ISO-ASHRAE
summary gives no standard safety class. Remaining pairs are conditional because of
A3/high flammability, B1 toxicity grouping, high-GWP HFC controls, or nonstandard
solvent use requiring project-specific hazard evidence.

## Operating-envelope findings

- {len(below_05)} representatives fall below 0.5 bar absolute.
- {len(below_10)} representatives fall below 1.0 bar absolute.
- {len(below_atm)} representatives fall below 1.01325 bar absolute.
- {len(fallback_reps)} representatives contain fsolve-to-least_squares fallback warnings ({warning_records} warning records); all S5 residual gates still passed.
- Maximum observed S5 temperatures are recorded per fluid in `p2_fluid_screening.csv`.

Sub-atmospheric cycles require air/moisture ingress, non-condensable accumulation,
vacuum sealing, oxidation and shutdown analysis. Solver fallback requires initial-
condition, design-variable perturbation, alternate-solver and start/stop sensitivity
tests before numerical robustness can be claimed.

## Evidence still required

1. Refrigerant charge, occupied volume, leakage scenario, ventilation and detector/interlock design.
2. Hazardous-area classification, ignition-source control, fire code and local permit review.
3. Metals, elastomers, lubricant and moisture compatibility; decomposition products and long-duration thermal ageing.
4. Pressure-vessel design pressure/vacuum rating, relief sizing, recovery/storage and maintenance isolation.
5. Jurisdiction- and equipment-category-specific F-gas/HFC quota, placing-on-market, leak-check and recovery assessment.

CoolProp convergence, critical temperature and S5 thermodynamic gates cannot supply
any of these missing facts.

## Source register

""" + "\n".join(f"- `{name}`: {url}" for name, url in SOURCES.items()) + "\n"
    (output / "P2_ENGINEERING_REVIEW.md").write_text(report, encoding="utf-8")

    summary = {
        "status": "ENGINEERING_DESIGN_FREEZE_BLOCKED",
        "s4_candidates": {"total": len(candidate_rows), "PASS": 0, **candidate_counts},
        "s5_representatives": {"total": len(representative_rows), "PASS": 0, **representative_counts},
        "below_0_5_bar": len(below_05),
        "below_1_0_bar": len(below_10),
        "below_standard_atmosphere": len(below_atm),
        "solver_fallback_representatives": sorted(fallback_reps),
        "solver_fallback_warning_records": warning_records,
        "sources": SOURCES,
    }
    (output / "p2_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
