#!/usr/bin/env python3
"""
Pareto 结果完整性与合法性审查 v0.1

检查所有 Pareto CSV 文件：
  1. 文件覆盖：按 WP×构型×工质对统计
  2. 行数：空文件、异常短文件
  3. 列完整性：9 设计变量 + 3 目标 + 5 元数据列
  4. 数值合法性：NaN/Inf/负密度/eta异常
  5. Penalty 混入
  6. 重复行/常数列
  7. 全局前沿输入可用性

运行方式：
  cd pure_deap_nsga
  ../.venv/bin/python audit_pareto_results.py
"""

import os
import sys
import json
import glob
import warnings
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

warnings.filterwarnings('ignore')

# ── Path setup ──────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPT_DIR / 'results'
REPORTS_DIR = SCRIPT_DIR / 'reports'
REPORTS_DIR.mkdir(exist_ok=True)

# ── Expected structure ───────────────────────────────────────────────────
DESIGN_VARS = ['T_st_ht', 'dT_st_sp', 'dT_hp_cs_gl', 'dT_hp_ev_sh',
               'dT_he_ev_sh', 'dT_hp_cd_sc', 'eta_max_cp', 'eta_max_ex', 'eta_pm']
OBJECTIVES = ['eta_p2p', 'energy_density_thermal', 'exergy_efficiency']
META_COLS = ['wp', 'cb_config', 'fluid_hp', 'fluid_he', 'label']
ALL_EXPECTED_COLS = DESIGN_VARS + OBJECTIVES + META_COLS

# ── Theory: expected combinations ────────────────────────────────────────
WPS = ['DC-A', 'DC-B', 'DC-C', 'DC-D', 'DC-E', 'DC-F']
CONFIGS = ['SBVCHP_SBORC', 'SBVCHP_SRORC', 'SRVCHP_SBORC', 'SRVCHP_SRORC']


def load_config():
    """Load optimization config for valid fluid pairings."""
    config_path = SCRIPT_DIR / 'optimization_config.json'
    with open(config_path) as f:
        return json.load(f)


def get_valid_combos(config):
    """Replicate fluid filtering logic from run_optimization.py."""
    sys.path.insert(0, str(SCRIPT_DIR))
    from run_optimization import get_fluid_combos
    combos_by_wp = {}
    for wp_name in WPS:
        wp = config['working_points'][wp_name]
        combos = get_fluid_combos(wp, config['fluid_candidates'])
        combos_by_wp[wp_name] = combos
    return combos_by_wp


def scan_files():
    """Scan all pareto CSV files and return structured info."""
    files = sorted(glob.glob(str(RESULTS_DIR / 'pareto_*.csv')))
    return files


def classify_files(files):
    """Parse filename into wp, config, hp_fluid, he_fluid."""
    parsed = []
    for fpath in files:
        fname = os.path.basename(fpath).replace('.csv', '')
        # Format: pareto_{WP}_{CFG}_{HP}_{HE}.csv
        parts = fname.split('_')
        if len(parts) < 5:
            parsed.append({'path': fpath, 'parse_error': True, 'wp': 'unknown'})
            continue
        wp = parts[1]
        # Config can be two parts: SBVCHP_SBORC or SRVCHP_SRORC etc
        cfg = None
        for i in range(2, len(parts)):
            candidate = '_'.join(parts[i:i+2])
            if candidate in CONFIGS:
                cfg = candidate
                hp_idx = i + 2
                break
            # Single-part config won't happen; all are two-part
        if cfg is None:
            parsed.append({'path': fpath, 'parse_error': True, 'wp': wp})
            continue

        # Remaining parts: hp_fluid and he_fluid
        remaining = parts[hp_idx:]
        # Heuristic: HP and HE fluids are the last two "segments"
        # Usually: R1233zd(E) + R1234ze(E) -> the split is by the last _R
        # Better: reconstruct the full remainder and split by known fluid patterns
        remainder_str = '_'.join(remaining)
        # Try known fluid patterns
        hp_fluid = he_fluid = None
        for hp_candidate in ['R1233zd(E)', 'R245fa', 'R600a', 'R600']:
            if remainder_str.startswith(hp_candidate):
                hp_fluid = hp_candidate
                he_fluid = remainder_str[len(hp_candidate)+1:]  # +1 for _
                break
        if hp_fluid is None:
            parsed.append({'path': fpath, 'parse_error': True, 'wp': wp, 'cfg': cfg})
            continue

        parsed.append({
            'path': fpath,
            'wp': wp, 'cfg': cfg,
            'hp_fluid': hp_fluid, 'he_fluid': he_fluid,
            'fname': fname,
        })
    return parsed


def audit_single_file(parsed_info):
    """Audit a single Pareto CSV and return dict of findings."""
    fpath = parsed_info['path']
    result = dict(parsed_info)
    result['exists'] = True
    result['error'] = None

    try:
        df = pd.read_csv(fpath)
    except Exception as e:
        result['error'] = f'read_failed: {e}'
        return result

    result['n_rows'] = len(df)
    result['n_cols'] = len(df.columns)
    result['columns'] = list(df.columns)

    # Column check
    missing_cols = [c for c in ALL_EXPECTED_COLS if c not in df.columns]
    extra_cols = [c for c in df.columns if c not in ALL_EXPECTED_COLS]
    result['missing_cols'] = missing_cols
    result['extra_cols'] = extra_cols

    if missing_cols:
        result['error'] = f'missing columns: {missing_cols}'
        return result

    # Numerical checks on objectives
    obj_df = df[OBJECTIVES]
    has_nan = obj_df.isna().any().any()
    has_inf = np.isinf(obj_df.values).any()
    result['has_nan'] = bool(has_nan)
    result['has_inf'] = bool(has_inf)

    # Range checks
    eta_p2p = df['eta_p2p']
    e_th = df['energy_density_thermal']
    eta_ex = df['exergy_efficiency']

    result['eta_p2p_min'] = float(eta_p2p.min())
    result['eta_p2p_max'] = float(eta_p2p.max())
    result['eta_p2p_negative'] = int((eta_p2p <= 0).sum())
    result['eta_p2p_over_one'] = int((eta_p2p >= 1).sum())
    result['e_th_negative'] = int((e_th < 0).sum())
    result['eta_ex_negative'] = int((eta_ex < 0).sum())
    result['eta_ex_over_one'] = int((eta_ex > 1.1).sum())  # 10% tolerance for numerical noise

    # Penalty check
    penalty_threshold = -5e5
    result['n_penalty'] = int(((eta_p2p < penalty_threshold) | (e_th < penalty_threshold) | (eta_ex < penalty_threshold)).sum())

    # NaN/Inf total
    result['n_nan'] = int(obj_df.isna().sum().sum())
    result['n_inf'] = int(np.isinf(obj_df.values).sum())

    # Duplicate rows
    result['n_duplicates'] = int(df[DESIGN_VARS + OBJECTIVES].duplicated().sum())
    result['n_total_dupes'] = int(df.duplicated().sum())

    # Constant objectives
    result['eta_p2p_constant'] = (eta_p2p.nunique() <= 1)
    result['e_th_constant'] = (e_th.nunique() <= 1)
    result['eta_ex_constant'] = (eta_ex.nunique() <= 1)

    # Label consistency
    if 'wp' in df.columns:
        wp_match = (df['wp'] == result['wp']).all()
        result['wp_label_consistent'] = bool(wp_match)

    return result


def analyze_completeness(audit_results, valid_combos):
    """Analyze coverage gaps."""
    # Expected: each WP × (valid fluid combos) × config
    expected = defaultdict(list)
    for wp in WPS:
        for hp_f, he_f in valid_combos.get(wp, []):
            for cfg in CONFIGS:
                expected[wp].append((cfg, hp_f, he_f))

    observed = defaultdict(set)
    for r in audit_results:
        if not r.get('error') or r['error'] is None:
            observed[r['wp']].add((r['cfg'], r['hp_fluid'], r['he_fluid']))
        else:
            observed[r['wp']].add(('ERROR', 'ERROR', 'ERROR'))

    # Calculate gaps
    gaps = {}
    for wp in WPS:
        exp_set = set(expected[wp])
        obs_set = observed[wp]
        missing = exp_set - obs_set
        gaps[wp] = {
            'expected': len(exp_set),
            'observed': len([x for x in obs_set if x[0] != 'ERROR']),
            'missing': sorted(missing),
            'n_missing': len(missing),
        }
    return gaps, expected


def main():
    print("=" * 70)
    print("  Pareto Results Audit Tool v0.1")
    print("=" * 70)

    # Load config
    print("\n[1/4] Loading configuration...")
    config = load_config()
    valid_combos = get_valid_combos(config)
    total_theoretical = sum(len(v) * len(CONFIGS) for v in valid_combos.values())
    print(f"  Theoretical maximum combos: {total_theoretical}")

    # Scan files
    print("\n[2/4] Scanning Pareto CSV files...")
    files = scan_files()
    print(f"  Found {len(files)} pareto_*.csv files")
    parsed = classify_files(files)

    # Audit each file
    print("\n[3/4] Auditing each file...")
    audit_results = []
    parse_errors = 0
    for p in parsed:
        if p.get('parse_error'):
            parse_errors += 1
            audit_results.append(p)
        else:
            r = audit_single_file(p)
            audit_results.append(r)

    n_ok = sum(1 for r in audit_results if r.get('exists') and not r.get('error'))
    n_error = sum(1 for r in audit_results if r.get('error'))
    print(f"  Audited: {n_ok} OK, {n_error} errors, {parse_errors} parse errors")

    # Completeness analysis
    print("\n[4/4] Analyzing coverage gaps...")
    gaps, expected = analyze_completeness(audit_results, valid_combos)

    # ── Generate Summary CSV ────────────────────────────────────────────
    print("\nWriting audit summary CSV...")
    csv_rows = []
    for r in audit_results:
        row = {
            'wp': r.get('wp', 'unknown'),
            'cb_config': r.get('cfg', 'unknown'),
            'fluid_hp': r.get('hp_fluid', 'unknown'),
            'fluid_he': r.get('he_fluid', 'unknown'),
            'n_rows': r.get('n_rows', 0),
            'n_cols': r.get('n_cols', 0),
            'has_error': bool(r.get('error')),
            'error_msg': str(r.get('error', ''))[:120],
            'has_nan': r.get('has_nan', False),
            'has_inf': r.get('has_inf', False),
            'eta_p2p_min': r.get('eta_p2p_min', None),
            'eta_p2p_max': r.get('eta_p2p_max', None),
            'eta_p2p_negative': r.get('eta_p2p_negative', 0),
            'eta_p2p_over_one': r.get('eta_p2p_over_one', 0),
            'e_th_negative': r.get('e_th_negative', 0),
            'n_penalty': r.get('n_penalty', 0),
            'n_duplicates': r.get('n_duplicates', 0),
            'n_nan': r.get('n_nan', 0),
            'n_inf': r.get('n_inf', 0),
        }
        csv_rows.append(row)

    df_summary = pd.DataFrame(csv_rows)
    csv_path = REPORTS_DIR / 'pareto_audit_summary.csv'
    df_summary.to_csv(csv_path, index=False)
    print(f"  Saved: {csv_path}")

    # ── Generate Audit Report ───────────────────────────────────────────
    print("\nWriting audit report...")
    report_lines = []
    report_lines.append("# Pareto Results Audit Report v0.1")
    report_lines.append(f"\n**Audit date:** 2026-06-25")
    report_lines.append(f"**Total Pareto CSV files:** {len(files)}")
    report_lines.append(f"**Theoretical max combinations:** {total_theoretical}")
    report_lines.append("")

    # Overall stats
    total_rows = sum(r.get('n_rows', 0) for r in audit_results if not r.get('error'))
    report_lines.append(f"## 1. Overall Statistics")
    report_lines.append(f"- Files OK: {n_ok}")
    report_lines.append(f"- Files with errors: {n_error}")
    report_lines.append(f"- Parse errors: {parse_errors}")
    report_lines.append(f"- Total rows across all files: {total_rows}")
    report_lines.append("")

    # Gap analysis
    report_lines.append(f"## 2. Coverage Gap Analysis")
    report_lines.append(f"| WP | Expected | Observed | Missing |")
    report_lines.append(f"|-----|----------|----------|---------|")
    total_missing = 0
    for wp in WPS:
        g = gaps[wp]
        total_missing += g['n_missing']
        report_lines.append(f"| {wp} | {g['expected']} | {g['observed']} | {g['n_missing']} |")
    report_lines.append(f"| **Total** | **{total_theoretical}** | **{n_ok}** | **{total_missing}** |")
    report_lines.append("")

    # Per-WP gap details
    for wp in WPS:
        g = gaps[wp]
        if g['n_missing'] > 0:
            report_lines.append(f"### Missing in {wp} ({g['n_missing']})")
            for cfg, hp_f, he_f in g['missing'][:10]:
                report_lines.append(f"- `{cfg}` / `{hp_f}` / `{he_f}`")
            if g['n_missing'] > 10:
                report_lines.append(f"- ... and {g['n_missing'] - 10} more")
            report_lines.append("")

    # Numerical anomaly detection
    report_lines.append(f"## 3. Numerical Anomaly Detection")

    eta_over_one_files = [r for r in audit_results if r.get('eta_p2p_over_one', 0) > 0]
    neg_density_files = [r for r in audit_results if r.get('e_th_negative', 0) > 0]
    nan_files = [r for r in audit_results if r.get('has_nan')]
    inf_files = [r for r in audit_results if r.get('has_inf')]
    penalty_files = [r for r in audit_results if r.get('n_penalty', 0) > 0]
    dup_files = [r for r in audit_results if r.get('n_duplicates', 0) > 0]

    report_lines.append(f"- eta_p2p >= 1: {len(eta_over_one_files)} files **⚠️ BLOCKER**")
    for r in eta_over_one_files:
        report_lines.append(f"  - {r.get('fname', '?')}: max={r.get('eta_p2p_max')}")
    report_lines.append(f"- Negative energy_density_thermal: {len(neg_density_files)} files **⚠️ BLOCKER**")
    for r in neg_density_files:
        report_lines.append(f"  - {r.get('fname', '?')}: n_neg={r['e_th_negative']}")
    report_lines.append(f"- NaN values: {len(nan_files)} files")
    report_lines.append(f"- Inf values: {len(inf_files)} files")
    report_lines.append(f"- Penalty contamination: {len(penalty_files)} files")
    report_lines.append(f"- Duplicate rows: {len(dup_files)} files")
    report_lines.append("")

    # DC-E specific check
    report_lines.append(f"## 4. DC-E High-Efficiency Boundary Check")
    dc_e_files = [r for r in audit_results if r.get('wp') == 'DC-E' and not r.get('error')]
    if dc_e_files:
        dce_max_eta = max(r.get('eta_p2p_max', 0) for r in dc_e_files)
        report_lines.append(f"- {len(dc_e_files)} DC-E files analyzed")
        report_lines.append(f"- Max eta_p2p across DC-E: {dce_max_eta:.4f} ({dce_max_eta*100:.2f}%)")
        if dce_max_eta > 0.5:
            report_lines.append(f"- ⚠️ DC-E efficiency > 50% — verify against expected physical limits")
    report_lines.append("")

    # Per-WP summary
    report_lines.append(f"## 5. Per-WP Summary")
    report_lines.append(f"| WP | Files OK | Anomalies | Mean eta_p2p_max | Mean rows |")
    report_lines.append(f"|-----|----------|-----------|------------------|-----------|")
    for wp in WPS:
        wp_files = [r for r in audit_results if r.get('wp') == wp and not r.get('error')]
        wp_anomalies = [r for r in audit_results if r.get('wp') == wp and r.get('error')]
        mean_max_eta = np.mean([r.get('eta_p2p_max', 0) for r in wp_files]) if wp_files else 0
        mean_rows = np.mean([r.get('n_rows', 0) for r in wp_files]) if wp_files else 0
        report_lines.append(f"| {wp} | {len(wp_files)} | {len(wp_anomalies)} | {mean_max_eta:.4f} | {mean_rows:.0f} |")
    report_lines.append("")

    # Verdict for Part I
    report_lines.append(f"## 6. Verdict: Ready for Part I / W3?")
    has_blockers = len(eta_over_one_files) > 0 or len(neg_density_files) > 0
    if has_blockers:
        report_lines.append(f"- **BLOCKED**: Found {len(eta_over_one_files)} files with eta_p2p>=1 or {len(neg_density_files)} files with negative density.")
        report_lines.append(f"- Fix root causes before using data for Part I.")
    elif total_missing > 50:
        report_lines.append(f"- **CAUTION**: Coverage gap of {total_missing} missing files. Part I analysis may be incomplete for some WPs.")
        report_lines.append(f"- Recommend documenting missing combos in paper supplementary.")
    else:
        report_lines.append(f"- **PASS**: {n_ok}/{total_theoretical} files OK, {total_missing} missing.")
        report_lines.append(f"- Data quality sufficient for Part I analysis with appropriate caveats on missing combos.")

    report_path = REPORTS_DIR / 'pareto_audit_report.md'
    with open(report_path, 'w') as f:
        f.write('\n'.join(report_lines))
    print(f"  Saved: {report_path}")

    # ── Console Summary ──────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  AUDIT COMPLETE")
    print(f"{'='*70}")
    print(f"  Files: {n_ok} OK / {n_error} errors / {parse_errors} parse errors")
    print(f"  Coverage gap: {total_missing}/{total_theoretical} missing")
    print(f"  eta_p2p >= 1: {len(eta_over_one_files)} files")
    print(f"  Negative density: {len(neg_density_files)} files")
    print(f"  NaN: {len(nan_files)} files")
    print(f"  NaN total cells: {sum(r.get('n_nan', 0) for r in audit_results)}")
    print(f"  Penalty contamination: {len(penalty_files)} files")
    print(f"  Duplicates: {len(dup_files)} files")
    print(f"  BLOCKED: {has_blockers}")
    print()

    return 0


if __name__ == '__main__':
    main()
