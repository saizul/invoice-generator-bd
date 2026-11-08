"""Amount in words (English and Bangla) using the South Asian or western number system."""

from __future__ import annotations

from decimal import Decimal

from .money import is_south_asian, round_money

_EN_UNITS = [
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
    "Eighteen", "Nineteen",
]  # fmt: skip
_EN_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

_BN_0_99 = (
    "শূন্য এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ "
    "এগারো বারো তেরো চৌদ্দ পনেরো ষোল সতেরো আঠারো ঊনিশ বিশ "
    "একুশ বাইশ তেইশ চব্বিশ পঁচিশ ছাব্বিশ সাতাশ আটাশ ঊনত্রিশ ত্রিশ "
    "একত্রিশ বত্রিশ তেত্রিশ চৌত্রিশ পঁয়ত্রিশ ছত্রিশ সাঁইত্রিশ আটত্রিশ ঊনচল্লিশ চল্লিশ "
    "একচল্লিশ বিয়াল্লিশ তেতাল্লিশ চুয়াল্লিশ পঁয়তাল্লিশ ছেচল্লিশ সাতচল্লিশ আটচল্লিশ ঊনপঞ্চাশ পঞ্চাশ "
    "একান্ন বায়ান্ন তিপ্পান্ন চুয়ান্ন পঞ্চান্ন ছাপ্পান্ন সাতান্ন আটান্ন ঊনষাট ষাট "
    "একষট্টি বাষট্টি তেষট্টি চৌষট্টি পঁয়ষট্টি ছেষট্টি সাতষট্টি আটষট্টি ঊনসত্তর সত্তর "
    "একাত্তর বাহাত্তর তিয়াত্তর চুয়াত্তর পঁচাত্তর ছিয়াত্তর সাতাত্তর আটাত্তর ঊনআশি আশি "
    "একাশি বিরাশি তিরাশি চুরাশি পঁচাশি ছিয়াশি সাতাশি আটাশি ঊননব্বই নব্বই "
    "একানব্বই বিরানব্বই তিরানব্বই চুরানব্বই পঁচানব্বই ছিয়ানব্বই সাতানব্বই আটানব্বই নিরানব্বই"
).split()
assert len(_BN_0_99) == 100

MAX_AMOUNT = Decimal("999999999999999")  # keeps recursion and output sane

CURRENCY_NAMES = {
    "BDT": ("Taka", "Paisa"),
    "INR": ("Rupees", "Paise"),
    "USD": ("US Dollars", "Cents"),
    "EUR": ("Euros", "Cents"),
    "GBP": ("Pounds", "Pence"),
}
CURRENCY_NAMES_BN = {
    "BDT": ("টাকা", "পয়সা"),
    "USD": ("মার্কিন ডলার", "সেন্ট"),
    "EUR": ("ইউরো", "সেন্ট"),
    "GBP": ("পাউন্ড", "পেন্স"),
    "INR": ("রুপি", "পয়সা"),
}


def _en_below_100(n: int) -> str:
    if n < 20:
        return _EN_UNITS[n]
    tens, unit = divmod(n, 10)
    return _EN_TENS[tens] + (f" {_EN_UNITS[unit]}" if unit else "")


def _en_below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_EN_UNITS[hundreds]} Hundred")
    if rest:
        parts.append(_en_below_100(rest))
    return " ".join(parts)


def int_to_words_en(n: int, south_asian: bool = True) -> str:
    """Spell a non-negative integer in English (lakh/crore or thousand/million/billion)."""
    if n < 0:
        raise ValueError("negative numbers are not supported")
    if n == 0:
        return "Zero"
    if south_asian:
        scales = [(10**7, "Crore"), (10**5, "Lakh"), (1000, "Thousand")]
    else:
        scales = [(10**12, "Trillion"), (10**9, "Billion"), (10**6, "Million"), (1000, "Thousand")]
    parts = []
    for size, name in scales:
        count, n = divmod(n, size)
        if count:
            # in the South Asian system crores can exceed 99 ("One Hundred Crore")
            words = int_to_words_en(count, south_asian) if count >= 1000 else _en_below_1000(count)
            parts.append(f"{words} {name}")
    if n:
        parts.append(_en_below_1000(n))
    return " ".join(parts)


def int_to_words_bn(n: int) -> str:
    """Spell a non-negative integer in Bangla (কোটি, লক্ষ, হাজার, শত)."""
    if n < 0:
        raise ValueError("negative numbers are not supported")
    if n == 0:
        return _BN_0_99[0]
    parts = []
    for size, name in ((10**7, "কোটি"), (10**5, "লক্ষ"), (1000, "হাজার")):
        count, n = divmod(n, size)
        if count:
            words = int_to_words_bn(count) if count >= 100 else _BN_0_99[count]
            parts.append(f"{words} {name}")
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append(f"{_BN_0_99[hundreds]} শত")
    if rest:
        parts.append(_BN_0_99[rest])
    return " ".join(parts)


def _split_amount(amount) -> tuple:
    value = round_money(Decimal(amount))
    if value < 0:
        raise ValueError("negative amounts are not supported")
    if value > MAX_AMOUNT:
        raise ValueError("amount is too large to spell out")
    whole = int(value)
    minor = int((value - whole) * 100)
    return whole, minor


def amount_in_words(amount, currency: str = "BDT", lang: str = "en") -> str:
    """Spell an amount, e.g. 'Taka One Lakh Twenty Thousand Only' / 'টাকা ... মাত্র'.

    Money is rounded to two decimals first. Bangla uses the lakh/crore system; English uses
    lakh/crore for BDT/INR-style currencies and thousand/million for others.
    """
    cur = currency.upper()
    whole, minor = _split_amount(amount)
    if lang == "bn":
        major_name, minor_name = CURRENCY_NAMES_BN.get(cur, (cur, ""))
        parts = []
        if whole or not minor:
            parts.append(int_to_words_bn(whole))
        text = " ".join(parts)
        if minor:
            minor_words = f"{int_to_words_bn(minor)} {minor_name}".strip()
            text = f"{text} ও {minor_words}" if whole else minor_words
        prefix = f"{major_name} " if (whole or not minor) else ""
        return f"{prefix}{text} মাত্র".strip()
    if lang != "en":
        raise ValueError(f"unsupported language: {lang!r}")
    major_name, minor_name = CURRENCY_NAMES.get(cur, (cur, "Cents"))
    sa = is_south_asian(cur)
    pieces = []
    if whole or not minor:
        pieces.append(f"{major_name} {int_to_words_en(whole, sa)}")
    if minor:
        minor_words = f"{int_to_words_en(minor, sa)} {minor_name}"
        pieces.append(f"and {minor_words}" if whole else minor_words)
    return " ".join(pieces) + " Only"
