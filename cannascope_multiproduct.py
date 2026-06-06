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
                "panels": [],
                "page_indices": [],
                "_texts": [],
            }
            order.append(key)
        if not g["product_description"] and ident["product_description"]:
            g["product_description"] = ident["product_description"]
        if not g["lab_report_no"] and ident["lab_report_no"]:
            g["lab_report_no"] = ident["lab_report_no"]
        if ident["panel"] != "?" and ident["panel"] not in g["panels"]:
            g["panels"].append(ident["panel"])
        g["page_indices"].append(idx)
        g["_texts"].append(ident["text"])

    products = []
    for key in order:
        g = groups[key]
        products.append({
            "lab_id": g["lab_id"],
            "lab_report_no": g["lab_report_no"],
            "product_description": g["product_description"],
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


def isolate_product(text=None, pages: Optional[List[str]] = None,
                    target_name: str = "", target_lab_id: str = "",
                    target_batch: str = "") -> Tuple[Optional[str], float, str]:
    """Return ``(block_text, confidence, reason)`` for the product matching the
    registry record, or ``(None, 0.0, reason)`` when it cannot be isolated
    confidently — in which case the caller MUST route to manual review rather
    than extract (extracting the wrong block = cross-attribution).

    Matching precedence (most reliable first):
      1. exact Laboratory ID # (if the registry record carries one),
      2. exact/normalized Product Description,
      3. distinguishing unit marker (the "#N" suffix) when the base names tie,
      4. otherwise -> ambiguous, return None.
    """
    doc = analyze_document(text=text, pages=pages)
    products = doc["products"]

    # 0 or 1 resolvable product blocks => nothing to split; parse the WHOLE document. This is the
    # common case (an ordinary single-product COA), and it must NOT be suppressed even if a weak
    # multi-product signal fired (e.g. a COA that merely mentions 2 registration numbers): suppressing
    # a legitimate single-product COA would drop real findings.
    if doc["n_products"] <= 1:
        if products:
            return (products[0]["text"], 1.0, "single-product document")
        whole = text if text is not None else "\n".join(pages or [])
        return (whole, 1.0, "single-product document")

    # --- multi-product: must pin the registry record to exactly one block ---
    tgt_id = lab_id(target_lab_id) if target_lab_id else ""
    if tgt_id:
        hit = [p for p in products if p["lab_id"] == tgt_id]
        if len(hit) == 1:
            return (hit[0]["text"], 1.0, f"matched Laboratory ID# {tgt_id}")

    tnorm = _norm(target_name)
    if tnorm:
        exact = [p for p in products if _norm(p["product_description"]) == tnorm]
        if len(exact) == 1:
            return (exact[0]["text"], 0.95, "matched product description (exact)")

        # Base-name ties (the Ferrarese case: every block is "Scott's OG #N").
        # Disambiguate ONLY if the registry record carries a unit marker that
        # uniquely identifies one block.
        tgt_unit = _desc_specificity(target_name) or _desc_specificity(target_batch)
        if tgt_unit:
            unit_hit = [p for p in products if _desc_specificity(p["product_description"]) == tgt_unit]
            if len(unit_hit) == 1:
                return (unit_hit[0]["text"], 0.85, f"matched unit marker #{tgt_unit}")

        # Substring containment, only if unambiguous.
        contains = [p for p in products if tnorm and tnorm in _norm(p["product_description"])]
        if len(contains) == 1:
            return (contains[0]["text"], 0.7, "matched product description (contains)")

    return (None, 0.0,
            f"ambiguous: {doc['n_products']} products in document, "
            f"registry record '{target_name or target_lab_id or '?'}' did not "
            f"uniquely match one block -> route to manual review")


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
