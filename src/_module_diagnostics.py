#!/usr/bin/env python3
"""
CBSim 求解器诊断模块 v0.2

v0.2 changes:
  - SolverDiagnostic.ok only False for severity="error" issues
  - primary_code uses cause-over-wrapper priority
  - backward-compatible to_dict()

Usage (embedded in HP/HE/CB classes):
    from _module_diagnostics import DiagnosticMixin, SolverIssue, SolverDiagnostic
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ═════════════════════════════════════════════════════════════════════════
# Priority rules for primary_code selection
# ═════════════════════════════════════════════════════════════════════════

# Low priority: wrapper / aggregation codes
WRAPPER_CODES = frozenset({
    'EVALUATE_CYCLE_EXCEPTION', 'UNKNOWN_EXCEPTION',
    'CB_SOLVER_ERROR', 'CB_CHILD_HP_ERROR', 'CB_CHILD_HE_ERROR',
    'PARAM_INVALID_VERSION',
})

# Medium priority: optimizer / config prechecks
PRECHECK_CODES = frozenset({
    'OPT_PRECHECK_STORAGE_TEMP_TOO_LOW',
    'FLUID_FILTER_TC_MARGIN_LOW',
    'KPI_SANITY_ETA_P2P_RANGE',
})

# High priority: thermodynamic cause codes (everything else is a cause)
# Recognized by pattern: HX_PINCH_*, RECUPERATOR_CONSTRAINT, SOLVER_RESIDUAL_TOO_HIGH,
# PHASE_*, PRESSURE_*, STATE_ENTROPY_ORDER, EFFICIENCY_NEGATIVE,
# REGIME_CRITICAL_TEMP_VIOLATION, COOLPROP_STATE_ERROR, SOLVER_FSOLVE_FAILED,
# SOLVER_MINIMIZE_FAILED, CB_STORAGE_TEMP_ORDER


def _is_cause_code(code: str) -> bool:
    """Return True if code is a thermodynamic cause (not a wrapper)."""
    if code in WRAPPER_CODES:
        return False
    if code in PRECHECK_CODES:
        return False  # prechecks are their own category, not thermodynamic causes
    return True


def compute_primary_code(issues: List['SolverIssue']) -> Optional[str]:
    """Select the most explanatory primary code from a list of issues.

    Priority:
      1. First thermodynamic cause code (non-wrapper, non-precheck)
      2. First precheck code
      3. First wrapper code
      4. None (if no issues)
    """
    best = None
    best_priority = 99  # lower = higher priority

    for issue in issues:
        code = issue.code
        if code in WRAPPER_CODES:
            prio = 3
        elif code in PRECHECK_CODES:
            prio = 2
        else:
            prio = 1  # thermodynamic cause
        if prio < best_priority:
            best_priority = prio
            best = code
            if prio == 1:
                break  # can't get better than cause code
    return best


# ═════════════════════════════════════════════════════════════════════════
# Data classes
# ═════════════════════════════════════════════════════════════════════════

@dataclass
class SolverIssue:
    """Single diagnostic issue captured during solver execution."""
    code: str
    component: str        # "HP" | "HE" | "CB" | "optimizer" | "config"
    cls: str              # class name
    method: str           # e.g. "check_consistency", "evaluate_cycle"
    message: str
    severity: str = "error"  # "error" | "warning"
    values: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SolverDiagnostic:
    """Aggregated diagnostics for one evaluation.

    ok=False only when severity="error" issues exist.
    primary_code is selected by cause-over-wrapper priority.
    """
    ok: bool = True
    primary_code: Optional[str] = None
    issues: List[SolverIssue] = field(default_factory=list)

    def add(self, issue: SolverIssue) -> None:
        """Add an issue. ok only goes False for error severity."""
        self.issues.append(issue)
        if issue.severity == "error":
            self.ok = False
        # primary_code is NOT auto-set here; caller should call recompute_primary()
        # For backward compat during HP/HE/CB check_consistency (which sets error+primary
        # via fail()), we do set primary_code on first issue if still None.
        if self.primary_code is None:
            self.primary_code = issue.code

    def recompute_primary(self) -> None:
        """Recompute primary_code using cause-over-wrapper priority."""
        self.primary_code = compute_primary_code(self.issues)

    def has_error(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "primary_code": self.primary_code,
            "n_issues": len(self.issues),
            "n_errors": self.error_count(),
            "n_warnings": self.warning_count(),
            "issues": [i.to_dict() for i in self.issues],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# ═════════════════════════════════════════════════════════════════════════
# Mixin
# ═════════════════════════════════════════════════════════════════════════

class DiagnosticMixin:
    """Mixin providing structured diagnostic recording for HP/HE/CB classes."""

    def _init_diagnostics(self):
        self.diagnostics = SolverDiagnostic()

    def _add_issue(self, code: str, component: str, method: str,
                   message: str, severity: str = "error", **values):
        issue = SolverIssue(
            code=code, component=component, cls=self.__class__.__name__,
            method=method, message=message, severity=severity, values=values,
        )
        self.diagnostics.add(issue)
        if severity == "error":
            self.error = True

    def fail(self, condition: bool, code: str, component: str,
             method: str, message: str, **values) -> bool:
        if condition:
            self._add_issue(code, component, method, message, **values)
        return condition

    def get_diagnostics(self) -> SolverDiagnostic:
        return self.diagnostics

    def get_diagnostics_dict(self) -> Dict[str, Any]:
        return self.diagnostics.to_dict()
