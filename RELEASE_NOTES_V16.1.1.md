# CannaScope CT V16.1.1

**Folder-name fix.** The output folder was still named "CannaScope CT V15 - Statewide Transparency
Reports" even though the program is V16 — a leftover from the V15→V16 transition (the `OUT_DIR`
constant was never bumped). V16.1.1 renames it to **"CannaScope CT V16 - Statewide Transparency
Reports"** and migrates the existing folder automatically.

## What changed
- `OUT_DIR` → `CannaScope CT V16 - Statewide Transparency Reports`.
- The V15 folder name is now first in `LEGACY_OUT_DIRS`, so on first run the existing folder is
  **renamed in place** (non-destructive) — the registry cache, the triple-verified COA cache, the
  regulatory source-document ledger, every prior numbered report, and the global report-number
  sequence all carry over. Nothing is re-downloaded; numbering continues unbroken.
- Build tooling (`_make_v16.py`) now looks for the V16 folder first (V15 as fallback).

Verified: an existing V15 install migrates to the V16 folder with the 76 MB COA cache, the regulatory
ledger, and 29 prior report folders intact, and report numbering continues (#84 → #85). No detection
logic changed; `ANALYSIS_VERSION` stays 15.1.0. All prior releases remain live.

## Downloads
`CannaScopeCT-V16.1.1-{Windows,macOS,Linux}.zip` — the self-contained `CannaScope_CT_V16.py` plus the
usual run scripts. Existing users: just run it once and your folder migrates automatically.
