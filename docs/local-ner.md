# Local NER (optional, Arabic + English)

apii can use **local ML-based NER models** as additional detectors for
PERSON / ORGANIZATION / LOCATION. There are two slots — Arabic and
English — and they run independently. Both run on CPU on your machine and
make no network call at inference time. Names and organizations the regex
layer can't express (Arabic, transliterated, and Latin-script names) are
caught here.

NER is **opt-in**. The structured recognizers (email, phone, IBAN, VAT,
CR, national ID, address) work without it; NER adds PERSON / ORGANIZATION
and boosts ADDRESS recall.

## What NER adds

On the real-document corpus (`tests/eval/real`, `tests/eval/real_bulk`),
turning NER on lifts recall for the name/org kinds it owns:

| Kind | Recall (NER on) |
|------|-----------------|
| PERSON | ~0.91 |
| ORGANIZATION | ~0.80 |
| ADDRESS | ~1.00 (regex geo + model LOC) |

PERSON and ORGANIZATION have **no** regex recognizer — they are detected
solely by NER, so without it those two kinds are not produced at all.

## Setup

### 1. Install the extra

```bash
pip install "apii[ner]"
```

This pulls `onnxruntime`, `tokenizers`, and `huggingface_hub`.

### 2. Models download themselves on first use

The first time NER runs, the int8 ONNX models are fetched once from the
Hugging Face Hub (`aajil-labs-sa/arabic-pii-ner`, ~105 MB each for the
Arabic and English slots) and cached under `~/.cache/huggingface`.
Subsequent runs load from cache — no network.

```bash
export APII_SECRET=$(openssl rand -hex 32)
echo "Payment to Walid Barakat in الرياض on 0501234567" | apii redact --tenant demo
```

You should see `الرياض` (Riyadh) tokenized as ADDRESS by the Arabic model
and `Walid Barakat` tokenized as PERSON by the English model.

To run **fully offline** (no auto-download), set `APII_NER_NO_DOWNLOAD=1`
and provide the models yourself (see below). Without the [ner] extra or a
reachable model, apii silently falls back to the regex layer.

## Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `APII_NER_THRESHOLD` | `0.85` | Spans with mean softmax probability below this are dropped. Lower → more recall, more false positives. Raise toward 0.90 if NER over-detects city/region words. |
| `APII_NER_CASE_AUG` | `auto` | Lowercase-name recovery (see below). `auto` = only fully-lowercase input; `always` = mixed-case too; `off` = strict cased behaviour. |
| `APII_NER_MODEL` | — | Path to a local Arabic model directory (overrides the auto-download). |
| `APII_NER_EN_MODEL` | — | Path to a local English model directory (overrides the auto-download). |
| `APII_NER_HF_REPO` | `aajil-labs-sa/arabic-pii-ner` | Hub repo to fetch models from. |
| `APII_NER_NO_DOWNLOAD` | — | Set to disable the Hub fetch entirely (offline / air-gapped). |

Either model slot can be left unset to disable that engine independently.

### Lowercase-name recovery

A cased NER model leans on capitalization, so a fully-lowercase
`talk to michael brown` would otherwise slip through while `Michael
Brown` is caught. apii runs a length-preserving title-cased second pass
and merges back the PERSON spans it recovers. It is scoped to PERSON and,
in `auto` mode, only fires on fully-lowercase input — so normal cased
text is untouched. Set `APII_NER_CASE_AUG=off` for strict cased behaviour.

## Bring your own model

Point `APII_NER_MODEL` / `APII_NER_EN_MODEL` at a directory containing:

- `model_int8.onnx` *or* `model_quantized.onnx` *or* `model.onnx`
- `tokenizer.json`
- `config.json` — a Hugging Face token-classification config with an
  `id2label` map using a BIO label set (`PER` / `ORG` / `LOC`, with the
  Arabic model's `PERSON` / `ORGANIZATION` / `LOCATION` also accepted).

To convert any HF token-classification model to ONNX and quantize it:

```bash
optimum-cli export onnx \
  --model CAMeL-Lab/bert-base-arabic-camelbert-mix-ner \
  --task token-classification --dtype fp32 --opset 14 \
  models/camelbert-ner/

optimum-cli onnxruntime quantize --avx512 \
  --onnx_model models/camelbert-ner/ -o models/camelbert-ner-int8/

export APII_NER_MODEL=$(pwd)/models/camelbert-ner-int8
```

## Limitations

- The default Arabic model is trained on MSA news. Saudi/GCC bank
  statements differ in distribution — expect somewhat lower recall than a
  model's published validation score.
- Transliterated English (e.g. "Salem Alyami") is caught by the **English**
  model, not the Arabic one — keep both slots enabled for mixed text.
- The first inference loads the model into memory and is slow (~1 s).
  Subsequent calls reuse the loaded engine and run in 10–20 ms per short
  input on a commodity laptop.

## Model credits

- Arabic NER base: [`hatmimoha/arabic-ner`](https://huggingface.co/hatmimoha/arabic-ner)
- English NER base: [`dslim/bert-base-NER`](https://huggingface.co/dslim/bert-base-NER) (MIT)
- Runtime: [`onnxruntime`](https://onnxruntime.ai/) + Hugging Face
  [`tokenizers`](https://github.com/huggingface/tokenizers)

The models are loaded as inference graphs only — no training data is
bundled, and the encrypted vault never stores model artifacts.
