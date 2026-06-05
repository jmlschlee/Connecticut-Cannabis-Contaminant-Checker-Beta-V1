# CannaScope CT V16.1.0

**Year-by-year regulatory standards, baked in — plus rendering and version fixes.** CT's testing
standards changed over the years, so V16.1.0 bakes the **per-year CT standard for every year
(2015–2026)** into the program, each with an authoritative citation, corroboration from the actual
COAs, and a confirmation date — so a report is always judged against the right year's limit, even
offline, and the live CT sources are re-consulted each run. All prior releases remain live.

---

## 1. CT Regulatory Standards — Year by Year (the headline)
A new **"CT Regulatory Standards — Year by Year (2015–2026)"** section lists, for every year, the
applied limit for yeast & mold, total aerobic, pathogens/Aspergillus, heavy metals, and THC. Each
value is:
- **Cited** to the CT statute / regulation / DCP policy (RCSA §21a-408-58, CGS Chapter 420h, DCP
  Policies & Procedures), with the source URL;
- **Corroborated by the dataset** — the report counts how many CT COAs actually print that action
  limit (e.g. yeast & mold 100,000 CFU/g appears on thousands of COAs), because the labs apply CT's
  limit, so the printed limit is primary-source evidence;
- **Confirmed** as of a stated date, and the live CT sources are re-consulted each run.

**Live-first, never a guess.** Where a category has no single CT number — heavy metals legitimately
differ by product type (inhaled vs other) — the report defers to **each COA's own printed action
limit** rather than assuming one. The "Applicable CT Standards" table now reads **VERIFIED**,
**VERIFIED (per-COA)**, or **N/A — no cap** instead of a blanket red "UNVERIFIED."

## 2. Rendering fixes (P0)
ReportLab's character-level word-splitting was breaking text mid-character in narrow columns —
integers split across lines (`10` → `1`/`0`) and headers garbled (`Confidence` → `Confidenc`/`e`).
Disabled character-level splitting on the base cell and header styles, so numbers and header words
stay whole across every table.

## 3. Version single-source (P4)
The header said V16 while disclaimers and the recommended `learn` command still named the old V15
script. Every rendered/printed mention now derives from one version constant, so the report always
names the actual current file. Version → **16.1.0**.

## Downloads
`CannaScopeCT-V16.1.0-{Windows,macOS,Linux}.zip` — each the single self-contained `CannaScope_CT_V16.py`
(program + engine + triple-verified COA dataset + registry, all embedded) plus README/requirements/
LICENSE/INSTALL/run scripts.

## Unchanged / preserved
Detection thresholds, the triple-verified COA dataset, source-binding, the three-part potency review,
conflicting-COA logic, per-run folders, global report numbering. `ANALYSIS_VERSION` stays 15.1.0.
Published findings on the standing dataset are unchanged.

## Known next steps (tracked, not in this release)
Count-invariant assertions + a coverage-gate review (pathogen/mercury zero-coverage surfaced more
prominently), an OCR/coverage visibility pass, a regression test suite, and caching the live source
*documents* (text + SHA-256) for full offline provenance.
