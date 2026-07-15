#!/usr/bin/env python3
"""
Minimal Uncertainty / Robustness Smoke Test Tool v0.1

Supports two modes:
  OAT: One-at-a-time perturbation of key boundary/component parameters
  LHS: Latin Hypercube Sampling of boundary/component parameters

Reads near-optimal representative designs, perturbs boundary conditions and
component efficiencies, re-evaluates CBSim, and reports performance retention.

Usage:
  ../.venv/bin/python uncertainty_analysis.py --mode oat --wp DC-A --design D_bal
  ../.venv/bin/python uncertainty_analysis.py --mode lhs --wp DC-A --design D_bal --n-samples 30 --seed 42

Outputs:
  results/uncertainty_{mode}_{WP}_{design}.csv
  reports/uncertainty_smoke_report.md
"""

import argparse
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import CoolProp.CoolProp as CP

warnings.filterwarnings("ignore")

# ── Path setup ──────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SRC_DIR = SCRIPT_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

import _module_carnot_battery as CB

RESULTS_DIR = SCRIPT_DIR / "results"
REPORTS_DIR = SCRIPT_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

OBJ_NAMES = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]


# ═════════════════════════════════════════════════════════════════════════
# 0. Load config and designs
# ═════════════════════════════════════════════════════════════════════════

def load_config():
    """Load optimization config."""
    with open(SCRIPT_DIR / "optimization_config.json") as f:
        return json.load(f)


def load_design(wp, design_name):
    """Load a single representative design from near_optimal_{WP}_designs.csv."""
    path = RESULTS_DIR / f"near_optimal_{wp}_designs.csv"
    if not path.exists():
        raise FileNotFoundError(f"Design file not found: {path}")
    df = pd.read_csv(path)
    mask = df["design_name"] == design_name
    if not mask.any():
        available = list(df["design_name"].unique())
        raise ValueError(f"Design '{design_name}' not found in {wp}. Available: {available}")
    return df[mask].iloc[0].to_dict()


def load_wp_config(config, wp_name):
    """Return (wp_dict, opt_cfg_dict) for a working point."""
    return config["working_points"][wp_name], config["optimization"]


# ═════════════════════════════════════════════════════════════════════════
# 1. CBSim single-point evaluation (adapted from off_design_eval.py)
# ═════════════════════════════════════════════════════════════════════════

def build_cb_inputs(design_row, T_hs, T_cs, cfg):
    """Build CBSim inputs/params/options from a design row."""
    d = design_row
    T_hp_cs_su_K = T_hs + 273.15
    dT_gl = float(d.get("dT_hp_cs_gl", 0))
    T_hp_cs_ex_K = max(T_hp_cs_su_K - dT_gl, 275.15)
    p_hp_cs = 1e5

    T_he_cs_su_K = T_cs + 273.15
    T_he_cs_ex_K = T_he_cs_su_K + cfg["dT_he_cs_gl"]
    p_he_cs = 1e5

    i_hp_cs_su = CP.PropsSI("H", "T", T_hp_cs_su_K, "P", p_hp_cs, "H2O")
    i_hp_cs_ex = CP.PropsSI("H", "T", T_hp_cs_ex_K, "P", p_hp_cs, "H2O")
    i_he_cs_su = CP.PropsSI("H", "T", T_he_cs_su_K, "P", p_he_cs, "H2O")
    i_he_cs_ex = CP.PropsSI("H", "T", T_he_cs_ex_K, "P", p_he_cs, "H2O")

    inputs = (
        p_hp_cs, i_hp_cs_su, p_hp_cs, i_hp_cs_ex, 1.0, "H2O",
        p_he_cs, i_he_cs_su, p_he_cs, i_he_cs_ex, 1.0, "H2O",
        1e3, 1e3,
    )

    params = {
        "p_hp_cs_su": p_hp_cs, "i_hp_cs_su": i_hp_cs_su, "i_hp_cs_ex": i_hp_cs_ex,
        "p_he_cs_su": p_he_cs, "i_he_cs_su": i_he_cs_su, "i_he_cs_ex": i_he_cs_ex,
        "m_hp_cs": 1.0, "m_he_cs": 1.0,
        "p_st_ht": cfg["p_st_ht"], "p_st_lt": cfg["p_st_lt"],
        "T_st_ht": float(d["T_st_ht"]) + 273.15,
        "dT_st_sp": float(d["dT_st_sp"]),
        "eta_max_cp": float(d["eta_max_cp"]),
        "eta_max_ex": float(d["eta_max_ex"]),
        "eta_pm": float(d["eta_pm"]),
        "dT_hp_ev_pp": cfg["dT_hp_ev_pp"],
        "dT_hp_cd_pp": cfg["dT_hp_cd_pp"],
        "dT_he_ev_pp": cfg["dT_he_ev_pp"],
        "dT_he_cd_pp": cfg["dT_he_cd_pp"],
        "dT_hp_ev_sh": float(d["dT_hp_ev_sh"]),
        "dT_he_ev_sh": float(d["dT_he_ev_sh"]),
        "dT_he_cd_sc": cfg["dT_he_cd_sc"],
        "dT_hp_cd_sc": float(d["dT_hp_cd_sc"]),
        "dp_hp_ev": 0.0, "dp_hp_cd": 0.0,
        "dp_hp_rg_lq": 0.0, "dp_hp_rg_vp": 0.0,
        "epsilon_hp": cfg["epsilon_hp"],
        "dp_he_ev": 0.0, "dp_he_cd": 0.0,
        "dp_he_rg_lq": 0.0, "dp_he_rg_vp": 0.0,
        "epsilon_he": cfg["epsilon_he"],
        "m_hp_st_max": 0.0, "m_he_st_max": 0.0,
        "version": "thermodynamic_full",
        "mode_hp": True, "mode_he": True, "mode": "source",
        "p_ref": p_he_cs, "T_ref": T_he_cs_su_K,
        "p_0": p_he_cs, "T_0": T_he_cs_su_K,
        "fluid_hp": d.get("fluid_hp", "R1233zd(E)"),
        "fluid_he": d.get("fluid_he", "R1234ze(E)"),
        "fluid_st": cfg.get("fluid_st", "H2O"),
        "wet_ex": 0, "m_rat_hp": 0, "m_rat_he": 0,
    }
    options = {"plot_flag": False, "print_flag": False, "debug": False, "exergy": True}
    return inputs, params, options


def run_cb_point(design_row, T_hs, T_cs, cb_class_name, cfg):
    """Evaluate a single CBSim point. Returns dict with success, KPIs, error."""
    cb_class = getattr(CB, cb_class_name + "_STES2T",
                       getattr(CB, cb_class_name, None))
    if cb_class is None:
        return {"success": False, "error_msg": f"Unknown CB class: {cb_class_name}"}

    result = {"success": False, "error_msg": None}
    for key in OBJ_NAMES:
        result[key] = np.nan

    try:
        inputs, params, options = build_cb_inputs(design_row, T_hs, T_cs, cfg)
        my_cb = cb_class(inputs, params, options)
        my_cb.evaluate()

        result["success"] = True
        result["eta_p2p"] = float(my_cb.eta_cb_elec)
        result["energy_density_thermal"] = float(my_cb.E_dens_th / 3.6e6)  # J/m³ → kWh/m³
        result["exergy_efficiency"] = float(my_cb.eta_cb_exer)
    except Exception as e:
        result["error_msg"] = str(e)[:200]

    return result


# ═════════════════════════════════════════════════════════════════════════
# 2. OAT (One-at-a-time) analysis
# ═════════════════════════════════════════════════════════════════════════

def run_oat(design, wp_cfg, opt_cfg, wp_name, design_name):
    """Run OAT perturbation analysis."""
    T_hs_nom = wp_cfg["T_hs"]
    T_cs_nom = wp_cfg["T_cs"]
    cb_class = design.get("cb_config", "SBVCHP_SBORC")

    # Perturbation definitions
    perturbations = {
        "T_hs":      {"nominal": T_hs_nom, "deltas": [-5, -2, +2, +5], "unit": "K"},
        "T_cs":      {"nominal": T_cs_nom, "deltas": [-5, -2, +2, +5], "unit": "K"},
        "eta_max_cp": {"nominal": float(design["eta_max_cp"]),
                       "deltas": [-0.03, -0.01, +0.01, +0.03], "unit": "-",
                       "clip": (0.70, 0.90)},
        "eta_max_ex": {"nominal": float(design["eta_max_ex"]),
                       "deltas": [-0.03, -0.01, +0.01, +0.03], "unit": "-",
                       "clip": (0.70, 0.90)},
        "dT_st_sp":  {"nominal": float(design["dT_st_sp"]),
                      "deltas": [-5, -2, +2, +5], "unit": "K"},
    }

    rows = []

    # Nominal point first
    print(f"  OAT: evaluating nominal point...")
    nom_result = run_cb_point(design, T_hs_nom, T_cs_nom, cb_class, opt_cfg)
    nominal_kpis = {k: nom_result.get(k, np.nan) for k in OBJ_NAMES}
    rows.append({
        "wp": wp_name, "design_name": design_name, "sample_id": "nominal",
        "T_hs": T_hs_nom, "T_cs": T_cs_nom,
        "eta_max_cp": float(design["eta_max_cp"]),
        "eta_max_ex": float(design["eta_max_ex"]),
        "dT_st_sp": float(design["dT_st_sp"]),
        "success": nom_result["success"],
        "error_msg": nom_result.get("error_msg", ""),
        "eta_p2p": nom_result["eta_p2p"],
        "energy_density_thermal": nom_result["energy_density_thermal"],
        "exergy_efficiency": nom_result["exergy_efficiency"],
        "eta_p2p_retention": 1.0,
        "e_th_retention": 1.0,
        "eta_ex_retention": 1.0,
    })

    # Perturb each variable
    for var_name, pert in perturbations.items():
        nominal_val = pert["nominal"]
        for delta in pert["deltas"]:
            new_val = nominal_val + delta
            if "clip" in pert:
                new_val = np.clip(new_val, pert["clip"][0], pert["clip"][1])

            # Build perturbed design
            pert_design = dict(design)
            T_hs_i = T_hs_nom
            T_cs_i = T_cs_nom

            if var_name == "T_hs":
                T_hs_i = new_val
            elif var_name == "T_cs":
                T_cs_i = new_val
            elif var_name in ["eta_max_cp", "eta_max_ex", "dT_st_sp"]:
                pert_design[var_name] = new_val

            sample_id = f"oat_{var_name}_{delta:+}"
            print(f"  OAT: {sample_id} (nominal={nominal_val}{pert['unit']} → {new_val}{pert['unit']})")
            result = run_cb_point(pert_design, T_hs_i, T_cs_i, cb_class, opt_cfg)

            row = {
                "wp": wp_name, "design_name": design_name,
                "sample_id": sample_id,
                "T_hs": T_hs_i, "T_cs": T_cs_i,
                "eta_max_cp": float(pert_design["eta_max_cp"]),
                "eta_max_ex": float(pert_design["eta_max_ex"]),
                "dT_st_sp": float(pert_design["dT_st_sp"]),
                "success": result["success"],
                "error_msg": result.get("error_msg", ""),
                "eta_p2p": result["eta_p2p"],
                "energy_density_thermal": result["energy_density_thermal"],
                "exergy_efficiency": result["exergy_efficiency"],
            }
            for k in OBJ_NAMES:
                nom_val = nominal_kpis.get(k, np.nan)
                pert_val = row[k]
                row[f"{k}_retention"] = pert_val / nom_val if (nom_val and not np.isnan(nom_val) and not np.isnan(pert_val)) else np.nan
            rows.append(row)

    df = pd.DataFrame(rows)
    out_path = RESULTS_DIR / f"uncertainty_oat_{wp_name}_{design_name}.csv"
    df.to_csv(out_path, index=False)
    print(f"  Saved: {out_path} ({len(df)} rows)")
    return df


# ═════════════════════════════════════════════════════════════════════════
# 3. LHS smoke test
# ═════════════════════════════════════════════════════════════════════════

def latin_hypercube(n_samples, n_vars, seed=None):
    """Simple LHS: one sample per stratum for each variable."""
    if seed is not None:
        np.random.seed(seed)
    samples = np.zeros((n_samples, n_vars))
    for j in range(n_vars):
        perm = np.random.permutation(n_samples)
        samples[:, j] = (perm + np.random.uniform(0, 1, n_samples)) / n_samples
    return samples


def run_lhs(design, wp_cfg, opt_cfg, wp_name, design_name, n_samples, seed):
    """Run LHS smoke test."""
    T_hs_nom = wp_cfg["T_hs"]
    T_cs_nom = wp_cfg["T_cs"]
    cb_class = design.get("cb_config", "SBVCHP_SBORC")

    # Variable ranges
    var_ranges = {
        "T_hs":      (T_hs_nom - 5, T_hs_nom + 5),
        "T_cs":      (T_cs_nom - 5, T_cs_nom + 5),
        "eta_max_cp": (max(0.70, float(design["eta_max_cp"]) - 0.03),
                       min(0.90, float(design["eta_max_cp"]) + 0.03)),
        "eta_max_ex": (max(0.70, float(design["eta_max_ex"]) - 0.03),
                       min(0.90, float(design["eta_max_ex"]) + 0.03)),
    }
    var_names = list(var_ranges.keys())

    # Nominal point
    print(f"  LHS: evaluating nominal point...")
    nom_result = run_cb_point(design, T_hs_nom, T_cs_nom, cb_class, opt_cfg)
    nominal_kpis = {k: nom_result.get(k, np.nan) for k in OBJ_NAMES}

    rows = [{
        "wp": wp_name, "design_name": design_name, "sample_id": "nominal",
        "T_hs": T_hs_nom, "T_cs": T_cs_nom,
        "eta_max_cp": float(design["eta_max_cp"]),
        "eta_max_ex": float(design["eta_max_ex"]),
        "dT_st_sp": float(design["dT_st_sp"]),
        "success": nom_result["success"],
        "error_msg": nom_result.get("error_msg", ""),
        "eta_p2p": nom_result["eta_p2p"],
        "energy_density_thermal": nom_result["energy_density_thermal"],
        "exergy_efficiency": nom_result["exergy_efficiency"],
        "eta_p2p_retention": 1.0,
        "e_th_retention": 1.0,
        "eta_ex_retention": 1.0,
    }]

    # Generate LHS samples
    lh_samples = latin_hypercube(n_samples, len(var_names), seed)

    for i in range(n_samples):
        pert_design = dict(design)
        T_hs_i = T_hs_nom
        T_cs_i = T_cs_nom

        for j, vname in enumerate(var_names):
            lo, hi = var_ranges[vname]
            val = lo + lh_samples[i, j] * (hi - lo)
            if vname == "T_hs":
                T_hs_i = val
            elif vname == "T_cs":
                T_cs_i = val
            else:
                pert_design[vname] = val

        sample_id = f"lhs_{i:03d}"
        result = run_cb_point(pert_design, T_hs_i, T_cs_i, cb_class, opt_cfg)

        row = {
            "wp": wp_name, "design_name": design_name,
            "sample_id": sample_id,
            "T_hs": T_hs_i, "T_cs": T_cs_i,
            "eta_max_cp": float(pert_design["eta_max_cp"]),
            "eta_max_ex": float(pert_design["eta_max_ex"]),
            "dT_st_sp": float(pert_design["dT_st_sp"]),
            "success": result["success"],
            "error_msg": result.get("error_msg", ""),
            "eta_p2p": result["eta_p2p"],
            "energy_density_thermal": result["energy_density_thermal"],
            "exergy_efficiency": result["exergy_efficiency"],
        }
        for k in OBJ_NAMES:
            nom_val = nominal_kpis.get(k, np.nan)
            pert_val = row[k]
            row[f"{k}_retention"] = pert_val / nom_val if (nom_val and not np.isnan(nom_val) and not np.isnan(pert_val)) else np.nan
        rows.append(row)

        if (i + 1) % 10 == 0:
            print(f"  LHS: {i+1}/{n_samples} samples evaluated...")

    df = pd.DataFrame(rows)
    out_path = RESULTS_DIR / f"uncertainty_lhs_{wp_name}_{design_name}.csv"
    df.to_csv(out_path, index=False)
    print(f"  Saved: {out_path} ({len(df)} rows)")
    return df


# ═════════════════════════════════════════════════════════════════════════
# 4. Main
# ═════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Uncertainty / Robustness Smoke Test")
    parser.add_argument("--mode", required=True, choices=["oat", "lhs"],
                        help="Perturbation mode")
    parser.add_argument("--wp", required=True, help="Working point (e.g. DC-A)")
    parser.add_argument("--design", required=True, help="Design name (e.g. D_bal)")
    parser.add_argument("--n-samples", type=int, default=30,
                        help="Number of LHS samples (LHS mode only)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (LHS mode only)")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  Uncertainty / Robustness Smoke Test")
    print(f"  Mode: {args.mode} | WP: {args.wp} | Design: {args.design}")
    print("=" * 60)

    # Load
    config = load_config()
    wp_cfg, opt_cfg = load_wp_config(config, args.wp)
    design = load_design(args.wp, args.design)

    print(f"\n  Design: {args.design}")
    print(f"  Nominal: T_hs={wp_cfg['T_hs']}°C, T_cs={wp_cfg['T_cs']}°C")
    print(f"  Config: {design.get('cb_config', '?')}")
    print(f"  Fluid: HP={design.get('fluid_hp', '?')}, ORC={design.get('fluid_he', '?')}")
    print(f"  T_st_ht={design.get('T_st_ht', '?')}°C, dT_st_sp={design.get('dT_st_sp', '?')}K")
    print(f"  eta_cp={design.get('eta_max_cp', '?')}, eta_ex={design.get('eta_max_ex', '?')}")

    if args.mode == "oat":
        print(f"\n[OAT] One-at-a-time perturbations...")
        df = run_oat(design, wp_cfg, opt_cfg, args.wp, args.design)
    else:
        print(f"\n[LHS] {args.n_samples} samples, seed={args.seed}...")
        df = run_lhs(design, wp_cfg, opt_cfg, args.wp, args.design,
                     args.n_samples, args.seed)

    # ── Summary stats ───────────────────────────────────────────────────
    success_rate = df["success"].mean()
    n_ok = df["success"].sum()
    n_total = len(df)
    print(f"\n  Summary: {n_ok}/{n_total} succeeded ({success_rate*100:.1f}%)")

    if n_ok > 1:
        ok_rows = df[df["success"]]
        for k in OBJ_NAMES:
            values = ok_rows[k].dropna()
            if len(values) > 0:
                print(f"  {k}: nominal={ok_rows.iloc[0][k]:.4f}, "
                      f"min={values.min():.4f}, max={values.max():.4f}, "
                      f"mean={values.mean():.4f}, std={values.std():.4f}")

        # Retention stats
        for k in OBJ_NAMES:
            ret_col = f"{k}_retention"
            ret_vals = ok_rows[ret_col].dropna()
            if len(ret_vals) > 1:
                perturbed = ret_vals[1:]  # exclude nominal
                if len(perturbed) > 0:
                    print(f"  {k}_retention (perturbed): min={perturbed.min():.4f}, "
                          f"max={perturbed.max():.4f}, mean={perturbed.mean():.4f}")

    # Failed samples
    failed = df[~df["success"]]
    if len(failed) > 0:
        print(f"\n  Failed samples ({len(failed)}):")
        for _, row in failed.iterrows():
            print(f"    {row['sample_id']}: {row['error_msg'][:100]}")

    print(f"\n{'=' * 60}")
    print(f"  DONE")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    main()
