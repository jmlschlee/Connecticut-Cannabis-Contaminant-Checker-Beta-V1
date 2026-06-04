<div align="center">

# 🌿 CannaScope CT V13

### Connecticut Cannabis Transparency Report
**Source-verified consumer-awareness & testing-pattern review**

[![Latest Release](https://img.shields.io/github/v/release/jmlschlee/CannaScope-CT?label=latest%20release&color=2ea44f)](https://github.com/jmlschlee/CannaScope-CT/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/jmlschlee/CannaScope-CT/total?color=blue)](https://github.com/jmlschlee/CannaScope-CT/releases)
[![License](https://img.shields.io/badge/license-see%20LICENSE-lightgrey)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab)](https://www.python.org/)

*Every flag is a **lead, not a conclusion.** Verify every product against its live COA.*

</div>

---

> ### 🆕 What's new in CannaScope CT **V13**
> V13 is a big readability + integrity + feature release. **New:** a neutral **Conflicting COA Results & Possible Lab-Shopping Indicators** section (same physical lot with conflicting pass/fail across labs — judged against each COA's own stated limit — *requires human review, never alleges misconduct*); the **High-Cannabinoid breakdown** (THCA · Δ9-THC · CBD · Total THC · Total Cannabinoids); reworked **Potential Compliance Review Leads** (buckets A–D + chemistry consistency checks). **Fixed:** honest producer percentages, a clear dataset-accounting line, hardened report numbering (one uniquely-numbered file, no overwrite), a box-overlap rendering bug. **Cleaner:** a *Most Important Findings* box, a *How To Read* legend, a publication-first section order with all technical material in an **Appendix**. **Removed:** the two potency-reference sections and five redundant *Top…* mini-tables. Advisory — not legal or medical advice.
>
> **V13 downloads:** [Windows](https://github.com/jmlschlee/CannaScope-CT/releases/download/v13.0.0/CannaScope.CT.V13.-.Windows.zip) · [macOS](https://github.com/jmlschlee/CannaScope-CT/releases/download/v13.0.0/CannaScope.CT.V13.-.macOS.zip) · [Linux](https://github.com/jmlschlee/CannaScope-CT/releases/download/v13.0.0/CannaScope.CT.V13.-.Linux.zip) · [release notes »](https://github.com/jmlschlee/CannaScope-CT/releases/tag/v13.0.0)

---


## ⬇️ Download — pick your operating system

> **One self-contained file.** Each download contains the entire program plus a one-click launcher, quick-start guide, and license. No companion files, no build step.

| Operating System | Download | How to launch |
|---|---|---|
| 🪟 **Windows** | **[CannaScope CT V13 - Windows.zip](https://github.com/jmlschlee/CannaScope-CT/releases/download/v13.0.0/CannaScope.CT.V13.-.Windows.zip)** | unzip → `run.bat statewide --days 90` |
| 🍎 **macOS** | **[CannaScope CT V13 - macOS.zip](https://github.com/jmlschlee/CannaScope-CT/releases/download/v13.0.0/CannaScope.CT.V13.-.macOS.zip)** | unzip → `chmod +x run.sh && ./run.sh statewide --days 90` |
| 🐧 **Linux** | **[CannaScope CT V13 - Linux.zip](https://github.com/jmlschlee/CannaScope-CT/releases/download/v13.0.0/CannaScope.CT.V13.-.Linux.zip)** | unzip → `chmod +x run.sh && ./run.sh statewide --days 90` |

➡️ **[See all downloads & release notes on the Releases page »](https://github.com/jmlschlee/CannaScope-CT/releases/latest)**
&nbsp;•&nbsp; The self-contained `CannaScope_CT_V13.py` (everything baked in) is inside each download zip above.

---

## What it does

CannaScope CT pulls Connecticut's **public** cannabis product registry, fetches each product's **live Certificate of Analysis (COA)**, parses it, and produces a polished, source-verified **consumer-awareness report** (PDF + CSV exports). It surfaces patterns worth a closer look — contaminant readings near the legal limit, unusually high cannabinoid content, possible remediation signals, conflicting COA results across lab reports, and producer/lab testing trends — while refusing to overstate them.

**Its guiding rule:** every flag is a *lead*, not a verdict. A value is only published if it literally appears in that product's live COA and the applicable Connecticut legal limit supports the concern.

CannaScope CT runs as **two reports in one program:**
- **Statewide Transparency Report** (`statewide`) — a whole-market scan.
- **Personalized Product Concern Report** (`concern`) — a careful, advisory review of one product a consumer is worried about (resolved from any identifiers). Advisory only — *not medical advice.*

## Highlights

- 🆕 **Conflicting COA Results & Possible Lab-Shopping Indicators** *(new in V13, statewide report)* — neutrally surfaces, **for human review**, when the same physical lot shows conflicting pass/fail results across lab reports (especially an earlier fail then a later pass), or when one COA carries more than one lab identity. Side-by-side comparisons, source/page references, severity tiers, and explicit innocent-explanation language. **No claims of wrongdoing.**
- 🛡️ **Per-line-item COA verification (anti-hallucination)** — every flagged value must be found, as a distinct number, in the COA's own text or it is excluded from all findings and routed to manual review. Enforced in both reports, with a COA Source-Binding Audit and provenance CSVs.
- 🧪 **Full contaminant engine** — yeast & mold, total aerobic bacteria, heavy metals (arsenic, cadmium, chromium, lead, mercury), mycotoxins, residual solvents, and zero-tolerance pathogens, each ranked by proximity to the Connecticut legal limit.
- 🧫 **Lab- & date-aware Yeast/Mold (TYM) Standard Review** — Connecticut's passing limit for total yeast & mold varied by **lab** and **date** (up to 100×); each result is shown against three benchmarks (the lab's limit on its test date / the current limit / a strict patient-protective benchmark).
- 🧬 **Three-category product taxonomy** — non-infused flower, infused flower products, and vapes/concentrates/extracts kept **strictly separate**.
- 🌾 **High-cannabinoid review** with implausible-value rejection (a "flower" reading above ~45% is treated as a parse error, not a finding).
- 🩺 **Patient-safety & compliance leads** — a CT Cannabis Ombudsman "closest to a contaminant limit" review and a "Potential Statute & Regulatory Flags to Evaluate" section, both human-review-only with cited (unverified) authorities — never determinations.
- 🏷️ **Producer / DBA identity resolution** with a 0–100 source-confidence score, cited against public CT records.
- 📅 **Multi-year support** — bound any window with `--since` / `--until`, from a single quarter to the full **2015–2026** registry (~33k products); per-section tables are capped so the PDF stays readable while the complete data lands in the CSVs.
- 🛡️ **Crash-proof, self-pacing OCR** — scanned/image-only COAs are OCR'd in an isolated subprocess (a native crash kills only that child, never the run); on big runs it **slows down and serializes OCR before the machine can run out of memory, so no document is missed.**
- 📦 **Offline / bundled-sources mode** — run once with `--keep-clean-pdfs` to cache every COA, then re-run fully offline with `--offline`.
- 🧾 **Reports are never overwritten** — each is uniquely numbered from 1 and date-stamped.
- ✅ **Self-audit + zero-result verification** — the report documents how it checked itself, and honestly reports `PASS` / `PASS WITH WARNINGS` / `DRAFT` / `FAIL`.

## Quick start

```bash
# any OS, with Python 3.9+
python3 -m pip install -r requirements.txt
python3 CannaScope_CT_V13.py statewide --since 2024-01-01 --until 2024-12-31
# one product a consumer is worried about:
python3 CannaScope_CT_V13.py concern --example
```

Or use the bundled launcher for your OS (see the download table above).

### Useful options
| Option | What it does |
|---|---|
| `--since YYYY-MM-DD` / `--until YYYY-MM-DD` | bound any date range, including multiple years |
| `--days N` | look back N days instead of `--since` |
| `--forms flower\|inhalable\|all` | product scope (default `all`) |
| `--keep-clean-pdfs` | keep **every** COA PDF → a complete local "sources" bundle |
| `--offline` | run from the bundle only, no network |
| `--fast-cached` | opt-in faster first run (skips embedded already-verified-clean COAs) |
| `--no-ocr` | skip OCR (image-only COAs are not read) |
| `--workers N` | download concurrency |

## Output

A folder **`CannaScope CT V13 - Statewide Transparency Reports/`** is created beside the program containing:
- the **PDF report** (cover dashboard, Findings at a Glance, the new Conflicting COA Results section, top findings, per-contaminant tables, high-cannabinoid review, TYM standard review, Ombudsman & regulatory-flag leads, producer/lab trends, validation & diagnostics),
- **CSV exports** for every section (including `conflicting_coa_results.csv`),
- the **registry cache** and the **source COA PDFs** for flagged products,
- a plain-text executive summary and a debug log.

The Personalized Product Concern Report writes to **`output/consumer_concerns/`**.

## Requirements

Python 3.9+ and the packages in [`requirements.txt`](requirements.txt) (installed automatically by the launchers). OCR is optional but recommended: **macOS** uses Apple Vision automatically; **Windows/Linux** use Tesseract.

## 💬 Feedback welcome — it directly improves the tool

Spotted a mis-parse, a COA that didn't read, or have an idea?
**[Open an issue »](https://github.com/jmlschlee/CannaScope-CT/issues)** or start a **[discussion »](https://github.com/jmlschlee/CannaScope-CT/discussions)**. Real-world COA examples and edge cases are especially valuable. ⭐ Star the repo if you find it useful.

## Version history

Every prior version remains available — **nothing is removed.** See the **[Releases page](https://github.com/jmlschlee/CannaScope-CT/releases)** for V11.1, V11, V10, V9.1, and earlier and their assets, and [`CHANGELOG.md`](CHANGELOG.md) for details.

## ⚖️ Disclaimer

CannaScope CT is a **consumer-awareness research tool**, not legal, medical, or professional advice, and not affiliated with the State of Connecticut. Findings — including everything in the Conflicting COA Results section — are leads to verify, not conclusions or accusations. Always confirm against the official, live COA. See [`DISCLAIMER.md`](DISCLAIMER.md).
