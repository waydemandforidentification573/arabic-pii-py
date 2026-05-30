---
name: apii
description: >-
  Keep personal data (PII) off the LLM. Redact Arabic/GCC and general PII —
  emails, phones, IBANs, national IDs, commercial registrations, VAT numbers,
  names, organizations, addresses — into stable, reversible tokens on the local
  machine BEFORE anything reaches a model or provider, then restore the real
  values locally. Use when reading, grepping, or processing files, logs,
  datasets, DB dumps, or customer records that may contain personal info, or
  when routing LLM/API traffic through a provider that must not see real PII
  (banking, telco, government, healthcare, any GCC customer data).
license: MIT OR Apache-2.0
compatibility: Requires the `apii` Python package (pip install apii), Python 3.10+
metadata:
  project: apii
  homepage: https://github.com/Aajil-Labs/arabic-pii-py
---

## The contract (read this first)

`apii` swaps real PII for **stable, reversible tokens** (`EMAIL_4F2…`,
`IBAN_…`, `PERSON_…`) **on the local machine**. The model / provider only ever
sees tokens; the real values are restored locally for the human. Two rules that
make everything else fall out:

1. **A token IS the value.** Reason about `EMAIL_4F2…` exactly as you would the
   real email — compare it, carry it across steps, write it into files. The same
   value always maps to the same token. **Never** ask the user for the "real"
   value, and **never** refuse to work with a token.
2. **Never put real PII back into the model's context.** Restoration happens at
   the last mile — the human's screen, or a file written to disk — not back into
   the chat or your reasoning.

## When to use it

- You're about to read / `cat` / grep a file, log, CSV, or DB dump that might
  hold customer PII → redact it **first** so raw values never enter context.
- You're sending text to an LLM API/provider → put `apii` in front so the
  provider receives tokens, not PII.
- The user handles GCC / Arabic data (banks, telco, gov, clinics) and legally
  cannot ship PII to a US-hosted model.

## Install (once)

```bash
pip install "apii[all]"      # the whole tool; `pip install apii` = library core only
```

Python 3.10+. Structured kinds (email, phone, IBAN, national ID, CR, VAT,
address) work with **no models**; `PERSON` / `ORGANIZATION` use the on-device
NER models in `apii[all]`/`apii[ner]` (auto-download once on first use).

## Pick the mode that fits

### A) Redact → use → restore (CLI, one task = one vault)
```bash
# tokenize; the token↔value map is saved in a vault you control
echo "call 0501234567, email omar@aajil.sa" | apii redact --vault run.vault
apii detect notes.txt                       # audit only — list detections, change nothing
apii restore reply.txt --vault run.vault     # turn the model's tokens back into real values
```
Redact **before** the data reaches you or the model; restore **only** the final
artifact a human reads or the file written to disk. Reuse ONE vault per task so
tokens stay consistent across steps.

### B) Proxy a whole client (no code change)
```bash
apii serve                                   # local gateway → http://127.0.0.1:8720
```
Point any client's base URL at it; it tokenizes the request, forwards only
tokens upstream, and restores the (streamed) reply. Routes
`/v1/chat/completions`, `/v1/responses`, `/v1/messages`. Choose the upstream
with `APII_OPENAI_BASE` / `APII_ANTHROPIC_BASE` — works with OpenAI, Anthropic,
Codex, OpenRouter, LiteLLM, anything OpenAI-compatible.

### C) In code (library)
```python
from apii.anonymizer import Anonymizer
a = Anonymizer(secret="your-secret", tenant="acme")
r = a.anonymize(text)            # r.text = tokens → safe to send to the model
real = a.deanonymize(reply)      # restore locally, for the human only
```

## If you're an agent working inside a user's project

- **Redact-on-read.** Before you display or act on file contents that look like
  they contain PII, run `apii redact --vault <project>.vault` and work with the
  tokens. One vault per task keeps tokens consistent.
- **Restore-on-write.** When you produce a deliverable the human keeps, restore
  into *that* file only.
- Keep restored PII out of your chat/reasoning. Tokens are enough to do the job.

## Gotchas

- One **vault** + one **secret** per task → consistent, reversible tokens. The
  secret is the only way back; without it tokens are irreversible (that's the
  point). Safe to log/commit tokens; **never** log the secret or the vault.
- `apii redact <file>` reads the file as plain text. For **documents**
  (pdf/docx/xlsx) use `apii redact-dir` or `apii ui` (they preserve layout).
- Tokens are `HMAC-SHA256(secret, value)` — deterministic and stable, so cross-
  references survive redaction.

## Detected kinds

EMAIL · PHONE (GCC + international) · IBAN (ISO-7064 MOD-97, all 6 GCC) ·
NATIONAL_ID (UAE-784 / Saudi Iqama / GCC) · COMMERCIAL_REGISTRATION ·
TAX_NUMBER (VAT) · PERSON · ORGANIZATION · ADDRESS.

## Why this approach (author's note)

Most "PII redaction" either blocks you or destroys reversibility, so people turn
it off. `apii`'s bet is the opposite: make tokens **first-class** — stable and
reversible — so the agent works exactly as before and the human still sees real
values. The only thing that changes is what crosses the wire. Internalize
"**a token IS the value**" and you'll never fight it.

Full docs & source: https://github.com/Aajil-Labs/arabic-pii-py
