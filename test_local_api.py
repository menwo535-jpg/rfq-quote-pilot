"""Real HTTP checks using an ephemeral loopback port and synthetic fixtures."""
import base64
import csv
import http.client
import io
import json
import threading
import unittest
from pathlib import Path

from local_api import create_server, MAX_REQUEST_BYTES

ROOT = Path(__file__).parent
TEST_TOKEN = 'localDemoTestingToken000000000000'


class LocalAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(TEST_TOKEN, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def payload(self, pdf=False):
        return {
            'rfq': {
                'format': 'pdf_base64' if pdf else 'txt',
                'content': base64.b64encode((ROOT / 'samples/rfq.pdf').read_bytes()).decode('ascii') if pdf else (ROOT / 'samples/rfq.txt').read_text(encoding='utf-8'),
            },
            'catalogue_csv': (ROOT / 'samples/catalogue.csv').read_text(encoding='utf-8'),
        }

    def request(self, payload=None, headers=None, method='POST', path='/quote', raw=None):
        outgoing = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TEST_TOKEN}
        outgoing.update(headers or {})
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            body = raw if raw is not None else json.dumps(self.payload() if payload is None else payload)
            conn.request(method, path, body=body, headers=outgoing)
            response = conn.getresponse()
            status, response_headers = response.status, dict(response.getheaders())
            result = json.loads(response.read())
            return status, result, response_headers
        finally:
            conn.close()

    def test_real_pdf_has_same_quote_and_outputs_as_text(self):
        status, pdf, headers = self.request(self.payload(pdf=True))
        self.assertEqual(status, 200)
        text = self.request()[1]
        for key in ('status', 'review_count', 'matched_subtotals_by_currency', 'complete_totals_by_currency'):
            self.assertEqual(pdf['quote'][key], text['quote'][key])
        self.assertEqual(pdf['quote']['review_count'], 4)
        self.assertEqual(pdf['quote']['matched_subtotals_by_currency'], {'USD': '32.50'})
        self.assertIsNone(pdf['quote']['complete_totals_by_currency'])
        self.assertEqual(len(list(csv.DictReader(io.StringIO(pdf['artifacts']['csv_utf8'])))), 6)
        self.assertIn('A complete quotation total is withheld', pdf['artifacts']['review_html'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(len(pdf['quote']['sources']['rfq']['sha256']), 64)
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_authentication_required(self):
        self.assertEqual(self.request(headers={'Authorization': ''})[0], 401)
        self.assertEqual(self.request(headers={'Authorization': 'Bearer wrong'})[0], 401)

    def test_host_must_be_loopback(self):
        self.assertEqual(self.request(headers={'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.server.server_address[0], '127.0.0.1')

    def test_route_and_methods_are_bounded(self):
        self.assertEqual(self.request(path='/../quote.py')[0], 404)
        self.assertEqual(self.request(method='GET')[0], 405)
        self.assertEqual(self.request(method='OPTIONS')[0], 405)

    def test_wrong_content_type(self):
        self.assertEqual(self.request(headers={'Content-Type': 'text/plain'})[0], 415)

    def test_invalid_json_and_utf8(self):
        for raw in (b'{', b'\xff'):
            self.assertEqual(self.request(raw=raw)[0], 400)

    def test_declared_size_is_rejected_before_body_read(self):
        self.assertEqual(self.request(headers={'Content-Length': str(MAX_REQUEST_BYTES + 1)}, raw=b'{}')[0], 413)
        self.assertEqual(self.request(headers={'Content-Length': '-1'}, raw=b'{}')[0], 411)
        self.assertEqual(self.request(headers={'Transfer-Encoding': 'chunked'}, raw=b'{}')[0], 400)

    def test_file_paths_urls_and_extra_fields_not_accepted(self):
        for payload in ({'rfq_path': 'quote.py'}, {'rfq': {'format': 'url', 'content': 'http://example.com'}, 'catalogue_csv': 'x'}, dict(self.payload(), output_path='outside')):
            self.assertEqual(self.request(payload)[0], 422)

    def test_wrong_schema_types_are_validation_errors(self):
        for payload in ([], 1, 'text', {'rfq': [], 'catalogue_csv': 7}, {'rfq': {'format': [], 'content': 1}, 'catalogue_csv': 'x'}):
            self.assertEqual(self.request(payload)[0], 422)

    def test_invalid_pdf_and_catalogue(self):
        payload = self.payload(pdf=True)
        for content in ('%%%', base64.b64encode(b'not a PDF').decode('ascii')):
            payload['rfq']['content'] = content
            self.assertEqual(self.request(payload)[0], 422)
        payload = self.payload()
        payload['catalogue_csv'] = 'wrong,headers\na,b\n'
        self.assertEqual(self.request(payload)[0], 422)

    def test_formula_and_markup_stay_inert_over_http(self):
        payload = self.payload()
        payload['rfq']['content'] = 'ITEMS\n=1+1|<script>bad</script>|1|EA\nEND ITEMS'
        status, result, _ = self.request(payload)
        self.assertEqual(status, 200)
        rows = list(csv.DictReader(io.StringIO(result['artifacts']['csv_utf8'])))
        self.assertEqual(rows[0]['code'], "'=1+1")
        self.assertEqual(rows[0]['unit_price'], '')
        self.assertNotIn('<script>', result['artifacts']['review_html'])

    def test_invalid_startup_token_is_rejected(self):
        for token in ('', 'short', 'spaces are not accepted ever', 'é' * 30):
            with self.assertRaises(ValueError):
                create_server(token, 0)


if __name__ == '__main__':
    unittest.main()
