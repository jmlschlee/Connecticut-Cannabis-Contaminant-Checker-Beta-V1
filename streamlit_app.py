"""
CannaScope CT V15.1 — Streamlit front end (consumer-friendly).

Deploys on Streamlit Community Cloud from the repo's deploy branch (main). It drives the REAL
current V15 program (auto-detected: cannascope_ct_v15_src.py, else CannaScope_CT_V15.py) to
generate a PDF, then serves it via st.download_button — so it never relies on a permanent server
folder. Work per click is kept LIGHT (one-product lookup, or a small capped statewide sample);
no full multi-thousand scans or cache rebuilds happen on a click. Friendly errors, no stack
traces. Advisory / non-diagnostic wording. Secrets (if ever needed) come from st.secrets only.
"""
import glob
import os
import subprocess
import sys
import time

import streamlit as st

st.set_page_config(page_title="CannaScope CT V15.1", page_icon="🌿", layout="centered")

HERE = os.path.dirname(os.path.abspath(__file__))
# Detect the real current V15 program file — do not guess.
_CANDIDATES = ["cannascope_ct_v15_src.py", "CannaScope_CT_V15.py"]
SCRIPT = next((c for c in _CANDIDATES if os.path.exists(os.path.join(HERE, c))), None)

STATEWIDE_DIR = "CannaScope CT V15 - Statewide Transparency Reports"
CONSUMER_DIR = os.path.join("output", "consumer_concerns")
# Caps keep a click bounded (a public click never triggers a full multi-thousand statewide scan).
# Raised to a larger sample; the FULL uncapped report is the desktop download.
STATEWIDE_MAX_LIMIT = 150
RUN_TIMEOUT = 600  # seconds; a slow/hung generation fails friendly, never blocks forever


def _newest_pdf(base, since):
    """Newest *.pdf created at/after `since` under `base` and its one-level run subfolders."""
    pats = [os.path.join(base, "*.pdf"), os.path.join(base, "*", "*.pdf")]
    cands = [p for pat in pats for p in glob.glob(pat) if os.path.getmtime(p) >= since - 1]
    return max(cands, key=os.path.getmtime) if cands else None


def run_report(args, output_base, label):
    """Run the V15 program as an isolated subprocess and return (ok, pdf_path_or_None, message)."""
    if not SCRIPT:
        return False, None, "The CannaScope V15 program file was not found next to this app."
    since = time.time()
    try:
        proc = subprocess.run([sys.executable, SCRIPT, *args], cwd=HERE,
                              capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, None, (f"The {label} took too long and was stopped. Try a smaller window, or "
                             "try again in a moment.")
    except Exception:
        return False, None, f"Could not start the {label}. Please try again."
    pdf = _newest_pdf(os.path.join(HERE, output_base), since)
    if pdf and os.path.exists(pdf):
        return True, pdf, "Report ready."
    # No PDF — surface a friendly reason from the tail of the program's own output (no stack traces).
    tail = (proc.stdout or "").strip().splitlines()[-3:] if proc and proc.stdout else []
    hint = " ".join(tail)[-300:] if tail else ""
    return False, None, ("No report could be generated for that request. "
                         + (f"({hint})" if hint else "Please check the details and try again."))


# ---------------------------------------------------------------- UI
st.title("🌿 CannaScope CT")
st.caption("V15.1 · Source-verified Connecticut cannabis transparency reports")
st.info("**Advisory tool — not medical, legal, or professional advice, and not affiliated with the "
        "State of Connecticut.** Every result is a *lead to verify, not a conclusion.* Always confirm "
        "against the official, live Certificate of Analysis (COA).", icon="ℹ️")

if not SCRIPT:
    st.error("Setup issue: the CannaScope V15 program file isn't deployed alongside this app. "
             "Make sure `cannascope_ct_v15_src.py` (and its engine files) are on the deploy branch.")
    st.stop()

mode = st.radio("What would you like to do?",
                ["🔎 Consumer Concern Lookup (one product)", "🏛️ Statewide Report (sample)"],
                index=0)

# ---- Mode 1: Consumer Concern Lookup (light: one product) ----
if mode.startswith("🔎"):
    st.subheader("Look up one product you're concerned about")
    st.write("Enter any identifier you have — a batch/lot number, an NDC, the registration number, "
             "or a COA / QR link. You'll get a plain-English, advisory review of that product.")
    kind = st.selectbox("Identifier type",
                        ["Batch / lot", "NDC", "COA number", "UID / BioTrack lot", "COA / QR link"])
    value = st.text_input("Value", placeholder="e.g. a batch number, NDC, COA number, BioTrack UID, or a COA URL")
    use_example = st.checkbox("Or just show me a worked example", value=False)
    if st.button("Generate consumer report", type="primary"):
        if use_example:
            args = ["concern", "--example"]
        elif not value.strip():
            st.warning("Please enter an identifier, or tick the worked-example box.")
            st.stop()
        else:
            flag = {"Batch / lot": "--batch", "NDC": "--ndc", "COA number": "--coa",
                    "UID / BioTrack lot": "--uid", "COA / QR link": "--qr"}[kind]
            args = ["concern", flag, value.strip()]
        with st.spinner("Looking up the product and its COA…"):
            ok, pdf, msg = run_report(args, CONSUMER_DIR, "consumer lookup")
        if ok:
            st.success("Your consumer concern report is ready.")
            with open(pdf, "rb") as f:
                st.download_button("⬇️ Download the PDF", f.read(), file_name=os.path.basename(pdf),
                                   mime="application/pdf", type="primary")
        else:
            st.error(msg)

# ---- Mode 2: Statewide Report (light: capped sample) ----
else:
    st.subheader("Statewide transparency report (recent sample)")
    st.write("Generates a **small, recent sample** statewide report so it stays fast for everyone. "
             "For a full multi-year report, run the program from the desktop download.")
    days = st.slider("How many recent days to sample", 7, 365, 30)
    limit = st.slider("Max products to review (sample cap)", 5, STATEWIDE_MAX_LIMIT, 25)
    st.caption("Larger windows / higher product counts take longer and, near the top end, may time "
               "out on the free hosting tier. For a full, uncapped statewide report, use the desktop download.")
    if st.button("Generate statewide sample", type="primary"):
        args = ["statewide", "--days", str(days), "--limit", str(int(limit))]
        with st.spinner(f"Reviewing up to {int(limit)} recent products…"):
            ok, pdf, msg = run_report(args, STATEWIDE_DIR, "statewide sample")
        if ok:
            st.success("Your statewide sample report is ready.")
            with open(pdf, "rb") as f:
                st.download_button("⬇️ Download the PDF", f.read(), file_name=os.path.basename(pdf),
                                   mime="application/pdf", type="primary")
        else:
            st.error(msg)

st.divider()
st.caption("Data: Connecticut product registry (data.ct.gov) + each product's linked COA. "
           "A value is shown only if it appears in its own linked COA. Findings are leads to verify.")
