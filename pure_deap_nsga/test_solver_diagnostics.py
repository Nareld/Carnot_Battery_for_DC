#!/usr/bin/env python3
"""
Solver Diagnostics Test Suite v0.1

Validates:
  1. SolverDiagnostic/SolverIssue dataclass serialization
  2. Optimizer pre-check diagnostics
  3. Feasible case → empty or warning-only diagnostics
  4. Known-infeasible case → non-empty diagnostics with codes
  5. CBEvaluator.evaluate() API unchanged (returns tuple)
"""

import json
import os
import sys
import warnings
from typing import Dict, List

import numpy as np
import pandas as pd

# ── Path setup ──────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(SCRIPT_DIR, '..', 'src')
sys.path.insert(0, SRC_DIR)
sys.path.insert(0, SCRIPT_DIR)

from _module_diagnostics import SolverIssue, SolverDiagnostic, DiagnosticMixin
from deap_optimizer import CBEvaluator, INFEASIBLE_PENALTY

def load_config():
    """Load optimization config (defined here to avoid circular imports)."""
    import json
    config_path = os.path.join(SCRIPT_DIR, 'optimization_config.json')
    with open(config_path) as f:
        return json.load(f)

warnings.filterwarnings('ignore')


def test_diagnostic_dataclass_serialization():
    """Test 1: SolverIssue and SolverDiagnostic serialization."""
    print("=" * 65)
    print("TEST 1: Diagnostic dataclass serialization")
    print("=" * 65)

    # Single issue
    issue = SolverIssue(
        code='HX_PINCH_HP_EVAP', component='HP', cls='SBVCHP',
        method='check_consistency', message='evaporator pinch violated',
        severity='error', values={'T_hp_4': 310.0, 'T_hp_cs_ex': 305.0, 'min_pinch': 5.0},
    )
    d = issue.to_dict()
    assert isinstance(d, dict), 'to_dict() must return dict'
    assert d['code'] == 'HX_PINCH_HP_EVAP'

    # JSON serializable
    json_str = json.dumps(d, default=str)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed['code'] == 'HX_PINCH_HP_EVAP'
    print('  ✓ SolverIssue serialization OK')

    # Diagnostic aggregation
    diag = SolverDiagnostic()
    assert diag.ok is True
    assert diag.primary_code is None

    diag.add(issue)
    assert diag.ok is False
    assert diag.primary_code == 'HX_PINCH_HP_EVAP'
    assert len(diag.issues) == 1

    # Second issue
    issue2 = SolverIssue(
        code='EFFICIENCY_NEGATIVE', component='HP', cls='SBVCHP',
        method='check_consistency', message='negative efficiency',
        severity='error', values={'eta': -0.1},
    )
    diag.add(issue2)
    assert diag.primary_code == 'HX_PINCH_HP_EVAP', 'primary_code must be FIRST issue'
    assert len(diag.issues) == 2

    d2 = diag.to_dict()
    assert d2['ok'] is False
    assert d2['n_issues'] == 2
    json_str2 = json.dumps(d2, default=str)
    assert isinstance(json_str2, str)
    print('  ✓ SolverDiagnostic serialization OK (2 issues)')
    print('PASSED\n')


def test_optimizer_precheck_diagnostic():
    """Test 2: Pre-check diagnostic when T_st_ht is too low."""
    print("=" * 65)
    print("TEST 2: Optimizer pre-check diagnostic")
    print("=" * 65)

    config = load_config()
    wp = config['working_points']['DC-A']
    cfg = config['optimization']
    cfg['diagnostics_enabled'] = True

    evaluator = CBEvaluator(
        wp=wp, cfg=cfg, cb_class_name='SBVCHP_SBORC_STES2T',
        fluid_hp='R1233zd(E)', fluid_he='R1234ze(E)',
        objectives=['eta_p2p', 'energy_density_thermal', 'exergy_efficiency'],
    )

    # T_st_ht = 30°C, T_hp_cs = 35°C → 30 <= 35+5=40 → pre-check fails
    x_infeasible = [30.0, 30.0, 10.0, 5.0, 1.5, 5.0, 0.80, 0.80, 0.50]
    result = evaluator.evaluate(x_infeasible)

    # Must return all penalty
    assert isinstance(result, tuple), f'Expected tuple, got {type(result)}'
    assert all(v == INFEASIBLE_PENALTY for v in result), 'All should be INFEASIBLE_PENALTY'
    print('  ✓ Returns all INFEASIBLE_PENALTY')

    # Must record diagnostic
    info = evaluator.last_eval_info
    assert info['feasible'] is False
    assert info['penalized'] is True
    assert info['primary_code'] == 'OPT_PRECHECK_STORAGE_TEMP_TOO_LOW', \
        f"Expected OPT_PRECHECK_STORAGE_TEMP_TOO_LOW, got {info['primary_code']}"
    assert len(info['issues']) >= 1
    assert info['issues'][0]['code'] == 'OPT_PRECHECK_STORAGE_TEMP_TOO_LOW'
    print(f'  ✓ primary_code = {info["primary_code"]}')
    print(f'  ✓ {len(info["issues"])} issue(s) recorded')

    # Diagnostics records
    assert len(evaluator.diagnostics_records) == 1
    print('  ✓ diagnostics_records populated')
    print('PASSED\n')


def test_feasible_case_has_empty_or_warning_diagnostics():
    """Test 3: Feasible DC-A point → feasible, no error issues."""
    print("=" * 65)
    print("TEST 3: Feasible case → no error diagnostics")
    print("=" * 65)

    config = load_config()
    wp = config['working_points']['DC-A']
    # Use same cfg construction as test_optimizer.py for exact value comparison
    cfg = {
        'dT_hp_ev_pp': 5.0, 'dT_hp_cd_pp': 3.0, 'dT_he_ev_pp': 3.0, 'dT_he_cd_pp': 5.0,
        'dT_he_cd_sc': 3.0, 'dT_he_cs_gl': 10.0, 'epsilon_hp': 0.8, 'epsilon_he': 0.8,
        'p_st_ht': 2.5e5, 'p_st_lt': 2.5e5, 'diagnostics_enabled': True,
    }

    evaluator = CBEvaluator(
        wp=wp, cfg=cfg, cb_class_name='SBVCHP_SBORC_STES2T',
        fluid_hp='R1233zd(E)', fluid_he='R1234ze(E)',
        objectives=['eta_p2p', 'energy_density_thermal', 'exergy_efficiency'],
    )

    # Known feasible from test_optimizer.py
    x_feasible = [80.0, 30.0, 10.0, 5.0, 1.5, 5.0, 0.80, 0.80, 0.50]
    result = evaluator.evaluate(x_feasible)

    assert isinstance(result, tuple)
    assert result[0] > INFEASIBLE_PENALTY / 2, 'First objective should be feasible'
    assert 0 < result[0] < 1.0, f'eta_p2p must be in (0,1), got {result[0]}'
    print(f'  ✓ eta_p2p = {result[0]:.6f} (feasible, in valid range)')

    info = evaluator.last_eval_info
    assert info['feasible'] is True
    assert info['penalized'] is False
    error_issues = [i for i in info['issues'] if i['severity'] == 'error']
    assert len(error_issues) == 0, f'No error issues expected, got {len(error_issues)}'
    print(f'  ✓ feasible=True, penalized=False')
    print(f'  ✓ error issues: {len(error_issues)}')

    if len(info['issues']) > 0:
        codes = [i['code'] for i in info['issues']]
        print(f'  ℹ warning-level issues: {codes}')
    print('PASSED\n')


def test_known_infeasible_has_nonempty_diagnostics():
    """Test 4: Known-infeasible point → penalty + non-empty diagnostics."""
    print("=" * 65)
    print("TEST 4: Known-infeasible → non-empty diagnostics")
    print("=" * 65)

    config = load_config()
    wp = config['working_points']['DC-A']
    cfg = config['optimization']
    cfg['diagnostics_enabled'] = True

    evaluator = CBEvaluator(
        wp=wp, cfg=cfg, cb_class_name='SBVCHP_SBORC_STES2T',
        fluid_hp='R1233zd(E)', fluid_he='R1234ze(E)',
        objectives=['eta_p2p', 'energy_density_thermal', 'exergy_efficiency'],
    )

    # Infeasible: T_st_ht=150 exceeds the max, and with high T_hs=35 → ORC struggles
    x_bad = [150.0, 80.0, 0.0, 3.0, 0.5, 0.0, 0.70, 0.70, 0.45]
    result = evaluator.evaluate(x_bad)

    assert isinstance(result, tuple)
    assert all(v == INFEASIBLE_PENALTY for v in result), 'All should be penalty'
    print('  ✓ Returns all INFEASIBLE_PENALTY')

    info = evaluator.last_eval_info
    assert info['penalized'] is True
    assert info['primary_code'] is not None, 'Must have a primary_code'
    assert len(info['issues']) > 0, 'Must have at least one issue'
    print(f'  ✓ primary_code = {info["primary_code"]}')
    print(f'  ✓ {len(info["issues"])} issue(s) recorded')

    # Check issue structure
    for issue in info['issues']:
        for key in ['code', 'component', 'cls', 'method', 'message']:
            assert key in issue, f'Issue missing key: {key}'
    print('  ✓ All issues have required fields (code/component/cls/method/message)')
    print('PASSED\n')


def test_existing_evaluate_api_unchanged():
    """Test 5: evaluate(x) still returns tuple of correct length."""
    print("=" * 65)
    print("TEST 5: evaluate() API unchanged")
    print("=" * 65)

    config = load_config()
    wp = config['working_points']['DC-A']
    cfg = dict(config['optimization'])
    cfg['diagnostics_enabled'] = False  # DEFAULT OFF

    for cb_class_name in ['SBVCHP_SBORC_STES2T', 'SRVCHP_SRORC_STES2T']:
        for fluid_hp, fluid_he in [('R1233zd(E)', 'R1234ze(E)'), ('R600', 'R227ea')]:
            evaluator = CBEvaluator(
                wp=wp, cfg=cfg, cb_class_name=cb_class_name,
                fluid_hp=fluid_hp, fluid_he=fluid_he,
                objectives=['eta_p2p', 'energy_density_thermal', 'exergy_efficiency'],
            )
            x = [80.0, 30.0, 10.0, 5.0, 1.5, 5.0, 0.80, 0.80, 0.50]
            result = evaluator.evaluate(x)
            assert isinstance(result, tuple), f'{cb_class_name}/{fluid_hp}: expected tuple, got {type(result)}'
            assert len(result) == 3, f'{cb_class_name}/{fluid_hp}: expected 3 objectives, got {len(result)}'
            # With diagnostics disabled, no records should accumulate
            assert len(evaluator.diagnostics_records) == 0, \
                f'{cb_class_name}/{fluid_hp}: diagnostics should not accumulate when disabled'
            print(f'  ✓ {cb_class_name} / {fluid_hp}+{fluid_he}: tuple(len={len(result)})')

    print('PASSED\n')


def test_diagnostics_csv_export():
    """Bonus: Export diagnostics records to CSV-like dict."""
    print("=" * 65)
    print("BONUS: Diagnostics CSV export")
    print("=" * 65)

    config = load_config()
    wp = config['working_points']['DC-A']
    cfg = config['optimization']
    cfg['diagnostics_enabled'] = True

    evaluator = CBEvaluator(
        wp=wp, cfg=cfg, cb_class_name='SRVCHP_SRORC_STES2T',
        fluid_hp='R600', fluid_he='R227ea',
        objectives=['eta_p2p', 'energy_density_thermal', 'exergy_efficiency'],
    )

    # Test a few points
    test_points = [
        ([80.0, 30.0, 10.0, 5.0, 1.5, 5.0, 0.80, 0.80, 0.50], 'mid-range'),
        ([120.0, 60.0, 0.0, 3.0, 0.5, 0.0, 0.90, 0.90, 0.55], 'boundary'),
        ([50.0, 15.0, 20.0, 15.0, 3.0, 15.0, 0.70, 0.70, 0.45], 'low-T'),
        ([140.0, 80.0, 5.0, 3.0, 0.5, 0.0, 0.90, 0.90, 0.55], 'extreme'),
    ]

    records = []
    for x, label in test_points:
        result = evaluator.evaluate(x)
        info = dict(evaluator.last_eval_info)
        info['label'] = label
        # Truncate for display
        info['issues_summary'] = [i['code'] for i in info['issues'][:3]]
        del info['issues']
        records.append(info)

    df = pd.DataFrame(records)
    print(f'  Collected {len(records)} diagnostic records')
    print(f'  Columns: {list(df.columns)}')
    print()
    for _, row in df.iterrows():
        codes = row['issues_summary']
        print(f'  {row["label"]:10s} | feasible={row["feasible"]} | '
              f'primary={row["primary_code"]} | issues={codes}')
    print('PASSED\n')


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 65)
    print("  Solver Diagnostics Test Suite v0.1")
    print("=" * 65)
    print()

    all_passed = True
    tests = [
        test_diagnostic_dataclass_serialization,
        test_optimizer_precheck_diagnostic,
        test_feasible_case_has_empty_or_warning_diagnostics,
        test_known_infeasible_has_nonempty_diagnostics,
        test_existing_evaluate_api_unchanged,
        test_diagnostics_csv_export,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            print(f'  ❌ FAILED: {e}')
            import traceback
            traceback.print_exc()
            all_passed = False

    print("=" * 65)
    if all_passed:
        print("  ALL TESTS COMPLETED SUCCESSFULLY")
    else:
        print("  SOME TESTS FAILED")
    print("=" * 65)
