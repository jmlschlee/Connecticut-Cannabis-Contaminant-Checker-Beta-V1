# 🌿 CannaScope CT

**Source-verified transparency reports for Connecticut cannabis — built so every number can be traced back to the product's own Certificate of Analysis (COA).**

🔗 **Live web app:** [cannascope-ct.streamlit.app](https://cannascope-ct.streamlit.app) &nbsp;·&nbsp; 💻 **Desktop download:** see [Releases](../../releases) &nbsp;·&nbsp; **Current version: V17.2**

---

## 🆕 What's new in V17.2 — the credibility, completeness & polish release

This is the biggest upgrade since V17. It makes the report **harder to argue with** (every record is accounted for and the math is checked), **more complete** (over-limit results can no longer hide), and **much nicer to read**.

### 🛑 A PASS on the cover can no longer hide a failing line inside the COA
Some lab reports say **"PASS / Below Action Limits" at the top**, yet a result **further down the same document is over its printed limit** (or marked FAIL). Before, CannaScope trusted the top-line PASS and those results were quarantined. **Now every analyte is judged against the limit printed on that same COA** — so an over-limit line **always surfaces** in its contaminant section, flagged **"COA Marked Pass But Contains Over-Limit Result,"** shown as a documented *internal contradiction* (the header says pass, a body line is over). It is never presented as an outside-confirmed failure — the COA's own PASS is shown right next to it.

### ✅ Two honest statuses instead of one confusing banner
The cover now shows **Report Validation** (how complete the data/parsing is) and **Findings Validation** (were the published numbers each re-verified against their own COA) **side by side**. A coverage gap no longer makes verified findings look "failed," and vice-versa.

### 🧾 Every single record is accounted for
A new **Record Accounting** table places every product in the window into exactly one bucket (reviewed · reused from prior verified runs · excluded out-of-window · date-failure · unknown) and **the totals must add up to the window — the report refuses to publish if they don't.** No more "where did the other records go?"

### ⚗️ Heavy-metal honesty
A dedicated **Heavy Metal Coverage** page shows, per metal, how many COAs reported it vs how many actually parsed — and says plainly **"no findings can currently be claimed"** for any metal with zero extraction. The report never implies coverage it doesn't have.

### 🌿 Top-100 highest-cannabinoid flower, uncapped
A new **Top 100 Highest-Cannabinoid Flower** table lists the strongest flower statewide, highest first, with no artificial display cap — biologically implausible values (>45%) are shown and clearly flagged rather than silently dropped.

### 🧮 "Inaccurate Laboratory Math Detection"
A clearly-named section surfaces COAs whose **own numbers are internally impossible** — Total THC greater than Total Cannabinoids, a total below the sum of its parts, negatives, or impossible percentages. These are **data-integrity alerts held out of findings** (routed for manual re-read), never treated as a safety finding or an accusation.

### 📈 Stronger, honest statistics
The boundary-clustering review adds **round-number, digit-preference and nearest-neighbor screens**, and every statistical callout now carries an explicit **significance tier** (interesting · unlikely · statistically significant · highly significant) with the threshold stated. Producer flag rates now show a **95% confidence interval** and mark **low-sample** groups, so a small sample is never read as a firm conclusion.

### 🔎 A date and a clickable COA on every product, every time
Every product listed anywhere in the report now shows its **test date** and a **clickable link to its COA** — every section, every time.

### 💅 Cleaner, full-width, easier to read
COA links no longer wrap or bleed between columns, tables now **use the full width of the page** (no more cramped columns with wasted space), and the lab-result-change comparisons read as big, obvious **before → after** values.

### 🎯 Reports are no longer mislabeled "diagnostic"
A fully-verified recent-year report was previously being branded "DIAGNOSTIC — not ready" because heavy metals are only required on a fraction of products. That readiness logic is fixed: it now judges the panels that are actually tested everywhere, so a clean, fully-verified report reads as a **clean pass with warnings.**

> Every flag remains a **lead to verify against the official COA — never a conclusion**, and CannaScope is **not** affiliated with the State of Connecticut, any lab, or any producer.

---

## 📦 Previously added (V17.1.x — still here)

- 🛰️ **Honest live-verification gate** — the cover states how many products were re-verified against their live source this run; a 0-live run is unmistakably stamped **`CACHE-REPLAY`**, and `--live-verify` / `--validate` force genuine live re-fetching.
- 📊 **"Convenient Lab Result Groupings"** — the statistical screen for results clustering just below a pass/fail limit (binomial / z-score / chi-square / Fisher / cliff-effect / 0–100 Convenience Score) — a **review signal only, never a fraud claim.**
- 🧮 **Laboratory Data Consistency Flags** & **Biologically Implausible High THC Flower Review** (accurate renames), **Coverage Integrity Summary**, decluttered/centered cover blocks, tier-banded producer table, Unicode-clean `µg/kg` rendering.

---

## 📋 What CannaScope CT does

- 🔎 **Look up a product** by name / brand / batch / COA number → a plain-English PDF.
- 🏛️ **Statewide report** over any date window → one downloadable PDF.
- 🧪 Reads each COA for 🦠 microbials (yeast & mold, aerobic bacteria, pathogens) · ⚗️ heavy metals · 🌾 pesticides · 🧴 residual solvents · 🍞 mycotoxins · 🌿 cannabinoids/potency · ✅/❌ pass-fail.
- 🛡️ **Live-first** (the cache is only a speed hint; live wins), **multi-product COA isolation** (never cross-attributes), **date-window integrity**, **below-detection aware**, and **fail-loud** (an empty or non-reconciling report stops; it never ships a silent blank).
- 📦 Downloadable PDF + CSV exports for every section + a technical appendix.

---

## 🚀 Run it

```bash
# Statewide (live-first). Add --validate for a full-window, 100% live-verified forensic run.
python CannaScope_CT_V17.py statewide --since 2024-01-01 --until 2026-06-10
python CannaScope_CT_V17.py statewide --since 2024-01-01 --until 2026-06-10 --validate

# Single-product consumer report
python CannaScope_CT_V17.py concern --example
```

Each OS zip bundles the self-contained `CannaScope_CT_V17.py` (embeds the triple-verified COA dataset) + README + requirements + LICENSE + install/run scripts. Python 3.9+; `pip install -r requirements.txt`.

---

## ⚖️ Important

CannaScope CT is an **independent, informational transparency tool** — **not** medical, legal, or professional advice, and **not** affiliated with or endorsed by the State of Connecticut, any lab, or any producer. **Every flag is a lead to verify against the official COA, not a conclusion.** Provided as-is, no warranty. *All prior releases are preserved; this is an additive release.*

---

<details>
<summary><b>🔧 Technical changes (V17.2) — for developers / auditors</b></summary>

**Detection / classification (ANALYSIS_VERSION → 17.2.0):**
- **Over-limit-under-PASS:** `assess_extraction` no longer routes a top-PASS + genuine body over-limit to UNCERTAIN/held; it marks `p._coa_pass_overlimit` and publishes the finding (ambiguous FAIL-status without a verified numeric exceedance still routes to review). New `coa_pass_overlimit_lines(p)` (robust on cache rows), `COA_PASS_OVERLIMIT_FLAG`, debug `coa_pass_with_overlimit_lines`, run-log count, and a "COA Marked Pass — Over-Limit Line Items" section. Surfaces in analyte/contaminant tables + producer/lab aggregation automatically.
- **Cannabinoid math:** `thc_conflict` now also flags Total Cannabinoids < sum(THCA + Δ9 + total CBD).
- **Confidence:** `assess_extraction` credits extraction breadth via `_extraction_richness` (promotes, never demotes).
- **Year-readiness:** `COAFormatLearner._core_coverage`/`_verdict` judge metals coverage relative to where reported (not ÷ all products), so sparsely-tested metals no longer force NOT-READY; arsenic presence regex no longer matches the English word "as".

**Accounting / validation backbone (single source of truth):**
- `VerificationAccounting` + `build_verification_accounting` (fail-loud reconciliation), `record_accounting_buckets` (record partition, fail-loud Unknown), `consistency_audit` (build-time, `sys.exit(5)` on contradiction), `write_remediation_report` (Final Remediation Report file). All wired before `build_pdf`. Tiers `FINDING_VALIDATION_FAIL` / `DIAGNOSTIC_COVERAGE_INCOMPLETE`; dual Report/Findings status on the cover.

**New analyses / helpers:** `heavy_metal_coverage_rows`, `top_cannabinoid_flower_rows`, `statistical_screens` + `significance_tier`, `_wilson_ci` + `CG_MIN_GROUP_SAMPLE`.

**Presentation:** date + clickable COA on every product table; `coacell` fixed (8pt, `splitLongWords=0`, `wordWrap=None`) so COA links never wrap/bleed; `_fit_widths` scales all tables to ~96% of usable width (stretch-capped, no overflow); big centered before→after in lab-change cases.

**Tests:** `_test_verification_accounting.py`, `_test_presence.py`, `_test_consistency_math.py`, `_test_overlimit.py`, plus S8/S10 assertions in `_test_convenience.py`. Build: `python3 _make_v17.py`. Forensic: `--validate` (needs the certifi CA bundle in restricted shells).

</details>
