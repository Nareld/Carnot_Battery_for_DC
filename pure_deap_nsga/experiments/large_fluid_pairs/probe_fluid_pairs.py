#!/usr/bin/env python3
"""Probe CoolProp support and the current critical-temperature pair gates.

This is a deterministic preflight tool.  It does not run CBSim and does not
claim thermodynamic feasibility; it writes an auditable eligibility table for
the next Sobol/LHS screening stage.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from CoolProp import __version__ as coolprop_version
from CoolProp.CoolProp import PropsSI


def property_or_none(output: str, fluid: str):
    try:
        return float(PropsSI(output, fluid))
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    fluids = config["fluid_candidates"]
    rows = []

    for wp_name, wp in config["working_points"].items():
        hp_threshold = float(wp["T_st_ht_max"]) + 20.0
        he_threshold = float(wp["T_cs"]) + 20.0
        for hp_name, hp_meta in fluids["hp_fluids"].items():
            hp_tc_k = property_or_none("Tcrit", hp_name)
            hp_pc = property_or_none("Pcrit", hp_name)
            hp_ttriple_k = property_or_none("Ttriple", hp_name)
            for he_name, he_meta in fluids["he_fluids"].items():
                he_tc_k = property_or_none("Tcrit", he_name)
                he_pc = property_or_none("Pcrit", he_name)
                he_ttriple_k = property_or_none("Ttriple", he_name)
                hp_tc_c = None if hp_tc_k is None else hp_tc_k - 273.15
                he_tc_c = None if he_tc_k is None else he_tc_k - 273.15
                hp_margin = None if hp_tc_c is None else hp_tc_c - hp_threshold
                he_margin = None if he_tc_c is None else he_tc_c - he_threshold
                supported = hp_tc_c is not None and he_tc_c is not None
                eligible = supported and hp_margin > 0.0 and he_margin > 0.0
                reasons = []
                if not supported:
                    reasons.append("FLUID_COOLPROP_UNAVAILABLE")
                if hp_margin is not None and hp_margin <= 0.0:
                    reasons.append("HP_FLUID_FILTER_TC_MARGIN_LOW")
                if he_margin is not None and he_margin <= 0.0:
                    reasons.append("HE_FLUID_FILTER_TC_MARGIN_LOW")
                rows.append({
                    "coolprop_version": coolprop_version,
                    "wp": wp_name,
                    "fluid_hp": hp_name,
                    "fluid_he": he_name,
                    "hp_pool": hp_meta.get("pool", "unspecified"),
                    "he_pool": he_meta.get("pool", "unspecified"),
                    "hp_tc_config_C": hp_meta.get("Tc_C"),
                    "he_tc_config_C": he_meta.get("Tc_C"),
                    "hp_tc_coolprop_C": hp_tc_c,
                    "he_tc_coolprop_C": he_tc_c,
                    "hp_pc_Pa": hp_pc,
                    "he_pc_Pa": he_pc,
                    "hp_ttriple_K": hp_ttriple_k,
                    "he_ttriple_K": he_ttriple_k,
                    "hp_tc_threshold_C": hp_threshold,
                    "he_tc_threshold_C": he_threshold,
                    "hp_tc_margin_K": hp_margin,
                    "he_tc_margin_K": he_margin,
                    "coolprop_supported": supported,
                    "eligible_current_tc_gate": eligible,
                    "reason_codes": ";".join(reasons),
                })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
