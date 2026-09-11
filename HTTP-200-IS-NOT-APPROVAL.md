# HTTP 200 can hide an unfinished quote

*Menwo · September 12, 2026 · A reproducible software experiment*

The most misleading number in this example is **USD 32.50**. The arithmetic is correct. Two requested lines match a catalogue. Four other lines need a decision. Put that number in a field called `total`, and the next step in an automation can turn a partial calculation into a customer-facing quote.

I prefer an interface that makes the unfinished work explicit. Here is the relevant part of the response from a small RFQ processor:

```json
{
  "status": "REVIEW_REQUIRED",
  "review_count": 4,
  "matched_subtotals_by_currency": {"USD": "32.50"},
  "complete_totals_by_currency": null
}
```

That response came back over an actual loopback HTTP connection with status **200**. The request succeeded: it produced a reviewable result. The commercial decision is still unresolved.

## Six lines, two different questions

An RFQ is a request for quotation. This demo reads a deliberately narrow text layout and matches it against a supplied price catalogue. It does not infer arbitrary PDF layouts or negotiate substitutions.

The synthetic request contains these six rows:

| Requested item | Result | Why |
| --- | --- | --- |
| Two MCB-16 circuit breakers | USD 17.50 | Code, description and unit match |
| 12.5 metres of CABLE-25 | USD 15.00 | Code, description and unit match |
| UNKNOWN-9 | Review | No catalogue entry |
| Three boxes of MCB-32 | Review | Catalogue price is per item, not per box |
| Zero RELAY-12 units | Review | Quantity must be positive |
| One CONTACT-1 | Review | Two catalogue entries share the code |

The easy question is “what do the matched lines cost?” The difficult one is “can this request become a complete quote?” Those questions deserve separate fields.

The row-level result keeps unresolved rows and their reasons. Their quoted price and line total remain blank. The summary preserves the useful subtotal while withholding the complete total. A workflow can route the document to review without losing the work already done.

There is a tradeoff here. This deliberately conservative policy flags inputs that a knowledgeable buyer might resolve immediately. A box could contain ten units; a duplicate line could be intentional. The software has no approved rule establishing either fact, so it records the conflict. Adding a conversion table would be a reasonable extension. Guessing the conversion would change the meaning of the quote.

## The duplicate that still fails when both prices agree

The catalogue contains CONTACT-1 twice, once at USD 18 and once at USD 19. I changed the second price to USD 18 and repeated the request. It still required review.

That behavior follows directly from `prepare_quote`: it gathers a list of candidates per code, then requires exactly one candidate. It does not choose the first row or compare the prices and collapse a tie.

I would keep that rule until the source system has an explicit way to identify the authoritative record. Equal prices do not establish which duplicate record is current. If the business does permit duplicates, that is a data-contract decision worth naming and testing. It should not appear accidentally because a dictionary assignment overwrote an earlier row.

## Transport success, resolved draft, approved quote

I exercised six cases against the existing HTTP adapter, without changing its implementation:

| Case | HTTP | Document state | Complete total |
| --- | --- | --- | --- |
| Full six-line request | 200 | `REVIEW_REQUIRED` | `null` |
| Only the two matching rows | 200 | `DRAFT_FOR_APPROVAL` | USD 32.50 |
| Per-box request against per-item price | 200 | `REVIEW_REQUIRED` | `null` |
| Duplicate code, different prices | 200 | `REVIEW_REQUIRED` | `null` |
| Duplicate code, same price | 200 | `REVIEW_REQUIRED` | `null` |
| Missing the required item block | 422 | No quote result | Not present |

The important transition is from review required to **draft for approval**. Even the two-row happy path does not claim the quote has been approved.

A downstream integration therefore needs two distinct decisions. First, inspect the document state: unresolved rows go to review; a resolved draft can enter the approval process. Second, require an actual approval before anything is sent to a customer. This demo has no approval store and sends no email, so it cannot supply the second decision.

Checking only HTTP success would lose both distinctions. Checking `review_count == 0` would still skip approval. Renaming that check `is_safe` would make the problem harder to notice.

## What the test does not establish

The reproducible result is small: six synthetic requests, six expected outcomes, Python 3.12.14, using the existing loopback server. It is evidence for this particular contract. It is not a production reliability measurement or an executed n8n integration.

There are also limits inside the contract. The processor requires a non-empty `price_version`, but it does not authenticate that version against an approval system. A caller supplies the catalogue. An internally consistent catalogue can still be commercially wrong. Source hashes help identify the files used; they do not establish who approved them.

Before connecting this to real purchasing, I would establish who controls the catalogue, how revisions become authoritative, and where approval is recorded. That work is more valuable than polishing a grand-total box while unresolved rows disappear behind it.

The rule I want a reviewer to check is concrete: **a subtotal must never silently become a complete quote**. The status names, missing complete total, retained problem rows and downstream approval step all help preserve that rule.

## Reproduce the result

The implementation examined is pinned to [commit 65e58b9](https://github.com/menwo535-jpg/rfq-quote-pilot/tree/65e58b950951eba7e434d0f90083b99d4645c3f7). The published `quote.py` and the local file used for this experiment had the same SHA-256 digest.

Download [quote.py](https://raw.githubusercontent.com/menwo535-jpg/rfq-quote-pilot/65e58b950951eba7e434d0f90083b99d4645c3f7/quote.py) and [local_api.py](https://raw.githubusercontent.com/menwo535-jpg/rfq-quote-pilot/65e58b950951eba7e434d0f90083b99d4645c3f7/local_api.py). Save the script below as `reproduce.py` beside them, then run `python reproduce.py` with Python 3.10 or later. These TXT-only cases use the standard library. The script binds an ephemeral loopback port, uses a temporary random token, checks each expected result, writes `observed-results.json`, and stops the server.

The six checks must finish successfully before the script writes its result file. The output includes both states and review reasons, so the result can be inspected rather than inferred from a green test count.

<details>
<summary>Executable reproduction script</summary>

```python
"""Reproduce article claims against the existing RFQ demo over loopback HTTP."""
import http.client
import json
from pathlib import Path
import secrets
import sys
import threading

ROOT = Path(__file__).resolve().parent
if not (ROOT / 'quote.py').exists():
    ROOT = ROOT.parent / 'rfq-pilot'
sys.path.insert(0, str(ROOT))
from local_api import create_server

token = secrets.token_hex(24)
server = create_server(token, 0)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
catalogue = '''code,description,unit,unit_price,currency,price_version
MCB-16,Circuit breaker 16A,EA,8.75,USD,DEMO-2026-09-v1
CABLE-25,Cable 2.5 mm2,M,1.20,USD,DEMO-2026-09-v1
MCB-32,Circuit breaker 32A,EA,12.00,USD,DEMO-2026-09-v1
RELAY-12,Relay 12V,EA,4.30,USD,DEMO-2026-09-v1
CONTACT-1,Contactor,EA,18.00,USD,DEMO-2026-09-v1
CONTACT-1,Contactor,EA,19.00,USD,DEMO-2026-09-v1
'''
sample = '''ITEMS
MCB-16|Circuit breaker 16A|2|EA
CABLE-25|Cable 2.5 mm2|12.5|M
UNKNOWN-9|Unlisted part|1|EA
MCB-32|Circuit breaker 32A|3|BOX
RELAY-12|Relay 12V|0|EA
CONTACT-1|Contactor|1|EA
END ITEMS'''
cases = [
    ('six-line fixture', sample, catalogue, 200, 'REVIEW_REQUIRED', 4, {'USD': '32.50'}, None),
    ('two resolved rows', 'ITEMS\nMCB-16|Circuit breaker 16A|2|EA\nCABLE-25|Cable 2.5 mm2|12.5|M\nEND ITEMS', catalogue, 200, 'DRAFT_FOR_APPROVAL', 0, {'USD': '32.50'}, {'USD': '32.50'}),
    ('unit conflict', 'ITEMS\nMCB-32|Circuit breaker 32A|3|BOX\nEND ITEMS', catalogue, 200, 'REVIEW_REQUIRED', 1, {}, None),
    ('duplicate catalogue', 'ITEMS\nCONTACT-1|Contactor|1|EA\nEND ITEMS', catalogue, 200, 'REVIEW_REQUIRED', 1, {}, None),
    ('same-price duplicate', 'ITEMS\nCONTACT-1|Contactor|1|EA\nEND ITEMS', catalogue.replace('CONTACT-1,Contactor,EA,19.00', 'CONTACT-1,Contactor,EA,18.00'), 200, 'REVIEW_REQUIRED', 1, {}, None),
    ('no item block', 'MCB-16|Circuit breaker 16A|2|EA', catalogue, 422, None, None, None, None),
]
results = []
try:
    for name, rfq, cat, expected_http, expected_state, expected_reviews, expected_partial, expected_complete in cases:
        body = json.dumps({'rfq': {'format': 'txt', 'content': rfq}, 'catalogue_csv': cat}).encode()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
        try:
            connection.request('POST', '/quote', body=body, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
            response = connection.getresponse()
            result = json.loads(response.read())
            assert response.status == expected_http, (name, response.status)
            entry = {'case': name, 'http_status': response.status}
            if expected_http == 200:
                quote = result['quote']
                for key, expected in [('status', expected_state), ('review_count', expected_reviews), ('matched_subtotals_by_currency', expected_partial), ('complete_totals_by_currency', expected_complete)]:
                    assert quote[key] == expected, (name, key, quote[key])
                    entry[key] = quote[key]
                for row in quote['rows']:
                    if row['status'] == 'REVIEW':
                        assert row['unit_price'] == '' and row['line_total'] == '', (name, row)
                entry['review_reasons'] = [row['reason'] for row in quote['rows'] if row['status'] == 'REVIEW']
            else:
                entry['error'] = result['error']
            results.append(entry)
        finally:
            connection.close()
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive(), 'local server did not stop'

output = {'python': sys.version.split()[0], 'transport': 'actual loopback HTTP', 'cases_passed': len(results), 'server_stopped': True, 'results': results}
Path(__file__).with_name('observed-results.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
print(json.dumps(output, indent=2))

```

</details>

*Provenance: prepared with Codex, which performed implementation, source inspection, the local HTTP experiments and writing. All inputs are synthetic. No customer deployment, human-only authorship or independent human code review is claimed.*
