/* bookfetch N2 UI — runs in browser (serve) or pywebview (desktop shell). */

/* ---------- backend adapter: fetch(HTTP) or pywebview(js_api) ---------- */
const BF = (() => {
  // pywebview injects a skeleton (window.pywebview.api = {}) at documentStart;
  // the real api_call lands in finish.js after page load (→ 'pywebviewready').
  // So readiness = api.api_call being a function — the skeleton {} must not
  // count. Channel is chosen per call; boot() waits before first use.
  const pvReady = () => !!(window.pywebview
    && typeof window.pywebview.api.api_call === 'function');
  async function http(name, params) {
    const r = await fetch('/api/' + name, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params || {}),
    });
    const j = await r.json();
    if (j.error) throw new Error(j.error);
    return j;
  }
  // pywebview transport: JSON-string protocol both ways (its per-annotation type
  // conversion chokes on nested null/array params).
  async function pv(name, params) {
    const raw = await window.pywebview.api.api_call(name, JSON.stringify(params || {}));
    const j = JSON.parse(raw);
    if (j.error) throw new Error(j.error);
    return j;
  }
  return {
    get inPyWebView() { return pvReady(); },
    api: (name, params) => (pvReady() ? pv(name, params) : http(name, params)),
  };
})();

// Wait until the backend bridge is reachable (see BF above for the injection
// race) or give up after a window — plain browser mode returns immediately.
async function waitBackend(timeoutMs = 15000) {
  const pvReady = () => !!(window.pywebview
    && typeof window.pywebview.api.api_call === 'function');
  if (!window.pywebview || pvReady()) return;
  await new Promise((resolve) => {
    const to = setTimeout(resolve, timeoutMs); // hard cap: degrade to http
    window.addEventListener('pywebviewready', () => { clearTimeout(to); resolve(); }, { once: true });
    const iv = setInterval(() => { // fallback if the event fired before we listened
      if (pvReady()) { clearInterval(iv); clearTimeout(to); resolve(); }
    }, 150);
  });
}

/* ---------- utils ---------- */
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

function showView(name) {
  document.querySelectorAll('.view').forEach((v) => v.classList.add('hidden'));
  $('#view-reader').classList.add('hidden');
  if (name === 'reader') $('#view-reader').classList.remove('hidden');
  else $('#view-' + name).classList.remove('hidden');
  document.querySelectorAll('.tab').forEach((t) =>
    t.classList.toggle('active', t.dataset.view === name));
  if (name !== 'reader') history.replaceState(null, '', '#' + name); // 深链可刷
  if (name === 'shelf') loadShelf();
}

/* ---------- 状态 ---------- */
const state = {
  sources: [],
  chip: 'all',
  tasks: new Map(),          // task_id -> dom el
  book: null,                // {rel,title,format,chapters[]}
  cur: 0,                    // chapter index
  pct: 0,                    // 0..1 scroll position
  fontIdx: 1,
  readerDark: false,
};

const FONTS = [17, 19, 22, 25];

/* ---------- 搜索 ---------- */
let _searchCache = [];   // 最近一次搜索的完整结果（下载按钮按索引取）

async function loadSources() {
  try {
    const r = await BF.api('sources', {});
    state.sources = r.sources || [];
    const chips = $('#source-chips');
    chips.innerHTML = '';
    [['all', '全部']].concat(state.sources.map((s) => [s, s])).forEach(([val, label]) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'chip' + (val === 'all' ? ' on' : '');
      b.textContent = label;
      b.onclick = () => {
        chips.querySelectorAll('.chip').forEach((c) => c.classList.remove('on'));
        b.classList.add('on');
        state.chip = val;
        $('#search-q').focus();
      };
      chips.appendChild(b);
    });
  } catch (e) { /* 源列表失败不阻塞 */ }
}

async function doSearch(q) {
  const box = $('#search-results');
  box.innerHTML = '<p class="muted">搜索中…</p>';
  let r;
  try {
    r = await BF.api('search', { query: q, sources: state.chip === 'all' ? null : [state.chip] });
  } catch (e) {
    box.innerHTML = `<p>搜索失败：${esc(e.message)}</p>`;
    return;
  }
  _searchCache = r.results || [];
  const meta = [];
  if (r.count) meta.push(`命中 ${r.count} 条`);
  Object.entries(r.errors || {}).forEach(([s, e]) => meta.push(`<span class="badge warn">${esc(s)}: ${esc(e)}</span>`));
  $('#search-meta').innerHTML = meta.join(' ');
  if (!_searchCache.length) {
    box.innerHTML = '<p class="empty">没有结果——换个关键词，或点上面的源标签试试单个源</p>';
    return;
  }
  box.innerHTML = _searchCache.map(bookCard).join('');
}

function bookCard(b, i) {
  const lic = (b.extra && b.extra.license) ? `<span class="badge warn" title="${esc(b.extra.license)}">⚠️ 使用前自审</span>` : '';
  const isRaw = !!(b.extra && (b.extra.extension || b.extra.raw));
  const btn = isRaw
    ? '<button data-act="dl" data-i="' + i + '" data-fmt="" class="dl" title="下载原文件">原文件</button>'
    : `<button data-act="dl" data-i="${i}" data-fmt="txt" title="下载 txt">txt</button>
       <button data-act="dl" data-i="${i}" data-fmt="epub" class="epub" title="下载 epub">epub</button>`;
  return `
  <div class="card">
    <h3>${esc(b.title)}</h3>
    <div class="sub">${esc(b.subtitle || '')}</div>
    <div class="badges"><span class="badge">${esc(b.source)}</span>${lic}</div>
    <div class="actions">${btn}</div>
  </div>`;
}

$('#search-results').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-act="dl"]');
  if (!btn) return;
  const b = _searchCache[+btn.dataset.i];
  if (!b) return;
  addTask(b, btn.dataset.fmt);
});

function addTask(b, fmt) {
  const title = b.title || b.id;
  const t = document.createElement('div');
  t.className = 'task';
  t.innerHTML = `
    <div class="t-row"><span class="t-title">${esc(title)}</span>
      <button class="close" title="关闭">✕</button></div>
    <div class="t-msg">排队中…</div>
    <div class="t-bar"><i></i></div>`;
  t.querySelector('.close').onclick = () => { t.remove(); };
  $('#tasks').classList.remove('hidden');
  $('#tasks').appendChild(t);
  const isRaw = !!(b.extra && (b.extra.extension || b.extra.raw));
  const realFmt = isRaw ? '' : (fmt || 'txt');
  BF.api('download', { source: b.source, id: b.id, title: b.title, fmt: realFmt })
    .then((r) => pollTask(r.task_id, t, title))
    .catch((e) => { t.classList.add('err'); t.querySelector('.t-msg').textContent = e.message; });
}

function pollTask(taskId, el, title) {
  const tick = async () => {
    let r;
    try { r = await BF.api('task_status', { task_id: taskId }); }
    catch { return; }
    const msg = el.querySelector('.t-msg');
    if (r.status === 'done') {
      el.classList.add('ok');
      msg.textContent = `完成 → ${r.out_rel}`;
      msg.innerHTML += ` <a href="#" class="go-shelf">去书架</a>`;
      el.querySelector('.go-shelf').onclick = (ev) => { ev.preventDefault(); showView('shelf'); };
      el.querySelector('.t-bar').remove();
      return; // 停止轮询
    }
    if (r.status === 'error') { el.classList.add('err'); msg.textContent = r.message || '失败'; return; }
    msg.textContent = r.message || '下载中…';
    setTimeout(tick, 1500);
  };
  tick();
}

/* ---------- 书架 ---------- */
async function loadShelf() {
  let r;
  try { r = await BF.api('shelf', {}); }
  catch (e) { $('#shelf-books').innerHTML = `<p>书架读取失败：${esc(e.message)}</p>`; return; }
  $('#shelf-lib').textContent = r.library;
  if (!r.books.length) {
    $('#shelf-empty').classList.remove('hidden');
    $('#shelf-books').innerHTML = '';
    return;
  }
  $('#shelf-empty').classList.add('hidden');
  $('#shelf-books').innerHTML = r.books.map((b) => {
    const pg = b.progress;
    let bar = '', pos = '<span class="pos">未读</span>';
    if (pg) {
      const ch = (pg.chapter ?? 0) + 1;
      const pp = Math.min(100, Math.max(1, Math.round((pg.pct || 0) / 10)));
      bar = `<span class="prog"><i style="width:${pp}%"></i></span>`;
      pos = `<span class="pos">第 ${ch} 章 · ${pp}%</span>`;
    }
    return `
    <div class="book-row" data-rel="${esc(b.rel)}" title="${esc(b.title)}">
      <span class="t">${esc(b.title)}</span>
      <span class="fmt">${esc(b.format)} · ${b.size_kb} KB</span>
      ${bar}${pos}
    </div>`;
  }).join('');
}
$('#shelf-books').addEventListener('click', (e) => {
  const row = e.target.closest('.book-row');
  if (row) openReader(row.dataset.rel);
});
$('#empty-go-search').addEventListener('click', (e) => { e.preventDefault(); showView('search'); });

/* ---------- 阅读器 ---------- */
async function openReader(rel) {
  let ob;
  try { ob = await BF.api('open_book', { rel }); }
  catch (e) { alert('打开失败：' + e.message); return; }
  state.book = ob; state.cur = 0;
  $('#reader-title').textContent = ob.title;
  $('#toc-list').innerHTML = ob.chapters.map((c) =>
    `<li data-i="${c.i}" title="${esc(c.title)}">${esc(c.title)}</li>`).join('');
  showView('reader');
  $('#reader-body').scrollTop = 0;
  try {
    const pg = await BF.api('progress_get', { rel });
    if (pg.progress && pg.progress.chapter != null) {
      state.cur = Math.min(pg.progress.chapter, ob.chapters.length - 1);
      state.pct = (pg.progress.pct || 0);
    }
  } catch { /* 无进度不阻塞 */ }
  loadChapter();
}

async function loadChapter() {
  const ob = state.book;
  if (!ob) return;
  let c;
  try { c = await BF.api('chapter', { rel: ob.rel, idx: state.cur }); }
  catch (e) { $('#reader-body').innerHTML = `<p>加载失败：${esc(e.message)}</p>`; return; }
  const paras = c.text.split(/\n{2,}|\n(?=\S)/).map((s) => s.trim()).filter(Boolean)
    .filter((s) => s !== c.title && s !== '《' + c.title + '》');
  $('#reader-body').innerHTML = `<h1>${esc(c.title)}</h1>` +
    paras.map((p) => `<p>${esc(p)}</p>`).join('');
  document.querySelectorAll('#toc-list li').forEach((li) =>
    li.classList.toggle('cur', +li.dataset.i === state.cur));
  $('#reader-pos').textContent = `第 ${state.cur + 1} / ${ob.chapters.length} 章`;
  const el = $('#reader-body');
  requestAnimationFrame(() => {
    if (state.pct > 0 && el.scrollHeight > el.clientHeight) {
      el.scrollTop = state.pct * (el.scrollHeight - el.clientHeight);
    }
    state.pct = 0;
  });
  saveProgressSoon();
}

function saveProgress() {
  if (!state.book) return;
  const el = $('#reader-body');
  const max = el.scrollHeight - el.clientHeight;
  const pct = max > 0 ? el.scrollTop / max : 0;
  BF.api('progress_set', { rel: state.book.rel, chapter: state.cur, pct: Math.round(pct * 1000) });
}
let _saveTimer = null;
function saveProgressSoon() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(saveProgress, 1200);
}

function goChapter(i) {
  if (i < 0 || i >= state.book.chapters.length) return;
  saveProgress();
  state.cur = i;
  loadChapter();
}

$('#reader-body').addEventListener('scroll', () => saveProgressSoon());
$('#reader-next').addEventListener('click', () => goChapter(state.cur + 1));
$('#reader-prev').addEventListener('click', () => goChapter(state.cur - 1));
$('#reader-back').addEventListener('click', () => { saveProgress(); state.book = null; loadShelf(); showView('shelf'); });
$('#toc-list').addEventListener('click', (e) => {
  const li = e.target.closest('li[data-i]');
  if (li) goChapter(+li.dataset.i);
});
$('#reader-toc-toggle').addEventListener('click', () => {
  const toc = $('#reader-toc');
  toc.classList.toggle('hidden');
  $('#reader-body').style.paddingLeft = toc.classList.contains('hidden') ? '' : '300px';
});

/* 字号 + 夜间 */
$('#reader-aa').addEventListener('click', () => {
  state.fontIdx = (state.fontIdx + 1) % FONTS.length;
  $('#reader-body').style.fontSize = FONTS[state.fontIdx] + 'px';
  try { localStorage.setItem('bf-font', state.fontIdx); } catch {}
});
$('#reader-theme').addEventListener('click', () => {
  state.readerDark = !state.readerDark;
  document.body.dataset.readerDark = state.readerDark ? '1' : '0';
  $('#reader-theme').textContent = state.readerDark ? '☀️' : '🌙';
  try { localStorage.setItem('bf-dark', state.readerDark ? '1' : '0'); } catch {}
});

/* ---------- tabs / theme / form ---------- */
document.querySelectorAll('.tab[data-view]').forEach((t) =>
  t.addEventListener('click', () => {
    if (state.book) { saveProgress(); state.book = null; }
    showView(t.dataset.view);
  }));
$('#tab-theme').addEventListener('click', () => {
  const html = document.documentElement;
  html.dataset.theme = html.dataset.theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('bf-theme', html.dataset.theme); } catch {}
});
$('#search-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const q = $('#search-q').value.trim();
  if (!q) return;
  doSearch(q);
});
$('#search-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') e.preventDefault(); });

window.addEventListener('beforeunload', () => saveProgress());

/* ---------- boot ---------- */
(async () => {
  await waitBackend(); // pywebview bridge may still be injecting (harmless on http)
  try { $('#shelf-lib').textContent = (await BF.api('library', {})).library; } catch {}
  try {
    const f = localStorage.getItem('bf-font'); if (f) state.fontIdx = +f;
    $('#reader-body').style.fontSize = FONTS[state.fontIdx] + 'px';
    const d = localStorage.getItem('bf-dark');
    if (d === '1') { state.readerDark = true; document.body.dataset.readerDark = '1'; $('#reader-theme').textContent = '☀️'; }
    const t = localStorage.getItem('bf-theme');
    if (t) document.documentElement.dataset.theme = t;
    // URL 参数覆盖（?theme=dark / ?rdark=1）：预览与截图用
    const q = new URLSearchParams(location.search);
    if (q.get('theme') === 'dark') document.documentElement.dataset.theme = 'dark';
    if (q.get('rdark') === '1') { document.body.dataset.readerDark = '1'; $('#reader-theme').textContent = '☀️'; }
  } catch {}
  loadSources();
  // 深链/刷新恢复：`#shelf` / `#reader/<rel>` 直达视图
  const m = (location.hash || '').match(/^#reader\/(.+)$/);
  if (m) openReader(decodeURIComponent(m[1]));
  else if (location.hash === '#shelf') showView('shelf');
})();
window.addEventListener('hashchange', () => {
  const h = location.hash || '';
  if (h === '#search' || h === '#shelf') showView(h.slice(1));
});
