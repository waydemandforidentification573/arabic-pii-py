"""Score the engine against the eval corpus.

Reads gold spans (tests/eval/gold/*.jsonl) and reports typed
precision/recall plus a per-(kind, source) breakdown. Run as
`python -m apii.evaluate`.

Gold offsets are UTF-8 *byte* positions; the engine works in Python str
char offsets. Each corpus file is decoded once and a byte->char map
converts gold spans before comparison.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from apii.pipeline import Pipeline
from apii.types import EntityKind

# Corpus subdirectories searched for a gold file's source text, in order.
_CORPUS_DIRS = ("corpus", "adversarial", "large")

# Kinds apii detects. Gold spans of any other kind are not counted as
# false negatives — they're tracked separately in `out_of_scope_gold` —
# so recall reflects only what apii is responsible for.
_SCOPE_KINDS: frozenset[str] = frozenset(k.value for k in EntityKind)


def _eval_root() -> Path:
    # apii/evaluate.py -> parents[1] is the repo root.
    return Path(__file__).resolve().parents[1] / "tests" / "eval"


def _real_root() -> Path:
    """The real (non-synthetic) corpus root, once it exists."""
    return Path(__file__).resolve().parents[1] / "tests" / "eval" / "real"


@dataclass(frozen=True)
class GoldSpan:
    file: str
    start: int  # char offset, already converted from the gold byte offset
    end: int
    kind: str


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0


@dataclass
class EvalResult:
    overall: Score = field(default_factory=Score)
    by_kind: dict[str, Score] = field(default_factory=lambda: defaultdict(Score))
    by_source_tp: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    by_source_fp: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    files: int = 0
    gold_total: int = 0  # in-scope gold counted toward TP/FN
    out_of_scope_gold: int = 0  # gold rows whose kind apii doesn't claim


def _byte_to_char(raw: bytes) -> tuple[str, dict[int, int]]:
    text = raw.decode("utf-8")
    b2c: dict[int, int] = {}
    b = 0
    for ci, ch in enumerate(text):
        b2c[b] = ci
        b += len(ch.encode("utf-8"))
    b2c[b] = len(text)
    return text, b2c


def _find_corpus_file(name: str, root: Path) -> Path | None:
    for d in _CORPUS_DIRS:
        p = root / d / name
        if p.exists():
            return p
    return None


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def evaluate(pipeline: Pipeline, root: Path | None = None) -> EvalResult:
    """Score `pipeline` against a gold corpus.

    `root` defaults to the synthetic corpus (tests/eval). Pass
    `_real_root()` (tests/eval/real) to score against the real,
    publicly-sourced corpus once it's built. Both layouts are
    `<root>/gold/*.jsonl` + `<root>/{corpus,adversarial,large}/<file>`.
    """
    if root is None:
        root = _eval_root()
    res = EvalResult()

    for gp in sorted((root / "gold").glob("*.jsonl")):
        rows = [json.loads(ln) for ln in gp.read_text().splitlines() if ln.strip()]
        if not rows:
            continue
        name = rows[0]["file"]
        cp = _find_corpus_file(name, root)
        if cp is None:
            continue
        text, b2c = _byte_to_char(cp.read_bytes())

        gold: list[GoldSpan] = []
        for r in rows:
            kind = r["kind"]
            if kind not in _SCOPE_KINDS:
                res.out_of_scope_gold += 1
                continue  # not a kind apii detects; see _SCOPE_KINDS
            s, e = b2c.get(r["start"]), b2c.get(r["end"])
            if s is None or e is None:
                continue  # span not on a char boundary; skip defensively
            gold.append(GoldSpan(name, s, e, kind))

        res.files += 1
        res.gold_total += len(gold)

        dets = pipeline.detect(text)

        for d in dets:
            kind = d.kind.value
            hit = any(_overlaps((d.start, d.end), (g.start, g.end)) and g.kind == kind for g in gold)
            bucket = res.by_source_tp if hit else res.by_source_fp
            bucket[(kind, d.source)] += 1
            if hit:
                res.overall.tp += 1
                res.by_kind[kind].tp += 1
            else:
                res.overall.fp += 1
                res.by_kind[kind].fp += 1

        for g in gold:
            covered = any(
                _overlaps((d.start, d.end), (g.start, g.end)) and d.kind.value == g.kind
                for d in dets
            )
            if not covered:
                res.overall.fn += 1
                res.by_kind[g.kind].fn += 1

    return res


def main() -> None:
    import apii

    res = evaluate(apii.default_pipeline())
    o = res.overall
    print(f"files scored: {res.files}   in-scope gold spans: {res.gold_total}")
    if res.out_of_scope_gold:
        print(f"  (out-of-scope gold skipped: {res.out_of_scope_gold})")
    print(f"TP={o.tp}  FP={o.fp}  FN={o.fn}")
    print(f"typed precision={o.precision:.3f}   recall={o.recall:.3f}\n")

    print(f"{'KIND':24} {'TP':>4} {'FP':>4} {'FN':>4} {'PREC':>6} {'REC':>6}")
    for kind in sorted(res.by_kind):
        s = res.by_kind[kind]
        print(f"{kind:24} {s.tp:>4} {s.fp:>4} {s.fn:>4} {s.precision:>6.2f} {s.recall:>6.2f}")

    if res.by_source_tp or res.by_source_fp:
        print("\nby (kind, source)  TP / FP:")
        for k in sorted(set(res.by_source_tp) | set(res.by_source_fp)):
            tp = res.by_source_tp.get(k, 0)
            fp = res.by_source_fp.get(k, 0)
            print(f"  {k[0]:24} {k[1]:20} TP={tp:>4}  FP={fp:>4}")


if __name__ == "__main__":
    main()
