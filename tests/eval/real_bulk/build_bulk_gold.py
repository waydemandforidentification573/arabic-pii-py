#!/usr/bin/env python3
"""Deterministic, offset-safe builder for the BULK real GCC PII eval corpus.

This is the large sibling of ``tests/eval/real/build_gold.py``. Where that
file hand-curates ~102 spans into multi-entity GCC documents, this builder
mechanically turns the harvested ``{kind, value, context, source}`` records
(verified real public values) into fixtures + gold, one fixture file per
harvest slice. It NEVER hand-authors an offset: each value's UTF-8 byte
offset is computed from the bytes of its own context block plus the running
byte length of the fixture file, so multi-byte Arabic can't drift.

Input  : a directory of ``*.jsonl`` slices, each line
         ``{"kind","value","context","source","lang","country"}``.
Output : ``<root>/corpus/<slice>.txt`` + ``<root>/gold/<slice>.jsonl``
         (gold lines ``{file,start,end,kind,text,confidence_floor:0.85}``).

A record is DROPPED (never invented) when its value is not a clean substring
of its context, or (for IBAN) fails ISO-7064 MOD-97. Dedup is by (kind,value)
globally — the first context that cleanly carries a value wins.

Run:  python3 tests/eval/real_bulk/build_bulk_gold.py [--src DIR] [--root DIR]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)
from apii.checksums import iban_mod97  # noqa: E402

FLOOR = 0.85

IN_SCOPE = {
    "EMAIL", "PHONE", "IBAN", "COMMERCIAL_REGISTRATION", "TAX_NUMBER",
    "NATIONAL_ID", "PERSON", "ORGANIZATION", "ADDRESS",
}

# Harvest slice file -> fixture base name. Slices not listed fall back to a
# sanitized version of their stem.
def _fixture_name(stem: str) -> str:
    return "bulk_" + stem.replace("-", "_").lower()


def _iban_ok(value: str) -> bool:
    compact = value.replace(" ", "").replace("-", "")
    if len(compact) < 5:
        return False
    try:
        return iban_mod97(compact[4:] + compact[:4]) == 1
    except Exception:
        return False


def build(src_dir: str, root: str) -> int:
    corpus_dir = os.path.join(root, "corpus")
    gold_dir = os.path.join(root, "gold")
    os.makedirs(corpus_dir, exist_ok=True)
    os.makedirs(gold_dir, exist_ok=True)

    slices = sorted(f for f in os.listdir(src_dir) if f.endswith(".jsonl"))
    seen: set[tuple[str, str]] = set()  # (kind, value) dedup, global
    per_kind: dict[str, int] = {}
    per_kind_domains: dict[str, set[str]] = {}  # kind -> source domains
    errors: list[str] = []
    total = 0
    dropped = 0

    for sf in slices:
        stem = os.path.splitext(sf)[0]
        fixture = _fixture_name(stem) + ".txt"
        recs = []
        for ln in open(os.path.join(src_dir, sf), encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                recs.append(json.loads(ln))
            except json.JSONDecodeError:
                continue

        text_parts: list[str] = []  # context blocks for this fixture
        gold_lines: list[str] = []
        byte_cursor = 0
        domains: set[str] = set()

        for r in recs:
            kind = r.get("kind")
            value = r.get("value")
            context = r.get("context")
            source = r.get("source", "")
            if kind not in IN_SCOPE or not value or not context:
                dropped += 1
                continue
            if (kind, value) in seen:
                continue
            vb = value.encode("utf-8")
            cb = context.encode("utf-8")
            local = cb.find(vb)
            if local < 0:
                dropped += 1
                continue  # value not a clean substring of its context — DROP
            if kind == "IBAN" and not _iban_ok(value):
                dropped += 1
                continue
            seen.add((kind, value))

            # The fixture line is the context block, newline-terminated. The
            # value's global byte offset is the running file byte length plus
            # the value's byte offset *within this block*.
            start = byte_cursor + local
            end = start + len(vb)
            block = context + "\n"
            text_parts.append(block)
            byte_cursor += len(block.encode("utf-8"))

            gold_lines.append(json.dumps({
                "file": fixture, "start": start, "end": end,
                "kind": kind, "text": value, "confidence_floor": FLOOR,
            }, ensure_ascii=False))
            per_kind[kind] = per_kind.get(kind, 0) + 1
            total += 1
            if source:
                dom = source.split("/")[2] if "//" in source else source
                domains.add(dom)
                per_kind_domains.setdefault(kind, set()).add(dom)

        if not gold_lines:
            continue
        # Write fixture, then VERIFY every span round-trips against the bytes
        # we actually wrote (defensive — catches any block-accounting bug).
        data = "".join(text_parts).encode("utf-8")
        with open(os.path.join(corpus_dir, fixture), "wb") as fh:
            fh.write(data)
        for gl in gold_lines:
            o = json.loads(gl)
            if data[o["start"]:o["end"]].decode("utf-8") != o["text"]:
                errors.append(f"{fixture}: round-trip FAIL {o['text']!r}")
        with open(os.path.join(gold_dir, _fixture_name(stem) + ".jsonl"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(gold_lines) + "\n")

    n_fixtures = len([f for f in os.listdir(gold_dir) if f.endswith(".jsonl")])
    print(f"Wrote {total} spans across {n_fixtures} "
          f"fixtures into {root}  (dropped {dropped} non-clean/out-of-scope).")
    print("Per-kind counts:")
    for k in sorted(per_kind):
        print(f"  {k}: {per_kind[k]}")
    if errors:
        print("\nERRORS:")
        for e in errors:
            print("  " + e)
        return 1
    print("\nAll spans round-trip OK (IBANs MOD-97-gated).")
    write_readme(root, per_kind, per_kind_domains, total, n_fixtures)
    return 0


# Recall on this broad set is measured by tests/python/test_real_bulk_corpus.py
# (the floors live there, beside the assertions). These notes explain WHY the
# label-cued kinds are harder here than on the curated tests/eval/real set.
_CEILING_NOTES = {
    "NATIONAL_ID":
        "Label-cued + bare-digit. Values are PUBLISHED VALIDATOR TEST-VECTORS "
        "(saudi-id-validator, django-localflavor test_kw/ae/qa, gov design-system "
        "format examples) — never a real individual's ID. Most appear in code/"
        "doc contexts with no detector witness, so regex recall is low by design.",
    "COMMERCIAL_REGISTRATION":
        "Witness/label-cued. Real CRs published in varied prose; un-cued mentions "
        "are not claimed (the curated set pins the label paths at 1.0).",
    "PHONE":
        "Bare 8-digit GCC locals are deliberately unmatched (no country code / "
        "leading 0), which dominates the miss set on diverse real pages.",
}


def write_readme(root, per_kind, per_kind_domains, total, n_fixtures):
    out = [
        "# tests/eval/real_bulk — BULK real Arabic/GCC PII evaluation corpus",
        "",
        "The large sibling of `tests/eval/real`. Where that set hand-curates",
        f"~102 spans into multi-entity GCC documents, this set holds **{total}**",
        "spans mechanically built from harvested real public values — one fixture",
        "file per harvest slice. It is **ground truth, not synthetic**: every",
        "value is a real, intentionally-published value or a documented",
        "validator test-vector / official specimen. Values were chosen only",
        "because they are real + public, never because a regex would match.",
        "",
        "It lives in its OWN root (separate `corpus/` + `gold/`) so the curated",
        "set's tight recall pins stay calibrated to that set. Recall on this",
        "broader, harder distribution is pinned **honestly** (and lower for the",
        "label-cued kinds) in `tests/python/test_real_bulk_corpus.py`.",
        "",
        "Gold format (UTF-8 **byte** offsets), one span per line in",
        "`gold/<slice>.jsonl` — identical schema to the curated set:",
        "",
        "```",
        '{"file":"bulk_<slice>.txt","start":N,"end":M,"kind":"KIND","text":"...","confidence_floor":0.85}',
        "```",
        "",
        "Offsets are computed FROM THE BYTES (never hand-authored); every span is",
        "round-trip-checked on write and IBANs are MOD-97-gated. Regenerate:",
        "",
        "```",
        "python3 tests/eval/real_bulk/build_bulk_gold.py   # reads /tmp/apii_gold_harvest",
        "python3 tests/eval/real/verify_gold.py            # verifies real + real_bulk",
        "```",
        "",
        f"Total labeled spans: {total} across {n_fixtures} fixtures. Per-kind:",
        "",
    ]
    for k in sorted(per_kind):
        out.append(f"- {k}: {per_kind[k]}")
    out.append("")
    out.append("## Provenance — source domains per kind")
    out.append("")
    out.append("(Full per-page URLs are in the harvest records; the published")
    out.append("sentence carrying each value is preserved verbatim in the fixture.)")
    out.append("")
    for k in sorted(per_kind_domains):
        doms = ", ".join(sorted(per_kind_domains[k]))
        out.append(f"- **{k}**: {doms}")
    out.append("")
    out.append("## Documented ceilings — why some kinds are sparse / low-recall")
    out.append("")
    for k in sorted(_CEILING_NOTES):
        if k in per_kind:
            out.append(f"- **{k}** ({per_kind[k]} spans): {_CEILING_NOTES[k]}")
    out.append("")
    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print(f"Wrote manifest: {os.path.join(root, 'README.md')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/apii_gold_harvest")
    ap.add_argument("--root", default=HERE)
    args = ap.parse_args()
    return build(args.src, args.root)


if __name__ == "__main__":
    sys.exit(main())
