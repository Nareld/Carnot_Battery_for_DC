#!/usr/bin/env python3
"""
Configuration-layer fluid filter diagnostics v0.2

Provides programmatic access to fluid filtering decisions so that
M01_fluid_filter_r600a_tc_margin can be executed as a diagnostic check.

v0.2 changes:
  - Reads Tc from optimization_config.json as primary data source
  - Hardcoded FLUID_TC retained as fallback
  - Boundary: Tc > threshold passes, Tc <= threshold fails
  - Consistent with run_optimization.py::get_fluid_combos()

Usage:
  from fluid_filter_diagnostics import check_fluid_filter
  result = check_fluid_filter(wp_cfg, fluid_hp, fluid_he, fluid_candidates)
"""

import json
import os
import sys
from typing import Any, Dict, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Hardcoded Tc values [°C] — used only as fallback when config is missing a fluid
_FALLBACK_TC = {
    'R1233zd(E)': 166.5,
    'R245fa': 153.9,
    'R600a': 134.7,
    'R600': 152.0,
    'R1234ze(E)': 109.4,
    'R227ea': 101.8,
    'R134a': 101.1,
    'R152a': 113.3,
}

TC_MARGIN = 20.0  # K  — Tc > threshold + 20K for subcritical operation


def load_config() -> dict:
    with open(os.path.join(SCRIPT_DIR, 'optimization_config.json')) as f:
        return json.load(f)


def _get_tc(fluid_name: str, fluid_candidates: Optional[dict] = None) -> Optional[float]:
    """Get critical temperature for a fluid, prefer config, fallback to hardcoded table."""
    if fluid_candidates is not None:
        for group in ['hp_fluids', 'he_fluids']:
            fluids = fluid_candidates.get(group, {})
            if fluid_name in fluids:
                tc = fluids[fluid_name].get('Tc_C')
                if tc is not None:
                    return float(tc)
    return _FALLBACK_TC.get(fluid_name)


def check_fluid_filter(wp_cfg: dict, fluid_hp: str, fluid_he: str,
                       fluid_candidates: Optional[dict] = None) -> Dict[str, Any]:
    """Check if a fluid pair passes the basic critical-temperature filter.

    Rule (from optimization_config.json comments):
      HP: Tc > T_st_ht_max + 20 K  →  Tc <= threshold → FAIL
      HE: Tc > T_cs + 20 K         →  Tc <= threshold → FAIL

    Returns dict with:
      - passed: bool
      - primary_code: str or None
      - n_issues: int
      - issues: list of issue dicts
    """
    issues = []

    T_st_ht_max = wp_cfg.get('T_st_ht_max', 150)
    T_cs = wp_cfg.get('T_cs', 5)
    threshold_hp = T_st_ht_max + TC_MARGIN
    threshold_he = T_cs + TC_MARGIN

    # HP check
    tc_hp = _get_tc(fluid_hp, fluid_candidates)
    if tc_hp is None:
        issues.append({
            'code': 'FLUID_FILTER_TC_MARGIN_LOW',
            'component': 'config', 'cls': 'FluidFilter', 'method': 'check_fluid_filter',
            'message': f'HP fluid {fluid_hp}: Tc unknown',
            'severity': 'error',
            'values': {'fluid': fluid_hp, 'Tc': None, 'threshold': threshold_hp, 'wp': dict(wp_cfg)},
        })
    elif tc_hp <= threshold_hp:
        issues.append({
            'code': 'FLUID_FILTER_TC_MARGIN_LOW',
            'component': 'config', 'cls': 'FluidFilter', 'method': 'check_fluid_filter',
            'message': f'HP fluid {fluid_hp}: Tc={tc_hp}°C <= T_st_ht_max+20={threshold_hp}°C',
            'severity': 'error',
            'values': {'fluid': fluid_hp, 'Tc': tc_hp, 'threshold': threshold_hp},
        })

    # HE check
    tc_he = _get_tc(fluid_he, fluid_candidates)
    if tc_he is None:
        issues.append({
            'code': 'FLUID_FILTER_TC_MARGIN_LOW',
            'component': 'config', 'cls': 'FluidFilter', 'method': 'check_fluid_filter',
            'message': f'HE fluid {fluid_he}: Tc unknown',
            'severity': 'error',
            'values': {'fluid': fluid_he, 'Tc': None, 'threshold': threshold_he},
        })
    elif tc_he <= threshold_he:
        issues.append({
            'code': 'FLUID_FILTER_TC_MARGIN_LOW',
            'component': 'config', 'cls': 'FluidFilter', 'method': 'check_fluid_filter',
            'message': f'HE fluid {fluid_he}: Tc={tc_he}°C <= T_cs+20={threshold_he}°C',
            'severity': 'error',
            'values': {'fluid': fluid_he, 'Tc': tc_he, 'threshold': threshold_he},
        })

    passed = len(issues) == 0
    primary_code = issues[0]['code'] if issues else None

    return {
        'passed': passed,
        'primary_code': primary_code,
        'n_issues': len(issues),
        'issues': issues,
    }


# ── Quick test ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    config = load_config()
    wp = config['working_points']['DC-A']
    fc = config.get('fluid_candidates')

    # M01: R600a should fail
    result = check_fluid_filter(wp, 'R600a', 'R1234ze(E)', fc)
    print(f"M01 R600a: passed={result['passed']}, primary={result['primary_code']}")
    for i in result['issues']:
        print(f"  {i['message']}")

    # Valid pair should pass
    result2 = check_fluid_filter(wp, 'R1233zd(E)', 'R1234ze(E)', fc)
    print(f"\nValid pair: passed={result2['passed']}, primary={result2['primary_code']}")

    # Verify consistency with get_fluid_combos
    sys.path.insert(0, SCRIPT_DIR)
    from run_optimization import get_fluid_combos
    combos = get_fluid_combos(wp, fc)
    print(f"\nget_fluid_combos DC-A: {len(combos)} combos")
    # Verify R600a not in combos
    r600a_combos = [c for c in combos if c[0] == 'R600a']
    print(f"R600a combos: {len(r600a_combos)} (expected 0)")
