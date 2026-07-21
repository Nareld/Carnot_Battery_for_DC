#!/usr/bin/env python3
"""Crash-isolated independent physical revalidation of S4 representatives."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any
import warnings

import numpy as np
import pandas as pd
import CoolProp.CoolProp as CP


HERE = Path(__file__).resolve().parent
NSGA_DIR = HERE.parent.parent
REPOSITORY = NSGA_DIR.parent
OBJECTIVES = ["eta_p2p", "energy_density_thermal", "exergy_efficiency"]
VARIABLES = [
    "T_st_ht", "dT_st_sp", "dT_hp_cs_gl", "dT_hp_ev_sh",
    "dT_he_ev_sh", "dT_hp_cd_sc", "eta_max_cp", "eta_max_ex", "eta_pm",
]
ALGORITHM = "s5_independent_physical_revalidation_v1"
KPI_RTOL = 1.0e-8
KPI_ATOL = 1.0e-10
CLOSURE_RTOL = 1.0e-10


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def relative_closure(left: list[float], right: list[float]) -> tuple[float, float]:
    residual = float(sum(left) - sum(right))
    scale = max(sum(abs(value) for value in left + right), 1.0)
    return residual, abs(residual) / scale


def physical_evidence(cb, stored_kpis: dict[str, float], computed_kpis: dict[str, float]) -> dict:
    """Extract explicit physical gates from a freshly evaluated CBSim object."""
    hp, he = cb.my_HP, cb.my_HE
    diagnostics = cb.get_diagnostics().to_dict()
    error_codes = [
        issue["code"] for issue in diagnostics["issues"]
        if issue.get("severity", "error") == "error"
    ]

    closures = {}
    hp_regenerator_exergy = float(getattr(hp, "loss_hp_regex", 0.0))
    he_regenerator_exergy = float(getattr(he, "loss_he_regex", 0.0))
    closure_specs = {
        "hp_energy": ([hp.q_out_hp_en, hp.w_out_hp_en], [hp.q_in_hp_en, hp.w_in_hp_en]),
        "he_energy": ([he.q_in_he_en, he.w_in_he_en], [he.q_out_he_en, he.w_out_he_en]),
        "hp_exergy_state_identity": (
            [hp.q_out_hp_ex, hp.w_out_hp_ex, hp_regenerator_exergy],
            [hp.q_in_hp_ex, hp.w_in_hp_ex],
        ),
        "he_exergy_state_identity": (
            [he.q_in_he_ex, he.w_in_he_ex],
            [he.q_out_he_ex, he.w_out_he_ex, he_regenerator_exergy],
        ),
    }
    for name, (left, right) in closure_specs.items():
        residual, relative = relative_closure(
            [float(value) for value in left], [float(value) for value in right]
        )
        closures[name] = {"residual": residual, "relative_residual": relative}

    pinch_margins = {
        "hp_evap_cold_end": (hp.T_hp_cs_ex - hp.T_hp_4, hp.parameters["dT_hp_ev_pp"]),
        "hp_evap_hot_end": (hp.T_hp_cs_su - hp.T_hp_1, hp.parameters["dT_hp_ev_pp"]),
        "hp_cond_cold_end": (hp.T_hp_2 - hp.T_hp_hs_ex, hp.parameters["dT_hp_cd_pp"]),
        "hp_cond_hot_end": (hp.T_hp_3 - hp.T_hp_hs_su, hp.parameters["dT_hp_cd_pp"]),
        "hp_cond_internal": (hp.T_wi - hp.T_hi, hp.parameters["dT_hp_cd_pp"]),
        "he_evap_cold_end": (he.T_he_hs_ex - he.T_he_2, he.parameters["dT_he_ev_pp"]),
        "he_evap_hot_end": (he.T_he_hs_su - he.T_he_3, he.parameters["dT_he_ev_pp"]),
        "he_evap_internal": (he.T_hi - he.T_wh, he.parameters["dT_he_ev_pp"]),
        "he_cond_cold_end": (he.T_he_4 - he.T_he_cs_ex, he.parameters["dT_he_cd_pp"]),
        "he_cond_hot_end": (he.T_he_1 - he.T_he_cs_su, he.parameters["dT_he_cd_pp"]),
        "he_cond_internal": (he.T_he_4x - he.T_ci, he.parameters["dT_he_cd_pp"]),
    }
    pinch = {
        name: {
            "actual_K": float(actual), "required_K": float(required),
            "model_tolerance_required_K": float(0.95 * required),
            "model_tolerance_pass": bool(actual >= 0.95 * required),
            "strict_pass": bool(actual >= required - 1.0e-6),
        }
        for name, (actual, required) in pinch_margins.items()
    }

    hp_pressures = [hp.p_hp_1, hp.p_hp_2, hp.p_hp_3, hp.p_hp_4]
    he_pressures = [he.p_he_1, he.p_he_2, he.p_he_3, he.p_he_4]
    pressure = {
        "hp_state_pressures_Pa": [float(value) for value in hp_pressures],
        "he_state_pressures_Pa": [float(value) for value in he_pressures],
        "hp_compression_ratio": float(hp.comp_ratio),
        "he_expansion_ratio": float(he.exp_ratio),
        "hp_high_pressure_Pa": float(hp.p_hp_2x),
        "hp_minimum_high_pressure_Pa": float(hp.p_hp_2x_min),
        "he_low_pressure_Pa": float(he.p_he_1x),
        "he_minimum_low_pressure_Pa": float(he.p_he_1x_min),
        "he_high_pressure_Pa": float(he.p_he_3x),
        "he_maximum_high_pressure_Pa": float(he.p_he_3x_max),
    }
    pressure_gate = bool(
        all(math.isfinite(float(value)) and value > 0 for value in hp_pressures + he_pressures)
        and 1.0 < hp.comp_ratio <= 50.0 and 1.0 < he.exp_ratio <= 50.0
        and hp.p_hp_2x >= hp.p_hp_2x_min
        and he.p_he_1x >= 0.99 * he.p_he_1x_min
        and he.p_he_3x <= he.p_he_3x_max
    )

    def state_point(component: str, state: int, fluid: str, pressure, enthalpy) -> dict:
        pressure, enthalpy = float(pressure), float(enthalpy)
        return {
            "component": component, "state": state, "fluid": fluid,
            "pressure_Pa": pressure, "enthalpy_J_kg": enthalpy,
            "temperature_K": float(CP.PropsSI("T", "P", pressure, "Hmass", enthalpy, fluid)),
            "entropy_J_kgK": float(CP.PropsSI("Smass", "P", pressure, "Hmass", enthalpy, fluid)),
            "density_kg_m3": float(CP.PropsSI("Dmass", "P", pressure, "Hmass", enthalpy, fluid)),
            "quality": float(CP.PropsSI("Q", "P", pressure, "Hmass", enthalpy, fluid)),
            "phase": str(CP.PhaseSI("P", pressure, "Hmass", enthalpy, fluid)),
        }

    state_points = [
        state_point("HP", state, hp.parameters["fluid_hp"],
                    getattr(hp, f"p_hp_{state}"), getattr(hp, f"i_hp_{state}"))
        for state in range(1, 5)
    ] + [
        state_point("HE", state, he.parameters["fluid_he"],
                    getattr(he, f"p_he_{state}"), getattr(he, f"i_he_{state}"))
        for state in range(1, 5)
    ]
    expansion_path = []
    for index, pressure_value in enumerate(np.linspace(he.p_he_3, he.p_he_4, 50)):
        pressure_value = float(pressure_value)
        isentropic_h = float(CP.PropsSI(
            "Hmass", "P", pressure_value, "Smass", he.s_he_3, he.parameters["fluid_he"]
        ))
        enthalpy_value = float(
            he.i_he_3 - he.eta_is_ex * (he.i_he_3 - isentropic_h)
        )
        expansion_path.append(state_point(
            "HE_EXPANSION", index, he.parameters["fluid_he"], pressure_value, enthalpy_value
        ))
    phase_error_codes = [code for code in error_codes if code.startswith("PHASE_")]
    hp_inlet_phase = state_points[0]["phase"]
    wet_expansion_count = sum(
        point["phase"] == "twophase" or 0.0 < point["quality"] < 1.0
        for point in expansion_path
    )
    phase = {
        "hp_compressor_inlet_phase": hp_inlet_phase,
        "hp_post_expansion_quality": float(hp.x_hp_4),
        "he_expansion_wet_point_count": int(wet_expansion_count),
        "phase_error_codes": phase_error_codes,
        "he_expansion_path": expansion_path,
    }
    finite_state_gate = all(
        math.isfinite(point[field])
        for point in state_points + expansion_path
        for field in ["pressure_Pa", "enthalpy_J_kg", "temperature_K",
                      "entropy_J_kgK", "density_kg_m3", "quality"]
    )
    phase_gate = bool(
        finite_state_gate and hp_inlet_phase in {"gas", "supercritical_gas"}
        and 0.0 <= hp.x_hp_4 <= 1.0 and wet_expansion_count == 0
        and not phase_error_codes
    )

    exergy_loss_groups = {
        "hp_compressor": float(hp.loss_hp_compex),
        "hp_valve": float(hp.loss_hp_valvex),
        "hp_evaporator_and_source": float(hp.loss_hp_evapex + hp.loss_hp_srcex),
        "hp_condenser": float(hp.loss_hp_condex),
        "hp_regenerator": hp_regenerator_exergy,
        "he_pump": float(he.loss_he_pumpex),
        "he_expander": float(he.loss_he_expex),
        "he_evaporator_and_source": float(he.loss_he_evapex + he.loss_he_srcex),
        "he_condenser_and_sink": float(he.loss_he_condex + he.loss_he_sinkex),
        "he_regenerator": he_regenerator_exergy,
    }
    exergy_scale = max(
        abs(float(hp.pow_hp_supplex)), abs(float(he.pow_he_supplex)), 1.0
    )
    exergy_losses_pass = all(
        math.isfinite(value) and value >= -1.0e-6 * exergy_scale
        for value in exergy_loss_groups.values()
    )
    recomputed_cb_exergy_efficiency = float(
        (he.w_net_he_en / he.f_he_hs * hp.f_hp_hs / hp.f_hp_cs)
        / (hp.pow_hp_supplex / hp.f_hp_cs)
    )
    exergy_efficiency_pass = math.isclose(
        recomputed_cb_exergy_efficiency, computed_kpis["exergy_efficiency"],
        rel_tol=KPI_RTOL, abs_tol=KPI_ATOL,
    )

    kpi_comparison = {}
    for name in OBJECTIVES:
        stored, computed = float(stored_kpis[name]), float(computed_kpis[name])
        kpi_comparison[name] = {
            "s4_value": stored, "s5_value": computed,
            "absolute_difference": abs(computed - stored),
            "pass": math.isclose(computed, stored, rel_tol=KPI_RTOL, abs_tol=KPI_ATOL),
        }
    kpi_physical = bool(
        0.01 < computed_kpis["eta_p2p"] < 1.0
        and 0.0 < computed_kpis["energy_density_thermal"] <= 50.0
        and 0.0 < computed_kpis["exergy_efficiency"] < 1.0
    )
    gates = {
        "solver": bool(not cb.error and diagnostics["n_errors"] == 0),
        "energy_conservation": all(
            closures[name]["relative_residual"] <= CLOSURE_RTOL
            for name in ["hp_energy", "he_energy"]
        ),
        "exergy_consistency": all(
            closures[name]["relative_residual"] <= CLOSURE_RTOL
            for name in ["hp_exergy_state_identity", "he_exergy_state_identity"]
        ) and exergy_losses_pass and exergy_efficiency_pass,
        "phase": phase_gate,
        "pinch_strict": all(item["strict_pass"] for item in pinch.values()),
        "pressure": pressure_gate,
        "kpi": kpi_physical and all(item["pass"] for item in kpi_comparison.values()),
        "solver_residuals": bool(
            abs(float(hp.resi)) <= 1.0
            and abs(float(he.resi_1)) <= 1.0e-2
            and abs(float(he.resi_2)) <= 1.0e-2
        ),
        "state_points": finite_state_gate,
    }
    return {
        "diagnostics": diagnostics, "closures": closures, "pinch": pinch,
        "pressure": pressure, "phase": phase, "state_points": state_points,
        "exergy_loss_groups": exergy_loss_groups,
        "recomputed_cb_exergy_efficiency": recomputed_cb_exergy_efficiency,
        "solver_residuals": {
            "hp": float(hp.resi), "he_1": float(he.resi_1), "he_2": float(he.resi_2),
        },
        "kpi_comparison": kpi_comparison,
        "gates": gates, "passed": all(gates.values()),
    }


def run_worker(task_path: Path, config_path: Path, result_path: Path) -> int:
    sys.path.insert(0, str(NSGA_DIR))
    from deap_optimizer import CBEvaluator, OBJECTIVE_MAP

    task = json.loads(task_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    row = task["representative"]
    started = time.perf_counter()
    payload: dict[str, Any] = {"task": task, "status": "EXCEPTION"}
    try:
        optimization = dict(config["optimization"])
        optimization["diagnostics_enabled"] = True
        evaluator = CBEvaluator(
            wp=config["working_points"][row["wp"]], cfg=optimization,
            cb_class_name=config["configurations"][row["cfg"]]["class"],
            fluid_hp=row["fluid_hp"], fluid_he=row["fluid_he"],
            objectives=OBJECTIVES,
        )
        x = [float(row[name]) for name in VARIABLES]
        bounds_gate = bool(all(
            math.isfinite(value) and float(lower) <= value <= float(upper)
            for value, lower, upper in zip(x, evaluator.lb, evaluator.ub)
        ))
        inputs, parameters, options = evaluator._build_inputs_params(x)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cb = evaluator.cb_class(inputs, parameters, options)
            cb.evaluate()
        computed = {name: float(OBJECTIVE_MAP[name](cb)) for name in OBJECTIVES}
        evidence = physical_evidence(
            cb, {name: float(row[name]) for name in OBJECTIVES}, computed
        )
        evidence["gates"]["decision_bounds"] = bounds_gate
        evidence["passed"] = all(evidence["gates"].values())
        payload.update({
            "status": "PASS" if evidence["passed"] else "PHYSICAL_GATE_FAILED",
            "computed_kpis": computed, "physical_evidence": evidence,
            "warnings": [str(item.message)[:500] for item in caught],
        })
    except BaseException as exc:
        payload.update({
            "exception_type": type(exc).__name__, "exception": str(exc)[:2000],
        })
    payload["elapsed_s"] = time.perf_counter() - started
    atomic_json(result_path, payload)
    return 0 if payload["status"] == "PASS" else 2


def execute_repeat(task: dict, repeat: int, config_path: Path,
                   output_dir: Path, timeout_s: float) -> dict:
    stem = f"{task['representative']['representative_id']}_r{repeat:02d}"
    task_path = output_dir / "tasks" / f"{stem}.input.json"
    result_path = output_dir / "evidence" / f"{stem}.json"
    log_path = output_dir / "logs" / f"{stem}.log"
    repeat_task = {**task, "repeat": repeat}
    atomic_json(task_path, repeat_task)
    command = [
        sys.executable, "-X", "faulthandler", str(Path(__file__).resolve()),
        "--worker-task", str(task_path), "--worker-config", str(config_path),
        "--worker-result", str(result_path),
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s)
        atomic_text(log_path, completed.stdout + completed.stderr)
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        elif completed.returncode < 0:
            result = {
                "status": "NATIVE_CRASH",
                "detail": signal.Signals(-completed.returncode).name,
            }
        else:
            result = {"status": "WORKER_FAILED", "detail": f"exit_{completed.returncode}"}
        result.update({
            "worker_exit_code": completed.returncode,
            "wall_elapsed_s": time.perf_counter() - started,
            "evidence_path": str(result_path.resolve()), "log_path": str(log_path.resolve()),
        })
        return result
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        atomic_text(log_path, stdout + stderr)
        return {
            "status": "TIMEOUT", "wall_elapsed_s": time.perf_counter() - started,
            "evidence_path": str(result_path.resolve()), "log_path": str(log_path.resolve()),
        }


def repeat_consistent(results: list[dict]) -> bool:
    if len(results) < 2 or any(result.get("status") != "PASS" for result in results):
        return False
    first = results[0]["computed_kpis"]
    return all(
        math.isclose(
            result["computed_kpis"][name], first[name],
            rel_tol=KPI_RTOL, abs_tol=KPI_ATOL,
        )
        for result in results[1:] for name in OBJECTIVES
    )


def verify_representative_sources(accepted_dir: Path, accepted: dict,
                                  representatives: pd.DataFrame) -> None:
    registry_path = accepted_dir / "accepted_run_registry.csv"
    expected_hash = accepted["output_sha256"].get(registry_path.name)
    if not registry_path.is_file() or sha256_file(registry_path) != expected_hash:
        raise ValueError("S5_ACCEPTED_REGISTRY_HASH_MISMATCH")
    registry = pd.read_csv(registry_path).set_index("run_id")
    for row in representatives.to_dict("records"):
        source_run_id = row["source_run_id"]
        if source_run_id not in registry.index:
            raise ValueError(f"S5_SOURCE_RUN_NOT_CANONICAL: {source_run_id}")
        source = registry.loc[source_run_id]
        if row["source_manifest_sha256"] != source["manifest_sha256"] \
        or row["source_pareto_sha256"] != source["pareto_sha256"]:
            raise ValueError(f"S5_SOURCE_HASH_LINEAGE_MISMATCH: {source_run_id}")
        pareto_path = Path(source["run_dir"]) / "outputs" / "pareto.csv"
        if sha256_file(pareto_path) != row["source_pareto_sha256"]:
            raise ValueError(f"S5_SOURCE_PARETO_HASH_MISMATCH: {source_run_id}")
        pareto = pd.read_csv(pareto_path)
        index = int(row["source_pareto_row_index"])
        if not 0 <= index < len(pareto):
            raise ValueError(f"S5_SOURCE_PARETO_ROW_INVALID: {source_run_id}")
        source_point = pareto.iloc[index]
        if not all(math.isclose(
            float(row[name]), float(source_point[name]), rel_tol=1e-13, abs_tol=1e-13
        ) for name in VARIABLES + OBJECTIVES):
            raise ValueError(f"S5_SOURCE_POINT_VALUE_MISMATCH: {source_run_id}")
        payload = {name: float(row[name]) for name in VARIABLES + OBJECTIVES}
        point_hash = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
        if point_hash != row["point_sha256"]:
            raise ValueError(f"S5_SOURCE_POINT_HASH_MISMATCH: {source_run_id}")


def revalidate(accepted_dir: Path, config_path: Path, output_dir: Path,
               repeats: int = 2, timeout_s: float = 120.0,
               smoke_limit: int | None = None, require_clean_git: bool = True) -> dict:
    accepted_manifest_path = accepted_dir / "accepted_manifest.json"
    representatives_path = accepted_dir / "s5_representative_points.csv"
    accepted = json.loads(accepted_manifest_path.read_text(encoding="utf-8"))
    formal = smoke_limit is None
    allowed_statuses = {"ACCEPTED_FOR_S5"} if formal else {
        "ACCEPTED_FOR_S5", "DEVELOPMENT_ACCEPTANCE"
    }
    if accepted.get("status") not in allowed_statuses:
        raise ValueError("S5_REQUIRES_ACCEPTED_S4_MANIFEST")
    if formal and (not require_clean_git or accepted.get("git_dirty")):
        raise ValueError("S5_FORMAL_REJECTS_DIRTY_OR_DEVELOPMENT_ACCEPTANCE")
    if sha256_file(config_path) != accepted.get("config_sha256"):
        raise ValueError("S5_CONFIG_HASH_MISMATCH")
    expected_representatives_hash = accepted["output_sha256"][representatives_path.name]
    if sha256_file(representatives_path) != expected_representatives_hash:
        raise ValueError("S5_REPRESENTATIVE_INPUT_HASH_MISMATCH")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True).strip()
    dirty = bool(subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=REPOSITORY, text=True
    ).strip())
    if require_clean_git and (dirty or commit != accepted.get("git_commit")):
        raise ValueError("S5_REQUIRES_ACCEPTED_CLEAN_GIT_COMMIT")
    if repeats < 2:
        raise ValueError("S5_REQUIRES_AT_LEAST_TWO_INDEPENDENT_REPEATS")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"S5_OUTPUT_NOT_EMPTY: {output_dir}")

    representatives = pd.read_csv(representatives_path).sort_values("representative_id")
    if len(representatives) != 18 or representatives.representative_id.duplicated().any():
        raise ValueError("S5_REPRESENTATIVE_COUNT_OR_ID_INVALID")
    verify_representative_sources(accepted_dir, accepted, representatives)
    if smoke_limit is not None:
        if smoke_limit < 1:
            raise ValueError("S5_SMOKE_LIMIT_MUST_BE_POSITIVE")
        representatives = representatives.head(smoke_limit)
    output_dir.mkdir(parents=True, exist_ok=True)
    accepted_hash = sha256_file(accepted_manifest_path)
    summaries = []
    run_rows, state_rows, pinch_rows = [], [], []
    balance_rows, phase_rows, diagnostic_rows = [], [], []
    for raw_row in representatives.to_dict("records"):
        row = {
            key: (None if pd.isna(value) else value.item()
                  if isinstance(value, np.generic) else value)
            for key, value in raw_row.items()
        }
        task = {
            "schema_version": "1.0", "algorithm": ALGORITHM,
            "accepted_s4_manifest": str(accepted_manifest_path.resolve()),
            "accepted_s4_manifest_sha256": accepted_hash,
            "representative_input_sha256": expected_representatives_hash,
            "representative": row,
        }
        results = [
            execute_repeat(task, repeat, config_path, output_dir, timeout_s)
            for repeat in range(1, repeats + 1)
        ]
        for repeat, result in enumerate(results, start=1):
            evidence = result.get("physical_evidence", {})
            base = {
                "representative_id": row["representative_id"], "repeat": repeat,
                "wp": row["wp"], "representative_type": row["representative_type"],
            }
            run_rows.append({
                **base, "status": result.get("status", "UNKNOWN"),
                "worker_exit_code": result.get("worker_exit_code"),
                "wall_elapsed_s": result.get("wall_elapsed_s"),
                "evidence_path": result.get("evidence_path"),
                "log_path": result.get("log_path"),
                "gates_json": json.dumps(evidence.get("gates", {}), sort_keys=True),
            })
            for point in evidence.get("state_points", []):
                state_rows.append({**base, **point})
            for name, item in evidence.get("pinch", {}).items():
                pinch_rows.append({**base, "location": name, **item})
            for name, item in evidence.get("closures", {}).items():
                balance_rows.append({**base, "balance": name, **item})
            for point in evidence.get("phase", {}).get("he_expansion_path", []):
                phase_rows.append({**base, **point})
            for issue in evidence.get("diagnostics", {}).get("issues", []):
                diagnostic_rows.append({
                    **base, **{key: issue.get(key) for key in [
                        "code", "severity", "component", "cls", "method", "message"
                    ]}, "values_json": json.dumps(issue.get("values", {}), sort_keys=True),
                })
        consistent = repeat_consistent(results)
        first = results[0]
        gates = first.get("physical_evidence", {}).get("gates", {})
        summaries.append({
            "representative_id": row["representative_id"], "wp": row["wp"],
            "representative_type": row["representative_type"], "cfg": row["cfg"],
            "fluid_hp": row["fluid_hp"], "fluid_he": row["fluid_he"],
            "source_run_id": row["source_run_id"],
            "accepted_s4_manifest_sha256": accepted_hash,
            **{f"gate_{name}": bool(value) for name, value in gates.items()},
            "repeat_consistent": consistent,
            "status": "PASS" if consistent and all(gates.values()) else "FAILED",
            "repeat_statuses": ";".join(result.get("status", "UNKNOWN") for result in results),
            "evidence_paths": ";".join(result["evidence_path"] for result in results),
        })
    summary = pd.DataFrame(summaries)
    tables = {
        "s5_evidence_summary.csv": summary,
        "s5_run_registry.csv": pd.DataFrame(run_rows),
        "representative_evidence.csv": summary.copy(),
        "state_points.csv": pd.DataFrame(state_rows),
        "pinch_evidence.csv": pd.DataFrame(pinch_rows),
        "balance_evidence.csv": pd.DataFrame(balance_rows),
        "phase_path.csv": pd.DataFrame(phase_rows),
        "diagnostic_issues.csv": pd.DataFrame(diagnostic_rows, columns=[
            "representative_id", "repeat", "wp", "representative_type",
            "code", "severity", "component", "cls", "method", "message", "values_json",
        ]),
    }
    for name, table in tables.items():
        atomic_text(output_dir / name, table.to_csv(index=False, lineterminator="\n"))
    all_pass = bool(len(summary) and (summary.status == "PASS").all())
    status = "S5_ACCEPTED" if formal and all_pass else "SMOKE_PASS" if all_pass else "S5_FAILED"
    artifact_hashes = {
        name: sha256_file(output_dir / name) for name in tables
    }
    for directory in ["tasks", "evidence", "logs"]:
        for path in sorted((output_dir / directory).glob("*")):
            if path.is_file():
                artifact_hashes[str(path.relative_to(output_dir))] = sha256_file(path)
    manifest = {
        "schema_version": "1.0", "algorithm": ALGORITHM, "status": status,
        "formal": formal, "representative_count": len(summary), "repeat_count": repeats,
        "passed_representatives": int((summary.status == "PASS").sum()),
        "git_commit": commit, "git_dirty": dirty,
        "accepted_s4_manifest": str(accepted_manifest_path.resolve()),
        "accepted_s4_manifest_sha256": accepted_hash,
        "config": str(config_path.resolve()), "config_sha256": sha256_file(config_path),
        "thresholds": {
            "closure_relative_tolerance": CLOSURE_RTOL,
            "kpi_relative_tolerance": KPI_RTOL, "kpi_absolute_tolerance": KPI_ATOL,
            "pinch_formal_gate": "actual_K >= required_K - 1e-6 K",
            "pinch_legacy_model_tolerance_factor_reported_only": 0.95,
            "maximum_pressure_ratio": 50.0,
        },
        "environment": {
            "python": platform.python_version(), "numpy": np.__version__,
            "coolprop": __import__("CoolProp").__version__,
            "pandas": pd.__version__,
        },
        "output_sha256": artifact_hashes,
        "scientific_scope": "Independent physical revalidation; engineering recommendation requires all formal gates to pass",
    }
    atomic_json(output_dir / "s5_manifest.json", manifest)
    report = f"""# S5 Independent Physical Revalidation

Status: **{status}**

- Representatives checked: {len(summary)}
- Independent repeats per point: {repeats}
- Passing representatives: {int((summary.status == 'PASS').sum())}
- Gates: solver/residual, energy closure, exergy consistency, state/phase path,
  strict pinch, pressure, KPI/source identity and repeat consistency
"""
    atomic_text(output_dir / "S5_REVALIDATION_REPORT.md", report)
    if not all_pass:
        raise ValueError("S5_PHYSICAL_REVALIDATION_FAILED")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--smoke-limit", type=int)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--worker-task", type=Path)
    parser.add_argument("--worker-config", type=Path)
    parser.add_argument("--worker-result", type=Path)
    args = parser.parse_args()
    if args.worker_task:
        if not args.worker_config or not args.worker_result:
            parser.error("worker mode requires --worker-config and --worker-result")
        return run_worker(args.worker_task, args.worker_config, args.worker_result)
    if not args.accepted_dir or not args.config or not args.output_dir:
        parser.error("batch mode requires --accepted-dir, --config and --output-dir")
    result = revalidate(
        args.accepted_dir, args.config, args.output_dir,
        repeats=args.repeats, timeout_s=args.timeout_s,
        smoke_limit=args.smoke_limit, require_clean_git=not args.allow_dirty,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
