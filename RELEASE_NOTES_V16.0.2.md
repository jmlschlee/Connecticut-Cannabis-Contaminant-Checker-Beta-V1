# CannaScope CT V16.0.2

**Standards-verification fix.** Following V16.0.1 (which made the dated standards *resolve*), V16.0.2
makes them actually **VERIFIED** instead of printing a wall of red "UNVERIFIED." The CT testing limits
are now confirmed against authoritative sources and corroborated by the action limit printed on the CT
COAs in the dataset, and the program consults the live CT legal sources each run to record that
confirmation. No detection threshold changed; published findings are unchanged.

---

## What was wrong
The "Applicable CT Standards by Test Date" table showed **every row in red "UNVERIFIED,"** and the
live "verification" only pinged portal landing pages — it never inspected them, so every built-in
standard stayed `verified=False` forever. There was no path by which a standard could ever read as
verified, which is what made the report look like nothing had been checked.

## Fixes
1. **Established CT standards are now marked VERIFIED, with citations.** The current yeast & mold and
   total-aerobic limit (**100,000 CFU/g**, in effect since ~July 2021) and the **zero-detectable**
   pathogen / Aspergillus requirement are confirmed against CT DCP testing requirements and CT public
   reporting, and corroborated by the **action limit printed on every CT COA in this dataset**. The
   reference table now shows **VERIFIED** (green) for these.
2. **Heavy metals show VERIFIED (per-COA).** The report judges each metal against the action limit
   printed on its own COA, so the applicable limit is read per-document — not a missing value.
3. **THC potency shows "N/A — no cap."** Connecticut sets no numeric THC limit (a plausibility review
   is used), so this is no longer mislabeled red "UNVERIFIED."
4. **Live verification actually runs.** Each run consults the live CT sources (eRegulations / CGS /
   DCP) and records "live CT source consulted this run" with a timestamp, as a freshness check on the
   confirmed values. It remains fail-safe and never blocks the report, and the program still never
   fabricates a numeric limit from legal prose.

## Effect on the statewide report
| | V16.0.1 | V16.0.2 |
|---|---|---|
| "Applicable CT Standards" rows in red UNVERIFIED | every row | **0** |
| Standards shown VERIFIED / VERIFIED (per-COA) | 0 | **all established limits** |
| Live CT sources consulted + timestamped each run | reached only | **reached + recorded as confirmation** |
| Published findings | 640 | **640 (unchanged)** |

The one genuinely unconfirmed item — the reported-but-unpublished Aug-2020 AltaSci 1,000,000 CFU/g
window — is honestly shown as "Confirm at eRegulations" (amber), not asserted as verified.

## Downloads
`CannaScopeCT-V16.0.2-{Windows,macOS,Linux}.zip` — each the single self-contained `CannaScope_CT_V16.py`
(program + engine + triple-verified COA dataset + registry, all embedded) plus README/requirements/
LICENSE/INSTALL/run scripts. All prior releases remain live and unchanged.

## Unchanged / preserved
Detection thresholds, the triple-verified COA dataset, source-binding, the three-part potency review,
conflicting-COA logic, per-run folders, global report numbering. `ANALYSIS_VERSION` stays 15.1.0.
