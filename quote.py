"""Bounded RFQ extraction and approved-price matching. Python 3.10+."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

FIELDS = ['code', 'description', 'unit', 'unit_price', 'currency', 'price_version']
OUTPUT_FIELDS = ['source', 'code', 'description', 'quantity', 'unit', 'status',
                 'reason', 'unit_price', 'currency', 'line_total', 'price_version']


def decimal_value(value, kind):
    value = str(value).strip()
    if not re.fullmatch(r'\d{1,9}(?:\.\d{1,4})?', value):
        raise ValueError(f'invalid {kind}')
    result = Decimal(value)
    if kind == 'quantity' and result <= 0:
        raise ValueError('quantity must be positive')
    return result


def parse_pages(pages):
    """One documented layout; retain every unparseable row inside the item block."""
    rows, in_items, started, ended = [], False, False, False
    for page_no, text in enumerate(pages, 1):
        if not text.strip():
            raise ValueError(f'page {page_no} has no text; OCR is not supported')
        for line_no, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if line == 'ITEMS':
                if started:
                    raise ValueError('multiple ITEMS blocks are not supported')
                in_items = started = True
                continue
            if line == 'END ITEMS':
                if not in_items:
                    raise ValueError('unexpected END ITEMS')
                in_items, ended = False, True
                continue
            if not in_items or not line:
                continue
            parts = [p.strip() for p in line.split('|')]
            row = {'source': f'p{page_no}:line{line_no}', 'raw': raw}
            if len(parts) != 4:
                row.update(code='', description=raw, quantity='', unit='', parse_error='expected code | description | quantity | unit')
            else:
                row.update(zip(['code', 'description', 'quantity', 'unit'], parts))
            rows.append(row)
    if not started or not ended or not rows:
        raise ValueError('expected a non-empty ITEMS ... END ITEMS block')
    if len(rows) > 500:
        raise ValueError('pilot limit is 500 item rows')
    return rows


def read_rfq(path):
    if path.stat().st_size > 10_000_000:
        raise ValueError('pilot input limit is 10 MB')
    if path.suffix.lower() == '.txt':
        return parse_pages([path.read_text(encoding='utf-8-sig')])
    if path.suffix.lower() != '.pdf':
        raise ValueError('RFQ must be a text PDF or UTF-8 TXT file')
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        if len(pdf.pages) > 20:
            raise ValueError('pilot limit is 20 PDF pages')
        return parse_pages([page.extract_text() or '' for page in pdf.pages])


def read_catalogue(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError('catalogue headers must be: ' + ','.join(FIELDS))
        result = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('malformed catalogue CSV row')
            result.append({k: v.strip() for k, v in row.items()})
    if not result or len(result) > 50000:
        raise ValueError('catalogue must contain 1 to 50000 rows')
    return result


def prepare_quote(items, catalogue):
    by_code = defaultdict(list)
    for product in catalogue:
        by_code[product['code'].strip()].append(product)
    occurrences = Counter((r['code'], r['unit'].upper()) for r in items if r['code'])
    result, subtotals = [], defaultdict(lambda: Decimal('0.00'))
    for item in items:
        row = {key: item.get(key, '') for key in OUTPUT_FIELDS}
        problems = []
        qty, price, product = None, None, None
        if item.get('parse_error'):
            problems.append(item['parse_error'])
        if not item['code']:
            problems.append('missing product code')
        if not item['description']:
            problems.append('missing description')
        try:
            qty = decimal_value(item['quantity'], 'quantity')
        except ValueError as exc:
            problems.append(str(exc))
        if occurrences[(item['code'], item['unit'].upper())] > 1:
            problems.append('repeated RFQ code/unit; confirm each line')
        candidates = by_code[item['code']]
        if len(candidates) != 1:
            problems.append('unknown product code' if not candidates else 'duplicate catalogue code')
        else:
            product = candidates[0]
            if not item['unit'] or item['unit'].upper() != product['unit'].upper():
                problems.append('unit mismatch or missing unit')
            if ' '.join(item['description'].lower().split()) != ' '.join(product['description'].lower().split()):
                problems.append('description differs from catalogue')
            if product['currency'] not in ('USD', 'EUR', 'GBP', 'CNY'):
                problems.append('unsupported currency (pilot supports USD/EUR/GBP/CNY)')
            if not product['price_version']:
                problems.append('missing approved price-list version')
            try:
                price = decimal_value(product['unit_price'], 'price')
            except ValueError as exc:
                problems.append(str(exc))
        if problems:
            row.update(status='REVIEW', reason='; '.join(problems))
        else:
            amount = (qty * price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            row.update(status='MATCHED_DRAFT', reason='', unit_price=str(price),
                       currency=product['currency'], line_total=str(amount),
                       price_version=product['price_version'])
            subtotals[product['currency']] += amount
        result.append(row)
    reviews = sum(r['status'] == 'REVIEW' for r in result)
    return {'status': 'REVIEW_REQUIRED' if reviews else 'DRAFT_FOR_APPROVAL',
            'rows': result, 'review_count': reviews,
            'matched_subtotals_by_currency': {k: str(v) for k, v in sorted(subtotals.items())},
            'complete_totals_by_currency': None if reviews else {k: str(v) for k, v in sorted(subtotals.items())}}


def spreadsheet_text(value):
    # CSV can execute formulas when opened in spreadsheet software.
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def render_html(quote):
    esc = lambda x: html.escape(str(x))
    columns = ['source', 'code', 'description', 'quantity', 'unit', 'status', 'reason', 'line_total', 'currency']
    headings = ''.join(f'<th>{esc(x.replace("_", " ").title())}</th>' for x in columns)
    rows = ''.join('<tr class="' + ('review' if row['status'] == 'REVIEW' else 'matched') + '">' +
                   ''.join(f'<td>{esc(row.get(k, ""))}</td>' for k in columns) + '</tr>' for row in quote['rows'])
    subtotals = ', '.join(f'{esc(k)} {esc(v)}' for k, v in quote['matched_subtotals_by_currency'].items()) or 'None'
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RFQ review draft</title><style>body{{font:15px system-ui;background:#f3f5f8;color:#183047;margin:0;padding:32px}}main{{max-width:1400px;margin:auto}}h1{{font-size:34px;margin-bottom:8px}}.muted{{color:#506579}}.stats{{display:flex;gap:16px;margin:28px 0;flex-wrap:wrap}}.card{{background:white;padding:20px;border-radius:12px;min-width:200px}}strong{{display:block;font-size:26px;margin-top:8px}}.table{{overflow:auto;background:white;border-radius:12px}}table{{border-collapse:collapse;width:100%;text-align:left}}th,td{{padding:13px;border-bottom:1px solid #e0e6ed;vertical-align:top}}th{{background:#193c56;color:white}}.review{{background:#fff3d9}}td:nth-child(7){{min-width:210px}}footer{{margin-top:24px;color:#506579}}</style>
<main><p class="muted">MENWO / LOCAL SOFTWARE DEMONSTRATION</p><h1>Review the RFQ before quoting</h1><p>Draft only. Prices come from the supplied catalogue; substitutions require human approval.</p>
<div class="stats"><div class="card">Requested lines<strong>{len(quote['rows'])}</strong></div><div class="card">Lines requiring review<strong>{quote['review_count']}</strong></div><div class="card">Matched lines subtotal only<strong>{subtotals}</strong></div></div>
<p><b>{esc(quote['status'])}</b> {'A complete quotation total is withheld while any line needs review.' if quote['review_count'] else 'All rows matched. Human approval is still required before sending.'}</p>
<div class="table"><table><thead><tr>{headings}</tr></thead><tbody>{rows}</tbody></table></div><footer>Synthetic demonstration inputs. No taxes, freight, discounts, exchange-rate conversion or automatic sending. Row references identify extracted page and text line.</footer></main></html>'''


def run(rfq_path, catalogue_path, output, *, include_xlsx=False):
    quote = prepare_quote(read_rfq(rfq_path), read_catalogue(catalogue_path))
    quote['sources'] = {name: {'file': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                        for name, p in [('rfq', rfq_path), ('approved_catalogue', catalogue_path)]}
    xlsx = None
    if include_xlsx:
        from xlsx_export import render_xlsx
        # Validate and build before changing output files. XLSX has a smaller
        # numeric range than the Decimal-based JSON/CSV output.
        xlsx = render_xlsx(quote)
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'quote-draft.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows({k: spreadsheet_text(v) for k, v in row.items()} for row in quote['rows'])
    (output / 'quote-result.json').write_text(json.dumps(quote, indent=2, ensure_ascii=False), encoding='utf-8')
    (output / 'review.html').write_text(render_html(quote), encoding='utf-8')
    if xlsx is not None:
        (output / 'quote-draft.xlsx').write_bytes(xlsx)
    return quote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rfq', type=Path)
    parser.add_argument('catalogue', type=Path)
    parser.add_argument('--out', type=Path, default=Path('output'))
    parser.add_argument('--xlsx', action='store_true', help='also export a native Excel review snapshot')
    args = parser.parse_args()
    try:
        quote = run(args.rfq, args.catalogue, args.out, include_xlsx=args.xlsx)
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(1, f'Error: {exc}\n')
    print(json.dumps({k: v for k, v in quote.items() if k not in ('rows', 'sources')}))
    return 2 if quote['review_count'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
