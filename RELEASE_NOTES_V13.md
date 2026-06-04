# 🌿 CannaScope CT V13

**A big readability, integrity, and feature release.** V13 carries everything from the V11/V12 line and
adds new analysis, a cleaner publication-style report, and important accuracy fixes. All prior releases
remain available — **nothing has been removed from the repository.**

CannaScope CT reads Connecticut's **public** cannabis product registry, fetches each product's **live
Certificate of Analysis (COA)**, parses it, checks the results against Connecticut's limits, and writes
a polished, source-verified report (PDF + CSV). Its guiding rule never changes: **every flag is a lead,
not a conclusion — verify each against the product's live COA.** Advisory only; not legal or medical advice.

---

## ✨ What's new in V13 (vs V12)

### 🔍 Conflicting COA Results & Possible Lab-Shopping Indicators *(new)*
A neutral, review-oriented section that flags when the **same physical lot** (matched on a shared batch /
lot / BioTrack / sample / product code) shows **conflicting pass/fail results across lab reports** —
especially an **earlier failing result followed by a later passing retest** at another lab. Pass/fail is
judged against the **limit printed on each COA** (Connecticut's CFU/g standards changed over the years, so
each document carries the limit that applied at the time). Each case shows a side-by-side comparison with
**clickable COA links**, dates, the numeric difference, and a plain-English explanation that names the
**innocent explanations too** (retest, sampling, remediation, clerical error). It **does not allege fraud
or misconduct** — it points to records for a human to verify.

### 🧪 High-cannabinoid breakdown *(new columns)*
The High-Cannabinoid review now shows the **component breakdown — THCA · Δ9-THC · CBD · Total THC · Total
Cannabinoids** — so you can see what makes up the headline number without opening the COA.

### 🧾 Potential Compliance Review Leads *(reworked & renamed)*
Renamed from "Statute & Regulatory Flags" and split into clear buckets — **A** over a current CT limit ·
**B** implausible/unusual potency (with the cannabinoid breakdown + chemistry consistency checks) · **C**
missing numeric microbial value despite a PASS · **D** COA/document inconsistency. Cautious wording
throughout ("authority area to verify in eRegulations") — **never a legal determination.**

### 📊 Honest numbers & integrity
- **Producer percentages fixed** — "% flagged" is now flagged ÷ that producer's **total products in the
  window** (not a misleading near-100%). Section renamed **"Flagged Findings by Producer."**
- **Dataset accounting line** — shows window total · scanned this run · reused from the verified-clean
  ledger · COAs fetched · published findings, so the denominators are clear.
- **Report numbering hardened** — the report number appears in the **filename, cover, footer, and PDF
  metadata**, with a guard that refuses to overwrite or reuse a number. Each report is **one uniquely
  numbered file** (a duplicate-copy bug that caused "overwrite" prompts is gone).

### 🎨 Reads like a publication
- New **"Most Important Findings"** summary + a **"How To Read These Findings"** legend at the top.
- **Section reorder** to a public-first flow; all technical material moved to a clearly labeled
  **Appendix (Technical Validation & Diagnostics)** at the end.
- Cleaner styling and a fixed box-overlap rendering bug.

### ➖ Removed in V13
- The two **potency-reference sections** (infused products, and vapes/concentrates/extracts) — they were
  pure potency listings; high potency is expected by design and isn't a finding. *(Contaminant results for
  vapes/extracts still appear in the contaminant sections.)*
- Five redundant **"Top …" mini summary tables** that duplicated the full sections and the summary boxes.

### 🛠️ Other fixes
- Remediation review now flags flower **at or under 100 CFU/g** (tightened).
- Lower-Concern range updated to **800–3,000 CFU/g**.
- Numerous lab-shopping false-positive and rendering fixes.

---

## 📚 Everything CannaScope CT does (full feature list)

**Two reports, one program**
- 🏛️ **Statewide Transparency Report** (`statewide`) — a whole-market scan of the public registry.
- 👤 **Personalized Product Concern Report** (`concern`) — a careful, advisory review of one product a
  consumer is worried about, resolved from any identifiers (NDC, batch, QR/COA link, name).

**Integrity**
- 🛡️ **Per-line-item COA source-binding** — a value is published **only** if it is re-verified to literally
  appear in that product's **own** linked COA; anything unconfirmed is excluded to a manual-review queue.
- 🧾 Provenance + COA Source-Binding Audit, source-mismatch and multiple-COA review exports.

**Analysis**
- 🧪 Full contaminant engine — yeast & mold, total aerobic bacteria, heavy metals (arsenic, cadmium,
  chromium, lead, mercury), mycotoxins, residual solvents, zero-tolerance pathogens — each ranked by
  proximity to the Connecticut legal limit.
- 🧫 **Lab- & date-aware Yeast/Mold (TYM) Standard Review** — CT's passing limit varied by lab and date
  (up to 100×); each result is shown against three benchmarks.
- 🧬 Three-category product taxonomy (non-infused flower / infused flower products / vapes-concentrates-
  extracts), kept strictly separate.
- 🌾 High-cannabinoid review with implausible-value rejection and the cannabinoid breakdown.
- 🩺 CT Cannabis Ombudsman "closest to a limit" patient-safety review.

**Engineering**
- 🔎 Crash-proof, self-pacing OCR for scanned/image-only COAs.
- 📅 Multi-year support (`--since` / `--until`); offline / bundled-sources mode; baked-in registry snapshot
  + opt-in `--fast-cached`.
- 🧾 Reports never overwritten — uniquely numbered + date/time-stamped.
- ✅ Self-audit + zero-result verification with honest `PASS` / `PASS WITH WARNINGS` / `DRAFT` / `FAIL` status.

---

## ⬇️ Download

| OS | Download | Run |
|---|---|---|
| 🪟 **Windows** | [CannaScope CT V13 - Windows.zip](https://github.com/jmlschlee/CannaScope-CT/releases/download/v13.0.0/CannaScope.CT.V13.-.Windows.zip) | unzip → `run.bat statewide --days 90` |
| 🍎 **macOS** | [CannaScope CT V13 - macOS.zip](https://github.com/jmlschlee/CannaScope-CT/releases/download/v13.0.0/CannaScope.CT.V13.-.macOS.zip) | unzip → `chmod +x run.sh && ./run.sh statewide --days 90` |
| 🐧 **Linux** | [CannaScope CT V13 - Linux.zip](https://github.com/jmlschlee/CannaScope-CT/releases/download/v13.0.0/CannaScope.CT.V13.-.Linux.zip) | unzip → `chmod +x run.sh && ./run.sh statewide --days 90` |

Each zip is the **entire program in one self-contained file** (`CannaScope_CT_V13.py`) plus a one-click
launcher, quick-start guide, and license. **Requirements:** Python 3.9+ (the launcher installs the rest).
OCR is optional — macOS uses Apple Vision automatically; Windows/Linux use Tesseract.

```bash
# any OS, manual:
python3 -m pip install -r requirements.txt
python3 CannaScope_CT_V13.py statewide --since 2025-01-01 --until 2026-12-31
python3 CannaScope_CT_V13.py concern --example
```

---

## ⚖️ Disclaimer
CannaScope CT is a **consumer-awareness research tool** — not legal, medical, or professional advice, and
not affiliated with the State of Connecticut. Findings, including everything in the Conflicting COA and
Compliance Review sections, are **leads to verify**, not conclusions or accusations. Always confirm against
the official, live COA.
