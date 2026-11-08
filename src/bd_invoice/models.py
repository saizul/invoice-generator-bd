"""Invoice data model and validation (parsing from plain dicts loaded from YAML/CSV)."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .money import to_decimal

DOC_TYPES = ("invoice", "quotation")
THEMES = ("minimal", "modern")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


class InvoiceError(ValueError):
    """Raised for invalid or incomplete invoice input."""


@dataclass
class Party:
    name: str
    name_bn: str = ""
    address: list = field(default_factory=list)
    email: str = ""
    phone: str = ""
    tax_id: str = ""  # BIN / TIN / VAT registration number
    tax_id_label: str = "BIN"


@dataclass
class LineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal
    unit: str = ""
    discount_percent: Decimal = Decimal(0)
    description_bn: str = ""


@dataclass
class Discount:
    kind: str = "percent"  # "percent" or "fixed"
    value: Decimal = Decimal(0)
    label: str = "Discount"


@dataclass
class Withholding:
    label: str
    percent: Decimal
    base: str = "taxable"  # "taxable" (after discount, before VAT) or "total" (including VAT)


@dataclass
class PaymentInfo:
    bank: dict = field(default_factory=dict)  # free text lines: bank_name, account_name, ...
    bkash: str = ""
    nagad: str = ""
    other: list = field(default_factory=list)
    qr: bool = False
    qr_payload: str = ""  # optional override; default is built from the invoice


@dataclass
class Invoice:
    doc_type: str
    number: str
    issue_date: dt.date
    currency: str
    seller: Party
    buyer: Party
    items: list
    due_date: dt.date | None = None
    valid_until: dt.date | None = None
    payment_terms: str = ""
    discount: Discount | None = None
    vat_percent: Decimal = Decimal(0)
    vat_label: str = "VAT"
    withholdings: list = field(default_factory=list)
    payment: PaymentInfo = field(default_factory=PaymentInfo)
    notes: str = ""
    terms: list = field(default_factory=list)
    theme: str = "minimal"
    accent: str = ""
    logo: str = ""
    language: str = "en"  # "en" or "both" (adds Bangla when a font is supplied)
    reference: str = ""  # buyer PO / reference
    watermark: str = ""  # diagonal page stamp such as PAID or DRAFT

    @property
    def title(self) -> str:
        return "QUOTATION" if self.doc_type == "quotation" else "INVOICE"


def _need(data: dict, key: str, where: str):
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise InvoiceError(f"{where}: '{key}' is required")
    return value


WATERMARK_MAX = 20


def parse_watermark(value) -> str:
    """Normalise a watermark label (upper case, Latin text only, at most 20 characters)."""
    text = str(value or "").strip().upper()
    if len(text) > WATERMARK_MAX:
        raise InvoiceError(f"watermark: at most {WATERMARK_MAX} characters, got {len(text)}")
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        raise InvoiceError("watermark: use Latin characters only (for example PAID or DRAFT)") from None
    return text


def parse_date(value, field_name: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise InvoiceError(f"{field_name}: expected a date like 2026-01-31, got {value!r}")


def _lines(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [ln.strip() for ln in value.splitlines() if ln.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    raise InvoiceError(f"expected text or a list of lines, got {value!r}")


def _decimal(value, name: str, minimum: Decimal | None = None) -> Decimal:
    try:
        result = to_decimal(value, name)
    except ValueError as exc:
        raise InvoiceError(str(exc)) from None
    if minimum is not None and result < minimum:
        raise InvoiceError(f"{name}: must be >= {minimum}, got {result}")
    return result


def parse_party(data, where: str) -> Party:
    if not isinstance(data, dict):
        raise InvoiceError(f"{where}: expected a mapping")
    return Party(
        name=str(_need(data, "name", where)).strip(),
        name_bn=str(data.get("name_bn") or "").strip(),
        address=_lines(data.get("address")),
        email=str(data.get("email") or "").strip(),
        phone=str(data.get("phone") or "").strip(),
        tax_id=str(data.get("tax_id") or data.get("bin") or "").strip(),
        tax_id_label=str(data.get("tax_id_label") or "BIN").strip(),
    )


def parse_item(data, index: int) -> LineItem:
    where = f"items[{index}]"
    if not isinstance(data, dict):
        raise InvoiceError(f"{where}: expected a mapping")
    return LineItem(
        description=str(_need(data, "description", where)).strip(),
        quantity=_decimal(data.get("quantity", 1), f"{where}.quantity", Decimal(0)),
        unit_price=_decimal(_need(data, "unit_price", where), f"{where}.unit_price", Decimal(0)),
        unit=str(data.get("unit") or "").strip(),
        description_bn=str(data.get("description_bn") or "").strip(),
        discount_percent=_decimal(data.get("discount_percent", 0), f"{where}.discount_percent", Decimal(0)),
    )


def parse_discount(data) -> Discount | None:
    if data in (None, "", 0):
        return None
    if not isinstance(data, dict):
        raise InvoiceError("discount: expected a mapping with 'type' and 'value'")
    kind = str(data.get("type", "percent")).lower()
    if kind not in ("percent", "fixed"):
        raise InvoiceError("discount.type must be 'percent' or 'fixed'")
    value = _decimal(data.get("value", 0), "discount.value", Decimal(0))
    if kind == "percent" and value > 100:
        raise InvoiceError("discount.value: a percentage cannot exceed 100")
    return Discount(kind, value, str(data.get("label") or "Discount"))


def parse_withholdings(data: dict) -> list:
    out = []
    if data.get("ait_percent") not in (None, "", 0, "0"):
        pct = _decimal(data["ait_percent"], "ait_percent", Decimal(0))
        base = str(data.get("ait_base", "taxable")).lower()
        out.append(Withholding("AIT", pct, base))
    for i, raw in enumerate(data.get("withholdings") or []):
        where = f"withholdings[{i}]"
        if not isinstance(raw, dict):
            raise InvoiceError(f"{where}: expected a mapping")
        out.append(
            Withholding(
                str(_need(raw, "label", where)),
                _decimal(_need(raw, "percent", where), f"{where}.percent", Decimal(0)),
                str(raw.get("base", "taxable")).lower(),
            )
        )
    for w in out:
        if w.base not in ("taxable", "total"):
            raise InvoiceError(f"withholding '{w.label}': base must be 'taxable' or 'total'")
        if w.percent > 100:
            raise InvoiceError(f"withholding '{w.label}': percent cannot exceed 100")
    return out


def parse_payment(data) -> PaymentInfo:
    if not data:
        return PaymentInfo()
    if not isinstance(data, dict):
        raise InvoiceError("payment: expected a mapping")
    bank = data.get("bank") or {}
    if not isinstance(bank, dict):
        raise InvoiceError("payment.bank: expected a mapping of label -> value")
    return PaymentInfo(
        bank={str(k): str(v) for k, v in bank.items() if v not in (None, "")},
        bkash=str(data.get("bkash") or "").strip(),
        nagad=str(data.get("nagad") or "").strip(),
        other=_lines(data.get("other")),
        qr=bool(data.get("qr", False)),
        qr_payload=str(data.get("qr_payload") or "").strip(),
    )


def parse_terms_days(text: str) -> int | None:
    """'Net 15' / 'Due in 30 days' -> 15 / 30; 'Due on receipt' -> 0."""
    lowered = text.lower()
    if "receipt" in lowered or "immediate" in lowered:
        return 0
    m = re.search(r"(\d+)", lowered)
    return int(m.group(1)) if m else None


def parse_invoice(data: dict, number: str | None = None) -> Invoice:
    """Validate a plain dict (from YAML) and build an Invoice. `number` overrides data['number']."""
    if not isinstance(data, dict):
        raise InvoiceError("document root must be a mapping")
    doc_type = str(data.get("type", "invoice")).lower()
    if doc_type not in DOC_TYPES:
        raise InvoiceError(f"type must be one of {DOC_TYPES}, got {doc_type!r}")
    currency = str(data.get("currency", "BDT")).upper()
    if not CURRENCY_RE.match(currency):
        raise InvoiceError(f"currency must be a 3-letter code, got {currency!r}")
    theme = str(data.get("theme", "minimal")).lower()
    if theme not in THEMES:
        raise InvoiceError(f"theme must be one of {THEMES}, got {theme!r}")
    accent = str(data.get("accent") or "")
    if accent and not HEX_RE.match(accent):
        raise InvoiceError(f"accent must be a hex colour like #1f6feb, got {accent!r}")
    language = str(data.get("language", "en")).lower()
    if language not in ("en", "both"):
        raise InvoiceError("language must be 'en' or 'both'")

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise InvoiceError("items: at least one line item is required")
    items = [parse_item(it, i) for i, it in enumerate(raw_items)]

    issue = parse_date(data.get("issue_date", dt.date.today()), "issue_date")
    terms = str(data.get("payment_terms") or "").strip()
    due = valid = None
    if doc_type == "invoice":
        if data.get("due_date"):
            due = parse_date(data["due_date"], "due_date")
        else:
            days = parse_terms_days(terms) if terms else None
            if days is None and data.get("due_days") is not None:
                days = int(_decimal(data["due_days"], "due_days", Decimal(0)))
            if days is not None:
                due = issue + dt.timedelta(days=days)
        if due is not None and due < issue:
            raise InvoiceError("due_date cannot be before issue_date")
    else:
        if data.get("valid_until"):
            valid = parse_date(data["valid_until"], "valid_until")
        else:
            days = int(_decimal(data.get("valid_days", 30), "valid_days", Decimal(0)))
            valid = issue + dt.timedelta(days=days)

    final_number = number or str(data.get("number") or "").strip()
    return Invoice(
        doc_type=doc_type,
        number=final_number,
        issue_date=issue,
        currency=currency,
        seller=parse_party(_need(data, "seller", "document"), "seller"),
        buyer=parse_party(_need(data, "buyer", "document"), "buyer"),
        items=items,
        due_date=due,
        valid_until=valid,
        payment_terms=terms,
        discount=parse_discount(data.get("discount")),
        vat_percent=_decimal(data.get("vat_percent", 0), "vat_percent", Decimal(0)),
        vat_label=str(data.get("vat_label") or "VAT"),
        withholdings=parse_withholdings(data),
        payment=parse_payment(data.get("payment")),
        notes=str(data.get("notes") or "").strip(),
        terms=_lines(data.get("terms")),
        theme=theme,
        accent=accent,
        logo=str(data.get("logo") or "").strip(),
        language=language,
        reference=str(data.get("reference") or "").strip(),
        watermark=parse_watermark(data.get("watermark")),
    )
