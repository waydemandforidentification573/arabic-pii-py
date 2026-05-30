"""Hook logic (run_hook) + the HTTP-hook daemon."""

from __future__ import annotations

import pytest

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.hook import HookClient, run_hook


def _anon():
    return Anonymizer("hook-secret", "t", pipeline=default_pipeline(enable_ner=False))


# ── run_hook core ──

def test_clean_prompt_passes_through():
    assert run_hook({"hook_event_name": "UserPromptSubmit", "prompt": "hello world"},
                    HookClient.CLAUDE, _anon()) is None


def test_prompt_with_pii_blocked_without_leaking_raw():
    out = run_hook({"hook_event_name": "UserPromptSubmit", "prompt": "call 0501234567 now"},
                   HookClient.CLAUDE, _anon())
    assert out["decision"] == "block"
    assert "PHONE:1" in out["reason"]
    assert "0501234567" not in out["reason"]  # no raw value leaked


def test_pre_tool_use_with_pii_denied():
    # A non-write tool whose input carries raw PII is denied so it can't
    # propagate via a side channel.
    out = run_hook({"hook_event_name": "PreToolUse", "tool_input": {"cmd": "mail ahmed@example.com"}},
                   HookClient.CLAUDE, _anon())
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_post_tool_use_anonymizes():
    out = run_hook({"hook_event_name": "PostToolUse", "tool_response": {"text": "reach ahmed@example.com"}},
                   HookClient.CLAUDE, _anon())
    updated = out["hookSpecificOutput"]["updatedToolOutput"]["text"]
    assert "ahmed@example.com" not in updated and "EMAIL_" in updated


def test_unknown_event_ignored():
    assert run_hook({"hook_event_name": "SomethingElse", "prompt": "call 0501234567"},
                    HookClient.CLAUDE, _anon()) is None


def test_camelcase_event_name_accepted():
    assert run_hook({"hookEventName": "UserPromptSubmit", "prompt": "call 0501234567"},
                    HookClient.CLAUDE, _anon()) is not None


def test_hook_client_parse():
    assert HookClient.parse("CLAUDE", HookClient.CLAUDE) is HookClient.CLAUDE
    assert HookClient.parse(None, HookClient.CLAUDE) is HookClient.CLAUDE
    assert HookClient.parse("nonsense", HookClient.CLAUDE) is HookClient.CLAUDE


# ── daemon (TestClient) ──

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from apii.daemon import build_hook_daemon  # noqa: E402


def _client():
    return TestClient(build_hook_daemon("hook-secret", "t"))


def test_daemon_health():
    r = _client().get("/health")
    assert r.json() == {"status": "ok", "local_only": True}


def test_daemon_hook_blocks_pii_prompt():
    r = _client().post("/hook", json={"hook_event_name": "UserPromptSubmit", "prompt": "call 0501234567"})
    body = r.json()
    assert body["decision"] == "block"
    assert "PHONE:1" in body["reason"]


def test_daemon_clean_prompt_empty_response():
    r = _client().post("/hook", json={"hook_event_name": "UserPromptSubmit", "prompt": "hi"})
    assert r.json() == {}


def test_daemon_post_tool_use_anonymizes():
    c = _client()
    out = c.post("/hook", params={"client": "claude"},
                 json={"hook_event_name": "PostToolUse", "tool_response": {"text": "a@b.ae"}})
    assert "updatedToolOutput" in out.json()["hookSpecificOutput"]


def test_daemon_persists_vault_on_pii(tmp_path):
    vault = tmp_path / "d.vault"
    app = build_hook_daemon("hook-secret", "t", vault_path=vault)
    TestClient(app).post("/hook", json={"hook_event_name": "PostToolUse",
                                        "tool_response": {"text": "reach ahmed@example.com"}})
    assert vault.exists()
    from apii import vault as vaultmod
    records = vaultmod.load_or_default(vault, "hook-secret")
    assert any(r.value == "ahmed@example.com" for r in records)
