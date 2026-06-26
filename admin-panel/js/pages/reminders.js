// ⏰ 提醒 — CRUD + 立即触发 + 启停（真实 HTTP 状态码）
import { get, post, put, del, escHtml, fmtDateTime } from '../api.js';
import { badge, emptyState, loadingBlock, toast, modal, confirmDialog, delegate, setBusy, ctl } from '../ui.js';

const REPEAT_OPTIONS = [
  { value: 'once', label: '单次' },
  { value: 'daily', label: '每天' },
  { value: 'weekly', label: '每周' },
  { value: 'monthly', label: '每月' },
  { value: 'yearly', label: '每年' },
];
const REPEAT_LABEL = Object.fromEntries(REPEAT_OPTIONS.map(o => [o.value, o.label]));

// ISO 字符串 → datetime-local 控件值（本地时区，去掉秒/时区）
function isoToLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
// datetime-local 值（本地）→ ISO 字符串
function localInputToIso(val) {
  if (!val) return '';
  const d = new Date(val);
  if (isNaN(d)) return '';
  return d.toISOString();
}

const STATUS_META = {
  pending: { label: '待触发', variant: 'info' },
  completed: { label: '已完成', variant: 'muted' },
  cancelled: { label: '已取消', variant: 'muted' },
  error: { label: '出错', variant: 'danger' },
};

export default {
  title: '提醒',

  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">提醒会在设定时间触发并推送给你。支持单次与按天/周/月/年重复；可随时手动触发或临时停用。</p>
      <div class="toolbar">
        <span class="muted text-sm" id="rem-count"></span>
        <span class="spacer"></span>
        <button class="btn btn-secondary" data-act="refresh">刷新</button>
        <button class="btn btn-primary" data-act="add">+ 新增提醒</button>
      </div>
      <div id="rem-list">${loadingBlock()}</div>
    `;

    delegate(root, {
      refresh: () => this.load(),
      add: () => this.editModal(null),
      edit: (el) => this.editModal(this.find(el.dataset.id)),
      del: (el) => this.remove(el.dataset.id),
      fire: (el) => this.fire(el.dataset.id, el),
      toggle: (el) => this.toggleEnabled(this.find(el.dataset.id)),
    });

    this.load();
  },

  find(id) { return (this.list || []).find(r => String(r.id) === String(id)); },

  async load() {
    const el = this.root.querySelector('#rem-list');
    el.innerHTML = loadingBlock();
    try {
      const data = await get('/reminders?all=true');
      this.list = Array.isArray(data) ? data : [];
      this.render();
    } catch (e) {
      el.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>${escHtml(e.message)}</div></div>`;
    }
  },

  render() {
    const el = this.root.querySelector('#rem-list');
    const countEl = this.root.querySelector('#rem-count');
    if (!this.list.length) {
      countEl.textContent = '';
      el.innerHTML = emptyState({ icon: '⏰', msg: '还没有提醒', hint: '点右上「新增提醒」设一个吧' });
      return;
    }
    countEl.textContent = `共 ${this.list.length} 条`;
    el.innerHTML = this.list.map(r => {
      const st = STATUS_META[r.status] || { label: r.status || '—', variant: 'muted' };
      const enabled = r.enabled !== false;
      return `
      <div class="item">
        <div class="item-row">
          <div style="flex:1;min-width:0">
            <div class="item-title">${escHtml(r.title || '（无标题）')} ${enabled ? '' : badge('已停用', 'muted')}</div>
            ${r.notes ? `<div class="text-sm muted clamp3" style="color:var(--text-soft)">${escHtml(r.notes)}</div>` : ''}
            <div class="btn-row mt8">
              <span class="badge badge-accent">🕒 ${escHtml(fmtDateTime(r.trigger_time))}</span>
              ${badge('🔁 ' + (REPEAT_LABEL[r.repeat_type] || r.repeat_type || 'once'), 'info')}
              ${badge(st.label, st.variant)}
              ${r.last_fired_at ? `<span class="faint text-xs">上次触发 ${escHtml(fmtDateTime(r.last_fired_at))}</span>` : ''}
            </div>
          </div>
          <div class="item-actions">
            <button class="btn btn-xs btn-primary" data-act="fire" data-id="${r.id}">立即触发</button>
            <button class="btn btn-xs btn-secondary" data-act="toggle" data-id="${r.id}">${enabled ? '停用' : '启用'}</button>
            <button class="btn btn-xs btn-secondary" data-act="edit" data-id="${r.id}">编辑</button>
            <button class="btn btn-xs btn-danger-soft" data-act="del" data-id="${r.id}">删除</button>
          </div>
        </div>
      </div>`;
    }).join('');
  },

  editModal(r) {
    const isNew = !r;
    const mod = modal({
      title: isNew ? '新增提醒' : `编辑提醒 #${r.id}`,
      body: `
        <div class="field"><label>标题 *</label>${ctl.text('title', r?.title || '', '提醒我做什么…')}</div>
        <div class="field"><label>备注</label>${ctl.area('notes', r?.notes || '', 3, '可选，补充细节…')}</div>
        <div class="grid grid-2">
          <div class="field"><label>触发时间 *</label>
            <input type="datetime-local" data-key="trigger_time" value="${isoToLocalInput(r?.trigger_time)}">
          </div>
          <div class="field"><label>重复</label>${ctl.select('repeat_type', r?.repeat_type || 'once', REPEAT_OPTIONS)}</div>
        </div>
        <div class="field"><label class="switch-row" style="display:flex;align-items:center;gap:10px;font-weight:500">
          <span>启用</span>${ctl.toggle('enabled', r ? r.enabled !== false : true)}
        </label></div>`,
      footer: `<button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>保存</button>`,
    });
    mod.root.querySelector('[data-cancel]').onclick = () => mod.close();
    mod.root.querySelector('[data-save]').onclick = async (ev) => {
      const title = mod.root.querySelector('[data-key="title"]').value.trim();
      const notes = mod.root.querySelector('[data-key="notes"]').value.trim();
      const localTime = mod.root.querySelector('[data-key="trigger_time"]').value;
      const repeat_type = mod.root.querySelector('[data-key="repeat_type"]').value;
      const enabled = mod.root.querySelector('[data-key="enabled"]').checked;
      if (!title) { toast('标题不能为空', 'err'); return; }
      if (!localTime) { toast('请选择触发时间', 'err'); return; }
      const trigger_time = localInputToIso(localTime);
      if (!trigger_time) { toast('触发时间无效', 'err'); return; }
      const body = { title, notes, trigger_time, repeat_type, enabled };
      if (isNew) { body.repeat_config = {}; body.status = 'pending'; }
      setBusy(ev.currentTarget, true, '保存中');
      try {
        if (isNew) await post('/reminders', body);
        else await put(`/reminders/${r.id}`, body);
        toast(isNew ? '提醒已创建' : '已更新'); mod.close(); this.load();
      } catch (e) { toast('保存失败：' + e.message, 'err'); setBusy(ev.currentTarget, false); }
    };
  },

  async remove(id) {
    if (!(await confirmDialog({ title: '删除提醒', message: '确定删除这条提醒？不可恢复。', danger: true, okText: '删除' }))) return;
    try { await del(`/reminders/${id}`); toast('已删除'); this.load(); }
    catch (e) { toast('删除失败：' + e.message, 'err'); }
  },

  async fire(id, btn) {
    setBusy(btn, true, '触发中');
    try {
      const r = await post(`/reminders/${id}/fire`);
      toast('已触发' + (r && r.repeat_type && r.repeat_type !== 'once' ? '（已重算下次时间）' : ''));
      this.load();
    } catch (e) { toast('触发失败：' + e.message, 'err'); setBusy(btn, false); }
  },

  async toggleEnabled(r) {
    if (!r) return;
    const next = !(r.enabled !== false);
    try {
      await put(`/reminders/${r.id}`, { enabled: next });
      toast(next ? '已启用' : '已停用');
      this.load();
    } catch (e) { toast('操作失败：' + e.message, 'err'); }
  },
};
