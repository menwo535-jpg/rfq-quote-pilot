# Saved drafts, safe retries and correction history

The optional SQLite adapter saves RFQ results across service restarts. It lets an integration retry a request without creating another stored draft, and lets an operator submit corrected input without overwriting a newer revision. All matching still runs through the existing Python processor. This is local portfolio software, not an assigned client delivery.

## Start

Install `requirements.txt`, set the existing private `RFQ_API_TOKEN`, then run:

```sh
python local_api.py --port 8765 --database drafts.sqlite3
```

The parent directory of the database must already exist. Without `--database`, the original `POST /quote` works as before and job endpoints are disabled. With it, `/quote` still creates no database records. Stop the server with Ctrl+C. Use the same database file after restarting.

The database contains quotation rows and generated CSV/HTML/XLSX artifacts. Keep it private, outside published source or demo packages. It does not store bearer tokens or raw input PDFs; the request digest and source digests identify the input used. Records are not encrypted or cryptographically tamper-proof. Shut down the service before copying the SQLite file for a backup. Schema version 1 is supported; unknown versions are rejected.

## Routes

Every route uses the existing loopback Host check and bearer authentication. Write requests need `Content-Type: application/json` and one `Idempotency-Key` header: 1–128 ASCII letters/digits or `_ . : -`.

| Method and path | Request | Response |
| --- | --- | --- |
| `POST /jobs` | Same RFQ/catalogue object as `/quote` | 201 for a stored revision 1; 200 for an identical retry |
| `GET /jobs/{id}` | No body | Latest stored revision and complete result |
| `POST /jobs/{id}/revisions` | `expected_revision` and `request` | 201 for the next revision; 200 for a replay |
| `GET /jobs/{id}/revisions` | No body | Revision numbers, UTC timestamps and request hashes |
| `GET /jobs/{id}/revisions/{number}` | No body | Original result for that revision |

The create request can be generated with `make_request.py` as documented in [HTTP-INTEGRATION.md](HTTP-INTEGRATION.md). A successful saved response wraps the existing result:

```json
{
  "job": {
    "id": "<32-character job id>",
    "revision": 1,
    "created_at": "<UTC timestamp>",
    "updated_at": "<UTC timestamp>",
    "request_sha256": "<SHA-256>"
  },
  "result": {
    "quote": {"status": "REVIEW_REQUIRED", "review_count": 1},
    "artifacts": {"csv_utf8": "...", "review_html": "...", "xlsx_base64": "..."}
  }
}
```

This abbreviated example omits the ordinary quote rows and totals. XLSX is only included when requested. For existing n8n nodes consuming `/quote`, keep that endpoint unless you also adapt the response references to `result.quote` and `result.artifacts`. The published seven-case n8n workflow targets `/quote`; these new `/jobs` routes have real HTTP/database tests, not a new n8n execution claim.

To correct a stored job, retrieve its latest revision first and send the full corrected RFQ/catalogue with a new key:

```json
{
  "expected_revision": 1,
  "request": {
    "rfq": {"format": "txt", "content": "ITEMS\n0001|Cable|4|M\nEND ITEMS"},
    "catalogue_csv": "code,description,unit,unit_price,currency,price_version\n0001,Cable,M,1.23,USD,v1\n",
    "include_xlsx": true
  }
}
```

## Retry and conflict rules

- Save the same idempotency key with the same operation when retrying after a timeout or restart. JSON key ordering does not matter; omitted `include_xlsx` and explicit `false` are equivalent. Other input text, including whitespace, is significant. Revision retries must also retain the original `expected_revision`.
- Successful replies include `Idempotency-Replayed: false` or `true`. A replay returns the **original operation's snapshot**, even after later edits. Use `GET /jobs/{id}` to obtain the latest revision.
- Reusing a key with different input returns 409. Create keys are shared within one database; revision keys are scoped to one job. Use separate keys for genuinely distinct imports.
- Editing an outdated revision returns 409. Fetch the current result, review what changed, and make a new correction with a new key and the current revision. Do not blindly increment a stale version.
- Unknown jobs/revisions return 404. Invalid input returns 422 and consumes no key. A missing dependency or database failure returns 503. Other existing input limits/error codes still apply.
- Each write atomically commits the job pointer, snapshot and retry record. Concurrent successful retries retain one stored result; PDF processing may run twice before that commit. This is not a background queue or an exactly-once execution guarantee for external side effects.

No route approves a quote, sends email, reserves stock or changes an ERP. Corrected input still passes every original matching rule. `DRAFT_FOR_APPROVAL` remains a draft requiring the user's review. History records inputs/results and time, not a verified reviewer identity or a signed approval. The synchronous development server has not been tested as a public, multi-user production service. There is no retention/deletion UI or background job scheduler.

## Verification

```sh
python -m pip install -r requirements-test.txt
python -m unittest -v
```

On September 13, 2026, all **66 Python tests** passed: the prior 47 checks and 19 new persistence checks. The new checks cover real PDF/HTTP/XLSX storage, a terminated and restarted CLI process, replay without reprocessing, preserved correction history, stale edits, two simultaneous connections, validation failures, and transaction rollback with an injected database-write failure. They also confirm stored results require the existing local authorization and the stateless endpoint remains compatible.

The injected database error is a test trigger; it does not simulate a full disk, hardware power loss or filesystem corruption. The concurrency test uses separate SQLite connections in two threads. The process restart check terminates the test's own CLI process after a completed commit, then starts a new process on the same file.
