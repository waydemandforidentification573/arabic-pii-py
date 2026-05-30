# QA for Private Arabic/GCC Documents

This checklist is for validating Arabic/GCC PII coverage without exposing
raw PII. Use synthetic fixtures by default. For internal corpora, run
commands only on approved local machines or private infrastructure, and
keep outputs in secured local paths such as `run/pii_audit/...`.

Raw PII must not be sent to cloud LLMs, hosted chat tools, public issue
trackers, or external debugging services. Any cloud LLM workflow must
receive only text that has already been locally anonymized.

## Coverage checklist

apii detects the kinds below. (API keys, payment cards, and arbitrary
company-issued codes are out of scope by design — route those to a secret
scanner or a PCI tokenizer.)

| Area | QA examples to include | Expected protection |
| --- | --- | --- |
| CR documents | Arabic company names, English legal names, 10-digit CR numbers, owner names, branch addresses | `ORGANIZATION`, `COMMERCIAL_REGISTRATION` (`CR_`), `PERSON`, `ADDRESS` placeholders |
| VAT / ZATCA statements | 15-digit VAT IDs, seller/buyer names, IBANs | `TAX_NUMBER` (`TAX_ID_`), `ORGANIZATION`, `IBAN` placeholders |
| Financial / bank statements | GCC IBANs, beneficiaries, merchant names | `IBAN`, `PERSON`, `ORGANIZATION` placeholders |
| Invoices | Supplier/customer names, VAT/CR identifiers, emails, phones, addresses | Detected values replaced; JSON/text structure preserved |
| Payroll | Employee names, national IDs, salary IBANs | Identity and bank fields replaced; amounts/dates kept useful |
| KYC | Applicant names, national IDs, phone/email, address, employer | All identity/contact values replaced before model use |
| Corporate / legal | Parties, signatories, legal addresses, contact details | Parties and identifiers replaced consistently across repeated mentions |
| National IDs | UAE Emirates ID (784-shape), Saudi/contextual GCC IDs, Arabic-Indic digits | Government identifiers replaced with `GOV_ID_` tokens |
| Emails / phones / IBAN | Mixed Arabic/English text, Arabic-Indic digits, spaced and hyphenated formats | Normalized detection with deterministic placeholders |

## Privacy-safe commands

Run the test suite against the shipped fixtures and real corpus:

```bash
pip install -e ".[dev]"
pytest
```

Scan a private corpus without writing raw detected values to the summary:

```bash
apii scan-dir /secure/private-corpus \
  --ext json \
  --out run/pii_audit/private-corpus/detection_summary.jsonl
```

Create local anonymized copies and an encrypted vault:

```bash
export APII_SECRET='replace-with-a-long-local-secret'
apii redact-dir /secure/private-corpus \
  --out-dir run/pii_audit/private-corpus/anonymized \
  --manifest run/pii_audit/private-corpus/manifest.jsonl \
  --vault .local/private-corpus.vault \
  --tenant internal-qa \
  --ext json
```

Inspect only aggregate counts from a scan summary:

```bash
jq -s '{
  files: length,
  detections: map(.total_detections // 0) | add
}' run/pii_audit/private-corpus/detection_summary.jsonl
```

An anonymized directory is cloud-eligible only after its outputs have been
reviewed and approved under your internal data-handling policy.

## Policy modes

`--policy` is available on `redact` and `redact-dir` (or set `APII_POLICY`):

- `strict` (default) — every detected span is replaced with an opaque
  reversible token. Use when the payload may leave the organization.
- `balanced` — like strict, but values matching operator-approved public
  terms pass through verbatim. Use for finance workflows where public bank
  / telco / payment-rail names must stay useful.
- `audit` — detect only; nothing is replaced. Use on local/private
  machines to review what would be found.

Narrow what gets redacted with `--redact-kinds PHONE,EMAIL` (other kinds
are still reported but left in the text).

## JSON-specific checks

- Validate JSON after batch anonymization with `jq empty`; invalid JSON
  means the output is not ready for downstream use.
- Sensitive scalar keys are anonymized even when the value has no
  surrounding label — e.g. CR, VAT/TRN, national-ID, IBAN, merchant, and
  employee keys (see `apii/structured.py`).
- Amount/date keys are intentionally preserved unless they appear in a
  sensitive narrative field, keeping balances, debits, credits, and dates
  useful while still masking party and identifier fields.

## Manual review notes

- Review false negatives with synthetic reproductions whenever possible.
- Do not paste real missed values into prompts or tickets. Describe the
  pattern, document type, language, digit style, and surrounding labels.
- Treat `apii detect` output as sensitive — it prints matched text.
- Store vault files under `.local/` or another encrypted/private path and
  keep tenant secrets out of shell history and committed files.
