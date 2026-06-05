# CannaScope CT V16.0.1

**Critical report-accuracy patch.** V16.0.1 fixes a single date-parsing bug whose effects made the
V16.0.0 statewide report look broken: every dated yeast & mold standard showed as *"unknown (no dated
standard) — unclear/unverified, manual review,"* the legal-source verification was keyed to the wrong
era, and a separate cannabinoid check produced false "not chemically possible" flags. All three are
resolved. No detection threshold changed; **no real finding was added or lost** — only false noise was
removed and standards now resolve correctly. All prior releases remain live and unchanged.

---

## What was wrong (and why the report looked like a failure)
The COA measurement cache stores test dates in ISO format (`2025-07-02`), but `parse_date()` only
understood US `MM/DD/YYYY`. Every ISO date silently became "no date." Because the dated-standard
lookup, the legal-era keying, year extraction, and conflict dating **all** flow through `parse_date`,
one blind spot cascaded into:

- **Every yeast & mold row marked "unknown / unclear-unverified — manual review"** — the lookup never
  ran, so it never found the applicable 100,000 CFU/g (post-~2022 unified) limit.
- **Legal-source verification keyed to the wrong era** — so the live-source confirmation table didn't
  line up with each product's actual test year.

## Fixes
1. **`parse_date` now accepts ISO `YYYY-MM-DD` and `YYYY/MM/DD` (and US `MM/DD/YYYY` with an optional
   trailing time).** This is the root cause. With it fixed, every dated standard resolves: a 2025/2026
   yeast & mold test now correctly applies the **100,000 CFU/g** standard and shows a real Lab / Now /
   Strict verdict instead of "unknown." The legal-source verification table is keyed to the correct
   **Era 2025 / 2026**, with eRegulations / CGS / DCP consulted as the live fallback (local-first, as
   designed — the program never fabricates a numeric limit from legal prose).
2. **Removed an invalid cannabinoid check.** "Total Cannabinoids" on CT COAs is reported on a
   decarboxylated basis, while THCA is the acid form (~14% heavier). Comparing the two flagged
   perfectly self-consistent COAs (e.g. THCA 39.3% with Total Cannabinoids 36.1%) as *"not chemically
   possible."* The only valid impossibility check — Total Cannabinoids below Total THC — is kept.
3. **Conflicting-COA / lab-shopping section is now compact.** Each case previously reserved a full page
   (header + a small table, then ~60% blank), bloating the report. Cases now pack several per page with
   their tables and narratives intact.

## Effect on the statewide report (365-day window, same dataset)
| | V16.0.0 | V16.0.1 |
|---|---|---|
| Yeast & mold rows "unknown (no dated standard)" | every row | **0** |
| "Applicable standard unclear/unverified" flags | every row | **0** |
| False "Total Cannabinoids LOWER than THCA" flags | 24 | **0** |
| Conflicting-COA cases per page | 1 | **2+** |
| Total report length | 115 pages | **81 pages** |
| Published findings (1 Red / 42 Orange / 212 Yellow / 24 High-THC) | 640 | **640 (unchanged)** |

## Downloads
Three OS packages — `CannaScopeCT-V16.0.1-{Windows,macOS,Linux}.zip` — each contains the single
self-contained `CannaScope_CT_V16.py` (program + engine + the triple-verified COA dataset + registry
snapshot, all embedded) plus README, requirements, LICENSE, INSTALL, and per-OS run scripts.

## Unchanged / preserved
Detection thresholds, the triple-verified COA dataset, the COA source-binding check, the three-part
potency review, conflicting-COA detection logic, per-run report folders, and global report numbering
are all as in V16.0.0. `ANALYSIS_VERSION` stays 15.1.0 (detection logic unchanged; this patch fixes
date parsing, a false-positive check, and layout). All prior releases remain live.
