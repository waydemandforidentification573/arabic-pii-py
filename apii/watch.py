"""Local side-viewer for the redact-on-read workflow.

Tails a Claude Code session transcript and re-renders the assistant's
messages with apii tokens restored to their real values — entirely locally,
reading the same vault the hook writes. Nothing here ever re-enters the
model's context: the model still only ever saw tokens; this is the *display*
boundary, where you (the operator) are allowed to see your own data.

  apii watch --vault org.vault          # follow the current session, live
  apii watch --vault org.vault --once   # render the session so far and exit
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterator, Optional

from apii import default_pipeline, vault
from apii.anonymizer import Anonymizer


def _projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def _encode_cwd(cwd: str) -> str:
    # Claude Code names a project's transcript dir after its cwd with every
    # non-alphanumeric char turned into '-'.
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def newest_transcript(cwd: Optional[str] = None) -> Optional[Path]:
    """Newest transcript *.jsonl for `cwd`'s Claude Code project.

    Strictly scoped to the folder: if `cwd` has no project (no Claude session
    has run there), returns None rather than falling back to another folder's
    chat — `apii watch` follows the session in the folder it's run from, never
    an unrelated global one. Pass `cwd=None` to search across all projects
    (used only when no folder context is available)."""
    root = _projects_root()
    if not root.exists():
        return None
    if cwd is not None:
        proj = root / _encode_cwd(cwd)
        if not proj.is_dir():
            return None
        candidates = list(proj.glob("*.jsonl"))
    else:
        candidates = list(root.glob("*/*.jsonl"))
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def iter_assistant_text(lines: Iterator[str], show_thinking: bool = False
                        ) -> Iterator[tuple[str, str]]:
    """Yield (timestamp, text) for each assistant message in `lines`."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("type") != "assistant":
            continue
        parts: list[str] = []
        for b in (o.get("message", {}) or {}).get("content", []) or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text"):
                parts.append(b["text"])
            elif show_thinking and b.get("type") == "thinking" and b.get("thinking"):
                parts.append("[thinking] " + b["thinking"])
        if parts:
            yield o.get("timestamp", ""), "\n".join(parts)


def _complete_lines(data: bytes) -> tuple[list[str], int]:
    """Split `data` into complete (newline-terminated) lines, holding back any
    trailing partial line. Returns (lines, bytes_consumed).

    The transcript is appended to live, so a poll can land mid-write. Only
    consuming through the last ``\\n`` (and re-reading the remainder next poll)
    keeps a straddling line from being split across two reads and lost.
    """
    nl = data.rfind(b"\n")
    if nl == -1:
        return [], 0
    complete = data[:nl + 1]
    return complete.decode("utf-8", "replace").splitlines(), len(complete)


def _restorer(secret: str, tenant: str, vault_path: Optional[str]) -> tuple[Anonymizer, int]:
    records = vault.load_or_default(Path(vault_path), secret) if vault_path else []
    anon = Anonymizer.from_records(secret, tenant, records,
                                   pipeline=default_pipeline(enable_ner=False))
    return anon, len(records)


def _emit(ts: str, restored: str, color: bool) -> None:
    head = f"\033[2m{ts}\033[0m" if color else ts
    sys.stdout.write(f"{head}\n{restored}\n\n")
    sys.stdout.flush()


def run(secret: str, tenant: str = "default", vault_path: Optional[str] = None,
        transcript: Optional[str] = None, cwd: Optional[str] = None,
        show_thinking: bool = False, once: bool = False, poll: float = 0.5) -> int:
    """Render (--once) or follow a transcript, restoring tokens for display."""
    color = sys.stdout.isatty()
    anon, n = _restorer(secret, tenant, vault_path)
    cwd = cwd or os.getcwd()

    if once:
        path = Path(transcript) if transcript else newest_transcript(cwd)
        if path is None or not path.exists():
            sys.stderr.write("apii watch: no transcript found\n")
            return 1
        with open(path, encoding="utf-8", errors="replace") as fh:
            for ts, text in iter_assistant_text(fh, show_thinking):
                _emit(ts, anon.deanonymize(text), color)
        return 0

    sys.stdout.write(f"apii watch — restoring tokens from the vault ({n} mapped). Ctrl-C to stop.\n\n")
    sys.stdout.flush()
    # Follow mode is tail-like: start at the CURRENT end of the transcript and
    # only render messages that arrive afterwards. (Use --once to dump the
    # whole session so far.) `offset` is a byte offset; the file is read binary.
    path = Path(transcript) if transcript else None
    offset = path.stat().st_size if (path and path.exists()) else 0
    while True:
        if path is None:
            path = newest_transcript(cwd)
            if path is None:
                time.sleep(poll)
                continue
            offset = path.stat().st_size  # start at end — new messages only
            sys.stderr.write(f"── following {path.name} ──\n")
        # Refresh the vault FIRST: the hook appends a token↔value mapping
        # before the model's reply (which uses it) is written, so load any new
        # mappings before deanonymizing or a fresh token renders un-restored.
        if vault_path:
            fresh = vault.load_or_default(Path(vault_path), secret)
            if len(fresh) != n:
                anon, n = Anonymizer.from_records(
                    secret, tenant, fresh, pipeline=default_pipeline(enable_ner=False)
                ), len(fresh)
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            path = None
            continue
        if size < offset:  # rotated/truncated
            offset = 0
        if size > offset:
            with open(path, "rb") as fh:
                fh.seek(offset)
                data = fh.read()
            lines, consumed = _complete_lines(data)  # holds back a partial tail
            offset += consumed
            for ts, text in iter_assistant_text(iter(lines), show_thinking):
                _emit(ts, anon.deanonymize(text), color)
        time.sleep(poll)
