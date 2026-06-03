#!/usr/bin/env python3
"""
CannaScope CT Beta V11.1
=======================
Connecticut Cannabis Transparency Report — source-verified consumer-awareness and
testing-pattern review.

Every flag is a LEAD, not a conclusion. CannaScope CT Beta V11.1 does not claim
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
    CannaScope_CT_Beta_V11_1_Report_<N>_MM_DD_YYYY.pdf, numbered sequentially from 1.

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
    sys.exit("CannaScope CT Beta V11.1 needs cannascope_ct_v5.py and cannascope_ct_v4.py beside it.")

names = getattr(v4, "names", None)
ProductV5 = v5.ProductV5

# ============================================================================
# Config
# ============================================================================
# Version label shown on the report cover, in output filenames, and in the footer.
APP_NAME = "CannaScope CT Beta V11.1"
REPORT_TITLE = "Connecticut Cannabis Statewide Transparency Report"
REPORT_SUBTITLE = "Source-Verified Consumer Awareness & Testing Pattern Review"
FRAMING = ("Every flag is a lead, not a conclusion. CannaScope CT Beta V11.1 does not claim "
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

OUT_DIR = "CannaScope CT Beta V11.1 - Statewide Transparency Reports"
LEGACY_OUT_DIRS = ["CannaScope CT Beta V11 - Statewide Transparency Reports"]   # auto-migrated to OUT_DIR if present
CACHE_DIR = os.path.join(OUT_DIR, "Flagged COA Source PDFs")
REGISTRY_CACHE = os.path.join(OUT_DIR, "Registry Cache.csv")
LEDGER = os.path.join(OUT_DIR, "Already-Scanned Skip List.txt")
SOURCE_CACHE = os.path.join(OUT_DIR, "Source Validation Cache.json")
REPORT_PREFIX = "CannaScope_CT_Beta_V11_1_Statewide_Transparency_Report_"
PUBLIC_PDF_NAME = "CannaScope_CT_Beta_V11_1_Statewide_Transparency_Report.pdf"   # stable name copied to the working folder
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


def load_registry(session, refresh=False, offline=False):
    v5.OUT_DIR = OUT_DIR
    v5.REGISTRY_CACHE = REGISTRY_CACHE
    _seed_embedded_registry()   # no-op unless a snapshot is embedded and no cache exists yet
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


def thc_review_value(p):
    """Highest reliable cannabinoid % for the non-infused flower review, or None.
    Skips parser conflicts and scientific-notation-tier garbage."""
    if thc_conflict(p):
        return None
    best = None
    for key in ("total_thc", "thca", "total_cannabinoids", "total_active", "thc", "d9_thc"):
        v = thc_value(p, key)
        if v is None or not math.isfinite(v) or v < 0.001 or v > 100:
            continue
        if best is None or v > best[1]:
            best = (key, v)
    return best


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
    import csv as _csv
    slug = re.sub(r"[^a-z0-9]+", "_", (analyte_name or "").lower()).strip("_")
    path = os.path.join(OUT_DIR, f"severity_{slug}.csv")
    if not slug or not os.path.exists(path):
        return None
    try:
        rows = list(_csv.DictReader(open(path, encoding="utf-8", errors="replace")))
    except Exception:
        return None
    ln = _norm(legal)
    hits = sum(1 for r in rows if ln and ln in _norm(r.get("producer_dba", "")))
    return dict(total=len(rows), producer=hits, analyte=analyte_name, file=os.path.basename(path))


def report_status(debug, remaining, draft_zero):
    """PASS / PASS WITH WARNINGS / DRAFT / FAIL — honest, not always 'PASSED'."""
    if remaining:
        return "FAIL"
    if draft_zero:
        return "DRAFT"
    warn = (debug.get("broken_or_missing_coa_links", 0) > 0
            or debug.get("unreadable_after_retry", 0) > 0
            or debug.get("coa_verification_queue", 0) > 0
            or debug.get("potency_parser_conflicts", 0) > 0)
    return "PASS WITH WARNINGS" if warn else "PASS"


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
              "serialized_low_memory": 0, "proceeded_under_load": 0}
_CPU = os.cpu_count() or 4
_OCR_AVAILABLE = None      # parent-side cache: is any OCR engine installed?
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


def _run_ocr_worker(src, max_pages, timeout):
    """Run the OCR worker in its own process group and return (returncode, stdout).
    On timeout the ENTIRE group is killed (no orphaned grandchildren), the child is
    reaped so no zombie lingers, and TimeoutExpired is re-raised to the caller."""
    proc = subprocess.Popen([sys.executable, _OCR_WORKER, src, str(max_pages)],
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


def _isolated_ocr_pdf(src, max_pages: int = 6) -> str:
    """OCR one COA in a separate process group. A segfault, hang, or timeout takes
    down only that child (and any grandchildren) -> '' (the COA is treated as
    unreadable and retried later) instead of taking down the scan."""
    if not isinstance(src, str) or not os.path.exists(_OCR_WORKER):
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
    for timeout in (120, 300):          # retry once with a longer timeout if overloaded
        try:
            if serialize:
                with _OCR_SERIALIZE, _OCR_SEM:
                    rc, out = _run_ocr_worker(src, max_pages, timeout)
            else:
                with _OCR_SEM:
                    rc, out = _run_ocr_worker(src, max_pages, timeout)
            if rc == 0:
                with _OCR_LOCK:
                    _OCR_STATS["ok"] += 1
                return (out or b"").decode("utf-8", "replace")
            with _OCR_LOCK:             # non-zero exit = native crash; retry won't help
                _OCR_STATS["crashes"] += 1
            return ""
        except subprocess.TimeoutExpired:
            with _OCR_LOCK:
                _OCR_STATS["timeouts"] += 1
            continue                    # overloaded/hung -> retry once, longer timeout
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
                    lp.append(f"COA Total THC {total:g}% does not reconcile with 0.877*THCA "
                              f"({thca:g}%) + delta-9 THC ({d9:g}%) = {computed:.1f}% — potential "
                              f"potency-labeling / calculation discrepancy")
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
# Zero-result verification (presume parser error until verified)
# ============================================================================
def parsed_count(all_results, key):
    """How many products had this analyte PARSED at all (any status)."""
    return sum(1 for p in all_results if key in p.analytes)


def zero_result_checks(all_results, flagged, watch):
    """For each expected category, decide: has flagged rows / confirmed zero /
    suspected parser error. Returns list of dicts + a draft flag."""
    checks = []

    def add(cat, n_flagged, parsed, total, extra=""):
        if n_flagged > 0:
            status, note = "OK", f"{n_flagged} validated row(s)."
        elif parsed == 0 and total > 0:
            status, note = ("DRAFT WARNING",
                            f"Parsed in 0 of {total} products — likely parser/filter error. {extra}")
        else:
            status, note = ("Confirmed Zero",
                            f"Parsed in {parsed} of {total} products; none crossed the "
                            f"CannaScope threshold. {extra}")
        checks.append(dict(category=cat, flagged=n_flagged, parsed=parsed,
                           total=total, status=status, note=note))

    total = len(all_results)
    for key, title in ANALYTE_TABLES:
        n = len(category_rows(flagged, key))
        add(title, n, parsed_count(all_results, key), total)
    # mycotoxins (distinct products that had any mycotoxin parsed)
    n = len(mycotoxin_rows(flagged))
    add("Mycotoxins", n, sum(1 for p in all_results if any(k in p.analytes for k in MYCO_KEYS)), total)
    # pathogens
    n = len(pathogen_rows(flagged))
    parsed = sum(1 for p in all_results if any(k in p.analytes for k in v5.PATHO_KEYS))
    add("Pathogens", n, parsed, total)
    # pesticides (panel)
    n = len(pesticide_rows(flagged))
    tested = sum(1 for p in all_results if p.pesticides in ("PASS", "FAIL"))
    add("Pesticides", n, tested, total, "(panel PASS/FAIL counts as parsed.)")
    # residual solvents (panel)
    n = len(solvent_rows(flagged))
    tested = sum(1 for p in all_results if p.solvents in ("PASS", "FAIL"))
    add("Residual Solvents", n, tested, total, "(panel PASS/FAIL counts as parsed.)")
    # high-THC non-infused flower (compute thc_review_value once per product)
    def _high_thc_flower(p):
        rv = thc_review_value(p)
        return is_noninfused_flower(p) and rv is not None and rv[1] > THC_REVIEW_PCT
    n = sum(1 for p in flagged if _high_thc_flower(p))
    parsed = sum(1 for p in all_results if p.cannabinoids)
    add("High-THC Flower Review", n, parsed, total)

    draft = any(c["status"] == "DRAFT WARNING" for c in checks)
    return checks, draft


# ============================================================================
# Self-audit
# ============================================================================
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
    # zero-result draft warnings
    zw = sum(1 for c in zero_checks if c["status"] == "DRAFT WARNING")
    chk("Zero-result sections suspected to be parser errors", zw, fixed=(zw == 0))

    remaining = [i for i in issues if i["status"] == "REMAINS"]
    return issues, remaining


# ============================================================================
# PDF
# ============================================================================
def next_report_path(status):
    """Reports are NEVER overwritten or erased. Each gets a unique name carrying the
    VERSION, a sequential REPORT NUMBER, and the PUBLICATION DATE + TIME:
        CannaScope_CT_Beta_V11_1_Report_<N>[_DRAFT]_<YYYY_MM_DD_HHMM>.pdf
    N starts at 1 and is one greater than the highest existing report number found in
    BOTH the output folder and the working folder (scanning both keeps the sequence
    robust even if one folder is cleared). The date+time stamp means even two reports
    with the same number (across cleared folders) never collide, so older reports
    always remain available for comparison and auditing."""
    import glob
    stamp = datetime.datetime.now().strftime("%Y_%m_%d_%H%M")   # publication date + time
    dirs = {OUT_DIR, os.path.dirname(os.path.abspath(OUT_DIR))}
    # Count existing reports under BOTH the current name and any legacy name
    # (e.g. the pre-rename "..._Report_<N>") so the sequence continues unbroken
    # across a feature rename and never reuses an old number.
    # Version-agnostic so the sequence CONTINUES across a version bump / folder migration
    # (e.g. V11.1 reports carried into a V11.1 folder still count toward the next number).
    ANY_REPORT = "CannaScope_CT_Beta_V*Report_*.pdf"
    rx = re.compile(r"Report_(\d+)")
    nums = [int(m.group(1)) for d in dirs
            for f in glob.glob(os.path.join(d, ANY_REPORT))
            for m in [rx.search(os.path.basename(f))] if m]
    n = (max(nums) + 1) if nums else 1
    tag = "_DRAFT" if status in ("DRAFT", "FAIL") else ""
    # Belt-and-suspenders: never reuse a number whose file already exists in EITHER
    # folder under EITHER naming — bump until the name is provably free, so a new
    # report can never overwrite an older one.
    while any(glob.glob(os.path.join(d, f"CannaScope_CT_Beta_V*Report_{n}_*.pdf")) for d in dirs):
        n += 1
    return os.path.join(OUT_DIR, f"{REPORT_PREFIX}{n}{tag}_{stamp}.pdf"), n


def build_pdf(out_path, report_no, ctx):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, legal
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, PageBreak, KeepTogether)

    BF, BFB = v4._setup_fonts()
    NAVY = colors.HexColor("#1F2D3D"); AQUA = colors.HexColor("#0E6B5A")
    PURPLE = colors.HexColor("#7D3C98"); RED = colors.HexColor("#C0392B")
    PAGE = landscape(legal); esc = v4._esc

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

    title_st = ParagraphStyle("t", fontName=BFB, fontSize=24, leading=27, alignment=1, textColor=NAVY)
    sub_st = ParagraphStyle("s", fontName=BF, fontSize=13, leading=16, alignment=1, textColor=colors.HexColor("#444"))
    meta_st = ParagraphStyle("m", fontName=BF, fontSize=10, leading=13, alignment=1, textColor=colors.HexColor("#444"))
    note_st = ParagraphStyle("n", fontName=BF, fontSize=9.5, leading=13, alignment=1)
    body_st = ParagraphStyle("b", fontName=BF, fontSize=10.5, leading=14, textColor=colors.HexColor("#222"))
    cell = ParagraphStyle("c", fontName=BF, fontSize=9.5, leading=12)
    cellc = ParagraphStyle("cc", parent=cell, alignment=1)
    cellb = ParagraphStyle("cb", parent=cell, fontName=BFB)
    head = ParagraphStyle("h", fontName=BFB, fontSize=9.5, leading=12, textColor=colors.white, alignment=1)
    # centered MAJOR section header (large)
    H1 = ParagraphStyle("h1", fontName=BFB, fontSize=20, leading=24, alignment=1, spaceBefore=14,
                        spaceAfter=7, textColor=NAVY, keepWithNext=1)
    CTX = ParagraphStyle("ctx", fontName=BF, fontSize=9.5, leading=12.5, alignment=1,
                         textColor=colors.HexColor("#555"), spaceAfter=8, keepWithNext=1)
    # centered subheader (mini tables + diagnostics)
    miniH = ParagraphStyle("mh", fontName=BFB, fontSize=13, leading=16, alignment=1, spaceBefore=13,
                           spaceAfter=7, textColor=NAVY, keepWithNext=1)

    now = datetime.datetime.now().astimezone()
    dcreated, tcreated = now.strftime("%Y-%m-%d"), now.strftime("%I:%M %p %Z").lstrip("0").strip()
    pmap, lmap, ident = ctx["pmap"], ctx["lmap"], ctx["ident"]
    watch, window, status = ctx["watch"], ctx["window"], ctx["status"]
    scol = {"PASS": "#1E7E34", "PASS WITH WARNINGS": "#E67E22",
            "DRAFT": "#C0392B", "FAIL": "#C0392B"}.get(status, "#C0392B")

    doc = SimpleDocTemplate(out_path, pagesize=PAGE, leftMargin=0.3*inch, rightMargin=0.3*inch,
                            topMargin=0.45*inch, bottomMargin=0.6*inch,
                            title=f"{APP_NAME} — Report {report_no}", author=APP_NAME)

    def pr(p):
        return esc(producer_short(p, ident))

    def td(p):
        return Paragraph(esc(test_date(p)) or "—", cellc)

    def coa(p):
        ref = tcase(p.registration_number or "COA")
        if p.report_url:
            return (f'<link href="{esc(p.report_url)}"><font color="#1155CC"><u><b>'
                    f'{esc(ref)}</b></u></font></link>')
        return '<font color="#C0392B"><b>Missing — Verify</b></font>'

    # A COA ID is ONE unbreakable string: a slightly smaller font + splitLongWords off
    # so an identifier like "MMBR.0033648" never force-wraps mid-id. Link stays clickable.
    coacell = ParagraphStyle("coa", parent=cellc, fontSize=8.5, leading=10.5, splitLongWords=0)

    def coa_cell(p):
        return Paragraph(coa(p), coacell)

    def H(title, color=NAVY):
        return Paragraph(esc(tcase(title)), ParagraphStyle("hx", parent=H1, textColor=color))

    def tbl(headers, rows, widths, hc=NAVY, band="#eef2f5", rank_sevs=None, big=True):
        data = [[Paragraph(h, head) for h in headers]]
        for r in rows:
            data.append([x if hasattr(x, "wrap") else Paragraph(str(x), cell) for x in r])
        t = Table(data, repeatRows=1, colWidths=widths)
        pad = 6 if big else 4
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

    def rich_rows(items):
        rows, sevs = [], []
        for i, (p, d) in enumerate(items, 1):
            sev = sev_of(d); bar = SEVC[sev][0]; sevs.append(sev); unit = d.get("unit", "")
            ctp = d.get("ct_pct"); vs = d.get("vs_std")
            rows.append([
                Paragraph(f'<font color="{bar}"><b>{i}</b></font>', cellc),
                Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                Paragraph(esc(clean_value(d.get("value"), unit)), cellb),
                Paragraph(esc(clean_value(d.get("ct_limit"), unit)), cellc),
                Paragraph(f'<font color="{bar}"><b>{v4.ct_pct_label(ctp, full=False)}</b></font>' if ctp is not None else "—", cellc),
                Paragraph(esc(clean_value(d.get("cs_std"), unit)), cellc),
                Paragraph(f'<font color="{bar}"><b>{v4.vs_standard_label(vs, full=False)}</b></font>' if vs is not None else "—", cellc),
                coa_cell(p)])
        return rows, sevs

    def rich_table(items, hc=NAVY):
        rows, sevs = rich_rows(items[:MAX_TABLE_ROWS])
        return tbl(RICH_COLS, rows, RICH_W, hc=hc, rank_sevs=sevs)

    def overflow_note(total, csv_hint, shown=MAX_TABLE_ROWS, what="rows"):
        """Append a note when a findings table was capped for length. The PDF shows
        the worst `shown`; the COMPLETE list is always in the named CSV export."""
        if total > shown:
            story.append(Paragraph(
                f"Showing the top {shown:,} of {total:,} {what} (ranked by severity). "
                f"The complete list is in <b>{esc(csv_hint)}</b>.",
                ParagraphStyle("ov", parent=CTX, textColor=colors.HexColor("#8a5a00"))))

    # ---- findings-first summary box + per-section trend notes (text only; tables unchanged) ----
    SUMM = ParagraphStyle("summ", parent=body_st, fontSize=10, leading=14.5,
                          textColor=colors.HexColor("#1F2D3D"), backColor=colors.HexColor("#eef2f5"),
                          borderPadding=8, spaceAfter=8)
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

    # ---------------- COVER ----------------  (intentional vertical rhythm; not compressed)
    story += [
        Paragraph(APP_NAME, title_st),
        Spacer(1, 5),
        Paragraph(esc(REPORT_TITLE), sub_st),
        Spacer(1, 2),
        Paragraph(esc(REPORT_SUBTITLE), ParagraphStyle("sub2", parent=sub_st, fontSize=11)),
        Spacer(1, 9),
        Paragraph(f"Report #{report_no} &nbsp;|&nbsp; <font color=\"{scol}\"><b>{esc(status)}</b></font>", meta_st),
        Spacer(1, 3),
        Paragraph(f"<b>Created:</b> {dcreated} {esc(tcreated)} &nbsp;|&nbsp; <b>Dataset Window:</b> {esc(window)}", meta_st),
        Spacer(1, 13),
        Paragraph(f"<b>{esc(FRAMING)}</b>", ParagraphStyle("fr", parent=note_st, fontSize=10.5, leading=14.5,
                  textColor=NAVY, backColor=colors.HexColor("#eef2f5"), borderPadding=8)),
        Spacer(1, 13),
        Paragraph(f"<b>{ctx['n_reviewed']:,}</b> reviewed &nbsp;•&nbsp; <b>{ctx['n_pub']:,}</b> validated findings &nbsp;•&nbsp; "
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
    story.append(H("Executive Summary"))
    story.append(tbl(["Reviewed", "Validated Findings", "Do Not Consume", "High Caution",
                      "Moderate Caution", "High Cannabinoid"],
                     [[f"{ctx['n_reviewed']:,}", f"{ctx['n_pub']:,}", str(ctx["n_red"]), str(ctx["n_org"]),
                       str(ctx["n_yel"]), str(ctx["n_thc"])]], [1.6*inch]*6))
    story.append(Spacer(1, 12))

    ai = ctx["analyte_items"]
    metals = sorted([pd for k in ("arsenic", "chromium", "cadmium", "lead", "mercury") for pd in ai[k]],
                    key=lambda pd: pd[1]["ct_pct"] or 0, reverse=True)
    micro = sorted(ai["tymc"] + ai["aerobic"], key=lambda pd: pd[1]["ct_pct"] or 0, reverse=True)

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
    glance.append("<i>Every item above is a lead, not a conclusion — verify each against the product's live COA.</i>")
    # Keep the heading with its box, and never split the box across a page boundary.
    story.append(KeepTogether([Paragraph("Findings at a Glance", miniH),
                               Paragraph("• " + "<br/>• ".join(glance), SUMM)]))

    def mini(title, headers, rows, widths):
        # Each mini = title + table as ONE atomic block with trailing breathing room. If it
        # doesn't fit on the current page it flows whole to the next page (no cramming / no
        # orphaned heading / no mid-table split) — e.g. the 3rd top table moves to page 3
        # rather than being squeezed onto page 2.
        block = [Paragraph(esc(title), miniH)]
        block.append(tbl(headers, rows, widths, big=False) if rows
                     else Paragraph("None in this run.", cellc))
        block.append(Spacer(1, 12))
        story.append(KeepTogether(block))

    def metal_rows(src, n=5):
        out = []
        for i, (p, d) in enumerate(src[:n], 1):
            sev = sev_of(d); bar = SEVC[sev][0]
            out.append([Paragraph(f'<font color="{bar}"><b>{i}</b></font>', cellc),
                        Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                        Paragraph(esc(d["name"]), cell), Paragraph(esc(clean_value(d.get("value"), d.get("unit", ""))), cellc),
                        Paragraph(f'<font color="{bar}"><b>{v4.ct_pct_label(d.get("ct_pct"), full=False)}</b></font>' if d.get("ct_pct") is not None else "—", cellc),
                        coa_cell(p)])
        return out

    mini("Top Heavy Metal Findings", ["#", "Product", "Testing Date", "Producer", "Metal", "Measured", "CT %", "COA"],
         metal_rows(metals), [0.35*inch, 2.7*inch, 0.95*inch, 2.1*inch, 1.15*inch, 1.45*inch, 0.95*inch, 1.15*inch])
    mini("Top Microbial Findings", ["#", "Product", "Testing Date", "Producer", "Type", "Measured", "CT %", "COA"],
         metal_rows(micro), [0.35*inch, 2.7*inch, 0.95*inch, 2.1*inch, 1.5*inch, 1.35*inch, 0.9*inch, 1.1*inch])

    thc_rows = [[Paragraph(f'<font color="#0E6B5A"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
                 td(p), Paragraph(pr(p), cell), Paragraph(f'<font color="#0E6B5A"><b>{val:g}%</b></font>', cellc),
                 coa_cell(p)] for i, (p, key, val) in enumerate(ctx["thc_flower"][:5], 1)]
    mini("Top High Cannabinoid Findings", ["#", "Product", "Testing Date", "Producer", "Cannabinoid %", "COA"], thc_rows,
         [0.35*inch, 3.2*inch, 0.95*inch, 2.7*inch, 1.3*inch, 1.15*inch])

    # NOTE: the former "Top Producer Patterns" mini-table was a duplicate of the fuller
    # "Producer Trends" section below; consolidated into that single producer-pattern section.
    lrow = [[Paragraph(esc(r["lab"]), cell), str(r["flagged"]), str(r["thc"]), Paragraph(esc(r["top"]), cell)]
            for r in ctx["lab_rows"][:5]]
    mini("Top Lab Patterns", ["Lab", "Contaminant-Flagged", "High Cannabinoid", "Most Common Contaminant"], lrow,
         [3.6*inch, 2.0*inch, 1.8*inch, 2.7*inch])

    rrow = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
             Paragraph(esc(clean_value(p.analytes.get("tymc", {}).get("value"), "CFU/g")), cellc),
             coa_cell(p)] for p in ctx["remediation"][:5]]
    mini("Top Possible Remediation Findings (Unusually Low Microbial Load)",
         ["Product", "Testing Date", "Producer", "Yeast & Mold", "COA"], rrow,
         [3.4*inch, 0.95*inch, 2.8*inch, 1.6*inch, 1.2*inch])

    # ---------------- PRODUCER & LAB TRENDS (directly under Executive Summary) ----------------
    story.append(H("Producer Trends"))
    rows = [[Paragraph(esc(r["label"]), cell), str(r["reviewed"]), str(r["flagged"]), f'{r["pct"]:.1f}%',
             Paragraph(esc(r["top"]), cell)] for r in ctx["producer_rows"][:18]]
    story.append(tbl(["Producer", "Reviewed", "Flagged", "% Flagged", "Most Common Issue"], rows,
                     [4.2*inch, 1.3*inch, 1.2*inch, 1.3*inch, 2.9*inch]))
    if ctx["producer_rows"]:
        pc = Counter({r["label"]: r["flagged"] for r in ctx["producer_rows"]})
        tot = sum(pc.values())
        rep = [r for r in ctx["producer_rows"] if r["flagged"] >= 2]
        extra = (f" {len(rep)} producer(s) have 2+ validated findings; the 'Most Common Issue' column shows where each repeats."
                 if rep else "")
        trend_note(_freq_line(pc, tot) + extra)

    story.append(H("Lab Trends"))
    rows = [[Paragraph(esc(r["lab"]), cell), str(r["flagged"]), str(r["thc"]), Paragraph(esc(r["top"]), cell)]
            for r in ctx["lab_rows"]]
    story.append(tbl(["Lab", "Contaminant-Flagged", "High Cannabinoid", "Most Common Contaminant"], rows,
                     [4.0*inch, 2.0*inch, 1.9*inch, 2.9*inch]))
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
    tf_w = [0.35*inch, 1.85*inch, 0.9*inch, 1.55*inch, 1.25*inch, 1.2*inch, 1.15*inch, 0.85*inch, 1.15*inch, 1.4*inch, 1.0*inch]
    rows, sevs = [], []
    for i, (p, d) in enumerate(ctx["exec_rows"][:15], 1):
        sev = sev_of(d); bar = SEVC[sev][0]; sevs.append(sev); unit = d.get("unit", "")
        rows.append([Paragraph(f'<font color="{bar}"><b>{i}</b></font>', cellc),
                     Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                     Paragraph(esc(d["name"]), cell), Paragraph(esc(clean_value(d.get("value"), unit)), cellb),
                     Paragraph(esc(clean_value(d.get("ct_limit"), unit)), cellc),
                     Paragraph(f'<font color="{bar}"><b>{v4.ct_pct_label(d.get("ct_pct"), full=False)}</b></font>', cellc),
                     Paragraph(esc(clean_value(d.get("cs_std"), unit)), cellc),
                     Paragraph(f'<font color="{bar}"><b>{v4.vs_standard_label(d.get("vs_std"), full=False)}</b></font>' if d.get("vs_std") is not None else "—", cellc),
                     coa_cell(p)])
    if rows:
        story.append(tbl(tf_cols, rows, tf_w, rank_sevs=sevs))
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
        overflow_note(len(ctx["mycotoxins"]), "CannaScope_CT_Beta_V11_1_Validated_Flagged.csv")
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
        overflow_note(len(ctx["solvents"]), "CannaScope_CT_Beta_V11_1_Validated_Flagged.csv")
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
        overflow_note(len(ctx["pesticides"]), "CannaScope_CT_Beta_V11_1_Validated_Flagged.csv")
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
        overflow_note(len(ctx["pathogens"]), "CannaScope_CT_Beta_V11_1_Validated_Flagged.csv")
    else:
        nsf.append(("Pathogens", next((c for c in ctx["zero"] if c["category"] == "Pathogens"), None)))

    # ---------------- HIGH CANNABINOID CONTENT (+ Testing Date + Lab) ----------------
    story.append(H("High Cannabinoid Content / High THC Content Findings", color=AQUA))
    story.append(Paragraph("Non-infused flower with a reliable cannabinoid reading above 35% — identifying unusually "
                           "high cannabinoid content for review, not an accusation. Testing date and lab help reveal patterns.", CTX))
    rows = [[Paragraph(f'<font color="#0E6B5A"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
             td(p), Paragraph(pr(p), cell), Paragraph(esc(lab_name(p, lmap)), cell),
             Paragraph(f'<font color="#0E6B5A"><b>{val:g}%</b></font>', cellc), coa_cell(p)]
            for i, (p, key, val) in enumerate(ctx["thc_flower"][:MAX_TABLE_ROWS], 1)]
    if rows:
        story.append(tbl(["#", "Product", "Testing Date", "Producer", "Lab", "Cannabinoid %", "COA"], rows,
                         [0.4*inch, 2.9*inch, 0.95*inch, 2.4*inch, 1.7*inch, 1.45*inch, 1.15*inch], hc=AQUA, band="#d4f5ee"))
        overflow_note(len(ctx["thc_flower"]), "high_thc_flower_noninfused.csv")
        thc_prods = Counter(producer_short(p, ident) for p, _k, _v in ctx["thc_flower"])
        thc_labs = Counter(lab_name(p, lmap) for p, _k, _v in ctx["thc_flower"])
        note = _freq_line(thc_prods, len(ctx["thc_flower"]))
        if note:
            tl, tc = thc_labs.most_common(1)[0]
            if tc > 1:
                note += f" Lab most associated: {esc(tl)} ({tc})."
            trend_note(note + " High cannabinoid content is a label-accuracy / review signal — not a contaminant or "
                              "safety finding.")
    else:
        story.append(Paragraph("No non-infused flower exceeded the 35% review threshold in this run.", cellc))

    # ---------------- POTENCY REFERENCE: INFUSED (separate from vapes/extracts) ----------------
    def _potency_section(title, blurb, items):
        story.append(H(title, color=PURPLE))
        story.append(Paragraph(blurb, CTX))
        rows = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                 Paragraph(esc(tcase(p.dosage_form)), cell), Paragraph(esc(lab_name(p, lmap)), cell),
                 Paragraph(f'{val:g}%', cellc), coa_cell(p)] for (p, key, val) in items[:40]]
        if rows:
            story.append(tbl(["Product", "Testing Date", "Producer", "Product Type", "Lab",
                              "Highest Cannabinoid %", "COA"], rows,
                             [2.7*inch, 0.9*inch, 2.2*inch, 1.5*inch, 1.5*inch, 1.5*inch, 1.1*inch],
                             hc=PURPLE, band="#ead9f2"))
        else:
            story.append(Paragraph("None reached the 35% reference threshold in this run.", cellc))

    _potency_section("Infused Products — Potency Reference",
                     "Infused FLOWER products only — infused joints, blunts, and pre-rolls (flower with added "
                     "concentrate). High potency is expected by design — reference only, not a flower abnormality. "
                     "Vapes / concentrates / extracts are NOT included here; they have their own section below.",
                     ctx["infused_potency"])
    _potency_section("Vapes, Concentrates & Extracts — Potency Reference",
                     "Vape cartridges, disposables, pods, and concentrates / extracts (rosin, resin, distillate, "
                     "diamonds, hash, etc.). High potency is expected by design — reference only. These are a "
                     "separate product class from infused flower products.",
                     ctx["extract_potency"])

    # ---------------- POSSIBLE REMEDIATION REVIEW ----------------
    if ctx["remediation"]:
        story.append(H("Possible Remediation / Unusually Low Microbial Load Review"))
        story.append(Paragraph("This is NOT proof of remediation. It is a consumer-awareness lead based on unusually "
                               "low or ND microbial readings (non-infused flower) and should be verified against the "
                               "live COA. Low microbial counts can be entirely normal.", CTX))
        rows = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                 Paragraph(esc(clean_value(p.analytes.get("tymc", {}).get("value"), "CFU/g")), cellc),
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

    # ---------------- LOWER-CONCERN PRODUCTS ----------------
    story.append(H("Lower-Concern Products", color=PURPLE))
    story.append(Paragraph("Non-infused flower with NO contaminant flag, a valid numeric Total THC, and a normal "
                           "nonzero yeast & mold (200–5,000 CFU/g). Not endorsed as safe.", CTX))
    rows = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
             Paragraph(esc(clean_value(p.analytes.get("tymc", {}).get("value"), "CFU/g")), cellc),
             Paragraph(f'{thc_value(p, "total_thc"):g}%', cellc), coa_cell(p)]
            for p in ctx["cleaner"][:40]]
    if rows:
        story.append(tbl(["Product", "Testing Date", "Producer", "Yeast & Mold", "Total THC", "COA"], rows,
                         [3.0*inch, 0.95*inch, 2.6*inch, 1.6*inch, 1.05*inch, 1.3*inch], hc=PURPLE, band="#ead9f2"))
    else:
        story.append(Paragraph("Not enough non-infused flower with a normal-range yeast & mold reading this run.", cellc))
    if ctx["cleaner_review"]:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Lower-Concern Candidates — Potency Data Missing</b> ({len(ctx['cleaner_review'])}): "
                               "otherwise-clean flower whose Total THC is missing or a parser conflict — verify potency "
                               "on the COA.", body_st))

    # ---------------- NO SIGNIFICANT FINDINGS ----------------
    story.append(H("No Significant Findings"))
    story.append(Paragraph("These categories were tested and parsed, but no result crossed the CannaScope "
                           "threshold in this run (verified against the raw parsed data).", CTX))
    rows = [[Paragraph(esc(title), cellb), (f'{zc["parsed"]}/{zc["total"]}' if zc else "—"),
             Paragraph("No result crossed the CannaScope threshold.", cell)] for title, zc in nsf]
    story.append(tbl(["Category", "Parsed / Total", "Result"], rows, [2.8*inch, 1.7*inch, 5.4*inch]))

    # ---------------- POTENTIAL STATUTE & REGULATORY FLAGS (V9 add-on) ----------------
    cflags = ctx.get("compliance_flags", [])
    story.append(H("Potential Statute & Regulatory Flags to Evaluate", color=RED))
    story.append(Paragraph(
        "<b>Leads to EVALUATE — not legal determinations and not an adjudication.</b> Potential "
        "Connecticut statutory / regulatory matters for a qualified compliance officer or attorney to "
        "review, derived ONLY from COA testing results CannaScope can read: a result over the "
        "Connecticut legal limit, a detected zero-tolerance pathogen, or a failed pesticide / "
        "residual-solvent panel. CannaScope cannot confirm whether a batch was released, remediated, or "
        "destroyed, and does not resolve exact rule text — each citation is at the authority level and "
        "must be verified in eRegulations. Categories needing licensing / operational data (licensing "
        "scope, traceability / diversion, labeling / marketing, security, recordkeeping, transport) are "
        "NOT assessed here. Verify every item against the live COA and current law.", CTX))
    if cflags:
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc),
                 Paragraph(esc(tcase(r["p"].product_name)), cell), td(r["p"]), Paragraph(pr(r["p"]), cell),
                 Paragraph(esc(lab_name(r["p"], lmap)), cell),
                 Paragraph(esc(r["finding"]), cell),
                 Paragraph(esc(r["cited_authority"]) + ' <font color="#C0392B"><b>[verify]</b></font>', cell),
                 Paragraph("Potential — review", cellc),
                 coa_cell(r["p"])]
                for i, r in enumerate(cflags[:MAX_TABLE_ROWS], 1)]
        story.append(tbl(["#", "Product", "Testing Date", "Producer", "Lab",
                          "Potential Issue (verify on COA)", "Cited Authority (verify in eRegulations)",
                          "Status", "COA"], rows,
                         [0.35*inch, 1.7*inch, 0.8*inch, 1.4*inch, 1.2*inch, 2.4*inch, 2.0*inch, 1.0*inch, 0.95*inch],
                         hc=RED, band="#f8d2d0"))
        overflow_note(len(cflags), "compliance_flags.csv")
        story.append(Spacer(1, 3))
        story.append(Paragraph("<b>Status</b> potential_violation = the COA shows an over-limit / detected "
                               "/ failed result, but whether the batch was released vs remediated / destroyed "
                               "is unknown to CannaScope. Every flag here is for human review only.", note_st))
    else:
        story.append(Paragraph("No COA-derived testing / product-quality flags in this run (no "
                               "over-legal-limit result, detected pathogen, or failed panel among verified "
                               "findings).", cellc))

    # ---------------- CT CANNABIS OMBUDSMAN — MEDICAL PATIENT SAFETY (V9 add-on) ----------------
    from reportlab.platypus import HRFlowable
    omb = ctx.get("ombudsman", [])
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.4, color=NAVY, spaceBefore=2, spaceAfter=6))
    story.append(Paragraph("CT CANNABIS OMBUDSMAN — MEDICAL PATIENT SAFETY REVIEW", H1))
    story.append(Paragraph("PRODUCTS CLOSEST TO A CONTAMINANT LIMIT",
                           ParagraphStyle("ombsub", parent=H1, fontSize=13, leading=16, textColor=PURPLE)))
    story.append(Paragraph("For the Office of the Cannabis Ombudsman. These products passed testing but "
                           "came closest to a Connecticut action limit on one or more contaminants. This is "
                           "patient-safety information for review and advisory purposes — not a finding that "
                           "any product failed or is unsafe, and not medical advice.", CTX))
    if omb:
        rows = []
        for i, r in enumerate(omb[:MAX_TABLE_ROWS], 1):
            p, d = r["p"], r["d"]; unit = d.get("unit", "")
            rows.append([
                Paragraph(f'<b>{i}</b>', cellc),
                Paragraph(esc(tcase(p.product_name)), cell), Paragraph(pr(p), cell),
                Paragraph(esc(f'{r["cls"]} — {d.get("name", "")}'), cell),
                Paragraph(esc(f'{clean_value(d.get("value"), unit)} / {clean_value(d.get("ct_limit"), unit)}'), cellc),
                Paragraph(f'<b>{r["ct_pct"]:.1f}%</b>', cellc),
                Paragraph(esc(r["tier"]), cellc),
                Paragraph(esc(r["note"]), cell),
                Paragraph(coa(p) if p.report_url else "COA not provided", coacell)])
        story.append(tbl(["#", "Product", "Producer", "Contaminant (class — analyte)", "Result / CT Limit",
                          "% Of Limit", "Tier", "Why It Matters (patient)", "COA"], rows,
                         [0.35*inch, 1.7*inch, 1.4*inch, 1.85*inch, 1.5*inch, 0.8*inch, 0.95*inch, 2.95*inch, 0.95*inch],
                         hc=PURPLE, band="#ead9f2"))
        overflow_note(len(omb), "ombudsman_closeness.csv")
    else:
        story.append(Paragraph("No products came within the configured margin of a contaminant limit in "
                               "the data reviewed.", cellc))
    story.append(Spacer(1, 3))
    story.append(Paragraph("This section is patient-safety information for the Office of the Cannabis "
                           "Ombudsman and is not medical advice or a substitute for a provider's or "
                           "pharmacist's judgment. Exact measured values and limits are shown; products "
                           "listed here PASSED testing.", note_st))

    # ================= VALIDATION & DIAGNOSTICS (LAST) =================
    story.append(PageBreak())
    story.append(H("Validation & Diagnostics"))
    story.append(Paragraph("Supporting validation detail. Findings above are the report; this documents how they were "
                           "checked. Status: " + esc(status) + ".", CTX))

    # ---- COA Source-Binding Audit (V11.1 integrity patch) ----
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
    rows = []
    for c in ctx["zero"]:
        col = "#C0392B" if c["status"] == "DRAFT WARNING" else ("#1E7E34" if c["status"] == "OK" else "#444")
        rows.append([Paragraph(esc(c["category"]), cell), str(c["flagged"]), f'{c["parsed"]}/{c["total"]}',
                     Paragraph(f'<font color="{col}"><b>{esc(c["status"])}</b></font>', cell)])
    story.append(tbl(["Category", "Flagged", "Parsed / Total", "Status"], rows,
                     [2.8*inch, 1.2*inch, 1.5*inch, 2.4*inch], big=False))
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
    story.append(Paragraph("Data Quality & Debug Log", miniH))
    rows = [[Paragraph(esc(k), cell), Paragraph(esc(str(v)), cell)] for k, v in ctx["debug"].items()]
    story.append(tbl(["Metric", "Value"], rows, [4.4*inch, 5.4*inch], big=False))

    def _footer(canvas, d_):
        canvas.saveState(); w, _h = PAGE
        canvas.setFont(BFB, 7.5); canvas.setFillColor(colors.HexColor("#333"))
        canvas.drawCentredString(w/2, 0.4*inch, "Every flag is a lead, not a conclusion. Verify against the live COA.")
        canvas.setFont(BF, 6.5); canvas.setFillColor(colors.HexColor("#666"))
        canvas.drawString(0.3*inch, 0.22*inch, f"{APP_NAME}  |  {status}  |  Created {dcreated} {tcreated}  |  Window {window}")
        canvas.drawRightString(w-0.3*inch, 0.22*inch, f"Page {d_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    print(f"Wrote {out_path}")


def producer_short_label(full_label):
    return re.sub(r"\s*\([^()]*\)\s*$", "", full_label).strip() or full_label


def tcase_dba(p, ident):
    return ident.resolve(p.producer)["label"]


def _zero_text(cat, zc):
    if zc and zc["status"] == "DRAFT WARNING":
        return (f"DRAFT WARNING — {cat} returned zero results but live source verification suggests a "
                f"parser / filter error. {zc['note']} Routed to the Zero-Result Verification Queue.")
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
    P = lambda n: os.path.join(OUT_DIR, n)
    pmap, lmap, ident, watch = ctx["pmap"], ctx["lmap"], ctx["ident"], ctx["watch"]

    def row(p, d=None):
        return [tcase(p.product_name), ident.resolve(p.producer)["label"], tcase(p.dosage_form),
                test_date(p), lab_name(p, lmap), p._coa_status, p.registration_number, p.report_url]

    # validated flagged products
    _w(P("CannaScope_CT_Beta_V11_1_Validated_Flagged.csv"),
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

    # high-THC flower
    _w(P("high_thc_flower_noninfused.csv"),
       ["rank", "product", "producer_dba", "type", "lab", "field", "value_pct", "over_35_by",
        "coa", "report_url", "coa_match_status"],
       [[i, tcase(p.product_name), ident.resolve(p.producer)["label"], tcase(p.dosage_form),
         lab_name(p, lmap), key, f"{val:g}", f"{val-THC_REVIEW_PCT:.1f}", p.registration_number,
         p.report_url, p._coa_status] for i, (p, key, val) in enumerate(ctx["thc_flower"], 1)])

    # potency references — infused and vape/extract kept in SEPARATE files
    for fn, items in (("infused_products_potency.csv", ctx["infused_potency"]),
                      ("vape_concentrate_extract_potency.csv", ctx["extract_potency"])):
        _w(P(fn),
           ["product", "producer_dba", "type", "lab", "highest_cannabinoid_pct", "coa", "report_url"],
           [[tcase(p.product_name), ident.resolve(p.producer)["label"], tcase(p.dosage_form),
             lab_name(p, lmap), f"{val:g}", p.registration_number, p.report_url]
            for (p, key, val) in items])

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
       ["product", "producer_dba", "lab", "test_date", "rule_category", "finding",
        "cited_authority", "authority_unverified", "status", "severity", "confidence",
        "recommended_review", "coa", "report_url"],
       [[tcase(r["p"].product_name), ident.resolve(r["p"].producer)["label"], lab_name(r["p"], lmap),
         test_date(r["p"]), r["rule_category"], r["finding"], r["cited_authority"],
         r["authority_unverified"], r["status"], r["severity"], r["confidence"],
         r["recommended_review"], r["p"].registration_number, r["p"].report_url]
        for r in ctx["compliance_flags"]])

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

    # identity + source confidence
    _w(P("producer_dba_identity_confidence.csv"),
       ["legal_entity", "common", "brands", "parent", "source_confidence_pct", "source"],
       [[r.get("legal", ""), r["common"], " | ".join(r["brands"]), r["parent"], r["confidence"], r["source"]]
        for r in ident.cache.values()])

    # self-audit
    _w(P("self_audit.csv"), ["check", "count", "status"],
       [[i["issue"], i["count"], i["status"]] for i in ctx["audit"]])

    # debug log
    _w(P("debug_log.csv"), ["metric", "value"], [[k, v] for k, v in ctx["debug"].items()])
    json.dump(ctx["debug"], open(P("debug_log.json"), "w"), indent=2)

    # V11.1 COA source-binding integrity exports ----------------------------------
    # Full provenance for every published flagged value (source COA == linked COA).
    prov = ctx.get("provenance_rows", [])
    _w(P("COA_Provenance_Audit.csv"),
       ["product", "producer", "lab", "coa_number", "registry_coa_url", "extracted_result_coa_url",
        "published_row_coa_url", "sample_id", "batch_id", "biotrack_uid", "testing_date", "analyte",
        "value", "unit", "legal_limit", "coa_match_status", "value_verified_in_linked_coa",
        "extraction_source_confirmed"],
       [[r["product"], r["producer"], r["lab"], r["coa_number"], r["registry_coa_url"],
         r["extracted_result_coa_url"], r["published_row_coa_url"], r["sample_id"], r["batch_id"],
         r["biotrack_uid"], r["testing_date"], r["analyte"], r["value"], r["unit"], r["legal_limit"],
         r["coa_match_status"], r["value_verified_in_linked_coa"], r["extraction_source_confirmed"]]
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
    with open(P("CannaScope_CT_Beta_V11_1_Executive_Summary.txt"), "w") as f:
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
# V11.1 COA SOURCE-BINDING INTEGRITY AUDIT
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


def audit_published_coa_sources(pub_raw, watch):
    """Independent final audit: re-open each would-be-published product's OWN cached
    COA and confirm every flagged value is literally present in THAT document.
    Returns (verified_products, mismatch_rows, provenance_rows, metrics)."""
    verified, mismatches, provenance = [], [], []
    n_verified = n_fail = 0
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
        bad = []
        for d in drivers:
            present = _value_in_coa_text(d.get("value"), text)
            if present:
                n_verified += 1
            else:
                n_fail += 1
                bad.append(d)
            provenance.append(dict(
                product=p.product_name, producer=p.producer, lab=prov["lab"],
                coa_number=p.registration_number, registry_coa_url=p.report_url,
                extracted_result_coa_url=p.report_url, published_row_coa_url=p.report_url,
                sample_id=prov["sample_id"], batch_id=prov["batch_id"], biotrack_uid=prov["biotrack_uid"],
                testing_date=test_date(p), analyte=d.get("name"), value=d.get("value"),
                unit=d.get("unit", ""), legal_limit=d.get("ct_limit"),
                coa_match_status=getattr(p, "_coa_status", ""),
                value_verified_in_linked_coa=("Yes" if present else "NO"),
                extraction_source_confirmed=("Yes" if present else "No")))
        if bad:
            mismatches.append(dict(p=p, prov=prov,
                analytes="; ".join(f"{d.get('name')} {clean_value(d.get('value'), d.get('unit',''))}" for d in bad)))
        else:
            verified.append(p)
    metrics = dict(
        published_rows_verified_against_linked_coa=n_verified,
        exact_value_link_verification_failures=n_fail,
        coa_source_mismatch_count=len(mismatches),
        rows_excluded_for_coa_source_mismatch=len(mismatches),
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
    ap.add_argument("--keep-clean-pdfs", action="store_true",
                    help="keep EVERY COA PDF in the cache (not just flagged ones), building a "
                         "complete local 'sources' bundle for fast offline re-runs.")
    ap.add_argument("--offline", action="store_true",
                    help="never touch the network: use the bundled Registry Cache + cached COA "
                         "PDFs only. Seed the bundle first with one online run (use --keep-clean-pdfs).")
    ap.add_argument("--no-ocr", action="store_true",
                    help="force OCR OFF (image-only COAs are skipped). Default is crash-proof isolated OCR.")
    ap.add_argument("--ocr-isolated", action="store_true", help="(default) kept for backward compatibility")
    ap.add_argument("--ocr-workers", type=int, default=4,
                    help="max concurrent OCR subprocesses (overload guard; default 4)")
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
    todo = [p for p in products if v4.coa_key(p) not in ledger]
    print(f"Scanning {len(todo)} COAs with {args.workers} workers ...\n")

    all_results, keep, failures = [], [], []
    new_clean = set(); lock = threading.Lock(); done = 0
    cache_reuse = 0; fetched = 0; broken = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_product, p, session, args.threshold): p for p in todo}
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

    print("\nBuilding validated analytics ...")
    watch = args.threshold
    for p in all_results:
        p._watch = watch

    ident = Identity(pmap, all_results)

    # report-flagged set (trustworthy severity) and publishable subset
    flagged = [p for p in keep if v5.report_severity(p, watch) in ("RED", "ORANGE", "YELLOW") or p.thc_flags or v5.pathogen_detections(p)]
    pub_raw = [p for p in flagged if p._coa_status in PUBLISHABLE]

    # --- V11.1 COA SOURCE-BINDING AUDIT: re-verify every would-be-published value against
    #     its OWN linked COA; exclude any mismatch to a review queue before anything is
    #     derived/published. Integrity over coverage.
    pub, source_mismatches, provenance_rows, src_metrics = audit_published_coa_sources(pub_raw, watch)
    multi_coa = detect_multiple_coa_alerts(all_results)
    src_metrics["multiple_coa_alert_count"] = len(multi_coa)
    src_metrics["pass_fail_coa_conflict_count"] = sum(1 for a in multi_coa if a.get("conflict"))
    if source_mismatches:
        print(f"  COA SOURCE AUDIT: excluded {len(source_mismatches)} product(s) whose flagged value "
              "could not be re-verified in their own linked COA -> COA Source Mismatch Review queue.")
    else:
        print(f"  COA SOURCE AUDIT: all {src_metrics['published_rows_verified_against_linked_coa']} "
              "published flagged values re-verified in their own linked COA.")

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
    remediation = [p for p in all_results if is_noninfused_flower(p)
                   and p.analytes.get("tymc", {}).get("value") is not None
                   and p.analytes["tymc"]["value"] <= 200
                   and v5.report_severity(p, watch) is None and not p.thc_flags]
    cleaner, cleaner_review = [], []
    for p in all_results:
        if not is_noninfused_flower(p):
            continue
        if v5.report_severity(p, watch) or p.thc_flags or v5.unquantified_findings(p) or v5.pathogen_detections(p):
            continue
        ym = p.analytes.get("tymc", {}).get("value")
        if ym is None or not (200 <= ym <= 5000):
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

    # producer / lab trend rows (keyed by the concise producer-level label)
    reviewed_c = Counter(producer_label_short(p.producer, ident) for p in all_results)
    flagged_c = Counter(producer_label_short(p.producer, ident) for p in pub)
    issue_c = defaultdict(Counter); conf_of = {}
    for p in all_results:
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
        "flagged_total": len(flagged),
        "flagged_published": len(pub),
        "coa_verification_queue": len(flagged) - len(pub),
        "high_thc_noninfused_flower": len(thc_flower),
        "implausible_flower_potency_excluded": implausible_flower,
        "infused_potency_ref": len(infused_potency),
        "vape_concentrate_extract_potency_ref": len(extract_potency),
        "potency_parser_conflicts": sum(1 for p in all_results if thc_conflict(p)),
        "zero_result_draft_warnings": sum(1 for c in zero if c["status"] == "DRAFT WARNING"),
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
        "ombudsman_near_limit_products": len(ombudsman),
    })
    debug.update(src_metrics)   # V11.1 COA source-binding audit metrics
    status = report_status(debug, remaining, draft_zero)
    # V11.1 source-integrity status rule: any published row whose value can't be verified in
    # its linked COA -> FAIL SOURCE VALIDATION (should never occur; such rows are excluded
    # first). If mismatches WERE found and excluded, the run can't be a clean PASS.
    if src_metrics["published_rows_verified_against_linked_coa"] != (
            sum(1 for p in pub for d in v5.quantified_details(p, watch) if v5.is_flag_driver(d))):
        status = "FAIL SOURCE VALIDATION"
    elif src_metrics["coa_source_mismatch_count"] and status == "PASS":
        status = "PASS WITH WARNINGS"
    debug["report_status"] = status
    draft = status in ("DRAFT", "FAIL", "FAIL SOURCE VALIDATION")

    ctx = dict(draft=draft, status=status, pmap=pmap, lmap=lmap, ident=ident, watch=watch, window=window,
               flagged=flagged, exec_rows=exec_rows, audit=audit, queue=queue,
               producer_rows=producer_rows, lab_rows=lab_rows, analyte_items=analyte_items,
               pesticides=pests, solvents=solvs, mycotoxins=mycos, pathogens=paths,
               thc_flower=thc_flower, infused_potency=infused_potency,
               extract_potency=extract_potency, remediation=remediation,
               cleaner=cleaner, cleaner_review=cleaner_review, zero=zero, debug=debug,
               compliance_flags=compliance_flags, ombudsman=ombudsman,
               source_mismatches=source_mismatches, multi_coa=multi_coa, provenance_rows=provenance_rows,
               src_metrics=src_metrics,
               n_reviewed=len(all_results), n_pub=len(pub), n_queue=len(flagged)-len(pub),
               n_red=sev_counts.get("RED", 0), n_org=sev_counts.get("ORANGE", 0),
               n_yel=sev_counts.get("YELLOW", 0), n_thc=len(thc_flower))

    write_outputs(ctx)
    out_path, report_no = next_report_path(status)
    build_pdf(out_path, report_no, ctx)

    import shutil
    # copy to the working folder under the SAME unique name (never overwrites)
    visible = os.path.join(os.path.dirname(os.path.abspath(OUT_DIR)), os.path.basename(out_path))
    try:
        shutil.copy2(out_path, visible)
    except OSError:
        visible = out_path

    print("\n" + "=" * 74)
    print(f"  CANNASCOPE CT BETA V11.1 — REPORT #{report_no} [{status}] IS READY")
    print(f"    {visible}")
    print(f"  Reviewed {len(all_results):,} • Published {len(pub):,} "
          f"({sev_counts.get('RED',0)} Red, {sev_counts.get('ORANGE',0)} Orange, "
          f"{sev_counts.get('YELLOW',0)} Yellow, {len(thc_flower)} High-THC flower) • "
          f"{len(flagged)-len(pub)} in COA queue")
    print(f"  Self-audit remaining: {len(remaining)} • Zero-result warnings: "
          f"{sum(1 for c in zero if c['status']=='DRAFT WARNING')}")
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
# PATIENT-REPORTED PRODUCT CONCERN — on-demand personalized patient PDF (V11.1)
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
PATIENT_PREFIX = "CannaScope_CT_Beta_V11_1_Personalized_Product_Concern_Report"
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
    # V11.1 SOURCE-BINDING: independently re-verify that EVERY value we will display
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
    out = []
    for same_product, same_size, same_form, dist, r, rp in chosen:
        summ = _analyze_sibling(rp, pin, session, watch)
        out.append(dict(row=r, p=rp, days_apart=(None if dist >= 10 ** 9 else dist),
                        same_form=(same_form == 0), same_size=(same_size == 0),
                        same_product=(same_product == 0), product=r.get("PRODUCT-NAME"),
                        ndc=r.get(_NDC_COL, ""), **summ))
    return out


def _patient_unique_path(ident_token):
    """output/patient_concerns/<PREFIX>_<sanitized id>_<YYYYMMDD-HHMMSS>.pdf, never
    overwriting: if a name ever collides, increment rather than replace."""
    os.makedirs(PATIENT_OUT_DIR, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (ident_token or "unresolved")).strip("-") or "unresolved"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{PATIENT_PREFIX}_{safe}_{stamp}"
    path = os.path.join(PATIENT_OUT_DIR, base + ".pdf")
    n = 2
    while os.path.exists(path):
        path = os.path.join(PATIENT_OUT_DIR, f"{base}_{n}.pdf")
        n += 1
    return path


def build_patient_pdf(out_path, pin, res, analysis):
    """Render the personalized, patient-friendly PDF. Portrait letter."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer)

    BF, BFB = v4._setup_fonts()
    esc = v4._esc
    NAVY = colors.HexColor("#1F2D3D"); RED = colors.HexColor("#C0392B")
    AMBER = colors.HexColor("#9A7B0A"); GREEN = colors.HexColor("#1E7E34")
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

    story = []
    story.append(Paragraph("Personalized Product Concern Report", title_st))
    story.append(Paragraph("A personalized review of one product's lab-testing data, for a consumer concern", sub_st))
    story.append(Spacer(1, 6))
    created = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %I:%M %p %Z")
    story.append(Paragraph(f"Prepared {esc(created)} · {esc(APP_NAME)}", small))
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

    # V11.1 source-binding: any value that could not be re-verified in THIS COA is NOT
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

    # 6) Safety framing / next steps
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

    SimpleDocTemplate(out_path, pagesize=letter, leftMargin=0.7*inch, rightMargin=0.7*inch,
                      topMargin=0.6*inch, bottomMargin=0.7*inch,
                      title="Personalized Product Concern Report",
                      author=APP_NAME).build(story)


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
    ap.add_argument("--example", action="store_true",
                    help="run the built-in Nutmeg New Britain test fixture")
    ap.add_argument("--threshold", type=int, default=v4.DEFAULT_WATCH)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--no-related", action="store_true",
                    help="do NOT look up related/sibling COAs from the same producer")
    ap.add_argument("--related-n", type=int, default=PATIENT_RELATED_MAX,
                    help=f"max related sibling COAs to fetch + show (default {PATIENT_RELATED_MAX})")
    ap.add_argument("--related-window-days", type=int, default=PATIENT_RELATED_WINDOW_DAYS,
                    help=f"time window for 'close enough' siblings (default {PATIENT_RELATED_WINDOW_DAYS})")
    args = ap.parse_args(argv)

    if args.example:
        pin = dict(_EXAMPLE_FIXTURE)
    else:
        pin = dict(product=args.product, cultivator=args.cultivator, batch=args.batch,
                   ndc_stated=args.ndc, ndc_label=args.ndc_label, uid=args.uid, coa=args.coa,
                   qr=args.qr, harvest=args.harvest, packaged=args.packaged, tested=args.tested,
                   exp=args.exp, thca=args.thca, thc=args.thc, concern=args.concern)
        if not any(pin.get(k) for k in ("product", "cultivator", "batch", "ndc_stated",
                                        "ndc_label", "uid", "coa", "qr")):
            ap.error("provide at least one identifier (e.g. --ndc, --batch, --qr, --product), "
                     "or use --example for the built-in test case.")

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

    print("Resolving the product from the identifiers you provided ...")
    rows = _patient_registry_rows(session, offline=args.offline)
    res = resolve_patient_product(rows, pin, session=session, offline=args.offline)
    if res["row"]:
        print(f"  Resolved via: {res['lookup_path']}  ({', '.join(res['matched_on'])})")
        if res["conflicts"]:
            print(f"  Discrepancies surfaced: {len(res['conflicts'])}")
    else:
        print("  Could not confidently resolve the product — the PDF will explain what is missing.")

    analysis = None
    if res["row"]:
        print("Fetching and parsing the COA ...")
        p = _row_to_product(res["row"])
        analysis = analyze_patient_product(p, pin, session, args.threshold, offline=args.offline)
        print(f"  COA {'parsed' if analysis['coa_fetched'] else 'not retrieved'}; "
              f"flags present: {analysis['any_flag']}")
        if not args.no_related:
            print("Looking up related/sibling COAs from the same producer ...")
            analysis["related"] = find_related_coas(
                res["row"], p, rows, pin, session, args.threshold,
                max_n=args.related_n, window_days=args.related_window_days, offline=args.offline)
            print(f"  {len(analysis['related'])} related COA(s) linked"
                  + (f"; {sum(1 for s in analysis['related'] if s['idmatch'])} match an ID on the package"
                     if any(s['idmatch'] for s in analysis['related']) else ""))
    else:
        analysis = dict(coa_fetched=False, classes={}, pathogens=[], compliance=[],
                        corroboration=[], coa_url="", testing_date="", parse_note="",
                        coa_status="", pesticide_panel="", solvent_panel="", any_flag=False, p=None)

    token = (pin.get("batch") or pin.get("ndc_label") or pin.get("ndc_stated")
             or pin.get("coa") or (res["row"] or {}).get(_NDC_COL) or "unresolved")
    out_path = _patient_unique_path(token)
    build_patient_pdf(out_path, pin, res, analysis)
    print(f"\nWrote personalized PDF:\n  {out_path}")
    return out_path


if __name__ == "__main__":
    # Two features, two clean subcommands (old aliases kept so nothing breaks):
    #   concern  : Personalized Product Concern Report (one product, consumer concern)
    #   statewide: Statewide Transparency Report (whole-market scan) — also the default
    _sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if _sub in ("concern", "consumer-concern", "patient-concern"):
        main_patient(sys.argv[2:])
    elif _sub in ("statewide", "report", "market"):
        sys.argv = [sys.argv[0]] + sys.argv[2:]   # strip the subcommand for main()'s argparse
        main()
    else:
        main()
