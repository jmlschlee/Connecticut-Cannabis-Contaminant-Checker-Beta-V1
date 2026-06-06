# CannaScope CT V16.2.0

**Transparency & readability refinement pass.** A careful, non-destructive update that makes the report
more accurate, easier to audit, and clearer for human review. No detection logic changed, no findings
were removed, and the conservative tone is preserved — every flag remains a lead, not a conclusion.

## Multiple / conflicting COA records — reframed for comparison
The section that surfaces the same product identifier appearing on more than one record is **kept in
full** (repeated/identical records are intentionally not discarded). It is now framed as material for a
human to **compare versions**, not as useless duplicates:
- Each case shows the **COA number**, batch/lot identifier, test date, lab, result, **pass/fail**, and
  the limit on each COA — side by side.
- A new **"Compare:"** line states, at a glance, whether the COA references, dates, pass/fail, and
  values are **identical or different** between the two records.
- The "Duplicate COA" label is now **"Multiple records (same lab, same date)."**

## Accuracy & clarity
- **Relative difference is now unambiguous** — the report shows both the ordinary **percent increase**
  and the **Relative Percent Difference (RPD, average-based)**, clearly labeled, so the math isn't
  misread.
- **Softer causal language** — "likely a parsing artifact" is now "this may reflect a parser issue, COA
  formatting issue, retest, remediation, sample variation, or other lab/reporting difference; manual
  review recommended."
- **Confidence counts clarified** — the extraction-confidence tally counts only COAs *freshly read this
  run* (cached COAs were format-checked when first read); metrics are renamed `*_this_run` and the
  section says so, so small numbers aren't misread as "only N of thousands were checked."
- **`coa_years_observed` fixed/renamed** — now `coa_years_fingerprinted_this_run`, plus a new
  `years_in_report_window` computed from every reviewed COA's date.
- **Readiness explained** — a short note on why a year can show a high Conf % yet still read PARTIAL or
  NOT READY (it also needs enough verified samples, lab coverage, parser-training coverage, and
  category coverage).

## Transparency
- **New "Parser / Coverage Issues" box near the summary** — broken COA links, unreadable COAs, potency
  parser conflicts held out of findings, and uncertain extractions held back. Shown as **report
  limitations, not findings or accusations**, so readers understand coverage boundaries.
- **Debug log is now human-readable** — every raw metric has a plain-English "What it means" explanation.
- **Tighter findings** — removed repeated explanatory text (the difference line, timeline line, and
  narrative no longer restate the same numbers).

## Unchanged / preserved
Detection thresholds, the triple-verified COA dataset, the year-by-year regulatory ledger + source-
document provenance, source-binding, conflicting-COA detection logic, per-run folders, and global
report numbering. `ANALYSIS_VERSION` stays 15.1.0. All prior releases remain live.
