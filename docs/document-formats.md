# Document format support

apii ingests text out of real document formats, runs detection over the
extracted text, and emits a masked output in the original format wherever
possible.

```bash
pip install "apii[documents]"
```

## Support matrix

| Format | Input | Output | Layout preserved | Notes |
|---|---|---|---|---|
| TXT, MD | ✓ | `.txt` / `.md` | n/a | UTF-8 required. |
| CSV | ✓ | `.csv` | ✓ (headers, row count, cell positions) | Re-quotes cells when tokens contain commas. |
| JSON | ✓ | `.json` | ✓ (object keys, non-string leaves, types) | Only string LEAVES are PII candidates. Numbers, booleans, nulls, and keys round-trip unchanged. |
| HTML | ✓ | `.html` | ✓ (markup, attributes, doctypes, comments) | Text inside `<script>` and `<style>` is intentionally NOT passed to the detector. |
| DOCX | ✓ | `.docx` | ✓ (tables, formatting, headers, footers, comments, images) | Only `<w:t>` element bodies are touched; everything else in the zip is byte-identical. |
| XLSX | ✓ | `.xlsx` | ✓ (formulas, formatting, merged cells, named ranges) | Walks `xl/sharedStrings.xml` and every `xl/worksheets/sheet*.xml`. |
| PDF | ✓ | `.txt` | ✗ — text-only output | apii extracts the text and redacts that; it does not edit the PDF in place. Needs the `pypdf` dependency. |

Format detection: by file extension first, then magic-bytes (`%PDF-`,
`PK\x03\x04` for Office zips, `<!doctype html`, leading `{`/`[` for
JSON), falling through to plain text.

## How structure is preserved

Every adapter uses the same pattern:

- Walk the source once to find every text-bearing range.
- Concatenate the bodies into a "detector view" string, separated by
  ASCII control characters that no PII regex matches (`U+001F` between
  CSV cells, `U+001E` between rows / JSON leaves / HTML text nodes / DOCX
  runs / XLSX `<t>` elements).
- Run detection on the concatenated text. Detection spans cannot cross a
  structural boundary, so a name in one cell cannot span two cells.
- After token substitution, re-split on the same separator and splice
  each leaf back into its original byte range. The bytes around each
  range are copied through verbatim, so formatting, attributes, formulas,
  etc. survive.

For DOCX and XLSX, the source zip is unpacked, only the text-bearing XML
parts are rewritten, and the archive is re-zipped with every other part
(relationships, styles, fonts, images, charts, workbook metadata)
byte-identical.

## Using it

### A whole folder — `apii redact-dir` (format-aware)

```bash
export APII_SECRET=$(openssl rand -hex 32)
apii redact-dir ./statements \
  --out-dir ./statements.masked \
  --ext csv \
  --vault statements.vault \
  --tenant bank-a
```

Each matching file is redacted into `--out-dir` in its original format,
and the token→value records are merged into one encrypted vault. Restore a
single file later with `apii restore <file> --vault statements.vault`.

Audit a folder without writing redacted copies:

```bash
apii scan-dir ./statements --ext csv --out audit.jsonl
```

### A single file — the local UI

```bash
apii ui          # opens http://127.0.0.1:8765 in your browser
```

Drag a CSV/Excel/JSON/text file in, download the masked copy in its
original format, and paste an LLM's reply back to restore real values.
Everything stays on `localhost`.

> `apii redact <file>` (the text command) reads a file as plain UTF-8 text
> — use `redact-dir` or the UI for structured formats so the layout is
> preserved.

## Known limits

- **DOCX run fragmentation.** Word may split a typed sentence across
  multiple `<w:r>` runs. The detector sees clean per-run text, so a PII
  span that crosses a run boundary won't be caught. Most real PII fits in
  one run.
- **PDF text extraction is best-effort.** Tables, columns, right-to-left
  Arabic, and OCR-broken text produce imperfect plaintext, and the output
  is plain `.txt`.
- **No image redaction.** Images (logos, signatures, photos of IDs) inside
  any container pass through unchanged. Pre-OCR image-bearing PDFs first.
- **Encoding.** Every adapter requires UTF-8 input. Re-encode legacy
  Windows-1256 / CP1252 sources first.
