"""Bundle the engine + V13 report program into ONE self-contained file,
CannaScope_CT_V13.py. Embeds the engine modules + OCR worker, PLUS a compressed
registry snapshot (offline seed / fallback) and a skip-list snapshot of
already-verified-CLEAN COAs (used only by the opt-in --fast-cached mode).
Re-run after editing cannascope_ct_v13.py (or the v4/v5/names/worker modules)."""
import base64, zlib, os

def blob(path):
    return base64.b64encode(zlib.compress(open(path, encoding='utf-8').read().encode('utf-8'), 9)).decode('ascii')

def bin_blob(path):
    return base64.b64encode(zlib.compress(open(path, 'rb').read(), 9)).decode('ascii')

NAMES, V4, V5, WORKER = (blob('ct_cannabis_names.py'), blob('cannascope_ct_v4.py'),
                         blob('cannascope_ct_v5.py'), blob('cannascope_ocr_worker.py'))

# Embedded caches (baked to speed first-time use; base64 has no '%', so it is template-safe).
_RD = 'CannaScope CT V13 - Statewide Transparency Reports'
for _alt in ('CannaScope CT Beta V12.1 - Statewide Transparency Reports', 'CannaScope CT Beta V12 - Statewide Transparency Reports', 'CannaScope CT Beta V11.1 - Statewide Transparency Reports'):
    if not os.path.exists(os.path.join(_RD,'Registry Cache.csv')) and os.path.exists(os.path.join(_alt,'Registry Cache.csv')):
        _RD=_alt
if not os.path.exists(os.path.join(_RD,'Registry Cache.csv')):
    _RD = 'CannaScope CT Beta V11 - Statewide Transparency Reports'
REG_PATH = os.path.join(_RD, 'Registry Cache.csv')
SKIP_PATH = os.path.join(_RD, 'Already-Scanned Skip List.txt')
REG = bin_blob(REG_PATH)
REG_EPOCH = int(os.path.getmtime(REG_PATH))
SKIP = bin_blob(SKIP_PATH) if os.path.exists(SKIP_PATH) else ''
print(f"  embedded registry: {os.path.getsize(REG_PATH):,}B raw -> {len(REG):,}B b64 (snapshot epoch {REG_EPOCH})")
print(f"  embedded skip-list: {(os.path.getsize(SKIP_PATH) if os.path.exists(SKIP_PATH) else 0):,}B raw -> {len(SKIP):,}B b64")

v9 = open('cannascope_ct_v13_src.py', encoding='utf-8').read()
body = v9[v9.index('import argparse'):]
OLD = '_OCR_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cannascope_ocr_worker.py")'
assert OLD in body
body = body.replace(OLD, '_OCR_WORKER = _materialize_ocr_worker()   # embedded worker -> temp file')
HEADER = '''#!/usr/bin/env python3
"""
================================================================================
 CannaScope CT V13  —  COMPLETE SELF-CONTAINED SINGLE-FILE BUILD
================================================================================
Connecticut cannabis testing & compliance tool. THIS ONE FILE IS THE ENTIRE PROGRAM.

EVERYTHING IS BAKED IN — the engine modules + OCR worker are embedded (compressed),
plus a registry snapshot and a skip-list snapshot to speed first-time use:
  - cannascope_ct_v4.py / cannascope_ct_v5.py / ct_cannabis_names.py / OCR worker
  - Registry snapshot  -> seeds the cache so the registry download is skipped while the
    snapshot is fresh, and the tool survives the state data portal being briefly down.
    ONLINE runs auto-refresh once it ages out, so online accuracy is never compromised.
    (A full --offline report still needs COA PDFs cached from a prior online run.)
  - Skip-list snapshot -> only used by the OPT-IN --fast-cached flag (skips
    already-verified-CLEAN COAs for a faster first run; findings unchanged, coverage lower).
You only need Python + the PyPI libraries below (installed with pip, not embedded).

REQUIREMENTS
  Python 3.9+ and:  pip install requests reportlab pypdfium2 pdfplumber Pillow psutil
  OCR (optional): macOS -> pip install ocrmac   |   Win/Linux -> pip install pytesseract + Tesseract

TWO REPORTS
  Statewide Transparency Report (whole market):
    python3 CannaScope_CT_V13.py statewide --days 365
    python3 CannaScope_CT_V13.py statewide --since 2024-01-01 --until 2024-12-31
    (faster first run, lower coverage:  add  --fast-cached  |  no network:  add  --offline)
  Personalized Product Concern Report (one product, for a consumer concern):
    python3 CannaScope_CT_V13.py concern --batch <BATCH> --ndc <NDC> --qr <URL>
    python3 CannaScope_CT_V13.py concern --example
  Outputs go to "CannaScope CT V13 - Statewide Transparency Reports/" and
  "output/consumer_concerns/". Reports are NEVER overwritten (numbered + timestamped).
"""
import base64 as _b64, os as _os, sys as _sys, tempfile as _tmp, types as _types, zlib as _zlib
_EMBEDDED = {"ct_cannabis_names": %(NAMES)r, "cannascope_ct_v4": %(V4)r, "cannascope_ct_v5": %(V5)r}
_OCR_WORKER_SRC_B64 = %(WORKER)r
_EMBEDDED_REGISTRY_B64 = %(REG)r
_EMBEDDED_REGISTRY_EPOCH = %(REG_EPOCH)d
_EMBEDDED_SKIPLIST_B64 = %(SKIP)r
def _install_embedded():
    base=_os.getcwd()
    for name in ("ct_cannabis_names","cannascope_ct_v4","cannascope_ct_v5"):
        if name in _sys.modules: continue
        src=_zlib.decompress(_b64.b64decode(_EMBEDDED[name])).decode("utf-8")
        mod=_types.ModuleType(name); mod.__file__=_os.path.join(base,name+".py")
        _sys.modules[name]=mod; exec(compile(src,mod.__file__,"exec"),mod.__dict__)
def _materialize_ocr_worker():
    try:
        p=_os.path.join(_tmp.gettempdir(),"cannascope_v13_ocr_worker.py")
        open(p,"w",encoding="utf-8").write(_zlib.decompress(_b64.b64decode(_OCR_WORKER_SRC_B64)).decode("utf-8"))
        return p
    except Exception: return ""
_install_embedded()
# ============================================================================
''' % dict(NAMES=NAMES, V4=V4, V5=V5, WORKER=WORKER, REG=REG, REG_EPOCH=REG_EPOCH, SKIP=SKIP)
out = HEADER + body
open('CannaScope_CT_V13.py', 'w', encoding='utf-8').write(out)
print(f'Wrote CannaScope_CT_V13.py ({len(out):,} bytes)')
