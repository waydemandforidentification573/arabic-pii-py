"""PHONE recognizer — GCC mobile/landline shapes with plausibility gates."""

from __future__ import annotations

from typing import Iterator

import regex

from apii.normalize import digits_only, normalize_digits
from apii.types import Detection, EntityKind

GCC_PHONE_RE = regex.compile(
    r"""(?x)
    (?:
        # International head — the +/00/(GCC-code) marker IS the signal:
        #   +966 / 00966 / (968) / +(965) / (+974) / "+ 974" / "00 966".
        # + may sit before OR inside the paren; one optional space only AFTER
        # +/00 (tied to the marker, so a bare leading space is never eaten —
        # the match always starts at +, 00, (, or the country-code digit).
        (?:(?:\+|00)\s?)?\(?(?:\+\s?)?(?:966|971|974|965|973|968)\s?\)?
        # ONE optional divider right after the country code, DASH-GATED so a
        # plain double space can't bridge two numbers (preserves the
        # double-space split invariant). Bridges "00965 - 23989111" and the
        # en-dash form "00965 – 23983661" (U+2010..U+2015, U+2212).
        (?:\s?[\-‐-―−]\s?)?
        # 6-12 body digits. Inter-digit separator = parens/dashes/dots with
        # AT MOST ONE whitespace, so a parenthesized area code
        # (+966 (011) 225 8000 — ") " and " (") is tolerated, but a DOUBLE
        # space between two distinct numbers ("+966512345678  1010123456")
        # is NOT bridged. plausible_gcc_phone enforces the 8-14 digit gate.
        (?:[\-\.()]{0,2}\s?[\-\.()]{0,2}[0-9٠-٩۰-۹]){6,12}
    )
    |
    (?:
        \b0?5[0-9٠-٩۰-۹](?:[\s\-]?[0-9٠-٩۰-۹]){7}\b
    )
    """
)

_GCC_PREFIXES = ("966", "971", "974", "965", "973", "968")


def _plausible_gcc_phone(raw: str, digits: str) -> bool:
    """Reject implausible phone shapes.

    `raw` is the matched substring with Arabic-Indic digits folded to
    ASCII (so `.` / `+` / `-` semantics are preserved). `digits` is the
    pure-digit fold.
    """
    if not (8 <= len(digits) <= 14):
        return False
    # International: a +/00/(GCC) marker plus a GCC country code at the front
    # (past an optional "00" trunk). The marker is the signal, so spaces, the
    # paren ordering, and dots inside are fine. Covers +966 / 00966 / (968) /
    # +(965) / (+974) / "+ 974" / "00 966" / dotted "+974.4423.0010".
    core = digits[2:] if digits.startswith("00") else digits
    marker = ("+" in raw) or digits.startswith("00") or ("(" in raw[:5])
    if marker and any(core.startswith(p) for p in _GCC_PREFIXES):
        return 9 <= len(digits) <= 14  # country code (3) + 6-11 body digits
    # Local shapes below — a "." here means a version/file string, not a phone.
    if "." in raw:
        return False
    # Saudi mobile (05X / 5X) — recognized broadly because PDF extracts
    # routinely strip the leading 0.
    if digits.startswith("05") or digits.startswith("5"):
        return True
    # Bare-country-code prefix from a `+`/`00`-stripped PDF extraction
    # (`Bill 966540646444 Payment FT…`). Anchored to 12-digit length so
    # generic 12-digit IDs don't match. (Witnessed SA landlines / 920 / bare
    # locals are handled by the witness-cued pass, not here.)
    return len(digits) == 12 and any(digits.startswith(p) for p in _GCC_PREFIXES)


def _boundaries_are_safe(text: str, start: int, end: int) -> bool:
    """Reject the match when its neighbour is itself a digit (ASCII,
    Arabic-Indic, or Persian). Without this, a phone shape could be
    sliced out of the middle of a longer identifier.
    """
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""

    def _is_digit(ch: str) -> bool:
        if not ch:
            return False
        cp = ord(ch)
        return (
            0x30 <= cp <= 0x39
            or 0x0660 <= cp <= 0x0669
            or 0x06F0 <= cp <= 0x06F9
        )

    return not _is_digit(before) and not _is_digit(after)


class PhoneRecognizer:
    name = "phone"
    kind = EntityKind.PHONE
    confidence = 0.93
    requires_witness = False

    def find(self, text: str) -> Iterator[Detection]:
        for m in GCC_PHONE_RE.finditer(text):
            raw = m.group()
            normalized = normalize_digits(raw)
            digits = digits_only(raw)
            if not _plausible_gcc_phone(normalized, digits):
                continue
            if not _boundaries_are_safe(text, m.start(), m.end()):
                continue
            yield Detection(
                start=m.start(),
                end=m.end(),
                kind=EntityKind.PHONE,
                text=raw,
                confidence=0.93,
                source="regex.gcc.phone",
            )
