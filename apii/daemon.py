"""Long-lived HTTP-hook daemon.

Claude Code fires a hook process per lifecycle event; a fork+exec plus
lazy-regex recompiles per cold start is a user-visible pause. This
daemon pays that once: it keeps ONE hot Anonymizer (regexes + vault warm)
and serves `POST /hook` with the same behavior as apii.hook.run_hook.
Claude's native `http` hook type POSTs straight here; the thin
hook-client bridge serves agents that only support `command` hooks.

Notes:
  - HTTP on 127.0.0.1 (TCP, not a unix socket — Claude's http hook needs
    TCP).
  - Vault persistence is a full encrypted snapshot when new records
    appear; a snapshot per PII-bearing event is adequate at hook rates.
  - The idle self-exit watchdog is wired only in the uvicorn entrypoint
    (serve), not the app factory, so TestClient use never exits.

Requires the [proxy] extra (fastapi). Import-guarded.

NOTE: no `from __future__ import annotations` — FastAPI must resolve the
locally-imported Request annotation at registration time (same reason as
apii/server.py).
"""

import threading
from pathlib import Path
from typing import Optional

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.hook import HookClient, run_hook
from apii.policy import AnonymizationPolicy


def build_hook_daemon(
    secret: str,
    tenant: str = "default",
    *,
    default_client: HookClient = HookClient.CLAUDE,
    vault_path: Optional[Path] = None,
    policy: Optional[AnonymizationPolicy] = None,
):
    """Build the FastAPI hook daemon around one hot Anonymizer."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("the hook daemon needs the [proxy] extra (fastapi)") from exc

    app = FastAPI(title="apii hook daemon")
    anonymizer = Anonymizer(secret, tenant, pipeline=default_pipeline(), policy=policy)
    lock = threading.Lock()  # run_hook is sync + mutates the shared vault

    def _persist_new(tokens_before: set[str]) -> None:
        if vault_path is None:
            return
        records = anonymizer.records()
        if any(r.token not in tokens_before for r in records):
            from apii import vault as vaultmod
            vaultmod.save_encrypted(Path(vault_path), secret, records)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "local_only": True})

    @app.post("/hook")
    async def hook(req: Request) -> JSONResponse:
        event = await req.json()
        client = HookClient.parse(req.query_params.get("client"), default_client)
        with lock:
            tokens_before = {r.token for r in anonymizer.records()}
            try:
                response = run_hook(event, client, anonymizer)
            except Exception as exc:  # noqa: BLE001
                return JSONResponse({"error": str(exc)})
            _persist_new(tokens_before)
        return JSONResponse(response if response is not None else {})

    return app


def serve(
    secret: str,
    tenant: str = "default",
    *,
    host: str = "127.0.0.1",
    port: int = 8718,
    default_client: HookClient = HookClient.CLAUDE,
    vault_path: Optional[Path] = None,
    idle_timeout: float = 1800.0,
) -> None:  # pragma: no cover - exercised by `apii daemon`, not unit tests
    """Run the daemon under uvicorn with an idle self-exit watchdog."""
    import time

    import uvicorn

    app = build_hook_daemon(secret, tenant, default_client=default_client, vault_path=vault_path)
    last = [time.monotonic()]

    @app.middleware("http")
    async def _touch(request, call_next):
        last[0] = time.monotonic()
        return await call_next(request)

    if idle_timeout > 0:
        def _watchdog() -> None:
            import os
            while True:
                time.sleep(30)
                if time.monotonic() - last[0] >= idle_timeout:
                    os._exit(0)
        threading.Thread(target=_watchdog, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
