from decimal import Decimal as D

import pytest

from bd_invoice.calc import compute_line, compute_totals
from bd_invoice.models import Discount, LineItem, Withholding, parse_invoice


def test_basic_totals(invoice):
    t = compute_totals(invoice)
    assert t.subtotal == D("4000.00")  # 2 x 1500.50 + 999
    assert t.vat == D("600.00")
    assert t.total == D("4600.00")
    assert t.net_payable == D("4600.00")


def test_line_rounding_per_line():
    line = compute_line(LineItem("x", D("3"), D("0.335")))
    assert line.gross == D("1.01")  # 1.005 -> 1.01


def test_decimal_exactness_no_float_noise(data):
    data["items"] = [{"description": "x", "quantity": 3, "unit_price": 0.1}]
    data["vat_percent"] = 0
    assert compute_totals(parse_invoice(data)).total == D("0.30")


def test_fractional_quantity(data):
    data["items"] = [{"description": "hours", "quantity": "2.5", "unit_price": 1200}]
    data["vat_percent"] = 0
    assert compute_totals(parse_invoice(data)).subtotal == D("3000.00")


def test_line_discount_percent(data):
    data["items"] = [{"description": "x", "quantity": 1, "unit_price": 1000, "discount_percent": 12.5}]
    t = compute_totals(parse_invoice(data))
    assert t.lines[0].discount == D("125.00")
    assert t.subtotal == D("875.00")


def test_discount_percent_before_vat(invoice):
    invoice.discount = Discount("percent", D(10))
    t = compute_totals(invoice)
    assert t.discount == D("400.00")
    assert t.taxable == D("3600.00")
    assert t.vat == D("540.00")
    assert t.total == D("4140.00")


def test_discount_fixed(invoice):
    invoice.discount = Discount("fixed", D("250.50"))
    t = compute_totals(invoice)
    assert t.taxable == D("3749.50")
    assert t.vat == D("562.43")  # 562.425 -> half up


def test_discount_fixed_capped_at_subtotal(invoice):
    invoice.discount = Discount("fixed", D(99999))
    t = compute_totals(invoice)
    assert t.discount == t.subtotal
    assert t.total == D("0.00")


def test_vat_rounding_half_up(data):
    data["items"] = [{"description": "x", "quantity": 1, "unit_price": "37051.90"}]
    t = compute_totals(parse_invoice(data))
    assert t.vat == D("5557.79")


def test_zero_vat(data):
    data["vat_percent"] = 0
    t = compute_totals(parse_invoice(data))
    assert t.vat == D("0.00") and t.total == t.subtotal


def test_ait_on_taxable_amount(data):
    data["ait_percent"] = 5
    t = compute_totals(parse_invoice(data))
    assert t.deductions == [("AIT", D(5), D("200.00"))]
    assert t.net_payable == D("4400.00")


def test_ait_on_total_base(data):
    data["ait_percent"] = 5
    data["ait_base"] = "total"
    t = compute_totals(parse_invoice(data))
    assert t.deductions[0][2] == D("230.00")


def test_ait_after_discount(data):
    data["ait_percent"] = 10
    data["discount"] = {"type": "percent", "value": 50}
    t = compute_totals(parse_invoice(data))
    assert t.taxable == D("2000.00")
    assert t.deductions[0][2] == D("200.00")


def test_multiple_withholdings(invoice):
    invoice.withholdings = [Withholding("AIT", D(5)), Withholding("VDS", D("7.5"), "total")]
    t = compute_totals(invoice)
    assert t.deduction_total == D("200.00") + D("345.00")
    assert t.net_payable == D("4600.00") - D("545.00")


def test_totals_are_two_places(invoice):
    t = compute_totals(invoice)
    for value in (t.subtotal, t.vat, t.total, t.net_payable):
        assert value == value.quantize(D("0.01"))


def test_sum_of_lines_equals_subtotal(invoice):
    t = compute_totals(invoice)
    assert sum(ln.net for ln in t.lines) == t.subtotal


@pytest.mark.parametrize("pct,expected", [("15", "150.00"), ("7.5", "75.00"), ("0.5", "5.00")])
def test_vat_percentages(data, pct, expected):
    data["items"] = [{"description": "x", "quantity": 1, "unit_price": 1000}]
    data["vat_percent"] = pct
    assert compute_totals(parse_invoice(data)).vat == D(expected)
