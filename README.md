<div align="center">

# 🌿 CannaScope CT Beta V9.1

### Connecticut Cannabis Transparency Report
**Source-verified consumer-awareness & testing-pattern review**

[![Latest Release](https://img.shields.io/github/v/release/jmlschlee/CannaScope-CT-Beta-V9.1?label=latest%20release&color=2ea44f)](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/jmlschlee/CannaScope-CT-Beta-V9.1/total?color=blue)](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases)
[![License](https://img.shields.io/badge/license-see%20LICENSE-lightgrey)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab)](https://www.python.org/)

*Every flag is a **lead, not a conclusion.** Verify every product against its live COA.*

</div>

---

> ### 🆕 CannaScope CT **V9.1** — now available
> New in V9: a **Compliance Screening** section (potential Connecticut statutory/regulatory flags to *investigate*, with cited authorities and clickable COA links) and a **CT Cannabis Ombudsman — Medical Patient Safety Review** section (products that *passed* testing but came closest to a CT action limit, ranked). Review aids — not legal or medical advice. V9 is the current release; V7.2 and all prior versions remain available below.
>
> **V9 Beta downloads:** [Windows](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases/download/v9.1.0-beta/CannaScopeCT-v9.1.0-beta-windows.zip) · [macOS](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases/download/v9.1.0-beta/CannaScopeCT-v9.1.0-beta-macos.zip) · [Linux](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases/download/v9.1.0-beta/CannaScopeCT-v9.1.0-beta-linux.zip) · [release notes »](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases/tag/v9.1.0-beta)

---


## ⬇️ Download — pick your operating system

> **One self-contained file.** Each download contains the entire program plus a one-click launcher, quick-start guide, and license. No companion files, no build step.

| Operating System | Download | How to launch |
|---|---|---|
| 🪟 **Windows** | **[CannaScope_CT_V7_2_Windows.zip](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases/latest/download/CannaScope_CT_V7_2_Windows.zip)** | unzip → double-click `run.bat` |
| 🍎 **macOS** | **[CannaScope_CT_V7_2_macOS.zip](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases/latest/download/CannaScope_CT_V7_2_macOS.zip)** | unzip → right-click `run.command` → **Open** |
| 🐧 **Linux** | **[CannaScope_CT_V7_2_Linux.zip](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases/latest/download/CannaScope_CT_V7_2_Linux.zip)** | unzip → `chmod +x run.sh && ./run.sh` |

➡️ **[See all downloads & release notes on the Releases page »](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases/latest)**
&nbsp;•&nbsp; Prefer one file? Grab **[`CannaScope_CT_V7_2.py`](CannaScope_CT_V7_2.py)** and run `python3 CannaScope_CT_V7_2.py`.

---

## What it does

CannaScope CT pulls Connecticut's **public** cannabis product registry, fetches each product's **live Certificate of Analysis (COA)**, parses it, and produces a polished, source-verified **consumer-awareness report** (PDF + CSV exports). It surfaces patterns worth a closer look — contaminant readings near the legal limit, unusually high cannabinoid content, possible remediation signals, and producer/lab testing trends — while refusing to overstate them.

**Its guiding rule:** every flag is a *lead*, not a verdict. A value is only published if it literally appears in that product's live COA and the applicable Connecticut legal limit supports the concern.

## Highlights

- 🧪 **Full contaminant engine** — yeast & mold, total aerobic bacteria, heavy metals (arsenic, cadmium, chromium, lead, mercury), mycotoxins, residual solvents, and zero-tolerance pathogens, each ranked by proximity to the Connecticut legal limit.
- 🚫 **Anti-hallucination, per-line-item COA verification** — every flagged value must be found, as a distinct number, in the COA's own text or it is excluded from all findings.
- 🧬 **Three-category product taxonomy** — non-infused flower, infused flower products (infused joints/blunts/pre-rolls), and vapes/concentrates/extracts are kept **strictly separate**. Vapes are never grouped with infused products.
- 🌾 **High-cannabinoid review** with implausible-value rejection (a "flower" reading above ~45% is treated as a parse error, not a finding).
- 🏷️ **Producer / DBA identity resolution** with a 0–100 source-confidence score, cited against public CT records.
- 📅 **Multi-year support** — bound any window with `--since` / `--until`, from a single quarter to the full **2015–2026** registry (~33k products), with per-section tables capped so the PDF stays readable and the complete data lands in the CSVs.
- 🛡️ **Crash-proof, self-pacing OCR** — scanned/image-only COAs are OCR'd in an isolated subprocess (a native crash kills only that child, never the run). On big runs it watches memory and **slows down — and serializes OCR — before the machine can OOM, so no document is missed.**
- 📦 **Offline / bundled-sources mode** — run once with `--keep-clean-pdfs` to cache every COA, then re-run fully offline with `--offline` (no network, bounded only by local parse speed).
- 🧾 **Reports are never overwritten** — each is uniquely numbered from 1 and date-stamped: `CannaScope_CT_V7_2_Report_<N>_<MM_DD_YYYY>.pdf`.
- ✅ **Self-audit + zero-result verification** — the report documents how it checked itself, and honestly reports `PASS` / `PASS WITH WARNINGS` / `DRAFT` / `FAIL`.

## Quick start

```bash
# any OS, with Python 3.9+
python3 -m pip install -r requirements.txt
python3 CannaScope_CT_V7_2.py --since 2024-01-01 --until 2024-12-31
```

Or use the bundled launcher for your OS (see the download table above).

### Useful options
| Option | What it does |
|---|---|
| `--since YYYY-MM-DD` / `--until YYYY-MM-DD` | bound any date range, including multiple years |
| `--days N` | look back N days instead of `--since` (default 60) |
| `--forms flower\|inhalable\|all` | product scope (default `all`) |
| `--keep-clean-pdfs` | keep **every** COA PDF → a complete local "sources" bundle |
| `--offline` | run from the bundle only, no network |
| `--no-ocr` | skip OCR (image-only COAs are not read) |
| `--workers N` | download concurrency (default 16) |

## Output

A folder **`CannaScope CT V7.2 - Reports/`** is created beside the program containing:
- the **PDF report** (cover dashboard, top findings, per-contaminant tables, high-cannabinoid review, producer/lab trends, validation & diagnostics),
- **CSV exports** for every section,
- the **registry cache** and the **source COA PDFs** for flagged products,
- a plain-text executive summary and a debug log.

## Requirements

Python 3.9+ and the packages in [`requirements.txt`](requirements.txt) (installed automatically by the launchers). OCR is optional but recommended: **macOS** uses Apple Vision automatically; **Windows/Linux** use Tesseract.

## 💬 Feedback welcome — it directly improves the tool

Spotted a mis-parse, a COA that didn't read, or have an idea?
**[Open an issue »](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/issues)** or start a **[discussion »](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/discussions)**. Real-world COA examples and edge cases are especially valuable. ⭐ Star the repo if you find it useful.

## Version history

Every prior version remains available — **nothing is removed.** See the **[Releases page](https://github.com/jmlschlee/CannaScope-CT-Beta-V9.1/releases)** for V6.1, V5, V4, V3, V2, and Beta V1 and their assets, and [`CHANGELOG.md`](CHANGELOG.md) for details.

## ⚖️ Disclaimer

CannaScope CT is a **consumer-awareness research tool**, not legal, medical, or professional advice, and not affiliated with the State of Connecticut. Findings are leads to verify — always confirm against the official, live COA. See [`DISCLAIMER.md`](DISCLAIMER.md).
