# CannaScope CT V16.3.6

**Two-column OCR microbial-table reader + 2015–2021 cache rebuild.** Recovers microbial pass/fail values
from the 2015-era scanned COAs whose columnar layout the parser previously couldn't read, and folds the
recovered data into the bundled compressed cache.

## What changed
The 2015-era Northeast Laboratories COAs are scanned images. Apple Vision OCR reads their tables **by
column** — all analyte labels, then all values, then all statuses — so an analyte's label and value land
on different lines and the row parser missed them (those COAs isolated to *empty*).

New repair (`cannascope_multiproduct.repair_columnar_layout`) re-pairs `label[i]` with `value[i]` (and
`status[i]`) and feeds same-line rows to the existing parser.

**Scoped to the microbial / pathogen safety panel only** (aerobic, yeast & mold, coliform, bile-tolerant
gram-negative, E. coli, Salmonella, …). Heavy-metal and cannabinoid columns are deliberately **not**
reconstructed:
- heavy-metal rows misread garbled OCR units (e.g. `<0.0005 4g/kg` → a spurious `4`, a false FAIL);
- cannabinoid rows can’t map every acid form (e.g. `THCAr`), which would understate total THC.

Emitting a wrong safety/potency value is worse than leaving it for review, so those panels stay out.

**Conservative guards:** only emits when the value count **exactly** matches the label count (never
mis-pairs an analyte to the wrong value), and it is a strict **no-op on modern COAs** (no “Result Units”
column header). Wired into both parse paths (single-product and per-product block extraction).

## Cache rebuild
Re-extracted **2015–2021 (11,775 records)** with the repair enabled and re-embedded the corrected
`COA Data Cache`, so the bundled offline dataset now carries the recovered 2015-era microbial pass/fail
values that were previously empty for these scanned columnar COAs.

## Versions
- APP / SOFTWARE / ANALYSIS → **16.3.6**.
- `MULTIPRODUCT_CACHE_VERSION` → 2 (invalidates the per-PDF block cache so blocks re-extract under the repair).

## Unchanged
- 16.3.4’s multi-product mechanism: per-PDF structured block cache, ranked identifier matching, isolate-or-
  suppress, and source-audit block binding.
- 16.3.5’s 2015–2019 cross-attribution correction (now superseded by this wider 2015–2021 rebuild).

## Tests
`_test_multiproduct.py` (now includes columnar-repair checks: re-pairs microbials, skips heavy metals,
emits nothing on count mismatch, no-op on modern COAs), `_test_multiproduct_cache.py`, and
`_test_report_integrity.py` all pass.

All prior releases remain live.
