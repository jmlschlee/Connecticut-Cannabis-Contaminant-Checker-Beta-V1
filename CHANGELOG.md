# Changelog

All notable changes to this project are documented here.

## V17.2.0 — current release

Biggest upgrade since V17 — credibility, completeness, and readability. ANALYSIS_VERSION → 17.2.0 (detection
logic changed).

**Over-limit-under-PASS surfacing.** A COA whose overall status reads PASS but whose body carries a genuine
over-limit line (numeric result over the limit printed on that same COA, or a panel FAIL / pathogen DETECTED) is
no longer quarantined as UNCERTAIN — it is published as an internal contradiction, flagged "COA Marked Pass But
Contains Over-Limit Result," and surfaced in the analyte/contaminant tables, producer/lab aggregation, and a new
summary section. Run log prints the self-discovered count.

**Validation backbone.** Single-source verification accounting; Record Accounting bucket partition that fails
loud on any unaccounted record; build-time consistency audit (`sys.exit(5)` on contradiction); a Final
Remediation Report file written per run; dual Report-Validation vs Findings-Validation status on the cover.

**New analyses.** Heavy Metal Coverage page (per-metal parsed-vs-actual; explicit no-findings on zero
extraction); Top-100 highest-cannabinoid flower (uncapped); Inaccurate Laboratory Math Detection section;
round-number / digit-preference / nearest-neighbor statistical screens with significance tiers; producer 95%
confidence intervals + low-sample marking; cannabinoid math now flags Total Cannabinoids < component sum.

**Fixes.** Year-readiness no longer forced NOT-READY by sparsely-tested metals (parsed-of-reported, not
parsed-of-all); arsenic presence regex no longer matches the word "as"; confidence now credits extraction
breadth.

**Presentation.** A test date + clickable COA on every product row in every section; COA links no longer
wrap/bleed; all tables fill the page width within reason (no compression, no overflow); big centered
before→after in lab-result-change cases.

## V17.1.1 

Honesty + readability + added-analysis update. No measurement, threshold, limit, or finding logic changed
(ANALYSIS_VERSION stays 17.0.0).

**Honest live-verification coverage (gate).** Genuine live COA downloads are now correctly credited as live
verification (the ledger path previously didn't set the live marker, so a real online run could show a
misleading "0% verified live"). The tier now gates on *products verified live this run*: a run with zero
live verification is stamped `CACHE-REPLAY — NOT LIVE-VERIFIED THIS RUN` (online) / `UNVALIDATED — CACHE
REPLAY` (offline) and no finding is presented as live-verified — incidental OCR can no longer exempt a
replay. Counters reconciled ("Live URL Verifications" relabeled; a true "COAs re-fetched LIVE this run"
added). New `--live-verify` switch forces a fresh live re-fetch of every COA; the run log states
`LIVE VERIFICATION: ON/OFF`.

**New "Convenient Lab Result Groupings by Producer and Lab"** statistical screen — boundary clustering just
below a pass/fail limit, by producer+lab+analyte (binomial / z-score / chi-square GOF / Fisher exact /
cliff-effect / 0–100 Convenience Score), with a plain-English column legend, public Top-10 summary, full
statistical appendix, and CSV. Review signal only, never a fraud claim.

**Renamed:** "Potency Parser Conflicts" / "Impossible Cannabinoid Math" → "Laboratory Data Consistency
Flags"; "High THC Flower Review" → "Biologically Implausible High THC Flower Review."

**Readability:** decluttered cover (status + counts + one warning + one pointer; detail moved to the
appendix); centered + larger "Most Important Findings", "Statewide Snapshot", "How To Read"; ranked,
tier-banded "Flagged Findings by Producer" (≥20% / 10–20% / <10%, rule printed); pathogen findings sorted
newest→oldest; section headers never orphan from their tables; front technical summary compressed to two
lines. Added a Coverage Integrity Summary (expected/acquired/parsed/live-verified, fail-loud reconciliation).
Embedded Unicode font so µg/kg renders in every viewer; removed missing-glyph (tofu) icons.

## V17.1.0 

**NEW — "Convenient Lab Result Groupings by Producer and Lab."** A boundary-clustering statistical
screen that flags statistically unusual clustering of quantitative results just BELOW a pass/fail
threshold, by producer / lab / analyte — a review signal, never a fraud claim. Per producer+lab+analyte:
near-threshold (95–100% of limit) counts, observed vs statewide-expected, observed/expected ratio,
binomial p-value, z-score, chi-square goodness-of-fit, Fisher exact (small-N), cliff-effect, and a
0–100 Convenience Score. Pure-Python statistics (no numpy/scipy), validated against known reference
values (`_test_convenience.py`); minimum-sample rules enforced. Public summary (statewide histogram +
ranked Top-10 + plain-English interpretation) and a Technical Appendix subsection (full methodology +
per-producer/lab comparison + per-grouping detail + scatter). New export
`convenient_lab_result_groupings.csv`.

**Renamed + reframed.** The report is now titled "CT Statewide Cannabis Report." "Potency Parser
Conflicts" / "Impossible Cannabinoid Math Review" are renamed everywhere to "Laboratory Data
Consistency Flags" and reframed as data-integrity alerts (a COA's own numbers being internally
inconsistent), not parser/software errors.

**Honest live-verification coverage.** Cold live reads now count toward validation coverage
(`products_freshly_read_live`), so a genuine live run no longer reads "0.0% verified"; offline /
cache-replay runs still correctly read 0% and are tiered UNVALIDATED — CACHE REPLAY. Cache-replay
detection hardened (no live work of any kind ⇒ cache replay); the disclaimer is run-aware and only
claims "confirmed this run" when live verification actually ran.

**Accounting + integrity.** Dataset-accounting buckets reconcile fail-loud (reused-from-ledger is
separate from excluded; analyzed + reused + excluded == in-window). New Coverage Integrity Summary
(expected / acquired / parsed / live-verified with reconciling ratios, fail-loud on a zero
denominator). Severity tiers reconcile to the published total; the triple-check no longer rounds
sub-100% up to "100%"; the three verification counts are labeled by scope and by live-vs-cached source.

**Rendering.** A Unicode TTF (Arial/DejaVu) is embedded so µg/kg renders in every viewer (no more
"g/kg" drop); the warning-icon tofu glyph removed. No detection logic, threshold, or limit changed in
this release.

## V17.0.0 

**SUPERIOR RULE — active cache self-audit (cache is a hint, live is the authority).** Every online,
cache-backed run now stride-samples cached COAs, re-pulls them LIVE from their source links, and compares
to the cache. Live always wins: disagreeing rows are corrected to live, the audit widens on disagreement,
and a genuine value conflict distrusts the cache for the whole window (full live re-pull). Offline runs
disclose "cache UNVERIFIED". Flags `--cache-audit-sample N` / `--full-cache-audit` / `--no-cache-audit`;
debug keys `cache_audit_*`. Verified live (12/12 agreed) + a real corruption demo (faked cache value caught
vs live, corrected, distrusted).

**Cross-platform acceptance criteria (every run, every OS).** Cross-platform OCR (ocrmac/Tesseract) and
per-OS OCR process groups; "when in doubt, go live" on empty OR implausible cached rows; OCR retried up to
5× (escalating DPI) before a field is marked unread — never fabricated; a units/ranges plausibility
cross-check gates implausible values out of publication; an empty report fails loud (`sys.exit 3`);
out-of-range data fails loud (`sys.exit 2`).

**Reconciled from 16.3.x:** online-OCR fallback in the report path; 2015 columnar metals/mycotoxin parser
(defensive, below-detect, garble-proof); persisted training ledger + diagnose-learning + training→report
traceability; `--forensic-no-cache`; honest category-level coverage accounting; multi-product block-binding
map; validation messaging derived from the worst readiness state; evidence-gated learning recommendation
(TRAINING STAGNATION DETECTED). Source renamed `cannascope_ct_v16_src.py` → `cannascope_ct_v17_src.py`;
builder `_make_v17.py`; program `CannaScope_CT_V17.py`. Additive — all prior releases preserved.

## [16.3.8] — 2026-06-06 — CannaScope CT V16.3.8 

Date-window integrity + independent live end-to-end verification + hosted-app contrast fix. Informational
tool; results are leads to verify against the official COA, not conclusions. `ANALYSIS_VERSION` → 16.3.8.
Additive — all prior releases remain available.

### Added
- Date-window integrity: statewide reports include ONLY records whose COA test date is within the requested
  window. Single enforcement chokepoint (cache-reloaded + fresh alike); out-of-window and no-test-date
  records excluded and counted; hard MIN/MAX validation aborts with a "DATE INTEGRITY" error instead of
  publishing if anything is out of range; new Date-Window Integrity section in the report + debug log;
  regression across 2015→2026 windows.

### Verified
- Independent re-read of every value-carrying 2015–2026 record (15,803), live-pulling 9,461 COAs fresh and
  checking per-product block attribution: 0 cross-attribution found.

### Fixed
- Hosted Streamlit app: pinned light theme + forced high-contrast dark text and form controls (renders
  correctly regardless of the visitor's dark-mode setting); dynamic version badge; offline cache-backed modes.

### Changed
- Refreshed/embedded the triple-verified COA dataset for fast offline reports.

## [16.3.7] — 2026-06-06 — CannaScope CT V16.3.7 

CRITICAL data-integrity fix: stop cross-attribution of COA results between products. `ANALYSIS_VERSION`
→ 16.3.7; `OCR_CACHE_VERSION` → 2. All prior releases remain live.

### Fixed
- Cross-attribution: a multi-product / mis-linked COA could publish one product's results under another
  product's name (e.g. a "Seraden Wax" record whose COA is actually a multi-product Scott's OG document
  published Scott's OG's failing Yeast & Mold as Seraden Wax's). Two causes fixed:
  - Stale OCR cache: `OCR_CACHE_VERSION` 1→2 — the page cap had gone 6→40 without bumping the cache
    version, so truncated 6-page OCR hid later products and defeated multi-product detection. Forces full re-OCR.
  - Permissive publish gate: `validate_coa_row` published a "Verified Partial Match" on mere value-presence.
    New `_coa_is_different_product()` guard marks a COA whose printed product(s) don't match the registry
    record as `COA Product Mismatch` (routed to review, not published) — even if a value appears.
- Rebuilt the embedded COA cache for 2015–2021 with full re-OCR + the new gate, removing these
  cross-attributed values from the bundled dataset.

### Unchanged
- Genuine matches still publish; ID-only COAs (no printed product description) still pass as partial.
- The 16.3.4 multi-product mechanism + 16.3.6 columnar OCR microbial reader remain in place.

## [16.3.6] — 2026-06-05 — CannaScope CT V16.3.6 

Two-column OCR microbial-table reader + 2015–2021 cache rebuild. `ANALYSIS_VERSION` → 16.3.6;
`MULTIPRODUCT_CACHE_VERSION` → 2. All prior releases remain live.

### Added
- `cannascope_multiproduct.repair_columnar_layout`: reconstructs 2015-era columnar OCR tables (label and
  value in separate columns) by re-pairing label[i]/value[i]/status[i] into same-line rows the parser reads.
  Scoped to the MICROBIAL / PATHOGEN safety panel only — heavy metals (OCR unit garble → misreads) and
  cannabinoids (unmapped acid forms → understated THC) are deliberately not reconstructed. Conservative:
  emits only when value count exactly equals label count; strict no-op on modern COAs. Wired into both the
  single-product and per-product block parse paths. Regression checks added to _test_multiproduct.py.

### Fixed (data)
- Re-extracted 2015–2021 (11,775 records) with the repair enabled and re-embedded the corrected
  COA Data Cache, recovering 2015-era microbial pass/fail values that were previously empty for scanned
  columnar COAs (supersedes 16.3.5's 2015–2019 refresh).

### Unchanged
- 16.3.4 multi-product mechanism (per-PDF block cache, ranked identifier matching, isolate-or-suppress,
  source-audit block binding).

### Known limitation (tracked)
- Multi-group microbial pages (a second analyte block after the first without its own "Result Units"
  header) recover only the first group's analytes; in practice the missed ones are passing pathogens, so no
  FAIL is lost. Heavy-metal/cannabinoid columnar recovery remains out of scope by design.

## [16.3.5] — 2026-06-05 — CannaScope CT V16.3.5 

Data-refresh release: the bundled offline COA cache is rebuilt to remove real multi-product
cross-attribution. No engine/logic change (`ANALYSIS_VERSION` stays 16.3.4). All prior releases remain live.

### Fixed (data)
- Re-extracted the 2015–2019 medical-era COAs (6,401 records) with the v16.3.4 multi-product-aware engine
  and re-embedded the corrected cache. Found 106 era records that are genuinely multi-product COAs NOT
  sharing a registry URL (e.g. one record whose PDF holds two products) — previously subject to
  first-product cross-attribution; now isolated to their own block or suppressed → COA Needs Manual Review.
- Bundled statewide report: published findings 3,041 → 3,038 (2 fewer RED — removed cross-attributed
  values); source audit re-verified all 1,688 remaining flagged values in their own block/COA; build clean.

### Unchanged
- Engine/detection logic and the 16.3.4 multi-product mechanism (per-PDF block cache, ranked identifier
  matching, isolate-or-suppress, source-audit block binding).

### Known limitation (tracked)
- Two-column OCR microbial tables on isolated one-per-page blocks aren't yet associated (isolate to empty —
  safe, never a wrong value).

## [16.3.4] — 2026-06-05 — CannaScope CT V16.3.4 

Multi-product COA data integrity: parse once, cache every product block separately, never
cross-attribute. `ANALYSIS_VERSION` → 16.3.4 (cache-path runs unchanged; only cold/online reads
affected). All prior releases remain live.

### Added
- Per-PDF structured block cache (`Multi-Product COA Cache.json`, content-hash keyed): a multi-product
  PDF is parsed ONCE; each product block is stored with its own identifiers (lab ID, sample ID, batch,
  product description, registration numbers, test date) AND its own measurements (cannabinoids,
  microbials, pesticides, heavy metals, solvents, pass/fail, mold/yeast CFU). Records sharing the PDF
  reuse their matched block from cache.
- Ranked identifier matching (`cannascope_multiproduct.match_block`): lab ID → registration number →
  sample ID → batch → product description → unique unit marker. A strong identifier matching >1 block is
  ambiguous and fails (no weaker fallback). Per-block extractors for sample ID, batch, test date,
  registration numbers.
- Source audit binds to the matched block: published flagged values from a multi-product COA are
  re-verified against THEIR product block (metric `multi_product_rows_verified_against_matched_block`),
  not merely somewhere in the shared PDF. Binding survives cache rehydration via the stored block id.
- Regression `_test_multiproduct_cache.py` (19 data-integrity checks incl. an 11-product COA);
  `_test_multiproduct.py` → 19 checks.

### Changed
- `_process_product` multi-product branch reuses the cached per-block extraction (parse once) and applies
  ONLY the matched block's measurements; unmatched records are suppressed → `COA Needs Manual Review`.
- Engages only when 2+ resolvable blocks exist (single-product COAs never suppressed); cache hits
  preserve the same per-product isolation as fresh parses.

### Note
- Rebuild the offline COA cache online (`build-cache`) to re-extract any multi-product records cached by
  the older single-product parser. Known limitation (tracked): two-column OCR microbial tables on
  isolated one-per-page blocks aren't yet associated (those isolate to empty — safe, never a wrong value).

## [16.3.3] — 2026-06-05 — CannaScope CT V16.3.3 

Multi-product COA per-product isolation on the published path (fixes cross-attribution) + OCR page-cap
fix. `ANALYSIS_VERSION` 16.3.0 → 16.3.3 (cold-read extraction can change; cache-path runs unchanged).
All prior releases remain live.

### Fixed
- Cross-attribution: a COA document holding several products was parsed by the single-product parser,
  which read the FIRST product's results and could attribute them to any record sharing the document URL.
  Now each record is parsed from only its own product's block, or suppressed and routed to manual review.
- OCR page cap: `ocr_pdf` / the OCR worker capped scanned docs at 6 pages (silently dropping later
  products/panels); they now read the whole document, bounded to 40 pages.

### Added / Changed
- Per-product isolation enabled on the published path (`MULTIPRODUCT_SPLIT_ENABLED`,
  `MULTIPRODUCT_MIN_CONF=0.7`); engages only when 2+ resolvable product blocks exist, so ordinary
  single-product COAs are never suppressed.
- Records that can't be uniquely tied to one block → `COA Needs Manual Review` (not extracted).
- New debug metrics `multi_product_coa_isolated`, `multi_product_coa_routed_to_review`; self-audit and
  glossary updated. Regression test `_test_multiproduct.py` → 19 checks.

### Known limitation (tracked)
- Two-column OCR microbial tables on isolated one-product-per-page pages aren't yet associated, so those
  products isolate to empty (a safe coverage gap — never a wrong value).

## [16.3.2] — 2026-06-05 — CannaScope CT V16.3.2 

Multi-product COA recognition (additive, detection/surface-only). No findings changed; `ANALYSIS_VERSION`
stays 16.3.0. All prior releases remain live.

### Added
- Generalized multi-product COA detection learned from a confirmed real 2015 Northeast Laboratories doc:
  signals on an incrementing Laboratory ID # suffix and/or multiple distinct Product Descriptions (not
  just `MMBR` registration numbers). Distinguishes one-product/multi-panel (combine pages) from
  multi-product/one-per-page (separate products) by the Laboratory ID #.
- New module `cannascope_multiproduct.py` (pure-stdlib, embedded in the single-file build): groups COA
  pages into products, plus a per-product splitter `isolate_product()` with a route-to-review guardrail
  (isolates a block only on a confident unique match; otherwise routes to manual review — never
  cross-attributes).
- Debug metrics `multi_product_coa_documents`, `multi_product_coa_products_recognized`; self-audit and
  glossary updated. Regression test `_test_multiproduct.py` (17 checks).

### Not in this release
- Substituting the isolated per-product block into the PUBLISHED extraction (requires a per-record
  statewide regression for zero cross-attribution + an OCR page-depth fix + an ANALYSIS_VERSION bump);
  tracked as the next release.

## [16.3.0] — 2026-06-05 — CannaScope CT V16.3.0 

Parser & data-routing safety fixes (conservative; route-to-review when uncertain). `ANALYSIS_VERSION`
15.1.0 → 16.3.0. All prior releases remain live.

### Fixed / Added
- Flower-classified rows with Total THC >45% held for Product-Type / Potency Classification Review (not
  published as high-THC flower); section C wired to the real queue.
- Total THC > Total Cannabinoids → potency-parser-conflict queue (with a ratio guard so mis-parsed small
  Total-Cannabinoids values don't suppress legitimate findings).
- Broad "< X CFU/g" microbial bounds above 10,000 → "consumer-risk UNDETERMINED (bound too broad)", not a clean low pass.
- Yeast & mold pass/fail now uses the COA's own printed limit (date/lab-aware), like aerobic; 10k watch line kept separate.
- Self-audit gate now warns on conflicting-COA records, product-type holds, THC>Total-Cannabinoids, broad-bound microbials.
- Clean-ledger version-stamped (ANALYSIS_VERSION) so legacy-clean records re-evaluate under new rules.

### Changed
- Modular source renamed cannascope_ct_v15_src.py → cannascope_ct_v16_src.py (engines v4/v5 unchanged). Version → 16.3.0.

### Not in this release
- Historical OCR / lab-layout template fallback (needs the specific failing COAs to build safely; tracked).

## [16.2.2] — 2026-06-05 — CannaScope CT V16.2.2 

Reprioritizes the Multiple/Conflicting COA Records section to lead with cases where the reported
analytical RESULT changed between COAs, ending with metadata-only differences. No detection logic
changed; nothing removed; `ANALYSIS_VERSION` stays 15.1.0.

### Changed
- Conflict findings are ordered by **what changed**: compliance-outcome changes (PASS↔FAIL, DETECTED↔ND)
  first, then changed analytical results (largest first), then metadata-only differences last —
  independent of whether the dates match. Severity is now only a tie-breaker.
- Each case head shows a color-coded tag: `[RESULT CHANGED — compliance outcome]` / `[RESULT CHANGED]` /
  `[METADATA ONLY — results identical]`.
- New "What changed" scoreboard at the top of the section (counts by change class).
- Section intro states the result-changes-first ordering.

### Added
- `change_class` / `change_size` / `change_substantial` on each conflict finding (`_classify_change`);
  `detect_coa_conflicts` sorts by change class → magnitude → severity.

### Unchanged / preserved
Metadata-only records are retained (ranked last, not removed); per-case Compare line + side-by-side
table; conservative non-accusatory tone; thresholds; report numbering.

## [16.2.1] — 2026-06-05 — CannaScope CT V16.2.1 

Crash fix: the V16.2.0 plain-English debug-log table could raise a ReportLab `LayoutError` on large /
all-time reports when a long metric value (e.g. `validation_warn_reasons`) wrapped into a cell taller
than a page. Debug-log cell values are now capped at 220 chars in the table (full values stay in
debug_log.json/.csv) and the columns rebalanced. Verified on a full all-time run (33,688 products,
184 pages). No detection logic changed; `ANALYSIS_VERSION` stays 15.1.0.

## [16.2.0] — 2026-06-05 — CannaScope CT V16.2.0 

Non-destructive transparency & readability refinement pass. No detection logic changed; no findings
removed; `ANALYSIS_VERSION` stays 15.1.0. All prior releases remain live.

### Changed
- **Multiple/conflicting COA records reframed for comparison** (kept in full, not discarded): each case
  now shows COA number, batch/lot, date, lab, result, pass/fail, limit + an explicit "Compare:" line
  (COA refs / dates / pass-fail / values identical-or-different). "Duplicate COA" → "Multiple records".
- **RPD disambiguated**: shows both percent increase (low→high) and Relative Percent Difference (RPD).
- **Softer causal wording** for large ratios (parser / formatting / retest / remediation / sample
  variation — manual review recommended), not "likely a parsing artifact".
- **Confidence metrics** renamed `*_this_run` + section clarifies they count only COAs freshly read this
  run (cached COAs format-checked when first read).
- `coa_years_observed` → `coa_years_fingerprinted_this_run`; added `years_in_report_window`.
- **Readiness section** explains why a high Conf % year can still be PARTIAL/NOT READY.
- Reduced repeated explanatory text under each conflict finding.

### Added
- **"Parser / Coverage Issues" box near the summary** (broken links, unreadable COAs, held potency
  conflicts, held uncertain extractions) — framed as report limitations, not findings.
- **Plain-English "What it means" column** in the Data Quality & Debug Log.

### Unchanged / preserved
Thresholds, triple-verified dataset, year-by-year regulatory ledger + source-document provenance,
source-binding, conflicting-COA detection logic, per-run folders, report numbering. Nothing deleted.

## [16.1.1] — 2026-06-05 — CannaScope CT V16.1.1 

Folder-name fix: the output folder is renamed from the stale "CannaScope CT V15 - Statewide
Transparency Reports" to "CannaScope CT V16 - …". `OUT_DIR` was never bumped at the V15→V16
transition. The V15 folder is now first in `LEGACY_OUT_DIRS` so an existing install auto-migrates
(renamed in place) — cache, regulatory ledger, prior reports, and the global report-number sequence
all carry over; nothing re-downloaded. `_make_v16.py` prefers the V16 folder (V15 fallback). No
detection logic changed; `ANALYSIS_VERSION` stays 15.1.0. All prior releases remain live.

## [16.1.0] — 2026-06-05 — CannaScope CT V16.1.0 

Bakes the per-year CT regulatory standard for every year (2015–2026) into the program with
authoritative citations, COA corroboration, and a confirmation date; fixes character-level rendering
garble; and makes the version string single-source. `ANALYSIS_VERSION` stays 15.1.0; published
findings unchanged. All prior releases remain live.

### Added
- **CT Regulatory Standards — Year by Year (2015–2026)** section: per-year applied limit for yeast &
  mold / aerobic / pathogens / heavy metals / THC, each cited to RCSA §21a-408-58 / CGS Ch. 420h / DCP
  Policies & Procedures (with URL), corroborated by the action limit printed on the COAs in the
  dataset (count shown), confirmed as of a stated date, and re-consulted live each run.
- `CT_REG_CITATIONS`, `CT_REG_AS_OF`, and `reg_corroboration()` (counts dataset COAs printing each
  applied limit). Live-first: where CT has no single number (heavy metals vary by product type) the
  report defers to each COA's own printed limit.
- **`fetch-standards` subcommand + embedded source-document ledger** — downloads each cited CT source
  (incl. the §21a-408-58 regulation PDF), extracts text via the pdfium→pdfplumber→OCR pipeline,
  SHA-256-hashes the raw bytes, and stores them in `CT Regulatory Ledger.json` (embedded + auto-seeded)
  for offline forensic provenance. New "Cached source-document provenance" table renders URL, size,
  method, text length, and content hash per source.

### Fixed
- **P0 rendering**: disabled ReportLab character-level word-splitting on the base cell + header styles
  — integers no longer split across lines (`10`→`1`/`0`) and headers no longer garble
  (`Confidence`→`Confidenc`/`e`).
- **P4 version drift**: every rendered/printed disclaimer and recommended command now derives from one
  version constant (`SCRIPT_FILE` / `PRODUCT_NAME`); the report no longer names the stale V15 script.
  Version → 16.1.0.

### Unchanged / preserved
Detection thresholds, triple-verified COA dataset, source-binding, three-part potency review,
conflicting-COA logic, per-run folders, global report numbering. No files/branches/tags/releases
deleted or renamed.

## [16.0.2] — 2026-06-05 — CannaScope CT V16.0.2 

Standards-verification fix. After V16.0.1 made dated standards resolve, V16.0.2 makes them actually
VERIFIED instead of a wall of red "UNVERIFIED": the established CT limits are confirmed against
authoritative sources + corroborated by the action limit printed on the CT COAs, and the live CT
sources are consulted each run to record that confirmation. No detection threshold changed; published
findings unchanged (640). `ANALYSIS_VERSION` stays 15.1.0.

### Fixed
- **Established CT standards now render VERIFIED (with citations)** instead of red UNVERIFIED. Yeast &
  mold / total aerobic 100,000 CFU/g (since ~July 2021) and zero-detectable pathogens/Aspergillus are
  marked verified — confirmed vs CT DCP requirements + CT public reporting, corroborated by the action
  limit printed on every CT COA in the dataset.
- **Heavy metals → VERIFIED (per-COA)**: each metal is judged against the action limit printed on its
  own COA (read per-document), not a missing baked-in number.
- **THC potency → "N/A — no cap"**: CT sets no numeric THC limit (plausibility review), no longer
  mislabeled red UNVERIFIED.
- **Live verification actually runs**: each run consults the live CT sources (eRegulations / CGS / DCP)
  and records "live CT source consulted this run" with a timestamp; fail-safe, never blocks the report,
  never fabricates a numeric limit from legal prose. Self-audit appendix wording corrected to match.

### Unchanged / preserved
Detection thresholds, triple-verified COA dataset, source-binding, three-part potency review,
conflicting-COA logic, per-run folders, global report numbering. No files/branches/tags/releases
deleted or renamed.

## [16.0.1] — 2026-06-05 — CannaScope CT V16.0.1 

Critical report-accuracy patch. Fixes a single `parse_date` bug (ISO `YYYY-MM-DD` test dates were
unreadable) that cascaded into the dated-standard lookup, legal-era keying, year extraction, and
conflict dating — making every yeast & mold standard render as "unknown (no dated standard) —
unclear/unverified." No detection threshold changed; no real finding added or lost (640 published,
unchanged). `ANALYSIS_VERSION` stays 15.1.0. All prior releases remain live.

### Fixed
- **`parse_date` now parses ISO `YYYY-MM-DD` / `YYYY/MM/DD`** (plus US `MM/DD/YYYY` with optional
  trailing time). Root cause: COA test dates are stored ISO, but the parser only understood US format,
  so every dated lookup silently got "no date." Now 2025/2026 yeast & mold tests correctly apply the
  100,000 CFU/g standard (real Lab/Now/Strict verdicts), and the live legal-source verification keys to
  the correct era (eRegulations/CGS/DCP reached as the local-first fallback).
- **Removed invalid cannabinoid check** comparing decarboxylated Total Cannabinoids against acid-form
  THCA (~14% heavier) — it falsely flagged self-consistent COAs as "not chemically possible." The valid
  Total-Cannabinoids-below-Total-THC check is kept.

### Changed
- **Conflicting-COA / lab-shopping section packs several cases per page** instead of one-per-page
  (eliminates ~60%-blank pages; the 365-day report drops from 115 to 81 pages). Version → **16.0.1**.

### Unchanged / preserved
Detection thresholds, the triple-verified COA dataset, COA source-binding, three-part potency review,
conflicting-COA detection logic, per-run folders, global report numbering. No files/branches/tags/
releases deleted or renamed.

## [16.0.0] — 2026-06-05 — CannaScope CT V16 

The data-integrity release: a persistent **triple-verified COA measurement dataset** (≈33,692 COAs,
2015–2026) baked into the program, plus six engine parser-accuracy fixes audited against the real
source COAs (misread rate **1.26% → 0.000%**). `ANALYSIS_VERSION` stays 15.1.0 (detection logic
unchanged). All prior releases remain live and unchanged; nothing removed.

### Fixed (parser accuracy — root-cause, in the V4/V5 engine)
- Below-detection `<X` no longer dropped as the limit (comparator token is always a result).
- Bare value == its own action limit → conservative below-limit bound (generic AND detail-table paths).
- Microbial CFU/g ≥ 1e11 rejected as an OCR artifact (e.g. a garbled `4e14` that would fire a false RED).
- Δ9-THC no longer matches the “THC” inside “THC-A” (was duplicating THCA into THC → Total THC >100%).
- A derived Total THC >100% (impossible) → drop the COA’s THC potency as not-reliably-readable.
- Net: limit-as-value 1.26%→0.000%, cannabinoid>100% 192→0, storage fidelity 100%, no false negatives.

### Added
- **Persistent COA→measurement cache** (`coa_csv_cache.py`, opt-in `--csv-cache`) — each COA read once;
  later runs reload measurements and recompute flags (~8× faster re-runs; threshold re-flag from cache).
- **`build-cache` subcommand** — full-registry analyze → TRIPLE-verify (source-extracted + source-bound
  + round-trip) → save CSV. The resulting dataset (33,692 COAs · 32,721 triple-verified) is **embedded**
  in the build and auto-seeds on first run.
- **Multi-product Consumer Concern report** (`concern --products-json`, optional `--conditions`).
- Persistent OCR-text cache; auto-sized OCR concurrency; concurrent sibling-COA fetch.

### Changed
- Streamlit web app updated to V16. Version → **16.0.0**.

### Unchanged / preserved
Detection thresholds, date-aware legal verification, six-field COA source-binding, three-part potency
review, conflicting-COA review, per-run folders, global report numbering. No files/branches/tags/
releases deleted or renamed.

## [15.2.0] — 2026-06-05 — CannaScope CT V15.2 

Performance + data-durability release on top of V15.1.3. Detection/validation logic is unchanged
(`ANALYSIS_VERSION` stays 15.1.0); this changes how COA data is stored and reused. All prior releases
remain live and unchanged; nothing removed from the repository.

### Added
- **Persistent COA → measurement cache** (`coa_csv_cache.py`, opt-in `--csv-cache`) — each COA is
  downloaded + read (incl. OCR) ONCE and its measurements saved to a spreadsheet-readable
  `COA Data Cache.csv`; later runs reload measurements and recompute flags from them. Re-runs are ~8×
  faster, and lowering `--threshold` re-flags previously-clean COAs from cache (no re-download/re-OCR).
  Flags are never stored — they are recomputed each run. Invalidates a row only on schema change,
  a changed registry COA URL, or a prior empty read.
- **`build-cache` subcommand** — walks the whole registry, reads each COA once, and TRIPLE-verifies
  every measurement (source-extracted + source-bound + CSV round-trip) before trusting it. Resumable,
  checkpointed (atomic flush), no PDF. This release ships with the resulting triple-verified COA data
  EMBEDDED, so the program comes with the validated measurements in hand (new/re-released COAs still
  fetch live).
- **Multi-product Consumer Concern report** — one combined PDF for several products
  (`concern --products-json`), shared header + per-product sections, optional `--conditions` health
  context (advisory only).

### Changed
- **Persistent OCR-text cache** — image-only COAs are OCR'd once ever (content-hash keyed); re-scans /
  audit-cache / `--force-rescan` skip re-OCR.
- **Auto-sized OCR concurrency** — default scales to `min(cores−2, 6)` (was a fixed 4); low-memory
  serialize guard unchanged.
- Concurrent sibling-COA fetch in the consumer report.
- Declared version bumped to **15.2.0**.

### Unchanged / preserved
Detection thresholds, date-aware legal verification, the COA source-binding six-field triple-check,
three-part potency review, conflicting-COA review, per-run report folders, and global report numbering.
No files, branches, tags, or releases were deleted or renamed.

## [15.1.3] — 2026-06-04 — CannaScope CT V15.1.3 

Additive report-quality patch on top of V15.1.2. All prior releases remain live and unchanged;
nothing was removed from the repository. This release fixes table rendering, an accuracy
contradiction in the legal-standard table, and documents coverage gaps more honestly.

### Fixed
- **Dates never wrap or split mid-value.** In every table, a testing/test date is now an atomic,
  non-breaking token sized to fit a full `YYYY-MM-DD` — no more `2025-07-0` + `2` splits.
- **Status words never break.** The Legal Standard Verification table no longer splits `UNVERIFIED`
  into `UNVERIFIE` + `D`.
- **Value+unit stays together.** In the Yeast & Mold review, a value and its unit no longer split
  (e.g. `380,000 CFU/g`, `not disclosed`).
- **Legal Standard Verification now reflects what the program actually did.** Previously the table
  marked categories like yeast & mold "UNVERIFIED" even though the report applied a known dated CT
  limit (e.g. 100,000 CFU/g) to judge those rows — an internal contradiction. The table now shows, per
  category/era, the **applied dated standard** it used (from the built-in date-keyed registry) in one
  column and a **separate, clearly-worded live-confirmation status** in another. The bare "historical
  standard not verified — manual legal review needed" wording is now reserved only for categories/eras
  where the program genuinely has no dated value on record.

### Changed
- **Conflicting-COA section is shorter and clearer.** The shared caveat that previously repeated on
  every one of ~75 leads is now stated once at the section top; each case keeps only its own specifics.
- **Higher-quality OCR for image-only COAs.** Scanned COAs whose first OCR pass returns no text are now
  re-rendered at a higher resolution and re-OCR'd (an escalating-DPI retry). Clean COAs are unaffected.
- **More honest coverage-gap wording.** Unreadable COAs are described as unreadable "even after an
  escalating-DPI OCR retry," documenting what was attempted before a record is held out as a gap.

### Unchanged / preserved
- Every V15.1.2 / V15.1.1 / V15.1.0 capability is intact, including the live-source fix and legal-cache
  versioning. No files, branches, tags, or releases were deleted or renamed.

## [15.1.2] — 2026-06-04 — CannaScope CT V15.1.2

Additive patch on top of V15.1.1. All prior releases remain live and unchanged; nothing was removed
from the repository. This release makes the V15.1.1 live-source fix take effect even when an older
build had already cached "unreachable" results.

### Fixed
- **Stale legal-source cache no longer masks the live-source fix.** The `Legal Standards Cache.json`
  entries are now stamped with a fetch-logic version (`LEGAL_FETCH_VERSION`). A cached entry whose
  stamp does not match the current version is treated as a miss and re-fetched. Because the V15.1.1
  fetch fix (corrected DCP URL, longer timeout, completed TLS chain) is a new fetch-logic version,
  any "live CT sources unreachable" entry written by a pre-fix build within the 30-day cache window
  is now ignored and re-verified live, instead of being shown again. No manual cache deletion needed.

### Unchanged / preserved
- Every V15.1.1 and V15.1.0 feature is unchanged. No files, branches, tags, or releases were deleted
  or renamed. The 30-day re-verification window and the fail-safe, never-fabricate behavior are intact.

## [15.1.1] — 2026-06-04 — CannaScope CT V15.1.1

Additive patch on top of V15.1.0. All prior releases remain live and unchanged; nothing was removed
from the repository. This release restores the program's ability to reach the live Connecticut
legal-reference sources used by the by-test-date **Legal Standard Verification** step.

### Fixed
- **Live legal-source verification reaches all three CT sources again.** The date-aware standard
  verifier (`verify_standard`) had stopped reaching every CT source it consults:
  - **CT DCP cannabis program** — the deep link had moved and returned HTTP 404; updated to the
    current page (`https://portal.ct.gov/cannabis/medical-marijuana-program`).
  - **CT eRegulations** — was timing out on a short 8-second budget; the per-source timeout is now
    25 seconds, with one automatic retry on a transient timeout / connection error.
  - **CT General Statutes (cga.ct.gov)** — the server presents an *incomplete* TLS certificate chain
    (it omits the GoDaddy intermediate), so verification failed with "unable to get local issuer
    certificate." CannaScope now supplies that well-known intermediate and verifies against it, so the
    chain validates **with TLS certificate verification still ON** — completing the chain the server
    should have sent, never disabling a security check.

  These are read-only fetches of public CT legal-reference pages. The verifier still never fabricates a
  dated limit, and continues to mark anything it cannot confirm as *"Historical standard not verified —
  manual legal review needed."* The product-registry download (data.ct.gov) and offline mode were not
  affected and are unchanged.

### Unchanged / preserved
- Every V15.1.0 feature — `audit-cache`, the `Data Exports` subfolder, the Streamlit app, short PDF
  filenames, per-run folders, the COA triple-check, and the three-part potency review — is unchanged.
  No files, branches, tags, or releases were deleted or renamed.

## [15.1.0] — 2026-06-04 — CannaScope CT V15.1

Additive maintenance + deployability release on top of V15.0.0. All prior releases (V15.0.0 and
every beta) remain live and unchanged; nothing was removed from the repository.

### Added
- **Pre-V16 cache audit & re-evaluation** — a new `audit-cache` subcommand that re-validates the
  scan ledger against the current analysis-logic version (`ANALYSIS_VERSION`). It re-evaluates every
  previously clean-skipped record under current detection/validation, surfaces any that now produce
  findings, and re-stamps the cache as current. Resumable, batched, checkpointed, and
  non-destructive (it backs up the ledger first). A full local run re-checked all ~17k records and
  confirmed the stale cache was not hiding findings.
- **`--force-rescan`** (on both `audit-cache` and `statewide`) — ignore the skip-list and reprocess
  everything from scratch, for testing / validation / major-version dev.
- **Streamlit web app (`streamlit_app.py`)** — a friendly browser UI (Statewide sample + Consumer
  Concern lookup) that drives the V15 program and serves the PDF via a download button. Deployable
  on Streamlit Community Cloud from `main`. Light work per click; secrets via `st.secrets` only.

### Changed
- **Tidier output folders** — within each per-run report folder, all CSV + diagnostic exports now go
  in a **`Data Exports`** subfolder, so the folder holds just the PDF + that one subfolder.
- Declared version bumped to **15.1** (cover, footer, metadata).

### Unchanged / preserved
- The short PDF filenames, per-run folders, persistent numbering registry, COA triple-check, legal
  date-aware verification, three-part potency review, and all V15.0.0 features remain as-is. No files,
  branches, tags, or releases were deleted or renamed.

## [15.0.0] — 2026-06-04 — CannaScope CT V15

A truth-in-reporting release: the report says only what the COAs and the date-correct standards
support, labels its own limits plainly, and packages cleanly. All prior releases remain live and
unchanged; nothing removed from the repository.

### Added
- **Three-part potency review** — High THC Flower (A), Impossible Cannabinoid Math (B), Possible
  Product-Type Misclassification (C) — replacing the combined high-cannabinoid section. Total THC is
  computed from the COA's own components (`0.877 × THCA + Δ9-THC`).
- **Six-field COA triple-check** on every published row (value · product · date · lab · unit ·
  analyte) with an auditable per-row stamp (`COA_Provenance_Audit.csv`); clear mismatches route to a
  new **Coverage Gaps / Unvalidated COAs** section.
- **Legal Standard Verification (by test date)** — local-first (built-in date-keyed registry → cached
  prior lookup), consulting live CT sources (eRegulations / CGS / DCP) **only as a fallback**, fully
  fail-safe and never fabricated; unconfirmed standards say "Historical standard not verified —
  manual legal review needed" with the URLs attempted. Cached in `Legal Standards Cache.json`.
- **Software Self-Enhancement & Self-Audit** section + a persistent cross-run **improvement log**
  (`Self-Improvement Log.json`) the next run reads and re-attempts.
- **Short PDF filenames + per-run output folders + persistent numbering registry** —
  `{N}-CannaScopeCT-{SW|CC}-{M.D.YY}-{TIME}.pdf`; each run gets its own
  `{N} Statewide Report {M.D.YY}` / `{N} Consumer Concern Report {M.D.YY}` folder holding the PDF +
  all CSVs/diagnostics; `report_registry.json` keeps global report numbers and per-type folder
  numbers; nothing is ever overwritten or reused.
- **Applicable CT Standards by Test Date** reference table; testing dates on **every** Ombudsman and
  Compliance Review Leads row.

### Changed / fixed
- **Conflict math** recomputed + consistency-gated (absolute difference, ratio = max ÷ min, %
  difference); near-equal values no longer show huge multipliers; implausible ratios are labeled
  likely parser/format artifacts.
- **Conflict wording** corrected — same-lab retests labeled as retests/duplicates; "possible
  lab-shopping indicator" reserved for genuine cross-lab pass/fail conflicts; no failed-result
  language in PASS/PASS cases.
- **Yeast & Mold review** renamed "Yeast & Mold — Date & Lab Standard Review" and narrowed to real
  standard/reporting/pathogen concerns.
- **PDF layout** — larger fonts, adaptive landscape table widths, no detached headers, cleaner page
  breaks, larger footers.
- Confidence/uncertainty appendix metrics relabeled to mutually-distinct names with an explainer.
- Year-by-year COA Format Learning now auto-prioritizes the least-trained years.

### Removed (V15 report sections/behaviors — repository history preserved)
- **Lower-Concern Products** section (risked reading as a safety ranking / endorsement).
- The internal **10,000 CFU/g benchmark as a standalone concern — from the Yeast & Mold Standard
  Review only** (still an internal awareness threshold shown elsewhere).
- Misleading same-lab/cross-lab wording; failed-result language in PASS/PASS cases; unvalidated /
  unreadable COAs from normal findings; and overly long PDF filenames.

### Known limitations
- Historical non-TYM limits ship marked **UNVERIFIED** pending manual confirmation; live legal
  lookups reach + log the sources but do not auto-extract an exact dated number from legal prose.
- 2023–2024 COA formats still being trained (surfaced in the Self-Audit; run `learn` online to mature).

## [14.0.0] — 2026-06-04 — CannaScope CT V14

Carries everything in V13 and adds historical COA-format awareness, a clean permanent report-naming
standard, and layout polish. All prior releases remain live and unchanged; nothing removed.

### Added
- **COA Format Learning Layer** — historical, year-by-year (2015–2026) awareness of changing COA
  layouts/labs/templates without assuming one fixed format and without touching the v4/v5 engine.
  `profile_coa()` fingerprints each COA's lab, year/era, sections present + their order, pass/fail/ND
  vocabulary, identity fields, and scanned-image flag. `assess_extraction()` cross-checks FIVE signals
  (top-level pass/fail summary · detailed breakdown tables · numeric values · batch/product/licensee
  identity · whether the COA matches the product record) → HIGH/MEDIUM/LOW/UNCERTAIN. A top-PASS /
  detail-FAIL conflict, impossible numbers, or a true product mismatch marks the extraction UNCERTAIN
  and **holds it out of the report** (a COA Extraction Review queue) instead of publishing bad data.
  A persisted per-year readiness map (`COAFormatLearner`) accumulates across runs.
- **`learn` self-test subcommand** — samples COAs from every available year, profiles + cross-checks
  them, and prints/writes a year-by-year parsing-confidence report (year · sampled · labs/producers ·
  fields read · uncertain · known layout patterns · ready-for-reports). New appendix subsection +
  `coa_format_confidence_by_year.csv` / `coa_extraction_held.csv` + debug metrics.
- **PDF report naming standard** — `[REPORT#]-CannaScopeCT-V[VERSION]-[TYPE]-[DATE]-[TIME].pdf`
  (TYPE = `Statewide` | `ConsumerConcern`; DATE = `YYYY-M-D`; TIME = 12-hour `H:MMAM/PM`). The report
  number is **global and continuous across both report types**, never resets, never reused; reports are
  never overwritten/renamed/deleted. Cover page reformatted to match (name / `Report #N` / type /
  `Created Month D, YYYY` / `H:MM AM/PM TZ`).

### Changed / fixed
- **Adaptive white-space reflow** — root cause was reportlab `keepWithNext` bundling a header + intro +
  the entire following table into one block (a too-tall table jumped to the next page, leaving big
  gaps). Headers no longer carry `keepWithNext`; a `CondPageBreak` guard prevents orphaned headers, so
  tables split and fill pages. The ~8 large interior gaps are gone; adapts to large and small reports.
- **Right-aligned numeric columns** (with matching right-aligned headers) across the findings tables,
  Top Findings, High-Cannabinoid, and producer/lab trend counts for easier scanning.
- **Conflicting-COA / lab-shopping persistence** — detection now runs over a persistent cross-run store
  of per-COA "conflict fingerprints," so a conflict whose two COAs were scanned in different runs is
  still found and earlier findings aren't lost on a ledger-warm re-run.
- Rebranded from **CannaScope CT V13** to **CannaScope CT V14**.

### Unchanged
- The COA source-binding integrity rule, thresholds/calculations, and the detection engine. The
  single-file build ships in the download zips (the embedded registry snapshot is intentionally NOT
  committed to git to avoid repo bloat).

## [13.0.0] — 2026-06-03 — CannaScope CT V13

Big readability + integrity + feature release. Carries all V11/V12 capabilities; all prior releases
remain live and unchanged. Nothing removed from the repository.

### Added
- **Conflicting COA Results & Possible Lab-Shopping Indicators** (statewide): same physical lot
  (shared batch/lot/BioTrack/sample/product-code) with conflicting pass/fail across lab reports,
  esp. an earlier FAIL followed by a later PASS. Pass/fail is judged against the limit STATED ON
  EACH COA (CT standards changed over the years). Neutral, human-review-only; never alleges
  misconduct. New `conflicting_coa_results.csv` export.
- **High-cannabinoid breakdown** columns: THCA / Δ9-THC / CBD / Total THC / Total Cannabinoids.
- **Potential Compliance Review Leads** (renamed from Statute & Regulatory Flags) with buckets
  A (over current CT limit) / B (implausible potency + cannabinoid breakdown + chemistry consistency
  checks) / C (missing numeric microbial despite PASS) / D (COA/document inconsistency); cautious
  "authority area to verify in eRegulations" wording.
- **Most Important Findings** summary box (computed) + **How To Read These Findings** legend.
- **Dataset accounting** line (window / scanned this run / reused from ledger / fetched / published).

### Changed / fixed
- **Producer percentages** now use each producer's total products in the window as the denominator
  (was a misleading near-100%); section renamed "Flagged Findings by Producer."
- **Report numbering** carried in filename + cover + footer + PDF metadata, with a guard against
  overwrite/reuse; each report is **one uniquely numbered file** (removed a duplicate-copy that
  caused OS "overwrite" prompts); second-precision timestamps.
- **Section reorder** to a publication-first flow; technical material moved to an **Appendix**.
- Fixed a box-overlap rendering bug (shaded boxes no longer bleed over headers); centered the
  Most Important Findings header; fixed a legend block that was pushed to a new page.
- Remediation now flags flower at/under 100 CFU/g; Lower-Concern range 800–3,000 CFU/g.
- Rebranded from "CannaScope CT Beta V12.1" to **"CannaScope CT V13"** (dropped "Beta").

### Removed
- The two potency-reference sections (infused products; vapes/concentrates/extracts) — pure potency
  listings, not findings.
- Five redundant "Top …" mini summary tables (duplicated the full sections + the summary boxes).

### Unchanged
- The COA source-binding integrity rule, thresholds/calculations, and the detection engine. The
  single-file build ships in the download zips (the embedded registry snapshot is intentionally NOT
  committed to git to avoid repo bloat).

## [12.1.0-beta] — 2026-06-03 — CannaScope CT Beta V12.1

Additive feature release. Carries every V11.1 integrity feature and all prior capabilities; all
prior releases remain live and unchanged. Nothing removed.

### Added — Conflicting COA Results & Possible Lab-Shopping Indicators (Statewide Transparency Report)
- A new statewide section that surfaces **document-level discrepancies for human review,
  neutrally** — no allegations of fraud or misconduct.
- **Cross-record detection:** the same physical lot (matched on a distinctive shared identifier —
  batch, lot, BioTrack/UID, lab sample ID, or product code) showing **conflicting pass/fail COA
  results** across lab reports, especially an **earlier failing result followed by a later passing
  result** on a regulated safety category (a *possible retesting discrepancy / possible
  lab-shopping indicator*).
- **Within-document detection:** one COA carrying more than one lab identity, or a passing summary
  alongside a failing regulated-test result (page numbers preserved where available). Uses a strict
  fail-verdict match that ignores "Pass/Fail" column headers (no false positives on clean COAs).
- Categories compared: total yeast & mold, total aerobic microbial count, Aspergillus, E. coli,
  Shiga toxin-producing E. coli, Salmonella, Listeria, mycotoxins, heavy metals, pesticide panel.
- Presentation: high-severity examples ride near the top of the report (red = Critical, orange =
  High); otherwise lower-severity observations appear later, and if none are found the report notes
  "No conflicting COA result patterns detected." Each case shows a side-by-side comparison, the
  numeric difference, a timeline note, source COA links/page references, and a plain-English
  explanation that names the innocent explanations too. Severity tiers Critical/High/Medium/Low.
- New export `conflicting_coa_results.csv`; an executive-summary line when Critical cases exist; and
  a validation note: "This section flags document-level discrepancies only. It does not prove
  intent, misconduct, remediation, or unlawful conduct without further verification."
- Statewide report only. The Personalized Product Concern report is unchanged unless the specific
  product is itself involved.

### Unchanged
- Thresholds, calculations, COA-verification standards, the rest of the section order, Ombudsman and
  TYM placement, and report numbering. The single-file build ships in the download zips (the
  registry snapshot it embeds is intentionally NOT committed to the git tree to avoid repo bloat).

## [11.1.0-beta] — 2026-06-03 — CannaScope CT V11.1 Beta — EMERGENCY COA INTEGRITY PATCH

Use V11.1 instead of V11. Additive; all prior releases remain live and unchanged.

### Fixed / hardened (data integrity)
- Enforced COA source-binding in BOTH reports: every published value is independently re-verified
  in its OWN linked COA; any value that cannot be confirmed is EXCLUDED and routed to manual
  review. Nothing unverified is ever published.
- New COA Source Mismatch Review queue; the consumer report shows a "held for manual review" note.
- New status FAIL SOURCE VALIDATION (and PASS WITH WARNINGS when mismatches are found + excluded).

### Added
- Integrity exports: COA_Provenance_Audit.csv, COA_Source_Mismatch_Review.csv, Multiple_COA_Alert.csv;
  a "COA Source-Binding Audit" diagnostics panel; new diagnostics metrics.
- Baked-in caches: embedded registry snapshot (skips the download when fresh; offline/fallback;
  online auto-refresh keeps data current) + opt-in --fast-cached first-run mode.

### Unchanged
- Thresholds, calculations, COA-verification standards, section order, Ombudsman placement, and
  report numbering. The single-file build ships in the download zips (the registry snapshot it
  embeds is intentionally NOT committed to the git tree to avoid repo bloat).

## [11.0.0-beta] — 2026-06-03 — CannaScope CT V11 Beta — beta

Additive release. All prior versions remain live and downloadable, unchanged.

### Added / improved
- Clean two-report naming: **Statewide Transparency Report** (`statewide`, also the default) and
  **Personalized Product Concern Report** (`concern`), each with its own output folder.
- Statewide report: first-pages (1-3) layout polish + findings-first **Findings at a Glance**
  summary, a consolidated producer section, and concise per-section trend notes. COA IDs never
  wrap and stay clickable; full product names preserved.
- Consumer report: **PRODUCT OF CONCERN** header, **Complaint Investigation Summary**,
  **severity tiers**, legal-entity + brand producer names, **Producer Trend Context**, smarter
  related/sibling-COA comparison (same product -> size -> closest date), and a
  **"Why this product was matched"** explanation.
- Self-contained `CannaScope_CT_Beta_V11.py` + modular `cannascope_ct_v11.py` + `_make_v11.py`.
- Windows / macOS / Linux download bundles.

### Unchanged
- Statute/Ombudsman sections, COA dates + clickable links, multi-lab COA-parsing accuracy,
  offline bundle, numbered never-overwrite reports. Thresholds, calculations, COA-verification,
  and matching logic are unchanged.

## [10.0.0-beta] — 2026-06-03 — CannaScope CT Beta V10 — beta

Additive release. All prior versions remain live and downloadable, unchanged. Repository
renamed to `CannaScope-CT` (stable name; GitHub redirect from the old name preserved — the
release, not the repo, now carries the version).

### Added
- **Patient-Reported Product Concern — Personalized Analysis PDF** (`patient-concern`
  subcommand). On-demand single-product report: resolves the product against the CT registry +
  its COA from any identifiers (name, batch, NDC, UID/BioTrack lot, COA #, dates, QR/COA link),
  runs the near-/over-limit + statute/regulatory-flag logic, surfaces identifier discrepancies,
  and links related/sibling COAs from the same producer (same strain + form, closest in time)
  with live clickable COA links so a patient can compare batches. Output to
  `output/patient_concerns/`; never overwrites. Advisory / non-diagnostic / not medical advice.
- Self-contained `CannaScope_CT_Beta_V10.py` + modular `cannascope_ct_v10.py` + `_make_v10.py`.
- Windows / macOS / Linux download bundles.

### Carried forward from V9.1 (unchanged)
- "Potential Statute & Regulatory Flags to Evaluate" and "CT Cannabis Ombudsman — Medical
  Patient Safety Review" PDF sections, with COA dates + clickable COA links.
- Multi-lab COA-parsing accuracy work; offline source bundle; numbered never-overwrite reports.
- The broader Compliance Screening + Environmental Linkage engines remain reserved/dormant
  (present in-code, not wired).

## [9.1.0-beta] — CannaScope CT Beta V9.1

Consolidation point release of the V9 line. Additive: all prior releases remain live and
downloadable, unchanged. Repository renamed to `CannaScope-CT-Beta-V9.1` to match.

### Changed
- Version label bumped to **CannaScope CT Beta V9.1**; refreshed Windows/macOS/Linux
  downloads under the V9.1 name.

### Unchanged from V9.0
- Compliance Screening + "Potential Statute & Regulatory Flags to Evaluate" PDF section.
- CT Cannabis Ombudsman — Medical Patient Safety Review PDF section.
- Field-aware COA extraction, ND/limit/LOQ/LOD never published as measurements,
  regulatory-limit → manual review, crash-isolated OCR, offline mode.
- No detection-logic changes.


## [9.0.0-beta] — CannaScope CT V9 Beta

Additive release. All prior releases remain live and downloadable, unchanged. Released as the current version; all prior releases remain live and downloadable.

### Added
- **Compliance Screening Engine** — surfaces *potential* Connecticut statutory/regulatory
  matters (authority set: CGS Ch. 420h / RERACA, CGS Ch. 420f, DCP Policies & Procedures
  eff. 2024-11-12, RCSA Sec. 21a-408, and the Public Acts amendment layer — resolve in
  eRegulations.ct.gov). Each item is a review flag with cited authority, status, severity,
  confidence, and recommended next step. Flags to investigate, not legal determinations.
- **"Potential Statute & Regulatory Flags to Evaluate" PDF section** (near the end of every
  report): results over the CT legal limit, detected zero-tolerance pathogens, failed
  pesticide/solvent panels, and high-cannabinoid potency-label reconciliation
  (0.877×THCA + Δ9 vs reported Total THC), each with a clickable COA link; renders even when
  empty.
- **"CT Cannabis Ombudsman — Medical Patient Safety Review" PDF section** (immediately after
  the flags): products that PASSED testing but came closest to a CT action limit, ranked by
  margin across all contaminant classes (tunable threshold, default 80%), with closeness
  tiers, per-class patient notes, and clickable COA links. Advisory; not medical advice.
- Pre-built self-contained downloads for Windows, macOS, and Linux.

### Notes
- Carries the V8.x accuracy work: field-aware COA extraction across lab/year formats,
  ND/limit/LOQ/LOD never published as measurements, regulatory-limit matches routed to
  manual review.
- Compliance and ombudsman outputs are review aids, not legal or
  medical advice.


## [5.0.0-beta] — CannaScope Beta V5 — public release

**Standardized the public-facing version name to CannaScope Beta V5.** Internal
development used "V7" report-build naming; those builds and all earlier versions
(Beta V1, CannaScope CT V2/V3/V4) are preserved in history — nothing was deleted.

### Added
- **Testing Date** column throughout every product-level table (COA test/sample
  date; never the report-generation date; registry date only as a fallback).
- **CT Legal Limit** and **CannaScope Limit** comparison columns, plus
  **CT % Of Limit** and **Difference From CannaScope** — full numeric context per row.
- **Producer Trends** and **Lab Trends** under the Executive Summary.
- **High Cannabinoid Content / High THC Content Findings** (non-infused flower > 35%).
- **Infused & Extract Potency Comparison Reference**.
- **Possible Remediation / Unusually Low Microbial Load Review** with cautious
  wording safeguards (explicitly *not* proof of remediation).
- Expanded Executive Summary dashboard (top heavy-metal / microbial / high-cannabinoid /
  producer / lab / possible-remediation findings) and per-measurement severity colors.

### Improved
- Clickable COA links on every finding; live COA row validation (substantive
  mismatches only); PASS / PASS WITH WARNINGS / DRAFT / FAIL status; zero-result
  verification; source-verified producer/DBA identity with confidence scores.
- Larger typography, centered headers, findings-first order, diagnostics at the end.

### Packaging
- New entry script `cannascope_beta_v5.py` (engine modules `cannascope_ct_v5.py`,
  `cannascope_ct_v4.py`, `ct_cannabis_names.py`).
- Per-OS packages `CannaScope_Beta_V5_{Windows,macOS,Linux}.zip` and sample report
  `CannaScope_Beta_V5_Report.pdf`.
- Docs: README, RELEASE_NOTES, DISCLAIMER, docs/user-guide, docs/validation-methodology,
  docs/report-fields.

## [0.4.0] — CannaScope CT Beta Version 4 — 2026-06-02

### CannaScope CT Beta Version 4
- Adds CannaScope CT Standard.
- Separates Connecticut Legal Limit from CannaScope CT Standard.
- Uses 10,000 CFU/g CannaScope CT Standard for yeast/mold and aerobic bacteria.
- Uses 50% of Connecticut Legal Limit as CannaScope CT Standard for metals, mycotoxins, pesticides, and other regulated contaminants.
- Adds + / - comparison against CannaScope CT Standard.
- Adds Date Created and Time Created to reports.
- Adds improved Executive Summary sections.
- Improves capitalization, font readability, spacing, table layout, and overall PDF appearance.
- Adds or updates macOS, Windows, and Linux Version 4 run/build support.

#### Version 4 refinements (2026-06-02)
- Flagging now uses the **CannaScope CT Standard**: heavy metals, mycotoxins, and residual solvents flag only at/over 50% of the Connecticut Legal Limit (trace detections far below the limit no longer create noise); Total Aerobic Bacteria flags at/over the 10,000 CFU/g CannaScope CT Standard, like Yeast & Mold.
- The internal-contradiction check is now a YELLOW "Verify" caution instead of RED "Do Not Consume", so nothing is marked Do Not Consume without a visible cause (a prohibited detection or an over-Connecticut-Legal-Limit result).
- Lab-name parser recognizes Northeast Laboratories COAs that identify only as "NELabs" / nelabsct.com, and no longer mistakes COA section headers (e.g. "Stability Testing") for a lab name.

## [0.3.0] — CannaScope CT Version 3 Beta — 2026-06-02

Adds proximity-to-limit reporting against BOTH the CT legal limit and a stricter
**CannaScope CT limit**, plus much clearer output. V2 and Beta V1 remain available
and unchanged as tagged releases.

### Added / changed
- **% of CT Legal Limit** and **% of CannaScope CT Limit** columns for every
  contaminant that has a limit, color-coded by proximity (>=90% dark red,
  75-89.9% orange, 50-74.9% yellow). Computed dynamically per COA.
- **Executive Summary page** — "Products Closest to the Limits," ranked by % of
  limit reached, showing measured value, CT legal limit, and CannaScope CT limit.
- **Recognizable producer names**: common / DBA name + legal LLC (e.g.
  "Fine Fettle (FFD 149 LLC)", "Theraplant (DXR Finance 3, LLC)"), plus the
  product brand parsed from the COA, via the new `ct_cannabis_names.py` module and
  optional `dba_overrides.csv`. Lab names normalized.
- **Reads Northeast Laboratories' columnar COAs** — recovers yeast/mold & aerobic
  counts earlier versions could not parse.
- **Per-Lab Analysis Summary** and a **name coverage audit** so every lab and
  producer is accounted for each run.
- **Clearer, wider report layout** (legal landscape, larger type) and the numbered
  report is also written to the top of the run folder for easy access.
- **Default look-back is now 60 days** (use `--days` to widen/narrow).

## [0.2.0] — CannaScope CT V2 — 2026-06-02

Renamed to **CannaScope CT** and substantially upgraded. The Beta V1 release
remains available and unchanged.

### Added / changed
- **All product types** evaluated by default (not just inhalables): flower,
  vapes, concentrates, edibles, tinctures, topicals.
- **OCR for scanned/image-only COAs** (Apple Vision via `ocrmac` on macOS,
  tesseract elsewhere) — they are now read and evaluated instead of skipped.
- **~65× faster PDF parsing** by switching from pdfplumber to pypdfium2, plus
  concurrent downloads (16 workers) — typical run is a couple of minutes, reruns
  are seconds.
- **Severity-sorted report**: most severe first (RED → ORANGE → YELLOW), then by
  contaminant magnitude within each tier.
- **Clickable COA links**: every COA number opens its exact source COA PDF.
- **Numbered reports**: `CannaScope CT - Flagged Products - N.pdf`, a new file per
  run (never overwrites).
- **Simplified color guide**: RED = do not consume; ORANGE = use high caution if
  sensitive; YELLOW = moderate caution for those with sensitivities.
- **Self-cleaning cache**: only flagged COA PDFs are retained; the cache prunes
  itself each run.
- **Pesticide-panel FAIL now flags RED** (was previously not flagged).
- **Clear, capitalized output folder/file names** under
  `CannaScope CT - Flagged Product Results and Sources/`.

## [0.1.0-beta] — Beta V1 — 2026-06-01

First public Beta (`connecticut_cannabis_contaminant_checker_beta_v1.py`).

- Inhalable-forms contaminant audit against CT's codified standards with a
  10,000 CFU/g yeast & mold watch line.
- Microbiological zero-tolerance, mycotoxins, heavy metals, pesticide/solvent
  pass-fail; color-coded PDF + CSV; concurrent download/parse; registry cache.
- Reads results with the COA's own units/limit columns to avoid unit-conversion
  mistakes.
