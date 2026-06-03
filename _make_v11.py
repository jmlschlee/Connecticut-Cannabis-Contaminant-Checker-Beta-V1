"""Bundle the engine + V11 report program into one self-contained file,
CannaScope_CT_Beta_V11.py. V11 is already branded, so no rebrand is needed —
this only embeds the engine modules + OCR worker and prepends the loader header.
Re-run after editing cannascope_ct_v11.py (or the v4/v5/names/worker modules)."""
import base64, zlib
def blob(path):
    return base64.b64encode(zlib.compress(open(path,encoding='utf-8').read().encode('utf-8'),9)).decode('ascii')
NAMES, V4, V5, WORKER = (blob('ct_cannabis_names.py'), blob('cannascope_ct_v4.py'),
                         blob('cannascope_ct_v5.py'), blob('cannascope_ocr_worker.py'))
v9 = open('cannascope_ct_v11.py',encoding='utf-8').read()
body = v9[v9.index('import argparse'):]
OLD='_OCR_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cannascope_ocr_worker.py")'
assert OLD in body
body = body.replace(OLD, '_OCR_WORKER = _materialize_ocr_worker()   # embedded worker -> temp file')
HEADER = '''#!/usr/bin/env python3
"""
================================================================================
 CannaScope CT Beta V11  —  COMPLETE SELF-CONTAINED SINGLE-FILE BUILD
================================================================================
Connecticut Cannabis Transparency Report. THIS ONE FILE IS THE ENTIRE PROGRAM.

EVERYTHING IS BAKED IN. The following project modules are embedded (compressed) in
this file and loaded into sys.modules at startup, so NO companion .py files are
needed:
  - cannascope_ct_v4.py    (download / OCR / contaminant parsing + flagging engine)
  - cannascope_ct_v5.py    (cannabinoid parsing, quantified-details, identity table)
  - ct_cannabis_names.py   (producer / lab name resolution)
  - cannascope_ocr_worker.py (crash-isolated OCR subprocess; materialized to a temp file)
You only need Python plus the third-party libraries below (these are PyPI packages,
not project files, so they are installed with pip rather than embedded).

REQUIREMENTS
  Python 3.9+ and:  pip install requests reportlab pypdfium2 pdfplumber Pillow psutil
  OCR (optional, recommended for scanned/image COAs):
    macOS  -> pip install ocrmac        (Apple Vision; no system binary needed)
    Win/Linux -> pip install pytesseract + install the Tesseract binary

HOW TO RUN
  python3 CannaScope_CT_Beta_V11.py --since 2024-01-01 --until 2024-12-31
  python3 CannaScope_CT_Beta_V11.py --days 90
  Offline re-run after one online --keep-clean-pdfs run:  add  --offline
  Useful flags: --forms flower|inhalable|all  --no-ocr  --workers N  --limit N

PATIENT-REPORTED PRODUCT CONCERN (on-demand personalized patient PDF):
  python3 CannaScope_CT_Beta_V11.py patient-concern --example
  python3 CannaScope_CT_Beta_V11.py patient-concern --ndc C0101000538 --batch ABC --qr <url>
  Writes to output/patient_concerns/ (separate from the regular report; never overwrites).

OUTPUT
  Creates "CannaScope CT Beta V11 - Reports/" beside this file: the PDF report, CSV
  exports, registry cache, and source COA PDFs for flagged products. Reports are NEVER
  overwritten:  CannaScope_CT_Beta_V11_Report_<N>_<YYYY_MM_DD_HHMM>.pdf
"""
import base64 as _b64, os as _os, sys as _sys, tempfile as _tmp, types as _types, zlib as _zlib
_EMBEDDED = {"ct_cannabis_names": %(NAMES)r, "cannascope_ct_v4": %(V4)r, "cannascope_ct_v5": %(V5)r}
_OCR_WORKER_SRC_B64 = %(WORKER)r
def _install_embedded():
    base=_os.getcwd()
    for name in ("ct_cannabis_names","cannascope_ct_v4","cannascope_ct_v5"):
        if name in _sys.modules: continue
        src=_zlib.decompress(_b64.b64decode(_EMBEDDED[name])).decode("utf-8")
        mod=_types.ModuleType(name); mod.__file__=_os.path.join(base,name+".py")
        _sys.modules[name]=mod; exec(compile(src,mod.__file__,"exec"),mod.__dict__)
def _materialize_ocr_worker():
    try:
        p=_os.path.join(_tmp.gettempdir(),"cannascope_v11_ocr_worker.py")
        open(p,"w",encoding="utf-8").write(_zlib.decompress(_b64.b64decode(_OCR_WORKER_SRC_B64)).decode("utf-8"))
        return p
    except Exception: return ""
_install_embedded()
# ============================================================================
''' % dict(NAMES=NAMES,V4=V4,V5=V5,WORKER=WORKER)
out=HEADER+body
open('CannaScope_CT_Beta_V11.py','w',encoding='utf-8').write(out)
print(f'Wrote CannaScope_CT_Beta_V11.py ({len(out):,} bytes)')
