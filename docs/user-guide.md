# User Guide — CannaScope Beta V5

## Install & run (release package)

1. Download the ZIP for your OS from the [Releases](../../releases) page:
   - `CannaScope_Beta_V5_Windows.zip`
   - `CannaScope_Beta_V5_macOS.zip`
   - `CannaScope_Beta_V5_Linux.zip`
2. Unzip it.
3. Run the launcher:
   - **Windows:** double-click `run.bat`
   - **macOS / Linux:** `./run.sh`

The launcher creates a local virtual environment, installs dependencies, and runs the tool. **Python 3.10+** must be installed.

## Run from source

```bash
pip install -r requirements.txt
python cannascope_beta_v5.py
```

## Options

| Flag | Description |
|---|---|
| `--days N` | Look-back window in days (default 60). |
| `--since YYYY-MM-DD` | Explicit start date (overrides `--days`). |
| `--forms {flower,inhalable,all}` | Product types to scan (default `all`). |
| `--limit N` | Cap COAs scanned (quick test). |
| `--workers N` | Concurrency (default 16; use 8–12 if you hit OCR issues). |
| `--refresh-registry` | Force a fresh registry download. |

Examples:

```bash
python cannascope_beta_v5.py --days 365            # one-year report
python cannascope_beta_v5.py --forms flower        # flower only
python cannascope_beta_v5.py --since 2026-01-01    # from a specific date
```

## Outputs

Written to `CannaScope Beta V5 - Reports/`, with the report also copied to the working folder as **`CannaScope_Beta_V5_Report.pdf`**:

- `CannaScope_Beta_V5_Report.pdf` — the report
- `severity_*.csv` — per-contaminant ranked tables
- `high_thc_flower_noninfused.csv`, `infused_extract_potency_reference.csv`
- `producer_dba_identity_confidence.csv` — identity + source confidence
- `coa_verification_queue.csv`, `zero_result_verification_queue.csv`
- `self_audit.csv`, `debug_log.csv` / `.json`
- `CannaScope_Beta_V5_Validated_Flagged.csv`, full per-product scan

## Reading the report

The report is **findings-first**. Read it top to bottom:

1. **Cover** — version, status, dataset window, summary counts, color legend.
2. **Executive Summary** — the top discoveries at a glance (heavy metals, microbial, high cannabinoid, producer & lab patterns, possible remediation).
3. **Top Findings** — the most significant validated results.
4. **Producer / Lab Trends.**
5. **Per-contaminant Findings** — each with full numeric context and clickable COAs.
6. **High Cannabinoid, Infused/Extract, Possible Remediation, Lower-Concern.**
7. **No Significant Findings.**
8. **Validation & Diagnostics** (at the end) — how everything was checked.

Every finding row links to its COA. **Always verify a finding against the source COA before drawing any conclusion.** See [`../DISCLAIMER.md`](../DISCLAIMER.md).

## Troubleshooting

- **A scanned COA won't read:** install OCR — `pip install ocrmac` (macOS) or `pip install pytesseract` plus the `tesseract` binary.
- **Rare crash on a scanned COA under high concurrency:** lower `--workers` (e.g. `--workers 8`) and re-run; already-scanned clean COAs are remembered and skipped.
- **Gated COA downloads:** some COAs may require a session; re-run, or supply browser cookies with `--cookies cookies.txt`.
