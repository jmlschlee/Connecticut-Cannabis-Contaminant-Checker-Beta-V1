# CannaScope CT V15.1.2 🌿

**An additive patch on top of V15.1.1.** Every prior release stays live and unchanged — nothing was
deleted or renamed. This release makes the V15.1.1 **live-source fix** take effect even on machines
where an older build had already cached "unreachable" results.

## 🔧 What's fixed

- **🗂️ Stale legal-source cache no longer masks the fix.** Entries in `Legal Standards Cache.json` are
  now stamped with a **fetch-logic version**. If a cached entry's stamp doesn't match the current
  version, it's treated as a miss and re-fetched. Since V15.1.1's fetch fix (corrected DCP URL, longer
  timeout, completed TLS chain) is a new fetch-logic version, any *"live CT sources unreachable"* entry
  written by a pre-fix build inside the 30-day cache window is now ignored and re-verified live —
  automatically, with **no manual cache deletion**.

## ✅ Unchanged

Every V15.1.1 / V15.1.0 capability is preserved: the live-source fix itself, `audit-cache`, the
`Data Exports` subfolder, the Streamlit app, short PDF filenames, the COA triple-check, and the
three-part potency review. The 30-day re-verification window and the fail-safe, never-fabricate
behavior are intact.

## 📦 Downloads

Self-contained, single-file builds (Python 3.9+). Each zip includes the program, a README, an
installer guide, and ready-to-run launch scripts:

- `CannaScopeCT-V15.1.2-Windows.zip`
- `CannaScopeCT-V15.1.2-macOS.zip`
- `CannaScopeCT-V15.1.2-Linux.zip`

> ⚖️ Advisory research tool — **not** legal, medical, or professional advice, and **not** affiliated
> with the State of Connecticut. Every flag is a **lead to verify, not a conclusion.**
