import csv
import datetime as dt
import json
from decimal import Decimal

import pytest
import yaml

from bd_invoice.calc import compute_totals
from bd_invoice.cli import main
from bd_invoice.models import InvoiceError, parse_invoice
from bd_invoice.register import (
    COLUMNS,
    aging_bucket,
    append_rows,
    read_register,
    register_row,
    summarize,
)


def write_yaml(tmp_path, data, name="inv.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def entry_row(number, issue, due, net, paid="0", doc_type="invoice", currency="BDT", buyer="Acme"):
    net_d, paid_d = Decimal(net), Decimal(paid)
    return {
        "number": number,
        "type": doc_type,
        "issue_date": issue,
        "due_date": due,
        "buyer": buyer,
        "currency": currency,
        "subtotal": net,
        "taxable": net,
        "total": net,
        "net_payable": net,
        "paid": paid,
        "balance_due": f"{net_d - paid_d:.2f}",
    }


def test_register_row_amounts(invoice):
    invoice.buyer.tax_id = "123"
    totals = compute_totals(invoice)
    row = register_row(invoice, totals, "/tmp/out/INV-2026-0001.pdf")
    assert row["number"] == "INV-2026-0001"
    assert row["issue_date"] == "2026-03-01" and row["due_date"] == "2026-03-16"
    # 2 x 1500.50 + 999 = 4000.00; VAT 15% = 600.00
    assert row["taxable"] == "4000.00" and row["vat"] == "600.00" and row["total"] == "4600.00"
    assert row["balance_due"] == "4600.00" and row["status"] == "unpaid"
    assert row["buyer_tax_id"] == "123" and row["file"] == "INV-2026-0001.pdf"
    assert set(row) == set(COLUMNS)


def test_register_row_quotation_uses_valid_until(data):
    data["type"] = "quotation"
    inv = parse_invoice(data)
    inv.number = "QT-1"
    row = register_row(inv, compute_totals(inv))
    assert row["status"] == "quotation" and row["due_date"] == "2026-03-31"


def test_register_row_neutralises_formulas(invoice):
    invoice.buyer.name = '=HYPERLINK("http://x")'
    invoice.reference = "+1\nsecond line"
    row = register_row(invoice, compute_totals(invoice))
    assert row["buyer"].startswith("'=")
    assert row["reference"] == "'+1 second line"


def test_append_writes_header_once(tmp_path, invoice):
    reg = tmp_path / "sub" / "register.csv"
    row = register_row(invoice, compute_totals(invoice))
    append_rows(reg, [row])
    append_rows(reg, [row])
    lines = reg.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(COLUMNS)
    assert len(lines) == 3


def test_append_refuses_foreign_csv(tmp_path, invoice):
    other = tmp_path / "clients.csv"
    other.write_text("name,email\nA,a@test.example\n", encoding="utf-8")
    with pytest.raises(InvoiceError, match="not a bd-invoice register"):
        append_rows(other, [register_row(invoice, compute_totals(invoice))])
    assert other.read_text(encoding="utf-8") == "name,email\nA,a@test.example\n"


def test_append_nothing_is_noop(tmp_path):
    assert append_rows(tmp_path / "r.csv", []) == 0
    assert not (tmp_path / "r.csv").exists()


def test_read_register_latest_row_wins(tmp_path):
    reg = tmp_path / "r.csv"
    append_rows(
        reg,
        [
            entry_row("INV-1", "2026-01-01", "2026-01-15", "1000.00"),
            entry_row("INV-2", "2026-01-05", "2026-01-20", "500.00"),
            entry_row("INV-1", "2026-01-01", "2026-01-15", "1000.00", paid="400.00"),
        ],
    )
    entries = read_register(reg)
    assert [e.number for e in entries] == ["INV-2", "INV-1"]
    assert entries[1].balance_due == Decimal("600.00")


def test_read_register_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_register(tmp_path / "missing.csv")
    bad = tmp_path / "bad.csv"
    bad.write_text("foo\n1\n", encoding="utf-8")
    with pytest.raises(InvoiceError, match="missing columns"):
        read_register(bad)
    reg = tmp_path / "r.csv"
    append_rows(reg, [entry_row("INV-1", "2026-13-01", "", "10")])
    with pytest.raises(InvoiceError, match="line 2: issue_date"):
        read_register(reg)
    reg2 = tmp_path / "r2.csv"
    bad_amount = entry_row("INV-1", "2026-01-01", "", "10")
    bad_amount["net_payable"] = "ten"
    append_rows(reg2, [bad_amount])
    with pytest.raises(InvoiceError, match="not a number"):
        read_register(reg2)


@pytest.mark.parametrize(
    "days,bucket",
    [(-5, "current"), (0, "current"), (1, "1-30"), (30, "1-30"), (31, "31-60"), (61, "61-90"), (91, "90+")],
)
def test_aging_bucket(days, bucket):
    assert aging_bucket(days) == bucket


def test_summarize_aging_and_currencies(tmp_path):
    reg = tmp_path / "r.csv"
    append_rows(
        reg,
        [
            entry_row("INV-1", "2026-01-01", "2026-01-15", "1000.00"),  # 45 days overdue
            entry_row("INV-2", "2026-02-01", "2026-02-20", "500.00", paid="200.00"),  # 9 days overdue
            entry_row("INV-3", "2026-02-20", "2026-03-10", "300.00"),  # not yet due
            entry_row("INV-4", "2026-02-21", "", "250.00", paid="250.00"),  # paid
            entry_row("QT-1", "2026-02-22", "2026-03-22", "9999.00", doc_type="quotation"),
            entry_row("INV-5", "2026-01-10", "2025-10-01", "80.00", currency="USD"),  # 151 days
        ],
    )
    as_of = dt.date(2026, 3, 1)
    bdt, usd = summarize(read_register(reg), as_of)
    assert bdt.currency == "BDT" and usd.currency == "USD"
    assert bdt.invoices == 4 and bdt.quotations == 1
    assert bdt.totals["net_payable"] == Decimal("2050.00")
    assert bdt.totals["paid"] == Decimal("450.00")
    assert bdt.outstanding == Decimal("1600.00")
    assert bdt.overdue == Decimal("1300.00")
    assert bdt.aging == {
        "current": Decimal("300.00"),
        "1-30": Decimal("300.00"),
        "31-60": Decimal("1000.00"),
        "61-90": Decimal("0.00"),
        "90+": Decimal("0.00"),
    }
    assert [d[0] for d in bdt.overdue_documents] == ["INV-1", "INV-2"]
    assert usd.aging["90+"] == Decimal("80.00")


def test_summarize_period_filter(tmp_path):
    reg = tmp_path / "r.csv"
    append_rows(
        reg,
        [
            entry_row("INV-1", "2026-01-01", "", "100.00"),
            entry_row("INV-2", "2026-02-01", "", "200.00"),
            entry_row("INV-3", "2026-03-01", "", "300.00"),
        ],
    )
    entries = read_register(reg)
    (only,) = summarize(entries, dt.date(2026, 3, 31), dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    assert only.invoices == 1 and only.totals["net_payable"] == Decimal("200.00")
    assert summarize(entries, dt.date(2026, 3, 31), dt.date(2027, 1, 1)) == []
    with pytest.raises(InvoiceError, match="--from"):
        summarize(entries, dt.date(2026, 3, 31), dt.date(2026, 3, 1), dt.date(2026, 2, 1))


def test_generate_appends_to_register(data, tmp_path, capsys):
    pytest.importorskip("pypdf")
    src = write_yaml(tmp_path, data)
    reg = tmp_path / "register.csv"
    common = ["--out-dir", str(tmp_path), "--counter-file", str(tmp_path / "c.json"), "--register", str(reg)]
    assert main(["generate", str(src), *common]) == 0
    assert main(["generate", str(src), *common, "--paid", "1000"]) == 0
    got = rows(reg)
    assert [r["number"] for r in got] == ["INV-2026-0001", "INV-2026-0002"]
    assert got[1]["paid"] == "1000.00" and got[1]["status"] == "partial"
    assert got[0]["file"] == "INV-2026-0001.pdf"


def test_rejected_document_is_not_registered(data, tmp_path):
    src = write_yaml(tmp_path, data)
    reg = tmp_path / "register.csv"
    code = main(["generate", str(src), "--no-count", "--register", str(reg), "--paid", "999999"])
    assert code == 2 and not reg.exists()


def test_batch_registers_each_success(tmp_path, capsys):
    pytest.importorskip("pypdf")
    profile = write_yaml(tmp_path, {"seller": {"name": "S"}, "vat_percent": 15}, "profile.yaml")
    csv_path = tmp_path / "in.csv"
    csv_path.write_text(
        "invoice,buyer_name,description,quantity,unit_price,issue_date\n"
        "A,Acme,Task,1,100,2026-03-01\n"
        "B,Beta,Task,1,-5,2026-03-01\n"
        "C,Gamma,Task,2,50,2026-03-02\n",
        encoding="utf-8",
    )
    reg = tmp_path / "register.csv"
    code = main(
        [
            "batch", str(csv_path), "--profile", str(profile), "--out-dir", str(tmp_path / "out"),
            "--counter-file", str(tmp_path / "c.json"), "--register", str(reg),
        ]
    )  # fmt: skip
    assert code == 1
    assert [r["buyer"] for r in rows(reg)] == ["Acme", "Gamma"]


def test_summary_command_text_and_json(tmp_path, capsys):
    reg = tmp_path / "r.csv"
    append_rows(
        reg,
        [
            entry_row("INV-1", "2026-01-01", "2026-01-15", "1000.00"),
            entry_row("INV-2", "2026-02-01", "2026-03-15", "500.00"),
        ],
    )
    assert main(["summary", str(reg), "--as-of", "2026-03-01"]) == 0
    out = capsys.readouterr().out
    assert "BDT: 2 invoice(s)" in out
    assert "outstanding  BDT 1,500.00  (overdue BDT 1,000.00)" in out
    assert "overdue   45 day(s)  INV-1  Acme  BDT 1,000.00" in out

    assert main(["summary", str(reg), "--as-of", "2026-03-01", "--json", "--from", "2026-02-01"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["as_of"] == "2026-03-01"
    (cur,) = payload["currencies"]
    assert cur["invoices"] == 1 and cur["outstanding"] == "500.00" and cur["overdue"] == "0.00"


def test_summary_command_errors(tmp_path, capsys):
    assert main(["summary", str(tmp_path / "none.csv")]) == 2
    reg = tmp_path / "r.csv"
    append_rows(reg, [entry_row("INV-1", "2026-01-01", "", "10.00")])
    assert main(["summary", str(reg), "--as-of", "yesterday"]) == 2
    assert "--as-of" in capsys.readouterr().err
    assert main(["summary", str(reg), "--from", "2030-01-01"]) == 0
    assert "no documents" in capsys.readouterr().out
