# RFQ extraction and approved-price matching pilot

A runnable software sample created for a potential quotation-preparation project. Synthetic inputs only; this is not a previous client delivery. The portable Python CLI exports CSV, JSON and an HTML review page, with optional native Excel export via `--xlsx`. The tested [local HTTP adapter](HTTP-INTEGRATION.md) accepts PDF/TXT content and returns the same outputs, including base64 XLSX when requested. The exporter uses the public XlsxWriter package and requires no Codex or paid API. See [XLSX notes](XLSX-NOTES.md) for the snapshot format and precision limits. The [importable n8n workflow](n8n/README.md) has also been executed against the real local API in n8n 2.38.7, with seven integration cases passing.

## Run

The [rfq-pilot-n8n-demo.zip](rfq-pilot-n8n-demo.zip) package includes the current source, PDF/TXT fixtures, catalogue, Python tests, n8n workflow and integration verifier. The previous `rfq-pilot-xlsx-demo.zip` contains the Python exporter but no n8n integration; the older `rfq-pilot-demo.zip` also predates native XLSX. Use the matching source and requirements from one package together. A generated [Excel sample](output/quote-draft.xlsx) is included.

Python 3.10+ is required. No paid API, hosted service or third-party credentials are needed. The optional HTTP adapter uses a private token generated on your own computer.

```sh
python -m pip install -r requirements.txt
python quote.py samples/rfq.pdf samples/catalogue.csv --out output --xlsx
python -m pip install -r requirements-test.txt
python -m unittest -v
```

Open `output/quote-draft.xlsx` or `output/review.html` to inspect the output. The bundled example produces six rows, four review flags and a **matched-lines subtotal of USD 32.50**. The complete quotation total remains absent until unresolved lines are addressed. Excel cells contain the validated Python results as a snapshot, not editable calculation or approval controls. Correct the source files and rerun to update them. Omitting `--xlsx` preserves the earlier CSV/JSON/HTML behavior; use a fresh output directory per input set to avoid confusing older artifacts with new ones.

For the HTTP adapter, follow [HTTP-INTEGRATION.md](HTTP-INTEGRATION.md). It requires a private local token and listens only on loopback. For the actual n8n import, credential setup and repeatable execution checks, follow [n8n/README.md](n8n/README.md). This integration targets a native n8n process on the same computer. There is no internet-hosted endpoint or automatic quote approval/sending.

Exit codes: 0 = matched draft awaiting human approval, 2 = output generated with review required, 1 = invalid input/runtime error. The sample deliberately exits 2; it is not a failed extraction.

## Pilot layout and matching rules

- One text-based PDF/TXT layout: an `ITEMS` line followed by `code | description | quantity | unit`, terminated by `END ITEMS`. Content outside the block is metadata. Invalid rows inside the block remain visible. Scanned PDFs and additional layouts are outside this demonstration.
- Catalogue header is exactly `code,description,unit,unit_price,currency,price_version`. One supplied catalogue includes the approved prices. Duplicate codes remain ambiguous, even when their prices agree.
- Codes match exactly, including case, after stripping outer spaces. Descriptions compare without case or repeated whitespace. Units compare without case; pack conversions and substitutions are never inferred.
- Repeated RFQ code/unit pairs all require review. They are neither silently removed nor billed twice.
- Quantities must be positive decimal numbers. Prices may be zero. Both allow at most nine integer and four fractional digits. Decimal arithmetic rounds each line to two decimals using half-up rounding. Currency subtotals remain separate (USD/EUR/GBP/CNY only).
- Unknown codes, description/unit conflicts, malformed rows, invalid quantities/prices or missing price versions get no quoted price. They require a corrected input/explicit human decision and rerun.
- Source filenames and SHA-256 digests accompany the JSON result. CSV formulas are escaped; import the code column as Text in Excel to preserve leading zeros. HTML content is escaped. All records stay on the local computer.

## Limitations and handover

This is a draft-preparation tool, not tax/accounting software. No stock reservation, VAT, freight, discount rules, exchange conversion, OCR, ERP access, email sending, production hosting, automatic approval or generic PDF-layout inference. A matching draft still requires human approval. The supplied PDF is a demonstrator, not the client's agreed format. Production data needs separate validation.

The 47 Python tests cover money rounding, malformed inputs, duplicates, unknown products, unit/description mismatches, currency separation, literal spreadsheet text, real PDF-to-output processing, and the local HTTP adapter. The suite includes 16 Excel/HTTP tests using the independent openpyxl reader. A separate [seven-case n8n execution check](n8n/validation.json) verifies real HTTP requests, review routing, unchanged workbook bytes and validation failures stopping the workflow. `make_sample_pdf.py` regenerates the synthetic fixture using reportlab; reportlab is not needed to run the delivered CLI or adapter. Native Microsoft Excel, n8n Cloud and customer deployment have not been validated.

Proposed first paid test: **USD 15 fixed**, one client-provided redacted text PDF (up to 20 item rows) and one catalogue sample (up to 100 rows), one agreed layout, source + CSV/JSON/review output + one correction round. Scope and payment method must be agreed before work is commissioned. The available Excel exporter can be demonstrated now; client-specific workbook columns and n8n deployment remain separately scoped after seeing the files and environment. This code improvement is not evidence of a confirmed order or payment.
