# CannaScope CT V16.2.1

**Crash fix for large / all-time reports.** V16.2.0's new plain-English debug-log table could overflow
on big runs: a long metric value (e.g. the accumulated `validation_warn_reasons` list) wrapped, in the
narrow Value column, into a single cell taller than a page — which ReportLab cannot split, so the PDF
build raised a `LayoutError`. This only surfaced on large windows (e.g. an all-time statewide report).

## Fix
- Debug-log cell values are capped at 220 characters in the rendered table (the **full** values remain
  in `debug_log.json` and `debug_log.csv`), and the three columns were rebalanced so no single cell can
  grow taller than a page.

## Verified
A full **all-time** statewide report (window 2015→present, **33,688 products**, 3,275 findings,
184 pages) now builds cleanly end-to-end; 23/23 integrity tests pass. No detection logic changed;
`ANALYSIS_VERSION` stays 15.1.0. All prior releases remain live.

## Downloads
`CannaScopeCT-V16.2.1-{Windows,macOS,Linux}.zip` — the self-contained `CannaScope_CT_V16.py` plus run
scripts.
