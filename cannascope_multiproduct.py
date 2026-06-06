#!/usr/bin/env python3
"""
CannaScope — multi-product COA recognition & per-product isolation.

Some historical CT COA documents (notably the 2015-era Northeast Laboratories,
Inc. "Analytical Report" PDFs sent to Connecticut Pharmaceutical Solutions)
pack SEVERAL products into a single document. Two real layouts occur, and they
must NOT be confused:

  LAYOUT A — single product, one PANEL per page.
    All pages share ONE Laboratory ID # (e.g. ``1562734-07``); each page is a
    different analyte panel (Microbial, Heavy Metals, Terpenes, Pesticides,
    Cannabinoids ...). The Product Description is identical on every page.
    -> This is ONE product. Pages must be COMBINED, never split.

  LAYOUT B — many products, one PRODUCT per page.
    The Laboratory ID # suffix INCREMENTS down the document
    (``1562829-01``, ``-02``, ``-03`` ...). Each page is a DIFFERENT product
    with its own Product Description (e.g. "Scott's OG #1" ... "#5").
    -> These are SEPARATE products and MUST be isolated before extraction, or
       one product's contaminants get attributed to another (catastrophic for
       a safety report).

The disambiguator is the **Laboratory ID #** (full ``NNNNNNN-NN`` string):
pages sharing one Lab ID are the SAME sample; distinct Lab IDs are distinct
products.

This module is intentionally conservative. ``isolate_product`` returns the
matching block ONLY when it can confidently tie the registry product to exactly
one block; otherwise it returns ``None`` with a reason so the pipeline can route
the record to manual review instead of guessing (which would risk
cross-attribution).

Pure-stdlib (``re`` only); never raises on bad input.
"""
from __future__ import annotations

import re
from typing import List, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Low-level field extractors (work on a single page's OCR/text)
# ---------------------------------------------------------------------------

# Laboratory ID #, e.g. "1562829 - 01", "1562949–06", "1562734-07".
_LAB_ID = re.compile(r"\b(1\d{6})\s*[-‒-―−]\s*(\d{1,3})\b")
# Laboratory Report #, e.g. "N1562829".
_LAB_REPORT = re.compile(r"\bN\s?(1\d{6})\b")
# CT registry registration number (data.ct.gov era), e.g. "MMBR.0033648".
_MMBR = re.compile(r"MMBR\.?\s?\d{4,}", re.I)
# "Page X of Y" page marker (1 per physical page in this format).
_PAGE_OF = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I)

# Northeast Labs "Analytical Report" page header — used as a page-top anchor when
# segmenting concatenated text that has lost its physical page breaks.
_PAGE_TOP = re.compile(r"Northeast\s+Laboratories,\s*Inc\.\s*\n\s*(?:Analytical\s+Report|Report\s+To:)",
                       re.I)


def lab_id(text: str) -> str:
    """Normalized Laboratory ID #, ``"NNNNNNN-NN"`` (zero-padded suffix), or ""."""
    m = _LAB_ID.search(text or "")
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2)):02d}"


def lab_report_no(text: str) -> str:
    m = _LAB_REPORT.search(text or "")
    return f"N{m.group(1)}" if m else ""


# Per-block secondary identifiers. These DISTINGUISH product blocks inside one document and, when a
# registry record happens to carry the same value, MATCH a record to its block. Conservative patterns:
# we would rather extract "" than a wrong value (a wrong identifier could mis-match -> cross-attribution).
_SAMPLE_ID = re.compile(r"\bSample\s*(?:ID|I\.D\.|Number|No\.?|#)\s*:?\s*([A-Za-z0-9][A-Za-z0-9\-/]{2,})", re.I)
_BATCH = re.compile(r"\b(?:Batch|Lot)\s*(?:ID|Number|No\.?|#)?\s*:?\s*([A-Za-z0-9][A-Za-z0-9\-/]{2,})", re.I)
_TEST_DATE = re.compile(r"\bDate\s*Tested\s*:?\s*([0-9]{1,2}[/\-][0-9]{1,2}[/\-][0-9]{2,4}|\d{4}-\d{2}-\d{2})", re.I)


def sample_id(text: str) -> str:
    m = _SAMPLE_ID.search(text or "")
    return m.group(1).strip() if m else ""


def batch_id(text: str) -> str:
    m = _BATCH.search(text or "")
    return m.group(1).strip() if m else ""


def test_date(text: str) -> str:
    m = _TEST_DATE.search(text or "")
    return m.group(1).strip() if m else ""


def registration_numbers(text: str) -> List[str]:
    """Distinct CT registration numbers (MMBR.######) found in the block, normalized."""
    return sorted({m.group(0).upper().replace(" ", "").replace("MMBR", "MMBR.").replace("..", ".")
                   for m in _MMBR.finditer(text or "")})


# Lines that appear in the identity block but are NOT the product description —
# the OCR interleaves these field VALUES (sample site, collector, dates, IDs,
# the company header) between the labels and the real product name.
_CHROME = re.compile(
    r"^(?:•|connecticut pharmaceutical|.*lower main|.*portland\s*c?t\b|"
    r"sample site|date collected|collected by|laboratory id|product description|"
    r"ca of nelabs|\d{1,2}[/:]\d|page\s+\d+\s+of|\d+\s*kilograms?|\d+\s*gram)",
    re.I)


def _is_chrome(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return True
    if _CHROME.match(s):
        return True
    # bare lab-id / report-no lines, or a lone address/number
    if _LAB_ID.fullmatch(s) or _LAB_REPORT.fullmatch(s):
        return True
    return False


def product_description(text: str) -> str:
    """The page's Product Description value. Reads the labelled field, skipping the
    interleaved identity-block "chrome" lines (sample site, dates, IDs, company
    header) that the OCR drops between the label and the real product name."""
    t = text or ""
    lines = [l.strip() for l in t.split("\n")]
    for j, l in enumerate(lines):
        if re.match(r"Product\s+Description", l, re.I):
            # value may be tacked onto the label line itself
            inline = l.split(":", 1)[1].strip() if ":" in l else ""
            if inline and not _is_chrome(inline):
                return _clean_desc(inline)
            # else scan downward for the first non-chrome line
            for k in range(j + 1, min(j + 8, len(lines))):
                if not _is_chrome(lines[k]):
                    return _clean_desc(lines[k])
            break
    # Last resort: a recognizable strain token anywhere on the page.
    m2 = re.search(r"(SCOTT'?S\s+OG[#\s\d\-]*)", t, re.I)
    if m2:
        return _clean_desc(m2.group(1))
    return ""


def _clean_desc(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip().strip(":").strip()


def _panel(text: str) -> str:
    t = (text or "").lower()
    for key, label in (("heavy metal", "Heavy Metals"), ("terpene", "Terpenes"),
                       ("pesticide", "Pesticides"), ("residual solvent", "Residual Solvents"),
                       ("cannabinoid", "Cannabinoids"), ("potency", "Potency"),
                       ("aerobic", "Microbial"), ("yeast", "Microbial")):
        if key in t:
            return label
    return "?"


# ---------------------------------------------------------------------------
# Page segmentation
# ---------------------------------------------------------------------------

def segment_pages(text: str) -> List[str]:
    """Best-effort split of concatenated COA text back into per-page chunks.

    Prefer passing a real per-page list to the higher-level functions; this is
    the fallback for when only the joined text survives. Splits on the recurring
    Northeast-Labs page-top header; if that anchor isn't present, returns the
    whole text as one page."""
    t = text or ""
    starts = [m.start() for m in _PAGE_TOP.finditer(t)]
    if len(starts) < 2:
        return [t] if t.strip() else []
    # Capture any preamble (cover letter) before the first header as its own chunk.
    bounds = ([0] if starts[0] > 0 else []) + starts + [len(t)]
    bounds = sorted(set(bounds))
    pages = [t[bounds[i]:bounds[i + 1]] for i in range(len(bounds) - 1)]
    return [p for p in pages if p.strip()]


# ---------------------------------------------------------------------------
# Product grouping
# ---------------------------------------------------------------------------

def _page_identity(page_text: str) -> Dict:
    return {
        "lab_id": lab_id(page_text),
        "lab_report_no": lab_report_no(page_text),
        "product_description": product_description(page_text),
        "sample_id": sample_id(page_text),
        "batch": batch_id(page_text),
        "test_date": test_date(page_text),
        "registration_numbers": registration_numbers(page_text),
        "panel": _panel(page_text),
        "page_of": (lambda m: (int(m.group(1)), int(m.group(2))) if m else None)(_PAGE_OF.search(page_text or "")),
        "text": page_text,
    }


def analyze_document(text=None, pages: Optional[List[str]] = None) -> Dict:
    """Map a (possibly multi-product) COA document.

    Pass ``pages`` (a per-page text list) when available — it is the reliable
    input. Otherwise pass ``text`` and it will be segmented heuristically.

    Returns::

        {
          "n_pages": int,
          "products": [ {lab_id, lab_report_no, product_description,
                         panels:[...], page_indices:[...], text:str}, ... ],
          "n_products": int,
          "is_multi_product": bool,
          "signal": "lab_id" | "product_description" | "mmbr" | "",
          "layout": "single" | "multi_per_page" | "single_multi_panel" | "unknown",
        }
    """
    if pages is None:
        pages = segment_pages(text or "")
    idents = [_page_identity(p) for p in pages]

    # Group pages into products. Primary key = Lab ID; pages with no Lab ID and
    # no product description are header/cover chrome and attach to nothing.
    groups: "Dict[str, Dict]" = {}
    order: List[str] = []
    for idx, ident in enumerate(idents):
        key = ident["lab_id"] or (ident["product_description"].upper() if ident["product_description"] else "")
        if not key:
            continue
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "lab_id": ident["lab_id"],
                "lab_report_no": ident["lab_report_no"],
                "product_description": ident["product_description"],
                "sample_id": ident["sample_id"],
                "batch": ident["batch"],
                "test_date": ident["test_date"],
                "registration_numbers": list(ident["registration_numbers"]),
                "panels": [],
                "page_indices": [],
                "_texts": [],
            }
            order.append(key)
        if not g["product_description"] and ident["product_description"]:
            g["product_description"] = ident["product_description"]
        if not g["lab_report_no"] and ident["lab_report_no"]:
            g["lab_report_no"] = ident["lab_report_no"]
        for fld in ("sample_id", "batch", "test_date"):
            if not g[fld] and ident[fld]:
                g[fld] = ident[fld]
        for rn in ident["registration_numbers"]:
            if rn not in g["registration_numbers"]:
                g["registration_numbers"].append(rn)
        if ident["panel"] != "?" and ident["panel"] not in g["panels"]:
            g["panels"].append(ident["panel"])
        g["page_indices"].append(idx)
        g["_texts"].append(ident["text"])

    products = []
    for n, key in enumerate(order):
        g = groups[key]
        products.append({
            "block_id": g["lab_id"] or g["sample_id"] or (g["product_description"].upper() if g["product_description"] else "") or f"block{n}",
            "lab_id": g["lab_id"],
            "lab_report_no": g["lab_report_no"],
            "product_description": g["product_description"],
            "sample_id": g["sample_id"],
            "batch": g["batch"],
            "test_date": g["test_date"],
            "registration_numbers": g["registration_numbers"],
            "panels": g["panels"],
            "page_indices": g["page_indices"],
            "text": "\n".join(g["_texts"]),
        })

    n_products = len(products)
    distinct_descs = {p["product_description"].upper() for p in products if p["product_description"]}
    mmbr = {m.group(0).upper().replace(" ", "") for m in _MMBR.finditer(text or "\n".join(pages))}

    signal = ""
    if n_products >= 2:
        signal = "lab_id"
    elif len(distinct_descs) >= 2:
        signal = "product_description"
    elif len(mmbr) >= 2:
        signal = "mmbr"

    is_multi = (n_products >= 2) or (len(distinct_descs) >= 2) or (len(mmbr) >= 2)

    if n_products <= 1:
        layout = "single" if not is_multi else "unknown"
    else:
        # Multi-page with distinct Lab IDs that differ only by suffix on the same
        # base report = the one-product-per-page layout.
        bases = {p["lab_id"].rsplit("-", 1)[0] for p in products if p["lab_id"]}
        layout = "multi_per_page" if bases else "unknown"

    return {
        "n_pages": len(pages),
        "products": products,
        "n_products": n_products,
        "is_multi_product": is_multi,
        "signal": signal,
        "mmbr_regs": sorted(mmbr),
        "layout": layout,
    }


# ---------------------------------------------------------------------------
# Per-product isolation (the splitter, with a route-to-review guardrail)
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _desc_specificity(desc: str) -> Optional[str]:
    """The distinguishing suffix of a product description, e.g. the "#2" / "#27-1"
    in "Scott's OG #2". Returns None if the description carries no unit marker."""
    m = re.search(r"#\s*([0-9]+(?:\s*[-]\s*[0-9]+)?)", desc or "")
    return re.sub(r"\s+", "", m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Columnar OCR repair — 2015-era Northeast Labs tables (and similar) put each
# analyte's label and value in SEPARATE columns, which Apple Vision OCR reads as
# "all labels, then all values, then all statuses" (label and value on different
# lines). The row parser then misses them. This re-pairs label[i] with value[i]
# (and status[i]) and appends same-line rows the existing parser can read.
# CONSERVATIVE: only emits when the value count EXACTLY matches the label count
# (mis-alignment could attach the wrong value to an analyte — worse than missing
# it), and only ADDS rows (never deletes the original text).
# ---------------------------------------------------------------------------
_RESULT_UNITS = re.compile(r"^\s*Result\s+Units?\s*$", re.I)
_PANEL_TITLE = re.compile(
    r"^\s*(Parameter|HEAVY\s+METALS|CANNABINOIDS|TERPENE|PESTICIDE|RESIDUAL\s+SOLVENT|"
    r"MICROB|MYCOTOXIN|FOREIGN\s+MATTER|WATER\s+ACTIVITY|MOISTURE|PATHOGEN)", re.I)
_STATUS_LINE = re.compile(r"^\s*(PASS|FAIL|Not\s+Detected|N/?D)\s*$", re.I)
_AFTER_BOUNDARY = re.compile(
    r"^\s*(METHODS|Comments|Approved|Recommended|Limits|LIMITS|Daily\s+Dose|Body\s+Weight|"
    r"Page\s+\d|Northeast\s+Laborator|\*|RECOMMENDED)", re.I)


def _is_value_line(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    if re.search(r"\d", s):
        return True
    if s[0] in "<—-":
        return True
    if re.match(r"(Not\s+Detected|ND)\b", s, re.I):
        return True
    return False


# Repair is restricted to the MICROBIAL / PATHOGEN safety panel — those labels parse cleanly from a
# re-paired "label value status" row. Heavy-metal rows misread garbled OCR units (e.g. "<0.0005 4g/kg"
# -> a spurious "4"), and cannabinoid rows can't map all acid forms (e.g. "THCAr") so they understate
# total THC. Emitting a WRONG safety/potency value is worse than leaving it for review, so we only
# reconstruct the microbial/pathogen panel here.
_MICRO_PATHOGEN_LABEL = re.compile(
    r"(aerobic|yeast|mold|coliform|bile[\s-]*tolerant|gram[\s-]*negative|"
    r"e\.?\s*coli|escherichia|salmonella|enterobacter|aspergillus|"
    r"total\s+plate|pathogen|\bstec\b|shiga)", re.I)


def repair_columnar_layout(text: str) -> str:
    """Re-pair label/value columns in 2015-era columnar OCR tables and append the
    reconstructed same-line rows so the row parser can read them. Returns the text
    unchanged if no such table is confidently found."""
    t = text or ""
    if "result unit" not in t.lower():        # cheap pre-check (the column header is "Result Units")
        return t
    lines = t.split("\n")
    rows = []
    for i, ln in enumerate(lines):
        if not _RESULT_UNITS.match(ln):
            continue
        # labels = the contiguous analyte lines immediately ABOVE "Result Units"
        labels = []
        j = i - 1
        while j >= 0:
            s = lines[j].strip()
            if not s:
                j -= 1
                continue
            if _PANEL_TITLE.match(s):
                break
            if _is_chrome(s) or _is_value_line(s) or _STATUS_LINE.match(s):
                break
            labels.append(s)
            j -= 1
            if len(labels) > 25:
                break
        labels.reverse()
        if not labels:
            continue
        # values = the next lines below "Result Units" that look like values
        vals = []
        k = i + 1
        while k < len(lines) and len(vals) < len(labels):
            s = lines[k].strip()
            if not s:
                k += 1
                continue
            if _AFTER_BOUNDARY.match(s) or _STATUS_LINE.match(s):
                break
            if _is_value_line(s):
                vals.append(s)
                k += 1
            else:
                break
        # CONSERVATIVE GUARD: only pair when counts match exactly
        if len(vals) != len(labels):
            continue
        # optional statuses (PASS/FAIL), exactly one per analyte
        stats = []
        while k < len(lines) and len(stats) < len(labels):
            s = lines[k].strip()
            if not s:
                k += 1
                continue
            if _STATUS_LINE.match(s):
                stats.append(s)
                k += 1
            else:
                break
        use_stats = len(stats) == len(labels)
        for n, lab in enumerate(labels):
            if not _MICRO_PATHOGEN_LABEL.search(lab):   # safety panel only (see note above)
                continue
            row = f"{lab} {vals[n]}"
            if use_stats:
                row += f" {stats[n]}"
            rows.append(row)
    if rows:
        return t + "\n\n[COLUMNAR-REPAIRED ROWS]\n" + "\n".join(rows)
    return t


def _norm_reg(s: str) -> str:
    """Normalize a registration number for comparison (strip spaces/punct, upper)."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def extract_blocks(text=None, pages: Optional[List[str]] = None) -> List[Dict]:
    """The structured per-product blocks of a (possibly multi-product) COA document.
    Each block carries its own identifiers + text (see ``analyze_document``)."""
    return analyze_document(text=text, pages=pages)["products"]


def match_block(blocks: List[Dict], *, registration_number: str = "", product_name: str = "",
                lab_id: str = "", sample_id: str = "", batch: str = "",
                test_date: str = "") -> Tuple[Optional[Dict], float, str, str]:
    """Match a registry record to EXACTLY ONE product block, by strongest identifier first.
    Returns ``(block, confidence, reason, strategy)`` or ``(None, 0.0, reason, "")`` when the
    record cannot be uniquely tied to one block — the caller MUST then route to manual review
    (never guess; a wrong block = cross-attribution).

    A STRONG identifier that matches MORE THAN ONE block is treated as genuinely ambiguous and
    fails immediately (we do not fall back to a weaker heuristic that might pick the wrong one).
    """
    if not blocks:
        return (None, 0.0, "no product blocks", "")

    def _uniq(pred):
        hits = [b for b in blocks if pred(b)]
        return hits[0] if len(hits) == 1 else (None if not hits else False)  # False = ambiguous

    # 1) Laboratory ID # (strongest — the lab's own per-sample key)
    tid = _norm_reg(_lab_id_norm(lab_id)) if lab_id else ""
    if tid:
        h = _uniq(lambda b: _norm_reg(b.get("lab_id", "")) == tid)
        if h: return (h, 1.0, f"matched Laboratory ID# {lab_id}", "lab_id")
        if h is False: return (None, 0.0, f"Laboratory ID# {lab_id} matched multiple blocks", "")
    # 2) CT registration number (MMBR) present in the block
    treg = _norm_reg(registration_number)
    if treg:
        h = _uniq(lambda b: any(_norm_reg(r) == treg for r in b.get("registration_numbers", [])))
        if h: return (h, 0.98, f"matched registration number {registration_number}", "registration_number")
        if h is False: return (None, 0.0, f"registration number {registration_number} matched multiple blocks", "")
    # 3) Sample ID
    if sample_id:
        h = _uniq(lambda b: b.get("sample_id", "") and _norm_reg(b["sample_id"]) == _norm_reg(sample_id))
        if h: return (h, 0.97, f"matched sample ID {sample_id}", "sample_id")
        if h is False: return (None, 0.0, f"sample ID {sample_id} matched multiple blocks", "")
    # 4) Batch / lot
    if batch:
        h = _uniq(lambda b: b.get("batch", "") and _norm_reg(b["batch"]) == _norm_reg(batch))
        if h: return (h, 0.95, f"matched batch {batch}", "batch")
        if h is False: return (None, 0.0, f"batch {batch} matched multiple blocks", "")
    # 5) Product description, exact (normalized) — disambiguate residual ties by test date
    tnorm = _norm(product_name)
    if tnorm:
        exact = [b for b in blocks if _norm(b.get("product_description", "")) == tnorm]
        if len(exact) == 1:
            return (exact[0], 0.9, "matched product description (exact)", "description")
        if len(exact) > 1 and test_date:
            td = [b for b in exact if b.get("test_date") and _same_date(b["test_date"], test_date)]
            if len(td) == 1:
                return (td[0], 0.9, "matched product description + test date", "description+date")
            return (None, 0.0, "product description matched multiple blocks (test date did not disambiguate)", "")
        if len(exact) > 1:
            return (None, 0.0, "product description matched multiple blocks", "")
        # 6) Distinguishing unit marker (#N) when base names tie (e.g. "Scott's OG #4")
        tgt_unit = _desc_specificity(product_name) or _desc_specificity(batch)
        if tgt_unit:
            unit_hit = [b for b in blocks if _desc_specificity(b.get("product_description", "")) == tgt_unit]
            if len(unit_hit) == 1:
                return (unit_hit[0], 0.85, f"matched unit marker #{tgt_unit}", "unit_marker")
            if len(unit_hit) > 1:
                return (None, 0.0, f"unit marker #{tgt_unit} matched multiple blocks", "")
        # 7) Substring containment, only if unambiguous
        contains = [b for b in blocks if tnorm in _norm(b.get("product_description", ""))]
        if len(contains) == 1:
            return (contains[0], 0.7, "matched product description (contains)", "description_contains")

    return (None, 0.0,
            f"ambiguous: {len(blocks)} products in document, record "
            f"'{product_name or registration_number or lab_id or '?'}' did not uniquely match one block",
            "")


def _lab_id_norm(s: str) -> str:
    return lab_id(s) or (s or "")


def _same_date(a: str, b: str) -> bool:
    """Loose date equality across ISO / US formats (digit-set comparison)."""
    da = sorted(re.findall(r"\d+", a or ""))
    db = sorted(re.findall(r"\d+", b or ""))
    return bool(da) and da == db


def isolate_product(text=None, pages: Optional[List[str]] = None,
                    target_name: str = "", target_lab_id: str = "", target_batch: str = "",
                    target_registration_number: str = "", target_sample_id: str = "",
                    target_test_date: str = "") -> Tuple[Optional[str], float, str]:
    """Return ``(block_text, confidence, reason)`` for the product matching the registry record,
    or ``(None, 0.0, reason)`` when it cannot be isolated confidently (caller must route to
    manual review). Thin wrapper over ``match_block`` that returns the matched block's TEXT."""
    doc = analyze_document(text=text, pages=pages)
    products = doc["products"]
    # 0 or 1 resolvable blocks => nothing to split; parse the WHOLE document. The common single-product
    # case must NOT be suppressed even if a weak signal fired (e.g. a COA mentioning 2 reg numbers).
    if doc["n_products"] <= 1:
        if products:
            return (products[0]["text"], 1.0, "single-product document")
        whole = text if text is not None else "\n".join(pages or [])
        return (whole, 1.0, "single-product document")
    block, conf, reason, _strategy = match_block(
        products, registration_number=target_registration_number, product_name=target_name,
        lab_id=target_lab_id, sample_id=target_sample_id, batch=target_batch, test_date=target_test_date)
    if block is not None:
        return (block["text"], conf, reason)
    return (None, 0.0, reason + " -> route to manual review")


if __name__ == "__main__":  # tiny smoke test against a cached OCR dump
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "_ferrarese_ocr.json"
    pages = json.load(open(path))
    d = analyze_document(pages=pages)
    print(f"pages={d['n_pages']} products={d['n_products']} "
          f"multi={d['is_multi_product']} signal={d['signal']} layout={d['layout']}")
    for p in d["products"]:
        print(f"  {p['lab_id']:14} {p['lab_report_no']:9} "
              f"{p['product_description']:22} panels={p['panels']} pages={p['page_indices']}")
