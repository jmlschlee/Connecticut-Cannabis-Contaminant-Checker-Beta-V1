#!/usr/bin/env python3
"""Regression tests for cannascope_multiproduct against a CONFIRMED real 2015
multi-product COA (DearFerrarese.pdf -> _ferrarese_ocr.json fixture).

The fixture is the OCR (Apple Vision) of all 18 pages. The document is:
  - 1 cover letter + report N1562734: ONE product (Scott's OG #031715), 6 panels
    on 6 pages, all sharing Laboratory ID# 1562734-07            (Layout A)
  - report N1562829: 5 products (Scott's OG #1..#5), one per page, Lab IDs -01..-05
  - report N1562949: 6 products (#27, #27-1, #26, #26-1, #33, #33-1), Lab IDs -01..-06
  => 12 distinct products total.

Run:  python3 _test_multiproduct.py
"""
import json
import os
import sys

import cannascope_multiproduct as mp

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ferrarese_ocr.json")
PAGES = json.load(open(FIX))

_fails = []


def check(cond, msg):
    print(("ok  " if cond else "FAIL") + "  " + msg)
    if not cond:
        _fails.append(msg)


# ---- detection / grouping (reliable per-page input) -------------------------
d = mp.analyze_document(pages=PAGES)
check(d["is_multi_product"] is True, "detects multi-product")
check(d["n_products"] == 12, f"finds 12 products (got {d['n_products']})")
check(d["signal"] == "lab_id", f"signal is lab_id (got {d['signal']})")
check(d["layout"] == "multi_per_page", f"layout is multi_per_page (got {d['layout']})")

prod0 = d["products"][0]
check(prod0["lab_id"] == "1562734-07", "first product Lab ID = 1562734-07")
check(len(prod0["page_indices"]) == 7,
      f"single-product report COMBINES its 7 panel pages (got {len(prod0['page_indices'])})")
check("Heavy Metals" in prod0["panels"] and "Cannabinoids" in prod0["panels"],
      "first product carries multiple panels (Heavy Metals + Cannabinoids)")

ids = [p["lab_id"] for p in d["products"]]
check(ids.count("1562829-03") == 1 and "1562829-05" in ids, "Layout-B products kept SEPARATE by Lab ID")
descs = " | ".join(p["product_description"] for p in d["products"])
check("SCOTT'S OG #2" in descs.upper() and "#5" in descs, "per-page product descriptions recovered")

# ---- detection on concatenated-text fallback --------------------------------
d2 = mp.analyze_document(text="\n".join(PAGES))
check(d2["n_products"] == 12, f"concat-text fallback also finds 12 (got {d2['n_products']})")

# ---- isolation guardrail ----------------------------------------------------
blk, conf, _ = mp.isolate_product(pages=PAGES, target_lab_id="1562829-03")
check(blk is not None and conf == 1.0, "isolates by exact Laboratory ID#")

blk, conf, reason = mp.isolate_product(pages=PAGES, target_name="Scott's OG")
check(blk is None and conf == 0.0, "GENERIC base name -> ambiguous -> route to review (no cross-attribution)")
check("manual review" in reason, "ambiguous case explains route-to-review")

blk, conf, _ = mp.isolate_product(pages=PAGES, target_name="Scott's OG #4")
check(blk is not None and "SCOTT'S OG #4" in blk.upper(), "distinct name '#4' isolates its block")

blk, conf, _ = mp.isolate_product(pages=PAGES, target_name="Blue Dream")
check(blk is None, "non-existent product -> route to review")

# single-product doc returns whole text
blk, conf, _ = mp.isolate_product(pages=PAGES[1:7], target_name="whatever")
check(blk is not None and conf == 1.0, "single-product doc returns whole text regardless of name")

# ---- no false positive on a normal single-page COA --------------------------
plain = ("ACME LABS Certificate of Analysis\nProduct: Blue Dream Flower\n"
         "Total Yeast & Mold 1200 CFU/g PASS\nLead <0.1 ppm PASS\n")
dp = mp.analyze_document(text=plain)
check(dp["is_multi_product"] is False, "normal single COA NOT flagged multi-product")

# ---- a single-product COA that merely MENTIONS 2 registration numbers must NOT be suppressed ----
# (regression: weak mmbr signal with <2 resolvable blocks => parse the whole doc, never drop findings)
twomm = ("ACME Labs COA\nProduct: Blue Dream Flower MMBR.0011111\nfacility MMBR.0022222\n"
         "Total Yeast & Mold 1,200 CFU/g PASS\nLead <0.1 ppm PASS\n")
blk, conf, _ = mp.isolate_product(text=twomm, target_name="Blue Dream Flower")
check(blk == twomm and conf == 1.0,
      "single-product COA mentioning 2 reg numbers -> parses whole doc (NOT suppressed)")

# ---- isolate on text with zero recognizable blocks returns the whole text, not None ----
blk, conf, _ = mp.isolate_product(text="random text no products here", target_name="x")
check(blk is not None and conf == 1.0, "unrecognized text -> whole doc (never a false suppress)")

# ---- columnar OCR repair (2015-era label/value-in-separate-columns) ----
# microbial table where label and value are on different lines (Apple Vision column read order)
col = ("Parameter\nTotal Aerobic Microbial Count\nTotal Yeast & Mold Count\nResult Units\n"
       "2,500,000 per gram\n110,000 per gram\nFAIL\nFAIL\nRecommended Limits *\n100,000\n10,000\n")
rep = mp.repair_columnar_layout(col)
check("Total Aerobic Microbial Count 2,500,000 per gram FAIL" in rep, "columnar repair re-pairs aerobic label+value")
check("Total Yeast & Mold Count 110,000 per gram FAIL" in rep, "columnar repair re-pairs yeast&mold label+value")
# heavy metals must NOT be repaired (garbled OCR units cause misreads -> safety panel only)
metals = ("Parameter\nArsenic, Total\nLead, Total\nResult Units\n<0.0005 4g/kg\n<0.002 Mg/kg\nPASS\nPASS\nLimits\n<0.14\n<0.29\n")
check("[COLUMNAR-REPAIRED ROWS]" not in mp.repair_columnar_layout(metals), "columnar repair SKIPS heavy metals (avoids unit-garble misreads)")
# mismatched label/value counts -> no rows (conservative, never mis-pairs)
bad = ("Parameter\nTotal Aerobic Microbial Count\nTotal Yeast & Mold Count\nResult Units\n2,500,000 per gram\nFAIL\n")
check("[COLUMNAR-REPAIRED ROWS]" not in mp.repair_columnar_layout(bad), "columnar repair emits nothing when counts mismatch")
# modern COA (no 'Result Units' column header) untouched
modern2 = "ACME COA\nTotal Yeast & Mold 1200 CFU/g PASS\n"
check(mp.repair_columnar_layout(modern2) == modern2, "columnar repair is a no-op on modern COAs")

print()
if _fails:
    print(f"{len(_fails)} FAILED")
    sys.exit(1)
print("ALL PASSED")
