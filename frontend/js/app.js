const UI = {
  qs: new URLSearchParams(location.search),
  money: n => '$' + Number(n || 0).toLocaleString('en-US'),
  STATUS: {
    APPROVED:['pass','✓'], REDUCE:['caution','↓'], ON_HOLD:['info','‖'],
    INVESTIGATE:['open','?'], EXPEDITE:['stop','»'], REJECTED:['stop','✕'], PENDING:['open','…']
  },
  chip(status) {
    const m = this.STATUS[status] || ['open','·'];
    return `<span class="chip ${m[0]}">${m[1]} ${status.replace('_',' ')}</span>`;
  },
  gateChip(s) {
    const map = {PASSED:'pass',FOUND:'pass',CLEAR:'pass',OPTIMAL:'pass',FAILED:'stop',
      DUPLICATE:'stop',PARTIAL:'caution',PO_OVERLAP:'caution',OVER:'caution',UNDER:'caution',
      NONE:'info',NEEDS_REVIEW:'open'};
    return `<span class="chip ${map[s]||'open'}">${s.replace('_',' ')}</span>`;
  },
  nav(key) { document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('active', a.dataset.nav === key)); },
  toast(msg) {
    const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg;
    document.body.appendChild(t); setTimeout(() => t.remove(), 3800);
  },
  async guard() {
    try {
      const u = await API.get('/auth/me');
      document.querySelectorAll('[data-user-name]').forEach(e => e.textContent = u.name);
      document.querySelectorAll('[data-user-role]').forEach(e => e.textContent = u.role);
      return u;
    } catch (e) { return null; }
  }
};
window.UI = UI;
document.addEventListener('DOMContentLoaded', async () => {
  await UI.guard();
  const gs = document.getElementById('globalsearch');
  if (gs) gs.addEventListener('submit', ev => {
    ev.preventDefault();
    location.href = '/history.html?q=' + encodeURIComponent(gs.querySelector('input').value);
  });
  const lo = document.getElementById('logout');
  if (lo) lo.addEventListener('click', async () => { await API.post('/auth/logout'); location.href = '/index.html'; });
});