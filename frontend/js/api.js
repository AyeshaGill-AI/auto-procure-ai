const API = {
  _csrf: null,
  base: '/api',
  init() {
    const m = document.querySelector('meta[name="csrf-token"]');
    if (m) API._csrf = m.content;
  },
  async req(m, p, b) {
    if (!API._csrf) this.init();
    const headers = {'Content-Type': 'application/json'};
    if (API._csrf) headers['X-CSRF-Token'] = API._csrf;
    const r = await fetch(this.base + p, {
      method: m, headers,
      credentials: 'same-origin', body: b ? JSON.stringify(b) : undefined
    });
    const csrf = r.headers.get('X-CSRF-Token');
    if (csrf) API._csrf = csrf;
    if (r.status === 401 && !location.pathname.endsWith('index.html') && location.pathname !== '/') {
      location.href = '/index.html'; throw new Error('auth');
    }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
    return d;
  },
  get(p)  { return this.req('GET', p); },
  post(p, b) { return this.req('POST', p, b); },
  put(p, b) { return this.req('PUT', p, b); },
  del(p) { return this.req('DELETE', p); }
};
window.API = API;