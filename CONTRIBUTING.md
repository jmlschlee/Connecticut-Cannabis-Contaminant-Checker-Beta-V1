# Contributing

Thanks for helping improve the Connecticut Cannabis Contaminant Checker. This is
a Beta tool and the most valuable contributions are **reports of COAs that parse
incorrectly** — those are how the parser gets more accurate.

## Reporting a parsing problem (most useful)
Open an Issue and include:
1. The **COA registration number** (e.g. `MMBR.0033539`) shown in the report.
2. What the tool reported vs. what the COA actually says (a screenshot of the
   COA row helps a lot).
3. Which lab produced the COA, if you can tell.

There is an issue template for this (`COA parsing issue`).

## Running the tests
The test suite is offline (no network needed) and checks the parsing/flagging
logic against synthetic COA snippets:

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python tests/test_contaminant_checker.py
```

You should see `ALL TESTS PASSED`. Please make sure tests pass before opening a
pull request, and add a test for any parsing fix.

## Code style
- Single-file program, standard library + the three pinned dependencies.
- Keep flags as **leads to verify**, never conclusions — see `DISCLAIMER.md`.
- New analytes follow the `ANALYTE_SPECS` pattern; new lab formats should be
  covered by a test snippet.

## Pull requests
Small, focused PRs are easiest to review. Describe what changed and why, and
reference any related issue.
