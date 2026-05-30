#!/usr/bin/env python3
"""Independent batch verifier for the REAL GCC PII eval gold files.

Re-reads every gold/*.jsonl and its corpus/*.txt counterpart from disk (it does
NOT import the builder's in-memory SPECS), asserts each span's UTF-8 byte slice
round-trips to the recorded ``text``, and re-checks every IBAN with ISO-7064
MOD-97. Exit code 0 iff all spans pass.

Verifies BOTH real corpora that ship with the repo: the curated
``tests/eval/real`` set and the bulk ``tests/eval/real_bulk`` set (skipped if
either is absent). Run from anywhere:  python3 tests/eval/real/verify_gold.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)
from apii.checksums import iban_mod97  # noqa: E402

# (root_name, corpus_dir, gold_dir) — the curated set lives here, the bulk set
# in the sibling real_bulk/.
ROOTS = [
    ("real", os.path.join(HERE, "corpus"), os.path.join(HERE, "gold")),
    ("real_bulk",
     os.path.join(HERE, "..", "real_bulk", "corpus"),
     os.path.join(HERE, "..", "real_bulk", "gold")),
]

IN_SCOPE = {
    "EMAIL", "PHONE", "IBAN", "COMMERCIAL_REGISTRATION", "TAX_NUMBER",
    "NATIONAL_ID", "PERSON", "ORGANIZATION", "ADDRESS",
}


def verify_root(name: str, corpus: str, gold: str, errors: list) -> tuple[int, int, int]:
    """Returns (checked, ibans, gold_files) for one root; appends to errors."""
    if not os.path.isdir(gold):
        return 0, 0, 0
    checked = ibans = 0
    cache: dict[str, bytes] = {}
    gold_files = sorted(f for f in os.listdir(gold) if f.endswith(".jsonl"))
    for gf in gold_files:
        for n, line in enumerate(open(os.path.join(gold, gf), encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            fname = o["file"]
            if fname not in cache:
                cpath = os.path.join(corpus, fname)
                if not os.path.exists(cpath):
                    errors.append(f"[{name}] {gf}:{n} corpus missing: {fname}")
                    cache[fname] = b""
                else:
                    cache[fname] = open(cpath, "rb").read()
            data = cache[fname]
            s, e = o["start"], o["end"]
            try:
                sliced = data[s:e].decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"[{name}] {gf}:{n} byte slice not valid UTF-8 ({s}:{e})")
                continue
            if sliced != o["text"]:
                errors.append(
                    f"[{name}] {gf}:{n} round-trip FAIL: {o['text']!r} != {sliced!r}")
                continue
            if o["kind"] not in IN_SCOPE:
                errors.append(f"[{name}] {gf}:{n} out-of-scope kind: {o['kind']}")
            if o["kind"] == "IBAN":
                compact = o["text"].replace(" ", "")
                if iban_mod97(compact[4:] + compact[:4]) != 1:
                    errors.append(f"[{name}] {gf}:{n} IBAN MOD-97 FAIL: {o['text']}")
                else:
                    ibans += 1
            checked += 1
    return checked, ibans, len(gold_files)


def main() -> int:
    errors: list[str] = []
    for name, corpus, gold in ROOTS:
        checked, ibans, nfiles = verify_root(name, corpus, gold, errors)
        if nfiles:
            print(f"[{name}] checked {checked} spans across {nfiles} gold files; "
                  f"{ibans} IBANs passed MOD-97.")
        else:
            print(f"[{name}] not present — skipped.")
    if errors:
        print("FAILURES:")
        for er in errors:
            print("  " + er)
        return 1
    print("ALL SPANS PASS: byte-offset round-trip + IBAN MOD-97 + in-scope kinds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
