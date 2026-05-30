#!/usr/bin/env python3
"""demo/server.py — local backend for the apii playground.

Serves the static frontend in this folder AND exposes one endpoint,
POST /api/analyze, that runs the REAL apii engine (regex + checksums +
on-device ONNX NER) on whatever text you send. Because the real engine
runs, names/orgs you type are detected live — unlike a browser-only page.

Everything is local: it binds 127.0.0.1 and makes no outbound calls
(except the one-time NER model download from Hugging Face on first use).

Run it with the venv where apii is installed:

    .venv/bin/python demo/server.py            # http://127.0.0.1:8000
    .venv/bin/python demo/server.py --port 9000 --no-open

The first /api/analyze with NER on downloads ~210 MB of models (cached
under ~/.cache/huggingface). Toggle NER off in the UI for instant
structured-only detection.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from apii import config, default_pipeline
from apii.anonymizer import Anonymizer, EntityRecord
from apii.normalize import normalize_for_kind, scrub_invisible
from apii.types import EntityKind

DEMO_DIR = Path(__file__).resolve().parent
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/examples.json": ("examples.json", "application/json; charset=utf-8"),
}

# Process-cached pipelines (the ONNX NER engine is loaded once, lazily).
_PIPELINES: dict[bool, object] = {}
_PIPE_LOCK = threading.Lock()


def _pipeline(enable_ner: bool):
    with _PIPE_LOCK:
        if enable_ner not in _PIPELINES:
            _PIPELINES[enable_ner] = default_pipeline(enable_ner=enable_ner)
        return _PIPELINES[enable_ner]


def analyze(text: str, secret: str, enable_ner: bool) -> dict:
    """Detect → tokenize on a FRESH anonymizer (vault scoped to this input),
    and return the rich shape the frontend renders from."""
    ner_used = enable_ner
    ner_error = None
    try:
        a = Anonymizer(secret, "demo", pipeline=_pipeline(enable_ner))
        report = a.anonymize(text)
    except Exception as exc:  # NER unavailable/offline → degrade to structured-only
        ner_used = False
        ner_error = str(exc)
        a = Anonymizer(secret, "demo", pipeline=_pipeline(False))
        report = a.anonymize(text)

    clean = scrub_invisible(text)
    dets = sorted(report.detections, key=lambda d: (d.start, -(d.end - d.start)))

    segments, vault, seen = [], [], {}
    pos = 0
    for d in dets:
        if d.start < pos:  # skip any overlap defensively
            continue
        if d.start > pos:
            segments.append({"type": "text", "text": clean[pos:d.start]})
        value = clean[d.start:d.end]
        token = a.token_for_value(d.kind, value)
        segments.append({
            "type": "entity",
            "kind": d.kind.value,
            "text": value,
            "token": token,
            "confidence": round(d.confidence, 3),
            "source": d.source,
        })
        if token not in seen:
            seen[token] = True
            vault.append({"token": token, "kind": d.kind.value, "value": value})
        pos = d.end
    if pos < len(clean):
        segments.append({"type": "text", "text": clean[pos:]})

    return {
        "ok": True,
        "segments": segments,
        "tokenized": report.text,
        "vault": vault,
        "count": len([s for s in segments if s["type"] == "entity"]),
        "ner_used": ner_used,
        "ner_error": ner_error,
    }


def deanonymize(text: str, vault: list, secret: str) -> dict:
    """Restore tokens → real values with the REAL engine — rebuilt from the
    vault the client holds. This is the actual apii deanonymize path (exact
    token lookup + fuzzy fallback for tokens an LLM mangled), so the demo's
    restore behaves exactly like the package, not a JS approximation."""
    records = []
    for v in vault or []:
        try:
            kind = EntityKind(v["kind"])
        except (KeyError, ValueError):
            continue
        value = v.get("value", "")
        records.append(EntityRecord(
            kind=kind, token=v["token"], value=value,
            normalized=normalize_for_kind(kind, value),
        ))
    # Restore only does token lookup (+ fuzzy) — it never detects, so attach
    # the no-NER pipeline to avoid loading the ONNX models for a restore.
    a = Anonymizer.from_records(secret, "demo", records, pipeline=_pipeline(False))
    report = a.deanonymize_with_report(text)
    return {
        "ok": True,
        "text": report.text,
        "restored": report.restored,
        "unrestored": report.unrestored_tokens,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/meta":
            body = json.dumps({"hosted": bool(os.environ.get("APII_DEMO_HOSTED"))}).encode()
            self._send(200, body, "application/json")
            return
        entry = STATIC.get(path)
        if not entry:
            self._send(404, b"not found", "text/plain")
            return
        fname, ctype = entry
        try:
            self._send(200, (DEMO_DIR / fname).read_bytes(), ctype)
        except FileNotFoundError:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("/api/analyze", "/api/deanonymize"):
            self._send(404, b"not found", "text/plain")
            return
        try:
            n = int(self.headers.get("content-length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            secret = self.server.secret  # type: ignore[attr-defined]
            if path == "/api/analyze":
                out = analyze(req.get("text", ""), secret, bool(req.get("ner", True)))
            else:
                out = deanonymize(req.get("text", ""), req.get("vault", []), secret)
            self._send(200, json.dumps(out, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        except Exception as exc:  # noqa: BLE001
            self._send(200, json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json")


def main():
    ap = argparse.ArgumentParser(description="apii playground (real engine)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to expose (containers)")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = ap.parse_args()

    secret = config.resolve_secret(None)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.secret = secret  # type: ignore[attr-defined]
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{shown}:{args.port}"
    print(f"apii playground → {url}  (real engine; Ctrl-C to stop)")

    # Hosted: warm the NER models in the background so the first visitor's
    # request is fast (models are baked into the image at build time).
    if os.environ.get("APII_DEMO_HOSTED"):
        def _warm():
            try:
                analyze("Mohammed Ali works in Riyadh", secret, True)
                print("NER models warm.")
            except Exception as exc:  # noqa: BLE001
                print("warmup skipped:", exc)
        threading.Thread(target=_warm, daemon=True).start()
    elif not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
