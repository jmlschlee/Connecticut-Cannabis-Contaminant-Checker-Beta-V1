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

## How it works

Everything it reports comes from **public data** — Connecticut's product registry
and the lab COAs that registry links to. The pipeline:

1. **Download the registry.** It pulls Connecticut's public registry CSV
   (dataset `egd5-wb6r`) and caches it locally so reruns are fast.
2. **Pick the products.** It filters to the inhalable forms you asked for
   (default: all inhalable, last 30 days) — flower, pre-rolls, vapes, carts,
   concentrates, extracts. Edibles, tinctures, and topicals are excluded.
3. **Fetch each COA.** For every product it opens the linked Certificate of
   Analysis PDF from the state portal (warming a browser-like session so the
   gated portal serves the file).
4. **Read the PDF.** Text is extracted with `pdfplumber`; if a COA is a scanned
   image, an optional OCR step (tesseract) is tried, otherwise it's listed in
   `parse_failures.csv` for manual review — never silently dropped.
5. **Parse each analyte carefully.** For every contaminant it locates the
   analyte's **label** (e.g. "Arsenic", "Total Yeast & Mold", "Ochratoxin A") and
   reads the result on that row — **never a stray nearby number**. It reads the
   value against the **COA's own limit column, in the COA's own units**, which is
   how it avoids unit-conversion mistakes (e.g. µg/kg vs µg/g).
6. **Apply the rules.** Zero-tolerance pathogens (any detection) and over-limit
   results → RED; a heavy metal or mycotoxin detected within its limit → ORANGE;
   yeast & mold over the 10,000 CFU/g watch line (but legal) or a solvent within
   limit → YELLOW. See "What the colors mean" above.
7. **Write the report.** It produces the color-coded `flagged_products.pdf`, a
   full `coa_results_full.csv` (every value parsed), and caches COAs so the next
   run skips everything already scanned clean.

It is deliberately conservative about claims: when a value can't be read with
confidence, the COA is sent to manual review rather than guessed.

---

## ⚠️ Always cross-check against the actual COA — and report errors

**This is a Beta tool, and you should treat every flag as a starting point, not a
verdict.** COA PDFs come in many lab-specific layouts and are parsed
automatically; mistakes happen.

- **Verify before you rely on anything.** Each row in the report includes the
  product's **COA registration number** (e.g. `MMBR.0033539`). Look that COA up
  on the state portal, open it, and confirm the number with your own eyes before
  drawing any conclusion or sharing it.
- **A flag is a lead, not proof.** It means "an automated read of public data
  warranted a closer look" — nothing about any lab's or producer's conduct.
- **Found a misread? Please report it.** That's the single most helpful thing you
  can do to make this better. Open an
  [**issue**](../../issues/new?template=coa_parsing_issue.md) with the COA
  number, what the tool said, and what the COA actually says (a screenshot of the
  COA row is ideal). See [`CONTRIBUTING.md`](CONTRIBUTING.md).

Full terms in [`DISCLAIMER.md`](DISCLAIMER.md).

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
