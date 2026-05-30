"""Batch scan_dir / anonymize_dir over a directory."""

from __future__ import annotations

import json

from apii import default_pipeline
from apii.batch import anonymize_dir, collect_files, scan_dir


def _pipe():
    return default_pipeline(enable_ner=False)


def test_collect_files_recursive_by_extension(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("y")
    (tmp_path / "c.csv").write_text("z")
    files = collect_files(tmp_path, "txt")
    assert [p.name for p in files] == ["a.txt", "b.txt"]


def test_scan_dir_counts_and_aggregates(tmp_path):
    (tmp_path / "one.txt").write_text("email a@b.ae phone 0501234567")
    (tmp_path / "two.txt").write_text("nothing sensitive here")
    out = tmp_path / "summary.jsonl"
    agg = scan_dir(tmp_path, "txt", out, pipeline=_pipe())
    assert agg.files == 2
    assert agg.files_with_detections == 1
    assert agg.total_detections == 2
    kinds = {kc.kind for kc in agg.by_kind}
    assert {"EMAIL", "PHONE"} <= kinds
    # per-file JSONL written
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert len(rows) == 2
    assert all("path_hash" in r for r in rows)  # paths never logged in clear


def test_anonymize_dir_json_uses_key_hints(tmp_path):
    # A bare CR number under a sensitive key would be missed by text-only
    # detection; the batch JSON path must use the key-hint layer (#3).
    import json as _json
    src = tmp_path / "src"
    src.mkdir()
    (src / "rec.json").write_text(_json.dumps({
        "cr_number": "1010010813",       # bare id — only the KEY reveals it
        "balance": "5591674.08",         # amount — must NOT be touched
        "email": "a@b.ae",
    }))
    out_dir = tmp_path / "out"
    vault = tmp_path / "v.vault"
    agg = anonymize_dir(src, "json", out_dir, secret="k", tenant="t",
                        vault=vault, pipeline=_pipe())
    out = list(out_dir.glob("*.json"))[0].read_text()
    obj = _json.loads(out)
    assert obj["cr_number"].startswith("CR_")       # bare CR caught via key
    assert obj["email"].startswith("EMAIL_")
    assert obj["balance"] == "5591674.08"            # amount untouched
    assert agg.total_detections >= 2


def test_anonymize_dir_redacts_writes_manifest_and_vault(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f1.txt").write_text("phone 0501234567")
    (src / "f2.txt").write_text("email a@b.ae")
    out_dir = tmp_path / "out"
    vault = tmp_path / "v.vault"
    manifest = tmp_path / "m.jsonl"
    agg = anonymize_dir(
        src, "txt", out_dir, secret="k", tenant="t",
        manifest=manifest, vault=vault, pipeline=_pipe(),
    )
    assert agg.files == 2
    # outputs written, PII gone
    outs = sorted(out_dir.glob("*.txt"))
    assert len(outs) == 2
    joined = "".join(p.read_text() for p in outs)
    assert "0501234567" not in joined and "a@b.ae" not in joined
    assert vault.exists() and manifest.exists()
    # the merged vault restores both files
    from apii import vault as vaultmod
    from apii.anonymizer import Anonymizer
    records = vaultmod.load_or_default(vault, "k")
    restorer = Anonymizer.from_records("k", "t", records, pipeline=_pipe())
    restored = "".join(restorer.deanonymize(p.read_text()) for p in outs)
    assert "0501234567" in restored and "a@b.ae" in restored
