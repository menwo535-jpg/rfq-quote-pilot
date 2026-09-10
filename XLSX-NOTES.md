# Excel quotation demonstration

`quote-draft.xlsx` contains the six synthetic RFQ lines from the existing Python sample. Four lines require review. Matched lines have a USD 32.50 subtotal; complete quotation totals are blank while any line requires review.

- Product codes are stored as text, with quantities and money stored as numeric cells.
- Line amounts use rounded quantity-times-approved-price formulas. Subtotals are separated by currency and restricted to matched draft lines.
- Review rows have no quoted price or amount. The reason and original source-row reference are visible. Table filters help examine the exceptions.
- The draft remains subject to human approval. Correct the original RFQ/catalogue and regenerate to change matching. Editing workbook cells does not rerun catalogue validation and must not be used to approve substitutions.
- The sample excludes tax, freight, discounts and exchange conversion.

## Validation and runtime

The workbook was recalculated with the bundled spreadsheet engine. Its row count, review count, individual line amounts, currency subtotals and withheld complete totals were checked against the Python JSON output. A temporary quantity edit recalculated the line amount and was restored before export. Five boundary checks covered half-cent rounding and leading-zero codes, approved zero prices, currency separation, all-review input with formula-like text and an oversized invalid quantity, and rejection of amounts exceeding the XLSX precision limit. The saved OOXML package retained formulas, numeric quantities, text codes, blank review prices and a filterable table, with no external-link parts. Formula-error scanning and a rendered visual review were performed. Native Microsoft Excel has not been opened for verification.

The Python package remains portable and unchanged. This XLSX was authored separately with `@oai/artifact-tool` supplied by Codex. The authoring source is `build-quote-xlsx.mjs`; it requires that bundled runtime and is **not** a standalone Python XLSX converter. A customer-installable Excel/n8n exporter remains a separately scoped implementation after confirming the customer's environment.

This is a software demonstration and contains no customer records, accepted quote or payment evidence.
