"""Invoice numbering with a local JSON counter file.

Pattern tokens: {YYYY} {YY} {MM} {DD} {seq} or {seq:N} (zero padded to N digits).
Example: "INV-{YYYY}-{seq:04}" -> INV-2026-0001. The counter can reset never/yearly/monthly.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path

DEFAULT_PATTERN = "INV-{YYYY}-{seq:04}"
QUOTE_PATTERN = "QT-{YYYY}-{seq:04}"
RESETS = ("never", "yearly", "monthly")
TOKEN_RE = re.compile(r"\{(YYYY|YY|MM|DD|seq)(?::(\d+))?\}")


class NumberingError(ValueError):
    pass


def validate_pattern(pattern: str) -> None:
    seqs = [m for m in TOKEN_RE.finditer(pattern) if m.group(1) == "seq"]
    if len(seqs) != 1:
        raise NumberingError("pattern must contain exactly one {seq} or {seq:N} token")
    leftover = TOKEN_RE.sub("", pattern)
    if "{" in leftover or "}" in leftover:
        raise NumberingError(f"unknown token in pattern: {pattern!r}")


def render_number(pattern: str, seq: int, date: dt.date) -> str:
    validate_pattern(pattern)

    def repl(m: re.Match) -> str:
        token, width = m.group(1), m.group(2)
        if token == "seq":
            return str(seq).zfill(int(width)) if width else str(seq)
        return {
            "YYYY": f"{date.year:04d}",
            "YY": f"{date.year % 100:02d}",
            "MM": f"{date.month:02d}",
            "DD": f"{date.day:02d}",
        }[token]

    return TOKEN_RE.sub(repl, pattern)


def period_key(pattern: str, reset: str, date: dt.date) -> str:
    if reset not in RESETS:
        raise NumberingError(f"reset must be one of {RESETS}")
    if reset == "yearly":
        period = f"{date.year:04d}"
    elif reset == "monthly":
        period = f"{date.year:04d}-{date.month:02d}"
    else:
        period = "all"
    # keep counters for different patterns (invoice vs quotation) independent
    shape = TOKEN_RE.sub(lambda m: "#" if m.group(1) == "seq" else m.group(0), pattern)
    return f"{shape}|{period}"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NumberingError(f"cannot read counter file {path}: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("counters", {}), dict):
        raise NumberingError(f"counter file {path} has an unexpected format")
    return data.get("counters", {})


def _save(path: Path, counters: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".counter-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"counters": counters}, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def peek_number(path, pattern: str = DEFAULT_PATTERN, reset: str = "yearly", date=None) -> str:
    """Return the number that next_number would issue, without changing the counter."""
    date = date or dt.date.today()
    counters = _load(Path(path))
    key = period_key(pattern, reset, date)
    return render_number(pattern, counters.get(key, 0) + 1, date)


def next_number(path, pattern: str = DEFAULT_PATTERN, reset: str = "yearly", date=None) -> str:
    """Issue the next number and persist the counter (atomic replace)."""
    date = date or dt.date.today()
    path = Path(path)
    counters = _load(path)
    key = period_key(pattern, reset, date)
    seq = counters.get(key, 0) + 1
    number = render_number(pattern, seq, date)
    counters[key] = seq
    _save(path, counters)
    return number
