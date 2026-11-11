# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Payments received: `paid` / `payments` fields, a `--paid AMOUNT|full` option and a `paid` CSV column.
  The PDF lists each payment under the totals and shows the balance due (in figures, in words and in the
  QR reference); overpayments are rejected before a number is issued.
- `watermark` field and `--watermark TEXT` option: a diagonal PAID / DRAFT / VOID stamp on every page.

## [0.1.0] - 2026-11-08

### Added
- `bd-invoice` CLI: `generate`, `batch`, `words`, `number`, `sample`.
- PDF invoices and quotations (A4) with `minimal` and `modern` themes, logo support, multi-page tables.
- Decimal-based calculations: line and document discounts, VAT, AIT/withholding lines, net payable.
- Amount in words in English and Bangla with the lakh/crore system, including paisa.
- BDT South Asian digit grouping; USD, EUR, GBP and other currencies.
- Invoice numbering patterns with a local counter file and yearly/monthly/never reset.
- Bank, bKash and Nagad text payment block and optional QR code (`qrcode` extra).
- Bangla rendering from a user supplied TTF with HarfBuzz shaping (`bangla` extra); English-only fallback.
- CSV batch mode with a shared YAML profile.
- Test suite, ruff configuration and GitHub Actions CI (Python 3.10-3.13).
