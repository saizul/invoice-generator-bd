"""Invoice arithmetic with Decimal and explicit rounding (ROUND_HALF_UP to 2 places)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .models import Invoice
from .money import percent_of, round_money

ZERO = Decimal("0.00")


@dataclass
class LineResult:
    description: str
    quantity: Decimal
    unit_price: Decimal
    unit: str
    gross: Decimal  # quantity x unit price
    discount: Decimal  # line-level discount amount
    net: Decimal  # gross - discount


@dataclass
class Totals:
    lines: list = field(default_factory=list)
    subtotal: Decimal = ZERO
    discount: Decimal = ZERO
    taxable: Decimal = ZERO
    vat_percent: Decimal = ZERO
    vat: Decimal = ZERO
    total: Decimal = ZERO
    deductions: list = field(default_factory=list)  # [(label, percent, amount)]
    deduction_total: Decimal = ZERO
    net_payable: Decimal = ZERO


def compute_line(item) -> LineResult:
    gross = round_money(item.quantity * item.unit_price)
    discount = percent_of(gross, item.discount_percent) if item.discount_percent else ZERO
    return LineResult(
        item.description, item.quantity, item.unit_price, item.unit, gross, discount, gross - discount
    )


def compute_totals(inv: Invoice) -> Totals:
    """Subtotal -> discount -> VAT on the discounted amount -> withholdings -> net payable."""
    lines = [compute_line(i) for i in inv.items]
    subtotal = sum((ln.net for ln in lines), ZERO)

    discount = ZERO
    if inv.discount is not None:
        if inv.discount.kind == "percent":
            discount = percent_of(subtotal, inv.discount.value)
        else:
            discount = min(round_money(inv.discount.value), subtotal)
    taxable = subtotal - discount
    vat = percent_of(taxable, inv.vat_percent) if inv.vat_percent else ZERO
    total = taxable + vat

    deductions = []
    for w in inv.withholdings:
        base = total if w.base == "total" else taxable
        deductions.append((w.label, w.percent, percent_of(base, w.percent)))
    deduction_total = sum((d[2] for d in deductions), ZERO)
    return Totals(
        lines=lines,
        subtotal=subtotal,
        discount=discount,
        taxable=taxable,
        vat_percent=inv.vat_percent,
        vat=vat,
        total=total,
        deductions=deductions,
        deduction_total=deduction_total,
        net_payable=total - deduction_total,
    )
