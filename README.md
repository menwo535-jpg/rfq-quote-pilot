# RFQ extraction and approved-price matching pilot

A runnable software sample created for a potential quotation-preparation project. Synthetic inputs only; this is not a previous client delivery. The portable Python CLI exports CSV, JSON and an HTML review page. A tested [local HTTP adapter](HTTP-INTEGRATION.md) now accepts PDF/TXT content and returns those same outputs for workflow integration. A native [Excel demonstration workbook](quote-draft.xlsx) is also available, produced separately from the same JSON result using the Codex bundled spreadsheet runtime. See [XLSX notes](XLSX-NOTES.md) for validation and limitations. An executed n8n workflow and standalone Python XLSX export are **not implemented**.

## Run

Download and unzip [`rfq-pilot-demo.zip`](rfq-pilot-demo.zip) for the complete runnable package, including the PDF/TXT fixtures, catalogue and generated outputs. The individual source files in the repository are also provided for convenient inspection.

Python 3.10+ is required. No paid API, hosted service or third-party credentials are needed. The optional HTTP adapter uses a private token generated on your own computer.

```sh
python -m pip install -r requirements.txt
python quote.py samples/rfq.pdf samples/catalogue.csv --out output
python -m unittest -v
```

Open `output/review.html` to inspect the output. The bundled example produces six rows, four review flags and a **matched-lines subtotal of USD 32.50**. The complete quotation total remains absent until unresolved lines are addressed. The ZIP contains the portable CLI, HTTP adapter, samples, tests and CSV/JSON/HTML demonstration; download `quote-draft.xlsx` separately for the native Excel draft.

For the HTTP adapter, follow [HTTP-INTEGRATION.md](HTTP-INTEGRATION.md). It requires a private local token and listens only on loopback. It is intended for small trusted tests on one computer. The guide explains how to configure an n8n HTTP Request node, but that n8n configuration has not been executed. There is no internet-hosted endpoint.

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

The 31 tests cover money rounding, malformed inputs, duplicates, unknown products, unit/description mismatches, currency separation, formula/text escaping, real PDF-to-output processing, and the local HTTP adapter's authentication, request validation and output. `make_sample_pdf.py` regenerates the synthetic fixture using reportlab; reportlab is not needed to run the delivered CLI or adapter.

Proposed first paid test: **USD 15 fixed**, one client-provided redacted text PDF (up to 20 item rows) and one catalogue sample (up to 100 rows), one agreed layout, source + CSV/JSON/review output + one correction round. Scope and payment method must be agreed before work is commissioned. Native Excel/n8n integration would be separately scoped after seeing the files and deployment environment.
