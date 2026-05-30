"""Local ONNX NER — Arabic (hatmimoha/arabic-ner) + English (dslim/bert-base-NER).

Both are token-classification BERTs exported to ONNX, loaded as
`model_quantized.onnx` + `tokenizer.json` + `config.json`.

Pipeline:
  1. tokenize → input_ids / attention_mask / token_type_ids(zeros),
     plus per-token offsets, special-tokens mask, and the subword strings
  2. ONNX inference → logits [1, seq, num_labels]
  3. softmax + argmax per token
  4. WordPiece merge: `##`-continuation subwords fold into the head word;
     the highest-confidence non-O tag in the word wins (handles models
     that label only the last subword, e.g. dslim)
  5. BIO aggregation, HF aggregation_strategy="first" semantics
  6. span confidence = mean of per-WORD max-class softmax probs; spans
     below the threshold (default 0.85, APII_NER_THRESHOLD) are dropped
  7. kind map: PER→Person, ORG→Organization, LOC→Address

OFFSETS: the Python `tokenizers` library returns CHARACTER offsets into
the input string. Since the whole apii engine works in char offsets, NER
detections drop in with no conversion.

Optional dependency: `pip install apii[ner]` pulls onnxruntime + tokenizers
+ numpy. Absent → `ner_available()` is False and the engine factories
return None, so the regex pipeline runs unchanged.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from apii.types import Detection, EntityKind

try:  # optional [ner] extra
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer

    _NER_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra
    _NER_AVAILABLE = False


def ner_available() -> bool:
    """True iff onnxruntime + tokenizers + numpy are importable."""
    return _NER_AVAILABLE


# Quantized variants preferred.
_MODEL_FILE_CANDIDATES = (
    "model_int8.onnx",
    "model_quantized.onnx",
    "model.onnx",
    "model_q4f16.onnx",
)

_DEFAULT_THRESHOLD = 0.85

# Max non-special tokens per inference window. BERT caps at 512 positions;
# 500 leaves margin for [CLS]/[SEP] and minor boundary re-tokenization.
_MAX_BODY_TOKENS = 500

# Arabic patronymic connectives the NER models O-tag inside transliterated
# names. They bridge (never break) a PERSON span — see the BIO loop.
_PER_CONNECTIVES = frozenset({"bin", "ibn", "bint", "bn", "بن", "ابن", "بنت"})

_SOURCE = "ner.onnx"
_SOURCE_CASEAUG = "ner.onnx.caseaug"  # spans recovered by the case-augmentation pass

# ── case-augmentation (lowercase recall) ──────────────────────────────────
# A *cased* NER model (dslim/bert-base-NER, trained on properly-cased
# CoNLL text) leans on capitalization as a signal, so a fully-lowercase
# "talk to michael brown" slips through entirely while "Michael Brown" is caught.
# To recover lowercase names we run a second inference pass on a title-cased
# variant of the text and merge back any PERSON spans the cased pass missed.
#
# Scope is deliberately tight, because title-casing is a precision bet:
#   • PERSON only. Title-casing common nouns reads them as orgs/places
#     ("finance team" → ORG, "nice" → LOC); ORG/LOC are NOT separable from
#     those FPs by threshold, so they stay sourced from the cased pass only.
#   • Gated to fully-lowercase input by default (APII_NER_CASE_AUG=auto).
#     Normal cased prose is left byte-identical — the augmented pass never
#     fires on it — so this cannot regress precision on already-cased text;
#     the bet is confined to casual lowercase input, where the alternative
#     is leaking the name in plaintext. Homonym names that are also common
#     words ("mark", "will", "bill") can still over-tokenize here — that is
#     privacy-safe over-redaction (a reversible token, never a leak).
#   • APII_NER_CASE_AUG=always forces the pass on mixed-case text too;
#     =off disables it (strict cased behaviour).
_WORD_RE = re.compile(r"[A-Za-z]+")


def _title_variant(text: str) -> str:
    """Length-preserving title-case: capitalize the first ASCII letter of
    each ASCII-letter run. a-z → A-Z is 1 char → 1 char and non-ASCII
    (Arabic) is untouched, so character offsets map 1:1 onto the original."""
    return _WORD_RE.sub(lambda m: m.group(0)[0].upper() + m.group(0)[1:], text)


def _case_aug_mode() -> str:
    raw = (os.environ.get("APII_NER_CASE_AUG") or "auto").strip().lower()
    return raw if raw in ("auto", "always", "off") else "auto"


def _should_augment(text: str, mode: str) -> bool:
    """Whether to run the case-augmentation pass on `text`."""
    if mode == "off":
        return False
    if not any("a" <= c <= "z" for c in text):
        return False  # no lowercase ASCII → nothing for title-casing to recover
    if mode == "always":
        return True
    # auto: only fully-lowercase input (no uppercase ASCII). Normal prose
    # always carries a sentence-initial capital, so this excludes it and the
    # precision bet stays confined to casual lowercase text.
    return not any("A" <= c <= "Z" for c in text)

# Hugging Face Hub fallback. When no local model is found, the int8 ONNX
# models auto-download once (cached under ~/.cache/huggingface) so a plain
# `pip install "apii[ner]"` works with zero manual setup. Repo layout: one repo
# with an `arabic-ner/` and an `en-ner/` subfolder, each holding
# model_quantized.onnx + tokenizer.json + config.json. Override the repo via
# APII_NER_HF_REPO; disable the download entirely with APII_NER_NO_DOWNLOAD=1.
_DEFAULT_HF_REPO = "aajil-labs-sa/arabic-pii-ner"


def _hf_model_dir(subdir: str) -> Optional[Path]:
    """Fetch the `subdir` model from the HF Hub repo (cached) and return its
    local path — or None if huggingface_hub is absent, downloads are disabled,
    or the fetch fails. A failure here leaves NER regex-only, never crashes.
    """
    if os.environ.get("APII_NER_NO_DOWNLOAD"):
        return None
    repo = os.environ.get("APII_NER_HF_REPO", _DEFAULT_HF_REPO)
    if not repo:
        return None
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return None
    try:
        import sys

        print(
            f"[apii] fetching NER model '{subdir}' from {repo} "
            "(~105MB, cached after first run)…",
            file=sys.stderr,
        )
        root = snapshot_download(repo_id=repo, allow_patterns=f"{subdir}/*")
        d = Path(root) / subdir
        return d if (d / "tokenizer.json").exists() else None
    except Exception:  # noqa: BLE001 - any network/auth/hub error → regex-only
        return None


def _threshold_from_env() -> float:
    """APII_NER_THRESHOLD as a float, falling back to the default on a
    missing / empty / unparseable value.

    A missing/malformed value must NOT raise — a raise here would be
    swallowed into a None engine by from_env_or_bundled, silently
    disabling NER entirely instead of running at the default 0.85.
    """
    raw = os.environ.get("APII_NER_THRESHOLD")
    if not raw:
        return _DEFAULT_THRESHOLD
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_THRESHOLD


def _pick_model_file(d: Path) -> Optional[Path]:
    for name in _MODEL_FILE_CANDIDATES:
        p = d / name
        if p.exists():
            return p
    return None


def _normalize_kind(raw: str) -> str:
    """Collapse label families onto PER / ORG / LOC / OTHER.

    Handles both the Arabic model's PERSON/ORGANIZATION/LOCATION labels
    and the English model's PER/ORG/LOC.
    """
    trimmed = raw.upper().split("-", 1)[0]
    if trimmed in ("PER", "PERS", "PERSON"):
        return "PER"
    if trimmed in ("ORG", "ORGANIZATION"):
        return "ORG"
    if trimmed in ("LOC", "LOCATION", "GPE", "FAC"):
        return "LOC"
    return "OTHER"


def _parse_label(label: str) -> tuple[str, str]:
    """Parse a BIO label → (bio_tag, kind).

    bio_tag is one of "O" / "B" / "I". S- maps to B (single-token entity);
    E- maps to I (end continues the span).
    """
    if label == "O" or not label:
        return ("O", "")
    for prefix, tag in (("B-", "B"), ("I-", "I"), ("S-", "B"), ("E-", "I")):
        if label.startswith(prefix):
            return (tag, _normalize_kind(label[len(prefix):]))
    return ("O", "")


# LOC → Address: the gateway treats a geographic entity as an address span.
_KIND_MAP = {
    "PER": EntityKind.PERSON,
    "ORG": EntityKind.ORGANIZATION,
    "LOC": EntityKind.ADDRESS,
}


class _Word:
    """A merged whole-word token: char span + winning label id + prob."""

    __slots__ = ("start", "end", "label", "prob")

    def __init__(self, start: int, end: int, label: int, prob: float) -> None:
        self.start = start
        self.end = end
        self.label = label
        self.prob = prob


class NerEngine:
    """Loaded ONNX session + tokenizer + label map for one language."""

    def __init__(self, session, tokenizer, labels: list[str], threshold: float,
                 case_augment: bool = False) -> None:
        self._session = session
        self._tokenizer = tokenizer
        self._labels = labels
        self._threshold = threshold
        # Run the lowercase-recovery pass (see _title_variant). Set for the
        # cased English engine; the Arabic model is script-cased-invariant.
        self._case_augment = case_augment
        # Cache which inputs the graph actually declares so we never feed
        # a token_type_ids tensor to a model that doesn't take one.
        self._input_names = {i.name for i in session.get_inputs()}

    # ── construction ──

    @classmethod
    def from_dir(cls, directory: Path, threshold: Optional[float] = None,
                 case_augment: bool = False) -> "NerEngine":
        """Build from a directory holding model_*.onnx + tokenizer.json +
        config.json (with id2label)."""
        if not _NER_AVAILABLE:
            raise RuntimeError("NER extra not installed (pip install apii[ner])")
        model_path = _pick_model_file(directory)
        if model_path is None:
            raise FileNotFoundError(f"no ONNX model under {directory}")
        tokenizer_path = directory / "tokenizer.json"
        if not tokenizer_path.exists():
            raise FileNotFoundError(f"tokenizer.json missing in {directory}")
        config_path = directory / "config.json"
        labels = _load_label_map(config_path)

        session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
        # The shipped tokenizer.json enables truncation (max_length=512).
        # We do our OWN ≤512-token windowing (see detect/_token_windows)
        # so we keep full recall on long documents — disable the
        # tokenizer's truncation/padding so encode() returns the complete
        # token stream and each window is a clean single sequence.
        tokenizer.no_truncation()
        tokenizer.no_padding()

        if threshold is None:
            threshold = _threshold_from_env()
        return cls(session, tokenizer, labels, threshold, case_augment=case_augment)

    @classmethod
    def from_env_or_bundled(
        cls, env_var: str, bundled_subdir: str, case_augment: bool = False
    ) -> Optional["NerEngine"]:
        """Honour an env-var model override first (operator-supplied
        directory), else fall back to the bundled models/<subdir>.
        Returns None when neither is loadable.
        """
        if not _NER_AVAILABLE:
            return None
        override = os.environ.get(env_var)
        if override:
            try:
                return cls.from_dir(Path(override), case_augment=case_augment)
            except Exception:  # noqa: BLE001
                # A corrupt/truncated model, bad tokenizer.json, or any
                # onnxruntime load error must DEGRADE to None (and fall
                # through to the bundled model), never crash the pipeline.
                # The except must stay broad: a narrow one lets onnxruntime
                # InvalidProtobuf / a bare tokenizer Exception escape.
                pass
        bundled = Path("models") / bundled_subdir
        if (
            _pick_model_file(bundled) is not None
            and (bundled / "tokenizer.json").exists()
            and (bundled / "config.json").exists()
        ):
            try:
                return cls.from_dir(bundled, case_augment=case_augment)
            except Exception:  # noqa: BLE001 - corrupt bundled model → regex-only
                return None
        # Last resort: auto-download from the HF Hub (cached), so a fresh
        # `pip install "apii[ner]"` works with no manual model placement.
        hf = _hf_model_dir(bundled_subdir)
        if hf is not None:
            try:
                return cls.from_dir(hf, case_augment=case_augment)
            except Exception:  # noqa: BLE001
                return None
        return None

    # ── inference ──

    def detect(self, text: str) -> list[Detection]:
        """Run NER, return char-offset Detections. Empty on blank input
        or any inference error (degrades gracefully).

        When `case_augment` is set (English engine), a fully-lowercase input
        also gets a title-cased second pass whose PERSON spans are merged in,
        so casual lowercase names ("talk to michael brown") are caught instead
        of leaking. See `_title_variant` / `_should_augment` for the scope
        and precision rationale (PERSON-only, gated, length-preserving)."""
        if not text.strip():
            return []
        out = self._detect_core(text)
        if not self._case_augment:
            return out
        mode = _case_aug_mode()
        if not _should_augment(text, mode):
            return out
        variant = _title_variant(text)
        if variant == text or len(variant) != len(text):
            return out  # nothing recased, or (defensive) length drifted

        def _ov(a: Detection, b: Detection) -> bool:
            return a.start < b.end and b.start < a.end

        # The cased model is unreliable on fully-lowercase input: it drops
        # name heads and emits fragments ("al"/"saud" while "mohammed" leaks
        # in plaintext). The title-cased pass is the more coherent PERSON
        # detector here, so for PERSON we let it REPLACE overlapping cased
        # spans (closing those leaks) — never losing coverage, since a cased
        # PERSON span the title-cased pass missed is still kept. ORG/ADDRESS
        # stay sourced from the cased pass (title-case over-flags them).
        aug = [
            Detection(
                start=d.start,
                end=d.end,
                kind=d.kind,
                text=text[d.start:d.end],  # real (original-case) surface
                confidence=d.confidence,
                source=_SOURCE_CASEAUG,
            )
            for d in self._detect_core(variant)
            if d.kind is EntityKind.PERSON
        ]
        non_person = [e for e in out if e.kind is not EntityKind.PERSON]
        # an augmented PERSON must not clobber a structured non-PERSON span
        aug = [a for a in aug if not any(_ov(a, e) for e in non_person)]
        # keep cased PERSON spans the title-cased pass didn't cover
        kept_person = [
            e for e in out
            if e.kind is EntityKind.PERSON and not any(_ov(e, a) for a in aug)
        ]
        merged = non_person + kept_person + aug
        merged.sort(key=lambda x: x.start)
        return merged

    def _detect_core(self, text: str) -> list[Detection]:
        """Windowed NER over `text` (the original detect path).

        BERT caps at 512 positions; a longer document would crash the
        ONNX graph ("broadcast 512 by N"). So we WINDOW the input into
        <=`_MAX_BODY_TOKENS`-token slices at token boundaries, run each,
        and offset detections back, so long documents keep full NER recall.
        """
        if not text.strip():
            return []
        try:
            windows = self._token_windows(text)
        except Exception:  # noqa: BLE001 - tokenizer hiccup → no NER
            return []
        out: list[Detection] = []
        for char_offset, segment in windows:
            try:
                dets = self._detect_inner(segment)
            except Exception as exc:  # noqa: BLE001 - per-window graceful fallback
                import sys

                print(f"apii: NER inference failed on a window: {exc}", file=sys.stderr)
                continue
            if char_offset == 0:
                out.extend(dets)
            else:
                for d in dets:
                    out.append(
                        Detection(
                            start=d.start + char_offset,
                            end=d.end + char_offset,
                            kind=d.kind,
                            text=d.text,
                            confidence=d.confidence,
                            source=d.source,
                        )
                    )
        return out

    def _token_windows(self, text: str) -> list[tuple[int, str]]:
        """Split `text` into (char_offset, segment) windows each tokenizing
        to <= _MAX_BODY_TOKENS non-special tokens. Splits at token
        boundaries via the tokenizer's char offsets, so a window's text
        re-tokenizes to roughly the same length (well under 512). A single
        short doc yields one window at offset 0 (the fast path)."""
        enc = self._tokenizer.encode(text)
        body = [i for i in range(len(enc.ids)) if enc.special_tokens_mask[i] == 0]
        if len(body) <= _MAX_BODY_TOKENS:
            return [(0, text)]
        windows: list[tuple[int, str]] = []
        for w in range(0, len(body), _MAX_BODY_TOKENS):
            chunk = body[w : w + _MAX_BODY_TOKENS]
            c_start = enc.offsets[chunk[0]][0]
            c_end = enc.offsets[chunk[-1]][1]
            if c_end > c_start:
                windows.append((c_start, text[c_start:c_end]))
        return windows

    def _detect_inner(self, text: str) -> list[Detection]:
        enc = self._tokenizer.encode(text)
        ids = enc.ids
        seq_len = len(ids)
        if seq_len == 0:
            return []

        ids_arr = np.array([ids], dtype=np.int64)
        feeds = {"input_ids": ids_arr}
        if "attention_mask" in self._input_names:
            feeds["attention_mask"] = np.array([enc.attention_mask], dtype=np.int64)
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros((1, seq_len), dtype=np.int64)

        logits = self._session.run(None, feeds)[0][0]  # [seq, num_labels]
        num_labels = len(self._labels)
        if logits.shape != (seq_len, num_labels):
            raise ValueError(
                f"expected logits {(seq_len, num_labels)} got {logits.shape}"
            )

        # Softmax + argmax per token (vectorized over the sequence).
        shifted = logits - logits.max(axis=1, keepdims=True)
        exps = np.exp(shifted)
        probs = exps / exps.sum(axis=1, keepdims=True)
        argmax = probs.argmax(axis=1)
        max_prob = probs[np.arange(seq_len), argmax]

        offsets = enc.offsets
        special = enc.special_tokens_mask
        tokens = enc.tokens

        try:
            outside_id = self._labels.index("O")
        except ValueError:
            outside_id = -1

        # ── WordPiece merge ──
        words: list[_Word] = []
        for i in range(seq_len):
            if special[i] == 1:
                continue
            s, e = offsets[i]
            lid = int(argmax[i])
            p = float(max_prob[i])
            is_continuation = tokens[i].startswith("##")
            if is_continuation and words:
                last = words[-1]
                last.end = e
                last_outside = last.label == outside_id
                this_outside = lid == outside_id
                if not this_outside and (last_outside or p > last.prob):
                    last.label = lid
                    last.prob = p
                continue
            words.append(_Word(s, e, lid, p))

        # ── BIO aggregation, aggregation_strategy="first" ──
        # PLUS a patronymic bridge: the NER models tag the Arabic
        # patronymic connective "bin"/"ibn"/"bint" (and Arabic بن/ابن/بنت)
        # as O inside transliterated names, which would flush the PERSON
        # span at the connective. Worse, the resulting fragments are scored
        # independently and a borderline trailing name token can fall below
        # the 0.85 threshold and LEAK in plaintext ("Khalid bin Sultan" →
        # "<token> bin Sultan"). We bridge: a connective never breaks a
        # PERSON span — the span stays whole so its high-confidence head
        # carries the tail token over threshold. The connective's own
        # (low, O-class) prob is NOT added, so the span mean isn't dragged
        # down.
        detections: list[Detection] = []
        # current: (kind_str, start, end, [probs])
        current: Optional[tuple[str, int, int, list[float]]] = None
        bridged = False  # the previous word was a bridged PERSON connective

        def flush() -> None:
            nonlocal current
            if current is not None:
                self._emit(detections, text, *current)
                current = None

        for w in words:
            label = self._labels[w.label] if 0 <= w.label < num_labels else "O"
            tag, kind = _parse_label(label)

            # Patronymic bridge: only inside an open PERSON span.
            if current is not None and current[0] == "PER":
                surface = text[w.start : w.end].strip().lower()
                if surface in _PER_CONNECTIVES:
                    # Extend the span across the connective without flushing
                    # and without polluting the prob list.
                    current = (current[0], current[1], w.end, current[3])
                    bridged = True
                    continue

            if tag == "O":
                flush()
                bridged = False
            elif tag == "B":
                # A B-tag right after a bridged connective continues the same
                # PERSON span instead of starting a fresh fragment.
                if bridged and current is not None and kind == current[0]:
                    current = (current[0], current[1], w.end, current[3] + [w.prob])
                else:
                    flush()
                    current = (kind, w.start, w.end, [w.prob])
                bridged = False
            else:  # tag == "I"
                if current is not None and current[0] == kind:
                    current = (current[0], current[1], w.end, current[3] + [w.prob])
                else:
                    # I-X without matching B-X: open a fresh span (lenient
                    # "first" semantics).
                    flush()
                    current = (kind, w.start, w.end, [w.prob])
                bridged = False
        flush()
        return detections

    def _emit(
        self,
        detections: list[Detection],
        text: str,
        kind_str: str,
        start: int,
        end: int,
        probs: list[float],
    ) -> None:
        """Emit a span: mean-prob threshold + kind map. Confidence is the
        mean over per-WORD probs in the span."""
        if not probs or end <= start or end > len(text):
            return
        mean = sum(probs) / len(probs)
        if mean < self._threshold:
            return
        kind = _KIND_MAP.get(kind_str)
        if kind is None:
            return
        detections.append(
            Detection(
                start=start,
                end=end,
                kind=kind,
                text=text[start:end],
                confidence=mean,
                source=_SOURCE,
            )
        )


def _load_label_map(config_path: Path) -> list[str]:
    """Load id2label from a HF token-classification config.json."""
    if not config_path.exists():
        raise FileNotFoundError(f"config.json missing: {config_path}")
    cfg = json.loads(config_path.read_text())
    id2label = cfg.get("id2label")
    if not isinstance(id2label, dict) or not id2label:
        raise ValueError(f"config.json has no id2label: {config_path}")
    pairs = sorted((int(k), v) for k, v in id2label.items())
    return [label for _, label in pairs]


# ── process-wide lazy singletons (one per language) ──

_ENGINE_AR: list[Optional[NerEngine]] = []
_ENGINE_EN: list[Optional[NerEngine]] = []


def shared_arabic() -> Optional[NerEngine]:
    """Lazily build the Arabic engine (APII_NER_MODEL override → models/arabic-ner)."""
    if not _ENGINE_AR:
        _ENGINE_AR.append(
            NerEngine.from_env_or_bundled("APII_NER_MODEL", "arabic-ner")
            if _NER_AVAILABLE
            else None
        )
    return _ENGINE_AR[0]


def shared_english() -> Optional[NerEngine]:
    """Lazily build the English engine (APII_NER_EN_MODEL override → models/en-ner).

    case_augment=True: the cased English model misses fully-lowercase names,
    so it gets the title-cased recovery pass (see _title_variant)."""
    if not _ENGINE_EN:
        _ENGINE_EN.append(
            NerEngine.from_env_or_bundled("APII_NER_EN_MODEL", "en-ner", case_augment=True)
            if _NER_AVAILABLE
            else None
        )
    return _ENGINE_EN[0]


def shared_engines() -> list[NerEngine]:
    """All available NER engines (Arabic + English), skipping any that
    failed to load. Empty when the [ner] extra or the models are absent."""
    return [e for e in (shared_arabic(), shared_english()) if e is not None]
