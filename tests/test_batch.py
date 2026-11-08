import pytest

from bd_invoice.batch import load_csv
from bd_invoice.models import InvoiceError, parse_invoice

HEADER = "invoice,buyer_name,buyer_address,description,quantity,unit_price,discount_percent,issue_date\n"


def write(tmp_path, body, header=HEADER):
    p = tmp_path / "in.csv"
    p.write_text(header + body, encoding="utf-8")
    return p


PROFILE = {"seller": {"name": "S"}, "vat_percent": 15, "currency": "BDT"}


def test_groups_rows_by_invoice(tmp_path):
    p = write(
        tmp_path, "A,Acme,Road 1|Dhaka,Task 1,1,100,,2026-03-01\nA,,,Task 2,2,50,10,\nB,Beta,,Task 3,1,10,,\n"
    )
    docs = load_csv(p, PROFILE)
    assert [d[0] for d in docs] == ["A", "B"]
    assert len(docs[0][1]["items"]) == 2 and len(docs[1][1]["items"]) == 1


def test_profile_merged_and_buyer_filled(tmp_path):
    p = write(tmp_path, "A,Acme,Road 1|Dhaka,Task,1,100,,2026-03-01\n")
    _, doc, _ = load_csv(p, PROFILE)[0]
    assert doc["seller"]["name"] == "S" and doc["vat_percent"] == 15
    assert doc["buyer"]["name"] == "Acme" and doc["buyer"]["address"] == "Road 1\nDhaka"


def test_documents_parse(tmp_path):
    p = write(tmp_path, "A,Acme,,Task,1,100,,2026-03-01\n")
    inv = parse_invoice(load_csv(p, PROFILE)[0][1])
    assert inv.items[0].unit_price == 100 and inv.buyer.name == "Acme"


def test_profile_not_mutated(tmp_path):
    p = write(tmp_path, "A,Acme,,Task,1,100,,\n")
    load_csv(p, PROFILE)
    assert "items" not in PROFILE and "buyer" not in PROFILE


def test_missing_required_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(InvoiceError, match="missing required"):
        load_csv(p)


def test_blank_rows_skipped(tmp_path):
    p = write(tmp_path, "A,Acme,,Task,1,100,,\n,,,,,,,\n")
    assert len(load_csv(p, PROFILE)[0][1]["items"]) == 1


def test_groups_by_buyer_without_invoice_value(tmp_path):
    p = write(tmp_path, ",Acme,,T1,1,1,,\n,Acme,,T2,1,1,,\n,Beta,,T3,1,1,,\n")
    assert len(load_csv(p, PROFILE)) == 2


def test_bom_header_handled(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes(("﻿" + HEADER + "A,Acme,,Task,1,100,,\n").encode("utf-8"))
    assert load_csv(p, PROFILE)[0][0] == "A"


def test_empty_file(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("", encoding="utf-8")
    with pytest.raises(InvoiceError):
        load_csv(p)
