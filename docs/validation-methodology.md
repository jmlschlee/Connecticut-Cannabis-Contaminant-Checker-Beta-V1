# Validation Methodology — CannaScope Beta V5

CannaScope treats every field as unverified until checked. The goal is a report where every published finding is traceable to a live COA and a Connecticut legal limit.

## 1. Quantified vs. detected-but-not-quantified

A measurement only drives a finding when it is **quantified** — a real numeric value backed by the COA text, not a bare "DETECTED", a non-numeric phrase, or a value that turns out to be a misread limit column. Detected-but-not-quantified fields are routed to a manual-review path and never ranked numerically. No value in the rankings is a guess.

## 2. Live COA row validation

Each flagged row is re-checked against its own COA PDF:

- the COA link returns a readable document;
- the product / brand / strain appears in the COA;
- a flagged measured value appears in the COA.

Only **substantive** conflicts are flagged (true product/value mismatch, broken or missing link). Cosmetic differences — capitalization, punctuation, spacing, abbreviation, formatting — are ignored. Rows that verify are marked **Verified**; the rare COA that names a product only by an internal ID is **Verified Partial Match**. Anything that cannot be confirmed goes to the **COA Verification Queue** and is kept out of the rankings.

## 3. Zero-result verification

Cannabis COAs mostly pass, so zero findings in a category is expected — but a category that was **never parsed** in any product is a likely parser error. CannaScope therefore re-checks every expected category against the raw parsed data:

- findings present → reported normally;
- parsed but nothing crossed the threshold → **Confirmed Zero** (stated plainly under "No Significant Findings");
- never parsed → **DRAFT WARNING**, routed to the Zero-Result Verification Queue.

## 4. Producer / DBA identity validation

Legal entities are resolved to a common brand / DBA using a curated, source-cited table layered over the Connecticut product registry's own brand mapping. Each producer gets a **source-confidence score**:

| Confidence | Basis |
|---|---|
| 100% | COA/registry brand + CT registry + public source |
| 90% | COA/registry brand + CT registry |
| 80% | COA/registry brand + public source |
| 70% | CT registry + public source |
| 60% | a single authoritative source |
| <60% | needs verification (marked "DBA Needs Verification") |

Sources include data.ct.gov (`egd5-wb6r`), CT eLicense documents, the DCP brand registry, and cited public records. **Names are never invented**; low-confidence mappings are marked for manual verification.

## 5. Cannabinoid / potency guards

Cannabinoid percentages are read from the COA potency section. A **potency-parser conflict** (e.g. Total THC reported as 0% alongside a 35%+ active-cannabinoid reading) is detected and **held out of the rankings** rather than published. No scientific notation appears in public tables.

## 6. Self-audit and status

Before export, an automatic self-audit checks for infused products leaking into the flower review, scientific-notation values, parser conflicts, rows without COA links, unverified rows, duplicates, and suspected zero-result parser errors. The report's status — **PASS / PASS WITH WARNINGS / DRAFT / FAIL** — reflects what the audit found. The full audit, queues, and a debug log are printed in the **Validation & Diagnostics** section at the end of the report and exported as CSV.
