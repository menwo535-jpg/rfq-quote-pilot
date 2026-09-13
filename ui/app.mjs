import {DraftClient} from './client.mjs';
const $ = id => document.getElementById(id);
let client = null, current = null, latestRevision = 0, busy = false, pdfContent = null;
let selectedJob = null, canRevise = true;
const reasonLabels = {'unknown product code':'价目表未找到产品编码',
  'unit mismatch or missing unit':'单位不一致或缺失', 'quantity must be positive':'数量必须大于零',
  'duplicate catalogue code':'价目表中存在重复编码', 'description mismatch':'产品描述不一致'};
function notice(text, error = false) { $('notice').textContent = text; $('notice').classList.toggle('error', error); }
function controls() {
  const locked = !client || busy || !!client.pending;
  $('input-fields').disabled = locked;
  for (const id of ['sample','new-draft','refresh-list']) $(id).disabled = locked;
  for (const button of $('draft-list').querySelectorAll('button')) button.disabled = locked;
  $('history').disabled = locked;
  $('refresh-current').disabled = locked;
  $('save').disabled = locked || (current && (!canRevise || current.job.revision !== latestRevision));
  $('retry').hidden = !client?.pending;
  $('retry').disabled = busy;
  $('save').textContent = current ? '保存为新修订 →' : '生成并保存草稿 →';
}
async function action(fn) {
  if (busy) return;
  busy = true; controls();
  try { await fn(); }
  catch (error) {
    if (error.status === 409) {
      canRevise = false;
      notice('这份草稿已有更新。本次未覆盖，请读取最新版本，对照输入后再保存。', true);
    } else if (client?.pending) {
      notice('尚未确认保存结果。请点击“重试同一请求”，保留原请求避免重复建单；不要刷新页面。' + (error.status === 401 ? ' 服务口令须保持与本页连接时一致。' : ''), true);
    } else {
      notice(error.status === 401 ? '访问口令不正确，请核对启动服务时的设置。' : error.message, true);
    }
  } finally { busy = false; controls(); }
}
function resetInputs() {
  pdfContent = null;
  for (const id of ['rfq-file','catalogue-file','rfq-text','catalogue-text']) $(id).value = '';
  $('rfq-text').disabled = false;
  $('rfq-note').textContent = '支持约定格式的文本 PDF，暂不含扫描件识别。';
}
function newDraft() {
  current = null; selectedJob = null; latestRevision = 0; canRevise = true;
  resetInputs(); $('result-panel').hidden = true;
  $('input-title').textContent = '准备报价输入';
  $('edit-note').textContent = '每次保存都会重新校验输入，生成 Excel 草稿。';
  for (const button of $('draft-list').querySelectorAll('button')) button.classList.remove('active');
  notice('新草稿：可以载入演示 PDF，或导入自己的文件。'); controls();
}
function bytesBase64(bytes) {
  let result = '';
  for (let i = 0; i < bytes.length; i += 8192) result += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(result);
}
function attachPDF(bytes, name) {
  if (bytes.length > 700000) throw new Error('演示版 PDF 上限为 700 KB，请使用更小的文件。');
  pdfContent = bytesBase64(bytes);
  $('rfq-text').value = ''; $('rfq-text').disabled = false;
  $('rfq-note').textContent = `已载入 ${name}。输入文本会替换这份 PDF；修订时可重新上传。`;
}
function payload() {
  const content = pdfContent ?? $('rfq-text').value;
  const catalogue = $('catalogue-text').value;
  if (!content.trim() || !catalogue.trim()) throw new Error('请同时提供询价单和完整的 CSV 价目表。');
  const value = {rfq:{format:pdfContent === null ? 'txt' : 'pdf_base64', content}, catalogue_csv:catalogue, include_xlsx:true};
  if (new TextEncoder().encode(JSON.stringify(value)).length > 1000000) throw new Error('询价单与价目表合计超过请求大小上限，请缩小文件。');
  return value;
}
async function listDrafts() {
  const data = await client.read('/jobs');
  $('draft-list').replaceChildren();
  for (const job of data.jobs) {
    const button = document.createElement('button'); button.className = 'draft-item';
    button.classList.toggle('active', job.id === selectedJob);
    button.textContent = `草稿 ${job.id.slice(0,8)} · v${job.revision}`;
    const line = document.createElement('span');
    line.textContent = `${job.row_count} 行 · ${job.review_count ? `${job.review_count} 项待复核` : '待人工批准'}`;
    button.append(line);
    button.addEventListener('click', () => action(() => loadJob(job.id)));
    $('draft-list').append(button);
  }
  $('list-note').textContent = data.has_more ? '这里只显示最近 50 份；较早草稿仍可通过 API 的 ID 读取。' : `${data.jobs.length} 份已保存草稿`;
}
async function loadJob(id, keepInputs = false) {
  const value = await client.read('/jobs/' + id);
  if (!keepInputs) resetInputs();
  current = value; selectedJob = id; latestRevision = value.job.revision; canRevise = true;
  render(); await history(); await listDrafts();
  notice(keepInputs ? '已读取最新结果。请对照保留的输入再保存修订。' : '已打开保存的草稿。修订前请重新载入完整源文件；原始 PDF 不保存在草稿库。');
}
async function history() {
  const data = await client.read(`/jobs/${selectedJob}/revisions`);
  $('history').replaceChildren();
  for (const item of data.revisions.slice().reverse()) {
    const option = document.createElement('option'); option.value = String(item.revision);
    option.textContent = `v${item.revision} · ${new Date(item.created_at).toLocaleString('zh-CN')}`;
    $('history').append(option);
  }
  $('history').value = String(current.job.revision);
}
function cell(tr, text, subtext = '') {
  const td = document.createElement('td'); td.textContent = text;
  if (subtext) { const small = document.createElement('small'); small.textContent = subtext; td.append(small); }
  tr.append(td); return td;
}
function renderRows() {
  $('rows').replaceChildren();
  if (!current) return;
  for (const row of current.result.quote.rows) {
    const review = row.status !== 'MATCHED_DRAFT';
    if ($('only-review').checked && !review) continue;
    const tr = document.createElement('tr'); if (review) tr.className = 'review-row';
    cell(tr, row.code || '未识别编码', row.description || row.source);
    cell(tr, `${row.quantity} ${row.unit}`);
    cell(tr, row.unit_price ? `${row.currency} ${row.unit_price}` : '—');
    cell(tr, row.line_total ? `${row.currency} ${row.line_total}` : '—');
    const status = cell(tr, review ? (reasonLabels[row.reason] || row.reason || '需要复核') : '已匹配 · 草稿', row.price_version);
    status.className = review ? 'row-reason' : 'matched';
    $('rows').append(tr);
  }
  $('empty-filter').hidden = $('rows').childElementCount > 0;
}
function render() {
  const quote = current.result.quote, old = current.job.revision !== latestRevision;
  $('result-panel').hidden = false;
  $('input-title').textContent = `修订草稿 ${current.job.id.slice(0,8)}`;
  $('result-title').textContent = `草稿 v${current.job.revision}${old ? ' · 历史快照' : ''}`;
  $('job-meta').textContent = current.job.id;
  $('row-count').textContent = String(quote.rows.length);
  $('review-count').textContent = String(quote.review_count);
  const complete = quote.complete_totals_by_currency;
  $('total-label').textContent = complete ? '待批准草稿合计' : '已匹配行小计';
  $('total').textContent = Object.entries(complete || quote.matched_subtotals_by_currency).map(([c,n]) => `${c} ${n}`).join(' / ') || '—';
  $('total-note').textContent = complete ? '所有行已匹配，仍需人工批准' : '含未处理异常，完整报价总额暂不生成';
  $('status-badge').textContent = quote.review_count ? `${quote.review_count} 项需要复核` : '已匹配，待人工批准';
  $('status-badge').classList.toggle('clear', !quote.review_count);
  $('download-xlsx').disabled = !current.result.artifacts.xlsx_base64;
  $('history-note').textContent = old ? '只读历史版本。读取最新版本后才能修订。' : '正在查看最新读取版本；保存时会检查并发修改。';
  $('edit-note').textContent = old ? '历史快照不能作为新修订的起点，请先读取最新版本。' : '完整输入将生成下一版本，已有历史保持不变。';
  renderRows(); controls();
}
async function saved(value) {
  current = value; selectedJob = value.job.id; latestRevision = value.job.revision; canRevise = true;
  render();
  notice(`草稿 v${value.job.revision} 已保存，${value.result.quote.review_count} 项待复核。`);
  // A successful write stays successful even when refreshing the list fails.
  try { await history(); await listDrafts(); }
  catch { notice('草稿已保存；列表或历史暂未刷新，可稍后读取最新版本。'); }
}
function download(format) {
  if (!current) return;
  let bytes, type;
  if (format === 'xlsx') {
    bytes = Uint8Array.from(atob(current.result.artifacts.xlsx_base64), c => c.charCodeAt(0));
    type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  } else { bytes = '\uFEFF' + current.result.artifacts.csv_utf8; type = 'text/csv;charset=utf-8'; }
  const url = URL.createObjectURL(new Blob([bytes], {type}));
  const a = document.createElement('a'); a.href = url;
  a.download = `quote-${current.job.id.slice(0,8)}-v${current.job.revision}.${format}`;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
}
$('connect-form').addEventListener('submit', event => {
  event.preventDefault(); action(async () => {
    const candidate = new DraftClient({token:$('token').value});
    await candidate.read('/jobs'); client = candidate; $('token').value = '';
    $('connect-panel').hidden = true; $('connection').textContent = '● 本地已连接'; $('connection').classList.add('live');
    await listDrafts(); notice('已连接。载入演示 PDF 即可体验真实文件处理与草稿保存。');
  });
});
$('sample').addEventListener('click', () => action(async () => {
  const [pdf, csv] = await Promise.all([fetch('/ui/sample.pdf'), fetch('/ui/sample.csv')]);
  if (!pdf.ok || !csv.ok) throw new Error('演示文件暂不可用。');
  attachPDF(new Uint8Array(await pdf.arrayBuffer()), 'rfq.pdf（合成演示）');
  $('catalogue-text').value = await csv.text();
  $('rfq-file').value = ''; $('catalogue-file').value = '';
  notice('已载入真实 PDF 和价目表。点击保存后由 Python 后端计算，样例含 4 项异常。');
}));
$('rfq-file').addEventListener('change', () => action(async () => {
  const file = $('rfq-file').files[0]; if (!file) return;
  pdfContent = null; $('rfq-text').value = ''; $('rfq-note').textContent = '正在读取选中的询价单…';
  if (file.size > 700000) throw new Error('询价文件上限为 700 KB。');
  if (/\.pdf$/i.test(file.name)) attachPDF(new Uint8Array(await file.arrayBuffer()), file.name);
  else if (/\.txt$/i.test(file.name)) { const text = await file.text(); pdfContent = null; $('rfq-text').value = text; $('rfq-note').textContent = `已载入 ${file.name}`; }
  else throw new Error('请导入 .pdf 或 .txt 文件。');
}));
$('catalogue-file').addEventListener('change', () => action(async () => {
  const file = $('catalogue-file').files[0]; if (!file) return;
  $('catalogue-text').value = '';
  if (!/\.csv$/i.test(file.name) || file.size > 700000) throw new Error('请使用 700 KB 以内的 CSV 文件。');
  $('catalogue-text').value = await file.text();
}));
$('rfq-text').addEventListener('input', () => { pdfContent = null; $('rfq-file').value = ''; $('rfq-note').textContent = '当前使用下方文本内容作为询价单。'; });
$('save').addEventListener('click', () => action(async () => {
  const input = payload();
  const value = current ? await client.write(`/jobs/${selectedJob}/revisions`, {expected_revision:current.job.revision,request:input}) : await client.write('/jobs',input);
  await saved(value);
}));
$('retry').addEventListener('click', () => action(async () => saved(await client.retry())));
$('new-draft').addEventListener('click', newDraft);
$('refresh-list').addEventListener('click', () => action(listDrafts));
$('refresh-current').addEventListener('click', () => action(() => loadJob(selectedJob, true)));
$('history').addEventListener('change', () => action(async () => {
  const requested = $('history').value;
  try { current = await client.read(`/jobs/${selectedJob}/revisions/${requested}`); render(); }
  catch (error) { $('history').value = String(current.job.revision); throw error; }
}));
$('only-review').addEventListener('change', renderRows);
$('download-csv').addEventListener('click', () => download('csv'));
$('download-xlsx').addEventListener('click', () => download('xlsx'));
window.addEventListener('beforeunload', event => { if (client?.pending) { event.preventDefault(); event.returnValue = ''; } });
