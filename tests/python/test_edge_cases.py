"""Regression tests for tricky edge cases across the pipeline."""

from __future__ import annotations

from apii import default_pipeline
from apii.anonymizer import Anonymizer, EntityRecord
from apii.streaming import StreamDeanonymizer, _as_int, _split_keep_lf
from apii.types import EntityKind


def _anon_with(records):
    return Anonymizer.from_records("k", "t", records, pipeline=default_pipeline(enable_ner=False))


# ── SSE split only on \n, not Unicode line separators ──

def test_split_keep_lf_ignores_unicode_line_separators():
    # U+2028 line-separator inside a data: payload must NOT split the event.
    raw = "data: {\"a\":\"x y\"}\n\n"
    parts = _split_keep_lf(raw)
    assert any(" " in p for p in parts)  # the LS stays inside one line
    assert all(p.endswith("\n") or p == parts[-1] for p in parts)


def test_token_with_unicode_separator_not_leaked_by_splitlines():
    recs = [EntityRecord(kind=EntityKind.PHONE, token="PHONE_AABBCCDD11", value="0501234567", normalized="0501234567")]
    a = _anon_with(recs)
    # A vault token adjacent to a U+2028 — must still be de-anonymized.
    sse = "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"x  PHONE_AABBCCDD11\"}}]}\n\n"
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "PHONE_AABBCCDD11" not in out
    assert "0501234567" in out


# ── OpenAI tool-call carry streams don't collide ──

def test_openai_tool_call_streams_do_not_collide():
    # Tokens are PHONE_ + exactly 10 hex chars. content carries the "1" token,
    # the tool-call arguments carry the "2" token; each is split across the
    # two SSE events and must reassemble in its OWN carry stream (no bleed).
    recs = [
        EntityRecord(kind=EntityKind.PHONE, token="PHONE_1111111111", value="0501111111", normalized="0501111111"),
        EntityRecord(kind=EntityKind.PHONE, token="PHONE_2222222222", value="0502222222", normalized="0502222222"),
    ]
    a = _anon_with(recs)
    sd = StreamDeanonymizer(a)
    sse = (
        'data: {"choices":[{"index":0,"delta":{"content":"see PHONE_111","tool_calls":['
        '{"function":{"arguments":"x PHONE_222"}}]}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"content":"1111111","tool_calls":['
        '{"function":{"arguments":"2222222"}}]}}]}\n\n'
    )
    out = sd.process_stream(sse)
    # Each token completes in its OWN stream and restores correctly; no bleed.
    assert "0501111111" in out  # content token reassembled
    assert "0502222222" in out  # tool-call token reassembled (separate stream)
    assert "PHONE_1111111111" not in out and "PHONE_2222222222" not in out


# ── _as_int strict integer semantics ──

def test_as_int_strict():
    assert _as_int(3, 0) == 3
    assert _as_int(True, 9) == 9   # bool is not an integer index
    assert _as_int(2.0, 9) == 9    # float not coerced
    assert _as_int("4", 9) == 9    # numeric string not coerced
    assert _as_int(None, 9) == 9


# ── vault tolerates unknown kinds ──

def test_vault_load_tolerates_unknown_kinds(tmp_path):
    import base64
    import hashlib
    import json

    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    from apii import vault
    # Hand-craft an encrypted vault holding an in-scope PHONE record and a
    # CREDIT_CARD record (a kind apii's enum doesn't model).
    payload = {"version": 1, "records": [
        {"kind": "PHONE", "token": "PHONE_AABBCCDD11", "value": "0501234567", "normalized": "0501234567"},
        {"kind": "CREDIT_CARD", "token": "CARD_DEADBEEF12", "value": "4111111111111111", "normalized": "4111111111111111"},
    ]}
    key = hashlib.sha256(b"k").digest()
    nonce = b"\x00" * 12
    ct = ChaCha20Poly1305(key).encrypt(nonce, json.dumps(payload).encode(), None)
    env = {"version": 1, "cipher": "CHACHA20POLY1305-SHA256-KEY",
           "nonce": base64.standard_b64encode(nonce).decode(),
           "ciphertext": base64.standard_b64encode(ct).decode()}
    p = tmp_path / "mixed.vault"
    p.write_text(json.dumps(env))
    recs = vault.load_or_default(p, "k")  # must NOT raise on CREDIT_CARD
    kinds = {r.kind for r in recs}
    assert EntityKind.PHONE in kinds
    assert len(recs) == 1  # the in-scope record loaded; the CARD record skipped


# ── detection doesn't re-fire on our own vault tokens ──

def test_placeholder_tokens_not_redetected():
    p = default_pipeline(enable_ner=False)
    # A line full of our tokens must produce ZERO detections (re-processing
    # already-redacted text is idempotent).
    dets = p.detect("see PHONE_AABBCCDD11 and GOV_ID_1234ABCD56 and BANK_ALRAJHI")
    assert dets == []


def test_anonymize_then_anonymize_is_idempotent():
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    once = a.anonymize("phone 0501234567 acct ACC-GCC-77889900").text
    twice = a.anonymize(once).text
    assert once == twice  # tokens not re-detected on the second pass


# ── hook edge semantics ──

def test_hook_event_name_key_presence_semantics():
    from apii.hook import HookClient, run_hook
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    # present-but-null hook_event_name does NOT fall back to camelCase.
    assert run_hook({"hook_event_name": None, "hookEventName": "UserPromptSubmit",
                     "prompt": "call 0501234567"}, HookClient.CLAUDE, a) is None
    # absent snake_case → camelCase used.
    assert run_hook({"hookEventName": "UserPromptSubmit", "prompt": "call 0501234567"},
                    HookClient.CLAUDE, a) is not None
    # non-dict body → safe no-op.
    assert run_hook("\"just a string\"", HookClient.CLAUDE, a) is None


# ── suppressor tag for an unknown kind is inert, not global ──

def test_suppressor_unknown_kind_tag_is_inert():
    from apii.suppressor import Suppressor
    s = Suppressor.from_text("SECRET:total\nearth")
    # "total" was tagged to a kind apii never emits → must NOT suppress globally.
    dets = [_det_person("total"), _det_person("earth")]
    kept = {d.text for d in s.filter(dets)}
    assert "total" in kept        # SECRET:total is inert
    assert "earth" not in kept    # global "earth" still drops


def _det_person(text):
    from apii.types import Detection
    return Detection(start=0, end=len(text), kind=EntityKind.PERSON, text=text, confidence=0.9, source="t")


# ── full SHA-256 path hash ──

def test_batch_path_hash_is_full_sha256(tmp_path):
    from apii.batch import scan_dir
    (tmp_path / "a.txt").write_text("phone 0501234567")
    out = tmp_path / "s.jsonl"
    scan_dir(tmp_path, "txt", out, pipeline=default_pipeline(enable_ner=False))
    import json
    row = json.loads(out.read_text().splitlines()[0])
    assert len(row["path_hash"]) == 64  # full digest, not truncated to 16


# ── vertical tab before a brace is TXT, not JSON ──

def test_from_bytes_vertical_tab_is_txt():
    from apii.documents import DocumentKind
    assert DocumentKind.from_bytes(b"\x0b{\"a\":1}") is DocumentKind.TXT
    assert DocumentKind.from_bytes(b"  {\"a\":1}") is DocumentKind.JSON


# ── phone over-consumption + 00-prefix edge cases ──

def test_phone_double_space_does_not_swallow_neighbour():
    from apii.recognizers import PHONE
    # An intl phone followed by a double space + another digit run must NOT
    # over-consume into the neighbour and drop both (fuzz repro).
    dets = [d.text for d in PHONE.find("+966512345678  1010123456")]
    assert "+966512345678" in dets


def test_phone_00_prefix_international_detected():
    from apii.recognizers import PHONE
    # 00-prefixed international GCC phones (the leak gate flags these, so
    # detection must too).
    assert any(d.text == "00966555550808" for d in PHONE.find("00966555550808"))
    assert any(d.text == "00966512345678" for d in PHONE.find("call 00966512345678 now"))


def test_phone_parenthesized_area_code_still_works():
    from apii.recognizers import PHONE
    # The single-whitespace separator tightening must not break the
    # parenthesized area-code form.
    assert any("(011)" in d.text for d in PHONE.find("Tel: +966 (011) 225 8000 ext"))
    assert any(d.text == "(+974) 44033333" for d in PHONE.find("Call (+974) 44033333"))


# ── marker-gated international PHONE shapes ──

def test_phone_marker_gated_international_shapes():
    from apii.recognizers import PHONE

    def one(t):
        d = list(PHONE.find(t))
        assert len(d) == 1, (t, [x.text for x in d])
        return d[0].text

    # + before the paren, single-digit area + grouped pairs.
    assert one("Phone: +(965) 1 85 85 85.") == "+(965) 1 85 85 85"
    # Parenthesized country code with NO +/00 — the paren IS the marker.
    assert one("Tel: (968) 23293333.") == "(968) 23293333"
    # Space after + / after 00.
    assert one("Telephone: + 974 4403 4980.") == "+ 974 4403 4980"
    assert one("Tel: 00 96614678414.") == "00 96614678414"
    # space-dash-space and en-dash dividers after the country code.
    assert one("Telephone: 00965 - 23989111.") == "00965 - 23989111"
    assert one("Fax: 00965 – 23983661.") == "00965 – 23983661"
    # Dotted international — the . reject must not apply once +/cc is present.
    assert one("Phone: +974.4423.0010.") == "+974.4423.0010"
    # No leading space is ever captured in any of the above.
    for t in ["Tel: (968) 23293333.", "x + 974 4403 4980 y"]:
        assert all(not d.text.startswith(" ") for d in PHONE.find(t))


def test_phone_marker_gated_does_not_overfire_on_bare_numbers():
    from apii.recognizers import PHONE
    # No +/00/(GCC) marker → must NOT fire (these need the witness-cued pass,
    # not a bare numeric rule that would shred order ids / references).
    assert list(PHONE.find("Order 24145989 shipped")) == []
    assert list(PHONE.find("ref 0114670375 xyz")) == []
    assert list(PHONE.find("invoice 1010032264 due")) == []
