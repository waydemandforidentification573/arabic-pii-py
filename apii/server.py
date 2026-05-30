"""FastAPI gateway server.

JSON endpoints:
  GET  /health
  POST /v1/detect       {text}          -> detections
  POST /v1/anonymize    {text}          -> {text, records}
  POST /v1/deanonymize  {text, records} -> {text}

Provider proxies (anonymize request → forward upstream → de-anonymize
response, streaming-aware via apii.streaming):
  POST /v1/messages           -> api.anthropic.com (Anthropic Messages)
  POST /v1/chat/completions   -> api.openai.com   (OpenAI Chat)
  POST /v1/responses          -> api.openai.com   (OpenAI Responses)

The proxy anonymizes the user-authored text in the request body, forwards
with the client's own auth headers (the gateway never holds provider
keys), then de-anonymizes the response — non-streaming JSON in place, or
SSE via a per-stream carry buffer that reassembles tokens split across
events. One Anonymizer per request (a fresh vault), optionally scoped by
an `x-apii-session` header.

Requires the [proxy] extra (fastapi + httpx) and, for the vault-less
in-request flow, nothing else. Import-guarded so the base package and the
non-proxy tests don't need fastapi installed.

NOTE: this module intentionally does NOT use `from __future__ import
annotations` — FastAPI resolves endpoint parameter annotations at
registration time, and the `Request` class is imported locally inside
build_app; stringized annotations would not resolve against module
globals and FastAPI would misread the request param as a query field.
"""

import os
from typing import Any, Optional

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.policy import AnonymizationMode, AnonymizationPolicy
from apii.streaming import StreamDeanonymizer

# Upstream bases (overridable for tests / private mirrors).
_ANTHROPIC_BASE = os.environ.get("APII_ANTHROPIC_BASE", "https://api.anthropic.com")
_OPENAI_BASE = os.environ.get("APII_OPENAI_BASE", "https://api.openai.com")

# Hop-by-hop / host headers we must not forward upstream. content-encoding is
# stripped because we re-serialize the body as plain JSON — a stale
# `content-encoding: gzip` from the client would mislabel it and corrupt it.
_STRIP_HEADERS = {"host", "content-length", "accept-encoding", "content-encoding",
                  "connection", "x-apii-session"}


# ── request-body anonymization ──

def anonymize_request_body(body: Any, anon: Anonymizer) -> Any:
    """Anonymize the user-authored text fields of a chat/messages request.

    Handles both the Anthropic and OpenAI shapes: `system` (str or block
    list) and `messages[].content` / `input` where content is a string or
    a list of `{type:"text", text:...}` blocks. Unknown fields pass
    through. Returns a new body; the anonymizer's vault is populated as a
    side effect so the response can be restored.
    """
    if not isinstance(body, dict):
        return body
    out = dict(body)
    # Top-level user-authored text across shapes: Anthropic `system`,
    # OpenAI Responses `input` + `instructions`.
    for key in ("system", "input", "instructions"):
        if key in out:
            out[key] = _anon_content(out[key], anon)
    if isinstance(out.get("messages"), list):
        out["messages"] = [_anon_message(m, anon) for m in out["messages"]]
    return out


# Block keys whose STRING value is user-authored text (Chat/Anthropic
# `text`, Responses `output_text`/`input_text`/`refusal` blocks all carry it
# under `text`; `output` is a function_call_output result; `arguments` is a
# tool-call argument string).
_TEXT_KEYS = ("text", "output", "refusal", "arguments")


def _anon_message(msg: Any, anon: Anonymizer) -> Any:
    """Anonymize one chat/messages entry: its `content` (string or block
    list) and any assistant `tool_calls[].function.arguments` — conversation
    history can carry PII inside a prior tool call as easily as in text."""
    if not isinstance(msg, dict):
        return msg
    m = dict(msg)
    if "content" in m:
        m["content"] = _anon_content(m["content"], anon)
    if isinstance(m.get("tool_calls"), list):
        m["tool_calls"] = [_anon_tool_call(tc, anon) for tc in m["tool_calls"]]
    return m


def _anon_tool_call(tc: Any, anon: Anonymizer) -> Any:
    if not (isinstance(tc, dict) and isinstance(tc.get("function"), dict)):
        return tc
    out = dict(tc)
    fn = dict(out["function"])
    if isinstance(fn.get("arguments"), str):
        fn["arguments"] = anon.anonymize(fn["arguments"]).text
    out["function"] = fn
    return out


def _anon_content(content: Any, anon: Anonymizer) -> Any:
    """Anonymize user-authored text inside a content value of ANY provider
    shape — a bare string, a list of blocks, or a single block dict —
    descending ONLY the known content-bearing paths so structural fields
    (type, role, name, ids, model) are never mutated.

    Covers Chat/Anthropic text blocks, Responses input_text/output_text/
    refusal blocks, nested `content` (Anthropic tool_result, Responses
    message items), tool_use `input` argument dicts, and inline tool-call
    `arguments` / function_call_output `output`."""
    if isinstance(content, str):
        return anon.anonymize(content).text
    if isinstance(content, list):
        return [_anon_content(b, anon) for b in content]
    if not isinstance(content, dict):
        return content
    out = dict(content)
    for k in _TEXT_KEYS:
        if isinstance(out.get(k), str):
            out[k] = anon.anonymize(out[k]).text
    if "content" in out:  # nested message / tool_result content
        out["content"] = _anon_content(out["content"], anon)
    if isinstance(out.get("input"), (dict, list)):  # tool-call argument payload
        out["input"] = _anon_values(out["input"], anon)
    return out


def _anon_values(obj: Any, anon: Anonymizer) -> Any:
    """Anonymize every STRING VALUE of a free-form structure (tool-call
    argument payloads), preserving keys and non-strings. Used only where the
    entire payload is user data, so there are no structural strings to guard."""
    if isinstance(obj, str):
        return anon.anonymize(obj).text
    if isinstance(obj, list):
        return [_anon_values(x, anon) for x in obj]
    if isinstance(obj, dict):
        return {k: _anon_values(v, anon) for k, v in obj.items()}
    return obj


def deanonymize_response_json(body: Any, anon: Anonymizer) -> Any:
    """Restore tokens in a non-streaming provider JSON response. Walks
    every string value (the response echoes our tokens wherever the model
    referenced redacted content) and de-anonymizes it."""
    if isinstance(body, str):
        return anon.deanonymize(body)
    if isinstance(body, list):
        return [deanonymize_response_json(x, anon) for x in body]
    if isinstance(body, dict):
        return {k: deanonymize_response_json(v, anon) for k, v in body.items()}
    return body


def _policy_from_env() -> AnonymizationPolicy:
    mode = os.environ.get("APII_POLICY", "strict")
    try:
        return AnonymizationPolicy(AnonymizationMode.parse(mode))
    except ValueError:
        return AnonymizationPolicy.strict()


def build_app(secret: Optional[str] = None, tenant: str = "default"):
    """Construct the FastAPI app. Import-guarded so fastapi/httpx are only
    needed when the proxy is actually used."""
    try:
        import httpx
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse, Response, StreamingResponse
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("the proxy needs the [proxy] extra (fastapi + httpx)") from exc

    secret = secret or os.environ.get("APII_SECRET", "")
    app = FastAPI(title="apii gateway")

    def _anon(session: Optional[str]) -> Anonymizer:
        return Anonymizer(
            secret, tenant, session=session,
            pipeline=default_pipeline(), policy=_policy_from_env(),
        )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/v1/detect")
    async def detect(req: Request) -> JSONResponse:
        body = await req.json()
        dets = default_pipeline().detect(body.get("text", ""))
        return JSONResponse(
            [{"kind": d.kind.value, "start": d.start, "end": d.end,
              "text": d.text, "confidence": d.confidence, "source": d.source} for d in dets]
        )

    @app.post("/v1/anonymize")
    async def anonymize(req: Request) -> JSONResponse:
        body = await req.json()
        a = _anon(req.headers.get("x-apii-session"))
        rep = a.anonymize(body.get("text", ""))
        return JSONResponse({
            "text": rep.text,
            "records": [
                {"kind": r.kind.value, "token": r.token, "value": r.value, "normalized": r.normalized}
                for r in rep.records
            ],
        })

    @app.post("/v1/deanonymize")
    async def deanonymize(req: Request) -> JSONResponse:
        import msgspec

        from apii.anonymizer import EntityRecord
        body = await req.json()
        records = [msgspec.convert(r, EntityRecord) for r in body.get("records", [])]
        a = Anonymizer.from_records(secret, tenant, records, pipeline=default_pipeline(enable_ner=False))
        return JSONResponse({"text": a.deanonymize(body.get("text", ""))})

    async def _proxy(req: Request, base: str, path: str) -> Any:
        session = req.headers.get("x-apii-session")
        a = _anon(session)
        body = await req.json()
        anon_body = anonymize_request_body(body, a)
        stream = bool(body.get("stream"))
        fwd_headers = {k: v for k, v in req.headers.items() if k.lower() not in _STRIP_HEADERS}
        url = base.rstrip("/") + path

        if not stream:
            async with httpx.AsyncClient(timeout=600) as client:
                up = await client.post(url, json=anon_body, headers=fwd_headers)
            # Forward upstream errors / non-JSON bodies verbatim — calling
            # up.json() on those would crash the proxy.
            ctype = up.headers.get("content-type", "")
            if up.status_code >= 400 or "application/json" not in ctype:
                return Response(content=up.content, status_code=up.status_code,
                                media_type=ctype or None)
            restored = deanonymize_response_json(up.json(), a)
            return JSONResponse(restored, status_code=up.status_code)

        async def event_stream():
            sd = StreamDeanonymizer(a)
            async with httpx.AsyncClient(timeout=600) as client:
                async with client.stream("POST", url, json=anon_body, headers=fwd_headers) as up:
                    buf = ""
                    async for chunk in up.aiter_text():
                        buf += chunk
                        # Emit complete SSE event blocks (separated by blank line).
                        while "\n\n" in buf:
                            block, buf = buf.split("\n\n", 1)
                            if sd.is_terminator(block):
                                # Flush held-back carry BEFORE the terminator, so a
                                # client that stops reading there still gets it.
                                syn = sd.flush_synthetic()
                                if syn:
                                    yield syn
                                # Rewrite the terminator too: [DONE]/message_stop
                                # are no-ops, but response.completed carries the
                                # full response text to de-anonymize.
                                yield sd.rewrite_block(block) + "\n\n"
                            else:
                                yield sd.rewrite_block(block) + "\n\n"
                    if buf:
                        yield sd.rewrite_block(buf)
                    # End-of-stream flush (covers terminator-less streams).
                    syn = sd.flush_synthetic()
                    if syn:
                        yield syn

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/v1/messages")
    async def messages(req: Request):
        return await _proxy(req, _ANTHROPIC_BASE, "/v1/messages")

    @app.post("/v1/chat/completions")
    async def chat_completions(req: Request):
        return await _proxy(req, _OPENAI_BASE, "/v1/chat/completions")

    @app.post("/v1/responses")
    async def responses(req: Request):
        return await _proxy(req, _OPENAI_BASE, "/v1/responses")

    return app
