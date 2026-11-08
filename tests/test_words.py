import pytest

from bd_invoice.words import amount_in_words, int_to_words_bn, int_to_words_en


@pytest.mark.parametrize(
    "n,expected",
    [(0, "Zero"), (7, "Seven"), (13, "Thirteen"), (20, "Twenty"), (21, "Twenty One"),
     (100, "One Hundred"), (101, "One Hundred One"), (999, "Nine Hundred Ninety Nine"),
     (1000, "One Thousand"), (12345, "Twelve Thousand Three Hundred Forty Five"),
     (100000, "One Lakh"), (123456, "One Lakh Twenty Three Thousand Four Hundred Fifty Six"),
     (10000000, "One Crore"), (12345678, "One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight"),
     (1000000000, "One Hundred Crore")],
)  # fmt: skip
def test_int_to_words_en_south_asian(n, expected):
    assert int_to_words_en(n, south_asian=True) == expected


@pytest.mark.parametrize(
    "n,expected",
    [(1000000, "One Million"), (1234567, "One Million Two Hundred Thirty Four Thousand Five Hundred Sixty Seven"),
     (5000000000, "Five Billion")],
)  # fmt: skip
def test_int_to_words_en_western(n, expected):
    assert int_to_words_en(n, south_asian=False) == expected


@pytest.mark.parametrize(
    "n,expected",
    [(0, "শূন্য"), (1, "এক"), (10, "দশ"), (21, "একুশ"), (99, "নিরানব্বই"),
     (100, "এক শত"), (250, "দুই শত পঞ্চাশ"), (1000, "এক হাজার"),
     (100000, "এক লক্ষ"), (10000000, "এক কোটি"),
     (1234567, "বারো লক্ষ চৌত্রিশ হাজার পাঁচ শত সাতষট্টি")],
)  # fmt: skip
def test_int_to_words_bn(n, expected):
    assert int_to_words_bn(n) == expected


def test_bn_table_has_no_duplicates_or_blanks():
    words = [int_to_words_bn(i) for i in range(100)]
    assert len(set(words)) == 100 and all(words)


def test_negative_not_supported():
    with pytest.raises(ValueError):
        int_to_words_en(-1)
    with pytest.raises(ValueError):
        int_to_words_bn(-1)
    with pytest.raises(ValueError):
        amount_in_words("-5")


def test_amount_taka_only_english():
    assert amount_in_words("120000") == "Taka One Lakh Twenty Thousand Only"


def test_amount_taka_only_bangla():
    assert amount_in_words("120000", lang="bn") == "টাকা এক লক্ষ বিশ হাজার মাত্র"


def test_amount_with_paisa_english():
    assert amount_in_words("1250.50") == "Taka One Thousand Two Hundred Fifty and Fifty Paisa Only"


def test_amount_with_paisa_bangla():
    assert amount_in_words("1250.50", lang="bn") == "টাকা এক হাজার দুই শত পঞ্চাশ ও পঞ্চাশ পয়সা মাত্র"


def test_amount_only_paisa():
    assert amount_in_words("0.05") == "Five Paisa Only"
    assert amount_in_words("0.05", lang="bn") == "পাঁচ পয়সা মাত্র"


def test_amount_zero():
    assert amount_in_words("0") == "Taka Zero Only"
    assert amount_in_words("0", lang="bn") == "টাকা শূন্য মাত্র"


def test_amount_rounds_to_two_places_first():
    assert amount_in_words("0.999") == "Taka One Only"
    assert amount_in_words("10.004") == "Taka Ten Only"


def test_amount_crore_scale():
    text = amount_in_words("123456789.05")
    assert text.startswith("Taka Twelve Crore Thirty Four Lakh")
    assert text.endswith("and Five Paisa Only")


def test_amount_usd_uses_western_system():
    assert (
        amount_in_words("1500000.25", "USD")
        == "US Dollars One Million Five Hundred Thousand and Twenty Five Cents Only"
    )


def test_amount_unknown_currency_uses_code():
    assert amount_in_words("5", "AUD") == "AUD Five Only"


def test_amount_bangla_usd():
    assert amount_in_words("12.50", "USD", "bn") == "মার্কিন ডলার বারো ও পঞ্চাশ সেন্ট মাত্র"


def test_amount_accepts_decimal_and_float_like():
    from decimal import Decimal

    assert amount_in_words(Decimal("21")) == "Taka Twenty One Only"


def test_unsupported_language():
    with pytest.raises(ValueError):
        amount_in_words("1", lang="fr")


def test_too_large():
    with pytest.raises(ValueError):
        amount_in_words("1" + "0" * 16)
