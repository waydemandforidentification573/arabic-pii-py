"""Residual-PII guard.

Wraps a detector pass as a post-anonymization safety check: after
redaction, confirm no detectable PII remains. `strict()` fails on any
residual detection; `audit()` reports without failing. The proxy can run
this on the anonymized request body before forwarding, as a belt-and-
braces complement to the fast leak_gate.
"""

from __future__ import annotations

import msgspec

from apii.anonymizer import Anonymizer
from apii.types import Detection


class ResidualGuardReport(msgspec.Struct):
    passed: bool
    detections: list[Detection]


class ResidualGuard:
    def __init__(self, fail_on_any_detection: bool) -> None:
        self._fail_on_any = fail_on_any_detection

    @classmethod
    def strict(cls) -> "ResidualGuard":
        return cls(True)

    @classmethod
    def audit(cls) -> "ResidualGuard":
        return cls(False)

    def check_text(self, anonymizer: Anonymizer, text: str) -> ResidualGuardReport:
        detections = anonymizer.detect(text)
        return ResidualGuardReport(
            passed=(not detections) or (not self._fail_on_any),
            detections=detections,
        )

    def ensure_text(self, anonymizer: Anonymizer, text: str) -> ResidualGuardReport:
        """Like check_text but raises ValueError in strict mode when
        residual PII remains."""
        report = self.check_text(anonymizer, text)
        if self._fail_on_any and report.detections:
            raise ValueError(
                f"residual sensitive data remained after anonymization: "
                f"{len(report.detections)} detection(s)"
            )
        return report
