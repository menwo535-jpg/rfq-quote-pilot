// A failed delivery can mean the write committed. Retain its exact key and body.
export class APIError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}
export class DraftClient {
  constructor({token, base = '', fetcher = (...args) => fetch(...args), timeoutMs = 20000}) {
    this.token = token; this.base = base; this.fetcher = fetcher;
    this.timeoutMs = timeoutMs; this.pending = null;
  }
  async read(path) {
    return this.send(path, {method: 'GET'});
  }
  async send(path, options) {
    const response = await this.fetcher(this.base + path, {
      ...options, cache: 'no-store', signal: AbortSignal.timeout(this.timeoutMs),
      headers: {'Authorization': 'Bearer ' + this.token, ...options.headers},
    });
    let data;
    try { data = await response.json(); }
    catch { throw new APIError('服务响应不完整，请保留本次请求重试。', response.ok ? 502 : response.status); }
    if (!response.ok) throw new APIError(data.error || '请求未完成', response.status);
    return data;
  }
  async write(path, payload) {
    if (this.pending) throw new Error('仍有结果未确认的请求，请先重试。');
    this.pending = Object.freeze({path, body: JSON.stringify(payload), key: crypto.randomUUID()});
    return this.retry();
  }
  async retry() {
    const request = this.pending;
    if (!request) throw new Error('没有待重试的请求。');
    try {
      const data = await this.send(request.path, {method: 'POST', body: request.body,
        headers: {'Content-Type': 'application/json', 'Idempotency-Key': request.key}});
      this.pending = null;
      return data;
    } catch (error) {
      // Server validation/conflict responses did not commit this operation.
      // Authentication, timeout, network and server errors retain the request.
      if ([400, 404, 409, 413, 415, 422].includes(error.status)) this.pending = null;
      throw error;
    }
  }
}
