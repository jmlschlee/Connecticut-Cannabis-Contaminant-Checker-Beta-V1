# CannaScope CT V11.1 Beta — Emergency COA Integrity Patch

**This is a data-integrity release. Please use V11.1 instead of V11.**

CannaScope CT reads Connecticut's public cannabis product registry and each product's
Certificate of Analysis (COA), checks the lab results against Connecticut's limits, and writes
clear PDF reports. V11.1 hardens the single most important promise the tool can make:

> **If the report shows a result, you can click that row's COA link and see that exact result in
> that exact document.** Anything that can't be proven against its own COA is never published —
> it is held for manual review instead.

---

## What V11.1 fixes / adds (the short version)

- **Emergency COA source-binding audit (both reports).** Before anything is published, every
  flagged value is independently re-opened in its **own** linked COA and re-verified. If the exact
  value isn't found in that document, the row is **excluded and routed to a manual-review queue** —
  never shown as a finding.
- **Nothing unverified is ever shown.** New rule, enforced in code, in *both* the statewide report
  and the consumer report.
- **New integrity outputs:** a provenance audit CSV, a COA Source Mismatch Review CSV, and a
  Multiple-COA Alert CSV — plus a "COA Source-Binding Audit" panel in the report's diagnostics.
- **New honest status:** `FAIL SOURCE VALIDATION` if any published value couldn't be verified
  (and `PASS WITH WARNINGS` if mismatches were found and excluded).
- **Baked-in speed caches** (carried in from late V11): an embedded registry snapshot (skips the
  big download when fresh; offline/again-down resilience; online still auto-refreshes so data
  stays current) and an opt-in `--fast-cached` first-run mode.

---

## The bug this prevents (in plain terms)

The fear: the report could display, say, **Yeast & Mold 380,000 CFU/g (FAIL)** on a row, but the
COA link could open a *different* document showing **22,300 CFU/g (PASS)** — so a reader clicking
through would see a different (or passing) result than the one reported.

**What we found when we investigated:** this was **not actually happening** — each value is parsed
from the exact COA the row links to, every product has a unique COA key (so the cache can't serve
the wrong file), and there was already a check that a value must appear in its COA. We even
re-checked the real 380,000 row: its linked COA genuinely contains 380,000.

**What V11.1 changes:** that protection is now **explicit, enforced, and auditable** rather than
implicit. Every published value is re-verified against its own COA at the end of the run, the
result is written to a provenance CSV you can audit, and any value that can't be confirmed is
removed from the findings and sent to manual review. Integrity is prioritized over completeness:
**it is better to publish fewer rows than to publish one row tied to the wrong COA.**

---

## The program has two modes — for a first-time user

CannaScope CT is **one file** with **two different jobs**. Pick the one that matches what you want.

### 1) Statewide Transparency Report  →  `statewide`
**Use this to look at the whole Connecticut market.** It scans every product in a date window and
produces a long, table-rich PDF: which products came closest to (or over) a limit, producer and
lab patterns, high-cannabinoid products, the Ombudsman patient-safety review, potential
statute/regulatory flags, and more — every row with a clickable COA link.
```
python3 CannaScope_CT_Beta_V11_1.py statewide --days 365
python3 CannaScope_CT_Beta_V11_1.py statewide --since 2024-01-01 --until 2024-12-31
```
Helpful options: `--fast-cached` (faster first run, lower coverage), `--no-ocr`, `--workers N`,
`--offline`. Output lands in `CannaScope CT Beta V11.1 - Statewide Transparency Reports/`.

### 2) Personalized Product Concern Report  →  `concern`
**Use this when a specific person is worried about one specific product they bought.** Give it
whatever is on the package — product name, batch, NDC, UID/BioTrack lot, COA number, dates, or the
QR link — and it finds that product, checks its COA, answers the concern in plain language
(a "Complaint Investigation Summary"), shows how close any result came to a limit, and links
related batches so they can compare. **It is advisory and is not medical advice.**
```
python3 CannaScope_CT_Beta_V11_1.py concern --batch <BATCH> --ndc <NDC> --qr <URL> --concern "didn't feel well after use"
python3 CannaScope_CT_Beta_V11_1.py concern --example     # built-in demo
```
Output lands in `output/consumer_concerns/`.

> **Quick rule of thumb:** *statewide* = the whole market; *concern* = one product a consumer has
> in hand. They are separate, write to separate folders, and the consumer report is never mixed
> into the statewide report.

Both modes **number every report and never overwrite** older ones — your full history is preserved.

---

## What changed between V11 and V11.1

| Area | V11 | V11.1 |
|---|---|---|
| COA source verification | Implicit (value parsed from the linked COA; one in-COA check) | **Explicit, enforced audit**: every published value re-verified in its own COA; failures excluded to manual review — in **both** reports |
| Manual-review routing | COA verification queue only | **+ COA Source Mismatch Review** queue/CSV; consumer report shows a "held for manual review" note |
| Integrity reporting | — | **Provenance audit CSV**, **Multiple-COA Alert CSV**, diagnostics panel, new metrics |
| Status | PASS / PASS WITH WARNINGS / FAIL | **+ FAIL SOURCE VALIDATION** |
| First-run speed | downloads everything | embedded registry snapshot + opt-in `--fast-cached` (carried in) |

Everything else — thresholds, calculations, COA-verification standards, section order, the
Ombudsman section, and report numbering — is unchanged.

---

## Downloads
- `CannaScope CT Beta V11.1 - Windows.zip`
- `CannaScope CT Beta V11.1 - macOS.zip`
- `CannaScope CT Beta V11.1 - Linux.zip`

Each is the single self-contained `CannaScope_CT_Beta_V11_1.py` + a launcher (`run.bat` /
`run.sh`), README, INSTALL guide, LICENSE, and requirements. **Windows:** unzip →
`run.bat statewide --days 90`. **macOS / Linux:** unzip → `./run.sh statewide --days 90`.
All prior releases (V11, V10, and earlier) remain available, unchanged.

## Requirements
Python 3.9+ and: `requests reportlab pypdfium2 pdfplumber Pillow psutil` (OCR optional: `ocrmac`
on macOS, or `pytesseract` + the Tesseract binary elsewhere). First online run refreshes the data.

## Beta notice
Pre-release for evaluation. Outputs are review aids, **not legal or medical advice**; confirm
citations against eRegulations.ct.gov and have a qualified compliance officer or attorney validate
flags before acting. The consumer report points people to a healthcare provider plus the CT Office
of the Cannabis Ombudsman and the Department of Consumer Protection.
