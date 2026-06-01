# Connecticut Cannabis Contaminant Checker — Beta V1

Pulls Connecticut's public **Medical Marijuana & Adult-Use Cannabis Product
Registry** (dataset `egd5-wb6r`), opens each product's linked Certificate of
Analysis (COA) PDF, extracts the full contaminant panel, and produces a
color-coded report of inhalable products flagged for consumer awareness.

It checks against Connecticut's codified standards (Conn. Agencies Regs.
§21a-408-60): zero tolerance for *E. coli*, STEC, *Salmonella*, *Listeria*, and
pathogenic *Aspergillus*; yeast & mold and total aerobic ≤ 100,000 CFU/g;
mycotoxins < 20 µg/kg each; heavy-metal and residual-solvent action limits. A
stricter **10,000 CFU/g yeast-&-mold "watch line"** surfaces products that are
legal in CT but may matter to sensitive consumers.

> Every flag is a **lead to verify against the source COA**, not a conclusion of
> wrongdoing. Each row includes the product's COA registration number so anyone
> can look it up and confirm.

---

## Requirements

- **Python 3.9+**
- Internet access to `data.ct.gov` and `elicense.ct.gov` (the COAs are served
  from a session-gated state portal)
- Python packages: `requests`, `pdfplumber`, `reportlab`
- *Optional* OCR for scanned-image COAs: `pytesseract` + the system `tesseract`
  binary

## Install & run

```bash
# 1. Get the code (clone the repo, or download and unzip this folder)
cd ct-contaminant-checker

# 2. Create an isolated environment and install dependencies
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Run it (defaults: last 30 days, all inhalable forms)
python connecticut_cannabis_contaminant_checker_beta_v1.py
```

Outputs land in `./ct_audit_output/`:

| File | What it is |
|------|------------|
| `flagged_products.pdf` | color-coded report with COA links |
| `coa_results_full.csv` | every analyte value parsed, per product |
| `parse_failures.csv`   | COAs that couldn't be read (e.g. scanned images) |
| `raw_coas/`            | cached COA PDFs |

## Common options

```bash
# Quick test (first 50 COAs)
python connecticut_cannabis_contaminant_checker_beta_v1.py --limit 50

# Flower only, last 60 days
python connecticut_cannabis_contaminant_checker_beta_v1.py --forms flower --days 60

# Specific start date, more download workers
python connecticut_cannabis_contaminant_checker_beta_v1.py --since 2026-01-01 --workers 12

# Lower the yeast/mold watch line to 5,000 CFU/g
python connecticut_cannabis_contaminant_checker_beta_v1.py --threshold 5000
```

Run with `-h` to see all options.

## If COAs come back "Document does not exist"

The state portal is session-gated. If downloads fail, open
<https://www.elicense.ct.gov/lookup/licenselookup.aspx> in your browser, run any
product lookup, export cookies with a "cookies.txt" browser extension, and pass
`--cookies cookies.txt`.

## Optional OCR (for scanned-image COAs)

```bash
pip install pytesseract pypdfium2
# then install the tesseract engine:
#   macOS:         brew install tesseract
#   Ubuntu/Debian: sudo apt install tesseract-ocr
#   Windows:       https://github.com/UB-Mannheim/tesseract/wiki
```

## Notes & limitations (Beta V1)

- Data is only as good as the underlying COA PDFs; lab formats vary and parsing
  is best-effort. Treat flags as leads, verify against the linked COA.
- Heavy-metal and mycotoxin amounts are read with the COA's own units and limit
  columns to avoid unit-conversion errors.
- Reruns reuse a local cache and skip already-scanned-clean COAs, so they're much
  faster than the first run.

## Disclaimer

This is an independent, non-commercial tool for consumer awareness. It makes no
assertion about any laboratory's or producer's licensure or conduct. Verify
every result against the official COA before relying on it.
