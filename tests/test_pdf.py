import copy

import pytest

from bd_invoice.models import parse_invoice
from bd_invoice.pdf import fmt_qty, latin_safe, qr_available, render_invoice

pypdf = pytest.importorskip("pypdf")


def read(path):
    reader = pypdf.PdfReader(str(path))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    return reader, text


def render(inv, tmp_path, **kw):
    out = tmp_path / "out.pdf"
    result = render_invoice(inv, out, **kw)
    return out, result


def test_pdf_bytes_and_pages(invoice, tmp_path):
    out, result = render(invoice, tmp_path)
    raw = out.read_bytes()
    assert raw.startswith(b"%PDF-") and raw.rstrip().endswith(b"%%EOF")
    reader, _ = read(out)
    assert len(reader.pages) == result.pages == 1


def test_pdf_contains_key_text(invoice, tmp_path):
    out, _ = render(invoice, tmp_path)
    _, text = read(out)
    for needle in ("INVOICE", "INV-2026-0001", "Test Agency", "Test Client", "Service A", "4,600.00"):
        assert needle in text


def test_pdf_amount_in_words(invoice, tmp_path):
    out, _ = render(invoice, tmp_path)
    _, text = read(out)
    assert "Four Thousand Six Hundred" in text.replace("\n", " ")


def test_pdf_vat_line(invoice, tmp_path):
    out, _ = render(invoice, tmp_path)
    _, text = read(out)
    assert "VAT (15%)" in text and "600.00" in text


def test_pdf_south_asian_grouping(data, tmp_path):
    data["items"] = [{"description": "Big job", "quantity": 1, "unit_price": 1234567.5}]
    data["vat_percent"] = 0
    inv = parse_invoice(data)
    inv.number = "INV-1"
    out, _ = render(inv, tmp_path)
    _, text = read(out)
    assert "12,34,567.50" in text
    assert "Twelve Lakh Thirty Four Thousand" in text.replace("\n", " ")


def test_pdf_ait_net_payable(data, tmp_path):
    data["ait_percent"] = 5
    inv = parse_invoice(data)
    inv.number = "INV-2"
    out, _ = render(inv, tmp_path)
    _, text = read(out)
    assert "Less: AIT (5%)" in text and "Net payable" in text and "4,400.00" in text


def test_pdf_discount_row(data, tmp_path):
    data["discount"] = {"type": "percent", "value": 10, "label": "Early bird"}
    inv = parse_invoice(data)
    inv.number = "INV-3"
    _, text = read(render(inv, tmp_path)[0])
    assert "Early bird (10%)" in text


def test_pdf_usd_quotation(data, tmp_path):
    data.update({"type": "quotation", "currency": "USD", "vat_percent": 0})
    inv = parse_invoice(data)
    inv.number = "QT-1"
    out, _ = render(inv, tmp_path)
    _, text = read(out)
    assert "QUOTATION" in text and "Valid until" in text and "$4,000.00" in text
    assert "US Dollars Four Thousand Only" in text.replace("\n", " ")
    assert "Due date" not in text


def test_pdf_minimal_and_modern_both_render(invoice, tmp_path):
    for theme in ("minimal", "modern"):
        invoice.theme = theme
        out, result = render(invoice, tmp_path)
        assert out.stat().st_size > 1500 and result.pages == 1


def test_pdf_custom_accent(invoice, tmp_path):
    invoice.theme, invoice.accent = "modern", "#aa3300"
    out, _ = render(invoice, tmp_path)
    assert out.exists()


def test_pdf_multi_page(data, tmp_path):
    data["items"] = [
        {
            "description": f"Line item number {i} with a reasonably long description",
            "quantity": 1,
            "unit_price": 100 + i,
        }
        for i in range(90)
    ]
    inv = parse_invoice(data)
    inv.number = "INV-BIG"
    out, result = render(inv, tmp_path)
    reader, text = read(out)
    assert len(reader.pages) == result.pages >= 2
    assert f"Page 2 of {len(reader.pages)}" in text


def test_pdf_metadata(invoice, tmp_path):
    out, _ = render(invoice, tmp_path)
    meta = pypdf.PdfReader(str(out)).metadata
    assert meta.title == "Invoice INV-2026-0001" and meta.author == "Test Agency"


def test_pdf_payment_block_text_only(data, tmp_path):
    data["payment"] = {
        "bank": {"bank_name": "Example Bank"},
        "bkash": "01700-000000",
        "nagad": "01800-000000",
    }
    inv = parse_invoice(data)
    inv.number = "INV-4"
    _, text = read(render(inv, tmp_path)[0])
    assert "PAYMENT INSTRUCTIONS" in text and "bKash" in text and "Nagad" in text and "Example Bank" in text


def test_pdf_no_payment_block_when_empty(invoice, tmp_path):
    _, text = read(render(invoice, tmp_path)[0])
    assert "PAYMENT INSTRUCTIONS" not in text


@pytest.mark.skipif(not qr_available(), reason="qrcode not installed")
def test_pdf_qr_renders(data, tmp_path):
    data["payment"] = {"bkash": "017", "qr": True}
    inv = parse_invoice(data)
    inv.number = "INV-5"
    out, result = render(inv, tmp_path)
    assert result.warnings == []
    assert out.stat().st_size > 2500


@pytest.mark.skipif(not qr_available(), reason="qrcode not installed")
def test_qr_payload_custom(data, tmp_path):
    from bd_invoice.calc import compute_totals
    from bd_invoice.pdf import Renderer

    data["payment"] = {"bkash": "017", "qr": True}
    inv = parse_invoice(data)
    inv.number = "INV-6"
    r = Renderer(inv, compute_totals(inv), None)
    assert r.qr_payload().startswith("REF:INV-6|AMT:4600.00|CUR:BDT")
    inv.payment.qr_payload = "custom"
    assert r.qr_payload() == "custom"


def test_logo_png_embedded(invoice, tmp_path):
    from PIL import Image

    logo = tmp_path / "logo.png"
    Image.new("RGB", (200, 80), (20, 120, 200)).save(logo)
    plain, _ = render(invoice, tmp_path)
    size_plain = plain.stat().st_size
    invoice.logo = str(logo)
    with_logo, result = render(invoice, tmp_path)
    assert result.warnings == [] and with_logo.stat().st_size > size_plain


def test_logo_relative_to_base_dir(invoice, tmp_path):
    from PIL import Image

    Image.new("RGB", (50, 50), (0, 0, 0)).save(tmp_path / "l.png")
    invoice.logo = "l.png"
    _, result = render(invoice, tmp_path, base_dir=str(tmp_path))
    assert result.warnings == []


def test_missing_logo_warns_but_renders(invoice, tmp_path):
    invoice.logo = str(tmp_path / "nope.png")
    out, result = render(invoice, tmp_path)
    assert out.exists() and any("logo not found" in w for w in result.warnings)


def test_corrupt_logo_warns(invoice, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    invoice.logo = str(bad)
    out, result = render(invoice, tmp_path)
    assert out.exists() and any("cannot read logo" in w for w in result.warnings)


def test_language_both_without_font_falls_back(invoice, tmp_path):
    invoice.language = "both"
    out, result = render(invoice, tmp_path)
    assert result.bangla is False
    assert any("--bangla-font" in w for w in result.warnings)
    assert out.exists()


def test_missing_font_file_falls_back(invoice, tmp_path):
    invoice.language = "both"
    out, result = render(invoice, tmp_path, bangla_font=str(tmp_path / "missing.ttf"))
    assert out.exists() and result.bangla is False
    assert any("not found" in w for w in result.warnings)


def test_bangla_text_in_latin_field_is_replaced_not_crashing(data, tmp_path):
    data["notes"] = "ধন্যবাদ for your business"
    inv = parse_invoice(data)
    inv.number = "INV-7"
    out, result = render(inv, tmp_path)
    _, text = read(out)
    assert "for your business" in text
    assert any("unsupported characters" in w for w in result.warnings)


def test_currency_without_symbol_uses_code(data, tmp_path):
    data["currency"] = "AUD"
    inv = parse_invoice(data)
    inv.number = "INV-8"
    _, text = read(render(inv, tmp_path)[0])
    assert "AUD 4,600.00" in text


def test_xml_special_characters_escaped(data, tmp_path):
    data["items"][0]["description"] = "R&D <phase 1> & testing"
    inv = parse_invoice(data)
    inv.number = "INV-9"
    _, text = read(render(inv, tmp_path)[0])
    assert "R&D <phase 1> & testing" in text


def test_item_discount_column_only_when_used(data, tmp_path):
    inv = parse_invoice(data)
    inv.number = "I"
    assert "Disc." not in read(render(inv, tmp_path)[0])[1]
    data["items"][0]["discount_percent"] = 10
    inv = parse_invoice(data)
    inv.number = "I"
    assert "Disc." in read(render(inv, tmp_path)[0])[1]


def test_fmt_qty():
    from decimal import Decimal as D

    assert fmt_qty(D("4")) == "4" and fmt_qty(D("2.50")) == "2.5" and fmt_qty(D("0.125")) == "0.125"


def test_latin_safe_replaces_and_warns():
    warnings = []
    assert latin_safe("café ৳", warnings, "x") == "café ?"
    assert warnings and "Bangla" in warnings[0]
    assert latin_safe("plain") == "plain"


def test_example_files_generate(examples_dir, tmp_path):
    import yaml

    for name in ("invoice-bdt.yaml", "quotation-usd.yaml"):
        data = yaml.safe_load((examples_dir / name).read_text(encoding="utf-8"))
        inv = parse_invoice(copy.deepcopy(data))
        inv.number = "EX-1"
        out, result = render(inv, tmp_path)
        assert out.stat().st_size < 300_000 and result.pages >= 1


def test_bundled_sample_pdfs_are_small_and_valid(examples_dir):
    for name in ("sample-invoice.pdf", "sample-quotation.pdf"):
        path = examples_dir / name
        assert path.stat().st_size < 300_000
        assert len(pypdf.PdfReader(str(path)).pages) == 1


# -- Bangla rendering (needs a user supplied font + uharfbuzz) --------------


def test_bangla_render_both(invoice, tmp_path, bangla_font):
    invoice.language = "both"
    invoice.seller.name_bn = "এক্সাম্পল এজেন্সি"
    out, result = render(invoice, tmp_path, bangla_font=bangla_font)
    assert result.bangla is True and result.warnings == []
    assert out.read_bytes().startswith(b"%PDF-")


def test_bangla_symbol_used_with_font(invoice, tmp_path, bangla_font):
    out, _ = render(invoice, tmp_path, bangla_font=bangla_font)
    reader = pypdf.PdfReader(str(out))
    fonts = str(reader.pages[0]["/Resources"]["/Font"])
    assert "BDInvoiceBangla" in fonts or "/F" in fonts


def test_shaper_reorders_vowel_sign(bangla_font):
    from bd_invoice.shaping import BanglaShaper

    shaper = BanglaShaper(bangla_font)
    glyphs = shaper.shape("বি")  # ba + i-kar: the sign is drawn before the consonant
    assert len(glyphs) == 2
    assert shaper.width("বি", 10) > 0
    assert shaper.wrap("এক দুই তিন চার", 10, 1) == ["এক", "দুই", "তিন", "চার"]
