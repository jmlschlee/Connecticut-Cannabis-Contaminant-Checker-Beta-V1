# CannaScope CT — V9 Beta

> This is an *additive* release: every prior version below remains live and downloadable, unchanged. V9 is the current release.

## What CannaScope CT is

A Connecticut-focused cannabis testing and transparency tool. It ingests Connecticut's public cannabis product registry and each product's **live Certificate of Analysis (COA)**, parses the state-mandated contaminant panels — **heavy metals, pesticides, microbials/mold, mycotoxins, residual solvents** — plus cannabinoids, evaluates each result against the applicable **Connecticut action/legal limit**, and generates a structured, source-verified **PDF report** (with CSV exports). Every published value is traceable to the actual result field on the COA, and every finding links back to the source document.

*Guiding principle: every flag is a **lead, not a conclusion** — verify every product against its live COA.*

## History (from this repo)

- **Beta V1** — initial Connecticut contaminant checker.
- **V2 / V3 / V4** — expanded parsing, flagging, and report structure.
- **Beta V5** — public-facing baseline: Testing-Date column, CT Legal Limit / CannaScope Limit / CT % of Limit columns, Producer & Lab Trends, High-Cannabinoid review, Infused/Extract potency reference, Possible-Remediation review, clickable COA links, honest PASS / PASS WITH WARNINGS / DRAFT / FAIL status.
- **V6.1** — three-category product taxonomy (flower / infused / vape-concentrate, kept strictly separate), per-line-item COA verification (anti-hallucination), implausible-value rejection, crash-proof isolated OCR.
- **V7.2** — self-contained single-file build (engine embedded), offline/bundled-sources mode, overwrite-proof sequential report numbering.
- **(V8.x, accuracy line)** — field-aware COA extraction across lab/year formats (Northeast Labs columnar layouts in both orders, AltaSci power-of-ten detection limits, Analytics Labs OCR), ND/limit/LOQ/LOD never published as measurements, regulatory-limit matches routed to manual review. *(Carried into V9.)*

All prior releases remain available on the Releases page.

## New in V9 Beta

- **Compliance Screening Engine.** Screens lab data against Connecticut cannabis law and surfaces *potential* statutory/regulatory matters. Authority set: **CGS Chapter 420h** (Regulation of Adult-Use Cannabis / RERACA), **CGS Chapter 420f** (Palliative Use of Marijuana), the **DCP Policies & Procedures** (edition effective Nov. 12, 2024, which carry the full force of law), **RCSA Sec. 21a-408**, and the relevant **Public Acts** amendment layer — to be resolved against **eRegulations.ct.gov**. Each item is a *review flag* with a cited authority (marked for verification), status (likely / potential / insufficient data), severity, confidence, and recommended next step. **Flags to investigate, not legal determinations.**

- **"Potential Statute & Regulatory Flags to Evaluate" PDF section.** Rendered near the end of every report. Covers what is derivable from the COA: a result **over the Connecticut legal limit**, a **detected zero-tolerance pathogen**, a **failed pesticide/residual-solvent panel**, and **high-cannabinoid potency-label checks** (reconciles 0.877×THCA + Δ9-THC against the reported Total THC; flags implausible flower potency). Each flag carries the cited authority (chapter/rule level, marked `authority_unverified` since exact section text must be confirmed in eRegulations), a clickable COA link, status/severity/next-step, and a plain-language explanation. If there are no flags, it says so explicitly. Categories needing licensing/operational data (diversion, labeling, security, recordkeeping, transport) are noted as not assessed.

- **CT Cannabis Ombudsman — Medical Patient Safety Review section.** A patient-safety section for Connecticut's independent Office of the Cannabis Ombudsman (established by **Public Act 23-79**). It surfaces products that **passed** testing but came **closest to a Connecticut action limit** on any contaminant — ranked by margin-to-limit across heavy metals, pesticides, microbials/mold, mycotoxins, and residual solvents, grouped by class, with a tunable closeness threshold (default **80%** of the limit), closeness tiers, per-class patient notes, and clickable COA links. **Advisory patient-awareness information — not a finding that a passing product is unsafe, and not medical advice.**

## Downloads

Pre-built, self-contained bundles (each = the single-file program + an OS launcher + quick-start + license; no build step):

| OS | File | Launch |
|---|---|---|
| 🪟 Windows | `CannaScopeCT-v9.0.0-beta-windows.zip` | unzip → double-click `run.bat` |
| 🍎 macOS | `CannaScopeCT-v9.0.0-beta-macos.zip` | unzip → right-click `run.command` → Open |
| 🐧 Linux | `CannaScopeCT-v9.0.0-beta-linux.zip` | unzip → `chmod +x run.sh && ./run.sh` |

All prior releases remain available unchanged.

## Important notice

The compliance and ombudsman outputs are **review aids, not legal or medical advice and not an adjudication**. Confirm every citation against eRegulations.ct.gov and have a qualified compliance officer or attorney validate flags before acting; verify every product against its official, live COA.
