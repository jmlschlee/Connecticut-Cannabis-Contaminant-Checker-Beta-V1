# 🌿 CannaScope CT

**Source-verified transparency reports for Connecticut cannabis — built so every number can be traced back to the product's own Certificate of Analysis (COA).**

🔗 **Live web app:** [cannascope-ct.streamlit.app](https://cannascope-ct.streamlit.app) &nbsp;·&nbsp; 💻 **Desktop download:** see [Releases](../../releases) &nbsp;·&nbsp; **Current version: V17.1.0**

---

## ⚖️ Please read first — what this tool is (and isn't)

CannaScope CT is an **independent, informational transparency tool**. It reads Connecticut's **public** product registry and each product's **publicly linked** lab Certificate of Analysis (COA), and organizes what those documents say into a readable report.

- ℹ️ **It is not medical, legal, or professional advice**, and it is **not affiliated with, endorsed by, or operated by** the State of Connecticut or any laboratory or producer.
- 🔎 **Every result is a lead to verify — not a conclusion.** CannaScope does **not** assert that any product is unsafe, adulterated, mislabeled, non-compliant, or fraudulent. A flag means "this is worth checking against the official COA," nothing more.
- ✅ **A value is shown only if it appears in that product's own linked COA.** Anything that can't be confidently matched to the correct product is **routed to manual review, not published.**
- 📅 Standards and limits change over time; the report shows the standard it applied and its source. **Always confirm against the official, current COA and the applicable Connecticut rule before relying on anything.**

If you are making a health, legal, or compliance decision, verify independently with the official documents and a qualified professional.

---

## ✨ What it does

### 📋 Two ways to use it
- 🔎 **Look up a product** — search by product or brand name (or enter a batch / COA number / UID) and get a plain-English PDF review of that product and its lab results.
- 🏛️ **Statewide transparency report** — review every product registered in a date window you choose, as one downloadable PDF.

### 🧪 What it reads from each COA
- 🦠 **Microbials** — total yeast & mold, total aerobic bacteria, and pathogen screens (Salmonella, E. coli, etc.)
- ⚗️ **Heavy metals** — arsenic, cadmium, lead, mercury, chromium
- 🌾 **Pesticides** and 🧴 **residual solvents**
- 🍞 **Mycotoxins** (aflatoxins / ochratoxin)
- 🌿 **Cannabinoids / potency** — THC, CBD, and totals
- ✅/❌ **Pass / fail status** as printed on the COA

### 🛡️ How it protects accuracy
- 🔗 **Source verification** — every published value is re-checked against the product's own COA before it appears.
- 🧬 **Multi-product COA handling** — some COA PDFs contain several products. CannaScope isolates **each product's own block** and will **never** attribute one product's results to another; if it can't be sure which product a value belongs to, it routes the record to review instead of guessing.
- 📅 **Date-window integrity** *(new in V16.3.8)* — a statewide report contains **only** records whose COA test date falls inside the requested window; the run shows the exact window applied and **stops rather than publish** anything outside it.
- 🧯 **Conservative by design** — when extraction is uncertain (e.g. a scanned/low-quality COA), the value is **held for manual review**, not published.
- 🔁 **Live always wins** *(new in V17.0.0)* — the cache only makes runs faster; it is **never** trusted blindly. Every online run **spot-checks the cache against the live COA at its source link** and re-pulls fresh whenever a row is empty, garbled, or implausible. If live and cache disagree, **live wins** and the cache is corrected.
- 🔬 **Reads 5×, never guesses** *(new in V17.0.0)* — image-only COAs are OCR'd up to **5 escalating attempts**; a value is left "unable to read" only after honest retries — a confidently-wrong safety number is never emitted.
- 🖥️ **Cross-platform** *(new in V17.0.0)* — identical behavior on macOS, Windows, and Linux.
- 🧫 **Below-detection aware** — "less-than" detection limits (e.g. `<10,000 CFU/g`) are treated as bounds, not as failing measurements.

### 📚 Regulatory context
- 📜 **Per-year Connecticut standards (2015–2026)** with citations, plus a live re-consult of public CT sources, so each result is judged against the limit that applied at its test date.
- 🏛️ **Patient-safety / ombudsman review** highlighting near-limit results for medical patients.
- 🔁 **Conflicting-COA detection** — flags when a product has multiple or differing COAs (e.g. a retest), shown side-by-side for comparison.
- 📊 **Producer & lab summaries** — honest, comparable rates (a producer's flagged products ÷ that producer's total in the window).

### 📦 Outputs & performance
- 🧾 **Downloadable PDF** report you can save, print, or share, plus 📑 **CSV exports** for every section and a transparent debug log.
- 💾 **Triple-verified COA data cache** — COAs are read once and reused, so reports build quickly and can run **offline** from the bundled dataset.
- 🖼️ **OCR** for older scanned / image-only COAs.
- 🔢 **Provenance & audit trail** — report numbering, source URLs, and a per-value verification stamp.

---

## 🚀 Getting started

**Web (easiest):** open [cannascope-ct.streamlit.app](https://cannascope-ct.streamlit.app), pick a mode, choose your window or search a product, and click **Generate the PDF report**.

**Desktop:** download the package for your OS from [Releases](../../releases), unzip, and run the included `run_statewide_report` / `run_consumer_concern_report` script (Python 3.9+; `pip install -r requirements.txt`).

```bash
python CannaScope_CT_V16.py statewide --since 2024-01-01 --until 2024-12-31
python CannaScope_CT_V16.py concern --example
```

---

## 🗂️ Data sources
Connecticut public product registry (data.ct.gov) + each product's publicly linked Certificate of Analysis. CannaScope stores and reuses what those public documents say; it does not generate lab results.

## 📄 License
See [LICENSE](LICENSE). Provided **as-is, for informational and transparency purposes only, with no warranty**.

*CannaScope CT surfaces what the public record says so patients, caregivers, and professionals can verify it themselves — quickly, and against the source.*
