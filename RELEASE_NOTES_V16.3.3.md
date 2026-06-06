# CannaScope CT V16.3.3

**Multi-product COA per-product isolation on the published path — fixes a cross-attribution bug.**
Building on 16.3.2's detection, CannaScope now isolates the correct product when a COA document packs
several products into one PDF (the 2015-era Northeast Laboratories layout), and fixes an OCR page cap that
silently dropped later products.

## The bug this fixes
When several products share one COA document, the single-product parser read the **first** product's
results and would attribute them to *any* registry record pointing at that document URL — e.g. one
product's failing yeast & mold (3,000,000 CFU/g) and aerobic (3,500,000 CFU/g) could be pinned to a
different product. For a safety report, that cross-attribution is unacceptable.

## What changed
- **Per-product isolation (enabled on the published path).** When a fetched COA holds 2+ products,
  CannaScope parses **only** the block that uniquely matches this registry record (by Laboratory ID #,
  product description, or a unique unit marker). Pages sharing one Laboratory ID # are panels of the same
  sample and are **combined**, never split.
- **Route-to-review guardrail.** If a record cannot be uniquely tied to one block, its extraction is
  **suppressed** and it is routed to manual review (*COA Needs Manual Review*) — one product's results are
  never attributed to another.
- **OCR page-cap fix.** `ocr_pdf` and the OCR worker capped scanned documents at 6 pages, silently
  dropping products/panels beyond page 6. They now read the whole document (bounded to 40 pages).
- **Conservative engagement.** Isolation/suppression engages **only** when 2+ resolvable product blocks
  exist, so an ordinary single-product COA — even one that merely mentions two registration numbers — is
  never suppressed.
- **New surfacing.** Debug metrics `multi_product_coa_isolated` and `multi_product_coa_routed_to_review`;
  self-audit and glossary updated.

## Scope & safety
- **Only cold/online reads are affected.** Cache-path runs are unchanged (the new path is dormant on
  cache hits — verified: multi-product metrics are 0 across an offline all-time run).
- `ANALYSIS_VERSION` 16.3.0 → 16.3.3, so legacy-clean ledger entries re-evaluate under the new rules.
- **Regression:** offline statewide (2024 and all-time, 33,688 products) builds clean with 0 self-audit /
  parser-gap / partial-coverage warnings, and the COA source audit re-verified every published flagged
  value in its own linked COA. `_test_multiproduct.py` (19 checks) and `_test_report_integrity.py` pass.

## Known limitation (tracked)
Two-column OCR microbial tables on isolated one-product-per-page pages aren't yet associated by the
parser, so those products currently isolate to **empty** (a safe coverage gap — a missing value, never a
wrong one). Teaching the parser that historical two-column OCR layout is the next step.

All prior releases remain live.
