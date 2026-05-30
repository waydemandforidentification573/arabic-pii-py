"""apii command-line interface — redact / restore / detect.

    apii redact   <file>  --secret … --tenant … --vault out.vault
    apii restore  <file>  --secret … --vault out.vault
    apii detect   <file>

`redact` anonymizes text (file or stdin) to stdout and persists the
token→value records to an encrypted vault. `restore` reverses it using
that vault. `detect` runs audit mode and prints the detections as JSON.

The secret comes from --secret or the APII_SECRET env var (never echoed).
Requires the [cli] extra (typer + cryptography).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import msgspec
import typer

from apii import default_pipeline, vault
from apii.anonymizer import Anonymizer
from apii.policy import AnonymizationMode, AnonymizationPolicy
from apii.types import EntityKind

app = typer.Typer(add_completion=False, help="Arabic/GCC PII gateway CLI.")


def _resolve_secret(secret: Optional[str]) -> str:
    # --secret > $APII_SECRET > managed ~/.apii/secret (auto-created 0600), so
    # the hook and the viewer share a key with nothing to type.
    from apii import config
    return config.resolve_secret(secret)


def _read_input(file: Optional[Path]) -> str:
    if file is not None:
        return Path(file).read_text()
    return sys.stdin.read()


def _build_policy(mode: str, redact_kinds: Optional[str]) -> AnonymizationPolicy:
    policy = AnonymizationPolicy(AnonymizationMode.parse(mode))
    if redact_kinds:
        kinds = [EntityKind(k.strip().upper()) for k in redact_kinds.split(",") if k.strip()]
        policy = policy.with_redact_kinds(kinds)
    return policy


@app.command()
def redact(
    file: Optional[Path] = typer.Argument(None, help="Input file (stdin if omitted)."),
    secret: Optional[str] = typer.Option(None, help="Vault secret (or APII_SECRET)."),
    tenant: str = typer.Option("default", help="Tenant id (scopes tokens)."),
    vault_path: Optional[Path] = typer.Option(None, "--vault", help="Encrypted vault file to append to."),
    session: Optional[str] = typer.Option(None, help="Conversation/session scope."),
    policy: str = typer.Option("strict", help="strict | balanced | audit."),
    redact_kinds: Optional[str] = typer.Option(None, "--redact-kinds", help="Comma-separated kinds to redact."),
    no_ner: bool = typer.Option(False, "--no-ner", help="Disable NER (regex only)."),
) -> None:
    """Anonymize text → stdout; persist records to the vault."""
    sec = _resolve_secret(secret)
    text = _read_input(file)
    existing = vault.load_or_default(vault_path, sec) if vault_path else []
    anon = Anonymizer.from_records(
        sec, tenant, existing,
        session=session,
        pipeline=default_pipeline(enable_ner=not no_ner),
        policy=_build_policy(policy, redact_kinds),
    )
    report = anon.anonymize(text)
    sys.stdout.write(report.text)
    if vault_path:
        vault.save_encrypted(Path(vault_path), sec, anon.records())
        typer.secho(
            f"[apii] {len(report.detections)} detected, {len(anon.records())} records in vault",
            fg="green", err=True,
        )


@app.command()
def restore(
    file: Optional[Path] = typer.Argument(None, help="Tokenized input (stdin if omitted)."),
    secret: Optional[str] = typer.Option(None, help="Vault secret (or APII_SECRET)."),
    tenant: str = typer.Option("default", help="Tenant id."),
    vault_path: Path = typer.Option(..., "--vault", help="Encrypted vault file."),
) -> None:
    """De-anonymize tokenized text → stdout using the vault."""
    sec = _resolve_secret(secret)
    text = _read_input(file)
    records = vault.load_or_default(Path(vault_path), sec)
    anon = Anonymizer.from_records(
        sec, tenant, records, pipeline=default_pipeline(enable_ner=False)
    )
    report = anon.deanonymize_with_report(text)
    sys.stdout.write(report.text)
    if report.unrestored_tokens:
        typer.secho(
            f"[apii] {len(report.unrestored_tokens)} unrestored token(s)",
            fg="yellow", err=True,
        )


@app.command()
def detect(
    file: Optional[Path] = typer.Argument(None, help="Input file (stdin if omitted)."),
    no_ner: bool = typer.Option(False, "--no-ner", help="Disable NER (regex only)."),
) -> None:
    """List detections as JSON (audit mode — nothing is redacted)."""
    text = _read_input(file)
    dets = default_pipeline(enable_ner=not no_ner).detect(text)
    out = [
        {"kind": d.kind.value, "start": d.start, "end": d.end, "text": d.text,
         "confidence": round(d.confidence, 4), "source": d.source}
        for d in dets
    ]
    sys.stdout.write(msgspec.json.encode(out).decode() + "\n")


@app.command(name="scan-dir")
def scan_dir_cmd(
    directory: Path = typer.Argument(..., help="Directory to scan recursively."),
    ext: str = typer.Option("txt", help="File extension to match."),
    out: Path = typer.Option(..., "--out", help="Per-file JSONL summary output."),
    no_ner: bool = typer.Option(False, "--no-ner", help="Disable NER (regex only)."),
) -> None:
    """Detect PII across a directory; write per-file summaries + print totals."""
    from apii.batch import scan_dir
    summary = scan_dir(directory, ext, out, pipeline=default_pipeline(enable_ner=not no_ner))
    typer.secho(
        f"[apii] {summary.files} files, {summary.files_with_detections} with PII, "
        f"{summary.total_detections} detections", fg="green", err=True,
    )
    sys.stdout.write(msgspec.json.encode(summary).decode() + "\n")


@app.command(name="redact-dir")
def redact_dir_cmd(
    directory: Path = typer.Argument(..., help="Directory to redact recursively."),
    out_dir: Path = typer.Option(..., "--out-dir", help="Output directory for redacted files."),
    ext: str = typer.Option("txt", help="File extension to match."),
    secret: Optional[str] = typer.Option(None, help="Vault secret (or APII_SECRET)."),
    tenant: str = typer.Option("default", help="Tenant id."),
    vault_path: Optional[Path] = typer.Option(None, "--vault", help="Encrypted vault to write."),
    manifest: Optional[Path] = typer.Option(None, "--manifest", help="JSONL manifest to write."),
    policy: str = typer.Option("strict", help="strict | balanced | audit."),
    no_ner: bool = typer.Option(False, "--no-ner", help="Disable NER (regex only)."),
) -> None:
    """Redact every matching file into out-dir; merge records into one vault."""
    from apii.batch import anonymize_dir
    sec = _resolve_secret(secret)
    summary = anonymize_dir(
        directory, ext, out_dir, secret=sec, tenant=tenant,
        manifest=manifest, vault=vault_path,
        policy=_build_policy(policy, None),
        pipeline=default_pipeline(enable_ner=not no_ner),
    )
    typer.secho(
        f"[apii] redacted {summary.files} files, {summary.total_detections} detections"
        + (f", vault {vault_path}" if vault_path else ""), fg="green", err=True,
    )


@app.command()
def hook(
    client: str = typer.Option("claude", help="Hook client response shape."),
    secret: Optional[str] = typer.Option(None, help="Vault secret (or APII_SECRET)."),
    tenant: str = typer.Option("default", help="Tenant id."),
    vault_path: Optional[Path] = typer.Option(None, "--vault", help="Encrypted vault (loaded + updated)."),
) -> None:
    """Per-event hook: read a hook-event JSON on stdin, print the
    hook-response JSON on stdout ({} when no action needed)."""
    from apii import config
    from apii.hook import HookClient, run_hook
    sec = _resolve_secret(secret)
    vp = Path(vault_path) if vault_path else config.default_vault()
    event = sys.stdin.read()
    records = vault.load_or_default(vp, sec)
    anon = Anonymizer.from_records(sec, tenant, records, pipeline=default_pipeline())
    before = {r.token for r in anon.records()}
    resp = run_hook(event, HookClient.parse(client, HookClient.CLAUDE), anon)
    if any(r.token not in before for r in anon.records()):
        vault.save_encrypted(vp, sec, anon.records())
    sys.stdout.write(msgspec.json.encode(resp if resp is not None else {}).decode() + "\n")


@app.command()
def watch(
    secret: Optional[str] = typer.Option(None, help="Vault secret (or APII_SECRET)."),
    tenant: str = typer.Option("default", help="Tenant id."),
    vault_path: Optional[Path] = typer.Option(None, "--vault", help="The vault the redact-on-read hook writes to."),
    transcript: Optional[Path] = typer.Option(None, help="Transcript .jsonl to follow (default: newest for this cwd)."),
    thinking: bool = typer.Option(False, help="Also show the assistant's thinking blocks."),
    once: bool = typer.Option(False, help="Render the session so far and exit (instead of following live)."),
) -> None:
    """Side-viewer: tail the Claude Code session transcript and re-render the
    assistant's messages with tokens restored to real values — locally. Real
    values are shown only on YOUR screen; they never re-enter the model's
    context. Pair with a redact-on-read hook writing the same --vault."""
    from apii import config
    from apii.watch import run
    vp = Path(vault_path) if vault_path else config.default_vault()
    raise typer.Exit(run(
        _resolve_secret(secret), tenant, str(vp),
        str(transcript) if transcript else None,
        show_thinking=thinking, once=once,
    ))


@app.command()
def ui(
    secret: Optional[str] = typer.Option(None, help="Vault secret (or APII_SECRET / managed)."),
    tenant: str = typer.Option("default", help="Tenant id."),
    vault_path: Optional[Path] = typer.Option(None, "--vault", help="Vault (default: managed ~/.apii)."),
    port: int = typer.Option(8765, help="Local port to serve on."),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open the browser."),
) -> None:
    """Launch the local paste-in / paste-out PII redactor in your browser.

    Redact text or a CSV/Excel file, take it to any LLM, then paste the reply
    back to restore the real values. Runs entirely on this machine (127.0.0.1),
    nothing is uploaded."""
    from apii import config
    from apii.ui import serve
    vp = Path(vault_path) if vault_path else config.default_vault()
    serve(_resolve_secret(secret), tenant, vp, port=port, open_browser=not no_open)


@app.command(name="install-claude-hook")
def install_claude_hook(
    global_: bool = typer.Option(
        False, "--global", help="Install to ~/.claude (every project) instead of just this one."),
    tenant: str = typer.Option("default", help="Tenant id (kept consistent across hook + watch)."),
) -> None:
    """Wire transparent PII protection into Claude Code in ONE command.

    Creates a local secret + vault (under ~/.apii) and writes two hooks:
      • redact-on-read  (PostToolUse/Read)        — Claude only ever sees tokens
      • restore-on-write (PreToolUse/Write,Edit…) — files come out with real values
    Then run `apii watch` in another pane to read Claude's answers decoded."""
    import json as _json

    from apii import config
    config.load_or_create_secret()  # ensure the shared secret exists
    vp = config.default_vault()

    target = (Path.home() / ".claude" / "settings.json") if global_ \
        else (Path(".claude") / "settings.local.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _json.loads(target.read_text()) if target.exists() else {}

    # cwd-independent: absolute interpreter + baked APII_HOME/vault, so the hook
    # finds the same secret regardless of where (or with what env) Claude runs it.
    cmd = (f"APII_HOME={config.config_dir()} {sys.executable} -m apii hook "
           f"--client claude --tenant {tenant} --vault {vp}")

    def _ensure(event: str, matcher: str) -> bool:
        groups = data.setdefault("hooks", {}).setdefault(event, [])
        if any(any("apii hook" in h.get("command", "") for h in g.get("hooks", []))
               for g in groups):
            return False
        groups.append({"matcher": matcher,
                       "hooks": [{"type": "command", "command": cmd, "timeout": 30}]})
        return True

    added = [
        _ensure("PostToolUse", "Read"),
        _ensure("PreToolUse", "Write|Edit|MultiEdit|NotebookEdit"),
    ]
    if any(added):
        target.write_text(_json.dumps(data, indent=2) + "\n")
        typer.echo(f"✓ redact-on-read + restore-on-write hooks installed → {target}")
    else:
        typer.echo(f"already installed in {target}")

    typer.echo(f"  secret: {config.secret_file()} (0600)")
    typer.echo(f"  vault:  {vp}")
    typer.echo("")
    typer.echo("Next:")
    typer.echo("  1) In Claude Code, run  /hooks  (or restart) to activate it.")
    typer.echo("  2) In another terminal pane, run:  apii watch")
    typer.echo("  Then ask Claude to read a file with PII — the chat shows tokens,")
    typer.echo("  the watch pane shows the real values. PII never reaches the model.")


@app.command()
def daemon(
    secret: Optional[str] = typer.Option(None, help="Vault secret (or APII_SECRET)."),
    tenant: str = typer.Option("default", help="Tenant id."),
    host: str = typer.Option("127.0.0.1", help="Bind host (local-only by default)."),
    port: int = typer.Option(8718, help="Bind port."),
    client: str = typer.Option("claude", help="Default hook client response shape."),
    vault_path: Optional[Path] = typer.Option(None, "--vault", help="Encrypted vault to persist to."),
    idle_timeout: float = typer.Option(1800.0, help="Self-exit after this many idle seconds (0=never)."),
) -> None:
    """Run the long-lived HTTP-hook daemon (hot anonymizer)."""
    from apii.daemon import serve
    from apii.hook import HookClient
    serve(
        _resolve_secret(secret), tenant, host=host, port=port,
        default_client=HookClient.parse(client, HookClient.CLAUDE),
        vault_path=vault_path, idle_timeout=idle_timeout,
    )


@app.command(name="hook-client")
def hook_client(
    url: str = typer.Option("http://127.0.0.1:8718/hook", help="Daemon /hook URL."),
    client: str = typer.Option("claude", help="Hook client."),
) -> None:
    """Thin bridge: read a hook-event JSON on stdin, POST it to the daemon,
    print the response — for agents that only support `command` hooks."""
    try:
        import httpx
    except ImportError:
        typer.secho("hook-client needs the [proxy] extra (httpx)", fg="red", err=True)
        raise typer.Exit(2) from None
    event = sys.stdin.read()
    try:
        r = httpx.post(url, params={"client": client}, content=event,
                       headers={"content-type": "application/json"}, timeout=30)
        sys.stdout.write(r.text)
    except httpx.HTTPError as e:
        # Fail-open is unsafe for a PII gate; fail-closed with an error.
        typer.secho(f"hook daemon unreachable: {e}", fg="red", err=True)
        raise typer.Exit(1) from e


@app.command()
def serve(
    secret: Optional[str] = typer.Option(None, help="Vault secret (or APII_SECRET)."),
    tenant: str = typer.Option("default", help="Tenant id."),
    host: str = typer.Option("127.0.0.1", help="Bind host (local-only by default)."),
    port: int = typer.Option(8720, help="Bind port."),
) -> None:
    """Run the local anonymizing LLM proxy (OpenAI- & Anthropic-compatible).

    Point your client's base URL at it (e.g. ANTHROPIC_BASE_URL): it anonymizes
    each outbound request, forwards only tokens upstream, and de-anonymizes the
    (streamed) response locally. Routes: /v1/messages, /v1/chat/completions,
    /v1/responses. Needs the [proxy] extra; upstream targets are overridable via
    APII_ANTHROPIC_BASE / APII_OPENAI_BASE."""
    try:
        import uvicorn
    except ImportError:
        typer.secho("serve needs the [proxy] extra (fastapi + uvicorn + httpx)",
                    fg="red", err=True)
        raise typer.Exit(2) from None
    from apii.server import build_app
    application = build_app(_resolve_secret(secret), tenant)
    typer.secho(f"apii proxy → http://{host}:{port}  (local only; Ctrl-C to stop)",
                fg="green", err=True)
    uvicorn.run(application, host=host, port=port, log_level="warning")


if __name__ == "__main__":  # python -m apii.cli
    app()
