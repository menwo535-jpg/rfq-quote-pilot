"""Real HTTP/static-shell checks for the local operator interface."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from job_store import JobStore
from local_api import create_server, build_response
from test_job_store import request_payload

TOKEN = 'workspaceTestToken00000000000000'

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rfq-ui-test-')
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'jobs.sqlite3'
        self.server = create_server(TOKEN, 0, database=self.database)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            conn.request('GET', path, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_shell_and_exact_assets_contain_no_server_token(self):
        for path, expected in [('/', 'text/html'), ('/ui/app.mjs','text/javascript'),
                               ('/ui/client.mjs','text/javascript'), ('/ui/style.css','text/css'),
                               ('/ui/sample.pdf','application/pdf'), ('/ui/sample.csv','text/csv')]:
            status, headers, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertTrue(headers['Content-Type'].startswith(expected))
            self.assertNotIn(TOKEN.encode(), body)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])

    def test_only_shell_is_public_and_unlisted_local_files_are_unavailable(self):
        self.assertEqual(self.get('/jobs')[0], 401)
        self.assertEqual(self.get('/', {'Host':'example.invalid'})[0], 403)
        for path in ['/ui/../local_api.py', '/jobs.sqlite3', '/ui/.env', '/ui/unknown.mjs']:
            self.assertNotEqual(self.get(path)[0], 200)

    def test_recent_list_uses_latest_revision_without_export_artifacts(self):
        store = JobStore(self.database, build_response)
        first, _ = store.create(request_payload(xlsx=True), 'create')
        store.revise(first['job']['id'], request_payload('5'), 'update', 1)
        status, _, body = self.get('/jobs', {'Authorization':'Bearer ' + TOKEN})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['jobs'][0]['revision'], 2)
        self.assertEqual(data['jobs'][0]['row_count'], 1)
        self.assertFalse(data['has_more'])
        self.assertNotIn('artifacts', body.decode())
        self.assertNotIn('catalogue_csv', body.decode())

    def test_recent_list_is_bounded_and_marks_omitted_drafts(self):
        result = {'quote':{'status':'DRAFT_FOR_APPROVAL','review_count':0,'rows':[]}}
        store = JobStore(self.database, lambda _: result)
        ids = [store.create({}, f'job-{i}')[0]['job']['id'] for i in range(51)]
        data = store.recent()
        self.assertEqual(len(data['jobs']), 50)
        self.assertTrue(data['has_more'])
        self.assertEqual(data['jobs'][0]['id'], ids[-1])
        self.assertNotIn(ids[0], [j['id'] for j in data['jobs']])

if __name__ == '__main__':
    unittest.main()
