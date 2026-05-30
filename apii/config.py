"""Managed local config under ~/.apii/ — so the hook and the viewer share a
secret and vault with zero setup.

The vault secret is the HMAC/encryption key; it must persist for tokens to
stay reversible across sessions. Resolution order everywhere:
    --secret flag  >  $APII_SECRET  >  ~/.apii/secret  (auto-created, 0600).
Override the directory with $APII_HOME.
"""
from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path


def config_dir() -> Path:
    d = Path(os.environ.get("APII_HOME") or (Path.home() / ".apii"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def secret_file() -> Path:
    return config_dir() / "secret"


def default_vault() -> Path:
    return config_dir() / "default.vault"


def load_or_create_secret() -> str:
    """The persisted secret, generating a 32-byte one (0600) on first use."""
    p = secret_file()
    if p.exists():
        existing = p.read_text().strip()
        if existing:
            return existing
    s = secrets.token_hex(32)
    p.write_text(s)
    p.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 — owner-only
    return s


def resolve_secret(explicit: str | None) -> str:
    """--secret > $APII_SECRET > managed ~/.apii/secret (auto-created)."""
    return explicit or os.environ.get("APII_SECRET") or load_or_create_secret()
