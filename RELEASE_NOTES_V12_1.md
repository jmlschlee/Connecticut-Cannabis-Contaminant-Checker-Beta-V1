# CannaScope CT Beta V12.1

**An additive feature release.** V12.1 carries everything from V11.1 (and V12) and adds one major
new statewide section. All prior releases remain live and unchanged — nothing has been removed.

CannaScope CT reads Connecticut's **public** cannabis product registry, fetches each product's
**live Certificate of Analysis (COA)**, parses it, checks the results against Connecticut's limits,
and writes clear, source-verified PDF + CSV reports. Its guiding rule is unchanged: **every flag is
a lead, not a conclusion — verify each against the product's live COA.**

---

## 🆕 New in V12.1 — Conflicting COA Results & Possible Lab-Shopping Indicators (statewide report)

A new section in the **Statewide Transparency Report** that surfaces **document-level
discrepancies for human review**, described **neutrally**. It does **not** allege fraud,
misconduct, or any wrongdoing — it points to records a person should look at and verify.

**What it looks for**

- **Conflicting COA results for the same physical lot.** When the same product/lot — matched on a
  distinctive shared identifier (batch, lot, BioTrack/UID, lab sample ID, or product code) —
  appears with **conflicting pass/fail results** across more than one lab report.
- **An earlier failing result followed by a later passing result** on a regulated safety category
  (a **possible retesting discrepancy / possible lab-shopping indicator**).
- **Multiple lab identities inside one COA**, or a passing summary alongside a failing
  regulated-test result in the same document (a stapled / appended second report). Page numbers are
  preserved where available.

**Categories compared:** total yeast & mold, total aerobic microbial count, *Aspergillus*,
*E. coli*, Shiga toxin-producing *E. coli*, *Salmonella*, *Listeria*, mycotoxins, heavy metals,
and the pesticide panel.

**How it is presented (carefully, for review)**

- If high-severity examples are found, the section rides near the **top** of the report (red header
  for Critical, orange for High); otherwise lower-severity observations appear later, and if none
  are found the report simply notes **"No conflicting COA result patterns detected."**
- Each case shows a clean **side-by-side comparison** (each lab's result, status, date, action
  limit, the numeric difference, a timeline note, the source COA links/page references) plus a
  plain-English explanation that lists the **innocent explanations too** (retesting, sampling
  differences, remediation, clerical error, or another reason) and flags the record **for human
  review**.
- **Severity tiers:** Critical (documented fail then later pass, same safety category) ·
  High (conflicting pass/fail, order not confirmable, or a single COA with both) ·
  Medium (large numeric swing on the same lot) · Low (same lot at more than one lab, no safety
  conflict).
- New CSV export **`conflicting_coa_results.csv`**, an executive-summary line when Critical cases
  exist, and a validation note: *"This section flags document-level discrepancies only. It does not
  prove intent, misconduct, remediation, or unlawful conduct without further verification."*

This section is **statewide-report only.** The Personalized Product Concern report is unchanged
unless the specific product is itself involved.

---

## Everything CannaScope CT does (full feature overview)

### Two reports, one program
- **Statewide Transparency Report** (`statewide`) — a whole-market scan of the public registry.
- **Personalized Product Concern Report** (`concern`) — a careful, advisory review of one product a
  consumer is worried about, resolved from any identifiers (NDC, batch, QR/COA link, product name).
  Advisory only — **not medical advice.**

### COA integrity (V11.1+)
- **Per-line-item COA source-binding.** A value is published **only** if it is independently
  re-verified to literally appear in that product's **own** linked COA; anything that cannot be
  confirmed is excluded and routed to a manual-review queue. Enforced in **both** reports.
- **Provenance + audit outputs:** COA Source-Binding Audit panel, `COA_Provenance_Audit.csv`,
  `COA_Source_Mismatch_Review.csv`, `Multiple_COA_Alert.csv`, and a `FAIL SOURCE VALIDATION`
  status if anything published can't be verified.

### Contaminant & potency analysis
- **Full contaminant engine** — yeast & mold, total aerobic bacteria, heavy metals (arsenic,
  cadmium, chromium, lead, mercury), mycotoxins, residual solvents, and zero-tolerance pathogens,
  each ranked by proximity to the Connecticut legal limit.
- **Lab- & date-aware Yeast/Mold (TYM) Standard Review** — Connecticut's passing limit for total
  yeast & mold varied by **lab** and by **date** (by up to 100×). Each result is shown against three
  benchmarks (the lab's limit on its test date / the current limit / a strict patient-protective
  benchmark), with effective dates flagged as unverified where the public record is ambiguous.
- **Three-category product taxonomy** — non-infused flower, infused flower products, and
  vapes/concentrates/extracts are kept **strictly separate**.
- **High-cannabinoid review** with implausible-value rejection.
- **Possible Remediation / Unusually Low Microbial Load** and **Lower-Concern** review sections.

### Patient-safety & compliance leads (human-review only, never determinations)
- **CT Cannabis Ombudsman — Products Closest to a Contaminant Limit** (passed testing, ranked by
  headroom to the limit).
- **Potential Statute & Regulatory Flags to Evaluate** — testing/product-quality leads with a cited
  authority, each marked authority-unverified and for human review.

### Identity, trends, and provenance
- **Producer / DBA identity resolution** with a 0–100 source-confidence score.
- **Producer & Lab trend** summaries and concise, factual per-section trend notes.

### Engineering
- **Crash-proof, self-pacing OCR** for scanned/image-only COAs (isolated subprocess; slows and
  serializes before the machine can run out of memory).
- **Multi-year support** (`--since` / `--until`), per-section table caps with full data in the CSVs.
- **Offline / bundled-sources mode** (`--keep-clean-pdfs` then `--offline`) and a baked-in registry
  snapshot + opt-in `--fast-cached` first-run mode.
- **Reports are never overwritten** — each is uniquely numbered and date-stamped.
- **Self-audit + zero-result verification**, with honest `PASS` / `PASS WITH WARNINGS` / `DRAFT` /
  `FAIL` status.

---

## Downloads

| OS | Download |
|---|---|
| 🪟 Windows | [CannaScope CT Beta V12.1 - Windows.zip](https://github.com/jmlschlee/CannaScope-CT/releases/download/v12.1.0-beta/CannaScope.CT.Beta.V12.1.-.Windows.zip) |
| 🍎 macOS | [CannaScope CT Beta V12.1 - macOS.zip](https://github.com/jmlschlee/CannaScope-CT/releases/download/v12.1.0-beta/CannaScope.CT.Beta.V12.1.-.macOS.zip) |
| 🐧 Linux | [CannaScope CT Beta V12.1 - Linux.zip](https://github.com/jmlschlee/CannaScope-CT/releases/download/v12.1.0-beta/CannaScope.CT.Beta.V12.1.-.Linux.zip) |

Each zip is the **entire program in one self-contained file** (`CannaScope_CT_Beta_V12_1.py`) plus a
one-click launcher, quick-start guide, and license. No companion files, no build step.

```bash
# macOS / Linux
unzip "CannaScope CT Beta V12.1 - macOS.zip" && cd "CannaScope CT Beta V12.1"
./run.sh statewide --days 90
```

---

## ⚖️ Disclaimer

CannaScope CT is a **consumer-awareness research tool** — not legal, medical, or professional
advice, and not affiliated with the State of Connecticut. Findings, including everything in the new
Conflicting COA Results section, are **leads to verify**, not conclusions or accusations. Always
confirm against the official, live COA.
