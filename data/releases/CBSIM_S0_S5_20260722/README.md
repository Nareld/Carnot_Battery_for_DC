# CBSim S0-S5 compact data release

This directory is the GitHub-sized audit package for the formal large-fluid-pair campaign.
It contains S1-S5 summary/acceptance records, S3 pooled Pareto fronts, the accepted S4
candidate/stability tables, and all 36 S5 independent-revalidation task/evidence records.

## Accepted stage chain

- S0: historical failed-batch evidence plus the 15 native / 109 wrapper remediation chain
- S1: formal feasibility sampling and failure spectrum
- S2: accepted coarse optimization registry
- S3: 60 selected candidates and pooled fronts
- S4: 300 canonical five-seed runs; 17 candidates accepted for S5
- S5: 18 representative points, two independent repeats each; 36/36 passed

S0 is historical remediation evidence and is not claimed as byte-reproducible from a
clean commit. S5 acceptance is a thermodynamic/numerical result, not an engineering recommendation.
Use `P2_ENGINEERING_REVIEW.md` and `p2_fluid_screening.csv` when present for the separate
safety, environmental, regulatory, materials, and equipment review.

## Integrity and portability

`release_manifest.json` records the source and packaged SHA-256 for every copied file.
`checksums.sha256` verifies the complete packaged tree. Machine-local text paths were
replaced with `${CBSIM_RUNS_ROOT}` and `${CBSIM_REPO_ROOT}`; source hashes remain in
the manifest. Raw per-run archives, failure records, logs, and checkpoints are excluded
in accordance with `COMPUTE_RUN_DATA_MANAGEMENT_SPEC.md`.

The 12 deterministic S2/S4 accepted-front shards are indexed under `assets/` and are
intended for GitHub Release assets, not git history.

Files: 93
Payload: 4477230 bytes
Source code commit: `8fd7fd856f899595424ca3f44c271875212d590e`
