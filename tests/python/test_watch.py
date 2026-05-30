"""Side-viewer: restore apii tokens in a Claude Code transcript for local display."""

from __future__ import annotations

import json

from apii import default_pipeline, vault
from apii.anonymizer import Anonymizer
from apii.watch import _complete_lines, iter_assistant_text, run


def test_complete_lines_holds_back_a_partial_trailing_line():
    # A poll that lands mid-write must not consume the partial last line —
    # otherwise its head is read now and its tail next poll, and the whole
    # JSON line never parses (the message would be silently dropped).
    buf = b'{"a":1}\n{"b":2}\n{"c":'          # last line incomplete
    lines, consumed = _complete_lines(buf)
    assert lines == ['{"a":1}', '{"b":2}']    # only complete lines surfaced
    assert consumed == len(b'{"a":1}\n{"b":2}\n')  # partial tail held back

    # next poll: the writer finished the line — re-reading from the held-back
    # offset yields the now-complete line intact.
    rest = buf[consumed:] + b'3}\n'
    lines2, consumed2 = _complete_lines(rest)
    assert lines2 == ['{"c":3}']
    assert consumed2 == len(rest)


def test_complete_lines_all_partial_consumes_nothing():
    lines, consumed = _complete_lines(b'{"partial":')
    assert lines == [] and consumed == 0


def test_newest_transcript_is_folder_scoped_no_global_fallback(tmp_path, monkeypatch):
    import apii.watch as w
    monkeypatch.setattr(w, "_projects_root", lambda: tmp_path)
    proj_a = tmp_path / w._encode_cwd("/work/projA")
    proj_a.mkdir()
    (proj_a / "s1.jsonl").write_text("{}\n")
    proj_b = tmp_path / w._encode_cwd("/work/projB")  # an unrelated session
    proj_b.mkdir()
    (proj_b / "s2.jsonl").write_text("{}\n")
    # scoped to projA → projA's transcript
    assert w.newest_transcript("/work/projA") == proj_a / "s1.jsonl"
    # a folder with NO session → None, never another folder's chat
    assert w.newest_transcript("/work/projC") is None


def test_iter_assistant_text_extracts_only_assistant_text():
    lines = [
        json.dumps({"type": "user", "message": {"content": "hi"}}),
        json.dumps({"type": "queue-operation"}),
        json.dumps({"type": "assistant", "timestamp": "T1", "message": {
            "content": [{"type": "thinking", "thinking": "hmm"},
                        {"type": "text", "text": "the answer"}]}}),
    ]
    assert list(iter_assistant_text(lines)) == [("T1", "the answer")]
    # thinking shown only when asked
    out = list(iter_assistant_text(lines, show_thinking=True))
    assert out == [("T1", "[thinking] hmm\nthe answer")]


def test_watch_once_restores_real_values_locally(tmp_path, capsys):
    secret, tenant = "watch-secret", "org-a"
    # 1. tokenize some PII and persist the token↔value map to a vault (this is
    #    what the redact-on-read hook does when Claude reads a file).
    a = Anonymizer(secret, tenant, pipeline=default_pipeline(enable_ner=False))
    anon = a.anonymize("reach omar@aajil.sa or wire SA0380000000608010167519")
    assert "EMAIL_" in anon.text and "IBAN_" in anon.text  # PII really tokenized
    vpath = tmp_path / "org.vault"
    vault.save_encrypted(vpath, secret, a.records())

    # 2. a transcript where the assistant answers using those tokens (all the
    #    model ever saw) — exactly what Claude Code writes to disk.
    tpath = tmp_path / "session.jsonl"
    assistant = {"type": "assistant", "timestamp": "2026-05-29T12:00:00Z",
                 "message": {"role": "assistant", "content": [
                     {"type": "text", "text": "I'll email " + anon.text.split("reach ")[1]}]}}
    tpath.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": "help"}}),
        json.dumps(assistant),
    ]) + "\n")

    # 3. the side-viewer restores the tokens for local display.
    rc = run(secret, tenant, str(vpath), str(tpath), once=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "omar@aajil.sa" in out                 # real value shown to the user
    assert "SA0380000000608010167519" in out
    assert "EMAIL_" not in out and "IBAN_" not in out  # tokens fully resolved


def test_watch_once_no_transcript_is_clean_error(tmp_path, capsys):
    rc = run("s", "t", None, str(tmp_path / "missing.jsonl"), once=True)
    assert rc == 1
