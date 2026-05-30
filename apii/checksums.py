"""Shared checksum primitives — Luhn, IBAN MOD-97, Kuwait Civil ID mod-11.

Each function takes a clean, digit-folded string (caller responsibility:
fold Arabic-Indic via `apii.normalize.digits_only` / `alnum_upper` first).

Empirical coverage:

  Luhn        — Saudi National ID / Iqama (100% on known-valid samples).
                Also the standard credit-card check.
  iban_mod97  — ISO/IEC 7064 MOD-97-10 over a rearranged IBAN.
  kuwait_mod11 — Kuwait Civil ID weights [2,1,6,3,7,9,10,5,8,4,2].

Saudi commercial registration (CR) and VAT registration intentionally
have no checksum function here: real public CRs sit at the ~10%
random-noise floor for every standard scheme, so any "checksum" would be
false confidence. CR/VAT recognizers stay structural-only.
"""

from __future__ import annotations


def luhn(digits: str) -> bool:
    """Standard Luhn (rightmost digit is the check digit).

    Caller must pre-fold Arabic-Indic digits — this function only accepts
    ASCII 0-9.

    All-zero strings are rejected (`sum > 0`). Without this an `00000000…`
    BBAN would pass and shadow every other recognizer with a bogus
    credit-card hit.
    """
    if not digits or not digits.isascii() or not digits.isdigit():
        return False
    total = 0
    double = False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if double:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        double = not double
    return total > 0 and total % 10 == 0


def iban_mod97(rearranged: str) -> int:
    """ISO/IEC 7064 MOD-97-10 over an already-rearranged IBAN string.

    "Rearranged" means the leading 4 chars (country code + check digits)
    have been moved to the end. A valid IBAN yields a remainder of 1.
    Returns -1 on any non-alphanumeric character.

    Letters map A=10 … Z=35; multi-digit values are folded as base-100 /
    base-10 hops so the running remainder stays in int range.
    """
    rem = 0
    for ch in rearranged:
        c = ord(ch)
        if 48 <= c <= 57:  # 0-9
            v = c - 48
        elif 65 <= c <= 90:  # A-Z
            v = c - 55
        else:
            return -1
        rem = (rem * 100 + v) % 97 if v > 9 else (rem * 10 + v) % 97
    return rem


def kuwait_mod11(digits: str) -> bool:
    """Kuwait Civil ID checksum: weights [2,1,6,3,7,9,10,5,8,4,2].

    The 12-digit Civil ID starts with 2 or 3 (century marker) and the
    last digit is the checksum. Sum of the first 11 digits × weights,
    check = (11 - sum % 11), which must equal digit 12 and be ≤ 9.
    """
    if not digits.isascii() or not digits.isdigit() or len(digits) != 12:
        return False
    if digits[0] not in "23":
        return False
    weights = (2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    total = sum((ord(digits[i]) - 48) * weights[i] for i in range(11))
    check = 11 - (total % 11)
    return check <= 9 and check == (ord(digits[11]) - 48)
