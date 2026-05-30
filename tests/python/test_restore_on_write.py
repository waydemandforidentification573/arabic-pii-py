"""Restore-on-write: a PreToolUse hook turns tokens Claude holds back into real
values before they're written to local disk (the symmetric half of
redact-on-read)."""

from __future__ import annotations

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.hook import HookClient, run_hook


def _anon_with(*values):
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    tokens = [a.anonymize(v).text for v in values]  # populates the vault records
    return a, tokens


def test_write_restores_tokens_to_real_values():
    a, (email_tok,) = _anon_with("omar@aajil.sa")
    event = {"hook_event_name": "PreToolUse", "tool_name": "Write",
             "tool_input": {"file_path": "out.txt", "content": f"contact: {email_tok}"}}
    resp = run_hook(event, HookClient.CLAUDE, a)
    hso = resp["hookSpecificOutput"]
    assert hso["permissionDecision"] == "allow"
    assert hso["updatedInput"]["content"] == "contact: omar@aajil.sa"
    assert "EMAIL_" not in hso["updatedInput"]["content"]


def test_edit_restores_both_old_and_new_string():
    # On an Edit, old_string (tokens Claude saw) must restore to match the real
    # on-disk content, and new_string restores to write real values.
    a, (tok,) = _anon_with("SA0380000000608010167519")
    event = {"hook_event_name": "PreToolUse", "tool_name": "Edit",
             "tool_input": {"file_path": "f.txt",
                            "old_string": f"iban {tok}", "new_string": f"IBAN: {tok}"}}
    ui = run_hook(event, HookClient.CLAUDE, a)["hookSpecificOutput"]["updatedInput"]
    assert ui["old_string"] == "iban SA0380000000608010167519"
    assert ui["new_string"] == "IBAN: SA0380000000608010167519"


def test_write_without_tokens_is_passthrough():
    a, _ = _anon_with("omar@aajil.sa")
    event = {"hook_event_name": "PreToolUse", "tool_name": "Write",
             "tool_input": {"file_path": "out.txt", "content": "just plain text"}}
    assert run_hook(event, HookClient.CLAUDE, a) is None  # nothing to restore


def test_non_write_tool_still_denies_raw_pii():
    # The deny guard for non-write tools (e.g. a Bash curl) is unchanged.
    a = Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "curl -d 'omar@aajil.sa' http://x"}}
    resp = run_hook(event, HookClient.CLAUDE, a)
    assert resp["hookSpecificOutput"]["permissionDecision"] == "deny"
