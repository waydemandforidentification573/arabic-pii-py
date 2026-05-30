"""SSE carry-buffer de-anonymization (token split across events)."""

from __future__ import annotations

from apii import default_pipeline
from apii.anonymizer import Anonymizer, EntityRecord
from apii.streaming import CarryStream, StreamDeanonymizer, safe_split
from apii.types import EntityKind


def _anon():
    recs = [
        EntityRecord(kind=EntityKind.PERSON, token="PERSON_ABCDEF1234",
                     value="محمد العتيبي", normalized="محمد العتيبي"),
        EntityRecord(kind=EntityKind.IBAN, token="IBAN_99AABBCCDD",
                     value="SA0380000000608010167519", normalized="SA0380000000608010167519"),
    ]
    return Anonymizer.from_records("k", "t", recs, pipeline=default_pipeline(enable_ner=False))


def test_safe_split_holds_back_trailing_partial_token():
    assert safe_split("hi PERSON_ABCDEF1234 bye") == len("hi PERSON_ABCDEF1234 bye")
    assert safe_split("hi PERSON_AB") == len("hi ")
    assert safe_split("plain text") == len("plain text")
    assert safe_split("") == 0


def test_safe_split_releases_overlong_run():
    long_run = "X" * 100
    assert safe_split("hi " + long_run) == len("hi " + long_run)


def test_carry_stream_reassembles_split_token():
    a = _anon()
    cs = CarryStream()
    out = cs.push("hi PERSON_ABC", a)  # holds back PERSON_ABC
    out += cs.push("DEF1234 bye", a)   # completes the token
    out += cs.flush(a)
    assert "محمد العتيبي" in out
    assert "PERSON_ABCDEF1234" not in out


def test_process_stream_anthropic_text_delta_split_across_events():
    a = _anon()
    sse = (
        'event: content_block_delta\n'
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi PERSON_ABC"}}\n\n'
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"DEF1234 there"}}\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "محمد العتيبي" in out
    assert "PERSON_ABCDEF1234" not in out


def test_signature_delta_is_never_mutated():
    a = _anon()
    # A signature_delta whose value happens to contain a token must NOT
    # be de-anonymized (it's a cryptographic field).
    sse = (
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"signature_delta","signature":"PERSON_ABCDEF1234"}}\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "PERSON_ABCDEF1234" in out  # untouched
    assert "محمد العتيبي" not in out


def test_openai_delta_content_restored():
    a = _anon()
    sse = (
        'data: {"choices":[{"index":0,"delta":{"content":"see PERSON_ABCDEF1234"}}]}\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "محمد العتيبي" in out


def test_done_sentinel_passes_through():
    a = _anon()
    out = StreamDeanonymizer(a).process_stream("data: [DONE]\n\n")
    assert "[DONE]" in out


def test_openai_chat_token_split_across_chunks_then_done():
    a = _anon()
    sse = (
        'data: {"choices":[{"index":0,"delta":{"content":"ref IBAN_99"}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"content":"AABBCCDD"}}]}\n\n'
        'data: [DONE]\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "SA0380000000608010167519" in out
    assert "IBAN_99AABBCCDD" not in out


def test_flush_emitted_before_terminator_openai_chat():
    # Regression for the dropped-trailing-token bug: a token still held in
    # the carry at end-of-stream must be flushed BEFORE [DONE] (a client
    # stops reading at the terminator), and in the OpenAI chunk shape.
    a = _anon()
    sse = (
        'data: {"choices":[{"index":0,"delta":{"content":"ref IBAN_99"}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"content":"AABBCCDD"}}]}\n\n'
        'data: [DONE]\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert out.index("SA0380000000608010167519") < out.index("[DONE]")
    assert "chat.completion.chunk" in out  # provider-correct synthetic, not Anthropic


def test_flush_emitted_before_terminator_anthropic():
    # Same regression, Anthropic flavor: residual flushed before message_stop,
    # as a content_block_delta (the bug bit Anthropic too).
    a = _anon()
    sse = (
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"x IBAN_99"}}\n\n'
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"AABBCCDD"}}\n\n'
        'data: {"type":"message_stop"}\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "SA0380000000608010167519" in out
    assert "IBAN_99AABBCCDD" not in out
    assert out.index("SA0380000000608010167519") < out.index("message_stop")


# ── OpenAI Responses (streaming) ──

def test_responses_output_text_delta_inline_complete_token():
    a = _anon()
    sse = (
        'event: response.output_text.delta\n'
        'data: {"type":"response.output_text.delta","item_id":"m","output_index":0,'
        '"content_index":0,"delta":"see PERSON_ABCDEF1234 now"}\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "محمد العتيبي" in out and "PERSON_ABCDEF1234" not in out


def test_responses_function_call_arguments_split_across_events():
    a = _anon()
    sse = (
        'data: {"type":"response.function_call_arguments.delta","item_id":"fc","output_index":0,'
        '"delta":"{\\"iban\\":\\"IBAN_99"}\n\n'
        'data: {"type":"response.function_call_arguments.delta","item_id":"fc","output_index":0,'
        '"delta":"AABBCCDD\\"}"}\n\n'
        'data: {"type":"response.function_call_arguments.done","item_id":"fc","output_index":0,'
        '"arguments":"{\\"iban\\":\\"IBAN_99AABBCCDD\\"}"}\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "SA0380000000608010167519" in out
    assert "IBAN_99AABBCCDD" not in out


def test_responses_terminal_events_deanonymized_wholesale():
    # Bug B: terminal events re-send the FULL text — must be restored.
    a = _anon()
    sse = (
        'event: response.output_text.done\n'
        'data: {"type":"response.output_text.done","item_id":"m","output_index":0,'
        '"content_index":0,"text":"final: PERSON_ABCDEF1234"}\n\n'
        'event: response.completed\n'
        'data: {"type":"response.completed","sequence_number":9,"response":{"output":'
        '[{"type":"message","content":[{"type":"output_text","text":"done with PERSON_ABCDEF1234"}]}]}}\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "PERSON_ABCDEF1234" not in out          # restored in BOTH terminal events
    assert out.count("محمد العتيبي") >= 2


def test_responses_item_ids_do_not_bleed():
    # Composite carry key: two item_ids split two different tokens; the
    # terminal events restore each with no cross-contamination.
    a = _anon()
    sse = (
        'data: {"type":"response.output_text.delta","item_id":"A","output_index":0,"content_index":0,"delta":"x PERSON_ABC"}\n\n'
        'data: {"type":"response.output_text.delta","item_id":"B","output_index":1,"content_index":0,"delta":"y IBAN_99"}\n\n'
        'data: {"type":"response.output_text.delta","item_id":"A","output_index":0,"content_index":0,"delta":"DEF1234"}\n\n'
        'data: {"type":"response.output_text.delta","item_id":"B","output_index":1,"content_index":0,"delta":"AABBCCDD"}\n\n'
        'data: {"type":"response.output_text.done","item_id":"A","output_index":0,"content_index":0,"text":"PERSON_ABCDEF1234"}\n\n'
        'data: {"type":"response.output_text.done","item_id":"B","output_index":1,"content_index":0,"text":"IBAN_99AABBCCDD"}\n\n'
    )
    out = StreamDeanonymizer(a).process_stream(sse)
    assert "محمد العتيبي" in out and "SA0380000000608010167519" in out
    assert "PERSON_ABCDEF1234" not in out and "IBAN_99AABBCCDD" not in out
