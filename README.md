# CannaScope Beta V5

**Connecticut Cannabis Transparency Report — Source-Verified Consumer Awareness & Testing Pattern Review**

> **Every flag is a lead, not a conclusion.** CannaScope Beta V5 does not claim fraud, unsafe product, or legal failure unless the live COA and the applicable Connecticut legal limit directly support that claim. Verify every product against its COA.

CannaScope reads Connecticut's public cannabis product registry, opens each product's lab Certificate of Analysis (COA), extracts the full contaminant and cannabinoid panel, and produces a clean, source-verified PDF that surfaces products worth a closer look — for consumers, journalists, regulators, legislators, and medical patients.

---

## ⬇️ Download CannaScope Beta V5

Grab the package for your operating system, unzip it, and run the launcher.

| Operating system | Download |
|---|---|
| 🪟 **Windows** | **`CannaScope_Beta_V5_Windows.zip`** → unzip → double-click **`run.bat`** |
| 🍎 **macOS** | **`CannaScope_Beta_V5_macOS.zip`** → unzip → run **`./run.sh`** |
| 🐧 **Linux** | **`CannaScope_Beta_V5_Linux.zip`** → unzip → run **`./run.sh`** |

> Downloads are published on the [**Releases**](../../releases) page under tag `v5.0.0-beta`. The latest generated report, **`CannaScope_Beta_V5_Report.pdf`**, is attached to the release as well.

Each launcher creates a local virtual environment, installs the dependencies, and runs the tool. Python 3.10+ is required.

---

## What CannaScope Beta V5 does

1. **Pulls the data** — downloads Connecticut's *Medical Marijuana and Adult-Use Cannabis Product Registry* (data.ct.gov dataset `egd5-wb6r`).
2. **Reads every COA** — opens each product's lab-analysis PDF (with OCR fallback for scanned COAs) and extracts the full panel: yeast & mold, total aerobic bacteria, heavy metals (arsenic, chromium, cadmium, lead, mercury), mycotoxins, residual solvents, pathogens, and cannabinoid potency.
3. **Compares to two thresholds** — the **Connecticut legal limit** (the COA's own action limit) and the stricter **CannaScope Limit** (a consumer-awareness threshold, *not* a legal-failure standard).
4. **Validates every finding** — re-checks each flagged row against its live COA, scores producer/DBA identity against public sources, and treats unexpected zero-results as suspected parser errors until verified.
5. **Publishes a professional PDF** — `CannaScope_Beta_V5_Report.pdf`, with clickable COA links, testing dates, producer and lab trends, and clear severity coloring.

### What is a COA?

A **Certificate of Analysis** is the lab report a licensed testing laboratory issues for a cannabis batch. It lists the measured contaminant and potency values and the action limits they are compared against. CannaScope links directly to the source COA for every finding so you can verify it yourself.

### What "flagged" means

A product is **flagged** when a *trustworthy, quantified* measurement crosses the CannaScope consumer-awareness threshold (or a zero-tolerance pathogen is reported detected, or a pesticide/solvent panel fails). A flag is a **lead for verification**, never a verdict.

### Color system (per-measurement severity)

| Color | Meaning |
|---|---|
| 🔴 **RED** | Near or over the Connecticut legal limit |
| 🟠 **ORANGE** | Elevated |
| 🟡 **YELLOW** | Above the CannaScope threshold |
| 🟢 **GREEN** | Below the threshold (not flagged) |

### Key terms

- **CT % Of Limit** — measured value ÷ Connecticut legal limit × 100.
- **CannaScope Limit** — the stricter consumer-awareness threshold (Yeast & Mold / Total Aerobic Bacteria = 10,000 CFU/g; every other contaminant = 50% of the CT legal limit).
- **Difference From CannaScope** — how far above (+) or below (−) the CannaScope threshold a result sits.
- **Testing Date** — the COA's test/sample date (never the report-generation date).
- **High Cannabinoid Content / High THC Content Review** — non-infused flower whose reliable cannabinoid reading exceeds 35%. This identifies *unusually high cannabinoid content for review* — it is **not** an accusation against any producer.
- **Infused & Extract Potency Comparison Reference** — concentrated products (infused pre-rolls, hash/THCA-infused items, vapes, concentrates, extracts) shown to compare against normal flower. High potency here is expected by design and is **not** a flower abnormality.
- **Possible Remediation / Unusually Low Microbial Load** — flower with an unusually low or ND microbial reading. **This is not proof of remediation.** It is a consumer-awareness lead and should be verified against the live COA.
- **PASS WITH WARNINGS** — the validation status when the report is publishable but non-blocking issues exist (e.g. potency-parser conflicts held out of rankings, or COAs that could not be auto-confirmed). Status values: `PASS`, `PASS WITH WARNINGS`, `DRAFT`, `FAIL`.

### What the report does **not** claim

CannaScope does **not** assert that any product is fraudulent, unsafe, illegally produced, or that it failed Connecticut testing. CannaScope thresholds are stricter than Connecticut's legal limits; a flag means a result crossed a *consumer-awareness* threshold and is worth verifying — nothing more.

---

## How to run it

If you downloaded a release ZIP, just run the launcher (`run.bat` on Windows, `./run.sh` on macOS/Linux).

To run from source:

```bash
pip install -r requirements.txt          # requests reportlab pypdfium2 (+ optional OCR)
python cannascope_beta_v5.py              # defaults: last 60 days, all product types
```

Common options:

```bash
python cannascope_beta_v5.py --days 365             # one-year window
python cannascope_beta_v5.py --since 2026-01-01     # explicit start date
python cannascope_beta_v5.py --forms flower         # flower only
python cannascope_beta_v5.py --limit 100            # cap COAs scanned (quick test)
python cannascope_beta_v5.py --workers 12           # concurrency
```

Outputs are written to `CannaScope Beta V5 - Reports/`, and the report is also copied to the working folder as **`CannaScope_Beta_V5_Report.pdf`**, alongside CSV exports (per-contaminant severity tables, high-cannabinoid review, producer/lab identity + confidence, validation queues, and a full per-product scan).

## How to build a release ZIP

```bash
# from the repository root
zip -r CannaScope_Beta_V5_macOS.zip   CannaScope_Beta_V5 -x '*/.venv/*'
zip -r CannaScope_Beta_V5_Linux.zip   CannaScope_Beta_V5 -x '*/.venv/*'
zip -r CannaScope_Beta_V5_Windows.zip CannaScope_Beta_V5 -x '*/.venv/*'
```

(The three packages contain the same source; they differ only in the included launcher — `run.bat` for Windows, `run.sh` for macOS/Linux.)

---

## Requirements

- **Python 3.10+**
- `requests`, `reportlab`, `pypdfium2`
- Optional OCR for scanned COAs: `ocrmac` (macOS) or `pytesseract` + the `tesseract` binary (other platforms)

---

## Version history

CannaScope grew through several internal development builds. **The public-facing release is standardized as CannaScope Beta V5.** Earlier builds carried "V7" naming during development; they are preserved for transparency, and no older version has been deleted. See [`CHANGELOG.md`](CHANGELOG.md) for the full history.

- **CannaScope Beta V5** — public release. Source-verified report with testing dates, CT/CannaScope limit comparisons, producer & lab trends, high-cannabinoid review, infused/extract comparison, possible-remediation safeguards, clickable COA links, and a full validation/diagnostics appendix.
- Earlier public builds — **Beta V1** (contaminant checker), **CannaScope CT V2 / V3 / V4** — and the internal **"V7"** report builds all remain in the repository history and tree, with their downloads under `downloads/`. No older version was removed.

---

## Documentation

- [`DISCLAIMER.md`](DISCLAIMER.md) — full disclaimer and limitations
- [`docs/user-guide.md`](docs/user-guide.md) — running the tool and reading the report
- [`docs/report-fields.md`](docs/report-fields.md) — every column and term explained
- [`docs/validation-methodology.md`](docs/validation-methodology.md) — how findings are validated
- [`CHANGELOG.md`](CHANGELOG.md) / [`RELEASE_NOTES.md`](RELEASE_NOTES.md) — what changed

---

*CannaScope Beta V5 is an independent consumer-awareness project. It is not affiliated with the State of Connecticut or any cannabis producer or laboratory.*
