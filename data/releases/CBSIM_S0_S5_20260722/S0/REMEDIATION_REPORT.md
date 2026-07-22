# S0 native-crash and wrapper-error remediation

## Scope

- 15 S0 tasks that previously terminated with `SIGSEGV`
- 109 S0 tasks whose primary diagnosis was the wrapper code
  `EVALUATE_CYCLE_EXCEPTION`

## Changes

1. Hmass-P queries in the identified HP/HE discretization and expansion paths
   can use isolated, vectorized `PropsSI` calls instead of mutating the cycle's
   shared `AbstractState`.
2. The isolated path is enabled by fluid-role configuration. The current
   guarded set covers:
   - HP: Acetone
   - HE: R1234yf, R290, R600a, R245fa, R134a, R152A
3. Non-finite values, non-positive pressures and CoolProp input-domain
   exceptions are converted to explicit property-domain failures.
4. Optimizer diagnostics promote recognized CoolProp domain messages from
   wrapper codes to:
   - `COOLPROP_PROPERTY_INPUT_OUT_OF_RANGE`
   - `COOLPROP_PROPERTY_NONFINITE`
5. The large-scale runner now accepts an exact task-list CSV for targeted
   quarantine reruns.

## Final 124-case rerun

Batch: `BATCH_S0FINALFIX_20260716T110657Z`

- Planned / terminal: 124 / 124
- Scheduler normal exits: 124
- Native crashes: 0
- `COMPLETED`: 7
- Structured `EMPTY`: 117
- Output/checksum/linkage problems: 0

Root-cause coverage:

- `COOLPROP_PROPERTY_INPUT_OUT_OF_RANGE`: 109
- `RECUPERATOR_CONSTRAINT`: 5
- `SOLVER_RESIDUAL_TOO_HIGH`: 3
- feasible cases: 7
- wrapper-level primary codes remaining: 0

## Regression

- optimizer tests: 4/4 pass
- solver diagnostics tests: 6/6 pass
- solver diagnostics acceptance: 9/9 pass
- large-scale optimizer/checkpoint tests: pass

The original same-process acceptance suite now completes without a native
crash for the R134a and R152a cases.

## Interpretation

The 15 original process failures were numerical/property-state integration
failures, not evidence that those fluid pairs were thermodynamically
infeasible. After remediation, seven midpoint cases are feasible and the
remaining eight have explicit model-level causes.

The 109 wrapper cases are now consistently identified as property input-domain
failures. They remain S0 midpoint failures only and must not be used to reject
the complete fluid pair without S1 feasible-domain sampling.
