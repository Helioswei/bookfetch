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
  trOn: false,               // N3：当前章沉浸式译文中（原文+译文对照）
  trs: null,                 // 当前章译文数组（对齐 p.para 序号）
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
  bd.textContent = `${_finished.n}`;
  bd.title = `${_finished.n} 项下载完成`;
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

/* 书架「继续下载」：半成品（.txt.part）→ resume_partial → 断点续传任务。
   重启后任务列表已清（内存态），书架是半成品的恢复入口（a91ccf1 + 2026-09-05）。 */
async function resumeShelfTask(row) {
  const rel = row.dataset.rel;
  const box = $('#tasks');
  box.classList.remove('hidden', 'collapsed');   // 面板自动展开
  $('#tasks-toggle').textContent = '▾';
  const t = document.createElement('div');
  t.className = 'task';
  const name = rel.slice(0, -'.part'.length).replace(/\.txt$/, '');
  t.innerHTML = `
    <div class="t-row"><span class="t-title" title="${esc(name)}">${esc(name)}</span>
      <span class="t-fmt">txt</span></div>
    <div class="t-msg">恢复下载中…</div>
    <div class="t-bar"><i style="width:0%"></i></div>
    <div class="t-ops"></div>`;
  $('#tasks-list').appendChild(t);
  let r;
  try { r = await BF.api('resume_partial', { rel }); }
  catch (e) {
    t.classList.add('err');
    t.querySelector('.t-msg').textContent = '无法继续下载：' + (e.message || '');
    const bar = t.querySelector('.t-bar'); if (bar) bar.remove();
    return;
  }
  t.querySelector('.t-title').textContent = r.title || name;
  const tf = t.querySelector('.t-fmt'); if (r.fmt) tf.textContent = r.fmt;
  pollTask(r.task_id, t, { onRetry: () => resumeShelfTask(row) });
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
      if (!$('#view-shelf').classList.contains('hidden')) loadShelf();  // 半成品条目 → 正式书：书架即时换新
      return;
    }
    if (r.status === 'error') {
      el.classList.add('err');
      msg.textContent = r.message || '下载失败';
      if (bar) bar.remove();
      taskOps(el, `<button class="mini retry">重试</button><button class="mini x" title="移除">✕</button>`)
        .querySelector('.retry').onclick = () => {
          el.remove();
          // resume 任务：重试 = 再次从断点续传（不是全量重下）；默认 = 原任务重下
          if (spec.onRetry) { spec.onRetry(); return; }
          addTask(spec.b, spec.fmt);
        };
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
    if (r.status === 'queued') {
      msg.textContent = '排队中…（同时最多下 3 本）';
      bar.classList.add('idle');
      if (!el.querySelector('.t-ops .cancel')) {
        taskOps(el, `<button class="mini cancel">取消</button>`)
          .querySelector('.cancel').onclick = async () => {
            el.querySelector('.t-ops').innerHTML = '<span class="cancelling">取消中…</span>';
            try { await BF.api('cancel', { task_id: taskId }); } catch { /* 任务可能已完成 */ }
          };
      }
      setTimeout(tick, 1200);
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
    // B4 边下边读：已下部分可先读（库内 .part，断点续传不中断）
    if (r.partial_rel && !el.querySelector('.t-ops .open-part')) {
      const ops = el.querySelector('.t-ops');
      const btn = document.createElement('button');
      btn.className = 'mini open-part';
      btn.textContent = `读已下 ${r.progress ? r.progress.done : ''} 章`;
      btn.title = '下载完成前先读已抓到的章节（继续下载不受影响）';
      btn.onclick = () => { openReader(r.partial_rel); };
      ops.appendChild(btn);
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
    <div class="book-row${b.partial ? ' partial' : ''}" data-rel="${esc(b.rel)}" title="${b.partial ? '未完成下载 · 点击阅读已下部分；「继续下载」断点续传不重抓（下载完成后自动变正式书，进度保留）' : esc(b.title)}">
      <span class="t">${esc(b.title)}</span>
      <span class="fmt">${b.partial ? '<em class="warn">未完成</em>' : `${esc(b.format)} · ${b.size_kb} KB`}</span>
      ${b.partial ? '<button class="mini resume" data-act="resume" title="继续下载——从断点续传，已下部分不会重抓">继续下载</button>' : ''}
      ${bar}<button class="mini del" data-act="del" title="删除这本书（文件与阅读进度一并删除，不可恢复）">删除</button>${pos}
    </div>`;
  }).join('');
}
$('#shelf-books').addEventListener('click', (e) => {
  const resume = e.target.closest('button[data-act="resume"]');
  if (resume) { e.stopPropagation(); resumeShelfTask(resume.closest('.book-row')); return; }
  const del = e.target.closest('button[data-act="del"]');
  if (del) { e.stopPropagation(); delShelfBook(del.closest('.book-row')); return; }
  const row = e.target.closest('.book-row');
  if (row) openReader(row.dataset.rel);
});
$('#empty-go-search').addEventListener('click', (e) => { e.preventDefault(); showView('search'); });
$('#shelf-open-lib').addEventListener('click', async () => {
  try { await BF.api('open_library', {}); }
  catch (e) { alert('无法打开书库目录：' + (e.message || e)); }
});
/* 导入书籍：桌面壳走后端原生对话框（点击即弹，绕 WebKit file-input 首击丢失）；
   浏览器形态（后端无壳 hook）回退 HTML file input */
function showImportSummary(ok, bad) {
  if (!ok.length && !bad.length) return;
  alert([ok.length ? `已导入 ${ok.length} 本：${ok.join('、')}` : '',
         bad.length ? `导入失败 ${bad.length} 本：${bad.join('；')}` : ''].filter(Boolean).join('\n'));
}
async function pickImportFiles() {
  let r = null;
  try { r = await BF.api('import_dialog', {}); }
  catch (e) { /* 后端异常 → 回退 file input */ }
  if (!r || r.unavailable) { $('#shelf-import-input').click(); return; }  // 浏览器形态
  if (r.cancelled) return;                                  // 用户取消
  if ((r.imported || []).length) loadShelf();
  showImportSummary(r.imported || [], r.failed || []);
}
$('#shelf-import').addEventListener('click', pickImportFiles);
$('#shelf-import-input').addEventListener('change', (e) => {
  const files = [...(e.target.files || [])];
  if (files.length) importBooks(files);
  e.target.value = '';   // 允许重复选同一文件
});

/* 删除书架条目（文件 + 进度，不可恢复——原生 confirm 二次确认） */
async function delShelfBook(row) {
  const rel = row.dataset.rel;
  const title = row.querySelector('.t').textContent;
  if (!confirm(`删除「${title}」？\n将同时删除书籍文件与阅读进度，不可恢复。`)) return;
  try {
    await BF.api('delete_book', { rel });
    loadShelf();
  } catch (e) { alert('删除失败：' + (e.message || e)); }
}

/* 导入本地书：FileReader → base64 → import_book；多文件逐个，失败不中断 */
function blobToBase64(f) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(',')[1] || '');
    r.onerror = () => rej(new Error('文件读取失败'));
    r.readAsDataURL(f);
  });
}
async function importBooks(files) {
  const ok = [], bad = [];
  for (const f of files) {
    try {
      const r = await BF.api('import_book', { name: f.name, data: await blobToBase64(f) });
      ok.push(r.title);
    } catch (e) { bad.push(`${f.name}（${e.message || e}）`); }
  }
  loadShelf();
  showImportSummary(ok, bad);
}

/* ---------- 阅读器 ---------- */
function renderToc(chapters) {
  $('#toc-list').innerHTML = chapters.map((c) =>
    `<li data-i="${c.i}" title="${esc(c.title)}">${esc(c.title)}</li>`).join('');
}
async function openReader(rel) {
  let ob;
  try { ob = await BF.api('open_book', { rel }); }
  catch (e) { alert('打开失败：' + e.message); return; }
  state.book = ob; state.cur = 0; state.pct = 0; state.simp = false; state.base = ob.base;
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
  _trSeq++;            // 切章使在途翻译请求失效
  _trBusy = false;     // 复位翻译态（防旧章 busy 卡死按钮）
  resetTrBtn();
  const paras = c.text.split(/\n{2,}|\n(?=\S)/).map((s) => s.trim()).filter(Boolean)
    .filter((s) => s !== c.title && s !== '《' + c.title + '》');
  $('#reader-body').innerHTML = `<h1>${esc(c.title)}</h1>` +
    paras.map((p) => `<p class="para">${esc(p)}</p>`).join('');
  state.trs = null; state.trOn = false;
  updateTrBtn(c.dir || 'en2zh');   // N3：方向后端权威（chapter() 返 dir），按钮全显示
  document.querySelectorAll('#toc-list li').forEach((li) =>
    li.classList.toggle('cur', +li.dataset.i === state.cur));
  $('#reader-pos').textContent = `第 ${state.cur + 1} / ${ob.chapters.length} 章`;
  const el = $('#reader-body');
  // 定位：仅 openReader 续读恢复（pct>0）时按比例滚动；其余（切章/简繁切换）一律回顶。
  // 不用 rAF —— 后台/不可见标签页 rAF 被浏览器节流不触发（headless 实测），
  // 依赖它切章回顶会静默失效；innerHTML 后同步读 scrollHeight 强制布局即可得正确值。
  const max = el.scrollHeight - el.clientHeight;
  el.scrollTop = state.pct > 0 && max > 0 ? state.pct * max : 0;
  state.pct = 0;
  saveProgressSoon();
}

/* N3 双向翻译：沉浸式对照（原文每段下插译文；按钮=当前态，on=对照中）。
   方向由后端 trans_direction 权威判定（chapter()/translate() 返 dir），前端不自算；
   渲染 p.para 与后端 split_reader_paras 同一套切段规则（对齐序号）。 */
const TR_DIR_HINT = { en2zh: '英译中', zh2en: '中译英' };
let _trBusy = false;      // 翻译请求在途（按钮 busy）
let _trSeq = 0;           // 章代际：切章后旧响应丢弃
function resetTrBtn() {
  const b = $('#reader-tr');
  b.textContent = '译';
  b.classList.remove('on', 'busy');
  // 非 macOS 平台（open_book.translate=false）藏「译」钮；macOS 内桥/语言包
  // 引导走点「译」后的报错路径，不在此藏（藏了引导无从发生）
  b.classList.toggle('hidden', !state.book || state.book.translate === false);
  b.disabled = false;
  b.title = '翻译本章（沉浸对照，方向自动）';
}
function updateTrBtn(dir) {
  resetTrBtn();
  const d = TR_DIR_HINT[dir] || '自动';
  $('#reader-tr').title = `翻译本章（${d}，沉浸对照）`;
}
async function translateChapter() {
  const ob = state.book, cur = state.cur;
  if (!ob || _trBusy) return;
  const b = $('#reader-tr');
  const seq = ++_trSeq;
  _trBusy = true;
  b.textContent = '译中…'; b.classList.remove('on'); b.disabled = true;
  try {
    const r = await BF.api('translate', { rel: ob.rel, idx: cur });
    if (seq !== _trSeq || !state.book || state.cur !== cur) return; // 已切章，丢弃
    state.trs = r.trs || [];
    state.trOn = true;
    b.textContent = '译'; b.classList.add('on');
    const d = TR_DIR_HINT[r.dir] || '';
    b.title = `对照中（${d}），点击恢复原文`;
    renderTrs();
  } catch (e) {
    if (seq !== _trSeq) return;
    const msg = e.message || '系统翻译不可用';
    if (msg.includes('翻译语言包')) {
      // N3 首次引导：语言包未装 → 拉起 SwiftUI 准备器（pywebview 会话无下载权限）
      const ok = confirm('翻译需要 macOS 系统翻译语言包（中英双向，首次一次性下载约 1GB，之后完全离线）。\n\n点「确定」打开「翻译语言包准备器」完成首次安装；装好后回到这里再点「译」即可。');
      if (ok) {
        try { await BF.api('open_activator', {}); }
        catch (e2) { alert('打开准备器失败：' + (e2.message || '')); }
      }
    } else {
      alert('翻译失败：' + msg);
    }
  } finally {
    if (seq === _trSeq) { _trBusy = false; b.disabled = false; b.classList.remove('busy'); }
  }
}
function renderTrs() {
  const paras = [...document.querySelectorAll('#reader-body p.para')];
  if (!state.trs || paras.length !== state.trs.length) return; // 段数不符则放弃（保原文可读）
  paras.forEach((p, i) => {
    const t = state.trs[i];
    if (!t) return;
    const d = document.createElement('div');
    d.className = 'reader-tr';
    d.textContent = t;
    p.after(d);
  });
}
$('#reader-tr').addEventListener('click', () => {
  if (!state.book) return;
  if (state.trOn) {                 // 关对照回原文（不删译文缓存，重开不重翻）
    state.trOn = false; state.trs = null;
    document.querySelectorAll('#reader-body .reader-tr').forEach((n) => n.remove());
    resetTrBtn();
  } else {
    translateChapter();
  }
});

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
  state.pct = 0;   // 切章不继承旧章内滚动比例——新章必须从开头读
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
  // 图标 = 当前态（坑 35 铁律同款）：日间 ☀️ / 夜间 🌙 + on 红线——旧版是目标态
  // （白天显 🌙 提示可切夜）与简繁按钮语义相悖，实测被少爷抓包
  $('#reader-theme').textContent = state.readerDark ? '🌙' : '☀️';
  $('#reader-theme').classList.toggle('on', state.readerDark);
  $('#reader-theme').title = state.readerDark ? '夜间模式，点击回日间' : '日间模式，点击夜间阅读';
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
  syncThemeBtn();
});
function syncThemeBtn() {
  // 全局明/暗是持久二态开关：暗色时 🌗 亮红线（激活态语义与阅读页 🌙 一致）
  $('#tab-theme').classList.toggle('on', document.documentElement.dataset.theme === 'dark');
  $('#tab-theme').title = document.documentElement.dataset.theme === 'dark' ? '暗色模式，点击回亮色' : '亮色模式，点击暗色阅读';
}
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
    if (d === '1') { state.readerDark = true; document.body.dataset.readerDark = '1'; $('#reader-theme').textContent = '🌙'; $('#reader-theme').classList.add('on'); }
    const t = localStorage.getItem('bf-theme');
    if (t) document.documentElement.dataset.theme = t;
    // URL 参数覆盖（?theme=dark / ?rdark=1）：预览与截图用
    const q = new URLSearchParams(location.search);
    if (q.get('theme') === 'dark') document.documentElement.dataset.theme = 'dark';
    syncThemeBtn();  // 恢复/覆盖后同步 🌗 激活态与 title
    if (q.get('rdark') === '1') { document.body.dataset.readerDark = '1'; $('#reader-theme').textContent = '🌙'; $('#reader-theme').classList.add('on'); }
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
