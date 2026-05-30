"""Tests for apii.normalize.

Each vector pins a specific normalization contract — same input, same
expected output — including the offset-map round-trip the recognizers
depend on.
"""

from apii.normalize import (
    NormalizedText,
    alnum_upper,
    ascii_digit,
    digits_only,
    is_arabic_letter,
    is_arabic_word,
    normalize_arabic,
    normalize_arabic_matching_view,
    normalize_digits,
    reverse_arabic_runs,
    scrub_invisible,
    strip_arabic_prefix_particles,
)


def test_ascii_digit_folds_arabic_and_persian():
    assert ascii_digit("0") == "0"
    assert ascii_digit("٥") == "5"  # Arabic-Indic
    assert ascii_digit("۹") == "9"  # Persian/Extended-Arabic
    assert ascii_digit("a") is None
    assert ascii_digit("") is None


def test_digit_helpers_round_trip():
    assert normalize_digits("SA٥٤ ٩٩٠٠") == "SA54 9900"
    assert digits_only("AE07 ٠٣٣١") == "070331"
    assert alnum_upper("sa54 99-00 AB") == "SA549900AB"


def test_is_arabic_letter_and_word():
    assert is_arabic_letter("م")
    assert not is_arabic_letter("m")
    assert is_arabic_word("شركة بناء")
    assert not is_arabic_word("شركة Bina")  # mixed
    assert not is_arabic_word("")


# ── scrub_invisible ──


def test_scrub_strips_zero_width_and_bidi_but_keeps_arabic_joiners():
    hidden = "ahmed​@exa​mple.com"
    assert scrub_invisible(hidden) == "ahmed@example.com"
    # Bidi override (polyglot-injection trick) removed.
    assert scrub_invisible("a‮bc‬d") == "abcd"
    # Arabic ZWNJ preserved.
    arabic = "می‌خواهم"
    assert scrub_invisible(arabic) == arabic


def test_scrub_folds_cyrillic_homoglyphs_to_latin():
    # Lowercase "pay" written with Cyrillic р, а, у.
    assert scrub_invisible("рау") == "pay"
    # Mixed Cyrillic + Latin in an account-like word.
    assert scrub_invisible("аccоunt") == "account"
    # Uppercase confusables.
    assert scrub_invisible("СОМ") == "COM"


def test_scrub_is_idempotent():
    messy = "​аhmed‮@x.com"
    once = scrub_invisible(messy)
    assert scrub_invisible(once) == once


def test_scrub_strips_unicode_tag_characters():
    # Tag-block smuggling: visible "hi" with an invisible tag run.
    tagged = "hi\U000E0001\U000E0048\U000E0049"
    assert scrub_invisible(tagged) == "hi"


def test_scrub_leaves_clean_text_unchanged():
    clean = "اتصل بأحمد على 0501234567 — Contact ahmed@example.com"
    assert scrub_invisible(clean) == clean


# ── reverse_arabic_runs ──


def test_reverse_arabic_runs_reverses_each_word_individually():
    visual = "نب دوعس"
    logical = reverse_arabic_runs(visual)
    assert logical == "بن سعود"
    # Char count preserved (per-run reversal does not move boundaries).
    assert len(logical) == len(visual)


def test_reverse_passes_through_non_arabic_unchanged():
    visual = "Invoice 5000 نب دوعس EOL"
    logical = reverse_arabic_runs(visual)
    # Words flip per-run; word order does not (different from block reversal).
    assert logical == "Invoice 5000 بن سعود EOL"


# ── strip_arabic_prefix_particles ──


def test_strip_prefix_particles():
    # Conservative: at least 3 chars must remain. Longest prefix wins, by
    # try-order (بال, وال, فال, كال, لل, ال, ب, و) — so "بالعميل" loses the
    # 3-char "بال", not just "ب".
    assert strip_arabic_prefix_particles("الشركة") == "شركة"
    assert strip_arabic_prefix_particles("بالعميل") == "عميل"
    # Below the 3-char floor → no strip.
    assert strip_arabic_prefix_particles("ابن") == "ابن"


# ── normalize_arabic (string comparison form) ──


def test_normalize_arabic_unifies_alef_and_tah_marbuta():
    # أ / إ / آ all fold to ا; ة folds to ه; spaces collapse.
    assert normalize_arabic("أحمد  إلى") == "احمد الي"
    assert normalize_arabic("شركة") == "شركه"
    # Digits fold too.
    assert normalize_arabic("الجوال ٠٥٠١٢٣٤٥٦٧") == "الجوال 0501234567"


# ── normalize_arabic_matching_view — the offset-map round-trip ──


def test_matching_view_preserves_ascii_identity():
    nv = normalize_arabic_matching_view("hello world")
    assert nv.text == "hello world"
    # Whole-string round-trip.
    assert nv.original_span(0, len(nv.text)) == (0, len("hello world"))


def test_matching_view_drops_diacritics_and_maps_back():
    # Arabic name with fatha + kasra diacritics. Diacritics disappear in
    # the normalized view; the bare letters stay.
    src = "مَنْصُور"  # م + fatha + ن + sukun + ص + damma + و + ر
    nv = normalize_arabic_matching_view(src)
    # Normalized view contains only the letters.
    assert nv.text == "منصور"
    # Asking for the original range covering the full normalized text
    # must return the bounds of the source (incl. diacritics).
    assert nv.original_span(0, len(nv.text)) == (0, len(src))


def test_matching_view_folds_arabic_indic_digits():
    nv = normalize_arabic_matching_view("SA٥٤")
    assert nv.text == "SA54"
    # 4-char window → 4-char original window.
    assert nv.original_span(0, 4) == (0, 4)


def test_matching_view_returns_none_for_invalid_range():
    nv = normalize_arabic_matching_view("abc")
    assert nv.original_span(2, 2) is None  # zero-width
    assert nv.original_span(0, 99) is None  # past end


def test_matching_view_partial_range_maps_to_original_window():
    # "AE07 0331" → matching view is identical (ASCII), so a normalized
    # substring "0331" maps to the same range in the source.
    src = "AE07 0331"
    nv = normalize_arabic_matching_view(src)
    start = nv.text.index("0331")
    end = start + 4
    assert nv.original_span(start, end) == (start, end)


def test_normalized_text_is_a_frozen_dataclass():
    # Sanity: the class is hashable / immutable enough to live in caches.
    nv = normalize_arabic_matching_view("x")
    assert isinstance(nv, NormalizedText)
    # Frozen dataclass: assignment fails.
    try:
        nv.text = "y"
    except Exception:  # noqa: BLE001
        pass
    else:
        raise AssertionError("expected frozen dataclass to reject mutation")
