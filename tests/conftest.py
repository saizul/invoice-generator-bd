import copy
import datetime as dt
import os
from pathlib import Path

import pytest

from bd_invoice.models import parse_invoice

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

BASE = {
    "type": "invoice",
    "currency": "BDT",
    "issue_date": "2026-03-01",
    "payment_terms": "Net 15",
    "vat_percent": 15,
    "seller": {"name": "Test Agency", "address": ["1 Road", "Dhaka"], "email": "a@test.example"},
    "buyer": {"name": "Test Client", "address": "5 Avenue\nDhaka"},
    "items": [
        {"description": "Service A", "quantity": 2, "unit_price": "1500.50"},
        {"description": "Service B", "quantity": 1, "unit_price": 999},
    ],
}


@pytest.fixture()
def data():
    return copy.deepcopy(BASE)


@pytest.fixture()
def invoice(data):
    inv = parse_invoice(data)
    inv.number = "INV-2026-0001"
    return inv


@pytest.fixture()
def examples_dir():
    return EXAMPLES


@pytest.fixture()
def bangla_font():
    """Path to a Bangla TTF for rendering tests; set BD_INVOICE_TEST_FONT to enable them."""
    path = os.environ.get("BD_INVOICE_TEST_FONT")
    if not path or not os.path.isfile(path):
        pytest.skip("set BD_INVOICE_TEST_FONT to a Bangla .ttf to run Bangla rendering tests")
    pytest.importorskip("uharfbuzz")
    return path


def make_date(y, m, d):
    return dt.date(y, m, d)
