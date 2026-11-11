"""CSV batch input: one row per line item, rows grouped into invoices."""

from __future__ import annotations

import copy
import csv
from pathlib import Path

from .models import InvoiceError

GROUP_COLUMN = "invoice"
PARTY_FIELDS = {
    "buyer_name": "name",
    "buyer_name_bn": "name_bn",
    "buyer_address": "address",
    "buyer_email": "email",
    "buyer_phone": "phone",
    "buyer_tax_id": "tax_id",
}
ITEM_FIELDS = ("description", "description_bn", "quantity", "unit_price", "unit", "discount_percent")
DOC_FIELDS = (
    "type", "number", "issue_date", "due_date", "valid_until", "payment_terms", "currency",
    "vat_percent", "ait_percent", "notes", "reference", "theme", "language", "watermark",
    "paid",
)  # fmt: skip


def read_rows(path) -> list:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise InvoiceError("CSV file is empty")
        names = {n.strip() for n in reader.fieldnames if n}
        missing = {"buyer_name", "description", "unit_price"} - names
        if missing:
            raise InvoiceError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        rows = []
        for line_no, raw in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            if any(row.values()):
                row["_line"] = str(line_no)
                rows.append(row)
        return rows


def rows_to_documents(rows: list, profile: dict | None = None) -> list:
    """Group rows by the `invoice` column (or by buyer when absent); merge with profile defaults.

    Returns a list of (label, document dict, first_csv_line).
    """
    groups: dict = {}
    for row in rows:
        key = row.get(GROUP_COLUMN) or row.get("buyer_name")
        groups.setdefault(key, []).append(row)
    docs = []
    for key, members in groups.items():
        first = members[0]
        doc = copy.deepcopy(profile or {})
        buyer = dict(doc.get("buyer") or {})
        for col, field_name in PARTY_FIELDS.items():
            value = first.get(col)
            if value:
                buyer[field_name] = value.replace("|", "\n") if field_name == "address" else value
        doc["buyer"] = buyer
        for col in DOC_FIELDS:
            if first.get(col):
                doc[col] = first[col]
        items = []
        for row in members:
            if not row.get("description"):
                raise InvoiceError(f"CSV line {row['_line']}: description is required")
            item = {f: row[f] for f in ITEM_FIELDS if row.get(f)}
            items.append(item)
        doc["items"] = items
        docs.append((str(key), doc, int(first["_line"])))
    return docs


def load_csv(path, profile: dict | None = None) -> list:
    return rows_to_documents(read_rows(Path(path)), profile)
