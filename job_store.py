"""Durable local RFQ drafts. No approval, queue, network calls or delivery."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid


class JobConflict(Exception):
    """An idempotency key or expected revision conflicts with stored work."""


class JobNotFound(Exception):
    """The requested job or revision does not exist."""


def _fingerprint(payload):
    if not isinstance(payload, dict):
        raise ValueError('request must be an object')
    normalized = dict(payload)
    normalized.setdefault('include_xlsx', False)
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value):
        raise ValueError('one Idempotency-Key of 1-128 ASCII letters/digits or _ . : - is required')
    return value


class JobStore:
    def __init__(self, path, processor):
        self.path = Path(path).resolve()
        self.processor = processor
        # Each operation gets its own connection, including across threads.
        # A caller chooses the local file; HTTP input cannot choose its path.
        with self._transaction() as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('unsupported RFQ database schema version')
            connection.execute('''CREATE TABLE IF NOT EXISTS rfq_jobs (
                id TEXT PRIMARY KEY, current_revision INTEGER NOT NULL,
                created_at TEXT NOT NULL)''')
            connection.execute('''CREATE TABLE IF NOT EXISTS rfq_revisions (
                job_id TEXT NOT NULL REFERENCES rfq_jobs(id),
                revision INTEGER NOT NULL CHECK(revision > 0),
                created_at TEXT NOT NULL, request_sha256 TEXT NOT NULL,
                response_json TEXT NOT NULL, PRIMARY KEY(job_id, revision))''')
            connection.execute('''CREATE TABLE IF NOT EXISTS rfq_operations (
                scope TEXT NOT NULL, key TEXT NOT NULL, request_sha256 TEXT NOT NULL,
                expected_revision INTEGER NOT NULL,
                job_id TEXT NOT NULL, revision INTEGER NOT NULL,
                PRIMARY KEY(scope, key),
                FOREIGN KEY(job_id, revision) REFERENCES rfq_revisions(job_id, revision))''')
            connection.execute('PRAGMA user_version = 1')

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys = ON')
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _snapshot(self, connection, job_id, revision=None):
        job = connection.execute('SELECT * FROM rfq_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None:
            raise JobNotFound('job not found')
        number = job['current_revision'] if revision is None else revision
        row = connection.execute('SELECT * FROM rfq_revisions WHERE job_id = ? AND revision = ?',
                                 (job_id, number)).fetchone()
        if row is None:
            raise JobNotFound('revision not found')
        return {'job': {'id': job_id, 'revision': number, 'created_at': job['created_at'],
                        'updated_at': row['created_at'], 'request_sha256': row['request_sha256']},
                'result': json.loads(row['response_json'])}

    def get(self, job_id, revision=None):
        with self._connection() as connection:
            # One read transaction keeps job metadata and its snapshot consistent.
            connection.execute('BEGIN')
            return self._snapshot(connection, job_id, revision)

    def history(self, job_id):
        with self._connection() as connection:
            connection.execute('BEGIN')
            if connection.execute('SELECT 1 FROM rfq_jobs WHERE id = ?', (job_id,)).fetchone() is None:
                raise JobNotFound('job not found')
            rows = connection.execute('''SELECT revision, created_at, request_sha256
                FROM rfq_revisions WHERE job_id = ? ORDER BY revision''', (job_id,)).fetchall()
            return {'job_id': job_id, 'revisions': [dict(row) for row in rows]}

    def _replay(self, connection, scope, key, digest, expected):
        operation = connection.execute('SELECT * FROM rfq_operations WHERE scope = ? AND key = ?',
                                       (scope, key)).fetchone()
        if operation is None:
            return None
        if operation['request_sha256'] != digest or operation['expected_revision'] != expected:
            raise JobConflict('Idempotency-Key was already used for a different request')
        return self._snapshot(connection, operation['job_id'], operation['revision'])

    def _check_revision(self, connection, job_id, expected):
        row = connection.execute('SELECT current_revision FROM rfq_jobs WHERE id = ?', (job_id,)).fetchone()
        if row is None:
            raise JobNotFound('job not found')
        if row['current_revision'] != expected:
            raise JobConflict(f'expected_revision is stale; current revision is {row["current_revision"]}')

    def create(self, payload, key):
        return self._write(payload, _key(key), None, 0)

    def revise(self, job_id, payload, key, expected_revision):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError('expected_revision must be a positive integer')
        return self._write(payload, _key(key), job_id, expected_revision)

    def _write(self, payload, key, job_id, expected):
        digest = _fingerprint(payload)
        scope = job_id if job_id is not None else 'create'
        with self._connection() as connection:
            connection.execute('BEGIN')
            replay = self._replay(connection, scope, key, digest, expected)
            if replay is not None:
                return replay, True
            if job_id is not None:
                self._check_revision(connection, job_id, expected)

        # Parse PDFs and create files before taking the database write lock.
        # Failure leaves neither a job nor a consumed idempotency key.
        result = self.processor(payload)
        serialized = json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
        with self._transaction() as connection:
            # Another process may have committed while this request was parsing.
            replay = self._replay(connection, scope, key, digest, expected)
            if replay is not None:
                return replay, True
            now = datetime.now(timezone.utc).isoformat()
            if job_id is None:
                job_id = uuid.uuid4().hex
                connection.execute('INSERT INTO rfq_jobs VALUES (?, 1, ?)', (job_id, now))
            else:
                self._check_revision(connection, job_id, expected)
                connection.execute('UPDATE rfq_jobs SET current_revision = ? WHERE id = ?',
                                   (expected + 1, job_id))
            connection.execute('INSERT INTO rfq_revisions VALUES (?, ?, ?, ?, ?)',
                               (job_id, expected + 1, now, digest, serialized))
            connection.execute('INSERT INTO rfq_operations VALUES (?, ?, ?, ?, ?, ?)',
                               (scope, key, digest, expected, job_id, expected + 1))
            return self._snapshot(connection, job_id, expected + 1), False
