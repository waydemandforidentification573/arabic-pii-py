from __future__ import annotations

from typing import Sequence

import regex

from apii import geo as _geo
from apii import suppressor as _suppressor
from apii.context import apply_context_boost
from apii.ner_merge import merge_ner
from apii.normalize import is_arabic_letter, normalize_arabic_matching_view, reverse_arabic_runs
from apii.recognizer import Recognizer
from apii.types import Detection

# Bare vault tokens (private PREFIX_HEX + balanced-mode public semantic
# tokens). Detections whose text IS one of these are dropped, so
# re-processing already-tokenized text doesn't re-detect the tokens.
_PLACEHOLDER_RE = regex.compile(
    r"\b(?:EMAIL|PHONE|IBAN|CR|TAX_ID|GOV_ID|PERSON|ORG|ADDRESS)_[A-F0-9]{10,32}\b"
    r"|\b(?:BANK|TELCO|CHANNEL|PAYMENT_RAIL|GOV)_[A-Z0-9_]+\b"
)


def _is_placeholder(text: str) -> bool:
    t = text.strip()
    m = _PLACEHOLDER_RE.fullmatch(t)
    return m is not None


class Pipeline:
    """normalize -> regex recognizers -> resolve -> merge NER.

    Construct once with a recognizer set (and optionally NER engines),
    then call `detect` per document.

    **Regex layer.** The structured recognizers run on the *normalized
    matching view* of the text (NFKC + Arabic diacritic drop +
    Arabic-Indic digit fold); every span is translated back to original
    char positions via the view's offset map. Effects:
      - Arabic-Indic digit shapes (`٠٥٠١٢٣٤٥٦٧`, `SA٥٤ ٩٩٠٠ …`) match
        the ASCII-literal regexes.
      - Diacritized Arabic matches diacritic-less literals.
    When the normalized text equals the source (ASCII / undiacritized),
    recognizers run directly on the source to skip the offset mapping.

    **NER layer.** PERSON and ORGANIZATION are detected SOLELY by NER
    (the project ships no name/org regex); NER also adds ADDRESS spans
    (model LOC). NER runs on the RAW text — the HF tokenizer already
    yields char offsets in the original coordinate space, so no mapping
    is needed. NER detections merge into the frozen regex-resolved set
    via a non-overlap union (see `apii.ner_merge.merge_ner`): regex wins
    overlap ties; Arabic NER beats English NER. Absent NER engines (no
    [ner] extra / no models), this layer is a no-op and the pipeline is
    pure regex.
    """

    def __init__(
        self,
        recognizers: Sequence[Recognizer] = (),
        ner_engines: Sequence[object] = (),
    ) -> None:
        self._recognizers = tuple(recognizers)
        self._ner_engines = tuple(ner_engines)

    def detect(self, text: str) -> list[Detection]:
        resolved = self._detect_regex(text)

        # Bidi fallback: PDF extractors emit RTL Arabic in visual order,
        # hiding it from the recognizers. Re-run on the per-run-reversed
        # view and merge non-overlapping additions. reverse_arabic_runs is
        # length-preserving so spans stay valid against the original text.
        if any(is_arabic_letter(c) for c in text):
            reversed_text = reverse_arabic_runs(text)
            if reversed_text != text and len(reversed_text) == len(text):
                extra = self._detect_regex(reversed_text)
                resolved = merge_ner(resolved, extra)

        # Context boost runs after overlap resolution (never changes which
        # spans survive — only their confidence).
        resolved = apply_context_boost(text, resolved)

        if self._ner_engines:
            ner_dets: list[Detection] = []
            for engine in self._ner_engines:
                ner_dets.extend(engine.detect(text))
            resolved = merge_ner(resolved, ner_dets)

        # Drop detections whose text is one of our own vault tokens — so
        # re-processing already-tokenized text (multi-turn, re-redaction)
        # doesn't re-detect the placeholders.
        resolved = [d for d in resolved if not _is_placeholder(d.text)]

        # Common-phrase suppressor runs last (drops structural vocabulary
        # NER mislabels as PII). No-op unless APII_SUPPRESS_PHRASES is set.
        return _suppressor.current().filter(resolved)

    def _detect_regex(self, text: str) -> list[Detection]:
        nv = normalize_arabic_matching_view(text)
        if nv.text == text:
            out: list[Detection] = []
            for rec in self._recognizers:
                out.extend(rec.find(text))
            # Geo gazetteer address detections (no-op unless APII_GEO_GAZETTEER
            # is set); run on raw text, participate in overlap resolution.
            out.extend(_geo.current().detections(text))
            return _resolve(out)
        raw: list[Detection] = []
        for rec in self._recognizers:
            raw.extend(rec.find(nv.text))
        mapped: list[Detection] = []
        for d in raw:
            span = nv.original_span(d.start, d.end)
            if span is None:
                continue
            o_start, o_end = span
            mapped.append(
                Detection(
                    start=o_start,
                    end=o_end,
                    kind=d.kind,
                    text=text[o_start:o_end],
                    confidence=d.confidence,
                    source=d.source,
                    explanation=d.explanation,
                )
            )
        mapped.extend(_geo.current().detections(text))
        return _resolve(mapped)


def _resolve(dets: list[Detection]) -> list[Detection]:
    """Resolve overlapping detections.

    Drop exact (kind, span) duplicates keeping the first emitted, then
    greedily select non-overlapping spans by confidence desc, length
    desc, start asc. A higher-confidence or longer detection claims its
    character range and suppresses anything overlapping it — this is how
    SECRET wins over an EMAIL nested in a DATABASE_URL and how the
    bare-IBAN match wins over the label-cued duplicate.
    """
    seen: set[tuple[str, int, int]] = set()
    unique: list[Detection] = []
    for d in dets:
        key = (d.kind.value, d.start, d.end)
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    if not unique:
        return []

    unique.sort(key=lambda d: (-d.confidence, -(d.end - d.start), d.start))

    max_end = max(d.end for d in unique)
    occupied = bytearray(max_end)
    selected: list[Detection] = []
    for d in unique:
        if d.start >= d.end or d.end > max_end:
            continue
        if any(occupied[d.start : d.end]):
            continue
        occupied[d.start : d.end] = b"\x01" * (d.end - d.start)
        selected.append(d)

    selected.sort(key=lambda d: d.start)
    return selected
