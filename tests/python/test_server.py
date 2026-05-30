"""Gateway server: request anonymization, JSON endpoints, round-trip."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from apii import default_pipeline  # noqa: E402
from apii.anonymizer import Anonymizer  # noqa: E402
from apii.server import (  # noqa: E402
    anonymize_request_body,
    build_app,
    deanonymize_response_json,
)


def _anon():
    return Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))


def test_anonymize_request_body_anthropic_string_content():
    a = _anon()
    body = {"model": "claude", "messages": [
        {"role": "user", "content": "email ahmed@example.ae phone 0501234567"}]}
    out = anonymize_request_body(body, a)
    txt = out["messages"][0]["content"]
    assert "ahmed@example.ae" not in txt and "0501234567" not in txt
    assert "EMAIL_" in txt and "PHONE_" in txt
    assert out["model"] == "claude"  # non-text fields untouched


def test_anonymize_request_body_block_list_and_system():
    a = _anon()
    body = {
        "system": "Caller IBAN SA0380000000608010167519",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "ring 0501234567"},
            {"type": "image", "source": {"url": "x"}},
        ]}],
    }
    out = anonymize_request_body(body, a)
    assert "SA0380000000608010167519" not in out["system"]
    blocks = out["messages"][0]["content"]
    assert "0501234567" not in blocks[0]["text"]
    assert blocks[1]["type"] == "image"  # non-text block untouched


def test_gateway_round_trip_contract():
    # The core guarantee, without a live upstream: anonymize a request,
    # the "upstream" echoes our tokens in its response, we de-anonymize →
    # the original PII is restored end to end.
    a = _anon()
    body = {"messages": [{"role": "user",
            "content": "Wire to IBAN SA0380000000608010167519 for ahmed@example.ae"}]}
    anon_body = anonymize_request_body(body, a)
    sent = anon_body["messages"][0]["content"]
    # simulate the model referring back to the (tokenized) entities
    upstream = {"choices": [{"message": {"content": f"Confirmed: {sent}"}}]}
    restored = deanonymize_response_json(upstream, a)
    msg = restored["choices"][0]["message"]["content"]
    assert "SA0380000000608010167519" in msg
    assert "ahmed@example.ae" in msg


def test_no_pii_leaks_in_forwarded_request_body():
    # The leak-critical invariant: every user-authored text field is
    # anonymized on the way OUT, so the body forwarded upstream contains
    # ZERO raw PII. We point the egress leak gate at the serialized body —
    # it strips our own tokens first, so any hit is a real leak.
    import json as _json

    from apii.leak_gate import has_residual_pii
    a = _anon()
    body = {
        "model": "x",
        "system": "IBAN SA0380000000608010167519",          # Anthropic
        "instructions": "call 0501234567",                    # OpenAI Responses
        "input": "email ahmed@example.ae",                    # OpenAI Responses
        "messages": [
            {"role": "user", "content": "phone 0559876543, mail ahmad@x.sa"},
            {"role": "user", "content": [
                {"type": "text", "text": "wire SA0380000000608010167519"},
                {"type": "image", "source": {"url": "keep-me"}},
            ]},
        ],
    }
    forwarded = _json.dumps(anonymize_request_body(body, a), ensure_ascii=False)
    assert not has_residual_pii(forwarded), "raw PII leaked into the forwarded body"
    assert "keep-me" in forwarded  # non-text parts pass through untouched


@pytest.mark.parametrize("label,body", [
    # OpenAI Responses nested input array — exactly what the Codex client sends.
    ("responses-input", {"input": [{"type": "message", "role": "user",
        "content": [{"type": "input_text", "text": "mail ahmed@example.ae"}]}]}),
    # Anthropic tool_result with nested content blocks.
    ("tool_result", {"messages": [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tu_1",
         "content": [{"type": "text", "text": "IBAN SA0380000000608010167519"}]}]}]}),
    # Anthropic tool_use with a structured argument dict.
    ("tool_use-input", {"messages": [{"role": "assistant", "content": [
        {"type": "tool_use", "id": "tu_1", "name": "wire",
         "input": {"to": "ahmed@example.ae", "amount": 50}}]}]}),
    # OpenAI chat assistant tool_calls with a JSON arguments string.
    ("tool_calls-args", {"messages": [{"role": "assistant", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "wire", "arguments": '{"phone": "0501234567"}'}}]}]}),
    # OpenAI Responses function_call_output.
    ("fn_call_output", {"input": [{"type": "function_call_output",
        "call_id": "c1", "output": "done for ahmed@example.ae"}]}),
])
def test_structured_shapes_no_pii_leak(label, body):
    # Real clients nest PII below the top level (content blocks, tool
    # results, tool-call arguments). Every such path must be anonymized out.
    import json as _json

    from apii.leak_gate import has_residual_pii
    forwarded = _json.dumps(anonymize_request_body(body, _anon()), ensure_ascii=False)
    assert not has_residual_pii(forwarded), f"raw PII leaked in {label}"


def test_structured_anonymization_preserves_structure():
    # Targeted, not blind: structural fields (types, roles, names, ids, arg
    # keys) survive — only user-authored text is tokenized.
    import json as _json
    body = {
        "input": [
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "mail ahmed@example.ae"}]},
            {"type": "function_call_output", "call_id": "c1", "output": "ok 0501234567"},
        ],
        "messages": [{"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu_1", "name": "wire", "input": {"to": "ahmad@x.sa"}}]}],
    }
    out = anonymize_request_body(body, _anon())
    blob = _json.dumps(out, ensure_ascii=False)
    for s in ("input_text", "function_call_output", "tool_use", "wire",
              "message", "assistant", "call_id", "tu_1", "c1"):
        assert f'"{s}"' in blob, f"structural token {s!r} was mangled"
    inp = out["messages"][0]["content"][0]["input"]
    assert "to" in inp and "ahmad@x.sa" not in inp["to"]  # arg key kept, value tokenized


def test_codex_responses_input_round_trip():
    # Codex's real shape end to end: nested input → tokenized out, the model
    # echoes tokens, de-anon restores the exact original.
    a = _anon()
    body = {"model": "gpt", "input": [{"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "ring 0501234567"}]}]}
    anon_body = anonymize_request_body(body, a)
    sent = anon_body["input"][0]["content"][0]["text"]
    assert "0501234567" not in sent and "PHONE_" in sent
    upstream = {"output": [{"type": "message",
                "content": [{"type": "output_text", "text": sent}]}]}
    restored = deanonymize_response_json(upstream, a)
    assert restored["output"][0]["content"][0]["text"] == "ring 0501234567"


def test_health_and_detect_and_anonymize_endpoints():
    client = TestClient(build_app(secret="k", tenant="t"))
    assert client.get("/health").json()["status"] == "ok"

    det = client.post("/v1/detect", json={"text": "email ahmed@example.ae"})
    assert det.status_code == 200
    assert any(r["kind"] == "EMAIL" for r in det.json())

    an = client.post("/v1/anonymize", json={"text": "phone 0501234567"})
    body = an.json()
    assert "0501234567" not in body["text"]
    assert body["records"] and body["records"][0]["kind"] == "PHONE"

    # round-trip through the deanonymize endpoint
    de = client.post("/v1/deanonymize", json={"text": body["text"], "records": body["records"]})
    assert de.json()["text"] == "phone 0501234567"
