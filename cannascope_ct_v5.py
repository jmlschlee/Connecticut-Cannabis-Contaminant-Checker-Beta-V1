#!/usr/bin/env python3
"""
CannaScope CT Beta Version 5
============================
Connecticut Cannabis Transparency Report — 365-Day Consumer Awareness &
Testing Pattern Review.

Every flag is a LEAD, not a conclusion. Verify every product against its COA.
CannaScope CT uses stricter consumer-awareness thresholds and does not claim that
flagged products legally failed Connecticut testing.

WHAT VERSION 5 ADDS (on top of the proven Version 4 contaminant engine)
  * PRODUCER-NORMALIZED FLAG RATES — raw flag counts AND % of a producer's
    reviewed products that were flagged, so a big catalog can't look "dirtier"
    than a small one just by volume.
  * CANNASCOPE RECURRENCE SCORE + RECURRING CONTAMINANT SIGNATURES — repeated
    pairings of producer x contaminant, producer x THC, lab x abnormality, and
    repeated product families / strains, surfaced as patterns worth investigating.
  * PRODUCT FAMILY & BATCH PATTERN REVIEW — clusters of related products (same
    producer + contaminant, shared strain/brand family) shown together.
  * PRODUCER IDENTITY RESOLVER — legal entity <-> common brand / DBA / parent /
    license, from a curated, source-verified table plus the ct_cannabis_names
    backfill; anything not confidently confirmed is marked, never invented, and
    logged for manual verification.
  * ABNORMALLY-HIGH THC / CANNABINOID FLAGGING (AQUAMARINE) — flower-based
    inhalables whose Total THC / THC / Delta-9 / THCA / Total Cannabinoids /
    Total Active Cannabinoids exceed 35% are surfaced for review (NOT a legal
    failure), with a dedicated page and a per-lab distribution of those results.
  * EXPANDED EXECUTIVE SUMMARY, section-per-page PDF layout, repeated table
    headers, consistent color coding (adds Aquamarine + Purple), an internal
    accuracy/verification pass, and a fuller set of CSV / text exports.

This program REUSES the Version 4 parsing + flagging core verbatim (imported as a
module) so the contaminant logic that was already validated is unchanged, and the
new analytics build strictly on top of it.

COLOR CODING
  Red        = Do Not Consume / extreme concern
  Orange     = High Caution
  Yellow     = Moderate Caution
  Aquamarine = Requires Investigation / abnormally high cannabinoid result
  Purple     = Potentially cleaner / lower-contaminant product (review only)

REQUIREMENTS:  pip install requests reportlab pypdfium2
  OCR (recommended): macOS `pip install ocrmac`; other OS `pip install pytesseract`
  Place cannascope_ct_v4.py and ct_cannabis_names.py beside this file.

TYPICAL RUN (defaults — last 365 days, ALL product types):
  python cannascope_ct_v5.py
NARROWER / QUICK TEST:
  python cannascope_ct_v5.py --forms flower --days 90 --limit 50
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
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---- Version 4 engine (proven download / OCR / contaminant parsing + flagging)
try:
    import cannascope_ct_v4 as v4
except ImportError:
    sys.exit("CannaScope CT V5 needs cannascope_ct_v4.py beside it "
             "(it reuses the validated V4 contaminant engine).")

# Name resolution module (re-exported through v4.names when available)
names = getattr(v4, "names", None)


# ============================================================================
# Config — V5 specific
# ============================================================================
APP_NAME = "CannaScope CT Beta Version 5"
REPORT_TITLE = ("Connecticut Cannabis Transparency Report — "
                "365-Day Consumer Awareness & Testing Pattern Review")
FRAMING = ("Every flag is a lead, not a conclusion. Verify every product against "
           "its COA. CannaScope CT uses stricter consumer-awareness thresholds and "
           "does not claim that flagged products legally failed Connecticut testing.")

DEFAULT_DAYS = 365                 # 365-day review window (title)
THC_REVIEW_PCT = 35.0              # flower cannabinoid review threshold (NOT a legal limit)
FLOWER_PLAUSIBLE_MAX = 45.0        # biological ceiling for DRY FLOWER Total THC. Above this, a
                                  # "flower"-classified row is almost certainly a concentrate / vape /
                                  # extract mis-routed as flower -> hold for product-type review, do NOT
                                  # publish as a high-THC FLOWER finding (item 1).

OUT_DIR = "CannaScope CT Beta V5 - Reports"
CACHE_DIR = os.path.join(OUT_DIR, "Flagged COA Source PDFs")
REGISTRY_CACHE = os.path.join(OUT_DIR, "Registry Cache.csv")
LEDGER = os.path.join(OUT_DIR, "Already-Scanned Skip List.txt")
IDENTITY_CACHE = os.path.join(OUT_DIR, "Identity Resolver Cache.json")

# Output files (all prefixed CannaScope_CT_Beta_V5)
F_FLAGGED_CSV   = os.path.join(OUT_DIR, "CannaScope_CT_Beta_V5_Flagged_Products.csv")
F_THC_CSV       = os.path.join(OUT_DIR, "CannaScope_CT_Beta_V5_High_THC_Aquamarine_Flags.csv")
F_NORM_CSV      = os.path.join(OUT_DIR, "CannaScope_CT_Beta_V5_Producer_Normalized_Rates.csv")
F_LABTHC_CSV    = os.path.join(OUT_DIR, "CannaScope_CT_Beta_V5_Lab_HighTHC_Distribution.csv")
F_UNRES_CSV     = os.path.join(OUT_DIR, "CannaScope_CT_Beta_V5_Unresolved_Identity.csv")
F_SIG_CSV       = os.path.join(OUT_DIR, "CannaScope_CT_Beta_V5_Recurring_Signatures.csv")
F_EXEC_TXT      = os.path.join(OUT_DIR, "CannaScope_CT_Beta_V5_Executive_Summary.txt")
F_FULL_CSV      = os.path.join(OUT_DIR, "CannaScope_CT_Beta_V5_All_Products_Scanned.csv")
REPORT_PREFIX   = "CannaScope_CT_Beta_V5_Report_"

REGISTRY_TTL = 6 * 3600

# Flower-for-THC taxonomy. Anything that is flower-based and smoked counts; vapes,
# concentrates, extracts, edibles, tinctures, topicals, capsules, beverages do not
# (unless the product is clearly a flower-based infused product, e.g. infused
# pre-rolls, which carry a flower keyword and no concentrate/edible keyword).
THC_FLOWER_KEYWORDS = (
    "flower", "usable marijuana", "plant material", "raw material", "mini flower",
    "flower mini", "flower minis", "smalls", "small", "ground flower", "shake",
    "bud", "pre-roll", "preroll", "pre roll", "infused pre-roll", "infused preroll",
    "blunt", "joint", "flower pack", "flower packs", "party pack", "party packs",
    "lil ricky", "lil' ricky", "lil rickys", "lil' ricky's",
)
THC_EXCLUDE_KEYWORDS = (
    "vape", "vaporizer", "cartridge", "cart", "disposable", "pod", "510",
    "concentrate", "extract", "distillate", "rosin", "resin", "wax", "shatter",
    "badder", "budder", "crumble", "sauce", "diamonds", "dab", "hash", "hashish",
    "kief", "edible", "gummy", "gummies", "tincture", "topical", "capsule",
    "tablet", "lozenge", "beverage", "drink", "syrup", "sublingual", "suppository",
    "patch", "cream", "balm", "lotion", "troche", "softgel", "oil",
)


# ============================================================================
# Data model — extends V4 Product with cannabinoids + THC flags + strain
# ============================================================================
@dataclass
class ProductV5(v4.Product):
    cannabinoids: dict = field(default_factory=dict)   # key -> {value(%), raw, name, unit}
    thc_flags: list = field(default_factory=list)      # [{field, name, value, over_by}]
    strain: str = ""


# ============================================================================
# Registry loading (builds ProductV5; reuses V4 row helpers)
# ============================================================================
def _rows_from_csv_text(text: str) -> list:
    reader = csv.DictReader(text.splitlines())
    out = []
    for row in reader:
        name = (row.get("PRODUCT-NAME") or "").strip()
        report_url = v4.extract_url(row.get("LAB-ANALYSIS", ""))
        if not report_url:
            continue
        out.append(ProductV5(
            product_name=name,
            dosage_form=(row.get("DOSAGE-FORM") or "").strip(),
            producer=(row.get("BRANDING-ENTITY") or "").strip(),
            brand=v4.parse_brand(name),
            approval_date=(row.get("APPROVAL-DATE") or "").strip(),
            registration_number=(row.get("REGISTRATION-NUMBER") or "").strip(),
            label_url=v4.extract_url(row.get("LABEL-IMAGE", "")),
            report_url=report_url,
        ))
    return out


def load_registry(session, refresh: bool = False) -> list:
    if (not refresh and os.path.exists(REGISTRY_CACHE)
            and time.time() - os.path.getmtime(REGISTRY_CACHE) < REGISTRY_TTL):
        age = int((time.time() - os.path.getmtime(REGISTRY_CACHE)) / 60)
        with open(REGISTRY_CACHE, encoding="utf-8", errors="replace") as f:
            text = f.read()
        products = _rows_from_csv_text(text)
        print(f"Registry: using cached copy ({age} min old, {len(products)} products).")
        return products
    print("Registry: downloading fresh CSV ...")
    r = session.get(v4.CSV_URL, timeout=180)
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(REGISTRY_CACHE, "w", encoding="utf-8") as f:
        f.write(text)
    products = _rows_from_csv_text(text)
    print(f"  {len(products)} products with a lab-analysis link (cached).")
    return products


# ============================================================================
# Flower-for-THC classification + strain / family extraction
# ============================================================================
def _hay(p) -> str:
    return f"{p.dosage_form} {p.product_name}".lower()


# Forms (the authoritative DOSAGE-FORM field) that ARE flower-based smokables.
_FORM_FLOWER_KEYWORDS = ("flower", "usable marijuana", "plant material", "raw material",
                         "shake", "bud", "pre-roll", "preroll", "pre roll", "blunt", "joint")
# Product-NAME tokens that mark a flower-based smokable even when the form is a
# generic "Marijuana Extract for Inhalation" (e.g. bubble-hash-infused pre-rolls).
_NAME_FLOWER_KEYWORDS = ("pre-roll", "preroll", "pre roll", "infused pre-roll",
                         "infused preroll", "blunt", "joint", "mini flower", "flower mini",
                         "smalls", "ground flower", "shake", "flower pack", "party pack",
                         "lil ricky", "lil' ricky")


def is_thc_flower(p) -> bool:
    """True if the product is a flower-based smoked product the 35% cannabinoid
    review applies to (whole flower, smalls/minis/shake, pre-rolls incl. infused
    pre-rolls and blunts). Classification is driven by the DOSAGE FORM, which is
    authoritative; the product name is used only for pre-roll/blunt/smalls cues.

    This deliberately does NOT treat a bare 'flower' in the product NAME as flower
    (brands like 'Flower by Edie Parker' ship vape pens), so vapes, concentrates,
    extracts, edibles, tinctures and topicals are correctly excluded."""
    form = (p.dosage_form or "").lower()
    name = (p.product_name or "").lower()
    form_excluded = any(k in form for k in THC_EXCLUDE_KEYWORDS)
    # 1. Flower by its dosage form (authoritative), unless that form is also an
    #    excluded type (rare; the form wins toward flower only when not excluded).
    if any(k in form for k in _FORM_FLOWER_KEYWORDS) and not form_excluded:
        return True
    # 2. Infused pre-rolls / blunts: a pre-roll/blunt NAME on an extract form.
    if any(k in name for k in ("pre-roll", "preroll", "pre roll", "blunt", "joint")):
        return True
    # 3. Other flower-name cues (smalls, mini flower, shake, packs) only when the
    #    dosage form is not an excluded (vape/concentrate/edible) type.
    if any(k in name for k in _NAME_FLOWER_KEYWORDS) and not form_excluded:
        return True
    return False


_SIZE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:g|mg|oz|ml|gram|grams|pk|ct|pack|count|x)\b", re.I)
_FORM_WORD_RE = re.compile(
    r"\b(?:flower|pre-?\s*roll(?:s)?|preroll(?:s)?|mini(?:s)?|smalls?|shake|bud|"
    r"blunt|joint|vape|cartridge|cart|disposable|concentrate|extract|rosin|resin|"
    r"wax|shatter|badder|budder|crumble|sauce|diamonds|live|cured|infused|usable|"
    r"marijuana|cannabis|whole|ground|pack(?:s)?|party)\b", re.I)


def product_core_name(p) -> str:
    """Best-effort strain / product-family core, used for clustering. CT registry
    names are often pipe-delimited 'Brand|Form|Strain|Size'; otherwise we strip the
    brand, sizes, and form words from the product name."""
    name = p.product_name or ""
    brand = (p.brand or "").strip()
    if "|" in name:
        segs = [s.strip() for s in name.split("|") if s.strip()]
        cands = []
        for s in segs:
            if brand and v4.names and _norm(s) == _norm(brand):
                continue
            if _SIZE_RE.fullmatch(s) or _SIZE_RE.match(s):
                continue
            letters = len(re.sub(r"[^A-Za-z]", "", s))
            if letters >= 3 and not _FORM_WORD_RE.fullmatch(s.strip()):
                cands.append((letters, s))
        if cands:
            return max(cands)[1]
    core = name
    if brand:
        core = re.sub(re.escape(brand), " ", core, flags=re.I)
    core = _SIZE_RE.sub(" ", core)
    core = _FORM_WORD_RE.sub(" ", core)
    core = re.sub(r"[|/\\,]+", " ", core)
    core = re.sub(r"\s+", " ", core).strip(" -|")
    return core or (name.strip())


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


_ENTITY_SUFFIX_RE = re.compile(r"\b(llc|l\.l\.c|inc|ltd|co|corp|corporation|company|the)\b", re.I)


def _ident_norm(s: str) -> str:
    """Entity-name key that strips legal suffixes (LLC / Inc / ...) so
    'FFD 149 LLC' == 'ffd 149'. Uses ct_cannabis_names.normalize when available so
    the V5 identity table and that module agree on keys."""
    if names is not None:
        return names.normalize(s)
    s = _ENTITY_SUFFIX_RE.sub(" ", (s or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


# ============================================================================
# Cannabinoid / THC parsing  (NEW — V4 did not read potency)
# ============================================================================
# Order: most-specific labels first so "Total THC" / "THCA" don't get eaten by a
# bare "THC" match. Each entry: key, display name, label regex.
CANN_SPECS = [
    ("total_active",       "Total Active Cannabinoids", r"total\s+active\s+cannabinoids?"),
    ("total_cannabinoids", "Total Cannabinoids",        r"total\s+cannabinoids?"),
    ("total_thc",          "Total THC",                 r"total\s+thc\b"),
    ("total_cbd",          "Total CBD",                 r"total\s+cbd\b"),
    ("thca",               "THCA",
        r"\bthca\b|\bthc[\s\-]?a\b|tetrahydrocannabinolic\s+acid"),
    ("d9_thc",             "Delta-9 THC",
        r"(?:delta[\s\-]*9|Δ9|Δ\s*\-?\s*9|δ\s*\-?\s*9|\bd[\s\-]?9\b)"
        r"[\s\-]*thc\b"),
    # Δ9/plain THC, but NOT the acid form: "THC-A"/"THC A"/"THCA" must not match here, or the THCA
    # value gets duplicated into the THC field and inflates derived Total THC past 100%.
    ("thc",                "THC",                       r"(?<![a-z])thc(?![\s\-]*a\b)(?![a-z])"),
]

_PCT_RE = re.compile(r"([\d]{1,3}(?:\.\d+)?)\s*%")
_MGG_RE = re.compile(r"([\d]+(?:\.\d+)?)\s*mg\s*/\s*g", re.I)
_CANN_SECTION = r"cannabinoids?|cannabinoid\s+profile|potency|total\s+cannabinoids?"


def _read_pct(segment: str) -> Optional[float]:
    """A plausible cannabinoid percentage from a result fragment. Prefer an
    explicit '%'; fall back to mg/g (÷10). Returns None if nothing plausible."""
    if v4.BELOW_DETECT.search(segment):
        return 0.0
    m = _PCT_RE.search(segment)
    if m:
        try:
            v = float(m.group(1))
        except ValueError:
            v = None
        if v is not None and 0.0 <= v <= 100.0:
            return v
    m = _MGG_RE.search(segment)
    if m:
        try:
            v = float(m.group(1)) / 10.0
        except ValueError:
            v = None
        if v is not None and 0.0 <= v <= 100.0:
            return v
    return None


# A formula / definition line, NOT a result row -- e.g. CT COAs print
# "Total THC % (0.877*THCA)+THC" as a label, with the computed value elsewhere.
_CANN_FORMULA = re.compile(r"0\.877|\*\s*thca|\+\s*thc|=\s*\(", re.I)


def _lodloq_result(segment: str) -> Optional[float]:
    """For a columnar 'Analyte LOD LOQ Result(%) Result(mg/g)' row, return the RESULT
    percentage -- the value AFTER the two leading detection-limit columns -- so the
    tiny LOD/LOQ figures (~0.0001) are never mistaken for the potency. 'ND' / a
    non-numeric in the result position returns None (handled as not-detected)."""
    toks = segment.split()
    nums = 0
    for i, tk in enumerate(toks):
        if re.fullmatch(r"\d+(?:\.\d+)?", tk.replace(",", "")):
            nums += 1
            if nums == 2:                       # LOD, LOQ consumed -> next token is Result
                rest = toks[i + 1:]
                if rest and re.fullmatch(r"\d+(?:\.\d+)?", rest[0].replace(",", "")):
                    v = float(rest[0].replace(",", ""))
                    return v if 0.0 <= v <= 100.0 else None
                return None                     # 'ND' or absent -> not detected
    return None


def _bare_pct(segment: str) -> Optional[float]:
    """First plausible 0-100 percentage from a bare-number '% w/w' cannabinoid row
    (e.g. 'THCA 37.06 2244.0' -> 37.06). The \\d{1,3} cap skips 4+ digit dosing
    columns (mg/package), and the first in-range token is the % w/w value."""
    for m in re.finditer(r"(?<![\d.,])(\d{1,3}(?:\.\d+)?)(?![\d.,])", segment):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if 0.0 <= v <= 100.0:
            return v
    return None


def parse_cannabinoids(text: str, p) -> None:
    """Record the cannabinoid potency fields needed for the 35% flower review.

    CT lab COAs print potency as a 'Cannabinoids Results (% w/w)' table whose rows
    are BARE numbers with no per-row '%' sign (e.g. 'THCA 37.06 2244.0' = 37.06%
    w/w, 2244 mg dosing). We therefore (1) scope to the cannabinoid region, (2) try
    an explicit '%'/'mg/g' read, then (3) fall back to the first bare 0-100 number
    when the table is a '% w/w' style. Formula/definition lines (the 'Total THC =
    (0.877*THCA)+THC' label) are skipped, and Total THC is derived from THCA +
    Delta-9 when only those were itemized."""
    mreg = (re.search(r"cannabinoids?\s+results|cannabinoid\s+profile|cannabinoids?\s*\(",
                      text, re.I) or re.search(r"\bcannabinoids?\b", text, re.I))
    body = text[mreg.start(): mreg.start() + 2200] if mreg else text
    ww = bool(re.search(r"%\s*w/?\s*w|\(\s*%|w/?w\b", body, re.I)) or mreg is not None
    # Newer labs (e.g. Analytics Labs) print a columnar table:
    #   Analyte | LOD | LOQ | Result(%) | Result(mg/g)
    # so a row is "THCa 0.00003 0.00010 29.656 296.560". The RESULT is the 3rd number;
    # naively taking the first bare number would read the LOD (~0.0001) as the potency.
    # When LOD AND LOQ column headers are present, read the value AFTER the two
    # detection-limit columns instead.
    has_lod_loq = bool(re.search(r"\bLOD\b", body, re.I) and re.search(r"\bLOQ\b", body, re.I))
    low = body.lower()
    for key, nice, label in CANN_SPECS:
        if key in p.cannabinoids:
            continue
        for m in re.finditer(label, low, re.I):
            line = body[m.start():].split("\n", 1)[0]
            if v4.FOOTNOTE_RE.search(line) or _CANN_FORMULA.search(line):
                continue
            after = line[m.end() - m.start():]
            pct = _lodloq_result(after) if has_lod_loq else None
            if pct is None:
                pct = _read_pct(after)
            if pct is None and ww:
                pct = _bare_pct(after)
            if pct is None:
                pct = _read_pct(line)
            if pct is None:
                continue
            p.cannabinoids[key] = {"value": pct, "raw": f"{pct:g}%",
                                   "name": nice, "unit": "%"}
            break
    # derive Total THC if the COA only itemized THCA + Delta-9 THC (or a bare THC)
    if "total_thc" not in p.cannabinoids:
        thca = p.cannabinoids.get("thca", {}).get("value")
        d9 = p.cannabinoids.get("d9_thc", {}).get("value")
        if d9 is None:
            d9 = p.cannabinoids.get("thc", {}).get("value")
        if thca is not None or d9 is not None:
            tot = 0.877 * (thca or 0.0) + (d9 or 0.0)
            if 0 < tot <= 100:
                p.cannabinoids["total_thc"] = {"value": round(tot, 2),
                                               "raw": f"{tot:.2f}% (derived)",
                                               "name": "Total THC (derived)",
                                               "unit": "%"}
            elif tot > 100:
                # A derived Total THC over 100% is physically impossible (% w/w) -> a component was
                # misread, almost always an OCR-garbled decimal on an old scan (".049"->49, "1.86"->86,
                # "o.78"->78). The potency for this COA is internally inconsistent, so drop the THC
                # fields rather than publish a wrong number — this COA's THC potency is treated as not
                # reliably readable instead of fabricated.
                for _f in ("thca", "thc", "d9_thc", "total_thc"):
                    p.cannabinoids.pop(_f, None)


# Cannabinoid fields that trigger the 35% flower review (highest wins).
THC_FLAG_FIELDS = ("total_thc", "thc", "d9_thc", "thca",
                   "total_cannabinoids", "total_active")


def suspected_nonflower_type(p) -> str:
    """Best guess at the real product type when a 'flower' row carries concentrate-level potency,
    from the product name + dosage form. Used to route an implausible-flower row to product-type
    review (item 1). Returns 'vape' / 'concentrate' / 'extract' / '' (unknown)."""
    txt = ((p.product_name or "") + " " + (p.dosage_form or "")).lower()
    if any(k in txt for k in ("vape", "cart", "cartridge", "disposable", "pod", "pen", "510")):
        return "vape"
    if any(k in txt for k in ("rosin", "resin", "wax", "shatter", "badder", "budder", "crumble",
                              "sauce", "diamond", "hash", "kief", "concentrate", "dab")):
        return "concentrate"
    if any(k in txt for k in ("extract", "distillate", "rso", "oil", "tincture", "syringe")):
        return "extract"
    return ""


def apply_thc_flags(p) -> None:
    """Aquamarine review flag: a flower-based product whose Total THC / THC /
    Delta-9 / THCA / Total Cannabinoids / Total Active Cannabinoids exceeds 35%.
    A review signal, never a legal-failure claim."""
    if not is_thc_flower(p):
        return
    triggers = []
    for key in THC_FLAG_FIELDS:
        e = p.cannabinoids.get(key)
        if not e or e.get("value") is None:
            continue
        v = e["value"]
        if v > THC_REVIEW_PCT:
            triggers.append({"field": key, "name": e.get("name", key),
                             "value": v, "over_by": v - THC_REVIEW_PCT})
    if not triggers:
        return
    triggers.sort(key=lambda d: d["value"], reverse=True)
    headline = triggers[0]["value"]
    # ITEM 1 GUARDRAIL: a FLOWER-classified row whose Total THC exceeds the biological flower ceiling
    # (~45%) is implausible for dry flower — almost certainly a concentrate/vape/extract mis-routed as
    # flower. Do NOT publish it as a high-THC FLOWER finding; route it to the Product-Type / Potency
    # Classification Review queue with a reclassification guess. (Conservative: hold, don't assert.)
    if headline > FLOWER_PLAUSIBLE_MAX:
        p._potency_typemismatch = {
            "value": headline, "field": triggers[0]["field"], "name": triggers[0]["name"],
            "suspected_type": suspected_nonflower_type(p),
            "reason": (f"Classified as flower but Total THC {headline:g}% exceeds the ~{FLOWER_PLAUSIBLE_MAX:g}% "
                       "biological ceiling for dry flower — likely a concentrate / vape / extract "
                       "mis-routed as flower; held for product-type review, not published as high-THC flower.")}
        return   # NOT a high-THC flower finding
    p.thc_flags = triggers   # keep all triggers, highest-magnitude first


def thc_headline(p):
    return p.thc_flags[0] if p.thc_flags else None


# ============================================================================
# Severity model (V4 contaminant severities + Aquamarine / Purple)
# ============================================================================
SEV_RANK = {"RED": 4, "ORANGE": 3, "YELLOW": 2, "AQUA": 1, None: 0}
SEV_TINT = dict(v4.SEV_TINT); SEV_TINT["AQUA"] = "#d4f5ee"; SEV_TINT["PURPLE"] = "#ead9f2"
SEV_BAR  = dict(v4.SEV_BAR);  SEV_BAR["AQUA"] = "#16A085";  SEV_BAR["PURPLE"] = "#7D3C98"
SEV_LABEL = dict(v4.SEV_LABEL)
SEV_LABEL["AQUA"] = "REQUIRES<br/>INVESTIGATION"
SEV_LABEL["PURPLE"] = "LOWER<br/>CONCERN"


def contaminant_severity(p):
    """The V4 contaminant severity (RED/ORANGE/YELLOW) or None."""
    return v4.product_severity(p)


def overall_severity(p):
    """Worst severity across contaminant flags and the THC review flag. A THC-only
    product is AQUA; a contaminant product keeps its contaminant severity."""
    sev = contaminant_severity(p)
    if sev:
        return sev
    if p.thc_flags:
        return "AQUA"
    return None


def is_flagged(p) -> bool:
    return bool(p.flags) or bool(p.thc_flags)


# ============================================================================
# Producer / lab identity
# ============================================================================
def producer_display(p, pmap=None) -> str:
    return v4._producer_display(p, pmap)


def lab_display(p, lmap=None) -> str:
    return v4._lab_display(p, lmap) or "Unidentified Lab"


# Curated identity table, keyed by normalized legal entity. Each value carries a
# `confidence` ("CONFIRMED" or "LIKELY") and a public `source`. These were verified
# against public reporting / CT records in 2026-06; entries that public sources did
# NOT pin down verbatim are marked LIKELY and surfaced with a "verify manually"
# note rather than asserted as fact. Brand sub-associations that could not be
# independently confirmed (e.g. Comffy, Daily!) are intentionally omitted.
# Anything not listed here and not in ct_cannabis_names is reported as unresolved
# (never invented). Confirm new entries against the CT product registry's
# branding-entity field (data.ct.gov egd5-wb6r) or the CT business search.
IDENTITY_TABLE = {
    "ffd 149": dict(
        common="Fine Fettle", parent="Fine Fettle Dispensaries",
        brands=["SAUS"], license="FFD 149 LLC (Fine Fettle social-equity cultivator)",
        confidence="CONFIRMED",
        source="hartfordbusiness.com / dabbin-dad.com (Comffy sub-brand NOT confirmed)"),
    "dxr finance 3": dict(
        common="Theraplant", parent="DXR Finance / DXR Holdco",
        brands=["Theraplant"], license="DXR Finance 3 LLC (acquired Theraplant, 2023)",
        confidence="CONFIRMED",
        source="CT Appellate AC46769 / ctnewsjunkie.com (Theraplant LLC remains operator)"),
    "theraplant": dict(
        common="Theraplant", parent="DXR (post-2023)", brands=["Theraplant"],
        license="Theraplant, LLC (Watertown producer)", confidence="CONFIRMED",
        source="CT producer license / ctnewsjunkie.com"),
    "debbie's dispensary": dict(
        common="Crisp Cannabis", parent="Debbie's Dispensary LLC (Mohave CT / Devine Holdings)",
        brands=["Crisp", "Let's Burn"],
        license="Debbie's Dispensary LLC d/b/a Crisp (retailer)",
        confidence="CONFIRMED",
        source="dutchie.com listing (Daily! sub-brand NOT confirmed; retailer not producer)"),
    "nutmeg new britain jv": dict(
        common="Brix Cannabis", parent="Curaleaf social-equity JV (co-owner Judy Prisco)",
        brands=["Brix Cannabis"], license="Nutmeg New Britain micro-cultivator",
        confidence="LIKELY",
        source="hartfordbusiness.com / brixofficial.com (exact legal string not verbatim)"),
    "shangri-la ct": dict(
        common="Shangri-La (Borealis Cannabis)", parent="Shangri-La (owner Jocelyn Cerda)",
        brands=["Borealis", "Asteroid", "Shangri-La"],
        license="Shangri-La CT (Stratford cultivation)", confidence="CONFIRMED",
        source="cga.ct.gov testimony / doingitlocal.com (Inc vs LLC suffix not verbatim)"),
    "advanced grow labs": dict(
        common="Advanced Grow Labs", parent="Green Thumb Industries (GTI)", brands=["AGL"],
        license="Advanced Grow Labs (West Haven producer)", confidence="CONFIRMED",
        source="mjbizdaily.com (GTI acquired 2019)"),
    "connecticut pharmaceutical solutions": dict(
        common="CTPharma", parent="Verano Holdings",
        brands=["Zen Leaf"], license="Connecticut Pharmaceutical Solutions (Rocky Hill)",
        confidence="CONFIRMED", source="hartfordbusiness.com (Verano acquired Dec 2021)"),
    "curaleaf": dict(common="Curaleaf", parent="Curaleaf Holdings", brands=["Curaleaf"],
                     license="Curaleaf Connecticut (Simsbury producer)", confidence="CONFIRMED",
                     source="hartfordbusiness.com (exact CT subsidiary string not verbatim)"),
    "the goods thc": dict(
        common="The Goods THC", parent="independent (operator Gloribel Diaz, Hartford)",
        brands=["Cookies", "Tyson 2.0"], license="The Goods THC", confidence="LIKELY",
        source="cannabisbusinesstimes.com (exact LLC name not surfaced)"),
    "affinity grow": dict(common="Affinity Grow", parent="MCEJV LLC (Portland micro-cultivator)",
                          brands=["Affinity Grow"], license="MCEJV LLC", confidence="LIKELY",
                          source="ctnewsjunkie.com (single-source on legal entity)"),
    "chillax": dict(common="Chillax", parent="Chillax LLC", brands=["Chillax"],
                    license="Chillax LLC (micro-cultivator applicant)", confidence="LIKELY",
                    source="420intel.com (operational/brand link not fully corroborated)"),
    "soundview manufacturing": dict(common="SoundView", parent="New England Edibles (Bristol)",
                                    brands=["SoundView"], license="New England Edibles d/b/a SoundView",
                                    confidence="LIKELY",
                                    source="getsoundview.com / hartfordbusiness.com"),
    "jananii": dict(common="Awssom", parent="Jananii LLC (Jusmin Patel, MD)", brands=["Awssom"],
                    license="Jananii LLC (New Britain cultivation)", confidence="LIKELY",
                    source="jananii.isolvedhire.com / awssom.com (single-thread on DBA)"),
    # NOTE: "56 Benton -> Lucky Chews" was NOT confirmed. Public sources tie Lucky
    # Chews to Lucky Break (Bridgeport), not a "56 Benton" entity. Deliberately
    # omitted so it surfaces as unresolved rather than asserting an unverified match.
}
# Re-key through the suffix-stripping normalizer so a registry name carrying ", LLC"
# / "Inc." still matches the hand-typed literals above.
IDENTITY_TABLE = {_ident_norm(k): v for k, v in IDENTITY_TABLE.items()}


class IdentityResolver:
    """Resolves a legal entity name to common brand / DBA / parent / license, using
    (1) the curated V5 IDENTITY_TABLE, (2) the ct_cannabis_names module, then marks
    anything unconfirmed. Results are cached in-memory and on disk so repeated
    lookups (and any future web confirmation) are not redone every run."""

    def __init__(self, pmap=None, cache_path=IDENTITY_CACHE):
        self.pmap = pmap
        self.cache_path = cache_path
        self.cache = {}
        self.unresolved = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}

    def resolve(self, legal: str) -> dict:
        legal = (legal or "").strip()
        if not legal:
            return self._unknown(legal)
        key = _ident_norm(legal)
        if key in self.cache:
            return self.cache[key]
        rec = self._lookup(legal, key)
        self.cache[key] = rec
        if not rec["confirmed"]:
            self.unresolved[key] = rec
        return rec

    def _lookup(self, legal: str, key: str) -> dict:
        hit = IDENTITY_TABLE.get(key)
        if hit:
            return dict(legal=legal, common=hit["common"], parent=hit.get("parent", ""),
                        brands=hit.get("brands", []), license=hit.get("license", ""),
                        source=hit.get("source", ""),
                        confidence=hit.get("confidence", "CONFIRMED"), confirmed=True)
        # fall back to ct_cannabis_names curated/registry map
        if names is not None:
            disp = names.display_producer(legal, self.pmap)
            if "[UNMAPPED" not in disp:
                common = disp.split(" (")[0].strip()
                if _ident_norm(common) != key:   # a real DBA, not just the legal name echoed
                    return dict(legal=legal, common=common, parent="", brands=[],
                                license="", source="ct_cannabis_names curated map",
                                confidence="LIKELY", confirmed=True)
        return self._unknown(legal)

    def _unknown(self, legal: str) -> dict:
        return dict(legal=legal, common=legal, parent="", brands=[], license="",
                    source="", confidence="UNRESOLVED", confirmed=False)

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2)
        except OSError:
            pass


# ============================================================================
# Data quality — quantified vs. detected-but-not-quantified
# ============================================================================
# Result text that is NOT a usable numeric measurement. A contaminant field
# carrying only one of these (or a value that turns out to be a misparsed limit)
# must never drive CT Limit %, CannaScope exceedance, or severity ranking; it is
# routed to "Detected But Not Quantified — Requires Manual COA Review" instead.
NON_NUMERIC_RESULTS = {
    "detected", "present", "positive", "found", "trace", "n/a", "na",
    "not reported", "missing", "blank", "see coa", "report", "tntc",
}
_CLEAN_RESULTS = {"nd", "n.d.", "not detected", "none detected", "negative",
                  "absent", "below detection", "<lod", "<loq", ""}

# Zero-tolerance pathogens (qualitative; a DETECTED here is a real do-not-consume
# RED flag even though it carries no number).
PATHO_KEYS = {"ecoli": "Escherichia coli", "stec": "Shiga toxin-producing E. coli",
              "salmonella": "Salmonella", "listeria": "Listeria monocytogenes",
              "aspergillus": "Pathogenic Aspergillus"}


def is_quantified(e) -> bool:
    """A trustworthy numeric contaminant result: a positive number backed by a
    digit-bearing raw string, not below-detection, and not an obvious limit-column
    misread (value identical to its own action limit while only marked DETECTED —
    the classic two-column-COA parsing artifact)."""
    if not e:
        return False
    if e.get("_coa_unverified"):     # value not found in the live COA -> not trusted
        return False
    v = e.get("value")
    if v is None or v <= 0:
        return False
    raw = (e.get("raw") or "").strip()
    if raw[:1] in "<≤":
        return False
    if not re.search(r"\d", raw):
        return False
    if raw.lower() in NON_NUMERIC_RESULTS:
        return False
    lim = e.get("limit")
    if (lim and abs(v - lim) <= max(1e-9, abs(lim) * 1e-6)
            and (e.get("status") or "").upper() == "DETECTED"):
        return False   # value == its own limit + only DETECTED -> misparsed limit
    # implausible magnitude -> almost certainly an OCR/parse error (e.g. a scanned
    # COA misread "5,088,888,888,888 CFU/g"), NOT a real result. Reject it so it
    # never produces a finding. A genuine gross failure (a few x the limit) is kept.
    if lim and lim > 0 and v > lim * 1000:
        return False
    if v > 1e9:
        return False
    return True


def classify_result(e) -> str:
    """'clean' (ND/below-detect/zero), 'quantified' (trustworthy number), or
    'detected_unquantified' (a detection/positive word, a non-numeric phrase, or a
    value that failed quantification)."""
    if not e:
        return "none"
    raw = (e.get("raw") or "").strip().lower()
    st = (e.get("status") or "").upper()
    v = e.get("value")
    if st == "ND" or raw in _CLEAN_RESULTS or raw[:1] in "<≤":
        return "clean"
    if is_quantified(e):
        return "quantified"
    if st == "DETECTED" or raw in NON_NUMERIC_RESULTS:
        return "detected_unquantified"
    if v is None or v == 0:
        return "clean"
    return "detected_unquantified"   # has a value but it failed quantification


def quantified_details(p, watch):
    """v4.limit_details, restricted to contaminant rows whose source value is
    trustworthy (is_quantified). Cached per product."""
    cache = getattr(p, "_qd_cache", None)
    if cache is not None and getattr(p, "_qd_watch", None) == watch:
        return cache
    out = []
    for d in v4.limit_details(p, watch):
        key = d["key"]
        if key.startswith("solvent:"):
            out.append(d)               # itemized solvent hits are always numeric
            continue
        if is_quantified(p.analytes.get(key)):
            out.append(d)
    p._qd_cache = out
    p._qd_watch = watch
    return out


_UNQ_NAMES = dict(v4.DETECT_DISPLAY)
_UNQ_NAMES["tymc"] = "Yeast & Mold"


def unquantified_findings(p):
    """Notable-but-not-quantified numeric contaminant fields (excluding the
    zero-tolerance pathogens, which are reported separately)."""
    out = []
    for key, name in _UNQ_NAMES.items():
        if key in PATHO_KEYS:
            continue
        e = p.analytes.get(key)
        if e and classify_result(e) == "detected_unquantified":
            out.append({"key": key, "name": name,
                        "raw": (e.get("raw") or e.get("status") or "").strip() or "(blank)",
                        "reason": "Detected but no confirmed numeric value — "
                                  "manual COA review required"})
    return out


def pathogen_detections(p):
    return [nice for k, nice in PATHO_KEYS.items()
            if p.analytes.get(k, {}).get("status") == "DETECTED"]


def report_findings(p, watch):
    """All report-relevant findings for a product, computed from trustworthy data."""
    return dict(quantified=quantified_details(p, watch),
                unquantified=unquantified_findings(p),
                pathogens=pathogen_detections(p),
                thc=bool(p.thc_flags),
                panel_fail=(p.pesticides == "FAIL" or p.solvents == "FAIL"))


def is_flag_driver(d) -> bool:
    """Does this quantified detail itself cross a CannaScope/CT threshold?"""
    v = d.get("value")
    if v is None:
        return False
    if d.get("ct_limit") and v > d["ct_limit"]:
        return True
    if d.get("cs_std") and v >= d["cs_std"]:
        return True
    return False


def report_severity(p, watch):
    """Severity derived ONLY from trustworthy data: pathogens / panel fails -> RED;
    a quantified over-limit -> RED; quantified metal/mycotoxin over the CannaScope
    standard -> ORANGE; quantified yeast/mold / aerobic / solvent over the standard
    -> YELLOW; otherwise an abnormal-THC-only product -> AQUA; else None."""
    f = report_findings(p, watch)
    if f["pathogens"] or f["panel_fail"]:
        return "RED"
    sev = None
    for d in f["quantified"]:
        v = d["value"]
        if d.get("ct_limit") and v > d["ct_limit"]:
            return "RED"
        if d.get("cs_std") and v >= d["cs_std"]:
            key = d["key"]
            here = "YELLOW" if (key in ("tymc", "aerobic") or key.startswith("solvent:")) else "ORANGE"
            sev = here if (sev is None or SEV_RANK[here] > SEV_RANK[sev]) else sev
    if sev:
        return sev
    if f["thc"]:
        return "AQUA"
    return None


def why_flagged(d) -> str:
    """Plain-language reason a quantified contaminant detail was flagged."""
    v, lim, std, key, name = (d["value"], d.get("ct_limit"), d.get("cs_std"),
                              d["key"], d["name"])
    unit = d.get("unit", "")
    if lim and v > lim:
        return f"{name} exceeded the Connecticut legal limit ({v:g} > {lim:g} {unit}).".strip()
    if std and v >= std:
        if key in ("tymc", "aerobic"):
            return f"{name} exceeded the CannaScope CT {int(std):,} CFU/g awareness threshold."
        if key.startswith("solvent:"):
            return f"{name} exceeded 50% of the CT residual-solvent limit (CannaScope CT standard)."
        if d.get("ct_pct") is not None:
            return (f"{name} reached {d['ct_pct']:.0f}% of the CT legal limit "
                    f"(over the CannaScope CT 50% standard).")
        return f"{name} exceeded 50% of the CT legal limit (CannaScope CT standard)."
    return f"{name} detected at {v:g} {unit}.".strip()


def data_confidence(d) -> str:
    """High = numeric + a CT limit to rank against; Medium = numeric but no CT
    limit (ranked by value only). Low never reaches the numeric rankings."""
    if d["key"].startswith("solvent:"):
        return "High" if d.get("ct_limit") else "Medium"
    return "High" if d.get("ct_pct") is not None else "Medium"


def cross_concerns(p, f, lmap=None) -> set:
    cs = set()
    for d in f["quantified"]:
        if not is_flag_driver(d):
            continue
        k = d["key"]
        if k == "tymc":
            cs.add("Yeast & Mold")
        elif k == "aerobic":
            cs.add("Aerobic Bacteria")
        elif k in ("arsenic", "chromium", "cadmium", "lead", "mercury"):
            cs.add("Heavy Metal")
        elif k.startswith("solvent:"):
            cs.add("Solvent")
        elif "afla" in k or k == "ochratoxin":
            cs.add("Mycotoxin")
    if f["pathogens"]:
        cs.add("Pathogen")
    if f["thc"]:
        cs.add("High THC")
    if f["panel_fail"]:
        cs.add("Panel FAIL")
    lab = lab_display(p, lmap)
    if "Unidentified" in lab or "UNRECOGNIZED" in lab or "Unknown" in lab:
        cs.add("Unknown Lab")
    if p.pesticides == "Not tested":
        cs.add("Pesticides not tested")
    return cs


def priority_score(p, f, watch, lmap=None) -> float:
    s = 0.0
    if f["pathogens"]:
        s += 1000
    if f["panel_fail"]:
        s += 400
    for d in f["quantified"]:
        if not is_flag_driver(d):
            continue
        if d.get("ct_limit") and d["value"] > d["ct_limit"]:
            s += 300
        if d.get("ct_pct") is not None:
            s += min(d["ct_pct"], 200)
        else:
            s += 60
    if f["thc"]:
        s += 100 + (thc_headline(p)["over_by"] if p.thc_flags else 0)
    cc = cross_concerns(p, f, lmap)
    if len(cc) > 1:
        s += 50 * len(cc)
    s += 60 * len(f["unquantified"])
    lab = lab_display(p, lmap)
    if "Unidentified" in lab or "UNRECOGNIZED" in lab:
        s += 40
    if p.pesticides == "Not tested":
        s += 30
    return s


# ============================================================================
# Analytics  (all derived from trustworthy / quantified data)
# ============================================================================
def producer_normalized_rates(all_results, reported_set, pmap, watch):
    """Per-producer: reviewed, flagged, % flagged, high/moderate caution counts,
    most-common contaminant, highest CT-limit %, highest CannaScope exceedance.
    'Flagged' uses report_severity / membership in the reported set."""
    reported_ids = {id(p) for p in reported_set}
    reviewed = Counter(); flagged = Counter(); high = Counter(); mod = Counter()
    aqua = Counter(); contam = defaultdict(Counter)
    max_ct = defaultdict(float); max_vs = defaultdict(lambda: None)
    for p in all_results:
        nm = producer_display(p, pmap)
        reviewed[nm] += 1
        if id(p) in reported_ids:
            flagged[nm] += 1
        sev = report_severity(p, watch)
        if sev in ("RED", "ORANGE"):
            high[nm] += 1
        elif sev == "YELLOW":
            mod[nm] += 1
        if p.thc_flags:
            aqua[nm] += 1
        for d in quantified_details(p, watch):
            if not is_flag_driver(d):
                continue
            contam[nm][d["name"]] += 1
            if d.get("ct_pct") is not None:
                max_ct[nm] = max(max_ct[nm], d["ct_pct"])
            if d.get("vs_std") is not None:
                cur = max_vs[nm]
                max_vs[nm] = d["vs_std"] if cur is None else max(cur, d["vs_std"])
    rows = []
    for nm, n in reviewed.items():
        rows.append(dict(producer=nm, reviewed=n, flagged=flagged[nm],
                         pct=(flagged[nm] / n * 100.0) if n else 0.0,
                         high=high[nm], moderate=mod[nm], aqua=aqua[nm],
                         top_contaminant=(contam[nm].most_common(1)[0][0] if contam[nm] else "—"),
                         max_ct_pct=(max_ct[nm] if nm in max_ct else None),
                         max_vs_std=max_vs[nm]))
    return rows


def recurrence_and_signatures(flagged, pmap, lmap, watch):
    pr = defaultdict(lambda: dict(p50=0, p75=0, p90=0, over_cs=0, contam=Counter(),
                                  thc=0, families=Counter(), labs=Counter()))
    sig_pc = Counter(); sig_pt = Counter(); sig_lc = Counter(); sig_lt = Counter()
    fam = defaultdict(list)
    for p in flagged:
        prod = producer_display(p, pmap); lab = lab_display(p, lmap)
        for d in quantified_details(p, watch):
            if not is_flag_driver(d):
                continue
            ct = d.get("ct_pct")
            if ct is not None:
                if ct >= 90: pr[prod]["p90"] += 1
                elif ct >= 75: pr[prod]["p75"] += 1
                elif ct >= 50: pr[prod]["p50"] += 1
            if d.get("vs_std") is not None and d["vs_std"] > 0:
                pr[prod]["over_cs"] += 1
            cname = d["name"]
            pr[prod]["contam"][cname] += 1
            pr[prod]["families"][p.strain or product_core_name(p)] += 1
            pr[prod]["labs"][lab] += 1
            sig_pc[(prod, cname)] += 1
            sig_lc[(lab, cname)] += 1
            fam[(prod, cname)].append(p)
        if p.thc_flags:
            pr[prod]["thc"] += 1
            sig_pt[prod] += 1
            sig_lt[lab] += 1
    signatures = []
    for (prod, cname), n in sig_pc.items():
        if n >= 2:
            signatures.append(dict(kind="Producer × Contaminant", entity=prod, detail=cname,
                                   count=n, note="repeated signal — pattern worth investigating"))
    for prod, n in sig_pt.items():
        if n >= 2:
            signatures.append(dict(kind="Producer × High-THC Flower", entity=prod,
                                   detail="flower cannabinoid > 35%", count=n,
                                   note="repeated high-cannabinoid result — worth verifying"))
    for (lab, cname), n in sig_lc.items():
        if n >= 3:
            signatures.append(dict(kind="Lab × Contaminant", entity=lab, detail=cname, count=n,
                                   note="lab concentration worth reviewing against COAs"))
    for lab, n in sig_lt.items():
        if n >= 3:
            signatures.append(dict(kind="Lab × High-THC Flower", entity=lab,
                                   detail="flower cannabinoid > 35%", count=n,
                                   note="lab concentration of high-THC results — verify vs COAs"))
    signatures.sort(key=lambda s: s["count"], reverse=True)
    return pr, signatures, fam


def product_family_clusters(fam, pmap, lmap, watch):
    clusters = []
    for (prod, cname), prods in fam.items():
        if len(prods) < 2:
            continue
        vals, cts, labs, dates, coas, strains = [], [], set(), [], [], Counter()
        for p in prods:
            for d in quantified_details(p, watch):
                if d["name"] != cname:
                    continue
                if d.get("value") is not None:
                    vals.append((d["value"], d.get("unit", "")))
                if d.get("ct_pct") is not None:
                    cts.append(d["ct_pct"])
            labs.add(lab_display(p, lmap))
            if p.approval_date:
                dates.append(p.approval_date.split()[0])
            coas.append(p.registration_number or "COA")
            strains[p.strain or product_core_name(p)] += 1
        unit = vals[0][1] if vals else ""
        nums = [v for v, _ in vals]
        vrange = (f"{min(nums):g}–{max(nums):g} {unit}".strip() if nums else "—")
        clusters.append(dict(producer=prod, contaminant=cname, count=len(prods),
                             value_range=vrange, max_ct_pct=(max(cts) if cts else None),
                             labs=sorted(labs), dates=sorted(set(dates)), coas=coas,
                             top_strain=(strains.most_common(1)[0][0] if strains else ""),
                             note="repeated family signal — verify each against its COA"))
    clusters.sort(key=lambda c: (c["count"], c["max_ct_pct"] or 0), reverse=True)
    return clusters


def lab_thc_distribution(thc_flagged, pmap, lmap):
    total = max(1, len(thc_flagged))
    by_lab = defaultdict(lambda: dict(n=0, producers=Counter(), max_val=0.0))
    for p in thc_flagged:
        lab = lab_display(p, lmap); h = thc_headline(p)
        by_lab[lab]["n"] += 1
        by_lab[lab]["producers"][producer_display(p, pmap)] += 1
        if h:
            by_lab[lab]["max_val"] = max(by_lab[lab]["max_val"], h["value"])
    return [dict(lab=lab, n=d["n"], pct=d["n"] / total * 100.0, max_val=d["max_val"],
                producers=[nm for nm, _ in d["producers"].most_common(3)])
            for lab, d in sorted(by_lab.items(), key=lambda kv: kv[1]["n"], reverse=True)]


def cleaner_flower(all_results, watch):
    out = []
    for p in all_results:
        if not is_thc_flower(p):
            continue
        if report_severity(p, watch) or p.thc_flags or unquantified_findings(p) or pathogen_detections(p):
            continue
        ym = p.analytes.get("tymc", {}).get("value")
        if ym is None or not (200 <= ym <= 5000):
            continue
        tt = p.cannabinoids.get("total_thc", {}).get("value")
        if tt is not None and tt > THC_REVIEW_PCT:
            continue
        out.append(p)
    out.sort(key=lambda p: p.analytes.get("tymc", {}).get("value") or 0)
    return out


# ---- Trend matrices ----
MATRIX_COLS = ["Yeast & Mold", "Aerobic Bacteria", "Arsenic", "Chromium",
               "Cadmium", "Lead", "High THC"]
_MATRIX_KEY = {"tymc": "Yeast & Mold", "aerobic": "Aerobic Bacteria",
               "arsenic": "Arsenic", "chromium": "Chromium",
               "cadmium": "Cadmium", "lead": "Lead"}


def _matrix(flagged, name_fn, watch):
    M = defaultdict(Counter)
    for p in flagged:
        ent = name_fn(p)
        for d in quantified_details(p, watch):
            if not is_flag_driver(d):
                continue
            col = _MATRIX_KEY.get(d["key"])
            if col:
                M[ent][col] += 1
        if p.thc_flags:
            M[ent]["High THC"] += 1
    return M


def producer_contaminant_matrix(flagged, pmap, watch):
    return _matrix(flagged, lambda p: producer_display(p, pmap), watch)


def lab_contaminant_matrix(flagged, lmap, watch):
    return _matrix(flagged, lambda p: lab_display(p, lmap), watch)


def producer_lab_pairings(flagged, pmap, lmap, watch):
    pair = defaultdict(lambda: dict(n=0, contam=Counter(), max_ct=0.0))
    for p in flagged:
        key = (producer_display(p, pmap), lab_display(p, lmap))
        pair[key]["n"] += 1
        for d in quantified_details(p, watch):
            if not is_flag_driver(d):
                continue
            pair[key]["contam"][d["name"]] += 1
            if d.get("ct_pct") is not None:
                pair[key]["max_ct"] = max(pair[key]["max_ct"], d["ct_pct"])
    rows = []
    for (prod, lab), d in sorted(pair.items(), key=lambda kv: kv[1]["n"], reverse=True):
        rows.append(dict(producer=prod, lab=lab, n=d["n"],
                         main=(d["contam"].most_common(1)[0][0] if d["contam"] else "—"),
                         max_ct=(d["max_ct"] if d["max_ct"] else None)))
    return rows


def priority_queue(reported, watch, pmap, lmap):
    out = []
    for p in reported:
        f = report_findings(p, watch)
        score = priority_score(p, f, watch, lmap)
        reasons = []
        if f["pathogens"]:
            reasons.append("zero-tolerance pathogen reported DETECTED")
        if f["panel_fail"]:
            reasons.append("pesticide/solvent panel FAIL")
        near = [d for d in f["quantified"] if d.get("ct_pct") and d["ct_pct"] >= 75]
        if near:
            reasons.append("near or over a Connecticut legal limit")
        cc = cross_concerns(p, f, lmap)
        if len(cc) > 1:
            reasons.append("multiple concerns (" + ", ".join(sorted(cc)) + ")")
        if f["thc"]:
            reasons.append("abnormally high THC/cannabinoid result")
        if f["unquantified"]:
            reasons.append("non-numeric 'DETECTED' field affecting review")
        lab = lab_display(p, lmap)
        if "Unidentified" in lab or "UNRECOGNIZED" in lab:
            reasons.append("missing/unknown lab")
        if p.pesticides == "Not tested":
            reasons.append("pesticides not tested")
        out.append((p, score, reasons or ["flagged record"]))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


# ============================================================================
# Verification + validation
# ============================================================================
def run_verification(all_results, flagged, thc_flagged, norm_rows, lab_thc, watch):
    notes = []
    mism = 0
    for p in flagged:
        for d in quantified_details(p, watch):
            v, lim = d.get("value"), d.get("ct_limit")
            if v is not None and lim:
                if d.get("ct_pct") is not None and abs(v / lim * 100.0 - d["ct_pct"]) > 0.01:
                    mism += 1
            cs = d.get("cs_std")
            if v is not None and cs:
                if d.get("vs_std") is not None and abs((v - cs) / cs * 100.0 - d["vs_std"]) > 0.01:
                    mism += 1
    notes.append(("CT% / CannaScope recomputation (quantified rows)",
                  "PASS — all consistent" if mism == 0 else f"NEEDS MANUAL VERIFICATION — {mism}"))
    bad = sum(1 for p in thc_flagged
              if not thc_headline(p) or thc_headline(p)["value"] <= THC_REVIEW_PCT or not is_thc_flower(p))
    notes.append(("Aquamarine THC flags > 35% on flower only",
                  "PASS" if bad == 0 else f"NEEDS MANUAL VERIFICATION — {bad}"))
    nf = sum(r["flagged"] for r in norm_rows)
    notes.append(("Producer flagged totals reconcile",
                  "PASS" if nf == len(flagged) else f"NEEDS REVIEW — {nf} vs {len(flagged)}"))
    ls = sum(r["n"] for r in lab_thc)
    notes.append(("Lab high-THC totals reconcile",
                  "PASS" if ls == len(thc_flagged) else f"NEEDS REVIEW — {ls} vs {len(thc_flagged)}"))
    dups = [k for k, n in Counter(v4.coa_key(p) for p in all_results).items() if n > 1]
    notes.append(("Duplicate COA rows",
                  "PASS — none" if not dups else f"NEEDS REVIEW — {len(dups)} duplicate key(s)"))
    return notes, all("NEEDS" not in v for _, v in notes)


def run_validation(reported, flagged, exec_rows, watch):
    """Pre-PDF data validation. Returns (errors, warnings). A CRITICAL error means
    an executive-summary value can't be traced to a quantified detail, or a
    'DETECTED' value leaked into the numeric rankings."""
    errors, warnings = [], []
    for r in exec_rows:
        if r.get("value") is None or r.get("ct_pct") is None:
            errors.append(["exec_summary", r.get("product", "?"),
                           "ranking row lacks a traceable numeric value/CT %"])
    for p in flagged:
        if report_severity(p, watch) is None and not p.thc_flags:
            errors.append(["severity", p.product_name,
                           "appears in flagged set without a quantified severity driver"])
    for p in reported:
        if not p.product_name:
            warnings.append(["missing_field", p.registration_number or "?", "product name blank"])
    return errors, warnings


# ============================================================================
# PDF report
# ============================================================================
def next_report_path():
    import glob
    nums = [int(m.group(1)) for f in glob.glob(os.path.join(OUT_DIR, REPORT_PREFIX + "*.pdf"))
            for m in [re.search(r"_(\d+)\.pdf$", f)] if m]
    n = (max(nums) + 1) if nums else 1
    return os.path.join(OUT_DIR, f"{REPORT_PREFIX}{n}.pdf"), n


def _thc_cell(p) -> str:
    """Cannabinoid summary cell; ▲ marks a value over the 35% review threshold."""
    order = [("total_thc", "Total THC"), ("thc", "THC"), ("d9_thc", "Δ9-THC"),
             ("thca", "THCA"), ("total_cannabinoids", "Total Cannabinoids"),
             ("total_active", "Total Active")]
    lines = []
    flagged_fields = {f["field"] for f in p.thc_flags}
    for key, short in order:
        e = p.cannabinoids.get(key)
        if not e or e.get("value") is None:
            continue
        val = f"{e['value']:g}%"
        if key in flagged_fields:
            lines.append(f'<font color="#0E6B5A"><b>{short}: {val} ▲</b></font>')
        else:
            lines.append(f'{short}: {val}')
    return "<br/>".join(lines) if lines else "—"


CONTAMINANT_SECTIONS = [
    ("tymc", "Yeast & Mold", "CFU/g",
     "Connecticut legal limit: 100,000 CFU/g. CannaScope CT consumer-awareness "
     "threshold: 10,000 CFU/g. Ranked by CT Limit %, then measured CFU/g."),
    ("aerobic", "Total Aerobic Bacteria", "CFU/g",
     "Connecticut legal limit: 100,000 CFU/g. CannaScope CT consumer-awareness "
     "threshold: 10,000 CFU/g. Ranked by CT Limit %, then measured CFU/g."),
    ("arsenic", "Arsenic", "",
     "Flagged at/over 50% of the COA's Connecticut legal limit (CannaScope CT "
     "standard). Heavy metals are shown in the COA's own units (µg/kg / ppm)."),
    ("chromium", "Chromium", "",
     "Flagged at/over 50% of the COA's Connecticut legal limit (CannaScope CT "
     "standard). Heavy metals are shown in the COA's own units (µg/kg / ppm)."),
    ("cadmium", "Cadmium", "",
     "Flagged at/over 50% of the COA's Connecticut legal limit (CannaScope CT "
     "standard). Heavy metals are shown in the COA's own units (µg/kg / ppm)."),
    ("lead", "Lead", "",
     "Flagged at/over 50% of the COA's Connecticut legal limit (CannaScope CT "
     "standard). Heavy metals are shown in the COA's own units (µg/kg / ppm)."),
]
_SECTION_KEYS = {k for k, _, _, _ in CONTAMINANT_SECTIONS}


def build_pdf(out_path, report_no, all_results, reported, flagged, thc_flagged,
              manual_review, norm_rows, recurrence, signatures, clusters, lab_thc,
              cleaner, identities, prio, prod_matrix, lab_matrix, pairings,
              exec_rows, verify_notes, validation, pmap, lmap, watch, window_str):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, legal
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, PageBreak)

    BF, BFB = v4._setup_fonts()
    NAVY = colors.HexColor("#1F2D3D"); AQUA = colors.HexColor("#0E6B5A")
    PURPLE = colors.HexColor("#7D3C98"); PAGE = landscape(legal)
    esc = v4._esc

    title_st = ParagraphStyle("title", fontName=BFB, fontSize=22, leading=25, alignment=1,
                              textColor=NAVY, spaceAfter=3)
    sub_st = ParagraphStyle("sub", fontName=BF, fontSize=12, leading=15, alignment=1,
                            textColor=colors.HexColor("#444444"), spaceAfter=3)
    meta_st = ParagraphStyle("meta", fontName=BF, fontSize=9.5, leading=12, alignment=1,
                             textColor=colors.HexColor("#444444"), spaceAfter=2)
    note_st = ParagraphStyle("note", fontName=BF, fontSize=9, leading=12, alignment=1)
    body_st = ParagraphStyle("body", fontName=BF, fontSize=9.5, leading=13,
                             textColor=colors.HexColor("#222222"), spaceAfter=5)
    cell = ParagraphStyle("c", fontName=BF, fontSize=7.6, leading=9.4)
    cellc = ParagraphStyle("cc", parent=cell, alignment=1)
    head = ParagraphStyle("h", fontName=BFB, fontSize=7.6, leading=9.6, textColor=colors.white)
    risk = ParagraphStyle("r", fontName=BFB, fontSize=7, leading=8, alignment=1, textColor=colors.white)
    h1 = ParagraphStyle("h1", fontName=BFB, fontSize=17, leading=20, spaceAfter=6, textColor=NAVY)
    h2 = ParagraphStyle("h2", fontName=BFB, fontSize=13, leading=16, spaceBefore=4, spaceAfter=3, textColor=NAVY)
    h2s = ParagraphStyle("h2s", fontName=BF, fontSize=9, leading=11.5, spaceAfter=6,
                         textColor=colors.HexColor("#444444"))

    now = datetime.datetime.now().astimezone()
    date_created = now.strftime("%Y-%m-%d")
    time_created = now.strftime("%I:%M %p %Z").lstrip("0").strip()

    doc = SimpleDocTemplate(out_path, pagesize=PAGE, leftMargin=0.32*inch, rightMargin=0.32*inch,
                            topMargin=0.5*inch, bottomMargin=0.6*inch,
                            title=f"{APP_NAME} — Report {report_no}", author=APP_NAME)

    def tstyle(header_color=NAVY, band="#eef2f5"):
        return TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), header_color),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d2da")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(band)]),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)])

    def table(headers, rows, widths, header_color=NAVY, band="#eef2f5", valign_top=False):
        data = [[Paragraph(h, head) for h in headers]]
        for r in rows:
            data.append([x if hasattr(x, "wrap") else Paragraph(str(x), cell) for x in r])
        tb = Table(data, repeatRows=1, colWidths=widths)
        st = tstyle(header_color, band)
        if valign_top:
            st.add("VALIGN", (0, 0), (-1, -1), "TOP")
        tb.setStyle(st)
        return tb

    def colp(text, color):
        return Paragraph(f'<font color="{color}"><b>{text}</b></font>', cell)

    def section(title, blurb=None, color=NAVY, new_page=True):
        items = [PageBreak()] if new_page else []
        items.append(Paragraph(esc(title), ParagraphStyle("hx", parent=h1, textColor=color)))
        if blurb:
            items.append(Paragraph(blurb, h2s))
        return items

    sev_counts = Counter(report_severity(p, watch) for p in flagged)
    n_red = sev_counts.get("RED", 0); n_org = sev_counts.get("ORANGE", 0)
    n_yel = sev_counts.get("YELLOW", 0); n_aqua = len(thc_flagged)

    story = []

    # -------- COVER --------
    story += [
        Paragraph(APP_NAME, title_st),
        Paragraph(esc(REPORT_TITLE), sub_st),
        Paragraph(f"Report #{report_no}", meta_st),
        Paragraph(f"<b>Date Created:</b> {date_created} &nbsp;|&nbsp; <b>Time Created:</b> "
                  f"{esc(time_created)} &nbsp;|&nbsp; <b>Dataset Window:</b> {esc(window_str)}", meta_st),
        Spacer(1, 10),
        Paragraph(f"<b>{esc(FRAMING)}</b>",
                  ParagraphStyle("frame", parent=note_st, fontSize=10, leading=14, textColor=NAVY,
                                 backColor=colors.HexColor("#eef2f5"), borderPadding=8)),
        Spacer(1, 10),
        Paragraph(f"<b>{len(all_results):,}</b> products reviewed &nbsp;•&nbsp; "
                  f"<b>{len(flagged):,}</b> flagged &nbsp;•&nbsp; "
                  f'<font color="#C0392B"><b>{n_red} Do Not Consume</b></font> &nbsp;•&nbsp; '
                  f'<font color="#E67E22"><b>{n_org} High Caution</b></font> &nbsp;•&nbsp; '
                  f'<font color="#B8950A"><b>{n_yel} Moderate Caution</b></font> &nbsp;•&nbsp; '
                  f'<font color="#0E6B5A"><b>{n_aqua} High-THC Review</b></font> &nbsp;•&nbsp; '
                  f"<b>{len(manual_review):,}</b> need manual COA review", meta_st),
        Spacer(1, 12),
        Paragraph('<font color="#C0392B"><b>RED = Do Not Consume / extreme concern</b></font> &nbsp; '
                  '<font color="#E67E22"><b>ORANGE = High Caution</b></font> &nbsp; '
                  '<font color="#B8950A"><b>YELLOW = Moderate Caution</b></font> &nbsp; '
                  '<font color="#0E6B5A"><b>AQUAMARINE = THC / Cannabinoid Result Requiring '
                  'Investigation</b></font> &nbsp; '
                  '<font color="#7D3C98"><b>PURPLE = Potentially Lower-Concern Product</b></font>', note_st),
    ]

    # -------- HOW TO READ --------
    story += section("How to Read This Report")
    htr = [
        "<b>CannaScope CT is stricter than Connecticut's legal failure standard.</b> A flag is "
        "NOT proof of an illegal, failed, or unsafe product — it is a lead for verification.",
        "<b>CT Limit %</b> = measured value &divide; the COA's Connecticut legal limit &times; 100. "
        "<b>CannaScope Difference</b> = how far a result is above (+) or below (&minus;) the stricter "
        "CannaScope CT threshold (Yeast &amp; Mold / Aerobic = 10,000 CFU/g; all other contaminants = "
        "50% of the Connecticut legal limit).",
        "<b>“Detected but not quantified”</b> means a COA field reported a detection without a "
        "confirmed number (e.g. just “DETECTED”). These are NOT ranked numerically — they are routed "
        "to a manual-COA-review section. No value in this report's rankings is a guessed number.",
        "<b>Aquamarine</b> marks an abnormally high THC / cannabinoid flower result (over 35%) that is "
        "unusual enough to review — not proof of fraud.",
        "<b>Producer raw counts ≠ normalized rates.</b> Raw counts show volume; normalized rates show "
        "how often a producer's reviewed products were flagged.",
        "The report is organized by contaminant, each ranked most-severe first, so you can see the "
        "biggest findings, what to review first, and which producers and labs recur.",
    ]
    for t in htr:
        story.append(Paragraph("•&nbsp; " + t, body_st))

    # -------- EXECUTIVE SUMMARY --------
    story += section("Executive Summary",
                     "Headline counts and fully-traceable rankings. Every ranked product below ties to "
                     "a quantified value in its contaminant section. Every figure is a lead for "
                     "verification against the original COA.")
    story.append(table(["Metric", "Count"],
                       [["Total products reviewed", f"{len(all_results):,}"],
                        ["Total products flagged", f"{len(flagged):,}"],
                        ["Do Not Consume (Red)", str(n_red)],
                        ["High Caution (Orange)", str(n_org)],
                        ["Moderate Caution (Yellow)", str(n_yel)],
                        ["Aquamarine High-THC Review", str(n_aqua)],
                        ["Detected but not quantified — manual review", f"{len(manual_review):,}"]],
                       [5.0*inch, 2.0*inch]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Top Producers by Raw Flag Count", h2))
    rows = [[Paragraph(esc(r["producer"]), cell), str(r["flagged"]), str(r["reviewed"]),
             f'{r["pct"]:.1f}%'] for r in sorted(norm_rows, key=lambda r: r["flagged"], reverse=True)[:10]
            if r["flagged"] > 0]
    story.append(table(["Producer", "Flagged", "Reviewed", "% Flagged"], rows,
                       [4.2*inch, 1.3*inch, 1.3*inch, 1.4*inch]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Top Producers by Normalized Flag Rate (≥ 3 products reviewed)", h2))
    rows = [[Paragraph(esc(r["producer"]), cell), f'{r["pct"]:.1f}%', str(r["flagged"]), str(r["reviewed"])]
            for r in sorted([r for r in norm_rows if r["reviewed"] >= 3 and r["flagged"] > 0],
                            key=lambda r: r["pct"], reverse=True)[:10]]
    story.append(table(["Producer", "% Flagged", "Flagged", "Reviewed"], rows,
                       [4.2*inch, 1.4*inch, 1.3*inch, 1.3*inch]))

    # Exec — traceable cross-category ranking table (clearly labeled)
    story += section("Executive Summary — Top Quantified Results (Cross-Category)",
                     "Clearly-labeled cross-category comparison. Units differ by contaminant; see each "
                     "contaminant's own section for the unit-consistent ranking.")
    rows = []
    for i, r in enumerate(exec_rows[:20], 1):
        rows.append([str(i), Paragraph(esc(r["product"]), cell), Paragraph(esc(r["producer"]), cell),
                     Paragraph(esc(r["brand"]), cell), Paragraph(esc(r["lab"]), cell),
                     Paragraph(esc(r["contaminant"]), cell),
                     Paragraph(esc(v4._fmt_value(r["value"], r["unit"])), cell),
                     Paragraph(esc(v4._fmt_value(r["ct_limit"], r["unit"]) if r["ct_limit"] else "—"), cell),
                     colp(v4.ct_pct_label(r["ct_pct"], full=False), v4.pct_color(r["ct_pct"])),
                     colp(v4.vs_standard_label(r["vs_std"], full=False) if r["vs_std"] is not None else "—",
                          v4.vs_color(r["vs_std"])),
                     Paragraph(esc(r["coa"]), cellc), Paragraph(esc(r["section"]), cell)])
    story.append(table(["#", "Product", "Producer", "Brand / DBA", "Lab", "Contaminant", "Measured",
                        "CT Limit", "CT %", "CannaScope Diff", "COA #", "Section"], rows,
                       [0.28*inch, 1.7*inch, 1.5*inch, 1.0*inch, 1.0*inch, 1.2*inch, 0.95*inch,
                        0.95*inch, 0.8*inch, 1.2*inch, 0.85*inch, 1.0*inch], valign_top=True))

    # -------- PRIORITY REVIEW QUEUE --------
    story += section("Priority Review Queue — Products Most Worth Manual COA Verification",
                     "Highest-priority records for manual verification. Not an accusation of wrongdoing — "
                     "these records combine the most review signals (near-limit results, multiple "
                     "concerns, high-THC, non-numeric fields, unknown lab, or untested panels).")
    rows = []
    for i, (p, score, reasons) in enumerate(prio[:25], 1):
        f = report_findings(p, watch)
        rows.append([str(i), Paragraph(esc(p.product_name), cell),
                     Paragraph(esc(producer_display(p, pmap)), cell),
                     Paragraph(esc(lab_display(p, lmap)), cell),
                     colp(report_severity(p, watch) or "REVIEW",
                          v4.SEV_BAR.get(report_severity(p, watch), "#555555")),
                     Paragraph(esc("; ".join(reasons)), cell),
                     Paragraph(esc(p.registration_number or "COA"), cellc)])
    story.append(table(["#", "Product", "Producer", "Lab", "Severity", "Why It's Priority", "COA #"],
                       rows, [0.28*inch, 2.0*inch, 1.7*inch, 1.2*inch, 0.9*inch, 4.2*inch, 0.9*inch],
                       valign_top=True))

    # -------- PRODUCER FLAG RATES --------
    story += section("Producer Flag Rates — Raw Counts vs Normalized Risk",
                     "“Raw flag counts show volume of flagged products, but normalized rates show how "
                     "often a producer's products were flagged relative to the number reviewed.” "
                     "Reviewed totals are the products scanned in this window (see Limitations).")
    rows = []
    for r in sorted(norm_rows, key=lambda r: (r["pct"], r["flagged"]), reverse=True):
        if r["flagged"] == 0:
            continue
        rows.append([Paragraph(esc(r["producer"]), cell), str(r["reviewed"]), str(r["flagged"]),
                     colp(f'{r["pct"]:.1f}%', "#C0392B" if r["pct"] >= 50 else ("#E67E22" if r["pct"] >= 25 else "#1F2D3D")),
                     str(r["high"]), str(r["moderate"]), str(r["aqua"]),
                     Paragraph(esc(r["top_contaminant"]), cell),
                     (v4.ct_pct_label(r["max_ct_pct"], full=False) if r["max_ct_pct"] is not None else "—"),
                     (v4.vs_standard_label(r["max_vs_std"], full=False) if r["max_vs_std"] is not None else "—")])
    story.append(table(["Producer", "Reviewed", "Flagged", "% Flagged", "High", "Moderate", "High-THC",
                        "Most Common Contaminant", "Highest CT %", "Highest CannaScope Exceedance"], rows,
                       [2.3*inch, 0.8*inch, 0.75*inch, 0.9*inch, 0.55*inch, 0.85*inch, 0.7*inch,
                        1.8*inch, 0.95*inch, 1.6*inch], valign_top=True))

    # -------- RECURRENCE / SIGNATURES --------
    story += section("CannaScope Recurrence Score & Recurring Contaminant Signatures",
                     "Repeated pairings worth investigating. A repeated signal may indicate a "
                     "production, source-material, environmental, remediation, or testing-pattern "
                     "issue — verify each against the original COA. No legal conclusion is asserted.")
    story.append(Paragraph("Producer Recurrence Score (threshold crossings)", h2))
    rows = []
    for prod, d in sorted(recurrence.items(),
                          key=lambda kv: kv[1]["p90"]*3 + kv[1]["p75"]*2 + kv[1]["p50"]
                          + kv[1]["thc"]*2 + kv[1]["over_cs"], reverse=True)[:20]:
        rows.append([Paragraph(esc(prod), cell), str(d["p50"]), str(d["p75"]), str(d["p90"]),
                     str(d["over_cs"]), str(d["thc"]),
                     Paragraph(esc(d["contam"].most_common(1)[0][0] if d["contam"] else "—"), cell)])
    story.append(table(["Producer", "≥50% CT", "≥75% CT", "≥90% CT", "Over CannaScope", "High-THC",
                        "Most Common Contaminant"], rows,
                       [2.6*inch, 1.0*inch, 1.0*inch, 1.0*inch, 1.4*inch, 0.95*inch, 1.9*inch]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Recurring Contaminant Signatures", h2))
    if signatures:
        rows = [[Paragraph(esc(s["kind"]), cell), Paragraph(esc(s["entity"]), cell),
                 Paragraph(esc(s["detail"]), cell), str(s["count"]), Paragraph(esc(s["note"]), cell)]
                for s in signatures[:30]]
        story.append(table(["Signature Type", "Entity", "Detail", "Count", "Review Note"], rows,
                           [2.0*inch, 2.4*inch, 1.8*inch, 0.7*inch, 2.6*inch], valign_top=True))
    else:
        story.append(Paragraph("No repeated signatures met the recurrence threshold in this run.", cell))

    # -------- TREND MATRICES --------
    story += section("Trend Matrices — Contaminant by Producer and by Lab",
                     "Counts of flagged products by contaminant category. A quick map of where patterns "
                     "concentrate. Verify any concentration against the original COAs.")
    story.append(Paragraph("Contaminant by Producer Matrix", h2))
    prods = sorted(prod_matrix.keys(), key=lambda k: -sum(prod_matrix[k].values()))[:20]
    rows = [[Paragraph(esc(pr), cell)] + [str(prod_matrix[pr].get(c, 0) or "") for c in MATRIX_COLS]
            for pr in prods]
    story.append(table(["Producer"] + MATRIX_COLS, rows,
                       [3.0*inch] + [1.28*inch]*len(MATRIX_COLS)))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Contaminant by Lab Matrix", h2))
    labs = sorted(lab_matrix.keys(), key=lambda k: -sum(lab_matrix[k].values()))
    rows = [[Paragraph(esc(lb), cell)] + [str(lab_matrix[lb].get(c, 0) or "") for c in MATRIX_COLS]
            for lb in labs]
    story.append(table(["Lab"] + MATRIX_COLS, rows, [3.0*inch] + [1.28*inch]*len(MATRIX_COLS)))

    # -------- PRODUCER-LAB PAIRINGS + REPEATED FAMILIES --------
    story += section("Producer-Lab Pairings & Repeated Product Families",
                     "Which producer/lab pairs recur, and which product families repeat. Patterns "
                     "worth investigating, not conclusions.")
    story.append(Paragraph("Producer-Lab Pairing Table", h2))
    rows = [[Paragraph(esc(r["producer"]), cell), Paragraph(esc(r["lab"]), cell), str(r["n"]),
             Paragraph(esc(r["main"]), cell),
             (v4.ct_pct_label(r["max_ct"], full=False) if r["max_ct"] is not None else "—")]
            for r in pairings[:20] if r["n"] >= 1]
    story.append(table(["Producer", "Lab", "Flagged Products", "Main Contaminant", "Highest CT %"], rows,
                       [3.0*inch, 2.2*inch, 1.4*inch, 1.9*inch, 1.3*inch], valign_top=True))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Repeated Product Family Table", h2))
    if clusters:
        rows = [[Paragraph(esc(c["top_strain"] or c["producer"]), cell),
                 Paragraph(esc(c["producer"]), cell), str(c["count"]),
                 Paragraph(esc(c["contaminant"]), cell), Paragraph(esc(c["value_range"]), cell),
                 Paragraph(esc(", ".join(c["labs"])), cell),
                 Paragraph(esc(", ".join(c["dates"][:4])), cell)] for c in clusters[:25]]
        story.append(table(["Product Family / Strain", "Producer", "Appearances", "Main Contaminant",
                            "Value Range", "Lab(s)", "Dates"], rows,
                           [2.0*inch, 1.9*inch, 0.95*inch, 1.4*inch, 1.5*inch, 1.5*inch, 1.6*inch],
                           valign_top=True))
    else:
        story.append(Paragraph("No product family reached the 2+ appearance threshold in this run.", cell))

    # -------- IDENTITY NOTES --------
    story += section("Producer Name Translation & Identity Notes",
                     "Legal entity → common brand / DBA / parent / license. Confirmed entries cite a "
                     "public source; anything not confidently confirmed is marked “verify manually.” "
                     "Names are never invented.")
    irows = []
    order = {"CONFIRMED": 0, "LIKELY": 1, "UNRESOLVED": 2}
    for rec in sorted(identities.values(),
                      key=lambda r: (order.get(r.get("confidence"), 3), r["legal"].lower())):
        conf = rec.get("confidence", "UNRESOLVED")
        if rec["confirmed"] and conf == "CONFIRMED":
            mapping = f'{esc(rec["legal"])} → <b>{esc(rec["common"])}</b>'
            status = '<font color="#1E7E34"><b>CONFIRMED</b></font>'
            brands = ", ".join(rec["brands"]) if rec["brands"] else "—"
        elif rec["confirmed"]:
            mapping = (f'{esc(rec["legal"])} → <b>{esc(rec["common"])}</b> '
                       f'<font color="#E67E22">(verify manually)</font>')
            status = '<font color="#E67E22"><b>LIKELY — verify</b></font>'
            brands = ", ".join(rec["brands"]) if rec["brands"] else "—"
        else:
            mapping = (f'{esc(rec["legal"])} → <font color="#C0392B"><b>DBA / parent company not '
                       f'confirmed — verify manually</b></font>')
            status = '<font color="#C0392B"><b>UNRESOLVED</b></font>'
            brands = "—"
        irows.append([Paragraph(mapping, cell), Paragraph(esc(rec["parent"] or "—"), cell),
                      Paragraph(esc(brands), cell), Paragraph(esc(rec["license"] or "—"), cell),
                      Paragraph(status + ('<br/>' + esc(rec["source"]) if rec["source"] else ''), cell)])
    story.append(table(["Legal Entity → Common Name / DBA", "Parent Company", "Brands", "License",
                        "Confidence / Source"], irows,
                       [3.0*inch, 1.7*inch, 1.5*inch, 1.7*inch, 2.4*inch], valign_top=True))

    # -------- CONTAMINANT-SPECIFIC SEVERITY SECTIONS --------
    def contaminant_section(key, title, blurb):
        items = [(p, d) for p in flagged
                 for d in [next((x for x in quantified_details(p, watch)
                                 if x["key"] == key and is_flag_driver(x)), None)] if d]
        items.sort(key=lambda pd: (pd[1]["ct_pct"] if pd[1]["ct_pct"] is not None else -1,
                                   pd[1]["value"] or 0,
                                   pd[1]["vs_std"] if pd[1]["vs_std"] is not None else -1e9,
                                   SEV_RANK.get(report_severity(pd[0], watch), 0),
                                   v4.parse_date(pd[0].approval_date)), reverse=True)
        blk = section(f"{title} — Ranked by Severity", blurb)
        if not items:
            blk.append(Paragraph(f"No quantified {title} results crossed a CannaScope CT threshold "
                                 "in this run.", cell))
            return blk
        # trend summary
        vals = [d["value"] for _, d in items if d["value"] is not None]
        top_p, top_d = items[0]
        prod_counts = Counter(producer_display(p, pmap) for p, _ in items)
        lab_counts = Counter(lab_display(p, lmap) for p, _ in items)
        spread = ("concentrated in one producer" if prod_counts.most_common(1)[0][1] > len(items) / 2
                  else "spread across producers")
        blk.append(Paragraph(
            f"<b>{title} Trend Summary</b> &nbsp; Total flagged: <b>{len(items)}</b> &nbsp;•&nbsp; "
            f"Highest value: <b>{v4._fmt_value(max(vals), top_d['unit']) if vals else '—'}</b> "
            f"({esc(top_p.product_name)} by {esc(producer_display(top_p, pmap))}) &nbsp;•&nbsp; "
            f"Most frequent producer: <b>{esc(prod_counts.most_common(1)[0][0])}</b> &nbsp;•&nbsp; "
            f"Most frequent lab: <b>{esc(lab_counts.most_common(1)[0][0])}</b> &nbsp;•&nbsp; "
            f"Pattern: {spread} — verify against original COAs.", body_st))
        rows = []
        for i, (p, d) in enumerate(items, 1):
            f = report_findings(p, watch)
            cc = cross_concerns(p, f, lmap)
            rows.append([str(i), Paragraph(esc(p.product_name), cell),
                         Paragraph(esc(producer_display(p, pmap)), cell),
                         Paragraph(esc(", ".join(thc_or_brand(p))), cell),
                         Paragraph(esc(lab_display(p, lmap)), cell),
                         Paragraph(esc(v4._fmt_value(d["value"], d["unit"])), cellc),
                         Paragraph(esc(v4._fmt_value(d["ct_limit"], d["unit"]) if d["ct_limit"] else "—"), cellc),
                         colp(v4.ct_pct_label(d["ct_pct"], full=False), v4.pct_color(d["ct_pct"])),
                         colp(v4.vs_standard_label(d["vs_std"], full=False) if d["vs_std"] is not None else "—",
                              v4.vs_color(d["vs_std"])),
                         Paragraph(esc(why_flagged(d)), cell),
                         Paragraph(data_confidence(d), cellc),
                         Paragraph(("Yes — " + ", ".join(sorted(cc))) if len(cc) > 1 else "No", cell),
                         Paragraph(esc(p.registration_number or "COA"), cellc)])
        blk.append(Spacer(1, 4))
        blk.append(table(["#", "Product", "Producer", "Brand / DBA", "Lab", "Measured", "CT Limit",
                          "CT %", "CannaScope", "Why This Was Flagged", "Conf.", "Cross-Flagged?", "COA #"],
                         rows, [0.28*inch, 1.5*inch, 1.25*inch, 0.85*inch, 0.9*inch, 0.85*inch, 0.8*inch,
                                0.65*inch, 0.95*inch, 2.0*inch, 0.55*inch, 1.3*inch, 0.8*inch],
                         valign_top=True))
        return blk

    def thc_or_brand(p):
        b = (p.brand or "").strip()
        return [b] if b else ["—"]

    for key, title, _unit, blurb in CONTAMINANT_SECTIONS:
        story += contaminant_section(key, title, blurb)

    # Other quantified contaminants (not in the dedicated sections above)
    story += section("Other Quantified Contaminants — Ranked by Severity",
                     "Quantified mercury, mycotoxins, residual solvents, and other regulated "
                     "contaminants. Units are shown per row to keep categories distinct.")
    other = []
    for p in flagged:
        for d in quantified_details(p, watch):
            if d["key"] in _SECTION_KEYS or not is_flag_driver(d):
                continue
            other.append((p, d))
    other.sort(key=lambda pd: (pd[1]["ct_pct"] if pd[1]["ct_pct"] is not None else -1,
                               pd[1]["vs_std"] if pd[1]["vs_std"] is not None else -1e9), reverse=True)
    if other:
        rows = []
        for i, (p, d) in enumerate(other, 1):
            rows.append([str(i), Paragraph(esc(d["name"]), cell), Paragraph(esc(p.product_name), cell),
                         Paragraph(esc(producer_display(p, pmap)), cell), Paragraph(esc(lab_display(p, lmap)), cell),
                         Paragraph(esc(v4._fmt_value(d["value"], d["unit"])), cellc),
                         Paragraph(esc(v4._fmt_value(d["ct_limit"], d["unit"]) if d["ct_limit"] else "—"), cellc),
                         colp(v4.ct_pct_label(d["ct_pct"], full=False), v4.pct_color(d["ct_pct"])),
                         Paragraph(esc(why_flagged(d)), cell), Paragraph(esc(p.registration_number or "COA"), cellc)])
        story.append(table(["#", "Contaminant", "Product", "Producer", "Lab", "Measured", "CT Limit",
                            "CT %", "Why This Was Flagged", "COA #"], rows,
                           [0.28*inch, 1.4*inch, 1.7*inch, 1.5*inch, 1.1*inch, 0.95*inch, 0.9*inch,
                            0.75*inch, 2.3*inch, 0.85*inch], valign_top=True))
    else:
        story.append(Paragraph("No other quantified contaminants crossed a CannaScope CT threshold.", cell))

    # -------- DETECTED BUT NOT QUANTIFIED --------
    story += section("Detected But Not Quantified — Requires Manual COA Review",
                     "These fields reported a detection without a confirmed numeric value, so they are "
                     "deliberately EXCLUDED from severity rankings and CT Limit % math. Zero-tolerance "
                     "pathogen detections (qualitative) are listed first as do-not-consume leads.")
    drows = []
    for p in all_results:
        for nice in pathogen_detections(p):
            drows.append((True, p, nice, "DETECTED",
                          "Zero-tolerance pathogen reported DETECTED — do-not-consume if confirmed; verify COA"))
        for u in unquantified_findings(p):
            drows.append((False, p, u["name"], u["raw"], u["reason"]))
    drows.sort(key=lambda t: (not t[0], producer_display(t[1], pmap)))
    if drows:
        rows = []
        for patho, p, field, raw, reason in drows:
            rows.append([Paragraph(esc(p.product_name), cell), Paragraph(esc(producer_display(p, pmap)), cell),
                         Paragraph(esc(lab_display(p, lmap)), cell), Paragraph(esc(p.registration_number or "COA"), cellc),
                         (colp(esc(field), "#C0392B") if patho else Paragraph(esc(field), cell)),
                         Paragraph(esc(raw), cellc), Paragraph(esc(reason), cell)])
        story.append(table(["Product", "Producer", "Lab", "COA #", "Contaminant Field", "Raw Text Value",
                            "Reason Excluded From Ranking"], rows,
                           [2.0*inch, 1.7*inch, 1.2*inch, 0.9*inch, 1.7*inch, 1.2*inch, 3.0*inch],
                           valign_top=True))
    else:
        story.append(Paragraph("No detected-but-not-quantified fields in this run.", cell))

    # -------- HIGH-THC --------
    story += section("Abnormally High THC & Cannabinoid Results Requiring Review",
                     "“These results are not proof of falsification, but flower products above 35% THC "
                     "or total cannabinoids are unusual enough to require review, especially when "
                     "repeated by the same producer or lab.”", color=AQUA)
    if thc_flagged:
        prod_counts = Counter(producer_display(p, pmap) for p in thc_flagged)
        rows = []
        for p in thc_flagged:
            h = thc_headline(p); prod = producer_display(p, pmap)
            coa = (f'<link href="{esc(p.report_url)}"><font color="#1155CC"><u><b>'
                   f'{esc(p.registration_number or "COA")}</b></u></font></link>' if p.report_url
                   else f'<b>{esc(p.registration_number or "COA")}</b>')
            rows.append([Paragraph(esc(p.product_name), cell), Paragraph(esc(prod), cell),
                         Paragraph(esc(p.dosage_form), cell), Paragraph(esc(lab_display(p, lmap)), cell),
                         Paragraph(_thc_cell(p), cell), Paragraph(f'<b>{esc(h["name"])}</b>', cell),
                         colp(f'+{h["over_by"]:.1f}%', "#0E6B5A"),
                         Paragraph(("Yes" if p.flags or report_severity(p, watch) in ("RED", "ORANGE", "YELLOW") else "No")
                                   + (f' / repeat producer ×{prod_counts[prod]}' if prod_counts[prod] > 1 else ''), cell),
                         Paragraph(coa, cellc),
                         Paragraph(p.approval_date.split()[0] if p.approval_date else "", cellc)])
        story.append(table(["Product", "Producer", "Form", "Lab", "Cannabinoids", "Triggering Field",
                            "Over 35% By", "Also Contaminant? / Repeat", "COA #", "Date"], rows,
                           [2.1*inch, 1.5*inch, 0.9*inch, 1.1*inch, 1.5*inch, 1.2*inch, 0.85*inch,
                            1.7*inch, 0.95*inch, 0.65*inch], header_color=AQUA, band="#d4f5ee",
                           valign_top=True))
    else:
        story.append(Paragraph("No flower-based products exceeded the 35% cannabinoid review threshold "
                               "in this run.", cell))

    # -------- LAB HIGH-THC DISTRIBUTION --------
    story += section("Lab Distribution of High-THC Flower Results",
                     "Share of abnormally-high THC flower results by lab. Not an accusation of "
                     "wrongdoing — a lab concentration worth reviewing; patterns should be checked "
                     "against the original COAs.", color=AQUA)
    if lab_thc:
        also = Counter(lab_display(p, lmap) for p in flagged if report_severity(p, watch) in ("RED", "ORANGE", "YELLOW"))
        rows = [[Paragraph(esc(r["lab"]), cell), str(r["n"]), f'{r["pct"]:.1f}%', f'{r["max_val"]:g}%',
                 Paragraph(esc(", ".join(r["producers"])), cell), ("yes" if also.get(r["lab"]) else "no")]
                for r in lab_thc]
        story.append(table(["Lab", "High-THC Flower Flags", "% of High-THC Flags",
                            "Highest THC/Cannabinoid Value", "Main Producers", "Also in Contaminant Flags?"],
                           rows, [2.4*inch, 1.6*inch, 1.5*inch, 1.9*inch, 2.6*inch, 1.4*inch], header_color=AQUA,
                           band="#d4f5ee", valign_top=True))
        top = lab_thc[0]
        interp = (f"High-THC outliers are spread across {len(lab_thc)} lab(s). " if len(lab_thc) > 1
                  else "High-THC outliers are concentrated in a single lab. ")
        if top["pct"] >= 60:
            interp += (f"{esc(top['lab'])} accounts for {top['pct']:.0f}% of high-THC flower flags — a "
                       f"lab concentration worth reviewing against original COAs. ")
        interp += "Where the same producer and lab repeatedly pair, the pattern should be checked against the COAs."
        story.append(Spacer(1, 8)); story.append(Paragraph(interp, body_st))
    else:
        story.append(Paragraph("No high-THC flower flags to distribute in this run.", cell))

    # -------- CLEANER PRODUCTS --------
    story += section("Potentially Lower-Concern Flower Products for Review",
                     "“These products are not endorsed as safe. They simply showed fewer flagged "
                     "signals under the CannaScope CT review logic.” Flower-based, not flagged for any "
                     "contaminant, no high-THC flag, yeast &amp; mold in a normal nonzero 200–5,000 "
                     "CFU/g range.", color=PURPLE)
    if cleaner:
        rows = []
        for p in cleaner[:40]:
            ym = p.analytes.get("tymc", {}).get("value")
            tt = p.cannabinoids.get("total_thc", {}).get("value")
            rows.append([Paragraph(esc(p.product_name), cell), Paragraph(esc(producer_display(p, pmap)), cell),
                         Paragraph(esc(p.dosage_form), cell), Paragraph(esc(lab_display(p, lmap)), cell),
                         (f"{int(ym):,}" if ym is not None else "—"), (f"{tt:g}%" if tt is not None else "—"),
                         Paragraph(esc(p.registration_number or "COA"), cellc)])
        story.append(table(["Product", "Producer", "Form", "Lab", "Yeast & Mold (CFU/g)", "Total THC", "COA #"],
                           rows, [2.6*inch, 1.8*inch, 1.0*inch, 1.2*inch, 1.4*inch, 0.9*inch, 1.0*inch],
                           header_color=PURPLE, band="#ead9f2", valign_top=True))
    else:
        story.append(Paragraph("This run did not contain enough non-flagged flower products with a "
                               "normal-range yeast &amp; mold reading to populate this section. A fuller "
                               "reviewed-product dataset is required to build it completely.", body_st))

    # -------- VALIDATION + LIMITATIONS --------
    story += section("Internal Validation & Accuracy Pass")
    rows = [[Paragraph(esc(k), cell), colp(esc(v), "#1E7E34" if "PASS" in v else "#C0392B")]
            for k, v in verify_notes]
    story.append(table(["Check", "Result"], rows, [5.0*inch, 3.0*inch]))
    story.append(Spacer(1, 8))
    errs, warns = validation
    story.append(Paragraph(
        ('<font color="#1E7E34"><b>Data validation: PASSED — every ranked value is traceable to a '
         'quantified COA result.</b></font>' if not errs else
         f'<font color="#C0392B"><b>Data validation: {len(errs)} error(s) — see '
         'validation_error_report.csv.</b></font>')
        + (f' &nbsp; {len(warns)} warning(s).' if warns else ''), body_st))

    story += section("Major Limitations & Methodology",
                     "Read every figure in this report as a lead for verification, not a conclusion.")
    for L in [
        "CannaScope CT thresholds are stricter than Connecticut legal limits. A flag does NOT mean a "
        "product legally failed Connecticut testing.",
        "Fields that report only a detection (e.g. “DETECTED”) without a confirmed number are excluded "
        "from numeric rankings and routed to manual COA review — no value in the rankings is a guess.",
        "“Reviewed” / normalized rates are based on the products scanned in this run's window, not a "
        "producer's full lifetime catalog. Interpret normalized rates with the reviewed count beside them.",
        "Cannabinoid percentages are read from the COA potency section; where a COA reports only mg/g the "
        "percentage is derived (÷10), and Total THC is derived from THCA + Delta-9 when not printed.",
        "The 35% cannabinoid review applies only to flower-based products; vapes, concentrates, extracts, "
        "edibles, tinctures, topicals, capsules and beverages are excluded.",
        "Producer identity (DBA / parent / license) is from a curated, source-verified table plus the CT "
        "registry brand mapping. Unconfirmed entities are marked “verify manually” and never invented. "
        "Authoritative cross-checks: data.ct.gov egd5-wb6r, service.ct.gov business search, "
        "elicense.ct.gov license lookup.",
        "OCR is used for scanned COAs; a small number of image-only COAs may remain unreadable and are "
        "logged for manual review.",
    ]:
        story.append(Paragraph("•&nbsp; " + esc(L), body_st))

    def _footer(canvas, doc_):
        canvas.saveState()
        w, _h = PAGE
        canvas.setFont(BFB, 7); canvas.setFillColor(colors.HexColor("#333333"))
        canvas.drawCentredString(w / 2.0, 0.4 * inch,
                                 "Every flag is a lead, not a conclusion. Verify against original COA.")
        canvas.setFont(BF, 6.5); canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(0.32 * inch, 0.22 * inch,
                          f"{APP_NAME}  |  Created {date_created} {time_created}  |  Window {window_str}")
        canvas.drawRightString(w - 0.32 * inch, 0.22 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    print(f"Wrote {out_path}  ({len(flagged)} flagged, {len(thc_flagged)} high-THC, "
          f"{len(manual_review)} manual-review)")


# ============================================================================
# CSV / text exports
# ============================================================================
def _w(path, header, rows):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f); wr.writerow(header)
        for r in rows:
            wr.writerow(r)


def write_outputs(out_dir, all_results, reported, flagged, thc_flagged, manual_review,
                  norm_rows, lab_thc, signatures, identities, resolver, prod_matrix,
                  lab_matrix, pairings, prio, clusters, exec_rows, validation,
                  pmap, lmap, watch, window_str, sev_counts, verify_notes):
    P = lambda n: os.path.join(out_dir, n)

    # per-contaminant severity CSVs
    for key, title, _u, _b in CONTAMINANT_SECTIONS:
        fn = "severity_" + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") + ".csv"
        rows = []
        items = [(p, d) for p in flagged for d in quantified_details(p, watch)
                 if d["key"] == key and is_flag_driver(d)]
        items.sort(key=lambda pd: (pd[1]["ct_pct"] or 0, pd[1]["value"] or 0), reverse=True)
        for i, (p, d) in enumerate(items, 1):
            f = report_findings(p, watch)
            rows.append([i, p.product_name, producer_display(p, pmap), p.brand, lab_display(p, lmap),
                         d["value"], d["unit"], d["ct_limit"] or "",
                         f'{d["ct_pct"]:.1f}' if d["ct_pct"] is not None else "",
                         f'{d["vs_std"]:.1f}' if d["vs_std"] is not None else "",
                         why_flagged(d), data_confidence(d),
                         "yes" if len(cross_concerns(p, f, lmap)) > 1 else "no",
                         p.registration_number, p.approval_date, p.report_url])
        _w(P(fn), ["rank", "product", "producer", "brand", "lab", "measured_value", "unit", "ct_limit",
                   "ct_limit_pct", "vs_cannascope_pct", "why_flagged", "data_confidence",
                   "cross_flagged", "coa", "date", "report_url"], rows)

    # detected but not quantified
    rows = []
    for p in all_results:
        for nice in pathogen_detections(p):
            rows.append([p.product_name, producer_display(p, pmap), lab_display(p, lmap),
                         p.registration_number, nice, "DETECTED",
                         "Zero-tolerance pathogen DETECTED — manual COA review (do-not-consume if confirmed)"])
        for u in unquantified_findings(p):
            rows.append([p.product_name, producer_display(p, pmap), lab_display(p, lmap),
                         p.registration_number, u["name"], u["raw"], u["reason"]])
    _w(P("detected_not_quantified_manual_review.csv"),
       ["product", "producer", "lab", "coa", "contaminant_field", "raw_text", "reason"], rows)

    # priority queue
    _w(P("priority_review_queue.csv"),
       ["rank", "product", "producer", "lab", "severity", "priority_score", "reasons", "coa"],
       [[i, p.product_name, producer_display(p, pmap), lab_display(p, lmap),
         report_severity(p, watch) or "REVIEW", f"{score:.0f}", "; ".join(reasons), p.registration_number]
        for i, (p, score, reasons) in enumerate(prio, 1)])

    # high-THC aquamarine
    _w(P("high_thc_aquamarine_flags.csv"),
       ["product", "producer", "form", "lab", "triggering_field", "value_pct", "over_35_by",
        "also_contaminant_flagged", "total_thc", "thca", "d9_thc", "total_cannabinoids", "coa", "report_url"],
       [[p.product_name, producer_display(p, pmap), p.dosage_form, lab_display(p, lmap),
         thc_headline(p)["name"], f'{thc_headline(p)["value"]:g}', f'{thc_headline(p)["over_by"]:.1f}',
         "yes" if report_severity(p, watch) in ("RED", "ORANGE", "YELLOW") else "no",
         p.cannabinoids.get("total_thc", {}).get("value", ""), p.cannabinoids.get("thca", {}).get("value", ""),
         p.cannabinoids.get("d9_thc", {}).get("value", ""), p.cannabinoids.get("total_cannabinoids", {}).get("value", ""),
         p.registration_number, p.report_url] for p in thc_flagged])

    # producer normalized rates
    _w(P("producer_normalized_rates.csv"),
       ["producer", "reviewed", "flagged", "pct_flagged", "high_caution", "moderate_caution",
        "high_thc", "most_common_contaminant", "highest_ct_pct", "highest_cannascope_exceedance_pct"],
       [[r["producer"], r["reviewed"], r["flagged"], f'{r["pct"]:.1f}', r["high"], r["moderate"], r["aqua"],
         r["top_contaminant"], f'{r["max_ct_pct"]:.1f}' if r["max_ct_pct"] is not None else "",
         f'{r["max_vs_std"]:.1f}' if r["max_vs_std"] is not None else ""]
        for r in sorted(norm_rows, key=lambda r: (r["pct"], r["flagged"]), reverse=True)])

    # lab high-THC distribution
    _w(P("lab_high_thc_distribution.csv"),
       ["lab", "high_thc_flower_flags", "pct_of_high_thc_flags", "highest_value_pct", "main_producers"],
       [[r["lab"], r["n"], f'{r["pct"]:.1f}', f'{r["max_val"]:g}', " | ".join(r["producers"])] for r in lab_thc])

    # matrices
    _w(P("producer_contaminant_matrix.csv"), ["producer"] + MATRIX_COLS,
       [[pr] + [prod_matrix[pr].get(c, 0) for c in MATRIX_COLS]
        for pr in sorted(prod_matrix, key=lambda k: -sum(prod_matrix[k].values()))])
    _w(P("lab_contaminant_matrix.csv"), ["lab"] + MATRIX_COLS,
       [[lb] + [lab_matrix[lb].get(c, 0) for c in MATRIX_COLS]
        for lb in sorted(lab_matrix, key=lambda k: -sum(lab_matrix[k].values()))])

    # producer-lab pairings
    _w(P("producer_lab_pairings.csv"), ["producer", "lab", "flagged_products", "main_contaminant", "highest_ct_pct"],
       [[r["producer"], r["lab"], r["n"], r["main"], f'{r["max_ct"]:.1f}' if r["max_ct"] is not None else ""]
        for r in pairings])

    # repeated product families
    _w(P("repeated_product_families.csv"),
       ["product_family", "producer", "appearances", "main_contaminant", "value_range", "labs", "dates"],
       [[c["top_strain"], c["producer"], c["count"], c["contaminant"], c["value_range"],
         " | ".join(c["labs"]), " | ".join(c["dates"])] for c in clusters])

    # unresolved identity
    _w(P("unresolved_identity.csv"), ["legal_entity", "status", "note"],
       [[rec["legal"], "UNRESOLVED", "DBA / parent company not confirmed — verify manually"]
        for rec in identities.values() if not rec["confirmed"]])

    # recurring signatures
    _w(P("recurring_signatures.csv"), ["signature_type", "entity", "detail", "count", "note"],
       [[s["kind"], s["entity"], s["detail"], s["count"], s["note"]] for s in signatures])

    # validation error report (only if there are errors)
    errs, warns = validation
    if errs or warns:
        _w(P("validation_error_report.csv"), ["severity", "area", "item", "message"],
           [["ERROR"] + e for e in errs] + [["WARNING"] + w for w in warns])

    # full scanned CSV
    analyte_keys = [s["key"] for s in v4.ANALYTE_SPECS] + v4.MYCO_COMP_KEYS
    cann_keys = [k for k, _, _ in CANN_SPECS]
    rows = []
    for p in sorted(all_results, key=lambda x: v4.parse_date(x.approval_date), reverse=True):
        row = [p.product_name, p.dosage_form, p.producer, producer_display(p, pmap), p.brand, p.strain,
               p.approval_date, p.registration_number, lab_display(p, lmap), p.overall_result,
               p.pesticides, p.solvents, "yes" if is_thc_flower(p) else "no",
               report_severity(p, watch) or ""]
        for ak in analyte_keys:
            e = p.analytes.get(ak, {})
            row.append(e.get("raw") or e.get("status") or "")
        for ck in cann_keys:
            row.append(p.cannabinoids.get(ck, {}).get("value", ""))
        row.append(" | ".join(p.flags))
        row.append(" | ".join(f'{d["name"]} {d["value"]:g}%' for d in p.thc_flags))
        rows.append(row)
    _w(P("CannaScope_CT_Beta_V5_All_Products_Scanned.csv"),
       ["product", "form", "producer", "producer_display", "brand", "strain", "date", "coa", "lab",
        "overall_result", "pesticides", "solvents", "is_thc_flower", "report_severity"]
       + analyte_keys + [f"cann_{k}" for k in cann_keys] + ["contaminant_flags", "thc_flags"], rows)

    # plain-text executive summary
    with open(P("CannaScope_CT_Beta_V5_Executive_Summary.txt"), "w") as f:
        f.write(f"{APP_NAME}\n{REPORT_TITLE}\n" + "=" * 78 + "\n")
        f.write(FRAMING + "\n\n")
        f.write(f"Dataset window: {window_str}\n")
        f.write(f"Generated: {datetime.datetime.now().astimezone():%Y-%m-%d %H:%M %Z}\n\n")
        f.write(f"Total products reviewed ............... {len(all_results):,}\n")
        f.write(f"Total products flagged ................ {len(flagged):,}\n")
        f.write(f"  Do Not Consume (Red) ............... {sev_counts.get('RED', 0)}\n")
        f.write(f"  High Caution (Orange) .............. {sev_counts.get('ORANGE', 0)}\n")
        f.write(f"  Moderate Caution (Yellow) .......... {sev_counts.get('YELLOW', 0)}\n")
        f.write(f"  Aquamarine High-THC Review ......... {len(thc_flagged)}\n")
        f.write(f"Detected but not quantified (review) .. {len(manual_review):,}\n\n")
        f.write("Top producers by raw flag count:\n")
        for r in sorted(norm_rows, key=lambda r: r["flagged"], reverse=True)[:10]:
            if r["flagged"]:
                f.write(f"  {r['producer']:44s} {r['flagged']:3d}/{r['reviewed']:<3d} ({r['pct']:.1f}%)\n")
        f.write("\nTop producers by normalized flag rate (>= 3 reviewed):\n")
        for r in sorted([r for r in norm_rows if r["reviewed"] >= 3 and r["flagged"]],
                        key=lambda r: r["pct"], reverse=True)[:10]:
            f.write(f"  {r['producer']:44s} {r['pct']:5.1f}%  ({r['flagged']}/{r['reviewed']})\n")
        f.write("\nPriority review queue (top 10):\n")
        for i, (p, score, reasons) in enumerate(prio[:10], 1):
            f.write(f"  {i:2d}. {p.product_name[:48]:48s} [{report_severity(p, watch) or 'REVIEW'}] "
                    f"{'; '.join(reasons[:2])}\n")
        f.write("\nLabs most associated with high-THC flower flags:\n")
        for r in lab_thc:
            f.write(f"  {r['lab']:36s} {r['n']:3d} ({r['pct']:.1f}%)\n")
        f.write("\nRecurring signatures (top 15):\n")
        for s in signatures[:15]:
            f.write(f"  [{s['kind']}] {s['entity']} — {s['detail']} x{s['count']}\n")
        f.write("\nInternal verification:\n")
        for k, v in verify_notes:
            f.write(f"  {k}: {v}\n")
        errs, warns = validation
        f.write(f"\nData validation: {'PASSED' if not errs else str(len(errs)) + ' ERROR(S)'}"
                f"{f' / {len(warns)} warning(s)' if warns else ''}.\n")
        f.write("\nMajor limitations: see the report's Limitations & Methodology page.\n")

    resolver.save()
    print(f"Wrote CSV/text exports to {out_dir}/")


# ============================================================================
# Worker
# ============================================================================
def process_product(p, session, watch):
    path = v4.download_pdf(p, session)
    if not path:
        p.parse_note = p.parse_note or "could not download COA"
        return p
    text = v4.read_pdf_text(path)
    if len(text.strip()) < 40:
        p.parse_note = "no extractable text (scanned image?)"
        return p
    p.overall_result = v4.find_overall_result(text)
    p.test_lab = v4.parse_lab(text)
    v4.parse_analytes(text, p)
    parse_cannabinoids(text, p)
    v4.apply_flags(p, text, watch)
    apply_thc_flags(p)
    p.strain = product_core_name(p)
    return p


def build_exec_rows(flagged, watch, pmap, lmap):
    """Fully-traceable cross-category ranking rows for the executive summary —
    every row carries a quantified value and its source section."""
    sec_of = {k: t for k, t, _u, _b in CONTAMINANT_SECTIONS}
    rows = []
    for p in flagged:
        for d in quantified_details(p, watch):
            if not is_flag_driver(d) or d["ct_pct"] is None:
                continue
            rows.append(dict(product=p.product_name, producer=producer_display(p, pmap),
                             brand=(p.brand or "—"), lab=lab_display(p, lmap), contaminant=d["name"],
                             value=d["value"], unit=d["unit"], ct_limit=d["ct_limit"], ct_pct=d["ct_pct"],
                             vs_std=d["vs_std"], coa=p.registration_number or "COA",
                             section=sec_of.get(d["key"], "Other Quantified Contaminants")))
    rows.sort(key=lambda r: r["ct_pct"], reverse=True)
    return rows


# ============================================================================
# Main
# ============================================================================
def main():
    ap = argparse.ArgumentParser(description=f"{APP_NAME} — {REPORT_TITLE}")
    ap.add_argument("--forms", choices=["flower", "inhalable", "all"], default="all")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"look-back window in days (default {DEFAULT_DAYS})")
    ap.add_argument("--since", default="", help="explicit YYYY-MM-DD (overrides --days)")
    ap.add_argument("--threshold", type=int, default=v4.DEFAULT_WATCH,
                    help=f"yeast/mold watch threshold (default {v4.DEFAULT_WATCH})")
    ap.add_argument("--limit", type=int, default=0, help="cap COAs scanned (0 = all)")
    ap.add_argument("--workers", type=int, default=v4.DEFAULT_WORKERS)
    ap.add_argument("--cookies", default="", help="Netscape cookies.txt")
    ap.add_argument("--refresh-registry", action="store_true")
    ap.add_argument("--keep-clean-pdfs", action="store_true")
    args = ap.parse_args()

    since = None
    if args.since:
        try:
            yr, mo, da = map(int, args.since.split("-"))
            since = (yr, mo, da)
        except ValueError:
            sys.exit("--since must be YYYY-MM-DD")
    elif args.days:
        d = datetime.date.today() - datetime.timedelta(days=args.days)
        since = (d.year, d.month, d.day)
    since_str = f"{since[0]:04d}-{since[1]:02d}-{since[2]:02d}" if since else "any date"
    window_str = f"{since_str} to {datetime.date.today():%Y-%m-%d}"

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    v4.CACHE_DIR = CACHE_DIR

    t0 = time.time()
    session = v4.make_session(args.cookies, args.workers)
    products = load_registry(session, refresh=args.refresh_registry)
    products.sort(key=lambda p: v4.parse_date(p.approval_date), reverse=True)

    pmap = lmap = None
    if names is not None:
        registry_producers = sorted({p.producer for p in products if p.producer})
        pmap = names.get_producer_map(registry_names=registry_producers)
        lmap = names.get_lab_map(use_live=False)
        print(f"Names: {len(pmap)} producers known, {len(lmap)} labs known.")

    before = len(products)
    products = v4.prefilter(products, args.forms, since)
    print(f"  prefilter ({args.forms}, since {since_str}): {len(products)} of {before}.")
    if args.limit:
        products = products[:args.limit]
    if not products:
        sys.exit("No products matched. Widen --forms / --days.")

    ledger = _load_ledger()
    todo = [p for p in products if v4.coa_key(p) not in ledger]
    print(f"  {len(products) - len(todo)} already scanned clean (skipping).")
    print(f"\nScanning {len(todo)} COAs with {args.workers} workers ...\n")

    all_results, keep, failures = [], [], []
    new_clean = set(); lock = threading.Lock(); done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_product, p, session, args.threshold): p for p in todo}
        for fut in as_completed(futs):
            p = fut.result()
            with lock:
                done += 1
                all_results.append(p)
                parsed = bool(p.analytes) or p.mold_yeast_cfu is not None or bool(p.cannabinoids)
                interesting = bool(p.flags) or bool(p.thc_flags) or bool(unquantified_findings(p)) or bool(pathogen_detections(p))
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
                        if not args.keep_clean_pdfs:
                            try: os.remove(v4.cache_path(p))
                            except OSError: pass
                if done % 50 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)}  ({len(keep)} kept, {time.time()-t0:.0f}s)", flush=True)
    _save_ledger(ledger | new_clean)

    # ---- Partition the kept products using trustworthy severity ----
    print("\nBuilding analytics ...")
    reported = keep
    flagged = [p for p in reported if report_severity(p, args.threshold) in ("RED", "ORANGE", "YELLOW", "AQUA")]
    thc_flagged = [p for p in flagged if p.thc_flags]
    thc_flagged.sort(key=lambda p: thc_headline(p)["value"], reverse=True)
    manual_review = [p for p in reported if unquantified_findings(p) or pathogen_detections(p)]

    norm_rows = producer_normalized_rates(all_results, reported, pmap, args.threshold)
    recurrence, signatures, fam = recurrence_and_signatures(flagged, pmap, lmap, args.threshold)
    clusters = product_family_clusters(fam, pmap, lmap, args.threshold)
    lab_thc = lab_thc_distribution(thc_flagged, pmap, lmap)
    cleaner = cleaner_flower(all_results, args.threshold)
    prod_matrix = producer_contaminant_matrix(flagged, pmap, args.threshold)
    lab_matrix = lab_contaminant_matrix(flagged, lmap, args.threshold)
    pairings = producer_lab_pairings(flagged, pmap, lmap, args.threshold)
    prio = priority_queue(reported, args.threshold, pmap, lmap)
    exec_rows = build_exec_rows(flagged, args.threshold, pmap, lmap)

    resolver = IdentityResolver(pmap)
    identities = {}
    for legal in sorted({p.producer for p in all_results if p.producer}):
        identities[_ident_norm(legal)] = resolver.resolve(legal)
    n_unres = sum(1 for r in identities.values() if not r["confirmed"])
    print(f"  Identity: {len(identities)} producers, {n_unres} unresolved (logged).")

    verify_notes, ok = run_verification(all_results, flagged, thc_flagged, norm_rows, lab_thc, args.threshold)
    validation = run_validation(reported, flagged, exec_rows, args.threshold)
    print("  Verification:")
    for k, v in verify_notes:
        print(f"    {k}: {v}")
    errs, warns = validation
    print(f"  Validation: {'PASSED' if not errs else str(len(errs)) + ' ERROR(S)'}"
          f"{f' / {len(warns)} warning(s)' if warns else ''}.")

    # Sort flagged most-alarming first
    flagged.sort(key=lambda p: (SEV_RANK[report_severity(p, args.threshold) or "AQUA"], v4.alarm_score(p),
                                (thc_headline(p)["value"] if p.thc_flags else 0), v4.yeast_mold_value(p)),
                 reverse=True)
    sev_counts = Counter(report_severity(p, args.threshold) for p in flagged)

    write_outputs(OUT_DIR, all_results, reported, flagged, thc_flagged, manual_review, norm_rows,
                  lab_thc, signatures, identities, resolver, prod_matrix, lab_matrix, pairings,
                  prio, clusters, exec_rows, validation, pmap, lmap, args.threshold, window_str,
                  sev_counts, verify_notes)

    if errs:
        # Validation policy: do not emit a final PDF when ranked values aren't traceable.
        print("\n" + "=" * 72)
        print(f"  VALIDATION FAILED — {len(errs)} error(s). See "
              f"{os.path.join(OUT_DIR, 'validation_error_report.csv')}.")
        print("  No final PDF was generated; fix the flagged data and re-run.")
        print("=" * 72)
        return

    out_path, report_no = next_report_path()
    build_pdf(out_path, report_no, all_results, reported, flagged, thc_flagged, manual_review,
              norm_rows, recurrence, signatures, clusters, lab_thc, cleaner, identities, prio,
              prod_matrix, lab_matrix, pairings, exec_rows, verify_notes, validation,
              pmap, lmap, args.threshold, window_str)

    import shutil
    visible = os.path.join(os.path.dirname(os.path.abspath(OUT_DIR)), os.path.basename(out_path))
    try:
        shutil.copy2(out_path, visible)
    except OSError:
        visible = out_path

    print("\n" + "=" * 72)
    print(f"  CANNASCOPE CT BETA V5 — REPORT #{report_no} IS READY")
    print(f"    {visible}")
    print(f"  Reviewed {len(all_results):,} • Flagged {len(flagged):,} "
          f"({sev_counts.get('RED',0)} Red, {sev_counts.get('ORANGE',0)} Orange, "
          f"{sev_counts.get('YELLOW',0)} Yellow, {len(thc_flagged)} Aquamarine) • "
          f"{len(manual_review)} manual-review")
    print(f"  Verification: {'ALL PASS' if ok else 'SOME CHECKS NEED MANUAL VERIFICATION'}")
    print(f"  Elapsed {time.time()-t0:.0f}s")
    print("=" * 72)


def _load_ledger() -> set:
    if not os.path.exists(LEDGER):
        return set()
    with open(LEDGER) as f:
        return {ln.strip() for ln in f if ln.strip()}


def _save_ledger(keys: set):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(LEDGER, "w") as f:
        for k in sorted(keys):
            f.write(k + "\n")


if __name__ == "__main__":
    main()
