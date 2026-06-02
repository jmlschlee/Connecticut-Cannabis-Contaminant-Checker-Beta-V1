# Report Fields — CannaScope Beta V5

Every column and term used in the report, explained.

## Product-level columns

| Field | Meaning |
|---|---|
| **#** (rank) | Position within the section, ranked by severity / proximity to the CT limit. The rank cell is shaded by per-measurement severity. |
| **Product** | The product name from the Connecticut registry. |
| **Testing Date** | The COA's **test / sample date** (preferred: date tested → date sampled/collected/received → date reported). This is *never* the report-generation date. Falls back to the registry approval date only when the COA has no date. |
| **Producer** | The combined **Common / DBA** name, e.g. *Fine Fettle (Comffy)*, *Brix Cannabis*, *Rodeo Cannabis*. The legal entity name appears in the appendix. |
| **Lab** | The testing laboratory that issued the COA (shown where relevant). |
| **Measured Value** | The value parsed from the COA, in the COA's own unit (e.g. CFU/g, µg/kg, ppm, %). |
| **CT Legal Limit** | The Connecticut legal action limit for that contaminant, as stated on the COA. |
| **CT % Of Limit** | Measured ÷ CT legal limit × 100. |
| **CannaScope Limit** | The stricter consumer-awareness threshold: Yeast & Mold / Total Aerobic Bacteria = 10,000 CFU/g; every other contaminant = 50% of the CT legal limit. |
| **Difference From CannaScope** | How far above (+) or below (−) the CannaScope threshold the result sits. |
| **COA** | A clickable link to the source Certificate of Analysis PDF. |

## Severity colors (per measurement)

| Color | Meaning |
|---|---|
| 🔴 RED | Near or over the Connecticut legal limit |
| 🟠 ORANGE | Elevated |
| 🟡 YELLOW | Above the CannaScope threshold |
| 🟢 GREEN | Below the threshold (not flagged) |

Color is applied to the rank number, **CT % Of Limit**, and **Difference From CannaScope**.

## Sections

- **Executive Summary** — headline counts plus dashboards: Top Heavy Metal, Top Microbial, Top High Cannabinoid, Top Producer Patterns, Top Lab Patterns, Top Possible Remediation.
- **Top Findings** — the most significant validated results across all categories.
- **Producer Trends / Lab Trends** — counts of validated flagged products by producer and by lab.
- **Per-contaminant Findings** — Yeast & Mold, Total Aerobic Bacteria, Arsenic, Chromium, Cadmium, Lead, Mercury, Mycotoxins, Residual Solvents, Pesticides, Pathogens.
- **High Cannabinoid Content / High THC Content Findings** — non-infused flower above 35%.
- **Infused & Extract Potency Comparison Reference** — concentrates compared against normal flower (high potency expected by design).
- **Possible Remediation / Unusually Low Microbial Load Review** — *not proof of remediation*; a consumer-awareness lead.
- **Lower-Concern Products** — non-infused flower with no contaminant flag, valid potency, and a normal microbial reading. Not endorsed as safe.
- **No Significant Findings** — categories tested and parsed with nothing crossing the threshold.
- **Validation & Diagnostics** — self-audit, COA verification queue, zero-result verification, producer identity validation, and the debug log.

## Validation status

| Status | Meaning |
|---|---|
| **PASS** | No warnings. |
| **PASS WITH WARNINGS** | Publishable, but non-blocking issues exist (e.g. potency-parser conflicts held out of rankings, or COAs that could not be auto-confirmed). |
| **DRAFT** | A zero-result category looked like a parser error and needs review. |
| **FAIL** | An unresolved major validation error. |
