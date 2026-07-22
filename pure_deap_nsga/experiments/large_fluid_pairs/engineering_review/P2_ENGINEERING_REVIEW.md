# P2 engineering review

Status: **ENGINEERING_DESIGN_FREEZE_BLOCKED**

Thermodynamic/numerical acceptance remains valid, but no candidate has enough
site-specific evidence for an unconditional engineering recommendation.

## Gate result

- S4 stable candidates: 17 total; PASS 0, CONDITIONAL 5, REJECT 12.
- S5 representatives: 18 total; PASS 0, CONDITIONAL 4, REJECT 14.
- `REJECT` means blocked from design freeze because required evidence is absent; it does not claim a universal legal ban.

All R236ea and R365MFC pairs are blocked because the cited government/ISO-ASHRAE
summary gives no standard safety class. Remaining pairs are conditional because of
A3/high flammability, B1 toxicity grouping, high-GWP HFC controls, or nonstandard
solvent use requiring project-specific hazard evidence.

## Operating-envelope findings

- 3 representatives fall below 0.5 bar absolute.
- 11 representatives fall below 1.0 bar absolute.
- 13 representatives fall below 1.01325 bar absolute.
- 6 representatives contain fsolve-to-least_squares fallback warnings (20 warning records); all S5 residual gates still passed.
- Maximum observed S5 temperatures are recorded per fluid in `p2_fluid_screening.csv`.

Sub-atmospheric cycles require air/moisture ingress, non-condensable accumulation,
vacuum sealing, oxidation and shutdown analysis. Solver fallback requires initial-
condition, design-variable perturbation, alternate-solver and start/stop sensitivity
tests before numerical robustness can be claimed.

## Evidence still required

1. Refrigerant charge, occupied volume, leakage scenario, ventilation and detector/interlock design.
2. Hazardous-area classification, ignition-source control, fire code and local permit review.
3. Metals, elastomers, lubricant and moisture compatibility; decomposition products and long-duration thermal ageing.
4. Pressure-vessel design pressure/vacuum rating, relief sizing, recovery/storage and maintenance isolation.
5. Jurisdiction- and equipment-category-specific F-gas/HFC quota, placing-on-market, leak-check and recovery assessment.

CoolProp convergence, critical temperature and S5 thermodynamic gates cannot supply
any of these missing facts.

## Source register

- `safety_gwp`: https://www.dcceew.gov.au/environment/protection/ozone/rac/global-warming-potential-values-hfc-refrigerants
- `ashrae_designations`: https://www.ashrae.org/technical-resources/standards-and-guidelines/ashrae-refrigerant-designations
- `eu_fgas`: https://eur-lex.europa.eu/eli/reg/2024/573/2024-02-20/eng
- `china_hfc_2026`: https://www.mee.gov.cn/xxgk2018/xxgk/xxgk05/202510/W020251024653086234356.pdf
- `acetone_niosh`: https://www.cdc.gov/niosh/npg/npgd0004.html
- `cyclopentane_niosh`: https://www.cdc.gov/niosh/npg/npgd0171.html
- `unep_odp`: https://ozone.unep.org/20-questions-and-answers
- `ipcc_ar6`: https://www.ipcc.ch/report/ar6/wg3/downloads/report/IPCC_AR6_WGIII_Annex-II.pdf
