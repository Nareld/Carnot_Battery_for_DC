# S3 Candidate Selection Report

Status: **S3 completed; candidates are unconfirmed until S4**

- Accepted S2 runs verified: 318
- Certified S2 Pareto points verified: 357599
- Selection units: 12 (`WP × observed configuration`)
- Selected candidates: 60 (5 per unit)
- Generated S4 tasks: 300 (5 independent seeds per candidate)
- Observed configurations: SBVCHP_SBORC, SRVCHP_SRORC
- Unobserved configurations (not inferred): SBVCHP_SRORC, SRVCHP_SBORC

## Method and gates

Each unit pools only certified `pareto.csv` rows from the canonical accepted S2 registry.
The three objective maxima are covered first. Remaining slots maximize incremental exact
hypervolume under the frozen S2 normalization; deterministic tie-breaking makes the result
independent of registry/file ordering. All acceptance gates in `s3_manifest.json` passed.

## Scientific limitation

This is an exploratory thermodynamic shortlist, not an engineering recommendation. Extreme
owners are explicitly marked for S5 physical review. S4 must establish five-seed stability
before any pair can be called a stable recommendation.
