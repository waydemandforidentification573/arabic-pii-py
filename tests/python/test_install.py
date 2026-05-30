"""Managed config + one-command Claude Code hook install."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from apii import config
from apii.cli import app


def test_managed_secret_is_stable_and_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("APII_HOME", str(tmp_path))
    s1 = config.load_or_create_secret()
    s2 = config.load_or_create_secret()
    assert s1 == s2 and len(s1) >= 32                    # stable across calls
    assert (tmp_path / "secret").stat().st_mode & 0o777 == 0o600  # owner-only


def test_secret_resolution_order(tmp_path, monkeypatch):
    monkeypatch.setenv("APII_HOME", str(tmp_path))
    monkeypatch.delenv("APII_SECRET", raising=False)
    assert config.resolve_secret("flag") == "flag"        # flag wins
    monkeypatch.setenv("APII_SECRET", "envsec")
    assert config.resolve_secret(None) == "envsec"        # env next
    monkeypatch.delenv("APII_SECRET")
    assert config.resolve_secret(None) == config.load_or_create_secret()  # file last


def test_install_claude_hook_writes_valid_idempotent_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APII_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["install-claude-hook", "--tenant", "me"])
    assert r.exit_code == 0, r.output

    settings = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    groups = settings["hooks"]["PostToolUse"]
    assert groups[0]["matcher"] == "Read"
    cmd = groups[0]["hooks"][0]["command"]
    assert "apii hook" in cmd and "--client claude" in cmd
    assert "APII_HOME=" in cmd                            # config dir baked in (cwd-independent)

    # running it again must not duplicate the hook
    CliRunner().invoke(app, ["install-claude-hook", "--tenant", "me"])
    again = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert len(again["hooks"]["PostToolUse"]) == 1
