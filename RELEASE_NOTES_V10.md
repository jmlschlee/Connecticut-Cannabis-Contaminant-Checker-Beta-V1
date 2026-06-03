# CannaScope CT — Beta V10

**What it is.** A Connecticut-focused cannabis testing & compliance analysis tool. It ingests
Connecticut's public cannabis product registry and each product's Certificate of Analysis
(COA), parses the mandated contaminant panels (heavy metals, pesticides, microbials/mold,
mycotoxins, residual solvents) plus cannabinoids, evaluates each result against the Connecticut
action limit, and generates source-verified PDF reports with clickable COA links throughout.
*Every flag is a lead, not a conclusion.*

## Existing features (carried into V10)
- **"Potential Statute & Regulatory Flags to Evaluate"** section — COA-grounded testing /
  product-quality leads (a result over the legal limit, a pathogen reported detected, a panel
  FAIL) plus a potency-label reconciliation, each a human-review flag with a cited authority
  (chapter/rule level, marked *verify in eRegulations*) and a clickable COA link. *Flags to
  investigate, not legal determinations.*
- **"CT Cannabis Ombudsman — Medical Patient Safety Review"** section (for the Office of the
  Cannabis Ombudsman, Public Act 23-79) — products that *passed* testing but came closest to a
  CT action limit, ranked by margin and grouped by contaminant class, advisory and
  patient-centered. *Not medical advice.*
- **COA dates + live clickable COA links** on referenced product lines, with an explicit
  "Missing — Verify" fallback rather than dead links.
- Multi-lab COA parsing (Northeast Laboratories, AltaSci, Analytics Labs, Advanced Grow Labs)
  with field-aware extraction; below-detection / limit / LOQ / LOD values are never published
  as measurements; offline source bundle; numbered, never-overwritten reports.
- *Reserved / dormant:* a broader Compliance Screening Engine and an Environmental Linkage
  module exist in-code as Phase-2 designs but are intentionally **not wired in** (no resolved
  rule corpus / data pipelines yet) and change nothing about parsing or current reports.

## New in V10 Beta
- **Patient-Reported Product Concern — Personalized Analysis PDF.** A separate, on-demand
  report a patient can request about a single product. From any identifiers they have (product
  name, batch, NDC, UID / BioTrack lot, COA number, dates, QR/COA link), the tool resolves the
  product against the CT product registry and its COA, runs the same near-/over-limit and
  statute/regulatory-flag logic, **surfaces identifier discrepancies** (e.g. a label NDC that
  doesn't match the registry record), and **links related/sibling COAs from the same producer**
  — same strain and product type, closest in time — each with a **live clickable COA link** and
  its own flags, so a patient can compare batches (for example, a re-tested or re-released one).
  Output is written as
  `Patient_Reported_Product_Concern_Personalized_Analysis_<batch>_<timestamp>.pdf` to
  `output/patient_concerns/` and never overwrites a prior file. It is **advisory and
  non-diagnostic** — it does not claim a product caused any health issue, is not medical advice,
  and points patients to a healthcare provider plus the Office of the Cannabis Ombudsman and the
  Department of Consumer Protection.

Run it with:
```
python3 CannaScope_CT_Beta_V10.py patient-concern --ndc <NDC> --batch <BATCH> --qr <URL>
python3 CannaScope_CT_Beta_V10.py patient-concern --example   # built-in demo
```

## Downloads
- `CannaScope CT Beta V10 - Windows.zip`
- `CannaScope CT Beta V10 - macOS.zip`
- `CannaScope CT Beta V10 - Linux.zip`

Each contains the single self-contained `CannaScope_CT_Beta_V10.py` plus a launcher, README,
INSTALL guide, LICENSE, and requirements. **Windows:** unzip → `run.bat`. **macOS / Linux:**
unzip → `./run.sh`. Or run directly: `python3 CannaScope_CT_Beta_V10.py --days 90`. All prior
releases remain available, unchanged.

## Notes
- The repository was renamed to **`CannaScope-CT`** (stable name). The GitHub redirect from the
  prior name is preserved, so existing clones and links keep working. The release — not the
  repository — carries the version.

## Beta notice
Pre-release for evaluation. Compliance and patient outputs are review aids, **not legal or
medical advice**; confirm any cited authority against eRegulations.ct.gov and have a qualified
compliance officer or attorney validate flags before acting.
