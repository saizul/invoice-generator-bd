import json

import pytest
import yaml

from bd_invoice.cli import SAMPLE_YAML, main, safe_filename

pypdf = pytest.importorskip("pypdf")


def write_yaml(tmp_path, data, name="inv.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_generate_creates_pdf_and_counter(data, tmp_path, capsys):
    src = write_yaml(tmp_path, data)
    counter = tmp_path / "c.json"
    code = main(["generate", str(src), "-o", str(tmp_path / "a.pdf"), "--counter-file", str(counter)])
    assert code == 0
    assert (tmp_path / "a.pdf").read_bytes().startswith(b"%PDF")
    assert "INV-2026-0001" in capsys.readouterr().out
    assert json.loads(counter.read_text())["counters"]


def test_generate_default_filename_uses_number(data, tmp_path):
    src = write_yaml(tmp_path, data)
    out_dir = tmp_path / "out"
    main(["generate", str(src), "--out-dir", str(out_dir), "--counter-file", str(tmp_path / "c.json")])
    assert (out_dir / "INV-2026-0001.pdf").exists()


def test_numbers_increase_across_runs(data, tmp_path):
    src = write_yaml(tmp_path, data)
    c = str(tmp_path / "c.json")
    main(["generate", str(src), "--out-dir", str(tmp_path), "--counter-file", c])
    main(["generate", str(src), "--out-dir", str(tmp_path), "--counter-file", c])
    assert (tmp_path / "INV-2026-0002.pdf").exists()


def test_explicit_number_does_not_touch_counter(data, tmp_path):
    data["number"] = "CUSTOM/7"
    src = write_yaml(tmp_path, data)
    c = tmp_path / "c.json"
    main(["generate", str(src), "--out-dir", str(tmp_path), "--counter-file", str(c)])
    assert (tmp_path / "CUSTOM_7.pdf").exists() and not c.exists()


def test_no_count_flag_keeps_counter(data, tmp_path):
    src = write_yaml(tmp_path, data)
    c = tmp_path / "c.json"
    main(["generate", str(src), "-o", str(tmp_path / "x.pdf"), "--counter-file", str(c), "--no-count"])
    assert not c.exists()


def test_quotation_uses_qt_pattern(data, tmp_path):
    data["type"] = "quotation"
    src = write_yaml(tmp_path, data)
    main(["generate", str(src), "--out-dir", str(tmp_path), "--counter-file", str(tmp_path / "c.json")])
    assert (tmp_path / "QT-2026-0001.pdf").exists()


def test_custom_pattern_option(data, tmp_path):
    src = write_yaml(tmp_path, data)
    main(["generate", str(src), "--out-dir", str(tmp_path), "--counter-file", str(tmp_path / "c.json"),
          "--number-pattern", "{YY}{MM}-{seq:03}"])  # fmt: skip
    assert (tmp_path / "2603-001.pdf").exists()


def test_theme_override(data, tmp_path):
    src = write_yaml(tmp_path, data)
    assert main(["generate", str(src), "-o", str(tmp_path / "t.pdf"), "--no-count", "--theme", "modern"]) == 0


def test_invalid_input_returns_2_and_no_pdf(data, tmp_path, capsys):
    del data["items"]
    src = write_yaml(tmp_path, data)
    code = main(
        ["generate", str(src), "-o", str(tmp_path / "bad.pdf"), "--counter-file", str(tmp_path / "c.json")]
    )
    assert code == 2
    assert not (tmp_path / "bad.pdf").exists() and not (tmp_path / "c.json").exists()
    assert "items" in capsys.readouterr().err


def test_invalid_yaml_returns_2(tmp_path, capsys):
    p = tmp_path / "bad.yaml"
    p.write_text("a: [1, 2", encoding="utf-8")
    assert main(["generate", str(p), "--no-count"]) == 2
    assert "invalid YAML" in capsys.readouterr().err


def test_missing_file_returns_2(tmp_path):
    assert main(["generate", str(tmp_path / "nope.yaml")]) == 2


def test_words_command(capsys):
    assert main(["words", "1,25,000.50"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Taka One Lakh Twenty Five Thousand and Fifty Paisa Only"
    assert out[1].startswith("টাকা এক লক্ষ পঁচিশ হাজার") and out[1].endswith("মাত্র")


def test_words_single_language(capsys):
    main(["words", "10", "--lang", "en"])
    assert capsys.readouterr().out.strip() == "Taka Ten Only"


def test_words_bad_amount(capsys):
    assert main(["words", "abc"]) == 2


def test_number_command(tmp_path, capsys):
    c = str(tmp_path / "c.json")
    main(["number", "--counter-file", c, "--peek"])
    main(["number", "--counter-file", c])
    main(["number", "--counter-file", c])
    lines = capsys.readouterr().out.split()
    assert lines[0].endswith("0001") and lines[1].endswith("0001") and lines[2].endswith("0002")


def test_sample_command_is_valid_and_generates(tmp_path, capsys):
    main(["sample"])
    text = capsys.readouterr().out
    assert text == SAMPLE_YAML
    src = tmp_path / "s.yaml"
    src.write_text(text, encoding="utf-8")
    assert main(["generate", str(src), "-o", str(tmp_path / "s.pdf"), "--no-count"]) == 0


def test_batch_generates_one_pdf_per_invoice(examples_dir, tmp_path, capsys):
    code = main(["batch", str(examples_dir / "clients.csv"), "--profile", str(examples_dir / "profile.yaml"),
                 "--out-dir", str(tmp_path / "out"), "--counter-file", str(tmp_path / "c.json")])  # fmt: skip
    assert code == 0
    assert sorted(p.name for p in (tmp_path / "out").glob("*.pdf")) == [
        "INV-2026-0001.pdf", "INV-2026-0002.pdf", "INV-2026-0003.pdf"]  # fmt: skip
    assert "3 generated, 0 failed" in capsys.readouterr().out


def test_batch_reports_failures_and_continues(examples_dir, tmp_path, capsys):
    csv_path = tmp_path / "b.csv"
    csv_path.write_text(
        "invoice,buyer_name,description,quantity,unit_price\nA,Acme,Task,1,100\nB,Beta,Task,1,abc\n",
        encoding="utf-8",
    )
    code = main(["batch", str(csv_path), "--profile", str(examples_dir / "profile.yaml"),
                 "--out-dir", str(tmp_path / "out"), "--counter-file", str(tmp_path / "c.json")])  # fmt: skip
    assert code == 1
    captured = capsys.readouterr()
    assert "1 generated, 1 failed" in captured.out and "invoice 'B'" in captured.err
    assert json.loads((tmp_path / "c.json").read_text())["counters"]


def test_font_from_environment(data, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BD_INVOICE_BANGLA_FONT", str(tmp_path / "missing.ttf"))
    data["language"] = "both"
    src = write_yaml(tmp_path, data)
    main(["generate", str(src), "-o", str(tmp_path / "e.pdf"), "--no-count"])
    assert "not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    "raw,expected", [("INV-2026-0001", "INV-2026-0001"), ("A/B C", "A_B_C"), ("///", "invoice")]
)
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


def test_watermark_flag_overrides_yaml(data, tmp_path):
    data["watermark"] = "DRAFT"
    src = write_yaml(tmp_path, data)
    out = tmp_path / "w.pdf"
    assert main(["generate", str(src), "-o", str(out), "--no-count", "--watermark", "paid"]) == 0
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(str(out)).pages)
    assert "PAID" in text and "DRAFT" not in text


def test_watermark_flag_rejects_non_latin(data, tmp_path, capsys):
    src = write_yaml(tmp_path, data)
    code = main(["generate", str(src), "-o", str(tmp_path / "x.pdf"), "--no-count", "--watermark", "পরিশোধ"])
    assert code == 2
    assert "Latin" in capsys.readouterr().err
