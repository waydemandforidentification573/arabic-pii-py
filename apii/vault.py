"""Encrypted token vault.

The vault holds the token→value records (the actual PII), so it is
encrypted at rest:

  key        = SHA-256(secret)                     (32 bytes)
  cipher     = ChaCha20-Poly1305 (IETF, 12-byte nonce)
  envelope   = {"version":1,"cipher":"CHACHA20POLY1305-SHA256-KEY",
                "nonce":<base64>,"ciphertext":<base64>}
  plaintext  = {"version":1,"records":[{kind,token,value,normalized}, …]}

Requires the `cryptography` package (the [cli] extra). Absent → the
loader/saver raise a clear error rather than silently losing data.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import msgspec

from apii.anonymizer import EntityRecord

try:
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CRYPTO_AVAILABLE = False

_VERSION = 1
_CIPHER_TAG = "CHACHA20POLY1305-SHA256-KEY"


def _key(secret: bytes | str) -> bytes:
    raw = secret.encode() if isinstance(secret, str) else bytes(secret)
    return hashlib.sha256(raw).digest()


def _require_crypto() -> None:
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError(
            "vault encryption needs the `cryptography` package (pip install apii[cli])"
        )


def save_encrypted(path: Path, secret: bytes | str, records: list[EntityRecord]) -> None:
    """Encrypt `records` to `path` (creating parent dirs)."""
    _require_crypto()
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    plaintext = msgspec.json.encode({"version": _VERSION, "records": records})
    nonce = os.urandom(12)
    ciphertext = ChaCha20Poly1305(_key(secret)).encrypt(nonce, plaintext, None)
    envelope = {
        "version": _VERSION,
        "cipher": _CIPHER_TAG,
        "nonce": base64.standard_b64encode(nonce).decode(),
        "ciphertext": base64.standard_b64encode(ciphertext).decode(),
    }
    path.write_text(json.dumps(envelope, indent=2))


def load_or_default(path: Path | None, secret: bytes | str) -> list[EntityRecord]:
    """Load records from an encrypted vault, or [] if path is None/missing."""
    if path is None:
        return []
    path = Path(path)
    if not path.exists():
        return []
    return load_encrypted(path, secret)


def load_encrypted(path: Path, secret: bytes | str) -> list[EntityRecord]:
    _require_crypto()
    envelope = json.loads(Path(path).read_text())
    nonce = base64.standard_b64decode(envelope["nonce"])
    ciphertext = base64.standard_b64decode(envelope["ciphertext"])
    plaintext = ChaCha20Poly1305(_key(secret)).decrypt(nonce, ciphertext, None)
    data = msgspec.json.decode(plaintext)
    out: list[EntityRecord] = []
    for r in data.get("records", []):
        try:
            out.append(msgspec.convert(r, EntityRecord))
        except (msgspec.ValidationError, TypeError):
            # Tolerate records of a kind apii doesn't model (an externally
            # written vault may carry kinds this build doesn't emit). Skip
            # them rather than failing the whole load.
            continue
    return out
