"""Structured-output (JSON) anonymization.

In structured data a field's KEY NAME reveals the kind even when the bare
value has no surrounding text context: a "cr_number" field holding
"1010123456" is a commercial registration; the free-text detector would
miss it without a label. `sensitive_key_kind` maps a key hint → kind;
`anonymize_structured` walks a parsed JSON value, tokenizing string leaves
(by key hint, else by running the text detector on the value) while
preserving the structure's shape.

`sensitive_key_kind` maps a key to one of the kinds apii detects; keys like
"api_key" / "card" / "cif" yield no key-based kind, so their values simply
fall through to normal text detection. `looks_like_placeholder` recognizes
every token prefix apii may emit, so already-tokenized input round-trips
without being re-detected.
"""

from __future__ import annotations

from typing import Optional

from apii.types import EntityKind

# Keys whose values are amounts / dates / indices — never PII; skip.
_SKIP = (
    "amount", "balance", "debit", "credit", "total", "subtotal", "tax_amount",
    "vat_amount", "date", "time", "row_index", "index", "page",
    "رصيد", "مدين", "دائن", "مبلغ", "تاريخ",
)

# (terms, kind) groups in priority order, one per kind apii detects.
_KEY_GROUPS: list[tuple[tuple[str, ...], EntityKind, bool]] = [
    (("email", "e_mail", "mail", "بريد"), EntityKind.EMAIL, False),
    (("phone", "mobile", "tel", "جوال", "هاتف"), EntityKind.PHONE, False),
    (("iban", "آيبان", "ايبان"), EntityKind.IBAN, False),
    (("commercial_registration", "cr_number", "cr_no", "registration_number",
      "سجل", "تجاري", "س.ت"), EntityKind.COMMERCIAL_REGISTRATION, False),
    (("vat", "trn", "tax_number", "tax_id", "tin", "zakat", "ضريبة", "زكاة"),
     EntityKind.TAX_NUMBER, False),
    (("national_id", "emirates_id", "civil_id", "iqama", "id_number",
      "هوية", "إقامة", "اقامة", "مدني"), EntityKind.NATIONAL_ID, False),
    (("company", "organization", "organisation", "merchant", "seller", "buyer",
      "beneficiary", "remitter", "sender", "receiver", "party", "vendor", "supplier",
      "شركة", "منشأة", "مؤسسة", "مستفيد", "مرسل", "بائع", "مشتري", "مورد"),
     EntityKind.ORGANIZATION, False),
    (("person_name", "customer_name", "employee_name", "owner_name",
      "shareholder_name", "signatory", "director", "manager",
      "اسم", "عميل", "موظف", "مالك", "مساهم", "مفوض", "مدير"),
     EntityKind.PERSON, True),  # requires an alphabetic char in the value
]

_PRIVATE_PREFIXES = frozenset({
    "EMAIL", "PHONE", "IBAN", "CR", "TAX_ID", "GOV_ID",
    "PERSON", "ORG", "ADDRESS",
})
_PUBLIC_PREFIXES = frozenset({"BANK", "TELCO", "CHANNEL", "PAYMENT_RAIL", "GOV"})

_SEPARATORS = "_-. /"


def _key_contains(key: str, terms: tuple[str, ...]) -> bool:
    """Exact-segment match for simple ASCII words (so `max_tokens` doesn't
    hit `token`), substring for multi-word / non-ASCII terms."""
    segments = key.replace("-", "_").replace(".", "_").replace(" ", "_").replace("/", "_").split("_")
    for term in terms:
        simple_ascii = term.isascii() and not any(c in term for c in _SEPARATORS)
        if simple_ascii:
            if any(seg == term for seg in segments):
                return True
        elif term in key:
            return True
    return False


def sensitive_key_kind(key_hint: Optional[str], value: str) -> Optional[EntityKind]:
    """Map a JSON key name → in-scope EntityKind, or None."""
    if key_hint is None:
        return None
    key = key_hint.lower()
    if _key_contains(key, _SKIP):
        return None
    for terms, kind, needs_alpha in _KEY_GROUPS:
        if _key_contains(key, terms):
            if needs_alpha and not any(ch.isalpha() for ch in value):
                continue
            return kind
    return None


def looks_like_placeholder(value: str) -> bool:
    """True if `value` is already an emitted token (private PREFIX_HEX or
    public semantic token)."""
    value = value.strip()
    if "_" not in value:
        return False
    prefix, _, suffix = value.rpartition("_")
    if prefix in _PRIVATE_PREFIXES:
        return 10 <= len(suffix) <= 32 and all(c in "0123456789abcdefABCDEF" for c in suffix)
    if prefix in _PUBLIC_PREFIXES:
        return bool(suffix) and all(c.isascii() and (c.isupper() or c.isdigit() or c == "_") for c in suffix)
    return False


def anonymize_structured(value, anonymizer, key_hint: Optional[str] = None):
    """Recursively anonymize string leaves of a parsed JSON value.

    For each string: an already-emitted token is left as-is; a key hint
    that maps to a kind tokenizes the WHOLE value as that kind (catching
    bare identifiers); otherwise the value runs through normal text
    anonymization. Dicts/lists are walked preserving shape; the
    anonymizer's vault is populated for restore.
    """
    if isinstance(value, dict):
        return {k: anonymize_structured(v, anonymizer, key_hint=k) for k, v in value.items()}
    if isinstance(value, list):
        return [anonymize_structured(v, anonymizer, key_hint=key_hint) for v in value]
    if isinstance(value, str):
        if looks_like_placeholder(value):
            return value
        kind = sensitive_key_kind(key_hint, value)
        if kind is not None:
            return anonymizer.token_for_value(kind, value)
        return anonymizer.anonymize(value).text
    return value  # numbers / bools / null untouched


def deanonymize_structured(value, anonymizer):
    """Restore tokens in a parsed JSON value (walk every string leaf)."""
    if isinstance(value, dict):
        return {k: deanonymize_structured(v, anonymizer) for k, v in value.items()}
    if isinstance(value, list):
        return [deanonymize_structured(v, anonymizer) for v in value]
    if isinstance(value, str):
        return anonymizer.deanonymize(value)
    return value
