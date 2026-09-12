"""Database transactions, independent connections and actual loopback HTTP."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import http.client
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

import openpyxl

from job_store import JobStore, JobConflict, JobNotFound
from local_api import build_response, create_server

ROOT = Path(__file__).parent
TOKEN = 'localPersistenceTestToken00000000'


def request_payload(quantity='2.5', xlsx=False):
    return {
        'rfq': {'format': 'txt', 'content': f'ITEMS\n0001|Cable|{quantity}|M\nEND ITEMS'},
        'catalogue_csv': 'code,description,unit,unit_price,currency,price_version\n0001,Cable,M,1.23,USD,v1\n',
        'include_xlsx': xlsx,
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rfq-store-test-')
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'drafts.sqlite3'
        self.store = JobStore(self.database, build_response)

    def test_restart_and_retry_return_identical_xlsx_without_reprocessing(self):
        first, replay = self.store.create(request_payload(xlsx=True), 'first-order')
        self.assertFalse(replay)
        reopened = JobStore(self.database, lambda _: self.fail('retry processed input again'))
        again, replay = reopened.create(request_payload(xlsx=True), 'first-order')
        self.assertTrue(replay)
        self.assertEqual(first, again)
        self.assertEqual(reopened.get(first['job']['id']), first)
        book = openpyxl.load_workbook(io.BytesIO(base64.b64decode(first['result']['artifacts']['xlsx_base64'])))
        self.assertEqual(len(book.worksheets), 2)
        book.close()

    def test_omitted_false_flag_and_key_order_are_equivalent(self):
        payload = request_payload()
        payload.pop('include_xlsx')
        first, _ = self.store.create(payload, 'equivalent')
        reordered = dict(reversed(list(request_payload().items())))
        self.assertEqual(self.store.create(reordered, 'equivalent'), (first, True))

    def test_changed_payload_cannot_reuse_create_key(self):
        first, _ = self.store.create(request_payload(), 'key-1')
        with self.assertRaises(JobConflict):
            self.store.create(request_payload('3'), 'key-1')
        self.assertEqual(self.store.get(first['job']['id']), first)

    def test_invalid_input_does_not_consume_key_or_create_job(self):
        bad = request_payload()
        bad['catalogue_csv'] = 'bad header'
        with self.assertRaises(ValueError):
            self.store.create(bad, 'correct-later')
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM rfq_jobs').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT count(*) FROM rfq_operations').fetchone()[0], 0)
        self.assertFalse(self.store.create(request_payload(), 'correct-later')[1])

    def test_revision_keeps_previous_result_and_replays_original_operation(self):
        initial = request_payload()
        initial['rfq']['content'] = 'ITEMS\n0001|Unconfirmed label|2.5|M\nEND ITEMS'
        first, _ = self.store.create(initial, 'create')
        job_id = first['job']['id']
        self.assertEqual(first['result']['quote']['status'], 'REVIEW_REQUIRED')
        second, replay = self.store.revise(job_id, request_payload(), 'fix-description', 1)
        self.assertFalse(replay)
        self.assertEqual(second['result']['quote']['status'], 'DRAFT_FOR_APPROVAL')
        self.assertEqual(second['result']['quote']['complete_totals_by_currency'], {'USD': '3.08'})
        self.assertEqual(second['job']['revision'], 2)
        self.assertEqual(self.store.get(job_id, 1), first)
        self.assertEqual(self.store.get(job_id), second)
        self.assertEqual(self.store.create(initial, 'create'), (first, True))
        self.store.revise(job_id, request_payload('5'), 'new-quantity', 2)
        self.assertEqual(self.store.revise(job_id, request_payload(), 'fix-description', 1), (second, True))
        self.assertEqual([x['revision'] for x in self.store.history(job_id)['revisions']], [1, 2, 3])
        with self.assertRaises(JobConflict):
            self.store.revise(job_id, request_payload(), 'fix-description', 3)

    def test_stale_revision_and_failed_correction_leave_history_unchanged(self):
        first, _ = self.store.create(request_payload(), 'create')
        job_id = first['job']['id']
        second, _ = self.store.revise(job_id, request_payload('3'), 'update', 1)
        with self.assertRaises(JobConflict):
            self.store.revise(job_id, request_payload('4'), 'stale', 1)
        with self.assertRaises(ValueError):
            self.store.revise(job_id, {}, 'bad-file', 2)
        self.assertEqual(self.store.get(job_id), second)
        self.assertEqual(len(self.store.history(job_id)['revisions']), 2)

    def test_unknown_jobs_and_revisions_do_not_create_records(self):
        with self.assertRaises(JobNotFound):
            self.store.get('f' * 32)
        with self.assertRaises(JobNotFound):
            self.store.history('f' * 32)
        with self.assertRaises(JobNotFound):
            self.store.revise('f' * 32, request_payload(), 'unknown', 1)
        first, _ = self.store.create(request_payload(), 'create')
        with self.assertRaises(JobNotFound):
            self.store.get(first['job']['id'], 2)

    def test_database_write_failure_rolls_back_all_three_tables(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('''CREATE TRIGGER fail_operation BEFORE INSERT ON rfq_operations
                BEGIN SELECT RAISE(ABORT, 'simulated disk-write failure'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create(request_payload(), 'retry-after-failure')
        with closing(sqlite3.connect(self.database)) as connection:
            for table in ('rfq_jobs', 'rfq_revisions', 'rfq_operations'):
                self.assertEqual(connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
            connection.execute('DROP TRIGGER fail_operation')
        self.assertFalse(self.store.create(request_payload(), 'retry-after-failure')[1])

    def test_database_write_failure_preserves_existing_revision_pointer(self):
        first, _ = self.store.create(request_payload(), 'create')
        job_id = first['job']['id']
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('''CREATE TRIGGER fail_operation BEFORE INSERT ON rfq_operations
                BEGIN SELECT RAISE(ABORT, 'simulated failure'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.revise(job_id, request_payload('10'), 'change', 1)
        self.assertEqual(self.store.get(job_id), first)
        self.assertEqual(len(self.store.history(job_id)['revisions']), 1)

    def racing_stores(self):
        barrier = threading.Barrier(2, timeout=10)

        def processing(payload):
            result = build_response(payload)
            barrier.wait()
            return result

        return [JobStore(self.database, processing), JobStore(self.database, processing)]

    def test_simultaneous_create_retries_commit_one_job(self):
        stores = self.racing_stores()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(store.create, request_payload(), 'simultaneous') for store in stores]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sorted(x[1] for x in results), [False, True])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM rfq_jobs').fetchone()[0], 1)

    def test_simultaneous_edits_cannot_overwrite_each_other(self):
        first, _ = self.store.create(request_payload(), 'create')
        job_id = first['job']['id']
        stores = self.racing_stores()
        results, conflicts = [], 0
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(store.revise, job_id, request_payload(str(i + 3)), f'edit-{i}', 1)
                       for i, store in enumerate(stores)]
            for future in futures:
                try:
                    results.append(future.result(timeout=15))
                except JobConflict:
                    conflicts += 1
        self.assertEqual(conflicts, 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(self.store.get(job_id), results[0][0])
        self.assertEqual(len(self.store.history(job_id)['revisions']), 2)

    def test_invalid_key_and_revision_types_are_rejected(self):
        for key in ('', 'bad key', '中', 'a' * 129, None):
            with self.assertRaises(ValueError):
                self.store.create(request_payload(), key)
        for revision in (True, False, 0, -1, 1.0, '1', None):
            with self.assertRaises(ValueError):
                self.store.revise('f' * 32, request_payload(), 'edit', revision)


class PersistentHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rfq-job-http-')
        self.database = Path(self.temp.name) / 'jobs.sqlite3'
        self.start_server()

    def start_server(self):
        self.server = create_server(TOKEN, 0, database=self.database)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def tearDown(self):
        self.stop_server()
        self.temp.cleanup()

    def request(self, method, path, payload=None, key=None, headers=None):
        outgoing = {'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'}
        if key is not None:
            outgoing['Idempotency-Key'] = key
        outgoing.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            body = None if payload is None else json.dumps(payload)
            connection.request(method, path, body=body, headers=outgoing)
            response = connection.getresponse()
            return response.status, json.loads(response.read()), dict(response.getheaders())
        finally:
            connection.close()

    def test_pdf_create_and_response_loss_retry_after_server_restart(self):
        payload = {'rfq': {'format': 'pdf_base64', 'content': base64.b64encode(
            (ROOT / 'samples/rfq.pdf').read_bytes()).decode('ascii')},
            'catalogue_csv': (ROOT / 'samples/catalogue.csv').read_text(encoding='utf-8'),
            'include_xlsx': True}
        status, first, headers = self.request('POST', '/jobs', payload, 'pdf-import-1')
        self.assertEqual(status, 201)
        self.assertEqual(headers['Idempotency-Replayed'], 'false')
        self.assertEqual(first['result']['quote']['review_count'], 4)
        self.stop_server()
        self.start_server()
        status, again, headers = self.request('POST', '/jobs', payload, 'pdf-import-1')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Idempotency-Replayed'], 'true')
        self.assertEqual(first, again)
        self.assertEqual(self.request('GET', '/jobs/' + first['job']['id'])[1], first)

    def test_correction_history_and_stale_http_edit(self):
        _, first, _ = self.request('POST', '/jobs', request_payload(), 'create')
        path = '/jobs/' + first['job']['id']
        correction = {'expected_revision': 1, 'request': request_payload('4', True)}
        status, second, _ = self.request('POST', path + '/revisions', correction, 'edit-1')
        self.assertEqual(status, 201)
        self.assertEqual(second['result']['quote']['complete_totals_by_currency'], {'USD': '4.92'})
        self.assertEqual(self.request('POST', path + '/revisions', correction, 'edit-1')[0], 200)
        self.assertEqual(self.request('POST', path + '/revisions', correction, 'stale-edit')[0], 409)
        self.assertEqual(self.request('GET', path + '/revisions/1')[1], first)
        self.assertEqual(self.request('GET', path + '/revisions/2')[1], second)
        self.assertEqual(len(self.request('GET', path + '/revisions')[1]['revisions']), 2)
        self.assertEqual(self.request('GET', path)[1], second)

    def test_keys_and_validation_errors_have_actionable_http_status(self):
        self.assertEqual(self.request('POST', '/jobs', request_payload())[0], 422)
        self.assertEqual(self.request('POST', '/jobs', {}, 'bad-file')[0], 422)
        self.assertEqual(self.request('POST', '/jobs', request_payload(), 'bad-file')[0], 201)
        self.assertEqual(self.request('POST', '/jobs', request_payload('4'), 'bad-file')[0], 409)

    def test_stored_data_requires_same_local_authorization(self):
        _, first, _ = self.request('POST', '/jobs', request_payload(), 'create')
        path = '/jobs/' + first['job']['id']
        for suffix in ('', '/revisions', '/revisions/1'):
            self.assertEqual(self.request('GET', path + suffix, headers={'Authorization': ''})[0], 401)
            self.assertEqual(self.request('GET', path + suffix, headers={'Host': 'example.com'})[0], 403)
        self.assertEqual(self.request('POST', path + '/revisions', {}, 'edit',
                                      headers={'Authorization': ''})[0], 401)

    def test_unknown_records_and_unsupported_methods_do_not_mutate(self):
        self.assertEqual(self.request('GET', '/jobs/' + 'a' * 32)[0], 404)
        self.assertEqual(self.request('GET', '/jobs/' + 'a' * 32 + '/revisions/0')[0], 404)
        self.assertEqual(self.request('POST', '/jobs/' + 'a' * 32 + '/revisions',
                                      {'expected_revision': 1, 'request': request_payload()}, 'edit')[0], 404)
        _, first, _ = self.request('POST', '/jobs', request_payload(), 'create')
        for method in ('DELETE', 'PUT', 'PATCH', 'OPTIONS'):
            self.assertEqual(self.request(method, '/jobs/' + first['job']['id'])[0], 405)
        self.assertEqual(self.request('GET', '/jobs/' + first['job']['id'])[1], first)

    def test_stateless_quote_still_works_with_persistence_enabled(self):
        status, result, headers = self.request('POST', '/quote', request_payload())
        self.assertEqual(status, 200)
        self.assertEqual(result, build_response(request_payload()))
        self.assertNotIn('Idempotency-Replayed', headers)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM rfq_jobs').fetchone()[0], 0)

    def test_cli_process_restart_keeps_committed_result(self):
        child_database = Path(self.temp.name) / 'child.sqlite3'
        payload = request_payload(xlsx=True)

        def cycle(create):
            process = subprocess.Popen(
                [sys.executable, str(ROOT / 'local_api.py'), '--port', '0', '--database', str(child_database)],
                cwd=ROOT, env=dict(os.environ, RFQ_API_TOKEN=TOKEN),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                ready = process.stdout.readline()
                match = re.search(r'127\.0\.0\.1:(\d+)/quote', ready)
                self.assertIsNotNone(match, ready)
                connection = http.client.HTTPConnection('127.0.0.1', int(match[1]), timeout=10)
                try:
                    connection.request('POST', '/jobs', json.dumps(payload),
                                       {'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json',
                                        'Idempotency-Key': 'survive-process-restart'})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 201 if create else 200)
                    return json.loads(response.read()), process.pid
                finally:
                    connection.close()
            finally:
                process.terminate()
                process.communicate(timeout=10)

        first, first_pid = cycle(True)
        second, second_pid = cycle(False)
        self.assertNotEqual(first_pid, second_pid)
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
