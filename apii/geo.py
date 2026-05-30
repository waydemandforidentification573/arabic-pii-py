"""Geo gazetteer + address co-occurrence gate.

A bare place name in prose ("met in Paris") is not PII; a place name that
co-occurs with address structure (a street word, postal code, or building
number within ~80 chars) is. The gazetteer holds country + city surface
forms (Arabic + English); find_address_gated returns only the hits that
pass the gate, which the pipeline emits as ADDRESS detections.

Activation is ENV-ONLY (APII_GEO_GAZETTEER) with no implicit fallback, so
the default pipeline stays deterministic — place names are public
geography, not a customer name/org list.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import regex

from apii.types import Detection, EntityKind

_CONTEXT_WINDOW = 80

# Address-head keywords (Arabic verbatim; English case-insensitive).
_ADDR_HEAD_RE = regex.compile(
    r"(?iu)(?:شارع|حي|طريق|بناية|مبنى|عمارة|فيلا|شقة|صندوق\s+بريد|ص\.?\s*ب|الرمز\s+البريدي"
    r"|العنوان|منطقة\s+تجارية|حي\s+تجاري|حي\s+سكني|المدينة\s+الصناعية)"
    r"|(?:street|st\.|road|rd\.|avenue|ave\.|boulevard|blvd\.|building|bldg\.|suite|ste\."
    r"|apt\.|apartment|p\.?\s*o\.?\s*box|postal\s+code|zip\s+code|industrial\s+(?:area|city))"
)
_POSTAL_CODE_RE = regex.compile(r"\b\d{4,5}\b")
_BUILDING_NUM_RE = regex.compile(r"(?iu)\b(?:#|No\.?|رقم|مبنى)\s*\d{1,5}\b")


def _has_address_context(text: str, start: int, end: int) -> bool:
    win_start = max(0, start - _CONTEXT_WINDOW)
    win_end = min(len(text), end + _CONTEXT_WINDOW)
    window = text[win_start:win_end]
    return bool(
        _ADDR_HEAD_RE.search(window)
        or _POSTAL_CODE_RE.search(window)
        or _BUILDING_NUM_RE.search(window)
    )


class GeoGazetteer:
    def __init__(self, surfaces: Optional[list[str]] = None) -> None:
        # Longest-first so the alternation prefers "United Arab Emirates"
        # over "Emirates" at the same position.
        self._surfaces = sorted(set(s.strip() for s in (surfaces or []) if len(s.strip()) >= 2),
                                key=lambda s: (-len(s), s))
        self._re = (
            regex.compile(r"(?i)(?:" + "|".join(regex.escape(s) for s in self._surfaces) + r")")
            if self._surfaces else None
        )

    @classmethod
    def from_data(cls, data: dict) -> "GeoGazetteer":
        surfaces: list[str] = []
        for entry in (data.get("countries", []) + data.get("cities", [])):
            surfaces.extend(entry.get("ar", []))
            surfaces.extend(entry.get("en", []))
        return cls(surfaces)

    @classmethod
    def load(cls, path: Path) -> "GeoGazetteer":
        return cls.from_data(json.loads(Path(path).read_text()))

    def is_empty(self) -> bool:
        return self._re is None

    def size(self) -> int:
        return len(self._surfaces)

    def find_address_gated(self, text: str) -> list[tuple[int, int, str]]:
        if self._re is None:
            return []
        out = []
        for m in self._re.finditer(text):
            if _has_address_context(text, m.start(), m.end()):
                out.append((m.start(), m.end(), m.group()))
        return out

    def detections(self, text: str) -> list[Detection]:
        return [
            Detection(start=s, end=e, kind=EntityKind.ADDRESS, text=surf,
                      confidence=0.82, source="geo.gazetteer_address_gated")
            for s, e, surf in self.find_address_gated(text)
        ]


_GLOBAL: list[Optional[GeoGazetteer]] = []


def set_global(g: Optional[GeoGazetteer]) -> None:
    _GLOBAL[:] = [g]


def current() -> GeoGazetteer:
    if not _GLOBAL:
        path = os.environ.get("APII_GEO_GAZETTEER")
        if path and Path(path).exists():
            try:
                _GLOBAL.append(GeoGazetteer.load(Path(path)))
            except (OSError, ValueError):
                _GLOBAL.append(GeoGazetteer())
        else:
            _GLOBAL.append(GeoGazetteer())
    return _GLOBAL[0] or GeoGazetteer()
