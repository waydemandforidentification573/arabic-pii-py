"""Env-loaded suppressor + geo gazetteer layers (no-op when unset)."""

from __future__ import annotations

from apii import default_pipeline
from apii import geo as geomod
from apii import suppressor as supmod
from apii.geo import GeoGazetteer
from apii.suppressor import Suppressor
from apii.types import Detection, EntityKind


def _det(kind, text, start=0):
    return Detection(start=start, end=start + len(text), kind=kind, text=text,
                     confidence=0.9, source="test")


# ── suppressor ──

def test_suppressor_agnostic_and_kind_scoped():
    s = Suppressor.from_text("# header\nearth\nADDRESS:position\n")
    dets = [_det(EntityKind.ADDRESS, "Earth"), _det(EntityKind.ADDRESS, "Position"),
            _det(EntityKind.PERSON, "position"), _det(EntityKind.ADDRESS, "Riyadh")]
    out = s.filter(dets)
    texts = {(d.kind, d.text) for d in out}
    assert (EntityKind.ADDRESS, "Earth") not in texts  # agnostic drop
    assert (EntityKind.ADDRESS, "Position") not in texts  # kind-scoped drop
    assert (EntityKind.PERSON, "position") in texts  # other kind kept
    assert (EntityKind.ADDRESS, "Riyadh") in texts


def test_suppressor_empty_is_noop():
    s = Suppressor()
    dets = [_det(EntityKind.PERSON, "anything")]
    assert s.filter(dets) == dets


def test_pipeline_suppressor_drops_phrase_when_installed():
    # Install a suppressor that drops an EMAIL surface, run the pipeline,
    # confirm it's filtered; then reset.
    try:
        supmod.set_global(Suppressor.from_text("EMAIL:noreply@example.com"))
        dets = default_pipeline(enable_ner=False).detect("write noreply@example.com please")
        assert not any(d.text == "noreply@example.com" for d in dets)
    finally:
        supmod.set_global(Suppressor())  # reset to no-op
    # After reset, the same email is detected again.
    dets2 = default_pipeline(enable_ner=False).detect("write noreply@example.com please")
    assert any(d.kind is EntityKind.EMAIL for d in dets2)


# ── geo ──

def test_geo_gated_only_with_address_context():
    g = GeoGazetteer.from_data({"cities": [{"en": ["Riyadh"], "ar": ["الرياض"]}]})
    # Bare mention → not gated.
    assert g.find_address_gated("officials met in Riyadh today") == []
    # With a street word / postal code nearby → gated.
    assert g.find_address_gated("King Fahd Street, Riyadh 11564") != []


def test_geo_empty_is_noop():
    assert GeoGazetteer().find_address_gated("Riyadh 11564 Street") == []


def test_pipeline_geo_adds_address_when_installed():
    # "Riyadh" is gated by the nearby building number but isn't itself
    # claimed by a regex ADDRESS pattern, so the geo detection survives
    # overlap resolution (where a city+postal span would be claimed by
    # the regex layer instead — that's correct, not a geo miss).
    try:
        geomod.set_global(GeoGazetteer.from_data({"cities": [{"en": ["Riyadh"]}]}))
        dets = default_pipeline(enable_ner=False).detect("building 7 in Riyadh")
        assert any(
            d.source == "geo.gazetteer_address_gated" and d.text == "Riyadh" for d in dets
        )
    finally:
        geomod.set_global(GeoGazetteer())  # reset to no-op


def test_default_pipeline_unaffected_without_env():
    # With neither layer installed, the pipeline behaves as before.
    supmod.set_global(Suppressor())
    geomod.set_global(GeoGazetteer())
    dets = default_pipeline(enable_ner=False).detect("phone 0501234567")
    assert any(d.kind is EntityKind.PHONE for d in dets)
