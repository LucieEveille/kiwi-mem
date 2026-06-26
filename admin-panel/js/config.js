// ============================================================
// config.js — 配置渲染 + 即时保存（所有功能页共用）
//
// 用法（功能页）：
//   import { loadConfig, renderConfigPage, wireConfig } from '../config.js';
//   const cfg = await loadConfig();
//   root.innerHTML = renderConfigPage('memories', cfg, { emoji:'🧩', label:'记忆系统' });
//   wireConfig(root, cfg);
//
// 控件改动即时 PUT /admin/config/{key}，无需保存按钮。总开关联动变暗下方旋钮。
// ============================================================
import { get, put, post, escHtml } from './api.js';
import { toast, cfgRow, ctl, masterSwitch, modal, setBusy } from './ui.js';
import { CONFIG_META, CONFIG_PAGES, RESTORABLE_PROMPTS } from './config-schema.js';

export async function loadConfig() {
  const data = await get('/admin/config');
  const raw = data.config || data;
  const flat = {};
  for (const [k, v] of Object.entries(raw)) {
    flat[k] = (v && typeof v === 'object' && 'value' in v) ? v.value : v;
  }
  return flat;
}

export async function saveConfig(key, value) {
  await put(`/admin/config/${key}`, { value: String(value ?? '') });
}

// 单个 key 的控件（带 data-cfg + data-key，供 wireConfig 自动保存）
function controlFor(key, val) {
  const m = CONFIG_META[key] || { input: 'text' };
  const v = val ?? '';
  const attr = `data-cfg data-key="${key}"`;
  switch (m.input) {
    case 'bool':
      return `<label class="switch"><input type="checkbox" ${attr} data-bool ${String(v) === 'true' ? 'checked' : ''}><span class="slider"></span></label>`;
    case 'int':
      return `<input type="number" step="1" ${attr} value="${escHtml(v)}">`;
    case 'float':
      return `<input type="number" step="0.01" ${attr} value="${escHtml(v)}">`;
    case 'pass':
      return `<input type="password" ${attr} value="${escHtml(v)}" placeholder="••••••">`;
    case 'model':
      return `<input type="text" list="model-datalist" ${attr} value="${escHtml(v)}" placeholder="留空跟随聊天模型">`;
    case 'json':
      return `<textarea class="mono" ${attr} rows="4" spellcheck="false" placeholder="JSON">${escHtml(v)}</textarea>`;
    case 'prompt':
      return promptControl(key, v);
    default:
      return `<input type="text" ${attr} value="${escHtml(v)}">`;
  }
}

function promptControl(key, val) {
  const preview = val ? escHtml(String(val).slice(0, 50)) + (String(val).length > 50 ? '…' : '') : '（空·用内置默认）';
  const restorable = RESTORABLE_PROMPTS.includes(key);
  // 用隐藏输入承载实际值，供 readForm / 保存读取
  return `<div class="prompt-ctl">
    <input type="hidden" data-cfg data-key="${key}" data-prompt value="${escHtml(val)}">
    <button class="btn btn-sm btn-secondary" data-act="editPrompt" data-id="${key}">✎ 编辑</button>
    ${restorable ? `<button class="btn btn-sm btn-ghost" data-act="restorePrompt" data-id="${key}">恢复默认</button>` : ''}
    <span class="prompt-preview faint text-xs" data-preview="${key}">${preview}</span>
  </div>`;
}

function rowFor(key, val) {
  const m = CONFIG_META[key];
  if (!m) return cfgRow({ key, label: key, control: controlFor(key, val), desc: '（未登记的配置项）' });
  return cfgRow({ key, label: m.label, control: controlFor(key, val), desc: m.desc || '', def: (m.def !== '' ? m.def : '') });
}

function groupHtml(group, cfg) {
  const inner = (group.keys || []).map(k => rowFor(k, cfg[k])).join('');
  const masterHtml = group.master
    ? masterSwitch({ key: group.master, label: (CONFIG_META[group.master]?.label || group.master), on: String(cfg[group.master]) === 'true', desc: CONFIG_META[group.master]?.desc || '' })
    : '';
  const body = `<div class="card-title">${escHtml(group.title)}</div>${group.desc ? `<div class="card-desc">${escHtml(group.desc)}</div>` : ''}
    ${masterHtml}
    <div class="knobs" ${group.master ? `data-knobs-for="${group.master}"` : ''}>${inner}</div>`;
  return `<div class="card">${body}</div>`;
}

// 渲染整页：顶部 master 总开关 + 各分组旋钮
export function renderConfigPage(pageKey, cfg, { emoji = '', label = '' } = {}) {
  const page = CONFIG_PAGES[pageKey];
  if (!page) return '';
  let html = '';
  if (page.master) {
    const m = CONFIG_META[page.master] || {};
    html += masterSwitch({ key: page.master, label: label || m.label, emoji, on: String(cfg[page.master]) === 'true', desc: m.desc || '' });
    html += `<div class="knobs" data-knobs-for="${page.master}">`;
    html += (page.groups || []).map(g => groupHtml(g, cfg)).join('');
    html += `</div>`;
  } else {
    html += (page.groups || []).map(g => groupHtml(g, cfg)).join('');
  }
  return html;
}

// 只渲染分组（无页级 master），给需要混排的页面用
export function renderConfigGroups(pageKey, cfg) {
  const page = CONFIG_PAGES[pageKey];
  if (!page) return '';
  return (page.groups || []).map(g => groupHtml(g, cfg)).join('');
}

// 自动保存 + 总开关联动 + prompt 编辑
export function wireConfig(root, cfg) {
  const applyDim = (key, on) => {
    const box = root.querySelector(`[data-knobs-for="${key}"]`);
    if (box) box.classList.toggle('dimmed', !on);
    const master = root.querySelector(`.master input[data-key="${key}"]`)?.closest('.master');
    if (master) master.classList.toggle('on', on), master.classList.toggle('off', !on);
    const state = master?.querySelector('.master-state');
    if (state) state.textContent = on ? '已启用' : '已关闭';
  };
  // 初始 dim
  root.querySelectorAll('[data-knobs-for]').forEach(box => {
    const key = box.dataset.knobsFor;
    applyDim(key, String(cfg[key]) === 'true');
  });

  root.addEventListener('change', async (e) => {
    const el = e.target.closest('[data-cfg][data-key]');
    if (!el || el.dataset.prompt !== undefined) return; // prompt 走弹窗保存
    const key = el.dataset.key;
    const isBool = el.dataset.bool !== undefined || el.type === 'checkbox';
    const value = isBool ? (el.checked ? 'true' : 'false') : el.value;
    if (isBool) applyDim(key, el.checked);
    flashStatus(el, 'saving');
    try {
      await saveConfig(key, value);
      cfg[key] = value;
      flashStatus(el, 'ok');
    } catch (err) {
      flashStatus(el, 'fail', err.message);
      toast(`「${CONFIG_META[key]?.label || key}」保存失败：${err.message}`, 'err');
      if (isBool) { el.checked = !el.checked; applyDim(key, el.checked); } // 回滚开关，避免界面骗人
    }
  });

  // Enter 即保存（触发 change）
  root.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.matches('input[data-cfg]:not([type=checkbox])')) { e.preventDefault(); e.target.blur(); }
  });

  // prompt 编辑 / 恢复默认
  root.addEventListener('click', async (e) => {
    const edit = e.target.closest('[data-act="editPrompt"]');
    const restore = e.target.closest('[data-act="restorePrompt"]');
    if (edit) { e.preventDefault(); openPromptEditor(root, edit.dataset.id, cfg); }
    if (restore) {
      e.preventDefault();
      const key = restore.dataset.id;
      try {
        await post(`/admin/restore-prompt/${key}`);
        const fresh = await loadConfig();
        cfg[key] = fresh[key];
        updatePromptUI(root, key, cfg[key]);
        toast('已恢复内置默认');
      } catch (err) { toast(`恢复失败：${err.message}`, 'err'); }
    }
  });
}

// 保存状态反馈：saving / ok / fail。fail 持久显示并把控件标红，让用户明确知道没存上。
function flashStatus(el, state, msg) {
  const host = el.closest('.cfg-control') || el.closest('.master')?.querySelector('.master-info') || el.parentElement;
  if (!host) return;
  let tag = host.querySelector('.cfg-saved');
  if (!tag) { tag = document.createElement('span'); tag.className = 'cfg-saved'; host.appendChild(tag); }
  clearTimeout(tag._t);
  el.classList.remove('invalid');
  tag.classList.remove('fail');
  if (state === 'saving') { tag.textContent = '保存中…'; tag.classList.add('show'); return; }
  if (state === 'ok') {
    tag.textContent = '✓ 已保存'; tag.classList.add('show');
    tag._t = setTimeout(() => tag.classList.remove('show'), 1600);
  } else {
    tag.textContent = '✗ 保存失败：' + (msg || '未知错误');
    tag.classList.add('show', 'fail');
    el.classList.add('invalid');
  }
}

function updatePromptUI(root, key, val) {
  const hidden = root.querySelector(`input[data-key="${key}"][data-prompt]`);
  if (hidden) hidden.value = val ?? '';
  const prev = root.querySelector(`[data-preview="${key}"]`);
  if (prev) prev.textContent = val ? String(val).slice(0, 50) + (String(val).length > 50 ? '…' : '') : '（空·用内置默认）';
}

function openPromptEditor(root, key, cfg) {
  const m = CONFIG_META[key] || {};
  const val = cfg[key] ?? '';
  const restorable = RESTORABLE_PROMPTS.includes(key);
  const mod = modal({
    title: m.label || key,
    wide: true,
    body: `${m.desc ? `<div class="card-desc mb12">${escHtml(m.desc)}</div>` : ''}
      <textarea class="mono" id="prompt-edit-area" rows="20" spellcheck="false">${escHtml(val)}</textarea>`,
    footer: `${restorable ? `<button class="btn btn-ghost" data-restore>恢复默认</button>` : ''}<span class="spacer"></span><button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>保存</button>`,
  });
  const area = mod.root.querySelector('#prompt-edit-area');
  mod.root.querySelector('[data-cancel]').addEventListener('click', () => mod.close());
  mod.root.querySelector('[data-save]').addEventListener('click', async (ev) => {
    const btn = ev.currentTarget; setBusy(btn, true, '保存中');
    try {
      await saveConfig(key, area.value);
      cfg[key] = area.value;
      updatePromptUI(root, key, area.value);
      toast('已保存'); mod.close();
    } catch (err) { toast(`保存失败：${err.message}`, 'err'); setBusy(btn, false); }
  });
  mod.root.querySelector('[data-restore]')?.addEventListener('click', async () => {
    try { await post(`/admin/restore-prompt/${key}`); const fresh = await loadConfig(); area.value = fresh[key] ?? ''; toast('已载入内置默认（记得保存）'); }
    catch (err) { toast(`恢复失败：${err.message}`, 'err'); }
  });
}

// 提供给页面：往 <head> 注入一个 datalist 供 model 输入框补全
export async function ensureModelDatalist() {
  if (document.getElementById('model-datalist')) return;
  const dl = document.createElement('datalist');
  dl.id = 'model-datalist';
  document.body.appendChild(dl);
  try {
    const data = await get('/admin/all-saved-models');
    dl.innerHTML = (data.models || []).map(m => `<option value="${escHtml(m.model_id)}">${escHtml(m.display_name || m.model_id)} · ${escHtml(m.provider_name || '')}</option>`).join('');
  } catch {}
}
