import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from quote import parse_pages, prepare_quote, read_catalogue, read_rfq, render_html, run, spreadsheet_text

ROOT = Path(__file__).parent


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(source='p1:line2', code='A', description='Cable', quantity='2.5', unit='M')
        self.product = dict(code='A', description='Cable', unit='M', unit_price='1.23', currency='USD', price_version='v1')

    def quote(self, **changes):
        return prepare_quote([dict(self.row, **changes)], [self.product])

    def test_decimal_rounding_and_draft(self):
        result = self.quote()
        self.assertEqual(result['rows'][0]['line_total'], '3.08')
        self.assertEqual(result['status'], 'DRAFT_FOR_APPROVAL')

    def test_unknown_code_withholds_complete_total(self):
        result = self.quote(code='B')
        self.assertIsNone(result['complete_totals_by_currency'])
        self.assertEqual(result['rows'][0]['unit_price'], '')

    def test_codes_are_case_sensitive(self):
        self.assertEqual(self.quote(code='a')['review_count'], 1)

    def test_units_cannot_be_converted_implicitly(self):
        self.assertIn('unit mismatch', self.quote(unit='BOX')['rows'][0]['reason'])

    def test_description_change_needs_review(self):
        self.assertEqual(self.quote(description='Different cable')['review_count'], 1)

    def test_invalid_quantities(self):
        for value in ['0', '-1', 'NaN', 'Infinity', '1e3', '1,5', '', '1000000000']:
            with self.subTest(value=value):
                self.assertEqual(self.quote(quantity=value)['review_count'], 1)

    def test_invalid_prices(self):
        for value in ['NaN', 'Infinity', '-2', '1e2', '']:
            with self.subTest(value=value):
                self.product['unit_price'] = value
                self.assertEqual(self.quote()['review_count'], 1)

    def test_zero_price_allowed_when_approved(self):
        self.product['unit_price'] = '0'
        self.assertEqual(self.quote()['rows'][0]['line_total'], '0.00')

    def test_ambiguous_catalogue(self):
        result = prepare_quote([self.row], [self.product, copy.deepcopy(self.product)])
        self.assertIn('duplicate catalogue', result['rows'][0]['reason'])

    def test_repeated_request_rows_both_reviewed(self):
        result = prepare_quote([self.row, copy.deepcopy(self.row)], [self.product])
        self.assertEqual(result['review_count'], 2)
        self.assertEqual(len(result['rows']), 2)

    def test_missing_price_version(self):
        self.product['price_version'] = ''
        self.assertEqual(self.quote()['review_count'], 1)

    def test_no_mixed_currency_total(self):
        other = dict(self.product, code='B', currency='EUR')
        result = prepare_quote([self.row, dict(self.row, code='B')], [self.product, other])
        self.assertEqual(result['complete_totals_by_currency'], {'EUR': '3.08', 'USD': '3.08'})

    def test_unsupported_currency(self):
        self.product['currency'] = 'JPY'
        self.assertEqual(self.quote()['review_count'], 1)

    def test_bad_rows_are_preserved(self):
        rows = parse_pages(['ITEMS\nmalformed input\nEND ITEMS'])
        self.assertEqual(len(rows), 1)
        self.assertIn('expected code', prepare_quote(rows, [self.product])['rows'][0]['reason'])

    def test_layout_and_empty_pages_rejected(self):
        for pages in [[''], ['ITEMS\nA|Cable|1|M'], ['ITEMS\nEND ITEMS'], ['no markers']]:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                parse_pages(pages)

    def test_csv_formula_text_is_inert(self):
        for text in ['=1+1', '+SUM(A1)', '-cmd', '@SUM(A1)', '  =1', '\tformula']:
            self.assertTrue(spreadsheet_text(text).startswith("'"))
        self.assertEqual(spreadsheet_text('00123'), '00123')

    def test_html_escaping(self):
        markup = render_html(self.quote(description='<script>alert(1)</script>'))
        self.assertNotIn('<script>', markup)
        self.assertIn('&lt;script&gt;', markup)

    def test_real_pdf_extract_matches_text_fixture(self):
        pdf = read_rfq(ROOT / 'samples/rfq.pdf')
        txt = read_rfq(ROOT / 'samples/rfq.txt')
        fields = ['code', 'description', 'quantity', 'unit']
        self.assertEqual([{k: r[k] for k in fields} for r in pdf], [{k: r[k] for k in fields} for r in txt])

    def test_complete_cli_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run(ROOT / 'samples/rfq.pdf', ROOT / 'samples/catalogue.csv', Path(folder))
            self.assertEqual(result['review_count'], 4)
            self.assertEqual(result['matched_subtotals_by_currency'], {'USD': '32.50'})
            saved = json.loads((Path(folder) / 'quote-result.json').read_text())
            self.assertEqual(len(saved['sources']['rfq']['sha256']), 64)
            with (Path(folder) / 'quote-draft.csv').open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 6)


if __name__ == '__main__':
    unittest.main()
