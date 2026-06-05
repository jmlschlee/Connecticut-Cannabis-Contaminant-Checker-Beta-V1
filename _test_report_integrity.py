#!/usr/bin/env python3
"""Regression tests for CannaScope CT report integrity (defects P0/P1/P4 + the parse_date fix).

Run:  python3 _test_report_integrity.py [path/to/latest_report.pdf]
If no PDF is given, the rendering/version checks are skipped (logic tests still run).
Exit code 0 = all pass, 1 = a failure (so CI / the build can gate on it).
"""
import importlib.util, sys, os, re, glob

FAILS = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  — {detail}" if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)

# ---- load engine (v4) for parse_date, and the src module for count logic ----
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m)
    return m

HERE = os.path.dirname(os.path.abspath(__file__))
v4 = _load("cannascope_ct_v4", os.path.join(HERE, "cannascope_ct_v4.py"))

# ---- parse_date: the bug that made every dated standard "unverified" (ISO not parsed) ----
check("parse_date ISO YYYY-MM-DD", v4.parse_date("2025-07-02") == (2025, 7, 2), repr(v4.parse_date("2025-07-02")))
check("parse_date US MM/DD/YYYY", v4.parse_date("07/02/2025") == (2025, 7, 2))
check("parse_date US + time", v4.parse_date("03/14/2025 12:00:00 AM") == (2025, 3, 14))
check("parse_date garbage -> 0", v4.parse_date("nope") == (0, 0, 0))

# ---- P1 count invariant logic: flagged <= parsed <= reported_on <= window ----
src = _load("cannascope_ct_v15_src", os.path.join(HERE, "cannascope_ct_v15_src.py"))

class _P:  # minimal product stub
    def __init__(self, analytes=None, cannabinoids=None, pesticides="", solvents=""):
        self.analytes = analytes or {}; self.cannabinoids = cannabinoids or {}
        self.pesticides = pesticides; self.solvents = solvents

# Cache-path style products: analytes present, but NO _cat_present (the bug condition).
prods = [_P(analytes={"tymc": {"value": 100, "limit": 100000}, "arsenic": {"value": 5, "limit": 200}})
         for _ in range(50)]
present_tymc = src._present_count(prods, "tymc")
parsed_tymc = src.parsed_count(prods, "tymc")
check("P1 reported-on >= parsed on cache path (tymc)", present_tymc >= parsed_tymc,
      f"present={present_tymc} parsed={parsed_tymc}")
check("P1 reported-on counts all 50 tymc COAs", present_tymc == 50, f"present={present_tymc}")
check("P1 arsenic reported-on >= parsed", src._present_count(prods, "arsenic") >= src.parsed_count(prods, "arsenic"))
# a category with no data must be 0/0 (no inversion)
check("P1 empty category 0 reported-on", src._present_count(prods, "mycotoxins") == 0)

# ---- version single-source (P4): constants are consistent, no V15 in the script filename ----
check("P4 SCRIPT_FILE matches major version", src.SCRIPT_FILE == f"CannaScope_CT_V{src.SOFTWARE_VERSION.split('.')[0]}.py",
      src.SCRIPT_FILE)
check("P4 SCRIPT_FILE is V16 not V15", "V15" not in src.SCRIPT_FILE, src.SCRIPT_FILE)
check("P4 APP_NAME matches SOFTWARE_VERSION", src.SOFTWARE_VERSION in src.APP_NAME, src.APP_NAME)

# ---- regulatory ledger sanity (headline) ----
check("ledger has citations for all categories",
      all(k in src.CT_REG_CITATIONS for k in ("yeast_mold", "aerobic", "pathogens", "heavy_metals", "thc_potency")))
check("ledger citations carry a URL", all(c[1].startswith("http") for c in src.CT_REG_CITATIONS.values()))

# ---- rendered-PDF checks (P0/P4) — only if a PDF path is supplied ----
pdf = None
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    pdf = sys.argv[1]
else:
    cands = sorted(glob.glob(os.path.join(HERE, "CannaScope CT V15 - Statewide Transparency Reports",
                                          "*", "*-CannaScopeCT-SW-*.pdf")), key=os.path.getmtime)
    pdf = cands[-1] if cands else None

if pdf:
    print(f"\n[rendering checks on {os.path.basename(pdf)}]")
    try:
        import pypdf
        txt = "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(pdf).pages)
        # P4: no stale version leak
        check("P4 no rendered CannaScope_CT_V15.py", "CannaScope_CT_V15.py" not in txt)
        check("P4 no rendered 'CannaScope CT V15'", "CannaScope CT V15" not in txt)
        check("P4 current version present", src.APP_NAME.split()[-1] in txt, src.APP_NAME)
        # P2/headline: standards no longer a wall of red UNVERIFIED
        check("standards not all-UNVERIFIED", txt.count("UNVERIFIED") == 0, f"count={txt.count('UNVERIFIED')}")
        check("year-by-year ledger present", ("Year by Year" in txt or "Year-by-Year" in txt))
        # P0: an integer split across lines extracts as a lone digit on its own line between digits.
        lone_digit_runs = len(re.findall(r"(?m)^\s*\d\s*$\n^\s*\d\s*$", txt))
        check("P0 no obvious split integers (lone-digit run-on lines)", lone_digit_runs == 0, f"runs={lone_digit_runs}")
    except Exception as e:
        check("rendering checks ran", False, f"{type(e).__name__}: {e}")
else:
    print("\n[no report PDF found — rendering checks skipped]")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: " + ", ".join(FAILS)); sys.exit(1)
print("ALL TESTS PASSED"); sys.exit(0)
