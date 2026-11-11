import datetime as dt
from decimal import Decimal

import pytest
import yaml

from bd_invoice.batch import load_csv
from bd_invoice.calc import compute_totals
from bd_invoice.cli import main
from bd_invoice.models import InvoiceError, Payment, parse_invoice, parse_payments
from bd_invoice.pdf import render_invoice

pypdf = pytest.importorskip("pypdf")

D = Decimal

# The shared fixture totals 4,000.00 + 15% VAT = 4,600.00.


def pdf_text(path):
    reader = pypdf.PdfReader(str(path))
    return "\n".join(p.extract_text() or "" for p in reader.pages).replace("\n", " ")


def write_yaml(tmp_path, data):
    p = tmp_path / "inv.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def run(tmp_path, data, *extra):
    src = write_yaml(tmp_path, data)
    out = tmp_path / "out.pdf"
    code = main(["generate", str(src), "-o", str(out), "--counter-file", str(tmp_path / "c.json"), *extra])
    return code, out


# -- parsing ---------------------------------------------------------------


def test_no_payments_by_default(data):
    assert parse_invoice(data).payments == []


def test_paid_shorthand(data):
    data["paid"] = "1,000.50"
    (p,) = parse_invoice(data).payments
    assert p == Payment(D("1000.50")) and p.label == "Paid"


def test_payments_list_with_details(data):
    data["payments"] = [
        {"date": "2026-03-05", "amount": 1000, "method": "bKash", "reference": "TXN123"},
        {"amount": "500", "method": "Cash"},
    ]
    undated, dated = parse_invoice(data).payments
    assert undated.amount == D(500) and undated.label == "Paid (Cash)"
    assert dated.date == dt.date(2026, 3, 5)
    assert dated.label == "Paid 2026-03-05 (bKash, TXN123)"


def test_payments_sorted_by_date_and_bare_numbers(data):
    data["payments"] = [{"date": "2026-03-20", "amount": 300}, {"date": dt.date(2026, 3, 2), "amount": 200}, 100]
    assert [p.amount for p in parse_invoice(data).payments] == [D(100), D(200), D(300)]


def test_paid_and_payments_combine_and_zero_is_dropped(data):
    data["paid"] = 0
    data["payments"] = [{"amount": 250}, {"amount": 0}]
    assert [p.amount for p in parse_invoice(data).payments] == [D(250)]


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"paid": -5}, "paid: must be >= 0"),
        ({"paid": "lots"}, "not a valid number"),
        ({"paid": {"amount": 5}}, "paid: expected an amount"),
        ({"payments": "500"}, "payments: expected a list"),
        ({"payments": [{"method": "bKash"}]}, "payments[0]: 'amount' is required"),
        ({"payments": [{"amount": -1}]}, "payments[0].amount: must be >= 0"),
        ({"payments": [{"amount": 1, "date": "soon"}]}, "payments[0].date"),
    ],
)
def test_invalid_payment_input(data, patch, message):
    data.update(patch)
    with pytest.raises(InvoiceError) as exc:
        parse_invoice(data)
    assert message in str(exc.value)


def test_quotations_cannot_record_payments(data):
    data.update(type="quotation", paid=100)
    with pytest.raises(InvoiceError, match="only invoices"):
        parse_invoice(data)


def test_parse_payments_empty_values():
    assert parse_payments({}) == []
    assert parse_payments({"paid": "", "payments": None}) == []


# -- arithmetic ------------------------------------------------------------


def test_totals_without_payments(invoice):
    t = compute_totals(invoice)
    assert t.paid == 0 and t.balance_due == t.net_payable == D("4600.00")
    assert t.payments == [] and t.payment_status == "unpaid"


def test_partial_payment_balance(data):
    data["payments"] = [{"amount": 1000, "method": "bKash"}, {"amount": "600.005"}]
    t = compute_totals(parse_invoice(data))
    assert t.paid == D("1600.01")  # each payment is rounded half up to 2 places
    assert t.balance_due == D("2999.99") and t.payment_status == "partial"
    assert t.payments == [("Paid (bKash)", D("1000.00")), ("Paid", D("600.01"))]


def test_balance_is_after_withholdings(data):
    data.update(ait_percent=5, paid=1400)
    t = compute_totals(parse_invoice(data))
    assert t.net_payable == D("4400.00") and t.balance_due == D("3000.00")


def test_paid_in_full(data):
    data["paid"] = 4600
    t = compute_totals(parse_invoice(data))
    assert t.balance_due == 0 and t.payment_status == "paid"


def test_overpayment_is_rejected(data):
    data["paid"] = "4600.01"
    inv = parse_invoice(data)
    with pytest.raises(InvoiceError, match="more than the net payable 4600.00"):
        compute_totals(inv)


# -- PDF -------------------------------------------------------------------


def test_pdf_shows_payment_rows_and_balance(data, tmp_path):
    data["payments"] = [{"date": "2026-03-05", "amount": 1000, "method": "bKash"}, {"amount": 600}]
    inv = parse_invoice(data)
    inv.number = "INV-9"
    out = tmp_path / "o.pdf"
    render_invoice(inv, out)
    text = pdf_text(out)
    assert "Paid 2026-03-05 (bKash)" in text and "-BDT 1,000.00" in text and "-BDT 600.00" in text
    assert "Balance due" in text and "3,000.00" in text
    assert "BALANCE DUE IN WORDS" in text and "Taka Three Thousand Only" in text
    assert "Four Thousand Six Hundred" not in text


def test_pdf_many_payments_are_summarised(data, tmp_path):
    data["payments"] = [{"amount": 100, "method": f"M{i}"} for i in range(5)]
    inv = parse_invoice(data)
    inv.number = "INV-9"
    out = tmp_path / "o.pdf"
    render_invoice(inv, out)
    text = pdf_text(out)
    assert "Paid (5 payments)" in text and "-BDT 500.00" in text and "M3" not in text
    assert "4,100.00" in text


def test_pdf_paid_in_full_words(data, tmp_path):
    data["paid"] = 4600
    inv = parse_invoice(data)
    inv.number = "INV-9"
    out = tmp_path / "o.pdf"
    render_invoice(inv, out)
    text = pdf_text(out)
    assert "AMOUNT PAID IN WORDS" in text and "Taka Four Thousand Six Hundred Only" in text
    assert "Balance due" in text and "BDT 0.00" in text


def test_pdf_without_payments_is_unchanged(invoice, tmp_path):
    out = tmp_path / "o.pdf"
    render_invoice(invoice, out)
    text = pdf_text(out)
    assert "Balance due" not in text and "AMOUNT PAYABLE IN WORDS" in text


def test_qr_payload_uses_balance_due(data):
    from bd_invoice.pdf import Renderer

    data["paid"] = 600
    inv = parse_invoice(data)
    inv.number = "INV-9"
    assert "AMT:4000.00|" in Renderer(inv, compute_totals(inv), None).qr_payload()


# -- CLI and batch ---------------------------------------------------------


def test_cli_paid_amount(data, tmp_path, capsys):
    code, out = run(tmp_path, data, "--paid", "1,600")
    assert code == 0
    assert "balance due BDT 3,000.00" in capsys.readouterr().out
    assert "Balance due" in pdf_text(out)


def test_cli_paid_adds_to_yaml_payments(data, tmp_path, capsys):
    data["paid"] = 600
    code, _ = run(tmp_path, data, "--paid", "1000")
    assert code == 0 and "balance due BDT 3,000.00" in capsys.readouterr().out


def test_cli_paid_full_settles_the_rest(data, tmp_path, capsys):
    data["paid"] = 600
    code, out = run(tmp_path, data, "--paid", "full", "--watermark", "PAID")
    assert code == 0 and "paid in full" in capsys.readouterr().out
    text = pdf_text(out)
    assert "-BDT 4,000.00" in text and "AMOUNT PAID IN WORDS" in text


def test_cli_report_unchanged_without_payments(data, tmp_path, capsys):
    code, _ = run(tmp_path, data)
    out = capsys.readouterr().out
    assert code == 0 and "balance due" not in out and "paid in full" not in out


@pytest.mark.parametrize("value", ["abc", "-5", "99999"])
def test_cli_bad_paid_fails_without_spending_a_number(data, tmp_path, capsys, value):
    code, out = run(tmp_path, data, f"--paid={value}")
    assert code == 2 and not out.exists() and not (tmp_path / "c.json").exists()
    assert "error:" in capsys.readouterr().err


def test_cli_paid_rejected_for_quotation(data, tmp_path, capsys):
    data["type"] = "quotation"
    code, _ = run(tmp_path, data, "--paid", "100")
    assert code == 2 and "only invoices" in capsys.readouterr().err


def test_batch_paid_column(tmp_path):
    p = tmp_path / "in.csv"
    p.write_text(
        "invoice,buyer_name,description,unit_price,paid\nA,Acme,Task,1000,250\nB,Beta,Task,500,\n",
        encoding="utf-8",
    )
    docs = load_csv(p, {"seller": {"name": "S"}})
    first, second = (compute_totals(parse_invoice(doc)) for _, doc, _ in docs)
    assert first.balance_due == D("750.00") and first.payment_status == "partial"
    assert second.payments == [] and second.balance_due == D("500.00")
