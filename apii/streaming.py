"""Streaming SSE de-anonymization.

When the proxy streams an LLM response back, a vault token (PERSON_AB12…)
can be split across two SSE events. A per-stream carry buffer holds back
the trailing run of token-shape chars ([A-Z0-9_]) at the end of each
fragment so a split token still round-trips.

Dispatch is by event SHAPE, so one de-anonymizer transparently handles
every provider flavour on the same connection:
  - Anthropic ``content_block_delta``: delta.text (text_delta),
    delta.thinking (thinking_delta), delta.partial_json (input_json_delta).
    delta.signature (signature_delta) is cryptographic — NEVER mutated.
  - OpenAI Chat chunk: choices[].delta.content and
    choices[].delta.tool_calls[].function.arguments.
  - OpenAI Responses events: the text/tool-arg `*.delta` events are
    carry-buffered; the terminal `*.done` / `response.completed` events
    re-send the full text and are de-anonymized wholesale.

Each text carry buffer registers a *builder* that can re-emit its residual
in the correct provider shape. Any carry left at end-of-stream is flushed
as a provider-correct synthetic event BEFORE the stream terminator
(``[DONE]`` / ``message_stop`` / ``response.completed``), so a client that
stops reading at the terminator still receives it.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

# Upper bound on token length, with headroom. A trailing token-char run
# longer than this can't be a partial token, so we never carry more than
# this many chars.
_MAX_TOKEN_CHARS = 64


def safe_split(text: str) -> int:
    """Char index up to which `text` is safe to emit now. The trailing
    run of token-shape chars [A-Z0-9_] might be a token-in-progress and
    is held back — unless it's too long to be a real token."""
    n = len(text)
    if n == 0:
        return 0
    trailing_start = n
    for i in range(n - 1, -1, -1):
        c = text[i]
        if "A" <= c <= "Z" or "0" <= c <= "9" or c == "_":
            trailing_start = i
        else:
            break
    if n - trailing_start > _MAX_TOKEN_CHARS:
        return n
    return trailing_start


class CarryStream:
    """Carry-buffered de-anonymizer for one logical text stream."""

    def __init__(self) -> None:
        self.carry = ""

    def push(self, fragment: str, anonymizer) -> str:
        self.carry += fragment
        split = safe_split(self.carry)
        emit, self.carry = self.carry[:split], self.carry[split:]
        return anonymizer.deanonymize(emit)

    def flush(self, anonymizer) -> str:
        if not self.carry:
            return ""
        out = anonymizer.deanonymize(self.carry)
        self.carry = ""
        return out


_ANTHROPIC_DELTA_FIELD = {
    "text_delta": "text",
    "thinking_delta": "thinking",
    "input_json_delta": "partial_json",
}

# Data payloads / event types that terminate a stream (per provider).
_TERMINATOR_TYPES = {"message_stop", "response.completed"}

# OpenAI Responses streaming delta events whose `delta` field is model text
# (or tool-call argument fragments) we de-anonymize. Audio (base64) is excluded.
_RESPONSES_TEXT_DELTAS = {
    "response.output_text.delta",
    "response.refusal.delta",
    "response.reasoning_text.delta",
    "response.reasoning_summary_text.delta",
    "response.function_call_arguments.delta",
}


def _sse(data_obj, event: Optional[str] = None) -> str:
    """Serialize one SSE event block (with the trailing blank line). Built
    from a dict via json.dumps, so a synthetic event is never malformed."""
    head = f"event: {event}\n" if event else ""
    return head + "data: " + json.dumps(data_obj, ensure_ascii=False, separators=(",", ":")) + "\n\n"


class StreamDeanonymizer:
    """Stateful SSE de-anonymizer; one per proxied streaming response.

    Shape-driven: Anthropic / OpenAI-Chat events (and, in later flavours,
    OpenAI-Responses / Gemini) are recognized by structure, so the same
    instance handles whatever the upstream speaks. Each text carry buffer
    registers a builder that re-emits its residual in the matching shape."""

    def __init__(self, anonymizer) -> None:
        self._anon = anonymizer
        self._streams: dict = {}
        # carry-key -> residual builder (None = no synthetic flush; the
        # provider re-sends the full text at end, e.g. OpenAI Responses).
        self._synth: dict[object, Optional[Callable[[str], str]]] = {}

    def _push(self, key, builder: Callable[[str], str], text: str) -> str:
        """De-anonymize `text` through the carry buffer for `key`, creating
        it (and registering its residual `builder`) on first use."""
        s = self._streams.get(key)
        if s is None:
            self._streams[key] = s = CarryStream()
            self._synth[key] = builder
        return s.push(text, self._anon)

    # ── per-event rewrite (shape-dispatched) ──

    def process_event_data(self, data: str) -> str:
        """Rewrite one SSE `data:` JSON payload. Non-JSON / sentinels
        (e.g. `[DONE]`) pass through untouched."""
        try:
            value = json.loads(data)
        except (ValueError, TypeError):
            return data
        if not isinstance(value, dict):
            return data
        t = value.get("type")
        if t == "content_block_delta":
            self._rewrite_anthropic(value)
        elif isinstance(t, str) and t.startswith("response."):
            self._rewrite_responses(value)
        elif isinstance(value.get("choices"), list):
            self._rewrite_openai_chat(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _rewrite_anthropic(self, value: dict) -> None:
        index = _as_int(value.get("index"), 0)
        delta = value.get("delta")
        if not isinstance(delta, dict):
            return
        dtype = delta.get("type", "")
        field = _ANTHROPIC_DELTA_FIELD.get(dtype)
        # signature_delta (and unknown types) are never mutated.
        if field is None or not isinstance(delta.get(field), str):
            return

        def build(text: str, i: int = index, dt: str = dtype, f: str = field) -> str:
            return _sse({"type": "content_block_delta", "index": i,
                         "delta": {"type": dt, f: text}})

        delta[field] = self._push(("a", index), build, delta[field])

    def _rewrite_openai_chat(self, value: dict) -> None:
        for choice in value["choices"]:
            if not isinstance(choice, dict):
                continue
            index = _as_int(choice.get("index"), 0)
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            if isinstance(delta.get("content"), str):
                def build_content(text: str, i: int = index) -> str:
                    return _sse({"object": "chat.completion.chunk", "choices": [
                        {"index": i, "delta": {"content": text}, "finish_reason": None}]})
                delta["content"] = self._push(("oc", index), build_content, delta["content"])
            tool_calls = delta.get("tool_calls")
            if isinstance(tool_calls, list):
                for offset, tc in enumerate(tool_calls):
                    fn = tc.get("function") if isinstance(tc, dict) else None
                    if not (isinstance(fn, dict) and isinstance(fn.get("arguments"), str)):
                        continue
                    # Each tool-call's arguments get a DISTINCT carry stream so a
                    # token split across chunks can't bleed into content or
                    # another tool-call slot.
                    tci = _as_int(tc.get("index"), offset)

                    def build_args(text: str, i: int = index, ti: int = tci) -> str:
                        return _sse({"object": "chat.completion.chunk", "choices": [
                            {"index": i, "delta": {"tool_calls": [
                                {"index": ti, "function": {"arguments": text}}]},
                             "finish_reason": None}]})
                    fn["arguments"] = self._push(("ot", index, offset), build_args, fn["arguments"])

    def _rewrite_responses(self, value: dict) -> None:
        t = value.get("type", "")
        if t in _RESPONSES_TEXT_DELTAS and isinstance(value.get("delta"), str):
            # Incremental text / tool-arg fragments — carry-buffer for
            # split-safety. builder=None → no synthetic flush: the terminal
            # `*.done` / `response.completed` events re-send the FULL text
            # (de-anonymized wholesale below), so the held-back tail is
            # delivered there rather than as a fabricated Responses event.
            key = ("r", t, value.get("item_id"), value.get("output_index"),
                   value.get("content_index"), value.get("summary_index"))
            value["delta"] = self._push(key, None, value["delta"])
        elif t.endswith(".done") or t == "response.completed":
            # Terminal re-sends carry the COMPLETE text (no split risk) — the
            # authoritative final render. De-anonymize every string in place;
            # robust to schema drift (no hardcoded field paths).
            self._deanon_in_place(value)

    def _deanon_in_place(self, obj) -> None:
        """Recursively de-anonymize every string value of a dict/list, in
        place. Used for terminal full-text events (complete strings)."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str):
                    obj[k] = self._anon.deanonymize(v)
                else:
                    self._deanon_in_place(v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                if isinstance(v, str):
                    obj[i] = self._anon.deanonymize(v)
                else:
                    self._deanon_in_place(v)

    # ── block / stream plumbing (shared by the live proxy and tests) ──

    def rewrite_block(self, block: str) -> str:
        """Rewrite the `data:` lines of one SSE event block. Splits on '\\n'
        only (never .splitlines(), which would break on U+2028 inside a
        payload and leak a token)."""
        out = []
        for line in block.split("\n"):
            if line.startswith("data:"):
                rest = line[len("data:"):]
                pre, payload = ("data: ", rest[1:]) if rest.startswith(" ") else ("data:", rest)
                out.append(pre + self.process_event_data(payload))
            else:
                out.append(line)
        return "\n".join(out)

    def is_terminator(self, block: str) -> bool:
        """True if this event block ends the stream (so we flush carry
        before forwarding it). Content-detected, not route-trusted."""
        for line in block.split("\n"):
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].lstrip()
            if payload == "[DONE]":
                return True
            try:
                v = json.loads(payload)
            except (ValueError, TypeError):
                continue
            if isinstance(v, dict) and v.get("type") in _TERMINATOR_TYPES:
                return True
        return False

    def flush_synthetic(self) -> str:
        """Emit any residual carry as provider-correct synthetic events
        (empty string if nothing is held). Idempotent — buffers are drained."""
        out = []
        for key, stream in self._streams.items():
            rest = stream.flush(self._anon)
            builder = self._synth.get(key)
            # builder is None for carries whose provider re-sends full text
            # at end (OpenAI Responses) — the residual is delivered there.
            if rest and builder is not None:
                out.append(builder(rest))
        return "".join(out)

    def process_stream(self, raw: str) -> str:
        """Whole-buffer rewrite used by tests; mirrors the live proxy's
        block loop exactly, including flushing residual carry BEFORE the
        terminator event."""
        out = []
        buf = raw
        while "\n\n" in buf:
            block, buf = buf.split("\n\n", 1)
            if self.is_terminator(block):
                out.append(self.flush_synthetic())
                # rewrite the terminator too: [DONE]/message_stop are no-ops,
                # but response.completed carries the full text to de-anonymize.
                out.append(self.rewrite_block(block) + "\n\n")
            else:
                out.append(self.rewrite_block(block) + "\n\n")
        if buf:
            out.append(self.rewrite_block(buf))
        out.append(self.flush_synthetic())
        return "".join(out)


def _split_keep_lf(raw: str) -> list[str]:
    """Split on '\\n' ONLY, keeping the terminator. Python str.splitlines()
    also breaks on Unicode line separators (U+2028/U+2029/U+0085/VT/FF),
    which would split an SSE `data:` payload mid-token and leak an
    un-deanonymized vault token."""
    if not raw:
        return []
    parts = raw.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def _as_int(value, default: int) -> int:
    # Only a genuine integer JSON value; a float / numeric-string / bool
    # yields the default (not coerced).
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default
