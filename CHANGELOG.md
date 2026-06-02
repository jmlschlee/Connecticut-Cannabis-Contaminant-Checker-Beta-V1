# Changelog

All notable changes to this project are documented here.

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
