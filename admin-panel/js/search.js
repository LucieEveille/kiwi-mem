// ============================================================
// search.js — 顶栏全局参数搜索（v1.6.1 新增，当前 v1.6.2）
//
// 索引：所有配置项（中文标签 / key / 描述）+ 页面名。
// 选中参数 → 跳到所在功能页（必要时自动切到「参数」tab）→
// 滚动到该行并高亮 2 秒。页面文件无需任何改动。
// ============================================================
import { CONFIG_META, CONFIG_PAGES } from './config-schema.js';
import { ROUTE_INDEX } from './routes.js';

// CONFIG_PAGES 的 key 大多就是路由页；例外在此映射
const PAGE_ALIAS = { reminderTools: 'tools' };
// 这些页的参数区在 tab 里，跳转后需自动点开
const TAB_PAGES = { memories: 'settings', dream: 'settings', calendar: 'settings' };

let INDEX = null;

function keyPos(key) {
  for (const [pk, def] of Object.entries(CONFIG_PAGES)) {
    const page = PAGE_ALIAS[pk] || pk;
    if (def.master === key) return page;
    for (const g of def.groups) {
      if (g.master === key || (g.keys || []).includes(key)) return page;
    }
  }
  return 'rawconfig'; // 未编排 → 兜底页
}

function buildIndex() {
  if (INDEX) return INDEX;
  INDEX = [];
  for (const [key, meta] of Object.entries(ROUTE_INDEX)) {
    INDEX.push({ type:'page', icon: meta.icon, label: meta.label, sub: meta.group, page: key, hay: (meta.label + ' ' + key).toLowerCase() });
  }
  for (const [key, m] of Object.entries(CONFIG_META)) {
    const page = keyPos(key);
    const pageMeta = ROUTE_INDEX[page] || { label: page, icon: '⚙️' };
    INDEX.push({
      type:'param', icon: pageMeta.icon, label: m.label, key,
      sub: pageMeta.label + ' › ' + key, page,
      hay: (m.label + ' ' + key + ' ' + (m.desc || '')).toLowerCase(),
    });
  }
  return INDEX;
}

function search(q) {
  const needle = q.trim().toLowerCase();
  if (!needle) return [];
  const idx = buildIndex();
  // 标签/key 命中优先于描述命中
  const strong = [], weak = [];
  for (const e of idx) {
    const inLabel = e.label.toLowerCase().includes(needle) || (e.key || '').includes(needle);
    if (inLabel) strong.push(e);
    else if (e.hay.includes(needle)) weak.push(e);
  }
  return strong.concat(weak).slice(0, 8);
}

// ---------- 跳转 + 高亮 ----------
function findRow(key) {
  const el = document.querySelector(`[data-cfg][data-key="${CSS.escape(key)}"]`);
  return el ? el.closest('.cfg-row') || el.closest('.master') : null;
}

export function tryHighlight() {
  const key = sessionStorage.getItem('kiwi-hl');
  if (!key) return;
  let tries = 0;
  const timer = setInterval(() => {
    tries++;
    let row = findRow(key);
    if (row && row.offsetParent === null) {
      // 藏在未激活的 tab 面板里 → 自动切「参数」tab
      const page = keyPos(key);
      const tab = TAB_PAGES[page];
      if (tab) document.querySelector(`.pill-tab[data-tab="${tab}"]`)?.click();
      row = findRow(key);
    }
    if (row && row.offsetParent !== null) {
      clearInterval(timer);
      sessionStorage.removeItem('kiwi-hl');
      const content = document.getElementById('content');
      if (content) {
        const top = row.getBoundingClientRect().top - content.getBoundingClientRect().top + content.scrollTop;
        content.scrollTop = Math.max(0, top - 110);
      }
      row.classList.add('cfg-hl');
      setTimeout(() => row.classList.remove('cfg-hl'), 2400);
    } else if (tries > 30) { // 3 秒放弃
      clearInterval(timer);
      sessionStorage.removeItem('kiwi-hl');
    }
  }, 100);
}

function goTo(entry) {
  if (entry.type === 'param') sessionStorage.setItem('kiwi-hl', entry.key);
  const target = '#/' + entry.page;
  if (location.hash === target) tryHighlight(); // 同页：直接高亮
  else location.hash = target;                   // 异页：route() 完成后由 app.js 调 tryHighlight
}

// ---------- UI ----------
export function initSearch(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="gs-box">
      <span class="gs-icon">⌕</span>
      <input type="search" class="gs-input" id="gs-input" placeholder="搜索参数、页面、操作…  例：半衰期 / 提示词 / dream" autocomplete="off" spellcheck="false">
      <div class="gs-drop" id="gs-drop" hidden></div>
    </div>`;
  const input = container.querySelector('#gs-input');
  const drop = container.querySelector('#gs-drop');
  let results = [], cursor = -1;

  const render = () => {
    if (!results.length) {
      drop.innerHTML = input.value.trim()
        ? `<div class="gs-empty">没有匹配「${input.value.trim().replace(/</g,'&lt;')}」的参数或页面</div>` : '';
      drop.hidden = !input.value.trim();
      return;
    }
    drop.hidden = false;
    drop.innerHTML = results.map((r, i) => `
      <div class="gs-item ${i === cursor ? 'gs-cur' : ''}" data-i="${i}">
        <span class="gs-it-icon">${r.icon}</span>
        <span class="gs-it-main"><b>${r.label.replace(/</g,'&lt;')}</b><small>${r.sub.replace(/</g,'&lt;')}</small></span>
        <span class="gs-it-kind">${r.type === 'page' ? '页面' : '参数'}</span>
      </div>`).join('');
  };

  input.addEventListener('input', () => { results = search(input.value); cursor = -1; render(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); cursor = Math.min(cursor + 1, results.length - 1); render(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); cursor = Math.max(cursor - 1, 0); render(); }
    else if (e.key === 'Enter') { const r = results[cursor] ?? results[0]; if (r) { goTo(r); input.value = ''; results = []; render(); input.blur(); } }
    else if (e.key === 'Escape') { results = []; drop.hidden = true; input.blur(); }
  });
  drop.addEventListener('mousedown', (e) => {
    const item = e.target.closest('.gs-item');
    if (!item) return;
    e.preventDefault();
    goTo(results[Number(item.dataset.i)]);
    input.value = ''; results = []; drop.hidden = true;
  });
  document.addEventListener('mousedown', (e) => { if (!container.contains(e.target)) drop.hidden = true; });
  input.addEventListener('focus', () => { if (results.length) drop.hidden = false; });
}
