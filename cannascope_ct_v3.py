#!/usr/bin/env python3
"""
CannaScope CT  (V3)
===================
Pulls the CT "Medical Marijuana and Adult-Use Cannabis Product Registry"
(dataset egd5-wb6r), opens EVERY product's lab-analysis PDF, extracts the FULL
contaminant panel, and surfaces products for CONSUMER AWARENESS against
Connecticut's codified standards plus a stricter yeast/mold watch line.

WHAT V3 CHANGES
  * NAMES YOU RECOGNIZE: producers and labs are resolved through
    ct_cannabis_names.py so the report shows BOTH the common / DBA name AND the
    legal LLC name (e.g. "Fine Fettle (FFD 149 LLC)"). The producer universe is
    taken from the product registry itself (egd5-wb6r), so EVERY producer in the
    data is accounted for; the curated DBA / common names layer on top.
  * NOTHING DROPPED: every producer and every lab seen across the scanned COAs is
    audited for coverage. Unrecognized labs/producers are FLAGGED (in the console
    and a "Name Coverage Audit.csv"), never silently skipped, so an incomplete
    PDF can't hide a new entity.

WHAT V2 CHANGED
  * ALL PRODUCT TYPES: evaluates every product on the registry by default
    (flower, vapes, concentrates, edibles, tinctures, topicals -- everything),
    not just inhalables. Override with --forms.
  * MUCH FASTER PARSING: text is extracted with pypdfium2 (~65x faster than
    pdfplumber). Downloads stay concurrent; PDF reads are serialized (pdfium is
    not thread-safe) but so fast it no longer matters.
  * SCANNED PDFs ARE READ: a built-in OCR step (Apple Vision via `ocrmac` on
    macOS, or tesseract elsewhere) reads image-only COAs so they're evaluated
    too, instead of skipped.
  * SELF-CLEANING CACHE: after evaluation, any COA (text OR scanned) with NO
    finding of note is deleted, and the cache is pruned to ONLY the flagged
    products each run -- it never fills up.
  * REPORT SORTED BY ALARM: rows are ordered most-alarming first -- pathogens
    and over-limit results at the top, then by highest contaminant magnitude
    (e.g. highest yeast & mold) descending.
  * DEFAULT SCOPE: last 30 days, ALL forms. Override with --since / --forms /
    --days.

STANDARDS ENCODED  (Conn. Agencies Regs. sec. 21a-408-60; DCP P&P)
  zero tolerance (NOT DETECTED): E. coli, STEC, Salmonella, Listeria,
    pathogenic Aspergillus (A. fumigatus/flavus/niger/terreus)
  total aerobic <= 100,000 CFU/g ; total yeast & mold <= 100,000 CFU/g
  mycotoxins < 20 ug/kg each (aflatoxin B1/B2/G1/G2, ochratoxin A)
  WATCH LINE (this audit, NOT a legal limit): yeast & mold > 10,000 CFU/g is
    surfaced YELLOW though still LEGAL in CT, for sensitive consumers.

Every flag is a LEAD FOR VERIFICATION against the source COA, never a
conclusion. Nothing about any lab's or producer's conduct is asserted.

OUTPUTS (./CannaScope CT - Flagged Product Results and Sources/)
  CannaScope CT - Flagged Products - N.pdf   color-coded report (severity-sorted),
                                             exact numbers, clickable COA links;
                                             a NEW numbered file each run
  All Products Scanned - Full Results.csv    every analyte value parsed, per product
  Unreadable COAs - Manual Review.csv        COAs that could not be read even with OCR
  Flagged COA Source PDFs/                    retained source COA PDFs (flagged only)
  Registry Cache.csv                         cached registry (skips re-download)
  Already-Scanned Skip List.txt              keys already evaluated (skipped on rerun)

REQUIREMENTS:  pip install requests reportlab pypdfium2
  OCR (recommended): macOS `pip install ocrmac`; other OS `pip install pytesseract`
TYPICAL RUN (defaults -- last 30 days, ALL product types):
  python cannascope_ct_v2.py
NARROWER / QUICK TEST:
  python cannascope_ct_v2.py --forms flower --days 30 --limit 50
"""

import argparse
import csv
import datetime
import http.cookiejar
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests
from requests.adapters import HTTPAdapter

try:
    import pypdfium2 as pdfium
except ImportError:
    sys.exit("Missing dependency: pip install pypdfium2")

# Producer / lab name resolution (common DBA + legal LLC) and coverage auditing.
# Optional: if the module isn't alongside this script, fall back to showing the
# raw registry name so the tool still runs (just without DBA enrichment).
try:
    import ct_cannabis_names as names
except ImportError:
    names = None
    print("[warn] ct_cannabis_names.py not found -- showing raw producer/lab "
          "names without DBA enrichment or coverage audit.", file=sys.stderr)

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
CSV_URL = "https://data.ct.gov/api/views/egd5-wb6r/rows.csv?accessType=DOWNLOAD"
PORTAL_WARM_URL = "https://www.elicense.ct.gov/lookup/licenselookup.aspx"
PORTAL_REFERER = PORTAL_WARM_URL

OUT_DIR = "CannaScope CT - Flagged Product Results and Sources"
CACHE_DIR = os.path.join(OUT_DIR, "Flagged COA Source PDFs")
FULL_CSV_OUT = os.path.join(OUT_DIR, "All Products Scanned - Full Results.csv")
FAILURES_CSV_OUT = os.path.join(OUT_DIR, "Unreadable COAs - Manual Review.csv")
COVERAGE_CSV_OUT = os.path.join(OUT_DIR, "Name Coverage Audit.csv")
LAB_SUMMARY_CSV_OUT = os.path.join(OUT_DIR, "Per-Lab Analysis Summary.csv")
PDF_OUT = os.path.join(OUT_DIR, "flagged_products.pdf")  # legacy; reports use next_report_path()
LEDGER = os.path.join(OUT_DIR, "Already-Scanned Skip List.txt")
REGISTRY_CACHE = os.path.join(OUT_DIR, "Registry Cache.csv")
REGISTRY_TTL = 6 * 3600          # reuse cached registry for 6 hours

CT_MICRO_LIMIT = 100_000         # CFU/g -- CT legal ceiling (TYMC & aerobic)
DEFAULT_WATCH = 10_000           # CFU/g -- consumer-awareness watch line
MYCOTOXIN_LIMIT = 20.0           # ug/kg each

DEFAULT_DAYS = 60                # default look-back window
DEFAULT_WORKERS = 16             # concurrent download workers (parsing is serialized)
MAX_RETRIES = 3
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Inhalable taxonomy (default). Pre-rolls/blunts are flower; the rest are other
# inhalable forms. Edibles/tinctures/topicals are intentionally excluded.
FLOWER_KEYWORDS = ("flower", "usable marijuana", "plant material", "raw material",
                   "pre-roll", "preroll", "pre roll", "shake", "bud", "blunt",
                   "joint")
INHALABLE_KEYWORDS = ("vape", "vaporizer", "cartridge", "cart", "disposable",
                      "pod", "510", "concentrate", "extract", "distillate",
                      "rosin", "resin", "live resin", "wax", "shatter", "badder",
                      "budder", "crumble", "sauce", "diamonds", "dab",
                      "hash", "hashish", "kief")
# Forms that are NEVER inhalable even if a keyword brushes them (e.g. "Marijuana
# Infused Edible" must not match via "infused"; "oil" tinctures are oral).
NONINHALABLE_KEYWORDS = ("edible", "gummy", "gummies", "tincture", "topical",
                         "capsule", "tablet", "lozenge", "beverage", "drink",
                         "syrup", "sublingual", "suppository", "patch", "cream",
                         "balm", "lotion", "chew", "troche")

# ---- number / token regexes ----
SCI = r"([\d.]+)\s*(?:[xX×]\s*10\s*\^?|[eE])\s*([+-]?\d+)"
QTY = re.compile(r"(<|>|≤|≥)?\s*((?:[\d.]+\s*(?:[xX×]\s*10\s*\^?|[eE])\s*[+-]?\d+)"
                 r"|(?:\d[\d,]*(?:\.\d+)?))")
BELOW_DETECT = re.compile(
    r"not\s+detected|none\s+detected|\bN\.?D\.?\b|<\s*lo[dq]\b"
    r"|below\s+(?:the\s+)?(?:lod|loq|detection|quantitation|reporting)"
    r"|\babsent\b|\bneg(?:ative)?\b", re.I)
ACTION_LIMIT_PASS = re.compile(
    r"below\s+(?:the\s+)?action\s+(?:limit|level)s?"
    r"|within\s+(?:the\s+)?(?:limit|spec|action\s+(?:limit|level))s?", re.I)
LIMIT_MARKER = re.compile(
    r"limit|action\s*level|spec(?:ification)?|max(?:imum)?|allow(?:able)?"
    r"|acceptance|reference|threshold|tolerance|standard|criteria", re.I)
POS_RE = re.compile(r"\bdetected\b|\bpositive\b|\bpresent\b|\bfail", re.I)
# a line that is method boilerplate, NOT a result row
FOOTNOTE_RE = re.compile(
    r"analyzed\s+per|are\s+analyzed|analyzed\s+by|method|protocol|\bSOP\b"
    r"|per\s+CT-SOP|chapter|decision\s+rule|measurement\s+of\s+uncertainty"
    r"|plating\s+of", re.I)

# ----------------------------------------------------------------------------
# Analyte specifications
#   kind: "nd"      -> zero tolerance; a real detection = flag
#         "numeric" -> read value; if `limit` set and `flag` True, compare
#   flag: whether THIS audit auto-flags it (display-only analytes have flag=False
#         so we surface exact numbers without making borderline accusations)
# ----------------------------------------------------------------------------
ANALYTE_SPECS = [
    {"key": "stec", "kind": "nd", "name": "Shiga toxin-producing E. coli",
     "group": "bacteria", "flag": True,
     "labels": [r"shiga[\s-]*toxin[\s-]*producing\s+e\.?\s*coli", r"shiga[\s-]*toxin", r"\bSTEC\b"]},
    {"key": "ecoli", "kind": "nd", "name": "Escherichia coli", "group": "bacteria", "flag": True,
     "labels": [r"(?:enteropathogenic\s+)?(?:escherichia|e\.?)\s*coli"]},
    {"key": "salmonella", "kind": "nd", "name": "Salmonella", "group": "bacteria", "flag": True,
     "labels": [r"salmonella"]},
    {"key": "listeria", "kind": "nd", "name": "Listeria monocytogenes", "group": "bacteria", "flag": True,
     "labels": [r"listeria(?:\s+monocytogenes)?", r"\bL\.\s*monocytogenes\b"]},
    {"key": "aspergillus", "kind": "nd", "name": "Aspergillus", "group": "asperg", "flag": True,
     "labels": [r"aspergillus\s+(?:fumigatus|flavus|niger|terreus)",
                r"pathogenic\s+aspergillus", r"aspergillus"]},
    # numeric microbial
    {"key": "tymc", "kind": "numeric", "name": "Yeast & Mold", "unit": "CFU/g",
     "group": "ym", "limit": CT_MICRO_LIMIT, "flag": True,
     "labels": [r"total\s+(?:combined\s+)?yeast\s*(?:and|&|/|\+)?\s*mold(?:\s*count)?",
                r"\bTYMC\b", r"yeast\s*(?:and|&|/|\+)?\s*molds?"]},
    {"key": "aerobic", "kind": "numeric", "name": "Total Aerobic Bacteria", "unit": "CFU/g",
     "group": "aerobic", "limit": CT_MICRO_LIMIT, "flag": True,
     "labels": [r"total\s+(?:viable\s+)?aerobic(?:\s+(?:microbial|bacterial|plate))?\s*(?:count|bacteria)?",
                r"\bTAC\b", r"\bTVAC\b", r"aerobic\s+plate\s+count"]},
    {"key": "coliform", "kind": "numeric", "name": "Total Coliform", "unit": "CFU/g",
     "group": "micro", "limit": None, "flag": False,
     "labels": [r"total\s+coliforms?"]},
    {"key": "btgn", "kind": "numeric", "name": "Bile-Tol. Gram-Neg", "unit": "CFU/g",
     "group": "micro", "limit": None, "flag": False,
     "labels": [r"bile[\s-]*tolerant\s+gram[\s-]*negative", r"\bBTGN\b"]},
    # mycotoxins (ug/kg)
    {"key": "aflatoxin", "kind": "numeric", "name": "Aflatoxin", "unit": "ug/kg",
     "group": "myco", "limit": MYCOTOXIN_LIMIT, "flag": True,
     "labels": [r"total\s+aflatoxin", r"aflatoxin(?:s)?(?:\s*(?:B1|B2|G1|G2))?"]},
    {"key": "ochratoxin", "kind": "numeric", "name": "Ochratoxin A", "unit": "ug/kg",
     "group": "myco", "limit": MYCOTOXIN_LIMIT, "flag": True,
     "labels": [r"ochratoxin(?:\s*A)?"]},
    # heavy metals (display exact numbers; flag only on clear internal fail)
    {"key": "arsenic", "kind": "numeric", "name": "Arsenic", "unit": "",
     "group": "metal", "limit": None, "flag": False, "labels": [r"\barsenic\b"]},
    {"key": "cadmium", "kind": "numeric", "name": "Cadmium", "unit": "",
     "group": "metal", "limit": None, "flag": False, "labels": [r"\bcadmium\b"]},
    {"key": "lead", "kind": "numeric", "name": "Lead", "unit": "",
     "group": "metal", "limit": None, "flag": False, "labels": [r"\blead\b"]},
    {"key": "mercury", "kind": "numeric", "name": "Mercury", "unit": "",
     "group": "metal", "limit": None, "flag": False, "labels": [r"\bmercury\b"]},
    {"key": "chromium", "kind": "numeric", "name": "Chromium", "unit": "",
     "group": "metal", "limit": None, "flag": False, "labels": [r"\bchromium\b"]},
]

# Known CT cannabis-testing labs (extend as needed). First hit wins.
KNOWN_LABS = [
    (re.compile(r"analytics\s*,?\s*(?:labs?|llc)?", re.I), "Analytics Labs"),
    (re.compile(r"altasci", re.I), "AltaSci Laboratories"),
    (re.compile(r"northeast\s+laborator", re.I), "Northeast Laboratories"),
    (re.compile(r"proverde", re.I), "ProVerde Laboratories"),
    (re.compile(r"abko", re.I), "ABKO Labs"),
    (re.compile(r"trichome\s+analytical", re.I), "Trichome Analytical"),
    (re.compile(r"\bMCR\s+labs", re.I), "MCR Labs"),
]

# Known CT consumer BRANDS, derived from the state registry's own product names
# (each brand is associated with a BRANDING-ENTITY in dataset egd5-wb6r). The COA
# product name often carries the brand even when the legal producer is opaque,
# and some brands (Earl Baker, Asteroid) are toll-manufactured by several
# entities -- so the brand is tracked PER PRODUCT here, in addition to the
# producer's DBA. Ordered most-specific first; first match wins.
KNOWN_BRANDS = [
    (re.compile(r"the\s+happy\s+confection", re.I), "The Happy Confection"),
    (re.compile(r"coast\s+cannabis", re.I),         "Coast Cannabis Co."),
    (re.compile(r"brix\s+cannabis|\bbrix\b", re.I), "Brix Cannabis"),
    (re.compile(r"zen\s+cannabis", re.I),           "Zen Cannabis"),
    (re.compile(r"lucky\s+chews", re.I),            "Lucky Chews"),
    (re.compile(r"let'?s\s+burn", re.I),            "Let's Burn"),
    (re.compile(r"earl\s+baker", re.I),             "Earl Baker"),
    (re.compile(r"early\s*birds", re.I),            "Early Birds"),
    (re.compile(r"zero\s+proof", re.I),             "Zero Proof"),
    (re.compile(r"grassroots", re.I),               "Grassroots"),
    (re.compile(r"\basteroid\b", re.I),             "Asteroid"),
    (re.compile(r"\bcomffy\b", re.I),               "Comffy"),
    (re.compile(r"\bawssom\b", re.I),               "Awssom"),
    (re.compile(r"tyson\s*2\.?0", re.I),            "Tyson 2.0"),
    (re.compile(r"\brodeo\b", re.I),                "Rodeo"),
    (re.compile(r"\bbudr\b", re.I),                 "BUDR"),
    (re.compile(r"\berva\b", re.I),                 "Erva"),
    (re.compile(r"\bsuperflux\b", re.I),            "Superflux"),
    (re.compile(r"\bastro\b", re.I),                "Astro"),
    (re.compile(r"the\s+goods\b", re.I),            "The Goods"),
    (re.compile(r"\bAGL\b", re.I),                  "AGL"),
    (re.compile(r"good\s+green", re.I),             "Good Green"),
    (re.compile(r"all\s*:?\s*hours", re.I),         "all:hours"),
    (re.compile(r"\bdaily!?\b", re.I),              "Daily!"),
    (re.compile(r"\bselect\b", re.I),               "Select"),
    (re.compile(r"\bpacks\b", re.I),                "Packs"),
    (re.compile(r"fast\s+times", re.I),             "Fast Times"),
]


# ----------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------
@dataclass
class Product:
    product_name: str = ""
    dosage_form: str = ""
    producer: str = ""
    brand: str = ""                  # consumer brand, parsed from PRODUCT-NAME
    approval_date: str = ""
    registration_number: str = ""
    label_url: str = ""
    report_url: str = ""
    test_lab: str = ""
    overall_result: str = ""
    pesticides: str = ""             # PASS / FAIL / ""
    solvents: str = ""               # panel status: PASS / FAIL / Not tested
    solvent_hits: list = field(default_factory=list)   # itemized detections
    analytes: dict = field(default_factory=dict)
    mold_yeast_cfu: Optional[float] = None
    mold_yeast_raw: str = ""
    parse_note: str = ""
    flags: list = field(default_factory=list)


# ----------------------------------------------------------------------------
# Registry CSV (cached)
# ----------------------------------------------------------------------------
URL_RE = re.compile(r"https?://[^\s)]+")

def extract_url(cell: str) -> str:
    if not cell:
        return ""
    m = URL_RE.search(cell)
    return m.group(0).rstrip(").,;") if m else ""


def parse_brand(product_name: str) -> str:
    """Resolve the consumer brand from a CT registry product name. First try the
    known-brand dictionary (covers 'Rodeo', 'Asteroid', 'Brix Cannabis', 'Earl
    Baker', etc. that appear anywhere in the name). Then fall back to the leading
    segment of a pipe-delimited name ('Comffy|PreRoll|...'). '' if nothing fits."""
    if not product_name:
        return ""
    for rx, disp in KNOWN_BRANDS:
        if rx.search(product_name):
            return disp
    if "|" in product_name:
        head = product_name.split("|", 1)[0].strip()
        if head and not re.fullmatch(r"[\d.\s]+(?:g|mg|oz|ml|pk|ct)?", head, re.I):
            return head
    return ""


def _rows_from_csv_text(text: str) -> list:
    reader = csv.DictReader(text.splitlines())
    products = []
    for row in reader:
        name = (row.get("PRODUCT-NAME") or "").strip()
        p = Product(
            product_name=name,
            dosage_form=(row.get("DOSAGE-FORM") or "").strip(),
            producer=(row.get("BRANDING-ENTITY") or "").strip(),
            brand=parse_brand(name),
            approval_date=(row.get("APPROVAL-DATE") or "").strip(),
            registration_number=(row.get("REGISTRATION-NUMBER") or "").strip(),
            label_url=extract_url(row.get("LABEL-IMAGE", "")),
            report_url=extract_url(row.get("LAB-ANALYSIS", "")),
        )
        if p.report_url:
            products.append(p)
    return products


def load_registry(session: requests.Session, refresh: bool = False) -> list:
    if (not refresh and os.path.exists(REGISTRY_CACHE)
            and time.time() - os.path.getmtime(REGISTRY_CACHE) < REGISTRY_TTL):
        age = int((time.time() - os.path.getmtime(REGISTRY_CACHE)) / 60)
        with open(REGISTRY_CACHE, encoding="utf-8", errors="replace") as f:
            text = f.read()
        products = _rows_from_csv_text(text)
        print(f"Registry: using cached copy ({age} min old, "
              f"{len(products)} products with a lab link).")
        return products
    print("Registry: downloading fresh CSV ...")
    r = session.get(CSV_URL, timeout=180)
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(REGISTRY_CACHE, "w", encoding="utf-8") as f:
        f.write(text)
    products = _rows_from_csv_text(text)
    print(f"  {len(products)} products with a lab-analysis link (cached).")
    return products


def parse_date(s: str):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if not m:
        return (0, 0, 0)
    mo, da, yr = map(int, m.groups())
    return (yr, mo, da)


def _matches(form: str, keywords) -> bool:
    f = form.strip().lower()
    return any(k in f for k in keywords)


def is_flower(p: Product) -> bool:
    return _matches(p.dosage_form, FLOWER_KEYWORDS)


def is_inhalable(p: Product) -> bool:
    if _matches(p.dosage_form, NONINHALABLE_KEYWORDS):
        return False
    return _matches(p.dosage_form, FLOWER_KEYWORDS + INHALABLE_KEYWORDS)


def prefilter(products, forms: str, since):
    out = []
    for p in products:
        if forms == "flower" and not is_flower(p):
            continue
        if forms == "inhalable" and not is_inhalable(p):
            continue
        if since and parse_date(p.approval_date) < since:
            continue
        out.append(p)
    return out


# ----------------------------------------------------------------------------
# Session + COA download
# ----------------------------------------------------------------------------
GATE_MARKERS = ("document does not exist", "session has expired",
                "object moved", "an error has occurred")

def make_session(cookie_file: str = "", workers: int = DEFAULT_WORKERS) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    adapter = HTTPAdapter(pool_connections=workers, pool_maxsize=workers * 2,
                          max_retries=0)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    if cookie_file:
        if not os.path.exists(cookie_file):
            sys.exit(f"--cookies file not found: {cookie_file}")
        cj = http.cookiejar.MozillaCookieJar(cookie_file)
        cj.load(ignore_discard=True, ignore_expires=True)
        s.cookies.update(cj)
        print(f"  loaded {len(s.cookies)} cookies from {cookie_file}")
    try:
        s.get(PORTAL_WARM_URL, timeout=60)
        print("  warmed elicense session.")
    except Exception as e:
        print(f"  WARNING: could not warm portal session ({e}).")
    return s


def looks_gated(content: bytes) -> bool:
    head = content[:4096].lower()
    return any(m.encode() in head for m in GATE_MARKERS)


def coa_key(p: Product) -> str:
    return (p.registration_number or str(abs(hash(p.report_url)))).replace("/", "_")


def cache_path(p: Product) -> str:
    return os.path.join(CACHE_DIR, f"{coa_key(p)}.pdf")


def download_pdf(p: Product, session: requests.Session) -> Optional[str]:
    """Fetch the COA and write it to the cache path so it can be parsed. (pdfium
    is not thread-safe parsing from memory buffers, so a real file is required.)
    Clean COAs are deleted again right after evaluation, so only flagged COAs
    ever persist. A previously-cached flagged COA is reused, not re-downloaded."""
    path = cache_path(p)
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    os.makedirs(CACHE_DIR, exist_ok=True)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(p.report_url, headers={"Referer": PORTAL_REFERER},
                            timeout=90, allow_redirects=True)
            r.raise_for_status()
            if b"%PDF" not in r.content[:2048]:
                if looks_gated(r.content):
                    p.parse_note = "COA gated -- 'Document does not exist'. Use --cookies."
                else:
                    p.parse_note = "report link did not return a PDF"
                return None
            with open(path, "wb") as f:
                f.write(r.content)
            return path
        except Exception as e:
            p.parse_note = f"download error (attempt {attempt}): {e}"
            time.sleep(0.3 * attempt)
    return None


# pdfium is NOT thread-safe -- ALL pdfium calls (text extraction AND OCR
# rendering) are serialized under this one lock. pdfium text extraction is so
# fast (~0.08s/PDF) that serializing it is still ~65x faster than parallel
# pdfplumber, while downloads stay fully concurrent.
_PDF_LOCK = threading.Lock()
_OCR_BACKEND = None        # 'ocrmac' | 'tesseract' | '' (resolved once)


def _pdfium_text(src) -> str:
    """Fast text via pypdfium2 (serialized -- pdfium is not thread-safe)."""
    with _PDF_LOCK:
        try:
            doc = pdfium.PdfDocument(src)
            parts = []
            for i in range(len(doc)):
                tp = doc[i].get_textpage()
                parts.append(tp.get_text_range() or "")
            doc.close()
            return "\n".join(parts)
        except Exception:
            return ""


def _pdfplumber_text(src) -> str:
    """Layout-aware text via pdfplumber. Slower, but for two-column COA layouts
    (e.g. Northeast Laboratories) it keeps each analyte's value ON the same line
    as its label, where pypdfium2's reading order splits them apart. pdfminer is
    pure-Python and thread-safe, so this runs WITHOUT the pdfium lock."""
    try:
        import pdfplumber
    except ImportError:
        return ""
    try:
        import io
        opener = pdfplumber.open(src if isinstance(src, str) else io.BytesIO(src))
        with opener as pdf:
            return "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    except Exception:
        return ""


# A microbial label line that carries NO digit means the label and its value got
# split onto different lines -> the layout was read in the wrong order.
_MICRO_LABEL = re.compile(
    r"(?im)^.*\btotal\s+.*(?:yeast\s*(?:and|&|/)?\s*mold|aerobic).*$")

def _layout_broken(text: str) -> bool:
    for m in _MICRO_LABEL.finditer(text):
        if not re.search(r"\d", m.group(0)):
            return True
    return False


def read_pdf_text(src) -> str:
    text = _pdfium_text(src)
    # If a two-column layout split labels from values, re-read with pdfplumber
    # (which preserves row layout). Only the affected COAs pay the slower path.
    if _layout_broken(text):
        alt = _pdfplumber_text(src)
        if alt and not _layout_broken(alt):
            text = alt
    if len(text.strip()) < 40:        # likely a scanned image -> OCR
        ocr = ocr_pdf(src)
        if len(ocr.strip()) > len(text.strip()):
            return ocr
    return text


def _ocr_backend() -> str:
    """Pick an OCR engine ONCE. Apple Vision (`ocrmac`) needs no system binary
    and is the default on macOS; tesseract is the cross-platform fallback."""
    global _OCR_BACKEND
    if _OCR_BACKEND is None:
        _OCR_BACKEND = ""
        try:
            import ocrmac.ocrmac  # noqa: F401
            _OCR_BACKEND = "ocrmac"
        except Exception:
            import shutil
            if shutil.which("tesseract"):
                try:
                    import pytesseract  # noqa: F401
                    _OCR_BACKEND = "tesseract"
                except Exception:
                    _OCR_BACKEND = ""
    return _OCR_BACKEND


def ocr_pdf(src, max_pages: int = 6) -> str:
    """Read a scanned/image COA via OCR so it is evaluated like any other. `src`
    may be PDF bytes or a path. The whole render+recognize is serialized under
    _PDF_LOCK (pdfium rendering is not thread-safe). Lines are preserved with
    newlines so the row-based parser can still find analyte rows."""
    backend = _ocr_backend()
    if not backend:
        return ""
    with _PDF_LOCK:
        try:
            doc = pdfium.PdfDocument(src)
            n = min(len(doc), max_pages)
            out = []
            for i in range(n):
                img = doc[i].render(scale=2.0).to_pil()
                if backend == "ocrmac":
                    from ocrmac import ocrmac
                    res = ocrmac.OCR(img).recognize()
                    out.append("\n".join(r[0] for r in res))
                else:
                    import pytesseract
                    out.append(pytesseract.image_to_string(img.convert("L")))
            doc.close()
            return "\n".join(out)
        except Exception:
            return ""


# ----------------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------------
def _to_float(raw: str) -> Optional[float]:
    raw = raw.strip()
    msci = re.search(SCI, raw)
    if msci:
        try:
            return float(msci.group(1)) * (10 ** int(msci.group(2)))
        except ValueError:
            return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _quantities(s: str):
    out, seen = [], []
    for m in QTY.finditer(s):
        st = m.start(2)
        if any(a <= st < b for a, b in seen):
            continue
        v = _to_float(m.group(2))
        if v is None:
            continue
        seen.append((st, m.end(2)))
        out.append({"raw": (m.group(1) or "").strip() + m.group(2).strip(),
                    "value": v, "qual": (m.group(1) or "").strip(), "start": st})
    return out


def _is_limit_token(q, line, known_limit, multi) -> bool:
    pre = line[max(0, q["start"] - 24): q["start"]]
    if LIMIT_MARKER.search(pre):
        return True
    if multi and known_limit and known_limit > 0:
        if abs(q["value"] - known_limit) <= max(0.5, known_limit * 0.005):
            return True
    return False


def _best_label_line(text: str, lowered: str, labels):
    """Return the analyte's RESULT line (text after the label, full line).
    Prefers a real result row (has ND / a value / pass-fail) over a method
    footnote -- so 'Aspergillus spp. are analyzed per CT-SOP-014' is skipped."""
    fallback = None
    for lbl in labels:
        for m in re.finditer(lbl, lowered, re.I):
            line = text[m.start():].split("\n", 1)[0]
            after = line[m.end() - m.start():]
            if FOOTNOTE_RE.search(line):
                continue
            has_result = (BELOW_DETECT.search(line) or POS_RE.search(line)
                          or re.search(r"\bpass\b|\bfail\b", line, re.I)
                          or _quantities(after))
            if has_result:
                return after, line
            if fallback is None:
                fallback = (after, line)
    return fallback


def extract_result(after_label: str, known_limit):
    """Returns {raw, value, nd, limit} for a numeric analyte row. `limit` is the
    COA's OWN action limit from that row when available -- comparing result>limit
    in the COA's native units avoids ALL unit-conversion mistakes (e.g. ug/kg vs
    ug/g, which is how a legal 183 ug/kg trace could look like a lethal dose)."""
    after_label = re.sub(r"\([^)]*\)", " ", after_label)   # drop (B1,B2,..)/(cfu/g)
    if BELOW_DETECT.search(after_label):
        return {"raw": "ND", "value": 0.0, "nd": True, "limit": known_limit}
    if ACTION_LIMIT_PASS.search(after_label):
        return {"raw": "<limit", "value": 0.0, "nd": True, "limit": known_limit}
    # DETAIL-TABLE layout "... LOD LOQ Limit RESULT  Pass/Fail": result is the LAST
    # value before the trailing status word; the LIMIT is the value just before it.
    mstat = re.search(r"(.*?)\s+(?:pass|fail|passed|failed)\s*$", after_label, re.I)
    if mstat:
        qs = _quantities(mstat.group(1))
        if qs:
            r = qs[-1]
            lim = qs[-2]["value"] if len(qs) >= 2 else known_limit
            return {"raw": r["raw"], "value": r["value"], "nd": False, "limit": lim}
    # generic layout (no trailing status): first quantity that is not the limit
    qs = _quantities(after_label)
    multi = len(qs) >= 2
    kept, lim, dropped = [], known_limit, False
    for q in qs:
        if not dropped and _is_limit_token(q, after_label, known_limit, multi):
            dropped = True
            lim = q["value"]
            continue
        kept.append(q)
    if not kept:
        return {"raw": "", "value": None, "nd": False, "limit": lim}
    r = kept[0]
    return {"raw": r["raw"], "value": r["value"], "nd": False, "limit": lim}


def find_overall_result(text: str) -> str:
    m = re.search(r"(overall|final|sample|batch|result)\s*"
                  r"(?:status|result|disposition)?\s*[:\-]?\s*(pass|fail|passed|failed)",
                  text, re.I)
    if m:
        return m.group(2).upper().rstrip("ED") + ("ED" if m.group(2).lower().endswith("ed") else "")
    head = text[:1200]
    if re.search(r"\bfail(ed)?\b", head, re.I):
        return "FAIL"
    if re.search(r"\bpass(ed)?\b", head, re.I):
        return "PASS"
    return ""


SECTION_HEADERS = (r"pesticides?|residual\s+solvents?|\bsolvents?|mycotoxins?|"
                   r"heavy\s+metals?|microbials?|microbiologic\w*|cannabinoids?|"
                   r"terpenes?|water\s+activity|moisture|foreign\s+material|"
                   r"filth|homogeneity")

def _section_slice(text: str, header_pat: str) -> str:
    """Text from a section header to the next major section header (or +1500)."""
    m = re.search(r"(?im)^\s*(?:" + header_pat + r")\b", text)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"(?im)^\s*(?:" + SECTION_HEADERS + r")\b", text[start:])
    end = start + (nxt.start() if nxt else 1500)
    return text[start:end]


def panel_status(text: str, header_pat: str) -> str:
    """PASS / FAIL / 'Not tested' for a whole panel (pesticides, solvents...),
    robust to labs that print a Pass/Fail summary AND labs that only print a
    results table with no summary word."""
    if not re.search(r"(?im)^\s*(?:" + header_pat + r")\b", text):
        return "Not tested"
    body = _section_slice(text, header_pat)
    # strip the ubiquitous "Pass/Fail" column header so it is not read as a FAIL
    cleaned = re.sub(r"pass\s*[/|]\s*fail", " ", body, flags=re.I)
    # a REAL failing row: 'fail' not adjacent to 'pass', or an explicit exceedance
    real_fail = bool(re.search(r"\b(exceeds?|out\s+of\s+spec|above\s+(?:the\s+)?"
                               r"(?:action\s+)?limit)\b", cleaned, re.I))
    if not real_fail:
        for m in re.finditer(r"\bfail(?:ed)?\b", cleaned, re.I):
            ctx = cleaned[max(0, m.start() - 14): m.end() + 6].lower()
            if "pass" not in ctx:
                real_fail = True
                break
    if real_fail:
        return "FAIL"
    # explicit summary right after the header, e.g. "Pesticides 02/12/2026 Pass"
    head = re.search(r"(?:" + header_pat + r")\b\s*(?:\d{1,2}/\d{1,2}/\d{4}\s*)?(pass|fail)",
                     text, re.I)
    if head:
        return head.group(1).upper()
    return "PASS"   # section present, no failing row -> tested & within limits


def parse_lab(text: str) -> str:
    for rx, name in KNOWN_LABS:
        if rx.search(text):
            return name
    for ln in text.splitlines()[:60]:
        s = ln.strip()
        if 3 < len(s) < 60 and re.search(r"laborator|analytics|\blabs?\b|testing", s, re.I):
            return s
    return "Unknown (see COA)"


UNIT_RE = re.compile(r"(µg/kg|ug/kg|mcg/kg|µg/g|ug/g|mg/kg|mg/g|ppm|ppb|cfu/g|cfu/ml)", re.I)

def _detect_unit(context: str) -> str:
    m = UNIT_RE.search(context)
    if not m:
        return ""
    return m.group(1).lower().replace("ug", "µg").replace("mcg", "µg")


# Northeast Laboratories (NELabs) COAs are a two-column table: PDF text
# extraction flattens it into a block of analyte LABELS followed by a block of
# their RESULT values, paired by position. The generic label->inline-value parse
# can't see the numbers (yeast&mold, aerobic), so those products never flagged.
# This recovers the numeric microbial counts by positional pairing.
_NELABS_FORMAT = re.compile(r"nelabs|northeast\s+laborator|nelabsct", re.I)
_MICRO_LABELS = [
    ("aerobic",     re.compile(r"total\s+aerobic\s+microbial\s+count", re.I)),
    ("tymc",        re.compile(r"total\s+yeast\s*&?\s*mold\s+count", re.I)),
    ("ecoli",       re.compile(r"enteropathogenic\s+e\.?\s*coli|escherichia", re.I)),
    ("listeria",    re.compile(r"listeria", re.I)),
    ("salmonella",  re.compile(r"salmonella", re.I)),
    ("aspergillus", re.compile(r"aspergillus", re.I)),
]
_RESULT_TOKEN = re.compile(
    r"^(?:<|>|≤|≥)?\s*\d[\d,]*(?:\.\d+)?$"
    r"|^(?:not\s+detected|nd|n\.?d\.?|absent|pass|fail|detected|positive|negative"
    r"|n\s*/\s*a|n\.?a\.?|—|-)\s*$", re.I)


def parse_columnar_micro(text: str, p: Product):
    """Recover Yeast&Mold and Aerobic counts from NELabs-style columnar COAs.

    Text extraction flattens the table into a block of analyte LABELS followed by
    a block of RESULT values (one per label, same order). The tricky part: stray
    numbers can sit between the two blocks, so we don't grab the first value seen
    -- we pick the contiguous result run whose length matches the label count, and
    pair by position. Only fills tymc/aerobic the generic parser missed; never
    overwrites an existing numeric, and skips non-numeric results (n/a, ND)."""
    if not _NELABS_FORMAT.search(text):
        return
    lines = [l.strip() for l in text.splitlines()]
    hdr = next((i for i, l in enumerate(lines) if re.fullmatch(r"microbiolog\w*", l, re.I)), None)
    scan = lines[hdr + 1:] if hdr is not None else lines

    # 1. label run (in document order), within a window after the Microbiology header
    labelseq, last = [], None
    for i, l in enumerate(scan[:80]):
        for key, rx in _MICRO_LABELS:
            if rx.search(l) and len(l) < 60 and key not in labelseq:
                labelseq.append(key)
                last = i
                break
    if len(labelseq) < 2 or last is None:
        return

    # 2. all contiguous runs of result tokens after the label block
    runs, cur = [], []
    for l in scan[last + 1:]:
        if _RESULT_TOKEN.match(l):
            cur.append(l)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)

    # 3. choose the run that matches the number of labels (real value block), not a
    #    stray 1-2 token run. Require ~one value per label; bail if none qualifies.
    cand = [r for r in runs if len(r) >= len(labelseq) - 1]
    if not cand:
        return
    values = max(cand, key=len)

    # 4. positional pairing; fill only the numeric microbials we still lack
    for key, tok in zip(labelseq, values):
        if key not in ("tymc", "aerobic"):
            continue
        if p.analytes.get(key, {}).get("value") is not None:
            continue
        m = re.match(r"(<|>|≤|≥)?\s*([\d,]+(?:\.\d+)?)\s*$", tok)
        if not m:                      # n/a, ND, etc. -> no numeric count to record
            continue
        val = float(m.group(2).replace(",", ""))
        p.analytes[key] = {"raw": tok, "value": val, "status": "DETECTED",
                           "name": "Yeast & Mold" if key == "tymc" else "Total Aerobic Bacteria",
                           "unit": "CFU/g", "limit": CT_MICRO_LIMIT}


def parse_analytes(text: str, p: Product):
    lowered = text.lower()
    for spec in ANALYTE_SPECS:
        found = _best_label_line(text, lowered, spec["labels"])
        if not found:
            continue
        after, line = found
        entry = {"raw": "", "value": None, "status": "", "name": spec["name"]}
        if spec["kind"] == "nd":
            scrub = re.sub(r"\b(?:not|none)\s+(?:detected|present)\b", " ", after, flags=re.I)
            scrub = re.sub(r"\bneg(?:ative)?\b", " ", scrub, flags=re.I)
            if POS_RE.search(scrub):
                entry["status"] = "DETECTED"
            elif BELOW_DETECT.search(after):
                entry["status"] = "ND"
            else:
                entry["status"] = "ND"   # a real result row, no positive word
        else:
            res = extract_result(after, spec.get("limit"))
            entry["limit"] = res.get("limit")
            pos = text.find(line)
            window = text[max(0, pos - 300): pos + len(line) + 20] if pos >= 0 else line
            entry["unit"] = _detect_unit(window) or spec.get("unit", "")
            if res["nd"]:
                entry.update(raw=res["raw"], value=0.0, status="ND")
            elif res["value"] is not None:
                entry.update(raw=res["raw"], value=res["value"])
            else:
                continue
        p.analytes[spec["key"]] = entry

    parse_mycotoxins(text, p)
    parse_columnar_micro(text, p)   # recover NELabs columnar yeast&mold / aerobic

    tymc = p.analytes.get("tymc")
    if tymc:
        p.mold_yeast_cfu = tymc.get("value")
        p.mold_yeast_raw = tymc.get("raw") or tymc.get("status") or ""

    p.pesticides = panel_status(text, r"pesticides?")
    p.solvents = panel_status(text, r"residual\s+solvents?|\bsolvents?")
    parse_solvents(text, p)


# CT residual-solvent panel. Labs that itemize give a per-row value; many (e.g.
# Northeast) report the whole panel as "Below Action Limits" and only name a
# solvent when it is actually detected. Default individual action limit is
# 1000 ppm (benzene is far stricter); the COA's own limit column is used when
# present, so flagging is unit/limit-safe regardless.
SOLVENT_ANALYTES = [
    ("acetone", "Acetone"), ("acetonitrile", "Acetonitrile"), ("benzene", "Benzene"),
    ("butane", "Butane"), ("ethanol", "Ethanol"),
    ("ethyl acetate", "Ethyl acetate"), ("heptane", "Heptane"),
    ("hexane", "Hexane"), ("isopropanol|isopropyl alcohol|2-propanol", "Isopropanol"),
    ("methanol", "Methanol"), ("pentane", "Pentane"), ("propane", "Propane"),
    ("toluene", "Toluene"), ("xylene", "Xylenes"), ("ethylene\\s+oxide", "Ethylene oxide"),
    ("ethylene\\s+glycol", "Ethylene glycol"), ("chloroform", "Chloroform"),
]

def parse_solvents(text: str, p: Product):
    """Itemize any residual solvent that is actually reported with a value. When
    all pass, CT COAs typically show only a grouped 'Below Action Limits' panel
    (captured in p.solvents); individual hits appear here only when present."""
    sec = _section_slice(text, r"residual\s+solvents?|\bsolvents?")
    if not sec:
        return
    low = sec.lower()
    for lbl, name in SOLVENT_ANALYTES:
        found = _best_label_line(sec, low, [r"\b(?:" + lbl + r")\b"])
        if not found:
            continue
        after, line = found
        res = extract_result(after, None)
        if res["nd"] or res["value"] is None or res["value"] <= 0:
            continue
        if (res["raw"] or "")[:1] in "<≤":
            continue
        unit = _detect_unit(sec) or "ppm"
        p.solvent_hits.append({"name": name, "value": res["value"],
                               "raw": res["raw"], "limit": res.get("limit"),
                               "unit": unit})


# Individual aflatoxin components. In the per-analyte detail table they appear as
# bare rows "B1 0.0 1.0 20.0 ND Pass" (cols: Analyte LOD LOQ Limit Result Status),
# so the combined "Aflatoxin" label never matches -- they MUST be read by row.
MYCO_COMPONENTS = [("afla_b1", "B1", "Aflatoxin B1"), ("afla_b2", "B2", "Aflatoxin B2"),
                   ("afla_g1", "G1", "Aflatoxin G1"), ("afla_g2", "G2", "Aflatoxin G2")]
MYCO_COMP_KEYS = [k for k, _, _ in MYCO_COMPONENTS]

def parse_mycotoxins(text: str, p: Product):
    """Capture EVERY mycotoxin CT regulates: aflatoxin B1/B2/G1/G2 and
    ochratoxin A. Ochratoxin + combined 'Aflatoxins' are handled by the generic
    label loop; here we add the individual aflatoxin component rows."""
    for key, sub, name in MYCO_COMPONENTS:
        # a real component row: the sub-label at line start, then a number
        m = re.search(r"(?mi)^\s*" + sub + r"\b\s+([0-9<].*)$", text)
        if not m:
            continue
        res = extract_result(m.group(1), MYCOTOXIN_LIMIT)
        unit = _detect_unit(text[max(0, m.start() - 300): m.start() + 60]) or "µg/kg"
        lim = res.get("limit") or MYCOTOXIN_LIMIT
        if res["nd"]:
            p.analytes[key] = {"raw": "ND", "value": 0.0, "status": "ND",
                               "name": name, "limit": lim, "unit": unit}
        elif res["value"] is not None:
            p.analytes[key] = {"raw": res["raw"], "value": res["value"],
                               "status": "", "name": name, "limit": lim, "unit": unit}


def detect_internal_contradiction(text: str) -> bool:
    cleaned = re.sub(r"pass\s*[/|]\s*fail", " ", text, flags=re.I)
    cleaned = re.sub(r"\bpass\s+fail\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"(determine|determining|for)\s+fail(?:ure|ed)?\b", " ", cleaned, flags=re.I)
    if re.search(r"\b(exceeds?|exceeded|out\s+of\s+spec(?:ification)?|"
                 r"over\s+(?:the\s+)?limit|above\s+(?:the\s+)?(?:action\s+)?limit)\b",
                 cleaned, re.I):
        return True
    for m in re.finditer(r"\bfail(?:ed|ure)?\b", cleaned, re.I):
        ctx = cleaned[max(0, m.start() - 14): m.end() + 6].lower()
        if "pass" in ctx:
            continue
        return True
    return False


# ----------------------------------------------------------------------------
# Flagging
# ----------------------------------------------------------------------------
# Heavy metals + mycotoxins: ANY detectable amount flags the product. Over the
# COA's own limit -> RED; detected but within limit -> ORANGE (still surfaced).
DETECTABLE_CONTAMINANTS = (
    ["aflatoxin", "ochratoxin"] + MYCO_COMP_KEYS +
    ["arsenic", "cadmium", "lead", "mercury", "chromium"])


def _amount(e) -> str:
    v = e.get("value")
    unit = e.get("unit") or ""
    num = f"{int(v):,}" if (v is not None and v == int(v)) else f"{v:,.3f}".rstrip("0").rstrip(".")
    q = (e.get("raw") or "")[:1]
    q = q if q in "<>≤≥" else ""
    return f"{q}{num} {unit}".strip()


def apply_flags(p: Product, text: str, watch: int):
    a = p.analytes

    # 1. Zero-tolerance microbiological (qPCR): pathogens + pathogenic Aspergillus
    #    -- ANY detection is a RED do-not-consume.
    nd_names = {"ecoli": "Escherichia coli", "stec": "Shiga toxin-producing E. coli",
                "salmonella": "Salmonella", "listeria": "Listeria monocytogenes",
                "aspergillus": "Pathogenic Aspergillus"}
    for key, nice in nd_names.items():
        e = a.get(key)
        if e and e.get("status") == "DETECTED":
            p.flags.append(f"PROHIBITED_DETECTED: {nice} DETECTED (zero tolerance)")

    # 2. Heavy metals + mycotoxins: any DETECTED amount flags the product.
    for key in DETECTABLE_CONTAMINANTS:
        e = a.get(key)
        if not e or e.get("value") is None or e["value"] <= 0:
            continue
        if (e.get("raw") or "")[:1] in "<≤":        # below detection -> not detected
            continue
        nm = e.get("name", key)
        lim = e.get("limit")
        if lim and e["value"] > lim:
            p.flags.append(f"OVER_CT_LIMIT: {nm} {_amount(e)} exceeds COA limit "
                           f"{lim:g} {e.get('unit','')}".rstrip())
        else:
            within = f" (within COA limit {lim:g})" if lim else ""
            p.flags.append(f"CONTAMINANT_DETECTED: {nm} {_amount(e)} detected{within}")

    # 2b. Residual solvents: ANY itemized detection -> YELLOW (report the level);
    #     over the COA's ppm limit -> RED; a failed solvent panel -> RED.
    for h in p.solvent_hits:
        amt = f"{h['value']:,.3f}".rstrip("0").rstrip(".") + f" {h.get('unit','ppm')}"
        if h.get("limit") and h["value"] > h["limit"]:
            p.flags.append(f"OVER_CT_LIMIT: {h['name']} {amt} exceeds COA limit "
                           f"{h['limit']:g} ppm")
        else:
            within = f" (limit {h['limit']:g} ppm)" if h.get("limit") else ""
            p.flags.append(f"SOLVENT_DETECTED: {h['name']} {amt} detected{within}")
    if p.solvents == "FAIL" and not p.solvent_hits:
        p.flags.append("OVER_CT_LIMIT: residual solvent panel FAIL (verify against COA)")

    # Pesticides: a FAILED pesticide panel = a prohibited or over-limit pesticide
    # (CT forbids several outright). Treat as RED do-not-consume.
    if p.pesticides == "FAIL":
        p.flags.append("OVER_CT_LIMIT: pesticide panel FAIL (prohibited/over-limit "
                       "pesticide -- verify against COA)")

    # 3. Total-count microbials over CT's codified ceiling (not 'any amount' --
    #    these are always present in some quantity).
    for key, nice in (("aerobic", "total aerobic"), ("coliform", "total coliform"),
                      ("btgn", "bile-tolerant gram-negative")):
        e = a.get(key)
        if not e or e.get("value") is None:
            continue
        lim = e.get("limit") or (CT_MICRO_LIMIT if key == "aerobic" else None)
        if lim and e["value"] > lim:
            p.flags.append(f"OVER_CT_LIMIT: {nice} {_amount(e)} > {lim:,.0f} CFU/g")

    # 4. Internal contradiction -> wrongful pass
    if p.overall_result in ("PASS", "PASSED") and detect_internal_contradiction(text):
        p.flags.append("WRONGFUL_PASS: a row reads FAIL/exceeds while batch marked PASS (verify)")

    # 5. Yeast & mold -- its OWN scale: > legal 100k = RED; watch..100k = YELLOW.
    tymc = a.get("tymc")
    if tymc and tymc.get("value") is not None:
        ym = tymc["value"]
        if ym > CT_MICRO_LIMIT:
            p.flags.append(f"OVER_CT_LIMIT: yeast & mold {_amount(tymc)} "
                           f"> {CT_MICRO_LIMIT:,} CFU/g (CT legal limit)")
        elif ym > watch:
            p.flags.append(f"OVER_WATCH_THRESHOLD: yeast & mold {_amount(tymc)} "
                           f"> {watch:,} watch line (LEGAL in CT; limit {CT_MICRO_LIMIT:,})")

    # 6. Remediation signature: low/ND yeast&mold yet a mycotoxin detectable
    myco_hit = any(a.get(k) and a[k].get("value") and a[k]["value"] > 0
                   for k in ["aflatoxin", "ochratoxin"] + MYCO_COMP_KEYS)
    if (is_flower(p) and tymc and tymc.get("value") is not None
            and tymc["value"] <= watch and myco_hit):
        p.flags.append("REMEDIATION_VERIFY: low/ND yeast&mold but a mycotoxin is detectable (verify)")


# ----------------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------------
def load_ledger() -> set:
    if not os.path.exists(LEDGER):
        return set()
    with open(LEDGER) as f:
        return {ln.strip() for ln in f if ln.strip()}


def save_ledger(keys: set):
    with open(LEDGER, "w") as f:
        for k in sorted(keys):
            f.write(k + "\n")


# ----------------------------------------------------------------------------
# Severity / PDF
# ----------------------------------------------------------------------------
SEV_RANK = {"RED": 3, "ORANGE": 2, "YELLOW": 1, None: 0}
SEV_TINT = {"RED": "#f8d2d0", "ORANGE": "#ffe3c2", "YELLOW": "#fff4c2"}
SEV_BAR = {"RED": "#c0392b", "ORANGE": "#e67e22", "YELLOW": "#b8950a"}
SEV_LABEL = {"RED": "DO NOT<br/>CONSUME", "ORANGE": "HIGH<br/>CAUTION",
             "YELLOW": "MODERATE<br/>CAUTION"}


def _esc(s) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def flag_severity(flag: str) -> str:
    # zero-tolerance microbiological (incl. pathogenic Aspergillus) and any
    # codified-limit exceedance -> RED do-not-consume.
    if flag.startswith(("PROHIBITED_DETECTED", "OVER_CT_LIMIT",
                        "MYCOTOXIN_OVER", "WRONGFUL_PASS")):
        return "RED"
    # a contaminant detected but within its legal limit, or remediation signature
    # -> ORANGE caution (still surfaced for sensitive consumers).
    if flag.startswith(("CONTAMINANT_DETECTED", "REMEDIATION_VERIFY")):
        return "ORANGE"
    # solvent detected within limit, or yeast&mold over the watch line -> YELLOW.
    return "YELLOW"


def product_severity(p) -> Optional[str]:
    best = None
    for f in p.flags:
        s = flag_severity(f)
        if SEV_RANK[s] > SEV_RANK[best]:
            best = s
    return best


def alarm_score(p) -> float:
    """A single comparable 'how alarming' number used to sort the report. Higher
    = worse. A detected zero-tolerance pathogen dominates; otherwise it's the
    worst fraction-of-limit across every analyte (so 250,000/100,000 yeast&mold
    = 2.5 outranks a 45,000/100,000 = 0.45), with solvents included."""
    score = 0.0
    a = p.analytes
    for k in ("ecoli", "stec", "salmonella", "listeria", "aspergillus"):
        if a.get(k, {}).get("status") == "DETECTED":
            score = max(score, 1e9)
    for e in a.values():
        v, lim = e.get("value"), e.get("limit")
        if v and lim and lim > 0:
            score = max(score, v / lim)
    for h in p.solvent_hits:
        if h.get("value") and h.get("limit"):
            score = max(score, h["value"] / h["limit"])
    tymc = a.get("tymc", {})
    if tymc.get("value"):
        score = max(score, tymc["value"] / CT_MICRO_LIMIT)
    return score


def yeast_mold_value(p) -> float:
    e = p.analytes.get("tymc", {})
    return e.get("value") or 0.0


# Units and FULL display names (no abbreviations). Order = most -> least serious.
DISPLAY_UNIT = {
    "tymc": "CFU/g", "aerobic": "CFU/g", "coliform": "CFU/g", "btgn": "CFU/g",
    "aflatoxin": "µg/kg", "afla_b1": "µg/kg", "afla_b2": "µg/kg",
    "afla_g1": "µg/kg", "afla_g2": "µg/kg", "ochratoxin": "µg/kg",
    # metals: NO fabricated default -- the COA's detected unit is used, else blank
    # (the result>limit flag is unit-safe either way).
    "arsenic": "", "cadmium": "", "lead": "", "mercury": "", "chromium": "",
}
DETECT_DISPLAY = [
    ("ecoli", "Escherichia coli"), ("salmonella", "Salmonella"),
    ("listeria", "Listeria monocytogenes"),
    ("stec", "Shiga toxin-producing E. coli"), ("aspergillus", "Aspergillus"),
    ("aflatoxin", "Total Aflatoxins"), ("afla_b1", "Aflatoxin B1"),
    ("afla_b2", "Aflatoxin B2"), ("afla_g1", "Aflatoxin G1"),
    ("afla_g2", "Aflatoxin G2"), ("ochratoxin", "Ochratoxin A"),
    ("arsenic", "Arsenic"), ("cadmium", "Cadmium"), ("lead", "Lead"),
    ("mercury", "Mercury"), ("chromium", "Chromium"),
    ("aerobic", "Total Aerobic Bacteria"), ("coliform", "Total Coliform"),
    ("btgn", "Bile-Tolerant Gram-Negative Bacteria"),
]


def _fmt_num(e) -> str:
    """Comma-consistent number, preserving a leading qualifier (e.g. <)."""
    v = e.get("value")
    if v is None:
        return ""
    raw = (e.get("raw") or "").strip()
    q = raw[0] if raw[:1] in "<>≤≥" else ""
    if v == int(v):
        s = f"{int(v):,}"
    else:
        s = f"{v:,.3f}".rstrip("0").rstrip(".")
    return q + s


def _notable(e) -> bool:
    """True only if the analyte was actually DETECTED / measured above zero.
    Not-detected, ND, and below-detection (<x) results are NOT notable, so they
    never clutter the report."""
    if not e:
        return False
    if e.get("status") == "DETECTED":
        return True
    v = e.get("value")
    if v is None or v == 0:
        return False
    if (e.get("raw") or "")[:1] in "<≤":
        return False
    return v > 0


def _ym_cell(p) -> str:
    e = p.analytes.get("tymc")
    return _fmt_num(e) if (e and e.get("value")) else "—"


def _contaminants_cell(p) -> str:
    """List ONLY contaminants actually detected, with full names, comma numbers,
    the COA's own unit, and whether the amount is within or OVER its limit.
    Nothing detected -> 'None detected'. Yeast & mold has its own column."""
    out = []
    for key, name in DETECT_DISPLAY:
        e = p.analytes.get(key)
        if not _notable(e):
            continue
        if e.get("status") == "DETECTED":
            out.append(f"<b>{name}: DETECTED</b>")
            continue
        unit = e.get("unit") or DISPLAY_UNIT.get(key, "")
        lim = e.get("limit")
        over = lim and e.get("value") is not None and e["value"] > lim
        ctx = ""
        if lim:
            ctx = (f" — OVER limit {lim:g}" if over else f" (limit {lim:g})")
        out.append(f"<b>{name} {_fmt_num(e)} {unit}{ctx}</b>".strip())
    for h in p.solvent_hits:
        amt = f"{h['value']:,.3f}".rstrip("0").rstrip(".") + f" {h.get('unit','ppm')}"
        over = h.get("limit") and h["value"] > h["limit"]
        ctx = (f" — OVER limit {h['limit']:g}" if over
               else (f" (limit {h['limit']:g})" if h.get("limit") else ""))
        out.append(f"<b>{h['name']} {amt}{ctx}</b>")
    return "<br/>".join(out) if out else "None detected"


def _solvent_cell(p) -> str:
    """Itemized solvent detections if any; else the grouped panel result. Raw
    flower / pre-rolls are not solvent-processed, so they carry no panel."""
    if p.solvent_hits:
        out = []
        for h in p.solvent_hits:
            amt = f"{h['value']:,.3f}".rstrip("0").rstrip(".") + f" {h.get('unit','ppm')}"
            over = h.get("limit") and h["value"] > h["limit"]
            out.append(f"<b>{h['name']} {amt}{' OVER' if over else ''}</b>")
        return "<br/>".join(out)
    if p.solvents == "FAIL":
        return "<b>Panel: FAIL</b>"
    if p.solvents == "PASS":
        return "Panel: below action limits"
    if is_flower(p) and not _matches(p.dosage_form, INHALABLE_KEYWORDS):
        return "N/A (not solvent-processed)"
    return "Not reported"


# ----------------------------------------------------------------------------
# "% of Limit Reached" -- proximity of each measured contaminant to BOTH the CT
# legal/action limit AND the stricter CannaScope CT standard. 100% = at that limit.
# Computed DYNAMICALLY from each COA's own value+limit; nothing is hardcoded.
#
# CannaScope CT limit: yeast & mold and total aerobic use the audit WATCH line
# (default 10,000 CFU/g, set by --threshold) -- the stricter-than-the-state line
# that is the whole point of this tool. Other contaminants default to the CT
# legal limit (no stricter CannaScope line) until you set one in CANNASCOPE_LIMITS
# below, e.g. CANNASCOPE_LIMITS["arsenic"] = 100  (same unit the COA reports).
# ----------------------------------------------------------------------------
CANNASCOPE_LIMITS = {}                         # analyte key -> absolute CannaScope CT limit
CANNASCOPE_WATCH_KEYS = ("tymc", "aerobic")   # these use the watch line as the CannaScope limit


def personal_limit(key, ct_limit, watch):
    if key in CANNASCOPE_LIMITS:
        return CANNASCOPE_LIMITS[key]
    if key in CANNASCOPE_WATCH_KEYS:
        return watch
    return ct_limit


def _fmt_pct(pct):
    if pct is None:
        return "N/A"
    return f"{pct:.1f}%" if pct >= 1 else f"{pct:.2f}%"


def _pct_label(pct):
    """'% of limit' plus a signed over/under-the-limit delta, e.g. 153% -> the
    contaminant is 53% OVER the limit -> '153.0% (+53%)'; 91.7% -> '91.7% (-8%)'.
    The sign makes 'over vs under the limit' obvious at a glance."""
    if pct is None:
        return "N/A"
    delta = pct - 100.0
    mag = abs(delta)
    dnum = f"{mag:.0f}" if mag >= 10 else f"{mag:.1f}"
    sign = "+" if delta >= 0 else "−"          # + over the limit, − under
    return f"{_fmt_pct(pct)} ({sign}{dnum}%)"


def pct_color(pct) -> str:
    """Informational proximity shading (NOT a regulatory violation):
    100%+ = at/over the standard, 90%+ dark red, 75-89.9% orange,
    50-74.9% yellow, else normal."""
    if pct is None:
        return "#000000"
    if pct >= 90:
        return "#c0392b"
    if pct >= 75:
        return "#e67e22"
    if pct >= 50:
        return "#b8950a"
    return "#000000"


def _fmt_value(v, unit: str) -> str:
    if v is None:
        return ""
    num = f"{int(v):,}" if v == int(v) else f"{v:,.3f}".rstrip("0").rstrip(".")
    return f"{num} {unit}".strip()


def limit_details(p, watch=DEFAULT_WATCH) -> list:
    """One dict per DETECTED contaminant with proximity to BOTH standards:
        {key, name, value, unit, ct_limit, ct_pct, my_limit, my_pct, raw}
    ct_pct/my_pct = (value / limit) * 100, or None when no limit applies.
    Fully derived from the parsed COA -- no hardcoded values."""
    items = []
    namemap = dict(DETECT_DISPLAY)

    def add(key, name, v, unit, ct_limit, raw):
        below = (raw or "")[:1] in "<≤"
        usable = v is not None and not below
        ct_pct = (v / ct_limit * 100.0) if (usable and ct_limit and ct_limit > 0) else None
        my_lim = personal_limit(key, ct_limit, watch) if ct_limit else None
        my_pct = (v / my_lim * 100.0) if (usable and my_lim and my_lim > 0) else None
        items.append({"key": key, "name": name, "value": v, "unit": unit,
                      "ct_limit": ct_limit, "ct_pct": ct_pct,
                      "my_limit": my_lim, "my_pct": my_pct, "raw": raw})

    for key in ["tymc"] + [k for k, _ in DETECT_DISPLAY]:
        e = p.analytes.get(key)
        if not _notable(e):
            continue
        add(key, e.get("name") or namemap.get(key, key), e.get("value"),
            e.get("unit") or DISPLAY_UNIT.get(key, ""), e.get("limit"), e.get("raw", ""))
    for h in p.solvent_hits:
        add("solvent:" + h["name"], h["name"], h.get("value"),
            h.get("unit", "ppm"), h.get("limit"), "")
    return items


def top_limit_detail(p, watch=DEFAULT_WATCH):
    """The contaminant closest to its CT limit (highest CT %), or None."""
    rated = [d for d in limit_details(p, watch) if d["ct_pct"] is not None]
    return max(rated, key=lambda d: d["ct_pct"]) if rated else None


def _pct_cell(p, which, watch=DEFAULT_WATCH) -> str:
    """A '% of limit' cell. which='ct' -> CT legal limit; which='my' -> the
    CannaScope CT limit. One color-coded line per contaminant; 'N/A' if no limit."""
    details = limit_details(p, watch)
    if not details:
        return "N/A"
    lines = []
    for d in details:
        pct = d["ct_pct"] if which == "ct" else d["my_pct"]
        if pct is None:
            lines.append(f'<font size="6">{_esc(d["name"])}: N/A</font>')
        else:
            lines.append(f'<font color="{pct_color(pct)}"><b>'
                         f'{_esc(d["name"])}: {_pct_label(pct)}</b></font>')
    return "<br/>".join(lines)


def next_report_path():
    """Each report gets its own incrementing name so prior reports are never
    overwritten:  'CannaScope CT - Flagged Products - 1.pdf', then 2, 3, ..."""
    import glob
    nums = []
    for f in glob.glob(os.path.join(OUT_DIR, "CannaScope CT - Flagged Products - *.pdf")):
        m = re.search(r"- (\d+)\.pdf$", f)
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    return os.path.join(OUT_DIR, f"CannaScope CT - Flagged Products - {n}.pdf"), n


def _producer_display(p, producer_map=None) -> str:
    """Best human-recognizable producer name, ALWAYS paired with the legal LLC:
        1. curated/verified DBA -> 'DBA (Legal LLC)'
        2. else the brand read off the COA product name -> 'Brand (Legal LLC)'
        3. else the legal name alone (genuinely unbranded, e.g. strain-only flower)
    Never shows a bare '[UNMAPPED]' legal name when the COA carries a brand."""
    legal = (p.producer or "").strip()
    if names is None:
        return legal or (p.brand or "")
    if legal:
        d = names.display_producer(legal, producer_map)
        if "[UNMAPPED" not in d:
            return d
    brand = (p.brand or "").strip()
    if brand and legal:
        return f"{brand} ({legal})"
    return brand or legal


def _producer_cell(p, producer_map=None) -> str:
    """HTML for the Producer column: the recognizable 'Name (Legal LLC)' plus the
    product's COA brand on a second line when it adds information."""
    primary = _producer_display(p, producer_map)
    base = _esc(primary)
    brand = (p.brand or "").strip()
    if brand and brand.lower() not in primary.lower():
        base += (f'<br/><font size="5" color="#555555">brand: '
                 f'{_esc(brand)}</font>')
    return base


def _lab_display(p, lab_map=None) -> str:
    """Recognizable lab name; raw parsed name if no resolver."""
    if names is None or not p.test_lab:
        return p.test_lab
    return names.display_lab(p.test_lab, lab_map)


def display_lab_name(lab: str, lab_map=None) -> str:
    """String-based lab display (for summaries); raw name if no resolver."""
    if names is None or not lab:
        return lab
    return names.display_lab(lab, lab_map)


def build_pdf(flagged: list, out_path: str, watch: int, report_no: int = 1,
              producer_map=None, lab_map=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, legal
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, PageBreak)

    PAGE = landscape(legal)            # 14 x 8.5 in -- wide, for legible tables
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("c", parent=styles["Normal"], fontSize=7, leading=8.5)
    head = ParagraphStyle("h", parent=styles["Normal"], fontSize=7, leading=8.5,
                          textColor=colors.white)
    risk = ParagraphStyle("r", parent=styles["Normal"], fontSize=6.5, leading=7.5,
                          textColor=colors.white, alignment=1)

    doc = SimpleDocTemplate(out_path, pagesize=PAGE,
                            leftMargin=0.3*inch, rightMargin=0.3*inch,
                            topMargin=0.45*inch, bottomMargin=0.45*inch)
    from collections import Counter
    sev_counts = Counter(product_severity(p) or "YELLOW" for p in flagged)
    summary = (f"{len(flagged)} flagged products — "
               f"{sev_counts.get('RED', 0)} RED, {sev_counts.get('ORANGE', 0)} ORANGE, "
               f"{sev_counts.get('YELLOW', 0)} YELLOW. Sorted most-alarming first.")
    story = [
        Paragraph(f"CannaScope CT — Flagged Products — {report_no}", styles["Title"]),
        Paragraph("Connecticut Cannabis Contaminant Report (all product types) — "
                  "for consumer awareness",
                  ParagraphStyle("sub", parent=styles["Normal"], fontSize=10,
                                 leading=12, alignment=1, spaceAfter=4)),
        Paragraph(f"<b>{summary}</b>",
                  ParagraphStyle("sum", parent=styles["Normal"], fontSize=9.5,
                                 leading=12, alignment=1, spaceAfter=4)),
        Paragraph(
            "Exact contaminant values from each product's linked Certificate of "
            "Analysis (CT registry egd5-wb6r), checked against Connecticut's "
            "codified standards (Conn. Agencies Regs. &sect;21a-408-60): zero "
            "tolerance for E.&nbsp;coli, STEC, Salmonella, Listeria and pathogenic "
            f"Aspergillus; yeast&amp;mold and total aerobic &le; {CT_MICRO_LIMIT:,} "
            f"CFU/g; mycotoxins &lt; 20&nbsp;&micro;g/kg. The report shows each "
            f"result's proximity to BOTH the <b>CT legal limit</b> and the "
            f"stricter <b>CannaScope CT limit</b> (yeast&amp;mold/aerobic watch "
            f"line = {watch:,}&nbsp;CFU/g). YELLOW rows exceed the CannaScope CT "
            "limit but remain LEGAL in CT. Every row is a lead to verify against "
            "the COA.",
            ParagraphStyle("desc", parent=styles["Normal"], fontSize=8, leading=10)),
        Spacer(1, 4),
        Paragraph(
            '<font color="#c0392b"><b>RED = do not consume</b></font> '
            '&nbsp;&nbsp;&nbsp; '
            '<font color="#e67e22"><b>ORANGE = use high caution if sensitive'
            '</b></font> &nbsp;&nbsp;&nbsp; '
            '<font color="#b8950a"><b>YELLOW = moderate caution for those with '
            'sensitivities</b></font>',
            ParagraphStyle("key", parent=styles["Normal"], fontSize=8.5, leading=11,
                           alignment=1)),
        Spacer(1, 3),
        Paragraph(
            "Each % shows the result as a share of that limit, with the amount "
            "over/under it in parentheses: e.g. <b>153% (+53%)</b> = 53% OVER the "
            "limit; <b>91.7% (&minus;8%)</b> = 8% under. (+) = over, (&minus;) = under.",
            ParagraphStyle("pkey", parent=styles["Normal"], fontSize=8, leading=10,
                           alignment=1)),
        Spacer(1, 12),
    ]

    # ---- Executive Summary: Products Closest to the Limits ------------------
    # One row per flagged product = its contaminant nearest a limit, ranked by
    # % of CT limit reached (descending). Shows BOTH standards. Fully dynamic.
    h2 = ParagraphStyle("h2", parent=styles["Normal"], fontSize=13, leading=15,
                        spaceAfter=2, textColor=colors.HexColor("#1f3b4d"))
    esum = [Paragraph("Executive Summary — Products Closest to the Limits", h2),
            Paragraph("Ranked by how close the nearest contaminant is to its CT "
                      "limit. Each shows proximity to the CT legal limit AND the "
                      "stricter CannaScope CT limit. Proximity is informational; a "
                      "product may be near a limit and still legally PASS.",
                      ParagraphStyle("h2s", parent=cell, fontSize=8.5, leading=10,
                                     spaceAfter=6))]
    ranked = sorted(((p, top_limit_detail(p, watch)) for p in flagged),
                    key=lambda pd: pd[1]["ct_pct"] if pd[1] else -1, reverse=True)
    ranked = [(p, d) for p, d in ranked if d]
    if ranked:
        ecols = ["#", "Product", "Producer", "Contaminant", "Measured Value",
                 "CT Legal Limit", "% of CT Legal Limit",
                 "CannaScope CT Limit", "% of CannaScope CT Limit"]
        edata = [[Paragraph(f"<b>{c}</b>", head) for c in ecols]]
        for rank, (p, d) in enumerate(ranked, start=1):
            edata.append([
                Paragraph(str(rank), cell),
                Paragraph(_esc(p.product_name), cell),
                Paragraph(_esc(_producer_display(p, producer_map)), cell),
                Paragraph(_esc(d["name"]), cell),
                Paragraph(_esc(_fmt_value(d["value"], d["unit"])), cell),
                Paragraph(_esc(_fmt_value(d["ct_limit"], d["unit"])), cell),
                Paragraph(f'<font color="{pct_color(d["ct_pct"])}"><b>'
                          f'{_pct_label(d["ct_pct"])}</b></font>', cell),
                Paragraph(_esc(_fmt_value(d["my_limit"], d["unit"])), cell),
                Paragraph(f'<font color="{pct_color(d["my_pct"])}"><b>'
                          f'{_pct_label(d["my_pct"])}</b></font>', cell),
            ])
        et = Table(edata, repeatRows=1,
                   colWidths=[0.3*inch, 2.5*inch, 2.0*inch, 1.45*inch, 1.35*inch,
                              1.2*inch, 1.0*inch, 1.2*inch, 1.0*inch])
        et.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b4d")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#eef2f5")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        esum.append(et)
    else:
        esum.append(Paragraph("No measured contaminant has an applicable CT limit "
                              "in this run.", cell))
    esum.append(PageBreak())
    story.extend(esum)

    def _ps(v):
        if v == "FAIL":
            return '<font color="#c0392b"><b>FAIL</b></font>'
        return v or "Not tested"

    def _pest_solv(p):
        return (f'<b>Pesticides:</b> {_ps(p.pesticides)}<br/>'
                f'<b>Solvents:</b> {_solvent_cell(p)}')

    cols = ["Risk", "Date", "Product", "Producer", "Form", "Lab",
            "Yeast &amp; Mold<br/>(CFU/g)", "Other Contaminants Detected",
            "% of CT<br/>Legal Limit", "% of CannaScope<br/>CT Limit",
            "Pesticides /<br/>Solvents", "COA #"]
    data = [[Paragraph(c, head) for c in cols]]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b4d")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, p in enumerate(flagged, start=1):
        sev = product_severity(p) or "YELLOW"
        coa_ref = p.registration_number or "COA"
        data.append([
            Paragraph(SEV_LABEL[sev], risk),
            Paragraph(p.approval_date.split()[0] if p.approval_date else "", cell),
            Paragraph(_esc(p.product_name), cell),
            Paragraph(_producer_cell(p, producer_map), cell),
            Paragraph(_esc(p.dosage_form), cell),
            Paragraph(_esc(_lab_display(p, lab_map)) or "—", cell),
            Paragraph(_ym_cell(p), cell),
            Paragraph(_contaminants_cell(p), cell),
            Paragraph(_pct_cell(p, "ct", watch), cell),
            Paragraph(_pct_cell(p, "my", watch), cell),
            Paragraph(_pest_solv(p), cell),
            # Clickable COA number -> opens the exact source COA PDF on the CT
            # portal, so anyone can self-verify the product and its results.
            Paragraph(f'<link href="{_esc(p.report_url)}">'
                      f'<font color="#1155cc"><u><b>{_esc(coa_ref)}</b></u></font></link>'
                      if p.report_url else _esc(coa_ref), cell),
        ])
        style_cmds.append(("BACKGROUND", (1, i), (-1, i), colors.HexColor(SEV_TINT[sev])))
        style_cmds.append(("BACKGROUND", (0, i), (0, i), colors.HexColor(SEV_BAR[sev])))

    t = Table(data, repeatRows=1,
              colWidths=[0.55*inch, 0.5*inch, 1.7*inch, 1.45*inch, 0.7*inch,
                         1.0*inch, 0.8*inch, 2.2*inch, 0.85*inch, 0.9*inch,
                         1.15*inch, 0.8*inch])
    t.setStyle(TableStyle(style_cmds))
    story.append(t)

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#555555"))
        w, _h = PAGE
        line1 = ("Beta tool — every flag is a LEAD, not a conclusion. Verify each "
                 "product against its COA (registration # shown in each row) before "
                 "relying on or sharing any result.")
        line2 = ("Found a misread? Please report it: github.com/jmlschlee/"
                 "Connecticut-Cannabis-Contaminant-Checker-Beta-V1/issues")
        canvas.drawCentredString(w / 2.0, 0.30 * inch, line1)
        canvas.drawCentredString(w / 2.0, 0.20 * inch, line2)
        canvas.drawRightString(w - 0.35 * inch, 0.20 * inch, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    print(f"Wrote {out_path}  ({len(flagged)} rows)")


# ----------------------------------------------------------------------------
# Worker
# ----------------------------------------------------------------------------
def process_product(p: Product, session) -> Product:
    path = download_pdf(p, session)
    if not path:
        p.parse_note = p.parse_note or "could not download COA"
        return p
    text = read_pdf_text(path)             # path-based: thread-stable under lock
    if len(text.strip()) < 40:
        p.parse_note = "no extractable text (scanned image?)"
        return p
    p.overall_result = find_overall_result(text)
    p.test_lab = parse_lab(text)
    parse_analytes(text, p)
    apply_flags(p, text, process_product.watch)
    return p


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="CT cannabis inhalable contaminant audit")
    ap.add_argument("--forms", choices=["flower", "inhalable", "all"],
                    default="all", help="default: all product types")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"look-back window in days (default {DEFAULT_DAYS})")
    ap.add_argument("--since", default="", help="explicit YYYY-MM-DD (overrides --days)")
    ap.add_argument("--threshold", type=int, default=DEFAULT_WATCH,
                    help=f"yeast/mold watch threshold (default {DEFAULT_WATCH})")
    ap.add_argument("--max-flagged", type=int, default=0,
                    help="cap rows in the PDF (0 = all flagged)")
    ap.add_argument("--limit", type=int, default=0, help="cap COAs scanned (0 = all)")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                    help=f"concurrent download+parse workers (default {DEFAULT_WORKERS})")
    ap.add_argument("--cookies", default="", help="Netscape cookies.txt")
    ap.add_argument("--refresh-registry", action="store_true",
                    help="force re-download of the registry CSV")
    ap.add_argument("--keep-clean-pdfs", action="store_true")
    ap.add_argument("--no-live-names", action="store_true",
                    help="don't seed the producer universe from the registry; use "
                         "curated producer/lab names only")
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

    os.makedirs(OUT_DIR, exist_ok=True)
    process_product.watch = args.threshold
    process_product.keep_clean = args.keep_clean_pdfs
    t0 = time.time()
    session = make_session(args.cookies, args.workers)

    products = load_registry(session, refresh=args.refresh_registry)
    products.sort(key=lambda p: parse_date(p.approval_date), reverse=True)

    # Resolve producer/lab common (DBA) + legal names once. The producer universe
    # comes straight from the registry we just downloaded (egd5-wb6r) so EVERY
    # producer is accounted for; curated DBA / common names layer on top. Labs
    # aren't in the registry (they're read off each COA), so the lab map is the
    # curated set, and the coverage audit flags any parsed lab we don't recognize.
    producer_map = lab_map = None
    if names is not None:
        if args.no_live_names:
            producer_map = names.get_producer_map(use_live=False)
        else:
            registry_producers = sorted({p.producer for p in products if p.producer})
            producer_map = names.get_producer_map(registry_names=registry_producers)
        lab_map = names.get_lab_map(use_live=False)
        print(f"Names: {len(producer_map)} producers known "
              f"({'curated only' if args.no_live_names else 'registry + curated'}), "
              f"{len(lab_map)} labs known.")

    before = len(products)
    products = prefilter(products, args.forms, since)
    since_str = f"{since[0]:04d}-{since[1]:02d}-{since[2]:02d}" if since else "any date"
    print(f"  prefilter ({args.forms}, since {since_str}): "
          f"{len(products)} of {before} to scan.")
    if args.limit:
        products = products[:args.limit]
    if not products:
        sys.exit("No products matched. Widen --forms / --days.")

    ledger = load_ledger()
    todo = [p for p in products if coa_key(p) not in ledger]
    print(f"  {len(products) - len(todo)} already scanned clean (skipping).")
    print(f"\nScanning {len(todo)} COAs with {args.workers} workers "
          f"(clean COAs deleted right after evaluation; only flagged kept"
          f"{'; all kept' if args.keep_clean_pdfs else ''}).\n")

    all_results, failures, flagged_keep = [], [], []
    new_clean = set()
    lock = threading.Lock()
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_product, p, session): p for p in todo}
        for fut in as_completed(futs):
            p = fut.result()
            with lock:
                done += 1
                all_results.append(p)
                parsed = bool(p.analytes) or p.mold_yeast_cfu is not None
                key = coa_key(p)
                if p.flags:
                    flagged_keep.append(p)          # keep its PDF for verification
                elif parsed:
                    # evaluated, nothing of note -> delete the PDF + remember it
                    new_clean.add(key)
                    if not args.keep_clean_pdfs:
                        try:
                            os.remove(cache_path(p))
                        except OSError:
                            pass
                else:
                    failures.append(p)
                    # downloaded but unreadable even with OCR -> drop it + remember,
                    # so the cache never fills with dead documents.
                    if "no extractable text" in (p.parse_note or ""):
                        new_clean.add(key)
                        if not args.keep_clean_pdfs:
                            try:
                                os.remove(cache_path(p))
                            except OSError:
                                pass
                if done % 50 == 0 or done == len(todo):
                    print(f"  {done}/{len(todo)}  ({len(flagged_keep)} flagged, "
                          f"{time.time()-t0:.0f}s)", flush=True)

    # write full CSV
    analyte_keys = [s["key"] for s in ANALYTE_SPECS] + MYCO_COMP_KEYS
    base_keys = ["product_name", "dosage_form", "producer", "brand", "approval_date",
                 "registration_number", "test_lab", "overall_result",
                 "pesticides", "solvents", "mold_yeast_raw", "report_url", "parse_note"]
    with open(FULL_CSV_OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(base_keys + ["producer_display", "lab_display"]
                   + analyte_keys + ["flags"])
        for p in sorted(all_results, key=lambda x: parse_date(x.approval_date), reverse=True):
            d = asdict(p)
            row = [d[k] for k in base_keys]
            row.append(_producer_display(p, producer_map))   # common DBA + legal LLC
            row.append(_lab_display(p, lab_map))
            for ak in analyte_keys:
                e = p.analytes.get(ak, {})
                row.append(e.get("raw") or e.get("status") or "")
            row.append(" | ".join(p.flags))
            w.writerow(row)
    print(f"Wrote {FULL_CSV_OUT}")

    if failures:
        with open(FAILURES_CSV_OUT, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["product_name", "dosage_form", "producer", "approval_date",
                        "parse_note", "report_url"])
            for p in failures:
                w.writerow([p.product_name, p.dosage_form, p.producer,
                            p.approval_date, p.parse_note, p.report_url])
        print(f"Wrote {FAILURES_CSV_OUT}  ({len(failures)} need review)")

    # ---- Coverage guarantee: account for EVERY lab and EVERY producer seen ----
    # Audit across ALL scanned products (not just flagged) so a lab or producer
    # can't quietly fall out of the analysis. Unknowns are reported, never dropped.
    if names is not None:
        coa_labs = [p.test_lab for p in all_results if p.test_lab]
        coa_producers = [p.producer for p in all_results if p.producer]
        lab_rep = names.audit_lab_coverage(coa_labs, lab_map)
        prod_rep = names.audit_producer_coverage(coa_producers, producer_map)
        print(f"Coverage: {len(lab_rep['labs_seen_in_coas'])} labs seen "
              f"({len(lab_rep['unrecognized_labs'])} unrecognized); "
              f"{len(prod_rep['producers_seen_in_coas'])} producers seen "
              f"({len(prod_rep['unmapped_producers'])} unmapped).")
        with open(COVERAGE_CSV_OUT, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["kind", "status", "name"])
            for n in lab_rep["unrecognized_labs"]:
                w.writerow(["lab", "UNRECOGNIZED -- verify", n])
            for n in lab_rep["known_labs_without_coas"]:
                w.writerow(["lab", "known, no COAs this run", n])
            for n in prod_rep["unmapped_producers"]:
                w.writerow(["producer", "UNMAPPED -- verify", n])
            for n in prod_rep["known_producers_without_coas"]:
                w.writerow(["producer", "known, no COAs this run", n])
        print(f"Wrote {COVERAGE_CSV_OUT}")

    # Per-lab analysis summary -- proves EVERY lab's COAs were not just seen but
    # actually parsed for the numeric contaminants (yeast&mold), and how many
    # flagged. A lab with COAs but 0 yeast&mold parsed is a parser-coverage gap.
    lab_stats = {}
    for p in all_results:
        lab = p.test_lab or "(unidentified)"
        s = lab_stats.setdefault(lab, {"scanned": 0, "ym_parsed": 0, "flagged": 0, "max_ym": 0.0})
        s["scanned"] += 1
        ym = p.analytes.get("tymc", {}).get("value")
        if ym is not None:
            s["ym_parsed"] += 1
            s["max_ym"] = max(s["max_ym"], ym)
        if p.flags:
            s["flagged"] += 1
    with open(LAB_SUMMARY_CSV_OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["lab", "coas_scanned", "yeast_mold_parsed", "flagged", "max_yeast_mold_cfu_g"])
        for lab, s in sorted(lab_stats.items(), key=lambda kv: -kv[1]["scanned"]):
            disp = display_lab_name(lab, lab_map)
            w.writerow([disp, s["scanned"], s["ym_parsed"], s["flagged"], f"{s['max_ym']:.0f}"])
    print(f"Wrote {LAB_SUMMARY_CSV_OUT}")
    print("  Per-lab analysis:")
    for lab, s in sorted(lab_stats.items(), key=lambda kv: -kv[1]["scanned"]):
        print(f"    {display_lab_name(lab, lab_map):28s} {s['scanned']:4d} scanned, "
              f"{s['ym_parsed']:4d} yeast&mold parsed, {s['flagged']:3d} flagged "
              f"(max Y&M {s['max_ym']:,.0f} CFU/g)")

    save_ledger(ledger | new_clean)

    # Prune the cache to ONLY the products flagged this run, so it never grows
    # without bound (out-of-window or previously-flagged-then-cleared PDFs go).
    if not args.keep_clean_pdfs:
        flagged_keys = {coa_key(p) for p in flagged_keep}
        try:
            removed = 0
            for fn in os.listdir(CACHE_DIR):
                if fn.endswith(".pdf") and fn[:-4] not in flagged_keys:
                    os.remove(os.path.join(CACHE_DIR, fn))
                    removed += 1
            if removed:
                print(f"  cache pruned: removed {removed} non-flagged PDF(s).")
        except OSError:
            pass

    # Most SEVERE first: RED (do not consume) -> ORANGE -> YELLOW, and within each
    # severity tier by contaminant magnitude (worst fraction-of-limit, then the
    # raw yeast & mold count) descending.
    flagged_keep.sort(key=lambda p: (SEV_RANK[product_severity(p) or "YELLOW"],
                                     alarm_score(p), yeast_mold_value(p)),
                      reverse=True)
    print(f"\nFlagged products: {len(flagged_keep)}  (elapsed {time.time()-t0:.0f}s)")
    if flagged_keep:
        rows = flagged_keep[:args.max_flagged] if args.max_flagged else flagged_keep
        out_path, report_no = next_report_path()
        build_pdf(rows, out_path, args.threshold, report_no,
                  producer_map=producer_map, lab_map=lab_map)
        # Also drop the numbered report at the TOP of the working folder (e.g.
        # ~/Downloads) so it's immediately visible without opening the subfolder.
        import shutil
        visible = os.path.join(os.path.dirname(os.path.abspath(OUT_DIR)),
                               os.path.basename(out_path))
        try:
            shutil.copy2(out_path, visible)
        except OSError:
            visible = out_path
        print("\n" + "=" * 70)
        print(f"  YOUR REPORT #{report_no} IS READY:")
        print(f"    {visible}")
        print(f"  (also in the output folder: {os.path.abspath(out_path)})")
        print("=" * 70)
    else:
        print("No products flagged. Widen --days/--forms, or COAs may be gated "
              "(rerun with --cookies).")


if __name__ == "__main__":
    main()
