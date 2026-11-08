from decimal import Decimal as D

import pytest

from bd_invoice.money import (
    format_money,
    format_number,
    group_digits,
    percent_of,
    round_money,
    to_decimal,
)


def test_to_decimal_int_and_str():
    assert to_decimal(5) == D(5)
    assert to_decimal("1,250.75") == D("1250.75")
    assert to_decimal(" 3 ") == D(3)


def test_to_decimal_float_uses_repr_not_binary_noise():
    assert to_decimal(0.1) == D("0.1")
    assert to_decimal(2.675) == D("2.675")


@pytest.mark.parametrize("bad", ["abc", "", "1.2.3", "NaN", "Infinity", None, True, [1]])
def test_to_decimal_rejects_garbage(bad):
    with pytest.raises(ValueError):
        to_decimal(bad)


@pytest.mark.parametrize(
    "raw,expected",
    [("0.005", "0.01"), ("0.004", "0.00"), ("2.675", "2.68"), ("1.005", "1.01"),
     ("-0.005", "-0.01"), ("10", "10.00"), ("99.994", "99.99"), ("99.995", "100.00")],
)  # fmt: skip
def test_round_money_half_up(raw, expected):
    assert round_money(D(raw)) == D(expected)


def test_percent_of_rounds_half_up():
    assert percent_of(D("37051.90"), D(15)) == D("5557.79")  # 5557.785 -> .79
    assert percent_of(D("100"), D("2.5")) == D("2.50")


@pytest.mark.parametrize(
    "digits,south,expected",
    [("1", True, "1"), ("999", True, "999"), ("1000", True, "1,000"), ("100000", True, "1,00,000"),
     ("1234567", True, "12,34,567"), ("123456789", True, "12,34,56,789"),
     ("1234567", False, "1,234,567"), ("100", False, "100")],
)  # fmt: skip
def test_group_digits(digits, south, expected):
    assert group_digits(digits, south) == expected


def test_format_number_bdt_south_asian():
    assert format_number(D("1234567.5"), "BDT") == "12,34,567.50"


def test_format_number_usd_western():
    assert format_number(D("1234567.5"), "USD") == "1,234,567.50"


def test_format_number_negative_and_zero():
    assert format_number(D("-1500"), "BDT") == "-1,500.00"
    assert format_number(D(0), "USD") == "0.00"


def test_format_money_bdt_without_font_uses_code():
    assert format_money(D("999"), "BDT") == "BDT 999.00"


def test_format_money_bdt_with_unicode_symbol():
    assert format_money(D("999"), "BDT", unicode_ok=True) == "৳999.00"


def test_format_money_usd_symbol_and_unknown_code():
    assert format_money(D("12.5"), "USD") == "$12.50"
    assert format_money(D("12.5"), "AUD") == "AUD 12.50"
