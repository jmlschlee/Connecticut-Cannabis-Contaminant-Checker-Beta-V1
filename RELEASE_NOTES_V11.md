# CannaScope CT V11 Beta

**What it is.** CannaScope CT is a Connecticut-focused cannabis testing & compliance analysis
tool. It reads Connecticut's public cannabis product registry and each product's Certificate
of Analysis (COA), parses the mandated contaminant panels (heavy metals, pesticides,
microbials/mold, mycotoxins, residual solvents) plus cannabinoids, evaluates every result
against the Connecticut action limit, and produces source-verified PDF reports with clickable
COA links throughout. **Every flag is a lead, not a conclusion** — values that match a limit or
can't be confirmed are routed to manual review, never published as findings.

This release is **one self-contained file** (`CannaScope_CT_Beta_V11.py`): the download/OCR/parse
engine, the cannabinoid + identity layer, the producer/lab name resolver, and the crash-isolated
OCR worker are all embedded. No companion files — just Python + the libraries in
`requirements.txt`.

---

## The program has two reports

### 1. Statewide Transparency Report  (`statewide`, also the default)
A whole-market scan over a date window — for transparency, trends, and compliance leads.
```
python3 CannaScope_CT_Beta_V11.py statewide --days 180
python3 CannaScope_CT_Beta_V11.py statewide --since 2024-01-01 --until 2024-12-31
```
Sections: Executive Summary + **Findings at a Glance**; Producer Trends; Lab Trends; Top
Findings; per-contaminant tables (Yeast & Mold, Total Aerobic Bacteria, Arsenic, Chromium,
Cadmium, Lead, Mercury, Mycotoxins, Residual Solvents, Pesticides, Pathogens); High-Cannabinoid
/ High-THC; Infused-product and Vape/Concentrate/Extract potency references; Possible
Remediation (with a producer-frequency summary); Lower-Concern Products; No-Significant-Findings;
**Potential Statute & Regulatory Flags to Evaluate**; **CT Cannabis Ombudsman — Medical Patient
Safety Review**; Validation & Diagnostics. Plus CSV exports of everything. Output folder:
`CannaScope CT Beta V11 - Statewide Transparency Reports/`.

### 2. Personalized Product Concern Report  (`concern`)
An on-demand, single-product report for a consumer worried about one product.
```
python3 CannaScope_CT_Beta_V11.py concern --batch <BATCH> --ndc <NDC> --qr <QR-URL> --concern "felt unwell after use"
python3 CannaScope_CT_Beta_V11.py concern --example     # built-in demo
```
It resolves the product from whatever identifiers the consumer has (name, brand, batch, NDC,
UID/BioTrack lot, COA #, dates, QR link) against the registry + its COA, then answers the
concern from the testing data. Output folder: `output/consumer_concerns/`. **Advisory and
non-diagnostic — not medical advice.**

> **Tip — which one?** Use **statewide** to study the whole market (or pull the underlying CSVs).
> Use **concern** when a specific consumer has a specific product in hand. They are separate
> programs with separate output folders; the consumer report is never mixed into the statewide
> report.

---

## Existing features (all baked into V11)

**Statewide report**
- COA-grounded **Potential Statute & Regulatory Flags** — over-legal-limit result, detected
  zero-tolerance pathogen, or failed pesticide/solvent panel — each a human-review lead with a
  cited (verify-in-eRegulations) authority. *Leads to evaluate, not legal determinations.*
- **CT Cannabis Ombudsman — Medical Patient Safety Review** (for the Office of the Cannabis
  Ombudsman, PA 23-79): products that PASSED but rode closest to a CT action limit, ranked.
- **COA dates + live clickable COA links** on every referenced product line.
- Producer & lab trend tables, per-contaminant findings, high-cannabinoid review, potency
  references, possible-remediation review, lower-concern products, full CSV exports.

**Engine**
- Multi-lab COA parsing (Northeast Laboratories, AltaSci, Analytics Labs, Advanced Grow Labs),
  field-aware extraction; below-detection / limit / LOQ / LOD values are never published as
  measurements; crash-isolated OCR for scanned COAs; offline source bundle; numbered,
  never-overwritten reports.

*Reserved / dormant:* a broader Compliance Screening engine and an Environmental Linkage module
exist in-code as Phase-2 designs but are intentionally not wired in.

## New & improved in V11

- **Clean two-report naming** — the whole-market run is now the **Statewide Transparency Report**
  (`statewide`) and the single-product run is the **Personalized Product Concern Report**
  (`concern`), each with its own output folder. (Older sub-command names still work.)
- **Statewide page 1–3 layout polish** — intentional spacing on the cover/summary; the three top
  summary tables (Heavy Metal, Microbial, High Cannabinoid) now breathe and flow cleanly across
  pages instead of crowding; **Findings at a Glance** findings-first summary up top; a duplicate
  producer section was consolidated; concise trend notes added after major sections.
- **COA IDs never wrap** and stay clickable, inside their column, full product names preserved.
- **Consumer report overhaul** — a prominent **PRODUCT OF CONCERN** header; a **Complaint
  Investigation Summary** that answers the concern (per-class Yes/No + a careful, non-causal
  summary); **severity tiers** (Elevated / High / Very High / Extremely Close To Limit);
  producer names shown as **legal entity + brand** (e.g. *FFD 149 LLC (Fine Fettle / Comffy)*);
  **Producer Trend Context** (how often a producer appears in the statewide findings on file);
  smarter **related/sibling-COA comparison** (ranked same-product → same-size → closest date)
  so a consumer can compare batches; a **"Why this product was matched"** explanation; and
  identifier-discrepancy surfacing. Cautious, non-diagnostic language throughout.

## Downloads
- `CannaScope CT Beta V11 - Windows.zip`
- `CannaScope CT Beta V11 - macOS.zip`
- `CannaScope CT Beta V11 - Linux.zip`

Each contains the single self-contained file + a launcher (`run.bat` / `run.sh`), README,
INSTALL guide, LICENSE, and requirements. **Windows:** unzip → `run.bat statewide --days 90`.
**macOS / Linux:** unzip → `./run.sh statewide --days 90`. All prior releases remain available,
unchanged.

## Requirements
Python 3.9+ and: `requests reportlab pypdfium2 pdfplumber Pillow psutil` (OCR optional: `ocrmac`
on macOS, or `pytesseract` + the Tesseract binary elsewhere). First run needs internet; repeat
runs reuse a local cache.

## Beta notice
Pre-release for evaluation. Compliance and consumer outputs are review aids, **not legal or
medical advice**; confirm citations against eRegulations.ct.gov and have a qualified compliance
officer or attorney validate flags before acting. The consumer report points people to a
healthcare provider plus the CT Office of the Cannabis Ombudsman and the Department of Consumer
Protection.
