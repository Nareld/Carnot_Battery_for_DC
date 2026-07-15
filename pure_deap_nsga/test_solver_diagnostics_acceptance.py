#!/usr/bin/env python3
"""
Solver Diagnostics Acceptance Test Suite v0.2

Reads solver_diagnostics_acceptance_dataset_v0.1.csv and executes each case.
Validates:
  - Feasible controls: feasible=True, 0 error issues, KPI match
  - Infeasible controls: penalty, primary_code NOT a wrapper when cause exists
  - Metadata M01: fluid filter diagnostic

Output: reports/solver_diagnostics_acceptance_observed_v0.2.csv
"""

import csv
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings('ignore')

# ── Paths ───────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SRC_DIR = SCRIPT_DIR.parent / 'src'
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from deap_optimizer import CBEvaluator, INFEASIBLE_PENALTY
from _module_diagnostics import WRAPPER_CODES, PRECHECK_CODES

DATA_DIR = SCRIPT_DIR / 'reports'
DATASET_PATH = DATA_DIR / 'solver_diagnostics_acceptance_dataset_v0.1.csv'
OUTPUT_PATH = DATA_DIR / 'solver_diagnostics_acceptance_observed_v0.2.csv'

# Wrapper codes that should NOT be primary when cause codes exist
WRAPPER_NAMES = {'EVALUATE_CYCLE_EXCEPTION', 'UNKNOWN_EXCEPTION',
                 'CB_SOLVER_ERROR', 'CB_CHILD_HP_ERROR', 'CB_CHILD_HE_ERROR'}


def load_config():
    with open(SCRIPT_DIR / 'optimization_config.json') as f:
        return json.load(f)


def run_cbevaluator_case(row, config):
    """Execute a CBEvaluator test case from the dataset row."""
    wp_name = row['wp']
    wp = config['working_points'][wp_name]
    cfg = dict(config['optimization'])
    cfg['diagnostics_enabled'] = True  # Always enable for acceptance testing

    cb_class_name = row['cb_class']

    # Parse expected issue codes
    raw_expected = row.get('expected_issue_code_contains', '')
    expected_codes = [c.strip() for c in raw_expected.split(';') if c.strip()]

    evaluator = CBEvaluator(
        wp=wp, cfg=cfg, cb_class_name=cb_class_name,
        fluid_hp=row['fluid_hp'], fluid_he=row['fluid_he'],
        objectives=['eta_p2p', 'energy_density_thermal', 'exergy_efficiency'],
    )

    x = [float(row[k]) for k in ['T_st_ht', 'dT_st_sp', 'dT_hp_cs_gl',
          'dT_hp_ev_sh', 'dT_he_ev_sh', 'dT_hp_cd_sc',
          'eta_max_cp', 'eta_max_ex', 'eta_pm']]

    result = evaluator.evaluate(x)
    info = evaluator.last_eval_info

    observed = {
        'case_id': row['case_id'],
        'observed_feasible': info.get('feasible', False),
        'observed_penalized': info.get('penalized', True),
        'observed_primary_code': info.get('primary_code', ''),
        'observed_n_error_issues': sum(1 for i in info.get('issues', [])
                                        if i.get('severity') == 'error'),
        'observed_n_warning_issues': sum(1 for i in info.get('issues', [])
                                          if i.get('severity') == 'warning'),
        'observed_error_codes': ';'.join(sorted(set(
            i['code'] for i in info.get('issues', [])
            if i.get('severity') == 'error'))),
        'observed_warning_codes': ';'.join(sorted(set(
            i['code'] for i in info.get('issues', [])
            if i.get('severity') == 'warning')))[:200],
    }

    # Determine root cause: first non-wrapper error code
    error_codes = [i['code'] for i in info.get('issues', [])
                   if i.get('severity') == 'error']
    root_cause = None
    for code in error_codes:
        if code not in WRAPPER_NAMES:
            root_cause = code
            break
    observed['observed_root_cause_code'] = root_cause or ''

    # Strict pass/fail logic
    expected_feasible = row['expected_feasible'].strip().lower() == 'true'
    passes = True

    if expected_feasible:
        # Feasible case checks
        if not info.get('feasible'):
            passes = False
        if observed['observed_n_error_issues'] > 0:
            passes = False
        # KPI check
        if info.get('feasible') and row.get('source_eta_p2p'):
            expected_p2p = float(row['source_eta_p2p'])
            observed_p2p = result[0] if result[0] > INFEASIBLE_PENALTY / 2 else None
            if observed_p2p is not None:
                if abs(observed_p2p - expected_p2p) > 1e-6:
                    passes = False
    else:
        # Infeasible case checks
        if not info.get('penalized'):
            passes = False
        if observed['observed_n_error_issues'] == 0:
            passes = False
        # primary_code must not be a wrapper if any cause code exists
        primary = observed['observed_primary_code']
        if primary in WRAPPER_NAMES and root_cause:
            passes = False
        # Check expected codes present
        found_codes = set(i['code'] for i in info.get('issues', []))
        if expected_codes:
            has_expected = any(ec in found_codes for ec in expected_codes)
            if not has_expected:
                passes = False

    observed['observed_status'] = 'PASS' if passes else 'FAIL'
    observed['observed_pass_strict_expectation'] = passes

    return observed, result


def run_fluid_filter_case(row, config):
    """Execute M01 fluid filter diagnostic."""
    from fluid_filter_diagnostics import check_fluid_filter

    wp_name = row['wp']
    wp = config['working_points'][wp_name]
    result = check_fluid_filter(wp, row['fluid_hp'], row['fluid_he'])

    observed = {
        'case_id': row['case_id'],
        'observed_feasible': False,
        'observed_penalized': True,
        'observed_primary_code': result['primary_code'] or '',
        'observed_n_error_issues': result['n_issues'],
        'observed_n_warning_issues': 0,
        'observed_error_codes': ';'.join(i['code'] for i in result['issues']),
        'observed_warning_codes': '',
        'observed_root_cause_code': result['primary_code'] or '',
    }

    expected_primary = row.get('expected_primary_code_set', '').split(';')[0].strip()
    passes = (result['primary_code'] == expected_primary)
    observed['observed_status'] = 'PASS' if passes else 'FAIL'
    observed['observed_pass_strict_expectation'] = passes

    return observed


def main():
    print("=" * 65)
    print("  Solver Diagnostics Acceptance Test Suite v0.2")
    print("=" * 65)

    config = load_config()

    # Read dataset
    with open(DATASET_PATH, newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"\n  Dataset: {len(rows)} cases loaded from {DATASET_PATH.name}")

    results = []
    n_pass = 0
    n_fail = 0

    for row in rows:
        case_id = row['case_id']
        executable = row.get('executable_by_cbevaluator', 'True').strip().lower() == 'true'

        print(f"\n  [{case_id}] ", end='')

        try:
            if executable:
                observed, cb_result = run_cbevaluator_case(row, config)
            else:
                observed = run_fluid_filter_case(row, config)

            results.append(observed)
            status = observed['observed_status']
            if status == 'PASS':
                n_pass += 1
                print(f"✅ {status}")
            else:
                n_fail += 1
                print(f"❌ {status}")
            print(f"    feasible={observed['observed_feasible']}, "
                  f"primary={observed['observed_primary_code']}, "
                  f"n_errors={observed['observed_n_error_issues']}, "
                  f"root_cause={observed['observed_root_cause_code']}")

        except Exception as e:
            print(f"❌ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'case_id': case_id,
                'observed_status': 'EXCEPTION',
                'observed_feasible': False,
                'observed_primary_code': '',
                'observed_root_cause_code': '',
                'observed_n_error_issues': 0,
                'observed_n_warning_issues': 0,
                'observed_error_codes': '',
                'observed_warning_codes': '',
                'observed_pass_strict_expectation': False,
            })
            n_fail += 1

    # Write output CSV
    fieldnames = ['case_id', 'observed_status', 'observed_feasible',
                  'observed_primary_code', 'observed_root_cause_code',
                  'observed_n_error_issues', 'observed_error_codes',
                  'observed_warning_count', 'observed_pass_strict_expectation']

    with open(OUTPUT_PATH, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for r in results:
            r_out = dict(r)
            r_out['observed_warning_count'] = r_out.get('observed_n_warning_issues', 0)
            writer.writerow(r_out)

    print(f"\n{'=' * 65}")
    print(f"  ACCEPTANCE SUMMARY: {n_pass}/{len(rows)} passed")
    print(f"  Output: {OUTPUT_PATH}")
    print(f"{'=' * 65}")

    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
