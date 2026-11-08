"""Command line interface: bd-invoice."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from . import __version__
from .batch import load_csv
from .models import InvoiceError, parse_invoice, parse_watermark
from .numbering import (
    DEFAULT_PATTERN,
    QUOTE_PATTERN,
    RESETS,
    NumberingError,
    next_number,
    peek_number,
)
from .pdf import render_invoice
from .words import amount_in_words

DEFAULT_COUNTER = ".bd-invoice-counter.json"
FONT_ENV = "BD_INVOICE_BANGLA_FONT"

SAMPLE_YAML = """\
type: invoice                  # or: quotation
currency: BDT                  # BDT, USD, EUR, GBP ...
issue_date: 2026-03-01
payment_terms: Net 15          # due date = issue date + 15 days (or set due_date)
theme: modern                  # minimal | modern
# watermark: DRAFT             # optional diagonal stamp on every page (PAID, DRAFT ...)
language: en                   # en | both (adds Bangla when --bangla-font is given)
vat_percent: 15
ait_percent: 5                 # Advance Income Tax withheld by the client
seller:
  name: Example Digital Agency
  address: [House 1, Road 2, Dhanmondi, Dhaka 1209]
  email: billing@example.com
  phone: "+880 1700-000000"
  tax_id: "0000000000000"
buyer:
  name: Sample Client Ltd.
  address: [Plot 5, Gulshan Avenue, Dhaka 1212]
items:
  - description: SEO audit and keyword research
    quantity: 1
    unit_price: 25000
  - description: Monthly content writing
    quantity: 4
    unit: articles
    unit_price: 3500.50
discount: {type: percent, value: 5, label: Loyalty discount}
payment:
  bank: {bank_name: Example Bank PLC, account_name: Example Digital Agency, account_number: "0000000000"}
  bkash: "01700-000000 (Merchant)"
  qr: true
notes: Thank you for your business.
"""


def _font_from(args, data: dict | None = None) -> str | None:
    return args.bangla_font or os.environ.get(FONT_ENV) or (data or {}).get("bangla_font") or None


def _load_yaml(path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise InvoiceError(f"{path}: invalid YAML ({exc.__class__.__name__})") from None
    if not isinstance(data, dict):
        raise InvoiceError(f"{path}: expected a YAML mapping at the top level")
    return data


def safe_filename(number: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", number).strip("._") or "invoice"


def assign_number(data: dict, args) -> tuple:
    """Return (number, issued_from_counter). An explicit `number` in the data always wins."""
    explicit = str(data.get("number") or "").strip()
    if explicit:
        return explicit, False
    numbering = data.get("numbering") or {}
    doc_type = str(data.get("type", "invoice")).lower()
    default = QUOTE_PATTERN if doc_type == "quotation" else DEFAULT_PATTERN
    pattern = args.number_pattern or numbering.get("pattern") or default
    reset = args.reset or numbering.get("reset") or "yearly"
    issue = data.get("issue_date") or dt.date.today()
    if isinstance(issue, str):
        issue = dt.date.fromisoformat(issue)
    if isinstance(issue, dt.datetime):
        issue = issue.date()
    fn = peek_number if args.no_count else next_number
    return fn(args.counter_file, pattern, reset, issue), not args.no_count


def build_one(data: dict, args, out_path: str | None, base_dir: str) -> tuple:
    inv = parse_invoice(data)  # validate before spending a counter value
    number, _ = assign_number(data, args)
    inv.number = number
    if args.theme:
        inv.theme = args.theme
    if args.watermark:
        inv.watermark = parse_watermark(args.watermark)
    target = out_path or str(Path(args.out_dir or ".") / f"{safe_filename(number)}.pdf")
    result = render_invoice(inv, target, _font_from(args, data), base_dir)
    return inv, result


def report(inv, result, out) -> None:
    from .money import format_money

    t = result.totals
    print(
        f"wrote {result.path}  [{inv.number}  {format_money(t.net_payable, inv.currency)}  "
        f"{result.pages} page(s)]",
        file=out,
    )
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)


def cmd_generate(args) -> int:
    data = _load_yaml(args.file)
    inv, result = build_one(data, args, args.output, str(Path(args.file).resolve().parent))
    report(inv, result, sys.stdout)
    return 0


def cmd_batch(args) -> int:
    profile = _load_yaml(args.profile) if args.profile else {}
    docs = load_csv(args.file, profile)
    base = str(Path(args.profile or args.file).resolve().parent)
    failures = 0
    for label, data, line in docs:
        try:
            inv, result = build_one(data, args, None, base)
            report(inv, result, sys.stdout)
        except (InvoiceError, NumberingError, ValueError) as exc:
            failures += 1
            print(f"error: invoice '{label}' (CSV line {line}): {exc}", file=sys.stderr)
    print(f"{len(docs) - failures} generated, {failures} failed")
    return 1 if failures else 0


def cmd_words(args) -> int:
    try:
        amount = Decimal(args.amount.replace(",", ""))
    except InvalidOperation:
        print(f"error: {args.amount!r} is not a number", file=sys.stderr)
        return 2
    langs = ["en", "bn"] if args.lang == "both" else [args.lang]
    try:
        for lang in langs:
            print(amount_in_words(amount, args.currency, lang))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_number(args) -> int:
    pattern = args.number_pattern or DEFAULT_PATTERN
    reset = args.reset or "yearly"
    fn = peek_number if args.peek else next_number
    print(fn(args.counter_file, pattern, reset, dt.date.today()))
    return 0


def cmd_sample(args) -> int:
    sys.stdout.write(SAMPLE_YAML)
    return 0


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--counter-file", default=DEFAULT_COUNTER, help="JSON file holding invoice counters")
    p.add_argument("--number-pattern", help=f"numbering pattern (default {DEFAULT_PATTERN})")
    p.add_argument("--reset", choices=RESETS, help="counter reset period (default yearly)")
    p.add_argument("--no-count", action="store_true", help="peek the number, do not advance the counter")
    p.add_argument("--bangla-font", help=f"path to a Bangla TTF (or set {FONT_ENV})")
    p.add_argument("--theme", choices=("minimal", "modern"), help="override the theme")
    p.add_argument(
        "--watermark", metavar="TEXT", help="diagonal stamp on every page, e.g. PAID or DRAFT (overrides the YAML)"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bd-invoice", description="PDF invoices and quotations for Bangladesh.")
    p.add_argument("--version", action="version", version=f"bd-invoice {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="create one PDF from a YAML file")
    g.add_argument("file")
    g.add_argument("-o", "--output", help="output PDF path (default: <number>.pdf)")
    g.add_argument("--out-dir", help="directory for the default file name")
    add_common(g)
    g.set_defaults(func=cmd_generate)

    b = sub.add_parser("batch", help="create many PDFs from a CSV (one row per line item)")
    b.add_argument("file", help="CSV file")
    b.add_argument("--profile", help="YAML with seller, payment and defaults shared by all invoices")
    b.add_argument("--out-dir", default="invoices", help="output directory")
    add_common(b)
    b.set_defaults(func=cmd_batch)

    w = sub.add_parser("words", help="spell an amount in words")
    w.add_argument("amount")
    w.add_argument("--currency", default="BDT")
    w.add_argument("--lang", choices=("en", "bn", "both"), default="both")
    w.set_defaults(func=cmd_words)

    n = sub.add_parser("number", help="issue (or --peek) the next invoice number")
    n.add_argument("--peek", action="store_true")
    n.add_argument("--counter-file", default=DEFAULT_COUNTER)
    n.add_argument("--number-pattern")
    n.add_argument("--reset", choices=RESETS)
    n.set_defaults(func=cmd_number)

    s = sub.add_parser("sample", help="print a sample invoice YAML")
    s.set_defaults(func=cmd_sample)
    return p


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (InvoiceError, NumberingError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
