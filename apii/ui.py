"""apii ui — a local, paste-in / paste-out PII redactor.

A localhost-only web page (no framework, stdlib http.server) with two boxes:
  • Redact:  paste text (or upload a CSV/Excel) → get tokenized output to take
    to any LLM (ChatGPT, Claude, …).
  • Restore: paste the LLM's reply (with tokens like PERSON_34985439) → get the
    real values back.

Everything runs on this machine. The server binds 127.0.0.1 and makes no
outbound calls. Token↔value mappings live in the managed vault under ~/.apii,
shared with the Claude Code hook + `apii watch`.
"""
from __future__ import annotations

import base64
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from apii import default_pipeline, vault
from apii.anonymizer import Anonymizer


class Engine:
    """Thread-safe redactor over the managed secret + vault. The vault is the
    single source of truth; each call builds a fresh anonymizer from it (NER
    engines are process-cached, so this is cheap) — which lets us turn the slow
    name/org NER OFF for big files and keep it ON for free text."""

    def __init__(self, secret: str, tenant: str, vault_path: Optional[Path]):
        self.secret, self.tenant, self.vault_path = secret, tenant, vault_path
        self.lock = threading.Lock()

    def _load(self):
        if not self.vault_path:
            return []
        try:
            return vault.load_or_default(self.vault_path, self.secret)
        except Exception:  # noqa: BLE001 - no crypto / unreadable → in-memory only
            return []

    def _anon(self, ner: bool) -> Anonymizer:
        # seeded with the whole current vault, so tokens stay consistent across
        # text/file/restore; anonymize() appends new mappings to the same set.
        return Anonymizer.from_records(self.secret, self.tenant, self._load(),
                                       pipeline=default_pipeline(enable_ner=ner))

    def _save(self, a: Anonymizer) -> None:
        if not self.vault_path:
            return
        try:
            vault.save_encrypted(self.vault_path, self.secret, a.records())
        except Exception:  # noqa: BLE001 - degrade to in-memory
            pass

    def redact(self, text: str) -> str:
        with self.lock:
            a = self._anon(ner=True)            # free text → catch names too
            out = a.anonymize(text).text
            self._save(a)
            return out

    def restore(self, text: str) -> str:
        with self.lock:
            return self._anon(ner=False).deanonymize(text)  # lookup only — no NER

    def redact_file(self, name: str, data: bytes, thorough: bool = False) -> bytes:
        from apii.documents import DocumentKind, redact_document
        with self.lock:
            kind = _kind_for(name, data)
            if kind is DocumentKind.CSV:
                # Tables → column-aware: the header tells the kind, so names/
                # orgs are caught reliably (no NER recall gaps), metadata and
                # the header row are left alone, and it's fast on big files.
                from apii.csvcols import redact_columns
                a = self._anon(ner=False)
                out = redact_columns(data, a)
            else:
                a = self._anon(ner=thorough)    # default fast: regex + checksums
                _, out, _ = redact_document(data, a, kind=kind)
            self._save(a)
            return out

    def restore_file(self, name: str, data: bytes) -> bytes:
        from apii.documents import emit_for_kind, extract_for_kind
        with self.lock:
            a = self._anon(ner=False)
            kind = _kind_for(name, data)
            extracted = extract_for_kind(kind, data)
            return emit_for_kind(kind, data, extracted, a.deanonymize(extracted.text))


def _kind_for(name: str, data: bytes):
    from apii.documents import DocumentKind
    if name and "." in name:
        k = DocumentKind.from_extension(name.rsplit(".", 1)[-1])
        if k is not None:
            return k
    return DocumentKind.from_bytes(data)


_PAGE = b"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>apii \xe2\x80\x94 local PII redactor</title>
<style>
:root{--bg:#0f1115;--card:#181b22;--line:#262b36;--fg:#e7eaf0;--mut:#9aa3b2;--accent:#4f8cff;--ok:#2fbf71}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:22px 24px;border-bottom:1px solid var(--line)}
header h1{margin:0;font-size:20px}header p{margin:4px 0 0;color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:24px;max-width:1100px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}
.card.files{grid-column:1/-1}
h2{margin:0 0 4px;font-size:15px}.sub{color:var(--mut);font-size:13px;margin:0 0 10px}
textarea{width:100%;min-height:150px;background:#0b0d12;color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:11px;font:13px/1.5 ui-monospace,Menlo,monospace;resize:vertical}
.row{display:flex;gap:8px;align-items:center;margin:10px 0}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:9px 15px;font-weight:600;cursor:pointer}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--fg);font-weight:500}
.hint{color:var(--mut);font-size:12px;margin:8px 0 0}
.files label{display:block;margin:8px 0;color:var(--mut);font-size:13px}
.files input{margin-top:4px}
.badge{display:inline-block;background:rgba(47,191,113,.15);color:var(--ok);border-radius:20px;padding:2px 10px;font-size:12px}
</style></head><body>
<header><h1>apii \xe2\x80\x94 local PII redactor</h1>
<p><span class=badge>100% on this machine</span> &nbsp; Paste text in, get tokens out; paste the LLM's reply back, get real values. Nothing is uploaded.</p></header>
<main>
 <section class=card>
  <h2>\xe2\x91\xa0 Redact</h2><p class=sub>Paste text with personal data:</p>
  <textarea id=in1 placeholder="Call \xd9\x85\xd8\xad\xd9\x85\xd8\xaf on 0501234567, email omar@aajil.sa\xe2\x80\xa6"></textarea>
  <div class=row><button onclick=redact()>Redact \xe2\x86\x92</button><button class=ghost onclick="cp('out1')">Copy</button></div>
  <textarea id=out1 readonly placeholder="tokenized output appears here"></textarea>
  <p class=hint>\xe2\x86\x92 Paste this into ChatGPT / Claude. The model never sees the real data.</p>
 </section>
 <section class=card>
  <h2>\xe2\x91\xa1 Restore</h2><p class=sub>Paste the LLM's reply (with tokens like PERSON_\xe2\x80\xa6):</p>
  <textarea id=in2 placeholder="Reach PERSON_34985439 at PHONE_\xe2\x80\xa6"></textarea>
  <div class=row><button onclick=restore()>Restore \xe2\x86\x92</button><button class=ghost onclick="cp('out2')">Copy</button></div>
  <textarea id=out2 readonly placeholder="real values appear here"></textarea>
 </section>
 <section class="card files">
  <h2>Files \xe2\x80\x94 CSV / Excel / JSON / docx \xe2\x80\xa6</h2>
  <label><input type=checkbox id=thorough> Also detect names &amp; organizations (AI \xe2\x80\x94 slower on big files; leave off for fast email/phone/IBAN/ID redaction)</label>
  <label>Redact a file (downloads a redacted copy): <input type=file id=f1></label>
  <label>Restore a file (downloads a copy with real values): <input type=file id=f2></label>
  <p class=hint>Detects: emails, GCC phones, IBANs (MOD-97), national IDs, VAT &amp; CR \xe2\x80\x94 plus names &amp; organizations when the box above is checked. A bare random number is <b>not</b> treated as PII (so dates, prices &amp; quantities aren't shredded).</p>
 </section>
</main>
<script>
async function post(p,b){const r=await fetch(p,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b)});return r.json()}
async function redact(){const o=await post('/api/redact',{text:in1.value});out1.value=o.error?('error: '+o.error):o.text}
async function restore(){const o=await post('/api/restore',{text:in2.value});out2.value=o.error?('error: '+o.error):o.text}
function cp(id){const t=document.getElementById(id);t.select();navigator.clipboard&&navigator.clipboard.writeText(t.value)}
function fileTo(input,path,prefix,extra){const f=input.files[0];if(!f)return;const rd=new FileReader();
 rd.onload=async()=>{const b64=rd.result.split(',')[1];const o=await post(path,Object.assign({name:f.name,b64:b64},extra||{}));
  if(o.error){alert(o.error);return}
  const bin=atob(o.b64),arr=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)arr[i]=bin.charCodeAt(i);
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([arr]));a.download=prefix+f.name;a.click()};
 rd.readAsDataURL(f)}
f1.onchange=()=>fileTo(f1,'/api/redact-file','redacted-',{thorough:thorough.checked});
f2.onchange=()=>fileTo(f2,'/api/restore-file','restored-');
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, _PAGE, "text/html; charset=utf-8")
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            eng: Engine = self.server.engine  # type: ignore[attr-defined]
            if self.path == "/api/redact":
                out = {"text": eng.redact(req.get("text", ""))}
            elif self.path == "/api/restore":
                out = {"text": eng.restore(req.get("text", ""))}
            elif self.path == "/api/redact-file":
                data = base64.b64decode(req.get("b64", ""))
                name = req.get("name", "file")
                res = eng.redact_file(name, data, thorough=bool(req.get("thorough")))
                out = {"name": name, "b64": base64.b64encode(res).decode()}
            elif self.path == "/api/restore-file":
                data = base64.b64decode(req.get("b64", ""))
                name = req.get("name", "file")
                out = {"name": name, "b64": base64.b64encode(eng.restore_file(name, data)).decode()}
            else:
                self._send(404, b'{"error":"not found"}')
                return
            self._send(200, json.dumps(out, ensure_ascii=False).encode())
        except Exception as exc:  # noqa: BLE001 - surface as a JSON error to the page
            self._send(200, json.dumps({"error": str(exc)}).encode())


def serve(secret: str, tenant: str = "default", vault_path: Optional[Path] = None,
          port: int = 8765, open_browser: bool = True) -> None:
    engine = Engine(secret, tenant, vault_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.engine = engine  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{port}"
    print(f"apii ui → {url}  (local only; Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        httpd.shutdown()
