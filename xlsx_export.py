"""Portable XLSX snapshots of quote.py results. No Codex runtime required."""
from __future__ import annotations

import io
import math
import re
from decimal import Decimal, InvalidOperation

# Numeric exports reserve the requested decimal places within Excel's
# 15-digit precision. The JSON/CSV engine supports larger exact amounts.
MAX_SCALED_NUMBER = Decimal('999999999999999')
DETAIL_HEADER_ROW = 10  # Zero based. Data starts at Excel row 12.
COLUMNS = [
    ('source', 'Source row', 15),
    ('code', 'Product code', 19),
    ('description', 'Requested description', 34),
    ('quantity', 'Quantity', 15),
    ('unit', 'Unit', 10),
    ('status', 'Match status', 24),
    ('reason', 'Review reason', 47),
    ('unit_price', 'Approved unit price', 19),
    ('currency', 'Currency', 12),
    ('line_total', 'Line amount', 23),
    ('price_version', 'Price-list version', 22),
]


def _number(value, places, label):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'invalid XLSX {label}') from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f'invalid XLSX {label}')
    scaled = number * (10 ** places)
    if scaled > MAX_SCALED_NUMBER or scaled != scaled.to_integral_value():
        raise ValueError(f'{label} exceeds XLSX precision limit; use JSON/CSV for exact values')
    return float(number)


def _text(value, label):
    text = str(value)
    if len(text) > 32767:
        raise ValueError(f'{label} exceeds the XLSX 32767-character cell limit')
    return text


def render_xlsx(quote):
    """Return a values-only workbook from a result produced by prepare_quote/run.

    Python Decimal owns matching and rounding. Excel is a review snapshot;
    edits do not recalculate, approve or rerun catalogue matching.
    """
    import xlsxwriter

    if not isinstance(quote.get('rows'), list) or not 1 <= len(quote['rows']) <= 500:
        raise ValueError('XLSX requires 1 to 500 quote rows')
    data = []
    for row in quote['rows']:
        if row['status'] not in ('REVIEW', 'MATCHED_DRAFT'):
            raise ValueError('unknown quote row status')
        matched = row['status'] == 'MATCHED_DRAFT'
        if not matched and (row['unit_price'] or row['line_total']):
            raise ValueError('review rows must not carry quoted prices')
        cells = []
        for key, label, _ in COLUMNS:
            value = row.get(key, '')
            if key in ('unit_price', 'line_total'):
                value = _number(value, 4 if key == 'unit_price' else 2, label) if matched else None
            elif key == 'quantity' and re.fullmatch(r'\d{1,9}(?:\.\d{1,4})?', str(value)):
                value = _number(value, 4, label)
            else:
                value = _text(value, label)
            cells.append(value)
        data.append(cells)

    subtotals = quote['matched_subtotals_by_currency']
    complete = quote['complete_totals_by_currency']
    currencies = sorted(subtotals)
    if any(c not in ('USD', 'EUR', 'GBP', 'CNY') for c in currencies):
        raise ValueError('unsupported XLSX currency')
    totals = [
        (currency, _number(subtotals[currency], 2, f'{currency} subtotal'),
         None if complete is None else _number(complete[currency], 2, f'{currency} complete total'))
        for currency in currencies
    ]
    sources = [(name, _text(source['file'], 'source filename'),
                _text(source['sha256'], 'source digest'))
               for name, source in quote.get('sources', {}).items()]
    stream = io.BytesIO()
    with xlsxwriter.Workbook(stream, {
        'in_memory': True, 'strings_to_formulas': False,
        'strings_to_urls': False, 'strings_to_numbers': False,
    }) as workbook:
        workbook.set_properties({'title': 'RFQ quotation draft', 'author': '',
                                 'comments': 'Generated from supplied RFQ and catalogue. Draft snapshot.'})
        base = {'font_name': 'Arial', 'font_size': 10, 'font_color': '#183047', 'valign': 'vcenter'}
        body = workbook.add_format(base)
        note = workbook.add_format(dict(base, italic=True, font_color='#506579'))
        heading = workbook.add_format(dict(base, font_size=16, bold=True))
        header = workbook.add_format(dict(base, bold=True, font_color='#FFFFFF',
                                         bg_color='#193C56', text_wrap=True, align='center'))
        bold = workbook.add_format(dict(base, bold=True))
        money = workbook.add_format(dict(base, num_format='#,##0.00'))
        row_formats = {}
        for review in (False, True):
            fmt = dict(base, text_wrap=True)
            if review:
                fmt['bg_color'] = '#FFF3D9'
            row_formats[review] = {
                'text': workbook.add_format(dict(fmt, num_format='@', indent=1)),
                'number': workbook.add_format(dict(fmt, num_format='#,##0.0###')),
                'price': workbook.add_format(dict(fmt, num_format='#,##0.00##')),
                'money': workbook.add_format(dict(fmt, num_format='#,##0.00')),
            }

        sheet = workbook.add_worksheet('Quote')
        sheet.hide_gridlines(2)
        sheet.set_tab_color('#193C56')
        sheet.set_default_row(22)
        for col, (_, _, width) in enumerate(COLUMNS):
            sheet.set_column(col, col, width, body)
        sheet.write_string('A2', 'RFQ quotation draft', heading)
        sheet.set_row(1, 29)
        sheet.write_string('A3', 'Snapshot from supplied files. Correct the inputs and regenerate to change the quote.', note)
        sheet.write_string('A5', 'Draft status', bold)
        sheet.write_string('B5', quote['status'], bold)
        sheet.write_string('A6', 'Requested lines', body)
        sheet.write_number('B6', len(data), body)
        sheet.write_string('A7', 'Needs review', body)
        sheet.write_number('B7', quote['review_count'], body)
        sheet.write_string('E5', 'Currency', header)
        sheet.write_string('F5', 'Matched subtotal', header)
        sheet.write_string('G5', 'Complete total', header)
        sheet.set_row(4, 30)
        for offset, (currency, subtotal, total) in enumerate(totals, 5):
            sheet.write_string(offset, 4, currency, body)
            sheet.write_number(offset, 5, subtotal, money)
            if total is not None:
                sheet.write_number(offset, 6, total, money)
        if not totals:
            sheet.write_string('F6', 'No priced lines', body)
        sheet.write_string('I5', 'Human approval required before sending.', note)
        sheet.write_string('I6', 'Complete totals stay blank while any line needs review.', note)
        sheet.write_string('A10', 'No tax, freight, discounts or currency conversion. Amber rows need review.', note)
        for col, (_, label, _) in enumerate(COLUMNS):
            sheet.write_string(DETAIL_HEADER_ROW, col, label, header)
        sheet.set_row(DETAIL_HEADER_ROW, 34)
        for i, cells in enumerate(data, DETAIL_HEADER_ROW + 1):
            review = cells[5] == 'REVIEW'
            formats = row_formats[review]
            line_count = 1
            for col, value in enumerate(cells):
                if value is None or value == '':
                    sheet.write_blank(i, col, None, formats['text'])
                elif isinstance(value, float):
                    style = 'money' if col == 9 else 'price' if col == 7 else 'number'
                    sheet.write_number(i, col, value, formats[style])
                else:
                    sheet.write_string(i, col, value, formats['text'])
                    # Wrap long descriptions without hiding the original text.
                    width = COLUMNS[col][2]
                    line_count = max(line_count, sum(max(1, math.ceil(len(part) / (width * .85)))
                                                    for part in value.split('\n')))
            sheet.set_row(i, min(409, max(28, line_count * 15 + 8)))
        end = DETAIL_HEADER_ROW + len(data)
        sheet.autofilter(DETAIL_HEADER_ROW, 0, end, len(COLUMNS) - 1)
        sheet.freeze_panes(DETAIL_HEADER_ROW + 1, 2)
        sheet.set_landscape()
        sheet.set_paper(8)  # A3 for the wide operational detail table.
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(DETAIL_HEADER_ROW)
        sheet.print_area(0, 0, end, len(COLUMNS) - 1)

        provenance = workbook.add_worksheet('Sources')
        provenance.hide_gridlines(2)
        provenance.set_default_row(24)
        provenance.set_column('A:A', 25, body)
        provenance.set_column('B:B', 36, body)
        provenance.set_column('C:C', 76, body)
        provenance.write_string('A2', 'Input references', heading)
        provenance.set_row(1, 29)
        provenance.write_row('A4', ['Input', 'Filename', 'SHA-256'], header)
        if sources:
            for index, source in enumerate(sources, 4):
                for column, text in enumerate(source):
                    provenance.write_string(index, column, text, body)
        else:
            provenance.write_string('A5', 'Source metadata not supplied', note)
    return stream.getvalue()
