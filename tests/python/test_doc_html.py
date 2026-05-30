"""HTML document adapter — extract granularity + redact round-trip.

The adapter is stdlib-only (no lxml); the tests need no external dep.
"""

from __future__ import annotations

from apii import default_pipeline
from apii.anonymizer import Anonymizer
from apii.documents import DocumentKind, extract_for_kind, redact_document
from apii.documents._base import HtmlTextNode
from apii.documents.html import NODE_SEP, HtmlAdapter


def _anonymizer() -> Anonymizer:
    return Anonymizer("k", "t", pipeline=default_pipeline(enable_ner=False))


def test_extract_text_and_segments():
    html = (
        "<html><body><p>Customer Ahmed</p>"
        "<p>Phone: 0501234567 email a@b.ae</p></body></html>"
    )
    ex = extract_for_kind(DocumentKind.HTML, html.encode())
    assert ex.kind is DocumentKind.HTML
    # Two prose text nodes -> two segments.
    assert len(ex.segments) == 2
    assert all(isinstance(seg.source, HtmlTextNode) for seg in ex.segments)
    assert [seg.source.index for seg in ex.segments] == [0, 1]
    # PII survived extraction into the detector view.
    assert "Customer Ahmed" in ex.text
    assert "0501234567" in ex.text
    assert "a@b.ae" in ex.text
    # Tag bytes did not.
    assert "<p>" not in ex.text
    assert "<html>" not in ex.text
    # Segment ranges point at the right slices, separated by NODE_SEP.
    for seg in ex.segments:
        start, end = seg.text_range
        assert end <= len(ex.text)
    assert NODE_SEP in ex.text


def test_extract_skips_script_style_comment_doctype():
    html = (
        "<!DOCTYPE html><!--secret 0501234567-->"
        "<html><head><style>body { color: red; }</style></head>"
        '<body><script>alert("0507654321");</script>'
        "<p>Hello Ahmed</p></body></html>"
    )
    ex = extract_for_kind(DocumentKind.HTML, html.encode())
    assert "Hello Ahmed" in ex.text
    assert "alert" not in ex.text
    assert "0507654321" not in ex.text  # script content not detector-visible
    assert "color" not in ex.text  # style content not detector-visible
    assert "secret" not in ex.text  # comment not detector-visible
    assert "0501234567" not in ex.text
    # One visible prose node.
    assert len(ex.segments) == 1


def test_extract_preserves_quoted_attribute_angles():
    # A `>` inside a quoted attribute value must not be treated as tag end.
    html = "<a href=\"https://x.test?q=1>foo\" title='angle<bracket'>Click</a>"
    ex = extract_for_kind(DocumentKind.HTML, html.encode())
    assert ex.text.startswith("Click")
    assert len(ex.segments) == 1
    # Round-trip with identity content preserves attribute syntax.
    out = HtmlAdapter.emit(html.encode(), ex, ex.text).decode()
    assert 'href="https://x.test?q=1>foo"' in out
    assert "title='angle<bracket'" in out


def test_emit_identity_round_trips_source_exactly():
    html = "<html><body><p>Customer Ahmed paid via 0501234567</p></body></html>"
    ex = extract_for_kind(DocumentKind.HTML, html.encode())
    out = HtmlAdapter.emit(html.encode(), ex, ex.text)
    assert out.decode() == html


def test_emit_token_substitution_keeps_markup():
    html = "<html><body><p>Customer Ahmed paid via 0501234567</p></body></html>"
    ex = extract_for_kind(DocumentKind.HTML, html.encode())
    anonymized = ex.text.replace("0501234567", "PHONE_TOKEN")
    out = HtmlAdapter.emit(html.encode(), ex, anonymized).decode()
    assert out.startswith("<html><body><p>")
    assert out.endswith("</p></body></html>")
    assert "0501234567" not in out
    assert "PHONE_TOKEN" in out


def test_emit_count_mismatch_raises():
    import pytest

    from apii.documents._base import DocumentError

    html = "<p>one</p><p>two</p>"
    ex = extract_for_kind(DocumentKind.HTML, html.encode())
    # Drop a separator so the leaf count no longer matches node count.
    mangled = ex.text.replace(NODE_SEP, "", 1)
    with pytest.raises(DocumentError):
        HtmlAdapter.emit(html.encode(), ex, mangled)


def test_emit_empty_document_raises():
    # A prose-less document (zero text nodes) splits the anonymized view
    # to [""] (one leaf) vs zero nodes — a mismatch we refuse by raising.
    import pytest

    from apii.documents._base import DocumentError

    html = "<html></html>"
    ex = extract_for_kind(DocumentKind.HTML, html.encode())
    assert ex.text == ""
    assert ex.segments == []
    with pytest.raises(DocumentError):
        HtmlAdapter.emit(html.encode(), ex, ex.text)


def test_redact_document_round_trip():
    html = (
        "<!DOCTYPE html><html><body>"
        "<p>Customer Ahmed</p>"
        "<p>Phone 0501234567 email a@b.ae</p>"
        '<a href="mailto:a@b.ae">contact</a>'
        "</body></html>"
    )
    a = _anonymizer()
    kind, out, report = redact_document(html.encode(), a, kind=DocumentKind.HTML)
    assert kind is DocumentKind.HTML
    redacted = out.decode()

    # PII is gone from prose text nodes; tokens spliced in; markup intact.
    assert "0501234567" not in redacted
    assert "PHONE_" in redacted
    assert "EMAIL_" in redacted
    assert "<!DOCTYPE html>" in redacted
    assert "<html><body>" in redacted
    assert "</body></html>" in redacted
    # The href value lives in an attribute (a tag), so the email there is
    # untouched — only prose text nodes are detector-visible.
    assert 'href="mailto:a@b.ae"' in redacted

    # Restore: deanonymizing the redacted file recovers the original
    # source exactly (the only changed regions were the prose nodes).
    assert a.deanonymize(redacted) == html
