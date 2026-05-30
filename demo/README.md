---
title: apii — Arabic / GCC PII Playground
emoji: 🔒
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
---

<!-- The YAML block above configures the Hugging Face Space (Docker SDK);
     it must be the first bytes of the file. GitHub ignores it. -->

# `apii` interactive playground

A local web app that shows `apii` working on **any** text you type. Pick a
synthetic GCC sample or paste your own, and watch the two boundaries side by
side:

- **What the LLM receives** → only reversible tokens (`IBAN_…`, `GOV_ID_…`, `PERSON_…`)
- **What *you* see** → the real values, restored locally

…plus the token↔value vault and a one-click "round trip" that shows a model
reply (in tokens) restored on your screen.

> **It runs the real engine.** Detection — including **names &
> organizations** via on-device ONNX NER — happens in the actual `apii`
> pipeline behind a tiny localhost server. So names you type yourself get
> masked, exactly as the package does. Everything stays on `127.0.0.1`; the
> only outbound call is the one-time NER model download.

## Run it

Use the environment where `apii` is installed (with the `ner` extra for
name/org detection):

```bash
pip install -e ".[ner,cli,proxy,documents]"   # from the repo root, once
python demo/server.py                          # → http://127.0.0.1:8000
```

Flags: `--port 9000`, `--no-open` (don't auto-open a browser).

The **first** analyze with NER enabled downloads ~210 MB of int8 ONNX models
(cached under `~/.cache/huggingface`). Untick **"Detect names &
organizations"** for instant, structured-only detection (email / phone / IBAN /
ID / CR / VAT) with no download.

## How it works

```
browser (index.html · app.js · styles.css)
   │  POST /api/analyze {text, ner}          → mask
   │  POST /api/deanonymize {text, vault}     → restore
   ▼
demo/server.py  ──►  apii.Anonymizer  (regex + checksums + ONNX NER)
   │  analyze:     {segments, tokenized, vault}
   │  deanonymize: {text, restored, unrestored}
   ▼
split view · vault table · round-trip restore tester
```

`server.py` is stdlib-only (`http.server`); it imports the real engine. The
frontend has no detection or restore logic of its own — **both** directions run
in the real `apii` engine:

- **mask** (`/api/analyze`) → `Anonymizer.anonymize`
- **restore** (`/api/deanonymize`) → `Anonymizer.deanonymize_with_report`, rebuilt
  from the vault. This is the genuine restore path, including the **fuzzy
  fallback** that recovers tokens an LLM garbled, and it reports which tokens
  were restored vs. left untouched. The round-trip box is editable, so you can
  paste any reply (mangle a token, reorder, add prose) and test real behavior.

## Files

| file | role |
|---|---|
| `server.py` | localhost server: static files + `/api/analyze` + `/api/deanonymize` (real engine) |
| `index.html` | page structure |
| `styles.css` | styling (dark, RTL-aware, color-coded entities) |
| `app.js` | UI: calls the backend for both mask and restore, renders views/vault/tester |
| `examples.json` | synthetic GCC quick-fill samples |
| `Dockerfile` | Hugging Face Space image (bakes the NER models in) |
| `README.md` (this file) | also carries the HF Space config frontmatter |

## Hosting (free, on Hugging Face Spaces)

Detection needs the Python engine + NER models, so this isn't a static page —
it can't go on plain GitHub Pages. It deploys instead to a **Docker Space** on
Hugging Face (free CPU tier; the NER models already live on HF at
[`aajil-labs-sa/arabic-pii-ner`](https://huggingface.co/aajil-labs-sa/arabic-pii-ner)).

**One-time setup** (only two things — CI provisions the Space itself):

1. Have an HF account with **Write** access to the `aajil-labs-sa` org.
2. In the **GitHub repo**, add a secret `HF_TOKEN` — a Hugging Face *write*
   token ([settings/tokens](https://huggingface.co/settings/tokens)) for that
   account.

The workflow's first step runs `create_repo(..., exist_ok=True)`, so the Space
`aajil-labs-sa/apii-demo` is created automatically on the first run (and is a
no-op afterwards). No manual Space creation needed.

**Auto-deploy.** After that, every merge to `main` that touches `demo/` runs
[`.github/workflows/deploy-space.yml`](../.github/workflows/deploy-space.yml),
which uploads `demo/` to the Space; HF rebuilds the image and the live URL
updates. The Space frontmatter lives at the top of this README; the hosted
build sets `APII_DEMO_HOSTED=1`, which flips the privacy banner (text *is* sent
to the server there) and warms the models on boot.

> **Hosted ≠ local privacy.** On the Space, text users submit is processed on a
> server — the banner says so and steers people to the synthetic samples. The
> "nothing leaves your machine" guarantee applies to the **local** install.
