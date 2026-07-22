# Formal S1 acceptance report

## Decision

**ACCEPTED as the formal S1 feasibility-screening dataset.**

The batch is suitable for S1 analysis and S2 candidate selection. A zero-hit
task remains a sparse-feasible-domain result, not proof of thermodynamic
infeasibility.

## Reproducible baseline

- Git commit: `99f4dac7e2f8c46cefda5be3369afab8246cfb60`
- Git dirty: false
- Config SHA-256:
  `04458d94dba01e985fd22679433a36dac3a3eeb5dba7981058bdd2f7a525d16e`
- Stage: S1
- Workers: 8
- Wall time: approximately 25 minutes 41 seconds

## Completion and integrity

- Tasks: 576/576 completed
- Samples: 147,456/147,456
- Feasible: 32,920
- Failed/infeasible: 114,536
- Overall feasible rate: 22.33%
- Native crashes/timeouts: 0
- Wrapper-level primary codes: 0
- Solver-attempt records: 17,093
- Zero-feasible tasks: 96
- Integrity/schema/checksum problems: 0
- Checksummed task content audited: approximately 0.888 GiB

All task CSV and Parquet files contain 256 unique Sobol sample identifiers.
Evaluation counts, failure JSON records, issue indexes and solver-attempt
foreign keys are consistent.

## Feasibility results

By working point:

- DC-B: 23.38%
- DC-D: 25.12%
- DC-F: 17.52%

By configuration:

- SBVCHP_SBORC: 28.77%
- SRVCHP_SRORC: 15.88%

The 96 zero-feasible tasks remain confined to SRVCHP_SRORC combined with
R1234yf, R134a, R152A or R290. Independent seed and 1024-point checks found
isolated feasible points in some nominally zero-hit strata. These tasks must
be marked sparse/quarantined rather than eliminated as physically impossible.

## Failure spectrum

- STATE_ENTROPY_ORDER: 57,551
- RECUPERATOR_CONSTRAINT: 23,424
- SOLVER_RESIDUAL_TOO_HIGH: 16,857
- HX_PINCH_HE_EVAP: 11,265
- HX_PINCH_HE_COND: 1,645
- COOLPROP_PROPERTY_INPUT_OUT_OF_RANGE: 1,591
- HX_PINCH_HP_COND: 1,092
- PHASE_WET_EXPANSION: 485
- KPI_SANITY_ETA_P2P_RANGE: 389
- SOLVER_INITIAL_GUESS_OUT_OF_BOUNDS: 236
- COOLPROP_BACKEND_TWOPHASE_UNSUPPORTED: 1

All codes are specific root-cause or guard codes; no generic wrapper remains.

## Comparison with S1DEV

- Task feasible-rate correlation: 0.9941
- Mean absolute feasible-rate difference: 0.0061
- Zero-feasible task count: 96 in both datasets

The largest shifts occur for SRVCHP_SRORC with R600a after correcting the ORC
pressure-solver bounds. The formal dataset supersedes S1DEV for downstream
selection.

## S2 use

S2 selection should combine:

1. feasible-rate tier;
2. KPI coverage among feasible S1 points;
3. failure-spectrum severity;
4. fluid engineering status;
5. explicit retention of efficiency, density and exergy extremes.

Do not select only by feasible rate, and do not advance zero-hit tasks unless
they are retained as a dedicated sparse-domain mechanism study.
