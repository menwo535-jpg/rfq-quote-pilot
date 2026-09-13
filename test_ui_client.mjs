// Run against a real Python HTTP server and SQLite database, without a browser mock.
import {test, before, after} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {once} from 'node:events';
import {DraftClient, APIError} from './ui/client.mjs';
let child, directory, base;
const token = 'uiIntegrationTestingToken00000000';
const fixture = qty => ({rfq:{format:'txt',content:`ITEMS\n0001|Cable|${qty}|M\nEND ITEMS`},
  catalogue_csv:'code,description,unit,unit_price,currency,price_version\n0001,Cable,M,1.23,USD,v1\n',include_xlsx:true});
before(async () => {
  directory = await mkdtemp(join(tmpdir(), 'rfq-client-integration-'));
  child = spawn(process.env.RFQ_TEST_PYTHON || 'python', ['-u','-c',
    'import os; from local_api import create_server; s=create_server(os.environ["RFQ_TEST_TOKEN"],0,database=os.environ["RFQ_TEST_DB"]); print(s.server_port,flush=True); s.serve_forever()'],
    {cwd:import.meta.dirname, env:{...process.env,RFQ_TEST_TOKEN:token,RFQ_TEST_DB:join(directory,'jobs.sqlite3')},stdio:['ignore','pipe','pipe'],windowsHide:true});
  base = await new Promise((resolve,reject) => {
    const timer = setTimeout(() => reject(new Error('test server startup timeout')),10000);
    let output = '', errors = '';
    child.stderr.on('data', chunk => { errors += chunk; });
    child.once('error', error => {clearTimeout(timer); reject(error);});
    child.once('exit', code => {clearTimeout(timer); reject(new Error(`server exited ${code}: ${errors}`));});
    child.stdout.on('data', chunk => {output += chunk; if (output.includes('\n')) {clearTimeout(timer); resolve('http://127.0.0.1:' + Number(output.trim()));}});
  });
});
after(async () => {
  if (child && child.exitCode === null) {const exited = once(child,'exit'); child.kill(); await exited;}
  // Only this test's own mkdtemp directory; no user files or computed parent path.
  if (directory) await rm(directory,{recursive:true});
});
test('a committed response lost in transit retries the same key/body and creates one draft', async () => {
  let lost = true; const attempts = [];
  const client = new DraftClient({token,base,fetcher:async (url, options) => {
    const response = await fetch(url,options);
    if (options.method === 'POST') {
      attempts.push({body:options.body,key:options.headers['Idempotency-Key']});
      if (lost) {lost = false; assert.equal(response.status,201); await response.json(); throw new TypeError('simulated response loss after real commit');}
    }
    return response;
  }});
  const input = fixture('2.5');
  await assert.rejects(client.write('/jobs',input));
  input.rfq.content = 'changed after original attempt';
  await assert.rejects(client.write('/jobs',fixture('10')), /仍有结果未确认/);
  const result = await client.retry();
  assert.equal(result.result.quote.complete_totals_by_currency.USD,'3.08');
  assert.deepEqual(attempts[0],attempts[1]);
  assert.equal(client.pending,null);
  assert.equal((await client.read('/jobs')).jobs.length,1);
});
test('two clients cannot silently overwrite a newer revision; original snapshot is preserved', async () => {
  const a = new DraftClient({token,base}), b = new DraftClient({token,base});
  const original = await a.write('/jobs',fixture('2'));
  const path = `/jobs/${original.job.id}/revisions`;
  await b.write(path,{expected_revision:1,request:fixture('5')});
  await assert.rejects(a.write(path,{expected_revision:1,request:fixture('9')}),error => error instanceof APIError && error.status === 409);
  assert.equal(a.pending,null);
  assert.equal((await a.read(`/jobs/${original.job.id}`)).result.quote.complete_totals_by_currency.USD,'6.15');
  assert.deepEqual(await a.read(path+'/1'),original);
});
test('validation errors unlock correction and do not add a draft', async () => {
  const client = new DraftClient({token,base});
  const count = (await client.read('/jobs')).jobs.length;
  await assert.rejects(client.write('/jobs',{...fixture('2'),catalogue_csv:'wrong'}), error => error.status === 422);
  assert.equal(client.pending,null);
  assert.equal((await client.read('/jobs')).jobs.length,count);
  assert.equal((await client.write('/jobs',fixture('2'))).job.revision,1);
});
test('server failure retains exact request for retry', async () => {
  let failed = false;
  const client = new DraftClient({token,base,fetcher:async (url,options) => {
    if (!failed) {failed = true; return new Response(JSON.stringify({error:'temporary unavailable'}),{status:503});}
    return fetch(url,options);
  }});
  await assert.rejects(client.write('/jobs',fixture('3')),error => error.status === 503);
  const key = client.pending.key;
  assert.equal((await client.retry()).result.quote.complete_totals_by_currency.USD,'3.69');
  assert.ok(key); assert.equal(client.pending,null);
});
