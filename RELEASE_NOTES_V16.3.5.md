# CannaScope CT V16.3.5

**Data-refresh release — the bundled offline COA cache is rebuilt to remove real multi-product
cross-attribution.** No engine changes (the multi-product mechanism shipped in 16.3.4); this ships the
corrected data.

## What changed
The 2015–2019 medical-era COAs (6,401 records) were re-extracted with the v16.3.4 multi-product-aware
engine and re-embedded into the bundled `COA Data Cache`. The rebuild found **106 era records that are
genuinely multi-product COAs and do NOT share a registry URL** — e.g. a single record like
“CPS Oil 206/481” whose PDF actually holds two products. These are exactly the cases the old
single-product parser would mis-attribute (reading the first product’s values). They are now isolated to
their own product block, or — when a record can’t be uniquely matched — suppressed and routed to
**COA Needs Manual Review**, never cross-attributed.

## Effect on the bundled statewide report
- Published findings **3,041 → 3,038** (including **2 fewer RED**) — the removed values were
  cross-attributed from multi-product documents.
- Source audit re-verified all **1,688** remaining flagged values in their own block/COA.
- Build clean: self-audit remaining 0, parser-gap 0, partial-coverage 0.
- 5,646 of the era’s records triple-verified on rebuild; cache restored to 33,692 COAs.

## Why only 2015–2019
Multi-product packing was the 2015-era medical-program practice; 2020–2026 COAs are single-product and
were already correctly extracted by the same v16 engine, so re-downloading them would change nothing.
Whole-registry shared-URL multi-product candidates are only 5 records / 2 clusters (all non-extracting,
handled in 16.3.4); the real residual exposure was the single-record multi-product PDFs in the medical
era, which this rebuild corrects.

## Unchanged
- Engine/detection logic (`ANALYSIS_VERSION` stays 16.3.4).
- The multi-product mechanism from 16.3.4: per-PDF structured block cache, ranked identifier matching
  (lab ID → registration number → sample ID → batch → description → unit marker), isolate-or-suppress,
  and source-audit block binding.

## Known limitation (tracked)
Two-column OCR microbial tables on isolated one-product-per-page blocks aren’t yet associated, so those
products isolate to empty (a safe coverage gap — a missing value, never a wrong one).

All prior releases remain live.
