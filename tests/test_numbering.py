import datetime as dt
import json

import pytest

from bd_invoice.numbering import (
    NumberingError,
    next_number,
    peek_number,
    render_number,
    validate_pattern,
)

D = dt.date(2026, 3, 9)


def test_render_default_pattern():
    assert render_number("INV-{YYYY}-{seq:04}", 7, D) == "INV-2026-0007"


def test_render_all_tokens():
    assert render_number("{YY}{MM}{DD}/{seq}", 12, D) == "260309/12"


def test_render_wider_than_padding():
    assert render_number("N{seq:02}", 1234, D) == "N1234"


@pytest.mark.parametrize("bad", ["INV-{YYYY}", "{seq}{seq}", "INV-{foo}-{seq}", "{seq", ""])
def test_invalid_patterns(bad):
    with pytest.raises(NumberingError):
        validate_pattern(bad)


def test_sequence_increments_and_persists(tmp_path):
    f = tmp_path / "c.json"
    assert next_number(f, date=D) == "INV-2026-0001"
    assert next_number(f, date=D) == "INV-2026-0002"
    assert json.loads(f.read_text())["counters"]


def test_peek_does_not_advance(tmp_path):
    f = tmp_path / "c.json"
    assert peek_number(f, date=D) == "INV-2026-0001"
    assert peek_number(f, date=D) == "INV-2026-0001"
    assert not f.exists()
    next_number(f, date=D)
    assert peek_number(f, date=D) == "INV-2026-0002"


def test_yearly_reset(tmp_path):
    f = tmp_path / "c.json"
    next_number(f, date=D)
    next_number(f, date=D)
    assert next_number(f, date=dt.date(2027, 1, 2)) == "INV-2027-0001"
    assert next_number(f, date=D) == "INV-2026-0003"


def test_monthly_reset(tmp_path):
    f = tmp_path / "c.json"
    p = "{YYYY}{MM}-{seq:03}"
    assert next_number(f, p, "monthly", D) == "202603-001"
    assert next_number(f, p, "monthly", D) == "202603-002"
    assert next_number(f, p, "monthly", dt.date(2026, 4, 1)) == "202604-001"


def test_never_reset_continues_across_years(tmp_path):
    f = tmp_path / "c.json"
    p = "A-{seq:03}"
    next_number(f, p, "never", D)
    assert next_number(f, p, "never", dt.date(2030, 1, 1)) == "A-002"


def test_patterns_have_independent_counters(tmp_path):
    f = tmp_path / "c.json"
    next_number(f, "INV-{YYYY}-{seq:04}", date=D)
    next_number(f, "INV-{YYYY}-{seq:04}", date=D)
    assert next_number(f, "QT-{YYYY}-{seq:04}", date=D) == "QT-2026-0001"


def test_invalid_reset(tmp_path):
    with pytest.raises(NumberingError):
        next_number(tmp_path / "c.json", reset="daily", date=D)


def test_corrupt_counter_file(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("{not json", encoding="utf-8")
    with pytest.raises(NumberingError, match="cannot read"):
        next_number(f, date=D)


def test_wrong_shape_counter_file(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("[1]", encoding="utf-8")
    with pytest.raises(NumberingError):
        next_number(f, date=D)


def test_no_temp_files_left_behind(tmp_path):
    f = tmp_path / "sub" / "c.json"
    next_number(f, date=D)
    assert [p.name for p in f.parent.iterdir()] == ["c.json"]


def test_counter_survives_new_process_style_reload(tmp_path):
    f = tmp_path / "c.json"
    for _ in range(3):
        next_number(f, date=D)
    assert next_number(f, date=D) == "INV-2026-0004"
