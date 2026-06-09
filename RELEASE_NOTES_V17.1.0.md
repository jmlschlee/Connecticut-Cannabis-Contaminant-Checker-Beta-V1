# CannaScope CT V17.1.0

Source-verified Connecticut cannabis transparency reporting. This release adds a major new
statistical section, renames the report, reframes cannabinoid-consistency flags, and lands a series
of honesty/accounting corrections so the report never over- or under-states what was verified.

## ✨ New: "Convenient Lab Result Groupings by Producer and Lab"
A boundary-clustering statistical screen that flags **statistically unusual** clustering of
quantitative results just **below** a pass/fail threshold, grouped by producer / lab / analyte. It is
a **review signal — never a fraud claim** (a convenient near-limit grouping can come from a legitimate
retest, remediation, sampling, rounding, reporting, or selection effect, and by itself warrants only
review).

- Primary target: **yeast & mold** near the 100,000 CFU/g legal limit (program watch line 10,000),
  plus total aerobic bacteria.
- Per producer+lab+analyte: total / near-threshold (95–100%) / over-limit counts, observed vs
  statewide-expected, observed/expected ratio, **binomial p-value, z-score, chi-square goodness-of-fit,
  Fisher exact (small-N), cliff-effect**, and a transparent **Convenience Score 0–100**.
- All statistics are **pure-Python** (no numpy/scipy dependency) and validated against known reference
  values (`_test_convenience.py`). Minimum-sample rules enforced (groups under 5 samples are not
  ranked; a "strong" score needs ≥3 near-threshold results).
- **Public summary** (statewide histogram + ranked Top-10 + plain-English interpretation) and a
  **Technical Appendix** subsection (full methodology, per-producer/lab comparison table, per-grouping
  detail, scatter of % of limit by date). New export `convenient_lab_result_groupings.csv`.

## 🏷️ Report rename + reframing
- The report is now titled **"CT Statewide Cannabis Report."**
- **"Potency Parser Conflicts" → "Laboratory Data Consistency Flags"** everywhere — reframed as
  **data-integrity alerts** (a COA's own numbers being internally inconsistent), not software/parser
  errors. The "Impossible Cannabinoid Math Review" is folded under this heading.

## 🔍 Honesty & accounting corrections
- **Live verification is credited honestly.** Cold live reads now count toward validation coverage
  (`products_freshly_read_live`), so a genuine live run no longer reads "0.0% verified." Offline /
  cache-replay runs still correctly show 0% and are tiered **UNVALIDATED — CACHE REPLAY**.
- **Cache-replay detection hardened** — a run with no live verification (no live re-pull, no
  cache-audit comparison, no OCR, no online-fallback) is correctly labeled a cache replay, with a
  run-aware disclaimer; the live/not-ready disclaimer only claims "confirmed this run" when live
  verification actually ran.
- **Dataset accounting reconciles, fail-loud.** Reused-from-ledger is a separate bucket from excluded;
  `analyzed + reused + excluded == in-window` is enforced (`sys.exit` on a mismatch).
- **Coverage Integrity Summary** (new appendix section): COAs expected / acquired / parsed /
  live-verified with reconciling ratios; fail-loud on a zero denominator.
- Severity tiers reconcile to the published total; the triple-check no longer rounds 1,174/1,176 up to
  "100%"; the three verification counts are labeled by scope (live sample vs source-binding vs all
  published rows) and by live-vs-cached source.
- **µg/kg renders everywhere** — a Unicode TTF (Arial/DejaVu) is now embedded, so the micro sign no
  longer drops to "g/kg" in viewers that substitute the non-embedded base font.

## ✅ Verification
All fixture suites + `_test_convenience.py` + date-window (9 ranges) + report-integrity pass. Live
online run verified (certifi CA bundle). Self-contained rebuilt; additive release — all prior releases
preserved.

## Run it
    python3 CannaScope_CT_V17.py statewide --since 2024-01-01 --until 2024-12-31              # live-first
    python3 CannaScope_CT_V17.py statewide --since 2024-01-01 --until 2024-12-31 --validate    # forensic live re-read
