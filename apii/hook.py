"""Coding-agent lifecycle hook logic.

Turns a Claude Code hook-event JSON into the hook-response: block a prompt
with raw PII (UserPromptSubmit), restore tokens before a local write or
deny a tool call whose input has PII (PreToolUse), and anonymize a tool
result before it enters context (PostToolUse).

No raw detected value ever appears in a response — block messages carry
only per-kind counts ("PHONE:1, EMAIL:2").
"""

from __future__ import annotations

import enum
import json
from collections import Counter
from typing import Optional, Union

from apii.anonymizer import Anonymizer
from apii.types import Detection


class HookClient(enum.Enum):
    CLAUDE = "claude"

    @classmethod
    def parse(cls, raw: Optional[str], default: "HookClient") -> "HookClient":
        if raw is None:
            return default
        # No .strip(): a whitespace-padded client value falls through to
        # the default rather than flipping behavior.
        if raw.lower() == "claude":
            return cls.CLAUDE
        return default


def _detection_summary(detections: list[Detection]) -> str:
    """Per-kind counts via token prefix, e.g. 'PHONE:1, EMAIL:2'. Never
    includes raw text — safe for a response or a log. Sorted for
    determinism."""
    counts: Counter[str] = Counter(d.kind.token_prefix for d in detections)
    return ", ".join(f"{k}:{counts[k]}" for k in sorted(counts))


def _collect_detections(value, anonymizer: Anonymizer, out: list[Detection]) -> None:
    if isinstance(value, str):
        out.extend(anonymizer.detect(value))
    elif isinstance(value, list):
        for item in value:
            _collect_detections(item, anonymizer, out)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_detections(item, anonymizer, out)


def _detections_in(value, anonymizer: Anonymizer) -> list[Detection]:
    out: list[Detection] = []
    if value is not None:
        _collect_detections(value, anonymizer, out)
    return out


def _anonymize_strings_in(value, anonymizer: Anonymizer):
    if isinstance(value, str):
        return anonymizer.anonymize(value).text
    if isinstance(value, list):
        return [_anonymize_strings_in(v, anonymizer) for v in value]
    if isinstance(value, dict):
        return {k: _anonymize_strings_in(v, anonymizer) for k, v in value.items()}
    return value


def _deanonymize_strings_in(value, anonymizer: Anonymizer):
    """Inverse of _anonymize_strings_in: tokens → real values (vault lookup)."""
    if isinstance(value, str):
        return anonymizer.deanonymize(value)
    if isinstance(value, list):
        return [_deanonymize_strings_in(v, anonymizer) for v in value]
    if isinstance(value, dict):
        return {k: _deanonymize_strings_in(v, anonymizer) for k, v in value.items()}
    return value


# Tools that write to local disk. On these, restore tokens→real before the
# bytes land, so deliverables hold real values while the chat stays tokens.
_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})


def _block_output(event_name: str, reason: str) -> dict:
    return {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {"hookEventName": event_name},
    }


def _pre_tool_deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def run_hook(
    event: Union[str, dict], client: HookClient, anonymizer: Anonymizer
) -> Optional[dict]:
    """Process one hook event. Returns None when no PII was found (agent
    proceeds), else the client-shaped response dict."""
    if isinstance(event, str):
        event = json.loads(event)
    if not isinstance(event, dict):
        return None  # non-object body is a safe no-op
    # Key-PRESENCE semantics: snake_case is tried first only by KEY
    # PRESENCE; a present-but-non-string value resolves to "" and does
    # NOT fall back to camelCase.
    if "hook_event_name" in event:
        raw = event["hook_event_name"]
    else:
        raw = event.get("hookEventName")
    name = raw if isinstance(raw, str) else ""

    if name == "UserPromptSubmit":
        prompt = event.get("prompt") or ""
        dets = anonymizer.detect(prompt)
        if not dets:
            return None
        return _block_output(
            "UserPromptSubmit",
            f"Sensitive data detected locally ({_detection_summary(dets)}). The prompt was "
            f"blocked before model submission. Anonymize first with `apii redact --vault <vault>` "
            f"or route the agent through the local gateway proxy.",
        )

    if name == "PreToolUse":
        tool_input = event.get("tool_input")
        # Restore-on-write: for a local-disk write, turn the tokens Claude is
        # holding back into real values BEFORE they're written, so the file is
        # correct (and an Edit's old_string matches the real on-disk content).
        if client is HookClient.CLAUDE and event.get("tool_name") in _WRITE_TOOLS:
            restored = _deanonymize_strings_in(tool_input, anonymizer)
            if restored == tool_input:
                return None  # no tokens to restore — let it through untouched
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": restored,
                    "permissionDecisionReason": (
                        "apii restored tokens to their real values before writing to local disk."
                    ),
                }
            }
        # Any other tool: deny if raw PII is about to propagate (a Bash curl,
        # a web fetch, …) so real values don't leave via a side channel.
        dets = _detections_in(tool_input, anonymizer)
        if not dets:
            return None
        return _pre_tool_deny(
            f"Sensitive data detected in pending tool input ({_detection_summary(dets)}). The "
            f"tool call was denied so raw values are not propagated. Anonymize the input first "
            f"or use a gateway-routed workflow."
        )

    if name == "PostToolUse":
        tool_response = event.get("tool_response")
        if tool_response is None:
            return None
        dets = _detections_in(tool_response, anonymizer)
        if not dets:
            return None
        sanitized = _anonymize_strings_in(tool_response, anonymizer)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedToolOutput": sanitized,
                "additionalContext": (
                    f"apii locally anonymized this output ({_detection_summary(dets)}): real PII "
                    f"appears as stable tokens (e.g. EMAIL_…, IBAN_…). Treat each token AS the "
                    f"real value — reason about it and write it into files normally. Tokens are "
                    f"automatically restored to the real values when written to disk or shown to "
                    f"the user, so do NOT ask for the real values and do NOT refuse to use the tokens."
                ),
            }
        }

    return None
