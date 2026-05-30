from apii import evaluate as ev
from apii.pipeline import Pipeline
from apii.types import EntityKind


def test_empty_pipeline_detects_nothing():
    assert Pipeline().detect("hello محمد") == []


def test_entitykind_wire_names_match_gold():
    # Every gold `kind` string must round-trip through EntityKind.
    assert EntityKind("PERSON") is EntityKind.PERSON
    assert EntityKind.ORGANIZATION.value == "ORGANIZATION"
    assert EntityKind.NATIONAL_ID.token_prefix == "GOV_ID"


def test_harness_loads_corpus_and_gold():
    # No recognizers yet, so precision is 0 — but the harness must read
    # the corpus and convert gold offsets, which means it has to find
    # false negatives. This proves the byte->char + file-loading path.
    # Scored against the REAL gold (always shipped); the development gold
    # corpus is dev-only and not shipped in the package.
    res = ev.evaluate(Pipeline(), root=ev._real_root())
    assert res.files > 0
    assert res.gold_total > 0
    assert res.overall.tp == 0
    assert res.overall.fn == res.gold_total
