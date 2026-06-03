# CannaScope CT Beta V9.1

> Current release of the V9 line. **Additive:** every prior version remains live and downloadable, unchanged.

## What CannaScope CT is

A Connecticut-focused cannabis testing and transparency tool. It ingests Connecticut's public cannabis product registry and each product's **live Certificate of Analysis (COA)**, parses the state-mandated contaminant panels — **heavy metals, pesticides, microbials/mold, mycotoxins, residual solvents** — plus cannabinoids, evaluates each result against the applicable **Connecticut action/legal limit**, and generates a structured, source-verified **PDF report** (with CSV exports) where every published value traces to the actual result field on the COA. *Every flag is a lead, not a conclusion.*

## V9 line — feature set

- **Compliance Screening + "Potential Statute & Regulatory Flags to Evaluate" PDF section** — potential Connecticut statutory/regulatory matters derived from the COA (result over the CT legal limit, detected zero-tolerance pathogen, failed pesticide/solvent panel) plus high-cannabinoid potency-label reconciliation (0.877×THCA + Δ9 vs reported Total THC). Each is a review flag with a cited authority (CGS Ch. 420h/420f, DCP P&P eff. 2024-11-12, RCSA 21a-408, Public Acts — marked for verification in eRegulations), status/severity/confidence/next-step, and a clickable COA link. Flags to investigate, **not legal determinations**.
- **CT Cannabis Ombudsman — Medical Patient Safety Review PDF section** — products that **passed** testing but came closest to a CT action limit, ranked by margin across all contaminant classes (tunable threshold, default 80%), with closeness tiers, per-class patient notes, and clickable COA links. Advisory; **not medical advice**.
- Carries the full accuracy engine: field-aware COA extraction across lab/year formats, ND/limit/LOQ/LOD never published as measurements, regulatory-limit matches routed to manual review, crash-isolated OCR, offline/bundled-sources mode, overwrite-proof report numbering.

## What's V9.1

A consolidation point release: the program self-identifies as **CannaScope CT Beta V9.1**, the repository is renamed to match, and the downloads are refreshed under the V9.1 name. No detection-logic changes from V9.0.

## Downloads

| OS | File | Launch |
|---|---|---|
| 🪟 Windows | `CannaScopeCT-v9.1.0-beta-windows.zip` | unzip → double-click `run.bat` |
| 🍎 macOS | `CannaScopeCT-v9.1.0-beta-macos.zip` | unzip → right-click `run.command` → Open |
| 🐧 Linux | `CannaScopeCT-v9.1.0-beta-linux.zip` | unzip → `chmod +x run.sh && ./run.sh` |

All prior releases (V9.0, V7.2, V6.1, V5, V4, V3, V2, Beta V1) remain available unchanged.

## Notice

Compliance and ombudsman outputs are **review aids, not legal or medical advice and not an adjudication**. Confirm citations against eRegulations.ct.gov, have a qualified compliance officer or attorney validate flags, and verify every product against its official, live COA.
