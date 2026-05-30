"""Batch directory processing.

scan_dir walks a directory, detects PII per file, and writes per-file
JSONL summaries. anonymize_dir walks, redacts each file into an output
dir (format-aware via the document layer), writes a manifest, and merges
all token records into one encrypted vault.

File paths are never logged in the clear — each file is keyed by a
`path_hash` (SHA-256 of the path).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Optional

import msgspec

from apii.anonymizer import Anonymizer, EntityRecord
from apii.documents import DocumentKind, redact_document
from apii.pipeline import Pipeline
from apii.policy import AnonymizationPolicy
from apii.types import EntityKind


class KindCount(msgspec.Struct):
    kind: str
    count: int


class FileSummary(msgspec.Struct):
    path_hash: str
    size_bytes: int
    counts: list[KindCount]
    total: int


class AggregateSummary(msgspec.Struct):
    files: int
    files_with_detections: int
    total_detections: int
    by_kind: list[KindCount]
    top_files: list[FileSummary]


def _hash_path(path: Path) -> str:
    # Full 64-char SHA-256 hex — paths are never logged in the clear; the
    # hash also names the output file.
    return hashlib.sha256(str(path).encode()).hexdigest()


# EntityKind declaration order (by wire string), so by_kind/counts sort
# follows that order, not alphabetical.
_KIND_ORDINAL = {k.value: i for i, k in enumerate(EntityKind)}


def collect_files(directory: Path, extension: str) -> list[Path]:
    """Recursively collect files whose extension matches (case-insensitive,
    leading dot optional), sorted for determinism."""
    ext = extension.lower().lstrip(".")
    out = [
        p for p in Path(directory).rglob("*")
        if p.is_file() and p.suffix.lower().lstrip(".") == ext
    ]
    return sorted(out)


def _kind_counts(detections) -> list[KindCount]:
    c = Counter(d.kind.value for d in detections)
    return [KindCount(kind=k, count=n) for k, n in sorted(c.items(), key=lambda kv: _KIND_ORDINAL.get(kv[0], 99))]


def _aggregate(summaries: list[FileSummary], top_n: int = 10) -> AggregateSummary:
    by_kind: Counter[str] = Counter()
    for s in summaries:
        for kc in s.counts:
            by_kind[kc.kind] += kc.count
    # tie-break equal-total files by path_hash ascending.
    top = sorted(summaries, key=lambda s: (-s.total, s.path_hash))[:top_n]
    return AggregateSummary(
        files=len(summaries),
        files_with_detections=sum(1 for s in summaries if s.total > 0),
        total_detections=sum(s.total for s in summaries),
        by_kind=[KindCount(kind=k, count=n)
                 for k, n in sorted(by_kind.items(), key=lambda kv: _KIND_ORDINAL.get(kv[0], 99))],
        top_files=top,
    )


def _write_jsonl(path: Path, rows: list) -> None:
    Path(path).write_bytes(b"\n".join(msgspec.json.encode(r) for r in rows) + b"\n")


def scan_dir(
    directory: Path, extension: str, output: Path, *, pipeline: Optional[Pipeline] = None
) -> AggregateSummary:
    """Detect PII across a directory; write per-file JSONL summaries."""
    if pipeline is None:
        from apii import default_pipeline
        pipeline = default_pipeline()
    summaries: list[FileSummary] = []
    for path in collect_files(directory, extension):
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        dets = pipeline.detect(text)
        summaries.append(FileSummary(
            path_hash=_hash_path(path), size_bytes=path.stat().st_size,
            counts=_kind_counts(dets), total=len(dets),
        ))
    _write_jsonl(output, summaries)
    return _aggregate(summaries)


class _ManifestEntry(msgspec.Struct):
    path_hash: str
    size_bytes: int
    output: str
    total: int


def _redact_one(data: bytes, anon):
    """Redact one file's bytes → (kind, out_bytes, detections).

    For JSON, route through the KEY-HINT structured path (apii.structured)
    so a bare identifier under a sensitive key (cr_number/iban/customer_name)
    is caught — the text-only document adapter would miss it. Other formats
    use the document layer.
    """
    import json as _json


    kind = DocumentKind.from_bytes(data)
    if kind is DocumentKind.JSON:
        from apii.structured import anonymize_structured
        obj = _json.loads(data.decode("utf-8"))
        before = {r.token for r in anon.records()}
        out_obj = anonymize_structured(obj, anon)
        new_records = [r for r in anon.records() if r.token not in before]
        out_bytes = _json.dumps(out_obj, ensure_ascii=False, indent=2).encode("utf-8")

        # Synthesize per-kind detection counts from the new vault records
        # (structured anonymization tokenizes leaves, it doesn't return
        # Detection spans) so the summary still reports what was redacted.
        class _D:  # minimal shim with a .kind for _kind_counts
            __slots__ = ("kind",)

            def __init__(self, k):
                self.kind = k

        dets = [_D(r.kind) for r in new_records]
        return kind, out_bytes, dets

    kind, out_bytes, report = redact_document(data, anon, kind=kind)
    return kind, out_bytes, report.detections


def anonymize_dir(
    directory: Path,
    extension: str,
    out_dir: Path,
    *,
    secret: str,
    tenant: str = "default",
    manifest: Optional[Path] = None,
    vault: Optional[Path] = None,
    policy: Optional[AnonymizationPolicy] = None,
    pipeline: Optional[Pipeline] = None,
) -> AggregateSummary:
    """Redact every matching file into out_dir (format-aware), write a
    manifest, and merge all records into one encrypted vault."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if pipeline is None:
        from apii import default_pipeline
        pipeline = default_pipeline()

    summaries: list[FileSummary] = []
    entries: list[_ManifestEntry] = []
    merged: dict[str, EntityRecord] = {}

    for path in collect_files(directory, extension):
        data = path.read_bytes()
        ph = _hash_path(path)
        anon = Anonymizer(secret, tenant, pipeline=pipeline, policy=policy)
        try:
            kind, out_bytes, detections = _redact_one(data, anon)
        except Exception:
            continue
        out_ext = kind.output_extension()
        out_name = f"{ph}.{out_ext}"
        (out_dir / out_name).write_bytes(out_bytes)
        for r in anon.records():
            merged.setdefault(r.token, r)
        summaries.append(FileSummary(
            path_hash=ph, size_bytes=len(data),
            counts=_kind_counts(detections), total=len(detections),
        ))
        entries.append(_ManifestEntry(
            path_hash=ph, size_bytes=len(data), output=out_name, total=len(detections),
        ))

    entries.sort(key=lambda e: e.path_hash)
    if manifest is not None:
        _write_jsonl(manifest, entries)
    if vault is not None:
        from apii import vault as vaultmod
        vaultmod.save_encrypted(Path(vault), secret, sorted(merged.values(), key=lambda r: r.token))
    return _aggregate(summaries)
