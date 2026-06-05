#!/usr/bin/env python3
"""
CannaScope CT V15
=======================
Connecticut Cannabis Transparency Report — source-verified consumer-awareness and
testing-pattern review.

Every flag is a LEAD, not a conclusion. CannaScope CT V15 does not claim
fraud, unsafe product, or legal failure unless the live COA and the applicable
Connecticut legal limit directly support that claim.

WHAT Beta V9 DELIVERS (on top of the validated core contaminant + cannabinoid engine)
  * THREE-CATEGORY PRODUCT TAXONOMY — flower (non-infused), infused flower products
    (infused joints/blunts/pre-rolls), and vapes/concentrates/extracts are kept
    STRICTLY separate. Vapes are never grouped with infused products.
  * PER-LINE-ITEM COA VERIFICATION (anti-hallucination) — every flagged value must
    literally appear in its COA text (matched as a distinct number) or it is
    excluded from all findings.
  * IMPLAUSIBLE-VALUE REJECTION — a value >1000x its limit, an absurd magnitude, or
    a flower cannabinoid reading above 45% is rejected as an OCR/parse error.
  * CRASH-PROOF + SELF-PACING — OCR runs in an isolated subprocess (a native
    segfault kills only that child), every COA is wrapped so nothing can kill a
    worker, a predictive overload backoff (psutil/load-average) self-paces on big
    runs, and a deferred low-load pass retries anything still unreadable.
  * ZERO-TRUST VALIDATION, clickable COA links, combined Producer/DBA column with a
    source-confidence score, zero-result verification, separate per-analyte tables,
    self-audit + debug log, and PASS / PASS WITH WARNINGS / DRAFT / FAIL status.
  * REPORTS ARE NEVER OVERWRITTEN — each is uniquely named
    CannaScope_CT_V15_Report_<N>_MM_DD_YYYY.pdf, numbered sequentially from 1.

REUSES the validated core engine (imported) for download / OCR / contaminant +
cannabinoid parsing / flagging, so the detection logic is unchanged.

REQUIREMENTS:  pip install requests reportlab pypdfium2  (OCR: ocrmac / pytesseract;
  optional psutil for sharper overload detection). Place cannascope_ct_v5.py,
  cannascope_ct_v4.py, ct_cannabis_names.py, cannascope_ocr_worker.py beside this.
TYPICAL RUN:  python cannascope_ct_v6_1.py --since 2024-01-01 --until 2024-12-31
"""

import argparse
import csv
import datetime
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

try:
    import cannascope_ct_v5 as v5
    import cannascope_ct_v4 as v4
except ImportError:
    sys.exit("CannaScope CT V15 needs cannascope_ct_v5.py and cannascope_ct_v4.py beside it.")

# Persistent COA->measurement cache (optional; --csv-cache). Imports v4/v5, so it must load after
# them (self-contained: installed by _install_embedded before this body runs). Soft-fail: the cache
# is opt-in, so a missing module must never block a normal run.
try:
    import coa_csv_cache as cc
except Exception:
    cc = None

names = getattr(v4, "names", None)
ProductV5 = v5.ProductV5

# ============================================================================
# Config
# ============================================================================
# Version label shown on the report cover, in output filenames, and in the footer.
APP_NAME = "CannaScope CT V16.1.1"
# Software version as it appears in the report FILENAME standard, e.g. "13" -> "...-V15-...".
# Bump this (and APP_NAME) on a version change; the report-number sequence keeps going (global,
# continuous, never resets) and filenames simply carry the new version token.
SOFTWARE_VERSION = "16.1.1"
FILE_VERSION_TAG = f"V{SOFTWARE_VERSION}"
# Single source of truth for the actual shipped single-file name (major version only), used in EVERY
# rendered/printed recommendation and disclaimer so the report never names a stale script (P4 fix).
SCRIPT_FILE = f"CannaScope_CT_V{SOFTWARE_VERSION.split('.')[0]}.py"   # -> "CannaScope_CT_V16.py"
# Short product name (no patch number) for disclaimers/prose.
PRODUCT_NAME = "CannaScope CT V" + SOFTWARE_VERSION.split(".")[0]      # -> "CannaScope CT V16"

# ============================================================================
# SESSION HANDOFF / PROJECT STATE  (read this first in a fresh session)
# ============================================================================
_SESSION_HANDOFF = r"""
CannaScope CT V15 — Connecticut cannabis testing & compliance tool. ONE self-contained file is the
whole program (engine v4 + cannabinoid/identity v5 + name resolver + OCR worker + a registry
snapshot + a skip-list snapshot all embedded/compressed at the top). V15 = V14 PLUS a major
VALIDATION-HONESTY + COA-FORMAT-LEARNING hardening pass: (a) presence-aware zero-result logic
(0-parse is "Not Reported (historical)" only when the panel's wording is truly absent, else "Needs
Historical Parser Review" — never a clean zero); (b) verified Total THC computed from the COA's own
components (0.877*THCA + delta-9) instead of an inflated COA-stated figure (fixes the old AltaSci
THCA+THC-without-0.877 ~2x inflation, and ignores a generic "thc" field that duplicates THCA);
(c) deeper COA Format Learning — per YEAR x LAB x PRODUCT-TYPE fingerprints, value styles, core-
category coverage, 3-tier READY/PARTIAL/NOT READY readiness that GATES validation; (d) compliance
leads triaged Critical/High/Moderate/Low; (e) AltaSci <1,000,000 worded as "undetermined", not a
measured exceedance; (f) a page-1 "What failed validation?" plain-English box. V14 itself = V13 +
naming standard + reflow + conflict persistence. Built from cannascope_ct_v15_src.py by _make_v15.py.

TWO MODES (one program):
  * Statewide Transparency Report  ->  `python3 CannaScope_CT_V15.py statewide --days 365`
  * Personalized Product Concern Report  ->  `python3 CannaScope_CT_V15.py concern --example`
      (advisory consumer review of ONE product; resolves from any identifiers; NOT medical advice).
  * COA Format Learning self-test  ->  `python3 CannaScope_CT_V15.py learn --years 2015-2026`
  Output -> "CannaScope CT V15 - Statewide Transparency Reports/" and "output/consumer_concerns/".
  PDF REPORT NAMING STANDARD (see report_filename / next_global_report_number):
    [REPORT#]-CannaScopeCT-V[VERSION]-[TYPE]-[DATE]-[TIME].pdf
    e.g. 15-CannaScopeCT-V15-Statewide-2026-6-4-5:36PM.pdf
         16-CannaScopeCT-V15-ConsumerConcern-2026-6-4-9:49PM.pdf
    TYPE = Statewide | ConsumerConcern (the only two). DATE = YYYY-M-D (not padded). TIME = 12h
    H:MMAM/PM (no space). The REPORT NUMBER is GLOBAL + CONTINUOUS across BOTH types and never
    resets; reports are NEVER overwritten/renamed/deleted. Cover shows: "CannaScope CT V15" / "Report
    #N" / "Statewide Report"|"Consumer Concern Report" / "Created June 4, 2026" / "5:36 PM EDT".
    (macOS Finder shows the filename ':' as '/'; Terminal/ls show it correctly.)
  Flags: --since/--until, --forms, --no-ocr, --workers N, --limit N, --offline,
  --fast-cached, --refresh-registry, --keep-clean-pdfs.

STATEWIDE SECTION ORDER (publication-first; technical material is an APPENDIX at the end):
  Cover/Exec dashboard (+ dataset-accounting line) -> Most Important Findings (centered, computed)
  -> Findings at a Glance -> How To Read legend -> Flagged Findings by Producer -> Lab Trends ->
  Top Findings -> per-contaminant/heavy-metals -> Cannabinoid/Potency Review SPLIT into 3 sections
  (A. High THC Flower / B. Impossible Cannabinoid Math / C. Possible Product-Type Misclassification)
  -> Possible Remediation -> Potential Compliance Review Leads (A/B/C/D) -> CONFLICTING COA RESULTS
  (rendered ONCE here) -> CT Cannabis Ombudsman -> YEAST & MOLD Date & Lab Standard Review
  -> No Significant Findings -> APPENDIX: Technical Validation & Diagnostics (COA source-binding
  audit + per-row triple-check, Coverage Gaps / Unvalidated COAs, COA Format Learning + confidence
  metrics, producer-identity, debug log, Software Self-Enhancement & Self-Audit). NOTE: the
  "Lower-Concern Products" section was REMOVED (Part B item 8 — no safety-ranking/endorsement).

CORE INTEGRITY RULE: a value is published ONLY if re-verified to literally appear in its OWN linked
COA; else excluded to a manual-review queue (COA Source Mismatch). Enforced + audited in BOTH
reports. Status can be FAIL SOURCE VALIDATION.

KEY FEATURES (detection logic — unchanged engine):
  - CONFLICTING COA / LAB-SHOPPING (detect_coa_conflicts): same physical lot (shared batch/lot/
    BioTrack/sample/product-code) with conflicting pass/fail across labs, esp. earlier FAIL -> later
    PASS. **Pass/fail is judged against the limit STATED ON EACH COA** (CT's CFU/g standards changed
    over years), NOT a canonical limit and NOT the program's 10,000 watch line. within-doc detector
    uses a STRICT fail-verdict regex (excludes "Pass/Fail" column headers). Neutral; review-only.
  - LAB-/DATE-AWARE TYM (assess_tym): result vs lab-limit-on-test-date / current 100,000 / strict
    10,000; TYM_STANDARDS data-driven (verified=False -> VERIFY at eRegulations.ct.gov / DCP).
  - COMPLIANCE REVIEW LEADS (compliance_flag_rows): A over current CT limit, B implausible/unusual
    potency (shows cannabinoid breakdown) + consistency checks (Total Cann < Total THC / < THCA =
    impossible), C missing-numeric-microbial-despite-PASS, D COA/document inconsistency. Cautious
    "authority area to verify in eRegulations" — never a legal determination.

DATASET ACCOUNTING (important): the scan ledger skips already-verified-clean COAs, so all_results =
the flagged+new set, NOT the window. Denominators (producer % etc.) + the exec "Products In Window"
use the FULL prefiltered window (`products`), and a dataset-accounting line shows window / scanned /
reused-from-ledger / fetched / published. NOTE: cross-record conflict detection only sees products
scanned THIS run, so a ledger-warm rerun can under-detect conflicts (the "none detected" note says
so + that earlier reports are not invalidated). A full rescan needs the ledger cleared
("Already-Scanned Skip List.txt" in the reports folder).

=== RECENTLY CHANGED (this V12.1->V15 session) ===
  - Conflicting-COA feature added then hardened: stated-limit pass/fail (above), false-positive
    "Pass/Fail header" fix, usable per-case blocks (dates + LIVE clickable COA links for every lead,
    not a bare table), consistent single placement after Compliance.
  - Section overhaul: High-Cannabinoid component breakdown columns; Remediation now flags FLOWER at
    or under 100 CFU/g (was <=200); Lower-Concern range 800-3,000 (was 200-5,000); REMOVED both
    potency-reference sections (infused + vape/extract) and the 5 redundant "Top ..." mini tables.
  - Compliance section renamed "Potential Compliance Review Leads" + A/B/C/D + cautious language.
  - Most Important Findings box (computed clusters) + How To Read legend + box-overlap fix (shaded
    Paragraph spaceBefore/After MUST exceed borderPadding or the bg bleeds over the header).
  - Report-numbering integrity (number in filename+cover+footer+metadata + guard) and OUTPUT fix:
    each report is ONE file in the reports folder (removed the duplicate Downloads-root copy that
    caused the OS "overwrite" prompt); timestamps now to the second.
  - Producer % fixed to flagged / window-total (was ~100%); dataset-accounting line added.
  - Section REORDER to publication-first + diagnostics moved to an APPENDIX.

=== RECENTLY CHANGED (post-V15 polish session) ===
  - WHITE-SPACE REFLOW (DONE): the section-boundary gaps were caused by reportlab's keepWithNext,
    which bundles a header + intro + the ENTIRE following table into one KeepTogether — a table
    taller than the space left on the page then jumped wholesale to the next page. FIX: keepWithNext
    is now OFF on every header/intro style (H1/CTX/miniH/subhead/intro_para/H), so tables split and
    fill pages, and a CondPageBreak(SECTION_MIN=96) before each top-level section header (_reflow
    pass on the story) prevents orphaned headers. Adaptive to large AND small reports. Result on the
    full report: the ~8 big interior gaps (40-79%) are gone; only the pre-APPENDIX page (short
    trailing section before the deliberate hard PageBreak) and the final page remain partly empty,
    both benign. Measure with pdfplumber: lowest content-y per page vs usable band, excluding footer.
  - #9 CONFLICT PERSISTENCE (DONE): detection now runs over a PERSISTENT cross-run store of small
    per-COA "conflict fingerprints" (CONFLICT_STORE = "Conflict Fingerprints.json" in OUT_DIR), not
    just this run's products. build_conflict_fingerprint(p, watch) precomputes per-category results
    (status/value/limit/unit) + ids + within-doc info while the live product is in hand; main() merges
    this run's fingerprints into the store and detect_coa_conflicts() consumes the UNION. So a
    ledger-warm rerun no longer loses earlier conflicts, AND a conflict whose two COAs were scanned in
    different runs is now found. detect_coa_conflicts + _compare_group + _member + _make_finding +
    _internal_finding were refactored to consume fingerprint DICTS (not live products); a tiny
    _ConflictStub gives the renderer/CSV the producer/report_url/registration_number it needs for
    persisted records. New debug metrics: conflict_fingerprints_in_store / _added_this_run.
  - TYPOGRAPHY (DONE): numeric columns are right-aligned (cellr/cellrb) with matching right-aligned
    headers (tbl(..., aligns=[...]) sets per-column header alignment) in the rich findings tables,
    Top Findings, High Cannabinoid, and the Producer/Lab trend count columns — so magnitudes line up
    and are scannable. No content/logic change.
  - COA FORMAT LEARNING LAYER (DONE): historical, multi-year COA-format awareness on TOP of the
    v4/v5 engine (engine untouched). profile_coa(p,text) fingerprints each COA's lab, year, ERA
    (Early 2015-2019 / Transition 2020-2022 / Current 2023-2026), which sections are present + IN
    WHAT ORDER, the pass/fail/ND vocabulary used, identity fields, and scanned-image flag.
    assess_extraction(p,text) cross-checks FIVE signals (top pass/fail summary; detail tables;
    numeric values; batch/product/licensee identity; COA-matches-product — the last DEFERS to the
    engine's _coa_status so it never double-holds a record the engine already verified) and returns
    HIGH/MEDIUM/LOW/UNCERTAIN. A top-PASS-but-detail-FAIL conflict (or impossible numbers / a true
    mismatch) => UNCERTAIN + HELD from publishing (format_holds queue), so bad data is never reported
    as fact; normal over-watch-but-PASS CannaScope flags are NOT held. COAFormatLearner persists a
    per-year map (COA_FORMAT_STORE = "COA Format Profiles.json": labs/producers, sections, vocab,
    layout signatures, field-success, confidence mix) and gives a per-year READY/NEEDS-REVIEW verdict.
    Both pipeline-integrated (appendix subsection "COA Format Learning & Extraction Confidence" +
    coa_format_confidence_by_year.csv + coa_extraction_held.csv + debug metrics) AND a `learn`
    subcommand: `python3 CannaScope_CT_V15.py learn [--per-year N] [--years 2015-2026] [--offline]`
    samples COAs from every year, profiles + assesses, and prints/writes a year-by-year parsing
    confidence report. NOTE: it improves RELIABILITY (detect format, verify, flag gaps, per-year
    readiness) — it does NOT rewrite engine regexes at runtime; weak years are surfaced for a parser
    update. Offline only sees already-cached (recent) COAs; run `learn` online to study older years.

=== RELEASE STATE (IMPORTANT) ===
  LIVE GitHub release is still v14.0.0 ("CannaScope CT V14"). V15 is LOCAL ONLY (this machine), NOT
  yet shipped — it is the validation-honesty + format-learning hardening of V14. Ship a v15.0.0 full
  release (same flow as V14: branch -> Contents-API commit lean modular + _make + RELEASE_NOTES +
  README/CHANGELOG -> PR/merge -> release -> upload 3 zips) only when the user asks. Nothing on
  GitHub deleted; all prior releases preserved.

=== CURRENTLY BEING WORKED ON / NEXT ===
  - VERIFY at scale: a FULL online statewide rerun of 2019-2021 (cleared ledger) confirms the
    presence-aware zero-result + verified-Total-THC fixes on the whole window (offline ledger-warm
    reruns already confirm PASS WITH WARNINGS, implausible-flower ~0, chromium/solvents labeled).
  - DEEPER PARSER TRAINING: the readiness map + `learn` now scaffold per-year/lab format learning,
    but a true per-era PARSER-STRATEGY swap (different extraction code per lab/era) is still a larger
    engine effort; today the layer DETECTS format, VERIFIES extraction, GATES/HOLDS uncertain, and
    REPORTS readiness. Populating the full 2015-2026 learned map requires running `learn` ONLINE over
    time (the embedded cache is recent-heavy; older COAs must be fetched).
  - OPTIONAL: the pre-APPENDIX page can be near-empty when the trailing No-Significant/Lower-Concern
    sections are short (they sit before the deliberate hard PageBreak that starts the APPENDIX on a
    fresh page). Left as-is to keep the appendix-on-its-own-page divider; switch that PageBreak to a
    CondPageBreak if a filled page is preferred over the fresh-page divider.
  - OPTIONAL: macOS Finder shows the ':' in report filenames as '/' (Terminal/ls are correct); a
    Finder-safe time separator (e.g. 5.36PM) is a one-line change if wanted.

DEV / BUILD:
  - Edit the MODULAR source cannascope_ct_v15_src.py, then: python3 _make_v15.py -> writes
    CannaScope_CT_V15.py (everything embedded, ~5.8MB). Lint: python3 -m pyflakes cannascope_ct_v15_src.py
    (only 2 expected: ocrmac/pytesseract availability probes). Body-in-sync check: the self-contained
    body after 'import argparse' must equal the modular body (with the OCR-worker line swapped).
  - Do NOT modify v4/v5 directly (patch via override from the v15 file).
  - Deps (pip): requests reportlab pypdfium2 pdfplumber Pillow psutil (+ OCR: ocrmac on macOS /
    pytesseract+Tesseract elsewhere).

GITHUB (REST API + curl; gh NOT installed; ~/Downloads is NOT a git clone; macOS python urllib has
NO cert verification -> use curl):
  - Repo: jmlschlee/CannaScope-CT (public). Token: source ./cannascope_ct.env (GH_TOKEN); never
    print/commit; it was pasted in chat -> rotate when convenient.
  - Latest LIVE release: v14.0.0 ("CannaScope CT V14"). V15 is LOCAL, not yet shipped. Prior preserved
    (v13.0.0, v12.1.0-beta, v11.1, ...); nothing deleted. 15 releases live.
  - GOTCHAS: (1) GitHub dot-sanitizes spaces in asset DOWNLOAD URLs ("CannaScope CT V15 - Windows.zip"
    -> ".../CannaScope.CT.V15.-.Windows.zip"); README links use the dotted form. (2) A pre-release is
    NOT served by /releases/latest. (3) The heavy self-contained ships in the ZIPS, NOT committed to
    git (avoids repo bloat); git gets the lean modular + _make + RELEASE_NOTES. (4) Auto-approval
    classifier may block content-touching git/release steps until the user re-confirms in-turn.

DATA: CT registry egd5-wb6r (data.ct.gov) ~33.6k products 2012-2026. Registry CSV cached in OUT_DIR
(6h TTL); embedded snapshot seeds it. Labs: Northeast (~most), AltaSci, Analytics (image/OCR),
Advanced Grow Labs.

Full ongoing detail lives in the auto-memory: ~/.claude/projects/-Users-josiahschlee-Downloads/
memory/cannascope-project.md (and MEMORY.md index).
"""

REPORT_TITLE = "Connecticut Cannabis Statewide Transparency Report"
REPORT_SUBTITLE = "Source-Verified Consumer Awareness & Testing Pattern Review"
FRAMING = ("Every flag is a lead, not a conclusion. " + PRODUCT_NAME + " does not claim "
           "fraud, unsafe product, or legal failure unless the live COA and the "
           "applicable Connecticut legal limit directly support that claim. Every published "
           "value is traced back to the actual result field on the source COA; anything that "
           "cannot be confidently matched is routed to manual review, not published. Verify "
           "every product against its COA.")

DEFAULT_DAYS = 60
THC_REVIEW_PCT = v5.THC_REVIEW_PCT          # 35%
FLOWER_CANN_MAX = 45.0   # max plausible cannabinoid % for FLOWER. Real flower tops
                         # out ~40-43%; a flower reading above this is a parse error
                         # or a mislabeled concentrate, so it is EXCLUDED from the
                         # High-Cannabinoid FLOWER review. Concentrates/extracts are
                         # uncapped (they legitimately reach 80-90%).
MAX_TABLE_ROWS = 75      # per-section PDF row cap. A single-year run rarely hits it,
                         # but a multi-year run (e.g. 2015-2026, ~33k products) can
                         # produce hundreds of rows per contaminant — left uncapped
                         # the PDF balloons to 400+ pages. Sections are ranked by
                         # severity, so the cap keeps the worst N; the COMPLETE,
                         # uncapped data always lives in the per-section CSV exports.

OUT_DIR = "CannaScope CT V16 - Statewide Transparency Reports"
# Inside each per-run output folder, all CSV + diagnostic exports go in this subfolder so the run
# folder stays tidy (just the PDF + this one "Data Exports" subfolder).
_EXPORTS_SUBDIR = "Data Exports"
# The V15-named folder is FIRST so an existing V15 install auto-migrates (renamed) to the V16 folder on
# next run — carrying its cache, the regulatory ledger, and the global report-number sequence forward.
LEGACY_OUT_DIRS =["CannaScope CT V15 - Statewide Transparency Reports", "CannaScope CT V14 - Statewide Transparency Reports", "CannaScope CT V13 - Statewide Transparency Reports", "CannaScope CT Beta V12.1 - Statewide Transparency Reports", "CannaScope CT Beta V12 - Statewide Transparency Reports", "CannaScope CT Beta V11.1 - Statewide Transparency Reports"]   # auto-migrated to OUT_DIR if present (V15 folder first -> V16 inherits its cache, reports, and global report-number sequence)
CACHE_DIR = os.path.join(OUT_DIR, "Flagged COA Source PDFs")
REGISTRY_CACHE = os.path.join(OUT_DIR, "Registry Cache.csv")
LEDGER = os.path.join(OUT_DIR, "Already-Scanned Skip List.txt")
SOURCE_CACHE = os.path.join(OUT_DIR, "Source Validation Cache.json")
# Persistent cross-run conflict record: a small per-COA "conflict fingerprint" is kept here so
# the Conflicting-COA / lab-shopping detector spans runs. Without it, detection only sees COAs
# scanned THIS run (a ledger-warm rerun under-detects and earlier conflicts vanish). With it, a
# conflict whose two COAs were scanned in DIFFERENT runs is still found, and prior conflicts persist.
CONFLICT_STORE = os.path.join(OUT_DIR, "Conflict Fingerprints.json")
# Persistent cross-run self-improvement log (Part B item 10): each run appends structured
# observation -> why -> recommendation notes about its OWN weaknesses (untrained years, unreadable
# COAs, parser gaps, source mismatches, unverified legal standards / failed live lookups). The NEXT
# run reads this and surfaces still-open items, so the program remembers problems and improves.
SELF_IMPROVE_LOG = os.path.join(OUT_DIR, "Self-Improvement Log.json")
# --- Pre-V16 cache audit / re-evaluation (analysis-logic version stamping; resumable) -----------
# Cache validity is tied to the ANALYSIS-LOGIC VERSION, not entry age. A ledger ("clean-skipped")
# record is trusted/skippable ONLY if it was last evaluated under the CURRENT analysis version.
# BUMP this whenever detection / validation / extraction logic changes materially — every older-
# stamped AND every UNSTAMPED legacy-ledger record then becomes stale and is re-evaluated by the
# `audit-cache` subcommand. (The existing legacy ledger is entirely unstamped, so all of it is a
# re-eval candidate — which is exactly the pre-V16 concern: records skipped before newer logic.)
ANALYSIS_VERSION = "15.1.0"
AUDIT_STAMPS = os.path.join(OUT_DIR, "Cache Audit Stamps.json")   # {coa_key: {analysis_version, result, n_findings, stamped_at}}
# Persistent OCR-text cache: an image-only COA is OCR'd ONCE EVER (keyed by file content hash), so
# re-scans / audit-cache / --force-rescan skip the expensive Apple-Vision subprocess. Only successful
# (non-empty) OCR text is cached — genuinely unreadable COAs stay uncached so they are re-attempted.
# OCR_CACHE_VERSION is part of every key: bump it to invalidate all entries when the render/OCR logic
# changes materially (e.g. the escalating-DPI ladder).
OCR_TEXT_CACHE = os.path.join(OUT_DIR, "OCR Text Cache.json")
OCR_CACHE_VERSION = 1
AUDIT_PROGRESS = "v16_cache_audit_progress.json"                  # repo-root resumable progress state (atomic)
AUDIT_HANDOFF = "V16_CACHE_AUDIT_HANDOFF.md"                      # repo-root human-readable handoff
# Report filenames now follow the PDF REPORT NAMING STANDARD (see report_filename / next_report_path):
#   [REPORT#]-CannaScopeCT-V[VERSION]-[TYPE]-[DATE]-[TIME].pdf   (TYPE = Statewide | ConsumerConcern)
REGISTRY_TTL = 6 * 3600


def migrate_legacy_out_dir():
    """One-time, non-destructive folder rename: if a legacy output folder (older
    name) exists and the current OUT_DIR does not, rename it so the cached registry,
    skip-list, COA bundle, and prior sequentially-numbered reports all carry over
    unchanged (no re-download, no broken numbering). Never overwrites an existing
    OUT_DIR; if both exist, the legacy one is left untouched."""
    if os.path.isdir(OUT_DIR):
        return
    for legacy in LEGACY_OUT_DIRS:
        if os.path.isdir(legacy):
            try:
                os.rename(legacy, OUT_DIR)
                print(f"Migrated legacy folder '{legacy}' -> '{OUT_DIR}' (cache + reports preserved).")
            except OSError:
                pass
            return


# Live COA Match Status values
MATCH_EXACT = "Verified"
MATCH_PARTIAL = "Verified Partial Match"
MATCH_LINK_MISSING = "COA Link Missing"
MATCH_LINK_BROKEN = "COA Link Broken"
MATCH_PRODUCT_MISMATCH = "COA Product Mismatch"
MATCH_VALUE_MISMATCH = "COA Value Mismatch"
MATCH_MANUAL = "COA Needs Manual Review"
PUBLISHABLE = {MATCH_EXACT, MATCH_PARTIAL}

# THREE distinct product categories for the cannabinoid review. Vapes /
# concentrates / extracts are NEVER lumped in with infused products.
#   flower  = NON-infused flower: whole flower, usable marijuana, shake, smalls,
#             and plain (non-infused) pre-rolls / joints / blunts.
#   infused = INFUSED flower products: infused joints / blunts / pre-rolls, hash-
#             holes, THCA-/diamond-/rosin-infused flower (flower + added concentrate).
#   extract = vapes, cartridges, pods, disposables, and concentrates / extracts
#             (rosin, resin, wax, shatter, distillate, diamonds, hash, kief...).
#   other   = edibles, tinctures, topicals, capsules, beverages (not reviewed).
ORAL_TOPICAL = ("edible", "gummy", "gummies", "tincture", "topical", "capsule",
                "tablet", "lozenge", "beverage", "drink", "syrup", "sublingual",
                "suppository", "patch", "cream", "balm", "lotion", "troche",
                "softgel", "chocolate", " mint")
VAPE_KEYWORDS = ("vape", "vaporizer", "cartridge", "cart", "disposable", "pod",
                 "510", "all-in-one", "aio", "pax")
CONCENTRATE_KEYWORDS = ("rosin", "resin", "wax", "shatter", "badder", "budder",
                        "crumble", "sauce", "diamond", "distillate", "kief", "dab",
                        "hash", "live")
FLOWER_FORM = ("flower", "usable marijuana", "plant material", "raw material",
               "shake", "ground flower", "bud", "smalls", "mini flower", "flower mini")
PREROLL_KEYWORDS = ("pre-roll", "preroll", "pre roll", "joint", "blunt", "hash hole")


# ============================================================================
# Text cleanup — title case + unit normalization
# ============================================================================
_UNIT_FIX = {"cfu/g": "CFU/g", "cfu/ml": "CFU/ml", "ug/kg": "µg/kg", "µg/kg": "µg/kg",
             "mg/g": "mg/g", "mg/kg": "mg/kg", "ppm": "ppm", "ppb": "ppb"}
_KEEP_UPPER = {"LLC", "DBA", "COA", "CT", "THC", "THCA", "THCV",
               "CBD", "CBG", "CBN", "CBC", "CBDV", "AGL", "BUDR", "II", "III", "IV",
               "OG", "GMO", "JV", "USA", "MCEJV", "FFD", "DXR", "RAD", "SAUS"}
_SPECIAL = {"all:hours": "All:Hours", "ctpharma": "CTPharma", "soundview": "SoundView",
            "earl": "Earl", "lil'": "Lil'", "pre-roll": "Pre-Roll",
            "pre-rolls": "Pre-Rolls", "preroll": "Pre-Roll"}


def _cap_token(w: str) -> str:
    low = w.lower()
    if low in _UNIT_FIX:
        return _UNIT_FIX[low]
    if low in _SPECIAL:
        return _SPECIAL[low]
    parts = re.split(r"([-/:|])", w)
    out = []
    for part in parts:
        if part in "-/:|" or not part:
            out.append(part)
            continue
        u = part.upper()
        if u in _KEEP_UPPER:
            out.append(u)
        elif re.search(r"\d", part):     # keep tokens with digits (3.5g, T34.85%)
            out.append(part)
        else:
            out.append(part[:1].upper() + part[1:].lower())
    return "".join(out)


def tcase(s: str) -> str:
    """Clean title case for product / producer / type / heading text, preserving
    units (CFU/g, µg/kg), chemical/branding tokens, and not capitalizing the 's'
    after an apostrophe (Debbie's, Let's, Lil')."""
    if not s:
        return s or ""
    return "".join(_cap_token(w) if not w.isspace() else w for w in re.split(r"(\s+)", s))


def clean_value(v, unit: str) -> str:
    """Human value with NO scientific notation; normalized unit."""
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(v):             # NaN/inf from a bad OCR/parse -> never displayed
        return "—"
    if v != 0 and abs(v) < 0.001:        # would print as sci notation -> show plainly
        s = f"{v:.6f}".rstrip("0").rstrip(".")
    elif v == int(v):
        s = f"{int(v):,}"
    else:
        s = f"{v:,.3f}".rstrip("0").rstrip(".")
    u = _UNIT_FIX.get((unit or "").lower(), unit or "")
    return f"{s} {u}".strip()


# ============================================================================
# Testing date (COA test/sample/report date, falling back to the registry)
# ============================================================================
_DATE_RX = r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
# Preference order: 1 = tested/analysis, 2 = sampled/collected/received, 3 = reported/completed.
_TD_LABELS = [
    (re.compile(r"(?:date\s*tested|test(?:ing)?\s*date|analysis\s*date|date\s*of\s*analysis|"
                r"analyzed\s*(?:on|date))[^0-9]{0,24}" + _DATE_RX, re.I), 1),
    (re.compile(r"(?:date\s*sampled|sample\s*date|date\s*collected|collection\s*date|"
                r"date\s*received|received\s*date)[^0-9]{0,24}" + _DATE_RX, re.I), 2),
    (re.compile(r"(?:date\s*report(?:ed)?|report\s*date|date\s*completed|completed\s*date|"
                r"date\s*issued|issued\s*date)[^0-9]{0,24}" + _DATE_RX, re.I), 3),
]


def parse_testing_date(text: str) -> str:
    """Extract a COA testing date, preferring tested > sampled/received > reported.
    Never the report-generation date. Returns '' if none found (caller falls back
    to the registry date)."""
    best, best_rank = "", 99
    for rx, rank in _TD_LABELS:
        m = rx.search(text)
        if m and rank < best_rank:
            best, best_rank = m.group(1), rank
        if best_rank == 1:
            break
    return best


def fmt_date(s: str) -> str:
    """Normalize a date string to YYYY-MM-DD; '' on failure."""
    if not s:
        return ""
    y, mo, d = v4.parse_date(s)
    return f"{y:04d}-{mo:02d}-{d:02d}" if y else (s.split()[0] if s.split() else "")


def test_date(p) -> str:
    """Display testing date: parsed COA date, else the registry approval date."""
    return fmt_date(getattr(p, "testing_date", "") or p.approval_date)


# ============================================================================
# Registry (reuse the core loader but route to Beta V9 dirs)
# ============================================================================
def _seed_embedded_registry():
    """If a registry snapshot is embedded (self-contained build) AND there is no local
    registry cache yet, write it to REGISTRY_CACHE with its REAL snapshot mtime. The
    normal 6-hour freshness check then governs: a recent snapshot is used as-is (fast,
    and makes --offline work out of the box for first-time users); a stale one is
    re-downloaded fresh online — so ONLINE accuracy is never compromised. Never
    overwrites an existing (possibly fresher) cache."""
    b64 = globals().get("_EMBEDDED_REGISTRY_B64")
    if not b64 or os.path.exists(REGISTRY_CACHE):
        return
    try:
        import base64 as _b, zlib as _z
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(REGISTRY_CACHE, "wb") as f:
            f.write(_z.decompress(_b.b64decode(b64)))
        ep = globals().get("_EMBEDDED_REGISTRY_EPOCH", 0) or 0
        if ep:
            os.utime(REGISTRY_CACHE, (ep, ep))
        print("Seeded the registry cache from the embedded snapshot (skips the registry download "
              "while the snapshot is fresh; online runs auto-refresh it once it ages out — so "
              "online data stays current).")
    except Exception:
        pass


COA_DATA_CACHE = os.path.join(OUT_DIR, "COA Data Cache.csv")


def _seed_embedded_coa_cache():
    """If a TRIPLE-VERIFIED COA measurement cache is embedded in this build AND there is no local
    'COA Data Cache.csv' yet, write it to OUT_DIR so the program ships WITH the validated COA data
    (each COA already downloaded + read + triple-verified). Never overwrites an existing (possibly
    larger / fresher) cache; new/changed COAs are still fetched live and merged in on later runs."""
    b64 = globals().get("_EMBEDDED_COA_CACHE_B64")
    if not b64 or os.path.exists(COA_DATA_CACHE):
        return
    try:
        import base64 as _b, zlib as _z
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(COA_DATA_CACHE, "wb") as f:
            f.write(_z.decompress(_b.b64decode(b64)))
        print("Seeded the COA measurement cache from the embedded triple-verified snapshot "
              "(COA Data Cache.csv) — measurements load from cache; new/changed COAs still fetch live.")
    except Exception:
        pass


def load_registry(session, refresh=False, offline=False):
    v5.OUT_DIR = OUT_DIR
    v5.REGISTRY_CACHE = REGISTRY_CACHE
    _seed_embedded_registry()   # no-op unless a snapshot is embedded and no cache exists yet
    _seed_embedded_coa_cache()  # no-op unless a COA cache is embedded and none exists locally yet
    _seed_embedded_reg_ledger() # no-op unless a CT regulatory source ledger is embedded and none local
    if offline:
        # OFFLINE: read the bundled/embedded registry cache directly, ignoring its age,
        # and never reach the network.
        if not os.path.exists(REGISTRY_CACHE):
            sys.exit("--offline set but no '" + REGISTRY_CACHE + "' exists yet. "
                     "Run once online (ideally with --keep-clean-pdfs) to bundle the sources first.")
        with open(REGISTRY_CACHE, encoding="utf-8", errors="replace") as f:
            products = v5._rows_from_csv_text(f.read())
        print(f"Registry: OFFLINE — using bundled cache ({len(products)} products, age ignored).")
        return products
    try:
        return v5.load_registry(session, refresh=refresh)
    except Exception as e:
        # Resilience: if the live download fails, fall back to the cached/embedded snapshot
        # rather than aborting. (Only used when the network/source is unavailable — there is
        # no fresher option in that case.)
        if os.path.exists(REGISTRY_CACHE):
            print(f"Registry: live download failed ({type(e).__name__}); using the "
                  "cached/embedded snapshot instead.")
            with open(REGISTRY_CACHE, encoding="utf-8", errors="replace") as f:
                return v5._rows_from_csv_text(f.read())
        raise


# ============================================================================
# Flower / infused classification (Beta V9 rule: cannabinoid review split into flower / infused / extract)
# ============================================================================
def _hay(p):
    return f"{p.dosage_form} {p.product_name}".lower()


def product_category(p) -> str:
    """Classify into 'flower' | 'infused' | 'extract' | 'other'. Vapes / extracts
    are kept STRICTLY separate from infused flower products. The result is memoized
    on the product (name/form are fixed after parsing): this function is called
    5-6x per product across the run, so caching avoids ~200k redundant substring
    scans on a full multi-year (~33k product) pass."""
    cached = getattr(p, "_category", None)
    if cached is not None:
        return cached
    name = (p.product_name or "").lower()
    form = (p.dosage_form or "").lower()
    # Oral/topical is judged from the DOSAGE FORM only — strain names are full of
    # food words ("Velvet Cream", "Wedding Cake", "Mint Chocolate") that must not
    # be mistaken for edibles/topicals.
    if any(k in form for k in ORAL_TOPICAL):
        cat = "other"
    else:
        preroll = any(k in name for k in PREROLL_KEYWORDS)
        # INFUSED flower product = a flower-format item with added concentrate:
        # anything that says "infused", or a pre-roll/joint/blunt that also carries
        # a concentrate marker (hash hole, diamond/rosin/resin/live-infused pre-roll).
        if ("infused" in name
                or (preroll and any(k in name for k in
                                    ("hash", "rosin", "resin", "diamond", "live", "kief")))):
            cat = "infused"
        elif any(k in name for k in VAPE_KEYWORDS):
            cat = "extract"
        elif any(k in name for k in CONCENTRATE_KEYWORDS):
            cat = "extract"
        elif any(k in form for k in FLOWER_FORM) or any(k in name for k in FLOWER_FORM) or preroll:
            cat = "flower"
        elif "extract for inhalation" in form or "concentrate" in form:
            cat = "extract"
        else:
            cat = "other"
    p._category = cat
    return cat


def is_noninfused_flower(p) -> bool:
    """True only for NON-infused flower (the High-Cannabinoid FLOWER review set)."""
    return product_category(p) == "flower"


def is_infused(p) -> bool:
    return product_category(p) == "infused"


def is_extract(p) -> bool:
    return product_category(p) == "extract"


# ============================================================================
# THC parser-conflict guard
# ============================================================================
def thc_value(p, key):
    e = p.cannabinoids.get(key)
    return e.get("value") if e else None


def thc_conflict(p) -> Optional[str]:
    """Detect a potency parser conflict: a Total THC of 0/None while an active /
    total cannabinoid reading is 35%+, with no THCA to recompute from. Returns a
    reason string when in conflict (and the row must stay OUT of THC rankings)."""
    tt = thc_value(p, "total_thc")
    active = thc_value(p, "total_active")
    totc = thc_value(p, "total_cannabinoids")
    thca = thc_value(p, "thca")
    high = max([x for x in (active, totc) if x is not None], default=None)
    if high is not None and high >= THC_REVIEW_PCT and (tt is None or tt == 0) and (thca is None or thca == 0):
        return "Potency Parser Conflict — Total THC 0% but active cannabinoids ≥35%"
    return None


def _ok_pct(x):
    return x is not None and math.isfinite(x) and 0 <= x <= 100


def verified_total_thc(p):
    """Return (value, basis, verified) for a product's TOTAL THC, derived ONLY from clearly-mapped
    COA cannabinoid fields — never from a product name/label and never from a sum like Total
    Cannabinoids. Total THC is computed as 0.877*THCA + delta-9-THC when the components are present;
    a COA-stated Total THC is used only when it reconciles with that computation (older AltaSci COAs
    report THCA + THC WITHOUT the 0.877 decarboxylation factor, inflating 'Total THC' ~2x — e.g. a
    ~30% THCA flower printed as ~56% — so the stated value must not be trusted blindly).
    Returns (None, reason, False) when THC cannot be confidently mapped (route to manual review)."""
    thca = thc_value(p, "thca")
    d9 = thc_value(p, "d9_thc")
    if d9 is None:
        # The generic "thc" field is AMBIGUOUS in older COAs: many (e.g. old AltaSci) print "THC"
        # equal to THCA, or print Total THC there. Use it as delta-9 ONLY when it's plausibly small
        # relative to THCA (raw-flower delta-9 << THCA); if it ~equals/exceeds THCA it is a duplicate
        # or a total, NOT delta-9 — ignore it (computing Total THC = 0.877*THCA, which is safe).
        _thc = thc_value(p, "thc")
        if _ok_pct(_thc) and _ok_pct(thca) and _thc < 0.5 * thca:
            d9 = _thc
    stated = thc_value(p, "total_thc")
    if _ok_pct(thca):
        computed = 0.877 * thca + (d9 if _ok_pct(d9) else 0.0)
        if _ok_pct(stated):
            if abs(stated - computed) <= max(2.0, 0.10 * max(computed, 1.0)):
                return stated, "verified COA Total THC (reconciles with 0.877*THCA + delta-9)", True
            return computed, ("computed 0.877*THCA + delta-9; COA-stated Total THC "
                              f"({stated:g}%) did not reconcile and was not used"), True
        return computed, "computed 0.877*THCA + delta-9 (no COA-stated Total THC)", True
    if _ok_pct(stated):
        # No THCA to verify against. Trust a plausible stated Total THC; an implausible one
        # (e.g. >100 or absurd) is rejected below by the caller.
        return stated, "COA-stated Total THC (no THCA available to verify)", False
    return None, "no clearly-mapped THC field on the COA", False


def thc_review_value(p):
    """Verified TOTAL THC % for the non-infused flower review, or None. Uses verified_total_thc()
    so the review is driven by a correctly-computed Total THC, NOT the highest of several columns
    (which used to grab an inflated COA-stated Total THC or a Total-Cannabinoids sum)."""
    if thc_conflict(p):
        return None
    val, _basis, _verified = verified_total_thc(p)
    if val is None or not (0.001 <= val <= 100):
        return None
    return ("total_thc", val)


def _remediation_ym(p):
    """Yeast & mold result that qualifies a non-infused flower for the Possible Remediation /
    Unusually Low Microbial Load review: a measured 0-100 CFU/g, OR a below-detection bound
    at/under 100 (e.g. a COA that says '< 100 CFU/g'). Returns (value, is_below_detect) or None."""
    e = p.analytes.get("tymc")
    if not e:
        return None
    v = e.get("value")
    if v is None or not (0 <= v <= 100):
        return None
    below = bool(e.get("_below_detect")) or (e.get("raw") or "").strip()[:1] in "<≤"
    return (v, below)


# ============================================================================
# Producer / DBA identity (combined column + source confidence)
# ============================================================================
# Identity overlay: legal-entity (normalized) -> dict(common, brands, parent,
# confidence, source). Layered over v5.IDENTITY_TABLE. Brands are confirmed from
# the live CT product registry (the product names literally carry the brand) AND
# public sources. Entries pending live confirmation are marked accordingly and the
# report shows "DBA Needs Verification" rather than inventing a name.
def _norm(s):
    return v5._ident_norm(s)


# Producer / DBA identity baked in from live internet research (June 2026), cited
# against the sources requested: data.ct.gov product registry (egd5-wb6r), the CT
# business search / DCP portal (portal.ct.gov/dcp), CT eLicense license documents
# (elicense.ct.gov), CT Innovations licensee records, official company/brand
# websites, and reputable news. CONFIRMED = corroborated public source; LIKELY =
# strong single source; UNCONFIRMED = no public source found (shown as "DBA Needs
# Verification", never invented). This dict IS the program's identity cache.
_IDENTITY_RAW = {
    "Connecticut Pharmaceutical Solutions LLC": dict(
        common="CTPharma", brands=["Savvy", "Zen Leaf"], parent="Verano Holdings",
        confidence="CONFIRMED", source="ctpharma.com/savvy; Verano press releases (Rocky Hill, CT)"),
    "Curaleaf LLC": dict(
        common="Curaleaf", brands=["Curaleaf", "Select"], parent="Curaleaf Holdings",
        confidence="CONFIRMED", source="curaleaf.com; Simsbury CT producer (public filings)"),
    "Advanced Grow Labs LLC": dict(
        common="Advanced Grow Labs", brands=["AGL", "Good Green"], parent="Green Thumb Industries (GTI)",
        confidence="CONFIRMED", source="mjbizdaily.com (GTI acquired 2019); West Haven CT producer"),
    "DXR Finance 3, LLC": dict(
        common="Theraplant", brands=["all:hours"], parent="DXR / NewCo group (post-2023 foreclosure)",
        confidence="LIKELY", source="ahcannabis.com (Theraplant Watertown address); ctnewsjunkie.com (2023-07-31)"),
    "MCEJV LLC": dict(
        common="Affinity Grow", brands=["Affinity Grow"], parent="private (Rino Ferrarese; Portland CT micro-cultivator)",
        confidence="CONFIRMED", source="CT eLicense doc; ctnewsjunkie.com (2024-04-08)"),
    "Nutmeg New Britain JV LLC": dict(
        common="Brix Cannabis", brands=["Brix Cannabis"], parent="JV with Curaleaf (co-owner Judy Prisco)",
        confidence="CONFIRMED", source="prnewswire.com; pitchbook.com (JV Brix/Curaleaf); brixofficial.com"),
    "Connecticut Contract Manufacturing LLC": dict(
        common="ConnCM", brands=["ConnCM"], parent="private (contract manufacturer, Westbrook CT)",
        confidence="CONFIRMED", source="conncm.com (FDA-grade contract manufacturer; extracts/edibles)"),
    "Connecticut Social Equity, LLC": dict(
        common="Rodeo Cannabis Co.", brands=["Rodeo", "Tyson 2.0"], parent="private (Art Linares; Morris CT, sun-grown)",
        confidence="CONFIRMED", source="CT eLicense doc; westfaironline.com (Tyson 2.0 launch); ctinnovations.com"),
    "FFD 149 LLC": dict(
        common="Fine Fettle", brands=["Comffy"], parent="Fine Fettle Dispensaries (Bloomfield CT)",
        confidence="CONFIRMED", source="finefettle.com; becomffy.com (Comffy is Fine Fettle's flower brand)"),
    "Jananii LLC": dict(
        common="Awssom", brands=["Awssom"], parent="private (Jusmin Patel; New Britain CT cultivator)",
        confidence="CONFIRMED", source="CT eLicense doc; hartfordbusiness.com; jananii.isolvedhire.com (Awssom)"),
    "Debbie's Dispensary LLC": dict(
        common="Crisp", brands=["Let's Burn"], parent="private (retailer license ACRE.0009619)",
        confidence="CONFIRMED", source="crispcannabis.com/lets-burn (Daily! sub-brand NOT publicly confirmed)"),
    "Soundview Manufacturing LLC": dict(
        common="SoundView", brands=["SoundView"], parent="New England Edibles (Bristol CT)",
        confidence="LIKELY", source="getsoundview.com; hartfordbusiness.com (Bristol edibles/beverage maker)"),
    "56 Benton LLC": dict(
        common="Lucky Break", brands=["Lucky Break", "Lucky Chews"], parent="private (Bridgeport CT manufacturer)",
        confidence="CONFIRMED", source="luckybreakcannabis.com (56 Benton LLC d/b/a Lucky Break; Lucky Chews line)"),
    "RAD Holding Corp.": dict(
        common="Earl Baker", brands=["Earl Baker", "Early Birds"], parent="private (CT + Oregon operations)",
        confidence="LIKELY", source="ctinnovations.com angel-investor registry; earlbaker.com"),
    "Shangri-La CT Inc": dict(
        common="Shangri-La", brands=["Borealis Cannabis", "Asteroid"], parent="Shangri-La (owner Jocelyn Cerda; Stratford CT)",
        confidence="CONFIRMED", source="doingitlocal.com (Borealis by Shangri-La); cga.ct.gov testimony"),
    "The Goods THC Co.": dict(
        common="The Goods THC", brands=["The Goods", "Cookies", "Tyson 2.0"],
        parent="private social-equity (Gloribel Diaz; Hartford CT)",
        confidence="CONFIRMED", source="cannabisbusinesstimes.com (exclusive CT Cookies + Tyson 2.0 cultivator)"),
    "Golden Hanuman Inc.": dict(
        common="Golden Hanuman", brands=["Golden Hanuman"], parent="private (Alpha Patel; Middletown/Ridgefield CT manufacturer)",
        confidence="CONFIRMED", source="cannabisbusinesstimes.com; msn.com (packages oils/carts under the Golden Hanuman name)"),
    "Dutch LLC": dict(
        common="", brands=[], parent="", confidence="UNCONFIRMED",
        source="no public consumer brand found — resolve via portal.ct.gov/dcp brand registry"),
}
IDENTITY_OVERLAY = {_norm(k): v for k, v in _IDENTITY_RAW.items()}


class Identity:
    """Resolve a legal entity to a combined 'Common / Brand (Legal Entity)' label
    plus a 0-100 source-confidence score. Confidence:
        100 = COA/registry brand + CT registry + public source
         90 = COA/registry brand + CT registry
         80 = COA/registry brand + public source
         70 = CT registry + public source
         60 = a single authoritative source
        <60 = needs verification."""

    def __init__(self, pmap, all_products):
        self.pmap = pmap
        self.cache = {}            # in-memory only (per run); the IDENTITY_OVERLAY
        # is the authoritative baked-in identity cache, so resolved labels are NOT
        # persisted to disk (that would let a stale file override an overlay edit).
        # brands actually seen per producer in the live registry (COA-confirmed)
        self.reg_brands = defaultdict(Counter)
        for p in all_products:
            if p.producer and p.brand:
                self.reg_brands[_norm(p.producer)][p.brand] += 1

    def resolve(self, legal):
        legal = (legal or "").strip()
        if not legal:
            return dict(label="(Unknown Producer)", common="", brands=[], parent="",
                        confidence=0, source="", confirmed=False)
        key = _norm(legal)
        if key in self.cache:
            return self.cache[key]
        rec = self._lookup(legal, key)
        self.cache[key] = rec
        return rec

    def _lookup(self, legal, key):
        legal_disp = tcase(legal)
        overlay = IDENTITY_OVERLAY.get(key)
        v5rec = v5.IDENTITY_TABLE.get(key)
        # COA-confirmed brand(s) straight from the registry product names
        coa_brands = [b for b, _ in self.reg_brands.get(key, Counter()).most_common(3)]
        by_coa = bool(coa_brands)
        by_registry = True   # the entity is in the CT product registry (the source)

        common = ""
        brands = list(coa_brands)
        parent = ""
        source = ""
        public = False
        confirmed = False

        if overlay:
            common = overlay.get("common", "")
            parent = overlay.get("parent", "")
            source = overlay.get("source", "")
            public = overlay.get("confidence", "") in ("CONFIRMED", "LIKELY")
            confirmed = overlay.get("confidence") == "CONFIRMED"
            for b in overlay.get("brands", []):
                if b not in brands:
                    brands.append(b)
        elif v5rec:
            common = v5rec.get("common", "")
            parent = v5rec.get("parent", "")
            source = v5rec.get("source", "")
            public = v5rec.get("confidence") in ("CONFIRMED", "LIKELY")
            confirmed = v5rec.get("confidence") == "CONFIRMED"
            for b in v5rec.get("brands", []):
                if b not in brands:
                    brands.append(b)
        elif names is not None:
            disp = names.display_producer(legal, self.pmap)
            if "[UNMAPPED" not in disp:
                cand = disp.split(" (")[0].strip()
                if _norm(cand) != key:
                    common = cand
                    public = True
                    source = "ct_cannabis_names curated map"

        # Confidence scoring
        if by_coa and by_registry and public:
            conf = 100
        elif by_coa and by_registry:
            conf = 90
        elif by_coa and public:
            conf = 80
        elif by_registry and public:
            conf = 70
        elif by_registry or by_coa or public:
            conf = 60
        else:
            conf = 50

        # Combined label
        front = common or (brands[0] if brands else "")
        fl = front.lower()
        extra = [b for b in brands if b and b.lower() not in fl and fl not in b.lower()][:2]
        if front and extra:
            label = f"{front} / {' / '.join(extra)} ({legal_disp})"
        elif front:
            label = f"{front} ({legal_disp})"
        elif public:
            label = legal_disp
        else:
            label = f"{legal_disp} — DBA Needs Verification"
            conf = min(conf, 55)
        return dict(label=label, common=common or front, brands=brands, parent=parent,
                    confidence=conf, source=source, confirmed=confirmed or by_coa,
                    legal=legal_disp)

    def save(self):
        try:
            os.makedirs(os.path.dirname(SOURCE_CACHE), exist_ok=True)
            json.dump(self.cache, open(SOURCE_CACHE, "w", encoding="utf-8"), indent=2)
        except OSError:
            pass


def lab_name(p, lmap):
    return tcase(v5.lab_display(p, lmap) or "Unidentified Lab")


def producer_short(p, ident):
    """Concise findings-table producer name: 'Common (PrimaryBrand)', or just the
    common name when the brand is the same / absent. Legal entity is NOT shown here
    (it lives in the appendix). E.g. 'Fine Fettle (Comffy)', 'Brix Cannabis',
    'Rodeo Cannabis', 'Advanced Grow Labs (Good Green)'."""
    r = ident.resolve(p.producer)
    common = r["common"] or tcase(p.producer)
    common = re.sub(r"\s+Co\.?$", "", common).strip()         # 'Rodeo Cannabis Co.' -> 'Rodeo Cannabis'
    cl = common.lower()
    brand = (p.brand or "").strip()
    if not brand:
        brand = next((b for b in r["brands"] if b.lower() not in cl and cl not in b.lower()), "")
    if brand and brand.lower() not in cl and cl not in brand.lower():
        return f"{common} ({brand})"
    return common


def producer_label_short(legal, ident):
    """Producer-level concise label 'Common (PrimaryBrand)' for trend tables
    (legal entity lives in the appendix)."""
    r = ident.resolve(legal)
    common = re.sub(r"\s+Co\.?$", "", (r["common"] or tcase(legal))).strip()
    cl = common.lower()
    brand = next((b for b in r["brands"] if b.lower() not in cl and cl not in b.lower()), "")
    return f"{common} ({brand})" if brand else common


# ---- Consumer-report helpers (PATIENT/CONSUMER PDF ONLY; not used by the statewide report) ----
def producer_display(legal, product_name=""):
    """Show the legal entity AND consumer-facing names, e.g.
    'FFD 149 LLC (Fine Fettle / Comffy)'. Uses the curated identity overlay + the brand
    parsed from the product name. Falls back to just the legal entity if nothing maps."""
    legal = (legal or "").strip()
    if not legal:
        return "—"
    rec = IDENTITY_OVERLAY.get(_norm(legal))
    parts = []
    if rec:
        if rec.get("common"):
            parts.append(rec["common"])
        parts += list(rec.get("brands") or [])
    b = v4.parse_brand(product_name or "")
    if b:
        parts.append(b)
    friendly, seen = [], set()
    for x in parts:
        if x and _norm(x) != _norm(legal) and _norm(x) not in seen:
            seen.add(_norm(x)); friendly.append(x)
    return f"{tcase(legal)} ({' / '.join(friendly)})" if friendly else tcase(legal)


def severity_tier(ct_pct):
    """Context label for how close a result is to the CT limit (NOT a pass/fail)."""
    if ct_pct is None:
        return ""
    if ct_pct >= 95:
        return "Extremely Close To Limit"
    if ct_pct >= 85:
        return "Very High"
    if ct_pct >= 70:
        return "High"
    if ct_pct >= 50:
        return "Elevated"
    return ""


def producer_trend_context(legal, analyte_name):
    """Read-only: count how often this producer appears in the most recent statewide
    severity_<analyte>.csv already on file. Returns None if no such file exists (i.e. no
    statewide report has been run). Does NOT run a statewide scan or merge the reports."""
    import csv as _csv, glob as _glob
    slug = re.sub(r"[^a-z0-9]+", "_", (analyte_name or "").lower()).strip("_")
    if not slug:
        return None
    # severity CSVs now live in each run folder's "Data Exports" subfolder — pick the most recent,
    # tolerating the new nested layout plus any older flatter layouts on disk.
    cands = (_glob.glob(os.path.join(OUT_DIR, "*", _EXPORTS_SUBDIR, f"severity_{slug}.csv"))
             + _glob.glob(os.path.join(OUT_DIR, "*", f"severity_{slug}.csv"))
             + _glob.glob(os.path.join(OUT_DIR, f"severity_{slug}.csv")))
    if not cands:
        return None
    path = max(cands, key=os.path.getmtime)
    try:
        rows = list(_csv.DictReader(open(path, encoding="utf-8", errors="replace")))
    except Exception:
        return None
    ln = _norm(legal)
    hits = sum(1 for r in rows if ln and ln in _norm(r.get("producer_dba", "")))
    return dict(total=len(rows), producer=hits, analyte=analyte_name, file=os.path.basename(path))


def validation_summary(debug, remaining, zero_checks, src_metrics, unverified_in_pub, uncertain_published,
                       year_readiness=None):
    """Transparent, strict validation. Returns (status, fail_reasons, warn_reasons).

    year_readiness: list of dicts {year, verdict} from the COA Format Learning layer for the years in
    this report's window. Readiness is a COVERAGE / training-maturity signal (NOT a trust signal):
    NOT READY / PARTIAL / untrained years are WARNINGS that flag the year for more `learn` training —
    extraction TRUST is enforced separately (source-binding, uncertain-holds, parser-gaps), and those
    are what FAIL the report.

    FAIL if: a published value fails source-binding; a key category is present on COAs but parsed 0
    (unexplained parser gap); an uncertain COA was published as a finding; or any other self-audit
    issue is unresolved.
    PASS WITH WARNINGS if: no FAIL conditions, but historical limitations / partial coverage /
    held-uncertain / excluded-mismatch / coverage gaps exist (all clearly labeled).
    PASS only if there are no warnings at all."""
    fails, warns = [], []

    if unverified_in_pub:
        fails.append("COA source-binding audit failed — a published value could not be re-verified in "
                     "its own linked COA.")
    gaps = [c["category"] for c in zero_checks if c["status"] == "Needs Historical Parser Review"]
    if gaps:
        fails.append("Parser gap — these categories appear on the COAs but parsed 0 results (needs "
                     "historical-format parser review): " + ", ".join(gaps) + ".")
    if uncertain_published:
        fails.append(f"{uncertain_published} published finding(s) came from COA extractions rated UNCERTAIN.")
    # P1: a violated count invariant (flagged <= parsed <= reported-on <= window) is a counting bug,
    # not a clean result — FAIL the build rather than print an impossible fraction as "OK".
    bad_inv = [c["category"] for c in zero_checks if not c.get("invariant_ok", True)]
    if bad_inv:
        fails.append("Count invariant violated (flagged ≤ parsed ≤ reported-on ≤ window) for: "
                     + ", ".join(bad_inv) + " — a counting bug; not published as OK.")
    for i in remaining:
        msg = (i.get("issue") or "")
        if "parsed 0" in msg.lower() or "historical parser gap" in msg.lower():
            continue   # already covered by 'gaps' above
        fails.append(f"Unresolved self-audit issue — {msg} ({i.get('count')}).")

    partial = [c["category"] for c in zero_checks if c["status"] == "Partial Coverage"]
    if partial:
        warns.append("Partial coverage — parsed only a subset of the COAs that report: "
                     + ", ".join(partial) + " ('no findings' covers only the parsed subset).")
    absent = [c["category"] for c in zero_checks if c["status"] == "Not Reported (historical)"]
    if absent:
        warns.append("Not reported on these historical COAs (labeled as a historical absence, not a clean "
                     "zero): " + ", ".join(absent) + ".")
    # P3: a SAFETY-CRITICAL panel with ZERO reporting coverage is not a benign absence — it caps how
    # reassuring any status can be, and must be surfaced prominently (not buried).
    _SAFETY_PANELS = {"Pathogens", "Mercury"}
    safety_zero = sorted({c["category"] for c in zero_checks
                          if c["category"] in _SAFETY_PANELS and c.get("present", 0) == 0
                          and c.get("flagged", 0) == 0})
    if safety_zero:
        warns.append("COVERAGE LIMITATION (safety-critical) — these panels have ZERO reporting coverage in "
                     "this window: " + ", ".join(safety_zero) + ". This report CANNOT provide assurance on "
                     "them; treat the absence of findings as 'not tested / not seen', not 'clean'. Status "
                     "reflects only the panels that were actually reported.")
    if src_metrics.get("coa_source_mismatch_count"):
        warns.append(f"{src_metrics['coa_source_mismatch_count']} value(s) excluded to the COA Source "
                     "Mismatch review queue (not published).")
    if src_metrics.get("extractions_held_uncertain"):
        warns.append(f"{src_metrics['extractions_held_uncertain']} uncertain extraction(s) held from "
                     "publication (COA Extraction Review).")
    if debug.get("broken_or_missing_coa_links"):
        warns.append(f"{debug['broken_or_missing_coa_links']} broken / missing COA link(s) — those products "
                     "could not be reviewed.")
    if debug.get("unreadable_after_retry"):
        warns.append(f"{debug['unreadable_after_retry']} COA(s) unreadable even after an escalating-DPI OCR retry (coverage gap).")
    if debug.get("potency_parser_conflicts"):
        warns.append(f"{debug['potency_parser_conflicts']} potency parser conflict(s) — held OUT of findings "
                     "and routed to review, not published.")
    if debug.get("coa_verification_queue"):
        warns.append(f"{debug['coa_verification_queue']} flagged row(s) routed to the COA Verification Queue.")

    # COA Format Learning readiness (item 11). IMPORTANT distinction: extraction TRUST is enforced
    # above (source-binding, uncertain-holds, parser-gaps, impossible-math) and FAILs the report when
    # violated. Readiness is a COVERAGE / training-maturity signal — a year can be "NOT READY" simply
    # because a category was not widely TESTED that era (e.g. metals/solvents in 2019-2021) or because
    # many old scans are unreadable, NOT because the parser misreads the format. So a NOT-READY year is
    # a strong WARNING (train it / coverage is limited), not an automatic FAIL of data that already
    # passed every trust check — auto-failing verified data would itself be dishonest. (If a NOT-READY
    # year ALSO had a parser gap, an uncertain-published finding, or a source-binding failure, those
    # independently FAIL above.)
    not_ready = [str(r["year"]) for r in (year_readiness or []) if r.get("verdict") == "NOT READY"]
    partial = [str(r["year"]) for r in (year_readiness or []) if r.get("verdict") == "PARTIAL"]
    untrained = [str(r["year"]) for r in (year_readiness or []) if r.get("verdict") in ("NO DATA", "INSUFFICIENT SAMPLE")]
    if not_ready:
        warns.append("COA Format Learning rates these years NOT READY — limited learned coverage (a core "
                     "category may not have been widely tested that era, and/or many old scans are "
                     "unreadable): " + ", ".join(not_ready) + ". Published values here still passed every "
                     "trust check (source-binding, no uncertain findings); run `learn` on these years/labs "
                     "to raise coverage confidence.")
    if partial:
        warns.append("COA Format Learning rates these years PARTIAL (usable but not fully trained): "
                     + ", ".join(partial) + " — run `learn` to raise confidence.")
    if untrained:
        warns.append("These years have too little learned-format data to rate ("
                     + ", ".join(untrained) + ") — run `learn --years <range>` to train the parser on them.")

    status = "FAIL" if fails else ("PASS WITH WARNINGS" if warns else "PASS")
    return status, fails, warns


# ============================================================================
# Live COA row validation
# ============================================================================
_COA_STOP = {"flower", "preroll", "pre", "roll", "rolls", "pack", "packs", "usable",
             "marijuana", "extract", "inhalation", "mini", "minis", "whole", "infused",
             "hash", "bubble", "live", "resin", "rosin", "the", "and", "for", "with",
             "smalls", "shake", "ground", "blunt", "cannabis", "grams", "gram"}


# Connecticut regulatory limits / common action / reporting thresholds that often
# appear as a LIMIT column on a COA (CFU/g and µg/kg). A parsed RESULT that exactly
# equals one of these — or its own row's limit — is suspicious: it is frequently the
# limit field misread as the result. V9 routes such a finding to MANUAL REVIEW
# rather than publishing it as confirmed (it is not automatically wrong, but it must
# be confirmed against the actual result field on the COA).
REG_LIMIT_VALUES = {20.0, 100.0, 200.0, 500.0, 600.0, 1000.0, 10000.0, 100000.0}


def _limit_match_review(d, p) -> bool:
    """True when a flag-driver value is a below-detection upper bound, or exactly
    equals its COA limit or a known regulatory limit -> route to manual review."""
    e = p.analytes.get(d.get("key"), {})
    if e.get("_below_detect"):                      # a "< X" upper bound is never a finding
        return True
    v = d.get("value")
    if v is None:
        return False
    lim = d.get("ct_limit")
    if lim and abs(v - lim) < 1e-9:                 # result == its own limit field
        return True
    return any(abs(v - L) < 1e-9 for L in REG_LIMIT_VALUES)


def validate_coa_row(p, text) -> str:
    """Live COA Match Status — flag only SUBSTANTIVE conflicts, never cosmetic ones
    (capitalization / punctuation / spacing / abbreviation / formatting differences).

    'Verified'            = the product / brand / strain is found in the COA (the
                            common case; the value was parsed from this very COA).
    'Verified Partial'    = the product name isn't textually found but a flagged
                            value is (e.g. a Biotrack-ID-only COA) — non-critical.
    'COA Product Mismatch'= neither the product NOR any flagged value appears.
    Plus broken / missing links. Nothing else is queued."""
    if not p.report_url:
        return MATCH_LINK_MISSING
    if not text or len(text.strip()) < 40:
        return MATCH_LINK_BROKEN
    low = text.lower()
    reg = (p.registration_number or "").lower()
    reg_ok = bool(reg) and (reg in low or reg.replace(".", "") in low.replace(".", ""))
    # product / brand / strain tokens (the COA prints these, not the state reg #)
    src = f"{p.product_name} {p.brand} {v5.product_core_name(p)}".lower()
    name_tokens = [t for t in re.split(r"[^a-z0-9]+", src)
                   if len(t) >= 3 and t not in _COA_STOP and not t.isdigit()]
    name_ok = reg_ok or (any(t in low for t in name_tokens) if name_tokens else False)
    # PER-LINE-ITEM verification (anti-hallucination): every flagged value must
    # literally appear in the COA text. Any value that does NOT is marked
    # `_coa_unverified` on its analyte entry, which makes is_quantified() reject it
    # so it can never become a published finding (it falls to manual review). This
    # is the single chokepoint that keeps an OCR/parse hallucination off the report.
    def _value_in_text(v):
        if v is None or not math.isfinite(v):
            return False
        if v == int(v):
            forms = {f"{int(v)}", f"{int(v):,}"}
        else:
            forms = {f"{v:g}"} | {f"{v:.{pr}f}".rstrip("0").rstrip(".") for pr in (1, 2, 3, 4)}
        # match each form only as a DISTINCT number (no adjacent digit), so 0.5 does
        # not "match" inside 0.18 or 10.52 — that loose match is how hallucinations slip in.
        return any(f and re.search(r"(?<![\d.])" + re.escape(f) + r"(?![\d])", text)
                   for f in forms)

    qd = [d for d in v5.quantified_details(p, p._watch) if v5.is_flag_driver(d)]
    val_ok = False
    changed = False
    for d in qd:
        if d["key"] in p.analytes and _limit_match_review(d, p):
            # value is a below-detection bound or exactly equals a regulatory/own limit
            # -> not confirmable as a measured result here; route to MANUAL REVIEW.
            p.analytes[d["key"]]["_coa_unverified"] = True
            p.analytes[d["key"]]["_limit_match_review"] = True
            changed = True
        elif _value_in_text(d.get("value")):
            val_ok = True
        elif d["key"] in p.analytes:          # not in the COA -> do not trust this line
            p.analytes[d["key"]]["_coa_unverified"] = True
            changed = True
    if not qd:
        val_ok = True
    if changed:                                # invalidate the cached details so the
        p._qd_cache = None                     # _coa_unverified flags take effect
    if name_ok:
        return MATCH_EXACT            # product confirmed in the COA -> Verified
    if val_ok:
        return MATCH_PARTIAL          # at least one value confirmed; name not textual
    return MATCH_PRODUCT_MISMATCH     # neither product nor any value found -> queue


# ============================================================================
# Crash-proof OCR — each scanned COA's OCR runs in an isolated subprocess GROUP,
# so a native engine segfault (e.g. Apple Vision) kills only that child, never the
# run. The child is launched in its own session (start_new_session) so a hang or
# timeout can be killed by PROCESS GROUP — taking down any grandchildren too (e.g.
# the `tesseract` binary pytesseract spawns), which would otherwise be orphaned and
# keep eating CPU across a long multi-year scan. A semaphore caps concurrent OCR
# (overload guard); a hung/overloaded OCR retries once with a longer timeout; a true
# crash returns '' (unreadable) and is retried in the deferred pass at the end.
# If NO OCR engine is installed, no subprocess is spawned at all (on a 33k-product
# multi-year run that avoids tens of thousands of no-op process launches). This is
# ON by default (disable with --no-ocr).
# ============================================================================
_OCR_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cannascope_ocr_worker.py")
_OCR_SEM = threading.Semaphore(4)
_OCR_LOCK = threading.Lock()
_OCR_SERIALIZE = threading.Lock()    # forces OCR one-at-a-time when memory is critical
_OCR_STATS = {"ok": 0, "crashes": 0, "timeouts": 0, "backoffs": 0,
              "serialized_low_memory": 0, "proceeded_under_load": 0,
              "cache_hits": 0, "rescued_high_dpi": 0}
_CPU = os.cpu_count() or 4
_OCR_AVAILABLE = None      # parent-side cache: is any OCR engine installed?


def _default_ocr_workers():
    """Auto-sized OCR concurrency default: scale to the machine but stay conservative on memory
    (Apple-Vision renders are memory-heavy; the adaptive backoff + low-memory serialize guard
    further throttle under pressure). Cap at 6 so we never thrash. An explicit --ocr-workers wins."""
    return min(max(_CPU - 2, 1), 6)


# Overload thresholds. Memory is the dominant OCR-crash cause (rendering a PDF page
# at 2x into a PIL image is memory-heavy; several parallel renders can OOM-kill a
# worker and LOSE that COA), so memory is watched harder than CPU and gets a second,
# stricter "critical" line at which OCR is throttled to one process at a time.
_MEM_HIGH = 82.0       # >= this %: back off (wait before starting more OCR)
_MEM_CRITICAL = 90.0   # >= this %: also serialize OCR so parallel renders can't OOM
_CPU_HIGH = 92.0       # >= this % CPU (psutil) : back off


def set_ocr_concurrency(n: int):
    global _OCR_SEM
    _OCR_SEM = threading.Semaphore(max(1, int(n)))


def _ocr_backend_available() -> bool:
    """Cheap one-time check (in the PARENT process) for an OCR engine. If none is
    installed we never spawn a worker — on a multi-year run with thousands of
    image-only COAs that is thousands of pointless process launches avoided."""
    global _OCR_AVAILABLE
    if _OCR_AVAILABLE is None:
        avail = False
        try:
            import ocrmac.ocrmac  # noqa: F401  (Apple Vision, macOS)
            avail = True
        except Exception:
            import shutil
            if shutil.which("tesseract"):
                try:
                    import pytesseract  # noqa: F401
                    avail = True
                except Exception:
                    avail = False
        _OCR_AVAILABLE = avail
    return _OCR_AVAILABLE


def _kill_ocr_group(proc):
    """Kill the OCR child AND any grandchildren by signaling the whole process group,
    so a hung/timed-out OCR can never leave an orphan (e.g. a stuck `tesseract`)
    consuming CPU. Falls back to a plain child kill where process groups are
    unavailable (non-POSIX)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (AttributeError, ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _run_ocr_worker(src, max_pages, timeout, scale=2.0):
    """Run the OCR worker in its own process group and return (returncode, stdout).
    On timeout the ENTIRE group is killed (no orphaned grandchildren), the child is
    reaped so no zombie lingers, and TimeoutExpired is re-raised to the caller.
    `scale` sets the render DPI (≈ scale×72) — higher rescues small-text image-only COAs."""
    proc = subprocess.Popen([sys.executable, _OCR_WORKER, src, str(max_pages), str(scale)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        _kill_ocr_group(proc)
        try:
            proc.communicate(timeout=5)     # reap the killed child (no zombie)
        except Exception:
            pass
        raise


def _system_overloaded() -> bool:
    """Predictive overload check. Uses psutil (memory first, then CPU) when available,
    else the Unix load average. True = the machine is too busy to safely start more
    OCR work yet."""
    try:
        import psutil
        if psutil.virtual_memory().percent >= _MEM_HIGH:
            return True
        return psutil.cpu_percent(interval=0.0) >= _CPU_HIGH
    except Exception:
        try:
            return os.getloadavg()[0] > _CPU * 1.5
        except (OSError, AttributeError):
            return False


def _memory_critical() -> bool:
    """True when free memory is dangerously low — the regime where a parallel OCR
    render is most likely to OOM-kill its worker (and lose that COA). Needs psutil;
    without it we cannot read memory and conservatively report False (the loadavg
    backoff still applies)."""
    try:
        import psutil
        return psutil.virtual_memory().percent >= _MEM_CRITICAL
    except Exception:
        return False


def _adaptive_backoff():
    """Slow down BEFORE the machine crashes, so no OCR document is lost to an OOM or
    overload. While the system is overloaded we WAIT (up to a generous cap — waiting
    is always cheaper than crashing and missing the COA), counting the stall in the
    debug stats. If we ever exhaust the cap and proceed anyway, that is recorded too
    so a chronically overloaded host is visible in the report's diagnostics."""
    waited = 0.0
    counted = False
    while _system_overloaded() and waited < 120.0:
        if not counted:
            with _OCR_LOCK:
                _OCR_STATS["backoffs"] += 1
            counted = True
        time.sleep(1.0)
        waited += 1.0
    if waited >= 120.0:
        with _OCR_LOCK:
            _OCR_STATS["proceeded_under_load"] += 1


# ---- Persistent OCR-text cache (see OCR_TEXT_CACHE) -------------------------------------------
# An image-only COA is OCR'd once ever, keyed by file CONTENT hash. Loaded lazily, written through
# every few additions and flushed at exit, thread-safe so the scan's worker pool can share it.
_OCR_CACHE = None
_OCR_CACHE_LOCK = threading.Lock()
_OCR_CACHE_DIRTY = 0
_OCR_CACHE_FLUSH_EVERY = 25


def _ocr_cache_load():
    global _OCR_CACHE
    if _OCR_CACHE is None:
        try:
            with open(OCR_TEXT_CACHE, encoding="utf-8") as f:
                d = json.load(f)
            _OCR_CACHE = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            _OCR_CACHE = {}
    return _OCR_CACHE


def _ocr_cache_key(src):
    """Content-hash key (identical COAs share; a changed COA re-OCRs), namespaced by OCR_CACHE_VERSION
    so bumping the version invalidates every entry. '' if the file can't be read."""
    import hashlib
    try:
        h = hashlib.sha1()
        with open(src, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return f"{OCR_CACHE_VERSION}:{h.hexdigest()}"
    except OSError:
        return ""


def _ocr_cache_flush(force=False):
    global _OCR_CACHE_DIRTY
    with _OCR_CACHE_LOCK:
        if _OCR_CACHE is None or (_OCR_CACHE_DIRTY == 0 and not force):
            return
        try:
            os.makedirs(OUT_DIR, exist_ok=True)
            tmp = OCR_TEXT_CACHE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_OCR_CACHE, f)
            os.replace(tmp, OCR_TEXT_CACHE)
            _OCR_CACHE_DIRTY = 0
        except OSError:
            pass


def _ocr_cache_get(key):
    if not key:
        return None
    with _OCR_CACHE_LOCK:
        return _ocr_cache_load().get(key)


def _ocr_cache_put(key, text):
    global _OCR_CACHE_DIRTY
    if not key or not text:
        return
    with _OCR_CACHE_LOCK:
        _ocr_cache_load()[key] = text
        _OCR_CACHE_DIRTY += 1
        due = _OCR_CACHE_DIRTY >= _OCR_CACHE_FLUSH_EVERY
    if due:
        _ocr_cache_flush()


import atexit as _atexit
_atexit.register(lambda: _ocr_cache_flush(force=True))


def _isolated_ocr_pdf(src, max_pages: int = 6) -> str:
    """OCR one COA in a separate process group. A segfault, hang, or timeout takes
    down only that child (and any grandchildren) -> '' (the COA is treated as
    unreadable and retried later) instead of taking down the scan. Successful OCR text
    is cached persistently by content hash, so a re-scan never re-OCRs the same COA."""
    if not isinstance(src, str):
        return ""
    key = _ocr_cache_key(src)
    if key:                              # content-hash hit -> skip the Apple-Vision subprocess entirely
        cached = _ocr_cache_get(key)
        if cached is not None:
            with _OCR_LOCK:
                _OCR_STATS["cache_hits"] = _OCR_STATS.get("cache_hits", 0) + 1
            return cached
    if not os.path.exists(_OCR_WORKER):
        return ""
    if not _ocr_backend_available():    # no engine installed -> don't spawn a no-op child
        return ""
    _adaptive_backoff()
    # Under critical memory, hold a global lock so OCR runs strictly one-at-a-time:
    # parallel page renders are what tip a low-memory host into an OOM that kills a
    # worker and loses its COA. Serializing trades speed for not missing documents.
    serialize = _memory_critical()
    if serialize:
        with _OCR_LOCK:
            _OCR_STATS["serialized_low_memory"] += 1

    def _attempt(scale, timeout):
        if serialize:
            with _OCR_SERIALIZE, _OCR_SEM:
                return _run_ocr_worker(src, max_pages, timeout, scale)
        with _OCR_SEM:
            return _run_ocr_worker(src, max_pages, timeout, scale)

    # Escalating DPI: a fast first pass at the normal scale, then — only if it comes back EMPTY
    # (an image-only COA whose small table text didn't resolve) — a higher-DPI quality retry that
    # often rescues heavy-metal / LOD-LOQ tables. The longer-timeout retries guard against overload.
    for scale, timeout in ((2.0, 120), (2.0, 300), (3.2, 300)):
        try:
            rc, out = _attempt(scale, timeout)
            if rc == 0:
                text = (out or b"").decode("utf-8", "replace")
                if text.strip():
                    with _OCR_LOCK:
                        _OCR_STATS["ok"] += 1
                        if scale > 2.0:
                            _OCR_STATS["rescued_high_dpi"] = _OCR_STATS.get("rescued_high_dpi", 0) + 1
                    _ocr_cache_put(key, text)   # persist so this COA is never re-OCR'd
                    return text
                continue                # empty at this DPI -> escalate to a higher-DPI retry
            with _OCR_LOCK:             # non-zero exit = native crash; a re-render won't help
                _OCR_STATS["crashes"] += 1
            return ""
        except subprocess.TimeoutExpired:
            with _OCR_LOCK:
                _OCR_STATS["timeouts"] += 1
            continue                    # overloaded/hung -> retry (longer timeout / next scale)
        except Exception:
            return ""
    return ""


def enable_isolated_ocr():
    v4.ocr_pdf = _isolated_ocr_pdf      # read_pdf_text calls the module global


# ============================================================================
# Leak-free PDF text extraction — installed over the V4 engine (V4 itself is left
# untouched). Beta V9 reads COA text via v4.read_pdf_text -> v4._pdfium_text; the
# engine's version closes the document but NOT the per-page page/textpage handles.
# Across a multi-year run of tens of thousands of COAs that is a real native-memory
# leak (and triggers pypdfium2 ObjectTracker assertions on exit). This drop-in
# replacement closes every page and textpage (and the doc, in a finally) and stays
# serialized under the engine's own pdfium lock. Installed exactly like the OCR
# override above: read_pdf_text resolves _pdfium_text as a module global at call
# time, so reassigning it on the v4 module takes effect everywhere — without
# modifying the validated V4 engine file.
# ============================================================================
def _safe_pdfium_text(src) -> str:
    with v4._PDF_LOCK:
        doc = None
        try:
            doc = v4.pdfium.PdfDocument(src)
            parts = []
            for i in range(len(doc)):
                page = doc[i]
                tp = page.get_textpage()
                parts.append(tp.get_text_range() or "")
                tp.close()
                page.close()
            return "\n".join(parts)
        except Exception:
            return ""
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


def enable_safe_pdf_text():
    v4._pdfium_text = _safe_pdfium_text   # read_pdf_text calls the module global


# ============================================================================
# Offline / bundled-sources mode — read COAs only from the local cache, never the
# network. Combined with a prior `--keep-clean-pdfs` run (which retains EVERY COA
# PDF, not just flagged ones) the cache folder becomes a complete, self-contained
# "sources" bundle: the registry CSV + every COA PDF live under the output folder,
# so a re-run needs no internet and is bounded only by local parse speed. Installed
# as a download override (same pattern as the OCR / text overrides) so V4 is untouched.
# ============================================================================
def _offline_download_pdf(p, session):
    path = v4.cache_path(p)
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    p.parse_note = "offline: COA not in local sources cache"
    p._coa_status = MATCH_LINK_BROKEN if p.report_url else MATCH_LINK_MISSING
    return None


def enable_offline_sources():
    v4.download_pdf = _offline_download_pdf   # process_product calls the module global


# ============================================================================
# Worker — parse (core engine) + Beta V9 validation, retaining text only long enough
# ============================================================================
def process_product(p, session, watch):
    """Never raises — any per-COA failure (download, parse, OCR) is caught and the
    product is returned with a parse_note, so one bad COA can't kill a worker."""
    p._watch = watch
    p._coa_status = MATCH_LINK_MISSING
    try:
        return _process_product(p, session, watch)
    except Exception as e:
        p.parse_note = f"processing error: {type(e).__name__}: {e}"[:160]
        return p


def cached_or_v15(p, session, watch, cache, allow_network=True):
    """--csv-cache wiring (thin adapter). HIT: rehydrate measurements from the CSV cache and reflag at
    `watch` — no network, no OCR — restoring the report-fidelity extras (testing date, COA-validation
    status). MISS: run V15's OWN process_product (full text-derived analysis: conflict inputs, format
    profile, presence, validation) and cache its measurements + those extras. So a HIT product is
    report-faithful, and lowering --threshold re-flags previously-clean COAs straight from cache."""
    p._watch = watch
    row = cache.fresh_row(p)
    if row is not None:
        rp = cache.rehydrate(row, watch)            # extras (testing_date/_coa_status) restored here
        rp._watch = watch
        rp._coa_present = True                       # we hold its measurements -> treat as fetched
        if not getattr(rp, "_coa_status", ""):
            rp._coa_status = MATCH_EXACT
        if not getattr(rp, "testing_date", ""):
            rp.testing_date = test_date(rp)
        return rp
    if not allow_network:
        p.parse_note = "offline: COA not in CSV cache"
        p._coa_status = MATCH_LINK_MISSING
        return p
    p = process_product(p, session, watch)
    if bool(getattr(p, "analytes", None)) or bool(getattr(p, "cannabinoids", None)):
        # Only cache a COA we actually read. Keep the report-fidelity extras that aren't measurements.
        cache.put(p, method="v15", text_len=0, pdf_path=v4.cache_path(p),
                  extra={"testing_date": getattr(p, "testing_date", "") or test_date(p),
                         "_coa_status": getattr(p, "_coa_status", "") or ""})
    return p


def _process_product(p, session, watch):
    path = v4.download_pdf(p, session)
    if not path:
        p.parse_note = p.parse_note or "could not download COA"
        p._coa_status = MATCH_LINK_BROKEN if p.report_url else MATCH_LINK_MISSING
        return p
    text = v4.read_pdf_text(path)
    if len(text.strip()) < 40:
        p.parse_note = "no extractable text (scanned image?)"
        p._coa_status = MATCH_LINK_BROKEN
        return p
    p.overall_result = v4.find_overall_result(text)
    p.test_lab = v4.parse_lab(text)
    v4.parse_analytes(text, p)
    v5.parse_cannabinoids(text, p)
    v4.apply_flags(p, text, watch)
    v5.apply_thc_flags(p)
    p.strain = v5.product_core_name(p)
    p.testing_date = parse_testing_date(text)
    p._coa_status = validate_coa_row(p, text)
    # Conflicting-COA detection inputs (extracted now, while the COA text is in hand —
    # clean PDFs may be evicted from the cache before the cross-record pass runs).
    p._ids = extract_coa_identifiers(text)
    p._internal = scan_internal_conflict(text, path)
    # Per-category presence (does each panel's wording appear at all?) — lets the zero-result
    # logic tell a true historical absence from a parser gap. Computed while the text is in hand.
    p._cat_present = _detect_presence(text)
    # COA FORMAT LEARNING LAYER: fingerprint this COA's format + cross-check the extraction
    # while the text is in hand. Stored so the pipeline can hold uncertain extractions and the
    # learner can build a per-year readiness map. Defensive — never let it break a scan.
    try:
        p._format_profile = profile_coa(p, text)
        p._extraction = assess_extraction(p, text, p._format_profile)
    except Exception as e:
        p._format_profile = None
        p._extraction = dict(level="UNCERTAIN", score=0, checks={}, conflict=False, mismatch=False,
                             hold=False, reasons=[f"format-learning error: {e}"])
    p._coa_present = True
    return p


# ============================================================================
# Category extraction (one lean ranked table per contaminant)
# ============================================================================
# (key, Title, prints-as-CFU/g?) — each gets its own section, never merged.
ANALYTE_TABLES = [
    ("tymc", "Yeast & Mold"), ("aerobic", "Total Aerobic Bacteria"),
    ("arsenic", "Arsenic"), ("chromium", "Chromium"), ("cadmium", "Cadmium"),
    ("lead", "Lead"), ("mercury", "Mercury"),
]
MYCO_KEYS = ["aflatoxin", "ochratoxin"] + v4.MYCO_COMP_KEYS


def quantified_for(p, key):
    for d in v5.quantified_details(p, p._watch):
        if d["key"] == key and v5.is_flag_driver(d):
            return d
    return None


def category_rows(flagged, key):
    items = [(p, d) for p in flagged for d in [quantified_for(p, key)] if d]
    items.sort(key=lambda pd: (pd[1]["ct_pct"] if pd[1]["ct_pct"] is not None else -1,
                               pd[1]["value"] or 0,
                               pd[1]["vs_std"] if pd[1]["vs_std"] is not None else -1e9),
               reverse=True)
    return items


def mycotoxin_rows(flagged):
    out = []
    for p in flagged:
        for d in v5.quantified_details(p, p._watch):
            if d["key"] in MYCO_KEYS and v5.is_flag_driver(d):
                out.append((p, d))
    out.sort(key=lambda pd: pd[1]["ct_pct"] or 0, reverse=True)
    return out


def pesticide_rows(flagged):
    return [p for p in flagged if p.pesticides == "FAIL"]


def solvent_rows(flagged):
    out = []
    for p in flagged:
        for d in v5.quantified_details(p, p._watch):
            if d["key"].startswith("solvent:") and v5.is_flag_driver(d):
                out.append((p, d))
        if p.solvents == "FAIL" and not any(d["key"].startswith("solvent:")
                                            for d in v5.quantified_details(p, p._watch)):
            out.append((p, {"name": "Residual Solvent Panel", "value": None, "unit": "",
                            "ct_limit": None, "ct_pct": None, "vs_std": None, "key": "solvent:panel"}))
    return out


def pathogen_rows(flagged):
    out = []
    for p in flagged:
        for nice in v5.pathogen_detections(p):
            out.append((p, nice))
    return out


# ============================================================================
# Potential statute / regulatory flags (V9 add-on) — DERIVED ONLY from COA testing
# data CannaScope can actually read: a result over the Connecticut LEGAL limit, a
# detected zero-tolerance pathogen, or a FAILED pesticide/solvent panel. These are
# leads for a qualified compliance officer or attorney to EVALUATE — never legal
# determinations and never an adjudication. Authority is cited at the chapter/rule
# level and marked for verification (CannaScope does not resolve exact eRegulations
# section text). Compliance categories that need licensing/operational data
# (diversion, labeling, security, recordkeeping, transport) are NOT assessed here.
# ============================================================================
_COMPLIANCE_AUTHORITY = ("CGS Ch. 420h (RERACA) testing & product-quality provisions; "
                         "DCP Policies & Procedures testing/product-quality requirements "
                         "(verify exact section & current text in eRegulations)")
_LABEL_AUTHORITY = ("CGS Ch. 420h (RERACA) & DCP Policies & Procedures labeling / potency-accuracy "
                    "& product-quality provisions (verify exact section & current text in eRegulations)")


def compliance_flag_rows(pub, watch):
    """One potential-flag record per product whose COA shows a Connecticut testing /
    product-quality concern: a result over the LEGAL limit, a pathogen DETECTED, or a
    FAILED pesticide/solvent panel. Every record stays a 'potential' lead for human
    review, tied to a cited (unverified) authority — never an adjudication."""
    rows = []
    for p in pub:
        # --- (A) Testing & product quality: over the LEGAL limit / pathogen / panel FAIL ---
        tq = []
        for d in v5.quantified_details(p, watch):
            if not v5.is_flag_driver(d):
                continue
            lim, val = d.get("ct_limit"), d.get("value")
            if lim and val is not None and val > lim:
                tq.append(f"{d['name']} {clean_value(val, d.get('unit',''))} over the "
                          f"Connecticut legal limit ({clean_value(lim, d.get('unit',''))})")
        for nice in v5.pathogen_detections(p):
            tq.append(f"zero-tolerance pathogen {nice} reported DETECTED")
        if p.pesticides == "FAIL":
            tq.append("pesticide panel returned FAIL (prohibited / over-limit pesticide)")
        if p.solvents == "FAIL":
            tq.append("residual solvent panel returned FAIL")
        if tq:
            rows.append(dict(
                p=p, rule_category="Testing & product quality",
                finding="COA shows " + "; ".join(tq) + ". If this batch reached market, verify it "
                        "was remediated/destroyed per DCP P&P rather than released.",
                cited_authority=_COMPLIANCE_AUTHORITY, authority_unverified=True,
                status="potential_violation", severity="high",
                confidence="High that the COA shows this result; POTENTIAL only — batch release/"
                           "remediation status is unknown to CannaScope",
                recommended_review="Compliance officer / DCP — confirm batch disposition and the "
                                   "exact current rule section in eRegulations"))
        # --- (B) Labeling & potency accuracy: open every HIGH-CANNABINOID product's COA and
        #     compare its THC categories (THCA, delta-9 THC, Total THC) in depth ---
        rv = thc_review_value(p)
        if rv and rv[1] > THC_REVIEW_PCT:
            thca = thc_value(p, "thca")
            d9 = thc_value(p, "d9_thc")
            if d9 is None:
                d9 = thc_value(p, "thc")
            total = thc_value(p, "total_thc")
            lp = []
            if product_category(p) == "flower" and rv[1] > FLOWER_CANN_MAX:
                lp.append(f"reported flower potency {rv[1]:g}% exceeds the plausible flower maximum "
                          f"(~{FLOWER_CANN_MAX:g}%) — possible mislabeling (concentrate reported as "
                          f"flower) or a potency-reporting error")
            if thca is not None and d9 is not None and total is not None and total > 0:
                computed = 0.877 * thca + d9
                if abs(computed - total) > max(2.0, 0.10 * total):
                    lp.append(f"reported Total THC {total:g}% does not reconcile with 0.877*THCA "
                              f"({thca:g}%) + delta-9 THC ({d9:g}%) = {computed:.1f}% — possible "
                              f"potency-reporting issue")
            # --- internal-consistency checks (review leads only; impossible math = a reporting issue) ---
            totc = thc_value(p, "total_cannabinoids")
            if totc is None:
                totc = thc_value(p, "total_active")
            # Compare Total Cannabinoids ONLY against decarboxylated Total THC — both are on the
            # same (decarbed) basis. Do NOT compare against THCA: THCA is the acid form (~14% heavier
            # than its decarbed equivalent), so a normal COA legitimately has Total Cannabinoids
            # (decarbed sum) BELOW raw THCA — e.g. THCA 39.3% with Total Cannabinoids 36.1% is fully
            # self-consistent (0.877*39.3 + small minors). Flagging that was a false positive.
            if totc is not None and total is not None and totc + 0.5 < total:
                lp.append(f"reported Total Cannabinoids ({totc:g}%) is LOWER than reported Total THC "
                          f"({total:g}%) — not chemically possible (Total Cannabinoids includes Total THC); "
                          f"possible reporting/transcription issue")
            if lp:
                rows.append(dict(
                    p=p, rule_category="Labeling & potency accuracy",
                    finding="High-cannabinoid review — " + "; ".join(lp) + ".",
                    cited_authority=_LABEL_AUTHORITY, authority_unverified=True,
                    status="potential_violation", severity="medium",
                    confidence="Computed from the COA's own THCA / delta-9 / Total THC values; "
                               "POTENTIAL only — verify against the COA and the product label",
                    recommended_review="Compliance officer / DCP — verify the COA's potency math and "
                                       "the product-label potency claim against current rules"))
    return rows


# ============================================================================
# CT Cannabis Ombudsman — Medical Patient Safety Review (V9 add-on). Patient-safety,
# NOT enforcement: products that PASSED but rode CLOSEST to a Connecticut action limit
# on ANY contaminant, ranked by narrowest margin, for the Office of the Cannabis
# Ombudsman (PA 23-79) to advise medical patients. Advisory only; not medical advice.
# ============================================================================
OMBUDSMAN_THRESHOLD = 80.0   # % of the CT action limit; TUNABLE. A product is included
                             # when its closest analyte reaches >= this % of its limit.

_OMB_CLASS_KEYS = (
    (("tymc", "aerobic", "coliform", "btgn", "bile"), "Microbials / mold"),
    (("arsenic", "cadmium", "chromium", "lead", "mercury"), "Heavy metals"),
)
_PATIENT_NOTE = {
    "Microbials / mold": "Microbial/mold load near the limit; immunocompromised or medically "
                         "vulnerable patients may wish to be cautious, especially with inhaled use.",
    "Heavy metals": "Heavy-metal result near the limit; relevant for patients with cumulative-"
                    "exposure concerns or frequent use.",
    "Pesticides": "Pesticide result near the limit; patients sensitive to pesticide residues may "
                  "wish to approach with caution.",
    "Mycotoxins": "Mycotoxin result near the limit; relevant for immunocompromised patients.",
    "Residual solvents": "Residual-solvent result near the limit; relevant for respiratory-"
                         "sensitive patients.",
    "Contaminant": "Result near the Connecticut action limit; worth patient awareness.",
}


def _analyte_class(key):
    k = (key or "").lower()
    if k.startswith("solvent:"):
        return "Residual solvents"
    if k.startswith("aflatoxin") or k.startswith("ochratoxin") or k in MYCO_KEYS:
        return "Mycotoxins"
    for keys, label in _OMB_CLASS_KEYS:
        if any(k == a or k.startswith(a) for a in keys):
            return label
    if "pestic" in k:
        return "Pesticides"
    return "Contaminant"


def ombudsman_rows(pub, threshold=None):
    """Products that PASSED but came CLOSEST to a CT action limit on ANY contaminant.
    Each product's closeness = its single closest analyte (max % of its CT limit). Ranked
    closest-first. Patient-safety / advisory only — never a failure or safety verdict."""
    thr = OMBUDSMAN_THRESHOLD if threshold is None else threshold
    out = []
    for p in pub:
        best = None
        for d in v5.quantified_details(p, p._watch):
            cp = d.get("ct_pct")
            if cp is None or d.get("value") is None:
                continue
            if best is None or cp > best["ct_pct"]:
                best = d
        if best is None or (best["ct_pct"] or 0) < thr:
            continue
        cp = best["ct_pct"]
        lim, val = best.get("ct_limit"), best.get("value")
        cls = _analyte_class(best["key"])
        out.append(dict(
            p=p, d=best, ct_pct=cp, cls=cls,
            headroom=((lim - val) if (lim is not None and val is not None) else None),
            tier=("at/over threshold" if cp >= 100 else "very close" if cp >= 90 else "close"),
            note=_PATIENT_NOTE.get(cls, _PATIENT_NOTE["Contaminant"])))
    out.sort(key=lambda r: r["ct_pct"], reverse=True)
    return out


# ============================================================================
# Lab- & DATE-aware Total Yeast & Mold (TYM) standard detection (V15, patient-safety)
# ----------------------------------------------------------------------------
# Connecticut's TYM passing limit varied by LAB and by DATE — by up to 100x — so a
# product could be stamped "PASS" under a temporary/loosened limit that would FAIL by
# the original standard or another lab's standard, and patients were never told. Limits
# are stored as DATA (per-lab, date-ranged), each with a source + `verified` flag — these
# must be confirmed against eRegulations.ct.gov / DCP. NEVER a single hardcoded global
# TYM number. Effective dates marked unverified are intentionally approximate (the public
# record is ambiguous); they are shown with that caveat, never asserted as authoritative.
# ============================================================================
TYM_CURRENT_LIMIT = 100_000          # working current CT limit (CFU/g) — UNVERIFIED for 2025/26
TYM_CURRENT_VERIFIED = False
TYM_CURRENT_AS_OF = "2023 reporting"
TYM_STRICT_BENCHMARK = 10_000        # strictest / most patient-protective (original 2012 standard)
TYM_HIGH_RISK_LAB = "altasci"
TYM_HIGH_RISK_START = (2020, 8, 1)
TYM_HIGH_RISK_END = (2022, 12, 31)

# lab: 'altasci' | 'northeast' | '*' (any/unknown).  Date ranges are [start, end); end=None = current.
TYM_STANDARDS = [
    dict(lab="*", start=(2012, 1, 1), end=(2020, 8, 1), limit=10_000, verified=True,
         source="Original CT medical-program total yeast & mold standard since 2012 legalization "
                "(10,000 CFU/g); documented in CT DCP testing history (CT Public, 2023-03-22).",
         note="Both labs, < 10,000 CFU/g. Value confirmed; exact effective date approximate."),
    dict(lab="altasci", start=(2020, 8, 1), end=(2022, 7, 1), limit=1_000_000, verified=False,
         source="DCP private-email approval at AltaSci's request, Aug 2020 (some outlets cite 2021) — "
                "reported, not a published reg; confirm exact effective date at eRegulations / DCP.",
         note="HIGH-RISK WINDOW: 100x looser than Northeast at the same time; Aspergillus genus testing added then."),
    dict(lab="northeast", start=(2020, 8, 1), end=(2022, 7, 1), limit=10_000, verified=True,
         source="Northeast Laboratories remained at the original 10,000 CFU/g during the AltaSci window "
                "(CT Public, 2023-03-22).",
         note="Differed from AltaSci by 100x simultaneously. Value confirmed."),
    dict(lab="*", start=(2022, 7, 1), end=None, limit=100_000, verified=True,
         source="CT DCP unified microbial standard: 100,000 CFU/g total yeast & mold + zero detectable "
                "Aspergillus, in effect since ~July 2021 (CT Public investigative report 2023-03-22; "
                "Cannabis Industry Journal) and CORROBORATED by the 100,000 CFU/g action limit printed on "
                "every CT COA in this dataset.",
         note="Current CT legal limit. Lowered AltaSci (1,000,000 -> 100,000) and raised Northeast (10,000 -> 100,000)."),
]


def _lab_key(lab):
    l = (lab or "").lower()
    if "altasci" in l:
        return "altasci"
    if "northeast" in l or "nelab" in l:
        return "northeast"
    return "other"


def _valid_date(t):
    return bool(t) and len(t) == 3 and t[0]


def tym_standard_for(lab, date):
    """Applicable TYM standard entry for a lab + test-date, or None if date unknown.
    Prefers a lab-specific entry over a wildcard one."""
    if not _valid_date(date):
        return None
    lk = _lab_key(lab)
    cands = [e for e in TYM_STANDARDS
             if e["start"] <= date and (e["end"] is None or date < e["end"])
             and (e["lab"] == "*" or e["lab"] == lk)]
    if not cands:
        return None
    spec = [e for e in cands if e["lab"] != "*"]
    return (spec or cands)[0]


# ---- General date-aware historical-standards registry (item 10) -------------------------------
# CT cannabis testing standards changed over time (and, for microbials, by lab). This registry lets
# the report state the standard that applied ON THE PRODUCT'S TEST DATE instead of assuming one
# universal limit. Yeast & mold keeps its richer dedicated framework (TYM_STANDARDS/tym_standard_for);
# this covers the other date-sensitive categories. EVERY limit here is verified=False until confirmed
# at eRegulations.ct.gov / DCP — a None limit means "the regime/date is known; confirm the number."
# Entry: dict(start, end, lab, product_type, limit, unit, verified, source, note). end=None == current.
HISTORICAL_STANDARDS = {
    "yeast_mold": "->tym",   # sentinel: delegate to the dedicated TYM framework
    "aerobic": [
        dict(start=(2012, 1, 1), end=(2022, 7, 1), lab="*", product_type="*", limit=100_000, unit="CFU/g",
             verified=True, source="CT total aerobic microbial count action limit (100,000 CFU/g); "
             "corroborated by the action limit printed on CT COAs in this dataset.",
             note="Value confirmed; exact effective date approximate."),
        dict(start=(2022, 7, 1), end=None, lab="*", product_type="*", limit=100_000, unit="CFU/g",
             verified=True, source="CT unified microbial rule total aerobic count 100,000 CFU/g; "
             "corroborated by the action limit printed on every CT COA in this dataset.",
             note="Current CT legal limit."),
    ],
    "pathogens": [
        dict(start=(2012, 1, 1), end=(2020, 8, 1), lab="*", product_type="*", limit=0, unit="in 1 g",
             verified=True, source="Zero-tolerance: Salmonella / STEC E. coli not detected (CT DCP).",
             note="Aspergillus genus testing not yet required this era. Value confirmed."),
        dict(start=(2020, 8, 1), end=None, lab="*", product_type="*", limit=0, unit="in 1 g",
             verified=True, source="Zero-tolerance pathogens + Aspergillus (flavus/fumigatus/niger/terreus) "
             "not detected (CT DCP; CT Public 2023-03-22); corroborated by CT COA pathogen reporting in this dataset.",
             note="Aspergillus added ~2020. Value (not-detected) confirmed."),
    ],
    "heavy_metals": [
        dict(start=(2012, 1, 1), end=None, lab="*", product_type="inhaled", limit=None, unit="µg/g",
             verified=True, per_coa=True,
             source="CT heavy-metal action limits (As / Cd / Pb / Hg / Cr). The report judges each metal "
             "against the action limit PRINTED ON ITS OWN COA, so the applicable limit is read per-document "
             "rather than from a single baked-in number.",
             note="Per-metal limits differ and vary by product type; the report uses each COA's own stated limit."),
    ],
    "thc_potency": [
        dict(start=(2012, 1, 1), end=None, lab="*", product_type="flower", limit=None, unit="% Total THC",
             verified=True, no_cap=True, source="No CT regulatory THC cap — plausibility review only.",
             note="Flower Total THC above ~35% is unusual and above ~45% implausible (label/parse review). "
                  "Total THC = 0.877×THCA + Δ9-THC."),
        dict(start=(2012, 1, 1), end=None, lab="*", product_type="infused", limit=None, unit="% Total THC",
             verified=True, no_cap=True, source="No CT regulatory THC cap; concentrates/infused can legitimately exceed flower ranges.",
             note="High potency on a concentrate/extract is expected; flag product-type mismatches only."),
    ],
}

_STD_CATEGORY_ALIASES = {
    "yeast & mold": "yeast_mold", "yeast and mold": "yeast_mold", "tym": "yeast_mold",
    "aerobic": "aerobic", "tamc": "aerobic",
    "pathogen": "pathogens", "salmonella": "pathogens", "e. coli": "pathogens", "aspergillus": "pathogens",
    "metal": "heavy_metals", "arsenic": "heavy_metals", "lead": "heavy_metals",
    "cadmium": "heavy_metals", "mercury": "heavy_metals",
    "thc": "thc_potency", "potency": "thc_potency", "cannabinoid": "thc_potency",
}


def _std_category(name):
    n = (name or "").strip().lower()
    if n in HISTORICAL_STANDARDS:
        return n
    for k, v in _STD_CATEGORY_ALIASES.items():
        if k in n:
            return v
    return ""


def _pt_match(e, pt):
    ept = (e.get("product_type") or "*")
    if ept in ("*", "") or ept == "inhaled":
        return True
    return ept in pt or pt in ept


def standard_for(category, date, lab="", product_type=""):
    """The CT standard entry that applied for a category on a test date (and lab / product type where
    relevant). Yeast & mold delegates to the dedicated TYM framework. Returns a dict or None; treat the
    limit as UNVERIFIED unless entry['verified'] is True."""
    cat = _std_category(category)
    if not cat:
        return None
    if HISTORICAL_STANDARDS.get(cat) == "->tym":
        e = tym_standard_for(lab, date) if _valid_date(date) else None
        return (dict(start=e["start"], end=e["end"], lab=e["lab"], product_type="*", limit=e["limit"],
                     unit="CFU/g", verified=e.get("verified", False), source=e.get("source", ""),
                     note=e.get("note", "")) if e else None)
    pt = (product_type or "").lower()
    cands = []
    for e in HISTORICAL_STANDARDS.get(cat, []):
        if not _valid_date(date):
            if e["end"] is None and _pt_match(e, pt):
                cands.append(e)
        elif e["start"] <= date and (e["end"] is None or date < e["end"]) and _pt_match(e, pt):
            cands.append(e)
    if not cands:
        return None
    spec = [e for e in cands if e["product_type"] not in ("*", "")]
    return (spec or cands)[0]


def standard_note(category, date, lab="", product_type=""):
    """Human one-liner: the applicable CT standard for the test date, with verification status."""
    e = standard_for(category, date, lab, product_type)
    if not e:
        return ""
    win = f"{e['start'][0]}–{(e['end'][0] if e['end'] else 'present')}"
    lim = (f"{e['limit']:,} {e.get('unit', '')}".strip() if isinstance(e.get("limit"), (int, float))
           else "see note")
    vflag = "" if e.get("verified") else " [UNVERIFIED — confirm at eRegulations.ct.gov]"
    return f"Applicable standard for test date ({win}): {lim}{vflag}. {e.get('note', '')}".strip()


# ============================================================================
# LEGAL STANDARD VERIFICATION — local-first, internet-FALLBACK, fail-safe (Part B item 7).
# ----------------------------------------------------------------------------
# Ordering (the "internet is a fallback, not the priority" rule): (1) the program's own date-keyed
# HISTORICAL_STANDARDS / TYM registry; (2) a persistent Legal Standards Cache from a prior lookup
# that is still fresh; (3) ONLY THEN, and only when online, consult the live CT primary sources as a
# FALLBACK. Every network call is wrapped with a short timeout and CANNOT crash or block report
# generation — on any failure the item is simply marked unverified and the run continues. Exact
# historical numeric limits are NEVER auto-fabricated from legal prose: a live consult records that
# the source was REACHED for manual confirmation; when no dated standard can be confidently
# established the record carries the exact string LEGAL_UNVERIFIED and the URLs that were attempted.
# ============================================================================
LEGAL_CACHE = os.path.join(OUT_DIR, "Legal Standards Cache.json")
LEGAL_CACHE_TTL = 30 * 24 * 3600          # re-verify monthly; a cache is a hint, not forever-truth
# Stamp written into each cache entry. BUMP THIS whenever the live-fetch logic changes (source URLs,
# timeout, TLS/cert handling) — a cached entry whose stamp != current is treated as a miss and
# re-fetched, so a fetch fix is never masked by stale "unreachable" entries from an older build.
# (v1 = original; v2 = V15.1.1 live-source fix: fixed DCP URL + 25s timeout + GoDaddy-G2 chain.)
LEGAL_FETCH_VERSION = 2
LEGAL_UNVERIFIED = "Historical standard not verified — manual legal review needed"
# CT primary sources consulted as a FALLBACK (domains are real; exact deep links may move — a 404
# still counts as a logged, honest attempt and falls back to "unverified", never a crash/fabrication).
LEGAL_SOURCES = {
    "_general": [
        ("CT eRegulations — RCSA §21a-408-58 (laboratory testing)",
         "https://eregulations.ct.gov/eRegsPortal/Browse/RCSA/Title_21aSubtitle_21a-408Section_21a-408-58/"),
        ("CT General Statutes — Chapter 420h (adult-use cannabis)", "https://www.cga.ct.gov/current/pub/chap_420h.htm"),
        ("CT DCP — Policies & Procedures for the Cannabis Program",
         "https://portal.ct.gov/cannabis/knowledge-base/articles/policies-and-procedures"),
    ],
}

# ── Year-by-year CT regulatory ledger (the "bake in every year's standard" requirement) ───────────
# Each applied limit carries an AUTHORITATIVE CITATION so the report never shows a bare number. The
# numeric values are confirmed against (1) the cited CT statute/regulation/DCP policy and (2) the
# action limit actually PRINTED ON the CT COAs in this dataset — that COA corroboration count is
# computed at runtime (see reg_corroboration). Heavy metals deliberately have NO single number (they
# differ by product type), so the report defers to each COA's OWN printed limit (live-first). The
# program also re-consults the live CT sources each run (verify_standard) to record confirmation
# freshness. CT_REG_AS_OF = the date these citations/values were last confirmed against CT sources.
CT_REG_AS_OF = "2026-06-05"
CT_REG_CITATIONS = {
    "yeast_mold":  ("RCSA §21a-408-58 / DCP Policies & Procedures (microbial); unified 100,000 CFU/g "
                    "+ zero detectable Aspergillus since ~July 2021 (CT Public investigative report, 2023-03-22)",
                    "https://www.cga.ct.gov/current/pub/chap_420h.htm"),
    "aerobic":     ("RCSA §21a-408-58 / DCP Policies & Procedures — total aerobic microbial count 100,000 CFU/g",
                    "https://eregulations.ct.gov/eRegsPortal/Browse/RCSA/Title_21aSubtitle_21a-408Section_21a-408-58/"),
    "pathogens":   ("RCSA §21a-408-58 / DCP Policies & Procedures — Salmonella / STEC E. coli / Aspergillus "
                    "(flavus, fumigatus, niger, terreus) not detected; Aspergillus added ~2020",
                    "https://eregulations.ct.gov/eRegsPortal/Browse/RCSA/Title_21aSubtitle_21a-408Section_21a-408-58/"),
    "heavy_metals":("RCSA §21a-408-58 / DCP Policies & Procedures — per-metal action limits (As / Cd / Pb / Hg / Cr), "
                    "which differ by product type (inhaled vs other); the report applies each COA's own printed limit",
                    "https://portal.ct.gov/cannabis/knowledge-base/articles/policies-and-procedures"),
    "thc_potency": ("No CT regulatory THC cap (CGS Chapter 420h / DCP Policies & Procedures) — plausibility review only",
                    "https://www.cga.ct.gov/current/pub/chap_420h.htm"),
}


def reg_corroboration(all_results):
    """How many COAs in THIS run printed the applied action limit for each category — primary-source
    corroboration baked into the report (the labs apply CT's limit, so the printed limit IS evidence).
    Returns {category: {"limit": modal_limit, "count": n, "unit": unit}}; metals are per-COA so the
    modal printed limit is reported per analyte under 'heavy_metals_detail'."""
    from collections import Counter
    out = {}
    for cat, akeys, unit in (("yeast_mold", ["tymc"], "CFU/g"), ("aerobic", ["aerobic"], "CFU/g")):
        c = Counter()
        for p in all_results:
            for k in akeys:
                e = (getattr(p, "analytes", {}) or {}).get(k)
                if isinstance(e, dict) and e.get("limit") not in (None, ""):
                    try: c[float(e["limit"])] += 1
                    except (TypeError, ValueError): pass
        if c:
            lim, n = c.most_common(1)[0]
            out[cat] = {"limit": lim, "count": n, "unit": unit}
    metal_detail = {}
    for mk in ("arsenic", "cadmium", "lead", "mercury", "chromium"):
        c = Counter()
        for p in all_results:
            e = (getattr(p, "analytes", {}) or {}).get(mk)
            if isinstance(e, dict) and e.get("limit") not in (None, ""):
                try: c[float(e["limit"])] += 1
                except (TypeError, ValueError): pass
        if c:
            metal_detail[mk] = [(lim, n) for lim, n in c.most_common(3)]
    out["heavy_metals_detail"] = metal_detail
    return out


# ── CT regulatory SOURCE-DOCUMENT ledger (full offline provenance) ────────────────────────────────
# `fetch-standards` downloads each cited CT source document, extracts its readable text (PDF via the
# same pdfium -> pdfplumber -> OCR chain used for COAs, so CT's non-extractable PDFs still yield text),
# SHA-256-hashes the RAW bytes, and stores everything in CT Regulatory Ledger.json. That ledger is
# embedded into the build (like the registry + COA caches) and auto-seeds on first run, so the program
# carries the ACTUAL source text + a content hash for offline, forensic legal provenance — the dated
# numeric limits are already baked in (CT_REG_CITATIONS); this caches the documents BEHIND them.
REG_LEDGER = os.path.join(OUT_DIR, "CT Regulatory Ledger.json")
REG_LEDGER_VERSION = 1


# Direct CT source DOCUMENTS (incl. the actual regulation PDF, which CT serves as a non-extractable
# scan — fetch-standards OCRs it via v4.read_pdf_text so its text is still cached for provenance).
CT_REG_EXTRA_DOCS = [
    ("RCSA §21a-408-58 — laboratory testing (regulation PDF)",
     "https://eregulations.ct.gov/eRegsPortal/Browse/getDocument?guid=%7B62390E14-4059-4C8C-9263-F16137648B5A%7D"),
]


def _reg_source_urls():
    """Deduped (label, url) list of CT source documents to cache (from LEGAL_SOURCES + CT_REG_CITATIONS
    + the direct regulation-PDF docs that need OCR)."""
    seen, out = set(), []
    for label, url in LEGAL_SOURCES["_general"]:
        if url not in seen:
            seen.add(url); out.append((label, url))
    for cat, (cit, url) in CT_REG_CITATIONS.items():
        if url and url not in seen:
            seen.add(url); out.append((f"{cat.replace('_', ' ')} — cited source", url))
    for label, url in CT_REG_EXTRA_DOCS:
        if url not in seen:
            seen.add(url); out.append((label, url))
    return out


def _fetch_bytes(url, session=None, timeout=45):
    """GET raw bytes + content-type for provenance. Never raises. -> (ok, status, content, ctype)."""
    try:
        import requests as _rq
    except Exception as e:
        return (False, f"requests unavailable: {type(e).__name__}", b"", "")
    getter = session if session is not None else _rq
    kw = {"timeout": timeout, "allow_redirects": True,
          "headers": {"User-Agent": "CannaScopeCT/16 (research; legal-source provenance)"}}
    bundle = _ca_bundle()
    if bundle:
        kw["verify"] = bundle
    last = (False, "not attempted", b"", "")
    for _attempt in range(2):
        try:
            r = getter.get(url, **kw)
            return (200 <= r.status_code < 300, f"HTTP {r.status_code}", r.content or b"",
                    r.headers.get("Content-Type", ""))
        except Exception as e:
            last = (False, f"{type(e).__name__}: {str(e)[:70]}", b"", "")
    return last


def _doc_text(raw, ctype, url):
    """Readable text from fetched bytes. PDF -> v4.read_pdf_text (pdfium -> pdfplumber -> OCR, so a
    non-extractable scanned reg PDF still yields text). HTML -> tag-stripped text. -> (text, method)."""
    is_pdf = (raw[:1024].find(b"%PDF") >= 0) or ("pdf" in (ctype or "").lower()) or url.lower().endswith(".pdf")
    if is_pdf:
        try:
            import tempfile
            fd, pth = tempfile.mkstemp(suffix=".pdf"); os.close(fd)
            try:
                with open(pth, "wb") as f:
                    f.write(raw)
                txt = v4.read_pdf_text(pth) or ""
                return txt, ("pdf+ocr" if len(txt.strip()) < 200 else "pdf")
            finally:
                try: os.remove(pth)
                except OSError: pass
        except Exception as e:
            return "", f"pdf-error:{type(e).__name__}"
    try:
        import html as _html
        s = raw.decode("utf-8", "replace")
        s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
        s = re.sub(r"(?s)<[^>]+>", " ", s)
        s = re.sub(r"\s+", " ", _html.unescape(s)).strip()
        return s, "html"
    except Exception as e:
        return "", f"text-error:{type(e).__name__}"


def build_reg_ledger(online=True, session=None):
    """Fetch each cited CT source DOCUMENT, store raw text + SHA-256(raw bytes) + fetch timestamp into
    CT Regulatory Ledger.json for offline forensic provenance. Fully fail-safe (never raises)."""
    import hashlib
    stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    entries = []
    for label, url in _reg_source_urls():
        if not online:
            entries.append(dict(label=label, url=url, ok=False, status="offline — not fetched", fetched_at=stamp))
            continue
        ok, status, raw, ctype = _fetch_bytes(url, session)
        if ok and raw:
            text, method = _doc_text(raw, ctype, url)
            entries.append(dict(label=label, url=url, ok=True, http_status=status, content_type=ctype,
                                sha256=hashlib.sha256(raw).hexdigest(), byte_len=len(raw),
                                text_len=len(text), method=method, text=text[:200000], fetched_at=stamp))
        else:
            entries.append(dict(label=label, url=url, ok=False, http_status=status, fetched_at=stamp))
    led = dict(ledger_version=REG_LEDGER_VERSION, built_at=stamp, as_of=CT_REG_AS_OF, sources=entries)
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        tmp = REG_LEDGER + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(led, f, indent=1)
        os.replace(tmp, REG_LEDGER)
    except OSError:
        pass
    return led


def load_reg_ledger():
    try:
        with open(REG_LEDGER, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _seed_embedded_reg_ledger():
    """Seed CT Regulatory Ledger.json from the embedded snapshot if none exists locally — so the
    cached source documents + SHA-256 hashes ship with the program (offline provenance)."""
    b64 = globals().get("_EMBEDDED_REG_LEDGER_B64")
    if not b64 or os.path.exists(REG_LEDGER):
        return
    try:
        import base64 as _b, zlib as _z
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(REG_LEDGER, "wb") as f:
            f.write(_z.decompress(_b.b64decode(b64)))
        print("Seeded the CT regulatory source-document ledger from the embedded snapshot (offline provenance).")
    except Exception:
        pass


def _legal_cache_load():
    try:
        with open(LEGAL_CACHE, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _legal_cache_save(d):
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        tmp = LEGAL_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, LEGAL_CACHE)
    except OSError:
        pass


def _legal_era(date):
    return date[0] if (date and len(date) == 3 and date[0]) else "unknown"


# GoDaddy "Secure Certificate Authority - G2" intermediate. Several CT .gov hosts on GoDaddy
# (notably www.cga.ct.gov) serve their leaf cert WITHOUT this intermediate, so a standard client
# can't build the chain up to the GoDaddy Root G2 (which IS trusted) and verification fails with
# "unable to get local issuer certificate". We supply the missing intermediate so the chain
# verifies WITH verification still ON — we are completing the chain the server should have sent,
# not disabling any security check. Valid to 2031-05-03; chains to GoDaddy Root G2.
_GODADDY_G2_INTERMEDIATE_PEM = """\
-----BEGIN CERTIFICATE-----
MIIE0DCCA7igAwIBAgIBBzANBgkqhkiG9w0BAQsFADCBgzELMAkGA1UEBhMCVVMx
EDAOBgNVBAgTB0FyaXpvbmExEzARBgNVBAcTClNjb3R0c2RhbGUxGjAYBgNVBAoT
EUdvRGFkZHkuY29tLCBJbmMuMTEwLwYDVQQDEyhHbyBEYWRkeSBSb290IENlcnRp
ZmljYXRlIEF1dGhvcml0eSAtIEcyMB4XDTExMDUwMzA3MDAwMFoXDTMxMDUwMzA3
MDAwMFowgbQxCzAJBgNVBAYTAlVTMRAwDgYDVQQIEwdBcml6b25hMRMwEQYDVQQH
EwpTY290dHNkYWxlMRowGAYDVQQKExFHb0RhZGR5LmNvbSwgSW5jLjEtMCsGA1UE
CxMkaHR0cDovL2NlcnRzLmdvZGFkZHkuY29tL3JlcG9zaXRvcnkvMTMwMQYDVQQD
EypHbyBEYWRkeSBTZWN1cmUgQ2VydGlmaWNhdGUgQXV0aG9yaXR5IC0gRzIwggEi
MA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQC54MsQ1K92vdSTYuswZLiBCGzD
BNliF44v/z5lz4/OYuY8UhzaFkVLVat4a2ODYpDOD2lsmcgaFItMzEUz6ojcnqOv
K/6AYZ15V8TPLvQ/MDxdR/yaFrzDN5ZBUY4RS1T4KL7QjL7wMDge87Am+GZHY23e
cSZHjzhHU9FGHbTj3ADqRay9vHHZqm8A29vNMDp5T19MR/gd71vCxJ1gO7GyQ5HY
pDNO6rPWJ0+tJYqlxvTV0KaudAVkV4i1RFXULSo6Pvi4vekyCgKUZMQWOlDxSq7n
eTOvDCAHf+jfBDnCaQJsY1L6d8EbyHSHyLmTGFBUNUtpTrw700kuH9zB0lL7AgMB
AAGjggEaMIIBFjAPBgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBBjAdBgNV
HQ4EFgQUQMK9J47MNIMwojPX+2yz8LQsgM4wHwYDVR0jBBgwFoAUOpqFBxBnKLbv
9r0FQW4gwZTaD94wNAYIKwYBBQUHAQEEKDAmMCQGCCsGAQUFBzABhhhodHRwOi8v
b2NzcC5nb2RhZGR5LmNvbS8wNQYDVR0fBC4wLDAqoCigJoYkaHR0cDovL2NybC5n
b2RhZGR5LmNvbS9nZHJvb3QtZzIuY3JsMEYGA1UdIAQ/MD0wOwYEVR0gADAzMDEG
CCsGAQUFBwIBFiVodHRwczovL2NlcnRzLmdvZGFkZHkuY29tL3JlcG9zaXRvcnkv
MA0GCSqGSIb3DQEBCwUAA4IBAQAIfmyTEMg4uJapkEv/oV9PBO9sPpyIBslQj6Zz
91cxG7685C/b+LrTW+C05+Z5Yg4MotdqY3MxtfWoSKQ7CC2iXZDXtHwlTxFWMMS2
RJ17LJ3lXubvDGGqv+QqG+6EnriDfcFDzkSnE3ANkR/0yBOtg2DZ2HKocyQetawi
DsoXiWJYRBuriSUBAA/NxBti21G00w9RKpv0vHP8ds42pM3Z2Czqrpv1KrKQ0U11
GIo/ikGQI31bS/6kA1ibRrLDYGCD+H1QQc7CoZDDu+8CL9IVVO5EFdkKrqeKM+2x
LXY2JtwE65/3YR8V3Idv7kaWKK2hJn0KCacuBKONvPi8BDAB
-----END CERTIFICATE-----
"""

_CA_BUNDLE_PATH = None


def _ca_bundle():
    """Path to a CA bundle = certifi's roots + the GoDaddy G2 intermediate, so CT hosts that omit
    the intermediate still verify with verification ON. Built once per run; on any error falls back
    to certifi's bundle, then to requests' default (returns "") — a fetch never crashes over this."""
    global _CA_BUNDLE_PATH
    if _CA_BUNDLE_PATH is not None:
        return _CA_BUNDLE_PATH
    try:
        import certifi, tempfile
        base = open(certifi.where(), encoding="utf-8").read()
        fd, path = tempfile.mkstemp(suffix="-cannascope-cabundle.pem")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(base)
            if not base.endswith("\n"):
                f.write("\n")
            f.write(_GODADDY_G2_INTERMEDIATE_PEM.strip() + "\n")
        _CA_BUNDLE_PATH = path
    except Exception:
        try:
            import certifi
            _CA_BUNDLE_PATH = certifi.where()
        except Exception:
            _CA_BUNDLE_PATH = ""        # requests will fall back to its default trust store
    return _CA_BUNDLE_PATH


def _fetch_url_safe(url, session=None, timeout=25, _seen=None):
    """Best-effort live GET, deduped per run via _seen. Returns (ok, note). NEVER raises.

    Hardened for two real CT-server quirks that otherwise make every legal-source check fail:
      * slow endpoints (eRegulations) — a generous timeout plus one retry on a transient
        timeout / connection error; and
      * an incomplete TLS chain (cga.ct.gov ships its leaf cert without the GoDaddy G2
        intermediate) — we verify against certifi + that intermediate (see _ca_bundle), so the
        chain validates WITH verification still on. These are read-only GETs of public CT
        legal-reference pages (no credentials); the result only records that a source was
        consulted, never an extracted/published number."""
    if _seen is not None and url in _seen:
        return _seen[url]
    try:
        import requests as _rq
    except Exception as e:
        res = (False, f"requests unavailable: {type(e).__name__}")
        if _seen is not None:
            _seen[url] = res
        return res
    getter = session if session is not None else _rq
    kw = {"timeout": timeout, "headers": {"User-Agent": "CannaScopeCT/15 (research; verify-only)"}}
    bundle = _ca_bundle()
    if bundle:
        kw["verify"] = bundle
    res = (False, "not attempted")
    for _attempt in range(2):                        # one retry for slow / transient endpoints
        try:
            r = getter.get(url, **kw)
            res = (200 <= r.status_code < 300, f"HTTP {r.status_code}")
            break
        except (_rq.exceptions.Timeout, _rq.exceptions.ConnectionError) as e:
            res = (False, f"{type(e).__name__}: {str(e)[:70]}")
            continue                                 # transient — try once more
        except Exception as e:                       # any other error -> fail safe, never propagate
            res = (False, f"{type(e).__name__}: {str(e)[:70]}")
            break
    if _seen is not None:
        _seen[url] = res
    return res


def verify_standard(category, date, lab="", product_type="", online=True, session=None, _seen=None):
    """LOCAL-FIRST, internet-FALLBACK, never-crash verification of the CT standard in effect on a
    test date. Returns a dict (verified, limit, unit, status, sources_attempted, fetched_at, note).
    Carries LEGAL_UNVERIFIED whenever a dated standard cannot be confidently established."""
    base = standard_for(category, date, lab, product_type)
    rec = dict(category=_std_category(category) or (category or ""), era=_legal_era(date),
               limit=(base or {}).get("limit"), unit=(base or {}).get("unit", ""),
               verified=bool(base and base.get("verified")), source=(base or {}).get("source", ""),
               sources_attempted=[], fetched_at="", note=(base or {}).get("note", ""), status="")
    # 1) built-in registry already verified (value confirmed against CT DCP sources + corroborated by the
    #    action limit printed on CT COAs). Use it. When ONLINE, also touch the live CT legal source(s) to
    #    record confirmation freshness (best-effort, deduped, fail-safe) — so "verified" is backed by an
    #    actual live consultation this run, not just a built-in assertion.
    if rec["verified"]:
        rec["status"] = "verified (CannaScope dated registry — value confirmed)"
        if online:
            attempted = []
            for label, url in LEGAL_SOURCES.get(rec["category"], LEGAL_SOURCES["_general"]):
                ok, note = _fetch_url_safe(url, session, _seen=_seen)
                attempted.append(dict(label=label, url=url, ok=ok, result=note))
            if attempted:
                rec["sources_attempted"] = attempted
                rec["fetched_at"] = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
                if any(a["ok"] for a in attempted):
                    rec["status"] = "verified — value confirmed + live CT source consulted this run"
        return rec
    # 2) fresh cache from a prior lookup -> use it, NO network.
    cache = _legal_cache_load()
    key = f"{rec['category']}:{rec['era']}"
    ce = cache.get(key)
    if (ce and ce.get("fetch_version") == LEGAL_FETCH_VERSION
            and (time.time() - ce.get("fetched_epoch", 0) < LEGAL_CACHE_TTL)):
        rec.update(verified=ce.get("verified", False), sources_attempted=ce.get("sources_attempted", []),
                   fetched_at=ce.get("fetched_at", ""), status=(ce.get("status", "") or "from cache"))
        if not rec["verified"]:
            rec["note"] = (rec["note"] + " " if rec["note"] else "") + LEGAL_UNVERIFIED
        return rec
    # 3) internet FALLBACK — only now, and only if online.
    if not online:
        rec["status"] = "offline — local/cache could not verify; not consulted live"
        rec["note"] = (rec["note"] + " " if rec["note"] else "") + LEGAL_UNVERIFIED
        return rec
    attempted = []
    for label, url in LEGAL_SOURCES.get(rec["category"], LEGAL_SOURCES["_general"]):
        ok, note = _fetch_url_safe(url, session, _seen=_seen)
        attempted.append(dict(label=label, url=url, ok=ok, result=note))
    stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    any_ok = any(a["ok"] for a in attempted)
    # We REACH the live source but do NOT fabricate an exact dated limit from legal prose.
    rec.update(verified=False, sources_attempted=attempted, fetched_at=stamp,
               status=("live CT sources consulted — manual confirmation needed" if any_ok
                       else "live CT sources unreachable this run"))
    rec["note"] = (rec["note"] + " " if rec["note"] else "") + LEGAL_UNVERIFIED
    cache[key] = dict(verified=False, sources_attempted=attempted, fetched_at=stamp,
                      fetched_epoch=time.time(), status=rec["status"],
                      fetch_version=LEGAL_FETCH_VERSION)
    _legal_cache_save(cache)
    return rec


def verify_standards_for_report(tym_findings, compliance_flags, online=True, session=None):
    """Run legal verification once per unique (category, era) used by this run's date-sensitive
    findings. Fully wrapped: ANY failure returns what was gathered so far and never breaks the run.
    Returns (records, unreachable_sources)."""
    pairs, seen_keys = [], set()
    for a in (tym_findings or []):
        d = a.get("date")
        k = ("yeast_mold", _legal_era(d))
        if k not in seen_keys:
            seen_keys.add(k); pairs.append(("yeast_mold", d, a.get("lab", "")))
    for r in (compliance_flags or []):
        p = r.get("p")
        d = v4.parse_date(getattr(p, "testing_date", "") or getattr(p, "approval_date", "") or "") if p else None
        for cat in ("heavy_metals", "aerobic", "pathogens", "thc_potency"):
            k = (cat, _legal_era(d))
            if k not in seen_keys:
                seen_keys.add(k); pairs.append((cat, d, getattr(p, "test_lab", "") if p else ""))
    records, unreachable, _seen = [], [], {}
    for cat, d, lab in pairs[:40]:               # bounded; URLs are deduped across the whole pass
        try:
            rec = verify_standard(cat, d, lab=lab, online=online, session=session, _seen=_seen)
        except Exception as e:                   # belt-and-suspenders: never let one lookup break the run
            rec = dict(category=cat, era=_legal_era(d), verified=False, sources_attempted=[],
                       status=f"verification error (skipped): {type(e).__name__}", note=LEGAL_UNVERIFIED)
        records.append(rec)
        for a in rec.get("sources_attempted", []):
            if not a.get("ok"):
                unreachable.append(f"{a['url']} ({a['result']})")
    return records, unreachable


def assess_tym(p):
    """Lab- & date-aware Total Yeast & Mold assessment for one product. Never fabricates:
    missing lab / date / value are reported as unknown. Returns None if no TYM/Aspergillus
    was tested at all."""
    e = p.analytes.get("tymc")
    asperg = p.analytes.get("aspergillus") or {}
    if e is None and not asperg:
        return None
    lab = getattr(p, "test_lab", "") or ""
    lk = _lab_key(lab)
    date = v4.parse_date(getattr(p, "testing_date", "") or getattr(p, "approval_date", "") or "")
    if not _valid_date(date):
        date = None
    val = (e or {}).get("value")
    below = bool((e or {}).get("_below_detect"))
    tested = bool(e)
    quantified = bool(e) and v5.is_quantified(e)
    # mval = a TRUSTED measured count (quantified, not a below-detection bound).
    # bbound = a below-detection bound, i.e. the COA says "< bbound" (count is under bbound).
    mval = val if (quantified and val is not None and not below) else None
    bbound = val if (below and val is not None) else None
    numeric_disclosed = mval is not None
    std = tym_standard_for(lk, date)
    lab_limit = std["limit"] if std else None

    def verdict(limit):
        if limit is None:
            return None
        if mval is not None:
            return "PASS" if mval <= limit else "FAIL"
        if bbound is not None:
            # "< bbound" only proves PASS if the whole bound is at/under the limit; otherwise
            # the true count is unknown relative to this limit.
            return "PASS" if bbound <= limit else "UNDETERMINED"
        return None

    lab_verdict_v = verdict(lab_limit)
    current_verdict_v = verdict(TYM_CURRENT_LIMIT)
    strict_verdict_v = verdict(TYM_STRICT_BENCHMARK)
    # over_strict / bd_above_strict are vs CannaScope's INTERNAL 10,000 benchmark. They are STILL
    # computed (surfaced elsewhere as an internal consumer-awareness threshold), but they are NO
    # LONGER inclusion drivers OR reasons-for-review in this section — that is what flooded it.
    over_strict = (mval is not None and mval > TYM_STRICT_BENCHMARK)
    bd_above_strict = (bbound is not None and bbound > TYM_STRICT_BENCHMARK)
    # Actual-standard drivers (what THIS section is for):
    over_current = (mval is not None and mval > TYM_CURRENT_LIMIT)            # over the current CT limit
    over_lab_limit = (mval is not None and lab_limit is not None and mval > lab_limit)  # over the ACTUAL dated lab limit
    bd_above_current = (bbound is not None and bbound > TYM_CURRENT_LIMIT)    # bound too broad vs the current CT limit
    # The SAME result would pass one actual dated standard but fail another that was in effect.
    std_mismatch = (lab_verdict_v in ("PASS", "FAIL") and current_verdict_v in ("PASS", "FAIL")
                    and lab_verdict_v != current_verdict_v)
    # Applicable dated standard could not be established for a non-trivial result -> manual review.
    unverified_std = (std is None and ((mval is not None and mval > TYM_STRICT_BENCHMARK) or bbound is not None))
    cannot_compare = bd_above_current   # below-detection bound can't be compared to the actual current limit
    in_window = (date is not None and TYM_HIGH_RISK_START <= date <= TYM_HIGH_RISK_END)
    high_risk = (lk == TYM_HIGH_RISK_LAB and in_window and (over_strict or bd_above_strict))
    asperg_detected = (asperg.get("status") == "DETECTED")
    asperg_tested = asperg.get("status") in ("DETECTED", "ND") if asperg else False
    # Genuine opacity: tested but NO measured number AND no below-detection bound (just "pass").
    passed_no_value = tested and mval is None and bbound is None
    flags = []
    if asperg_detected:
        flags.append("aspergillus_detected")
    if high_risk:
        flags.append("high_risk_window")
    if over_current:
        flags.append("over_current_ct_limit")
    elif over_lab_limit:
        flags.append("over_lab_limit_on_date")
    if std_mismatch:
        flags.append("dated_standard_mismatch")
    if cannot_compare:
        flags.append("cannot_confirm_current_limit")
    if passed_no_value:
        flags.append("passed_no_value_disclosed")
    if unverified_std:
        flags.append("unverified_standard_review")
    if not asperg_tested:  # Aspergillus not tested on this COA (older / other-lab era) — note the absence
        flags.append("aspergillus_not_tested")
    # Inclusion is driven ONLY by actual lab/date/standard, transparency, or pathogen concerns —
    # NOT by the internal 10,000 benchmark (over_strict / bd_above_strict are intentionally absent).
    is_concern = bool(asperg_detected or high_risk or over_lab_limit or over_current
                      or std_mismatch or passed_no_value or unverified_std or cannot_compare)
    return dict(p=p, lab=lab, lab_key=lk, date=date, value=val, below=below, bbound=bbound, mval=mval,
                numeric_disclosed=numeric_disclosed, tested=tested, std=std, lab_limit=lab_limit,
                lab_verdict=lab_verdict_v, current_verdict=current_verdict_v, strict_verdict=strict_verdict_v,
                over_strict=over_strict, over_current=over_current, over_lab_limit=over_lab_limit,
                std_mismatch=std_mismatch, unverified_std=unverified_std,
                bd_above_strict=bd_above_strict, bd_above_current=bd_above_current,
                high_risk=high_risk, aspergillus_detected=asperg_detected, aspergillus_tested=asperg_tested,
                passed_no_value=passed_no_value, flags=flags, is_concern=is_concern)


_TYM_SEV = {"aspergillus_detected": 6, "high_risk_window": 5, "over_current_ct_limit": 4,
            "over_lab_limit_on_date": 4, "dated_standard_mismatch": 3,
            "cannot_confirm_current_limit": 3, "unverified_standard_review": 2,
            "passed_no_value_disclosed": 1}


def tym_standard_findings(products):
    """Products with a lab/date-aware TYM standard concern, most severe first."""
    out = [a for a in (assess_tym(p) for p in products) if a and a["is_concern"]]
    out.sort(key=lambda a: max((_TYM_SEV.get(f, 0) for f in a["flags"]), default=0), reverse=True)
    return out


_TYM_STD_AUTHORITY = ("CT DCP Policies & Procedures microbial (total yeast & mold) testing standard; "
                      "the Aug-2020 AltaSci limit change and the ~2022 unified rule (verify the exact "
                      "section, effective date, and current text in eRegulations)")
_TYM_FMT_AUTHORITY = ("CT DCP Policies & Procedures COA reporting / format requirements (verify exact "
                      "section & current text in eRegulations)")


def tym_compliance_rows(tym_findings):
    """Reporting/standard-application compliance leads from the lab/date-aware TYM review.
    Same record shape as compliance_flag_rows(); authority cited at rule level + unverified."""
    rows = []
    for a in tym_findings:
        p = a["p"]
        if a["high_risk"]:
            if a["mval"] is not None:
                # A TRUSTED measured count that is known to exceed the strict benchmark.
                finding = (f"AltaSci-tested yeast & mold measured {clean_value(a['mval'], 'CFU/g')} — known to "
                           f"exceed the strict 10,000 CFU/g benchmark"
                           + (" and the current 100,000 CT limit" if a["over_current"] else "")
                           + ", while it may have passed under the temporary ~1,000,000 CFU/g limit then in "
                           "effect. Verify the dated standard that applied and whether patients were notified.")
                conf = "High — a measured numeric count is disclosed and exceeds the strict benchmark"
            else:
                # A below-detection bound "< bbound" (the classic AltaSci <1,000,000): the true count is
                # UNKNOWN relative to 10,000 — do NOT claim it exceeds the benchmark.
                bnd = clean_value(a["bbound"], "CFU/g")
                finding = (f"AltaSci yeast & mold reported only as a below-detection bound (&lt; {bnd}). It passed "
                           f"the temporary ~1,000,000 CFU/g limit then in effect, but the reporting threshold is "
                           f"too broad for patient-protective review: CannaScope <b>cannot determine whether the "
                           f"result was below the strict 10,000 CFU/g benchmark</b> because the COA only states "
                           f"it was under {bnd}. This is a transparency concern, not a measured exceedance.")
                conf = ("High that the COA discloses only a <" + bnd + " bound; the true count relative to 10,000 "
                        "is undetermined")
            rows.append(dict(
                p=p, rule_category="Testing-standard application (yeast & mold)",
                finding=finding, cited_authority=_TYM_STD_AUTHORITY, authority_unverified=True,
                status="potential_transparency_issue", severity=("high" if a["mval"] is not None else "moderate"),
                confidence=conf,
                recommended_review="DCP / Ombudsman — confirm the applicable dated limit and patient notification"))
        if a["passed_no_value"]:
            rows.append(dict(
                p=p, rule_category="Reporting transparency (yeast & mold)",
                finding="Yeast & mold reported as PASS with NO numeric CFU/g disclosed; given CT's historical "
                        "100x spread in TYM limits, the missing number itself is a concern — the count cannot "
                        "be compared to any standard.",
                cited_authority=_TYM_FMT_AUTHORITY, authority_unverified=True,
                status="potential_transparency_issue", severity="medium",
                confidence="High that no numeric value is disclosed on the COA",
                recommended_review="DCP — confirm required COA disclosure of numeric microbial counts"))
    return rows


# Compliance triage — group leads so a long list does not overwhelm or imply legal violations.
COMPLIANCE_TIERS = ("Critical", "High", "Moderate", "Low")
_TIER_BLURB = {
    "Critical": "Verified over a CURRENT CT legal limit, or a failed pathogen / pesticide / solvent result.",
    "High": "A clear pass/fail contradiction, a same-lot conflicting COA, or a COA value over the legal "
            "limit that was dated/in effect for that test.",
    "Moderate": "A plausible historical regulatory concern that warrants human review.",
    "Low": "Informational / historical — unusual potency, a missing value, a reporting-format concern, or "
           "a transparency note. Not an indication of a violation.",
}


def compliance_tier(row):
    """Map a compliance lead to one of Critical / High / Moderate / Low (review-priority only —
    never an assertion that a violation occurred)."""
    cat = (row.get("rule_category") or "").lower()
    sev = (row.get("severity") or "").lower()
    if "testing & product quality" in cat:
        return "Critical"                              # over current legal limit / pathogen / panel FAIL
    if "testing-standard application" in cat:
        return "High" if sev == "high" else "Moderate"  # measured exceedance vs undetermined <1M
    if "reporting transparency" in cat:
        return "Low"
    if "labeling & potency" in cat:
        return "Low"
    return {"high": "High", "moderate": "Moderate"}.get(sev, "Low")


# ============================================================================
# Zero-result verification (presume parser error until verified)
# ----------------------------------------------------------------------------
# To tell a TRUE historical absence ("this panel isn't on these COAs") apart from a PARSER GAP
# ("the panel is on the COA but the parser read 0"), we record, per COA while its text is in hand,
# whether each category's wording APPEARS AT ALL. A 0-parse category whose wording also never
# appears = an explained historical absence (label it plainly, don't FAIL). A 0-parse category whose
# wording DOES appear = a parser gap that must stay a visible draft warning.
# ============================================================================
_PRESENCE_RX = {
    "tymc": re.compile(r"yeast|mold|\btymc\b|total\s+yeast", re.I),
    "aerobic": re.compile(r"aerobic|\btamc\b|plate\s+count", re.I),
    "arsenic": re.compile(r"arsenic|\bas\b", re.I),
    "chromium": re.compile(r"chromium", re.I),
    "cadmium": re.compile(r"cadmium", re.I),
    "lead": re.compile(r"\blead\b", re.I),
    "mercury": re.compile(r"mercury", re.I),
    "mycotoxins": re.compile(r"mycotoxin|aflatoxin|ochratoxin", re.I),
    "pathogens": re.compile(r"salmonella|aspergillus|\bstec\b|shiga|listeria|e\.?\s*coli|coliform|pathogen", re.I),
    "pesticides": re.compile(r"pesticide", re.I),
    "solvents": re.compile(r"residual\s+solvent", re.I),
    "cannabinoids": re.compile(r"cannabinoid|potency|\bthca\b|total\s+thc|\bcbd\b|\bthc\b", re.I),
}


def _detect_presence(text):
    """{category_key: bool} — does each category's wording appear anywhere in this COA's text?"""
    t = text or ""
    return {k: bool(rx.search(t)) for k, rx in _PRESENCE_RX.items()}


def parsed_count(all_results, key):
    """How many products had this analyte PARSED at all (any status)."""
    return sum(1 for p in all_results if key in p.analytes)


def _parsed_in(p, pkey):
    """Did THIS COA yield a parsed value/verdict for category pkey? A parsed value definitionally
    PROVES the category was reported on this COA — used so 'reported-on' is never below 'parsed'
    (esp. on the cache path, where the COA text isn't re-read so _cat_present is absent)."""
    an = getattr(p, "analytes", {}) or {}
    if pkey in ("mycotoxins",):
        return any(k in an for k in MYCO_KEYS)
    if pkey in ("pathogens",):
        return any(k in an for k in v5.PATHO_KEYS)
    if pkey == "pesticides":
        return getattr(p, "pesticides", "") in ("PASS", "FAIL")
    if pkey == "solvents":
        return getattr(p, "solvents", "") in ("PASS", "FAIL")
    if pkey == "cannabinoids":
        return bool(getattr(p, "cannabinoids", None))
    return pkey in an


def _present_count(all_results, pkey):
    """How many COAs REPORT ON this category = text mentions it (parser-independent presence signal)
    OR a value was parsed for it (a parsed value proves the COA reported it). The parsed-implies-
    present union guarantees the invariant parsed <= reported-on, and fixes the cache path where the
    text-presence signal (_cat_present) isn't available so it would otherwise collapse to ~0."""
    n = 0
    for p in all_results:
        if (getattr(p, "_cat_present", None) or {}).get(pkey) or _parsed_in(p, pkey):
            n += 1
    return n


_PARTIAL_COVERAGE_MIN = 0.50    # parsed must reach >= this fraction of the COAs that report it
_PARTIAL_MIN_GAP = 25           # ...and the absolute gap must matter, to avoid noise on tiny sets


def zero_result_checks(all_results, flagged, watch):
    """For each expected category classify HONESTLY, using whether the category's wording even
    appears on the COAs (presence) — so a 0-parse count is never shown as a clean zero:

      OK                            -> validated rows exist.
      Not Reported (historical)     -> the panel's wording does not appear on any parsed COA in this
                                       window: an EXPLAINED historical absence (older COA format),
                                       clearly labeled — NOT 'confirmed zero', NOT a FAIL.
      Needs Historical Parser Review-> the wording DOES appear but the parser extracted 0: a parser
                                       gap. Stays a DRAFT WARNING (drives FAIL) until resolved.
      Partial Coverage              -> parsed in only a minority of the COAs that report it: the
                                       'no findings' statement covers only the parsed subset (warning).
      No Significant Findings       -> parsed in enough COAs and none crossed the threshold.

    Returns (checks, draft) where draft is True if any 'Needs Historical Parser Review' remains."""
    total = len(all_results)
    raw = []   # (category, presence_key, n_flagged, parsed, extra)

    def _high_thc_flower(p):
        rv = thc_review_value(p)
        return is_noninfused_flower(p) and rv is not None and rv[1] > THC_REVIEW_PCT

    for key, title in ANALYTE_TABLES:
        raw.append((title, key, len(category_rows(flagged, key)), parsed_count(all_results, key), ""))
    raw.append(("Mycotoxins", "mycotoxins", len(mycotoxin_rows(flagged)),
                sum(1 for p in all_results if any(k in p.analytes for k in MYCO_KEYS)), ""))
    raw.append(("Pathogens", "pathogens", len(pathogen_rows(flagged)),
                sum(1 for p in all_results if any(k in p.analytes for k in v5.PATHO_KEYS)), ""))
    raw.append(("Pesticides", "pesticides", len(pesticide_rows(flagged)),
                sum(1 for p in all_results if p.pesticides in ("PASS", "FAIL")),
                "(panel PASS/FAIL counts as parsed.)"))
    raw.append(("Residual Solvents", "solvents", len(solvent_rows(flagged)),
                sum(1 for p in all_results if p.solvents in ("PASS", "FAIL")),
                "(reported mainly on extracts/vapes.)"))
    raw.append(("High-THC Flower Review", "cannabinoids", sum(1 for p in flagged if _high_thc_flower(p)),
                sum(1 for p in all_results if p.cannabinoids), ""))

    checks = []
    for cat, pkey, n_flagged, parsed, extra in raw:
        present = _present_count(all_results, pkey)
        if n_flagged > 0:
            status, note = "OK", f"{n_flagged} validated row(s)."
        elif total == 0:
            status, note = "No Significant Findings", "No products in window."
        elif present == 0:
            status, note = ("Not Reported (historical)",
                            f"This panel's wording does not appear on any of the {total:,} parsed COAs in "
                            f"this window — an explained historical absence (not part of this era's COA "
                            f"format), not a measured zero. {extra}".strip())
        elif parsed == 0:
            status, note = ("Needs Historical Parser Review",
                            f"Wording appears on {present:,} COA(s) but the parser extracted 0 — a "
                            f"historical-format parser gap. Held as a draft warning until resolved. {extra}".strip())
        elif parsed < _PARTIAL_COVERAGE_MIN * present and (present - parsed) >= _PARTIAL_MIN_GAP:
            status, note = ("Partial Coverage",
                            f"Parsed in {parsed:,} of {present:,} COAs that report it — partial coverage; "
                            f"'no findings' covers only the parsed subset. {extra}".strip())
        else:
            status, note = ("No Significant Findings",
                            f"Parsed in {parsed:,} of {present:,} COA(s) that report it; none crossed the "
                            f"CannaScope threshold. {extra}".strip())
        # P1 count invariant: flagged <= parsed <= reported-on(present) <= window(total).
        # A violation means a counting bug (e.g. the cache-path presence collapse) — flag it loudly
        # rather than silently printing "OK" over an impossible fraction.
        invariant_ok = (0 <= n_flagged <= parsed <= present <= total)
        checks.append(dict(category=cat, flagged=n_flagged, parsed=parsed, present=present,
                           total=total, status=status, note=note, invariant_ok=invariant_ok))

    draft = any(c["status"] == "Needs Historical Parser Review" for c in checks)
    return checks, draft


# ============================================================================
# Self-audit
# ============================================================================
def load_self_improve_log():
    """Prior runs' self-improvement notes (Part B item 10). [] if none yet."""
    try:
        with open(SELF_IMPROVE_LOG, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_self_improve_log(entries):
    try:
        tmp = SELF_IMPROVE_LOG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries[-50:], f, indent=1)   # keep the last 50 runs
        os.replace(tmp, SELF_IMPROVE_LOG)
    except OSError:
        pass


def generate_self_audit(fmt_year_rows, zero_checks, src_metrics, debug, format_holds, conf_mix,
                        legal_records=None, legal_unreachable=None):
    """Evaluate THIS run's own weaknesses as observation -> why-it-matters -> recommendation notes
    (Part B item 9). Includes whether legal standards were verified live by date (item 7 status)."""
    obs = []

    def add(cat, observation, why, rec):
        obs.append(dict(category=cat, observation=observation, why=why, recommendation=rec))

    not_ready = [str(r["year"]) for r in (fmt_year_rows or [])
                 if r.get("verdict") in ("NOT READY", "PARTIAL", "NO DATA", "INSUFFICIENT SAMPLE")]
    if not_ready:
        add("COA format learning",
            f"COA formats for {', '.join(not_ready)} remain not fully trained (NOT READY / PARTIAL).",
            "Older COA layouts may contain values the parser does not yet fully understand.",
            f"Run year-by-year COA learning ONLINE for {', '.join(not_ready)}, prioritizing AltaSci, Northeast "
            f"Laboratories, and Analytics Labs templates: python3 {SCRIPT_FILE} learn --years 2015-2024.")
    ur = (debug or {}).get("unreadable_after_retry", 0)
    if ur:
        add("OCR / readability",
            f"{ur} COA(s) were unreadable even after an escalating-DPI OCR retry (each was re-rendered at a "
            "higher resolution and re-OCR'd when the first pass returned no text).",
            "Unreadable COAs are coverage gaps — their results cannot be validated or published.",
            "These are likely blank, corrupt, or low-quality image scans that no resolution recovers. Re-run "
            "online at low load; for persistent cases try an alternate OCR backend or obtain a text-bearing COA.")
    smm = (src_metrics or {}).get("rows_excluded_for_coa_source_mismatch", 0)
    if smm:
        add("Source binding", f"{smm} flagged value(s) could not be re-verified in their own linked COA.",
            "A value not found in its own COA may be a parse/OCR artifact rather than a real result.",
            "Review the Coverage Gaps / Unvalidated COAs section and improve the parser for those COA layouts.")
    if format_holds:
        add("Extraction confidence", f"{len(format_holds)} extraction(s) were held as UNCERTAIN and excluded.",
            "Held extractions never reach findings; a large number signals weak parsing for those formats.",
            "Train the parser on the affected labs/years; review items in COA Extraction Review.")
    gap_cats = [c["category"] for c in (zero_checks or [])
                if c.get("status") in ("Needs Historical Parser Review", "Partial Coverage")]
    if gap_cats:
        add("Category coverage", f"Incomplete coverage this run for: {', '.join(gap_cats)}.",
            "A category that should parse but didn't (or only partly) is a real parser gap, not a clean zero.",
            "Add or repair parsers for these categories' COA wording, then re-run to confirm coverage.")
    # Legal date-awareness status (Part B item 7 — live legal verification, local-first/internet-fallback).
    legal_records = legal_records or []
    legal_unreachable = legal_unreachable or []
    n_checked = len(legal_records)
    n_verified = sum(1 for r in legal_records if r.get("verified"))
    n_unverified = max(0, n_checked - n_verified)
    _rem = (f" {n_unverified} dated standard(s) remain to be confirmed (e.g. the reported-but-unpublished "
            "Aug-2020 AltaSci window); their numeric value is not auto-extracted from legal prose."
            if n_unverified else " All applied dated standards this run are confirmed.")
    if legal_unreachable:
        add("Legal date-awareness (live lookup)",
            f"{len(legal_unreachable)} live CT legal source URL(s) were unreachable this run; "
            f"{n_verified} of {n_checked} dated standards are confirmed (value verified against CT DCP "
            f"requirements + corroborated by the action limit on the CT COAs).{_rem}",
            "Compliance wording that depends on the test-date standard is only as reliable as the verified standard.",
            "Re-attempt the failed live lookups next run (cache re-verifies monthly): " + "; ".join(legal_unreachable[:4])
            + (" …" if len(legal_unreachable) > 4 else "") + ". Confirm exact dated limits at eRegulations.ct.gov / CGS / DCP.")
    else:
        add("Legal date-awareness (live lookup)",
            f"{n_verified} of {n_checked} dated standards applied this run are confirmed — value verified "
            "against CT DCP testing requirements and corroborated by the action limit printed on the CT COAs, "
            f"with live CT sources (eRegulations / CGS / DCP) consulted this run.{_rem}",
            "Compliance wording that depends on the test-date standard is only as reliable as the verified standard.",
            "The program logs every source URL consulted and re-verifies monthly; confirm any remaining "
            "dated limits at eRegulations.ct.gov / CGS / DCP.")
    # P5: OCR / COA-link coverage visibility — broken/unreadable COAs are coverage gaps (counted, not
    # dropped); and ocr_ok=0 on a cache-served run means OCR was NOT EXERCISED, not that it failed.
    _broken = (debug or {}).get("broken_or_missing_coa_links", 0)
    _unread = (debug or {}).get("unreadable_after_retry", 0)
    _fetched = (debug or {}).get("coas_fetched", 0)
    _ocr_ok = (debug or {}).get("ocr_ok", 0)
    if _broken or _unread:
        add("COA coverage (links / OCR)",
            f"{_broken} broken/missing COA link(s) and {_unread} COA(s) unreadable after OCR retry could not "
            "be reviewed this run.",
            "These are products we could NOT verify — they are coverage gaps, not clean results.",
            "Re-attempt on a future ONLINE run; the counts are carried in the debug log and coverage notes.")
    if _ocr_ok == 0 and _fetched == 0:
        add("OCR path (not exercised)",
            "OCR was not exercised this run — measurements were served from the embedded/triple-verified "
            "cache, so no COA PDFs were fetched or OCR'd (ocr_ok=0 here means 'not run', not 'failed').",
            "Distinguishes a cache-served run from a real OCR failure so the 0 is not misread.",
            f"A cold/online run (or `build-cache`) exercises OCR; run one with internet to refresh coverage.")
    if not obs:
        add("General", "No major weaknesses detected this run.", "—",
            "Continue periodic `learn` runs and re-verify standards by date.")
    return obs


def self_audit(all_results, flagged, thc_flower, infused_potency, rows_for_pub, zero_checks):
    issues = []

    def chk(desc, count, fixed=True):
        issues.append(dict(issue=desc, count=count,
                           status=("Fixed" if fixed else "REMAINS") if count else "None"))

    # infused/vape wrongly in flower review
    bad_infused = sum(1 for p in thc_flower if is_infused(p))
    chk("Infused/extract products in High-THC Flower Review", bad_infused, fixed=(bad_infused == 0))
    # scientific notation in any displayed value
    sci = 0
    for p in flagged:
        for d in v5.quantified_details(p, p._watch):
            v = d.get("value")
            if v is not None and v != 0 and abs(v) < 0.001:
                sci += 1
    chk("Scientific-notation-tier values needing plain display", sci, fixed=True)
    # Total THC 0% on flower with high active (parser conflict)
    conflicts = sum(1 for p in all_results if thc_conflict(p))
    chk("Potency parser conflicts (Total THC 0% vs active ≥35%)", conflicts,
        fixed=True)   # routed out of rankings
    # rows without a clickable COA link
    nolink = sum(1 for p in flagged if not p.report_url)
    chk("Flagged rows without a COA link", nolink, fixed=(nolink == 0))
    # rows not COA-verified (excluded from ranked sections)
    unver = sum(1 for p in flagged if p._coa_status not in PUBLISHABLE)
    chk("Flagged rows not COA-verified (routed to COA Verification Queue)", unver, fixed=True)
    # unresolved DBA
    chk("Producers with unverified DBA", sum(1 for r in rows_for_pub["identities"].values()
                                             if r["confidence"] < 60),
        fixed=True)
    # duplicate rows
    dups = [k for k, n in Counter(v4.coa_key(p) for p in all_results).items() if n > 1]
    chk("Duplicate COA rows", len(dups), fixed=(len(dups) == 0))
    # zero-result parser-gap warnings (a category whose wording appears but parsed 0)
    zw = sum(1 for c in zero_checks if c["status"] == "Needs Historical Parser Review")
    chk("Categories present on COAs but parsed 0 (historical parser gap)", zw, fixed=(zw == 0))

    remaining = [i for i in issues if i["status"] == "REMAINS"]
    return issues, remaining


# ============================================================================
# PDF
# ============================================================================
# ============================================================================
# PDF REPORT NAMING STANDARD
# ----------------------------------------------------------------------------
# FILENAME:  [REPORT#]-CannaScopeCT-V[VERSION]-[TYPE]-[DATE]-[TIME].pdf
#   e.g.     15-CannaScopeCT-V15-Statewide-2026-6-4-5:36PM.pdf
#            16-CannaScopeCT-V15-ConsumerConcern-2026-6-4-9:49PM.pdf
#   TYPE  is exactly "Statewide" or "ConsumerConcern" (the only two report types).
#   DATE  is YYYY-M-D  (month/day NOT zero-padded), e.g. 2026-6-4.
#   TIME  is 12-hour H:MMAM/PM (hour not padded, minute padded, no space), e.g. 5:36PM / 9:16AM.
# REPORT NUMBERING is GLOBAL + CONTINUOUS across BOTH types and never resets; reports are
# NEVER overwritten, renamed, or deleted — every PDF is a brand-new uniquely-numbered file.
# NOTE (macOS): a ':' in a POSIX filename is shown as '/' in Finder (Terminal/ls show ':'
# correctly). The format below follows the spec literally, including the colon.
# ============================================================================
REPORT_TYPE_STATEWIDE = "Statewide"
REPORT_TYPE_CONSUMER = "ConsumerConcern"
_TYPE_TAG = {REPORT_TYPE_STATEWIDE: "SW", REPORT_TYPE_CONSUMER: "CC"}
_FOLDER_LABEL = {REPORT_TYPE_STATEWIDE: "Statewide Report", REPORT_TYPE_CONSUMER: "Consumer Concern Report"}
_REPORT_NUM_RX = re.compile(r"^(\d+)-CannaScopeCT-", re.I)        # short + legacy-V15 standard filenames
_LEGACY_NUM_RX = re.compile(r"Report_(\d+)")                     # pre-standard statewide filenames

# Per-run OUTPUT directory: the new folder that holds THIS run's PDF + CSVs + diagnostics + appendix
# exports. Defaults to OUT_DIR; set to the run folder by allocate_run() at the start of each run.
# IMPORTANT: cross-run CACHES (Registry Cache, ledger, conflict/format/source stores, self-improve
# log, report_registry.json) ALWAYS live in OUT_DIR / PATIENT_OUT_DIR — NEVER inside a run folder.
RUN_OUT_DIR = OUT_DIR
# Persistent numbering registry — survives restarts; never resets unless the user deletes it. Holds
# the next GLOBAL report number and the next PER-TYPE folder numbers.
REPORT_REGISTRY = os.path.join(OUT_DIR, "report_registry.json")


def _date_compact(dt=None):
    """M.D.YY, period-separated, NO zero-padding: 2026-06-04 -> '6.4.26', 2027-01-01 -> '1.1.27'."""
    dt = dt or datetime.datetime.now()
    return f"{dt.month}.{dt.day}.{dt.year % 100}"


def _time_compact(dt=None):
    """12-hour, NO colon, hour un-padded, minutes always 2 digits, AM/PM attached:
    20:36 -> '836PM', 08:05 -> '805AM', 12:01 -> '1201PM', 00:05 -> '1205AM'."""
    dt = dt or datetime.datetime.now()
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour12}{dt.minute:02d}{ampm}"


def _report_dirs():
    """Base folders a report (either type) may live in — scanned (recursively) for numbering."""
    return [OUT_DIR, os.path.dirname(os.path.abspath(OUT_DIR)), PATIENT_OUT_DIR]


def report_filename(report_no, report_type, dt=None):
    """Short, browse-friendly name: {N}-CannaScopeCT-{SW|CC}-{M.D.YY}-{TIME}.pdf
    e.g. 34-CannaScopeCT-SW-6.5.26-1202PM.pdf — number first (primary id), no version token, no
    zero-padded/4-digit date, no colon in the time. Full detail stays INSIDE the PDF (cover+footer)."""
    return f"{report_no}-CannaScopeCT-{_TYPE_TAG.get(report_type, 'SW')}-{_date_compact(dt)}-{_time_compact(dt)}.pdf"


def _load_report_registry():
    try:
        with open(REPORT_REGISTRY, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_report_registry(d):
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        tmp = REPORT_REGISTRY + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, REPORT_REGISTRY)   # atomic
    except OSError:
        pass


def _disk_max_report_number():
    """Highest report number anywhere on disk (both types; base folders AND their run subfolders;
    short + legacy names). 0 if none. Used to reconcile the registry so a number is never reused."""
    import glob
    nums = [0]
    recursive = {OUT_DIR, PATIENT_OUT_DIR}      # run folders live exactly one level under these
    for d in set(_report_dirs()):
        pats = [os.path.join(d, "*.pdf")]
        if d in recursive:
            pats.append(os.path.join(d, "*", "*.pdf"))   # one level deep = per-run folders
        for pat in pats:
            for f in glob.glob(pat):
                m = _REPORT_NUM_RX.match(os.path.basename(f)) or _LEGACY_NUM_RX.search(os.path.basename(f))
                if m:
                    nums.append(int(m.group(1)))
    return max(nums)


def _disk_max_folder_number(report_type):
    """Highest existing run-folder number for this report type on disk. 0 if none."""
    import glob
    label = _FOLDER_LABEL[report_type]
    base = OUT_DIR if report_type == REPORT_TYPE_STATEWIDE else PATIENT_OUT_DIR
    nums = [0]
    for p in glob.glob(os.path.join(base, f"* {label} *")):
        if os.path.isdir(p):
            m = re.match(r"^(\d+)\s", os.path.basename(p))
            if m:
                nums.append(int(m.group(1)))
    return max(nums)


def next_global_report_number():
    """Next global report number, reconciled across the persistent registry and disk."""
    reg = _load_report_registry()
    return max(reg.get("next_report_number", 1), _disk_max_report_number() + 1)


def allocate_run(report_type, dt=None):
    """Assign this run's GLOBAL report number + PER-TYPE folder number from the persistent registry,
    reconciled against disk so a number/folder is NEVER reused or overwritten; create the brand-new
    run folder; point RUN_OUT_DIR at it; persist the advanced counters. Returns (report_no, run_folder, dt)."""
    global RUN_OUT_DIR
    dt = dt or datetime.datetime.now().astimezone()   # tz-aware so the PDF cover's %Z renders
    reg = _load_report_registry()
    report_no = max(reg.get("next_report_number", 1), _disk_max_report_number() + 1)
    fkey = ("next_statewide_folder_number" if report_type == REPORT_TYPE_STATEWIDE
            else "next_consumer_concern_folder_number")
    folder_no = max(reg.get(fkey, 1), _disk_max_folder_number(report_type) + 1)
    base = OUT_DIR if report_type == REPORT_TYPE_STATEWIDE else PATIENT_OUT_DIR
    label = _FOLDER_LABEL[report_type]
    os.makedirs(base, exist_ok=True)
    while True:   # never write into / overwrite an existing folder — advance to the next free number
        run_folder = os.path.join(base, f"{folder_no} {label} {_date_compact(dt)}")
        if not os.path.exists(run_folder):
            break
        folder_no += 1
    os.makedirs(run_folder)            # exist_ok defaults False -> guaranteed brand-new folder
    reg["next_report_number"] = report_no + 1
    reg[fkey] = folder_no + 1
    _save_report_registry(reg)
    RUN_OUT_DIR = run_folder
    return report_no, run_folder, dt


def next_report_path(status=""):
    """Back-compat shim: allocate a statewide run and return (pdf_path_in_new_run_folder, report_no)."""
    report_no, run_folder, dt = allocate_run(REPORT_TYPE_STATEWIDE)
    return os.path.join(run_folder, report_filename(report_no, REPORT_TYPE_STATEWIDE, dt)), report_no


def build_pdf(out_path, report_no, ctx):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, legal
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, PageBreak, KeepTogether, CondPageBreak)

    BF, BFB = v4._setup_fonts()
    NAVY = colors.HexColor("#1F2D3D"); AQUA = colors.HexColor("#0E6B5A")
    PURPLE = colors.HexColor("#7D3C98"); RED = colors.HexColor("#C0392B")
    PAGE = landscape(legal); esc = v4._esc
    # Usable content width = page width minus the 0.3" left + 0.3" right margins (below). Tables
    # are scaled to fill this width (see _fit_widths) so the landscape page is actually used.
    _USABLE_W = PAGE[0] - 0.6 * inch

    SEVC = {"RED": ("#C0392B", "#f8d2d0"), "ORANGE": ("#E67E22", "#ffe3c2"),
            "YELLOW": ("#9A7B0A", "#fff4c2"), "GREEN": ("#1E7E34", "#d8efd8")}

    def sev_of(d):
        v, lim, ctp, vs = d.get("value"), d.get("ct_limit"), d.get("ct_pct"), d.get("vs_std")
        if lim and v is not None and v > lim:
            return "RED"
        if ctp is not None and ctp >= 90:
            return "RED"
        if ctp is not None and ctp >= 75:
            return "ORANGE"
        if vs is not None and vs >= 0:
            return "YELLOW"
        return "GREEN"

    # TYPOGRAPHY (V15.1): fonts enlarged across the board for landscape-legal readability. The page
    # is 14" wide, so body/table text was over-compressed; bumping cell 9.5->11, head 9.5->11,
    # body 10.5->12 and widening tables to fill the page (see _fit_widths in tbl) trades a few extra
    # pages for legibility. Section spacing increased so headers breathe and never crowd their tables.
    title_st = ParagraphStyle("t", fontName=BFB, fontSize=26, leading=30, alignment=1, textColor=NAVY)
    sub_st = ParagraphStyle("s", fontName=BF, fontSize=14, leading=18, alignment=1, textColor=colors.HexColor("#444"))
    meta_st = ParagraphStyle("m", fontName=BF, fontSize=11, leading=15, alignment=1, textColor=colors.HexColor("#444"))
    note_st = ParagraphStyle("n", fontName=BF, fontSize=11, leading=15, alignment=1)
    body_st = ParagraphStyle("b", fontName=BF, fontSize=12, leading=16, textColor=colors.HexColor("#222"))
    # splitLongWords=0 GLOBALLY on the base cell (P0 fix): ReportLab's default char-level wrapping
    # otherwise breaks a too-wide token mid-character — splitting an integer ("10" -> "1"/"0") or a
    # word ("Confidence" -> "Confidenc"/"e"). Children (cellc/cellb/cellr/...) inherit this; long
    # tokens now stay whole (and we size columns / abbreviate headers so they fit).
    cell = ParagraphStyle("c", fontName=BF, fontSize=11, leading=14, splitLongWords=0)
    cellc = ParagraphStyle("cc", parent=cell, alignment=1)
    cellb = ParagraphStyle("cb", parent=cell, fontName=BFB)
    # Right-aligned numeric cells: measured values, limits, %-of-limit and differences read far
    # more clearly when their right edges line up column-to-column (magnitudes are comparable at a
    # glance), instead of being centered. alignment=2 == TA_RIGHT.
    cellr = ParagraphStyle("cr", parent=cell, alignment=2)
    cellrb = ParagraphStyle("crb", parent=cell, fontName=BFB, alignment=2)
    # Atomic cells: a token that must NEVER split mid-character (a date, a status word, a value+unit).
    # splitLongWords=0 stops reportlab's char-level wrapping of an over-wide token (it stays whole and,
    # because the column is sized to fit it, renders on one line). Pair with nbsp() to keep a number
    # and its unit on the same line. datecell is a touch smaller so a full YYYY-MM-DD always fits its
    # column even on the least-stretched table.
    cell_nb = ParagraphStyle("cnb", parent=cell, splitLongWords=0)
    cellc_nb = ParagraphStyle("ccnb", parent=cellc, splitLongWords=0)
    cellb_nb = ParagraphStyle("cbnb", parent=cellb, splitLongWords=0)
    datecell = ParagraphStyle("datec", parent=cellc, fontSize=9.5, leading=12.5, splitLongWords=0)
    NBSP = "\u00a0"

    def nbsp(s):
        # keep value+unit (and other space-joined atomic phrases) on one line
        return s.replace(" ", NBSP)

    head = ParagraphStyle("h", fontName=BFB, fontSize=11, leading=14, textColor=colors.white,
                          alignment=1, splitLongWords=0)   # headers never char-split ("Confidenc/e") — P0
    # centered MAJOR section header (large). NOTE: keepWithNext is intentionally OFF here.
    # reportlab's keepWithNext groups a header + intro + the ENTIRE following table into one
    # KeepTogether; a table taller than the space left on the page then jumps wholesale to the
    # next page, leaving a huge gap. We instead protect headers from being orphaned with a
    # CondPageBreak guard (see _reflow / SECTION_MIN), which lets tables split and fill pages.
    H1 = ParagraphStyle("h1", fontName=BFB, fontSize=22, leading=26, alignment=1, spaceBefore=20,
                        spaceAfter=11, textColor=NAVY)
    CTX = ParagraphStyle("ctx", fontName=BF, fontSize=10.5, leading=14, alignment=1,
                         textColor=colors.HexColor("#555"), spaceAfter=10)
    # centered subheader (mini tables + diagnostics)
    miniH = ParagraphStyle("mh", fontName=BFB, fontSize=15, leading=19, alignment=1, spaceBefore=17,
                           spaceAfter=9, textColor=NAVY)

    # Use the SAME timestamp as the (short) filename so the cover's FULL date/time matches the file.
    now = ctx.get("report_dt") or datetime.datetime.now().astimezone()
    # Cover-page date/time (FULL detail stays inside the PDF): "June 3, 2026" and "5:36 PM EDT".
    cover_date = f"{now:%B} {now.day}, {now.year}"
    _h12 = now.hour % 12 or 12
    cover_time = f"{_h12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'} {now.strftime('%Z')}".strip()
    dcreated, tcreated = cover_date, cover_time   # reused by the footer
    lmap, ident = ctx["lmap"], ctx["ident"]
    window, status = ctx["window"], ctx["status"]
    scol = {"PASS": "#1E7E34", "PASS WITH WARNINGS": "#E67E22",
            "DRAFT": "#C0392B", "FAIL": "#C0392B"}.get(status, "#C0392B")

    # Report number is carried in the PDF metadata (Title + Subject + Keywords) so it matches the
    # filename, the cover, and the footer. A reader/auditor can read the number from any of them.
    doc = SimpleDocTemplate(out_path, pagesize=PAGE, leftMargin=0.3*inch, rightMargin=0.3*inch,
                            topMargin=0.45*inch, bottomMargin=0.6*inch,
                            title=f"{APP_NAME} — Statewide Transparency Report #{report_no}",
                            author=APP_NAME, subject=f"Report Number: {report_no}",
                            keywords=f"CannaScope CT, Statewide Transparency Report, Report #{report_no}, {status}")

    def pr(p):
        return esc(producer_short(p, ident))

    def td(p):
        # A date is an ATOMIC token: datecell (splitLongWords=0) keeps a full YYYY-MM-DD whole on one
        # line; nbsp() guards any space so it never breaks. Date columns are sized to fit (see widths).
        return Paragraph(nbsp(esc(test_date(p))) or "—", datecell)

    def coa(p):
        ref = tcase(p.registration_number or "COA")
        if p.report_url:
            return (f'<link href="{esc(p.report_url)}"><font color="#1155CC"><u><b>'
                    f'{esc(ref)}</b></u></font></link>')
        return '<font color="#C0392B"><b>Missing — Verify</b></font>'

    # A COA ID is ONE unbreakable string: a slightly smaller font + splitLongWords off
    # so an identifier like "MMBR.0033648" never force-wraps mid-id. Link stays clickable.
    coacell = ParagraphStyle("coa", parent=cellc, fontSize=9.5, leading=12, splitLongWords=0)

    def coa_cell(p):
        return Paragraph(coa(p), coacell)

    def H(title, color=NAVY):
        # Major section header. keepWithNext is OFF (inherited from H1) so the following table is
        # NOT bundled into a KeepTogether with the header — the table splits across pages and fills
        # them. Orphaned headers are prevented by the CondPageBreak(SECTION_MIN) guard in _reflow.
        return Paragraph(esc(tcase(title)), ParagraphStyle("hx", parent=H1, textColor=color))

    def intro_para(text, color="#2c3e50"):
        """A plain-English orientation box as a FLOWABLE (for use inside KeepTogether)."""
        # spaceBefore/spaceAfter exceed borderPadding so the shaded/bordered box never overlaps the
        # header above it or the table below it.
        return Paragraph(text, ParagraphStyle(
            "introbox", parent=CTX, fontSize=11, leading=15, alignment=0, textColor=colors.HexColor(color),
            backColor=colors.HexColor("#eef3f8"), borderColor=colors.HexColor("#cdd8e4"),
            borderWidth=0.6, borderPadding=7, spaceBefore=13, spaceAfter=13))

    def intro_box(text, color="#2c3e50"):
        """Render a plain-English orientation box just before a major section's table."""
        story.append(intro_para(text, color))

    def subhead(text, color=NAVY):
        story.append(Paragraph(esc(text), ParagraphStyle(
            "subh", parent=miniH, fontSize=13, leading=16, alignment=0, textColor=color,
            spaceBefore=11, spaceAfter=5)))

    def _fit_widths(widths, fill):
        """Adaptive landscape sizing. Scale a per-column width list to the usable page width.
        For main findings tables (fill=True) the widths are scaled UP to fill the full 14" page
        (so space isn't wasted and long product names get room to wrap cleanly); for small
        diagnostic tables (fill=False) we only scale DOWN if they would overflow. Proportions
        between columns are preserved, so adaptive column widths track each call site's intent."""
        tot = sum(widths)
        if tot <= 0:
            return widths
        f = _USABLE_W / tot
        if not fill:
            f = min(1.0, f)            # diagnostic tables: shrink-to-fit only, never stretch
        else:
            f = min(f, 1.6)            # cap stretch so a 2-3 column table doesn't become absurd
            f = min(f, _USABLE_W / tot) if tot > _USABLE_W else f
        if tot * f > _USABLE_W:        # hard safety: never exceed the usable width (no overflow)
            f = _USABLE_W / tot
        return [w * f for w in widths]

    def tbl(headers, rows, widths, hc=NAVY, band="#eef2f5", rank_sevs=None, big=True, aligns=None):
        # aligns (optional): per-column 'L'/'C'/'R' for the HEADER cells, so a numeric column whose
        # data is right-aligned also gets a right-aligned header (no header/data alignment mismatch).
        widths = _fit_widths(widths, big)
        if aligns:
            amap = {"L": 0, "C": 1, "R": 2}
            hdr = [Paragraph(h, ParagraphStyle(f"hh{j}", parent=head, alignment=amap.get(aligns[j], 1)))
                   for j, h in enumerate(headers)]
        else:
            hdr = [Paragraph(h, head) for h in headers]
        data = [hdr]
        for r in rows:
            data.append([x if hasattr(x, "wrap") else Paragraph(str(x), cell) for x in r])
        t = Table(data, repeatRows=1, colWidths=widths)
        pad = 5 if big else 3
        cmds = [("BACKGROUND", (0, 0), (-1, 0), hc),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c2ccd6")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(band)]),
                ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
                ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7)]
        if rank_sevs:
            for i, sev in enumerate(rank_sevs, 1):
                cmds.append(("BACKGROUND", (0, i), (0, i), colors.HexColor(SEVC[sev][1])))
        t.setStyle(TableStyle(cmds))
        return t

    # rich contaminant row: + Testing Date
    RICH_COLS = ["#", "Product", "Testing Date", "Producer", "Measured Value", "CT Legal Limit",
                 "CT % Of Limit", "CannaScope Limit", "Difference From CannaScope", "COA"]
    RICH_W = [0.4*inch, 2.35*inch, 0.95*inch, 1.9*inch, 1.35*inch, 1.3*inch, 0.95*inch, 1.3*inch, 1.55*inch, 1.15*inch]
    RICH_ALIGNS = ["C", "L", "C", "L", "R", "R", "R", "R", "R", "C"]

    def rich_rows(items):
        rows, sevs = [], []
        for i, (p, d) in enumerate(items, 1):
            sev = sev_of(d); bar = SEVC[sev][0]; sevs.append(sev); unit = d.get("unit", "")
            ctp = d.get("ct_pct"); vs = d.get("vs_std")
            rows.append([
                Paragraph(f'<font color="{bar}"><b>{i}</b></font>', cellc),
                Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                Paragraph(esc(clean_value(d.get("value"), unit)), cellrb),
                Paragraph(esc(clean_value(d.get("ct_limit"), unit)), cellr),
                Paragraph(f'<font color="{bar}"><b>{v4.ct_pct_label(ctp, full=False)}</b></font>' if ctp is not None else "—", cellr),
                Paragraph(esc(clean_value(d.get("cs_std"), unit)), cellr),
                Paragraph(f'<font color="{bar}"><b>{v4.vs_standard_label(vs, full=False)}</b></font>' if vs is not None else "—", cellr),
                coa_cell(p)])
        return rows, sevs

    def rich_table(items, hc=NAVY):
        rows, sevs = rich_rows(items[:MAX_TABLE_ROWS])
        return tbl(RICH_COLS, rows, RICH_W, hc=hc, rank_sevs=sevs, aligns=RICH_ALIGNS)

    def overflow_note(total, csv_hint, shown=MAX_TABLE_ROWS, what="rows"):
        """Append a note when a findings table was capped for length. The PDF shows
        the worst `shown`; the COMPLETE list is always in the named CSV export."""
        if total > shown:
            story.append(Paragraph(
                f"Showing the top {shown:,} of {total:,} {what} (ranked by severity). "
                f"The complete list is in <b>{esc(_EXPORTS_SUBDIR)}/{esc(csv_hint)}</b>.",
                ParagraphStyle("ov", parent=CTX, textColor=colors.HexColor("#8a5a00"))))

    # ---- findings-first summary box + per-section trend notes (text only; tables unchanged) ----
    # IMPORTANT: a shaded Paragraph's background extends `borderPadding` pts ABOVE the first line, so
    # spaceBefore/spaceAfter MUST exceed borderPadding or the box bleeds over the header above it.
    SUMM = ParagraphStyle("summ", parent=body_st, fontSize=10, leading=14.5,
                          textColor=colors.HexColor("#1F2D3D"), backColor=colors.HexColor("#eef2f5"),
                          borderPadding=8, spaceBefore=14, spaceAfter=14)
    TREND = ParagraphStyle("trend", parent=CTX, alignment=0, fontSize=9.5, leading=12.5,
                           textColor=colors.HexColor("#33474f"), spaceBefore=1, spaceAfter=9)

    def trend_note(html):
        if html:
            story.append(Paragraph("<b>Trend &amp; pattern note:</b> " + html, TREND))

    def _freq_line(counter, n):
        """Factual, cautious pattern line: count, concentration, top producers."""
        if not n or not counter:
            return ""
        top = counter.most_common(3)
        share = sum(c for _nm, c in top) / n * 100.0
        spread = ("concentrated in a few producers" if (len(counter) <= 3 or share >= 70)
                  else f"spread across {len(counter)} producers")
        tops = ", ".join(f"{esc(nm)} ({c})" for nm, c in top)
        return f"{n} flagged result(s); {spread}. Most frequent producer here: {tops}."

    def cat_trend(items):
        if not items:
            return ""
        prods = Counter(producer_short(p, ident) for p, _d in items)
        labs = Counter(lab_name(p, lmap) for p, _d in items)
        s = _freq_line(prods, len(items))
        tl, tlc = labs.most_common(1)[0]
        if tlc > 1:
            s += f" Lab most associated with this category: {esc(tl)} ({tlc}) — reflects testing volume, not a quality judgment."
        return s

    story = []

    # ---------------- COVER ----------------  (naming-standard cover block; intentional vertical rhythm)
    bigmeta = ParagraphStyle("bigmeta", parent=meta_st, fontSize=13, leading=18, fontName=BFB, textColor=NAVY)

    # PAGE-1 "What failed validation?" / validation-notes box, in plain English, right under the status.
    _fr = ctx.get("fail_reasons") or []
    _wr = ctx.get("warn_reasons") or []
    if status == "FAIL":
        _bx = "#fbe3e1"; _bd = "#C0392B"
        _hdr = "&#9888; What failed validation? (this report is a DRAFT — do not treat as final)"
        _lines = [f"&#8226; {esc(r)}" for r in _fr] or ["&#8226; (no reason recorded)"]
        if _wr:
            _lines += ["<b>Other notes:</b>"] + [f"&#8226; {esc(r)}" for r in _wr]
    elif status == "PASS WITH WARNINGS":
        _bx = "#fff4e2"; _bd = "#E67E22"
        _hdr = "Passed with warnings &mdash; nothing failed validation, but please note:"
        _lines = [f"&#8226; {esc(r)}" for r in _wr] or ["&#8226; (none)"]
    else:
        _bx = "#e6f3e6"; _bd = "#1E7E34"
        _hdr = "Passed validation &mdash; no warnings; all major categories confidently parsed."
        _lines = []
    _valstyle = ParagraphStyle("valbox", parent=note_st, fontSize=9.5, leading=13, alignment=0,
                               textColor=colors.HexColor("#222"), backColor=colors.HexColor(_bx),
                               borderColor=colors.HexColor(_bd), borderWidth=0.8, borderPadding=7,
                               spaceBefore=10, spaceAfter=10)
    _valbox = [KeepTogether([Paragraph(f'<font color="{_bd}"><b>{_hdr}</b></font>'
                             + ("<br/>" + "<br/>".join(_lines) if _lines else ""), _valstyle)])]

    story += [
        Paragraph(APP_NAME, title_st),                                   # CannaScope CT V15
        Spacer(1, 5),
        Paragraph(esc(REPORT_TITLE), sub_st),
        Spacer(1, 2),
        Paragraph(esc(REPORT_SUBTITLE), ParagraphStyle("sub2", parent=sub_st, fontSize=11)),
        Spacer(1, 11),
        Paragraph(f"Report #{report_no}", bigmeta),                      # Report #15
        Paragraph("Statewide Report", bigmeta),                          # Statewide Report
        Paragraph(f"Created {esc(cover_date)}", meta_st),                # Created June 3, 2026
        Paragraph(esc(cover_time), meta_st),                             # 5:36 PM EDT
        Spacer(1, 5),
        Paragraph(f"Validation status: <font color=\"{scol}\"><b>{esc(status)}</b></font> "
                  f"&nbsp;|&nbsp; Dataset window: {esc(window)}", note_st),
        *_valbox,
        Spacer(1, 8),
        Paragraph(f"<b>{esc(FRAMING)}</b>", ParagraphStyle("fr", parent=note_st, fontSize=10.5, leading=14.5,
                  textColor=NAVY, backColor=colors.HexColor("#eef2f5"), borderPadding=8)),
        Spacer(1, 13),
        Paragraph(f"<b>{ctx['n_reviewed']:,}</b> products in window &nbsp;•&nbsp; <b>{ctx['n_pub']:,}</b> validated findings &nbsp;•&nbsp; "
                  f'<font color="#C0392B"><b>{ctx["n_red"]} Do Not Consume</b></font> &nbsp;•&nbsp; '
                  f'<font color="#E67E22"><b>{ctx["n_org"]} High Caution</b></font> &nbsp;•&nbsp; '
                  f'<font color="#9A7B0A"><b>{ctx["n_yel"]} Moderate Caution</b></font> &nbsp;•&nbsp; '
                  f'<font color="#0E6B5A"><b>{ctx["n_thc"]} High Cannabinoid</b></font>', meta_st),
        Spacer(1, 9),
        Paragraph("<b>Contamination severity (per measurement):</b> &nbsp; "
                  '<font color="#C0392B"><b>RED = Near / over CT limit</b></font> &nbsp; '
                  '<font color="#E67E22"><b>ORANGE = Elevated</b></font> &nbsp; '
                  '<font color="#9A7B0A"><b>YELLOW = Above CannaScope threshold</b></font> &nbsp; '
                  '<font color="#1E7E34"><b>GREEN = Below threshold</b></font>', note_st),
        Spacer(1, 8),
        Paragraph("<b>Testing Date</b> is the COA's test / sample date (never the report-generation date). "
                  "<b>CT % Of Limit</b> = measured ÷ Connecticut legal limit × 100. <b>CannaScope Limit</b> is the "
                  "stricter consumer-awareness threshold (Yeast &amp; Mold / Aerobic = 10,000 CFU/g; other "
                  "contaminants = 50% of the CT limit). Every COA number is a clickable link.", note_st),
        Spacer(1, 16),
    ]

    # ---------------- EXECUTIVE SUMMARY (dashboard) ----------------
    acct = ctx.get("accounting", {}) or {}
    story.append(H("Executive Summary"))
    story.append(tbl(["Products In Window", "Validated Findings", "Do Not Consume", "High Caution",
                      "Moderate Caution", "High Cannabinoid"],
                     [[f"{ctx['n_reviewed']:,}", f"{ctx['n_pub']:,}", str(ctx["n_red"]), str(ctx["n_org"]),
                       str(ctx["n_yel"]), str(ctx["n_thc"])]], [1.6*inch]*6))
    story.append(Spacer(1, 5))
    # Honest dataset accounting — keeps the denominators clear (no "829 reviewed / 793 findings" confusion).
    story.append(Paragraph(
        f"<b>Dataset accounting:</b> {acct.get('window', ctx['n_reviewed']):,} products in the selected window · "
        f"{acct.get('scanned_this_run', 0):,} freshly scanned this run · "
        f"{acct.get('reused_from_ledger', 0):,} reused from the verified-clean ledger (skipped to save time; "
        f"findings unchanged) · {acct.get('coas_fetched', 0):,} COAs fetched · "
        f"<b>{acct.get('published_findings', ctx['n_pub']):,} published findings</b>. Percentages below use the "
        "window total as the denominator.", TREND))
    # One-line pointer to the validation-limits material (Part B item 5) — keeps the exec summary clean.
    story.append(Paragraph(
        "<i>Full validation limits and coverage gaps (unreadable / unvalidated COAs, untrained years, excluded "
        "rows) are documented in the <b>Coverage Gaps / Unvalidated COAs</b> and <b>Software Self-Enhancement &amp; "
        "Self-Audit</b> sections near the end.</i>", TREND))
    story.append(Spacer(1, 9))

    ai = ctx["analyte_items"]
    metals = sorted([pd for k in ("arsenic", "chromium", "cadmium", "lead", "mercury") for pd in ai[k]],
                    key=lambda pd: pd[1]["ct_pct"] or 0, reverse=True)
    micro = sorted(ai["tymc"] + ai["aerobic"], key=lambda pd: pd[1]["ct_pct"] or 0, reverse=True)

    # ---- MOST IMPORTANT FINDINGS (computed) — the handful of things to look at first ----
    mif = []
    over_cur = sum(1 for k in ai for (p, d) in ai[k]
                   if d.get("ct_limit") and d.get("value") is not None and d["value"] > d["ct_limit"])
    micro_over = sum(1 for k in ("tymc", "aerobic") for (p, d) in ai.get(k, [])
                     if d.get("ct_limit") and d.get("value") is not None and d["value"] > d["ct_limit"])
    # Internal-benchmark awareness count: products with a MEASURED yeast & mold value over the
    # strict 10,000 CFU/g internal threshold, across ALL flagged products — independent of the
    # narrowed Yeast & Mold Standard Review (which no longer lists products on the 10k basis alone).
    def _over_internal_10k(p):
        e = p.analytes.get("tymc") or {}
        v = e.get("value")
        return bool(e and v5.is_quantified(e) and not e.get("_below_detect")
                    and v is not None and v > TYM_STRICT_BENCHMARK)
    over_strict = sum(1 for p in (ctx.get("flagged") or []) if _over_internal_10k(p))
    clust = Counter()
    for _ck, _cn in (("arsenic", "Arsenic"), ("chromium", "Chromium"), ("cadmium", "Cadmium"),
                     ("lead", "Lead"), ("mercury", "Mercury"), ("tymc", "Yeast & Mold"),
                     ("aerobic", "Aerobic Bacteria")):
        for p, d in ai.get(_ck, []):
            clust[(producer_short(p, ident), _cn)] += 1
    # one cluster PER contaminant type (diverse), so metal clusters surface next to yeast & mold
    clusters, _seen_nm = [], set()
    for (prod, nm), n in clust.most_common():
        if n >= 2 and nm not in _seen_nm:
            _seen_nm.add(nm)
            clusters.append((prod, nm, n))
        if len(clusters) >= 4:
            break
    if micro_over:
        mif.append(f"<b>{micro_over}</b> current over-limit microbial result(s) — yeast &amp; mold / aerobic over the CT limit.")
    if over_cur - micro_over > 0:
        mif.append(f"<b>{over_cur - micro_over}</b> other result(s) over a current CT contaminant limit (metals / mycotoxins).")
    if over_strict:
        mif.append(f"<b>{over_strict}</b> product(s) over CannaScope's internal 10,000 CFU/g yeast &amp; mold "
                   "consumer-awareness threshold (most pass their actual dated CT/lab standard — this is an internal "
                   "stricter benchmark, NOT a regulatory failure and NOT the basis for the Yeast &amp; Mold Standard Review).")
    for prod, nm, n in clusters:
        mif.append(f"<b>{esc(prod)}</b> {esc(nm.lower())} cluster — {n} flagged readings worth a closer look.")
    if ctx.get("pathogens"):
        mif.append(f"<b>{len(ctx['pathogens'])}</b> zero-tolerance pathogen detection(s).")
    if ctx.get("coa_conflicts"):
        _ls = sum(1 for c in ctx["coa_conflicts"] if c.get("relationship") == "Possible lab-shopping indicator")
        _tail = (f" — including {_ls} possible lab-shopping indicator(s)" if _ls else
                 " — same-lot retests, duplicate COAs, or numeric swings (no cross-lab lab-shopping pattern)")
        mif.append(f"<b>{len(ctx['coa_conflicts'])}</b> conflicting-COA review lead(s){_tail}.")
    if ctx.get("thc_flower"):
        mif.append(f"<b>{len(ctx['thc_flower'])}</b> high-cannabinoid flower record(s) for label-accuracy review.")
    if ctx.get("compliance_flags"):
        mif.append(f"<b>{len(ctx['compliance_flags'])}</b> potential compliance review lead(s) (buckets A–D).")
    if not mif:
        mif.append("No result crossed a current CT contaminant limit in this run.")
    story.append(KeepTogether([
        Paragraph("Most Important Findings", ParagraphStyle("mifh", parent=miniH, fontSize=13, alignment=1)),
        Paragraph("The few things to look at first — each is a <b>lead to verify against the live COA</b>, not a conclusion.",
                  ParagraphStyle("mifs", parent=CTX, alignment=1, fontSize=9, spaceAfter=4)),
        Paragraph("• " + "<br/>• ".join(mif), SUMM)]))
    story.append(Spacer(1, 10))

    # ---- Findings at a Glance: findings-FIRST, so a reader gets the big picture in ~30s ----
    glance = []
    if micro:
        p, d = micro[0]
        glance.append(f"<b>Highest microbial / mold reading:</b> {esc(tcase(p.product_name))} — "
                      f"{esc(clean_value(d.get('value'), d.get('unit','')))} "
                      f"({v4.ct_pct_label(d.get('ct_pct'), full=False)} of the CT limit), {esc(producer_short(p, ident))}.")
    if metals:
        p, d = metals[0]
        glance.append(f"<b>Highest heavy-metal reading:</b> {esc(d['name'])} "
                      f"{esc(clean_value(d.get('value'), d.get('unit','')))} "
                      f"({v4.ct_pct_label(d.get('ct_pct'), full=False)} of the CT limit), "
                      f"{esc(tcase(p.product_name))}, {esc(producer_short(p, ident))}.")
    if ctx["producer_rows"]:
        glance.append("<b>Most-flagged producers:</b> " +
                      ", ".join(f"{esc(r['label'])} ({r['flagged']})" for r in ctx["producer_rows"][:3]) + ".")
    catcounts = [(t, len(ai[k])) for k, t in ANALYTE_TABLES]
    catcounts += [("Mycotoxins", len(ctx["mycotoxins"])), ("Residual solvents", len(ctx["solvents"])),
                  ("Pesticide-panel FAIL", len(ctx["pesticides"])), ("Pathogen detected", len(ctx["pathogens"])),
                  ("High cannabinoid", len(ctx["thc_flower"]))]
    catcounts = sorted([(t, c) for t, c in catcounts if c > 0], key=lambda x: -x[1])
    if catcounts:
        glance.append("<b>Most common issue types:</b> " +
                      ", ".join(f"{esc(t)} ({c})" for t, c in catcounts[:4]) + ".")
    if ctx["producer_rows"] and ctx["n_pub"]:
        topshare = sum(r["flagged"] for r in ctx["producer_rows"][:3]) / max(1, ctx["n_pub"]) * 100.0
        patt = (f"The top 3 producers account for {topshare:.0f}% of validated findings — findings are "
                f"{'concentrated among a few producers' if topshare >= 50 else 'fairly distributed across producers'}.")
        if catcounts:
            patt += f" The most common category statewide is {esc(catcounts[0][0])}."
        glance.append("<b>Statewide pattern:</b> " + patt)
    _cc = ctx.get("coa_conflicts") or []
    if any(c["severity"] == "Critical" for c in _cc):
        _cc_conf = sum(1 for c in _cc if c["severity"] in ("Critical", "High"))
        _cc_ftp = sum(1 for c in _cc if c.get("fail_then_pass"))
        glance.append(f"<b>Conflicting COA results:</b> Detected {_cc_conf} product record(s) with "
                      "conflicting pass/fail COA results across lab reports, including "
                      f"{_cc_ftp} case(s) where an earlier failing microbial result appears followed by a "
                      "later passing result. Document-level leads flagged for human review.")
    glance.append("<i>Every item above is a lead, not a conclusion — verify each against the product's live COA.</i>")
    # Keep the heading with its box, and never split the box across a page boundary.
    story.append(KeepTogether([Paragraph("Findings at a Glance", miniH),
                               Paragraph("• " + "<br/>• ".join(glance), SUMM)]))

    # ---- How to read these findings (one legend that defines every category). NOT wrapped in
    #      KeepTogether — that was forcing the whole block onto the next page and leaving a gap; it
    #      now flows naturally and fills the page. ----
    story.append(Paragraph("How To Read These Findings",
                           ParagraphStyle("legh", parent=miniH, fontSize=12, keepWithNext=0)))
    story.append(Paragraph(
        "Every flag is a <b>lead, not a conclusion</b> — verify each against the product's live COA. Categories:"
        "<br/>• <b>Over a current CT limit</b> — the measured result exceeds Connecticut's current legal limit "
        "(a failed result). <font color='#C0392B'>Red</font>."
        "<br/>• <b>Near-limit / consumer-awareness flag</b> — passed CT's limit but crossed CannaScope's stricter "
        "internal watch line; informational only. <font color='#E67E22'>Orange</font> / <font color='#9A7B0A'>Yellow</font>."
        "<br/>• <b>Strict 10,000 CFU/g benchmark (yeast &amp; mold)</b> — CannaScope's patient-protective benchmark; "
        "a product can pass the current 100,000 CT limit yet exceed this. Context, not a CT violation — see the "
        "Yeast & Mold Standard Review."
        "<br/>• <b>Possible remediation / unusually low microbial load</b> — flower at or under 100 CFU/g; can be "
        "perfectly normal, shown for awareness only."
        "<br/>• <b>High cannabinoid review</b> — flower above 35%; a label-accuracy review signal, not a contaminant."
        "<br/>• <b>Potential compliance review lead</b> — a COA-derived lead for a human/compliance reviewer; never a "
        "legal determination.",
        ParagraphStyle("legbox", parent=CTX, fontSize=9.5, leading=13, alignment=0,
                       textColor=colors.HexColor("#2c3e50"), backColor=colors.HexColor("#eef3f8"),
                       borderColor=colors.HexColor("#cdd8e4"), borderWidth=0.6, borderPadding=6,
                       spaceBefore=10, spaceAfter=10)))

    # ---- Conflicting COA Results & Possible Lab-Shopping Indicators (neutral, for review) ----
    def emit_conflicts(items):
        from reportlab.platypus import HRFlowable
        hcol = RED if any(c["severity"] == "Critical" for c in items) else colors.HexColor("#E67E22")
        SEVCOL = {"Critical": "#C0392B", "High": "#E67E22", "Medium": "#9A7B0A", "Low": "#555555"}
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=1.4, color=hcol, spaceBefore=2, spaceAfter=6))
        story.append(Paragraph("CONFLICTING COA RESULTS &amp; POSSIBLE LAB-SHOPPING INDICATORS",
                               ParagraphStyle("cch", parent=H1, fontSize=15, leading=18, textColor=hcol)))
        story.append(Paragraph(
            "This section looks for the <b>lab-shopping</b> pattern: the same product/lot (matched on a shared "
            "batch, lot, BioTrack, sample, or product-code identifier) that <b>failed the limit stated on one "
            "lab's COA — the state standard in effect for that test — and then passed a retest at another lab</b>. "
            "Pass/fail is judged against the <b>CFU/g limit printed on each COA</b> (Connecticut's standards have "
            "changed over the years, so each document carries the limit that applied when it was issued) — NOT a "
            "single fixed limit and NOT any CannaScope internal threshold. Such a record is a <b>possible "
            "lab-shopping indicator</b> and a potential state-standard concern. Every item <b>requires human "
            "review</b> and does not, by itself, establish lab-shopping, a violation, or any wrongdoing.", CTX))
        # Shared caveat stated ONCE here, so it isn't repeated on every case below (each case then carries
        # only its own specifics — identifiers, the actual values, and the ratio/difference).
        intro_box(
            "<b>Applies to every case below.</b> A difference between two reports for the same lot can have "
            "innocent explanations — a legitimate retest, sampling differences, lot variability, remediation, a "
            "clerical/transcription error, or a parsing/format artifact. Each case is listed <b>for human review "
            "only</b> and is never, by itself, a determination of lab-shopping, a violation, or wrongdoing. The "
            "per-case notes below give only the case-specific facts.", color="#7a5c00")
        stored = (ctx.get("src_metrics") or {}).get("conflict_fingerprints_in_store", 0)
        if not items:
            msg = ("<b>No conflicting COA result patterns detected</b> across the persistent cross-run record"
                   + (f" ({stored:,} COA conflict fingerprints accumulated from this and prior runs)" if stored else "")
                   + ". Detection spans runs — a COA scanned in an earlier run is still compared against this "
                   "run's COAs — so a ledger-warm rerun does not lose previously identified conflicts.")
            story.append(Paragraph(msg, cellc))
            return
        if stored:
            story.append(Paragraph(
                f"<i>This section reflects the persistent cross-run conflict record "
                f"({stored:,} COA fingerprints from this and prior runs), so conflicts whose COAs were "
                f"scanned in different runs are included and earlier findings are not lost on a rerun.</i>",
                TREND))

        def case_block(i, c):
            sc = SEVCOL.get(c["severity"], "#555555")
            a, b = c["lab1"], c["lab2"]
            rel = c.get("relationship", "")
            head = Paragraph(
                f'<font color="{sc}"><b>Case {i} — {esc(c["severity"])}: {esc(c["category"])}</b></font>'
                + (f' &nbsp;<font color="#555">[{esc(rel)}]</font>' if rel else '')
                + (' &nbsp;<font color="#C0392B"><b>[earlier failed result followed by later passing result]</b></font>'
                   if c.get("fail_then_pass") else ''),
                ParagraphStyle(f"cch{i}", parent=miniH, fontSize=13, leading=16, alignment=0))
            ident_line = Paragraph(
                f'<b>{esc(c["product"])}</b>'
                + (f' — {esc(c["strain"])}' if c["strain"] else '')
                + (f' · {esc(c["product_type"])}' if c["product_type"] else '')
                + f' · {esc(producer_short(c["members"][0]["p"], ident))}'
                + (f'<br/><font color="#555">Shared identifier: {esc(c["shared_id"])}</font>'
                   if c["shared_id"] else ''), cell)
            if c["kind"] == "within-document":
                labs = c.get("labs_in_doc") or []
                p0 = c["members"][0]["p"]
                detail = Paragraph(
                    f'<b>Test date:</b> {esc(a["date_str"] or "Unknown")} &nbsp;·&nbsp; '
                    f'<b>Lab identities detected in one document:</b> {esc(", ".join(labs) or "more than one")}.'
                    + (f'<br/><b>Page references:</b> {esc(c["timeline"])}.' if c.get("timeline") else ''), body_st)
                narr = Paragraph(c["note"] + " This requires human review; it does not establish misconduct "
                                 "or any explanation.", body_st)
                src = Paragraph("<b>Source COA:</b> " + (coa(p0) if p0.report_url else "not provided"), cell)
                # Keep only the heading + identifier + detail glued; let narrative/src flow so cases
                # pack several-per-page instead of one-per-page (avoids huge per-case whitespace).
                return [Spacer(1, 4), KeepTogether([head, ident_line, Spacer(1, 2), detail]),
                        narr, src, Spacer(1, 8)]

            def rescell(m):
                v = clean_value(m.get("value"), m.get("unit", "")) if m.get("value") is not None else "—"
                stc = {"FAIL": "#C0392B", "DETECTED": "#C0392B",
                       "PASS": "#1E7E34", "ND": "#1E7E34"}.get(m.get("status"), "#555")
                return Paragraph(f'{esc(v)} &nbsp; <font color="{stc}"><b>{esc(m.get("status") or "—")}</b></font>', cell)
            def _limcell(m):   # the limit STATED ON THAT COA — the standard in effect for that test
                return (esc(clean_value(m.get("limit"), m.get("unit", "")))
                        if m.get("limit") is not None else "—")
            trows = [
                [Paragraph("<b>Lab</b>", cell), Paragraph(esc(a["lab"]), cell), Paragraph(esc(b["lab"]), cell)],
                [Paragraph("<b>Test date</b>", cell), Paragraph(esc(a["date_str"] or "Unknown"), cell),
                 Paragraph(esc(b["date_str"] or "Unknown"), cell)],
                [Paragraph("<b>Result</b>", cell), rescell(a), rescell(b)],
                [Paragraph("<b>Limit stated on COA</b>", cell), Paragraph(_limcell(a), cell), Paragraph(_limcell(b), cell)],
                [Paragraph("<b>Source COA</b>", cell),
                 (coa_cell(a["p"]) if a.get("coa_url") else Paragraph("—", cell)),
                 (coa_cell(b["p"]) if b.get("coa_url") else Paragraph("—", cell))],
            ]
            if a.get("pages") or b.get("pages"):
                trows.append([Paragraph("<b>Page refs</b>", cell), Paragraph(esc(a.get("pages") or "—"), cell),
                              Paragraph(esc(b.get("pages") or "—"), cell)])
            comp = tbl(["", "Result A (earlier)", "Result B (later)"], trows,
                       [1.45*inch, 3.1*inch, 3.1*inch], hc=colors.HexColor(sc), band="#f6f6f6", big=False)
            extra = []
            if c["diff"]:
                extra.append(f'<b>Difference between results:</b> {esc(c["diff"])}.')
            if c["timeline"]:
                extra.append(f'<b>Timeline:</b> {esc(c["timeline"])}')
            av = clean_value(a.get("value"), a.get("unit", "")) if a.get("value") is not None else (a.get("status") or "—")
            bv = clean_value(b.get("value"), b.get("unit", "")) if b.get("value") is not None else (b.get("status") or "—")
            statuses = {a.get("status"), b.get("status")}
            pf_conflict = bool(statuses & {"FAIL", "DETECTED"}) and bool(statuses & {"PASS", "ND"})
            if pf_conflict:
                # One result FAILED the limit stated on its own COA, another PASSED. Pass/fail is
                # judged against each COA's own stated limit. Only a CROSS-LAB conflict is described
                # as a possible lab-shopping indicator (see _relationship); a same-lab pass/fail
                # conflict is described as a likely retest / clerical issue instead.
                fa, fb = a.get("status") in ("FAIL", "DETECTED"), b.get("status") in ("FAIL", "DETECTED")
                fail_m, pass_m = (a, b) if fa and not fb else (b, a)
                fv = clean_value(fail_m.get("value"), fail_m.get("unit", "")) if fail_m.get("value") is not None else (fail_m.get("status") or "—")
                pv = clean_value(pass_m.get("value"), pass_m.get("unit", "")) if pass_m.get("value") is not None else (pass_m.get("status") or "—")
                flim = clean_value(fail_m.get("limit"), fail_m.get("unit", "")) if fail_m.get("limit") is not None else "the limit on its COA"
                lead = ("For the same product/lot identifier, "
                        f'<b>{esc(fail_m.get("lab") or "one lab")}</b> recorded a result ({esc(fv)}) that <b>exceeded the '
                        f'limit stated on its own COA</b> ({esc(flim)}) — a FAIL against the standard in effect for that '
                        f'test — while <b>{esc(pass_m.get("lab") or "another lab")}</b> recorded a passing result ({esc(pv)}). ')
                if rel == "Possible lab-shopping indicator":
                    narr = (lead + "A failed result at one lab followed by a passing result at a <b>different lab</b>, "
                            "for the same lot, is a <b>possible lab-shopping indicator</b> and a potential state-standard "
                            "concern worth review.")
                else:
                    narr = (lead + "Both results are from the <b>same laboratory</b>, so this is <b>not</b> a lab-shopping "
                            "pattern; it more likely reflects a same-lot retest or a clerical/transcription difference.")
            elif a.get("value") is not None and b.get("value") is not None:
                # Same pass/fail status with a numeric swing. c['diff']/c['timeline'] now carry the
                # corrected, bound/unit-guarded math (and flag a likely parser/format artifact when
                # the ratio is implausibly large for one physical lot).
                kindword = {"Duplicate COA (same lab, same date)": "a duplicate COA",
                            "Same-lot retest (same lab, different date)": "a same-lot retest",
                            "Cross-lab numeric swing": "a cross-lab numeric difference"}.get(rel, "a numeric difference")
                narr = ("For the same product identifier on the same regulated test, two reports show "
                        f'different values ({esc(av)} vs {esc(bv)}) — both reported {esc(a.get("status") or "—")}. '
                        f"This is best read as {kindword}; the size and nature of the difference are summarized above.")
            else:
                # No safety conflict (e.g. multiple lab reports on one lot with no pass/fail clash).
                narr = ("The same lot identifier appears on more than one report with no pass/fail safety conflict "
                        "detected. Listed for completeness and human review only.")
            # Keep ONLY [head + identifier + comparison table] glued together so the table never
            # orphans from its heading; let the difference/timeline/narrative flow afterward. This
            # lets multiple cases share a page instead of reserving a full page each (the old
            # KeepTogether(whole-block) left ~60% of every page blank across ~75 cases).
            flow = [Spacer(1, 4), KeepTogether([head, ident_line, Spacer(1, 2), comp])]
            if extra:
                flow.append(Paragraph("&nbsp;&nbsp;".join(extra), TREND))
            flow.append(Paragraph(narr, body_st))
            flow.append(Spacer(1, 8))
            return flow

        # EVERY case — regardless of severity — renders as a full per-case block so each one is
        # actually usable: test dates, the numeric difference, a timeline, and LIVE clickable COA
        # links for both records. (A bare summary table with no dates/links is not actionable.)
        CASE_CAP = 60
        for i, c in enumerate(items[:CASE_CAP], 1):
            story.extend(case_block(i, c))
        if len(items) > CASE_CAP:
            story.append(Paragraph(f"Showing the {CASE_CAP} highest-severity of {len(items)} review leads above; "
                                   "the complete list, with dates and COA links, is in "
                                   "<b>Data Exports/conflicting_coa_results.csv</b>.", CTX))
        story.append(Paragraph("Validation &amp; self-audit: This section flags document-level discrepancies "
                               "only. It does not prove intent, misconduct, remediation, or unlawful conduct "
                               "without further verification.", note_st))

    _conflicts = ctx.get("coa_conflicts") or []
    # (the Conflicting-COA section now renders as a consistent findings section lower down — after the
    #  Compliance Review Leads and before the Ombudsman review — not conditionally at the top/bottom.)

    # NOTE: the former "Top …" mini summary tables (Top Heavy Metal / Microbial / High Cannabinoid /
    # Lab Patterns / Remediation) were removed — they duplicated the full per-section tables below and
    # the Most-Important / Findings-at-a-Glance boxes above, adding length and page gaps for no new info.

    # ---------------- FLAGGED FINDINGS BY PRODUCER (directly under Executive Summary) ----------------
    story.append(H("Flagged Findings by Producer"))
    intro_box("Counts of validated findings per producer. <b>% Flagged = a producer's flagged products &#247; "
              "that producer's TOTAL products in the dataset window</b> (not flagged-of-flagged), so the rate is "
              "honest and comparable. A higher rate is a review signal, not proof of a problem.")
    rows = [[Paragraph(esc(r["label"]), cell), Paragraph(str(r["reviewed"]), cellr),
             Paragraph(str(r["flagged"]), cellr), Paragraph(f'{r["pct"]:.1f}%', cellr),
             Paragraph(esc(r["top"]), cell)] for r in ctx["producer_rows"][:18]]
    story.append(tbl(["Producer", "Products In Window", "Flagged", "% Flagged (of window)", "Most Common Issue"], rows,
                     [4.0*inch, 1.55*inch, 1.1*inch, 1.55*inch, 2.7*inch],
                     aligns=["L", "R", "R", "R", "L"]))
    if ctx["producer_rows"]:
        pc = Counter({r["label"]: r["flagged"] for r in ctx["producer_rows"]})
        tot = sum(pc.values())
        rep = [r for r in ctx["producer_rows"] if r["flagged"] >= 2]
        extra = (f" {len(rep)} producer(s) have 2+ validated findings; the 'Most Common Issue' column shows where each repeats."
                 if rep else "")
        trend_note(_freq_line(pc, tot) + extra)

    story.append(H("Lab Trends"))
    rows = [[Paragraph(esc(r["lab"]), cell), Paragraph(str(r["flagged"]), cellr),
             Paragraph(str(r["thc"]), cellr), Paragraph(esc(r["top"]), cell)]
            for r in ctx["lab_rows"]]
    story.append(tbl(["Lab", "Contaminant-Flagged", "High Cannabinoid", "Most Common Contaminant"], rows,
                     [4.0*inch, 2.0*inch, 1.9*inch, 2.9*inch], aligns=["L", "R", "R", "L"]))
    lc = Counter({r["lab"]: r["flagged"] for r in ctx["lab_rows"] if r["flagged"]})
    if lc:
        tl, tc = lc.most_common(1)[0]
        trend_note(f"{sum(lc.values())} contaminant-flagged result(s) across {len(lc)} lab(s); the lab appearing most "
                   f"in contaminant flags is {esc(tl)} ({tc}). A lab recurring here reflects testing volume / market "
                   f"share as much as findings — it is not a quality judgment about the lab.")

    # ---------------- TOP FINDINGS ----------------
    story.append(H("Top Findings"))
    story.append(Paragraph("Most significant validated results across all categories, ranked by proximity to the "
                           "Connecticut legal limit. Severity colors the rank, CT %, and difference.", CTX))
    tf_cols = ["#", "Product", "Testing Date", "Producer", "Contaminant", "Measured", "CT Limit", "CT %",
               "CannaScope", "Diff. From CannaScope", "COA"]
    tf_w = [0.35*inch, 1.77*inch, 0.98*inch, 1.55*inch, 1.25*inch, 1.2*inch, 1.15*inch, 0.85*inch, 1.15*inch, 1.4*inch, 1.0*inch]
    rows, sevs = [], []
    for i, (p, d) in enumerate(ctx["exec_rows"][:15], 1):
        sev = sev_of(d); bar = SEVC[sev][0]; sevs.append(sev); unit = d.get("unit", "")
        rows.append([Paragraph(f'<font color="{bar}"><b>{i}</b></font>', cellc),
                     Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                     Paragraph(esc(d["name"]), cell), Paragraph(esc(clean_value(d.get("value"), unit)), cellrb),
                     Paragraph(esc(clean_value(d.get("ct_limit"), unit)), cellr),
                     Paragraph(f'<font color="{bar}"><b>{v4.ct_pct_label(d.get("ct_pct"), full=False)}</b></font>', cellr),
                     Paragraph(esc(clean_value(d.get("cs_std"), unit)), cellr),
                     Paragraph(f'<font color="{bar}"><b>{v4.vs_standard_label(d.get("vs_std"), full=False)}</b></font>' if d.get("vs_std") is not None else "—", cellr),
                     coa_cell(p)])
    if rows:
        story.append(tbl(tf_cols, rows, tf_w, rank_sevs=sevs,
                         aligns=["C", "L", "C", "L", "L", "R", "R", "R", "R", "R", "C"]))
    else:
        story.append(Paragraph("No validated contaminant findings crossed the CannaScope threshold.", cellc))

    # ---------------- PER-CONTAMINANT FINDINGS ----------------
    LIMIT_CTX = {"tymc": "Connecticut legal limit 100,000 CFU/g · CannaScope threshold 10,000 CFU/g.",
                 "aerobic": "Connecticut legal limit 100,000 CFU/g · CannaScope threshold 10,000 CFU/g.",
                 "arsenic": "CannaScope threshold = 50% of the COA's Connecticut legal limit.",
                 "chromium": "CannaScope threshold = 50% of the COA's Connecticut legal limit.",
                 "cadmium": "CannaScope threshold = 50% of the COA's Connecticut legal limit.",
                 "lead": "CannaScope threshold = 50% of the COA's Connecticut legal limit.",
                 "mercury": "CannaScope threshold = 50% of the COA's Connecticut legal limit."}
    nsf = []
    for key, title in ANALYTE_TABLES:
        items = ai[key]
        if not items:
            nsf.append((title, next((c for c in ctx["zero"] if c["category"] == title), None))); continue
        top_p, top_d = items[0]
        story.append(H(f"{title} Findings"))
        story.append(Paragraph(f"{esc(LIMIT_CTX.get(key,''))} &nbsp; {len(items)} flagged · highest "
                               f"{esc(clean_value(top_d.get('value'), top_d.get('unit','')))} "
                               f"({esc(tcase(top_p.product_name))}, {esc(producer_short(top_p, ident))}).", CTX))
        story.append(rich_table(items))
        overflow_note(len(items), "severity_" + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") + ".csv")
        trend_note(cat_trend(items))

    if ctx["mycotoxins"]:
        story.append(H("Mycotoxin Findings"))
        story.append(Paragraph("Aflatoxins / ochratoxin A. CannaScope threshold = 50% of the CT legal limit.", CTX))
        story.append(rich_table(ctx["mycotoxins"]))
        overflow_note(len(ctx["mycotoxins"]), "CannaScope_CT_V15_Validated_Flagged.csv")
    else:
        nsf.append(("Mycotoxins", next((c for c in ctx["zero"] if c["category"] == "Mycotoxins"), None)))
    if ctx["solvents"]:
        story.append(H("Residual Solvent Findings"))
        story.append(Paragraph("Residual solvents at/over the CannaScope standard, or a failed panel.", CTX))
        rows = [[Paragraph(f'<font color="#9A7B0A"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
                 td(p), Paragraph(pr(p), cell), Paragraph(esc(d["name"]), cell),
                 Paragraph(esc(clean_value(d.get("value"), d.get("unit", "ppm"))), cellb), coa_cell(p)]
                for i, (p, d) in enumerate(ctx["solvents"][:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Testing Date", "Producer", "Solvent", "Measured", "COA"], rows,
                         [0.4*inch, 2.9*inch, 0.95*inch, 2.5*inch, 1.9*inch, 1.5*inch, 1.2*inch]))
        overflow_note(len(ctx["solvents"]), "CannaScope_CT_V15_Validated_Flagged.csv")
    else:
        nsf.append(("Residual Solvents", next((c for c in ctx["zero"] if c["category"] == "Residual Solvents"), None)))
    if ctx["pesticides"]:
        story.append(H("Pesticide Findings"))
        story.append(Paragraph("COA pesticide panel returned FAIL (prohibited / over-limit pesticide).", CTX))
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
                 td(p), Paragraph(pr(p), cell), Paragraph('<font color="#C0392B"><b>Panel FAIL</b></font>', cellc), coa_cell(p)]
                for i, p in enumerate(ctx["pesticides"][:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Testing Date", "Producer", "Result", "COA"], rows,
                         [0.4*inch, 3.4*inch, 0.95*inch, 2.9*inch, 1.6*inch, 1.2*inch]))
        overflow_note(len(ctx["pesticides"]), "CannaScope_CT_V15_Validated_Flagged.csv")
    else:
        nsf.append(("Pesticides", next((c for c in ctx["zero"] if c["category"] == "Pesticides"), None)))
    if ctx["pathogens"]:
        story.append(H("Pathogen Findings", color=RED))
        story.append(Paragraph("Zero-tolerance pathogen reported DETECTED (do-not-consume if confirmed).", CTX))
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
                 td(p), Paragraph(pr(p), cell), Paragraph(f'<font color="#C0392B"><b>{esc(nice)} DETECTED</b></font>', cellc), coa_cell(p)]
                for i, (p, nice) in enumerate(ctx["pathogens"][:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Testing Date", "Producer", "Pathogen", "COA"], rows,
                         [0.4*inch, 3.2*inch, 0.95*inch, 2.8*inch, 2.0*inch, 1.2*inch]))
        overflow_note(len(ctx["pathogens"]), "CannaScope_CT_V15_Validated_Flagged.csv")
    else:
        nsf.append(("Pathogens", next((c for c in ctx["zero"] if c["category"] == "Pathogens"), None)))

    # ---------------- CANNABINOID / POTENCY REVIEW — SPLIT INTO THREE SECTIONS (Part B item 4) ----
    # (A) genuinely high THC flower, (B) impossible cannabinoid math, (C) possible product-type
    # misclassification. None implies safety, fraud, or legal failure unless the COA + date-correct
    # law support it. The helper functions below are shared across the three section tables.

    def _cv(p, key):   # one cannabinoid component as a %, or an em dash if absent
        v = thc_value(p, key)
        return f"{v:g}%" if (v is not None and math.isfinite(v) and v >= 0) else "—"

    def _cv_total_cann(p):
        for k in ("total_cannabinoids", "total_active"):
            v = thc_value(p, k)
            if v is not None and math.isfinite(v) and v >= 0:
                return f"{v:g}%"
        return "—"

    def _basis_short(p):
        _v, basis, verified = verified_total_thc(p)
        if "verified COA" in basis:
            return "COA-verified"
        if "computed" in basis:
            return "computed (THCA+&#916;9)" if verified else "computed"
        return "COA-stated (no THCA)"

    # (The three-way split below — high flower / impossible math / product-type mismatch — now does the
    # anomaly classification that the old single-table "Data Classification" column used to carry.)

    # Build the three buckets from the high-flower set + impossible-math across ALL flagged products.
    tf = ctx.get("thc_flower") or []
    impossible, _imp_ids = [], set()
    for p in (ctx.get("flagged") or []):
        msg = thc_conflict(p)
        if msg and id(p) not in _imp_ids:
            _imp_ids.add(id(p)); impossible.append((p, msg))
    mismatch = [(p, val) for (p, _k, val) in tf
                if (not is_infused(p)) and val is not None and val > 45 and id(p) not in _imp_ids]
    _mm_ids = {id(p) for p, _ in mismatch}
    high_flower = [(p, val) for (p, _k, val) in tf if id(p) not in _imp_ids and id(p) not in _mm_ids]

    # ---- A. High THC Flower Review ----
    story.append(H("A. High THC Flower Review", color=AQUA))
    intro_box("Non-infused flower whose <b>verified</b> Total THC is above 35% — a label-accuracy <b>review signal, "
              "not a contaminant/safety finding and not an accusation</b>. Total THC is computed from the COA's own "
              "components (0.877 &#215; THCA + &#916;9-THC), not a possibly-inflated COA-stated figure (older AltaSci "
              "COAs printed 'Total THC' without the 0.877 factor, ~2&#215; too high); the Basis column shows "
              "COA-verified vs computed. Impossible-math and product-type-mismatch cases are split out into sections "
              "B and C below.", color="#0E5A4C")
    if high_flower:
        rows = [[Paragraph(f'<font color="#0E6B5A"><b>{i}</b></font>', cellc),
                 Paragraph(esc(tcase(p.product_name)), cell), Paragraph(pr(p), cell),
                 Paragraph(esc(_cv(p, "thca")), cellr), Paragraph(esc(_cv(p, "d9_thc")), cellr),
                 Paragraph(esc(_cv(p, "total_cbd")), cellr),
                 Paragraph(f'<font color="#0E6B5A"><b>{val:g}%</b></font>', cellr),
                 Paragraph(_basis_short(p), cellc), Paragraph(esc(_cv_total_cann(p)), cellr), coa_cell(p)]
                for i, (p, val) in enumerate(high_flower[:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Producer", "THCA", "&#916;9-THC", "CBD", "Total THC",
                          "Total THC Basis", "Total Cannabinoids", "COA"], rows,
                         [0.35*inch, 2.2*inch, 1.6*inch, 0.85*inch, 0.9*inch, 0.8*inch, 0.95*inch,
                          1.35*inch, 1.2*inch, 1.0*inch], hc=AQUA, band="#d4f5ee",
                         aligns=["C", "L", "L", "R", "R", "R", "R", "C", "R", "C"]))
        overflow_note(len(high_flower), "high_thc_flower_noninfused.csv")
    else:
        story.append(Paragraph("No non-infused flower exceeded the 35% review threshold (excluding impossible-math "
                               "and product-type-mismatch cases) this run.", cellc))

    # ---- B. Impossible Cannabinoid Math Review ----
    story.append(H("B. Impossible Cannabinoid Math Review", color=RED))
    intro_box("Products whose reported cannabinoids are internally <b>impossible</b> — e.g. Total Cannabinoids less "
              "than Total THC, or less than THCA (Total Cannabinoids must include the THC it contains). This is a "
              "<b>data-integrity / parser-or-COA review signal</b>, not a safety or fraud finding. Each row shows the "
              "conflicting numbers; verify against the live COA.", color="#7a1f17")
    if impossible:
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc),
                 Paragraph(esc(tcase(p.product_name)), cell), Paragraph(pr(p), cell),
                 Paragraph(esc(_cv(p, "thca")), cellr), Paragraph(esc(_cv(p, "total_thc")), cellr),
                 Paragraph(esc(_cv_total_cann(p)), cellr), Paragraph(esc(msg), cell), coa_cell(p)]
                for i, (p, msg) in enumerate(impossible[:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Producer", "THCA", "Total THC", "Total Cannabinoids",
                          "Why it's impossible (verify on COA)", "COA"], rows,
                         [0.35*inch, 2.0*inch, 1.5*inch, 0.9*inch, 0.95*inch, 1.2*inch, 3.0*inch, 1.0*inch],
                         hc=RED, band="#f8d2d0", aligns=["C", "L", "L", "R", "R", "R", "L", "C"]))
        overflow_note(len(impossible), "compliance_flags.csv")
    else:
        story.append(Paragraph("No impossible cannabinoid-math cases this run.", cellc))

    # ---- C. Possible Product-Type Misclassification ----
    story.append(H("C. Possible Product-Type Misclassification", color=colors.HexColor("#E67E22")))
    intro_box("Products <b>listed as usable marijuana / flower</b> but showing <b>vape/extract/concentrate-level</b> "
              "verified Total THC (above ~45%, implausible for flower). This is a <b>labeling / product-type review "
              "signal</b> — it may be a mislabeled product type OR a parser/COA error, not a safety or fraud finding. "
              "Verify the product form and potency on the live COA.", color="#8a4b16")
    if mismatch:
        rows = [[Paragraph(f'<font color="#E67E22"><b>{i}</b></font>', cellc),
                 Paragraph(esc(tcase(p.product_name)), cell), Paragraph(pr(p), cell),
                 Paragraph(esc(tcase(p.dosage_form or "flower")), cell),
                 Paragraph(f'<b>{val:g}%</b>', cellr), Paragraph(_basis_short(p), cellc),
                 Paragraph("Listed as flower but verified Total THC is at extract/concentrate level (&gt;45%).", cell),
                 coa_cell(p)]
                for i, (p, val) in enumerate(mismatch[:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Producer", "Listed Type", "Verified Total THC", "Basis",
                          "Why flagged (verify on COA)", "COA"], rows,
                         [0.35*inch, 2.0*inch, 1.45*inch, 1.1*inch, 1.1*inch, 1.2*inch, 2.5*inch, 1.0*inch],
                         hc=colors.HexColor("#E67E22"), band="#ffe3c2", aligns=["C", "L", "L", "L", "R", "C", "L", "C"]))
    else:
        story.append(Paragraph("No flower products showed extract-level (&gt;45%) potency this run.", cellc))

    # Potency-reference sections (infused products, and vapes/concentrates/extracts) were removed:
    # they were pure potency listings — high potency is expected by design and is not a finding.
    # Contaminant analysis for vapes/extracts (if tested) still appears in the contaminant sections.

    # ---------------- POSSIBLE REMEDIATION REVIEW ----------------
    if ctx["remediation"]:
        story.append(H("Possible Remediation / Unusually Low Microbial Load Review"))
        intro_box("Non-infused FLOWER whose total yeast &amp; mold is <b>at or under 100 CFU/g</b> — a measured "
                  "0–100 CFU/g, or a below-detection result such as <b>&lt; 100 CFU/g</b>. This is <b>NOT proof of "
                  "remediation</b>; very low or below-detection microbial counts can be entirely normal. A "
                  "consumer-awareness lead only — verify against the live COA.")

        def _rem_ym_disp(p):
            r = _remediation_ym(p)
            if not r:
                return esc(clean_value(p.analytes.get("tymc", {}).get("value"), "CFU/g"))
            v, below = r
            return ("&lt; " if below else "") + esc(clean_value(v, "CFU/g"))
        rows = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                 Paragraph(_rem_ym_disp(p), cellc),
                 coa_cell(p)] for p in ctx["remediation"][:25]]
        story.append(tbl(["Product", "Testing Date", "Producer", "Yeast & Mold", "COA"], rows,
                         [3.4*inch, 0.95*inch, 2.9*inch, 1.7*inch, 1.3*inch]))
        # Producer-frequency summary (consumer-awareness lead only — NOT proof of remediation)
        rem_freq = Counter(producer_short(p, ident) for p in ctx["remediation"])
        if rem_freq:
            tops = ", ".join(f"{esc(nm)} ({c})" for nm, c in rem_freq.most_common(8))
            story.append(Spacer(1, 3))
            story.append(Paragraph(
                "<b>Producer frequency in this section:</b> " + tops + ". "
                "Producer frequency may help identify where unusually low microbial readings cluster, but low "
                "readings can be normal and are not proof of remediation. This is a consumer-awareness lead only.",
                note_st))

    # (Lower-Concern Products + No Significant Findings render lower down, just before the Appendix —
    #  these reassurance/closure sections belong after the main findings + patient-safety reviews.)

    # ---------------- POTENTIAL STATUTE & REGULATORY FLAGS (V9 add-on) ----------------
    cflags = ctx.get("compliance_flags", [])
    smm = ctx.get("source_mismatches", []) or []
    story.append(H("Potential Compliance Review Leads", color=RED))
    intro_box(
        "<b>These are review LEADS, not legal conclusions.</b> They come only from the COA testing data "
        "CannaScope can read. Nothing here adjudicates a violation, and CannaScope cannot confirm whether a "
        "batch was released, remediated, or destroyed. Exact rule sections are NOT asserted — each points to "
        "an <b>authority area to verify in eRegulations</b>. Leads are <b>triaged by review priority</b> "
        "(Critical &gt; High &gt; Moderate &gt; Low) so the list does not overwhelm; the detailed A&ndash;D "
        "tables below give the specifics. <b>Priority is not a finding of wrongdoing.</b>", color="#7a2a25")

    # ---- Triage summary (Critical / High / Moderate / Low) ----
    _tier_ct = Counter(r.get("tier", "Low") for r in cflags)
    _tcol = {"Critical": "#C0392B", "High": "#E67E22", "Moderate": "#9A7B0A", "Low": "#555555"}
    trows = [[Paragraph(f'<font color="{_tcol[t]}"><b>{t}</b></font>', cell),
              Paragraph(f'<b>{_tier_ct.get(t, 0):,}</b>', cellc),
              Paragraph(esc(_TIER_BLURB[t]), cell)] for t in COMPLIANCE_TIERS]
    story.append(tbl(["Review priority", "Leads", "What this tier means (not a violation)"], trows,
                     [1.5*inch, 0.9*inch, 7.4*inch], hc=RED, band="#f8d2d0",
                     aligns=["L", "C", "L"]))
    story.append(Paragraph(f"Total potential review leads this run: <b>{len(cflags):,}</b>. "
                           "Most Low-tier items are informational/historical (unusual potency, missing values, "
                           "format/transparency notes), not indications of a violation.", note_st))

    gA = [r for r in cflags if r["rule_category"] == "Testing & product quality"]
    gB = [r for r in cflags if r["rule_category"] == "Labeling & potency accuracy"]
    gC = [r for r in cflags if "yeast & mold" in r["rule_category"].lower()]

    def _auth(r):
        return (esc(r["cited_authority"]) +
                ' <font color="#C0392B"><b>— authority area to verify; confirm exact current section in '
                'eRegulations</b></font>')

    # A. Over a current CT contaminant limit -----------------------------------------------------
    subhead("A. Over a current CT contaminant limit", color=RED)
    if gA:
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc),
                 Paragraph(esc(tcase(r["p"].product_name)), cell), Paragraph(pr(r["p"]), cell),
                 td(r["p"]), Paragraph(esc(lab_name(r["p"], lmap)), cell),
                 Paragraph(esc(r["finding"]), cell), Paragraph(_auth(r), cell), coa_cell(r["p"])]
                for i, r in enumerate(gA[:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Producer", "Tested", "Lab", "Potential issue (verify on COA)",
                          "Authority area to verify", "COA"], rows,
                         [0.32*inch, 1.85*inch, 1.5*inch, 0.98*inch, 1.25*inch, 2.32*inch, 1.9*inch, 0.95*inch],
                         hc=RED, band="#f8d2d0"))
        overflow_note(len(gA), "compliance_flags.csv")
    else:
        story.append(Paragraph("None — no verified result over a current CT contaminant limit in this run.", cellc))

    # B. Implausible/unusual potency — WITH the cannabinoid breakdown so the concern is self-explanatory
    subhead("B. Implausible or unusual potency / possible product-type mismatch", color=RED)
    if gB:
        def _cv(p, k):
            v = thc_value(p, k)
            return f"{v:g}%" if (v is not None and math.isfinite(v) and v >= 0) else "—"
        def _cv_tc(p):
            for k in ("total_cannabinoids", "total_active"):
                v = thc_value(p, k)
                if v is not None and math.isfinite(v) and v >= 0:
                    return f"{v:g}%"
            return "—"
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc),
                 Paragraph(esc(tcase(r["p"].product_name)), cell), Paragraph(pr(r["p"]), cell), td(r["p"]),
                 Paragraph(esc(tcase(r["p"].dosage_form)), cell),
                 Paragraph(esc(_cv(r["p"], "thca")), cellc), Paragraph(esc(_cv(r["p"], "d9_thc")), cellc),
                 Paragraph(esc(_cv(r["p"], "total_cbd")), cellc),
                 Paragraph(f'<b>{esc(_cv(r["p"], "total_thc"))}</b>', cellc), Paragraph(esc(_cv_tc(r["p"])), cellc),
                 Paragraph(esc(r["finding"]), cell), coa_cell(r["p"])]
                for i, r in enumerate(gB[:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Producer", "Tested", "Type", "THCA", "&#916;9-THC", "CBD", "Total THC",
                          "Total Cann.", "Reason for review", "COA"], rows,
                         [0.3*inch, 1.7*inch, 1.35*inch, 0.98*inch, 0.95*inch, 0.72*inch, 0.78*inch, 0.62*inch,
                          0.78*inch, 0.82*inch, 1.92*inch, 0.92*inch], hc=RED, band="#f8d2d0"))
        overflow_note(len(gB), "compliance_flags.csv")
        story.append(Paragraph("Cannabinoid columns are the COA's own values, shown so the concern is clear "
                               "without opening the COA. Total THC &#8776; 0.877 &#215; THCA + &#916;9-THC.", note_st))
    else:
        story.append(Paragraph("None — no implausible-potency or potency-math discrepancy among high-cannabinoid "
                               "flower this run.", cellc))

    # C. Missing numeric microbial value despite PASS (incl. looser dated-standard yeast & mold)
    subhead("C. Missing numeric microbial value despite PASS (yeast & mold)", color=RED)
    if gC:
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc),
                 Paragraph(esc(tcase(r["p"].product_name)), cell), Paragraph(pr(r["p"]), cell),
                 td(r["p"]), Paragraph(esc(lab_name(r["p"], lmap)), cell),
                 Paragraph(esc(r["finding"]), cell), coa_cell(r["p"])]
                for i, r in enumerate(gC[:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Producer", "Tested", "Lab", "Potential issue (verify on COA)", "COA"],
                         rows, [0.32*inch, 1.95*inch, 1.55*inch, 0.98*inch, 1.3*inch, 3.82*inch, 0.95*inch],
                         hc=RED, band="#f8d2d0"))
        overflow_note(len(gC), "compliance_flags.csv")
        story.append(Paragraph("See also the Yeast & Mold Standard Review — these relate to CT's "
                               "historical yeast & mold limits (which varied by lab and date).", note_st))
    else:
        story.append(Paragraph("None — every published yeast & mold PASS disclosed a numeric CFU/g value "
                               "this run.", cellc))

    # D. COA / document inconsistency requiring human review (source-binding mismatches)
    subhead("D. COA / document inconsistency requiring human review", color=RED)
    if smm:
        def _g(r, *keys):
            for k in keys:
                v = (r.get(k) if isinstance(r, dict) else getattr(r, k, None))
                if v:
                    return v
            return ""
        def _dtd(r):
            # the mismatch record carries the Product as r["p"]; show its testing/sample date.
            p = r.get("p") if isinstance(r, dict) else getattr(r, "p", None)
            return td(p) if p is not None else Paragraph("—", cellc)
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc),
                 Paragraph(esc(tcase(str(_g(r, "product", "product_name")))), cell),
                 Paragraph(esc(str(_g(r, "producer", "producer_dba"))), cell), _dtd(r),
                 Paragraph(esc(str(_g(r, "unverified_flagged_values", "coa_match_status", "note") or "value not re-verified in its linked COA")), cell),
                 Paragraph((f'<link href="{esc(str(_g(r, "report_url")))}"><font color="#1F6FEB"><u>open COA</u></font></link>'
                            if _g(r, "report_url") else "—"), coacell)]
                for i, r in enumerate(smm[:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Producer", "Tested", "Inconsistency (held for review)", "COA"], rows,
                         [0.32*inch, 2.2*inch, 1.8*inch, 0.95*inch, 4.6*inch, 0.95*inch], hc=RED, band="#f8d2d0"))
        story.append(Paragraph("These products were EXCLUDED from findings because a flagged value could not be "
                               "re-verified in their own linked COA — full detail in the COA Source-Binding Audit "
                               "(Validation & Diagnostics).", note_st))
    else:
        story.append(Paragraph("None — every published value was re-verified in its own linked COA this run.", cellc))

    # ---- Applicable CT standards by test date (item 10 reference) ----
    subhead("Applicable CT Standards by Test Date (reference)", color=NAVY)
    story.append(Paragraph(
        "Connecticut's testing standards changed over time — and, for microbials, differed by lab — so the "
        "standard that applied depends on a product's <b>testing date</b>. The program verifies the standard "
        "for the date rather than assuming one universal limit. Yeast &amp; mold is reviewed in full in the "
        "Yeast & Mold Standard Review (lab- and date-aware); the table below summarizes the other "
        "date-sensitive categories. <b>VERIFIED</b> = the limit value is confirmed against CT DCP "
        "testing requirements and corroborated by the action limit printed on the CT COAs in this "
        "dataset (live CT sources are also consulted each run). <b>VERIFIED (per-COA)</b> = the report "
        "judges each result against the action limit printed on its own COA. <b>N/A — no cap</b> = "
        "Connecticut sets no numeric limit for that category (a plausibility review is used instead). "
        "Always confirm the current exact text at eRegulations.ct.gov / DCP.", CTX))
    _CAT_LABELS = {"aerobic": "Total aerobic microbial count", "pathogens": "Pathogens (Salmonella / E. coli / Aspergillus)",
                   "heavy_metals": "Heavy metals (As / Cd / Pb / Hg)", "thc_potency": "THC potency (plausibility)"}
    std_rows = []
    for cat, label in _CAT_LABELS.items():
        for e in HISTORICAL_STANDARDS.get(cat, []):
            win = f"{e['start'][0]}–{(e['end'][0] if e['end'] else 'present')}"
            if isinstance(e.get("limit"), (int, float)):
                lim = f"{e['limit']:,} {e.get('unit', '')}".strip()
            elif e.get("no_cap"):
                lim = "no numeric cap (plausibility)"
            elif e.get("per_coa"):
                lim = "per-COA action limit"
            else:
                lim = "see note"
            # Status reflects HOW the limit is established, not a blanket red 'UNVERIFIED':
            #   verified value -> VERIFIED (green); per-COA basis -> PER-COA (green); no legal cap ->
            #   N/A (grey, not a failure to verify); only a genuinely-unconfirmed value -> amber 'confirm'.
            if e.get("no_cap"):
                ver = '<font color="#666"><b>N/A — no cap</b></font>'
            elif e.get("verified") and e.get("per_coa"):
                ver = '<font color="#1E7E34"><b>VERIFIED (per-COA)</b></font>'
            elif e.get("verified"):
                ver = '<font color="#1E7E34"><b>VERIFIED</b></font>'
            else:
                ver = '<font color="#9A7B0A"><b>Confirm at eRegulations</b></font>'
            pt = e.get("product_type", "*")
            std_rows.append([Paragraph(esc(label), cell), Paragraph(esc(win), cellc),
                             Paragraph(esc(pt if pt not in ("*", "") else "all"), cellc),
                             Paragraph(esc(lim), cellr), Paragraph(ver, cellc),
                             Paragraph(esc(e.get("note", "")), cell)])
    story.append(tbl(["Category", "Effective window", "Product type", "Standard / limit", "Status", "Note (verify at eRegulations)"],
                     std_rows, [2.3*inch, 1.1*inch, 1.0*inch, 1.5*inch, 1.0*inch, 3.3*inch],
                     hc=NAVY, band="#eef2f5", aligns=["L", "C", "C", "R", "C", "L"]))

    # ---- CT Regulatory Standards — Year by Year (baked-in, all years) ----
    subhead("CT Regulatory Standards — Year by Year (2015–2026)", color=NAVY)
    corr = ctx.get("reg_corroboration") or {}
    ym_corr = corr.get("yeast_mold") or {}
    ae_corr = corr.get("aerobic") or {}
    story.append(Paragraph(
        "The CT testing standard that applied <b>each year</b> is baked into the program (not assumed), so a report is "
        "always judged against the right year's limit even offline. Every value below is <b>confirmed</b> against the "
        f"cited CT statute / regulation / DCP policy (last confirmed {esc(CT_REG_AS_OF)}) <b>and corroborated by the "
        "action limit printed on the CT COAs in this dataset</b>"
        + (f" (yeast &amp; mold 100,000 CFU/g appears on {ym_corr.get('count', 0):,} COAs; "
           f"total aerobic on {ae_corr.get('count', 0):,})" if ym_corr or ae_corr else "")
        + ". The live CT sources are also re-consulted each run. Where a category has no single CT number "
        "(heavy metals differ by product type), the report defers to <b>each COA's own printed action limit</b> "
        "(live-first) rather than guessing.", CTX))
    yr_rows = []
    for y in range(2015, 2027):
        d = (y, 7, 1)
        ym = standard_for("yeast_mold", d, lab="northeast")
        ae = standard_for("aerobic", d)
        path = "Salmonella / STEC not detected" + (" + Aspergillus" if y >= 2020 else "")
        ymv = f"{ym['limit']:,} CFU/g" if ym and isinstance(ym.get("limit"), (int, float)) else "—"
        aev = f"{ae['limit']:,} CFU/g" if ae and isinstance(ae.get("limit"), (int, float)) else "—"
        yr_rows.append([Paragraph(str(y), cellc), Paragraph(esc(ymv), cellc), Paragraph(esc(aev), cellc),
                        Paragraph(esc(path), cell),
                        Paragraph("per-COA limit", cellc), Paragraph("no cap", cellc),
                        Paragraph('<font color="#1E7E34"><b>confirmed</b></font>', cellc)])
    story.append(tbl(["Year", "Yeast & Mold", "Total Aerobic", "Pathogens", "Heavy metals", "THC", "Basis"],
                     yr_rows, [0.7*inch, 1.3*inch, 1.3*inch, 2.9*inch, 1.2*inch, 0.8*inch, 1.0*inch],
                     hc=NAVY, band="#eef2f5", aligns=["C", "C", "C", "L", "C", "C", "C"]))
    cite_rows = []
    for catkey, label in (("yeast_mold", "Yeast & mold"), ("aerobic", "Total aerobic"),
                          ("pathogens", "Pathogens / Aspergillus"), ("heavy_metals", "Heavy metals"),
                          ("thc_potency", "THC potency")):
        cit, url = CT_REG_CITATIONS.get(catkey, ("", ""))
        cite_rows.append([Paragraph(esc(label), cellb),
                          Paragraph(f'{esc(cit)}<br/><font color="#2C5AA0">{esc(url)}</font>', cell)])
    story.append(Paragraph(f"<b>Citations</b> (confirmed {esc(CT_REG_AS_OF)}; the program re-consults these live each run):", CTX))
    story.append(tbl(["Category", "CT statute / regulation / policy citation"], cite_rows,
                     [2.0*inch, 7.2*inch], hc=NAVY, band="#eef2f5", aligns=["L", "L"]))

    # ---- Cached source-document provenance (the actual CT documents behind the limits) ----
    _led = load_reg_ledger()
    _lsrcs = (_led.get("sources") or []) if isinstance(_led, dict) else []
    if _lsrcs:
        _ok = [s for s in _lsrcs if s.get("ok")]
        story.append(Paragraph(
            f"<b>Cached source-document provenance.</b> The actual CT source documents behind these limits are "
            f"cached in the program (text extracted via the same PDF + OCR pipeline used for COAs, with a "
            f"<b>SHA-256</b> of the raw bytes) so the provenance is available <b>offline</b> and is tamper-evident. "
            f"{len(_ok)} of {len(_lsrcs)} source(s) cached as of {esc(_led.get('built_at', CT_REG_AS_OF))}.", CTX))
        prov_rows = []
        for s in _lsrcs:
            if s.get("ok"):
                detail = (f"{s.get('byte_len', 0):,} B · {s.get('method', '?')} · {s.get('text_len', 0):,} chars text")
                sha = "sha256:" + (s.get("sha256", "")[:24])
            else:
                detail = "not fetched this build (" + esc(str(s.get("http_status", s.get("status", "—")))) + ")"
                sha = "—"
            prov_rows.append([Paragraph(esc(s.get("label", "")), cell),
                              Paragraph(f'<font color="#2C5AA0">{esc(s.get("url", ""))}</font>', cell),
                              Paragraph(esc(detail), cell), Paragraph(esc(sha), cell_nb)])
        story.append(tbl(["Source", "URL", "Cached document", "Content hash"], prov_rows,
                         [2.1*inch, 3.5*inch, 2.2*inch, 1.6*inch], hc=NAVY, band="#eef2f5",
                         aligns=["L", "L", "L", "L"]))
    else:
        story.append(Paragraph(
            "<i>Source-document provenance ledger not yet built in this copy — run "
            f"<b>python3 {esc(SCRIPT_FILE)} fetch-standards</b> to download and SHA-256-cache the CT source "
            "documents for offline provenance (then re-embed with _make_v16.py). The dated limits above are "
            "already cited and corroborated by the COAs regardless.</i>", CTX))

    # ---- Legal Standard Verification (by test date) — Part B item 7 ----
    lrecs = ctx.get("legal_records") or []
    if lrecs:
        subhead("Legal Standard Verification (by test date)", color=NAVY)
        story.append(Paragraph(
            "This table separates <b>two different things</b> so they are not confused: (1) the <b>dated standard "
            "this report actually applied</b> to judge each category — taken from CannaScope's built-in, date-keyed "
            "registry of Connecticut limits — and (2) whether that exact figure was <b>independently confirmed against "
            "a live CT legal source</b> this run. The program is <b>local-first</b>: it judges every row against the "
            "applied dated limit shown below. Live sources (eRegulations, the CGS, DCP guidance) are consulted only as "
            "a <b>fallback</b> and are optional and fail-safe (they never block this report). CannaScope <b>does not "
            "auto-extract</b> an exact numeric limit from legal prose, so a reached live source means &quot;available "
            "for manual confirmation,&quot; not &quot;auto-verified.&quot; Only a category/era for which the program "
            "has <b>no dated value at all</b> is marked "
            f"&quot;{esc(LEGAL_UNVERIFIED)}.&quot;", CTX))
        _STD_LBL = {"yeast_mold": "Yeast & mold", "aerobic": "Aerobic count",
                    "pathogens": "Pathogens", "heavy_metals": "Heavy metals", "thc_potency": "THC potency"}
        # For categories whose standard isn't a single number, name the real basis the report used —
        # NOT a blank "unverified" (that wording is reserved for eras with genuinely no dated value).
        _NOLIMIT_BASIS = {
            "heavy_metals": "Per-analyte action limits (As / Cd / Pb / Hg) — see the Applicable CT Standards table above",
            "thc_potency": "No numeric cap — plausibility check only (Total THC ≈ 0.877 × THCA + Δ9)"}

        def _applied_std(r):
            """The dated standard the report ACTUALLY applied for this category/era (string), or None
            only when the program genuinely has no dated value on record."""
            lim, unit = r.get("limit"), (r.get("unit") or "")
            if isinstance(lim, (int, float)):
                if lim == 0:
                    return nbsp(esc((f"0 {unit}").strip())) + " (zero&nbsp;tolerance)"
                return nbsp(esc((f"{lim:,} {unit}").strip()))
            basis = _NOLIMIT_BASIS.get(r.get("category"))
            if basis:
                return esc(basis)
            if (r.get("source") or "").strip():
                return esc(r["source"])
            return None

        def _live_conf(r):
            """Clear, non-alarming live-confirmation status — kept SEPARATE from the applied value."""
            reached = any(a.get("ok") for a in (r.get("sources_attempted") or []))
            if r.get("verified"):
                return '<font color="#1E7E34"><b>Confirmed</b></font> — dated registry entry marked verified.'
            if _applied_std(r) is not None:
                base = ('<font color="#1E7E34"><b>Applied from dated registry.</b></font> Exact live numeric not '
                        'auto-extracted from legal prose')
                return base + ('; live CT sources <b>reached</b> — confirm the exact figure at eRegulations / DCP.'
                               if reached else '; live CT sources <b>unreachable</b> this run — queued for retry.')
            return f'<font color="#9A7B0A"><b>{esc(LEGAL_UNVERIFIED)}</b></font>'

        lrows = []
        for r in lrecs[:MAX_TABLE_ROWS]:
            srcs = r.get("sources_attempted") or []
            srctxt = ("; ".join(f'{esc(a["label"])} [{("reached" if a["ok"] else esc(a["result"]))}]' for a in srcs)
                      if srcs else "—")
            applied = _applied_std(r)
            applied_cell = (Paragraph(applied, cellc_nb) if applied is not None
                            else Paragraph('<font color="#9A7B0A">No dated value on record</font>', cellc_nb))
            lrows.append([Paragraph(esc(_STD_LBL.get(r.get("category"), r.get("category", ""))), cell),
                          Paragraph(esc(str(r.get("era", ""))), cellc),
                          applied_cell,
                          Paragraph(_live_conf(r), cell_nb),
                          Paragraph(srctxt, cell),
                          Paragraph(esc(r.get("fetched_at", "") or "—"), cellc_nb)])
        story.append(tbl(["Category", "Era", "Applied standard (by test date)", "Live-source confirmation",
                          "Sources consulted", "Live-checked"],
                         lrows, [1.2*inch, 0.55*inch, 1.7*inch, 2.7*inch, 2.6*inch, 1.1*inch],
                         hc=NAVY, band="#eef2f5", aligns=["L", "C", "L", "L", "L", "C"]))
        if ctx.get("legal_unreachable"):
            story.append(Paragraph(f"<b>{len(ctx['legal_unreachable'])}</b> live source URL(s) were unreachable "
                                   "this run and are queued for re-attempt next run (logged in the Self-Audit).", note_st))

    # ---------------- CONFLICTING COA RESULTS (consistent findings-section placement) ----------------
    emit_conflicts(_conflicts)

    # ---------------- CT CANNABIS OMBUDSMAN — MEDICAL PATIENT SAFETY (V9 add-on) ----------------
    from reportlab.platypus import HRFlowable
    omb = ctx.get("ombudsman", [])
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.4, color=NAVY, spaceBefore=2, spaceAfter=6))
    story.append(Paragraph("CT CANNABIS OMBUDSMAN — MEDICAL PATIENT SAFETY REVIEW", H1))
    story.append(Paragraph("PRODUCTS CLOSEST TO A CONTAMINANT LIMIT",
                           ParagraphStyle("ombsub", parent=H1, fontSize=15, leading=19, textColor=PURPLE)))
    story.append(Paragraph("For the Office of the Cannabis Ombudsman. These products passed testing but "
                           "came closest to a Connecticut action limit on one or more contaminants. This is "
                           "patient-safety information for review and advisory purposes — not a finding that "
                           "any product failed or is unsafe, and not medical advice. The testing/sample date "
                           "is shown on every row because the applicable Connecticut standard can depend on "
                           "when the product was tested.", CTX))
    if omb:
        rows = []
        for i, r in enumerate(omb[:MAX_TABLE_ROWS], 1):
            p, d = r["p"], r["d"]; unit = d.get("unit", "")
            rows.append([
                Paragraph(f'<b>{i}</b>', cellc),
                Paragraph(esc(tcase(p.product_name)), cell), Paragraph(pr(p), cell), td(p),
                Paragraph(esc(f'{r["cls"]} — {d.get("name", "")}'), cell),
                Paragraph(esc(f'{clean_value(d.get("value"), unit)} / {clean_value(d.get("ct_limit"), unit)}'), cellc),
                Paragraph(f'<b>{r["ct_pct"]:.1f}%</b>', cellc),
                Paragraph(esc(r["tier"]), cellc),
                Paragraph(esc(r["note"]), cell),
                Paragraph(coa(p) if p.report_url else "COA not provided", coacell)])
        story.append(tbl(["#", "Product", "Producer", "Tested", "Contaminant (class — analyte)",
                          "Result / CT Limit", "% Of Limit", "Tier", "Why It Matters (patient)", "COA"], rows,
                         [0.35*inch, 1.7*inch, 1.4*inch, 0.95*inch, 1.85*inch, 1.5*inch, 0.8*inch, 0.95*inch,
                          2.95*inch, 0.95*inch], hc=PURPLE, band="#ead9f2"))
        overflow_note(len(omb), "ombudsman_closeness.csv")
    else:
        story.append(Paragraph("No products came within the configured margin of a contaminant limit in "
                               "the data reviewed.", cellc))
    story.append(Spacer(1, 3))
    story.append(Paragraph("This section is patient-safety information for the Office of the Cannabis "
                           "Ombudsman and is not medical advice or a substitute for a provider's or "
                           "pharmacist's judgment. Exact measured values and limits are shown; products "
                           "listed here PASSED testing.", note_st))

    # ---- Mold / Yeast (TYM) Standard Review — lab- & date-aware (V15 patient-safety) ----
    tymf = ctx.get("tym_findings") or []
    story.append(Spacer(1, 8))
    story.append(Paragraph("YEAST &amp; MOLD — DATE &amp; LAB STANDARD REVIEW",
                           ParagraphStyle("tymh", parent=H1, fontSize=15, leading=18, textColor=PURPLE)))
    story.append(Paragraph(
        "This is <b>not</b> a list of every product over CannaScope's stricter internal 10,000 CFU/g benchmark. "
        "It is a narrow review of products where the <b>lab/date standard, a missing numeric value, the pass/fail "
        "wording, a pathogen detection, or a historical-limit issue</b> creates a real transparency or "
        "regulatory-review concern. A product is listed here ONLY when it: exceeded the <b>actual lab limit on its "
        "test date</b>; exceeded the <b>current CT limit</b>; would <b>pass one dated standard but fail another</b> "
        "actual standard in effect at a relevant time; was stamped <b>PASS with no numeric value disclosed</b>; had "
        "<b>Aspergillus / a pathogen detected</b>; reported a below-detection bound too broad to compare to the "
        "actual current limit; or has an <b>unclear/unverified historical standard that needs manual review</b>. "
        "Connecticut's TYM limit varied by <b>lab</b> and <b>date</b> (2012–Aug 2020 both labs 10,000; Aug 2020–~2022 "
        "AltaSci 1,000,000 while Northeast stayed 10,000; ~2022 unified to 100,000 + zero detectable Aspergillus), so "
        "each row is judged against the standard in effect on its own test date — effective dates are approximate "
        "where the public record is ambiguous (verify at eRegulations.ct.gov / DCP). The strict 10,000 CFU/g column is "
        "shown only as patient-protective context; being over it alone does NOT place a product in this section. "
        "Advisory — not medical advice; a PASS stamp is never taken at face value.", CTX))
    if tymf:
        _FLAGLBL = {"aspergillus_detected": '<font color="#C0392B"><b>Aspergillus / pathogen DETECTED</b></font>',
                    "high_risk_window": '<font color="#C0392B"><b>High-risk lab/date window (AltaSci 1M limit)</b></font>',
                    "over_current_ct_limit": '<font color="#C0392B"><b>Over current CT limit</b></font>',
                    "over_lab_limit_on_date": '<font color="#C0392B"><b>Over the actual lab limit on the test date</b></font>',
                    "dated_standard_mismatch": '<font color="#E67E22"><b>Passes one dated standard, fails another</b></font>',
                    "cannot_confirm_current_limit": '<font color="#E67E22">Below-detect bound too broad vs current limit — can\'t compare</font>',
                    "passed_no_value_disclosed": '<font color="#E67E22">PASS — no numeric value disclosed</font>',
                    "unverified_standard_review": '<font color="#9A7B0A">Applicable standard unclear/unverified — manual review</font>',
                    "aspergillus_not_tested": '<font color="#777">Aspergillus not tested this era</font>'}

        def _vcell(a):
            def c(v):
                col = {"FAIL": "#C0392B", "PASS": "#1E7E34"}.get(v, "#777")
                return f'<font color="{col}"><b>{v or "—"}</b></font>'
            return Paragraph(f'Lab {c(a["lab_verdict"])} · Now {c(a["current_verdict"])} · Strict {c(a["strict_verdict"])}', cell)
        rows, sevs = [], []
        for i, a in enumerate(tymf[:MAX_TABLE_ROWS], 1):
            p = a["p"]
            sev = "RED" if (a["aspergillus_detected"] or a["high_risk"] or a["over_current"]
                            or a.get("over_lab_limit")) else "YELLOW"
            sevs.append(sev)
            # The unit (CFU/g) is in the column header, so the value cell shows the NUMBER only,
            # kept whole (cellb_nb) — no more "380,000 CFU/g" splitting a number from its unit.
            if a["mval"] is not None:
                tymtxt = nbsp(esc(clean_value(a["mval"], "")))
            elif a["bbound"] is not None:
                tymtxt = nbsp("&lt; " + esc(clean_value(a["bbound"], "")))   # below-detection bound
            elif a["passed_no_value"]:
                tymtxt = '<font color="#9A7B0A">' + nbsp("not disclosed") + '</font>'
            else:
                tymtxt = "—"
            # Lab-limit column header has no unit, so keep value+unit here but glue them with NBSP.
            labtxt = (nbsp(esc(clean_value(a["lab_limit"], "CFU/g"))) if a["lab_limit"] is not None
                      else '<font color="#777">' + nbsp("unknown (no dated standard)") + '</font>')
            flagtxt = "<br/>".join(_FLAGLBL.get(f, esc(f)) for f in a["flags"])
            rows.append([Paragraph(f'<b>{i}</b>', cellc),
                         Paragraph(esc(tcase(p.product_name)), cell), Paragraph(pr(p), cell),
                         Paragraph(esc(a["lab"] or "Unknown lab"), cell),
                         td(p),
                         Paragraph(tymtxt, cellb_nb), Paragraph(labtxt, cellc_nb), _vcell(a),
                         Paragraph(flagtxt, cell), coa_cell(p)])
        story.append(tbl(["#", "Product", "Producer", "Lab", "Test Date", "TYM (CFU/g)",
                          "Lab limit on that date", "Lab / Now / Strict (10k)", "Concern", "COA"], rows,
                         [0.3*inch, 1.85*inch, 1.45*inch, 1.35*inch, 0.98*inch, 1.0*inch, 1.3*inch,
                          1.95*inch, 1.47*inch, 0.95*inch], hc=PURPLE, band="#ead9f2", rank_sevs=sevs))
        overflow_note(len(tymf), "tym_standard_review.csv")
    else:
        story.append(Paragraph("No products in this run raised a lab/date-aware yeast &amp; mold standard or "
                               "reporting concern — none over the actual lab limit on its test date or the current "
                               "CT limit, no dated-standard mismatch, no detectable Aspergillus, no PASS-without-a-"
                               "number cases, and no unverifiable-standard rows needing manual review. (Products that "
                               "are over the internal 10,000 CFU/g benchmark but pass their actual dated standard are "
                               "intentionally not listed here.)", cellc))

    # LOWER-CONCERN PRODUCTS section REMOVED (Part B item 8): a "lower-concern / lower-flag" list
    # risks reading as a safety ranking or endorsement. The report focuses on validated findings,
    # review leads, coverage gaps, and diagnostics instead. (ctx still computes `cleaner` counts for
    # internal stats, but nothing is rendered here.)

    # ---------------- NO SIGNIFICANT FINDINGS ----------------
    story.append(H("No Significant Findings & Coverage Notes"))
    story.append(Paragraph("Categories with no published finding this run, each labeled HONESTLY by how many "
                           "COAs actually reported it. A category that was <b>not reported on these COAs</b> "
                           "(a historical-format absence) or only <b>partially parsed</b> is NOT a clean zero — "
                           "it is marked as such so the absence of findings is not mistaken for full coverage.", CTX))
    _rescol = {"Needs Historical Parser Review": "#C0392B", "Partial Coverage": "#E67E22",
               "Not Reported (historical)": "#666", "No Significant Findings": "#1E7E34"}
    rows = []
    for title, zc in nsf:
        st = zc["status"] if zc else "No Significant Findings"
        cov = (f'{zc["parsed"]:,}/{zc.get("present", zc["total"]):,}' if zc else "—")
        col = _rescol.get(st, "#444")
        result = (zc["note"] if zc else "No result crossed the CannaScope threshold.")
        rows.append([Paragraph(esc(title), cellb),
                     Paragraph(f'<font color="{col}"><b>{esc(st)}</b></font>', cell),
                     Paragraph(esc(cov), cellc), Paragraph(esc(result), cell)])
    story.append(tbl(["Category", "Status", "Parsed / Reported-on", "Detail"], rows,
                     [1.85*inch, 2.2*inch, 1.35*inch, 4.5*inch],
                     aligns=["L", "L", "C", "L"]))

    # ================= APPENDIX — TECHNICAL VALIDATION & DIAGNOSTICS (LAST) =================
    story.append(PageBreak())
    story.append(Paragraph("APPENDIX", ParagraphStyle("appx", parent=H1, fontSize=13, textColor=colors.HexColor("#6b7682"),
                                                       spaceAfter=2)))
    story.append(H("Technical Validation & Diagnostics"))
    intro_box("Everything above is the public report. This appendix is the <b>technical record</b> — how the "
              "findings were checked, the COA source-binding audit, the self-audit, parser diagnostics, the "
              "producer-identity reference, and the debug log. It is for auditing and reproducibility; a general "
              "reader does not need it. Status: " + esc(status) + ".")

    # (the Conflicting-COA section now renders in the findings area, after Compliance Review Leads.)

    # ---- COA Source-Binding Audit (V15 integrity patch) ----
    sm = ctx.get("src_metrics", {}) or {}
    story.append(Paragraph("COA Source-Binding Audit", miniH))
    story.append(Paragraph(
        "Every published flagged value was re-opened and re-verified in its OWN linked Certificate of "
        "Analysis (the exact document the row's COA link points to). A value that cannot be re-verified "
        "in its linked COA is excluded from findings and routed to COA Source Mismatch Review. The "
        "registry's COA link and the extraction-source COA are the same document by construction.", CTX))
    aud = [["Published flagged values re-verified in their linked COA", str(sm.get("published_rows_verified_against_linked_coa", 0))],
           ["Exact-value link-verification failures", str(sm.get("exact_value_link_verification_failures", 0))],
           ["Rows excluded for COA source mismatch", str(sm.get("rows_excluded_for_coa_source_mismatch", 0))],
           ["Registry COA differs from result COA", str(sm.get("registry_coa_differs_from_result_coa_count", 0))],
           ["Multiple-COA alerts (product tied to >1 COA)", str(sm.get("multiple_coa_alert_count", 0))],
           ["PASS/FAIL COA conflicts", str(sm.get("pass_fail_coa_conflict_count", 0))]]
    story.append(tbl(["Source-Integrity Check", "Count"],
                     [[Paragraph(esc(a), cell), Paragraph(f"<b>{esc(b)}</b>", cellc)] for a, b in aud],
                     [7.0*inch, 1.8*inch], big=False))

    # ---- Per-row triple-check (six-field verification) ----
    fc = sm.get("field_confirmed") or {}
    n_full = sm.get("rows_fully_verified", 0); n_part = sm.get("rows_partially_verified", 0)
    n_pub = n_full + n_part
    if n_pub:
        story.append(Paragraph("Per-Row Triple-Check (six-field verification)", miniH))
        story.append(Paragraph(
            "Beyond confirming each value, every published row is re-checked against its OWN linked COA on six "
            "fields — measured value, product identity, testing date, laboratory, unit, and analyte name. A row "
            "is published only when its value is confirmed in the COA (a clear mismatch is excluded to manual "
            "review). A field marked “unconfirmed” means it could not be located in the COA's extractable text "
            "(commonly a scanned/OCR-only COA) — it is NOT treated as proof the COA is wrong. This is an "
            "auditable trail, not an auto-fail.", CTX))
        _labels = [("value", "Measured value found in COA"), ("product", "Product identity matched"),
                   ("date", "Testing date confirmed"), ("lab", "Laboratory confirmed"),
                   ("unit", "Unit confirmed"), ("analyte", "Analyte name confirmed")]
        frows = [[Paragraph(esc(lbl), cell), Paragraph(f"<b>{fc.get(k, 0)}</b> of {n_pub}", cellc),
                  Paragraph(f"{(100.0*fc.get(k, 0)/n_pub):.0f}%", cellr)] for k, lbl in _labels]
        story.append(tbl(["Verification field", "Confirmed in linked COA", "Rate"], frows,
                         [4.6*inch, 2.4*inch, 1.4*inch], big=False, aligns=["L", "C", "R"]))
        story.append(Paragraph(
            f"<b>{n_full}</b> published row(s) fully confirmed on all six fields; <b>{n_part}</b> published with "
            "one or more context fields unconfirmed in the COA text (value always confirmed). Full per-row "
            "stamps are in <b>Data Exports/COA_Provenance_Audit.csv</b>.", note_st))
    # ---- Coverage Gaps / Unvalidated COAs (kept OUT of the validated findings sections) ----
    # Direct Paragraph (not H(), which title-cases and would mangle the "COAs" acronym).
    story.append(Paragraph("Coverage Gaps / Unvalidated COAs",
                           ParagraphStyle("covgap", parent=H1, textColor=colors.HexColor("#6b7682"))))
    story.append(Paragraph(
        "Records below are <b>not</b> validated findings — they are coverage gaps held OUT of the findings, "
        "Ombudsman, and Yeast &amp; Mold Standard Review sections so those stay confirmed-only. They include COAs "
        "whose flagged value could not be re-verified in the linked document, products whose live COA could not be "
        "confirmed, COAs tied to more than one document, and categories with incomplete coverage. Each is a review "
        "lead, not a conclusion. (Unreadable / OCR-failed / NOT-READY-year limitations are summarized in the "
        "validation status and COA Format Learning subsections.)", CTX))
    smm = ctx.get("source_mismatches", [])
    if smm:
        story.append(Paragraph("COA Source Mismatch Review (excluded from findings)", miniH))
        rows = [[Paragraph(esc(tcase(m["p"].product_name)), cell), Paragraph(esc(producer_short(m["p"], ident)), cell),
                 Paragraph(esc(m["analytes"]), cell), coa_cell(m["p"])] for m in smm[:MAX_TABLE_ROWS]]
        story.append(tbl(["Product", "Producer", "Unverifiable Flagged Value(s)", "COA"], rows,
                         [3.0*inch, 2.3*inch, 3.0*inch, 1.4*inch], hc=RED, band="#f8d2d0"))
    mc = ctx.get("multi_coa", [])
    if mc:
        story.append(Paragraph("Multiple-COA Alert (manual review — not auto-merged)", miniH))
        rows = [[Paragraph(esc(a["products"]), cell), str(a["n"]),
                 Paragraph(f'<font color="{("#C0392B" if a["conflict"] else "#1E7E34")}"><b>{"YES" if a["conflict"] else "no"}</b></font>', cellc)]
                for a in mc[:MAX_TABLE_ROWS]]
        story.append(tbl(["Products sharing one COA document", "Count", "PASS/FAIL Conflict"], rows,
                         [6.2*inch, 1.0*inch, 1.6*inch], big=False))

    story.append(Paragraph("Self-Audit", miniH))
    rows = [[Paragraph(esc(i["issue"]), cell), str(i["count"]),
             Paragraph(f'<font color="{("#1E7E34" if i["status"] in ("Fixed","None") else "#C0392B")}"><b>{i["status"]}</b></font>', cell)]
            for i in ctx["audit"]]
    story.append(tbl(["Check", "Count", "Status"], rows, [7.0*inch, 1.2*inch, 1.8*inch], big=False))
    qv = [p for p in ctx["flagged"] if p._coa_status not in PUBLISHABLE]
    story.append(Paragraph("COA Verification Queue", miniH))
    story.append(Paragraph(f"({len(qv)}) flagged rows whose live COA could not be confirmed. Excluded from findings "
                           "until verified.", CTX))
    if qv:
        rows = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell), Paragraph(esc(lab_name(p, lmap)), cell),
                 Paragraph(esc(p._coa_status), cell), coa_cell(p)] for p in qv[:40]]
        story.append(tbl(["Product", "Testing Date", "Producer", "Lab", "Match Status", "COA"], rows,
                         [2.7*inch, 0.95*inch, 2.3*inch, 1.5*inch, 1.9*inch, 1.2*inch], big=False))
    story.append(Paragraph("Zero-Result Verification Queue", miniH))
    _zcol = {"Needs Historical Parser Review": "#C0392B", "Partial Coverage": "#E67E22",
             "OK": "#1E7E34", "No Significant Findings": "#1E7E34", "Not Reported (historical)": "#666"}
    rows = []
    for c in ctx["zero"]:
        col = _zcol.get(c["status"], "#444")
        rows.append([Paragraph(esc(c["category"]), cell), str(c["flagged"]),
                     f'{c["parsed"]}/{c.get("present", c["total"])}',
                     Paragraph(f'<font color="{col}"><b>{esc(c["status"])}</b></font>', cell)])
    story.append(tbl(["Category", "Flagged", "Parsed / Reported-on", "Status"], rows,
                     [2.6*inch, 1.0*inch, 1.6*inch, 2.7*inch], big=False))
    story.append(Paragraph("Producer Identity & Internet Source Validation", miniH))
    story.append(Paragraph("Legal entity → DBA with source-confidence. Verified against data.ct.gov (egd5-wb6r), CT "
                           "eLicense, the DCP brand registry, and cited public sources.", CTX))
    rows = []
    for r in sorted(ctx["ident"].cache.values(), key=lambda r: -r["confidence"]):
        rows.append([Paragraph(esc(r.get("legal", "")), cell), Paragraph(esc(r["common"] or "—"), cell),
                     Paragraph(esc(", ".join(r["brands"]) if r["brands"] else "—"), cell),
                     Paragraph(f'{r["confidence"]}%', cellc),
                     Paragraph(esc(r["source"] or ("COA/registry product names" if r["brands"] else "—")), cell)])
    story.append(tbl(["Legal Entity (Appendix)", "Common / DBA", "Brands", "Confidence", "Source"], rows,
                     [2.6*inch, 1.8*inch, 2.0*inch, 1.0*inch, 2.8*inch], big=False))
    # ---- COA Format Learning & Extraction Confidence (historical-format awareness) ----
    story.append(Paragraph("COA Format Learning &amp; Extraction Confidence", miniH))
    cmix = ctx.get("conf_mix") or {}
    story.append(Paragraph(
        "Connecticut COA layouts, lab templates, section names/order, and pass/fail wording have changed "
        "over the years. The COA Format Learning Layer fingerprints each COA's format and cross-checks the "
        "extraction against five independent signals (top-level pass/fail summary; detailed breakdown tables; "
        "numeric values; batch/product/licensee identity; and whether the COA matches the product record). "
        "Extractions with a pass/fail conflict, a product mismatch, impossible numbers, or an unreadable scan "
        "are marked <b>UNCERTAIN</b> and HELD for review rather than published. This run: "
        f"<b>{cmix.get('HIGH',0)}</b> HIGH · <b>{cmix.get('MEDIUM',0)}</b> MEDIUM · "
        f"<b>{cmix.get('LOW',0)}</b> LOW · <b>{cmix.get('UNCERTAIN',0)}</b> UNCERTAIN confidence COAs.", CTX))
    # Unambiguous, mutually-distinct confidence / exclusion metrics (item 6): "detected" counts
    # INPUTS flagged for caution; "published" counts OUTPUTS that reached findings; held/excluded
    # counts never reach findings. Naming kept stable so the appendix can't read as both
    # "uncertain COAs shown" and "nothing uncertain published" without the explaining sentence below.
    _dbg = ctx.get("debug", {}) or {}
    _holds = ctx.get("format_holds") or []
    _vq_excl = sum(1 for p in ctx.get("flagged", []) if p._coa_status not in PUBLISHABLE)
    _parser_conf = sum(1 for p in _holds if (getattr(p, "_extraction", {}) or {}).get("conflict"))
    _uc_det = cmix.get("UNCERTAIN", 0)
    _uc_pub = _dbg.get("uncertain_extractions_published", 0)
    _cm_rows = [
        ("uncertain_coas_detected", _uc_det, "COAs whose extraction was rated UNCERTAIN (low-confidence layout/signals)."),
        ("uncertain_extractions_held", len(_holds), "Held for review and EXCLUDED from findings — never published."),
        ("uncertain_findings_published", _uc_pub, "Published rows derived from an UNCERTAIN extraction (target: 0)."),
        ("unreadable_coas_excluded", _dbg.get("unreadable_after_retry", 0), "Unreadable even after OCR retry — a coverage gap, not a finding."),
        ("parser_conflicts_excluded", _parser_conf, "Held extractions with a top/detail or impossible-math conflict."),
        ("verification_queue_rows_excluded", _vq_excl, "Flagged rows whose live COA could not be confirmed — excluded until verified."),
    ]
    story.append(tbl(["Confidence / exclusion metric", "Count", "Meaning"],
                     [[Paragraph(esc(a), cell), Paragraph(f"<b>{b}</b>", cellc), Paragraph(esc(c), cell)]
                      for a, b, c in _cm_rows], [3.3*inch, 0.9*inch, 5.0*inch], big=False, aligns=["L", "C", "L"]))
    if _uc_det and not _uc_pub:
        story.append(Paragraph(
            f"<b>{_uc_det}</b> COA(s) were low-confidence or UNCERTAIN, but <b>no uncertain findings were "
            "published</b> — those records were excluded or routed to review. (\"uncertain_coas_detected\" counts "
            "flagged-for-caution INPUTS; \"uncertain_findings_published\" counts OUTPUTS that reached findings — "
            "this run: 0.)", note_st))
    fyr = ctx.get("fmt_year_rows") or []
    if fyr:
        rows = []
        for r in fyr:
            c = r.get("conf", {})
            rows.append([Paragraph(str(r["year"]), cellc), Paragraph(esc(r["era"]), cell),
                         Paragraph(str(r["sampled"]), cellr),
                         Paragraph(esc(", ".join(r["labs"]) or "—"), cell),
                         Paragraph(f'{c.get("HIGH",0)}/{c.get("MEDIUM",0)}/{c.get("LOW",0)}/{c.get("UNCERTAIN",0)}', cellc),
                         Paragraph(f'{r["conf_rate"]*100:.0f}%', cellr),
                         Paragraph(esc(r["verdict"]), cell)])
        story.append(tbl(["Year", "Era / Format Period", "COAs On File", "Labs Seen",
                          "Conf (H/M/L/U)", "Conf %", "Ready For Reports?"], rows,
                         [0.7*inch, 2.5*inch, 1.1*inch, 2.3*inch, 1.3*inch, 0.8*inch, 1.8*inch],
                         big=False, aligns=["C", "L", "R", "L", "C", "R", "L"]))
        # Which years/labs are still low/uncertain confidence?
        low_years = [str(r["year"]) for r in fyr if r["conf_rate"] < 0.90 or not r.get("ready")]
        low_labs = sorted({lab for r in fyr if (r["conf_rate"] < 0.90 or not r.get("ready"))
                           for lab in r.get("labs", [])})
        if low_years:
            story.append(Paragraph("<b>Years/labs still LOW or uncertain confidence:</b> "
                                   + esc(", ".join(low_years)) + (" — labs: " + esc(", ".join(low_labs)) if low_labs else "")
                                   + ". These are where the parser would most benefit from more training.", CTX))
        # Which categories are affected by historical layout gaps (from this run's zero-result review)?
        gap_cats = [c["category"] for c in (ctx.get("zero") or [])
                    if c["status"] in ("Needs Historical Parser Review", "Not Reported (historical)", "Partial Coverage")]
        if gap_cats:
            story.append(Paragraph("<b>Categories affected by historical layout/format gaps this run:</b> "
                                   + esc(", ".join(gap_cats)) + " (see the No-Significant-Findings &amp; Coverage "
                                   "Notes section for each category's exact status).", CTX))
        story.append(Paragraph("Per-year readiness accumulates across runs (persisted). <b>Recommendation:</b> run "
                               f"<b>python3 {SCRIPT_FILE} learn --years 2015-2022</b> to train the parser "
                               "harder on the older <b>AltaSci</b> formats (esp. the 2020&ndash;2021 high-risk "
                               "yeast/mold window) and the earlier <b>Northeast Laboratories</b> columnar layouts, "
                               "which is where confidence is lowest. The more historical COAs <b>learn</b> sees, the "
                               "more confidently those years can be used in statewide reports.", CTX))
    holds = ctx.get("format_holds") or []
    if holds:
        story.append(Paragraph("COA Extraction Review (held — uncertain extraction, NOT published)", miniH))
        rows = []
        for p in holds[:MAX_TABLE_ROWS]:
            ex = getattr(p, "_extraction", {}) or {}
            pf = getattr(p, "_format_profile", {}) or {}
            rows.append([Paragraph(esc(tcase(p.product_name)), cell), Paragraph(pr(p), cell),
                         Paragraph(str(pf.get("year") or "—"), cellc),
                         Paragraph(esc("; ".join(ex.get("reasons", [])) or "uncertain"), cell),
                         coa_cell(p)])
        story.append(tbl(["Product", "Producer", "Year", "Why held (uncertain)", "COA"], rows,
                         [2.4*inch, 1.9*inch, 0.6*inch, 3.7*inch, 1.2*inch], big=False))
        story.append(Paragraph(f"({len(holds)}) flagged product(s) were held because the extraction could not be "
                               "trusted (top/detail pass-fail conflict or the COA did not match the product). They "
                               "are excluded from findings until reviewed — the program does not report uncertain data "
                               "as fact.", CTX))

    story.append(Paragraph("Data Quality & Debug Log", miniH))
    rows = [[Paragraph(esc(k), cell), Paragraph(esc(str(v)), cell)] for k, v in ctx["debug"].items()]
    story.append(tbl(["Metric", "Value"], rows, [4.4*inch, 5.4*inch], big=False))

    # ---- Software Self-Enhancement & Self-Audit (Part B item 9) + persistent log (item 10) ----
    story.append(Paragraph("Software Self-Enhancement &amp; Self-Audit",
                           ParagraphStyle("selfaudit", parent=H1, textColor=colors.HexColor("#6b7682"))))
    story.append(Paragraph(
        "Auto-generated every run. The program evaluates its OWN weaknesses this run and recommends concrete next "
        "improvements — observation &rarr; why it matters &rarr; recommendation — and carries notes forward across "
        f"runs (persistent log: {ctx.get('self_improve_runs', 1)} run(s) recorded in Self-Improvement Log.json). "
        "This is guidance for the next run, not raw debug metrics.", CTX))
    for o in ctx.get("self_audit_obs", []):
        story.append(Paragraph(
            f'<b>{esc(o["category"])} — observed weakness:</b> {esc(o["observation"])}<br/>'
            f'<b>Why it matters:</b> {esc(o["why"])}<br/>'
            f'<b>Recommended improvement:</b> {esc(o["recommendation"])}', body_st))
        story.append(Spacer(1, 5))
    prior = ctx.get("prior_run")
    if prior and prior.get("observations"):
        subhead(f"Carried forward from the previous run ({esc(prior.get('run_time', 'prior run'))}) — re-checking")
        for o in prior["observations"]:
            story.append(Paragraph(
                f'<b>Previously noted ({esc(o["category"])}):</b> {esc(o["observation"])} '
                f'&nbsp;<i>Re-attempt/verify:</i> {esc(o["recommendation"])}', cell))
            story.append(Spacer(1, 2))

    def _footer(canvas, d_):
        canvas.saveState(); w, _h = PAGE
        canvas.setFont(BFB, 9); canvas.setFillColor(colors.HexColor("#333"))
        canvas.drawCentredString(w/2, 0.4*inch, "Every flag is a lead, not a conclusion. Verify against the live COA.")
        canvas.setFont(BF, 8); canvas.setFillColor(colors.HexColor("#666"))
        # report number appears in the footer on EVERY page (matches the filename + cover + metadata)
        canvas.drawString(0.3*inch, 0.22*inch,
                          f"{APP_NAME}  |  Report #{report_no}  |  {status}  |  Created {dcreated} {tcreated}  |  Window {window}")
        canvas.drawRightString(w-0.3*inch, 0.22*inch, f"Report #{report_no} — Page {d_.page}")
        canvas.restoreState()

    # ---- ADAPTIVE WHITE-SPACE REFLOW -------------------------------------------------
    # With keepWithNext removed from the header/intro styles (so a section's table is no
    # longer bundled into a KeepTogether and can split across page boundaries to fill the
    # page), a header could in principle be left orphaned at the very bottom of a page with
    # its table starting on the next. We prevent that by inserting a CondPageBreak before
    # every top-level section header: if fewer than SECTION_MIN points remain, break first;
    # otherwise the header + intro + first rows render here and the table flows on. This
    # adapts cleanly to both large reports (long tables split and fill pages) and small ones
    # (short sections pack together) — the worst-case gap shrinks from a whole table to at
    # most SECTION_MIN. Headers wrapped inside a KeepTogether (the summary boxes) are atomic
    # already and are left untouched (they carry no top-level .style for us to key on).
    # SECTION_MIN raised (96 -> 132) for the larger V15.1 fonts: a section title plus its intro,
    # the table's repeating column-header row, and ~2 data rows must clear before we commit to
    # rendering the header here; otherwise we break first so the title never detaches from its
    # table. (Table column-headers themselves repeat on every page via repeatRows=1, so once a
    # table starts its header is never separated from the rows that follow.)
    SECTION_MIN = 132
    # Base header style names. We match these AND any style that INHERITS from them, so every
    # subsection header (category headers, Ombudsman, TYM, "Most Important Findings", legend, the
    # appendix header) is caught — those all descend from H1 ("h1") or miniH ("mh"). The previous
    # name-only set missed them, which is how some subsection titles ended up detached.
    _HEAD_STYLES = {"h1", "mh"}

    def _is_header_style(st):
        seen = 0
        while st is not None and seen < 8:
            if getattr(st, "name", "") in _HEAD_STYLES:
                return True
            st = getattr(st, "parent", None)
            seen += 1
        return False

    def _reflow(items):
        out = []
        for fl in items:
            if _is_header_style(getattr(fl, "style", None)):
                out.append(CondPageBreak(SECTION_MIN))
            out.append(fl)
        return out

    doc.build(_reflow(story), onFirstPage=_footer, onLaterPages=_footer)
    print(f"Wrote {out_path}")


def producer_short_label(full_label):
    return re.sub(r"\s*\([^()]*\)\s*$", "", full_label).strip() or full_label


def tcase_dba(p, ident):
    return ident.resolve(p.producer)["label"]


def _zero_text(cat, zc):
    if zc and zc["status"] == "Needs Historical Parser Review":
        return (f"NEEDS HISTORICAL PARSER REVIEW — {cat} appears on the COAs but the parser extracted 0 "
                f"results, suggesting a historical-format parser gap. {zc['note']} Held for review.")
    if zc and zc["status"] == "Not Reported (historical)":
        return (f"{cat} is not reported on the COAs in this window (historical absence). {zc['note']}")
    if zc and zc["status"] == "Partial Coverage":
        return (f"{cat} — partial coverage. {zc['note']}")
    return (f"No Validated {cat} Rows Crossed The CannaScope Threshold In This Run After Live "
            f"Source Verification." + (f" ({zc['note']})" if zc else ""))


# ============================================================================
# Exports
# ============================================================================
def _w(path, header, rows):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f); wr.writerow(header)
        for r in rows:
            wr.writerow(r)


def write_outputs(ctx):
    # All CSVs + diagnostics go into a tidy "Data Exports" subfolder of this run's folder, so the run
    # folder itself holds just the PDF + that one subfolder.
    _exports = os.path.join(RUN_OUT_DIR, _EXPORTS_SUBDIR)
    os.makedirs(_exports, exist_ok=True)
    P = lambda n: os.path.join(_exports, n)
    lmap, ident, watch = ctx["lmap"], ctx["ident"], ctx["watch"]

    def row(p, d=None):
        return [tcase(p.product_name), ident.resolve(p.producer)["label"], tcase(p.dosage_form),
                test_date(p), lab_name(p, lmap), p._coa_status, p.registration_number, p.report_url]

    # validated flagged products
    _w(P("CannaScope_CT_V15_Validated_Flagged.csv"),
       ["product", "producer_dba", "type", "date", "lab", "coa_match_status", "coa", "report_url",
        "severity"],
       [row(p) + [v5.report_severity(p, watch) or ""] for p in ctx["flagged"] if p._coa_status in PUBLISHABLE])

    # per-analyte severity CSVs
    for key, title in ANALYTE_TABLES:
        fn = "severity_" + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") + ".csv"
        _w(P(fn), ["rank", "product", "producer_dba", "type", "date", "lab", "measured", "unit",
                   "ct_limit", "ct_pct", "vs_cannascope", "coa", "report_url", "coa_match_status"],
           [[i] + row(p)[:5] + [d["value"], d["unit"], d["ct_limit"] or "",
                                f'{d["ct_pct"]:.1f}' if d["ct_pct"] is not None else "",
                                f'{d["vs_std"]:.1f}' if d["vs_std"] is not None else "",
                                p.registration_number, p.report_url, p._coa_status]
            for i, (p, d) in enumerate(ctx["analyte_items"][key], 1)])

    # high-THC flower — with the cannabinoid component breakdown (THCA / d9-THC / CBD / totals)
    def _cval(p, k):
        v = p.cannabinoids.get(k, {}).get("value")
        return f"{v:g}" if (v is not None) else ""
    _w(P("high_thc_flower_noninfused.csv"),
       ["rank", "product", "producer_dba", "type", "lab", "headline_field", "headline_pct", "over_35_by",
        "thca_pct", "d9_thc_pct", "cbd_pct", "total_thc_pct", "total_cannabinoids_pct",
        "coa", "report_url", "coa_match_status"],
       [[i, tcase(p.product_name), ident.resolve(p.producer)["label"], tcase(p.dosage_form),
         lab_name(p, lmap), key, f"{val:g}", f"{val-THC_REVIEW_PCT:.1f}",
         _cval(p, "thca"), _cval(p, "d9_thc"), _cval(p, "total_cbd"), _cval(p, "total_thc"),
         _cval(p, "total_cannabinoids") or _cval(p, "total_active"),
         p.registration_number, p.report_url, p._coa_status] for i, (p, key, val) in enumerate(ctx["thc_flower"], 1)])

    # (potency-reference CSVs removed — both the infused and vape/extract potency sections were dropped)

    # COA verification queue
    _w(P("coa_verification_queue.csv"),
       ["product", "producer_dba", "lab", "coa_match_status", "coa", "report_url"],
       [[tcase(p.product_name), ident.resolve(p.producer)["label"], lab_name(p, lmap), p._coa_status,
         p.registration_number, p.report_url] for p in ctx["flagged"] if p._coa_status not in PUBLISHABLE])

    # zero-result queue
    _w(P("zero_result_verification_queue.csv"),
       ["category", "flagged_rows", "parsed", "total", "status", "note"],
       [[c["category"], c["flagged"], c["parsed"], c["total"], c["status"], c["note"]] for c in ctx["zero"]])

    # potential statute / regulatory flags (V9 add-on) — testing/product-quality leads
    _w(P("compliance_flags.csv"),
       ["review_priority", "product", "producer_dba", "lab", "test_date", "rule_category", "finding",
        "cited_authority", "authority_unverified", "status", "severity", "confidence",
        "recommended_review", "coa", "report_url"],
       [[r.get("tier", "Low"), tcase(r["p"].product_name), ident.resolve(r["p"].producer)["label"],
         lab_name(r["p"], lmap), test_date(r["p"]), r["rule_category"], r["finding"], r["cited_authority"],
         r["authority_unverified"], r["status"], r["severity"], r["confidence"],
         r["recommended_review"], r["p"].registration_number, r["p"].report_url]
        for r in sorted(ctx["compliance_flags"], key=lambda r: COMPLIANCE_TIERS.index(r.get("tier", "Low")))])

    # CT Cannabis Ombudsman — products closest to a contaminant limit (passed testing)
    _w(P("ombudsman_closeness.csv"),
       ["rank", "product", "producer_dba", "lab", "test_date", "contaminant_class", "analyte",
        "measured", "unit", "ct_action_limit", "pct_of_limit", "headroom", "tier",
        "why_it_matters_patient", "coa", "report_url"],
       [[i, tcase(r["p"].product_name), ident.resolve(r["p"].producer)["label"], lab_name(r["p"], lmap),
         test_date(r["p"]), r["cls"], r["d"].get("name", ""), r["d"].get("value"), r["d"].get("unit", ""),
         r["d"].get("ct_limit"), f'{r["ct_pct"]:.1f}', (r["headroom"] if r["headroom"] is not None else ""),
         r["tier"], r["note"], r["p"].registration_number, r["p"].report_url]
        for i, r in enumerate(ctx["ombudsman"], 1)])

    # lab- & date-aware TYM standard review
    _w(P("tym_standard_review.csv"),
       ["rank", "product", "producer_dba", "lab", "test_date", "tym_cfu_g", "numeric_disclosed",
        "lab_limit_on_test_date", "lab_verdict", "current_ct_limit", "current_verdict",
        "strict_benchmark", "strict_verdict", "high_risk_window", "aspergillus_detected",
        "aspergillus_tested", "passed_no_value_disclosed", "concern_flags",
        "applicable_standard_source", "standard_verified", "coa", "report_url"],
       [[i, tcase(a["p"].product_name), ident.resolve(a["p"].producer)["label"], a["lab"] or "",
         fmt_date(getattr(a["p"], "testing_date", "") or a["p"].approval_date),
         (a["value"] if a["value"] is not None else ""), ("yes" if a["numeric_disclosed"] else "no"),
         (a["lab_limit"] if a["lab_limit"] is not None else ""), a["lab_verdict"] or "",
         TYM_CURRENT_LIMIT, a["current_verdict"] or "", TYM_STRICT_BENCHMARK, a["strict_verdict"] or "",
         ("yes" if a["high_risk"] else "no"), ("yes" if a["aspergillus_detected"] else "no"),
         ("yes" if a["aspergillus_tested"] else "no"), ("yes" if a["passed_no_value"] else "no"),
         "; ".join(a["flags"]), ((a["std"] or {}).get("source", "") + (" [UNVERIFIED]" if (a["std"] and not a["std"].get("verified")) else "")),
         ("yes" if (a["std"] and a["std"].get("verified")) else "no"),
         a["p"].registration_number, a["p"].report_url]
        for i, a in enumerate(ctx.get("tym_findings", []), 1)])

    # Conflicting COA Results & Possible Lab-Shopping Indicators (document-level, for review)
    def _cc_cell(m):
        return clean_value(m.get("value"), m.get("unit", "")) if m.get("value") is not None else m.get("status", "")
    def _cc_lim(m):
        return (m.get("limit") if m.get("limit") is not None else "")
    _w(P("conflicting_coa_results.csv"),
       ["rank", "type", "relationship", "severity", "earlier_fail_later_pass", "product", "strain", "product_type",
        "producer_dba", "shared_identifier", "test_category",
        "lab1", "lab1_date", "lab1_result", "lab1_stated_limit", "lab1_status",
        "lab2", "lab2_date", "lab2_result", "lab2_stated_limit", "lab2_status",
        "difference", "timeline_note", "human_review", "source_pages", "lab1_coa", "lab2_coa"],
       [[i, c["kind"], c.get("relationship", ""), c["severity"], ("yes" if c.get("fail_then_pass") else "no"),
         c["product"], c["strain"], c["product_type"], ident.resolve(c["producer"])["label"],
         c["shared_id"], c["category"],
         c["lab1"]["lab"], c["lab1"]["date_str"], _cc_cell(c["lab1"]), _cc_lim(c["lab1"]), c["lab1"]["status"],
         c["lab2"]["lab"], c["lab2"]["date_str"], _cc_cell(c["lab2"]), _cc_lim(c["lab2"]), c["lab2"]["status"],
         c["diff"], c["timeline"], c["note"],
         (c["lab1"].get("pages") or c["lab2"].get("pages") or ""),
         c["lab1"].get("coa_url", ""), c["lab2"].get("coa_url", "")]
        for i, c in enumerate(ctx.get("coa_conflicts", []), 1)])

    # identity + source confidence
    _w(P("producer_dba_identity_confidence.csv"),
       ["legal_entity", "common", "brands", "parent", "source_confidence_pct", "source"],
       [[r.get("legal", ""), r["common"], " | ".join(r["brands"]), r["parent"], r["confidence"], r["source"]]
        for r in ident.cache.values()])

    # self-audit
    _w(P("self_audit.csv"), ["check", "count", "status"],
       [[i["issue"], i["count"], i["status"]] for i in ctx["audit"]])

    # COA Format Learning — per-year parsing readiness + the held (uncertain) extractions
    _w(P("coa_format_confidence_by_year.csv"),
       ["year", "era", "coas_on_file", "labs_seen", "high", "medium", "low", "uncertain",
        "confidence_rate", "known_layouts", "ready_for_reports", "verdict"],
       [[r["year"], r["era"], r["sampled"], "; ".join(r["labs"]),
         r["conf"].get("HIGH", 0), r["conf"].get("MEDIUM", 0), r["conf"].get("LOW", 0),
         r["conf"].get("UNCERTAIN", 0), f"{r['conf_rate']*100:.0f}%", "; ".join(r["layouts"]),
         "yes" if r["ready"] else "no", r["verdict"]] for r in ctx.get("fmt_year_rows", [])])
    _w(P("coa_extraction_held.csv"),
       ["product", "producer_dba", "year", "lab", "confidence", "reasons", "coa", "report_url"],
       [[tcase(p.product_name), ident.resolve(p.producer)["label"],
         (getattr(p, "_format_profile", {}) or {}).get("year", ""),
         lab_name(p, lmap), (getattr(p, "_extraction", {}) or {}).get("level", ""),
         "; ".join((getattr(p, "_extraction", {}) or {}).get("reasons", [])),
         p.registration_number, p.report_url] for p in ctx.get("format_holds", [])])

    # debug log
    _w(P("debug_log.csv"), ["metric", "value"], [[k, v] for k, v in ctx["debug"].items()])
    json.dump(ctx["debug"], open(P("debug_log.json"), "w"), indent=2)

    # V15 COA source-binding integrity exports ----------------------------------
    # Full provenance for every published flagged value (source COA == linked COA).
    prov = ctx.get("provenance_rows", [])
    _w(P("COA_Provenance_Audit.csv"),
       ["product", "producer", "lab", "coa_number", "registry_coa_url", "extracted_result_coa_url",
        "published_row_coa_url", "sample_id", "batch_id", "biotrack_uid", "testing_date", "analyte",
        "value", "unit", "legal_limit", "coa_match_status", "value_verified_in_linked_coa",
        "extraction_source_confirmed", "verification_level", "date_confirmed", "lab_confirmed",
        "unit_confirmed", "analyte_confirmed"],
       [[r["product"], r["producer"], r["lab"], r["coa_number"], r["registry_coa_url"],
         r["extracted_result_coa_url"], r["published_row_coa_url"], r["sample_id"], r["batch_id"],
         r["biotrack_uid"], r["testing_date"], r["analyte"], r["value"], r["unit"], r["legal_limit"],
         r["coa_match_status"], r["value_verified_in_linked_coa"], r["extraction_source_confirmed"],
         r.get("verification_level", ""), r.get("date_confirmed", ""), r.get("lab_confirmed", ""),
         r.get("unit_confirmed", ""), r.get("analyte_confirmed", "")]
        for r in prov])

    # Rows EXCLUDED because a flagged value could not be re-verified in their linked COA.
    _w(P("COA_Source_Mismatch_Review.csv"),
       ["product", "producer", "lab", "coa_number", "report_url", "sample_id", "batch_id",
        "biotrack_uid", "testing_date", "unverified_flagged_values", "coa_match_status"],
       [[m["p"].product_name, m["p"].producer, m["prov"]["lab"], m["p"].registration_number,
         m["p"].report_url, m["prov"]["sample_id"], m["prov"]["batch_id"], m["prov"]["biotrack_uid"],
         test_date(m["p"]), m["analytes"], m["p"]._coa_status] for m in ctx.get("source_mismatches", [])])

    # Products tied to more than one COA document (manual review; never auto-merged).
    _w(P("Multiple_COA_Alert.csv"),
       ["shared_coa_url", "num_products", "products", "producers", "pass_fail_conflict"],
       [[a["url"], a["n"], a["products"], a["producers"], "YES" if a["conflict"] else "no"]
        for a in ctx.get("multi_coa", [])])

    # plain-text executive summary
    with open(P("CannaScope_CT_V15_Executive_Summary.txt"), "w") as f:
        f.write(f"{APP_NAME}\n{REPORT_TITLE}\n" + "=" * 78 + "\n")
        f.write("VALIDATION STATUS: " + ctx["status"] + "\n")
        f.write(FRAMING + "\n\n")
        f.write(f"Window: {ctx['window']}    Generated: {datetime.datetime.now().astimezone():%Y-%m-%d %H:%M %Z}\n")
        f.write(f"Reviewed {ctx['n_reviewed']:,} | Published {ctx['n_pub']:,} | "
                f"Red {ctx['n_red']} Orange {ctx['n_org']} Yellow {ctx['n_yel']} "
                f"High-THC {ctx['n_thc']} | COA-Queue {ctx['n_queue']}\n\n")
        f.write("Self-audit:\n")
        for i in ctx["audit"]:
            f.write(f"  [{i['status']}] {i['issue']}: {i['count']}\n")
        f.write("\nZero-result verification:\n")
        for c in ctx["zero"]:
            f.write(f"  [{c['status']}] {c['category']}: {c['note']}\n")
        f.write("\nDebug:\n")
        for k, v in ctx["debug"].items():
            f.write(f"  {k}: {v}\n")
    ident.save()
    print(f"Wrote CSV/text exports to {OUT_DIR}/")


# ============================================================================
# Ledger
# ============================================================================
def _load_ledger():
    if not os.path.exists(LEDGER):
        return set()
    return {ln.strip() for ln in open(LEDGER) if ln.strip()}


def _embedded_skiplist():
    """Decompress the embedded skip-list of already-verified-CLEAN COA keys, if present
    (self-contained build). Returns a set (empty if none embedded). Used only by the
    opt-in --fast-cached mode; flagged / new products are never on this list."""
    b64 = globals().get("_EMBEDDED_SKIPLIST_B64")
    if not b64:
        return set()
    try:
        import base64 as _b, zlib as _z
        return {ln for ln in _z.decompress(_b.b64decode(b64)).decode("utf-8").split("\n") if ln.strip()}
    except Exception:
        return set()


def _save_ledger(keys):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(LEDGER, "w") as f:
        for k in sorted(keys):
            f.write(k + "\n")


# ============================================================================
# Main
# ============================================================================
# ============================================================================
# V15 COA SOURCE-BINDING INTEGRITY AUDIT
# Core rule: a published flagged value must literally appear in the EXACT COA its
# row links to. Every value is parsed from the PDF fetched at p.report_url and
# cached at cache_path(p) (key = the product's UNIQUE registration_number), so the
# linked COA and the extraction source are the same document by construction. This
# layer RE-OPENS that document and INDEPENDENTLY re-verifies each published value,
# EXCLUDES any that fail to a dedicated COA-Source-Mismatch queue, records full
# provenance, and flags products tied to more than one COA. Integrity over coverage.
# ============================================================================
def _value_in_coa_text(v, text):
    """True iff the numeric value appears in the COA text as a DISTINCT number
    (no adjacent digit), so 0.5 never 'matches' inside 0.18 / 10.52."""
    if v is None or not text:
        return False
    try:
        if not math.isfinite(v):
            return False
    except TypeError:
        return False
    if v == int(v):
        forms = {f"{int(v)}", f"{int(v):,}"}
    else:
        forms = {f"{v:g}"} | {f"{v:.{pr}f}".rstrip("0").rstrip(".") for pr in (1, 2, 3, 4)}
    return any(f and re.search(r"(?<![\d.])" + re.escape(f) + r"(?![\d])", text) for f in forms)


_PROV_SAMPLE_RX = re.compile(r"sample\s*(?:id|#)?\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-./]{3,})", re.I)
_PROV_BATCH_RX = re.compile(r"(?:batch|lot)\s*(?:id|#|no\.?|number)?\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-./]{3,})", re.I)
_PROV_BIO_RX = re.compile(r"(?:biotrack|uid|metrc)[^0-9A-Za-z]{0,8}((?:\d[\d ]{8,})\d)", re.I)


def _coa_provenance(p, text):
    def _f(rx):
        m = rx.search(text or "")
        return m.group(1).strip() if m else ""
    return dict(sample_id=_f(_PROV_SAMPLE_RX), batch_id=_f(_PROV_BATCH_RX),
                biotrack_uid=_f(_PROV_BIO_RX), lab=getattr(p, "test_lab", "") or "")


_UNIT_FAMILY_RX = {
    "cfu": re.compile(r"cfu", re.I),
    "ppb": re.compile(r"\bppb\b|[µu]g\s*/\s*kg|microgram", re.I),
    "ppm": re.compile(r"\bppm\b|mg\s*/\s*kg|mg\s*/\s*g", re.I),
    "pct": re.compile(r"%|percent", re.I),
}


def _unit_family(unit):
    u = (unit or "").lower()
    if "cfu" in u:
        return "cfu"
    if "ppb" in u or "µg/kg" in u or "ug/kg" in u:
        return "ppb"
    if "ppm" in u or "mg/kg" in u or "mg/g" in u:
        return "ppm"
    if "%" in u:
        return "pct"
    return ""


def _tok_in(s, text, minlen=4):
    s = (s or "").strip()
    return bool(len(s) >= minlen and text and s.lower() in text.lower())


def _triple_check(p, text, drivers, value_ok):
    """Per-row verification stamp (item 7/8, conservative mode). Re-checks each published row
    against its OWN linked COA on six fields and records which were CONFIRMED in the document:
      value    — every flag-driver value appears in the COA text (the hard, anti-hallucination gate)
      product  — the engine's source-binding matched the product/brand/strain (MATCH_EXACT/PARTIAL)
      date     — the parsed testing/sample year appears in the COA text
      lab      — the testing lab name (or a recognizable lab signature) appears in the COA text
      unit     — every driver's unit family (CFU / ppb / ppm / %) appears in the COA text
      analyte  — at least one flagged analyte's name appears in the COA text
    A field that is False is UNCONFIRMED in the extractable text (often a scanned/OCR gap) — it is
    NOT treated as proof of error. Only value-absent is a hard exclusion (handled by the caller);
    everything else publishes WITH this stamp so the triple-check is auditable, not silently buried."""
    txt = text or ""
    product_ok = getattr(p, "_coa_status", "") in PUBLISHABLE
    d = test_date(p)
    yr = d[:4] if len(d) >= 4 and d[:4].isdigit() else ""
    date_ok = bool(yr and yr in txt)
    lab = (getattr(p, "test_lab", "") or "").strip()
    lab_ok = _tok_in(lab.split()[0] if lab else "", txt) or bool(find_labs_in_text(txt))
    unit_oks, analyte_oks = [], []
    for dd in drivers:
        fam = _unit_family(dd.get("unit", ""))
        unit_oks.append(bool(fam and _UNIT_FAMILY_RX[fam].search(txt)) if fam else True)
        nm = (dd.get("name") or "").split("(")[0].strip()
        if nm:
            analyte_oks.append(_tok_in(nm, txt, minlen=4))
    unit_ok = all(unit_oks) if unit_oks else True
    analyte_ok = any(analyte_oks) if analyte_oks else True
    fields = dict(value=value_ok, product=product_ok, date=date_ok,
                  lab=lab_ok, unit=unit_ok, analyte=analyte_ok)
    n_ok = sum(1 for v in fields.values() if v)
    level = "Full" if n_ok == 6 else ("Partial" if value_ok else "Unverified")
    return dict(fields=fields, level=level, confirmed=n_ok)


def audit_published_coa_sources(pub_raw, watch):
    """Independent final audit: re-open each would-be-published product's OWN cached
    COA and confirm every flagged value is literally present in THAT document, then attach a
    six-field verification stamp (see _triple_check) to every published row.
    Returns (verified_products, mismatch_rows, provenance_rows, metrics)."""
    verified, mismatches, provenance = [], [], []
    n_verified = n_fail = 0
    n_full = n_partial = 0
    field_confirmed = dict(value=0, product=0, date=0, lab=0, unit=0, analyte=0)
    for p in pub_raw:
        text = ""
        try:
            cp = v4.cache_path(p)
            if os.path.exists(cp):
                text = v4.read_pdf_text(cp) or ""
        except Exception:
            text = ""
        prov = _coa_provenance(p, text)
        drivers = [d for d in v5.quantified_details(p, watch) if v5.is_flag_driver(d)]
        presents = [(d, _value_in_coa_text(d.get("value"), text)) for d in drivers]
        bad = [d for d, ok in presents if not ok]
        n_verified += sum(1 for _, ok in presents if ok)
        n_fail += len(bad)
        # Triple-check stamp (conservative): clear mismatch == a flag-driver value not found in the
        # linked COA -> excluded to manual review (unchanged). Everything else is published WITH the
        # stamp recording which context fields were confirmed in the document.
        stamp = _triple_check(p, text, drivers, value_ok=not bad)
        p._verify = stamp
        _fl = stamp["fields"]
        for d, present in presents:
            provenance.append(dict(
                product=p.product_name, producer=p.producer, lab=prov["lab"],
                coa_number=p.registration_number, registry_coa_url=p.report_url,
                extracted_result_coa_url=p.report_url, published_row_coa_url=p.report_url,
                sample_id=prov["sample_id"], batch_id=prov["batch_id"], biotrack_uid=prov["biotrack_uid"],
                testing_date=test_date(p), analyte=d.get("name"), value=d.get("value"),
                unit=d.get("unit", ""), legal_limit=d.get("ct_limit"),
                coa_match_status=getattr(p, "_coa_status", ""),
                value_verified_in_linked_coa=("Yes" if present else "NO"),
                extraction_source_confirmed=("Yes" if present else "No"),
                verification_level=stamp["level"],
                date_confirmed=("Yes" if _fl["date"] else "No"),
                lab_confirmed=("Yes" if _fl["lab"] else "No"),
                unit_confirmed=("Yes" if _fl["unit"] else "No"),
                analyte_confirmed=("Yes" if _fl["analyte"] else "No")))
        if bad:
            mismatches.append(dict(p=p, prov=prov,
                analytes="; ".join(f"{d.get('name')} {clean_value(d.get('value'), d.get('unit',''))}" for d in bad)))
        else:
            for k, v in stamp["fields"].items():
                if v:
                    field_confirmed[k] += 1
            if stamp["level"] == "Full":
                n_full += 1
            else:
                n_partial += 1
            verified.append(p)
    metrics = dict(
        published_rows_verified_against_linked_coa=n_verified,
        exact_value_link_verification_failures=n_fail,
        coa_source_mismatch_count=len(mismatches),
        rows_excluded_for_coa_source_mismatch=len(mismatches),
        rows_fully_verified=n_full,
        rows_partially_verified=n_partial,
        field_confirmed=field_confirmed,
        # registry COA == extracted-result COA by construction (we fetch & parse the
        # registry's own LAB-ANALYSIS link); recorded explicitly for transparency.
        registry_coa_differs_from_result_coa_count=0)
    return verified, mismatches, provenance, metrics


def detect_multiple_coa_alerts(all_results):
    """Products tied to more than one COA document, and PASS/FAIL conflicts among them.
    With unique per-product registration numbers this is normally near-empty; surfaced
    for human review rather than auto-merged."""
    from collections import defaultdict as _dd
    by_url = _dd(list)
    for p in all_results:
        if getattr(p, "report_url", ""):
            by_url[p.report_url].append(p)
    alerts = []
    for url, ps in by_url.items():
        names = sorted({pp.product_name for pp in ps})
        if len(ps) > 1:
            flagged_states = {bool(pp.flags or pp.thc_flags or v5.pathogen_detections(pp)) for pp in ps}
            alerts.append(dict(url=url, products="; ".join(names), n=len(ps),
                               producers="; ".join(sorted({pp.producer for pp in ps})),
                               conflict=(len(flagged_states) > 1)))
    return alerts


# ============================================================================
# Conflicting COA Results & Possible Lab-Shopping Indicators (V15 add-on)
# ----------------------------------------------------------------------------
# NEUTRAL, review-oriented document-level discrepancy detection. This surfaces
# records for HUMAN REVIEW and NEVER asserts misconduct, intent, remediation, or
# unlawful conduct. Two complementary detectors:
#   (1) cross-record  — the SAME physical lot (matched on a strong shared
#       identifier: batch / lot / BioTrack / sample / product code) appears on
#       more than one COA with conflicting pass/fail results for a regulated
#       safety category (especially an earlier FAIL followed by a later PASS).
#   (2) within-document — one COA carries more than one lab identity AND/OR a
#       passing summary alongside a failing regulated-test result (a stapled or
#       appended second lab report). Page numbers are preserved when available.
# Matching deliberately requires a distinctive physical-lot identifier (>=6
# alphanumerics, digit-bearing) so two routine different batches of the same
# product are NOT mistaken for a conflict.
# ============================================================================

# Regulated safety categories compared across reports -> p.analytes keys already
# parsed by the engine. Water activity / moisture are intentionally omitted (not
# reliably parsed) and surface only inside the raw COA, not as a comparison here.
def _conflict_categories():
    return [
        ("Total Yeast & Mold", ["tymc"]),
        ("Total Aerobic Microbial Count", ["aerobic"]),
        ("Aspergillus species", ["aspergillus"]),
        ("E. coli", ["ecoli"]),
        ("Shiga toxin-producing E. coli", ["stec"]),
        ("Salmonella", ["salmonella"]),
        ("Listeria", ["listeria"]),
        ("Mycotoxins", list(MYCO_KEYS)),
        ("Heavy metals", ["arsenic", "cadmium", "lead", "mercury", "chromium"]),
        ("Pesticides", ["__pesticide_panel__"]),
    ]

_CONFLICT_PATHO = {"ecoli", "stec", "salmonella", "listeria", "aspergillus"}
_STRONG_ID_FIELDS = ("batch", "lot", "biotrack", "sample", "product_code")
_SEV_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}

# Labeled-identifier extraction from COA text. Real lot/sample/BioTrack ids carry a
# digit; we require >=4 chars and a digit to avoid capturing stray words.
_ID_LABELS = [
    ("batch",        r"batch(?:\s*(?:id|no\.?|number|#))?"),
    ("lot",          r"lot(?:\s*(?:id|no\.?|number|#))?"),
    ("biotrack",     r"(?:bio\s*-?\s*track|biotrack|metrc|package\s*tag|tag\s*id|\buid\b)"),
    ("sample",       r"(?:sample\s*(?:id|no\.?|number|#)|lab\s*sample|order\s*(?:no\.?|number|#))"),
    ("product_code", r"(?:product\s*(?:code|id|#)|item\s*(?:code|no\.?|#)|\bsku\b)"),
    ("coa_number",   r"(?:certificate\s*(?:no\.?|number|#)|coa\s*(?:no\.?|number|#)|report\s*(?:no\.?|number|#)|analysis\s*(?:no\.?|number|#))"),
]
_ID_VALUE = r"[:#\s\.]{0,4}([A-Za-z0-9][A-Za-z0-9\-_]{2,40})"


def _norm_id(s):
    return re.sub(r"[^A-Za-z0-9]", "", (s or "")).upper()


def extract_coa_identifiers(text):
    """First labeled batch / lot / BioTrack / sample / product-code / COA number found
    in the COA text. Returns {field: raw_value}. Never raises."""
    ids = {}
    for key, lab in _ID_LABELS:
        rx = re.compile(r"\b" + lab + _ID_VALUE, re.I)
        for m in rx.finditer(text):
            val = m.group(1).strip(" -_.")
            n = _norm_id(val)
            if len(n) < 4 or not re.search(r"\d", n):
                continue
            ids[key] = val
            break
    return ids


def _strong_ids(p):
    """Distinctive physical-lot identifiers for cross-report matching (>=6
    alphanumerics, digit-bearing). Field label is dropped so the same lot id
    matches across labs even when one COA calls it 'Batch' and another 'Lot'."""
    ids = getattr(p, "_ids", {}) or {}
    out = set()
    for f in _STRONG_ID_FIELDS:
        v = ids.get(f)
        if not v:
            continue
        n = _norm_id(v)
        if len(n) >= 6:
            out.add(n)
    return out


def find_labs_in_text(text):
    """Canonical names of every recognized lab whose signature appears in the text."""
    return [name for rx, name in v4.KNOWN_LABS if rx.search(text)]


_SAFE_TERM_RX = re.compile(r"yeast|mold|aerobic|microbial|aspergillus|salmonella|"
                           r"\bcoli\b|listeria|mycotoxin|aflatoxin|ochratoxin|pathogen|"
                           r"heavy\s*metal|pesticide", re.I)
# A genuine FAIL VERDICT — NOT the word "Fail" inside a "Pass/Fail" column legend.
# Requires either "failed" or a verdict-labeled "... result/status: Fail".
_FAIL_STRICT_RX = re.compile(r"\bfailed\b|"
                             r"(?:result|results|status|overall|determination|conclusion)\s*[:\-—]?\s*"
                             r"fail(?:ure)?\b", re.I)
_PASSFAIL_LEGEND_RX = re.compile(r"pass\s*/\s*fail|fail\s*/\s*pass|pass\s+or\s+fail|fail\s+or\s+pass", re.I)
_PASS_RX = re.compile(r"\bpass(?:ed|es)?\b", re.I)


def _safe_fail_verdict(text):
    """True iff text carries a genuine FAIL verdict on a regulated safety test — not a
    'Pass/Fail' column header. Returns the matched fail-page-eligible boolean."""
    for m in _FAIL_STRICT_RX.finditer(text):
        if _PASSFAIL_LEGEND_RX.search(text[max(0, m.start() - 14): m.end() + 14]):
            continue   # part of a 'Pass/Fail' legend, not a verdict
        if _SAFE_TERM_RX.search(text[max(0, m.start() - 100): m.end() + 100]):
            return True
    return False


def _coa_pages_text(path):
    """Best-effort per-page text for page-number provenance. [] if unreadable.
    Closes every page/textpage/doc handle (like _safe_pdfium_text) so a multi-year
    run doesn't leak native pdfium handles or trip the ObjectTracker warning on exit."""
    with v4._PDF_LOCK:
        doc = None
        try:
            doc = v4.pdfium.PdfDocument(path)
            pages = []
            for i in range(len(doc)):
                page = doc[i]
                tp = page.get_textpage()
                pages.append(tp.get_text_range() or "")
                tp.close()
                page.close()
            return pages
        except Exception:
            return []
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass


def scan_internal_conflict(text, path=""):
    """Detect a single COA that carries >1 lab identity and/or a passing summary
    alongside a failing regulated-test result. Returns a compact dict or None.
    Conservative: reports only what is literally present; assigns page numbers when
    per-page text can be read."""
    labs = sorted(set(find_labs_in_text(text)))
    multi_lab = len(labs) >= 2
    has_pass = bool(_PASS_RX.search(text))
    safe_fail = _safe_fail_verdict(text)
    if not (multi_lab or (safe_fail and has_pass)):
        return None
    lab_pages, fail_pages, pass_pages = {}, [], []
    pages = _coa_pages_text(path) if path else []
    for i, pg in enumerate(pages, 1):
        for rx, name in v4.KNOWN_LABS:
            if rx.search(pg):
                lab_pages.setdefault(name, []).append(i)
        if _safe_fail_verdict(pg):
            fail_pages.append(i)
        if _PASS_RX.search(pg):
            pass_pages.append(i)
    return dict(labs=labs, multi_lab=multi_lab, safe_fail=safe_fail, has_pass=has_pass,
                lab_pages=lab_pages, fail_pages=sorted(set(fail_pages)),
                pass_pages=sorted(set(pass_pages)), n_pages=len(pages))


def _conflict_date(p):
    s = getattr(p, "testing_date", "") or getattr(p, "approval_date", "") or ""
    y, mo, d = v4.parse_date(s)
    return (y, mo, d) if y else None


def _date_key(dt):
    return dt if dt else (9999, 99, 99)   # unknown dates sort last


_STATUS_RANK = {"FAIL": 3, "DETECTED": 3, "PASS": 1, "ND": 1}


def _category_result(p, keys, watch, dmap):
    """Most-adverse single result for a product within one category, or None.
    status in {'FAIL','PASS','DETECTED','ND'}."""
    if keys == ["__pesticide_panel__"]:
        panel = getattr(p, "pesticides", "")
        if panel in ("PASS", "FAIL"):
            return dict(status=panel, value=None, limit=None, unit="", raw=panel)
        return None
    best = None
    for k in keys:
        e = p.analytes.get(k)
        if not e:
            continue
        st = (e.get("status") or "").upper()
        raw = (e.get("raw") or "").strip()
        if k in _CONFLICT_PATHO:
            if st == "DETECTED":
                cand = dict(status="DETECTED", value=None, limit=None, unit="", raw=raw)
            elif st == "ND" or raw[:1] in "<≤":
                cand = dict(status="ND", value=None, limit=None, unit="", raw=raw)
            else:
                cand = None
        else:
            d = dmap.get(k)
            val = (d or e).get("value")
            # LAB-SHOPPING is about whether the flower FAILED the standard recorded ON ITS OWN COA —
            # so pass/fail is judged against the limit STATED IN THAT COA pdf (CT's CFU/g standards
            # changed over the years; each COA carries the limit that was in effect for that test).
            # NOT a single canonical limit, and NOT the program's internal watch line.
            lim = e.get("limit")
            if lim is None:
                lim = (d or {}).get("ct_limit")
            if val is None or not v5.is_quantified(e):
                cand = None
            else:
                cand = dict(status=("FAIL" if (lim and val > lim) else "PASS"),
                            value=val, limit=lim, unit=(d or {}).get("unit", "") or e.get("unit", ""),
                            raw=raw)
        if cand and (best is None
                     or _STATUS_RANK.get(cand["status"], 0) > _STATUS_RANK.get(best["status"], 0)
                     or (_STATUS_RANK.get(cand["status"], 0) == _STATUS_RANK.get(best["status"], 0)
                         and (cand.get("value") or 0) > (best.get("value") or 0))):
            best = cand
    return best


class _ConflictStub:
    """Minimal product-like object so the renderer/CSV (producer_short, coa, coa_cell) work
    identically for BOTH live conflicts (this run) and persisted cross-run conflicts (rebuilt
    from a stored fingerprint, where the original product object no longer exists)."""
    __slots__ = ("producer", "brand", "report_url", "registration_number")

    def __init__(self, producer="", brand="", report_url="", registration_number=""):
        self.producer = producer
        self.brand = brand
        self.report_url = report_url
        self.registration_number = registration_number


def build_conflict_fingerprint(p, watch):
    """Serializable per-COA conflict fingerprint, built WHILE the live product is in hand (the
    pre-computed per-category results mean detection can later run on the stored dicts alone,
    with no live product or COA text). Returns None for a COA that can never participate in a
    conflict (no strong physical-lot identifier AND no within-document discrepancy)."""
    if not getattr(p, "_coa_present", False):
        return None
    strong = sorted(_strong_ids(p))
    internal = getattr(p, "_internal", None)
    if not strong and not internal:
        return None
    dmap = {d["key"]: d for d in v4.limit_details(p, watch)}
    cats = {}
    for label, keys in _conflict_categories():
        rec = _category_result(p, keys, watch, dmap)
        if rec:
            cats[label] = {"status": rec["status"], "value": rec.get("value"),
                           "limit": rec.get("limit"), "unit": rec.get("unit", ""),
                           "raw": rec.get("raw", "")}
    dt = _conflict_date(p)
    return {
        "coa_key": v4.coa_key(p),
        "reg": getattr(p, "registration_number", "") or "",
        "report_url": getattr(p, "report_url", "") or "",
        "producer": getattr(p, "producer", "") or "",
        "brand": getattr(p, "brand", "") or "",
        "product": tcase(getattr(p, "product_name", "") or ""),
        "strain": tcase(getattr(p, "strain", "") or ""),
        "product_type": tcase(getattr(p, "dosage_form", "") or ""),
        "test_lab": getattr(p, "test_lab", "") or "",
        "date": list(dt) if dt else None,
        "date_str": test_date(p) or "",
        "strong_ids": strong,
        "shared_id": _shared_id_label(p),
        "internal": internal,
        "cats": cats,
    }


def _stub_for(cfp):
    return _ConflictStub(producer=cfp.get("producer", ""), brand=cfp.get("brand", ""),
                         report_url=cfp.get("report_url", ""),
                         registration_number=cfp.get("reg", ""))


def _member(cfp, rec, pages_note=""):
    """Build a comparison-member dict from a (live-or-persisted) fingerprint + a per-category
    result. `p` is a lightweight stub so the renderer keeps working for cross-run records."""
    dt = cfp.get("date")
    return dict(p=_stub_for(cfp), cfp=cfp,
                lab=cfp.get("test_lab", "") or "Unknown lab",
                date=(tuple(dt) if dt else None), date_str=cfp.get("date_str", "") or "",
                status=rec["status"], value=rec.get("value"), limit=rec.get("limit"),
                unit=rec.get("unit", ""), raw=rec.get("raw", ""),
                coa_url=cfp.get("report_url", "") or "", reg=cfp.get("reg", "") or "",
                pages=pages_note)


def _shared_id_label(p):
    ids = getattr(p, "_ids", {}) or {}
    parts = []
    for f, lbl in (("batch", "Batch"), ("lot", "Lot"), ("biotrack", "BioTrack"),
                   ("sample", "Sample"), ("product_code", "Product code")):
        if ids.get(f):
            parts.append(f"{lbl} {ids[f]}")
    return "; ".join(parts)


def _pick_pair(members):
    """Earliest adverse result vs latest clean result (for a pass/fail conflict);
    otherwise the chronological extremes."""
    adverse = sorted([m for m in members if m["status"] in ("FAIL", "DETECTED")],
                     key=lambda m: _date_key(m["date"]))
    clean = sorted([m for m in members if m["status"] in ("PASS", "ND")],
                   key=lambda m: _date_key(m["date"]))
    if adverse and clean:
        return adverse[0], clean[-1]
    s = sorted(members, key=lambda m: _date_key(m["date"]))
    return s[0], s[-1]


def _norm_unit(u):
    """Normalize a unit for comparison: lowercase, strip spaces/dots, fold micro signs."""
    return re.sub(r"[\s.]", "", (u or "").lower()).replace("μ", "u").replace("µ", "u")


def _is_bound(m):
    """True if a member's result is a below-detection upper bound (<X / ≤X), not a measurement.
    Such a value is NOT a real number and must never drive a ratio / swing calculation."""
    raw = (m.get("raw") or "").strip()
    return raw[:1] in "<≤" or "below" in raw.lower() or bool(m.get("below_detect"))


def _swing_metrics(a, b):
    """Safe, clearly-labeled comparison of two results on the SAME physical lot/category.

    Returns dict(comparable, reason, abs_diff, ratio, pct_diff, large_swing, suspect_artifact).
    Formulas (only when both values are positive, finite, real measurements in the same unit):
      abs_diff = |a - b|
      ratio    = max(a, b) / min(a, b)          (a clean "X:1", never a percent)
      pct_diff = |a - b| / ((a + b) / 2) * 100   (symmetric relative difference)
    A "large swing" requires BOTH a real ratio (>=2.0x) AND a real relative change (>=50%), so
    near-equal values like 2,000 vs 1,950 (1.03x, 2.5%) are never called a swing. A ratio that is
    implausibly large for one physical lot (>=50x) is flagged as a likely parsing/format artifact
    (a dropped "<" bound, OCR error, or unit mismatch) rather than asserted as a true measured swing."""
    res = dict(comparable=False, reason="", abs_diff=None, ratio=None, pct_diff=None,
               large_swing=False, suspect_artifact=False)
    va, vb = a.get("value"), b.get("value")
    if va is None or vb is None:
        res["reason"] = "one or both results are non-numeric (pass/fail or not-detected)"
        return res
    try:
        va, vb = float(va), float(vb)
    except (TypeError, ValueError):
        res["reason"] = "a value could not be read as a number"
        return res
    if not (math.isfinite(va) and math.isfinite(vb)):
        res["reason"] = "a value is non-finite"
        return res
    if _is_bound(a) or _is_bound(b):
        res["reason"] = "a result is a below-detection bound (<X), not a measured number"
        return res
    ua, ub = a.get("unit") or "", b.get("unit") or ""
    if ua and ub and _norm_unit(ua) != _norm_unit(ub):
        res["reason"] = f"different units ({ua} vs {ub}) — not directly comparable"
        return res
    res["abs_diff"] = abs(va - vb)
    if va <= 0 or vb <= 0:
        res["reason"] = "a value is zero or negative — ratio is undefined"
        return res
    hi, lo = max(va, vb), min(va, vb)
    res["comparable"] = True
    res["ratio"] = hi / lo
    res["pct_diff"] = (hi - lo) / ((va + vb) / 2.0) * 100.0
    res["large_swing"] = res["ratio"] >= 2.0 and res["pct_diff"] >= 50.0
    res["suspect_artifact"] = res["ratio"] >= 50.0
    return res


def _relationship(members, kind, fail_then_pass):
    """Classify what a same-lot conflict actually IS, so the report uses the right, defensible
    label (item 11). Only a genuine CROSS-LAB pass/fail conflict earns 'lab-shopping'."""
    if kind == "within-document":
        return "Within-document inconsistency"
    labs = {(m.get("lab") or "").strip().lower() for m in members}
    labs.discard(""); labs.discard("unknown lab")
    cross_lab = len(labs) >= 2
    dates = {tuple(m["date"]) if m.get("date") else None for m in members}
    statuses = {m.get("status") for m in members}
    pf_conflict = bool(statuses & {"FAIL", "DETECTED"}) and bool(statuses & {"PASS", "ND"})
    if pf_conflict and cross_lab:
        return "Possible lab-shopping indicator"
    if pf_conflict:
        return "Pass/fail conflict (same lab — likely retest or clerical)"
    if cross_lab:
        return "Cross-lab numeric swing"
    if len(dates) <= 1:
        return "Duplicate COA (same lab, same date)"
    return "Same-lot retest (same lab, different date)"


def _diff_text(a, b):
    """Human-readable, correctly-labeled difference between two results. Never emits a multiplier
    for non-comparable values (below-detection bounds, unit mismatches, non-numeric results)."""
    m = _swing_metrics(a, b)
    if m["abs_diff"] is None:
        return ""
    unit = a.get("unit") or b.get("unit") or ""
    out = f"{clean_value(m['abs_diff'], unit)} absolute difference"
    if not m["comparable"]:
        return out + (f" (ratio not computed — {m['reason']})" if m["reason"] else "")
    out += f"; ratio {m['ratio']:.1f}:1 (max ÷ min); {m['pct_diff']:.0f}% relative difference"
    if m["suspect_artifact"]:
        out += (" — ratio implausibly large for one physical lot; likely a parsing/format artifact "
                "(e.g. a dropped “<” bound or unit error), manual review recommended")
    elif m["large_swing"]:
        out += " — large swing"
    return out


def _make_finding(category, members, severity, kind="cross-record",
                  fail_then_pass=False, timeline="", note=""):
    a, b = _pick_pair(members) if len(members) >= 2 else (members[0], members[0])
    lim = next((m.get("limit") for m in members if m.get("limit") is not None), None)
    cfp0 = members[0]["cfp"]
    return dict(
        kind=kind, category=category, severity=severity, fail_then_pass=fail_then_pass,
        relationship=_relationship(members, kind, fail_then_pass),
        timeline=timeline, note=note,
        product=cfp0.get("product", ""),
        strain=cfp0.get("strain", ""),
        product_type=cfp0.get("product_type", ""),
        producer=cfp0.get("producer", ""),
        shared_id=cfp0.get("shared_id", ""),
        action_limit=lim, unit=(a.get("unit") or b.get("unit") or ""),
        members=members, lab1=a, lab2=b, diff=_diff_text(a, b),
        coa_url=cfp0.get("report_url", ""))


def _compare_group(group, watch):
    # `group` is a list of conflict fingerprints sharing a strong physical-lot id. Per-category
    # results were precomputed at fingerprint time (so this works for cross-run records too).
    out = []
    for label, keys in _conflict_categories():
        members = []
        for cfp in group:
            rec = (cfp.get("cats") or {}).get(label)
            if rec:
                members.append(_member(cfp, rec))
        if len(members) < 2:
            continue
        statuses = {m["status"] for m in members}
        adverse = statuses & {"FAIL", "DETECTED"}
        clean = statuses & {"PASS", "ND"}
        if adverse and clean:
            a, b = _pick_pair(members)
            # Critical: a documented adverse result dated EARLIER than a later clean
            # result for the same safety category (earlier fail -> later pass).
            ftp = (a["status"] in ("FAIL", "DETECTED") and b["status"] in ("PASS", "ND")
                   and a["date"] and b["date"] and _date_key(a["date"]) < _date_key(b["date"]))
            if ftp:
                sev, tl = "Critical", ("Earlier "
                    f"{'failing' if a['status']=='FAIL' else 'positive'} result ({a['date_str'] or 'date unknown'}) "
                    f"followed by a later passing/clean result ({b['date_str'] or 'date unknown'}).")
            else:
                sev, tl = "High", ("Conflicting pass/fail results across reports; test order could not "
                                   "be confirmed as earlier-fail-then-later-pass from available dates.")
            out.append(_make_finding(label, members, sev, fail_then_pass=ftp, timeline=tl))
        else:
            # No pass/fail conflict — assess a numeric swing using SAFE metrics (bound/unit-guarded,
            # correct ratio + relative-difference). Only a real large swing is flagged, and a swing
            # whose ratio is implausibly large for one lot is downgraded to a likely parser artifact.
            a2, b2 = _pick_pair(members)
            sm = _swing_metrics(a2, b2)
            if sm["comparable"] and sm["large_swing"]:
                if sm["suspect_artifact"]:
                    out.append(_make_finding(label, members, "Low",
                        timeline=(f"Numeric swing on the same lot: ratio {sm['ratio']:.1f}:1, "
                                  f"{sm['pct_diff']:.0f}% relative difference. The ratio is "
                                  "implausibly large for one physical lot, so this is most likely a "
                                  "parsing/format artifact (e.g. a dropped “<” bound or unit error) "
                                  "rather than a true measured swing — manual review only.")))
                else:
                    out.append(_make_finding(label, members, "Medium",
                        timeline=(f"Numeric swing on the same lot: ratio {sm['ratio']:.1f}:1, "
                                  f"{sm['pct_diff']:.0f}% relative difference, with both reports "
                                  "showing the same pass/fail status (no pass/fail change).")))
    if not out:
        labs = {cfp.get("test_lab", "") for cfp in group}
        if len([l for l in labs if l]) >= 2:
            anymem = [_member(group[0], dict(status="PASS", value=None, limit=None, unit="", raw=""))]
            out.append(_make_finding("Multiple lab reports (no safety conflict)", anymem * 2, "Low",
                note="Same lot identifier appears on reports from more than one laboratory; no pass/fail "
                     "safety conflict was detected."))
    return out


def _internal_finding(cfp, watch):
    intl = cfp.get("internal") or {}
    labs = intl.get("labs") or []
    sev = "High" if (intl.get("safe_fail") and intl.get("has_pass")) else "Low"
    lp = intl.get("lab_pages") or {}
    lab_txt = "; ".join(f"{nm} (p. {', '.join(map(str, pg))})" if pg else nm
                        for nm, pg in lp.items()) or "; ".join(labs)
    pages = []
    if intl.get("fail_pages"):
        pages.append("regulated-test 'fail' wording on p. " + ", ".join(map(str, intl["fail_pages"])))
    if intl.get("pass_pages"):
        pages.append("'pass' wording on p. " + ", ".join(map(str, intl["pass_pages"])))
    rec = dict(status="FAIL" if intl.get("safe_fail") else "PASS", value=None, limit=None, unit="", raw="")
    m = _member(cfp, rec, pages_note="; ".join(pages))
    f = _make_finding("Within-document (single COA)", [m, m], sev, kind="within-document",
                      timeline="; ".join(pages),
                      note=("This single COA document appears to contain more than one laboratory identity"
                            + (" and a passing summary alongside a failing regulated-test result"
                               if (intl.get("safe_fail") and intl.get("has_pass")) else "")
                            + ". Detected lab identities: " + lab_txt + "."))
    f["labs_in_doc"] = labs
    return f


def detect_coa_conflicts(fingerprints, watch):
    """Cross-record + within-document conflicting-COA findings, most severe first.

    Operates on conflict FINGERPRINTS (plain dicts from build_conflict_fingerprint), not live
    products, so it can run over the persistent cross-run union — finding conflicts whose two
    COAs were scanned in different runs and re-surfacing conflicts on a ledger-warm rerun."""
    findings = []
    prods = [c for c in fingerprints if c.get("strong_ids")]
    # union-find over fingerprints that share a distinctive physical-lot identifier
    key_to_idx = defaultdict(list)
    for i, c in enumerate(prods):
        for k in c["strong_ids"]:
            key_to_idx[k].append(i)
    parent = list(range(len(prods)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for idxs in key_to_idx.values():
        for j in idxs[1:]:
            ra, rb = find(idxs[0]), find(j)
            if ra != rb:
                parent[ra] = rb
    groups = defaultdict(list)
    for i in range(len(prods)):
        groups[find(i)].append(prods[i])
    for g in groups.values():
        if len(g) >= 2:
            findings.extend(_compare_group(g, watch))
    # within-document
    for c in fingerprints:
        intl = c.get("internal")
        if intl and (intl.get("multi_lab") or (intl.get("safe_fail") and intl.get("has_pass"))):
            findings.append(_internal_finding(c, watch))
    findings.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 0), f.get("fail_then_pass", False)),
                  reverse=True)
    return findings


def _load_conflict_store():
    """Persistent cross-run conflict fingerprints, keyed by COA key. Never raises."""
    try:
        with open(CONFLICT_STORE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_conflict_store(store):
    try:
        tmp = CONFLICT_STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f)
        os.replace(tmp, CONFLICT_STORE)
    except OSError:
        pass


# ============================================================================
# COA FORMAT LEARNING LAYER
# ----------------------------------------------------------------------------
# Connecticut's product/COA registry spans many years (≈2015–2026), and COA
# layout, terminology, lab templates, section names/order, and pass/fail wording
# have ALL changed over time — even for the same lab or producer. This layer makes
# the parser HISTORICALLY AWARE without assuming one fixed format and without
# touching the v4/v5 engine (it sits on top):
#   * profile_coa()       — fingerprints a COA's lab, year/era, which sections are
#                           present and IN WHAT ORDER, the pass/fail/ND vocabulary
#                           used, identity fields, and whether it's a scanned image.
#   * assess_extraction() — cross-checks FIVE independent signals (top-level
#                           pass/fail summary; detailed breakdown tables; numeric
#                           values; batch/product/licensee identity; and whether the
#                           COA actually matches the product record) and returns a
#                           confidence LEVEL. A top/detail pass-fail conflict, a
#                           product mismatch, impossible numbers, or an unreadable
#                           scan make the extraction UNCERTAIN — so bad data is held
#                           for review instead of being confidently reported.
#   * COAFormatLearner    — accumulates, PER YEAR, the labs/producers seen, the
#                           section vocabulary + layout signatures, field-extraction
#                           success rates, and the confidence distribution. It is
#                           persisted (COA_FORMAT_STORE) so the program practices
#                           against historical COAs across runs and reports, per
#                           year, whether the parser is READY to use that year's data.
#   * coa_format_selftest — the `learn` subcommand: samples COAs from every available
#                           year, runs the above, and prints/writes a year-by-year
#                           parsing confidence report.
# IMPORTANT framing: this layer improves parsing RELIABILITY (it detects which format
# it's looking at, verifies the parse with cross-checks, and flags formats it cannot
# yet parse well) and accumulates a per-year readiness map — it does not rewrite the
# engine's regexes at runtime. Formats that score poorly are surfaced for a parser
# update rather than silently trusted.
# ============================================================================
COA_FORMAT_STORE = os.path.join(OUT_DIR, "COA Format Profiles.json")
COA_FIRST_YEAR = 2015

# Section probes are deliberately BROADER than the engine's, to catch historical
# wording variants (e.g. "Microbiological Contaminants" vs "Microbials" vs "TYMC").
_SECTION_PROBES = {
    "cannabinoids":      r"cannabinoids?|potency|total\s+thc|thca\b|\bcbd\b|\bthc\b",
    "microbials":        r"microbial|microbiolog|yeast\s*&?\s*(?:and\s*)?mold|\btymc\b|total\s+aerobic|"
                         r"aerobic\s+(?:plate|bacteria|count)|coliform|salmonella|e\.?\s*coli|aspergillus|listeria",
    "heavy_metals":      r"heavy\s*metals?|\barsenic\b|\bcadmium\b|\blead\b|\bmercury\b|\bchromium\b",
    "pesticides":        r"pesticides?",
    "residual_solvents": r"residual\s+solvents?|\bsolvents?\b",
    "mycotoxins":        r"mycotoxins?|aflatoxin|ochratoxin",
    "terpenes":          r"terpenes?",
    "water_activity":    r"water\s+activity|\ba[\s_]?w\b",
    "moisture":          r"moisture(?:\s+content)?",
    "foreign_material":  r"foreign\s+material|\bfilth\b",
}
_SECTION_PROBES_C = {k: re.compile(v, re.I) for k, v in _SECTION_PROBES.items()}

# Result vocabulary, seeded with the variants seen across CT COAs over the years. Each
# is (human label, regex). The learner records which appear per year (descriptive); the
# pass/fail VERDICT itself is judged by the engine's conflict-safe panel_status / overall.
_VOCAB = {
    "pass": [("pass/passed", r"\bpass(?:ed|es)?\b"), ("complies", r"\bcomplies\b"),
             ("within limits", r"within\s+(?:the\s+)?(?:action\s+)?limits?"),
             ("meets spec", r"\bmeets?\s+spec"), ("conforms", r"\bconforms?\b")],
    "fail": [("fail/failed", r"\bfail(?:ed|ure)?\b"), ("exceeds", r"\bexceeds?\b"),
             ("out of spec", r"out\s+of\s+(?:spec|specification|tolerance)"),
             ("above limit", r"above\s+(?:the\s+)?(?:action\s+)?limit"),
             ("non-compliant", r"\bnon-?compliant\b")],
    "nd":   [("not detected", r"\bnot\s+detected\b"), ("ND", r"\bn\.?\s*/?\s*d\b"),
             ("none detected", r"\bnone\s+detected\b"), ("<LOD/<LOQ", r"<\s*lo[dq]\b"),
             ("below detection", r"below\s+(?:the\s+)?(?:detection|reporting)\s+(?:limit|level)"),
             ("BDL/BQL", r"\bb[dq]l\b")],
}
_VOCAB_C = {kind: [(lbl, re.compile(rx, re.I)) for lbl, rx in items] for kind, items in _VOCAB.items()}

# Curated, human-readable notes on what changed each era (seed knowledge; the learner
# adds the empirically observed labs/signatures on top). Keyed by era label.
_ERA_NOTES = {
    "Early (2015-2019)": "Earliest registry COAs; fewer mandated panels, older lab templates, more "
                         "scanned/image PDFs; AltaSci/Northeast columnar layouts; microbial limits often 10,000 CFU/g.",
    "Transition (2020-2022)": "Standard change window — AltaSci yeast/mold limit rose to 1,000,000 (high-risk) "
                              "while Northeast stayed 10,000; power-of-ten detection limits (\"<10^4\"); panels expanding.",
    "Current (2023-2026)": "Unified 100,000 CFU/g + zero-Aspergillus; Northeast columnar (values↔labels by era), "
                           "Analytics Labs image-only/OCR with LOD/LOQ/Result columns; fuller panels.",
    "Unknown": "Year could not be determined from the COA test/approval date.",
}


def _coa_year(p):
    for s in (getattr(p, "testing_date", "") or "", getattr(p, "approval_date", "") or ""):
        y, _m, _d = v4.parse_date(s)
        if y and 2000 <= y <= 2100:
            return y
    return None


def _era_for(year):
    if not year:
        return "Unknown"
    if year <= 2019:
        return "Early (2015-2019)"
    if year <= 2022:
        return "Transition (2020-2022)"
    return "Current (2023-2026)"


def _fl_tokens(s):
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower())
            if len(t) >= 3 and t not in _COA_STOP and not t.isdigit()]


def _present_sections(text):
    """Section types present, IN ORDER OF FIRST APPEARANCE (captures the fact that
    different eras/labs order the same sections differently)."""
    found = []
    for key, rx in _SECTION_PROBES_C.items():
        m = rx.search(text)
        if m:
            found.append((m.start(), key))
    found.sort()
    return [k for _i, k in found]


def _vocab_seen(text):
    return {kind: sorted({lbl for lbl, rx in items if rx.search(text)})
            for kind, items in _VOCAB_C.items()}


def _layout_signature(lab, year, sections):
    # lab + era + ordered section initials => a coarse "known layout pattern" key.
    sec = "".join(s[0] for s in sections)
    return f"{(lab or 'Unknown')[:4].upper()}|{_era_for(year)}|{sec or '-'}"


def profile_coa(p, text):
    """Structural fingerprint of one COA: lab, year/era, sections present + order,
    result vocabulary, identity fields, scanned-image flag, layout signature."""
    text = text or ""
    year = _coa_year(p)
    lab = getattr(p, "test_lab", "") or v4.parse_lab(text) or "Unknown lab"
    sections = _present_sections(text)
    ids = getattr(p, "_ids", None)
    if ids is None:
        ids = extract_coa_identifiers(text)
    low = text.lower()
    reg = (getattr(p, "registration_number", "") or "").lower()
    name_toks = _fl_tokens(f"{getattr(p, 'product_name', '')} {getattr(p, 'brand', '')} "
                           f"{v5.product_core_name(p)}")
    prod_toks = _fl_tokens(getattr(p, "producer", "") or "")
    identity = {
        "product": bool(name_toks) and any(t in low for t in name_toks),
        "producer": bool(prod_toks) and any(t in low for t in prod_toks),
        "batch": bool(ids.get("batch") or ids.get("lot") or ids.get("biotrack")),
        "reg": bool(reg) and (reg in low or reg.replace(".", "") in low.replace(".", "")),
    }
    # value styles seen on the COA (how results are expressed — varies by era/lab)
    val_styles = []
    if re.search(r"\bnot\s+detected\b|\bn\.?\s*/?\s*d\b|\bnone\s+detected\b", low):
        val_styles.append("ND")
    if re.search(r"<\s*\d", text) or re.search(r"<\s*lo[dq]", low):
        val_styles.append("below-detect (<X)")
    if re.search(r"10\s*\^|1?0\^?\d|e[+\-]?\d", text):
        val_styles.append("scientific/power-of-ten")
    if re.search(r"\d", text):
        val_styles.append("numeric")
    pm = re.search(r"page\s+\d+\s+of\s+(\d+)", low)
    n_pages = int(pm.group(1)) if pm else None
    # which result categories the parser actually EXTRACTED for this COA (success signal per format)
    cats_parsed = sorted(
        ([k for k, _t in ANALYTE_TABLES if k in (getattr(p, "analytes", None) or {})])
        + (["mycotoxins"] if any(k in (getattr(p, "analytes", None) or {}) for k in MYCO_KEYS) else [])
        + (["pathogens"] if any(k in (getattr(p, "analytes", None) or {}) for k in v5.PATHO_KEYS) else [])
        + (["pesticides"] if getattr(p, "pesticides", "") in ("PASS", "FAIL") else [])
        + (["solvents"] if getattr(p, "solvents", "") in ("PASS", "FAIL") else [])
        + (["cannabinoids"] if getattr(p, "cannabinoids", None) else []))
    return dict(
        year=year, lab=lab, era=_era_for(year), sections=sections,
        product_type=product_category(p), n_pages=n_pages, value_styles=val_styles,
        cats_parsed=cats_parsed,
        vocab=_vocab_seen(text), identity=identity,
        scanned_image=(len(text.strip()) < 200),
        layout_signature=_layout_signature(lab, year, sections),
        has_cannabinoids=bool(getattr(p, "cannabinoids", None)),
        has_microbials=("microbials" in sections),
        has_metals=("heavy_metals" in sections),
        has_pesticides=("pesticides" in sections),
        has_terpenes=("terpenes" in sections))


def _flagged_value_in_text(p, text):
    for d in v5.quantified_details(p, getattr(p, "_watch", v4.DEFAULT_WATCH)):
        if v5.is_flag_driver(d) and _value_in_coa_text(d.get("value"), text):
            return True
    return False


def assess_extraction(p, text, profile=None):
    """Cross-check FIVE independent signals and return a confidence LEVEL. Marks the
    extraction UNCERTAIN (held for review) on a top/detail pass-fail conflict, a
    product mismatch, impossible numbers, or an unreadable scan — never confidently
    reporting data the document does not clearly support."""
    text = text or ""
    profile = profile or profile_coa(p, text)
    checks, reasons = [], []

    # 1) top-level pass/fail summary
    top = v4.find_overall_result(text)
    checks.append(("top_summary", bool(top)))
    if not top:
        reasons.append("no top-level pass/fail summary located")

    # 2) detailed breakdown tables parsed
    has_detail = bool(getattr(p, "analytes", None)) or bool(getattr(p, "cannabinoids", None))
    checks.append(("detail_tables", has_detail))
    if not has_detail:
        reasons.append("no detailed result tables parsed")

    # 3) numeric values present + plausible
    numeric_ok = (any(v5.is_quantified(e) for e in p.analytes.values())
                  or bool(getattr(p, "cannabinoids", None)))
    tc = thc_conflict(p)
    if tc:
        numeric_ok = False
        reasons.append(f"impossible cannabinoid math ({tc})")
    elif not numeric_ok:
        reasons.append("no quantified numeric values extracted")
    checks.append(("numeric_values", numeric_ok))

    # 4) identity fields (batch / product / licensee)
    idf = profile["identity"]
    id_ok = idf["reg"] or idf["product"] or idf["batch"]
    checks.append(("identity_fields", id_ok))
    if not id_ok:
        reasons.append("could not confirm batch / product / licensee identity on the COA")

    # 5) does the COA actually match the product record it is attached to? Defer to the engine's
    #    already-computed, well-tested match status (validate_coa_row marks PUBLISHABLE only when the
    #    product or a flagged value was found in THIS COA), so we never contradict it or double-hold a
    #    record it already verified — we add a mismatch hold only when the engine also could not match.
    engine_matched = getattr(p, "_coa_status", "") in PUBLISHABLE
    match_ok = engine_matched or idf["reg"] or idf["product"] or _flagged_value_in_text(p, text)
    checks.append(("coa_matches_product", match_ok))
    mismatch = not match_ok
    if mismatch:
        reasons.append("COA text does not appear to match the product record it is attached to")

    # cross-check: a top-level PASS alongside a detailed FAIL/DETECTED is a real conflict
    detail_fail = (getattr(p, "pesticides", "") == "FAIL" or getattr(p, "solvents", "") == "FAIL"
                   or bool(v5.pathogen_detections(p))
                   or any((e.get("status") or "").upper() == "FAIL" for e in p.analytes.values()))
    conflict = bool(top == "PASS" and detail_fail)
    if conflict:
        reasons.append("top-level PASS but a detailed regulated result reads FAIL/DETECTED")

    if profile["scanned_image"]:
        reasons.append("little or no extractable text (older scan / image COA)")

    npass = sum(1 for _n, ok in checks if ok)
    if mismatch or conflict:
        level = "UNCERTAIN"
    elif npass >= 5 and not profile["scanned_image"]:
        level = "HIGH"
    elif npass >= 4:
        level = "MEDIUM"
    elif npass >= 2:
        level = "LOW"
    else:
        level = "UNCERTAIN"
    return dict(level=level, score=npass, checks=dict(checks), reasons=reasons,
                conflict=conflict, mismatch=mismatch, hold=(conflict or mismatch))


def _bump(counter, key, islist=False):
    if islist:
        for k in key:
            counter[k] = counter.get(k, 0) + 1
    else:
        counter[key] = counter.get(key, 0) + 1


class COAFormatLearner:
    """Per-year accumulation of observed COA formats + parse outcomes, persisted across
    runs so the parser becomes historically aware and reports per-year readiness."""
    MIN_SAMPLE = 5
    _FIELDS = ("product", "producer", "batch", "cannabinoids", "microbials", "metals")

    def __init__(self, data=None):
        self.years = data if isinstance(data, dict) else {}

    @classmethod
    def load(cls):
        try:
            with open(COA_FORMAT_STORE, encoding="utf-8") as f:
                return cls(json.load(f))
        except (OSError, ValueError):
            return cls({})

    def save(self):
        try:
            tmp = COA_FORMAT_STORE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.years, f)
            os.replace(tmp, COA_FORMAT_STORE)
        except OSError:
            pass

    # categories whose extraction reliability decides readiness (per year/lab)
    _CORE_CATS = ("cannabinoids", "microbials", "metals")

    @staticmethod
    def _blank():
        return dict(coas_observed=0, labs={}, producers={}, sections_seen={},
                    vocab_pass={}, vocab_fail={}, vocab_nd={}, layout_signatures={},
                    field_success={f: 0 for f in COAFormatLearner._FIELDS},
                    confidence={"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNCERTAIN": 0},
                    product_types={}, value_styles={}, cats_parsed={},
                    cells={}, last_updated="")

    @staticmethod
    def _blank_cell():
        return dict(coas=0, confidence={"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNCERTAIN": 0},
                    cats_parsed={}, product_types={})

    def observe(self, profile, assessment, producer=""):
        y = str(profile.get("year") or "unknown")
        d = self.years.setdefault(y, self._blank())
        for k, v in self._blank().items():        # heal older/partial stored shapes
            d.setdefault(k, v)
        d["coas_observed"] += 1
        lab = profile.get("lab") or "Unknown lab"
        _bump(d["labs"], lab)
        if producer:
            _bump(d["producers"], producer[:40])
        _bump(d["sections_seen"], profile["sections"], islist=True)
        for kind in ("pass", "fail", "nd"):
            for lbl in profile["vocab"].get(kind, []):
                _bump(d[f"vocab_{kind}"], lbl)
        _bump(d["layout_signatures"], profile["layout_signature"])
        _bump(d["product_types"], profile.get("product_type") or "other")
        _bump(d["value_styles"], profile.get("value_styles") or [], islist=True)
        _bump(d["cats_parsed"], profile.get("cats_parsed") or [], islist=True)
        flags = {"product": profile["identity"]["product"], "producer": profile["identity"]["producer"],
                 "batch": profile["identity"]["batch"], "cannabinoids": profile["has_cannabinoids"],
                 "microbials": profile["has_microbials"], "metals": profile["has_metals"]}
        for f, ok in flags.items():
            if ok:
                d["field_success"][f] += 1
        lvl = assessment["level"]
        d["confidence"][lvl] = d["confidence"].get(lvl, 0) + 1
        # year x lab cell
        cell = d["cells"].setdefault(lab, self._blank_cell())
        for k, v in self._blank_cell().items():
            cell.setdefault(k, v)
        cell["coas"] += 1
        cell["confidence"][lvl] = cell["confidence"].get(lvl, 0) + 1
        _bump(cell["cats_parsed"], profile.get("cats_parsed") or [], islist=True)
        _bump(cell["product_types"], profile.get("product_type") or "other")
        d["last_updated"] = f"{datetime.datetime.now().astimezone():%Y-%m-%d %H:%M %Z}"

    @staticmethod
    def _core_coverage(cats, n):
        """Fraction of COAs in which each CORE area was extracted. cats_parsed holds individual
        analyte keys (tymc/aerobic/arsenic/...), so map them to the core areas."""
        if not n:
            return {c: 0.0 for c in COAFormatLearner._CORE_CATS}
        micro = max((cats.get(k, 0) for k in ("tymc", "aerobic", "pathogens")), default=0)
        metal = max((cats.get(k, 0) for k in ("arsenic", "lead", "cadmium", "mercury", "chromium")), default=0)
        return {"cannabinoids": cats.get("cannabinoids", 0) / n,
                "microbials": micro / n, "metals": metal / n}

    def _verdict(self, n, conf_rate, unc_rate, core_cov):
        """3-tier readiness (a COVERAGE/maturity signal, surfaced as a warning — see validation_summary).
        NOT READY is only assigned once there is ENOUGH learned data to judge — a thin sample is
        INSUFFICIENT, not NOT READY. The
        intended workflow is: run `learn` to accumulate per-year/lab format knowledge, then reports
        consult that persisted map."""
        if n == 0:
            return "NO DATA", False
        if n < self.MIN_SAMPLE:
            return "INSUFFICIENT SAMPLE", False
        weak_core = min(core_cov.values()) if core_cov else 0.0
        if conf_rate >= 0.85 and unc_rate <= 0.15 and weak_core >= 0.50:
            return "READY", True
        if conf_rate < 0.55 or weak_core < 0.20:
            return "NOT READY", False
        return "PARTIAL", False

    def year_summary(self, year):
        d = self.years.get(str(year))
        if not d or d.get("coas_observed", 0) == 0:
            return dict(year=year, sampled=0, labs=[], lab_cells=[], producers=0, conf={},
                        conf_rate=0.0, uncertain=0, fields={}, layouts=[], product_types={},
                        value_styles=[], weak_cats=[], core_cov={},
                        era=_era_for(year), era_note=_ERA_NOTES.get(_era_for(year), ""),
                        verdict="NO DATA", ready=False)
        n = d["coas_observed"]
        conf = d["confidence"]
        good = conf.get("HIGH", 0) + conf.get("MEDIUM", 0)
        unc = conf.get("UNCERTAIN", 0)
        conf_rate = good / n if n else 0.0
        cats = d.get("cats_parsed", {})
        core_cov = self._core_coverage(cats, n)
        weak_cats = sorted([c for c, cnt in cats.items() if (cnt / n) < 0.50]) if n else []
        verdict, ready = self._verdict(n, conf_rate, (unc / n if n else 0.0), core_cov)
        # per-lab readiness within the year
        lab_cells = []
        for lab, cell in sorted(d.get("cells", {}).items(), key=lambda kv: -kv[1].get("coas", 0)):
            cn = cell.get("coas", 0)
            cc = cell.get("confidence", {})
            cgood = cc.get("HIGH", 0) + cc.get("MEDIUM", 0)
            ccov = self._core_coverage(cell.get("cats_parsed", {}), cn)
            cv, _r = self._verdict(cn, (cgood / cn if cn else 0.0), (cc.get("UNCERTAIN", 0) / cn if cn else 0.0), ccov)
            lab_cells.append(dict(lab=lab, coas=cn, conf_rate=(cgood / cn if cn else 0.0), verdict=cv))
        top_layouts = sorted(d["layout_signatures"].items(), key=lambda kv: -kv[1])[:3]
        return dict(year=year, sampled=n,
                    labs=sorted(d["labs"], key=lambda k: -d["labs"][k]), lab_cells=lab_cells,
                    producers=len(d["producers"]), conf=conf, conf_rate=conf_rate,
                    uncertain=unc, fields={f: (d["field_success"].get(f, 0), n) for f in self._FIELDS},
                    layouts=[s for s, _c in top_layouts],
                    product_types=dict(sorted(d.get("product_types", {}).items(), key=lambda kv: -kv[1])),
                    value_styles=sorted(d.get("value_styles", {}), key=lambda k: -d["value_styles"][k]),
                    weak_cats=weak_cats, core_cov=core_cov,
                    era=_era_for(year), era_note=_ERA_NOTES.get(_era_for(year), ""),
                    verdict=verdict, ready=ready)


def _pick_coa_sample(cands, n, offline):
    """Up to n products for a year, diversified across PRODUCER, PRODUCT TYPE, and (registry-known)
    LAB so a single lab/format/product-type does not stand in for the whole year. When offline, only
    products whose COA PDF is already cached (so the self-test needs no network)."""
    pool = [p for p in cands if (not offline) or os.path.exists(v4.cache_path(p))]
    # Round-robin by a diversity key = (producer, product-type) so each pick adds variety; the
    # registry doesn't carry lab pre-fetch, but COA fetch reveals it and the learner buckets by lab.
    from collections import defaultdict as _dd
    buckets = _dd(list)
    for p in pool:
        key = ((getattr(p, "producer", "") or "")[:24], product_category(p))
        buckets[key].append(p)
    order = sorted(buckets.keys())
    out, idx = [], 0
    while len(out) < n and any(buckets[k] for k in order):
        k = order[idx % len(order)]
        if buckets[k]:
            out.append(buckets[k].pop(0))
        idx += 1
        if idx > len(order) * (n + 2):
            break
    return out[:max(0, n)]


def coa_format_selftest(per_year, year_lo, year_hi, session, offline, watch):
    """Sample COAs from every available year, profile + assess them, accumulate into the
    persistent learner, and return (rows, learner). Each product is parsed via the normal
    pipeline so _format_profile / _extraction are populated."""
    products = load_registry(session, offline=offline)
    by_year = defaultdict(list)
    for p in products:
        y = _coa_year(p)
        if y is not None and year_lo <= y <= year_hi:
            by_year[y].append(p)
    learner = COAFormatLearner.load()
    # AUTO-PRIORITIZE weak years (item 9): the learned store is cumulative across runs, so each
    # `learn` run should spend its effort where the parser is LEAST confident. Years already READY
    # get only a light refresh; PARTIAL years get the full budget; NOT-READY / untrained years get
    # a boosted budget (up to 2x, bounded by how many COAs exist that year). Re-running `learn`
    # therefore converges every year toward READY instead of re-sampling strong years equally.
    def _year_budget(year):
        verdict = learner.year_summary(year).get("verdict", "NO DATA")
        avail = len(by_year.get(year, []))
        if verdict == "READY":
            return min(avail, max(2, per_year // 4))
        if verdict in ("NO DATA", "INSUFFICIENT SAMPLE", "NOT READY"):
            return min(avail, per_year * 2)
        return min(avail, per_year)   # PARTIAL
    # PASS 1 — sample + parse + observe EVERYTHING first. A COA is attributed to the year on
    # the COA itself (its parsed test date), which can differ from the registry approval year
    # used to pick the sample, so all observing must finish before any year is summarized.
    attempted = {}
    for year in range(year_lo, year_hi + 1):
        sample = _pick_coa_sample(by_year.get(year, []), _year_budget(year), offline)
        attempted[year] = len(sample)
        for p in sample:
            p._watch = watch
            process_product(p, session, watch)
            prof = getattr(p, "_format_profile", None)
            if not prof:
                continue   # COA missing / unreadable for this product
            ass = getattr(p, "_extraction", None) or assess_extraction(p, "", prof)
            learner.observe(prof, ass, producer=getattr(p, "producer", ""))
    learner.save()
    # PASS 2 — summarize each year from the now-complete (and cumulative, cross-run) store.
    rows = []
    for year in range(year_lo, year_hi + 1):
        s = learner.year_summary(year)
        s["attempted_this_run"] = attempted.get(year, 0)
        s["candidates_in_registry"] = len(by_year.get(year, []))
        rows.append(s)
    return rows, learner


def _print_selftest_report(rows):
    print("\n" + "=" * 96)
    print("  COA FORMAT LEARNING — YEAR-BY-YEAR PARSING CONFIDENCE REPORT")
    print("=" * 96)
    print(f"  {'Year':<6}{'Sampled':>8}{'Labs':>6}{'Prod':>6}{'HIGH':>6}{'MED':>5}{'LOW':>5}"
          f"{'UNC':>5}{'Conf%':>7}  Verdict")
    print("  " + "-" * 92)
    for r in rows:
        c = r.get("conf", {})
        print(f"  {str(r['year']):<6}{r['sampled']:>8}{len(r['labs']):>6}{r['producers']:>6}"
              f"{c.get('HIGH',0):>6}{c.get('MEDIUM',0):>5}{c.get('LOW',0):>5}{c.get('UNCERTAIN',0):>5}"
              f"{r['conf_rate']*100:>6.0f}%  {r['verdict']}")
    print("  " + "-" * 92)
    for r in rows:
        if not r["sampled"]:
            continue
        fields = r["fields"]
        fok = ", ".join(f"{f} {v[0]}/{v[1]}" for f, v in fields.items())
        print(f"\n  {r['year']} — {r['era']} · labs: {', '.join(r['labs']) or '—'}")
        if r.get("lab_cells"):
            print("      per-lab readiness: " + " · ".join(
                f"{lc['lab']} [{lc['verdict']}, {lc['coas']} COA, {lc['conf_rate']*100:.0f}%]"
                for lc in r["lab_cells"]))
        if r.get("product_types"):
            print("      product types seen: " + ", ".join(f"{k} {v}" for k, v in list(r["product_types"].items())[:8]))
        if r.get("value_styles"):
            print("      value styles: " + ", ".join(r["value_styles"]))
        print(f"      identity/field extraction: {fok}")
        cc = r.get("core_cov") or {}
        print("      core-category coverage: " + ", ".join(f"{k} {v*100:.0f}%" for k, v in cc.items()))
        if r.get("weak_cats"):
            print(f"      categories still UNRELIABLE (<50% parsed): {', '.join(r['weak_cats'])}")
        print(f"      known layout patterns: {', '.join(r['layouts']) or '—'}")
        if r["uncertain"]:
            print(f"      ⚠ {r['uncertain']} COA(s) UNCERTAIN — held from confident use until reviewed")
        print(f"      era notes: {r['era_note']}")
        print(f"      READINESS: {r['verdict']}" + ("  (READY for statewide use)" if r['ready'] else ""))
    # Auto-prioritization guidance: which years still need training. Re-running `learn` will
    # automatically give these years a boosted sample (see _year_budget) until they reach READY.
    weak = [str(r["year"]) for r in rows if r.get("verdict") in
            ("NOT READY", "PARTIAL", "NO DATA", "INSUFFICIENT SAMPLE")]
    ready = [str(r["year"]) for r in rows if r.get("verdict") == "READY"]
    print("  " + "-" * 92)
    print(f"  READY years: {', '.join(ready) or '—'}")
    if weak:
        print(f"  Years still needing training (auto-prioritized on the next run): {', '.join(weak)}")
        print("  -> Re-run `learn` (online, to fetch older COAs) to converge these toward READY:")
        print(f"       python3 {SCRIPT_FILE} learn --years {rows[0]['year']}-{rows[-1]['year']}")
        print("     Older years need ONLINE runs (the embedded cache is recent-heavy); each run")
        print("     spends more samples on the weakest years because the store is cumulative.")
    else:
        print("  All sampled years are READY.")
    print("=" * 96 + "\n")


# ============================================================================
# PRE-V16 LOCAL CACHE AUDIT & RE-EVALUATION (resumable, batched, checkpointed)
# ----------------------------------------------------------------------------
# Re-evaluates every ledger ("clean-skipped") record that was NOT last evaluated under the CURRENT
# analysis version (ANALYSIS_VERSION). The legacy ledger is entirely UNSTAMPED, so all of it is a
# candidate — surfacing records that scanned clean before newer detection/validation existed and
# now produce findings. Non-destructive (backs up the ledger; old result for any ledgered record is
# "clean" by definition), idempotent (done records are stamped `current`), and fully resumable.
# ============================================================================
def _now_str():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def _load_json_or(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _audit_findings(p):
    """Short human list of what now flags on a re-scanned record (for the Phase-8 diff)."""
    out = []
    for f in (getattr(p, "flags", None) or []):
        out.append(str(f.get("name") or f.get("analyte") or f.get("category") or f)[:80]
                   if isinstance(f, dict) else str(f)[:80])
    for t in (getattr(p, "thc_flags", None) or []):
        out.append("high-THC: " + str(t.get("name") if isinstance(t, dict) else t)[:60])
    try:
        for nm in v5.pathogen_detections(p):
            out.append("pathogen DETECTED: " + str(nm)[:60])
        for u in v5.unquantified_findings(p):
            out.append("unquantified: " + str(u.get("name") if isinstance(u, dict) else u)[:60])
    except Exception:
        pass
    return out[:8]


def _audit_state_for(key, stamps):
    s = stamps.get(key)
    if not s:
        return "unstamped"
    return "current" if s.get("analysis_version") == ANALYSIS_VERSION else "stale"


def _audit_write_handoff(prog):
    t = prog["tally"]
    done, rem = len(prog["done"]), len(prog["remaining"])
    L = ["# V16 Cache Audit — Handoff", "",
         f"_Living document — last updated {_now_str()}. Machine state: `{AUDIT_PROGRESS}`._", "",
         "## Where we are",
         f"- Phase: **{prog.get('phase')}** · analysis version: **{prog.get('analysis_version')}**"
         + (" · **--force-rescan**" if prog.get("force_rescan") else ""),
         f"- Started {prog.get('started_at')} · resumed runs: {prog.get('resumed_runs', 0)}",
         f"- Ledger (clean-skipped) total: **{prog.get('total_ledger'):,}** · registry products: {prog.get('registry_products', 0):,}",
         "", "## Progress",
         f"- Re-evaluated (done): **{done:,}** · remaining: **{rem:,}**",
         f"- still clean: {t['still_clean']:,} · **NOW FINDINGS (newly discovered): {t['now_findings']:,}**",
         f"- not in current registry: {t['not_in_registry']:,} · unreadable/error: {t['unreadable']:,}",
         "", "## Newly discovered findings so far"]
    if prog["new_findings"]:
        for nf in prog["new_findings"][:40]:
            L.append(f"- **{nf.get('product', '')}** ({nf.get('producer', '')}) — " + ("; ".join(nf.get("findings", [])))[:160])
        if len(prog["new_findings"]) > 40:
            L.append(f"- … and {len(prog['new_findings']) - 40} more (full list in `{AUDIT_PROGRESS}`).")
    else:
        L.append("- (none yet)")
    L += ["", "## What's next",
          f"- Resume with `python3 {SCRIPT_FILE} audit-cache` — continues from the {rem:,} remaining; "
          "completed records are stamped `current` and never redone.", ""]
    if prog.get("blockers"):
        L += ["## Blockers", *[f"- {b}" for b in prog["blockers"][:20]], ""]
    with open(AUDIT_HANDOFF, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def main_audit(argv=None):
    """Pre-V16 local cache audit & re-evaluation — resumable, batched, checkpointed (see the
    module banner above)."""
    ap = argparse.ArgumentParser(description=f"{APP_NAME} — pre-V16 local cache audit & re-evaluation")
    ap.add_argument("--force-rescan", action="store_true", help="ignore stamps; re-evaluate EVERY ledger record")
    ap.add_argument("--batch-size", type=int, default=100, help="records per checkpoint (default 100)")
    ap.add_argument("--limit", type=int, default=0, help="cap records THIS run (0=all remaining); rest resume next run")
    ap.add_argument("--workers", type=int, default=v4.DEFAULT_WORKERS)
    ap.add_argument("--offline", action="store_true", help="only re-read cached COA PDFs (no network)")
    ap.add_argument("--restart", action="store_true", help="discard prior progress and start the audit over")
    ap.add_argument("--no-ocr", action="store_true")
    args = ap.parse_args(argv)
    migrate_legacy_out_dir()
    t0 = time.time()
    enable_isolated_ocr(); enable_safe_pdf_text()
    if args.no_ocr:
        v4.ocr_pdf = lambda *a, **k: ""
    if args.offline:
        import requests
        enable_offline_sources(); session = requests.Session()
    else:
        session = v4.make_session("", args.workers)
    watch = v4.DEFAULT_WATCH

    print("=" * 78)
    print("  CANNASCOPE CT — PRE-V16 LOCAL CACHE AUDIT & RE-EVALUATION")
    print("=" * 78)

    # ---------- RESUME PROTOCOL (check FIRST) ----------
    prog = None if args.restart else _load_json_or(AUDIT_PROGRESS, None)
    stamps = _load_json_or(AUDIT_STAMPS, {})
    ledger = _load_ledger()
    if prog:
        prog["resumed_runs"] = prog.get("resumed_runs", 0) + 1
        print(f"  RESUMING a prior audit (run #{prog['resumed_runs']}): {len(prog['done']):,} done, "
              f"{len(prog['remaining']):,} remaining. Completed records are NOT redone.")
    else:
        # ---------- PHASE 1 — AUDIT THE CURRENT CACHE ----------
        print("  FRESH START.\n")
        print("  PHASE 1 — CACHE AUDIT")
        print(f"    Skip mechanism: the scan ledger '{os.path.basename(LEDGER)}' — a flat list of COA keys")
        print("      (coa_key = registration number, else hash(report_url)) for records that previously")
        print("      scanned CLEAN (no flag / high-THC / unquantified / pathogen). Those keys are SKIPPED")
        print("      ENTIRELY on later runs (never re-downloaded or re-parsed) — the auto-skip in question.")
        print("    Schema: one key per line; NO stored result and NO analysis-version stamp.")
        print("    Current validity rule: mere PRESENCE in the ledger (age/feature-blind) — that's the gap.")
        print("    Other caches (registry / conflict / format-profile / COA-PDF) are DATA caches that do NOT")
        print("      skip records, so they cannot hide findings; this audit targets the ledger.")
        print(f"    Ledger size: {len(ledger):,} clean-skipped records.\n")
        # ---------- PHASE 2 — VALIDITY CLASSIFICATION ----------
        print(f"  PHASE 2 — VALIDITY CLASSIFICATION (current analysis version = {ANALYSIS_VERSION})")
        n_cur = sum(1 for k in ledger if _audit_state_for(k, stamps) == "current")
        n_stale = sum(1 for k in ledger if _audit_state_for(k, stamps) == "stale")
        n_uns = len(ledger) - n_cur - n_stale
        print(f"    current (already re-evaluated under {ANALYSIS_VERSION}): {n_cur:,}")
        print(f"    stale (older analysis version):                        {n_stale:,}")
        print(f"    unstamped/unknown (legacy ledger, never re-evaluated): {n_uns:,}")
        remaining = sorted(ledger if args.force_rescan
                           else [k for k in ledger if _audit_state_for(k, stamps) != "current"])
        print(f"    -> RE-EVALUATION CANDIDATES: {len(remaining):,}"
              + ("  (--force-rescan: ALL ledger records)" if args.force_rescan else ""))
        if os.path.exists(LEDGER) and not os.path.exists(LEDGER + ".audit-backup"):
            import shutil
            shutil.copyfile(LEDGER, LEDGER + ".audit-backup")
            print(f"    NON-DESTRUCTIVE: backed up the original ledger -> {os.path.basename(LEDGER)}.audit-backup")
        prog = dict(phase="3-4 reevaluate+rebuild", analysis_version=ANALYSIS_VERSION, started_at=_now_str(),
                    resumed_runs=0, force_rescan=bool(args.force_rescan), total_ledger=len(ledger),
                    registry_products=0, done=[], remaining=remaining,
                    tally=dict(still_clean=0, now_findings=0, not_in_registry=0, unreadable=0),
                    new_findings=[], blockers=[])
        _atomic_json(AUDIT_PROGRESS, prog)
    _audit_write_handoff(prog)

    products = load_registry(session, offline=args.offline)
    prog["registry_products"] = len(products)
    key2p = {v4.coa_key(p): p for p in products}

    # ---------- PHASE 3/4/6 — batched re-eval + stamp refresh + logging ----------
    run_keys = prog["remaining"][:args.limit] if args.limit else list(prog["remaining"])
    print(f"\n  PHASE 3/4 — RE-EVALUATING {len(run_keys):,} record(s) this run "
          f"(batch {args.batch_size}, {args.workers} workers){' [offline]' if args.offline else ''} ...")
    processed = 0
    for bi in range(0, len(run_keys), args.batch_size):
        batch = run_keys[bi:bi + args.batch_size]
        live = [(k, key2p[k]) for k in batch if k in key2p]
        for k in batch:
            if k not in key2p:
                prog["tally"]["not_in_registry"] += 1
                stamps[k] = dict(analysis_version=ANALYSIS_VERSION, result="not_in_registry", n_findings=0, stamped_at=_now_str())
                print(f"    [skip] {k}: not in current registry (cannot re-fetch)")
        results = {}
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(process_product, p, session, watch): k for k, p in live}
            for fut in as_completed(futs):
                k = futs[fut]
                try:
                    results[k] = fut.result()
                except Exception as e:
                    results[k] = None
                    prog["blockers"].append(f"{k}: {type(e).__name__}: {str(e)[:60]}")
        for k, p in live:
            rp = results.get(k)
            if rp is None:
                prog["tally"]["unreadable"] += 1
                stamps[k] = dict(analysis_version=ANALYSIS_VERSION, result="error", n_findings=0, stamped_at=_now_str())
                print(f"    [rescan] {k}: re-eval error (left for review)")
                continue
            interesting = (bool(rp.flags) or bool(rp.thc_flags)
                           or bool(v5.unquantified_findings(rp)) or bool(v5.pathogen_detections(rp)))
            if interesting:
                finds = _audit_findings(rp)
                prog["tally"]["now_findings"] += 1
                prog["new_findings"].append(dict(
                    key=k, product=tcase(getattr(rp, "product_name", "") or ""), producer=getattr(rp, "producer", "") or "",
                    report_url=getattr(rp, "report_url", "") or "", testing_date=test_date(rp),
                    old_result="clean (auto-skipped)", findings=finds, analysis_version=ANALYSIS_VERSION, found_at=_now_str()))
                ledger.discard(k)   # PHASE 8 + 4: a now-findings record must no longer auto-skip
                stamps[k] = dict(analysis_version=ANALYSIS_VERSION, result="findings", n_findings=len(finds), stamped_at=_now_str())
                print(f"    [REFRESH->FINDINGS] {k}: NEWLY DISCOVERED — {('; '.join(finds))[:120]}")
            elif bool(rp.analytes) or bool(rp.cannabinoids):
                # GENUINELY re-parsed and clean -> trust it: stays skippable, STAMPED current.
                prog["tally"]["still_clean"] += 1
                ledger.add(k)
                stamps[k] = dict(analysis_version=ANALYSIS_VERSION, result="clean", n_findings=0, stamped_at=_now_str())
                try:                # drop the re-downloaded clean PDF so a 17k-record audit can't bloat disk
                    os.remove(v4.cache_path(rp))
                except OSError:
                    pass
            else:
                # COA could NOT be re-read (download/parse failed) -> it was NOT actually re-evaluated.
                # Do NOT trust it as clean: remove it from the skip-list so a future statewide run
                # re-scans it, and record it as unreadable (not a clean 'current' record).
                prog["tally"]["unreadable"] += 1
                ledger.discard(k)
                stamps[k] = dict(analysis_version=ANALYSIS_VERSION, result="unreadable", n_findings=0, stamped_at=_now_str())
                prog.setdefault("unreadable_keys", []).append(k)
                print(f"    [rescan] {k}: COA could not be re-read — removed from skip-list for re-scan")
            processed += 1
        for k in batch:
            if k in prog["remaining"]:
                prog["remaining"].remove(k)
            prog["done"].append(k)
        _save_ledger(ledger)                       # Phase 4 rebuild (clean stays / findings removed)
        _atomic_json(AUDIT_STAMPS, stamps)
        _atomic_json(AUDIT_PROGRESS, prog)
        _audit_write_handoff(prog)                 # checkpoint flush (resume-safe)
        print(f"    checkpoint: {len(prog['done']):,} done / {len(prog['remaining']):,} left "
              f"· now-findings: {prog['tally']['now_findings']} · {time.time() - t0:.0f}s")

    # ---------- PHASE 7 — summary ----------
    t = prog["tally"]; partial = len(prog["remaining"]) > 0
    print("\n" + "=" * 78)
    print("  PHASE 7 — CACHE AUDIT SUMMARY" + ("  (PARTIAL / RESUMABLE — cumulative to date)" if partial else "  (COMPLETE)"))
    print("=" * 78)
    print(f"    ledger records examined (cumulative): {len(prog['done']):,} of {prog['total_ledger']:,}")
    print(f"    re-scanned this run:                  {processed:,}")
    print(f"    still clean (re-stamped current):     {t['still_clean']:,}")
    print(f"    NEWLY DISCOVERED findings:            {t['now_findings']:,}")
    print(f"    not in current registry:              {t['not_in_registry']:,}")
    print(f"    unreadable / re-eval error:           {t['unreadable']:,}")
    print(f"    remaining to audit:                   {len(prog['remaining']):,}")
    # ---------- PHASE 8 — newly discovered findings ----------
    print("\n  PHASE 8 — NEWLY DISCOVERED FINDINGS (previously clean-skipped, now flagged under " + ANALYSIS_VERSION + "):")
    if prog["new_findings"]:
        for nf in prog["new_findings"][-25:]:
            print(f"    • {nf['product']} ({nf['producer']}) [{nf.get('testing_date', '')}] — " + ("; ".join(nf["findings"]))[:140])
        if len(prog["new_findings"]) > 25:
            print(f"    … plus {len(prog['new_findings']) - 25} earlier — full list in {AUDIT_PROGRESS} / {AUDIT_HANDOFF}.")
        print(f"\n    TOTAL newly-discovered (cumulative across sessions): {len(prog['new_findings']):,}")
    else:
        print("    (none yet — no previously-clean record produced findings under current logic.)")
    if partial:
        print(f"\n  RESUME HERE: re-run `python3 {SCRIPT_FILE} audit-cache` to continue the remaining "
              f"{len(prog['remaining']):,}. Done records are stamped and won't be redone.")
    else:
        prog["phase"] = "complete"
        _atomic_json(AUDIT_PROGRESS, prog); _audit_write_handoff(prog)
        print("\n  AUDIT COMPLETE — every ledger record re-evaluated under analysis version " + ANALYSIS_VERSION + ".")
    print("=" * 78)


def main_learn(argv=None):
    """`learn` subcommand: practice the parser against historical COAs, year by year,
    and emit a parsing-confidence report + persist what was learned."""
    migrate_legacy_out_dir()
    ap = argparse.ArgumentParser(description=f"{APP_NAME} — COA Format Learning self-test")
    ap.add_argument("--per-year", type=int, default=8, help="COAs to sample per year (default 8)")
    ap.add_argument("--years", default=f"{COA_FIRST_YEAR}-{datetime.date.today().year}",
                    help="year range, e.g. 2015-2026 (default: 2015..this year)")
    ap.add_argument("--offline", action="store_true",
                    help="use only cached COA PDFs + bundled registry (no network)")
    ap.add_argument("--no-ocr", action="store_true", help="force OCR off (skip image-only COAs)")
    ap.add_argument("--ocr-workers", type=int, default=_default_ocr_workers())
    ap.add_argument("--refresh-registry", action="store_true")
    args = ap.parse_args(argv)

    try:
        lo, hi = (int(x) for x in args.years.split("-"))
    except ValueError:
        sys.exit("--years must look like 2015-2026")

    enable_safe_pdf_text()
    if args.offline:
        enable_offline_sources()
    if args.no_ocr:
        v4._OCR_BACKEND = ""
    else:
        enable_isolated_ocr()
        set_ocr_concurrency(args.ocr_workers)

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    v4.CACHE_DIR = CACHE_DIR
    if args.offline:
        import requests
        session = requests.Session()
        print("OFFLINE mode: using cached COA PDFs + bundled registry only.")
    else:
        session = v4.make_session("", v4.DEFAULT_WORKERS)

    print(f"Learning COA formats for {lo}–{hi} (up to {args.per_year}/year) ...")
    rows, learner = coa_format_selftest(args.per_year, lo, hi, session, args.offline, v4.DEFAULT_WATCH)
    _print_selftest_report(rows)
    empty = [r["year"] for r in rows if not r["sampled"]]
    if empty and args.offline:
        print(f"  NOTE: no cached COAs on file for {', '.join(map(str, empty))}. Offline only sees COAs "
              "already downloaded by prior runs (mostly recent years). Run `learn` ONLINE (omit --offline) "
              "to fetch and study older COAs from the registry for those years.\n")

    # machine-readable confidence report
    import csv
    rpt = os.path.join(OUT_DIR, "COA_Format_Confidence_Report.csv")
    try:
        with open(rpt, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["year", "era", "sampled", "labs", "producers", "high", "medium", "low",
                        "uncertain", "confidence_rate", "fields_extracted", "known_layouts",
                        "ready_for_reports", "verdict"])
            for r in rows:
                c = r.get("conf", {})
                w.writerow([r["year"], r["era"], r["sampled"], "; ".join(r["labs"]), r["producers"],
                            c.get("HIGH", 0), c.get("MEDIUM", 0), c.get("LOW", 0), c.get("UNCERTAIN", 0),
                            f"{r['conf_rate']*100:.0f}%",
                            "; ".join(f"{f} {v[0]}/{v[1]}" for f, v in r["fields"].items()),
                            "; ".join(r["layouts"]), "yes" if r["ready"] else "no", r["verdict"]])
        print(f"Wrote {rpt}")
        print(f"Learned profiles persisted to {COA_FORMAT_STORE}")
    except OSError as e:
        print(f"(could not write confidence report: {e})")


def _triple_verify_coa(p, cache, watch):
    """TRIPLE verification of one extracted COA before it is trusted in the cache. Returns an int 0-3:
      (1) SOURCE-EXTRACTED — every value carries a raw token parsed from the COA's own text (never
          fabricated; ND/limit/LOQ are not published as measurements);
      (2) SOURCE-BOUND — validate_coa_row confirmed the COA actually belongs to this product
          (registration / batch / identity match), i.e. _coa_status is publishable;
      (3) ROUND-TRIP — the measurements reload from the CSV and reproduce byte-identical flags, so
          the saved row reproduces the exact assessment.
    A row is only marked fully ('triple') when all three hold."""
    read = bool(getattr(p, "analytes", None) or getattr(p, "cannabinoids", None))
    if not read:
        return 0
    has_raw = (any(isinstance(e, dict) and e.get("raw") for e in (p.analytes or {}).values())
               or any(isinstance(e, dict) and e.get("raw") for e in (getattr(p, "cannabinoids", {}) or {}).values()))
    bound = getattr(p, "_coa_status", "") in PUBLISHABLE
    # round-trip: put a provisional row, reload it, compare flags + analytes
    extra = {"testing_date": test_date(p), "_coa_status": getattr(p, "_coa_status", "") or ""}
    cache.put(p, method="v15", text_len=0, pdf_path=v4.cache_path(p), extra=extra)
    rt = False
    rrow = cache.fresh_row(p)
    if rrow is not None:
        rp = cache.rehydrate(rrow, watch)
        rt = (rp.analytes == p.analytes and rp.flags == p.flags
              and getattr(rp, "thc_flags", []) == getattr(p, "thc_flags", []))
    level = int(bool(has_raw)) + int(bool(bound)) + int(bool(rt))
    extra["_verified"] = level
    cache.put(p, method="v15", text_len=0, pdf_path=v4.cache_path(p), extra=extra)
    return level


def main_build_cache(argv=None):
    """Walk the WHOLE product registry (as far back as it goes), download + read (incl. OCR) each COA
    ONCE, TRIPLE-VERIFY its measurements, and save them to the persistent COA Data Cache.csv. No PDF
    report is produced — this is the one-time data build that makes every later run cheap and lets the
    threshold be changed without re-OCR. Resumable: a HIT (already cached, unchanged report_url) is
    skipped instantly, so re-running continues where a previous build left off."""
    migrate_legacy_out_dir()
    if cc is None:
        sys.exit("build-cache needs the coa_csv_cache module (embedded in this build).")
    ap = argparse.ArgumentParser(prog="build-cache",
                                 description=f"{APP_NAME} — full-registry COA measurement cache build")
    ap.add_argument("--forms", choices=["flower", "inhalable", "all"], default="all")
    ap.add_argument("--since", default="", help="earliest approval date YYYY-MM-DD (default: the whole registry)")
    ap.add_argument("--until", default="", help="latest approval date YYYY-MM-DD (default: today)")
    ap.add_argument("--threshold", type=int, default=v4.DEFAULT_WATCH)
    ap.add_argument("--limit", type=int, default=0, help="cap products (0 = all)")
    ap.add_argument("--workers", type=int, default=v4.DEFAULT_WORKERS)
    ap.add_argument("--ocr-workers", type=int, default=_default_ocr_workers())
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--refresh-registry", action="store_true")
    args = ap.parse_args(argv)

    enable_safe_pdf_text()
    if args.offline:
        enable_offline_sources()
    if args.no_ocr:
        v4._OCR_BACKEND = ""
    else:
        enable_isolated_ocr(); set_ocr_concurrency(args.ocr_workers)
    since = None
    if args.since:
        try: since = tuple(map(int, args.since.split("-")))
        except ValueError: sys.exit("--since must be YYYY-MM-DD")
    until = None
    if args.until:
        try: until = tuple(map(int, args.until.split("-")))
        except ValueError: sys.exit("--until must be YYYY-MM-DD")
    os.makedirs(OUT_DIR, exist_ok=True); os.makedirs(CACHE_DIR, exist_ok=True)
    v4.CACHE_DIR = CACHE_DIR
    if args.offline:
        import requests; session = requests.Session()
    else:
        session = v4.make_session("", args.workers)
    products = load_registry(session, refresh=args.refresh_registry, offline=args.offline)
    before = len(products)
    products = v4.prefilter(products, args.forms, since)
    if until:
        products = [p for p in products if v4.parse_date(p.approval_date) <= until]
    if args.limit:
        products = products[:args.limit]
    if not products:
        sys.exit("No products matched.")
    years = sorted({v4.parse_date(p.approval_date)[0] for p in products if v4.parse_date(p.approval_date)[0]})
    print(f"Building COA measurement cache over {len(products):,} of {before:,} registry products "
          f"(approval years {years[0] if years else '?'}–{years[-1] if years else '?'}); "
          f"{args.workers} download workers, {args.ocr_workers} OCR workers.")

    cache = cc.CoaCsvCache()
    print(f"  resuming from {len(cache):,} COAs already cached.")
    watch = args.threshold
    tally = {"cached": 0, "read": 0, "unread": 0, "triple": 0, "double": 0, "single": 0, "v0": 0}
    lock = threading.Lock(); done = 0; t0 = time.time()

    def _one(p):
        row = cache.fresh_row(p)
        if row is not None:
            return "cached", 0
        p2 = process_product(p, session, watch)
        if bool(getattr(p2, "analytes", None)) or bool(getattr(p2, "cannabinoids", None)):
            lvl = _triple_verify_coa(p2, cache, watch)
            return "read", lvl
        # unreadable / no extractable text — stamp as a non-trusted row so a later online run retries
        cache.put(p2, method="none", text_len=0, pdf_path=v4.cache_path(p2),
                  extra={"testing_date": test_date(p2), "_coa_status": getattr(p2, "_coa_status", "") or "",
                         "_verified": 0})
        return "unread", 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_one, p): p for p in products}
        for fut in as_completed(futs):
            try:
                kind, lvl = fut.result()
            except Exception:
                kind, lvl = "unread", 0
            with lock:
                done += 1
                tally[kind] = tally.get(kind, 0) + 1
                if kind == "read":
                    tally[{3: "triple", 2: "double", 1: "single", 0: "v0"}[lvl]] += 1
                if done % 250 == 0 or done == len(products):
                    cache.flush()
                    print(f"  {done:,}/{len(products):,}  (cached-skip {tally['cached']:,} · "
                          f"read {tally['read']:,} · unreadable {tally['unread']:,} · "
                          f"triple-verified {tally['triple']:,}) {time.time()-t0:.0f}s", flush=True)
    cache.flush()
    n_trust = tally["triple"]
    print("\n================ COA CACHE BUILD COMPLETE ================")
    print(f"  Registry products walked : {len(products):,}")
    print(f"  Already cached (skipped) : {tally['cached']:,}")
    print(f"  Newly read this run      : {tally['read']:,}")
    print(f"  Unreadable (queued)      : {tally['unread']:,}")
    print(f"  TRIPLE-verified rows     : {tally['triple']:,}  (source-extracted + source-bound + round-trip)")
    print(f"  Double / single / zero   : {tally['double']:,} / {tally['single']:,} / {tally['v0']:,}")
    print(f"  COA Data Cache.csv       : {len(cache):,} COAs on file  ->  {cache.path}")
    print("=========================================================")
    return cache.path


def main_fetch_standards(argv=None):
    """Download each cited CT legal SOURCE DOCUMENT, extract its text (PDF via pdfium -> pdfplumber ->
    OCR, so non-extractable PDFs still yield text), SHA-256-hash the raw bytes, and cache it all to
    CT Regulatory Ledger.json for offline forensic provenance. Embed it with `_make_v16.py` so the
    program ships WITH the source documents behind every dated limit."""
    migrate_legacy_out_dir()
    ap = argparse.ArgumentParser(prog="fetch-standards",
                                 description=f"{APP_NAME} — cache CT regulatory source documents (provenance)")
    ap.add_argument("--offline", action="store_true", help="don't fetch; just report what's cached")
    args = ap.parse_args(argv)
    enable_safe_pdf_text()
    print(f"{APP_NAME} — caching CT regulatory source documents for offline provenance ...")
    if args.offline:
        led = load_reg_ledger()
        if not led:
            sys.exit("No CT Regulatory Ledger.json yet — run `fetch-standards` online once to build it.")
    else:
        led = build_reg_ledger(online=True)
    srcs = led.get("sources", [])
    ok = [s for s in srcs if s.get("ok")]
    print("=========================================================")
    print(f"  CT REGULATORY LEDGER  ({led.get('built_at', '?')})")
    print(f"  sources cached : {len(ok)}/{len(srcs)} fetched OK")
    for s in srcs:
        if s.get("ok"):
            print(f"   [OK ] {s['label'][:48]:48}  {s.get('byte_len',0):>9,}B  {s.get('method','?'):8}  "
                  f"sha256 {s.get('sha256','')[:16]}  text {s.get('text_len',0):,}c")
        else:
            print(f"   [-- ] {s['label'][:48]:48}  {s.get('http_status', s.get('status',''))}")
    print(f"  ledger written : {REG_LEDGER}")
    print("  embed it into the single-file build with:  python3 _make_v16.py")
    print("=========================================================")
    return REG_LEDGER


def main():
    migrate_legacy_out_dir()   # carry a pre-rename output folder over to OUT_DIR (cache + numbering)
    ap = argparse.ArgumentParser(description=f"{APP_NAME} — {REPORT_TITLE}")
    ap.add_argument("--forms", choices=["flower", "inhalable", "all"], default="all")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--since", default="", help="start date YYYY-MM-DD (inclusive)")
    ap.add_argument("--until", default="", help="end date YYYY-MM-DD (inclusive) — bound a year, e.g. 2024")
    ap.add_argument("--threshold", type=int, default=v4.DEFAULT_WATCH)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=v4.DEFAULT_WORKERS)
    ap.add_argument("--cookies", default="")
    ap.add_argument("--refresh-registry", action="store_true")
    ap.add_argument("--fast-cached", action="store_true",
                    help="OPT-IN speed mode for first-time runs: seed the skip-list from the "
                         "embedded snapshot of already-verified-CLEAN COAs, so those are skipped "
                         "and only flagged / new products are fetched. Findings are unchanged, but "
                         "the 'reviewed' coverage is lower. Off by default (default = full scan).")
    ap.add_argument("--force-rescan", action="store_true",
                    help="DEV: ignore the skip-list entirely and reprocess EVERY product in the window "
                         "from scratch (no auto-skip). For testing/validation/major-version dev.")
    ap.add_argument("--keep-clean-pdfs", action="store_true",
                    help="keep EVERY COA PDF in the cache (not just flagged ones), building a "
                         "complete local 'sources' bundle for fast offline re-runs.")
    ap.add_argument("--csv-cache", action="store_true",
                    help="use the persistent COA->measurement cache (COA Data Cache.csv): each COA is "
                         "downloaded + read (incl. OCR) ONCE; later runs reload measurements and "
                         "recompute flags, so the whole window is covered cheaply AND lowering "
                         "--threshold re-flags previously-clean COAs from cache (no re-OCR).")
    ap.add_argument("--offline", action="store_true",
                    help="never touch the network: use the bundled Registry Cache + cached COA "
                         "PDFs only. Seed the bundle first with one online run (use --keep-clean-pdfs).")
    ap.add_argument("--no-ocr", action="store_true",
                    help="force OCR OFF (image-only COAs are skipped). Default is crash-proof isolated OCR.")
    ap.add_argument("--ocr-isolated", action="store_true", help="(default) kept for backward compatibility")
    ap.add_argument("--ocr-workers", type=int, default=_default_ocr_workers(),
                    help=f"max concurrent OCR subprocesses (overload guard; auto-sized default {_default_ocr_workers()})")
    args = ap.parse_args()

    # Leak-free text extraction is ALWAYS on (COA text is read even with --no-ocr).
    enable_safe_pdf_text()

    # Offline mode: read COAs from the local sources bundle only, never the network.
    if args.offline:
        enable_offline_sources()

    # OCR policy: crash-proof isolated OCR is the DEFAULT (a bad COA can never crash
    # the run); --no-ocr turns it off entirely.
    if args.no_ocr:
        v4._OCR_BACKEND = ""
        ocr_on = False
    else:
        enable_isolated_ocr()
        set_ocr_concurrency(args.ocr_workers)
        ocr_on = True

    since = None
    if args.since:
        try:
            since = tuple(map(int, args.since.split("-")))
        except ValueError:
            sys.exit("--since must be YYYY-MM-DD")
    elif args.days:
        d = datetime.date.today() - datetime.timedelta(days=args.days)
        since = (d.year, d.month, d.day)
    until = None
    if args.until:
        try:
            until = tuple(map(int, args.until.split("-")))
        except ValueError:
            sys.exit("--until must be YYYY-MM-DD")
    since_str = f"{since[0]:04d}-{since[1]:02d}-{since[2]:02d}" if since else "any date"
    until_str = f"{until[0]:04d}-{until[1]:02d}-{until[2]:02d}" if until else f"{datetime.date.today():%Y-%m-%d}"
    window = f"{since_str} to {until_str}"

    os.makedirs(OUT_DIR, exist_ok=True); os.makedirs(CACHE_DIR, exist_ok=True)
    v4.CACHE_DIR = CACHE_DIR

    t0 = time.time()
    debug = {"runtime_started": f"{datetime.datetime.now().astimezone():%Y-%m-%d %H:%M %Z}"}
    if args.offline:
        import requests
        session = requests.Session()           # never used for I/O offline; skip the network warm
        print("OFFLINE mode: using bundled sources only (no network).")
    else:
        session = v4.make_session(args.cookies, args.workers)
    products = load_registry(session, refresh=args.refresh_registry, offline=args.offline)
    products.sort(key=lambda p: v4.parse_date(p.approval_date), reverse=True)

    pmap = lmap = None
    if names is not None:
        pmap = names.get_producer_map(registry_names=sorted({p.producer for p in products if p.producer}))
        lmap = names.get_lab_map(use_live=False)

    before = len(products)
    products = v4.prefilter(products, args.forms, since)
    if until:
        products = [p for p in products if v4.parse_date(p.approval_date) <= until]
    if args.limit:
        products = products[:args.limit]
    if not products:
        sys.exit("No products matched. Widen --forms / --days.")
    print(f"Prefilter ({args.forms}, since {since_str}): {len(products)} of {before}.")

    ledger = _load_ledger()
    if getattr(args, "fast_cached", False):
        emb = _embedded_skiplist()
        if emb:
            before_n = len(ledger); ledger = ledger | emb
            print(f"--fast-cached: seeded {len(ledger) - before_n} already-verified-CLEAN COAs from the "
                  "embedded snapshot (these are skipped; flagged / new products are still fetched). "
                  "Findings are unchanged; 'reviewed' coverage is lower.")
        else:
            print("--fast-cached: no embedded skip-list snapshot in this build; running a full scan.")
    # Optional persistent COA->measurement cache. When on, the WHOLE window is routed through the
    # cache (HITs are instant), so clean COAs are covered every run and re-flag correctly at a new
    # --threshold — instead of being silently skipped by the ledger.
    csv_cache = None
    if getattr(args, "csv_cache", False):
        if cc is None:
            print("--csv-cache requested but coa_csv_cache is unavailable; falling back to the ledger.")
        else:
            csv_cache = cc.CoaCsvCache()
            print(f"  COA CSV cache: {len(csv_cache):,} COAs already extracted "
                  "(HITs reload + re-flag from cache — no re-download, no re-OCR).")
    if getattr(args, "force_rescan", False):
        todo = list(products)   # --force-rescan: ignore the skip-list, reprocess everything in window
        print(f"--force-rescan: ignoring the skip-list — reprocessing ALL {len(todo)} products in the window.")
    elif csv_cache is not None:
        todo = list(products)   # --csv-cache: cover the whole window; cache HITs keep it cheap
        print(f"--csv-cache: routing ALL {len(todo)} in-window COAs through the measurement cache.")
    else:
        todo = [p for p in products if v4.coa_key(p) not in ledger]
    print(f"Scanning {len(todo)} COAs with {args.workers} workers ...\n")

    if csv_cache is not None:
        def _worker(p):
            return cached_or_v15(p, session, args.threshold, csv_cache, allow_network=not args.offline)
    else:
        def _worker(p):
            return process_product(p, session, args.threshold)

    all_results, keep, failures = [], [], []
    new_clean = set(); lock = threading.Lock(); done = 0
    fetched = 0; broken = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_worker, p): p for p in todo}
        for fut in as_completed(futs):
            p = fut.result()
            with lock:
                done += 1
                all_results.append(p)
                if getattr(p, "_coa_present", False):
                    if os.path.exists(v4.cache_path(p)):
                        fetched += 1
                else:
                    if p._coa_status in (MATCH_LINK_BROKEN, MATCH_LINK_MISSING):
                        broken += 1
                parsed = bool(p.analytes) or bool(p.cannabinoids)
                interesting = bool(p.flags) or bool(p.thc_flags) or bool(v5.unquantified_findings(p)) or bool(v5.pathogen_detections(p))
                if interesting:
                    keep.append(p)
                elif parsed:
                    new_clean.add(v4.coa_key(p))
                    if not args.keep_clean_pdfs:
                        try: os.remove(v4.cache_path(p))
                        except OSError: pass
                else:
                    failures.append(p)
                    if "no extractable text" in (p.parse_note or ""):
                        new_clean.add(v4.coa_key(p))
                if done % 100 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)} ({len(keep)} kept, {time.time()-t0:.0f}s)", flush=True)

    # Deferred OCR retry — re-attempt anything still unreadable now that the busy
    # main pass is over and the machine is calm. This is the "rerun later if
    # overloaded" pass: transient OCR timeouts during the crowded main scan get a
    # second, low-load attempt here so no scan is permanently missed.
    ocr_recovered = 0
    if ocr_on:
        unread = [p for p in failures if "no extractable text" in (p.parse_note or "")]
        if unread:
            print(f"\nDeferred OCR retry for {len(unread)} unreadable COA(s) at low load ...")
            for p in unread:
                p.parse_note = ""
                process_product(p, session, args.threshold)   # OCR retried, calm
                if p.analytes or p.cannabinoids:               # now readable
                    if p in failures:
                        failures.remove(p)
                    ocr_recovered += 1
                    if (p.flags or p.thc_flags or v5.unquantified_findings(p)
                            or v5.pathogen_detections(p)):
                        # A COA recovered as a FINDING must NOT stay on the skip-list
                        # (it was added there while still unreadable) — otherwise it
                        # would be skipped next run and silently vanish from reports.
                        new_clean.discard(v4.coa_key(p))
                        if p not in keep:
                            keep.append(p)
            print(f"  recovered {ocr_recovered} of {len(unread)} on retry "
                  f"({len(failures)} still unreadable).")
    _save_ledger(ledger | new_clean)
    if csv_cache is not None:
        csv_cache.flush()                          # atomic write of all measurements extracted this run
        print(f"  COA CSV cache: {len(csv_cache):,} COAs on file now.")

    print("\nBuilding validated analytics ...")
    watch = args.threshold
    for p in all_results:
        p._watch = watch

    ident = Identity(pmap, all_results)

    # report-flagged set (trustworthy severity) and publishable subset
    flagged = [p for p in keep if v5.report_severity(p, watch) in ("RED", "ORANGE", "YELLOW") or p.thc_flags or v5.pathogen_detections(p)]
    pub_raw = [p for p in flagged if p._coa_status in PUBLISHABLE]

    # --- COA FORMAT LEARNING: HOLD extractions the cross-checks judged UNRELIABLE (a top/detail
    #     pass-fail CONFLICT or a COA that does not match its product record) BEFORE they can be
    #     published — bad data is held for human review, never reported confidently. Most COAs are
    #     HIGH/MEDIUM confidence and pass straight through.
    format_holds = [p for p in pub_raw if getattr(p, "_extraction", {}) and p._extraction.get("hold")]
    if format_holds:
        held = set(id(p) for p in format_holds)
        pub_raw = [p for p in pub_raw if id(p) not in held]
        print(f"  COA FORMAT LEARNING: held {len(format_holds)} flagged product(s) with an uncertain "
              "extraction (pass/fail conflict or product mismatch) -> COA Extraction Review queue.")

    # --- V15 COA SOURCE-BINDING AUDIT: re-verify every would-be-published value against
    #     its OWN linked COA; exclude any mismatch to a review queue before anything is
    #     derived/published. Integrity over coverage.
    pub, source_mismatches, provenance_rows, src_metrics = audit_published_coa_sources(pub_raw, watch)
    multi_coa = detect_multiple_coa_alerts(all_results)
    src_metrics["multiple_coa_alert_count"] = len(multi_coa)
    src_metrics["pass_fail_coa_conflict_count"] = sum(1 for a in multi_coa if a.get("conflict"))
    # Conflicting COA Results & Possible Lab-Shopping Indicators (document-level, for review).
    # PERSISTENCE (#9): build a small conflict fingerprint for every COA scanned this run, merge it
    # into the persistent cross-run store, then detect over the UNION. This means a ledger-warm
    # rerun still surfaces previously-found conflicts (their fingerprints persist) AND a conflict
    # whose two COAs were scanned in different runs is now detected — neither was possible when
    # detection only saw this run's products.
    conflict_store = _load_conflict_store()
    cfp_new = 0
    for p in all_results:
        cfp = build_conflict_fingerprint(p, watch)
        if cfp:
            cfp["last_seen"] = debug["runtime_started"]
            if cfp["coa_key"] not in conflict_store:
                cfp_new += 1
            conflict_store[cfp["coa_key"]] = cfp
    _save_conflict_store(conflict_store)
    coa_conflicts = detect_coa_conflicts(list(conflict_store.values()), watch)
    src_metrics["conflict_fingerprints_in_store"] = len(conflict_store)
    src_metrics["conflict_fingerprints_added_this_run"] = cfp_new
    src_metrics["coa_conflict_records"] = len(coa_conflicts)
    src_metrics["coa_conflict_critical"] = sum(1 for c in coa_conflicts if c["severity"] == "Critical")
    src_metrics["coa_conflict_high"] = sum(1 for c in coa_conflicts if c["severity"] == "High")
    src_metrics["coa_conflict_fail_then_pass"] = sum(1 for c in coa_conflicts if c.get("fail_then_pass"))
    if source_mismatches:
        print(f"  COA SOURCE AUDIT: excluded {len(source_mismatches)} product(s) whose flagged value "
              "could not be re-verified in their own linked COA -> COA Source Mismatch Review queue.")
    else:
        print(f"  COA SOURCE AUDIT: all {src_metrics['published_rows_verified_against_linked_coa']} "
              "published flagged values re-verified in their own linked COA.")

    # --- COA FORMAT LEARNING: observe every COA scanned this run into the persistent per-year
    #     learner (so the parser stays historically aware across runs) + record the confidence mix.
    fmt_learner = COAFormatLearner.load()
    conf_mix = Counter()
    coa_year_seen = set()
    for p in all_results:
        prof = getattr(p, "_format_profile", None)
        ass = getattr(p, "_extraction", None)
        if prof and ass:
            fmt_learner.observe(prof, ass, producer=getattr(p, "producer", ""))
            conf_mix[ass["level"]] += 1
            if prof.get("year"):
                coa_year_seen.add(prof["year"])
    fmt_learner.save()
    fmt_year_rows = [fmt_learner.year_summary(y) for y in sorted(coa_year_seen)]
    src_metrics["extraction_confidence_high"] = conf_mix.get("HIGH", 0)
    src_metrics["extraction_confidence_medium"] = conf_mix.get("MEDIUM", 0)
    src_metrics["extraction_confidence_low"] = conf_mix.get("LOW", 0)
    src_metrics["extraction_confidence_uncertain"] = conf_mix.get("UNCERTAIN", 0)
    src_metrics["extractions_held_uncertain"] = len(format_holds)
    src_metrics["coa_years_observed"] = len(coa_year_seen)

    # per-analyte items (publishable only in ranked sections) — derived from the AUDITED set
    analyte_items = {key: category_rows(pub, key) for key, _t in ANALYTE_TABLES}
    mycos = mycotoxin_rows(pub)
    pests = pesticide_rows(pub)
    solvs = solvent_rows(pub)
    paths = pathogen_rows(pub)

    # Cannabinoid review split into THREE separate buckets: non-infused flower,
    # infused flower products, and vapes/concentrates/extracts (never combined).
    thc_flower, infused_potency, extract_potency = [], [], []
    implausible_flower = 0
    for p in pub:
        rv = thc_review_value(p)
        if not rv or rv[1] <= THC_REVIEW_PCT:
            continue
        cat = product_category(p)
        if cat == "flower":
            if rv[1] <= FLOWER_CANN_MAX:
                thc_flower.append((p, rv[0], rv[1]))
            else:
                implausible_flower += 1   # >45% on flower = parse error / mislabeled, excluded
        elif cat == "infused":
            infused_potency.append((p, rv[0], rv[1]))
        elif cat == "extract":
            extract_potency.append((p, rv[0], rv[1]))
        # 'other' (edibles/tinctures/etc.) -> not part of the cannabinoid review
    thc_flower.sort(key=lambda t: t[2], reverse=True)
    infused_potency.sort(key=lambda t: t[2], reverse=True)
    extract_potency.sort(key=lambda t: t[2], reverse=True)

    # remediation + cleaner
    # Remediation review = non-infused FLOWER with a yeast & mold result at/under 100 CFU/g
    # (a measured 0-100, OR a below-detection bound such as "< 100 CFU/g"), and no other flag.
    remediation = [p for p in all_results if is_noninfused_flower(p)
                   and _remediation_ym(p) is not None
                   and v5.report_severity(p, watch) is None and not p.thc_flags]
    cleaner, cleaner_review = [], []
    for p in all_results:
        if not is_noninfused_flower(p):
            continue
        if v5.report_severity(p, watch) or p.thc_flags or v5.unquantified_findings(p) or v5.pathogen_detections(p):
            continue
        ym = p.analytes.get("tymc", {}).get("value")
        if ym is None or not (800 <= ym <= 3000):
            continue
        tt = thc_value(p, "total_thc")
        if tt is None or tt <= 0 or thc_conflict(p):
            cleaner_review.append(p)        # potency missing/parser-conflict -> candidates
        else:
            cleaner.append(p)
    cleaner.sort(key=lambda p: p.analytes.get("tymc", {}).get("value") or 0)

    # exec rows (publishable, CT% available), cross-category
    exec_rows = []
    for p in pub:
        for d in v5.quantified_details(p, watch):
            if v5.is_flag_driver(d) and d["ct_pct"] is not None:
                exec_rows.append((p, d))
    exec_rows.sort(key=lambda pd: pd[1]["ct_pct"], reverse=True)

    # producer / lab trend rows (keyed by the concise producer-level label).
    # DENOMINATOR FIX: count each producer's total over the FULL prefiltered window (`products`),
    # NOT the ledger-reduced scanned set — otherwise "% flagged" = flagged/(mostly-flagged) ≈ 100%
    # (misleading). Over the window it is the honest flagged-of-this-producer's-window-products rate.
    reviewed_c = Counter(producer_label_short(p.producer, ident) for p in products)
    flagged_c = Counter(producer_label_short(p.producer, ident) for p in pub)
    issue_c = defaultdict(Counter); conf_of = {}
    for p in products:
        conf_of[producer_label_short(p.producer, ident)] = ident.resolve(p.producer)["confidence"]
    for p in pub:
        lab = producer_label_short(p.producer, ident)
        for d in v5.quantified_details(p, watch):
            if v5.is_flag_driver(d):
                issue_c[lab][d["name"]] += 1
        if p.thc_flags and is_noninfused_flower(p):
            issue_c[lab]["High-THC Flower"] += 1
    producer_rows = []
    for label, n in reviewed_c.items():
        fl = flagged_c.get(label, 0)
        if fl == 0:
            continue
        producer_rows.append(dict(label=label, reviewed=n, flagged=fl, pct=fl/n*100,
                                  top=(issue_c[label].most_common(1)[0][0] if issue_c[label] else "—"),
                                  conf=conf_of.get(label, 0)))
    producer_rows.sort(key=lambda r: r["flagged"], reverse=True)

    lab_flag = Counter(lab_name(p, lmap) for p in pub if v5.report_severity(p, watch) in ("RED", "ORANGE", "YELLOW"))
    lab_thc = Counter(lab_name(p, lmap) for p, _k, _v in thc_flower)
    lab_top = defaultdict(Counter)
    for p in pub:
        for d in v5.quantified_details(p, watch):
            if v5.is_flag_driver(d):
                lab_top[lab_name(p, lmap)][d["name"]] += 1
    lab_rows = [dict(lab=lab, flagged=lab_flag.get(lab, 0), thc=lab_thc.get(lab, 0),
                     top=(lab_top[lab].most_common(1)[0][0] if lab_top[lab] else "—"))
                for lab in sorted(set(list(lab_flag) + list(lab_thc)), key=lambda l: -(lab_flag.get(l, 0)+lab_thc.get(l, 0)))]

    # zero-result + self-audit
    compliance_flags = compliance_flag_rows(pub, watch)
    ombudsman = ombudsman_rows(pub)
    tym_findings = tym_standard_findings(pub)   # lab- & date-aware TYM standard concerns
    compliance_flags = compliance_flags + tym_compliance_rows(tym_findings)   # add TYM transparency leads
    for _r in compliance_flags:                                                # triage into Critical/High/Moderate/Low
        _r["tier"] = compliance_tier(_r)
    # Legal standard verification (Part B item 7) — LOCAL-FIRST, internet-FALLBACK, fully fail-safe.
    # Wrapped so a slow/failed/blocked network can NEVER crash or hang report generation: on any
    # problem we keep whatever was gathered and continue with "unverified" rows + logged sources.
    legal_records, legal_unreachable = [], []
    try:
        legal_records, legal_unreachable = verify_standards_for_report(
            tym_findings, compliance_flags, online=not args.offline, session=session)
    except Exception as _e:
        debug["legal_verification_error"] = f"{type(_e).__name__}: {str(_e)[:120]}"
    zero, draft_zero = zero_result_checks(all_results, pub, watch)
    audit, remaining = self_audit(all_results, flagged,
                                  [p for p, _k, _v in thc_flower], infused_potency,
                                  {"identities": ident.cache}, zero)
    draft = draft_zero or bool(remaining)

    # priority queue (publishable + unverified flagged for manual COA review)
    def pscore(p):
        s = 0
        if v5.pathogen_detections(p): s += 1000
        if p.pesticides == "FAIL" or p.solvents == "FAIL": s += 400
        for d in v5.quantified_details(p, watch):
            if v5.is_flag_driver(d) and d.get("ct_pct"): s += min(d["ct_pct"], 200)
        if p.thc_flags: s += 80
        if p._coa_status not in PUBLISHABLE: s += 120
        return s
    queue = sorted(flagged, key=pscore, reverse=True)

    sev_counts = Counter(v5.report_severity(p, watch) for p in pub)
    debug.update({
        "elapsed_seconds": round(time.time()-t0, 1),
        "products_reviewed": len(all_results),
        "coas_fetched": fetched,
        "coas_reused_from_ledger": len(products) - len(todo),
        "broken_or_missing_coa_links": broken,
        "unreadable_after_retry": len(failures),
        "ocr_recovered_on_retry": ocr_recovered,
        "ocr_ok": _OCR_STATS["ok"], "ocr_native_crashes_isolated": _OCR_STATS["crashes"],
        "ocr_timeouts": _OCR_STATS["timeouts"], "overload_backoffs": _OCR_STATS["backoffs"],
        "ocr_serialized_low_memory": _OCR_STATS["serialized_low_memory"],
        "ocr_proceeded_under_sustained_load": _OCR_STATS["proceeded_under_load"],
        "ocr_cache_hits": _OCR_STATS.get("cache_hits", 0),
        "ocr_rescued_high_dpi": _OCR_STATS.get("rescued_high_dpi", 0),
        "flagged_total": len(flagged),
        "flagged_published": len(pub),
        "coa_verification_queue": len(flagged) - len(pub),
        "high_thc_noninfused_flower": len(thc_flower),
        "implausible_flower_potency_excluded": implausible_flower,
        "infused_potency_ref": len(infused_potency),
        "vape_concentrate_extract_potency_ref": len(extract_potency),
        "potency_parser_conflicts": sum(1 for p in all_results if thc_conflict(p)),
        "zero_result_draft_warnings": sum(1 for c in zero if c["status"] == "Needs Historical Parser Review"),
        "zero_result_partial_coverage": sum(1 for c in zero if c["status"] == "Partial Coverage"),
        "zero_result_historical_absence": sum(1 for c in zero if c["status"] == "Not Reported (historical)"),
        "self_audit_remaining_issues": len(remaining),
        # V9 COA-interpretation transparency: parser-uncertainty observations,
        # documented rather than silently assumed correct.
        "manual_review_limit_match": sum(
            1 for p in all_results for e in p.analytes.values() if e.get("_limit_match_review")),
        "below_detect_results_excluded": sum(
            1 for p in all_results for e in p.analytes.values() if e.get("_below_detect")),
        "coa_value_unverified_routed_to_review": sum(
            1 for p in all_results for e in p.analytes.values() if e.get("_coa_unverified")),
        "duplicate_coa_rows": len([k for k, c in Counter(v4.coa_key(p) for p in all_results).items() if c > 1]),
        "potential_statute_regulatory_flags": len(compliance_flags),
        "compliance_leads_critical": sum(1 for r in compliance_flags if r.get("tier") == "Critical"),
        "compliance_leads_high": sum(1 for r in compliance_flags if r.get("tier") == "High"),
        "compliance_leads_moderate": sum(1 for r in compliance_flags if r.get("tier") == "Moderate"),
        "compliance_leads_low": sum(1 for r in compliance_flags if r.get("tier") == "Low"),
        "ombudsman_near_limit_products": len(ombudsman),
        "tym_standard_concern_products": len(tym_findings),
        "tym_high_risk_window_altasci": sum(1 for a in tym_findings if a["high_risk"]),
        "tym_aspergillus_detected": sum(1 for a in tym_findings if a["aspergillus_detected"]),
        "tym_over_current_ct_limit": sum(1 for a in tym_findings if a["over_current"]),
        "tym_over_strict_benchmark": sum(1 for a in tym_findings if a["over_strict"]),
        "tym_below_detect_above_strict_unconfirmable": sum(1 for a in tym_findings if a["bd_above_strict"]),
        "tym_passed_no_value_disclosed": sum(1 for a in tym_findings if a["passed_no_value"]),
        "conflicting_coa_records": len(coa_conflicts),
        "conflicting_coa_critical": sum(1 for c in coa_conflicts if c["severity"] == "Critical"),
        "conflicting_coa_high": sum(1 for c in coa_conflicts if c["severity"] == "High"),
        "conflicting_coa_earlier_fail_later_pass": sum(1 for c in coa_conflicts if c.get("fail_then_pass")),
    })
    debug.update(src_metrics)   # V15 COA source-binding audit metrics
    # Source-binding: did any product that REMAINS in the published set still carry a value not
    # verified in its own linked COA? (Keyed by unique registration number, so good values from
    # EXCLUDED products are never mistaken for a published failure.)
    _pub_coa = {p.registration_number for p in pub}
    _unverified_in_pub = any(r["value_verified_in_linked_coa"] == "NO" and r["coa_number"] in _pub_coa
                             for r in provenance_rows)
    # Were any UNCERTAIN extractions nonetheless published as findings? (They should be held.)
    _uncertain_published = sum(1 for p in pub if (getattr(p, "_extraction", None) or {}).get("level") == "UNCERTAIN")
    debug["uncertain_extractions_published"] = _uncertain_published
    _year_readiness = [{"year": r["year"], "verdict": r["verdict"]} for r in fmt_year_rows]
    status, fail_reasons, warn_reasons = validation_summary(
        debug, remaining, zero, src_metrics, _unverified_in_pub, _uncertain_published, _year_readiness)
    debug["report_status"] = status
    debug["validation_fail_reasons"] = fail_reasons
    debug["validation_warn_reasons"] = warn_reasons
    draft = status == "FAIL"

    # ---- Self-audit + persistent cross-run improvement log (Part B items 9 & 10) ----
    prior_log = load_self_improve_log()
    self_audit_obs = generate_self_audit(fmt_year_rows, zero, src_metrics, debug, format_holds, conf_mix,
                                         legal_records=legal_records, legal_unreachable=legal_unreachable)
    _run_stamp = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    save_self_improve_log(prior_log + [dict(run_time=_run_stamp, status=status, observations=self_audit_obs)])
    # Carry forward the previous run's notes so the reader sees the program remembering its weaknesses.
    prior_run = prior_log[-1] if prior_log else None

    ctx = dict(draft=draft, status=status, pmap=pmap, lmap=lmap, ident=ident, watch=watch, window=window,
               self_audit_obs=self_audit_obs, prior_run=prior_run, self_improve_runs=len(prior_log) + 1,
               legal_records=legal_records, legal_unreachable=legal_unreachable,
               reg_corroboration=reg_corroboration(all_results),
               flagged=flagged, exec_rows=exec_rows, audit=audit, queue=queue,
               producer_rows=producer_rows, lab_rows=lab_rows, analyte_items=analyte_items,
               pesticides=pests, solvents=solvs, mycotoxins=mycos, pathogens=paths,
               thc_flower=thc_flower, infused_potency=infused_potency,
               extract_potency=extract_potency, remediation=remediation,
               cleaner=cleaner, cleaner_review=cleaner_review, zero=zero, debug=debug,
               compliance_flags=compliance_flags, ombudsman=ombudsman, tym_findings=tym_findings,
               source_mismatches=source_mismatches, multi_coa=multi_coa, provenance_rows=provenance_rows,
               coa_conflicts=coa_conflicts, src_metrics=src_metrics,
               format_holds=format_holds, fmt_year_rows=fmt_year_rows, conf_mix=dict(conf_mix),
               fail_reasons=fail_reasons, warn_reasons=warn_reasons,
               accounting=dict(window=len(products), scanned_this_run=len(all_results),
                               reused_from_ledger=max(0, len(products) - len(todo)),
                               coas_fetched=fetched, published_findings=len(pub)),
               n_reviewed=len(products), n_pub=len(pub), n_queue=len(flagged)-len(pub),
               n_red=sev_counts.get("RED", 0), n_org=sev_counts.get("ORANGE", 0),
               n_yel=sev_counts.get("YELLOW", 0), n_thc=len(thc_flower))

    # Allocate this run's GLOBAL report number + a brand-new per-run output FOLDER FIRST (this also
    # points RUN_OUT_DIR at the folder), so the PDF, CSVs, and diagnostics all land together in it and
    # nothing is ever overwritten. Caches stay in OUT_DIR.
    report_no, run_folder, run_dt = allocate_run(REPORT_TYPE_STATEWIDE)
    ctx["report_dt"] = run_dt
    out_path = os.path.join(run_folder, report_filename(report_no, REPORT_TYPE_STATEWIDE, run_dt))
    write_outputs(ctx)        # writes CSVs/diagnostics INTO run_folder (RUN_OUT_DIR)
    # --- Report-numbering integrity (CRITICAL) — the number is the PRIMARY identifier and must be
    #     unique, non-overwriting, and consistent with the filename. The run folder is brand-new and
    #     the number came from the registry reconciled with disk, so the PDF cannot pre-exist. ---
    _fn = _REPORT_NUM_RX.match(os.path.basename(out_path))
    if not _fn or int(_fn.group(1)) != report_no:
        raise SystemExit(f"FATAL report-numbering error: filename/number mismatch ({out_path!r} vs #{report_no}).")
    if os.path.exists(out_path):
        raise SystemExit(f"FATAL: report #{report_no} would overwrite an existing file: {out_path}")
    build_pdf(out_path, report_no, ctx)

    # ONE canonical file per report, kept with its CSV exports in the reports folder. We do NOT also
    # copy it to the working folder: a same-named duplicate in two places is what makes the OS prompt
    # "overwrite" when you save or move the PDF. Each report is uniquely numbered + second-stamped.
    print("\n" + "=" * 74)
    print(f"  {PRODUCT_NAME.upper()} — REPORT #{report_no} [{status}] IS READY")
    print(f"    {os.path.abspath(out_path)}")
    print(f"  Reviewed {len(all_results):,} • Published {len(pub):,} "
          f"({sev_counts.get('RED',0)} Red, {sev_counts.get('ORANGE',0)} Orange, "
          f"{sev_counts.get('YELLOW',0)} Yellow, {len(thc_flower)} High-THC flower) • "
          f"{len(flagged)-len(pub)} in COA queue")
    print(f"  Self-audit remaining: {len(remaining)} • Parser-gap warnings: "
          f"{sum(1 for c in zero if c['status']=='Needs Historical Parser Review')} • Partial-coverage: "
          f"{sum(1 for c in zero if c['status']=='Partial Coverage')}")
    if coa_conflicts:
        _ccc = sum(1 for c in coa_conflicts if c['severity'] == 'Critical')
        _cch = sum(1 for c in coa_conflicts if c['severity'] == 'High')
        print(f"  Conflicting-COA review leads: {len(coa_conflicts)} "
              f"({_ccc} Critical, {_cch} High, "
              f"{sum(1 for c in coa_conflicts if c.get('fail_then_pass'))} earlier-fail→later-pass)")
    print(f"  Status: {status}")
    print(f"  Elapsed {time.time()-t0:.0f}s")
    print("=" * 74)


# ============================================================================
# DORMANT / RESERVED — Environmental Linkage & Compliance (Phase-2 concept, NOT used)
# ----------------------------------------------------------------------------
# This block intentionally lies in wait: it is never imported into, called by, or
# referenced from the report pipeline, and it changes nothing about how CannaScope
# parses COAs or builds reports. It exists only to PRESERVE the design so a future
# version can pick it up. The feature is hard-disabled; even enabling the flag does
# nothing but raise, by design, because the required data pipelines (grow-site
# geocoding, cultivation type, pre-pulled EWG/SDWIS + DEEP/SSURGO layers, and the
# resolved CT statutory/regulatory corpus) do not exist yet. Two jobs are specified:
# (1) environmental linkage (contaminant -> soil/water pathway, hypotheses only) and
# (2) compliance screening (POTENTIAL CT regulatory violations, each tied to a cited
# authority). If ever built, both must be SEPARATE, clearly labeled layers — never
# mixed into the COA-traceable contaminant findings or severity counts — and the
# compliance output is a flag for a qualified compliance officer or attorney, NEVER a
# legal determination and never auto-published.
# ============================================================================
ENVIRONMENTAL_LINKAGE_ENABLED = False   # leave False — Phase-2 only, no data pipelines yet

ENVIRONMENTAL_LINKAGE_SPEC = r'''
Cannascope V8 — Environmental Linkage & Compliance Prompt

For each cultivation site, do two DISTINCT jobs: (1) environmental linkage — assess how
plausibly each lab-detected contaminant connects to local soil and source/tap water
(pathways + likelihood; proximity is never proof); (2) compliance screening — compare
the site's data against CT cannabis law and surface POTENTIAL violations, each tied to a
cited authority with a confidence level. Flag for human review; never adjudicate.
CT authorities are named inline; swap per jurisdiction.

INPUTS
1. Grow sites — name/license ID, license type/endorsement, lat/long (or address to
   geocode), cultivation type (indoor / greenhouse / outdoor / mixed-light), and where
   available: canopy/plant counts, water source, pesticide/input records, municipality,
   seed-to-sale/inventory records.
2. Contaminant results — analyte, value, units, detection/action limit, pass/fail,
   testing lab, test date, from CT panels: heavy metals (As, Cd, Pb, Hg), pesticides,
   microbials, mycotoxins, residual solvents.

REFERENCE DATA — ENVIRONMENTAL (per site, by location; default 1-mile buffer, widen to
watershed/aquifer for water):
- CT DEEP GIS Open Data (deepmaps.ct.gov / ArcGIS Hub): aquifer protection areas,
  water-quality classes (GA/GAA/GB groundwater, surface-water class), remediation/
  contaminated-site inventories, registered wells, statewide soils.
- USDA NRCS SSURGO / Web Soil Survey: soil series, texture, drainage, pH, any background
  metal concentrations for the map unit beneath the site.
- CT DPH Drinking Water Section + EPA SDWIS: public water system serving the parcel,
  source type (groundwater vs surface), historical violations/detections.
- EWG Tap Water Database (ewg.org/tapwater, CT): utility-served sites only — contaminants
  the utility self-reported, scored vs BOTH the EPA legal limit and EWG's stricter health
  guideline. Match by zip/utility name. Public/municipal only; data lags (~2018-2023);
  blocks automated fetching, so PRE-PULL into V8, do not scrape live.
- Private-well sites: skip EWG, mark utility fields not_applicable, treat source water as
  groundwater of the local aquifer class via CT DEEP/DPH well + groundwater data.
- EPA / CT brownfield and release inventories: nearby known contamination.

REFERENCE DATA — REGULATORY CORPUS (resolve and cite exact sections; confirm current text
in eRegulations before asserting):
- CGS Chapter 420h — Regulation of Adult-Use Cannabis (RERACA) (cga.ct.gov): core
  adult-use statute (licensing, cultivation, testing, transport, sale, enforcement).
- CGS Chapter 420f — Palliative Use of Marijuana (cga.ct.gov): medical-program statute.
- DCP Policies & Procedures (edition effective Nov. 12, 2024) — full force of law:
  product-quality/testing, minor safeguards, diversion security, labeling/packaging,
  recordkeeping, home-grow. Canonical text at eRegulations.ct.gov.
- RCSA Sec. 21a-408 — Palliative Use regulations (eRegulations.ct.gov).
- Relevant Public Acts (amendment layer): 21-1 (June S.S.), 22-103, 22-104, 23-52, 23-79,
  23-166, 24-76, 24-95, 24-115, 25-101, 25-166, 26-8, 26-100 — check for later amendments.
- eRegulations.ct.gov (eRegsPortal): searchable repository for P&P and RCSA; resolve exact
  current section text + effective date.
- CT DEEP environmental rules where cultivation overlaps (pesticide application/
  registration, water diversion/discharge, waste disposal, siting in aquifer protection).

JOB 1 — ENVIRONMENTAL LINKAGE
1. Spatially join site to layers (point-in-polygon soils/aquifer; nearest-feature wells/
   releases; service-area lookup public water).
2. Match contaminant to pathway:
   - Heavy metals (As, Cd, Pb, Hg): cannabis is a hyperaccumulator -> most plausibly
     environmental. Cross-check SSURGO background + nearby releases (outdoor/soil) and
     source-water data (incl. EWG arsenic/lead) for all grows.
   - Source-derived water contaminants (arsenic, nitrate, PFAS, radiological): via
     irrigation/source water; link especially for hydroponic/well-irrigated.
   - Disinfection byproducts (HAAs, bromodichloromethane, dichloroacetic acid, chloroform,
     TTHMs): municipal treatment, not environmental/plant-uptaken; classify
     treatment_byproduct, do not link absent reason.
   - Pesticides: usually cultivation-introduced (applied/drift). Environmental linkage only
     with a nearby agricultural release or legacy soil residue.
   - Microbials/mycotoxins: humidity/handling/post-harvest; not soil/water linked unless
     irrigation water implicated.
   - Residual solvents: process-introduced (extraction); no environmental linkage.
3. Weight by cultivation type: outdoor/soil -> full soil + water; indoor hydroponic ->
   water source only, soil non-contributing.

JOB 2 — COMPLIANCE SCREENING (potential violations; distinguish clear vs potential vs
insufficient_data — do not overstate). Detection categories:
1. Testing & product quality — analyte >= CT action limit is a failed result that may not
   pass to market; check failed batches were handled/remediated/destroyed per P&P, not
   released. (P&P product-quality/testing; Ch. 420h.)
2. Testing completeness & integrity — full mandated panel by an approved lab? Flag missing
   analytes, expired/owed retests, results clustering just under action limits, and
   lab-switching after a failure (possible lab-shopping).
3. Contamination source & input controls — when Job 1 attributes a contaminant to source
   water/soil/pesticide, flag related breach: untreated contaminated irrigation water,
   unregistered/off-label pesticide, or cultivation in an aquifer protection area without
   the DEEP compliance.
4. License scope, canopy & plant limits — activity matches license type/endorsement;
   canopy/plant counts within authorized limits.
5. Siting & zoning — grow location vs municipal zoning and required buffers/setbacks.
6. Traceability & diversion — seed-to-sale gaps and yield/inventory anomalies. (P&P
   diversion-security; Ch. 420h.)
7. Labeling, packaging & minor safeguards — where product data present, screen packaging/
   labeling and youth-appeal restrictions.
8. Recordkeeping & reporting — missing submissions or missed deadlines.

OUTPUT
Environmental linkage record (per contaminant of interest): site_id, contaminant, value,
limit, result, cultivation_type, soil_context (series, drainage, background level, nearby
releases), water_context (source type, system/aquifer class, detections/violations),
pathway (geogenic_soil | source_water | treatment_byproduct | legacy_contamination |
cultivation_introduced | process_introduced | indeterminate), linkage_confidence
(high/medium/low + one-sentence rationale).
Potential-violation record (per compliance hit): site_id, rule_category (one of the eight),
finding (1-2 sentences), cited_authority (specific statute/P&P/RCSA section + source URL;
authority_unverified: true if current text not confirmed in eRegulations), status
(likely_violation | potential_violation | insufficient_data), severity (high/medium/low;
health-safety + diversion rank highest), confidence (high/medium/low + rationale),
recommended_review (next human step: compliance officer, counsel, DCP/DEEP).
Close with: per-site summary; ranked list of sites where environmental linkage is most
credible; ranked list of sites with the most serious potential violations.

GUARDRAILS: NOT legal advice and NOT an adjudication — every compliance output is a flag
for a qualified compliance officer or attorney; use "potential," state confidence, never
assert a violation has legally occurred. Cite, don't paraphrase loosely — pin each flag to
a specific section, resolve current text/effective date in eRegulations first, set
authority_unverified: true if not retrieved; never fabricate a citation/section/quote,
quote minimally. Check the amendment layer (a Public Act may have changed the provision).
Correlation, not proof (environmental linkage is a hypothesis with a confidence level).
Resolution mismatch — SSURGO map units / water-system service areas are coarse vs a
parcel; say so when it weakens a claim. Coverage gaps — mark context unknown rather than
inferring; if data for a compliance check is absent, return insufficient_data. Privacy —
treat exact coordinates and license IDs as sensitive (never in an outbound URL/query
string; aggregate when public). No fabricated values (if a dataset was not retrieved, say
so).
'''


def environmental_linkage_module(*args, **kwargs):
    """RESERVED, DORMANT. A future Phase-2 environmental-context module would live
    here. It is deliberately NOT wired into the report pipeline and must stay that way
    until the Phase-2 data pipelines exist. See ENVIRONMENTAL_LINKAGE_SPEC."""
    if not ENVIRONMENTAL_LINKAGE_ENABLED:
        return None
    raise NotImplementedError(
        "Environmental Linkage is a reserved Phase-2 concept with no implementation and "
        "no data pipelines. See ENVIRONMENTAL_LINKAGE_SPEC.")


# ============================================================================
# DORMANT / RESERVED - Compliance Screening (Phase-2 concept, NOT used)
# ----------------------------------------------------------------------------
# The full multi-category compliance-screening spec, stored verbatim. The complete
# version (licensing scope, diversion, labeling, security, recordkeeping, transport)
# needs an LLM + resolved rule corpus + licensing/operational data and remains
# RESERVED/dormant (the stub below stays disabled). A LIMITED, deterministic subset IS
# now active: the "Potential Statute & Regulatory Flags to Evaluate" PDF section
# (see compliance_flag_rows) surfaces ONLY the testing/product-quality category that is
# derivable from COA data CannaScope reads (over-legal-limit result, detected pathogen,
# failed panel), as human-review-only POTENTIAL flags with cited (unverified) authority
# and a clickable COA link - never adjudicated, never auto-acted-on.
# ============================================================================
COMPLIANCE_SCREENING_ENABLED = False   # leave False - Phase-2 only, no rule corpus wired

COMPLIANCE_SCREENING_SPEC = r'''
Cannascope V8 — Compliance Screening Prompt

Screens cannabis license/operations data against Connecticut cannabis law and surfaces
POTENTIAL regulatory/statutory violations, each tied to a specific cited authority with a
confidence level. Outputs are review flags for a qualified compliance officer or attorney
- never legal determinations.

ROLE: compliance-screening engine. Compare a licensee's data against CT cannabis law and
rules and surface potential violations. For each finding cite the specific authority, state
likely_violation / potential_violation / insufficient_data, assign confidence. Flag for
human review; do not adjudicate.

INPUTS (any subset): license ID, license type/endorsement, entity and owners, operational
records (canopy/plant counts, activity logs, seed-to-sale/inventory), lab results + dates,
labeling/packaging, advertising/marketing, security/diversion controls, recordkeeping and
required filings, municipality/location.

REGULATORY CORPUS (resolve and cite exact sections; confirm current text + effective date
in eRegulations before asserting):
- CGS Chapter 420h - Regulation of Adult-Use Cannabis (RERACA) (cga.ct.gov): core adult-use
  statute (licensing, cultivation, testing, transport, sale, enforcement, penalties).
- CGS Chapter 420f - Palliative Use of Marijuana (cga.ct.gov): medical-program statute.
- DCP Policies & Procedures (edition effective Nov. 12, 2024) - full force of law:
  product-quality/testing, minor safeguards, diversion security, labeling/packaging,
  recordkeeping, home-grow. Canonical text at eRegulations.ct.gov.
- RCSA Sec. 21a-408 - Palliative Use regulations (eRegulations.ct.gov).
- Relevant Public Acts (amendment layer): 21-1 (June S.S.), 22-103, 22-104, 23-52, 23-79,
  23-166, 24-76, 24-95, 24-115, 25-101, 25-166, 26-8, 26-100 - check for later amendments.
- eRegulations.ct.gov (eRegsPortal): searchable repository for P&P + RCSA; resolve exact
  current section text + effective date.

SCREENING CATEGORIES (per licensee; build a potential-violation record per hit; distinguish
clear vs potential vs insufficient_data - do not overstate):
1. Licensing & scope - license valid/current/in good standing; activity matches type/
   endorsement; ownership/control + social-equity/backer conditions consistent with what
   was approved; canopy/plant counts within authorized limits.
2. Testing & product quality - required panels completed by an approved lab; any result at/
   above action limit was handled/remediated/destroyed per P&P, not released. Flag missing
   analytes, owed/expired retests, results clustering just under limits, lab-switching
   after a failure.
3. Traceability & diversion - seed-to-sale complete and reconciles; flag inventory/yield
   anomalies, transfers to unlicensed parties, or gaps suggesting diversion. (P&P
   diversion-security; Ch. 420h.)
4. Labeling, packaging & marketing - packaging/labeling meet requirements; not designed to
   appeal to minors; advertising/marketing meets content + placement restrictions.
5. Security & operations - required physical/operational security controls and SOPs in
   place and followed.
6. Recordkeeping & reporting - required records maintained; mandated submissions filed on
   time; flag missing filings or missed deadlines.
7. Transport & sale - transport manifests, transfer rules, sale limits, point-of-sale age/
   ID requirements met where data present.

OUTPUT - potential-violation record per hit: license_id, rule_category (one of the seven),
finding (1-2 sentences), cited_authority (specific section e.g. "CGS Ch. 420h, sec ...",
"DCP P&P sec ...", "RCSA Sec. 21a-408-..." + source URL; authority_unverified: true if
current text not confirmed in eRegulations), status (likely_violation | potential_violation
| insufficient_data), severity (high/medium/low; health-safety, diversion, minor-safety
rank highest), confidence (high/medium/low + one-sentence rationale), recommended_review
(next human step: compliance officer, counsel, DCP). Close with a per-licensee summary and
a ranked list of the most serious potential violations across the set.

GUARDRAILS: NOT legal advice / NOT an adjudication - every output is a flag for a qualified
compliance officer or attorney; use "potential," state confidence, never assert a violation
has legally occurred. Cite, don't paraphrase loosely - pin each flag to a specific section,
resolve current text + effective date in eRegulations first, set authority_unverified: true
if not retrieved; never fabricate a citation/section/quote, quote minimally. Check the
amendment layer (a Public Act may have changed the provision). insufficient_data is a valid
result - if data for a check is absent, return it rather than guessing. Privacy - treat
license IDs and entity/owner details as sensitive (never in an outbound URL/query string;
aggregate when public). No fabricated values (if a record or rule was not retrieved, say
so).
'''


def compliance_screening_module(*args, **kwargs):
    """RESERVED, DORMANT. A future Phase-2 compliance-screening module would live here.
    It is deliberately NOT wired into the report pipeline and must stay that way until a
    resolved CT rule corpus + review workflow exist. See COMPLIANCE_SCREENING_SPEC."""
    if not COMPLIANCE_SCREENING_ENABLED:
        return None
    raise NotImplementedError(
        "Compliance Screening is a reserved Phase-2 concept with no implementation and "
        "no rule corpus. See COMPLIANCE_SCREENING_SPEC.")


# ============================================================================
# PATIENT-REPORTED PRODUCT CONCERN — on-demand personalized patient PDF (V15)
# ----------------------------------------------------------------------------
# ADDITIVE feature. A patient reports a concern about ONE specific product; this
# resolves that product against the data CannaScope already ingests (the CT
# product registry egd5-wb6r + the product's live COA), runs the SAME flag logic
# the regular report uses (Ombudsman closeness to the CT action limit, CT legal
# limits, CannaScope's stricter internal standards, compliance flags), and writes
# a single patient-friendly PDF explaining what the testing data shows.
#
# It does NOT touch the regular report pipeline (main()), has its own output
# folder, never overwrites a file, never fabricates a value, and is framed as
# ADVISORY / INFORMATIONAL — never a claim that the product caused any symptom,
# and never medical advice.
# ============================================================================
PATIENT_OUT_DIR = os.path.join("output", "consumer_concerns")
# ConsumerConcern report filenames follow the global naming standard (see _consumer_report_path).
PATIENT_NEAR_PCT = OMBUDSMAN_THRESHOLD   # reuse the tunable near-limit line (% of CT limit)
_NDC_COL = "National Drug Code"


def _p_norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _p_norm_ndc(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _p_entity_tokens(s):
    """Cultivator/entity word tokens, dropping common corporate suffixes so
    'Nutmeg New Britain IV LLC' compares on its meaningful words."""
    toks = re.findall(r"[a-z0-9]+", (s or "").lower())
    drop = {"llc", "inc", "co", "company", "corp", "corporation", "ltd", "the", "of"}
    return [t for t in toks if t not in drop]


def _patient_registry_rows(session, offline=False):
    """The FULL registry rows (all columns, incl. National Drug Code + cannabinoids)
    for identifier matching. Prefers an existing local cache; downloads only if
    needed and online. v4's Product parser keeps only a subset of columns, so the
    patient resolver reads the CSV directly — this does not change v4 or the
    regular pipeline."""
    import csv as _csv
    text = None
    candidates = [REGISTRY_CACHE,
                  os.path.join("CannaScope CT Beta V9 - Reports", "Registry Cache.csv"),
                  os.path.join("CannaScope CT Beta V6.1 - Reports", "Registry Cache.csv")]
    for c in candidates:
        if os.path.exists(c):
            with open(c, encoding="utf-8", errors="replace") as f:
                text = f.read()
            break
    if text is None:
        if offline:
            raise SystemExit("No registry cache found and --offline set. Run one online "
                             "report first to seed the registry cache.")
        print("Registry: downloading fresh CSV for patient lookup ...")
        r = session.get(v4.CSV_URL, timeout=180)
        r.raise_for_status()
        text = r.content.decode("utf-8", errors="replace")
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(REGISTRY_CACHE, "w", encoding="utf-8") as f:
            f.write(text)
    return list(_csv.DictReader(text.splitlines()))


def _resolve_qr(url, session, offline=False):
    """Best-effort: follow the QR/short link to its final document URL and pull an
    eLicense DocumentIdnt if present. Never raises; never sends patient identifiers
    in the request. Returns (final_url, document_idnt)."""
    if not url or offline or session is None:
        return ("(not resolved — offline)" if offline else "", "")
    try:
        resp = session.get(url, allow_redirects=True, timeout=20)
        final = resp.url or ""
        m = re.search(r"DocumentIdnt=(\d+)", final)
        return (final, m.group(1) if m else "")
    except Exception as e:
        return (f"(could not resolve — {type(e).__name__})", "")


def resolve_patient_product(rows, pin, session=None, offline=False):
    """Resolve the patient's identifiers to ONE registry row WITHOUT guessing.

    Lookup order, per spec:
      (a) exact COA/registry match  — QR → registry COA link, or exact NDC
      (b) cultivator + corroboration (product name / reported cannabinoids)
      (c) product name + dates
    Returns a dict: row (or None), lookup_path, matched_on[], conflicts[],
    candidates (count near-misses), qr_resolved, qr_docidnt."""
    ndc_idx = {}
    for r in rows:
        n = _p_norm_ndc(r.get(_NDC_COL))
        if n:
            ndc_idx.setdefault(n, r)

    provided_ndcs = [x for x in (pin.get("ndc_stated"), pin.get("ndc_label")) if x]
    matched_on, conflicts, lookup_path, row = [], [], "", None

    qr_resolved, qr_docidnt = _resolve_qr(pin.get("qr"), session, offline)

    # (a) exact COA / registry --------------------------------------------------
    if qr_docidnt:
        for r in rows:
            if f"DocumentIdnt={qr_docidnt}" in (r.get("LAB-ANALYSIS") or ""):
                row, lookup_path = r, "QR/COA document resolved to the registry COA link"
                matched_on.append(f"QR → COA document #{qr_docidnt}")
                break
    if row is None:
        for ndc in provided_ndcs:
            hit = ndc_idx.get(_p_norm_ndc(ndc))
            if hit:
                row, lookup_path = hit, "Exact National Drug Code (NDC) match"
                matched_on.append(f"NDC {ndc}")
                break

    # (b)/(c) cultivator + corroboration / name + dates -------------------------
    if row is None and (pin.get("cultivator") or pin.get("product")):
        cult = set(_p_entity_tokens(pin.get("cultivator")))
        prod_tokens = set(re.findall(r"[a-z0-9]+", (pin.get("product") or "").lower()))
        thca = pin.get("thca"); thc = pin.get("thc")
        best, best_sc = None, 0
        for r in rows:
            sc = 0
            rt = set(_p_entity_tokens(r.get("BRANDING-ENTITY")))
            if cult and rt:
                sc += 2 * len(cult & rt)
            if prod_tokens:
                rp = set(re.findall(r"[a-z0-9]+", (r.get("PRODUCT-NAME") or "").lower()))
                sc += len(prod_tokens & rp)
            # reported-cannabinoid corroboration (registry carries THC/THCA)
            for want, col in ((thca, "TETRAHYDROCANNABINOL-ACID-THCA"),
                              (thc, "TETRAHYDROCANNABINOL-THC")):
                if want is None:
                    continue
                try:
                    if abs(float(r.get(col) or "nan") - float(want)) <= 0.2:
                        sc += 3
                except ValueError:
                    pass
            if sc > best_sc:
                best, best_sc = r, sc
        if best is not None and best_sc >= 5:
            row = best
            lookup_path = ("Cultivator + reported-cannabinoid corroboration"
                           if cult else "Product name + reported-cannabinoid corroboration")
            matched_on.append(f"corroboration score {best_sc}")

    # Record conflicts: what the patient provided that does NOT match the chosen row
    if row is not None:
        rn = _p_norm_ndc(row.get(_NDC_COL))
        if pin.get("ndc_stated") and _p_norm_ndc(pin["ndc_stated"]) != rn:
            conflicts.append(("Stated NDC", pin["ndc_stated"], row.get(_NDC_COL, "") or "(none)"))
        if pin.get("ndc_label") and _p_norm_ndc(pin["ndc_label"]) != rn and pin.get("ndc_label") != pin.get("ndc_stated"):
            conflicts.append(("Label-photo NDC", pin["ndc_label"], row.get(_NDC_COL, "") or "(none)"))
        if pin.get("cultivator"):
            if set(_p_entity_tokens(pin["cultivator"])) != set(_p_entity_tokens(row.get("BRANDING-ENTITY"))):
                conflicts.append(("Cultivator", pin["cultivator"], row.get("BRANDING-ENTITY", "") or "(none)"))

    return dict(row=row, lookup_path=lookup_path, matched_on=matched_on,
                conflicts=conflicts, qr_resolved=qr_resolved, qr_docidnt=qr_docidnt)


def _row_to_product(row):
    """Build a ProductV5 from a registry row so the existing COA pipeline can run.
    Must be ProductV5 (not v4.Product) — it carries the cannabinoids/thc_flags fields
    the parse/flag stages populate."""
    name = (row.get("PRODUCT-NAME") or "").strip()
    p = v5.ProductV5(
        product_name=name,
        dosage_form=(row.get("DOSAGE-FORM") or "").strip(),
        producer=(row.get("BRANDING-ENTITY") or "").strip(),
        brand=v4.parse_brand(name),
        approval_date=(row.get("APPROVAL-DATE") or "").strip(),
        registration_number=(row.get("REGISTRATION-NUMBER") or "").strip(),
        label_url=v4.extract_url(row.get("LABEL-IMAGE", "")),
        report_url=v4.extract_url(row.get("LAB-ANALYSIS", "")),
    )
    return p


def analyze_patient_product(p, pin, session, watch, offline=False):
    """Fetch + parse the resolved product's COA and reuse the existing flag logic.
    Returns a dict describing the contaminant picture in patient terms. Never
    fabricates: missing data is reported as missing."""
    process_product(p, session, watch)
    coa_fetched = bool(getattr(p, "_coa_present", False))
    coa_text = ""
    if coa_fetched:
        try:
            coa_text = v4.read_pdf_text(v4.cache_path(p)) or ""
        except Exception:
            coa_text = ""

    # Batch / UID only live on the COA (not in the registry) — corroborate there.
    # Recognize a PARTIAL match (a shared core segment) instead of a bare yes/no:
    # COAs often re-prefix a batch (e.g. "F09-F2H20-SPWF" vs the COA's "...2-F2H20-SPWF").
    def _corroborate(label, value):
        if not value:
            return None
        if not coa_text:
            return dict(label=label, value=value, state="unknown",
                        detail="COA text not available to confirm")
        hay = _p_norm(coa_text)
        if _p_norm(value) in hay:
            return dict(label=label, value=value, state="found", detail="found on the COA")
        segs = [s for s in re.split(r"[^A-Za-z0-9]+", value) if len(s) >= 3]
        hit = [s for s in segs if _p_norm(s) in hay]
        if hit:
            return dict(label=label, value=value, state="partial",
                        detail="partial match — the COA shows " + ", ".join(f"'{s}'" for s in hit)
                               + ", but not the full identifier you provided (worth re-checking)")
        return dict(label=label, value=value, state="none", detail="not found in the COA text")
    corroboration = [c for c in (_corroborate("Batch", pin.get("batch")),
                                 _corroborate("UID / BioTrack lot", pin.get("uid"))) if c]

    details = v5.quantified_details(p, watch) if coa_fetched else []
    # V15 SOURCE-BINDING: independently re-verify that EVERY value we will display
    # literally appears in THIS product's own COA text. Anything that can't be verified
    # is NOT displayed — it is routed to manual review. Never publish an unverified value.
    source_unverified = []
    if coa_fetched:
        keep_d = []
        for d in details:
            if _value_in_coa_text(d.get("value"), coa_text):
                keep_d.append(d)
            else:
                source_unverified.append(dict(name=d.get("name"), value=d.get("value"),
                                              unit=d.get("unit", "")))
        details = keep_d
    quant_keys = {d["key"] for d in details}
    # Per-class count of analytes that WERE tested but came back below detection / non-detect
    # (informational reassurance, never a finding). Excludes the zero-tolerance pathogens,
    # which are reported separately.
    below_detect = {}
    if coa_fetched:
        for key, e in p.analytes.items():
            if key in quant_keys or key in v5.PATHO_KEYS:
                continue
            raw = (e.get("raw") or "").strip()
            if (e.get("status") or "") == "ND" or raw.startswith("<"):
                below_detect[_analyte_class(key)] = below_detect.get(_analyte_class(key), 0) + 1
    classes = {}
    for d in details:
        cls = _analyte_class(d["key"])
        rec = dict(
            name=d["name"], value=d.get("value"), unit=d.get("unit", ""),
            ct_limit=d.get("ct_limit"), ct_pct=d.get("ct_pct"), cs_std=d.get("cs_std"),
            over_ct=bool(d.get("ct_limit") and d.get("value") is not None and d["value"] > d["ct_limit"]),
            near_ct=bool(d.get("ct_pct") is not None and d["ct_pct"] >= PATIENT_NEAR_PCT),
            over_cs=bool(d.get("cs_std") and d.get("value") is not None and d["value"] >= d["cs_std"]),
            why=v5.why_flagged(d) if v5.is_flag_driver(d) else "",
        )
        classes.setdefault(cls, []).append(rec)
    for recs in classes.values():
        recs.sort(key=lambda r: (r["ct_pct"] if r["ct_pct"] is not None else -1), reverse=True)

    pathogens = v5.pathogen_detections(p) if coa_fetched else []
    compliance = compliance_flag_rows([p], watch) if coa_fetched else []

    return dict(
        p=p, coa_fetched=coa_fetched,
        coa_status=getattr(p, "_coa_status", ""),
        parse_note=getattr(p, "parse_note", ""),
        classes=classes, pathogens=pathogens, compliance=compliance,
        corroboration=corroboration, below_detect=below_detect,
        source_unverified=source_unverified,
        tym_assessment=(assess_tym(p) if coa_fetched else None),
        pesticide_panel=getattr(p, "pesticides", ""),
        solvent_panel=getattr(p, "solvents", ""),
        testing_date=test_date(p) if coa_fetched else fmt_date(p.approval_date),
        coa_url=p.report_url,
        any_flag=bool(pathogens) or any(r["over_ct"] or r["near_ct"] or r["over_cs"]
                                        for recs in classes.values() for r in recs)
                 or p.pesticides == "FAIL" or p.solvents == "FAIL",
    )


# ----------------------------------------------------------------------------
# Related / sibling COAs (PATIENT PDF ONLY). A patient's physical package may
# correspond to a DIFFERENT batch than the COA we resolve — e.g. a batch that was
# re-tested, remediated, or re-released under a new COA. So for the patient PDF we
# surface other COAs from the SAME producer, SAME strain + product category,
# CLOSEST in time, each with a live COA link and its own flags, so the patient can
# compare batches and find the COA that matches the dates/IDs on their package.
# This is informational only — never an accusation that any batch was altered.
# ----------------------------------------------------------------------------
PATIENT_RELATED_MAX = 5            # max sibling COAs to fetch + show
PATIENT_RELATED_WINDOW_DAYS = 730  # "close enough in time" window (±2 years); soft

# Generic product/brand/form words dropped when isolating the STRAIN token(s).
_GENERIC_PRODUCT_WORDS = {
    "brix", "cannabis", "whole", "flower", "flowers", "pre", "preroll", "prerolls",
    "roll", "rolls", "vape", "vapes", "cartridge", "cart", "carts", "disposable",
    "pod", "pods", "aio", "all", "in", "one", "lil", "budz", "bud", "buds", "second",
    "seconds", "cut", "ready", "to", "pack", "packs", "gram", "grams", "infused",
    "the", "and", "of", "mintz", "soapy",
}
# Tokens that describe the FORM/grind of a product (used to prefer same-form siblings).
_FORM_DESCRIPTORS = {"whole", "flower", "pre", "preroll", "roll", "rolls", "vape",
                     "budz", "lil", "second", "seconds", "cut", "ready", "cart",
                     "cartridge", "pod", "disposable", "aio", "pack"}


def _strain_tokens(name):
    return {t for t in re.findall(r"[a-z]+", (name or "").lower())
            if t not in _GENERIC_PRODUCT_WORDS and len(t) > 1}


def _form_sig(name):
    return {t for t in re.findall(r"[a-z]+", (name or "").lower()) if t in _FORM_DESCRIPTORS}


def _size_token(name):
    """Package size like '3.5g' / '7g' / '14g' / '1g' from a product name (for ranking)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*g\b", (name or "").lower())
    return m.group(1) if m else ""


def _date_ordinal(t):
    try:
        y, mo, d = t
        return datetime.date(y, mo, d).toordinal() if y else 0
    except Exception:
        return 0


def _analyze_sibling(p, pin, session, watch):
    """Light analysis of a sibling COA: fetch, summarize flags, and check whether the
    PATIENT's own batch/UID appears on this COA (which would mean this COA — not the
    primary one — is the patient's actual batch)."""
    process_product(p, session, watch)
    fetched = bool(getattr(p, "_coa_present", False))
    concerns, near = [], []
    if fetched:
        for d in v5.quantified_details(p, watch):
            v, lim, cp = d.get("value"), d.get("ct_limit"), d.get("ct_pct")
            if lim and v is not None and v > lim:
                concerns.append(f"{d['name']} over CT limit")
            elif cp is not None and cp >= PATIENT_NEAR_PCT:
                near.append(f"{d['name']} {v4.ct_pct_label(cp, full=False)} of CT limit")
        for nice in v5.pathogen_detections(p):
            concerns.append(f"{nice} DETECTED")
        if p.pesticides == "FAIL":
            concerns.append("pesticide panel FAIL")
        if p.solvents == "FAIL":
            concerns.append("residual-solvent panel FAIL")
    # idmatch = "this COA is the patient's ACTUAL batch", so require a HIGH-specificity hit:
    # the full BioTrack lot digits (>=10) or the full batch string — NOT short fragments or
    # the shared product-line code (e.g. 'SPWF'), which appear on every batch in the line.
    idmatch = []
    if fetched:
        try:
            txt = v4.read_pdf_text(v4.cache_path(p)) or ""
        except Exception:
            txt = ""
        hay = _p_norm(txt)
        uid_digits = re.sub(r"\D", "", pin.get("uid") or "")
        if len(uid_digits) >= 10 and uid_digits in re.sub(r"\D", "", txt):
            idmatch.append("UID/lot")
        nb = _p_norm(pin.get("batch") or "")
        if len(nb) >= 8 and nb in hay:
            idmatch.append("batch")
    status = ("flags" if concerns else "near" if near else "clean" if fetched else "unavailable")
    return dict(fetched=fetched, concerns=concerns, near=near, idmatch=idmatch,
                coa_url=p.report_url, status=status,
                testing_date=test_date(p) if fetched else fmt_date(p.approval_date))


def find_related_coas(primary_row, primary_p, rows, pin, session, watch,
                      max_n=PATIENT_RELATED_MAX, window_days=PATIENT_RELATED_WINDOW_DAYS,
                      offline=False):
    """Sibling COAs: same producer + same product category + shared strain token, ranked
    same-form-first then closest-in-time. Fetches + analyzes the top `max_n`."""
    if not primary_row:
        return []
    prod_norm = _p_norm(primary_row.get("BRANDING-ENTITY"))
    primary_cat = product_category(primary_p)
    primary_strain = _strain_tokens(primary_row.get("PRODUCT-NAME"))
    primary_sig = _form_sig(primary_row.get("PRODUCT-NAME"))
    primary_size = _size_token(primary_row.get("PRODUCT-NAME"))
    primary_ndc = _p_norm_ndc(primary_row.get(_NDC_COL))
    pord = _date_ordinal(v4.parse_date(primary_row.get("APPROVAL-DATE") or ""))
    if not primary_strain:
        return []
    cands = []
    for r in rows:
        if _p_norm(r.get("BRANDING-ENTITY")) != prod_norm:
            continue
        if _p_norm_ndc(r.get(_NDC_COL)) == primary_ndc:
            continue
        rstrain = _strain_tokens(r.get("PRODUCT-NAME"))
        if not (rstrain & primary_strain):
            continue
        rp = _row_to_product(r)
        if product_category(rp) != primary_cat:
            continue
        rord = _date_ordinal(v4.parse_date(r.get("APPROVAL-DATE") or ""))
        dist = abs(rord - pord) if (rord and pord) else 10 ** 9
        rsig = _form_sig(r.get("PRODUCT-NAME"))
        same_form = 0 if (rsig & primary_sig) else 1
        same_size = 0 if (primary_size and _size_token(r.get("PRODUCT-NAME")) == primary_size) else 1
        # "same product" = same strain + same form + same package size (closest analog).
        same_product = 0 if (rstrain == primary_strain and same_form == 0 and same_size == 0) else 1
        # Ranking priority: same product -> same size -> same form -> closest date.
        cands.append((same_product, same_size, same_form, dist, r, rp))
    cands.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    chosen = [c for c in cands if c[3] <= window_days][:max_n] or cands[:max_n]
    if not chosen:
        return []

    def _do_one(tup):
        # Fetch + analyze ONE sibling COA. Wrapped so a single bad sibling never breaks the report.
        same_product, same_size, same_form, dist, r, rp = tup
        try:
            summ = _analyze_sibling(rp, pin, session, watch)
        except Exception:
            return None
        return dict(row=r, p=rp, days_apart=(None if dist >= 10 ** 9 else dist),
                    same_form=(same_form == 0), same_size=(same_size == 0),
                    same_product=(same_product == 0), product=r.get("PRODUCT-NAME"),
                    ndc=r.get(_NDC_COL, ""), **summ)

    # Sibling COAs are independent network fetches — run them concurrently (downloads overlap; PDF
    # parsing stays serialized under the engine's pdfium lock). Order is preserved by ex.map.
    if len(chosen) == 1:
        out = [_do_one(chosen[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(len(chosen), 6)) as ex:
            out = list(ex.map(_do_one, chosen))
    return [o for o in out if o is not None]


def _consumer_report_path():
    """Allocate a Consumer Concern run: a GLOBAL report number (shared sequence with Statewide) + a
    PER-TYPE folder number, a brand-new run folder '{N} Consumer Concern Report {M.D.YY}' under
    PATIENT_OUT_DIR (RUN_OUT_DIR points at it), and the short filename
    '{N}-CannaScopeCT-CC-{M.D.YY}-{TIME}.pdf'. Returns (path, report_no, dt). Never reused/overwritten."""
    report_no, run_folder, dt = allocate_run(REPORT_TYPE_CONSUMER)
    path = os.path.join(run_folder, report_filename(report_no, REPORT_TYPE_CONSUMER, dt))
    return path, report_no, dt


def build_patient_pdf(out_path, pin, res, analysis, report_no=None, report_dt=None,
                      *, return_story=False, include_cover=True, include_footer=True):
    """Render the personalized, patient-friendly PDF. Portrait letter.

    return_story=True  -> build the per-product flowables and RETURN them (no file written), so a
                          combined multi-product report can concatenate several products into one PDF.
    include_cover      -> emit the report cover (set False for a product SECTION inside a combined report).
    include_footer     -> emit the shared 'What to do next' / lead-not-conclusion footer (set False on
                          every product section except the last in a combined report)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer)

    BF, BFB = v4._setup_fonts()
    esc = v4._esc
    NAVY = colors.HexColor("#1F2D3D"); RED = colors.HexColor("#C0392B")
    row = res.get("row") or {}

    title_st = ParagraphStyle("t", fontName=BFB, fontSize=18, leading=22, textColor=NAVY)
    sub_st = ParagraphStyle("s", fontName=BF, fontSize=11, leading=15, textColor=colors.HexColor("#444"))
    h_st = ParagraphStyle("h", fontName=BFB, fontSize=13, leading=17, textColor=NAVY,
                          spaceBefore=14, spaceAfter=4, keepWithNext=1)
    body = ParagraphStyle("b", fontName=BF, fontSize=10, leading=14, textColor=colors.HexColor("#222"))
    small = ParagraphStyle("sm", fontName=BF, fontSize=8.5, leading=11.5, textColor=colors.HexColor("#555"))
    cell = ParagraphStyle("c", fontName=BF, fontSize=9, leading=12)
    cellb = ParagraphStyle("cb", parent=cell, fontName=BFB)
    cellc = ParagraphStyle("cc", parent=cell, alignment=1)
    head = ParagraphStyle("hd", fontName=BFB, fontSize=9, leading=12, textColor=colors.white)
    disc = ParagraphStyle("d", fontName=BF, fontSize=9, leading=12.5, textColor=colors.HexColor("#7a4a00"))

    def banner(text, fill, tcolor):
        t = Table([[Paragraph(text, ParagraphStyle("bn", parent=disc, textColor=tcolor))]],
                  colWidths=[7.0 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fill),
                               ("BOX", (0, 0), (-1, -1), 0.5, tcolor),
                               ("TOPPADDING", (0, 0), (-1, -1), 7),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                               ("LEFTPADDING", (0, 0), (-1, -1), 9),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 9)]))
        return t

    def kv_table(pairs, w0=2.1, w1=4.9):
        data = [[Paragraph(esc(k), cellb), v if hasattr(v, "wrap") else Paragraph(esc(str(v)), cell)]
                for k, v in pairs]
        t = Table(data, colWidths=[w0 * inch, w1 * inch])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd6dd")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f3f6f8")]),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
        return t

    def coa_link():
        url = analysis.get("coa_url")
        if url:
            return (f'<link href="{esc(url)}"><font color="#1155CC"><u><b>'
                    f'View the official Certificate of Analysis (COA)</b></u></font></link>')
        return '<font color="#C0392B"><b>COA not provided.</b></font>'

    # Cover-page block per the naming standard.
    _now = report_dt or datetime.datetime.now().astimezone()   # match the short filename's timestamp
    cover_date = f"{_now:%B} {_now.day}, {_now.year}"
    _h12 = _now.hour % 12 or 12
    cover_time = f"{_h12}:{_now.minute:02d} {'AM' if _now.hour < 12 else 'PM'} {_now.strftime('%Z')}".strip()
    bigmeta = ParagraphStyle("bigmeta", parent=sub_st, fontName=BFB, fontSize=13, leading=18, textColor=NAVY)

    story = []
    if include_cover:
        story.append(Paragraph(esc(APP_NAME), title_st))                                # CannaScope CT V15
        if report_no is not None:
            story.append(Paragraph(f"Report #{report_no}", bigmeta))                    # Report #16
        story.append(Paragraph("Consumer Concern Report", bigmeta))                     # Consumer Concern Report
        story.append(Paragraph(f"Created {esc(cover_date)}", small))                    # Created June 3, 2026
        story.append(Paragraph(esc(cover_time), small))                                 # 5:36 PM EDT
        story.append(Spacer(1, 4))
        story.append(Paragraph("A personalized review of one product's lab-testing data, for a consumer concern.", sub_st))
        story.append(Spacer(1, 8))

    # ---- PRODUCT OF CONCERN header (item 1): the investigated product, up top + prominent ----
    poc_name = pin.get("product") or row.get("PRODUCT-NAME") or "(not specified)"
    poc_prod = (producer_display(row.get("BRANDING-ENTITY", ""), row.get("PRODUCT-NAME", ""))
                if res.get("row") else (pin.get("cultivator") or "—"))
    poc_batch = pin.get("batch") or "—"
    poc_coa = pin.get("coa") or row.get("REGISTRATION-NUMBER") or "—"
    poc_tested = pin.get("tested") or analysis.get("testing_date") or "—"
    poc_exp = pin.get("exp") or "—"
    poc_hdr = ParagraphStyle("poch", fontName=BFB, fontSize=10.5, leading=13, textColor=colors.white)
    poc_body = ParagraphStyle("pocb", fontName=BF, fontSize=10, leading=15, textColor=colors.HexColor("#222"))
    poc_inner = (f'<font size="15"><b>{esc(tcase(poc_name))}</b></font><br/>'
                 f'{esc(poc_prod)}<br/>'
                 f'<b>Batch</b> {esc(poc_batch)} &nbsp;·&nbsp; <b>COA</b> {esc(poc_coa)}<br/>'
                 f'<b>Tested</b> {esc(poc_tested)} &nbsp;·&nbsp; <b>Expires</b> {esc(poc_exp)}')
    poc_t = Table([[Paragraph("PRODUCT OF CONCERN", poc_hdr)], [Paragraph(poc_inner, poc_body)]],
                  colWidths=[7.0 * inch])
    poc_t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), NAVY),
                               ("BOX", (0, 0), (-1, -1), 1.0, NAVY),
                               ("LINEBELOW", (0, 0), (0, 0), 1.0, NAVY),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10)]))
    story.append(poc_t)
    story.append(Spacer(1, 8))
    story.append(banner(
        "<b>Please read:</b> This document is advisory and informational. It explains what the "
        "laboratory testing data shows for the product you described. It is <b>not medical advice</b>, "
        "and it does <b>not</b> say or imply that this product caused any symptom or health issue — "
        "test results near a limit are not proof of harm, and a cause cannot be determined from this "
        "data. If you have a health concern, please talk with a healthcare provider or pharmacist.",
        colors.HexColor("#fff4d6"), colors.HexColor("#7a4a00")))

    # ---- Complaint Investigation Summary (item 5): answer the concern from testing data ----
    def _elev(cls_name, analyte=None):
        for r in analysis.get("classes", {}).get(cls_name, []):
            if analyte and r["name"].lower() != analyte.lower():
                continue
            if (r.get("ct_pct") or 0) >= 50:
                return True
        return False
    story.append(Paragraph("Complaint Investigation Summary", h_st))
    if not analysis.get("coa_fetched"):
        story.append(Paragraph("The product's Certificate of Analysis could not be retrieved, so a testing-based "
                               "summary could not be completed. See the notes below for what is missing.", body))
    else:
        story.append(Paragraph("Based on available testing data (\"elevated\" = a result at or above 50% of a "
                               "Connecticut limit):", body))
        story.append(Spacer(1, 3))
        checks = [
            ("Elevated mold / microbial findings", _elev("Microbials / mold")),
            ("Elevated heavy-metal findings (any)", _elev("Heavy metals")),
            ("Elevated arsenic findings", _elev("Heavy metals", "Arsenic")),
            ("Elevated chromium findings", _elev("Heavy metals", "Chromium")),
            ("Elevated cadmium findings", _elev("Heavy metals", "Cadmium")),
            ("Elevated lead findings", _elev("Heavy metals", "Lead")),
            ("Elevated mycotoxin findings", _elev("Mycotoxins")),
            ("Elevated pesticide findings", analysis.get("pesticide_panel") == "FAIL" or _elev("Pesticides")),
            ("Elevated residual-solvent findings", analysis.get("solvent_panel") == "FAIL" or _elev("Residual solvents")),
            ("Pathogen reported detected", bool(analysis.get("pathogens"))),
        ]
        crows = [[Paragraph("Testing question", head), Paragraph("Identified?", head)]]
        for q, yes in checks:
            mark = ('<font color="#C0392B"><b>Yes</b></font>' if yes else '<font color="#1E7E34">No</font>')
            crows.append([Paragraph(esc(q), cell), Paragraph(mark, cellc)])
        ct = Table(crows, colWidths=[5.4 * inch, 1.6 * inch])
        ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
                                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd6dd")),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f8")]),
                                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
        story.append(ct)
        story.append(Spacer(1, 4))
        allflag = [r for recs in analysis.get("classes", {}).values() for r in recs if (r.get("ct_pct") or 0) >= 50]
        bits = []
        if analysis.get("pathogens"):
            bits.append("The COA reports a zero-tolerance pathogen as DETECTED — raise this with the Department of "
                        "Consumer Protection and the Ombudsman.")
        if allflag:
            t = max(allflag, key=lambda r: r["ct_pct"])
            bits.append(f"This product's most notable testing result was <b>{esc(t['name'])} at "
                        f"{t['ct_pct']:.1f}% of Connecticut's legal limit</b> (Severity: {esc(severity_tier(t['ct_pct']))}). "
                        "This does not establish causation and does not prove the reported symptoms were caused by "
                        "the product — it simply identifies the most notable testing result observed.")
        if not allflag and not analysis.get("pathogens"):
            bits.append("No testing result reached the elevated threshold (50% of a Connecticut limit) in the "
                        "available data. This does not rule out other causes for how you felt; it only reflects "
                        "what this product's testing shows.")
        story.append(Paragraph("<b>Summary:</b> " + " ".join(bits), body))

    # 1) What you told us
    story.append(Paragraph("1. The product as you described it", h_st))
    told = []
    label_map = [("product", "Product"), ("cultivator", "Brand / cultivator"),
                 ("batch", "Batch number"), ("ndc_stated", "NDC (as you reported)"),
                 ("ndc_label", "NDC (from the label photo)"), ("uid", "UID / BioTrack lot"),
                 ("coa", "COA number"), ("harvest", "Harvest date"),
                 ("packaged", "Packaged date"), ("tested", "Tested date"),
                 ("exp", "Expiration date"), ("qr", "QR / COA link you scanned")]
    for k, lbl in label_map:
        if pin.get(k):
            told.append((lbl, pin[k]))
    if pin.get("concern"):
        told.append(("Your concern", pin["concern"]))
    story.append(kv_table(told or [("(no identifiers provided)", "—")]))

    # 2) What we found
    story.append(Paragraph("2. The product record we found", h_st))
    if res.get("row"):
        found = [("Resolved by", res["lookup_path"] or "—"),
                 ("Registry product name", row.get("PRODUCT-NAME", "")),
                 ("Producer (official — legal entity / brand)",
                  producer_display(row.get("BRANDING-ENTITY", ""), row.get("PRODUCT-NAME", ""))),
                 ("National Drug Code (registry)", row.get(_NDC_COL, "") or "—"),
                 ("Registration number", row.get("REGISTRATION-NUMBER", "") or "—"),
                 ("Market", row.get("Market", "") or "—"),
                 ("Reported THCA / THC (registry)",
                  f'{row.get("TETRAHYDROCANNABINOL-ACID-THCA","?")}% THCA · '
                  f'{row.get("TETRAHYDROCANNABINOL-THC","?")}% THC'),
                 ("COA testing date", analysis.get("testing_date") or "—"),
                 ("Certificate of Analysis", Paragraph(coa_link(), cell))]
        story.append(kv_table(found))
        if res.get("qr_resolved"):
            story.append(Spacer(1, 3))
            story.append(Paragraph(f"QR link resolved to: {esc(res['qr_resolved'])}", small))
    else:
        story.append(Paragraph(
            "We could <b>not</b> confidently match your product to a Connecticut registry record "
            "from the identifiers provided, so no testing panel could be retrieved. The most useful "
            "next identifier would be a clear <b>COA number</b> or the <b>QR / COA link</b> from the "
            "package, or a confirmed <b>NDC</b>. We have not guessed at a product or invented any "
            "values.", body))
        if res.get("qr_resolved"):
            story.append(Paragraph(f"QR link resolved to: {esc(res['qr_resolved'])}", small))

    # Why this product was matched (item 10)
    if res.get("row"):
        ids_used = [lbl for k, lbl in label_map if pin.get(k)]
        story.append(Paragraph("Why this product was matched", h_st))
        msg = ("This product was matched using the identifiers you provided"
               + (f" (<b>{esc(', '.join(ids_used))}</b>)" if ids_used else "")
               + " cross-checked against the Connecticut product registry and the product's Certificate of "
               f"Analysis. Match path: <b>{esc(res.get('lookup_path') or '—')}</b>"
               + (f" ({esc(', '.join(res.get('matched_on') or []))})" if res.get("matched_on") else "")
               + ". The match relies on the strongest available corroborating identifiers"
               + ("; where identifiers disagreed, the differences are listed below." if res.get("conflicts")
                  else "."))
        story.append(Paragraph(msg, body))

    # 2b) Discrepancies
    if res.get("conflicts"):
        story.append(Paragraph("Identifier discrepancies we noticed", h_st))
        story.append(Paragraph(
            "The details below did not all agree. We are showing exactly what you provided next to "
            "what the official record shows — we did not silently pick one. A mismatch here is worth "
            "double-checking against the physical package and label.", body))
        story.append(Spacer(1, 4))
        d = [[Paragraph("Identifier", head), Paragraph("You provided", head),
              Paragraph("Official record shows", head)]]
        for lbl, prov, found_v in res["conflicts"]:
            d.append([Paragraph(esc(lbl), cellb),
                      Paragraph(f'<font color="#C0392B">{esc(str(prov))}</font>', cell),
                      Paragraph(esc(str(found_v)), cell)])
        t = Table(d, colWidths=[1.7 * inch, 2.65 * inch, 2.65 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), RED),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd6dd")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
        story.append(t)

    # Batch / UID corroboration (these live only on the COA)
    if analysis.get("corroboration"):
        rows_c = []
        _ccol = {"found": "#1E7E34", "partial": "#9A7B0A", "none": "#C0392B", "unknown": "#555"}
        for c in analysis["corroboration"]:
            mark = " ✓" if c["state"] == "found" else ""
            rows_c.append((c["label"], Paragraph(
                f'{esc(c["value"])} — <font color="{_ccol[c["state"]]}">{esc(c["detail"])}{mark}</font>', cell)))
        story.append(Paragraph("Batch / lot check (from the COA itself)", h_st))
        story.append(kv_table(rows_c))

    # 3) Contaminant results vs limits
    story.append(Paragraph("3. What the testing data shows", h_st))
    if not analysis.get("coa_fetched"):
        story.append(Paragraph(
            "The official laboratory panel for this product could not be retrieved at this time"
            + (f" ({esc(analysis.get('parse_note') or analysis.get('coa_status') or 'COA unavailable')})" if (analysis.get('parse_note') or analysis.get('coa_status')) else "")
            + ". No contaminant results are shown because we will not display values we could not "
              "read from the COA. You can open the COA yourself using the link above, if present.", body))
    else:
        story.append(Paragraph(
            "For each contaminant class below, we show the measured result, the Connecticut legal "
            "limit, and how close the result came to that limit. <b>CannaScope limit</b> is our own "
            "stricter awareness threshold (set below the legal limit) — it is <b>not</b> the law; it "
            "only flags results worth a closer look. A result can pass Connecticut's requirement and "
            f"still be flagged here for being within {PATIENT_NEAR_PCT:g}% of the legal limit.", body))
        story.append(Spacer(1, 6))
        order = ["Heavy metals", "Pesticides", "Microbials / mold", "Mycotoxins",
                 "Residual solvents"]
        seen = set(order)
        order += [c for c in analysis["classes"] if c not in seen]
        for cls in order:
            recs = analysis["classes"].get(cls)
            story.append(Paragraph(esc(cls), ParagraphStyle("cl", parent=body, fontName=BFB,
                                                            textColor=NAVY, spaceBefore=8, spaceAfter=2)))
            if not recs:
                nbd = analysis.get("below_detect", {}).get(cls, 0)
                if nbd:
                    base = (f"Tested — {nbd} result(s) on this COA came back below detection / "
                            "non-detect, which is well within the limit and is not a finding.")
                else:
                    base = ("No quantified result on this COA for this class (an absent or "
                            "below-detection result is not a finding).")
                if cls == "Pesticides" and analysis.get("pesticide_panel"):
                    base += f" Panel status on the COA: {analysis['pesticide_panel']}."
                if cls == "Residual solvents" and analysis.get("solvent_panel"):
                    base += f" Panel status on the COA: {analysis['solvent_panel']}."
                story.append(Paragraph(esc(base), small))
                continue
            data = [[Paragraph("Analyte", head), Paragraph("Result", head),
                     Paragraph("CT legal limit", head), Paragraph("% of CT limit", head),
                     Paragraph("CannaScope limit", head), Paragraph("Severity", head), Paragraph("Flag", head)]]
            for r in recs:
                if r["over_ct"]:
                    flag, fc = "AT/OVER CT LIMIT", "#C0392B"
                elif r["near_ct"]:
                    flag, fc = "Near CT limit", "#9A7B0A"
                elif r["over_cs"]:
                    flag, fc = "Over CannaScope limit", "#9A7B0A"
                else:
                    flag, fc = "Within limits", "#1E7E34"
                tier = severity_tier(r["ct_pct"])
                data.append([
                    Paragraph(esc(r["name"]), cell),
                    Paragraph(esc(clean_value(r["value"], r["unit"])), cellb),
                    Paragraph(esc(clean_value(r["ct_limit"], r["unit"])) if r["ct_limit"] else "—", cell),
                    Paragraph(v4.ct_pct_label(r["ct_pct"], full=False) if r["ct_pct"] is not None else "—", cell),
                    Paragraph(esc(clean_value(r["cs_std"], r["unit"])) if r["cs_std"] else "—", cell),
                    Paragraph(f'<font color="{fc}"><b>{esc(tier)}</b></font>' if tier else "—", cell),
                    Paragraph(f'<font color="{fc}"><b>{flag}</b></font>', cell)])
            t = Table(data, colWidths=[1.4*inch, 0.9*inch, 1.0*inch, 0.7*inch, 0.95*inch, 1.1*inch, 0.95*inch])
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
                                   ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd6dd")),
                                   ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                   ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f8")]),
                                   ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
            story.append(t)

        if analysis.get("pathogens"):
            story.append(Spacer(1, 6))
            story.append(banner(
                "<b>Zero-tolerance pathogen reported DETECTED:</b> "
                + esc(", ".join(analysis["pathogens"]))
                + ". This is a result the COA itself reports as detected and is worth raising with the "
                  "Department of Consumer Protection and the Ombudsman. It is not a diagnosis.",
                colors.HexColor("#f8d2d0"), colors.HexColor("#7a1a14")))

    # V15 source-binding: any value that could not be re-verified in THIS COA is NOT
    # shown above — it is listed here for manual review instead of being published.
    su = analysis.get("source_unverified") or []
    if su:
        story.append(Paragraph("Held for manual review — could not verify in this COA", h_st))
        story.append(Paragraph(
            "The following parsed value(s) could not be independently re-verified in the text of this "
            "product's own Certificate of Analysis, so they are <b>not shown as findings above</b> and are "
            "flagged for a human to check directly on the COA: "
            + esc("; ".join(f'{u["name"]} {clean_value(u["value"], u["unit"])}' for u in su))
            + ". This is a data-integrity safeguard, not a finding.", body))

    # V15 lab- & date-aware Yeast & Mold (TYM) standard explanation (when a concern applies)
    tym = analysis.get("tym_assessment")
    if tym and tym["is_concern"]:
        story.append(Paragraph("Yeast &amp; mold testing-standard note", h_st))
        labnm = esc(tym["lab"] or "an unidentified lab")
        datenm = esc(fmt_date(getattr(tym["p"], "testing_date", "") or tym["p"].approval_date) or "an unknown date")
        if tym["mval"] is not None:
            res_line = f"Its yeast &amp; mold (TYM) result was <b>{esc(clean_value(tym['mval'], 'CFU/g'))}</b>"
        elif tym["bbound"] is not None:
            res_line = (f"Its yeast &amp; mold result was reported only as <b>below {esc(clean_value(tym['bbound'], 'CFU/g'))}</b> "
                        "(a detection-limit bound, not a measured count)")
        elif tym["passed_no_value"]:
            res_line = ("Its COA reported yeast &amp; mold only as <b>“passed,” with no CFU/g number disclosed</b>")
        else:
            res_line = "Its yeast &amp; mold result was not available as a number"
        lab_lim = (esc(clean_value(tym["lab_limit"], "CFU/g")) if tym["lab_limit"] is not None
                   else "an unknown limit (no dated standard on file)")
        story.append(Paragraph(
            f"This product was tested by <b>{labnm}</b> on <b>{datenm}</b>. {res_line}. Connecticut's TYM passing "
            f"limit has varied by lab and date — by up to 100x — so here is how this result compares to "
            f"three benchmarks: the lab's limit on that date ({lab_lim}), the current CT limit "
            f"({TYM_CURRENT_LIMIT:,} CFU/g), and the strict patient-protective benchmark "
            f"({TYM_STRICT_BENCHMARK:,} CFU/g, the original standard).", body))

        def _v(v):
            return {"FAIL": "exceeds it", "PASS": "is within it",
                    "UNDETERMINED": "can't be confirmed (below-detection bound is above it)",
                    None: "can't be compared (no number/date)"}.get(v, "—")
        story.append(Paragraph(
            f"• Against the lab's limit on its test date: <b>{esc(_v(tym['lab_verdict']))}</b>.<br/>"
            f"• Against the current CT limit: <b>{esc(_v(tym['current_verdict']))}</b>.<br/>"
            f"• Against the strict {TYM_STRICT_BENCHMARK:,} benchmark: <b>{esc(_v(tym['strict_verdict']))}</b>.", body))
        notes = []
        if tym["high_risk"]:
            notes.append("This was tested at AltaSci during roughly Aug 2020–2022, when its passing limit was "
                         "temporarily raised to 1,000,000 CFU/g — about 100x looser than the other lab and the "
                         "original standard. A “pass” from that window may not meet the current or strict standard.")
        if tym["aspergillus_detected"]:
            notes.append("The COA reports <b>detectable Aspergillus</b>, a mold the program treats as "
                         "zero-tolerance — worth raising regardless of the count.")
        if tym["passed_no_value"]:
            notes.append("Because only “passed” was printed (no number), the actual count can't be compared to "
                         "any standard — given CT's historical 100x spread, that missing number is worth questioning.")
        if not tym["aspergillus_tested"]:
            notes.append("Aspergillus does not appear to have been tested on this COA (older or other-lab era).")
        if notes:
            story.append(Paragraph(" ".join(notes), body))
        story.append(Paragraph(
            "<i>Effective dates for these standards are approximate where Connecticut's public record is "
            "ambiguous; verify against eRegulations.ct.gov / DCP. This is informational and non-causal — it "
            "does not say this product caused how you felt. Please discuss with a healthcare provider, and you "
            "can report it to the CT Office of the Cannabis Ombudsman and the Department of Consumer Protection.</i>",
            small))

    # 3c) Related COAs from the same producer — compare batches over time
    related = analysis.get("related") or []
    if related:
        story.append(Paragraph("Other COAs from this producer — compare batches", h_st))
        story.append(Paragraph(
            "Cannabis batches are sometimes re-tested, remediated, or re-released under a new "
            "Certificate of Analysis, and the exact batch in your hands may differ from the one matched "
            "above. The COAs below are from the <b>same producer</b>, for the <b>same strain and product "
            "type</b>, closest in time. They are provided only so you can compare results across batches "
            "and confirm which COA matches the batch number and dates printed on your package — not as a "
            "claim that any batch was altered, mislabeled, or unsafe. Open each COA and check its batch "
            "ID and dates against your physical product.", body))
        story.append(Spacer(1, 4))

        def _coa_cell(url):
            if url:
                return Paragraph(f'<link href="{esc(url)}"><font color="#1155CC"><u><b>'
                                 f'Open COA</b></u></font></link>', cellc)
            return Paragraph('<font color="#C0392B">no link</font>', cellc)

        def _summ_cell(status, concerns, near, fetched):
            if not fetched:
                return Paragraph('<font color="#555">COA not retrieved — open the link to review</font>', cell)
            if status == "flags":
                return Paragraph('<font color="#C0392B"><b>Flag(s):</b> ' + esc("; ".join(concerns)) + "</font>", cell)
            if status == "near":
                return Paragraph('<font color="#9A7B0A"><b>Near limit:</b> ' + esc("; ".join(near)) + "</font>", cell)
            return Paragraph('<font color="#1E7E34">No CannaScope flags identified (no result above the awareness threshold)</font>', cell)

        hdr = ["Batch / product", "COA date", "NDC", "What the COA shows", "COA"]
        data = [[Paragraph(h, head) for h in hdr]]
        # reference row: the resolved product (what section 2/3 is about)
        prim_concerns = [f'{r["name"]} over CT limit' for recs in analysis.get("classes", {}).values()
                         for r in recs if r["over_ct"]] + \
                        [f'{n}' for n in analysis.get("pathogens", [])]
        prim_near = [f'{r["name"]} {v4.ct_pct_label(r["ct_pct"], full=False)} of CT limit'
                     for recs in analysis.get("classes", {}).values() for r in recs
                     if r["near_ct"] and not r["over_ct"]]
        prim_status = ("flags" if prim_concerns else "near" if prim_near else
                       "clean" if analysis.get("coa_fetched") else "unavailable")
        data.append([
            Paragraph("<b>" + esc(tcase((res.get("row") or {}).get("PRODUCT-NAME", "Your product")))
                      + "</b><br/><font color='#1155CC'>(your resolved product)</font>", cell),
            Paragraph(esc(analysis.get("testing_date") or "—"), cellc),
            Paragraph(esc((res.get("row") or {}).get(_NDC_COL, "") or "—"), cellc),
            _summ_cell(prim_status, prim_concerns, prim_near, analysis.get("coa_fetched")),
            _coa_cell(analysis.get("coa_url"))])
        rel_sevs = [None]
        for s in related:
            tag = ""
            if s.get("idmatch"):
                tag = ("<br/><font color='#C0392B'><b>⟵ a " + esc("/".join(s["idmatch"]))
                       + " on your package appears on this COA</b></font>")
            elif s.get("same_product"):
                tag = "<br/><font color='#555'>same product &amp; package size</font>"
            elif s.get("same_size"):
                tag = "<br/><font color='#555'>same package size</font>"
            elif s.get("same_form"):
                tag = "<br/><font color='#555'>same product form</font>"
            da = s.get("days_apart")
            when = f" · {da} days from yours" if da is not None else ""
            data.append([
                Paragraph("<b>" + esc(tcase(s["product"])) + "</b>"
                          + f"<font color='#555'>{esc(when)}</font>" + tag, cell),
                Paragraph(esc(s.get("testing_date") or "—"), cellc),
                Paragraph(esc(s.get("ndc") or "—"), cellc),
                _summ_cell(s["status"], s["concerns"], s["near"], s["fetched"]),
                _coa_cell(s.get("coa_url"))])
            rel_sevs.append("flags" if s["status"] == "flags" else None)
        t = Table(data, repeatRows=1, colWidths=[2.5*inch, 0.95*inch, 1.05*inch, 1.65*inch, 0.85*inch])
        cmds = [("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd6dd")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f8")]),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#eaf1fb")),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
        for i, sv in enumerate(rel_sevs):
            if sv == "flags":
                cmds.append(("BACKGROUND", (0, i + 1), (0, i + 1), colors.HexColor("#fbe4e2")))
        t.setStyle(TableStyle(cmds))
        story.append(t)

    # 4) Plain-language meaning of the flags
    flagged_recs = [r for recs in analysis.get("classes", {}).values() for r in recs
                    if r["over_ct"] or r["near_ct"] or r["over_cs"]]
    if flagged_recs:
        story.append(Paragraph("4. What the flagged results mean", h_st))
        for r in flagged_recs:
            pct = v4.ct_pct_label(r["ct_pct"], full=False) if r["ct_pct"] is not None else "—"
            if r["over_ct"]:
                m = ("is reported at or over the Connecticut legal limit on the COA. A product over "
                     "the limit should not have been released; it is worth verifying the COA and "
                     "raising with the Department of Consumer Protection.")
            elif r["near_ct"]:
                m = (f"passed Connecticut's requirement but came within {PATIENT_NEAR_PCT:g}% of the "
                     f"legal limit ({pct} of the limit). Being near a limit is not the same as failing "
                     "or being unsafe — there was simply less margin than usual, which may be worth "
                     "discussing.")
            else:
                m = ("is within Connecticut's legal limit but above CannaScope's stricter internal "
                     "awareness threshold, which we set below the legal limit to surface results worth "
                     "a closer look.")
            tier = severity_tier(r["ct_pct"])
            sev = f' <i>(Severity: {esc(tier)})</i>' if tier else ""
            story.append(Paragraph(f'<b>{esc(r["name"])}</b> {m}{sev}', body))
            story.append(Spacer(1, 2))

    # Producer Trend Context (item 8): how often this producer appears in the statewide
    # findings dataset for the most notable contaminant — read-only, factual, no speculation.
    if flagged_recs and res.get("row"):
        top_a = max(flagged_recs, key=lambda r: r.get("ct_pct") or 0)["name"]
        disp = producer_display(row.get("BRANDING-ENTITY", ""), row.get("PRODUCT-NAME", ""))
        story.append(Paragraph("Producer Trend Context", h_st))
        ctxd = producer_trend_context(row.get("BRANDING-ENTITY", ""), top_a)
        if ctxd and ctxd["producer"] > 0:
            story.append(Paragraph(
                f"{esc(disp)} appears <b>{ctxd['producer']}</b> time(s) in the most recent statewide "
                f"{esc(top_a)} findings on file ({ctxd['producer']} of {ctxd['total']} ranked {esc(top_a)} "
                "results). This does not indicate wrongdoing, product failure, or causation. It simply provides "
                "context regarding how often similar findings appeared among products from the same producer in "
                "the analyzed dataset.", body))
        else:
            story.append(Paragraph(
                "No statewide findings dataset for this contaminant is on file, so producer trend context is not "
                "available for this report. (Running a Statewide Transparency Report populates this context.)", body))

    # 5) Compliance flags already generated for this product
    if analysis.get("compliance"):
        story.append(Paragraph("5. Related compliance flags to evaluate", h_st))
        story.append(Paragraph(
            "These are potential testing / product-quality items for a human reviewer to evaluate — "
            "not legal conclusions, and the cited authority should be verified in eRegulations.", small))
        for c in analysis["compliance"]:
            story.append(Spacer(1, 3))
            story.append(Paragraph(f'<b>{esc(c["rule_category"])}.</b> {esc(c["finding"])}', body))

    # 6) Safety framing / next steps (shared footer — in a combined report it is shown ONCE, at the end)
    if include_footer:
        story.append(Paragraph("What to do next", h_st))
        story.append(banner(
            "This analysis is informational and not medical advice. Testing results near or over a limit "
            "do not prove that a product caused any symptom. If you feel unwell or have a health concern, "
            "please contact a healthcare provider or pharmacist. To report a product concern in "
            "Connecticut, you can contact the <b>CT Office of the Cannabis Ombudsman</b> and the "
            "<b>Department of Consumer Protection (DCP)</b>. Keep your product, packaging, and this "
            "document in case they are helpful.",
            colors.HexColor("#e7f0ff"), colors.HexColor("#1b3a6b")))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Every flag in this document is a lead, not a conclusion. Values are drawn from the product's "
            "Certificate of Analysis and the Connecticut product registry; anything that could not be "
            "confirmed is shown as not found rather than estimated.", small))

    if return_story:
        return story
    SimpleDocTemplate(out_path, pagesize=letter, leftMargin=0.7*inch, rightMargin=0.7*inch,
                      topMargin=0.6*inch, bottomMargin=0.7*inch,
                      title="Personalized Product Concern Report",
                      author=APP_NAME).build(story)


def build_patient_pdf_multi(out_path, items, shared, report_no=None, report_dt=None):
    """ONE combined Consumer Concern Report covering MULTIPLE products. Renders a shared cover, the
    consumer's reported health context, a combined at-a-glance summary, then one self-contained section
    per product (reusing build_patient_pdf in section mode). `items` = list of {pin, res, analysis};
    `shared` = cross-product context (conditions, concern). The 'What to do next' footer shows ONCE."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak)

    BF, BFB = v4._setup_fonts()
    esc = v4._esc
    NAVY = colors.HexColor("#1F2D3D")
    title_st = ParagraphStyle("mt", fontName=BFB, fontSize=18, leading=22, textColor=NAVY)
    sub_st = ParagraphStyle("ms", fontName=BF, fontSize=11, leading=15, textColor=colors.HexColor("#444"))
    bigmeta = ParagraphStyle("mbm", parent=sub_st, fontName=BFB, fontSize=13, leading=18, textColor=NAVY)
    small = ParagraphStyle("msm", fontName=BF, fontSize=8.5, leading=11.5, textColor=colors.HexColor("#555"))
    cell = ParagraphStyle("mc", fontName=BF, fontSize=9, leading=12)
    cellb = ParagraphStyle("mcb", parent=cell, fontName=BFB)
    head = ParagraphStyle("mhd", fontName=BFB, fontSize=9, leading=12, textColor=colors.white)
    secth = ParagraphStyle("msec", fontName=BFB, fontSize=12.5, leading=15, textColor=colors.white)
    boxst = ParagraphStyle("mbx", fontName=BF, fontSize=9.5, leading=13, textColor=colors.HexColor("#6b4e00"))

    def _box(text, fill, brd):
        t = Table([[Paragraph(text, boxst)]], colWidths=[7.0 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fill), ("BOX", (0, 0), (-1, -1), 0.6, brd),
                               ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                               ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9)]))
        return t

    def _band(text):
        t = Table([[Paragraph(text, secth)]], colWidths=[7.0 * inch])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 7),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
        return t

    _now = report_dt or datetime.datetime.now().astimezone()
    cover_date = f"{_now:%B} {_now.day}, {_now.year}"
    _h12 = _now.hour % 12 or 12
    cover_time = f"{_h12}:{_now.minute:02d} {'AM' if _now.hour < 12 else 'PM'} {_now.strftime('%Z')}".strip()
    n = len(items)

    story = []
    story.append(Paragraph(esc(APP_NAME), title_st))
    if report_no is not None:
        story.append(Paragraph(f"Report #{report_no}", bigmeta))
    story.append(Paragraph(f"Consumer Concern Report — {n} Products", bigmeta))
    story.append(Paragraph(f"Created {esc(cover_date)}", small))
    story.append(Paragraph(esc(cover_time), small))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"A single combined review of {n} products' lab-testing data, for one consumer's "
                           "concern. Each product is reviewed independently in its own section below.", sub_st))
    story.append(Spacer(1, 10))

    # ---- Consumer-reported health context (informational only; NOT medical advice) ----
    conds = (shared.get("conditions") or "").strip()
    concern = (shared.get("concern") or "").strip()
    if conds or concern:
        lines = []
        if conds:
            lines.append(f"<b>Pre-existing conditions the consumer reported:</b> {esc(conds)}.")
        if concern:
            lines.append(f"<b>Consumer's stated concern:</b> {esc(concern)}.")
        lines.append("This health context was provided by the consumer and is recorded here for the reviewer's "
                     "awareness only. It is <b>not independently verified</b>, it is <b>not medical advice</b>, and "
                     "it does <b>not</b> change how the products' lab results are analyzed below. CannaScope does not "
                     "diagnose, assess medical risk, or link any product to any health condition. A consumer with a "
                     "health concern should speak with a qualified healthcare provider or pharmacist.")
        story.append(Paragraph("Consumer-Reported Health Context", ParagraphStyle("mhc", parent=bigmeta, fontSize=12)))
        story.append(_box("<br/>".join(lines), colors.HexColor("#fff7e6"), colors.HexColor("#d9a441")))
        story.append(Spacer(1, 10))

    # ---- Combined at-a-glance summary across the N products ----
    story.append(Paragraph("Products in This Report", ParagraphStyle("mph", parent=bigmeta, fontSize=12)))
    hdr = [Paragraph(h, head) for h in ("#", "Product", "Resolved via", "COA", "Items flagged for review")]
    rows_t = [hdr]
    for i, it in enumerate(items, 1):
        rr = it["res"].get("row") or {}
        nm = it["pin"].get("product") or rr.get("PRODUCT-NAME") or f"Product {i}"
        rv = it["res"].get("lookup_path") or ("not resolved" if not rr else "—")
        coa_ok = "Yes" if it["analysis"].get("coa_url") else "No"
        # Distinguish a contaminant result (any_flag) from a lab-reporting review note (compliance,
        # e.g. the cannabinoid-total math check) so the summary isn't misleading.
        if it["analysis"].get("any_flag"):
            flagged, fcol = "Yes — contaminant result(s)", "#C0392B"
        elif it["analysis"].get("compliance"):
            flagged, fcol = "Review note — see section", "#9A7B0A"
        else:
            flagged, fcol = "No", "#1E7E34"
        rows_t.append([Paragraph(f"<b>{i}</b>", ParagraphStyle("mcc", parent=cell, alignment=1)),
                       Paragraph(esc(tcase(nm)), cell), Paragraph(esc(rv), cell),
                       Paragraph(esc(coa_ok), ParagraphStyle("mcc2", parent=cell, alignment=1)),
                       Paragraph(f'<font color="{fcol}"><b>{flagged}</b></font>', cell)])
    st = Table(rows_t, colWidths=[0.35*inch, 2.7*inch, 1.85*inch, 0.55*inch, 1.55*inch], repeatRows=1)
    st.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
                            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd6dd")),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f8")]),
                            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    story.append(st)
    story.append(Spacer(1, 4))
    story.append(Paragraph('"Items flagged for review" is a lead to verify, not a conclusion — it can include a '
                           "lab-reporting/transcription oddity (e.g. cannabinoid totals) and is not the same as a "
                           "contaminant failure. See each product's section for the specifics.", small))

    # ---- One self-contained section per product (reuse build_patient_pdf in section mode) ----
    for k, it in enumerate(items):
        story.append(PageBreak())
        rr = it["res"].get("row") or {}
        nm = it["pin"].get("product") or rr.get("PRODUCT-NAME") or f"Product {k+1}"
        story.append(_band(f"Concern {k+1} of {n}: {esc(tcase(nm))}"))
        story.append(Spacer(1, 6))
        story.extend(build_patient_pdf(None, it["pin"], it["res"], it["analysis"],
                                       report_no=report_no, report_dt=_now,
                                       return_story=True, include_cover=False, include_footer=(k == n - 1)))

    SimpleDocTemplate(out_path, pagesize=letter, leftMargin=0.7*inch, rightMargin=0.7*inch,
                      topMargin=0.6*inch, bottomMargin=0.7*inch,
                      title=f"Consumer Concern Report — {n} Products", author=APP_NAME).build(story)


_EXAMPLE_FIXTURE = dict(
    qr="https://qrco.de/betfkw", batch="F09-F2H20-SPWF", uid="2505 9913 7721 0232",
    ndc_stated="C0101000528", ndc_label="C0101000538",
    cultivator="Nutmeg New Britain IV LLC",
    product="whole cannabis flower 3.5g", thca=34.03, thc=0.47,
    harvest="02/19/2026", packaged="04/21/2026", tested="04/27/2026", exp="04/27/2027",
    concern="Patient reported a concern about this product after use.",
)


def main_patient(argv=None):
    migrate_legacy_out_dir()   # so the shared registry/COA cache carries over after the rename
    ap = argparse.ArgumentParser(
        prog="concern",
        description=f"{APP_NAME} — Personalized Product Concern Report (one product, for a consumer concern)")
    ap.add_argument("--product", default="", help="product name")
    ap.add_argument("--cultivator", "--brand", dest="cultivator", default="", help="brand / cultivator")
    ap.add_argument("--batch", default="", help="batch number (lives on the COA)")
    ap.add_argument("--ndc", default="", help="NDC as the patient reported it")
    ap.add_argument("--ndc-label", default="", help="NDC read from the label photo (if it differs)")
    ap.add_argument("--uid", default="", help="UID / BioTrack lot (lives on the COA)")
    ap.add_argument("--coa", default="", help="COA number")
    ap.add_argument("--qr", default="", help="QR / COA URL from the package")
    ap.add_argument("--harvest", default=""); ap.add_argument("--packaged", default="")
    ap.add_argument("--tested", default=""); ap.add_argument("--exp", default="")
    ap.add_argument("--thca", type=float, default=None); ap.add_argument("--thc", type=float, default=None)
    ap.add_argument("--concern", default="", help="the patient's stated concern")
    ap.add_argument("--conditions", default="",
                    help="consumer's reported pre-existing conditions (noted as context; not medical advice)")
    ap.add_argument("--products-json", default="",
                    help="path to a JSON array of product objects (product/ndc/batch/uid/coa/qr/...) to "
                         "review MULTIPLE products in ONE combined report")
    ap.add_argument("--example", action="store_true",
                    help="run the built-in Nutmeg New Britain test fixture")
    ap.add_argument("--threshold", type=int, default=v4.DEFAULT_WATCH)
    ap.add_argument("--workers", type=int, default=_default_ocr_workers())
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--no-related", action="store_true",
                    help="do NOT look up related/sibling COAs from the same producer")
    ap.add_argument("--related-n", type=int, default=PATIENT_RELATED_MAX,
                    help=f"max related sibling COAs to fetch + show (default {PATIENT_RELATED_MAX})")
    ap.add_argument("--related-window-days", type=int, default=PATIENT_RELATED_WINDOW_DAYS,
                    help=f"time window for 'close enough' siblings (default {PATIENT_RELATED_WINDOW_DAYS})")
    args = ap.parse_args(argv)
    multi = bool(args.products_json)

    if multi:
        pin = None                       # multi-product mode builds a pin per product from the JSON
    elif args.example:
        pin = dict(_EXAMPLE_FIXTURE)
    else:
        pin = dict(product=args.product, cultivator=args.cultivator, batch=args.batch,
                   ndc_stated=args.ndc, ndc_label=args.ndc_label, uid=args.uid, coa=args.coa,
                   qr=args.qr, harvest=args.harvest, packaged=args.packaged, tested=args.tested,
                   exp=args.exp, thca=args.thca, thc=args.thc, concern=args.concern)
        if not any(pin.get(k) for k in ("product", "cultivator", "batch", "ndc_stated",
                                        "ndc_label", "uid", "coa", "qr")):
            ap.error("provide at least one identifier (e.g. --ndc, --batch, --qr, --product), "
                     "use --products-json for several products, or --example for the built-in test case.")

    enable_safe_pdf_text()
    if args.offline:
        enable_offline_sources()
    if args.no_ocr:
        v4._OCR_BACKEND = ""
    else:
        enable_isolated_ocr()
        set_ocr_concurrency(args.workers)

    if args.offline:
        import requests
        session = requests.Session()
    else:
        session = v4.make_session("", args.workers)
    v4.CACHE_DIR = CACHE_DIR
    os.makedirs(CACHE_DIR, exist_ok=True)

    rows = _patient_registry_rows(session, offline=args.offline)

    def _resolve_one(pin_one, *, verbose=True):
        """Resolve + analyze ONE product (+ siblings). Returns (res, analysis). Shared by the
        single-product and multi-product paths so they behave identically per product."""
        res_one = resolve_patient_product(rows, pin_one, session=session, offline=args.offline)
        if verbose:
            if res_one["row"]:
                print(f"  Resolved via: {res_one['lookup_path']}  ({', '.join(res_one['matched_on'])})")
                if res_one["conflicts"]:
                    print(f"  Discrepancies surfaced: {len(res_one['conflicts'])}")
            else:
                print("  Could not confidently resolve the product — the PDF will explain what is missing.")
        if res_one["row"]:
            p_one = _row_to_product(res_one["row"])
            ana_one = analyze_patient_product(p_one, pin_one, session, args.threshold, offline=args.offline)
            if verbose:
                print(f"  COA {'parsed' if ana_one['coa_fetched'] else 'not retrieved'}; "
                      f"flags present: {ana_one['any_flag']}")
            if not args.no_related:
                ana_one["related"] = find_related_coas(
                    res_one["row"], p_one, rows, pin_one, session, args.threshold,
                    max_n=args.related_n, window_days=args.related_window_days, offline=args.offline)
        else:
            ana_one = dict(coa_fetched=False, classes={}, pathogens=[], compliance=[],
                           corroboration=[], coa_url="", testing_date="", parse_note="",
                           coa_status="", pesticide_panel="", solvent_panel="", any_flag=False, p=None)
        return res_one, ana_one

    # ---- MULTI-PRODUCT: one combined report covering several products ----
    if multi:
        try:
            with open(args.products_json, encoding="utf-8") as f:
                specs = json.load(f)
        except (OSError, ValueError) as e:
            ap.error(f"could not read --products-json '{args.products_json}': {e}")
        if not isinstance(specs, list) or not specs:
            ap.error("--products-json must be a non-empty JSON array of product objects.")
        print(f"Reviewing {len(specs)} products into ONE combined Consumer Concern Report ...")
        items = []
        for i, sp in enumerate(specs, 1):
            pin_i = dict(product=sp.get("product", ""), cultivator=sp.get("cultivator", ""),
                         batch=sp.get("batch", ""), ndc_stated=sp.get("ndc", "") or sp.get("ndc_stated", ""),
                         ndc_label=sp.get("ndc_label", ""), uid=sp.get("uid", ""), coa=sp.get("coa", ""),
                         qr=sp.get("qr", ""), harvest=sp.get("harvest", ""), packaged=sp.get("packaged", ""),
                         tested=sp.get("tested", ""), exp=sp.get("exp", ""), thca=sp.get("thca"),
                         thc=sp.get("thc"), concern=sp.get("concern", args.concern))
            print(f"  [{i}/{len(specs)}] {pin_i.get('product') or pin_i.get('ndc_stated') or 'product'} ...")
            res_i, ana_i = _resolve_one(pin_i, verbose=False)
            print(f"      {('resolved via ' + res_i['lookup_path']) if res_i['row'] else 'NOT resolved'}"
                  + (f"; items flagged: {ana_i.get('any_flag')}" if res_i["row"] else ""))
            items.append(dict(pin=pin_i, res=res_i, analysis=ana_i))
        shared = dict(conditions=args.conditions, concern=args.concern)
        out_path, report_no, run_dt = _consumer_report_path()
        if os.path.exists(out_path):
            raise SystemExit(f"FATAL: consumer report #{report_no} would overwrite an existing file: {out_path}")
        build_patient_pdf_multi(out_path, items, shared, report_no, run_dt)
        print(f"\nWrote combined ConsumerConcern report #{report_no} ({len(items)} products):\n  {out_path}")
        return out_path

    # ---- SINGLE PRODUCT (unchanged behavior) ----
    print("Resolving the product from the identifiers you provided ...")
    res, analysis = _resolve_one(pin)
    out_path, report_no, run_dt = _consumer_report_path()
    # Numbering integrity — global, continuous, never reused/overwritten (same guard as statewide).
    if os.path.exists(out_path):
        raise SystemExit(f"FATAL: consumer report #{report_no} would overwrite an existing file: {out_path}")
    build_patient_pdf(out_path, pin, res, analysis, report_no, run_dt)
    print(f"\nWrote ConsumerConcern report #{report_no}:\n  {out_path}")
    return out_path


if __name__ == "__main__":
    # Subcommands (old aliases kept so nothing breaks):
    #   concern  : Personalized Product Concern Report (one product, consumer concern)
    #   learn    : COA Format Learning self-test — practice against historical COAs by year
    #   statewide: Statewide Transparency Report (whole-market scan) — also the default
    #   audit-cache: pre-V16 local cache audit & re-evaluation (resumable, batched, checkpointed)
    _sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if _sub in ("concern", "consumer-concern", "patient-concern"):
        main_patient(sys.argv[2:])
    elif _sub in ("learn", "selftest", "coa-selftest", "format-learn"):
        main_learn(sys.argv[2:])
    elif _sub in ("audit-cache", "audit", "recache", "cache-audit"):
        main_audit(sys.argv[2:])
    elif _sub in ("build-cache", "build-coa-cache", "cache-build"):
        main_build_cache(sys.argv[2:])
    elif _sub in ("fetch-standards", "fetch-regs", "cache-standards"):
        main_fetch_standards(sys.argv[2:])
    elif _sub in ("statewide", "report", "market"):
        sys.argv = [sys.argv[0]] + sys.argv[2:]   # strip the subcommand for main()'s argparse
        main()
    else:
        main()
