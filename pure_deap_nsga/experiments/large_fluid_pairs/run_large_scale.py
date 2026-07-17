#!/usr/bin/env python3
"""Auditable task-level runner for large CBSim fluid-pair optimizations."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
NSGA_DIR = ROOT / "pure_deap_nsga"
sys.path.insert(0, str(NSGA_DIR))

VARIABLE_NAMES = [
    "T_st_ht", "dT_st_sp", "dT_hp_cs_gl", "dT_hp_ev_sh",
    "dT_he_ev_sh", "dT_hp_cd_sc", "eta_max_cp", "eta_max_ex", "eta_pm",
]
TERMINAL_STATES = {"COMPLETED", "EMPTY", "FAILED", "TIMEOUT", "CANCELLED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_name(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or char in "-_")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_checksums(run_dir: Path) -> None:
    paths = []
    for relative_root in ["config", "outputs", "failures"]:
        root = run_dir / relative_root
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file()
                         and not path.name.endswith(".tmp"))
    lines = [
        f"{sha256(path)}  {path.relative_to(run_dir)}"
        for path in sorted(paths)
    ]
    target = run_dir / "metadata" / "checksums.sha256"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".sha256.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def git_info() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip())
    return commit, dirty


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_pairs(path: Path) -> list[tuple[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"fluid_hp", "fluid_he"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"pair list must contain columns {sorted(required)}")
        return list(dict.fromkeys((row["fluid_hp"].strip(), row["fluid_he"].strip())
                                  for row in reader))


def read_exact_tasks(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"wp", "cfg", "fluid_hp", "fluid_he", "seed"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"task list must contain columns {sorted(required)}")
        rows = []
        seen = set()
        for row in reader:
            item = {
                "wp": row["wp"].strip(), "cfg": row["cfg"].strip(),
                "fluid_hp": row["fluid_hp"].strip(),
                "fluid_he": row["fluid_he"].strip(), "seed": int(row["seed"]),
            }
            key = tuple(item.values())
            if key not in seen:
                rows.append(item)
                seen.add(key)
        return rows


def pair_gate(config: dict[str, Any], wp_key: str, hp: str, he: str) -> dict[str, Any]:
    from fluid_filter_diagnostics import check_fluid_filter
    from CoolProp.CoolProp import PropsSI
    if hp not in config["fluid_candidates"]["hp_fluids"]:
        raise ValueError(f"unknown HP fluid: {hp}")
    if he not in config["fluid_candidates"]["he_fluids"]:
        raise ValueError(f"unknown HE fluid: {he}")
    result = check_fluid_filter(
        config["working_points"][wp_key], hp, he, config["fluid_candidates"]
    )
    issues = list(result["issues"])
    wp = config["working_points"][wp_key]
    opt = config["optimization"]
    pressure_window = config.get("experiment", {}).get("pressure_window_bar", [0.5, 40.0])
    p_min, p_max = (float(value) * 1e5 for value in pressure_window)
    # The HP exergy calculation uses the cold-sink state as its fixed
    # thermodynamic reference.  This state is independent of the optimizer,
    # so a fluid that cannot represent it must be rejected before a task is
    # launched.  The previous saturation-only gate missed CycloHexane/DC-E,
    # whose 5 °C reference lies below its triple point.
    reference_pressure = 1.0e5
    reference_temperature_k = float(wp["T_cs"]) + 273.15
    try:
        hp_triple_k = float(PropsSI("Ttriple", hp))
        if reference_temperature_k <= hp_triple_k + 1.0:
            issues.append({
                "code": "FLUID_FILTER_REFERENCE_STATE_BELOW_TRIPLE",
                "component": "config", "cls": "LargeScaleGate",
                "method": "pair_gate",
                "message": "HP fixed reference temperature is below the fluid domain",
                "severity": "error",
                "values": {
                    "side": "HP", "fluid": hp,
                    "pressure_Pa": reference_pressure,
                    "temperature_K": reference_temperature_k,
                    "Ttriple_K": hp_triple_k,
                    "margin_K": reference_temperature_k - hp_triple_k,
                    "location": "CBEvaluator.params.p_ref/T_ref",
                },
            })
        else:
            # Query both properties used by the exergy reference calculation.
            PropsSI("Hmass", "P", reference_pressure, "T", reference_temperature_k, hp)
            PropsSI("Smass", "P", reference_pressure, "T", reference_temperature_k, hp)
    except Exception as exc:
        issues.append({
            "code": "FLUID_FILTER_REFERENCE_STATE_QUERY_FAILED",
            "component": "config", "cls": "LargeScaleGate",
            "method": "pair_gate",
            "message": f"HP fixed reference query failed: {type(exc).__name__}: {exc}",
            "severity": "error",
            "values": {
                "side": "HP", "fluid": hp,
                "pressure_Pa": reference_pressure,
                "temperature_K": reference_temperature_k,
                "location": "CBEvaluator.params.p_ref/T_ref",
            },
        })
    checks = [
        ("HP_CONDENSER", hp, wp["T_st_ht_max"] - opt["dT_hp_cd_pp"], 0.0),
        ("HP_EVAPORATOR", hp, wp["T_hs"] - opt["dT_hp_ev_pp"], 1.0),
        ("HE_CONDENSER", he, wp["T_cs"] + opt["dT_he_cd_pp"] + opt["dT_he_cd_sc"], 0.0),
        ("HE_EVAPORATOR", he, wp["T_st_ht_min"] - opt["dT_he_ev_pp"] - 0.5, 1.0),
    ]
    pressures = {}
    for label, fluid, temperature_c, quality in checks:
        try:
            triple_k = float(PropsSI("Ttriple", fluid))
            temperature_k = float(temperature_c) + 273.15
            if temperature_k <= triple_k + 1.0:
                issues.append({
                    "code": "FLUID_FILTER_TRIPLE_MARGIN_LOW", "component": "config",
                    "cls": "LargeScaleGate", "method": "pair_gate",
                    "message": f"{label} temperature is too close to/below Ttriple",
                    "severity": "error",
                    "values": {"fluid": fluid, "temperature_K": temperature_k,
                               "Ttriple_K": triple_k, "margin_K": temperature_k - triple_k},
                })
                continue
            pressure = float(PropsSI("P", "T", temperature_k, "Q", quality, fluid))
            pressures[label] = pressure
            if not p_min <= pressure <= p_max:
                issues.append({
                    "code": "FLUID_FILTER_PRESSURE_WINDOW", "component": "config",
                    "cls": "LargeScaleGate", "method": "pair_gate",
                    "message": f"{label} saturation pressure outside configured window",
                    "severity": "error",
                    "values": {"fluid": fluid, "pressure_Pa": pressure,
                               "window_Pa": [p_min, p_max], "temperature_C": temperature_c},
                })
        except Exception as exc:
            issues.append({
                "code": "FLUID_FILTER_PROPERTY_QUERY_FAILED", "component": "config",
                "cls": "LargeScaleGate", "method": "pair_gate",
                "message": f"{label}: {type(exc).__name__}: {exc}",
                "severity": "error",
                "values": {"fluid": fluid, "temperature_C": temperature_c, "quality": quality},
            })
    for side, high_key, low_key in [
        ("HP", "HP_CONDENSER", "HP_EVAPORATOR"),
        ("HE", "HE_EVAPORATOR", "HE_CONDENSER"),
    ]:
        if high_key in pressures and low_key in pressures:
            ratio = pressures[high_key] / pressures[low_key]
            if ratio <= 1.0 or ratio > 50.0:
                issues.append({
                    "code": "FLUID_FILTER_PRESSURE_RATIO", "component": "config",
                    "cls": "LargeScaleGate", "method": "pair_gate",
                    "message": f"{side} estimated pressure ratio outside (1, 50]",
                    "severity": "error",
                    "values": {"side": side, "pressure_ratio": ratio},
                })
    error_issues = [
        issue for issue in issues if issue.get("severity", "error") == "error"
    ]
    return {
        "passed": not error_issues,
        "primary_code": error_issues[0]["code"] if error_issues else None,
        "n_issues": len(issues),
        "issues": issues,
        "estimated_pressures_Pa": pressures,
    }


def make_run_id(stage: str, wp: str, cfg: str, hp: str, he: str,
                seed: int, stamp: str) -> str:
    return "_".join([
        safe_name(stage), safe_name(wp.replace("-", "")), safe_name(cfg.replace("_", "-")),
        safe_name(hp), safe_name(he), f"seed{seed:03d}", stamp,
    ])


def expand_tasks(args, config: dict[str, Any], batch_dir: Path) -> list[dict[str, Any]]:
    exact_tasks = read_exact_tasks(args.task_list) if args.task_list else None
    if exact_tasks:
        wp_keys = list(dict.fromkeys(item["wp"] for item in exact_tasks))
        cfg_keys = list(dict.fromkeys(item["cfg"] for item in exact_tasks))
    else:
        wp_keys = args.wp or list(config["working_points"])
        cfg_keys = args.cfg or list(config["configurations"])
    for key in wp_keys:
        if key not in config["working_points"]:
            raise ValueError(f"unknown working point: {key}")
    for key in cfg_keys:
        if key not in config["configurations"]:
            raise ValueError(f"unknown configuration: {key}")

    if exact_tasks:
        pairs = []
    elif args.pair_list:
        pairs = read_pairs(args.pair_list)
    elif args.fluid_hp or args.fluid_he:
        if not (args.fluid_hp and args.fluid_he):
            raise ValueError("--fluid-hp and --fluid-he must be used together")
        pairs = [(args.fluid_hp, args.fluid_he)]
    else:
        pairs = [
            (hp, he)
            for hp in config["fluid_candidates"]["hp_fluids"]
            for he in config["fluid_candidates"]["he_fluids"]
        ]

    tasks = []
    stamp = utc_stamp()
    filtered = []
    expansion = (
        [(item["wp"], item["cfg"], item["fluid_hp"], item["fluid_he"], item["seed"])
         for item in exact_tasks]
        if exact_tasks else
        [(wp, cfg, hp, he, seed)
         for wp in wp_keys for hp, he in pairs for cfg in cfg_keys for seed in args.seed]
    )
    for wp, cfg, hp, he, seed in expansion:
            gate = pair_gate(config, wp, hp, he)
            if not gate["passed"]:
                filtered.append({
                    "wp": wp, "cfg": cfg, "fluid_hp": hp, "fluid_he": he,
                    "status": "FILTERED", "primary_code": gate["primary_code"],
                    "issues": gate["issues"],
                })
                continue
            run_id = make_run_id(args.stage, wp, cfg, hp, he, seed, stamp)
            run_dir = batch_dir / "runs" / run_id
            tasks.append({
                "run_id": run_id, "stage": args.stage, "wp": wp, "cfg": cfg,
                "cb_class": config["configurations"][cfg]["class"],
                "fluid_hp": hp, "fluid_he": he, "seed": seed,
                "population_size": args.population_size,
                "n_generations": args.generations,
                "checkpoint_every": args.checkpoint_every,
                "archive_tol": args.archive_tol,
                        "mode": args.mode,
                        "screening_samples": args.samples,
                "config_path": str(args.config.resolve()),
                "config_sha256": sha256(args.config.resolve()),
                "run_dir": str(run_dir),
                "resume_from": str(args.resume_from.resolve()) if args.resume_from else None,
            })
    atomic_json(batch_dir / "filtered_cases.json", filtered)
    if not tasks:
        raise ValueError("no eligible tasks after fluid gates")
    run_ids = [task["run_id"] for task in tasks]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("duplicate run_id generated")
    atomic_json(batch_dir / "task_plan.json", tasks)
    return tasks


def stage_for_code(code: str | None, component: str | None = None,
                   method: str | None = None, message: str | None = None) -> str:
    if not code:
        return "UNKNOWN_WRAPPER"
    component = str(component or "").upper()
    method_text = str(method or "").lower()
    message_text = str(message or "").lower()
    if code.startswith(("OPT_PRECHECK", "FLUID_FILTER")):
        return "OPT_PRECHECK"
    if code.startswith("COOLPROP_") or code == "UPSTREAM_NONFINITE_STATE":
        return "PROPERTY_INPUT_BUILD"
    if code.startswith(("KPI_", "EFFICIENCY_")):
        return "KPI_SANITY"
    if "RECUPERATOR" in code:
        return "HP_RECUPERATOR_SOLVE" if component == "HP" else "HE_RECUPERATOR_SOLVE"
    if code.startswith("SOLVER_"):
        if component == "HP":
            return "HP_CONSISTENCY" if "consistency" in method_text else "HP_PRESSURE_SOLVE"
        if component == "HE":
            return "HE_CONSISTENCY" if "consistency" in method_text else "HE_PRESSURE_SOLVE"
        if any(name in message_text for name in ("sborc", "srorc", "tborc", "trorc")):
            return "HE_PRESSURE_SOLVE"
        if any(name in message_text for name in ("sbvchp", "srvchp", "tbvchp", "trvchp")):
            return "HP_PRESSURE_SOLVE"
        return "SOLVER_EXECUTION"
    if component == "HP" or "HP_" in code or code.startswith("HX_PINCH_HP"):
        return "HP_CONSISTENCY"
    if component == "HE" or "HE_" in code or code.startswith("HX_PINCH_HE"):
        return "HE_CONSISTENCY"
    if code.startswith(("STATE_", "PHASE_", "PRESSURE_")):
        return "CB_COUPLING_CONSISTENCY"
    return "CB_COUPLING_CONSISTENCY"


def design_variable_record(evaluator, x: list[float]) -> dict[str, Any]:
    units = ["C", "K", "K", "K", "K", "K", "-", "-", "-"]
    output = {}
    for name, unit, value, lo, hi in zip(
        VARIABLE_NAMES, units, x, evaluator.lb, evaluator.ub
    ):
        span = float(hi - lo)
        distance = min(value - lo, hi - value) / span if span > 0 else None
        output[f"{name}_{unit}" if unit != "-" else name] = {
            "value": float(value), "lb": float(lo), "ub": float(hi),
            "out_of_bounds": not (lo <= value <= hi),
            "normalized_nearest_bound_distance": float(distance) if distance is not None else None,
        }
    return output


def write_failures(task: dict[str, Any], evaluator, config: dict[str, Any],
                   commit: str, dirty: bool) -> int:
    from jsonschema import Draft202012Validator

    run_dir = Path(task["run_dir"])
    records_dir = run_dir / "failures" / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    failed_rows = []
    issue_rows = []
    solver_rows = []
    wp = config["working_points"][task["wp"]]
    schema = json.loads(
        (HERE / "failure_record.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    for index, info in enumerate(evaluator.diagnostics_records, 1):
        if info.get("feasible"):
            continue
        evaluation_id = f"evaluation_{index:09d}"
        x = [float(info.get("decoded", {}).get(name, math.nan)) for name in VARIABLE_NAMES]
        issues = info.get("issues") or [{
            "code": info.get("primary_code") or "UNKNOWN_EXCEPTION",
            "component": "optimizer", "cls": "CBEvaluator", "method": "evaluate",
            "message": "penalized evaluation without detailed issue",
            "severity": "error", "values": {},
        }]
        primary = info.get("primary_code") or issues[0]["code"]
        normalized_issues = []
        solver_attempts = []
        for issue_index, issue in enumerate(issues, 1):
            issue_id = f"{evaluation_id}_issue_{issue_index:03d}"
            normalized = {
                "issue_id": issue_id, "stage_code": stage_for_code(
                    issue.get("code"), issue.get("component"),
                    issue.get("method"), issue.get("message")
                ),
                "code": issue.get("code", "UNKNOWN_EXCEPTION"),
                "severity": issue.get("severity", "error"),
                "component": issue.get("component", "unknown"),
                "class": issue.get("cls", "unknown"),
                "method": issue.get("method", "unknown"),
                "message": str(issue.get("message", "")),
                "values": issue.get("values", {}),
                "exception": None,
            }
            normalized_issues.append(normalized)
            issue_rows.append({
                "evaluation_id": evaluation_id, "issue_id": issue_id,
                "stage_code": normalized["stage_code"], "code": normalized["code"],
                "severity": normalized["severity"], "component": normalized["component"],
                "class": normalized["class"], "method": normalized["method"],
                "message": normalized["message"],
            })
            if normalized["code"].startswith("SOLVER_"):
                is_least_squares = (
                    "least_squares" in normalized["message"]
                    or "x0" in normalized["message"]
                )
                residual = normalized["values"].get(
                    "residual_linf", normalized["values"].get("residual")
                )
                attempt = {
                    "attempt_index": len(solver_attempts) + 1,
                    "component": normalized["component"],
                    "method": normalized["method"],
                    "solver_name": (
                        "least_squares" if is_least_squares
                        else "post_solve_consistency"
                    ),
                    "is_fallback": is_least_squares,
                    "fallback_from": "fsolve" if is_least_squares else None,
                    "x0": normalized["values"].get("x0"),
                    "bounds": normalized["values"].get("bounds"),
                    "solver_options": {},
                    "x_final": normalized["values"].get("x_final"),
                    "residual_vector": normalized["values"].get(
                        "residual_vector", [residual] if residual is not None else None
                    ),
                    "residual_l2": normalized["values"].get("residual_l2"),
                    "residual_linf": residual,
                    "residual_tol": normalized["values"].get("residual_tol"),
                    "success": False,
                    "status": None, "ier": None,
                    "message": normalized["message"],
                    "nfev": None, "njev": None, "nit": None, "elapsed_ms": None,
                }
                solver_attempts.append(attempt)
                solver_rows.append({
                    "evaluation_id": evaluation_id,
                    "attempt_index": attempt["attempt_index"],
                    "component": attempt["component"],
                    "method": attempt["method"],
                    "solver_name": attempt["solver_name"],
                    "success": attempt["success"],
                    "message": attempt["message"],
                })
        primary_issue = next(
            (issue for issue in normalized_issues if issue["code"] == primary),
            normalized_issues[0],
        )
        deepest_stage = primary_issue["stage_code"]
        record = {
            "schema_version": "0.1", "evaluation_id": evaluation_id,
            "parent_evaluation_id": None,
            "run": {
                "run_id": task["run_id"], "case_id": task["run_id"],
                "seed": task["seed"], "algorithm": config["optimization"].get("algorithm", "NSGA2"),
                "generation": None, "individual_index": None,
                "worker_pid": os.getpid(), "hostname": socket.gethostname(),
            },
            "model": {
                "wp": task["wp"], "cb_config": task["cfg"], "cb_class": task["cb_class"],
                "fluid_hp": task["fluid_hp"], "fluid_he": task["fluid_he"],
                "objectives": config["optimization"]["objectives"],
            },
            "working_point": {
                "T_hs_C": wp["T_hs"], "T_cs_C": wp["T_cs"],
                "delta_T_K": wp.get("delta_T"),
                "T_st_ht_min_C": wp["T_st_ht_min"],
                "T_st_ht_max_C": wp["T_st_ht_max"],
                "dT_st_sp_min_K": wp["dT_st_sp_min"],
                "dT_st_sp_max_K": wp["dT_st_sp_max"],
            },
            "design_variables": design_variable_record(evaluator, x),
            "raw_x": x, "fixed_parameters": config["optimization"],
            "outcome": {
                "feasible": False, "penalized": True, "penalty_value": -1e6,
                "constraint_violation": float(info.get("constraint_violation", 10.0)),
                "primary_code": primary,
                "secondary_codes": [issue["code"] for issue in normalized_issues[1:]],
                "deepest_stage": deepest_stage, "stage_path": None, "kpis": {},
            },
            "issues": normalized_issues, "solver_attempts": solver_attempts,
            "states": {}, "timings": {},
            "reproduction": {
                "timestamp_utc": utc_now(), "timezone": "UTC",
                "git_commit": commit, "git_dirty": dirty,
                "config_path": task["config_path"], "config_sha256": task["config_sha256"],
                "cli_argv": sys.argv, "cwd": str(ROOT),
                "python_version": platform.python_version(),
                "numpy_version": __import__("numpy").__version__,
                "scipy_version": __import__("scipy").__version__,
                "coolprop_version": __import__("CoolProp").__version__,
                "deap_version": __import__("deap").__version__,
                "platform": platform.platform(), "retry_count": 0,
            },
        }
        validation_errors = sorted(
            validator.iter_errors(record), key=lambda error: list(error.path)
        )
        if validation_errors:
            messages = "; ".join(
                f"{'/'.join(map(str, error.path))}: {error.message}"
                for error in validation_errors[:10]
            )
            raise ValueError(
                f"failure record schema validation failed for {evaluation_id}: {messages}"
            )
        relative = Path("failures") / "records" / f"{evaluation_id}.json"
        atomic_json(run_dir / relative, record)
        failed_rows.append({
            "evaluation_id": evaluation_id, "primary_code": primary,
            "deepest_stage": deepest_stage,
            "constraint_violation": float(info.get("constraint_violation", 10.0)),
            **{name: value for name, value in zip(VARIABLE_NAMES, x)},
            "record_path": str(relative),
        })
    failed_fields = ["evaluation_id", "primary_code", "deepest_stage",
                     "constraint_violation", *VARIABLE_NAMES, "record_path"]
    issue_fields = ["evaluation_id", "issue_id", "stage_code", "code", "severity",
                    "component", "class", "method", "message"]
    atomic_csv(run_dir / "failures" / "failed_evaluations.csv", failed_rows, failed_fields)
    atomic_csv(run_dir / "failures" / "failure_issues.csv", issue_rows, issue_fields)
    atomic_csv(run_dir / "failures" / "solver_attempts.csv", solver_rows, [
        "evaluation_id", "attempt_index", "component", "method", "solver_name",
        "success", "message",
    ])
    return len(failed_rows)


def validate_front(df, evaluator, objectives: list[str]) -> list[str]:
    errors = []
    if df.empty:
        return errors
    if df.isna().any().any():
        errors.append("FRONT_CONTAINS_NAN")
    numeric = df[VARIABLE_NAMES + objectives].to_numpy(dtype=float)
    if not all(math.isfinite(value) for value in numeric.ravel()):
        errors.append("FRONT_CONTAINS_NONFINITE")
    for name, lo, hi in zip(VARIABLE_NAMES, evaluator.lb, evaluator.ub):
        if ((df[name] < lo) | (df[name] > hi)).any():
            errors.append(f"FRONT_VARIABLE_OUT_OF_BOUNDS:{name}")
    if "eta_p2p" in df and not ((df["eta_p2p"] > 0.01) & (df["eta_p2p"] < 1.0)).all():
        errors.append("FRONT_ETA_P2P_RANGE")
    if "energy_density_thermal" in df and not (df["energy_density_thermal"] > 0).all():
        errors.append("FRONT_ENERGY_DENSITY_RANGE")
    if "exergy_efficiency" in df and not (
        (df["exergy_efficiency"] > 0) & (df["exergy_efficiency"] < 1)
    ).all():
        errors.append("FRONT_EXERGY_EFFICIENCY_RANGE")
    if df.duplicated(subset=VARIABLE_NAMES).any():
        errors.append("FRONT_DUPLICATE_DESIGNS")
    return errors


def set_status(run_dir: Path, state: str) -> None:
    status_dir = run_dir / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    for existing in status_dir.iterdir():
        existing.unlink()
    (status_dir / state).touch()


def run_worker(task_path: Path) -> int:
    import pandas as pd
    from deap_optimizer import CBEvaluator, NSGAOptimizer

    task = json.loads(task_path.read_text(encoding="utf-8"))
    run_dir = Path(task["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / ".lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f"run directory is locked: {run_dir}")
    os.write(lock_fd, f"{os.getpid()}\n".encode())
    os.close(lock_fd)

    commit, dirty = git_info()
    config = load_config(Path(task["config_path"]))
    snapshot = run_dir / "config" / "config.snapshot.json"
    atomic_json(snapshot, config)
    manifest = {
        "schema_version": "1.0", **task, "status": "RUNNING",
        "git_commit": commit, "git_dirty": dirty, "hostname": socket.gethostname(),
        "cli_argv": list(sys.argv), "cwd": str(ROOT),
        "python_version": platform.python_version(),
        "numpy_version": __import__("numpy").__version__,
        "scipy_version": __import__("scipy").__version__,
        "coolprop_version": __import__("CoolProp").__version__,
        "deap_version": __import__("deap").__version__,
        "platform": platform.platform(),
        "start_time_utc": utc_now(), "end_time_utc": None, "exit_code": None,
    }
    atomic_json(run_dir / "metadata" / "manifest.json", manifest)
    set_status(run_dir, "RUNNING")
    started = time.time()
    try:
        wp = config["working_points"][task["wp"]]
        opt = dict(config["optimization"])
        opt["population_size"] = task["population_size"]
        opt["n_generations"] = task["n_generations"]
        opt["seed"] = task["seed"]
        opt["diagnostics_enabled"] = True
        evaluator = CBEvaluator(
            wp=wp, cfg=opt, cb_class_name=task["cb_class"],
            fluid_hp=task["fluid_hp"], fluid_he=task["fluid_he"],
            objectives=opt["objectives"], economic_params=opt.get("economic_params"),
        )
        mode = task.get("mode", "optimize")
        sampling_rows = None
        if mode == "s0":
            x = [
                float((lo + hi) / 2)
                for lo, hi in zip(evaluator.lb, evaluator.ub)
            ]
            values = evaluator.evaluate(x)
            if evaluator.last_eval_info.get("feasible"):
                row = evaluator.decode(x)
                row.update(dict(zip(opt["objectives"], map(float, values))))
                df = pd.DataFrame([row])
            else:
                df = pd.DataFrame(columns=VARIABLE_NAMES + opt["objectives"])
            generation_metrics = [{
                "generation": 0, "n_evaluated": 1,
                "n_feasible": int(evaluator.last_eval_info.get("feasible", False)),
                "population_size": 1, "front_size": len(df),
                "archive_size": len(df), "unique_ratio": 1.0,
                "elapsed_s": time.time() - started,
            }]
            archive_size = len(df)
        elif mode == "s1":
            import numpy as np
            from scipy.stats import qmc
            sample_count = int(task["screening_samples"])
            if sample_count < 2 or sample_count & (sample_count - 1):
                raise ValueError("S1 screening sample count must be a power of two")
            sampler = qmc.Sobol(d=evaluator.n_vars, scramble=True, seed=task["seed"])
            unit_samples = sampler.random_base2(m=int(math.log2(sample_count)))
            samples = qmc.scale(unit_samples, evaluator.lb, evaluator.ub)
            sampling_rows = []
            feasible_records = []
            for sample_id, x_array in enumerate(samples):
                x = list(map(float, x_array))
                values = evaluator.evaluate(x)
                info = evaluator.last_eval_info
                feasible = bool(info.get("feasible"))
                row = {
                    "sample_id": sample_id, "feasible": feasible,
                    "primary_code": info.get("primary_code") or "",
                    **evaluator.decode(x),
                }
                for name, value in zip(opt["objectives"], values):
                    row[name] = float(value) if feasible else None
                sampling_rows.append(row)
                if feasible:
                    feasible_records.append({
                        **evaluator.decode(x),
                        **dict(zip(opt["objectives"], map(float, values))),
                    })
            df = pd.DataFrame(feasible_records)
            generation_metrics = [{
                "generation": 0, "n_evaluated": sample_count,
                "n_feasible": len(feasible_records),
                "population_size": sample_count,
                "front_size": 0, "archive_size": 0,
                "unique_ratio": len({
                    tuple(np.round(row[VARIABLE_NAMES].to_numpy(dtype=float), 12))
                    for _, row in pd.DataFrame(sampling_rows).iterrows()
                }) / sample_count,
                "elapsed_s": time.time() - started,
            }]
            archive_size = 0
        else:
            optimizer = NSGAOptimizer(
                evaluator=evaluator, algorithm=opt.get("algorithm", "NSGA2"),
                pop_size=opt["population_size"], n_gen=opt["n_generations"],
                cx_prob=opt.get("crossover_prob", 0.9),
                mut_prob=opt.get("mutation_prob", 0.1), seed=task["seed"],
                archive_tol=task["archive_tol"],
            )
            resume_state = None
            if task.get("resume_from"):
                resume_state = json.loads(Path(task["resume_from"]).read_text(encoding="utf-8"))
                expected_run_signature = {
                    "config_sha256": task["config_sha256"], "wp": task["wp"],
                    "cfg": task["cfg"], "fluid_hp": task["fluid_hp"],
                    "fluid_he": task["fluid_he"], "seed": task["seed"],
                }
                if resume_state.get("run_signature") != expected_run_signature:
                    raise ValueError("checkpoint run signature does not match requested task")

            checkpoint_dir = run_dir / "checkpoints"
            def save_checkpoint(payload):
                generation = payload["generation"]
                payload["run_signature"] = {
                    "config_sha256": task["config_sha256"], "wp": task["wp"],
                    "cfg": task["cfg"], "fluid_hp": task["fluid_hp"],
                    "fluid_he": task["fluid_he"], "seed": task["seed"],
                }
                atomic_json(checkpoint_dir / f"generation_{generation:06d}.json", payload)
                atomic_json(checkpoint_dir / "latest.json", payload)

            front, _ = optimizer.run(
                verbose=True, resume_state=resume_state,
                checkpoint_every=task["checkpoint_every"],
                checkpoint_callback=save_checkpoint,
            )
            df = optimizer.results_to_dataframe(front)
            generation_metrics = optimizer.generation_metrics
            archive_size = len(front)
        if not df.empty:
            df["wp"] = task["wp"]
            df["cb_config"] = task["cfg"]
            df["fluid_hp"] = task["fluid_hp"]
            df["fluid_he"] = task["fluid_he"]
            df["seed"] = task["seed"]
            df["run_id"] = task["run_id"]
        validation_errors = validate_front(df, evaluator, opt["objectives"])
        if validation_errors:
            raise ValueError(";".join(validation_errors))
        output_dir = run_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        if mode == "s1":
            sampling_df = pd.DataFrame(sampling_rows)
            for key, value in {
                "wp": task["wp"], "cb_config": task["cfg"],
                "fluid_hp": task["fluid_hp"], "fluid_he": task["fluid_he"],
                "seed": task["seed"], "run_id": task["run_id"],
            }.items():
                sampling_df[key] = value
            temporary_sampling = output_dir / "sampling_feasibility.csv.tmp"
            sampling_df.to_csv(temporary_sampling, index=False)
            os.replace(
                temporary_sampling, output_dir / "sampling_feasibility.csv"
            )
            temporary_parquet = output_dir / "sampling_feasibility.parquet.tmp"
            sampling_df.to_parquet(temporary_parquet, index=False)
            os.replace(
                temporary_parquet, output_dir / "sampling_feasibility.parquet"
            )
        else:
            temporary_front = output_dir / "pareto.csv.tmp"
            df.to_csv(temporary_front, index=False)
            os.replace(temporary_front, output_dir / "pareto.csv")
        atomic_csv(
            output_dir / "generation_metrics.csv",
            generation_metrics,
            ["generation", "n_evaluated", "n_feasible", "population_size",
             "front_size", "archive_size", "unique_ratio",
             "min_constraint_violation", "elapsed_s"],
        )
        failure_count = write_failures(task, evaluator, config, commit, dirty)
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        atomic_csv(run_dir / "logs" / "resource_usage.csv", [{
            "elapsed_s": time.time() - started,
            "user_cpu_s": usage.ru_utime, "system_cpu_s": usage.ru_stime,
            "max_rss_kb": usage.ru_maxrss,
        }], ["elapsed_s", "user_cpu_s", "system_cpu_s", "max_rss_kb"])
        status = (
            "COMPLETED" if mode == "s1"
            else "COMPLETED" if not df.empty else "EMPTY"
        )
        summary = {
            "run_id": task["run_id"], "status": status,
            "elapsed_s": time.time() - started,
            "evaluation_count": len(evaluator.diagnostics_records),
            "feasible_count": sum(
                1 for record in evaluator.diagnostics_records if record.get("feasible")
            ),
            "failure_count": failure_count, "pareto_size": len(df),
            "archive_size": archive_size, "validation_errors": [],
        }
        if mode == "s1":
            summary.update({
                "sample_count": len(sampling_rows),
                "feasible_rate": len(df) / len(sampling_rows),
            })
        atomic_json(output_dir / "summary.json", summary)
        write_checksums(run_dir)
        manifest.update(summary)
        manifest.update({"status": status, "end_time_utc": utc_now(), "exit_code": 0})
        atomic_json(run_dir / "metadata" / "manifest.json", manifest)
        set_status(run_dir, status)
        return 0
    except BaseException as exc:
        manifest.update({
            "status": "FAILED", "end_time_utc": utc_now(), "exit_code": 1,
            "exception_type": type(exc).__name__, "exception": str(exc)[:2000],
            "elapsed_s": time.time() - started,
        })
        atomic_json(run_dir / "metadata" / "manifest.json", manifest)
        set_status(run_dir, "FAILED")
        raise
    finally:
        lock_path.unlink(missing_ok=True)


def mark_external_failure(task: dict[str, Any], state: str, detail: str,
                          exit_code: int | None) -> None:
    run_dir = Path(task["run_dir"])
    manifest_path = run_dir / "metadata" / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"schema_version": "1.0", **task}
    manifest.update({
        "status": state, "end_time_utc": utc_now(), "exit_code": exit_code,
        "external_failure": detail[:4000],
    })
    atomic_json(manifest_path, manifest)
    set_status(run_dir, state)
    (run_dir / ".lock").unlink(missing_ok=True)


def run_scheduler(tasks: list[dict[str, Any]], workers: int,
                  timeout_s: float) -> list[dict[str, Any]]:
    pending = list(tasks)
    running: dict[int, dict[str, Any]] = {}
    results = []
    while pending or running:
        while pending and len(running) < workers:
            task = pending.pop(0)
            run_dir = Path(task["run_dir"])
            task_path = run_dir / "config" / "task.json"
            atomic_json(task_path, task)
            log_path = run_dir / "logs" / "stdout_stderr.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("w", encoding="utf-8")
            command = [
                sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()),
                "--worker", str(task_path),
            ]
            process = subprocess.Popen(
                command, cwd=ROOT, stdout=log_handle, stderr=subprocess.STDOUT,
                text=True,
            )
            running[process.pid] = {
                "process": process, "task": task, "started": time.time(),
                "log_handle": log_handle,
            }
        time.sleep(0.2)
        for pid, item in list(running.items()):
            process = item["process"]
            elapsed = time.time() - item["started"]
            if process.poll() is None and elapsed <= timeout_s:
                continue
            task = item["task"]
            if process.poll() is None:
                process.kill()
                process.wait()
                state, detail = "TIMEOUT", f"hard timeout after {timeout_s}s"
            elif process.returncode == 0:
                state, detail = "FINISHED", ""
            elif process.returncode < 0:
                state, detail = "FAILED", f"native signal {-process.returncode}"
            else:
                state, detail = "FAILED", f"worker exit {process.returncode}"
            item["log_handle"].close()
            if state != "FINISHED":
                mark_external_failure(task, state, detail, process.returncode)
            results.append({
                "run_id": task["run_id"], "scheduler_status": state,
                "exit_code": process.returncode, "elapsed_s": elapsed,
                "run_dir": task["run_dir"], "detail": detail,
                "stage": task["stage"], "wp": task["wp"], "cfg": task["cfg"],
                "fluid_hp": task["fluid_hp"], "fluid_he": task["fluid_he"],
                "seed": task["seed"],
            })
            manifest_path = Path(task["run_dir"]) / "metadata" / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                results[-1].update({
                    "terminal_status": manifest.get("status"),
                    "git_commit": manifest.get("git_commit"),
                    "git_dirty": manifest.get("git_dirty"),
                    "config_sha256": manifest.get("config_sha256"),
                    "start_time_utc": manifest.get("start_time_utc"),
                    "end_time_utc": manifest.get("end_time_utc"),
                    "evaluation_count": manifest.get("evaluation_count"),
                    "feasible_count": manifest.get("feasible_count"),
                    "failure_count": manifest.get("failure_count"),
                    "pareto_size": manifest.get("pareto_size"),
                    "manifest_path": str(manifest_path),
                })
            del running[pid]
    return results


def finalize_s1_batch(batch_dir: Path, results: list[dict[str, Any]]) -> None:
    import pandas as pd

    sample_frames = []
    task_rows = []
    for result in results:
        if result["scheduler_status"] != "FINISHED":
            continue
        run_dir = Path(result["run_dir"])
        sample_path = run_dir / "outputs" / "sampling_feasibility.parquet"
        summary_path = run_dir / "outputs" / "summary.json"
        if not sample_path.exists() or not summary_path.exists():
            continue
        sample_frames.append(pd.read_parquet(sample_path))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        task_rows.append({
            "run_id": result["run_id"], "wp": result["wp"], "cfg": result["cfg"],
            "fluid_hp": result["fluid_hp"], "fluid_he": result["fluid_he"],
            "seed": result["seed"], "sample_count": summary["sample_count"],
            "feasible_count": summary["feasible_count"],
            "failure_count": summary["failure_count"],
            "feasible_rate": summary["feasible_rate"],
        })
    if not sample_frames:
        return
    combined = pd.concat(sample_frames, ignore_index=True)
    temporary = batch_dir / "sampling_feasibility.parquet.tmp"
    combined.to_parquet(temporary, index=False)
    os.replace(temporary, batch_dir / "sampling_feasibility.parquet")
    atomic_csv(
        batch_dir / "sampling_task_summary.csv", task_rows,
        ["run_id", "wp", "cfg", "fluid_hp", "fluid_he", "seed",
         "sample_count", "feasible_count", "failure_count", "feasible_rate"],
    )
    failure_spectrum = (
        combined.loc[~combined["feasible"], "primary_code"]
        .value_counts(dropna=False)
        .rename_axis("primary_code").reset_index(name="count")
    )
    atomic_csv(
        batch_dir / "failure_spectrum.csv",
        failure_spectrum.to_dict("records"), ["primary_code", "count"],
    )
    atomic_json(batch_dir / "s1_batch_summary.json", {
        "sample_count": len(combined),
        "task_count": len(task_rows),
        "feasible_count": int(combined["feasible"].sum()),
        "failure_count": int((~combined["feasible"]).sum()),
        "feasible_rate": float(combined["feasible"].mean()),
        "zero_feasible_tasks": sum(row["feasible_count"] == 0 for row in task_rows),
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=False)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--stage", default="DEV")
    parser.add_argument("--mode", choices=("s0", "s1", "optimize"), default="optimize")
    parser.add_argument("--wp", action="append")
    parser.add_argument("--cfg", action="append")
    parser.add_argument("--fluid-hp")
    parser.add_argument("--fluid-he")
    parser.add_argument("--pair-list", type=Path)
    parser.add_argument("--task-list", type=Path)
    parser.add_argument("--seed", action="append", type=int)
    parser.add_argument("--population-size", type=int)
    parser.add_argument("--generations", type=int)
    parser.add_argument("--archive-tol", type=float, default=1e-9)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--samples", type=int)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--task-timeout", type=float, default=86400.0)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker:
        return run_worker(args.worker)
    if args.config is None or args.data_root is None:
        parser.error("--config and --data-root are required")
    if not args.config.exists():
        parser.error(f"config does not exist: {args.config}")
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    config = load_config(args.config)
    args.samples = args.samples or int(
        config.get("experiment", {}).get("screening_points_per_pair", 256)
    )
    args.seed = args.seed or [int(config["optimization"].get("seed", 42))]
    args.population_size = args.population_size or int(config["optimization"]["population_size"])
    args.generations = args.generations or int(config["optimization"]["n_generations"])
    commit, dirty = git_info()
    formal = args.stage.upper() in {"S1", "S2", "S3", "S4", "S5"}
    if formal and dirty and not args.allow_dirty:
        parser.error("formal S1-S5 runs require a clean git worktree")
    if formal and config.get("experiment", {}).get("status") != "approved_for_full_run":
        parser.error(
            "formal S1-S5 runs require experiment.status=approved_for_full_run"
        )
    if args.resume_from and (
        len(args.wp or []) != 1 or len(args.cfg or []) != 1
        or not args.fluid_hp or not args.fluid_he or len(args.seed) != 1
    ):
        parser.error("--resume-from requires exactly one wp/cfg/fluid pair/seed task")
    if args.mode in {"s0", "s1"} and args.resume_from:
        parser.error("S0/S1 tasks do not use optimizer checkpoints")
    batch_id = f"BATCH_{safe_name(args.stage)}_{utc_stamp()}"
    batch_dir = args.data_root.resolve() / batch_id
    batch_dir.mkdir(parents=True, exist_ok=False)
    tasks = expand_tasks(args, config, batch_dir)
    batch_manifest = {
        "schema_version": "0.1", "batch_id": batch_id, "stage": args.stage,
        "status": "RUNNING", "git_commit": commit, "git_dirty": dirty,
        "config_path": str(args.config.resolve()), "config_sha256": sha256(args.config.resolve()),
        "workers": args.workers, "task_count": len(tasks), "start_time_utc": utc_now(),
    }
    atomic_json(batch_dir / "batch_manifest.json", batch_manifest)
    results = run_scheduler(tasks, args.workers, args.task_timeout)
    if args.mode == "s1":
        finalize_s1_batch(batch_dir, results)
    atomic_csv(batch_dir / "run_registry.csv", results, [
        "run_id", "stage", "wp", "cfg", "fluid_hp", "fluid_he", "seed",
        "scheduler_status", "terminal_status", "exit_code", "elapsed_s",
        "git_commit", "git_dirty", "config_sha256", "start_time_utc",
        "end_time_utc", "evaluation_count", "feasible_count", "failure_count",
        "pareto_size", "run_dir", "manifest_path", "detail",
    ])
    accepted = all(row["scheduler_status"] == "FINISHED" for row in results)
    batch_manifest.update({
        "status": "COMPUTE_COMPLETE" if accepted else "FAILED",
        "end_time_utc": utc_now(), "accepted_compute": accepted,
    })
    atomic_json(batch_dir / "batch_manifest.json", batch_manifest)
    print(f"batch={batch_id} tasks={len(tasks)} accepted_compute={accepted}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
