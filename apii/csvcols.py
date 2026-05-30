"""Column-aware CSV redaction.

For a structured table, the *header* tells you the kind of each column — far
more reliable (and faster) than running NER over the whole blob, which misses
transliterated names, mangles the grid, and even tokenizes the header row.
We classify each column by its header, then:
  • a PII-kind column → tokenize every cell as that kind (reliable, no NER);
  • any other column → a cheap regex pass only on cells that *look* like they
    hold an email or a long number (catches stray PII without scanning text);
  • the header row is never touched.

Run:  python -m apii.csvcols <in-folder-or-file> <out-folder> [--secret S] [--vault V]
"""
from __future__ import annotations

import csv
import io
import re
from typing import Optional

from apii.types import EntityKind

# ── header → kind classification ──────────────────────────────────────────

# Headers that contain "email" but hold a flag / date / source, NOT an address.
_EMAIL_META = ("status", "source", "verif", "catch", "bounce", "confidence",
               "open", "sent", "last ", "score", "sync", "count", "name")
# Tokens that mean a "*name" column is NOT a person.
_NOT_PERSON = ("company", "business", "account", "organization", "organisation",
               "ad ", "ad_", "adgroup", "campaign", "form", "page", "file",
               "product", "brand", "domain", "event", "stage", "template",
               "keyword", "display", "city", "country", "state", "industry",
               "tender", "supplier", "vendor", "for email", "group")
_PERSON_EXACT = {"first name", "last name", "full name", "middle name", "lead name",
                 "lead owner", "account executive", "account owner", "contact owner",
                 "previous owner", "converted contact", "owner", "contact",
                 "contact name", "contact person", "name", "arabicname", "englishname",
                 "الاسم", "اسم", "الاسم الكامل"}
_ORG_EXACT = {"company", "company name", "company name for emails", "business name",
              "business", "organization", "organisation", "employer", "account",
              "converted account", "referrer account", "referrer vendor", "vendor",
              "supplier", "suppliername", "partner", "account name",
              "اسم الشركة", "الشركة"}
_ADDR_TAIL = ("street", "city", "state", "country", "region", "address", "location")


def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower())


def column_kind(header: str) -> Optional[EntityKind]:
    """Map a column header to the EntityKind its cells hold, or None to skip."""
    h = _norm(header).lstrip("﻿")
    if h.endswith(".id") or h.endswith(".module"):
        return None  # internal reference id, not the value itself
    if "email" in h or "e-mail" in h or "بريد" in h:
        if not any(m in h for m in _EMAIL_META):
            return EntityKind.EMAIL
    if ("phone" in h or "mobile" in h or "whatsapp" in h or "هاتف" in h
            or "جوال" in h or h in ("tel", "fax", "cell")):
        return EntityKind.PHONE
    if any(h == w or h.endswith(" " + w) or h.endswith(w) for w in _ADDR_TAIL):
        return EntityKind.ADDRESS
    if h in _PERSON_EXACT or ("name" in h and not any(x in h for x in _NOT_PERSON)):
        return EntityKind.PERSON
    if h in _ORG_EXACT:
        return EntityKind.ORGANIZATION
    return None


_DIGIT = re.compile(r"\d")


def _looks_pii(cell: str) -> bool:
    """Cheap pre-filter: only bother regex-scanning an unhinted cell if it
    could hold an email or a long number (skips the millions of short cells)."""
    return "@" in cell or sum(c.isdigit() for c in cell) >= 7


def redact_columns(data: bytes, anonymizer) -> bytes:
    """Redact a CSV by column. Header row untouched; PII columns tokenized."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows:
        return data
    kinds = [column_kind(h) for h in rows[0]]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(rows[0])  # header: never redacted
    for row in rows[1:]:
        new = []
        for i, cell in enumerate(row):
            if not cell.strip():
                new.append(cell)
                continue
            k = kinds[i] if i < len(kinds) else None
            if k is not None:
                new.append(anonymizer.token_for_value(k, cell))
            elif _looks_pii(cell):
                new.append(anonymizer.anonymize(cell).text)
            else:
                new.append(cell)
        w.writerow(new)
    return out.getvalue().encode("utf-8")


def _main() -> int:
    import glob
    import os
    import sys
    import time

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a.split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    if len(args) < 2:
        print("usage: python -m apii.csvcols <in-folder-or-file> <out-folder> [--secret=…] [--vault=…]")
        return 2
    src, outdir = args[0], args[1]
    os.makedirs(outdir, exist_ok=True)

    from apii import config, default_pipeline, vault
    from apii.anonymizer import Anonymizer
    secret = opts.get("--secret") or config.resolve_secret(None)
    vpath = opts.get("--vault") or os.path.join(outdir, "vault.apii")
    from pathlib import Path
    recs = vault.load_or_default(Path(vpath), secret) if os.path.exists(vpath) else []
    anon = Anonymizer.from_records(secret, "leads", recs,
                                   pipeline=default_pipeline(enable_ner=False))

    files = sorted(glob.glob(os.path.join(src, "*.csv"))) if os.path.isdir(src) else [src]
    for f in files:
        t = time.time()
        with open(f, "rb") as fh:
            data = fh.read()
        try:
            kinds = [column_kind(h) for h in next(csv.reader(io.StringIO(data.decode("utf-8-sig", "replace"))))]
        except StopIteration:
            kinds = []
        out = redact_columns(data, anon)
        name = "redacted-" + os.path.basename(f)
        with open(os.path.join(outdir, name), "wb") as fh:
            fh.write(out)
        import collections
        per = collections.Counter(k.value for k in kinds if k)
        print(f"  {os.path.basename(f):42} {time.time()-t:5.1f}s  PII cols: {dict(per)}")
    from pathlib import Path as _P
    vault.save_encrypted(_P(vpath), secret, anon.records())
    print(f"\nvault: {vpath}  ({len(anon.records())} mappings)  → restore with: apii restore <file> --vault {vpath} --secret <secret>")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
