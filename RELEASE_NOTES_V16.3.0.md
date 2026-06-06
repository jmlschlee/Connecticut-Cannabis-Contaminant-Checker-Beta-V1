# CannaScope CT V16.3.0

**Parser & data-routing safety release.** Conservative fixes so the statewide report does not publish
misleading findings or falsely-clean results across the 2015–2026 ledger. When the parser is uncertain,
rows are routed to a review queue rather than published. No detection threshold was loosened.

## Fixes
1. **Product-type / potency guardrail.** A flower-classified row with Total THC above the ~45% biological
   flower ceiling is HELD for a **Product-Type Mismatch / Potency Classification Review** (with a suspected
   real type: vape/concentrate/extract) instead of being published as a "high-THC flower" finding. (That
   review section was previously dead code — it is now wired to the real queue.)
2. **Impossible cannabinoid math.** When reported Total THC exceeds Total Cannabinoids, the row is routed
   to the potency-parser-conflict queue and not published. A ratio guard ensures only genuine near-equal
   inversions are held (the real cases), so a mis-parsed small Total-Cannabinoids value does not suppress
   a legitimate potency finding.
3. **Legacy broad "< X CFU/g" microbial bounds.** A below-detection bound above the 10,000 strict
   benchmark is labeled **"passed its dated standard, but consumer-risk visibility UNDETERMINED — bound
   too broad to confirm < 10,000"** — clearly separated from regulatory-failure language, no longer read
   as a clean modern low pass.
5. **Limit-value selection.** Yeast & mold pass/fail is now judged against the action limit PRINTED ON
   THE COA (the standard in effect at its test date / lab) — like aerobic already did — so an
   AltaSci-era high-limit COA is not falsely RED and a pre-2020 stricter-limit COA is correctly
   evaluated. The internal 10,000 consumer-awareness watch line stays separate from the regulatory limit.
6. **Self-audit.** The page-1 gate now warns on conflicting-COA records (incl. earlier-FAIL→later-PASS,
   previously computed but never surfaced), product-type holds, Total-THC>Total-Cannabinoids conflicts,
   and broad-bound microbials; with matching self-audit observations and debug metrics.
7. **Cache / ledger safety.** `ANALYSIS_VERSION` → 16.3.0; the clean-ledger is now version-stamped, so a
   record verified under an older ruleset is re-evaluated under the new rules rather than bypassing them.

**Item 4 (historical OCR / lab-layout template fallback) is intentionally NOT in this release** — building
it without the specific failing COAs would risk regressing the audited cache; the conservative routing
already prevents publishing mis-parses. Tracked for a focused follow-up.

Also: the modular source was renamed `cannascope_ct_v15_src.py` → `cannascope_ct_v16_src.py` (engines
v4/v5 keep their engine-version names). `ANALYSIS_VERSION` 15.1.0 → 16.3.0. All prior releases remain live.
