// ============================================================
// ui.js — 共享 UI 组件库
//
// 两类导出：
//   · 返回 HTML 字符串的纯函数（card / statCard / badge / field / cfgRow / emptyState …），
//     用模板字符串拼装，再 root.innerHTML = ...
//   · 副作用 DOM 工具（toast / modal / confirmDialog / delegate / setBusy …）
//
// 交互范式：元素加 data-act="动作" [data-id="…"]，页面用 delegate(root, {动作: (el,ev)=>{}}) 统一接管。
//   （取代旧面板满屏的全局 onclick="" — 那是「乱」的来源之一）
// ============================================================
import { escHtml, escAttr } from './api.js';

// ---------- Toast ----------
let toastWrap;
export function toast(msg, type = 'ok') {
  if (!toastWrap) {
    toastWrap = document.createElement('div');
    toastWrap.className = 'toast-wrap';
    document.body.appendChild(toastWrap);
  }
  const el = document.createElement('div');
  el.className = `toast toast-${type === true ? 'ok' : type === false ? 'err' : type}`;
  el.textContent = msg;
  toastWrap.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, 2600);
  setTimeout(() => el.remove(), 3000);
}
export const toastOk  = (m) => toast(m, 'ok');
export const toastErr = (m) => toast(m, 'err');

// ---------- String components ----------
export function spinner(cls = '') { return `<span class="spinner ${cls}"></span>`; }
export function loadingBlock(msg = '加载中…') { return `<div class="loading-block">${spinner()} ${escHtml(msg)}</div>`; }
export function emptyState({ icon = '🍃', msg = '暂无数据', hint = '' } = {}) {
  return `<div class="empty"><div class="icon">${icon}</div><div class="msg">${escHtml(msg)}</div>${hint ? `<div class="hint">${escHtml(hint)}</div>` : ''}</div>`;
}
export function errorBlock(msg) {
  return `<div class="banner banner-warn"><span>⚠️</span><div>${escHtml(msg)}</div></div>`;
}
export function badge(text, variant = '') {
  return `<span class="badge ${variant ? 'badge-' + variant : ''}">${escHtml(text)}</span>`;
}
export function card({ title = '', desc = '', actions = '', body = '', id = '', cls = '' } = {}) {
  const head = (title || actions || desc)
    ? `<div class="card-head"><div>${title ? `<div class="card-title">${escHtml(title)}</div>` : ''}${desc ? `<div class="card-desc">${desc}</div>` : ''}</div>${actions ? `<div class="btn-row">${actions}</div>` : ''}</div>`
    : '';
  return `<div class="card ${cls}" ${id ? `id="${id}"` : ''}>${head}${body}</div>`;
}
export function statCard({ label = '', value = '-', cls = '', sub = '', id = '' } = {}) {
  return `<div class="stat"><div class="label">${label}</div><div class="value ${cls}" ${id ? `id="${id}"` : ''}>${value}</div>${sub ? `<div class="sub">${sub}</div>` : ''}</div>`;
}
export function field({ label = '', hint = '', control = '', id = '' } = {}) {
  return `<div class="field" ${id ? `id="${id}"` : ''}>${label ? `<label>${escHtml(label)}</label>` : ''}${control}${hint ? `<div class="field-hint">${hint}</div>` : ''}</div>`;
}
export function kv(k, v) { return `<div class="kv"><span class="k">${escHtml(k)}</span><span class="v">${v}</span></div>`; }

// 模块总开关：放在每个功能页最顶部，醒目的开/关 + 一句话说明。
// 关掉时下方旋钮区会自动变暗（给 .knobs 容器加 .dimmed）。
export function masterSwitch({ key, label, on, desc = '', emoji = '' } = {}) {
  return `<div class="master ${on ? 'on' : 'off'}" data-master="${key}">
    <div class="master-info">
      <div class="master-title">${emoji ? emoji + ' ' : ''}${escHtml(label)}
        <span class="master-state">${on ? '已启用' : '已关闭'}</span>
      </div>
      ${desc ? `<div class="master-desc">${desc}</div>` : ''}
    </div>
    <label class="switch switch-lg"><input type="checkbox" data-key="${key}" data-cfg data-bool ${on ? 'checked' : ''}><span class="slider"></span></label>
  </div>`;
}

// 一行配置项：label + 控件 + 说明（解决「忘了参数干嘛的」）
export function cfgRow({ key, label, control, desc = '', def = '' } = {}) {
  return `<div class="cfg-row">
    <div><div class="cfg-label">${escHtml(label || key)}</div><div class="cfg-key">${escHtml(key)}</div></div>
    <div class="cfg-control">
      <div class="cfg-input-line">${control}</div>
      ${desc || def ? `<div class="cfg-desc">${desc}${def ? ` <span class="cfg-default">默认：${escHtml(def)}</span>` : ''}</div>` : ''}
    </div>
  </div>`;
}

// 表单控件字符串（带 data-key，便于读取）
export const ctl = {
  text:   (key, val, ph = '') => `<input type="text" data-key="${key}" value="${escAttr(val ?? '')}" placeholder="${escAttr(ph)}">`,
  pass:   (key, val, ph = '') => `<input type="password" data-key="${key}" value="${escAttr(val ?? '')}" placeholder="${escAttr(ph)}">`,
  num:    (key, val, step = '1') => `<input type="number" data-key="${key}" value="${escAttr(val ?? '')}" step="${step}">`,
  area:   (key, val, rows = 4, ph = '') => `<textarea data-key="${key}" rows="${rows}" placeholder="${escAttr(ph)}">${escHtml(val ?? '')}</textarea>`,
  areaMono:(key, val, rows = 8, ph = '') => `<textarea class="mono" data-key="${key}" rows="${rows}" spellcheck="false" placeholder="${escAttr(ph)}">${escHtml(val ?? '')}</textarea>`,
  toggle: (key, on) => `<label class="switch"><input type="checkbox" data-key="${key}" ${on ? 'checked' : ''}><span class="slider"></span></label>`,
  select: (key, val, options) => `<select data-key="${key}">${options.map(o => {
    const v = typeof o === 'string' ? o : o.value, t = typeof o === 'string' ? o : o.label;
    return `<option value="${escAttr(v)}" ${String(v) === String(val) ? 'selected' : ''}>${escHtml(t)}</option>`;
  }).join('')}</select>`,
};

// ---------- Button busy state ----------
export function setBusy(btn, busy, busyText) {
  if (!btn) return;
  if (busy) {
    btn.dataset._txt = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `${spinner()} ${busyText || btn.textContent.trim()}`;
  } else {
    btn.disabled = false;
    if (btn.dataset._txt != null) { btn.innerHTML = btn.dataset._txt; delete btn.dataset._txt; }
  }
}

// ---------- Event delegation ----------
// delegate(root, { edit:(el,ev)=>{}, del:(el,ev)=>{} }, 'click')
export function delegate(root, handlers, evType = 'click') {
  root.addEventListener(evType, (e) => {
    const t = e.target.closest('[data-act]');
    if (!t || !root.contains(t)) return;
    const fn = handlers[t.dataset.act];
    if (fn) { e.preventDefault(); fn(t, e); }
  });
}

// ---------- Modal ----------
export function modal({ title = '', body = '', footer = '', wide = false, onClose } = {}) {
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  mask.innerHTML = `<div class="modal ${wide ? 'wide' : ''}">
    <div class="modal-head"><h3>${escHtml(title)}</h3><button class="modal-close" data-close>&times;</button></div>
    <div class="modal-body"></div>
    ${footer ? `<div class="modal-foot">${footer}</div>` : ''}
  </div>`;
  const bodyEl = mask.querySelector('.modal-body');
  if (typeof body === 'string') bodyEl.innerHTML = body; else bodyEl.appendChild(body);
  const close = () => { mask.remove(); document.removeEventListener('keydown', onKey); onClose && onClose(); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  mask.addEventListener('mousedown', (e) => { if (e.target === mask) close(); });
  mask.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) close(); });
  document.addEventListener('keydown', onKey);
  document.body.appendChild(mask);
  return { root: mask, body: bodyEl, close };
}

export function confirmDialog({ title = '确认', message = '', okText = '确定', danger = false } = {}) {
  return new Promise((resolve) => {
    const m = modal({
      title,
      body: `<div style="font-size:14px;line-height:1.7;color:var(--text-soft)">${escHtml(message)}</div>`,
      footer: `<button class="btn btn-secondary" data-no>取消</button><button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-yes>${escHtml(okText)}</button>`,
      onClose: () => resolve(false),
    });
    m.root.querySelector('[data-yes]').addEventListener('click', () => { m.close(); resolve(true); });
    m.root.querySelector('[data-no]').addEventListener('click', () => m.close());
  });
}

// 读取一个容器内所有 [data-key] 控件的值 → 对象
export function readForm(root) {
  const out = {};
  root.querySelectorAll('[data-key]').forEach(el => {
    const k = el.dataset.key;
    if (el.type === 'checkbox') out[k] = el.checked;
    else if (el.type === 'number') out[k] = el.value === '' ? '' : Number(el.value);
    else out[k] = el.value;
  });
  return out;
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('已复制'); }
  catch { toast('复制失败', 'err'); }
}
