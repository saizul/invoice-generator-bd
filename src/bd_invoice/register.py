"""Sales register (a CSV ledger of issued documents) and a receivables summary built from it.

Every document generated with `--register FILE` appends one row. The register is plain CSV so it
opens in a spreadsheet, can be handed to an accountant for the monthly VAT return, and is read back
by `bd-invoice summary` to report sales, VAT, withholdings and outstanding balances by age.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .calc import ZERO, Totals
from .models import Invoice, InvoiceError

COLUMNS = (
    "number", "type", "issue_date", "due_date", "buyer", "buyer_tax_id", "reference", "currency",
    "subtotal", "discount", "taxable", "vat", "total", "deductions", "net_payable", "paid",
    "balance_due", "status", "file",
)  # fmt: skip
AMOUNT_COLUMNS = ("subtotal", "discount", "taxable", "vat", "total", "deductions", "net_payable", "paid")
AGING_BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")
# Spreadsheets run cells starting with these characters as formulas (CSV injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def register_row(inv: Invoice, totals: Totals, path: str = "") -> dict:
    """One register row for a rendered document (amounts as plain 2-decimal strings)."""
    due = inv.due_date if inv.doc_type == "invoice" else inv.valid_until
    status = totals.payment_status if inv.doc_type == "invoice" else "quotation"
    row = {
        "number": _cell(inv.number),
        "type": inv.doc_type,
        "issue_date": inv.issue_date.isoformat(),
        "due_date": due.isoformat() if due else "",
        "buyer": _cell(inv.buyer.name),
        "buyer_tax_id": _cell(inv.buyer.tax_id),
        "reference": _cell(inv.reference),
        "currency": inv.currency,
        "subtotal": f"{totals.subtotal:.2f}",
        "discount": f"{totals.discount:.2f}",
        "taxable": f"{totals.taxable:.2f}",
        "vat": f"{totals.vat:.2f}",
        "total": f"{totals.total:.2f}",
        "deductions": f"{totals.deduction_total:.2f}",
        "net_payable": f"{totals.net_payable:.2f}",
        "paid": f"{totals.paid:.2f}",
        "balance_due": f"{totals.balance_due:.2f}",
        "status": status,
        "file": _cell(os.path.basename(path)) if path else "",
    }
    return row


def _read_header(path: Path) -> list | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return next(csv.reader(fh), None)


def append_rows(path, rows: list) -> int:
    """Append rows to the register, writing the header when the file is new or empty.

    Refuses to write to an existing file whose header does not match, so a typo in `--register`
    cannot scribble register rows into an unrelated CSV.
    """
    if not rows:
        return 0
    target = Path(path)
    header = _read_header(target)
    if header is not None and tuple(h.strip() for h in header) != COLUMNS:
        raise InvoiceError(
            f"{target}: not a bd-invoice register (unexpected header); use a new file for --register"
        )
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        if header is None:
            writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in COLUMNS})
    return len(rows)


@dataclass
class RegisterEntry:
    number: str
    doc_type: str
    issue_date: dt.date
    due_date: dt.date | None
    buyer: str
    currency: str
    amounts: dict  # column -> Decimal
    balance_due: Decimal
    line: int

    def days_overdue(self, as_of: dt.date) -> int:
        if self.due_date is None or self.balance_due <= 0:
            return 0
        return max((as_of - self.due_date).days, 0)


def _parse_amount(text: str, column: str, line: int) -> Decimal:
    raw = (text or "").strip().replace(",", "") or "0"
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise InvoiceError(f"register line {line}: {column} {text!r} is not a number") from None
    if not value.is_finite():
        raise InvoiceError(f"register line {line}: {column} {text!r} is not a number")
    return value


def _parse_iso(text: str, column: str, line: int, required: bool) -> dt.date | None:
    text = (text or "").strip()
    if not text:
        if required:
            raise InvoiceError(f"register line {line}: {column} is required")
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise InvoiceError(f"register line {line}: {column} {text!r} is not a date (YYYY-MM-DD)") from None


def read_register(path) -> list:
    """Read a register back. Later rows for the same document number and type replace earlier ones
    (re-issuing an invoice after recording a payment updates its balance)."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"{target}: register not found")
    with open(target, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise InvoiceError(f"{target}: register is empty")
        missing = {"number", "type", "issue_date", "currency", "net_payable"} - {
            n.strip() for n in reader.fieldnames if n
        }
        if missing:
            raise InvoiceError(f"{target}: register is missing columns: {', '.join(sorted(missing))}")
        latest: dict = {}
        for line, raw in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k}
            if not any(row.values()):
                continue
            doc_type = row.get("type", "invoice").lower() or "invoice"
            if doc_type not in ("invoice", "quotation"):
                raise InvoiceError(f"register line {line}: unknown type {doc_type!r}")
            amounts = {c: _parse_amount(row.get(c, ""), c, line) for c in AMOUNT_COLUMNS}
            balance_text = row.get("balance_due", "")
            balance = (
                _parse_amount(balance_text, "balance_due", line)
                if balance_text
                else amounts["net_payable"] - amounts["paid"]
            )
            entry = RegisterEntry(
                number=row.get("number", ""),
                doc_type=doc_type,
                issue_date=_parse_iso(row.get("issue_date", ""), "issue_date", line, True),
                due_date=_parse_iso(row.get("due_date", ""), "due_date", line, False),
                buyer=row.get("buyer", ""),
                currency=(row.get("currency") or "BDT").upper(),
                amounts=amounts,
                balance_due=balance,
                line=line,
            )
            latest.pop((entry.number, doc_type), None)  # keep file order of the latest version
            latest[(entry.number, doc_type)] = entry
        return list(latest.values())


def aging_bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1-30"
    if days_overdue <= 60:
        return "31-60"
    if days_overdue <= 90:
        return "61-90"
    return "90+"


@dataclass
class CurrencySummary:
    currency: str
    invoices: int = 0
    quotations: int = 0
    totals: dict = field(default_factory=lambda: {c: ZERO for c in AMOUNT_COLUMNS})
    outstanding: Decimal = ZERO
    overdue: Decimal = ZERO
    aging: dict = field(default_factory=lambda: {b: ZERO for b in AGING_BUCKETS})
    overdue_documents: list = field(default_factory=list)  # [(number, buyer, days, balance)]

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "invoices": self.invoices,
            "quotations": self.quotations,
            **{k: f"{v:.2f}" for k, v in self.totals.items()},
            "outstanding": f"{self.outstanding:.2f}",
            "overdue": f"{self.overdue:.2f}",
            "aging": {k: f"{v:.2f}" for k, v in self.aging.items()},
            "overdue_documents": [
                {"number": n, "buyer": b, "days_overdue": d, "balance_due": f"{bal:.2f}"}
                for n, b, d, bal in self.overdue_documents
            ],
        }


def summarize(
    entries: list,
    as_of: dt.date,
    start: dt.date | None = None,
    end: dt.date | None = None,
) -> list:
    """Totals per currency for invoices issued in [start, end]; quotations are only counted.

    Aging uses days past the due date as of `as_of`; invoices without a due date are 'current'.
    """
    if start and end and start > end:
        raise InvoiceError("summary: --from must not be after --to")
    out: dict = {}
    for e in entries:
        if (start and e.issue_date < start) or (end and e.issue_date > end):
            continue
        s = out.setdefault(e.currency, CurrencySummary(e.currency))
        if e.doc_type == "quotation":
            s.quotations += 1
            continue
        s.invoices += 1
        for c in AMOUNT_COLUMNS:
            s.totals[c] += e.amounts[c]
        if e.balance_due > 0:
            s.outstanding += e.balance_due
            days = e.days_overdue(as_of)
            s.aging[aging_bucket(days)] += e.balance_due
            if days > 0:
                s.overdue += e.balance_due
                s.overdue_documents.append((e.number, e.buyer, days, e.balance_due))
    for s in out.values():
        s.overdue_documents.sort(key=lambda d: (-d[2], d[0]))
    return [out[k] for k in sorted(out)]
