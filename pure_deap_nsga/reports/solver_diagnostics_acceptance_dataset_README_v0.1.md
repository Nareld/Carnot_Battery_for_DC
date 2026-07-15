# Solver Diagnostics Acceptance Dataset v0.1

This dataset fixes the acceptance cases for the first-round solver diagnostics review. It is built from existing Pareto / near-optimal solution sets and the thermodynamic infeasibility conclusions in `pure_deap_nsga/reports/infeasibility_statistical_diagnosis.md`.

## Files

- Dataset: `pure_deap_nsga/reports/solver_diagnostics_acceptance_dataset_v0.1.csv`
- Observed run with current implementation: `pure_deap_nsga/reports/solver_diagnostics_acceptance_observed_v0.1.csv`

## Dataset Composition

- Total cases: 9
- Executable by `CBEvaluator`: 8
- Expected feasible controls: 3
- Expected infeasible / metadata cases: 6

## Case Families

1. Feasible controls from existing Pareto and near-optimal solutions: SBORC baseline, SRORC near-optimal, high-temperature sparse feasible case.
2. Optimizer pre-check case: low storage temperature.
3. Thermodynamic infeasibility cases from prior analysis: SRORC + R152a wet-fluid fragility, SRORC + R134a summer recuperator conflict, recuperator boundary failure, extreme spread residual failure.
4. Metadata filter reference: R600a critical-temperature margin filtering. This is not executed by `CBEvaluator` in round 1 and is kept as a round-2 configuration-layer diagnostic target.

## Current Observed Result

Executable cases passing basic expectation under current Claude implementation: 8/8.

For feasible cases, warning-level issues are acceptable; error-level issues are not. For infeasible cases, the acceptance check requires at least one expected issue code or expected primary code to appear.

This is a coarse first-round pass, not full approval of diagnostic quality. In the current observed file, several thermodynamic infeasibility cases still report `EVALUATE_CYCLE_EXCEPTION` as the primary code, while the scientifically useful causes such as `RECUPERATOR_CONSTRAINT` and `SOLVER_RESIDUAL_TOO_HIGH` appear only as child issue codes. For future infeasibility-library work, these child causes should be promoted or ranked so the primary diagnosis supports direct statistical aggregation.

## Round-2 Tightening Criteria

- Feasible controls must remain feasible and must contain zero error-level issues.
- Warning-only feasible controls are acceptable, but warning volume and warning code types should be tracked separately from solver errors.
- Infeasible cases should expose a thermodynamic cause code as the primary or top-ranked non-wrapper issue whenever available.
- Wrapper codes such as `EVALUATE_CYCLE_EXCEPTION` and `UNKNOWN_EXCEPTION` should not be the only machine-actionable cause when child diagnostics exist.
- The metadata case `M01_fluid_filter_r600a_tc_margin` should become executable after configuration-layer fluid filtering diagnostics are added.
- The same dataset should be run against all currently optimized CB classes before broad-spectrum fluid-pair screening.

## Intended Use

Use this dataset as the fixed regression suite for Codex approval and future Claude Code iterations. A future executable test can iterate over rows where `executable_by_cbevaluator=True`, run `CBEvaluator.evaluate()`, and compare `last_eval_info` against `expected_feasible`, `expected_primary_code_set`, and `expected_issue_code_contains`.
