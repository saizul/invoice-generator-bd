"""Invoice arithmetic with Decimal and explicit rounding (ROUND_HALF_UP to 2 places)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .models import Invoice, InvoiceError
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
    payments: list = field(default_factory=list)  # [(label, amount)] in date order
    paid: Decimal = ZERO
    balance_due: Decimal = ZERO

    @property
    def payment_status(self) -> str:
        """'unpaid', 'partial' or 'paid' (an invoice with nothing to pay counts as unpaid)."""
        if not self.paid:
            return "unpaid"
        return "paid" if self.balance_due == ZERO else "partial"


def compute_line(item) -> LineResult:
    gross = round_money(item.quantity * item.unit_price)
    discount = percent_of(gross, item.discount_percent) if item.discount_percent else ZERO
    return LineResult(
        item.description, item.quantity, item.unit_price, item.unit, gross, discount, gross - discount
    )


def compute_totals(inv: Invoice) -> Totals:
    """Subtotal -> discount -> VAT on the discounted amount -> withholdings -> net payable.

    Payments already received are then taken off the net payable to give the balance due.
    Raises InvoiceError when the payments add up to more than the net payable.
    """
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
    net_payable = total - deduction_total

    payments = [(p.label, round_money(p.amount)) for p in inv.payments]
    paid = sum((amount for _, amount in payments), ZERO)
    if paid > net_payable:
        raise InvoiceError(
            f"payments: {paid} received is more than the net payable {net_payable}; "
            "check the amounts or issue a refund/credit separately"
        )
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
        net_payable=net_payable,
        payments=payments,
        paid=paid,
        balance_due=net_payable - paid,
    )
