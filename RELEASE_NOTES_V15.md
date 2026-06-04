# CannaScope CT V15 — Source-Verified Cannabis Transparency Reports

V15 is a **truth-in-reporting** release. It does not chase flashy features — it makes the report
say only what the COAs and the date-correct standards actually support, labels its own limits
plainly, and packages cleanly. Every flag remains a **lead to verify, not a conclusion.**

## 🚀 What's New in V15

- **Three-part potency review** replacing the old combined section: **A. High THC Flower**,
  **B. Impossible Cannabinoid Math**, **C. Possible Product-Type Misclassification**.
- **Date- & lab-aware Yeast & Mold review**, narrowed to genuine standard/reporting/pathogen
  concerns (the internal 10,000 CFU/g benchmark no longer floods it).
- **Six-field COA triple-check** on every published row (value · product · date · lab · unit ·
  analyte), shown as an auditable stamp.
- **Legal Standard Verification (by test date)** — local-first, with live CT sources consulted
  **only as a fallback**, fully fail-safe, never fabricated.
- **Software Self-Enhancement & Self-Audit** section plus a **persistent cross-run improvement
  log** the next run reads and acts on.
- **Short, browse-friendly filenames + per-run output folders + a persistent numbering registry.**

## 🛠 Major Fixes

- **Conflict math is recomputed and consistency-gated.** Absolute difference, ratio (max ÷ min),
  and % difference are derived from the same normalized fields; near-equal values (e.g. 2,000 vs
  1,950 CFU/g) are no longer reported as huge multipliers; implausible ratios (a dropped "<" bound
  or unit mismatch) are flagged as **likely parser/format artifacts**, not real swings.
- **Same-lab vs cross-lab wording corrected.** Same-lab retests are labeled as retests/duplicates;
  "possible lab-shopping indicator" is reserved for genuine **cross-lab** pass/fail conflicts.
- **No failed-result language in PASS/PASS cases.** Narratives are driven by the actual result pair.
- **Honest potency.** Total THC is computed from the COA's own components
  (`0.877 × THCA + Δ9-THC`), fixing older AltaSci figures printed ~2× too high.

## 📄 PDF Output Improvements

- Larger, readable fonts (table text 11pt, body 12pt, headers 22pt); **adaptive landscape table
  widths** that fill the page; **no detached/orphaned section headers**; no crushed tables, no
  wrapped dates, cleaner page breaks, larger footers.
- **Short filenames:** `{N}-CannaScopeCT-{SW|CC}-{M.D.YY}-{TIME}.pdf`
  (e.g. `42-CannaScopeCT-SW-6.4.26-135PM.pdf`). The **full** report number, date, time, type, and
  dataset window remain inside the PDF.
- **Per-run output folders** (`{N} Statewide Report {M.D.YY}` / `{N} Consumer Concern Report …`)
  hold the PDF + every CSV/diagnostic together; **nothing is ever overwritten**, and a persistent
  `report_registry.json` keeps **global** report numbers and **per-type** folder numbers.

## 🔎 COA Verification Improvements

- A value is published **only if it literally appears in its own linked COA**, then **triple-checked**
  on six fields with an auditable per-row stamp (full detail in `COA_Provenance_Audit.csv`).
- Clear mismatches route to **Coverage Gaps / Unvalidated COAs**; unreadable/low-confidence COAs are
  excluded from normal findings; a **COA Verification Queue** lists what couldn't be confirmed.
- Mutually-distinct confidence metrics (`uncertain_coas_detected`, `uncertain_findings_published`,
  `unreadable_coas_excluded`, …) with a plain-English explainer.

## ⚖️ Legal / Regulatory Date-Aware Review

- Every date-sensitive finding is judged against the standard **in effect on the product's test
  date** — never assuming today's limit applied to an older test.
- Verification is **local-first** (built-in date-keyed registry → cached prior lookup) and consults
  **live** CT sources (eRegulations, the CGS, DCP) **only as a fallback**, logging every URL and a
  fetch timestamp. Network is optional and **fail-safe** — it never blocks or crashes a report.
- Exact historical numeric limits are **never fabricated** from legal prose; an unconfirmed standard
  reads **"Historical standard not verified — manual legal review needed"** with the sources tried.

## 🧪 Testing & Parser Improvements

- **Year-by-year COA Format Learning** that auto-prioritizes the least-trained years and persists
  across runs; per-year READY / PARTIAL / NOT READY readiness.
- Clear separation of **verified findings vs parser uncertainty vs coverage gaps vs manual-review
  leads**, so parser uncertainty is never presented as a COA error.

## 📊 Report Structure Changes

- Potency split into the three sections above; Yeast & Mold review renamed **"Yeast & Mold — Date &
  Lab Standard Review"** and narrowed; **Ombudsman** and **Compliance Review Leads** now show the
  **testing date on every row**; new **Coverage Gaps / Unvalidated COAs** and **Software
  Self-Enhancement & Self-Audit** sections; an **Applicable CT Standards by Test Date** reference.

## 🗑 Removed in V15

- The **Lower-Concern Products** section (it risked reading as a safety ranking / endorsement).
- The internal **10,000 CFU/g benchmark as a standalone concern — from the Yeast & Mold Standard
  Review only** (it remains an internal consumer-awareness threshold shown elsewhere).
- **Misleading same-lab / cross-lab conflict wording.**
- **Failed-result language in PASS/PASS cases.**
- **Unvalidated / unreadable COAs from normal findings** (moved to Coverage Gaps).
- **Overly long PDF filenames** (e.g. the old `…-V15-Statewide-2026-6-4-12:02PM.pdf`).

## ⚠️ Known Limitations

- Historical regulatory limits for several categories (heavy metals, aerobic, pathogens, THC) ship
  marked **UNVERIFIED** pending manual confirmation at eRegulations / CGS / DCP. Live legal lookups
  reach and log the sources but **do not auto-extract** an exact dated number from legal prose.
- Older COA formats (2023–2024 especially) are still being trained; weak years are surfaced in the
  Self-Audit with a `learn` recommendation. Run `learn` online over time to mature them.
- Not legal/medical advice; not affiliated with the State of Connecticut.

## 📦 Download Options

- `CannaScopeCT-V15-Windows.zip` — incl. `run_statewide_report.bat`, `run_consumer_concern_report.bat`
- `CannaScopeCT-V15-macOS.zip` — incl. `run_statewide_report.command`, `run_consumer_concern_report.command`
- `CannaScopeCT-V15-Linux.zip` — incl. `run_statewide_report.sh`, `run_consumer_concern_report.sh`

Each package is the single self-contained `CannaScope_CT_V15.py` (engine + cannabinoid/identity
layer + name resolver + OCR worker embedded) plus README, requirements, LICENSE, and INSTALL.
Requires Python 3.9+ and the listed libraries.

## 🧩 Existing features (carried forward, described in full)

Statewide Transparency Reports and one-product Consumer Concern Reports; COA scanning and source
verification; contaminant flagging (heavy metals, microbials, mycotoxins, residual solvents,
pesticides); microbial and heavy-metals review; zero-tolerance pathogen detection; potency / high-THC
review; product-type mismatch review; conflicting-COA / same-lab-retest / cross-lab conflict review;
CT Cannabis Ombudsman medical patient-safety review; potential compliance review leads (triaged);
CSV exports and a diagnostics appendix; producer / DBA identity mapping; COA format learning and
year-by-year parser learning; coverage-gap reporting; and software self-audit / self-improvement
logging.

## 🙏 Notes for Patients, Advocates, and Reviewers

Treat every item as a **lead to verify, not a conclusion**. Nothing here implies a product is unsafe,
fraudulent, endorsed, or in legal violation. When the report says a standard is **UNVERIFIED** or a
COA is a **coverage gap**, that is the honest state of the public record — please confirm against the
official, live COA and the applicable Connecticut rule for the test date.
