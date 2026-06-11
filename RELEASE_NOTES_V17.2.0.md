# 🌿 CannaScope CT — V17.2

**Source-verified Connecticut cannabis transparency reporting.** The biggest upgrade since V17: the report is now **harder to argue with** (every record accounted for, the math checked), **more complete** (over-limit results can't hide behind a header PASS), and **much nicer to read**.

🔗 **Live web app:** https://cannascope-ct.streamlit.app &nbsp;·&nbsp; 💻 Desktop downloads below (Windows / macOS / Linux).

---

## 🆕 Headline changes

- 🛑 **A cover "PASS" can no longer hide a failing line inside the COA.** Every analyte is judged against the limit printed on that same COA — an over-limit body line now **always surfaces** in its contaminant section, flagged **"COA Marked Pass But Contains Over-Limit Result,"** shown as a documented internal contradiction (never an outside-confirmed failure; the COA's own PASS is shown beside it).
- ✅ **Two honest statuses** — **Report Validation** (data/parse completeness) and **Findings Validation** (was each published number re-verified) shown side by side, so a coverage gap never makes verified findings look "failed."
- 🧾 **Record Accounting** — every product lands in exactly one bucket and the totals must sum to the window; the report **refuses to publish if they don't reconcile.**
- ⚗️ **Heavy Metal Coverage page** — per-metal parsed-vs-actual coverage, with an explicit "no findings can be claimed" for any zero-extraction metal.
- 🌿 **Top-100 highest-cannabinoid flower** — uncapped, highest first; implausible (>45%) values shown and flagged, never silently dropped.
- 🧮 **Inaccurate Laboratory Math Detection** — a named section for COAs whose own numbers are impossible (Total THC > Total Cannabinoids, total below the sum of parts, negatives, >100%); held out of findings for manual re-read.
- 📈 **Stronger, honest statistics** — round-number / digit-preference / nearest-neighbor screens, explicit significance tiers (interesting · unlikely · statistically significant · highly significant), and 95% confidence intervals + low-sample marking on producer rates.
- 🔎 **A date + clickable COA on every product, every time** — every section, every row.
- 💅 **Cleaner, full-width layout** — COA links no longer wrap/bleed, tables use the full page width, lab-result-change rows read as big before → after comparisons.
- 🎯 **No more mislabeled "diagnostic."** Readiness no longer punishes panels (like heavy metals) that are only required on a fraction of products, so a clean fully-verified report reads as a clean pass with warnings.

> Every flag is a **lead to verify against the official COA — never a conclusion.** CannaScope is independent and **not** affiliated with the State of Connecticut, any lab, or any producer.

---

## 🚀 Run it

```bash
python CannaScope_CT_V17.py statewide --since 2024-01-01 --until 2026-06-10            # live-first
python CannaScope_CT_V17.py statewide --since 2024-01-01 --until 2026-06-10 --validate  # full-window, 100% live-verified
python CannaScope_CT_V17.py concern --example                                          # single-product
```

Each OS zip bundles the self-contained `CannaScope_CT_V17.py` (embeds the triple-verified COA dataset) + README + requirements + LICENSE + install/run scripts. Python 3.9+; `pip install -r requirements.txt`.

---

## ⚖️ Important
Independent, informational transparency tool — **not** medical/legal/professional advice and **not** affiliated with or endorsed by the State of Connecticut, any lab, or any producer. Every flag is a lead to verify against the official COA, not a conclusion. Provided as-is, no warranty.

🌿 *All prior releases are preserved; this is an additive release.*
