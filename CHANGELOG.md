# Changelog

All notable changes to this project are documented here. This project aims to
follow [Semantic Versioning](https://semver.org/) once it leaves Beta.

## [0.1.0-beta] — 2026-06-01

First public Beta.

### Features
- Pulls Connecticut's public cannabis registry (`egd5-wb6r`), opens each
  product's linked COA, and extracts the full contaminant panel.
- **Default scope:** last 30 days, all inhalable forms (flower, pre-rolls,
  vapes, cartridges, concentrates, extracts, rosin/resin/wax, etc.). Edibles,
  tinctures, and topicals are excluded.
- **Microbiological (zero tolerance, RED):** E. coli, STEC, Salmonella,
  Listeria, pathogenic Aspergillus — any detection is flagged.
- **Mycotoxins:** aflatoxin B1/B2/G1/G2 and ochratoxin A — each compared to its
  limit; any detection is surfaced.
- **Heavy metals:** arsenic, cadmium, lead, mercury (+ chromium) — read in the
  COA's own units and compared to the COA's own limit column to avoid
  unit-conversion errors. Over limit → RED; detected within limit → ORANGE.
- **Residual solvents:** itemized detections flagged YELLOW (RED over the ppm
  limit); grouped "below action limits" panels reported as such.
- **Yeast & mold:** > 100,000 CFU/g (legal limit) → RED; > 10,000 CFU/g watch
  line → YELLOW (legal, surfaced for sensitive consumers).
- Color-coded PDF report (RED / ORANGE / YELLOW), exact values, full contaminant
  names, consistent comma formatting, and each product's COA reference number
  for self-verification.
- Concurrent download + parse, local registry cache, and a scanned-clean ledger
  for fast reruns. Optional OCR (tesseract) for scanned-image COAs.

### Known limitations
- Parsing is best-effort across many lab formats; treat flags as leads and
  verify against the COA.
- Vape/extract COAs that report solvents only as a grouped "below action limits"
  panel do not expose individual solvent values when passing.
- Requires live internet access to `data.ct.gov` and `elicense.ct.gov`.
