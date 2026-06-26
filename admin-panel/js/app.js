// ============================================================
// app.js — 应用外壳：侧栏 / 路由 / 主题 / 移动端
// 哈希路由 #/<key> → 懒加载 js/pages/<key>.js，调用 default.mount(root)
// ============================================================
import { NAV, ROUTE_INDEX } from './routes.js';
import { errorBlock, loadingBlock } from './ui.js';

const DEFAULT_ROUTE = 'dashboard';

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
let currentMod = null;
async function route() {
  const key = (location.hash.replace(/^#\/?/, '') || DEFAULT_ROUTE).split('?')[0];
  const meta = ROUTE_INDEX[key];
  const content = document.getElementById('content');
  const titleEl = document.getElementById('page-title');
  const crumbEl = document.getElementById('page-crumb');

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
  route();
}

boot();
