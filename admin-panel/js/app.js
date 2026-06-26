// ============================================================
// app.js — 应用外壳：侧栏 / 路由 / 主题 / 移动端
// 哈希路由 #/<key> → 懒加载 js/pages/<key>.js，调用 default.mount(root)
// ============================================================
import { NAV, ROUTE_INDEX } from './routes.js';
import { errorBlock, loadingBlock } from './ui.js';
import { get } from './api.js';

const DEFAULT_ROUTE = 'dashboard';

// 已从管理面板移除的旧路由 → key:中文名。命中后给明确提示，不再静默跳仪表盘。
const REMOVED = {
  journey: '消息旅程',
  fileextract: '文件提取',
  reminders: '提醒',
  comments: '评论',
  search: '对话搜索',
  phrases: '指令与短语',
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
      pill.textContent = status.version ? '● ' + status.version : '● 运行中';
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

let currentMod = null;
async function route() {
  const key = (location.hash.replace(/^#\/?/, '') || DEFAULT_ROUTE).split('?')[0];
  const meta = ROUTE_INDEX[key];
  const content = document.getElementById('content');
  const titleEl = document.getElementById('page-title');
  const crumbEl = document.getElementById('page-crumb');

  // 已移除的旧路由：给明确提示并提供返回链接，而非静默跳仪表盘。
  if (REMOVED[key]) {
    highlight('');
    titleEl.textContent = '页面已移除';
    crumbEl.textContent = 'kiwi-mem';
    document.title = '页面已移除 · Kiwi-Mem';
    content.scrollTop = 0;
    closeSidebar();
    try { currentMod?.unmount?.(); } catch {}
    currentMod = null;
    content.innerHTML = `<div class="banner banner-info"><span>💡</span><div>「${REMOVED[key]}」已从管理面板移除（相关功能已交给客户端）。<a href="#/${DEFAULT_ROUTE}">返回仪表盘</a></div></div>`;
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

  // 卸载上一个页面
  try { currentMod?.unmount?.(); } catch {}
  currentMod = null;

  try {
    const mod = (await import(`./pages/${key}.js`)).default;
    currentMod = mod;
    content.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'fade-in';
    content.appendChild(wrap);
    await mod.mount(wrap, { key });
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
  document.getElementById('theme-btn')?.addEventListener('click', () => {
    applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  });
  document.getElementById('menu-btn')?.addEventListener('click', openSidebar);
  document.getElementById('sb-backdrop')?.addEventListener('click', closeSidebar);
  window.addEventListener('hashchange', route);
  if (!location.hash) location.hash = '#/' + DEFAULT_ROUTE;
  refreshShellStatus();
  route();
}

boot();
