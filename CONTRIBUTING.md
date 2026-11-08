# Contributing

Thanks for helping improve bd-invoice.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Before opening a pull request

- `ruff check .` and `ruff format .` pass.
- `pytest` passes. New behaviour needs tests. Money logic must stay `Decimal`-based with explicit rounding;
  add a rounding test for any new calculation.
- To run the Bangla rendering tests, download a static Bangla TTF yourself (for example Noto Sans Bengali,
  OFL) and run `BD_INVOICE_TEST_FONT=/path/to/font.ttf pytest`. Never commit font files.
- Keep Python 3.10-3.13 supported (CI runs all four).
- Example data must be synthetic: no real names, bank accounts, phone numbers or BIN/TIN values.

## Scope

In scope: layout, calculations, numbering, Bangla/English wording, input formats.
Out of scope: tax advice, bundled fonts, online payment integrations.

## Reporting issues

Include the YAML (with private data removed), the command, and the warning text the tool printed.
