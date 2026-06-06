"""
CannaScope CT V16.0.0 — Streamlit front end (consumer-friendly).

Drives the REAL current program (auto-detected) to generate a PDF, served via st.download_button.
ADAPTIVE: if the triple-verified COA cache is available (the self-contained CannaScope_CT_V16.py, or a
local COA Data Cache.csv), the app runs FULL reports straight from the cache (fast, no per-product cap).
Otherwise it runs a small, capped LIVE sample so a public click stays fast on the free hosting tier.
Product search reads the CT registry (cached). Friendly errors, no stack traces. Advisory wording.
"""
import csv
import datetime
import glob
import io
import os
import subprocess
import sys
import time

import streamlit as st

st.set_page_config(page_title="CannaScope CT", page_icon="🌿", layout="centered",
                   initial_sidebar_state="collapsed")

HERE = os.path.dirname(os.path.abspath(__file__))
# Prefer the self-contained V16 (it embeds the triple-verified cache + auto-seeds it) so the web app
# can run full, fast reports; fall back to the modular source.
_CANDIDATES = ["CannaScope_CT_V16.py", "cannascope_ct_v16_src.py", "CannaScope_CT_V15.py"]
SCRIPT = next((c for c in _CANDIDATES if os.path.exists(os.path.join(HERE, c))), None)

STATEWIDE_DIR = "CannaScope CT V15 - Statewide Transparency Reports"
CONSUMER_DIR = os.path.join("output", "consumer_concerns")
LOCAL_REGISTRY = os.path.join(HERE, STATEWIDE_DIR, "Registry Cache.csv")
LOCAL_COA_CACHE = os.path.join(HERE, STATEWIDE_DIR, "COA Data Cache.csv")
REGISTRY_URL = "https://data.ct.gov/resource/egd5-wb6r.csv?$limit=40000"
RUN_TIMEOUT = 600
# Cache available if the self-contained (with embedded cache) is the program, or a cache CSV exists.
CACHE_READY = bool(SCRIPT and "V16" in SCRIPT) or os.path.exists(LOCAL_COA_CACHE)
SAMPLE_CAP = 150          # live-mode product cap (only used when CACHE_READY is False)
MAX_DAYS = 365 if CACHE_READY else 365

# ---------------------------------------------------------------- styling (keep Streamlit's font family
# everywhere so typography is consistent; only color/weight/spacing are themed)
st.markdown("""
<style>
html, body, [class*="css"], .stMarkdown, .stButton>button { font-family: "Source Sans Pro", sans-serif; }
.stApp { background: linear-gradient(180deg,#f6faf6 0%,#ffffff 260px); }
.block-container { max-width: 760px; padding-top: 1.5rem; }
h1,h2,h3 { color:#14321f; letter-spacing:-.01em; }
.cs-badge { background:#1E7E34; color:#fff; font-size:.70rem; font-weight:700; padding:2px 9px;
  border-radius:999px; position:relative; top:-6px; margin-left:.4rem; }
.stButton>button[kind="primary"], .stDownloadButton>button {
  background:#1E7E34; border:0; border-radius:10px; font-weight:700; padding:.55rem 1rem; color:#fff; }
.stButton>button[kind="primary"]:hover, .stDownloadButton>button:hover { background:#176a2b; color:#fff; }
.stTabs [data-baseweb="tab"] { font-size:1rem; font-weight:600; }
div[data-testid="stMetricValue"] { color:#1E7E34; }
.cs-foot { color:#6b7d6b; font-size:.82rem; }
.cs-prod { background:#fff; border:1px solid #e6ece6; border-radius:12px; padding:.7rem .9rem;
  font-size:.92rem; color:#14321f; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- registry (autocomplete + window counts)
def _g(row, *keys):
    for k in keys:
        for v in (k, k.lower(), k.replace("-", "_").lower()):
            if row.get(v):
                return str(row[v]).strip()
    return ""


def _parse_date(s):
    import re
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        return None
    mo, da, yr = map(int, m.groups())
    try:
        return datetime.date(yr, mo, da)
    except ValueError:
        return None


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_products():
    text = None
    if os.path.exists(LOCAL_REGISTRY):
        try:
            text = open(LOCAL_REGISTRY, encoding="utf-8", errors="replace").read()
        except OSError:
            text = None
    if not text:
        try:
            import requests
            r = requests.get(REGISTRY_URL, timeout=45,
                             headers={"User-Agent": "CannaScopeCT/16 (consumer web app)"})
            r.raise_for_status()
            text = r.content.decode("utf-8", "replace")
        except Exception:
            return []
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        name = _g(row, "PRODUCT-NAME", "product_name")
        reg = _g(row, "REGISTRATION-NUMBER", "registration_number")
        if not name or not reg:
            continue
        out.append({"name": name, "producer": _g(row, "BRANDING-ENTITY", "branding_entity"),
                    "form": _g(row, "DOSAGE-FORM", "dosage_form"), "reg": reg,
                    "date": _parse_date(_g(row, "APPROVAL-DATE", "approval_date"))})
    return out


def _newest_pdf(base, since):
    pats = [os.path.join(base, "*.pdf"), os.path.join(base, "*", "*.pdf")]
    cands = [p for pat in pats for p in glob.glob(pat) if os.path.getmtime(p) >= since - 1]
    return max(cands, key=os.path.getmtime) if cands else None


def run_report(args, output_base, label):
    if not SCRIPT:
        return False, None, "The CannaScope program file was not found next to this app."
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
        return True, pdf, "ok"
    tail = (proc.stdout or "").strip().splitlines()[-3:] if proc and proc.stdout else []
    hint = " ".join(tail)[-300:] if tail else ""
    return False, None, ("No report could be generated for that request. "
                         + (f"({hint})" if hint else "Please check the details and try again."))


def offer_pdf(pdf, label):
    st.success(f"✅  Your {label} is ready — download it below (PDF).")
    with open(pdf, "rb") as f:
        st.download_button("⬇️  Download the PDF report", f.read(), file_name=os.path.basename(pdf),
                           mime="application/pdf", type="primary", use_container_width=True)


# ---------------------------------------------------------------- header
st.markdown('# 🌿 CannaScope CT <span class="cs-badge">V16.0.0</span>', unsafe_allow_html=True)
st.caption("Source-verified Connecticut cannabis transparency reports · 33,000+ triple-verified COAs")
st.info("**Advisory tool — not medical, legal, or professional advice, and not affiliated with the "
        "State of Connecticut.** Every result is a *lead to verify, not a conclusion.* Always confirm "
        "against the official, live Certificate of Analysis (COA).", icon="ℹ️")
st.markdown("Each report is generated as a **downloadable PDF** you can save, print, or share.")

if not SCRIPT:
    st.error("Setup issue: the CannaScope program file isn't deployed alongside this app.")
    st.stop()

products = load_products()
tab_look, tab_state = st.tabs(["🔎  Look up a product", "🏛️  Statewide report"])

# ================================================================ Consumer lookup
with tab_look:
    st.subheader("Look up a product you're concerned about")
    st.write("Search by name, then download a plain-English PDF review of that product and its lab results.")

    chosen = None
    if products:
        q = st.text_input("Search by product or brand name",
                          placeholder="Start typing — e.g. “Brix”, “Gelato”, “Theraplant”…")
        if q and len(q.strip()) >= 2:
            ql = q.strip().lower()
            matches = [p for p in products if ql in p["name"].lower() or ql in p["producer"].lower()]
            if matches:
                labels = [f"{p['name']}  —  {p['producer'] or 'unknown producer'}" for p in matches[:30]]
                st.caption(f"{len(matches):,} match(es)" + (" (showing first 30)" if len(matches) > 30 else "")
                           + " — pick yours:")
                pick = st.selectbox("Matching products", labels, label_visibility="collapsed")
                chosen = matches[labels.index(pick)]
                st.markdown(f'<div class="cs-prod">📦 <b>{chosen["name"]}</b><br>Producer: '
                            f'{chosen["producer"] or "—"} · Form: {chosen["form"] or "—"} · '
                            f'Reg #: {chosen["reg"]}</div>', unsafe_allow_html=True)
            else:
                st.caption("No matches yet — try fewer letters, or use the manual identifier option below.")
    else:
        st.caption("Product search is temporarily unavailable — use the manual identifier option below.")

    with st.expander("Or enter an identifier manually (batch, NDC, COA #, UID, or QR link)"):
        kind = st.selectbox("Identifier type",
                            ["Batch / lot", "NDC", "COA number", "UID / BioTrack lot", "COA / QR link"])
        manual_val = st.text_input("Value", key="manual_val",
                                   placeholder="a batch number, NDC, COA number, BioTrack UID, or a COA URL")

    use_example = st.checkbox("Show me a worked example instead", value=False)

    if st.button("Generate the PDF report", type="primary", use_container_width=True, key="btn_consumer"):
        if use_example:
            args = ["concern", "--example"]
        elif chosen:
            args = ["concern", "--product", chosen["name"], "--coa", chosen["reg"]]
        elif manual_val.strip():
            flag = {"Batch / lot": "--batch", "NDC": "--ndc", "COA number": "--coa",
                    "UID / BioTrack lot": "--uid", "COA / QR link": "--qr"}[kind]
            args = ["concern", flag, manual_val.strip()]
        else:
            st.warning("Search and pick a product, enter an identifier, or tick the worked-example box.")
            st.stop()
        with st.spinner("Looking up the product and its COA, then building your PDF…"):
            ok, pdf, msg = run_report(args, CONSUMER_DIR, "consumer concern report")
        offer_pdf(pdf, "consumer concern report") if ok else st.error(msg)

# ================================================================ Statewide
with tab_state:
    st.subheader("Statewide transparency report")
    if CACHE_READY:
        st.write("Reviews **every** product registered in your chosen window, straight from the "
                 "triple-verified COA dataset, and returns a **downloadable PDF**. Just pick how far back to look.")
    else:
        st.write("Reviews recently-registered products statewide and returns a **downloadable PDF**. "
                 "This hosted version reads each COA live, so it checks a fast, capped batch (newest first).")

    if CACHE_READY:
        # The triple-verified COA dataset loads instantly, so the window is NOT limited by data speed.
        # Offer everything up to all-time; the only real bound is how big a report the host can BUILD.
        WINDOWS = {"Last 30 days": 30, "Last 90 days": 90, "Last 6 months": 182,
                   "Last year": 365, "Last 2 years": 730, "All available (every year)": None}
        choice = st.selectbox("How far back to review", list(WINDOWS), index=3,
                              help="Data loads instantly from the embedded dataset. Larger windows just "
                                   "take longer to compile into the PDF.")
        days = WINDOWS[choice]
        if days is None:
            in_window = len(products) if products else None
            args_preview = ["statewide", "--since", "2012-01-01", "--csv-cache"]
        else:
            in_window = (sum(1 for p in products if p["date"]
                             and p["date"] >= datetime.date.today() - datetime.timedelta(days=days))
                         if products else None)
            args_preview = ["statewide", "--days", str(int(days)), "--csv-cache"]
        run_label = "statewide report"
        if in_window is not None:
            st.metric("Products this report will review", f"{in_window:,}")
            st.success(f"Reviews **all {in_window:,}** products ({choice.lower()}) from the "
                       "triple-verified COA dataset — no per-product cap — and returns one combined PDF.")
        st.caption("The data is instant; build time scales with the number of products. The very largest "
                   "windows can be heavy on the free hosting tier — the desktop download handles any size.")
    else:
        days = st.slider("How many days back to review", 7, MAX_DAYS, 90,
                         help="A product is included if it was registered within this many days of today.")
        in_window = (sum(1 for p in products if p["date"]
                         and p["date"] >= datetime.date.today() - datetime.timedelta(days=days))
                     if products else None)
        if in_window is not None:
            st.metric(f"Products registered in the last {days} days", f"{in_window:,}")
        if in_window is not None and in_window > SAMPLE_CAP:
            st.warning(f"Hosted live mode: reviews the **{SAMPLE_CAP} newest** of these "
                       f"**{in_window:,}** products. For the complete report, use the desktop download.")
        args_preview = ["statewide", "--days", str(int(days)), "--limit", str(SAMPLE_CAP)]
        run_label = "statewide sample report"

    if st.button("Generate the PDF report", type="primary", use_container_width=True, key="btn_state"):
        with st.spinner("Reviewing products and building your PDF…"):
            ok, pdf, msg = run_report(args_preview, STATEWIDE_DIR, run_label)
        offer_pdf(pdf, run_label) if ok else st.error(msg)

st.divider()
st.markdown('<div class="cs-foot">Data: Connecticut product registry (data.ct.gov) + each product\'s '
            'linked COA. A value is shown only if it appears in its own linked Certificate of Analysis. '
            'Findings are leads to verify, never conclusions.</div>', unsafe_allow_html=True)
