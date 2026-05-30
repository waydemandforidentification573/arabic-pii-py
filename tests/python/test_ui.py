"""Local paste-in / paste-out UI engine: text + file redact↔restore round-trips."""

from __future__ import annotations

from apii import config
from apii.ui import Engine


def _engine(tmp_path, monkeypatch):
    monkeypatch.setenv("APII_HOME", str(tmp_path))
    return Engine(config.load_or_create_secret(), "t", config.default_vault())


def test_text_round_trip(tmp_path, monkeypatch):
    e = _engine(tmp_path, monkeypatch)
    src = "email omar@aajil.sa, IBAN SA0380000000608010167519"
    red = e.redact(src)
    assert "omar@aajil.sa" not in red and "EMAIL_" in red and "IBAN_" in red
    assert e.restore(red) == src  # tokens map back exactly


def test_csv_round_trip(tmp_path, monkeypatch):
    e = _engine(tmp_path, monkeypatch)
    csv = b"name,email\nClient,a@b.ae\n"
    red = e.redact_file("contacts.csv", csv)
    assert b"a@b.ae" not in red and b"EMAIL_" in red   # cell tokenized, shape kept
    assert "a@b.ae" in e.restore_file("contacts.csv", red).decode()


def test_restore_passes_unknown_tokens_through(tmp_path, monkeypatch):
    e = _engine(tmp_path, monkeypatch)
    # a token with no vault mapping is left as-is (never crashes / invents).
    assert e.restore("see EMAIL_DEADBEEF00") == "see EMAIL_DEADBEEF00"
