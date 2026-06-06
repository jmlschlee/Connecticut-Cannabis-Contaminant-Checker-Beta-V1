#!/usr/bin/env python3
"""
CannaScope OCR worker — runs ONE COA's OCR in an isolated subprocess.

CannaScope's main run launches this as a short-lived child process for each
scanned / image-only COA. If a native OCR engine (e.g. Apple Vision via ocrmac)
segfaults on a malformed image, only this child dies — the parent run catches the
non-zero exit and continues, treating that single COA as unreadable instead of
crashing the entire scan. This is what makes 100% coverage safe on very large runs.

Usage:  python cannascope_ocr_worker.py <pdf_path> [max_pages]
Prints the recognized text to stdout. Prints nothing and exits 0 if no OCR
backend is available; a crash/segfault exits non-zero (handled by the parent).
"""
import sys


def _backend():
    try:
        import ocrmac.ocrmac  # noqa: F401  (Apple Vision, macOS)
        return "ocrmac"
    except Exception:
        import shutil
        if shutil.which("tesseract"):
            try:
                import pytesseract  # noqa: F401
                return "tesseract"
            except Exception:
                return ""
    return ""


def main():
    if len(sys.argv) < 2:
        return
    path = sys.argv[1]
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    # Optional 3rd arg: render scale (≈ scale×72 DPI). Higher DPI markedly improves OCR of small
    # table text in image-only COAs (e.g. heavy-metal LOD/LOQ/Result columns). Default stays 2.0
    # for back-compat; the main program routes the quality retry through a higher scale.
    try:
        scale = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    except (TypeError, ValueError):
        scale = 2.0
    scale = max(1.0, min(scale, 4.0))     # clamp: below 1 is useless, above 4 risks OOM for no gain
    backend = _backend()
    if not backend:
        return
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)

    def _page_text(i):
        page = doc[i]
        bitmap = page.render(scale=scale)
        img = bitmap.to_pil()
        if backend == "ocrmac":
            from ocrmac import ocrmac
            res = ocrmac.OCR(img).recognize()
            t = "\n".join(r[0] for r in res)
        else:
            import pytesseract
            t = pytesseract.image_to_string(img.convert("L"))
        bitmap.close()
        page.close()
        return t

    # A scanned COA with MORE than `max_pages` pages is read in FULL (up to hard_cap) rather than
    # truncated: 2015-era multi-product documents put one product per page beyond page 6 (and a long
    # single-product COA can carry its panels across many pages), so capping at 6 silently dropped
    # whole products/panels. Early single-product pages can't reveal later ones, so we don't gate on a
    # text signature — any >max_pages scanned doc is fully OCR'd, bounded by hard_cap.
    hard_cap = 40
    n = min(len(doc), max(max_pages, hard_cap))
    out = [_page_text(i) for i in range(n)]
    doc.close()
    sys.stdout.write("\n".join(out))


if __name__ == "__main__":
    main()
