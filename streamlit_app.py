"""
CannaScope CT V17.0.0 — Streamlit front end (consumer-friendly).

Drives the REAL current program (auto-detected) to generate a PDF, served via st.download_button.
ADAPTIVE: if the triple-verified COA cache is available (the self-contained CannaScope_CT_V17.py, or a
local COA Data Cache.csv), the app runs FULL reports straight from the cache (fast, no per-product cap).
Otherwise it runs a small, capped LIVE sample so a public click stays fast on the free hosting tier.
Product search reads the CT registry (cached). Friendly errors, no stack traces. Advisory wording.
"""
import csv
import datetime
import glob
import io
import os
import re
import subprocess
import sys
import time

import streamlit as st

st.set_page_config(page_title="CannaScope CT", page_icon="🌿", layout="centered",
                   initial_sidebar_state="collapsed")

HERE = os.path.dirname(os.path.abspath(__file__))
# Prefer the self-contained V17 (it embeds the triple-verified cache + auto-seeds it) so the web app
# can run full, fast reports; fall back to the modular source.
_CANDIDATES = ["CannaScope_CT_V17.py", "cannascope_ct_v17_src.py", "CannaScope_CT_V16.py", "cannascope_ct_v16_src.py"]
SCRIPT = next((c for c in _CANDIDATES if os.path.exists(os.path.join(HERE, c))), None)


@st.cache_data(show_spinner=False)
def app_version():
    """The REAL program version, read from the shipped code so the UI badge can never drift from the
    actual build. Prefers the small lean source; falls back to scanning the self-contained."""
    for cand in ("cannascope_ct_v17_src.py", "cannascope_ct_v16_src.py", SCRIPT or ""):
        p = os.path.join(HERE, cand)
        if cand and os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    m = re.search(r'SOFTWARE_VERSION\s*=\s*"([^"]+)"', f.read())
                if m:
                    return m.group(1)
            except Exception:
                pass
    return ""


STATEWIDE_DIR = "CannaScope CT V17 - Statewide Transparency Reports"
CONSUMER_DIR = os.path.join("output", "consumer_concerns")
LOCAL_REGISTRY = os.path.join(HERE, STATEWIDE_DIR, "Registry Cache.csv")
LOCAL_COA_CACHE = os.path.join(HERE, STATEWIDE_DIR, "COA Data Cache.csv")
REGISTRY_URL = "https://data.ct.gov/resource/egd5-wb6r.csv?$limit=40000"
RUN_TIMEOUT = 600
# Cache available if the self-contained (with embedded cache) is the program, or a cache CSV exists.
CACHE_READY = bool(SCRIPT and ("V17" in SCRIPT or "V16" in SCRIPT)) or os.path.exists(LOCAL_COA_CACHE)
SAMPLE_CAP = 150          # live-mode product cap (only used when CACHE_READY is False)
MAX_DAYS = 365 if CACHE_READY else 365

# ---------------------------------------------------------------- styling (UI ONLY — colors, fonts,
# spacing, layout). Pairs with .streamlit/config.toml (pinned light theme). No logic is affected.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

/* ===== HARD LIGHT MODE: stop the visitor's OS/browser dark mode from inverting text or native form
   controls (the white-on-white / dark-widget contrast bug). Explicit dark text on light surfaces. ===== */
:root, html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  color-scheme: light !important; }
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], .main, .block-container,
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stSidebar"] {
  background-color:#ffffff !important; }
/* default every text node to dark; brand-colored rules below use !important so they still win */
.stApp, .stApp p, .stApp li, .stApp span, .stApp label, .stApp small,
.stMarkdown, [data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] * { color:#16271d; }
/* form fields + dropdown popovers: dark text on white, readable everywhere */
.stTextInput input, .stNumberInput input, textarea,
[data-baseweb="select"], [data-baseweb="select"] *, [data-baseweb="input"] *,
[data-baseweb="popover"], [data-baseweb="popover"] *, [role="listbox"], [role="option"] {
  color:#16271d !important; background-color:#ffffff !important; }
[data-baseweb="select"] svg, [data-testid="stExpander"] svg { fill:#16271d !important; }

/* ---- type system: Inter everywhere, comfortable body, strong dark text ---- */
html, body, [class*="css"], .stMarkdown, .stMarkdown p, .stButton>button, input, textarea,
label, .stSelectbox, [data-baseweb="select"] * {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important; }
.stMarkdown, .stMarkdown p, label, .stCaption, p { font-size: 1rem; line-height: 1.55; color:#16271d; }

/* ---- page canvas: centered, comfortable max-width, generous spacing ---- */
.stApp { background: linear-gradient(180deg,#f4f8f4 0%, #ffffff 320px); }
.block-container { max-width: 720px; padding-top: 1.6rem; padding-bottom: 3.5rem; }

/* ---- headings / type scale ---- */
h1 { color:#10311c !important; font-weight:800 !important; font-size:2.15rem !important;
  letter-spacing:-.025em; line-height:1.15; margin-bottom:.15rem; }
h2 { color:#14321f !important; font-weight:700 !important; font-size:1.35rem !important; letter-spacing:-.01em; }
h3 { color:#14321f !important; font-weight:700 !important; font-size:1.12rem !important; }
.stCaption, [data-testid="stCaptionContainer"] { color:#5d6f5d !important; }

/* ---- version badge: tasteful, not crowding the title ---- */
.cs-badge { background:#1E7E34; color:#fff !important; font-size:.62rem; font-weight:700;
  letter-spacing:.02em; padding:3px 9px; border-radius:999px; vertical-align:middle;
  position:relative; top:-2px; margin-left:.55rem; box-shadow:0 1px 2px rgba(16,49,28,.18); }

/* ---- the two main options: clear, deliberate tabs with an obvious selected state ---- */
.stTabs [data-baseweb="tab-list"] { gap:.4rem; border-bottom:1px solid #e2eae2; padding-bottom:0; }
.stTabs [data-baseweb="tab"] { font-size:1.02rem !important; font-weight:600 !important; color:#5d6f5d;
  padding:.6rem 1.1rem; border-radius:10px 10px 0 0; }
.stTabs [data-baseweb="tab"]:hover { background:#f1f6f1; color:#14321f; }
.stTabs [aria-selected="true"] { color:#1E7E34 !important; background:#eaf3ea;
  border-bottom:3px solid #1E7E34; font-weight:700 !important; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { background:transparent; }

/* ---- primary + download buttons: the obvious next action ---- */
.stButton>button[kind="primary"], .stDownloadButton>button {
  background:#1E7E34 !important; border:0 !important; border-radius:10px; font-weight:700;
  padding:.62rem 1.1rem; color:#fff !important; box-shadow:0 2px 6px rgba(30,126,52,.28);
  transition:background .15s ease, transform .05s ease; }
.stButton>button[kind="primary"]:hover, .stDownloadButton>button:hover {
  background:#176a2b !important; color:#fff !important; }
.stButton>button[kind="primary"]:active, .stDownloadButton>button:active { transform:translateY(1px); }
.stButton>button[kind="secondary"] { border:1px solid #cfdccf; border-radius:10px; font-weight:600;
  color:#14321f; }

/* ---- crisp form fields with readable placeholders + clear focus ---- */
.stTextInput input, .stSelectbox [data-baseweb="select"] > div {
  border-radius:9px !important; border:1px solid #cdd8cf !important; background:#fff !important; }
.stTextInput input:focus, .stSelectbox [data-baseweb="select"] > div:focus-within {
  border-color:#1E7E34 !important; box-shadow:0 0 0 3px rgba(30,126,52,.15) !important; }
.stTextInput input::placeholder { color:#7a8a7a !important; opacity:1; }
.stTextInput label, .stSelectbox label, .stSlider label, .stCheckbox label {
  font-weight:600 !important; color:#14321f !important; }

/* ---- advisory + alert boxes: readable, grouped ---- */
[data-testid="stAlert"] { border-radius:10px; }
[data-testid="stAlert"] p { color:#14321f !important; }

/* ---- "enter identifier manually" expander ---- */
[data-testid="stExpander"] { border:1px solid #e2eae2 !important; border-radius:10px; background:#fbfdfb; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary p { font-weight:600; color:#14321f !important; }

/* ---- metric (product count) ---- */
div[data-testid="stMetricValue"] { color:#1E7E34 !important; font-weight:800; }
div[data-testid="stMetricLabel"] p { color:#5d6f5d !important; font-weight:600; }

/* ---- product result card + footer ---- */
.cs-prod { background:#fff; border:1px solid #e2eae2; border-radius:12px; padding:.85rem 1rem;
  font-size:.95rem; color:#14321f; box-shadow:0 1px 3px rgba(16,49,28,.05); }
.cs-foot { color:#6b7d6b; font-size:.82rem; line-height:1.5; }

/* ---- graceful on mobile ---- */
@media (max-width: 640px) {
  .block-container { padding-left:1rem; padding-right:1rem; }
  h1 { font-size:1.7rem !important; }
  .stTabs [data-baseweb="tab"] { padding:.5rem .7rem; font-size:.95rem !important; }
}
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
    pats = [os.path.join(base, "*.pdf"), os.path.join(base, "*", "*.pdf"),
            os.path.join(base, "**", "*.pdf")]
    cands = [p for pat in pats for p in glob.glob(pat, recursive=True)
             if os.path.getmtime(p) >= since - 1]
    # Fallback so a program output-folder rename (e.g. a version bump) can't hide a freshly written
    # report: scan any CannaScope output folder under HERE for a PDF created during this run.
    if not cands:
        for pat in (os.path.join(HERE, "CannaScope CT V*", "**", "*.pdf"),
                    os.path.join(HERE, "output", "**", "*.pdf")):
            cands += [p for p in glob.glob(pat, recursive=True) if os.path.getmtime(p) >= since - 1]
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
st.markdown(f'# 🌿 CannaScope CT <span class="cs-badge">V{app_version() or "17"}</span>',
            unsafe_allow_html=True)
st.caption("Source-verified Connecticut cannabis transparency reports · 33,000+ triple-verified COAs")
st.info("**Advisory tool — not medical, legal, or professional advice, and not affiliated with the "
        "State of Connecticut.** Every result is a *lead to verify, not a conclusion.* Always confirm "
        "against the official, live Certificate of Analysis (COA).", icon="ℹ️")
st.markdown("Each report is generated as a **downloadable PDF** you can save, print, or share.")

# Persistent desktop-download callout — always points at the CURRENT GitHub release (permalink), works on
# Windows / macOS / Linux. Shown on every load, above both tabs.
GITHUB_LATEST = "https://github.com/jmlschlee/CannaScope-CT/releases/latest"
st.markdown(
    '<div style="background:#eaf3ea;border:1px solid #cfe3cf;border-radius:10px;padding:.7rem .95rem;'
    'margin:.25rem 0 .7rem;color:#14321f;font-size:.95rem;line-height:1.5;">'
    '💻 <b>Prefer the desktop app?</b> Free download — runs on <b>🪟 Windows</b>, <b>🍎 macOS</b>, and '
    '<b>🐧 Linux</b>. &nbsp;'
    f'<a href="{GITHUB_LATEST}" target="_blank" rel="noopener" '
    'style="color:#1E7E34;font-weight:700;text-decoration:none;">⬇️ Get the latest release on GitHub →</a>'
    '</div>', unsafe_allow_html=True)

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
        # SUPERIOR RULE — LIVE-FIRST. The cache only makes runs faster; the live COA is the authority. So the
        # DEFAULT is a live-validated run (re-verify each product against its source COA). "Fast (cached,
        # unverified)" is an explicit opt-out that replays the cache WITHOUT live verification — and the report
        # is then labeled UNVALIDATED. Neither path forces --offline (the program refuses a silent offline run
        # while the network is reachable), so the hosted app can never silently degrade to a cache replay.
        VAL_MODES = {"🔬 Live-validated (recommended)": "live",
                     "⚡ Fast (cached, unverified)": "fast"}
        vmode = st.radio("Validation mode", list(VAL_MODES), index=0,
                         help="Live-validated re-checks each product against its live COA at the source link "
                              "before trusting the cache (forensic, slower). Fast replays the cached dataset "
                              "with no live verification — the report is then labeled UNVALIDATED — CACHE REPLAY.")
        mode = VAL_MODES[vmode]
        win = (["--since", "2012-01-01"] if days is None else ["--days", str(int(days))])
        # live = online, live-first (default); fast = online but cache-first/sampled via --fast-cache.
        args_preview = ["statewide", *win, "--csv-cache"] + (["--fast-cache"] if mode == "fast" else [])
        run_label = "statewide report (fast/cached)" if mode == "fast" else "statewide report (live-validated)"
        if days is None:
            in_window = len(products) if products else None
        else:
            in_window = (sum(1 for p in products if p["date"]
                             and p["date"] >= datetime.date.today() - datetime.timedelta(days=days))
                         if products else None)
        if in_window is not None:
            st.metric("Products this report will review", f"{in_window:,}")
            if mode == "live":
                st.success(f"**Live-validated** — re-verifies all {in_window:,} products ({choice.lower()}) "
                           "against their live source COAs; the report shows a **Validation Coverage %**.")
            else:
                st.warning(f"**Fast / cached** — replays {in_window:,} products ({choice.lower()}) from the "
                           "cached dataset **without live verification**. The PDF is labeled "
                           "**UNVALIDATED — CACHE REPLAY**. Use Live-validated for a forensic report.")
        st.caption("Live-validated re-pulls source COAs, so build time scales with the number of products; the "
                   "very largest windows are heavy on the free hosting tier — the desktop download handles any size.")
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
st.markdown(
    f'<div class="cs-foot">💻 Desktop app (🪟 Windows · 🍎 macOS · 🐧 Linux): '
    f'<a href="{GITHUB_LATEST}" target="_blank" rel="noopener" style="color:#1E7E34;font-weight:600;">'
    'download the latest release on GitHub →</a></div>', unsafe_allow_html=True)
st.markdown('<div class="cs-foot">Data: Connecticut product registry (data.ct.gov) + each product\'s '
            'linked COA. A value is shown only if it appears in its own linked Certificate of Analysis. '
            'Findings are leads to verify, never conclusions.</div>', unsafe_allow_html=True)
