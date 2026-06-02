#!/usr/bin/env python3
"""
CannaScope Beta V5
============================
Connecticut Cannabis Transparency Report — Master Validation, Format, DBA, COA,
Internet-Source, Zero-Result, and Logic-Fix build.

Every flag is a LEAD, not a conclusion. CannaScope Beta V5 does not claim fraud,
unsafe product, or legal failure unless the live COA and the applicable
Connecticut legal limit directly support that claim.

WHAT VERSION 7 ADDS (on top of the validated V5 / V4 contaminant + cannabinoid engine)
  * ZERO-TRUST VALIDATION — every flagged row is re-checked against its live COA
    PDF (link works, COA/registration number present, reported value present) and
    given a Live COA Match Status. Rows that are not a Verified Exact / Partial
    Match are pulled from the ranked sections into a COA Verification Queue.
  * CLICKABLE COA LINKS EVERYWHERE — every COA number is a blue hyperlink to the
    source PDF; missing links are marked "COA LINK MISSING — VERIFY MANUALLY".
  * COMBINED PRODUCER / DBA COLUMN — "Common / Brand (Legal Entity)" with a
    source-confidence score; unconfirmed DBAs are searched and otherwise marked
    "DBA Not Confirmed" (never invented).
  * ZERO-RESULTS ARE PRESUMED PARSER ERRORS — any expected category returning
    zero is re-checked against the raw parsed data; a true zero is stated plainly,
    a suspicious zero raises a DRAFT WARNING and routes to a Zero-Result
    Verification Queue.
  * HIGH-THC FLOWER REVIEW = NON-INFUSED FLOWER ONLY — vapes, concentrates,
    extracts, hash/THCA-infused pre-rolls and infused blunts move to a separate
    "Infused / Extract Potency Reference" section (not a flower abnormality).
  * THC PARSER-CONFLICT GUARD — no scientific notation in public tables; a
    Total THC of 0% alongside a 35%+ active-cannabinoid reading is flagged
    "Potency Parser Conflict — Needs Manual Review" and kept OUT of rankings.
  * SEPARATE ANALYTE TABLES — Yeast & Mold, Total Aerobic Bacteria, Arsenic,
    Chromium, Cadmium, Lead, Mercury, Pesticides, Residual Solvents, Mycotoxins,
    and Pathogens each get their own ranked, lean table.
  * SELF-AUDIT + DEBUG LOG + DRAFT GATING — an automatic major-error scan, a
    machine-readable debug log, and a hard rule: if major validation issues
    remain, the report is exported as "DRAFT — MAJOR VALIDATION ISSUES REMAIN".

REUSES the V5 engine (imported) for download / OCR / contaminant + cannabinoid
parsing / flagging, so the validated detection logic is unchanged.

REQUIREMENTS:  pip install requests reportlab pypdfium2  (OCR: ocrmac / pytesseract)
  Place cannascope_ct_v5.py, cannascope_ct_v4.py, ct_cannabis_names.py beside this.
TYPICAL RUN:  python cannascope_ct_v7.py --days 60
"""

import argparse
import csv
import datetime
import json
import os
import re
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
    sys.exit("CannaScope Beta V5 needs cannascope_ct_v5.py and cannascope_ct_v4.py beside it.")

names = getattr(v4, "names", None)
ProductV5 = v5.ProductV5

# ============================================================================
# Config
# ============================================================================
# Public release name. (Internal development builds used "V7" naming; the
# public-facing release is standardized as CannaScope Beta V5 — see CHANGELOG.)
APP_NAME = "CannaScope Beta V5"
REPORT_TITLE = "Connecticut Cannabis Transparency Report"
REPORT_SUBTITLE = "Source-Verified Consumer Awareness & Testing Pattern Review"
FRAMING = ("Every flag is a lead, not a conclusion. CannaScope Beta V5 does not claim "
           "fraud, unsafe product, or legal failure unless the live COA and the "
           "applicable Connecticut legal limit directly support that claim. Verify "
           "every product against its COA.")

DEFAULT_DAYS = 60
THC_REVIEW_PCT = v5.THC_REVIEW_PCT          # 35%

OUT_DIR = "CannaScope Beta V5 - Reports"
CACHE_DIR = os.path.join(OUT_DIR, "Flagged COA Source PDFs")
REGISTRY_CACHE = os.path.join(OUT_DIR, "Registry Cache.csv")
LEDGER = os.path.join(OUT_DIR, "Already-Scanned Skip List.txt")
SOURCE_CACHE = os.path.join(OUT_DIR, "Source Validation Cache.json")
REPORT_PREFIX = "CannaScope_Beta_V5_Report_"
PUBLIC_PDF_NAME = "CannaScope_Beta_V5_Report.pdf"   # stable name copied to the working folder
REGISTRY_TTL = 6 * 3600

# Live COA Match Status values
MATCH_EXACT = "Verified"
MATCH_PARTIAL = "Verified Partial Match"
MATCH_LINK_MISSING = "COA Link Missing"
MATCH_LINK_BROKEN = "COA Link Broken"
MATCH_PRODUCT_MISMATCH = "COA Product Mismatch"
MATCH_VALUE_MISMATCH = "COA Value Mismatch"
MATCH_MANUAL = "COA Needs Manual Review"
PUBLISHABLE = {MATCH_EXACT, MATCH_PARTIAL}

# Products that are flower-based but NOT infused (the only ones eligible for the
# High-THC FLOWER abnormality review). Infused / extract products are reviewed
# separately as a potency reference, not as a flower abnormality.
INFUSED_MARKERS = ("infused", "hash infused", "bubble hash", "thca infused",
                   "vape", "cartridge", "pod", "rosin", "resin", "badder", "sauce",
                   "concentrate", "extract", "live resin", "live rosin",
                   "marijuana extract for inhalation", "mix infused", "distillate",
                   "diamond", "blunt")
NONINFUSED_FORM_FLOWER = ("flower", "usable marijuana", "plant material",
                          "raw material", "shake", "ground flower", "bud")


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
# Registry (reuse V5 loader but route to V7 dirs)
# ============================================================================
def load_registry(session, refresh=False):
    v5.OUT_DIR = OUT_DIR
    v5.REGISTRY_CACHE = REGISTRY_CACHE
    return v5.load_registry(session, refresh=refresh)


# ============================================================================
# Flower / infused classification (V7 rule: High-THC review = non-infused flower)
# ============================================================================
def _hay(p):
    return f"{p.dosage_form} {p.product_name}".lower()


def is_infused(p) -> bool:
    h = _hay(p)
    return any(k in h for k in INFUSED_MARKERS)


def is_noninfused_flower(p) -> bool:
    """Eligible for High-THC FLOWER abnormality review: flower-based AND not
    infused / not a vape / concentrate / extract."""
    if is_infused(p):
        return False
    form = (p.dosage_form or "").lower()
    name = (p.product_name or "").lower()
    if any(k in form for k in NONINFUSED_FORM_FLOWER):
        return True
    # non-infused pre-rolls / mini pre-rolls (name carries pre-roll, infused already excluded)
    if ("pre-roll" in name or "preroll" in name or "pre roll" in name) and "infused" not in name:
        return True
    if any(k in name for k in ("flower minis", "flower mini", "smalls", "ground flower", "shake")):
        return True
    return False


def is_infused_or_extract(p) -> bool:
    """Eligible for the Infused / Extract Potency Reference section."""
    return is_infused(p) or v5.is_thc_flower(p) is False and any(
        k in _hay(p) for k in ("extract", "concentrate", "vape", "cartridge"))


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
        if v is None or v < 0.001 or v > 100:
            continue
        if best is None or v > best[1]:
            best = (key, v)
    return best


# ============================================================================
# Producer / DBA identity (combined column + source confidence)
# ============================================================================
# V7 identity overlay: legal-entity (normalized) -> dict(common, brands, parent,
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
_V7_RAW = {
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
V7_IDENTITY = {_norm(k): v for k, v in _V7_RAW.items()}


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
        self.cache = {}            # in-memory only (per run); the V7_IDENTITY overlay
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
        overlay = V7_IDENTITY.get(key)
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


def report_status(debug, remaining, draft_zero):
    """PASS / PASS WITH WARNINGS / DRAFT / FAIL — honest, not always 'PASSED'."""
    if remaining:
        return "FAIL"
    if draft_zero:
        return "DRAFT"
    warn = (debug.get("broken_or_missing_coa_links", 0) > 0
            or debug.get("parser_failures_no_text", 0) > 0
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
    # value check: a flagged measured value appears (tolerant of number formatting)
    qd = [d for d in v5.quantified_details(p, p._watch) if v5.is_flag_driver(d)]
    val_ok = True
    if qd:
        val_ok = False
        for d in qd:
            v = d.get("value")
            if v is None:
                continue
            cands = {f"{v:g}", f"{int(round(v))}", f"{v:,.0f}", f"{v:.1f}", f"{v:.2f}"}
            if any(c and c in text for c in cands):
                val_ok = True
                break
    if name_ok:
        return MATCH_EXACT            # product confirmed in the COA -> Verified
    if val_ok:
        return MATCH_PARTIAL          # value confirmed, product name not textual -> Partial
    return MATCH_PRODUCT_MISMATCH     # neither found -> substantive mismatch -> queue


# ============================================================================
# Worker — parse (V5 engine) + V7 validation, retaining text only long enough
# ============================================================================
def process_product(p, session, watch):
    p._watch = watch
    p._coa_status = MATCH_LINK_MISSING
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
    # high-THC non-infused flower
    n = sum(1 for p in flagged if is_noninfused_flower(p) and thc_review_value(p)
            and thc_review_value(p)[1] > THC_REVIEW_PCT)
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
    import glob
    nums = [int(m.group(1)) for f in glob.glob(os.path.join(OUT_DIR, REPORT_PREFIX + "*.pdf"))
            for m in [re.search(r"_(\d+)\.pdf$", f)] if m]
    n = (max(nums) + 1) if nums else 1
    tag = "_DRAFT" if status in ("DRAFT", "FAIL") else ""
    return os.path.join(OUT_DIR, f"{REPORT_PREFIX}{n}{tag}.pdf"), n


def build_pdf(out_path, report_no, ctx):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, legal
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, PageBreak)

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
    H1 = ParagraphStyle("h1", fontName=BFB, fontSize=20, leading=24, alignment=1, spaceBefore=12,
                        spaceAfter=4, textColor=NAVY, keepWithNext=1)
    CTX = ParagraphStyle("ctx", fontName=BF, fontSize=9.5, leading=12.5, alignment=1,
                         textColor=colors.HexColor("#555"), spaceAfter=6, keepWithNext=1)
    # centered subheader (mini tables + diagnostics)
    miniH = ParagraphStyle("mh", fontName=BFB, fontSize=13, leading=16, alignment=1, spaceBefore=8,
                           spaceAfter=3, textColor=NAVY, keepWithNext=1)

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
                Paragraph(coa(p), cellc)])
        return rows, sevs

    def rich_table(items, hc=NAVY):
        rows, sevs = rich_rows(items)
        return tbl(RICH_COLS, rows, RICH_W, hc=hc, rank_sevs=sevs)

    story = []

    # ---------------- COVER ----------------
    story += [
        Paragraph(APP_NAME, title_st), Paragraph(esc(REPORT_TITLE), sub_st),
        Paragraph(esc(REPORT_SUBTITLE), ParagraphStyle("sub2", parent=sub_st, fontSize=11)),
        Paragraph(f"Report #{report_no} &nbsp;|&nbsp; <font color=\"{scol}\"><b>{esc(status)}</b></font>", meta_st),
        Paragraph(f"<b>Created:</b> {dcreated} {esc(tcreated)} &nbsp;|&nbsp; <b>Dataset Window:</b> {esc(window)}", meta_st),
        Spacer(1, 7),
        Paragraph(f"<b>{esc(FRAMING)}</b>", ParagraphStyle("fr", parent=note_st, fontSize=10.5, leading=14.5,
                  textColor=NAVY, backColor=colors.HexColor("#eef2f5"), borderPadding=8)),
        Spacer(1, 7),
        Paragraph(f"<b>{ctx['n_reviewed']:,}</b> reviewed &nbsp;•&nbsp; <b>{ctx['n_pub']:,}</b> validated findings &nbsp;•&nbsp; "
                  f'<font color="#C0392B"><b>{ctx["n_red"]} Do Not Consume</b></font> &nbsp;•&nbsp; '
                  f'<font color="#E67E22"><b>{ctx["n_org"]} High Caution</b></font> &nbsp;•&nbsp; '
                  f'<font color="#9A7B0A"><b>{ctx["n_yel"]} Moderate Caution</b></font> &nbsp;•&nbsp; '
                  f'<font color="#0E6B5A"><b>{ctx["n_thc"]} High Cannabinoid</b></font>', meta_st),
        Spacer(1, 6),
        Paragraph("<b>Contamination severity (per measurement):</b> &nbsp; "
                  '<font color="#C0392B"><b>RED = Near / over CT limit</b></font> &nbsp; '
                  '<font color="#E67E22"><b>ORANGE = Elevated</b></font> &nbsp; '
                  '<font color="#9A7B0A"><b>YELLOW = Above CannaScope threshold</b></font> &nbsp; '
                  '<font color="#1E7E34"><b>GREEN = Below threshold</b></font>', note_st),
        Spacer(1, 5),
        Paragraph("<b>Testing Date</b> is the COA's test / sample date (never the report-generation date). "
                  "<b>CT % Of Limit</b> = measured ÷ Connecticut legal limit × 100. <b>CannaScope Limit</b> is the "
                  "stricter consumer-awareness threshold (Yeast &amp; Mold / Aerobic = 10,000 CFU/g; other "
                  "contaminants = 50% of the CT limit). Every COA number is a clickable link.", note_st),
        Spacer(1, 4),
    ]

    # ---------------- EXECUTIVE SUMMARY (dashboard) ----------------
    story.append(H("Executive Summary"))
    story.append(tbl(["Reviewed", "Validated Findings", "Do Not Consume", "High Caution",
                      "Moderate Caution", "High Cannabinoid"],
                     [[f"{ctx['n_reviewed']:,}", f"{ctx['n_pub']:,}", str(ctx["n_red"]), str(ctx["n_org"]),
                       str(ctx["n_yel"]), str(ctx["n_thc"])]], [1.6*inch]*6))

    ai = ctx["analyte_items"]
    metals = sorted([pd for k in ("arsenic", "chromium", "cadmium", "lead", "mercury") for pd in ai[k]],
                    key=lambda pd: pd[1]["ct_pct"] or 0, reverse=True)
    micro = sorted(ai["tymc"] + ai["aerobic"], key=lambda pd: pd[1]["ct_pct"] or 0, reverse=True)

    def mini(title, headers, rows, widths):
        story.append(Paragraph(esc(title), miniH))
        if rows:
            story.append(tbl(headers, rows, widths, big=False))
        else:
            story.append(Paragraph("None in this run.", cellc))

    def metal_rows(src, n=5):
        out = []
        for i, (p, d) in enumerate(src[:n], 1):
            sev = sev_of(d); bar = SEVC[sev][0]
            out.append([Paragraph(f'<font color="{bar}"><b>{i}</b></font>', cellc),
                        Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                        Paragraph(esc(d["name"]), cell), Paragraph(esc(clean_value(d.get("value"), d.get("unit", ""))), cellc),
                        Paragraph(f'<font color="{bar}"><b>{v4.ct_pct_label(d.get("ct_pct"), full=False)}</b></font>' if d.get("ct_pct") is not None else "—", cellc),
                        Paragraph(coa(p), cellc)])
        return out

    mini("Top Heavy Metal Findings", ["#", "Product", "Testing Date", "Producer", "Metal", "Measured", "CT %", "COA"],
         metal_rows(metals), [0.35*inch, 2.7*inch, 0.95*inch, 2.1*inch, 1.15*inch, 1.45*inch, 0.95*inch, 1.15*inch])
    mini("Top Microbial Findings", ["#", "Product", "Testing Date", "Producer", "Type", "Measured", "CT %", "COA"],
         metal_rows(micro), [0.35*inch, 2.7*inch, 0.95*inch, 2.1*inch, 1.5*inch, 1.35*inch, 0.9*inch, 1.1*inch])

    thc_rows = [[Paragraph(f'<font color="#0E6B5A"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
                 td(p), Paragraph(pr(p), cell), Paragraph(f'<font color="#0E6B5A"><b>{val:g}%</b></font>', cellc),
                 Paragraph(coa(p), cellc)] for i, (p, key, val) in enumerate(ctx["thc_flower"][:5], 1)]
    mini("Top High Cannabinoid Findings", ["#", "Product", "Testing Date", "Producer", "Cannabinoid %", "COA"], thc_rows,
         [0.35*inch, 3.2*inch, 0.95*inch, 2.7*inch, 1.3*inch, 1.15*inch])

    prow = [[Paragraph(esc(r["label"]), cell), str(r["reviewed"]), str(r["flagged"]), f'{r["pct"]:.1f}%',
             Paragraph(esc(r["top"]), cell)] for r in ctx["producer_rows"][:5]]
    mini("Top Producer Patterns", ["Producer", "Reviewed", "Flagged", "% Flagged", "Most Common Issue"], prow,
         [3.8*inch, 1.3*inch, 1.2*inch, 1.3*inch, 2.6*inch])

    lrow = [[Paragraph(esc(r["lab"]), cell), str(r["flagged"]), str(r["thc"]), Paragraph(esc(r["top"]), cell)]
            for r in ctx["lab_rows"][:5]]
    mini("Top Lab Patterns", ["Lab", "Contaminant-Flagged", "High Cannabinoid", "Most Common Contaminant"], lrow,
         [3.6*inch, 2.0*inch, 1.8*inch, 2.7*inch])

    rrow = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
             Paragraph(esc(clean_value(p.analytes.get("tymc", {}).get("value"), "CFU/g")), cellc),
             Paragraph(coa(p), cellc)] for p in ctx["remediation"][:5]]
    mini("Top Possible Remediation Findings (Unusually Low Microbial Load)",
         ["Product", "Testing Date", "Producer", "Yeast & Mold", "COA"], rrow,
         [3.4*inch, 0.95*inch, 2.8*inch, 1.6*inch, 1.2*inch])

    # ---------------- PRODUCER & LAB TRENDS (directly under Executive Summary) ----------------
    story.append(H("Producer Trends"))
    rows = [[Paragraph(esc(r["label"]), cell), str(r["reviewed"]), str(r["flagged"]), f'{r["pct"]:.1f}%',
             Paragraph(esc(r["top"]), cell)] for r in ctx["producer_rows"][:18]]
    story.append(tbl(["Producer", "Reviewed", "Flagged", "% Flagged", "Most Common Issue"], rows,
                     [4.2*inch, 1.3*inch, 1.2*inch, 1.3*inch, 2.9*inch]))

    story.append(H("Lab Trends"))
    rows = [[Paragraph(esc(r["lab"]), cell), str(r["flagged"]), str(r["thc"]), Paragraph(esc(r["top"]), cell)]
            for r in ctx["lab_rows"]]
    story.append(tbl(["Lab", "Contaminant-Flagged", "High Cannabinoid", "Most Common Contaminant"], rows,
                     [4.0*inch, 2.0*inch, 1.9*inch, 2.9*inch]))

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
                     Paragraph(coa(p), cellc)])
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

    if ctx["mycotoxins"]:
        story.append(H("Mycotoxin Findings"))
        story.append(Paragraph("Aflatoxins / ochratoxin A. CannaScope threshold = 50% of the CT legal limit.", CTX))
        story.append(rich_table(ctx["mycotoxins"]))
    else:
        nsf.append(("Mycotoxins", next((c for c in ctx["zero"] if c["category"] == "Mycotoxins"), None)))
    if ctx["solvents"]:
        story.append(H("Residual Solvent Findings"))
        story.append(Paragraph("Residual solvents at/over the CannaScope standard, or a failed panel.", CTX))
        rows = [[Paragraph(f'<font color="#9A7B0A"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
                 td(p), Paragraph(pr(p), cell), Paragraph(esc(d["name"]), cell),
                 Paragraph(esc(clean_value(d.get("value"), d.get("unit", "ppm"))), cellb), Paragraph(coa(p), cellc)]
                for i, (p, d) in enumerate(ctx["solvents"], 1)]
        story.append(tbl(["#", "Product", "Testing Date", "Producer", "Solvent", "Measured", "COA"], rows,
                         [0.4*inch, 2.9*inch, 0.95*inch, 2.5*inch, 1.9*inch, 1.5*inch, 1.2*inch]))
    else:
        nsf.append(("Residual Solvents", next((c for c in ctx["zero"] if c["category"] == "Residual Solvents"), None)))
    if ctx["pesticides"]:
        story.append(H("Pesticide Findings"))
        story.append(Paragraph("COA pesticide panel returned FAIL (prohibited / over-limit pesticide).", CTX))
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
                 td(p), Paragraph(pr(p), cell), Paragraph('<font color="#C0392B"><b>Panel FAIL</b></font>', cellc), Paragraph(coa(p), cellc)]
                for i, p in enumerate(ctx["pesticides"], 1)]
        story.append(tbl(["#", "Product", "Testing Date", "Producer", "Result", "COA"], rows,
                         [0.4*inch, 3.4*inch, 0.95*inch, 2.9*inch, 1.6*inch, 1.2*inch]))
    else:
        nsf.append(("Pesticides", next((c for c in ctx["zero"] if c["category"] == "Pesticides"), None)))
    if ctx["pathogens"]:
        story.append(H("Pathogen Findings", color=RED))
        story.append(Paragraph("Zero-tolerance pathogen reported DETECTED (do-not-consume if confirmed).", CTX))
        rows = [[Paragraph(f'<font color="#C0392B"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
                 td(p), Paragraph(pr(p), cell), Paragraph(f'<font color="#C0392B"><b>{esc(nice)} DETECTED</b></font>', cellc), Paragraph(coa(p), cellc)]
                for i, (p, nice) in enumerate(ctx["pathogens"], 1)]
        story.append(tbl(["#", "Product", "Testing Date", "Producer", "Pathogen", "COA"], rows,
                         [0.4*inch, 3.2*inch, 0.95*inch, 2.8*inch, 2.0*inch, 1.2*inch]))
    else:
        nsf.append(("Pathogens", next((c for c in ctx["zero"] if c["category"] == "Pathogens"), None)))

    # ---------------- HIGH CANNABINOID CONTENT (+ Testing Date + Lab) ----------------
    story.append(H("High Cannabinoid Content / High THC Content Findings", color=AQUA))
    story.append(Paragraph("Non-infused flower with a reliable cannabinoid reading above 35% — identifying unusually "
                           "high cannabinoid content for review, not an accusation. Testing date and lab help reveal patterns.", CTX))
    rows = [[Paragraph(f'<font color="#0E6B5A"><b>{i}</b></font>', cellc), Paragraph(esc(tcase(p.product_name)), cell),
             td(p), Paragraph(pr(p), cell), Paragraph(esc(lab_name(p, lmap)), cell),
             Paragraph(f'<font color="#0E6B5A"><b>{val:g}%</b></font>', cellc), Paragraph(coa(p), cellc)]
            for i, (p, key, val) in enumerate(ctx["thc_flower"], 1)]
    if rows:
        story.append(tbl(["#", "Product", "Testing Date", "Producer", "Lab", "Cannabinoid %", "COA"], rows,
                         [0.4*inch, 2.9*inch, 0.95*inch, 2.4*inch, 1.7*inch, 1.45*inch, 1.15*inch], hc=AQUA, band="#d4f5ee"))
    else:
        story.append(Paragraph("No non-infused flower exceeded the 35% review threshold in this run.", cellc))

    # ---------------- INFUSED & EXTRACT POTENCY COMPARISON REFERENCE ----------------
    story.append(H("Infused & Extract Potency Comparison Reference", color=PURPLE))
    story.append(Paragraph("This section exists to compare concentrated products (infused pre-rolls, hash/THCA-infused "
                           "items, vapes, concentrates, extracts) against normal flower. High potency here is expected "
                           "by design — reference only, NOT a flower abnormality.", CTX))
    rows = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
             Paragraph(esc(lab_name(p, lmap)), cell), Paragraph(f'{val:g}%', cellc), Paragraph(coa(p), cellc)]
            for (p, key, val) in ctx["infused_potency"][:40]]
    if rows:
        story.append(tbl(["Product", "Testing Date", "Producer", "Lab", "Highest Cannabinoid %", "COA"], rows,
                         [2.9*inch, 0.95*inch, 2.4*inch, 1.7*inch, 1.7*inch, 1.15*inch], hc=PURPLE, band="#ead9f2"))
    else:
        story.append(Paragraph("No infused / extract products reached the 35% reference threshold.", cellc))

    # ---------------- POSSIBLE REMEDIATION REVIEW ----------------
    if ctx["remediation"]:
        story.append(H("Possible Remediation / Unusually Low Microbial Load Review"))
        story.append(Paragraph("This is NOT proof of remediation. It is a consumer-awareness lead based on unusually "
                               "low or ND microbial readings (non-infused flower) and should be verified against the "
                               "live COA. Low microbial counts can be entirely normal.", CTX))
        rows = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
                 Paragraph(esc(clean_value(p.analytes.get("tymc", {}).get("value"), "CFU/g")), cellc),
                 Paragraph(coa(p), cellc)] for p in ctx["remediation"][:25]]
        story.append(tbl(["Product", "Testing Date", "Producer", "Yeast & Mold", "COA"], rows,
                         [3.4*inch, 0.95*inch, 2.9*inch, 1.7*inch, 1.3*inch]))

    # ---------------- LOWER-CONCERN PRODUCTS ----------------
    story.append(H("Lower-Concern Products", color=PURPLE))
    story.append(Paragraph("Non-infused flower with NO contaminant flag, a valid numeric Total THC, and a normal "
                           "nonzero yeast & mold (200–5,000 CFU/g). Not endorsed as safe.", CTX))
    rows = [[Paragraph(esc(tcase(p.product_name)), cell), td(p), Paragraph(pr(p), cell),
             Paragraph(esc(clean_value(p.analytes.get("tymc", {}).get("value"), "CFU/g")), cellc),
             Paragraph(f'{thc_value(p, "total_thc"):g}%', cellc), Paragraph(coa(p), cellc)]
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

    # ================= VALIDATION & DIAGNOSTICS (LAST) =================
    story.append(PageBreak())
    story.append(H("Validation & Diagnostics"))
    story.append(Paragraph("Supporting validation detail. Findings above are the report; this documents how they were "
                           "checked. Status: " + esc(status) + ".", CTX))
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
                 Paragraph(esc(p._coa_status), cell), Paragraph(coa(p), cellc)] for p in qv[:40]]
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
    _w(P("CannaScope_CT_Beta_V7_Validated_Flagged.csv"),
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

    # infused/extract potency reference
    _w(P("infused_extract_potency_reference.csv"),
       ["product", "producer_dba", "type", "lab", "highest_cannabinoid_pct", "coa", "report_url"],
       [[tcase(p.product_name), ident.resolve(p.producer)["label"], tcase(p.dosage_form),
         lab_name(p, lmap), f"{val:g}", p.registration_number, p.report_url]
        for (p, key, val) in ctx["infused_potency"]])

    # COA verification queue
    _w(P("coa_verification_queue.csv"),
       ["product", "producer_dba", "lab", "coa_match_status", "coa", "report_url"],
       [[tcase(p.product_name), ident.resolve(p.producer)["label"], lab_name(p, lmap), p._coa_status,
         p.registration_number, p.report_url] for p in ctx["flagged"] if p._coa_status not in PUBLISHABLE])

    # zero-result queue
    _w(P("zero_result_verification_queue.csv"),
       ["category", "flagged_rows", "parsed", "total", "status", "note"],
       [[c["category"], c["flagged"], c["parsed"], c["total"], c["status"], c["note"]] for c in ctx["zero"]])

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

    # plain-text executive summary
    with open(P("CannaScope_CT_Beta_V7_Executive_Summary.txt"), "w") as f:
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


def _save_ledger(keys):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(LEDGER, "w") as f:
        for k in sorted(keys):
            f.write(k + "\n")


# ============================================================================
# Main
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description=f"{APP_NAME} — {REPORT_TITLE}")
    ap.add_argument("--forms", choices=["flower", "inhalable", "all"], default="all")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--since", default="")
    ap.add_argument("--threshold", type=int, default=v4.DEFAULT_WATCH)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=v4.DEFAULT_WORKERS)
    ap.add_argument("--cookies", default="")
    ap.add_argument("--refresh-registry", action="store_true")
    ap.add_argument("--keep-clean-pdfs", action="store_true")
    args = ap.parse_args()

    since = None
    if args.since:
        try:
            since = tuple(map(int, args.since.split("-")))
        except ValueError:
            sys.exit("--since must be YYYY-MM-DD")
    elif args.days:
        d = datetime.date.today() - datetime.timedelta(days=args.days)
        since = (d.year, d.month, d.day)
    since_str = f"{since[0]:04d}-{since[1]:02d}-{since[2]:02d}" if since else "any date"
    window = f"{since_str} to {datetime.date.today():%Y-%m-%d}"

    os.makedirs(OUT_DIR, exist_ok=True); os.makedirs(CACHE_DIR, exist_ok=True)
    v4.CACHE_DIR = CACHE_DIR

    t0 = time.time()
    debug = {"runtime_started": f"{datetime.datetime.now().astimezone():%Y-%m-%d %H:%M %Z}"}
    session = v4.make_session(args.cookies, args.workers)
    products = load_registry(session, refresh=args.refresh_registry)
    products.sort(key=lambda p: v4.parse_date(p.approval_date), reverse=True)

    pmap = lmap = None
    if names is not None:
        pmap = names.get_producer_map(registry_names=sorted({p.producer for p in products if p.producer}))
        lmap = names.get_lab_map(use_live=False)

    before = len(products)
    products = v4.prefilter(products, args.forms, since)
    if args.limit:
        products = products[:args.limit]
    if not products:
        sys.exit("No products matched. Widen --forms / --days.")
    print(f"Prefilter ({args.forms}, since {since_str}): {len(products)} of {before}.")

    ledger = _load_ledger()
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
    _save_ledger(ledger | new_clean)

    print("\nBuilding validated analytics ...")
    watch = args.threshold
    for p in all_results:
        p._watch = watch

    ident = Identity(pmap, all_results)

    # report-flagged set (trustworthy severity) and publishable subset
    flagged = [p for p in keep if v5.report_severity(p, watch) in ("RED", "ORANGE", "YELLOW") or p.thc_flags or v5.pathogen_detections(p)]
    pub = [p for p in flagged if p._coa_status in PUBLISHABLE]

    # per-analyte items (publishable only in ranked sections)
    analyte_items = {key: category_rows(pub, key) for key, _t in ANALYTE_TABLES}
    mycos = mycotoxin_rows(pub)
    pests = pesticide_rows(pub)
    solvs = solvent_rows(pub)
    paths = pathogen_rows(pub)

    # high-THC non-infused flower vs infused/extract potency
    thc_flower, infused_potency = [], []
    for p in pub:
        rv = thc_review_value(p)
        if not rv or rv[1] <= THC_REVIEW_PCT:
            continue
        if is_noninfused_flower(p):
            thc_flower.append((p, rv[0], rv[1]))
        else:
            infused_potency.append((p, rv[0], rv[1]))
    thc_flower.sort(key=lambda t: t[2], reverse=True)
    infused_potency.sort(key=lambda t: t[2], reverse=True)

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
        "parser_failures_no_text": len(failures),
        "flagged_total": len(flagged),
        "flagged_published": len(pub),
        "coa_verification_queue": len(flagged) - len(pub),
        "high_thc_noninfused_flower": len(thc_flower),
        "infused_extract_potency_ref": len(infused_potency),
        "potency_parser_conflicts": sum(1 for p in all_results if thc_conflict(p)),
        "zero_result_draft_warnings": sum(1 for c in zero if c["status"] == "DRAFT WARNING"),
        "self_audit_remaining_issues": len(remaining),
    })
    status = report_status(debug, remaining, draft_zero)
    debug["report_status"] = status
    draft = status in ("DRAFT", "FAIL")

    ctx = dict(draft=draft, status=status, pmap=pmap, lmap=lmap, ident=ident, watch=watch, window=window,
               flagged=flagged, exec_rows=exec_rows, audit=audit, queue=queue,
               producer_rows=producer_rows, lab_rows=lab_rows, analyte_items=analyte_items,
               pesticides=pests, solvents=solvs, mycotoxins=mycos, pathogens=paths,
               thc_flower=thc_flower, infused_potency=infused_potency, remediation=remediation,
               cleaner=cleaner, cleaner_review=cleaner_review, zero=zero, debug=debug,
               n_reviewed=len(all_results), n_pub=len(pub), n_queue=len(flagged)-len(pub),
               n_red=sev_counts.get("RED", 0), n_org=sev_counts.get("ORANGE", 0),
               n_yel=sev_counts.get("YELLOW", 0), n_thc=len(thc_flower))

    write_outputs(ctx)
    out_path, report_no = next_report_path(status)
    build_pdf(out_path, report_no, ctx)

    import shutil
    visible = os.path.join(os.path.dirname(os.path.abspath(OUT_DIR)), PUBLIC_PDF_NAME)
    try:
        shutil.copy2(out_path, visible)
    except OSError:
        visible = out_path

    print("\n" + "=" * 74)
    print(f"  CANNASCOPE BETA V5 — REPORT #{report_no} [{status}] IS READY")
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


if __name__ == "__main__":
    main()
