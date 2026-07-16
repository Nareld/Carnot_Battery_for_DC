# CBSim scientific-test API contract

This note defines the narrow API used by `scientific_test_runner.py`.  The
runner deliberately avoids depending on internal heat-pump/heat-engine
objects because those objects are mutable during a solve.

## Stable optimization-level entry point

```python
evaluator = CBEvaluator(
    wp=working_point,
    cfg=optimization_config,
    cb_class_name="SBVCHP_SBORC_STES2T",
    fluid_hp="R1233zd(E)",
    fluid_he="R1234ze(E)",
    objectives=["eta_p2p", "energy_density_thermal", "exergy_efficiency"],
)
objectives = evaluator.evaluate(x)
```

`x` contains nine finite scalar values in this exact order:

1. `T_st_ht` [degC]
2. `dT_st_sp` [K]
3. `dT_hp_cs_gl` [K]
4. `dT_hp_ev_sh` [K]
5. `dT_he_ev_sh` [K]
6. `dT_hp_cd_sc` [K]
7. `eta_max_cp` [-]
8. `eta_max_ex` [-]
9. `eta_pm` [-]

The corresponding lower and upper bounds are available as `evaluator.lb`
and `evaluator.ub`.  A successful call returns a tuple with one finite value
per requested objective.  A model-level failure returns
`INFEASIBLE_PENALTY`; `evaluator.last_eval_info` provides the diagnostic
classification when diagnostics are enabled.

## CBSim-level constructor

The evaluator converts `x` into the CBSim constructor contract:

```text
CBClass(inputs_14_tuple, parameters_dict, options_dict).evaluate()
```

The primary scientific outputs used by the optimization layer are
`eta_cb_elec`, `E_dens_th`, and `eta_cb_exer`.  These are read only after
`error == False`.  Direct consumers must not reuse a CB, HP, HE, or
CoolProp `AbstractState` instance across independent evaluations.

## Isolation and acceptance rules

Each thermodynamic evaluation runs in a fresh subprocess.  This is required
because a native CoolProp failure cannot be caught by Python exceptions.
The parent process classifies normal, penalized, exception, timeout, and
signal-exit outcomes without losing already completed cases.

A scientific smoke-test case passes only when:

- all nine inputs are finite and within the evaluator bounds;
- the subprocess exits normally before its timeout;
- the evaluator reports `feasible=True` and no penalty;
- all three KPI values are finite;
- `0.01 < eta_p2p < 1`, energy density is positive, and
  `0 < exergy_efficiency < 1`;
- repeated evaluations agree within the configured absolute/relative
  tolerances.

Passing this smoke test demonstrates executable API and deterministic
baseline behavior.  It does not establish optimizer convergence or
engineering suitability of a fluid pair.
