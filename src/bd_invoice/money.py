"""Decimal money helpers: rounding, South Asian / western digit grouping, symbols."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
SOUTH_ASIAN_CURRENCIES = frozenset({"BDT", "INR", "NPR", "PKR", "LKR"})

# Symbols that exist in the standard PDF fonts (WinAnsi). BDT's symbol needs a Bangla font.
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}
BDT_SYMBOL = "৳"


def to_decimal(value, field: str = "value") -> Decimal:
    """Convert numbers/strings (commas allowed) to Decimal; never goes through float math."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError(f"{field}: expected a number, got {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            result = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"{field}: {value!r} is not a valid number") from None
        if not result.is_finite():
            raise ValueError(f"{field}: {value!r} is not a finite number")
        return result
    raise ValueError(f"{field}: expected a number, got {value!r}")


def round_money(value: Decimal) -> Decimal:
    """Round to 2 decimal places, halves away from zero (the usual invoicing convention)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def percent_of(base: Decimal, percent: Decimal) -> Decimal:
    return round_money(base * percent / Decimal(100))


def group_digits(integer_part: str, south_asian: bool) -> str:
    """Group a string of digits: 1234567 -> 12,34,567 (south asian) or 1,234,567."""
    if len(integer_part) <= 3:
        return integer_part
    if not south_asian:
        parts = []
        s = integer_part
        while len(s) > 3:
            parts.append(s[-3:])
            s = s[:-3]
        parts.append(s)
        return ",".join(reversed(parts))
    head, tail = integer_part[:-3], integer_part[-3:]
    parts = []
    while len(head) > 2:
        parts.append(head[-2:])
        head = head[:-2]
    if head:
        parts.append(head)
    return ",".join(reversed(parts)) + "," + tail


def is_south_asian(currency: str) -> bool:
    return currency.upper() in SOUTH_ASIAN_CURRENCIES


def format_number(value: Decimal, currency: str = "BDT") -> str:
    """Format with two decimals and currency-appropriate grouping, no symbol."""
    value = round_money(value)
    sign = "-" if value < 0 else ""
    text = f"{abs(value):f}"
    integer, _, frac = text.partition(".")
    frac = (frac + "00")[:2]
    return f"{sign}{group_digits(integer, is_south_asian(currency))}.{frac}"


def currency_label(currency: str, unicode_ok: bool = False) -> str:
    """Prefix shown before amounts: a symbol where one can be drawn, else the ISO code."""
    cur = currency.upper()
    if cur == "BDT":
        return BDT_SYMBOL if unicode_ok else "BDT"
    return SYMBOLS.get(cur, cur)


def format_money(value: Decimal, currency: str = "BDT", unicode_ok: bool = False) -> str:
    label = currency_label(currency, unicode_ok)
    sep = "" if len(label) == 1 else " "
    return f"{label}{sep}{format_number(value, currency)}"
