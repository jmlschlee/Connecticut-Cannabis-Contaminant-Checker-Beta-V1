# Connecticut Cannabis Contaminant Checker — Beta V1

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB.svg)
![Status](https://img.shields.io/badge/status-Beta-orange.svg)
![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

Pulls Connecticut's public **Medical Marijuana & Adult-Use Cannabis Product
Registry** (dataset `egd5-wb6r`), opens each product's linked Certificate of
Analysis (COA) PDF, extracts the full contaminant panel, and produces a
color-coded report of inhalable products flagged for consumer awareness.

> **Every flag is a lead to verify against the source COA, not a conclusion of
> wrongdoing.** Each row includes the product's COA registration number so anyone
> can look it up and confirm. Please read [`DISCLAIMER.md`](DISCLAIMER.md).

![Sample report](docs/sample_report.png)

---

## Download (no coding required)

Grab the file for your operating system from the
[**Releases**](../../releases/latest) page, unzip it, and run the launcher:

| Your computer | Download | Then |
|---|---|---|
| **Windows** | `ct-contaminant-checker-windows.zip` | unzip → double-click `setup_and_run.bat` |
| **macOS** | `ct-contaminant-checker-macos.zip` | unzip → right-click `run.command` → **Open** |
| **Linux** | `ct-contaminant-checker-linux.zip` | unzip → `./run.sh` |

The launcher sets up everything on first run. You still need **Python 3.9+**
installed (the launcher links you to the download if it's missing) and an
internet connection.

## What the colors mean

| Color | Meaning |
|-------|---------|
| 🟥 **RED** | Over a Connecticut legal limit, a zero-tolerance pathogen, or a mycotoxin over limit — *do not consume* |
| 🟧 **ORANGE** | A heavy metal or mycotoxin **detected but within** its legal limit — caution, especially if sensitive |
| 🟨 **YELLOW** | Yeast & mold over this tool's stricter 10,000 CFU/g **watch line** (still legal in CT), or a residual solvent detected within limit |

Connecticut's codified standards (Conn. Agencies Regs. §21a-408-60): zero
tolerance for *E. coli*, STEC, *Salmonella*, *Listeria*, and pathogenic
*Aspergillus*; yeast & mold and total aerobic ≤ 100,000 CFU/g; mycotoxins
< 20 µg/kg each; plus heavy-metal and residual-solvent action limits.

---

## Run from source

```bash
git clone https://github.com/jmlschlee/Connecticut-Cannabis-Contaminant-Checker-Beta-V1.git
cd Connecticut-Cannabis-Contaminant-Checker-Beta-V1

python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

python connecticut_cannabis_contaminant_checker_beta_v1.py   # last 30 days, all inhalable
```

Outputs land in `./ct_audit_output/`:

| File | What it is |
|------|------------|
| `flagged_products.pdf` | color-coded report with COA links |
| `coa_results_full.csv` | every analyte value parsed, per product |
| `parse_failures.csv`   | COAs that couldn't be read (e.g. scanned images) |
| `raw_coas/`            | cached COA PDFs |

### Common options

```bash
python connecticut_cannabis_contaminant_checker_beta_v1.py --limit 50          # quick test
python connecticut_cannabis_contaminant_checker_beta_v1.py --forms flower      # flower only
python connecticut_cannabis_contaminant_checker_beta_v1.py --days 60           # last 60 days
python connecticut_cannabis_contaminant_checker_beta_v1.py --since 2026-01-01  # explicit start
python connecticut_cannabis_contaminant_checker_beta_v1.py --threshold 5000    # stricter watch line
python connecticut_cannabis_contaminant_checker_beta_v1.py --workers 12        # more download workers
```

Run with `-h` for all options.

## Running the tests

The test suite is **offline** (no network) and checks the parsing/flagging logic
against synthetic COA snippets that mirror the real lab formats:

```bash
python tests/test_contaminant_checker.py
# -> ALL TESTS PASSED (16 checks)
```

## If COAs come back "Document does not exist"

The state portal is session-gated. If downloads fail, open
<https://www.elicense.ct.gov/lookup/licenselookup.aspx> in your browser, run any
product lookup, export cookies with a "cookies.txt" browser extension, and pass
`--cookies cookies.txt`.

## Optional OCR (for scanned-image COAs)

Some COAs are scanned images with no embedded text. To read those, install the
OCR engine:

```bash
pip install pytesseract pypdfium2
#   macOS:         brew install tesseract
#   Ubuntu/Debian: sudo apt install tesseract-ocr
#   Windows:       https://github.com/UB-Mannheim/tesseract/wiki
```

Without it, scanned-image COAs are simply listed in `parse_failures.csv`.

## Building true standalone executables (optional)

`.github/workflows/build.yml` builds a single-file executable for Windows,
macOS, and Linux automatically when you push a version tag (e.g. `v0.1.0-beta`)
and attaches them to the matching GitHub Release — so users wouldn't need Python
at all. (Requires the workflow to have permission to create releases.)

## Notes & limitations (Beta)

- Parsing is best-effort across many lab formats. **Treat flags as leads and
  verify against the linked COA.**
- Heavy-metal and mycotoxin amounts are read with the COA's **own units and
  limit columns** to avoid unit-conversion mistakes.
- Vape/extract COAs that report solvents only as a grouped "below action limits"
  panel don't expose individual solvent values when passing.
- Reruns reuse a local cache and skip already-scanned-clean COAs, so they're much
  faster than the first run.

## Project files

| File | Purpose |
|------|---------|
| [`DISCLAIMER.md`](DISCLAIMER.md) | **Read this** — scope, accuracy, and "leads not conclusions" |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | How to report a misread COA or contribute |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |
| [`LICENSE`](LICENSE) | MIT |

## License

[MIT](LICENSE) — provided "as is," without warranty. See [`DISCLAIMER.md`](DISCLAIMER.md).
