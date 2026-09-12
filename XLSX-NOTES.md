# Portable Excel quotation export

`python quote.py samples/rfq.pdf samples/catalogue.csv --out output --xlsx` now generates a native workbook directly from the quotation engine. The optional HTTP `include_xlsx: true` field returns the same format as base64. Python 3.10+, the public XlsxWriter package and the existing PDF dependency are sufficient. No Codex spreadsheet runtime, Node.js, paid API or desktop Excel installation is required by the exporter.

The supplied synthetic example has six rows, four requiring review and a USD 32.50 **matched-lines subtotal**. No complete total appears while any line needs review. This is a software demonstration, not an accepted quotation or a payment record.

## Workbook contract

- `Quote` contains the status, row counts, separate currency subtotals and every requested line. An autofilter and frozen headings make the review rows easier to inspect. Amber rows need correction/review and carry no quoted price or line amount.
- `Sources` records the input basenames and SHA-256 digests. Source page/line references and price-list versions remain in the detail table. Absolute local paths and API tokens are not included.
- Product codes stay text, preserving leading zeros. Valid quantities and money are numeric cells. Invalid quantities stay as the original text. Formula-like strings, URLs and descriptions are literal text, not formulas or hyperlinks.
- Python Decimal performs the line rounding and currency aggregation. The workbook stores those results as **fixed values**. Editing cells does not recalculate matching, totals or approval. Correct the source RFQ/catalogue and regenerate to obtain a new draft. Every draft requires human approval before sending; approval controls and automatic sending are not implemented.
- No tax, freight, discounts or currency conversion is inferred.

## Precision and size

The exporter reserves four decimal places for quantity/unit price and two for line amounts/subtotals within a 15-digit numeric budget. Line amounts and currency totals must be at most **9,999,999,999,999.99**. Larger values return an explicit error rather than silently losing cents. Both individual amounts and sums are checked. The existing JSON/CSV engine retains its wider Decimal range when XLSX is not requested.

The 500-item limit remains. A cell longer than 32,767 characters is rejected rather than truncated. Very long accepted text remains in the cell but may require the formula bar to read in full; row height is limited by Excel. Use a new output directory for each input set. An XLSX validation error occurs before output files are written; an operating-system write failure is not a transactional multi-file rollback.

## Verification

Install `requirements-test.txt`, then run `python -m unittest -v`. The 47 tests include 16 new checks that read actual XLSX files using the independent openpyxl reader. They cover the real PDF-to-XLSX path, actual loopback HTTP delivery, half-cent rounding, zero prices, multiple currencies, retained review rows, leading-zero codes, Chinese/Unicode text, precision overflow, long cells, 500 rows and legacy CLI/HTTP behavior. Generated packages are checked for readable files, literal cells and absence of external links or macros.

The exported sample is also imported and rendered with the bundled spreadsheet tool for visual review. Native Microsoft Excel has not been used. A separate [n8n integration check](n8n/README.md) executed seven cases in n8n 2.38.7, including byte-for-byte comparison between the endpoint's workbook and n8n's binary output. The previous separately authored formula-based demonstration used Codex's spreadsheet runtime; it is distinct from this portable values-only exporter and is not required to run it.

API references: [XlsxWriter worksheet methods](https://xlsxwriter.readthedocs.io/worksheet.html) and [workbook options](https://xlsxwriter.readthedocs.io/workbook.html).
