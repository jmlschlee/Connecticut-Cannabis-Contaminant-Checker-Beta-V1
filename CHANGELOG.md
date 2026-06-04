# Changelog

All notable changes to this project are documented here.

## [13.0.0] — 2026-06-03 — CannaScope CT V13 — current release

Big readability + integrity + feature release. Carries all V11/V12 capabilities; all prior releases
remain live and unchanged. Nothing removed from the repository.

### Added
- **Conflicting COA Results & Possible Lab-Shopping Indicators** (statewide): same physical lot
  (shared batch/lot/BioTrack/sample/product-code) with conflicting pass/fail across lab reports,
  esp. an earlier FAIL followed by a later PASS. Pass/fail is judged against the limit STATED ON
  EACH COA (CT standards changed over the years). Neutral, human-review-only; never alleges
  misconduct. New `conflicting_coa_results.csv` export.
- **High-cannabinoid breakdown** columns: THCA / Δ9-THC / CBD / Total THC / Total Cannabinoids.
- **Potential Compliance Review Leads** (renamed from Statute & Regulatory Flags) with buckets
  A (over current CT limit) / B (implausible potency + cannabinoid breakdown + chemistry consistency
  checks) / C (missing numeric microbial despite PASS) / D (COA/document inconsistency); cautious
  "authority area to verify in eRegulations" wording.
- **Most Important Findings** summary box (computed) + **How To Read These Findings** legend.
- **Dataset accounting** line (window / scanned this run / reused from ledger / fetched / published).

### Changed / fixed
- **Producer percentages** now use each producer's total products in the window as the denominator
  (was a misleading near-100%); section renamed "Flagged Findings by Producer."
- **Report numbering** carried in filename + cover + footer + PDF metadata, with a guard against
  overwrite/reuse; each report is **one uniquely numbered file** (removed a duplicate-copy that
  caused OS "overwrite" prompts); second-precision timestamps.
- **Section reorder** to a publication-first flow; technical material moved to an **Appendix**.
- Fixed a box-overlap rendering bug (shaded boxes no longer bleed over headers); centered the
  Most Important Findings header; fixed a legend block that was pushed to a new page.
- Remediation now flags flower at/under 100 CFU/g; Lower-Concern range 800–3,000 CFU/g.
- Rebranded from "CannaScope CT Beta V12.1" to **"CannaScope CT V13"** (dropped "Beta").

### Removed
- The two potency-reference sections (infused products; vapes/concentrates/extracts) — pure potency
  listings, not findings.
- Five redundant "Top …" mini summary tables (duplicated the full sections + the summary boxes).

### Unchanged
- The COA source-binding integrity rule, thresholds/calculations, and the detection engine. The
  single-file build ships in the download zips (the embedded registry snapshot is intentionally NOT
  committed to git to avoid repo bloat).

## [12.1.0-beta] — 2026-06-03 — CannaScope CT Beta V12.1

Additive feature release. Carries every V11.1 integrity feature and all prior capabilities; all
prior releases remain live and unchanged. Nothing removed.

### Added — Conflicting COA Results & Possible Lab-Shopping Indicators (Statewide Transparency Report)
- A new statewide section that surfaces **document-level discrepancies for human review,
  neutrally** — no allegations of fraud or misconduct.
- **Cross-record detection:** the same physical lot (matched on a distinctive shared identifier —
  batch, lot, BioTrack/UID, lab sample ID, or product code) showing **conflicting pass/fail COA
  results** across lab reports, especially an **earlier failing result followed by a later passing
  result** on a regulated safety category (a *possible retesting discrepancy / possible
  lab-shopping indicator*).
- **Within-document detection:** one COA carrying more than one lab identity, or a passing summary
  alongside a failing regulated-test result (page numbers preserved where available). Uses a strict
  fail-verdict match that ignores "Pass/Fail" column headers (no false positives on clean COAs).
- Categories compared: total yeast & mold, total aerobic microbial count, Aspergillus, E. coli,
  Shiga toxin-producing E. coli, Salmonella, Listeria, mycotoxins, heavy metals, pesticide panel.
- Presentation: high-severity examples ride near the top of the report (red = Critical, orange =
  High); otherwise lower-severity observations appear later, and if none are found the report notes
  "No conflicting COA result patterns detected." Each case shows a side-by-side comparison, the
  numeric difference, a timeline note, source COA links/page references, and a plain-English
  explanation that names the innocent explanations too. Severity tiers Critical/High/Medium/Low.
- New export `conflicting_coa_results.csv`; an executive-summary line when Critical cases exist; and
  a validation note: "This section flags document-level discrepancies only. It does not prove
  intent, misconduct, remediation, or unlawful conduct without further verification."
- Statewide report only. The Personalized Product Concern report is unchanged unless the specific
  product is itself involved.

### Unchanged
- Thresholds, calculations, COA-verification standards, the rest of the section order, Ombudsman and
  TYM placement, and report numbering. The single-file build ships in the download zips (the
  registry snapshot it embeds is intentionally NOT committed to the git tree to avoid repo bloat).

## [11.1.0-beta] — 2026-06-03 — CannaScope CT V11.1 Beta — EMERGENCY COA INTEGRITY PATCH

Use V11.1 instead of V11. Additive; all prior releases remain live and unchanged.

### Fixed / hardened (data integrity)
- Enforced COA source-binding in BOTH reports: every published value is independently re-verified
  in its OWN linked COA; any value that cannot be confirmed is EXCLUDED and routed to manual
  review. Nothing unverified is ever published.
- New COA Source Mismatch Review queue; the consumer report shows a "held for manual review" note.
- New status FAIL SOURCE VALIDATION (and PASS WITH WARNINGS when mismatches are found + excluded).

### Added
- Integrity exports: COA_Provenance_Audit.csv, COA_Source_Mismatch_Review.csv, Multiple_COA_Alert.csv;
  a "COA Source-Binding Audit" diagnostics panel; new diagnostics metrics.
- Baked-in caches: embedded registry snapshot (skips the download when fresh; offline/fallback;
  online auto-refresh keeps data current) + opt-in --fast-cached first-run mode.

### Unchanged
- Thresholds, calculations, COA-verification standards, section order, Ombudsman placement, and
  report numbering. The single-file build ships in the download zips (the registry snapshot it
  embeds is intentionally NOT committed to the git tree to avoid repo bloat).

## [11.0.0-beta] — 2026-06-03 — CannaScope CT V11 Beta — beta

Additive release. All prior versions remain live and downloadable, unchanged.

### Added / improved
- Clean two-report naming: **Statewide Transparency Report** (`statewide`, also the default) and
  **Personalized Product Concern Report** (`concern`), each with its own output folder.
- Statewide report: first-pages (1-3) layout polish + findings-first **Findings at a Glance**
  summary, a consolidated producer section, and concise per-section trend notes. COA IDs never
  wrap and stay clickable; full product names preserved.
- Consumer report: **PRODUCT OF CONCERN** header, **Complaint Investigation Summary**,
  **severity tiers**, legal-entity + brand producer names, **Producer Trend Context**, smarter
  related/sibling-COA comparison (same product -> size -> closest date), and a
  **"Why this product was matched"** explanation.
- Self-contained `CannaScope_CT_Beta_V11.py` + modular `cannascope_ct_v11.py` + `_make_v11.py`.
- Windows / macOS / Linux download bundles.

### Unchanged
- Statute/Ombudsman sections, COA dates + clickable links, multi-lab COA-parsing accuracy,
  offline bundle, numbered never-overwrite reports. Thresholds, calculations, COA-verification,
  and matching logic are unchanged.

## [10.0.0-beta] — 2026-06-03 — CannaScope CT Beta V10 — beta

Additive release. All prior versions remain live and downloadable, unchanged. Repository
renamed to `CannaScope-CT` (stable name; GitHub redirect from the old name preserved — the
release, not the repo, now carries the version).

### Added
- **Patient-Reported Product Concern — Personalized Analysis PDF** (`patient-concern`
  subcommand). On-demand single-product report: resolves the product against the CT registry +
  its COA from any identifiers (name, batch, NDC, UID/BioTrack lot, COA #, dates, QR/COA link),
  runs the near-/over-limit + statute/regulatory-flag logic, surfaces identifier discrepancies,
  and links related/sibling COAs from the same producer (same strain + form, closest in time)
  with live clickable COA links so a patient can compare batches. Output to
  `output/patient_concerns/`; never overwrites. Advisory / non-diagnostic / not medical advice.
- Self-contained `CannaScope_CT_Beta_V10.py` + modular `cannascope_ct_v10.py` + `_make_v10.py`.
- Windows / macOS / Linux download bundles.

### Carried forward from V9.1 (unchanged)
- "Potential Statute & Regulatory Flags to Evaluate" and "CT Cannabis Ombudsman — Medical
  Patient Safety Review" PDF sections, with COA dates + clickable COA links.
- Multi-lab COA-parsing accuracy work; offline source bundle; numbered never-overwrite reports.
- The broader Compliance Screening + Environmental Linkage engines remain reserved/dormant
  (present in-code, not wired).

## [9.1.0-beta] — CannaScope CT Beta V9.1

Consolidation point release of the V9 line. Additive: all prior releases remain live and
downloadable, unchanged. Repository renamed to `CannaScope-CT-Beta-V9.1` to match.

### Changed
- Version label bumped to **CannaScope CT Beta V9.1**; refreshed Windows/macOS/Linux
  downloads under the V9.1 name.

### Unchanged from V9.0
- Compliance Screening + "Potential Statute & Regulatory Flags to Evaluate" PDF section.
- CT Cannabis Ombudsman — Medical Patient Safety Review PDF section.
- Field-aware COA extraction, ND/limit/LOQ/LOD never published as measurements,
  regulatory-limit → manual review, crash-isolated OCR, offline mode.
- No detection-logic changes.


## [9.0.0-beta] — CannaScope CT V9 Beta

Additive release. All prior releases remain live and downloadable, unchanged. Released as the current version; all prior releases remain live and downloadable.

### Added
- **Compliance Screening Engine** — surfaces *potential* Connecticut statutory/regulatory
  matters (authority set: CGS Ch. 420h / RERACA, CGS Ch. 420f, DCP Policies & Procedures
  eff. 2024-11-12, RCSA Sec. 21a-408, and the Public Acts amendment layer — resolve in
  eRegulations.ct.gov). Each item is a review flag with cited authority, status, severity,
  confidence, and recommended next step. Flags to investigate, not legal determinations.
- **"Potential Statute & Regulatory Flags to Evaluate" PDF section** (near the end of every
  report): results over the CT legal limit, detected zero-tolerance pathogens, failed
  pesticide/solvent panels, and high-cannabinoid potency-label reconciliation
  (0.877×THCA + Δ9 vs reported Total THC), each with a clickable COA link; renders even when
  empty.
- **"CT Cannabis Ombudsman — Medical Patient Safety Review" PDF section** (immediately after
  the flags): products that PASSED testing but came closest to a CT action limit, ranked by
  margin across all contaminant classes (tunable threshold, default 80%), with closeness
  tiers, per-class patient notes, and clickable COA links. Advisory; not medical advice.
- Pre-built self-contained downloads for Windows, macOS, and Linux.

### Notes
- Carries the V8.x accuracy work: field-aware COA extraction across lab/year formats,
  ND/limit/LOQ/LOD never published as measurements, regulatory-limit matches routed to
  manual review.
- Compliance and ombudsman outputs are review aids, not legal or
  medical advice.


## [5.0.0-beta] — CannaScope Beta V5 — public release

**Standardized the public-facing version name to CannaScope Beta V5.** Internal
development used "V7" report-build naming; those builds and all earlier versions
(Beta V1, CannaScope CT V2/V3/V4) are preserved in history — nothing was deleted.

### Added
- **Testing Date** column throughout every product-level table (COA test/sample
  date; never the report-generation date; registry date only as a fallback).
- **CT Legal Limit** and **CannaScope Limit** comparison columns, plus
  **CT % Of Limit** and **Difference From CannaScope** — full numeric context per row.
- **Producer Trends** and **Lab Trends** under the Executive Summary.
- **High Cannabinoid Content / High THC Content Findings** (non-infused flower > 35%).
- **Infused & Extract Potency Comparison Reference**.
- **Possible Remediation / Unusually Low Microbial Load Review** with cautious
  wording safeguards (explicitly *not* proof of remediation).
- Expanded Executive Summary dashboard (top heavy-metal / microbial / high-cannabinoid /
  producer / lab / possible-remediation findings) and per-measurement severity colors.

### Improved
- Clickable COA links on every finding; live COA row validation (substantive
  mismatches only); PASS / PASS WITH WARNINGS / DRAFT / FAIL status; zero-result
  verification; source-verified producer/DBA identity with confidence scores.
- Larger typography, centered headers, findings-first order, diagnostics at the end.

### Packaging
- New entry script `cannascope_beta_v5.py` (engine modules `cannascope_ct_v5.py`,
  `cannascope_ct_v4.py`, `ct_cannabis_names.py`).
- Per-OS packages `CannaScope_Beta_V5_{Windows,macOS,Linux}.zip` and sample report
  `CannaScope_Beta_V5_Report.pdf`.
- Docs: README, RELEASE_NOTES, DISCLAIMER, docs/user-guide, docs/validation-methodology,
  docs/report-fields.

## [0.4.0] — CannaScope CT Beta Version 4 — 2026-06-02

### CannaScope CT Beta Version 4
- Adds CannaScope CT Standard.
- Separates Connecticut Legal Limit from CannaScope CT Standard.
- Uses 10,000 CFU/g CannaScope CT Standard for yeast/mold and aerobic bacteria.
- Uses 50% of Connecticut Legal Limit as CannaScope CT Standard for metals, mycotoxins, pesticides, and other regulated contaminants.
- Adds + / - comparison against CannaScope CT Standard.
- Adds Date Created and Time Created to reports.
- Adds improved Executive Summary sections.
- Improves capitalization, font readability, spacing, table layout, and overall PDF appearance.
- Adds or updates macOS, Windows, and Linux Version 4 run/build support.

#### Version 4 refinements (2026-06-02)
- Flagging now uses the **CannaScope CT Standard**: heavy metals, mycotoxins, and residual solvents flag only at/over 50% of the Connecticut Legal Limit (trace detections far below the limit no longer create noise); Total Aerobic Bacteria flags at/over the 10,000 CFU/g CannaScope CT Standard, like Yeast & Mold.
- The internal-contradiction check is now a YELLOW "Verify" caution instead of RED "Do Not Consume", so nothing is marked Do Not Consume without a visible cause (a prohibited detection or an over-Connecticut-Legal-Limit result).
- Lab-name parser recognizes Northeast Laboratories COAs that identify only as "NELabs" / nelabsct.com, and no longer mistakes COA section headers (e.g. "Stability Testing") for a lab name.

## [0.3.0] — CannaScope CT Version 3 Beta — 2026-06-02

Adds proximity-to-limit reporting against BOTH the CT legal limit and a stricter
**CannaScope CT limit**, plus much clearer output. V2 and Beta V1 remain available
and unchanged as tagged releases.

### Added / changed
- **% of CT Legal Limit** and **% of CannaScope CT Limit** columns for every
  contaminant that has a limit, color-coded by proximity (>=90% dark red,
  75-89.9% orange, 50-74.9% yellow). Computed dynamically per COA.
- **Executive Summary page** — "Products Closest to the Limits," ranked by % of
  limit reached, showing measured value, CT legal limit, and CannaScope CT limit.
- **Recognizable producer names**: common / DBA name + legal LLC (e.g.
  "Fine Fettle (FFD 149 LLC)", "Theraplant (DXR Finance 3, LLC)"), plus the
  product brand parsed from the COA, via the new `ct_cannabis_names.py` module and
  optional `dba_overrides.csv`. Lab names normalized.
- **Reads Northeast Laboratories' columnar COAs** — recovers yeast/mold & aerobic
  counts earlier versions could not parse.
- **Per-Lab Analysis Summary** and a **name coverage audit** so every lab and
  producer is accounted for each run.
- **Clearer, wider report layout** (legal landscape, larger type) and the numbered
  report is also written to the top of the run folder for easy access.
- **Default look-back is now 60 days** (use `--days` to widen/narrow).

## [0.2.0] — CannaScope CT V2 — 2026-06-02

Renamed to **CannaScope CT** and substantially upgraded. The Beta V1 release
remains available and unchanged.

### Added / changed
- **All product types** evaluated by default (not just inhalables): flower,
  vapes, concentrates, edibles, tinctures, topicals.
- **OCR for scanned/image-only COAs** (Apple Vision via `ocrmac` on macOS,
  tesseract elsewhere) — they are now read and evaluated instead of skipped.
- **~65× faster PDF parsing** by switching from pdfplumber to pypdfium2, plus
  concurrent downloads (16 workers) — typical run is a couple of minutes, reruns
  are seconds.
- **Severity-sorted report**: most severe first (RED → ORANGE → YELLOW), then by
  contaminant magnitude within each tier.
- **Clickable COA links**: every COA number opens its exact source COA PDF.
- **Numbered reports**: `CannaScope CT - Flagged Products - N.pdf`, a new file per
  run (never overwrites).
- **Simplified color guide**: RED = do not consume; ORANGE = use high caution if
  sensitive; YELLOW = moderate caution for those with sensitivities.
- **Self-cleaning cache**: only flagged COA PDFs are retained; the cache prunes
  itself each run.
- **Pesticide-panel FAIL now flags RED** (was previously not flagged).
- **Clear, capitalized output folder/file names** under
  `CannaScope CT - Flagged Product Results and Sources/`.

## [0.1.0-beta] — Beta V1 — 2026-06-01

First public Beta (`connecticut_cannabis_contaminant_checker_beta_v1.py`).

- Inhalable-forms contaminant audit against CT's codified standards with a
  10,000 CFU/g yeast & mold watch line.
- Microbiological zero-tolerance, mycotoxins, heavy metals, pesticide/solvent
  pass-fail; color-coded PDF + CSV; concurrent download/parse; registry cache.
- Reads results with the COA's own units/limit columns to avoid unit-conversion
  mistakes.
