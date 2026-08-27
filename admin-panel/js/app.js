// ============================================================
// app.js — 应用外壳：侧栏 / 路由 / 主题 / 移动端（v1.6.2）
// 哈希路由 #/<key> → 懒加载 js/pages/<key>.js，调用 default.mount(root)
//
// 本次改版：
//   · 顶栏挂载全局参数搜索（search.js）；路由完成后 tryHighlight()
//     完成「搜索 → 跳页 → 高亮参数行」闭环。
//   · 每页顶部渲染讲解条（routes.js 的 LEDES），页面自身的
//     .page-intro 由 CSS 隐藏，页面文件无需改动。
//   · REMOVED 增加 prompts（提示词回归各功能页）。
//   · boot 时检查是否需要首次配置向导（wizard.js）。
// ============================================================
import { NAV, ROUTE_INDEX, LEDES } from './routes.js';
import { errorBlock, loadingBlock } from './ui.js';
import { get } from './api.js';
import { initSearch, tryHighlight } from './search.js';
import { maybeShowWizard } from './wizard.js';
import {
  bindProjectChanges,
  createNavVisibilityController,
  shouldHide,
} from './nav-visibility.mjs';

const DEFAULT_ROUTE = 'dashboard';

// 已从管理面板移除的旧路由 → key:中文名。命中后给明确提示，不再静默跳仪表盘。
const REMOVED = {
  journey: '消息旅程',
  fileextract: '文件提取',
  reminders: '提醒',
  comments: '评论',
  search: '对话搜索',
  phrases: '指令与短语',
  prompts: '提示词模板',
};
// 移除页的去处说明（比「已交给客户端」更具体）
const REMOVED_HINT = {
  prompts: '提示词已跟随各自的功能页：记忆提取在「记忆碎片」、Dream 在「Dream」、各级总结在「日历与整理」……用顶栏搜索「提示词」能列出全部。',
};

// ---------- 主题 ----------
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('kiwi-theme', t);
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = t === 'dark' ? '☀️' : '🌙';
}
function initTheme() {
  const saved = localStorage.getItem('kiwi-theme')
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  applyTheme(saved);
}

// ---------- 侧栏 ----------
function renderSidebar() {
  const nav = document.getElementById('sidebar-nav');
  nav.innerHTML = NAV.map(grp => `
    ${grp.title ? `<div class="nav-group-title">${grp.title}</div>` : ''}
    <div class="nav-group">
      ${grp.items.map(it => `
        <a class="nav-item" href="#/${it.key}" data-key="${it.key}">
          <span class="ico">${it.icon}</span><span class="nav-label">${it.label}</span>
        </a>`).join('')}
    </div>`).join('');
}

const conditionalNavItems = NAV.flatMap(group => group.items)
  .filter(item => item.hideWhenEmpty);
const navVisibilityController = createNavVisibilityController({
  items: conditionalNavItems,
  fetchVisibility: async item => {
    try { return shouldHide(await get(item.hideWhenEmpty)); } catch { return false; }
  },
  navRoot: () => document.getElementById('sidebar-nav'),
});

export function refreshNavVisibility() {
  return navVisibilityController.refresh();
}

function highlight(key) {
  document.querySelectorAll('.nav-item').forEach(a =>
    a.classList.toggle('active', a.dataset.key === key));
}

// ---------- 路由 ----------
async function refreshShellStatus() {
  const pill = document.getElementById('status-pill');
  const foot = document.getElementById('foot-version');
  try {
    const status = await get('/');
    if (pill) {
      // 版本号在侧栏底部已经有一份，顶栏胶囊只说「通不通」，不重复显示版本。
      pill.textContent = '● 运行中';
      pill.className = 'badge badge-accent';
    }
    if (foot && status.version) foot.textContent = status.version;
  } catch {
    if (pill) {
      pill.textContent = '● 离线';
      pill.className = 'badge badge-danger';
    }
  }
}

// 每页讲解条（LEDES 有数据才渲染）
function ledeHtml(key) {
  const lede = LEDES[key];
  const meta = ROUTE_INDEX[key];
  if (!lede || !meta) return '';
  return `<div class="page-lede">
    <span class="page-lede-ico">${meta.icon}</span>
    <div><div class="page-lede-t">${lede[0]}</div><div class="page-lede-s">${lede[1]}</div></div>
  </div>`;
}

let currentMod = null;
async function route() {
  const key = (location.hash.replace(/^#\/?/, '') || DEFAULT_ROUTE).split('?')[0];
  const meta = ROUTE_INDEX[key];
  const content = document.getElementById('content');
  const titleEl = document.getElementById('page-title');
  const crumbEl = document.getElementById('page-crumb');

  if (REMOVED[key]) {
    highlight('');
    titleEl.textContent = '页面已移除';
    crumbEl.textContent = 'kiwi-mem';
    document.title = '页面已移除 · Kiwi-Mem';
    content.scrollTop = 0;
    closeSidebar();
    try { currentMod?.unmount?.(); } catch {}
    currentMod = null;
    const hint = REMOVED_HINT[key] || '相关功能已交给客户端。';
    content.innerHTML = `<div class="banner banner-info"><span>💡</span><div>「${REMOVED[key]}」已从管理面板移除。${hint} <a href="#/${DEFAULT_ROUTE}">返回仪表盘</a></div></div>`;
    return;
  }

  if (!meta) { location.hash = '#/' + DEFAULT_ROUTE; return; }

  highlight(key);
  titleEl.textContent = `${meta.icon} ${meta.label}`;
  crumbEl.textContent = meta.group || 'kiwi-mem';
  document.title = `${meta.label} · Kiwi-Mem`;
  content.scrollTop = 0;
  content.innerHTML = loadingBlock();
  closeSidebar();

  try { currentMod?.unmount?.(); } catch {}
  currentMod = null;

  try {
    const mod = (await import(`./pages/${key}.js`)).default;
    currentMod = mod;
    content.innerHTML = ledeHtml(key);
    const wrap = document.createElement('div');
    wrap.className = 'fade-in';
    content.appendChild(wrap);
    await mod.mount(wrap, { key });
    tryHighlight(); // 搜索跳转来的：滚动 + 高亮目标参数行
  } catch (e) {
    console.error(e);
    content.innerHTML = errorBlock(`页面加载失败：${e.message}。该模块可能尚未实现或后端不可用。`);
  }
}

// ---------- 移动端侧栏 ----------
function openSidebar()  { document.getElementById('sidebar')?.classList.add('open'); document.getElementById('sb-backdrop')?.classList.add('show'); }
function closeSidebar() { document.getElementById('sidebar')?.classList.remove('open'); document.getElementById('sb-backdrop')?.classList.remove('show'); }

// ---------- 启动 ----------
function boot() {
  initTheme();
  renderSidebar();
  initSearch(document.getElementById('global-search'));
  bindProjectChanges(window, refreshNavVisibility);
  refreshNavVisibility();
  document.getElementById('theme-btn')?.addEventListener('click', () => {
    applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  });
  document.getElementById('menu-btn')?.addEventListener('click', openSidebar);
  document.getElementById('sb-backdrop')?.addEventListener('click', closeSidebar);
  window.addEventListener('hashchange', route);
  if (!location.hash) location.hash = '#/' + DEFAULT_ROUTE;
  refreshShellStatus();
  route();
  maybeShowWizard(); // 首次使用 & 没有供应商时弹三步向导（可跳过）
}

boot();
