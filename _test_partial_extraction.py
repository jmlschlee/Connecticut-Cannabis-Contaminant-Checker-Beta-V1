#!/usr/bin/env python3
"""Acceptance test for the PARTIAL-EXTRACTION false-clean guard (highest-risk integrity gap).

The danger: a COA whose text PRINTS a safety panel (so the product WAS tested for it) but whose parser
produced NOTHING for that panel is currently treated as "usable" (because some OTHER panel — e.g.
potency — parsed) and published as a confident clean. A real exceedance the parser dropped then reads as
"not reported" instead of a finding. This proves the guard:

  1. `_missing_safety_panels(p, text)` detects a printed-but-unparsed safety panel (and does NOT
     false-fire on a parsed panel, empty text, or a panel the COA never printed).
  2. cached_or_v15: an incomplete cached HIT is re-pulled LIVE when online; a complete live read WINS.
  3. cached_or_v15 OFFLINE (or after an unresolved live re-read): the record is HELD for review
     (`_safety_panel_incomplete`, status -> Needs Manual Review) — never returned as a silent clean.
  4. A complete + plausible cached HIT is still trusted with NO re-read (happy path unchanged).

Run:  python3 _test_partial_extraction.py
"""
import sys
import cannascope_ct_v17_src as cc
import cannascope_ct_v4 as v4
import cannascope_ct_v5 as v5

_fails = []
def check(cond, msg):
    print(("ok  " if cond else "FAIL") + "  " + msg)
    if not cond:
        _fails.append(msg)


def _prod(reg="X", analytes=None, cannabinoids=None, pesticides="", solvents=""):
    p = v5.ProductV5()
    p.registration_number = reg
    p.report_url = "http://x/" + reg + ".pdf"
    p.analytes = analytes or {}
    p.cannabinoids = cannabinoids or {}
    p.pesticides = pesticides
    p.solvents = solvents
    return p


MICRO_TEXT = ("ACME Labs COA\nProduct: Blue Dream Flower\nCANNABINOIDS\nTotal THC 24.0 %\n"
              "Total Yeast & Mold Count\nTotal Aerobic Microbial Count\nResult Units\n")
METAL_TEXT = "ACME Labs COA\nHEAVY METALS\nLead\nCadmium\nMercury\nResult Units\nTotal THC 18 %\n"

# ---- 1. detection ----
# microbial panel PRINTED, but no tymc/aerobic parsed (only potency) -> missing
inc = _prod(cannabinoids={"total_thc": {"value": 24.0}})
miss = cc._missing_safety_panels(inc, MICRO_TEXT)
check("microbial" in miss, f"printed-but-unparsed microbial panel is detected (got {miss})")
check("pathogens" not in miss, "a panel the COA never printed is NOT flagged")

# microbial panel PRINTED and parsed -> not missing
comp = _prod(analytes={"tymc": {"value": 1200.0, "raw": "1200"}}, cannabinoids={"total_thc": {"value": 24.0}})
check("microbial" not in cc._missing_safety_panels(comp, MICRO_TEXT),
      "a parsed microbial panel is NOT flagged as missing")

# heavy metals printed, none parsed -> missing; bare 'as'/noise does not over-fire
check("heavy_metals" in cc._missing_safety_panels(_prod(cannabinoids={"total_thc": {"value": 18.0}}), METAL_TEXT),
      "printed-but-unparsed heavy-metals panel is detected")
check(cc._missing_safety_panels(_prod(analytes={"lead": {"value": 0.1, "raw": "0.1"}}), METAL_TEXT) == [],
      "a parsed heavy-metals panel is NOT flagged")

# empty / no-text -> nothing claimed
check(cc._missing_safety_panels(inc, "") == [], "empty text yields no missing-panel claims")
# a COA that prints NO safety panels at all (potency-only doc) -> nothing missing
check(cc._missing_safety_panels(inc, "Potency only\nTotal THC 24 %\n") == [],
      "a potency-only COA (no safety panel printed) claims nothing missing")


# ---- cached_or_v15 wiring with a fake cache + controlled live ----
class FakeCache:
    def __init__(self, rows): self.rows = dict(rows)
    def fresh_row(self, p): return self.rows.get(v4.coa_key(p))
    def rehydrate(self, row, watch): return row
    def put(self, p, **kw): self.rows[v4.coa_key(p)] = p


def _incomplete_cached():
    p = _prod(reg="INC", cannabinoids={"total_thc": {"value": 24.0}})   # potency parsed...
    p._missing_safety_panels = ["microbial"]                            # ...but microbial printed-unparsed
    return p

WATCH = 80.0
_orig_pp = cc.process_product

# 2. ONLINE: incomplete cached HIT -> re-pulled live; complete live WINS
fake = FakeCache({"INC": _incomplete_cached()})
live_complete = _prod(reg="INC", analytes={"tymc": {"value": 1200.0, "raw": "1200"}},
                      cannabinoids={"total_thc": {"value": 24.0}})
live_complete._missing_safety_panels = []
cc.process_product = lambda p, s, w: live_complete
try:
    out = cc.cached_or_v15(_prod(reg="INC"), None, WATCH, fake, allow_network=True)
finally:
    cc.process_product = _orig_pp
check(out is live_complete, "incomplete cached HIT is re-pulled LIVE and the complete live read wins")
check(fake.rows["INC"] is live_complete, "LIVE WINS: cache row corrected to the complete live read")

# 3a. OFFLINE: incomplete cached HIT -> HELD for review (never a silent clean), no re-read
fake2 = FakeCache({"INC": _incomplete_cached()})
def _boom(p, s, w):
    raise AssertionError("process_product must NOT be called when offline")
cc.process_product = _boom
try:
    out = cc.cached_or_v15(_prod(reg="INC"), None, WATCH, fake2, allow_network=False)
finally:
    cc.process_product = _orig_pp
check(getattr(out, "_safety_panel_incomplete", False) is True,
      "offline incomplete HIT is marked _safety_panel_incomplete (held)")
check(out._coa_status == cc.MATCH_MANUAL, "offline incomplete HIT is routed to Needs Manual Review")
check("microbial" in (getattr(out, "parse_note", "") or ""), "the hold note names the unparsed panel")

# 3b. ONLINE but live STILL incomplete -> live wins AND is held (not published clean)
fake3 = FakeCache({"INC": _incomplete_cached()})
live_still_inc = _prod(reg="INC", cannabinoids={"total_thc": {"value": 24.0}})
live_still_inc._missing_safety_panels = ["microbial"]
cc.process_product = lambda p, s, w: live_still_inc
try:
    out = cc.cached_or_v15(_prod(reg="INC"), None, WATCH, fake3, allow_network=True)
finally:
    cc.process_product = _orig_pp
check(getattr(out, "_safety_panel_incomplete", False) is True,
      "an unresolved live re-read is HELD (still missing a printed safety panel)")

# 4. happy path: a complete + plausible cached HIT is trusted with NO re-read
fake4 = FakeCache({"OK": _prod(reg="OK", analytes={"tymc": {"value": 1200.0, "raw": "1200"}})})
# (no _missing_safety_panels attr at all -> treated as complete)
cc.process_product = _boom
try:
    out = cc.cached_or_v15(_prod(reg="OK"), None, WATCH, fake4, allow_network=True)
finally:
    cc.process_product = _orig_pp
check(out is fake4.rows["OK"] and out.analytes.get("tymc", {}).get("value") == 1200.0,
      "a complete+plausible cached HIT is returned untouched (no needless re-read)")

print()
if _fails:
    print(f"{len(_fails)} FAILED"); sys.exit(1)
print("ALL PASSED")
