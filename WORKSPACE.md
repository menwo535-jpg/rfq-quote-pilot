# Draftdesk: a working local RFQ interface

Draftdesk connects a browser interface to the existing Python processor and SQLite store. Load a real PDF, inspect unresolved rows, save corrected input as a new revision, reopen drafts and download the displayed version's CSV or Excel. This is a self-built portfolio sample, not an assigned client project or evidence of paid work.

## Run

Install `requirements.txt`, set the private `RFQ_API_TOKEN` described in [HTTP-INTEGRATION.md](HTTP-INTEGRATION.md), and run:

```sh
python local_api.py --port 8765 --database drafts.sqlite3
```

Open `http://127.0.0.1:8765/` and enter the token. Keep the terminal open; Ctrl+C stops it. The interface currently uses Chinese labels. The static page contains no token or customer data. The token lives only in the open page's memory, so reloading requires reconnecting. Keep the database private. No paid service or cloud account is required.

## Complete workflow

1. **载入演示 PDF** loads the actual synthetic PDF and CSV. **生成并保存草稿** sends them to Python: six rows, four unresolved, USD 32.50 matched-lines subtotal. A complete quotation total is withheld.
2. **只看待复核** filters unresolved rows. Missing products, prices and pack conversions are never guessed.
3. Edit the complete source text/catalogue or select replacement PDF/TXT and CSV files. Typing text replaces the loaded PDF. **保存为新修订** retains earlier snapshots.
4. **修订历史** shows old snapshots. Saving from an old version is disabled until the latest version is read. Downloads use the displayed version, including unresolved rows.
5. Reload, reconnect and select the saved draft on the left. To revise a reopened draft, supply the original files again; raw PDFs are deliberately not retained in SQLite.

The new authenticated `GET /jobs` route returns up to 50 recent summaries and `has_more`, without large artifacts or original input. Older records remain accessible through the ID routes in [PERSISTENT-JOBS.md](PERSISTENT-JOBS.md). UI pagination/search is outside this demo.

## Retries and conflicting edits

Before sending, the browser keeps the exact body and idempotency key in memory. A timeout, lost response or server error retains that request and locks editing. **重试同一请求** resends the original request with its original key. There is no automatic retry loop. Keep the page open until the result is confirmed. Closing or refreshing loses the pending request; inspect saved drafts before starting another import. A browser leave-page confirmation is requested for pending writes, but is not a durability guarantee.

Validation errors unlock correction. A stale-version response disables saving until the latest result is read. The interface does not silently increment the version or overwrite another edit. If saving succeeded but sidebar refresh failed, the page continues to report the successful save.

## Verified September 13, 2026

- **70 Python tests passed**: 66 existing checks plus four actual HTTP/list checks, including current revision summaries, the 50-record limit and static assets without server tokens.
- **4 Node client tests passed against a real Python HTTP server**: discarded response after an actual database commit; exact replay; competing revisions; CSV validation; temporary server failure. These are four tests, some covering multiple related assertions.
- In Chromium, connected, loaded the real bundled PDF, saved version 1 and filtered its four unresolved rows. Corrected synthetic input produced version 2: five matched rows and USD 90.80 draft total. Version 1 still showed USD 32.50 and could not overwrite version 2.
- Both Excel versions were downloaded through the actual interface. Their bytes matched the corresponding database artifacts exactly, and the independent openpyxl reader opened both `Quote` and `Sources` sheets.
- Invalid CSV was rejected without creating a third revision. Reloading, reconnecting and selecting the saved draft recovered the stored result and both versions.
- The first browser run exposed a native `fetch` receiver-binding issue that Node did not catch. An explicit wrapper fixed it; the browser workflow and all four client tests subsequently passed.

Reproduce automated checks:

```sh
python -m pip install -r requirements-test.txt
python -m unittest -v
node --test test_ui_client.mjs
```

Node 24 was used. Set `RFQ_TEST_PYTHON` to the Python executable if it is not on PATH. The Node test starts/stops only its own temporary server and removes only its own synthetic test directory.

## Limits

Local synchronous service only: no production deployment, multi-user permissions, OCR, ERP, automatic approval or external sending. A fully matched quote still requires human approval. Responsive CSS is included; real mobile devices, other browser engines and operating-system file-picker flows have not been certified. Browser validation used the built-in PDF sample and text fields. The previous seven-case n8n evidence remains for `/quote`, not this UI or `/jobs`.
