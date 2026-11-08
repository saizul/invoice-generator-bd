import datetime as dt
from decimal import Decimal as D

import pytest

from bd_invoice.models import InvoiceError, parse_invoice, parse_terms_days


def test_parse_ok(data):
    inv = parse_invoice(data)
    assert inv.doc_type == "invoice" and inv.currency == "BDT"
    assert inv.issue_date == dt.date(2026, 3, 1)
    assert inv.items[0].unit_price == D("1500.50")
    assert inv.vat_percent == D(15)


def test_due_date_from_net_terms(data):
    assert parse_invoice(data).due_date == dt.date(2026, 3, 16)


def test_explicit_due_date_wins(data):
    data["due_date"] = "2026-04-01"
    assert parse_invoice(data).due_date == dt.date(2026, 4, 1)


def test_due_days_without_terms(data):
    data.pop("payment_terms")
    data["due_days"] = 7
    assert parse_invoice(data).due_date == dt.date(2026, 3, 8)


def test_due_on_receipt(data):
    data["payment_terms"] = "Due on receipt"
    assert parse_invoice(data).due_date == dt.date(2026, 3, 1)


def test_due_before_issue_rejected(data):
    data["due_date"] = "2026-02-01"
    with pytest.raises(InvoiceError, match="before"):
        parse_invoice(data)


def test_yaml_date_objects_accepted(data):
    data["issue_date"] = dt.date(2026, 5, 5)
    assert parse_invoice(data).issue_date == dt.date(2026, 5, 5)


def test_bad_date(data):
    data["issue_date"] = "05/03/2026"
    with pytest.raises(InvoiceError, match="issue_date"):
        parse_invoice(data)


@pytest.mark.parametrize(
    "text,days", [("Net 15", 15), ("Due in 30 days", 30), ("on receipt", 0), ("whenever", None)]
)
def test_parse_terms_days(text, days):
    assert parse_terms_days(text) == days


def test_quotation_valid_until(data):
    data["type"] = "quotation"
    data["valid_days"] = 10
    inv = parse_invoice(data)
    assert inv.valid_until == dt.date(2026, 3, 11) and inv.due_date is None
    assert inv.title == "QUOTATION"


def test_quotation_default_30_days(data):
    data["type"] = "quotation"
    assert parse_invoice(data).valid_until == dt.date(2026, 3, 31)


def test_missing_seller(data):
    del data["seller"]
    with pytest.raises(InvoiceError, match="seller"):
        parse_invoice(data)


def test_missing_buyer_name(data):
    data["buyer"] = {"email": "x@y.z"}
    with pytest.raises(InvoiceError, match="name"):
        parse_invoice(data)


@pytest.mark.parametrize("items", [None, [], "nope"])
def test_items_required(data, items):
    data["items"] = items
    with pytest.raises(InvoiceError, match="items"):
        parse_invoice(data)


def test_negative_price_rejected(data):
    data["items"][0]["unit_price"] = -5
    with pytest.raises(InvoiceError):
        parse_invoice(data)


def test_item_requires_description(data):
    data["items"][0]["description"] = " "
    with pytest.raises(InvoiceError, match="description"):
        parse_invoice(data)


def test_bad_number_text(data):
    data["items"][0]["quantity"] = "two"
    with pytest.raises(InvoiceError):
        parse_invoice(data)


def test_bad_currency(data):
    data["currency"] = "taka"
    with pytest.raises(InvoiceError, match="currency"):
        parse_invoice(data)


def test_currency_uppercased(data):
    data["currency"] = "usd"
    assert parse_invoice(data).currency == "USD"


def test_bad_theme_and_type(data):
    data["theme"] = "neon"
    with pytest.raises(InvoiceError, match="theme"):
        parse_invoice(data)
    data["theme"] = "modern"
    data["type"] = "receipt"
    with pytest.raises(InvoiceError, match="type"):
        parse_invoice(data)


def test_bad_accent(data):
    data["accent"] = "red"
    with pytest.raises(InvoiceError, match="accent"):
        parse_invoice(data)


def test_discount_validation(data):
    data["discount"] = {"type": "percent", "value": 120}
    with pytest.raises(InvoiceError, match="100"):
        parse_invoice(data)
    data["discount"] = {"type": "weird", "value": 1}
    with pytest.raises(InvoiceError, match="type"):
        parse_invoice(data)


def test_discount_none_when_absent(data):
    assert parse_invoice(data).discount is None


def test_withholding_validation(data):
    data["ait_percent"] = 5
    data["ait_base"] = "gross"
    with pytest.raises(InvoiceError, match="base"):
        parse_invoice(data)


def test_withholdings_list(data):
    data["withholdings"] = [{"label": "VDS", "percent": 7.5, "base": "total"}]
    inv = parse_invoice(data)
    assert inv.withholdings[0].label == "VDS" and inv.withholdings[0].percent == D("7.5")


def test_address_string_split_into_lines(data):
    assert parse_invoice(data).buyer.address == ["5 Avenue", "Dhaka"]


def test_tax_id_alias_bin(data):
    data["seller"]["bin"] = "123"
    assert parse_invoice(data).seller.tax_id == "123"


def test_number_override_and_explicit(data):
    data["number"] = "X-1"
    assert parse_invoice(data).number == "X-1"
    assert parse_invoice(data, number="Y-2").number == "Y-2"


def test_payment_parsing(data):
    data["payment"] = {"bank": {"bank_name": "B", "empty": ""}, "bkash": "017", "qr": True}
    p = parse_invoice(data).payment
    assert p.bank == {"bank_name": "B"} and p.bkash == "017" and p.qr is True


def test_root_must_be_mapping():
    with pytest.raises(InvoiceError):
        parse_invoice([1, 2])


def test_language_validation(data):
    data["language"] = "fr"
    with pytest.raises(InvoiceError, match="language"):
        parse_invoice(data)


def test_watermark_is_normalised_and_validated():
    from bd_invoice.models import parse_watermark

    assert parse_watermark(None) == ""
    assert parse_watermark("  draft ") == "DRAFT"
    with pytest.raises(InvoiceError, match="at most 20"):
        parse_watermark("x" * 21)
    with pytest.raises(InvoiceError, match="Latin"):
        parse_watermark("পরিশোধিত")
