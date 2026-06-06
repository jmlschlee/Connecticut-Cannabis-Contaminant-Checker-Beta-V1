# 🌿 CannaScope CT V16.3.0 — Source-Verified Cannabis Transparency Reports

**CannaScope CT** is a consumer-awareness research tool for Connecticut's legal cannabis market.
It reads the state's public product registry and the Certificates of Analysis (COAs) those products
link to, then produces clear, **source-verified** PDF reports about testing, contaminants, potency,
and reporting transparency.

> ⚖️ **It is not legal, medical, or professional advice, and is not affiliated with the State of
> Connecticut.** Every flag is a **lead to verify, not a conclusion**. Always confirm against the
> live, official COA.

---

## ✨ What's new in V16

- 🗓️ **Year-by-year CT regulatory standards, baked in (2015–2026).** Every year's testing limit
  (yeast & mold, total aerobic, pathogens/Aspergillus, heavy metals, THC) is carried in the program
  with an **authoritative citation** (RCSA §21a-408-58 / CGS Chapter 420h / DCP Policies & Procedures),
  **corroborated by the action limit printed on the COAs in the dataset**, and re-checked against live
  CT sources each run — so a report is always judged against the right year's standard, even offline.
- 🔏 **Source-document provenance (`fetch-standards`).** The actual CT source documents (including the
  regulation PDF) are downloaded, text-extracted, and **SHA-256-hashed**, then embedded for offline,
  tamper-evident legal provenance.
- ✅ **Standards now read VERIFIED, not "unverified."** Established CT limits are confirmed and cited;
  where CT sets no single number (heavy metals vary by product type) the report defers to **each COA's
  own printed limit** ("VERIFIED — per-COA"); THC shows "no numeric cap (plausibility review)."
- 🔎 **Clearer, more auditable review.** Multiple/duplicate records for one product identifier are
  **kept and reframed for comparison** (COA number, pass/fail, and an explicit "Compare:" line showing
  what changed); relative differences show both **% increase** and **Relative Percent Difference
  (RPD)**; a **Parser / Coverage Issues** box surfaces report limitations near the summary; and the
  debug log carries a plain-English explanation for every metric.

---

## 🧭 What it is & who it's for

A single self-contained Python program that turns thousands of public COAs into two kinds of report:

- 🏛️ **Statewide Transparency Report** — a whole-market scan: contaminant flags, microbial &
  heavy-metal review, pathogen detections, potency review, multiple/conflicting-COA comparison, a
  medical patient-safety (Ombudsman) review, and compliance review *leads*.
- 🧑‍⚕️ **Consumer Concern Report** — an advisory review of **one** product a patient or advocate is
  worried about, resolved from any identifier (batch, NDC, QR/COA link, registration number).

Built for **patients, caregivers, advocates, journalists, and regulators** who want to understand
what a COA actually says — and where the public record is incomplete.

## 🚀 Quick start

```bash
# 1) unzip, then from inside the folder:
pip install -r requirements.txt          # requests reportlab pypdfium2 pdfplumber Pillow psutil (+OCR)

# 2a) Statewide report (last 365 days):
python3 CannaScope_CT_V16.py statewide --days 365

# 2b) One-product Consumer Concern report:
python3 CannaScope_CT_V16.py concern --batch <BATCH>          # or --ndc / --qr <COA URL>
python3 CannaScope_CT_V16.py concern --example               # a worked example

# 2c) Teach the parser older COA formats (year-by-year, online):
python3 CannaScope_CT_V16.py learn --years 2015-2026

# 2d) Cache the CT regulatory source documents for offline provenance (text + SHA-256):
python3 CannaScope_CT_V16.py fetch-standards
```

Or just **double-click a run script** in your OS package:
`run_statewide_report.*` / `run_consumer_concern_report.*` (`.command` macOS · `.bat` Windows · `.sh` Linux).

**Requires** Python 3.9+ and the libraries in `requirements.txt`. OCR (for scanned/image COAs) is
optional: `ocrmac` on macOS, `pytesseract` + Tesseract on Windows/Linux.

## 🌐 Use it in your browser (Streamlit)

No download needed — deploy the app on **Streamlit Community Cloud**:

- **Repository:** `jmlschlee/CannaScope-CT`  ·  **Branch:** `main`  ·  **Main file:** `streamlit_app.py`

The web app offers a **Consumer Concern Lookup** (one product by batch / NDC / COA number / BioTrack
UID / COA link) and a small **Statewide sample** report, each delivered as a downloadable PDF. Work
per click is kept light, and any secrets are read from `st.secrets` (never hard-coded).

## 🔎 What "source-verified" means

A value is **published only if it is re-verified to literally appear in its own linked COA.** On top
of that, every published row is **triple-checked** against its COA on six fields — measured value,
product identity, testing date, laboratory, unit, and analyte name — and the result is shown as an
auditable stamp. Anything that can't be confirmed is routed to **manual review / Coverage Gaps**, not
presented as a finding. Unreadable or unvalidated COAs never appear as normal findings.

## 📋 What's in a Statewide report

- 🧪 **Contaminant flagging** — heavy metals, microbials (yeast/mold, aerobic), mycotoxins, residual
  solvents, pesticides, and **zero-tolerance pathogen** detections, each against the CT limit.
- 🧫 **Yeast & Mold — Date & Lab Standard Review** — judged against the standard *in effect on the
  product's test date* (CT's limit changed by lab and year), not one universal number.
- 🗓️ **CT Regulatory Standards — Year by Year (2015–2026)** — the applied limit for each year and
  category, with citations, COA-corroboration counts, and a confirmation date.
- 🌡️ **Potency review, in three honest parts** — (A) **High THC Flower**, (B) **Impossible
  Cannabinoid Math**, (C) **Possible Product-Type Misclassification** — using a **verified** Total
  THC (`0.877 × THCA + Δ9-THC`), never an inflated COA-stated figure.
- 🔁 **Multiple / conflicting-COA comparison** — when the same lot appears on more than one record, the
  versions are shown side by side (COA number, date, lab, result, pass/fail) so a reviewer can compare
  what changed. Differences show ratio, **% increase**, and **RPD**; a cross-lab fail→pass is flagged
  as a *possible* lab-shopping indicator only when the data supports it.
- 🏥 **CT Cannabis Ombudsman — Medical Patient-Safety Review** — products closest to a limit, with
  testing dates on every row.
- 📌 **Potential Compliance Review Leads** — triaged Critical / High / Moderate / Low, with testing
  dates and a careful "authority area to verify" — never a legal determination.
- ⚖️ **Legal Standard Verification (by test date)** — the applied dated limit is confirmed and cited,
  with live CT sources (eRegulations / statutes / DCP) consulted each run and the source documents
  cached (text + SHA-256) for provenance.
- 🧰 **Parser / Coverage Issues**, **Coverage Gaps / Unvalidated COAs**, and a **Software
  Self-Enhancement & Self-Audit** section that records this run's limitations and carries improvement
  notes forward across runs.

## 🗂️ Reports, numbering & output folders

- Each run creates its **own new folder** (under `CannaScope CT V16 - Statewide Transparency Reports/`)
  holding the PDF + all CSV/diagnostic exports — nothing is ever overwritten or reused.
- **Short, browse-friendly filenames:** `{N}-CannaScopeCT-{SW|CC}-{M.D.YY}-{TIME}.pdf`
  (e.g. `85-CannaScopeCT-SW-6.5.26-805PM.pdf`). The **full** report number, date, time, type, and
  dataset window stay **inside** the PDF.
- **Report numbers are global and sequential** across both report types; **folder numbers** advance
  independently per type. A persistent `report_registry.json` survives restarts and never resets.

## 📚 Data sources

- Connecticut product registry (`data.ct.gov`, dataset `egd5-wb6r`).
- The COA / lab-analysis document each product links to.
- For legal standards: CT eRegulations (RCSA §21a-408-58), the Connecticut General Statutes
  (Chapter 420h), and DCP Policies & Procedures — cited per category, consulted live each run, and
  cached as source documents (text + SHA-256) for offline provenance.

## ⚠️ Limitations & disclaimer

CannaScope CT is a **consumer-awareness research tool**, not legal, medical, or professional advice,
and is **not affiliated with the State of Connecticut**. Findings are **leads to verify, not
conclusions**, and never imply safety, fraud, endorsement, or a legal violation. Some older COA
formats may parse incompletely (surfaced in the Parser / Coverage Issues and Coverage Gaps sections).
**Always confirm against the official, live COA.**

---

*Older versions remain available as tagged GitHub releases. V16 is one self-contained file — the
engine, cannabinoid/identity layer, name resolver, OCR worker, the triple-verified COA dataset, the
registry snapshot, and the CT regulatory source-document ledger are all embedded.*
