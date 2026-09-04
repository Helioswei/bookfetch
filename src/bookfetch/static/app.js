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
  chip: '全部',                // 当前分类组名（SOURCE_GROUPS 的 key）
  tasks: new Map(),          // task_id -> dom el
  book: null,                // {rel,title,format,chapters[],base}
  cur: 0,                    // chapter index
  pct: 0,                    // 0..1 scroll position
  fontIdx: 1,
  readerDark: false,
  base: null,                // 文本基准简繁 'trad'|'simp'（open_book 返回）；null=无 OpenCC
  simp: false,               // 已切到与基准相反的语言（2026-09-05）
};

const FONTS = [17, 19, 22, 25];

/* ---------- 搜索 ---------- */
let _searchCache = [];   // 最近一次搜索的完整结果（下载按钮按索引取）

// 分类 → 源组（2026-09-05 少爷定稿：UI 只让用户选"书的类别"，源是内部实现）。
// 顺序 = chips 显示顺序；null = 全部源。libgen 为综合库，进每个具体分类。
const SOURCE_GROUPS = {
  '全部': null,
  '中文古籍': ['ctext', 'github', 'libgen'],
  '中文近代': ['wikisource', 'libgen'],
  '网络小说': ['biquge', 'libgen'],
  '外文原版': ['gutenberg', 'wikisource-en', 'libgen'],
};

async function loadSources() {
  try {
    const r = await BF.api('sources', {});
    // sources API 返回 [{name, label}]：label 用于结果卡片的来源徽标（分类 UI 不再暴露源名）
    state.catalog = r.sources || [];
    state.slabel = {};
    state.catalog.forEach((s) => { state.slabel[s.name] = s.label; });
    const chips = $('#source-chips');
    chips.innerHTML = '';
    Object.keys(SOURCE_GROUPS).forEach((g) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'chip' + (state.chip === g ? ' on' : '');
      b.dataset.group = g;
      b.textContent = g;  // 纯中文分类名，不带源名（2026-09-05 少爷定稿）
      b.onclick = () => {
        state.chip = g;
        chips.querySelectorAll('.chip').forEach((c) => c.classList.toggle('on', c.dataset.group === g));
        $('#search-q').focus();
      };
      chips.appendChild(b);
    });
  } catch (e) { /* 源列表失败不阻塞 */ }
}

const labelOf = (name) => (state.slabel && state.slabel[name]) || name;

async function doSearch(q) {
  const box = $('#search-results');
  box.innerHTML = '<p class="muted">搜索中…</p>';
  let r;
  try {
    r = await BF.api('search', {
      query: q,
      sources: state.chip === '全部' ? null : SOURCE_GROUPS[state.chip],
    });
  } catch (e) {
    box.innerHTML = `<p>搜索失败：${esc(e.message)}</p>`;
    return;
  }
  _searchCache = r.results || [];
  const meta = [];
  if (r.count) meta.push(`命中 ${r.count} 条`);
  Object.entries(r.errors || {}).forEach(([s, e]) =>
    meta.push(`<span class="badge warn" title="技术详情见日志 bookfetch.log">${esc(labelOf(s))}：${esc(e)}</span>`));
  $('#search-meta').innerHTML = meta.join(' ');
  if (!_searchCache.length) {
    box.innerHTML = '<p class="empty">没有结果——换个关键词，或换个书籍分类再试</p>';
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
    <div class="badges"><span class="badge" title="${esc(b.source)}">${esc(labelOf(b.source))}</span>${lic}</div>
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

/* ---------- 设置（网络代理，D1 addendum） ---------- */
const $settingsModal = () => $('#settings-modal');
$('#tab-settings').addEventListener('click', openSettings);

async function openSettings() {
  try {
    const r = await BF.api('settings_get', {});
    const p = (r.proxy || {});
    document.querySelectorAll('input[name="proxy-mode"]').forEach((el) => {
      el.checked = el.value === (p.mode || 'system');
    });
    $('#proxy-url').value = p.url || '';
    $('#proxy-url').disabled = (p.mode || 'system') !== 'manual';
  } catch { /* 保持默认值 */ }
  $settingsModal().classList.remove('hidden');
}

document.querySelectorAll('input[name="proxy-mode"]').forEach((el) => {
  el.addEventListener('change', () => {
    $('#proxy-url').disabled = el.value !== 'manual';
    if (el.value === 'manual' && !$('#proxy-url').value) {
      $('#proxy-url').value = 'http://127.0.0.1:7897';
    }
  });
});
$settingsModal().querySelector('.modal-x').addEventListener('click', () => $settingsModal().classList.add('hidden'));
$('#settings-save').addEventListener('click', async () => {
  const mode = document.querySelector('input[name="proxy-mode"]:checked').value;
  const url = $('#proxy-url').value.trim();
  const msg = $('#settings-msg');
  msg.textContent = '';
  try {
    await BF.api('settings_set', { proxy: { mode, url } });
    msg.textContent = '已保存，对之后的请求生效';
    msg.classList.add('ok');
    setTimeout(() => { msg.textContent = ''; msg.classList.remove('ok'); $settingsModal().classList.add('hidden'); }, 1200);
  } catch (e) {
    msg.textContent = '保存失败：' + (e.message || '');
    msg.classList.add('err');
  }
});
$settingsModal().addEventListener('click', (e) => {
  if (e.target === $settingsModal()) $settingsModal().classList.add('hidden');  // 点遮罩关闭
});

/* ---------- 下载任务面板 ---------- */
const _finished = { n: 0 };

function bumpBadge() {
  _finished.n += 1;
  const bd = $('#tasks-badge');
  bd.textContent = `${_finished.n} 项完成`;
  bd.classList.remove('hidden');
}

$('#tasks-toggle').addEventListener('click', () => {
  const t = $('#tasks');
  t.classList.toggle('collapsed');
  const icon = t.classList.contains('collapsed') ? '▸' : '▾';
  $('#tasks-toggle').textContent = icon;
});

function addTask(b, fmt) {
  const title = b.title || b.id;
  const box = $('#tasks');
  box.classList.remove('hidden', 'collapsed');  // 新任务自动展开
  $('#tasks-toggle').textContent = '▾';
  const isRaw = !!(b.extra && (b.extra.extension || b.extra.raw));
  const realFmt = isRaw ? '' : (fmt || 'txt');
  const t = document.createElement('div');
  t.className = 'task';
  t.innerHTML = `
    <div class="t-row"><span class="t-title" title="${esc(title)}">${esc(title)}</span>
      <span class="t-fmt">${esc(realFmt || '原文件')}</span></div>
    <div class="t-msg">排队中…</div>
    <div class="t-bar"><i style="width:0%"></i></div>
    <div class="t-ops"></div>`;
  $('#tasks-list').appendChild(t);
  BF.api('download', { source: b.source, id: b.id, title: b.title, fmt: realFmt })
    .then((r) => pollTask(r.task_id, t, { b, fmt: realFmt }))
    .catch((e) => {
      t.classList.add('err');
      t.querySelector('.t-msg').textContent = '无法开始下载：' + (e.message || '');
      const bar = t.querySelector('.t-bar'); if (bar) bar.remove();
    });
}

const taskOps = (el, html) => {
  const ops = el.querySelector('.t-ops');
  ops.innerHTML = html;
  return ops;
};

function pollTask(taskId, el, spec) {
  const tick = async () => {
    let r;
    try { r = await BF.api('task_status', { task_id: taskId }); }
    catch { setTimeout(tick, 1500); return; }  // 瞬断不杀轮询
    const msg = el.querySelector('.t-msg');
    const bar = el.querySelector('.t-bar');
    if (r.status === 'unknown') { el.remove(); return; }
    if (r.status === 'done') {
      el.classList.add('ok');
      msg.innerHTML = '完成';
      if (bar) bar.remove();
      taskOps(el, `<button class="mini open">打开阅读</button><button class="mini x" title="移除">✕</button>`)
        .querySelector('.open').onclick = () => { el.remove(); openReader(r.out_rel); };
      el.querySelector('.x').onclick = () => el.remove();
      bumpBadge();
      return;
    }
    if (r.status === 'error') {
      el.classList.add('err');
      msg.textContent = r.message || '下载失败';
      if (bar) bar.remove();
      taskOps(el, `<button class="mini retry">重试</button><button class="mini x" title="移除">✕</button>`)
        .querySelector('.retry').onclick = () => { el.remove(); addTask(spec.b, spec.fmt); };
      el.querySelector('.x').onclick = () => el.remove();
      return;
    }
    if (r.status === 'cancelled') {
      el.classList.add('cancelled');
      msg.textContent = '已取消';
      if (bar) bar.remove();
      taskOps(el, `<button class="mini x" title="移除">✕</button>`);
      el.querySelector('.x').onclick = () => el.remove();
      return;
    }
    // running：有 progress → 百分比进度；否则阶段文字 + 流动动画
    const i = bar && bar.querySelector('i');
    if (r.progress && r.progress.total) {
      const pct = Math.max(2, Math.round(r.progress.done / r.progress.total * 100));
      msg.textContent = `下载中 ${r.progress.done}/${r.progress.total}`;
      if (i) { i.style.width = pct + '%'; i.style.animation = 'none'; }
    } else {
      msg.textContent = r.message || '下载中…';
      if (bar) bar.classList.add('idle');
    }
    if (!el.querySelector('.t-ops .cancel')) {
      taskOps(el, `<button class="mini cancel">取消</button>`)
        .querySelector('.cancel').onclick = async () => {
          el.querySelector('.t-ops').innerHTML = '<span class="cancelling">取消中…</span>';
          try { await BF.api('cancel', { task_id: taskId }); } catch { /* 任务可能已完成 */ }
        };
    }
    setTimeout(tick, 1200);
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
      // 整本进度 = (已到章 + 本章内滚动比) / 总章数；单章书/无章数时不报 % 防误导
      let pp = null;
      if (b.chapters > 1) {
        pp = Math.min(100, Math.max(1, Math.round(((pg.chapter ?? 0) + (pg.pct || 0) / 1000) / b.chapters * 100)));
      }
      bar = pp != null ? `<span class="prog"><i style="width:${pp}%"></i></span>` : '';
      pos = `<span class="pos">第 ${ch} 章${pp != null ? ' · ' + pp + '%' : ''}</span>`;
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
function renderToc(chapters) {
  $('#toc-list').innerHTML = chapters.map((c) =>
    `<li data-i="${c.i}" title="${esc(c.title)}">${esc(c.title)}</li>`).join('');
}
async function openReader(rel) {
  let ob;
  try { ob = await BF.api('open_book', { rel }); }
  catch (e) { alert('打开失败：' + e.message); return; }
  state.book = ob; state.cur = 0; state.simp = false; state.base = ob.base;
  updateSimpBtn();
  $('#reader-title').textContent = ob.title;
  renderToc(ob.chapters);
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
  try { c = await BF.api('chapter', { rel: ob.rel, idx: state.cur, simp: state.simp }); }
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
  BF.api('progress_set', { rel: state.book.rel, chapter: state.cur, pct: Math.round(Math.min(1, Math.max(0, pct)) * 1000) });
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
function exitReader(view) {
  saveProgress(); state.book = null;
  $('#reader-toc').classList.add('hidden');           // 复位目录态
  $('#reader-toc-toggle').classList.remove('on');
  $('#reader-body').style.paddingLeft = '';
  showView(view);
}
$('#reader-back').addEventListener('click', () => exitReader('shelf'));
$('#reader-goto-search').addEventListener('click', () => exitReader('search'));
$('#toc-list').addEventListener('click', (e) => {
  const li = e.target.closest('li[data-i]');
  if (li) goChapter(+li.dataset.i);
});
$('#reader-toc-toggle').addEventListener('click', () => {
  const toc = $('#reader-toc');
  toc.classList.toggle('hidden');
  $('#reader-body').style.paddingLeft = toc.classList.contains('hidden') ? '' : '300px';
  $('#reader-toc-toggle').classList.toggle('on', !toc.classList.contains('hidden'));
});

/* 简繁切换：按钮标签 = 当前文本语言；on = 简体阅读态（简体=朱红高亮）。
   方向由后端按书基准决定：繁书→简(t2s)、简书→繁(s2t)——简书也可转繁读。 */
function updateSimpBtn() {
  const b = $('#reader-simp');
  if (!state.base) { b.classList.add('hidden'); return; }  // 未装 [simp] extra：不显示切换
  const nowSimp = (state.base === 'simp') ? !state.simp : state.simp;
  b.textContent = nowSimp ? '简' : '繁';
  b.classList.toggle('on', nowSimp);   // on = 正在读简体（朱红 + 下划线）
  b.title = nowSimp ? '当前简体，点击转繁体' : '当前繁体，点击转简体';
  b.classList.remove('hidden');
}
$('#reader-simp').addEventListener('click', async () => {
  if (!state.book) return;
  state.simp = !state.simp;
  updateSimpBtn();
  loadChapter();            // 正文先切（单章转换秒级完成，不等目录）
  try {
    const ob = await BF.api('open_book', { rel: state.book.rel, simp: state.simp });
    state.book.chapters = ob.chapters;
    renderToc(ob.chapters);             // 目录标题随后跟上
  } catch (e) {
    alert('切换失败：' + e.message);
    state.simp = !state.simp; updateSimpBtn(); loadChapter();
  }
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
  $('#reader-theme').classList.toggle('on', state.readerDark);
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
    if (d === '1') { state.readerDark = true; document.body.dataset.readerDark = '1'; $('#reader-theme').textContent = '☀️'; $('#reader-theme').classList.add('on'); }
    const t = localStorage.getItem('bf-theme');
    if (t) document.documentElement.dataset.theme = t;
    // URL 参数覆盖（?theme=dark / ?rdark=1）：预览与截图用
    const q = new URLSearchParams(location.search);
    if (q.get('theme') === 'dark') document.documentElement.dataset.theme = 'dark';
    if (q.get('rdark') === '1') { document.body.dataset.readerDark = '1'; $('#reader-theme').textContent = '☀️'; $('#reader-theme').classList.add('on'); }
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
