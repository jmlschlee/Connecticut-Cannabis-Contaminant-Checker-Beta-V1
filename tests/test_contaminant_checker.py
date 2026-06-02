#!/usr/bin/env python3
"""
Offline test suite for the Connecticut Cannabis Contaminant Checker.

These tests need NO internet — they feed synthetic COA text (matching the real
lab layouts) through the parsing + flagging logic and assert the result. They
guard the behaviors that were hard-won during development (column-order quirks,
unit handling, false-positive footnotes, etc.).

Run directly:      python tests/test_contaminant_checker.py
Or with pytest:    pytest -q
"""
import importlib.util
import os

# Load the single-file program by path (its filename isn't import-friendly).
_HERE = os.path.dirname(os.path.abspath(__file__))
_MOD = os.path.join(_HERE, "..", "cannascope_ct_v2.py")
_spec = importlib.util.spec_from_file_location("cccc", _MOD)
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)


def _run(text, dosage="Usable Marijuana", watch=10000):
    """Parse + flag a synthetic COA, return the Product."""
    p = A.Product(dosage_form=dosage)
    p.overall_result = A.find_overall_result(text)
    A.parse_analytes(text, p)
    A.apply_flags(p, text, watch)
    return p


# --- microbiological zero-tolerance -----------------------------------------
def test_ecoli_detected_is_red():
    p = _run("E. coli Detected 1 Not Detected Fail\nTotal Yeast & Mold 200 100000\nOverall: Fail")
    assert any(f.startswith("PROHIBITED_DETECTED") for f in p.flags)
    assert A.product_severity(p) == "RED"

def test_aspergillus_real_row_detected_is_red():
    p = _run("Aspergillus flavus Detected in 1g Not Detected Fail\nTotal Yeast & Mold 200 100000 Pass")
    assert A.product_severity(p) == "RED"

def test_aspergillus_method_footnote_is_not_a_detection():
    # The label appears only in a methodology footnote -> must NOT be "detected".
    txt = ("Total Yeast & Mold 100000 <100 Pass\n"
           "E. coli Not Detected in 1g Not Detected Pass\n"
           "Escherichia coli and Salmonella spp. are analyzed per CT-SOP-007. "
           "Aspergillus spp. are analyzed per CT-SOP-014. Viruses")
    p = _run(txt)
    assert p.analytes.get("aspergillus", {}).get("status") != "DETECTED"
    assert not any("PROHIBITED" in f for f in p.flags)


# --- yeast & mold column layouts + thresholds -------------------------------
def test_ym_limit_first_layout():
    p = _run("Total Yeast & Mold 100000 1400 Pass")
    assert p.analytes["tymc"]["value"] == 1400

def test_ym_result_first_layout():
    p = _run("Total Yeast & Mold Count (cfu/g) 350 100,000 AOAC 2014.05")
    assert p.analytes["tymc"]["value"] == 350

def test_ym_over_watch_is_yellow():
    p = _run("Total Yeast & Mold 100000 45000 Pass")
    assert A.product_severity(p) == "YELLOW"

def test_ym_over_legal_limit_is_red():
    p = _run("Total Yeast & Mold Count (cfu/g) 250,000 100,000")
    assert any(f.startswith("OVER_CT_LIMIT") for f in p.flags)
    assert A.product_severity(p) == "RED"


# --- heavy metals: unit-safe, COA-limit-based -------------------------------
def test_arsenic_within_limit_is_orange_not_red():
    # 182.282 ug/kg under the COA's 200 ug/kg limit -> detected, ORANGE, NOT red.
    p = _run("Heavy Metals Pass\nug/kg ug/kg ug/kg ug/kg\n"
             "Arsenic 0.236 0.500 200.000 182.282 Pass\nTotal Yeast & Mold 100000 300 Pass")
    e = p.analytes["arsenic"]
    assert abs(e["value"] - 182.282) < 0.01 and e["limit"] == 200.0
    assert e.get("unit") == "µg/kg"
    assert A.product_severity(p) == "ORANGE"
    assert not any(f.startswith("OVER_CT_LIMIT") for f in p.flags)

def test_arsenic_over_limit_is_red():
    p = _run("Heavy Metals\nArsenic 0.236 0.500 200.000 250 Fail\nTotal Yeast & Mold 100000 300 Pass")
    assert A.product_severity(p) == "RED"
    assert any("OVER_CT_LIMIT" in f and "Arsenic" in f for f in p.flags)


# --- mycotoxins: all aflatoxins scanned -------------------------------------
def test_aflatoxin_b1_over_limit_is_red():
    p = _run("Mycotoxins Pass\nAnalyte LOD LOQ Limit Results Status\n"
             "B1 0.0 1.0 20.0 25.0 Fail\nTotal Yeast & Mold 100000 300 Pass")
    assert any("OVER_CT_LIMIT" in f and "B1" in f for f in p.flags)
    assert A.product_severity(p) == "RED"

def test_aflatoxin_b1_detected_within_limit_is_orange():
    p = _run("Mycotoxins Pass\nB1 0.0 1.0 20.0 5.0 Pass\nTotal Yeast & Mold 100000 300 Pass")
    assert any("CONTAMINANT_DETECTED" in f and "B1" in f for f in p.flags)
    assert A.product_severity(p) == "ORANGE"


# --- residual solvents ------------------------------------------------------
def test_solvent_detected_is_yellow():
    p = _run("Residual Solvents Pass\nppm ppm ppm ppm\n"
             "Ethanol 1.0 5.0 5000 250 Pass\nTotal Yeast & Mold 100000 300 Pass",
             dosage="Vape Cartridge")
    assert any("SOLVENT_DETECTED" in f and "Ethanol" in f for f in p.flags)
    assert A.product_severity(p) == "YELLOW"

def test_solvent_over_limit_is_red():
    p = _run("Residual Solvents Fail\nppm ppm ppm ppm\nBenzene 0.1 0.5 2 9 Fail",
             dosage="Vape Cartridge")
    assert A.product_severity(p) == "RED"

def test_pass_fail_header_is_not_a_failure():
    # "Pass/Fail Pass" must not be read as a FAIL.
    assert A.panel_status("Pesticides Results Limits Methods\n"
                          "Per Sample Below Action Limits LC-MS\nPass/Fail Pass",
                          r"pesticides?") == "PASS"


# --- scope ------------------------------------------------------------------
def test_edibles_excluded_from_inhalable():
    assert A.is_inhalable(A.Product(dosage_form="Solid Marijuana Infused Edible")) is False

def test_vape_and_extract_included():
    assert A.is_inhalable(A.Product(dosage_form="Vape Cartridge")) is True
    assert A.is_inhalable(A.Product(dosage_form="Marijuana Extract for Inhalation")) is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}  {e}")
    print()
    if failed:
        print(f"{failed} of {len(fns)} TESTS FAILED")
        raise SystemExit(1)
    print(f"ALL TESTS PASSED ({len(fns)} checks)")
