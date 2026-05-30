"""CLI round-trip: redact → vault → restore, plus detect."""

from __future__ import annotations

import json

import pytest

from apii.types import EntityKind

typer_testing = pytest.importorskip("typer.testing")
pytest.importorskip("cryptography")

from apii.cli import app  # noqa: E402

runner = typer_testing.CliRunner()


def test_redact_restore_round_trip(tmp_path):
    vault = tmp_path / "t.vault"
    src = tmp_path / "in.txt"
    src.write_text("Reach ahmed@example.ae, IBAN SA0380000000608010167519, phone 0501234567.")

    # redact (regex-only for a hermetic, fast test)
    r = runner.invoke(
        app,
        ["redact", str(src), "--secret", "k", "--vault", str(vault), "--no-ner"],
    )
    assert r.exit_code == 0, r.output
    redacted = r.stdout
    assert "ahmed@example.ae" not in redacted
    assert "SA0380000000608010167519" not in redacted
    assert "0501234567" not in redacted
    assert vault.exists()

    # restore from the vault → original text
    redacted_file = tmp_path / "red.txt"
    redacted_file.write_text(redacted)
    r2 = runner.invoke(
        app, ["restore", str(redacted_file), "--secret", "k", "--vault", str(vault)]
    )
    assert r2.exit_code == 0, r2.output
    assert r2.stdout == src.read_text()


def test_restore_with_wrong_secret_fails(tmp_path):
    vault = tmp_path / "t.vault"
    src = tmp_path / "in.txt"
    src.write_text("phone 0501234567")
    runner.invoke(app, ["redact", str(src), "--secret", "right", "--vault", str(vault), "--no-ner"])
    r = runner.invoke(app, ["restore", str(src), "--secret", "wrong", "--vault", str(vault)])
    assert r.exit_code != 0  # decryption fails on wrong secret


def test_detect_emits_json(tmp_path):
    src = tmp_path / "in.txt"
    src.write_text("email ahmed@example.ae")
    r = runner.invoke(app, ["detect", str(src), "--no-ner"])
    assert r.exit_code == 0, r.output
    rows = json.loads(r.stdout)
    assert any(row["kind"] == EntityKind.EMAIL.value for row in rows)


def test_missing_secret_falls_back_to_managed(tmp_path, monkeypatch):
    # No --secret and no APII_SECRET → use the managed ~/.apii/secret
    # (auto-created), so redaction works with zero setup. APII_HOME isolates
    # the test from the real ~/.apii.
    monkeypatch.delenv("APII_SECRET", raising=False)
    monkeypatch.setenv("APII_HOME", str(tmp_path / "home"))
    src = tmp_path / "in.txt"
    src.write_text("email a@b.ae")
    r = runner.invoke(app, ["redact", str(src), "--no-ner"])
    assert r.exit_code == 0
    assert "EMAIL_" in r.stdout
    assert (tmp_path / "home" / "secret").exists()  # managed secret auto-created


def test_secret_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APII_SECRET", "envkey")
    vault = tmp_path / "t.vault"
    src = tmp_path / "in.txt"
    src.write_text("phone 0501234567")
    r = runner.invoke(app, ["redact", str(src), "--vault", str(vault), "--no-ner"])
    assert r.exit_code == 0, r.output
    assert "0501234567" not in r.stdout
