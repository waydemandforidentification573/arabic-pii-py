"""Merge NER detections into the regex-resolved detection set.

NER is the SOLE authority for PERSON and ORGANIZATION (there is no name/org
regex — those patterns are too brittle across Arabic, transliterated, and
Latin forms to beat the models), and a recall booster for ADDRESS (model
LOC → Address). The merge is a simple non-overlap union:

  - The regex-resolved set is frozen and added first, so a structured
    regex detection (ADDRESS, IBAN, …) WINS a tie against an
    overlapping NER span.
  - NER detections are appended in engine order (Arabic before English),
    each kept only if it overlaps nothing already accepted — so an
    Arabic NER hit beats an overlapping English NER hit, and neither
    can clobber a regex span.
  - Final result is position-sorted.

There is no witness gating: with NER as the sole name/org authority, the
model's confidence threshold (0.85, APII_NER_THRESHOLD) is the precision
control.
"""

from __future__ import annotations

from apii.types import Detection


def _overlaps(a: Detection, b: Detection) -> bool:
    return a.start < b.end and b.start < a.end


def merge_ner(resolved: list[Detection], ner_dets: list[Detection]) -> list[Detection]:
    """Append non-overlapping NER detections to the frozen regex set."""
    out = list(resolved)
    for d in ner_dets:
        if any(_overlaps(e, d) for e in out):
            continue
        out.append(d)
    out.sort(key=lambda x: x.start)
    return out
