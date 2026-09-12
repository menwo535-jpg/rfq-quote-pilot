"""Loopback-only RFQ integration demo. Not a production HTTP server."""
from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hmac
import json
import os
import re
import sqlite3
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from quote import run
from job_store import JobStore, JobConflict, JobNotFound

MAX_REQUEST_BYTES = 1_000_000


def build_response(payload):
    """Accept content only, never paths, URLs, output locations or commands."""
    required = {'rfq', 'catalogue_csv'}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - {'include_xlsx'}:
        raise ValueError('expected rfq, catalogue_csv and optional include_xlsx fields')
    include_xlsx = payload.get('include_xlsx', False)
    if not isinstance(include_xlsx, bool):
        raise ValueError('include_xlsx must be a boolean')
    rfq = payload['rfq']
    if not isinstance(rfq, dict) or set(rfq) != {'format', 'content'}:
        raise ValueError('rfq requires only format and content fields')
    if not isinstance(rfq['format'], str) or rfq['format'] not in ('txt', 'pdf_base64'):
        raise ValueError('rfq format must be txt or pdf_base64')
    if not isinstance(rfq['content'], str) or not rfq['content'].strip():
        raise ValueError('rfq content must be a non-empty string')
    catalogue = payload['catalogue_csv']
    if not isinstance(catalogue, str) or not catalogue.strip():
        raise ValueError('catalogue_csv must be a non-empty string')
    if len(rfq['content'].encode('utf-8')) + len(catalogue.encode('utf-8')) > MAX_REQUEST_BYTES:
        raise ValueError('content exceeds demo size limit')

    suffix = '.txt' if rfq['format'] == 'txt' else '.pdf'
    if suffix == '.pdf':
        try:
            content = base64.b64decode(rfq['content'], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('PDF content must be strict base64') from exc
        if not content.startswith(b'%PDF-'):
            raise ValueError('decoded content must be a PDF')
    else:
        content = rfq['content'].encode('utf-8')

    with tempfile.TemporaryDirectory(prefix='rfq-demo-') as directory:
        root = Path(directory)
        rfq_path = root / ('rfq' + suffix)
        catalogue_path = root / 'catalogue.csv'
        rfq_path.write_bytes(content)
        catalogue_path.write_text(catalogue, encoding='utf-8', newline='')
        result = run(rfq_path, catalogue_path, root / 'output', include_xlsx=include_xlsx)
        response = {
            'quote': result,
            'artifacts': {
                'csv_utf8': (root / 'output/quote-draft.csv').read_text(encoding='utf-8-sig'),
                'review_html': (root / 'output/review.html').read_text(encoding='utf-8'),
            },
        }
        if include_xlsx:
            response['artifacts']['xlsx_base64'] = base64.b64encode(
                (root / 'output/quote-draft.xlsx').read_bytes()).decode('ascii')
        return response


def create_server(token, port=8765, *, database=None):
    if not isinstance(token, str) or len(token) < 24 or not token.isascii() or not token.isalnum():
        raise ValueError('RFQ_API_TOKEN must contain at least 24 ASCII letters/digits')
    store = JobStore(database, build_response) if database is not None else None

    class Handler(BaseHTTPRequestHandler):
        server_version = 'RFQLocalDemo/1'
        sys_version = ''

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format, *args):
            # Do not put RFQ data, headers or request paths into console logs.
            pass

        def reply(self, status, value, *, replayed=None):
            data = json.dumps(value, ensure_ascii=True, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Connection', 'close')
            if replayed is not None:
                self.send_header('Idempotency-Replayed', str(replayed).lower())
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True

        def authorized(self):
            expected_hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            if len(self.headers.get_all('Host', [])) != 1 or self.headers.get('Host') not in expected_hosts:
                self.reply(403, {'error': 'local Host required'})
                return False
            auth = self.headers.get('Authorization', '')
            if len(self.headers.get_all('Authorization', [])) != 1 or not hmac.compare_digest(auth.encode('utf-8'), ('Bearer ' + token).encode('ascii')):
                self.reply(401, {'error': 'valid bearer token required'})
                return False
            return True

        def do_POST(self):
            if not self.authorized():
                return
            revision_route = re.fullmatch(r'/jobs/([a-f0-9]{32})/revisions', self.path)
            if self.path != '/quote' and not (store is not None and (self.path == '/jobs' or revision_route)):
                return self.reply(404, {'error': 'unknown endpoint'})
            if self.headers.get_content_type() != 'application/json':
                return self.reply(415, {'error': 'application/json required'})
            if self.headers.get('Transfer-Encoding'):
                return self.reply(400, {'error': 'chunked requests are not supported'})
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                return self.reply(411, {'error': 'one Content-Length is required'})
            if len(lengths[0]) > 9:
                return self.reply(413, {'error': 'request exceeds 1 MB limit'})
            length = int(lengths[0])
            if length < 1 or length > MAX_REQUEST_BYTES:
                return self.reply(413, {'error': 'request must contain 1 to 1000000 bytes'})
            try:
                raw = self.rfile.read(length)
            except TimeoutError:
                return self.reply(408, {'error': 'request body timed out'})
            if len(raw) != length:
                return self.reply(400, {'error': 'incomplete request body'})
            try:
                payload = json.loads(raw.decode('utf-8'))
            except (ValueError, UnicodeError):
                return self.reply(400, {'error': 'valid UTF-8 JSON required'})
            try:
                replayed = None
                if self.path == '/quote':
                    result = build_response(payload)
                    status = 200
                else:
                    keys = self.headers.get_all('Idempotency-Key', [])
                    if len(keys) != 1:
                        raise ValueError('one Idempotency-Key is required')
                    if revision_route:
                        if not isinstance(payload, dict) or set(payload) != {'expected_revision', 'request'}:
                            raise ValueError('revision requires expected_revision and request fields')
                        result, replayed = store.revise(revision_route[1], payload['request'], keys[0],
                                                       payload['expected_revision'])
                    else:
                        result, replayed = store.create(payload, keys[0])
                    status = 200 if replayed else 201
            except JobConflict as exc:
                return self.reply(409, {'error': str(exc)})
            except JobNotFound as exc:
                return self.reply(404, {'error': str(exc)})
            except sqlite3.Error:
                return self.reply(503, {'error': 'local database unavailable; retry later with the same idempotency key'})
            except ImportError:
                return self.reply(503, {'error': 'requested format support unavailable; install requirements.txt'})
            except (ValueError, UnicodeError, csv.Error) as exc:
                return self.reply(422, {'error': str(exc)})
            except Exception:
                # Parser/internal details can include local paths; keep them private.
                return self.reply(500, {'error': 'unable to process this input; inspect it locally'})
            self.reply(status, result, replayed=replayed)

        def do_GET(self):
            if store is None or not self.path.startswith('/jobs/'):
                return self.reply(405, {'error': 'use POST /quote, or enable --database for jobs'})
            if not self.authorized():
                return
            route = re.fullmatch(r'/jobs/([a-f0-9]{32})(?:/(revisions)(?:/([1-9][0-9]{0,8}))?)?', self.path)
            if route is None:
                return self.reply(404, {'error': 'unknown endpoint'})
            try:
                if route[2] and not route[3]:
                    result = store.history(route[1])
                else:
                    result = store.get(route[1], int(route[3]) if route[3] else None)
                self.reply(200, result)
            except JobNotFound as exc:
                self.reply(404, {'error': str(exc)})
            except sqlite3.Error:
                self.reply(503, {'error': 'local database unavailable'})
            except Exception:
                self.reply(500, {'error': 'unable to read stored result; inspect it locally'})

        def unsupported(self):
            self.reply(405, {'error': 'unsupported method'})

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = unsupported

    return HTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--database', type=Path, help='optional local SQLite file for persistent jobs')
    args = parser.parse_args()
    try:
        server = create_server(os.environ.get('RFQ_API_TOKEN', ''), args.port, database=args.database)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'Error: {exc}\n')
    print(f'Local demo: POST http://127.0.0.1:{server.server_port}/quote; Ctrl+C to stop.', flush=True)
    if args.database is not None:
        print('Persistent draft endpoints enabled at /jobs; no approval or automatic sending.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
