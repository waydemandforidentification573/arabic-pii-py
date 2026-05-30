"""JSON document adapter — extract string-leaf segments + redact round-trip.

String VALUES become segments (keys never), objects walk in sorted-key
order, and numbers/bools/nulls round-trip untouched. Stdlib-only (no
importorskip).
"""

from __future__ import annotations

import json

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.documents import DocumentKind, redact_document
from apii.documents._base import JsonPath
from apii.documents.json import JsonAdapter

LEAF_SEP = "\x1e"


def _paths(extracted):
    return [s.source.path for s in extracted.segments if isinstance(s.source, JsonPath)]


def test_extract_string_leaves_sorted_order():
    # keys: age (number, skipped), meta, name, phone -> 3 string leaves
    # in sorted-key order: /meta/city, /name, /phone.
    data = b'{"name":"Ahmed","phone":"0501234567","age":30,"meta":{"city":"Riyadh"}}'
    ex = JsonAdapter.extract(data)
    assert ex.kind is DocumentKind.JSON
    assert "Ahmed" in ex.text
    assert "0501234567" in ex.text
    assert "Riyadh" in ex.text
    # age=30 is a number, not a string leaf -> not in detector view.
    assert "30" not in ex.text
    assert _paths(ex) == ["/meta/city", "/name", "/phone"]
    assert len(ex.segments) == 3


def test_extract_offsets_index_into_text():
    data = b'{"name":"Ahmed","phone":"0501234567"}'
    ex = JsonAdapter.extract(data)
    # Each segment's char range must slice the exact leaf value out of text.
    for seg in ex.segments:
        start, end = seg.text_range
        assert ex.text[start:end] in ("Ahmed", "0501234567")
    # Joined with the record separator, terminated by one.
    assert ex.text == "Ahmed" + LEAF_SEP + "0501234567" + LEAF_SEP


def test_keys_never_extracted():
    data = b'{"customer_name":"Ahmed"}'
    ex = JsonAdapter.extract(data)
    assert "Ahmed" in ex.text
    assert "customer_name" not in ex.text


def test_rfc6901_pointer_escapes():
    data = b'{"a/b":"value","c~d":"another"}'
    ex = JsonAdapter.extract(data)
    paths = _paths(ex)
    assert "/a~1b" in paths  # `/` -> `~1`
    assert "/c~0d" in paths  # `~` -> `~0`


def test_array_index_pointers():
    data = b'{"items":["x","y"]}'
    ex = JsonAdapter.extract(data)
    assert _paths(ex) == ["/items/0", "/items/1"]


def test_emit_preserves_non_string_leaves():
    data = b'{"count":42,"active":true,"tags":null,"name":"Ahmed"}'
    ex = JsonAdapter.extract(data)
    anonymized = ex.text.replace("Ahmed", "PERSON_TOKEN")
    out = JsonAdapter.emit(data, ex, anonymized)
    reparsed = json.loads(out)
    assert reparsed["count"] == 42
    assert reparsed["active"] is True
    assert reparsed["tags"] is None
    assert reparsed["name"] == "PERSON_TOKEN"


def test_emit_token_substitution():
    data = b'{"name":"Ahmed","phone":"0501234567"}'
    ex = JsonAdapter.extract(data)
    anonymized = ex.text.replace("Ahmed", "PERSON_TOKEN").replace("0501234567", "PHONE_TOKEN")
    out = JsonAdapter.emit(data, ex, anonymized)
    reparsed = json.loads(out)
    assert reparsed["name"] == "PERSON_TOKEN"
    assert reparsed["phone"] == "PHONE_TOKEN"


def test_extract_no_string_leaves():
    # Zero string leaves -> empty detector view, empty segments, no
    # phantom leaf on emit (the empty-anonymized guard).
    data = b'{"a":1,"b":true,"c":null}'
    ex = JsonAdapter.extract(data)
    assert ex.text == ""
    assert ex.segments == []
    out = JsonAdapter.emit(data, ex, ex.text)
    assert json.loads(out) == {"a": 1, "b": True, "c": None}


def test_extract_invalid_json_raises():
    import pytest

    from apii.documents._base import DocumentError

    with pytest.raises(DocumentError):
        JsonAdapter.extract(b"{not valid json")


def test_arabic_round_trips_utf8():
    data = json.dumps({"city": "الرياض"}, ensure_ascii=False).encode("utf-8")
    ex = JsonAdapter.extract(data)
    out = JsonAdapter.emit(data, ex, ex.text)
    # Raw UTF-8, not \uXXXX escapes.
    assert "الرياض".encode("utf-8") in out
    assert json.loads(out)["city"] == "الرياض"


def test_redact_document_round_trip():
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    original = {
        "name": "Ahmed",
        "contact": {"phone": "0501234567", "email": "a@b.ae"},
        "age": 30,
        "tags": ["vip", "0501234567"],
    }
    data = json.dumps(original, ensure_ascii=False).encode("utf-8")
    kind, out, report = redact_document(data, a, kind=DocumentKind.JSON)
    assert kind is DocumentKind.JSON
    redacted = out.decode("utf-8")
    # PII gone, tokens spliced in.
    assert "0501234567" not in redacted
    assert "a@b.ae" not in redacted
    assert "PHONE_" in redacted
    assert "EMAIL_" in redacted
    # Non-string and structure preserved.
    reparsed = json.loads(redacted)
    assert reparsed["age"] == 30
    # Deanonymize restores the original structure + values (order/format
    # independent compare).
    restored = a.deanonymize(redacted)
    assert json.loads(restored) == original
