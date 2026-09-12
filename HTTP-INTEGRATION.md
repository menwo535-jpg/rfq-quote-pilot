# Local HTTP adapter for RFQ workflows

The Python demo has a **tested loopback HTTP endpoint**. It reuses `quote.py`; it does not duplicate the matching or money calculations in an automation platform. The input can be the documented text layout or its text-based PDF. The response contains the quote JSON, escaped CSV text, escaped HTML review page, and optional base64 XLSX.

This is a portfolio demonstration with synthetic fixtures. **An n8n workflow has not been imported or executed.** The endpoint now generates native XLSX with the public Python XlsxWriter package when `include_xlsx` is true. No API credits or hosted account are needed.

## Run on one computer

Python 3.10+ and the existing `requirements.txt` are sufficient. From the extracted package directory, install those requirements. Set `RFQ_API_TOKEN` to a randomly generated private value containing at least 24 ASCII letters/digits. For example, in PowerShell:

```powershell
$env:RFQ_API_TOKEN = python -c "import secrets; print(secrets.token_hex(24))"
python local_api.py --port 8765
```

The server listens on **127.0.0.1 only**. Keep the token private; it is not printed by the server. Stop with Ctrl+C. Do not expose this development server to the internet or use a tunnel to make it public. The HTTP server is synchronous, intended for small trusted local demonstrations, and has not been load-tested or reviewed for production hosting.

In a second terminal, build a request file (no token is stored in this file):

```sh
python make_request.py samples/rfq.pdf samples/catalogue.csv --out request.json --xlsx
```

Send the file to `http://127.0.0.1:8765/quote` using an HTTP client configured with:

- Method: POST.
- Authorization header: `Bearer ` followed by the same private `RFQ_API_TOKEN` value.
- Content-Type: `application/json`.
- Body: the contents of `request.json`.
- Request timeout: 30 seconds for the small supplied sample.

The total encoded JSON request must be at most 1,000,000 bytes, including PDF base64 expansion. The existing 20-page PDF and 500-item limits also apply. The endpoint accepts content, not filesystem paths or URLs. Temporary RFQ/catalogue/output files are removed when a request finishes normally; filesystem erasure is not guaranteed after a crash.

## Request and response

The required request fields are `rfq` and `catalogue_csv`, plus optional boolean `include_xlsx` (default false). `rfq` contains `format` (`txt` or `pdf_base64`) and string `content`. `catalogue_csv` contains the full approved CSV, including its header. Other fields are rejected. Example text request:

```json
{
  "rfq": {"format": "txt", "content": "ITEMS\nA|Cable|2.5|M\nEND ITEMS"},
  "catalogue_csv": "code,description,unit,unit_price,currency,price_version\nA,Cable,M,1.23,USD,v1\n",
  "include_xlsx": true
}
```

A successful HTTP 200 response contains:

- `quote.status`, `quote.rows`, `quote.review_count`, the per-currency subtotals and source digests.
- `artifacts.csv_utf8`: CSV text. Save as UTF-8; import product codes as Text when using Excel.
- `artifacts.review_html`: self-contained review page. Save as `.html`.
- `artifacts.xlsx_base64`: present only when requested. Decode the base64 to bytes and save as `.xlsx`; do not save the base64 text directly as a workbook. MIME type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

For a saved JSON response, the XLSX can be extracted locally with:

```python
import base64, json
from pathlib import Path
response = json.loads(Path('response.json').read_text(encoding='utf-8'))
Path('quote-draft.xlsx').write_bytes(base64.b64decode(response['artifacts']['xlsx_base64'], validate=True))
```

Missing or false `include_xlsx` retains the original response shape. A string such as `"true"`, a number or null returns 422. XLSX amounts/subtotals that exceed the documented precision limit also return 422; the original exact JSON/CSV route remains available by setting the flag false. See [XLSX notes](XLSX-NOTES.md). Output sizes increase with the XLSX payload; the 1 MB limit applies to the encoded request.

**HTTP 200 only means processing succeeded.** If `quote.status` is `REVIEW_REQUIRED`, the complete total remains null. Even `DRAFT_FOR_APPROVAL` is not permission to send a quote or collect payment. The supplied PDF gives six lines, four needing review, and a matched subtotal of USD 32.50. These are synthetic amounts.

Errors: 400 malformed JSON/request framing; 401 missing/incorrect token; 403 non-local Host; 404 unknown route; 405 unsupported method; 408 body timeout; 411 missing/invalid length; 413 size limit; 415 wrong content type; 422 validation/Excel precision error; 503 missing requested-format dependency; 500 parser/internal failure. No input content or token is written to access logs. Do not auto-retry invalid files indefinitely.

## n8n connection guide — not yet executed in n8n

These steps target an n8n process running **natively on the same computer**, with access to that computer's loopback interface. n8n Cloud and an ordinary separate Docker network cannot reach this URL. Those environments require separately scoped hosting/networking; changing the URL alone is insufficient.

1. Add a Manual Trigger and an HTTP Request node.
2. Set POST and the local `/quote` URL above.
3. Use Generic Credential Type → Header Auth. Configure the credential name `Authorization` and value `Bearer <your private token>`. Do not embed the token in exported workflow JSON.
4. Enable Send Body, choose JSON / Using JSON, and paste the synthetic `request.json`. Select a JSON response and a 30,000 ms timeout. Leave Never Error disabled.
5. Manually execute the small synthetic test. Inspect `quote.status`, review flags, separate subtotals and the returned CSV/HTML before connecting any later node.
6. Add a review step for every draft. No automatic email, ERP mutation, payment or approval is part of this demonstration.

The exact node labels depend on the installed n8n version. Source checked: [official HTTP Request documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest). This guide is a configuration recipe, not evidence of a completed n8n integration.

## Verification

```sh
python -m pip install -r requirements-test.txt
python -m unittest -v test_quote test_local_api test_xlsx_export
```

The HTTP tests create a server on a temporary loopback port, make real requests using the synthetic PDF/TXT/CSV files, and shut the server down. They cover the PDF result, retained review rows, CSV/HTML escaping, authentication, Host restrictions, route/method restrictions, malformed requests, size limits and input types. The additional XLSX tests decode the actual HTTP response and inspect the workbook with openpyxl. They also verify the optional flag and the original response behavior. These checks do not prove arbitrary customer PDF support or production readiness.
