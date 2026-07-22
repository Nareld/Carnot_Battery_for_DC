#!/usr/bin/env python3
"""Crash-isolated scientific smoke tests for the CBSim evaluator API.

Every thermodynamic evaluation is executed in a fresh subprocess.  Native
CoolProp crashes, hangs, and ordinary model penalties therefore become
auditable case outcomes instead of terminating the complete test round.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any


HERE = Path(__file__).resolve().parent
NSGA_DIR = HERE.parent.parent
DEFAULT_CONFIG = NSGA_DIR / "optimization_config.json"
OBJECTIVES = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]
VARIABLE_NAMES = [
    "T_st_ht", "dT_st_sp", "dT_hp_cs_gl", "dT_hp_ev_sh",
    "dT_he_ev_sh", "dT_hp_cd_sc", "eta_max_cp", "eta_max_ex", "eta_pm",
]
WRAPPER_FAILURE_CODES = {
    None, "EVALUATE_CYCLE_EXCEPTION", "UNKNOWN_EXCEPTION", "CB_SOLVER_ERROR",
    "CB_CHILD_HP_ERROR", "CB_CHILD_HE_ERROR",
}


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _midpoint_case(config: dict[str, Any], wp_name: str, cfg_name: str,
                   fluid_hp: str, fluid_he: str) -> dict[str, Any]:
    wp = config["working_points"][wp_name]
    x = [
        (wp["T_st_ht_min"] + wp["T_st_ht_max"]) / 2,
        (wp["dT_st_sp_min"] + wp["dT_st_sp_max"]) / 2,
        10.0, 9.0, 1.75, 7.5, 0.80, 0.80, 0.50,
    ]
    return {
        "case_id": f"S0_{wp_name}_{cfg_name}_{fluid_hp}_{fluid_he}".replace("(", "").replace(")", ""),
        "wp": wp_name,
        "cb_config": cfg_name,
        "cb_class": config["configurations"][cfg_name]["class"],
        "fluid_hp": fluid_hp,
        "fluid_he": fluid_he,
        "x": x,
        "source": "S0_midpoint",
    }


def _s0_cases(config: dict[str, Any], wp_name: str, fluid_hp: str,
              fluid_he: str) -> list[dict[str, Any]]:
    return [
        _midpoint_case(config, wp_name, cfg_name, fluid_hp, fluid_he)
        for cfg_name in config["configurations"]
    ]


def _control_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "F01_basic_orc_dc_a_eta_control", "wp": "DC-A",
            "cb_config": "SBVCHP_SBORC", "cb_class": "SBVCHP_SBORC_STES2T",
            "fluid_hp": "R1233zd(E)", "fluid_he": "R1234ze(E)",
            "x": [78.72529620918931, 15.01512631335368, 3.8713981958780224,
                  3.8733494713448327, 2.9788446387723124, 14.925951089160543,
                  0.8953020257070974, 0.8999465563702256, 0.5395603834264513],
            "source": "acceptance_fixture",
        },
        {
            "case_id": "F02_recuperated_near_optimal_dc_a", "wp": "DC-A",
            "cb_config": "SRVCHP_SRORC", "cb_class": "SRVCHP_SRORC_STES2T",
            "fluid_hp": "R600", "fluid_he": "R227ea",
            "x": [118.528161, 54.883522, 0.853227, 3.059761, 2.897437,
                  14.593586, 0.899786, 0.899497, 0.540941],
            "source": "acceptance_fixture",
        },
        {
            "case_id": "F03_high_temp_sparse_dc_e", "wp": "DC-E",
            "cb_config": "SRVCHP_SBORC", "cb_class": "SRVCHP_SBORC_STES2T",
            "fluid_hp": "R1233zd(E)", "fluid_he": "R227ea",
            "x": [84.94297002813805, 25.458682793549865, 2.0441947592244354,
                  3.246685449856862, 1.089766475615736, 10.07256413579819,
                  0.893946127030495, 0.8924235743962952, 0.5465112348633678],
            "source": "acceptance_fixture",
        },
    ]


def _worker(case_path: Path, config_path: Path, result_path: Path) -> int:
    sys.path.insert(0, str(NSGA_DIR))
    from deap_optimizer import CBEvaluator, INFEASIBLE_PENALTY

    case = json.loads(case_path.read_text(encoding="utf-8"))
    config = _load_config(config_path)
    wp = config["working_points"][case["wp"]]
    cfg = dict(config["optimization"])
    cfg["diagnostics_enabled"] = True
    x = [float(value) for value in case["x"]]
    started = time.perf_counter()
    payload: dict[str, Any] = {"case": case, "status": "EXCEPTION"}
    try:
        evaluator = CBEvaluator(
            wp=wp, cfg=cfg, cb_class_name=case["cb_class"],
            fluid_hp=case["fluid_hp"], fluid_he=case["fluid_he"],
            objectives=OBJECTIVES,
        )
        bounds_ok = len(x) == len(VARIABLE_NAMES) and all(
            math.isfinite(value) and float(lo) <= value <= float(hi)
            for value, lo, hi in zip(x, evaluator.lb, evaluator.ub)
        )
        values = evaluator.evaluate(x)
        info = evaluator.last_eval_info
        finite = len(values) == 3 and all(math.isfinite(float(v)) for v in values)
        physical = finite and 0.01 < values[0] < 1.0 and values[1] > 0.0 and 0.0 < values[2] < 1.0
        penalized = any(value <= INFEASIBLE_PENALTY / 2 for value in values)
        passed = bounds_ok and bool(info.get("feasible")) and not penalized and physical
        payload.update({
            "status": "PASS" if passed else "MODEL_REJECTED",
            "bounds_ok": bounds_ok, "finite_kpis": finite,
            "physical_kpis": physical, "penalized": penalized,
            "objectives": dict(zip(OBJECTIVES, map(float, values))),
            "diagnostics": info,
        })
    except BaseException as exc:
        payload.update({"exception_type": type(exc).__name__, "exception": str(exc)[:1000]})
    payload["elapsed_s"] = time.perf_counter() - started
    _atomic_json(result_path, payload)
    return 0 if payload["status"] == "PASS" else 2


def _run_one(case: dict[str, Any], repeat: int, config_path: Path,
             output_dir: Path, timeout_s: float) -> dict[str, Any]:
    stem = f"{case['case_id']}_r{repeat:02d}"
    case_path = output_dir / "cases" / f"{stem}.input.json"
    result_path = output_dir / "cases" / f"{stem}.result.json"
    log_path = output_dir / "logs" / f"{stem}.log"
    _atomic_json(case_path, case)
    command = [sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()),
               "--worker", str(case_path), str(config_path), str(result_path)]
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s)
        elapsed = time.perf_counter() - started
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            if completed.returncode < 0:
                signum = -completed.returncode
                status = "NATIVE_CRASH"
                detail = signal.Signals(signum).name
            else:
                status = "WORKER_FAILED"
                detail = f"exit_{completed.returncode}"
            result = {"case": case, "status": status, "detail": detail}
        result.update({"repeat": repeat, "worker_exit_code": completed.returncode,
                       "wall_elapsed_s": elapsed, "log_path": str(log_path)})
        return result
    except subprocess.TimeoutExpired as exc:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        log_path.write_text(stdout + stderr, encoding="utf-8")
        return {"case": case, "status": "TIMEOUT", "repeat": repeat,
                "wall_elapsed_s": time.perf_counter() - started,
                "log_path": str(log_path)}


def _repeat_consistent(results: list[dict[str, Any]], rtol: float, atol: float) -> bool:
    if not results or len({row["status"] for row in results}) != 1:
        return False
    if results[0]["status"] == "MODEL_REJECTED":
        primary_codes = {row.get("diagnostics", {}).get("primary_code") for row in results}
        return len(primary_codes) == 1 and not (primary_codes & WRAPPER_FAILURE_CODES)
    if results[0]["status"] != "PASS":
        return False
    reference = results[0]["objectives"]
    return all(
        math.isclose(row["objectives"][name], reference[name], rel_tol=rtol, abs_tol=atol)
        for row in results[1:] for name in OBJECTIVES
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--suite", choices=("controls", "s0"), default="controls")
    parser.add_argument("--wp", default="DC-A")
    parser.add_argument("--fluid-hp", default="R1233zd(E)")
    parser.add_argument("--fluid-he", default="R1234ze(E)")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--rtol", type=float, default=1e-8)
    parser.add_argument("--atol", type=float, default=1e-10)
    parser.add_argument("--worker", nargs=3, metavar=("CASE", "CONFIG", "RESULT"))
    args = parser.parse_args()
    if args.worker:
        return _worker(*(Path(value) for value in args.worker))
    if args.output_dir is None:
        parser.error("--output-dir is required")
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")

    config_path = args.config.resolve()
    config = _load_config(config_path)
    cases = _control_cases() if args.suite == "controls" else _s0_cases(
        config, args.wp, args.fluid_hp, args.fluid_he)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict[str, Any]] = []
    case_summary: list[dict[str, Any]] = []
    for case in cases:
        repeats = []
        for repeat in range(1, args.repeat + 1):
            result = _run_one(case, repeat, config_path, output_dir, args.timeout)
            repeats.append(result)
            all_results.append(result)
            print(f"{case['case_id']} repeat={repeat}: {result['status']}", flush=True)
        consistent = _repeat_consistent(repeats, args.rtol, args.atol)
        if consistent and repeats[0]["status"] == "PASS":
            status = "FEASIBLE_STABLE"
        elif consistent and repeats[0]["status"] == "MODEL_REJECTED":
            status = "REJECTED_STABLE"
        else:
            status = "FAIL"
        case_summary.append({
            "case_id": case["case_id"], "status": status,
            "repeat_statuses": [row["status"] for row in repeats],
            "repeat_consistent": consistent,
        })

    manifest = {
        "schema_version": "0.1", "suite": args.suite,
        "python": sys.version, "config_path": str(config_path),
        "config_sha256": _sha256(config_path), "repeat": args.repeat,
        "timeout_s": args.timeout, "objectives": OBJECTIVES,
        "case_summary": case_summary,
        "accepted": all(
            row["status"] == "FEASIBLE_STABLE" if args.suite == "controls"
            else row["status"] in {"FEASIBLE_STABLE", "REJECTED_STABLE"}
            for row in case_summary
        ),
    }
    _atomic_json(output_dir / "manifest.json", manifest)
    _atomic_json(output_dir / "results.json", all_results)
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "status", "repeat_statuses", "repeat_consistent"])
        writer.writeheader()
        for row in case_summary:
            writer.writerow({**row, "repeat_statuses": ";".join(row["repeat_statuses"])})
    print(f"accepted={manifest['accepted']} output={output_dir}")
    return 0 if manifest["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
