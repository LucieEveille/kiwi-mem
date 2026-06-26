// 📅 日历与整理 — 总开关 + 日历浏览/编辑 + 各级生成 + 参数（pill-tabs）
import { get, put, del, escHtml, escAttr, fmtDate, todayStr } from '../api.js';
import { badge, emptyState, loadingBlock, errorBlock, toast, modal, confirmDialog, delegate, setBusy, ctl, masterSwitch } from '../ui.js';
import { loadConfig, renderConfigGroups, wireConfig, ensureModelDatalist } from '../config.js';
import { CONFIG_META } from '../config-schema.js';

export default {
  title: '日历与整理',
  state: { cfg: {}, pages: [], tab: 'browse' },

  async mount(root) {
    this.root = root;
    ensureModelDatalist();
    root.innerHTML = `
      <p class="page-intro">日历把零散对话凝成日/周/月/季/年的总结，开启注入后 AI 便知道「最近发生了什么」。这里可以浏览、手动编辑，也能随时触发各级整理。</p>
      <div id="master-slot">${loadingBlock()}</div>
      <div class="pill-tabs" id="tabs">
        <div class="pill-tab active" data-act="tab" data-tab="browse">🗂️ 日历浏览</div>
        <div class="pill-tab" data-act="tab" data-tab="generate">⚙️ 生成整理</div>
        <div class="pill-tab" data-act="tab" data-tab="settings">🎛️ 参数设置</div>
      </div>
      <div id="panel-browse"></div>
      <div id="panel-generate" style="display:none"></div>
      <div id="panel-settings" style="display:none"></div>
    `;

    this.state.cfg = await loadConfig().catch(() => ({}));
    this.renderMaster();
    this.renderBrowseShell();
    this.renderGenerate();
    this.renderSettings();
    this.loadPages();

    delegate(root, {
      tab: (el) => this.switchTab(el.dataset.tab),
      reload: () => this.loadPages(),
      edit: (el) => this.editModal(this.findPage(el.dataset.id)),
      del: (el) => this.remove(el.dataset.date, el.dataset.type),
      'gen-daily': (el) => this.runTask(el, () => `/admin/daily-digest${this.dateQ('d-daily')}`, '每日整理'),
      'gen-day': (el) => this.runTask(el, () => `/admin/day-page${this.dateQ('d-day')}`, '日页面生成'),
      'gen-week': (el) => this.runTask(el, () => `/admin/week-summary${this.weekQ()}`, '周总结'),
      'gen-month': (el) => this.runTask(el, () => `/admin/month-summary?month=${encodeURIComponent(this.val('d-month'))}`, '月总结'),
      'gen-quarter': (el) => this.runTask(el, () => `/admin/quarter-summary?quarter=${encodeURIComponent(this.val('d-quarter'))}`, '季度总结'),
      'gen-year': (el) => this.runTask(el, () => `/admin/year-summary?year=${encodeURIComponent(this.val('d-year'))}`, '年度总结'),
    });
  },

  // ---- master switch (持久在 tabs 之上) ----
  renderMaster() {
    const key = 'calendar_inject_enabled';
    const on = String(this.state.cfg[key]) === 'true';
    const slot = this.root.querySelector('#master-slot');
    slot.innerHTML = masterSwitch({ key, emoji: '📅', label: CONFIG_META[key].label, on, desc: CONFIG_META[key].desc });
    wireConfig(slot, this.state.cfg);
  },

  renderSettings() {
    const el = this.root.querySelector('#panel-settings');
    el.innerHTML = renderConfigGroups('calendar', this.state.cfg);
    wireConfig(el, this.state.cfg);
  },

  switchTab(tab) {
    this.state.tab = tab;
    this.root.querySelectorAll('.pill-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    this.root.querySelector('#panel-browse').style.display = tab === 'browse' ? '' : 'none';
    this.root.querySelector('#panel-generate').style.display = tab === 'generate' ? '' : 'none';
    this.root.querySelector('#panel-settings').style.display = tab === 'settings' ? '' : 'none';
  },

  // ---- 浏览 ----
  renderBrowseShell() {
    this.root.querySelector('#panel-browse').innerHTML = `
      <div class="toolbar">
        <label class="text-sm muted">起</label>
        <input type="date" id="cal-start" value="${escAttr(todayStr(-30))}">
        <label class="text-sm muted">止</label>
        <input type="date" id="cal-end" value="${escAttr(todayStr(0))}">
        <select id="cal-type" style="width:130px">
          <option value="">全部类型</option>
          <option value="day">日</option>
          <option value="week">周</option>
          <option value="month">月</option>
          <option value="quarter">季</option>
          <option value="year">年</option>
        </select>
        <button class="btn btn-secondary" data-act="reload">查询</button>
      </div>
      <div id="cal-list">${loadingBlock()}</div>
    `;
  },

  typeLabel(t) {
    return ({ day: '日', week: '周', month: '月', quarter: '季', year: '年' })[t] || (t || '页面');
  },

  async loadPages() {
    const el = this.root.querySelector('#cal-list');
    if (!el) return;
    el.innerHTML = loadingBlock();
    const start = this.val('cal-start'), end = this.val('cal-end'), type = this.val('cal-type');
    let url = '/calendar?';
    if (start) url += `start=${encodeURIComponent(start)}&`;
    if (end) url += `end=${encodeURIComponent(end)}&`;
    if (type) url += `type=${encodeURIComponent(type)}`;
    try {
      const d = await get(url);
      this.state.pages = d.pages || [];
      this.renderList();
    } catch (e) { el.innerHTML = errorBlock(e.message); }
  },

  findPage(id) { return (this.state.pages || []).find(p => String(p.id) === String(id)); },

  renderList() {
    const el = this.root.querySelector('#cal-list');
    const pages = this.state.pages;
    if (!pages.length) { el.innerHTML = emptyState({ icon: '📭', msg: '这段时间还没有日历页面', hint: '去「生成整理」触发每日整理或各级总结' }); return; }
    el.innerHTML = pages.map(p => {
      const body = p.diary || p.summary || p.digest || '';
      const secs = Array.isArray(p.sections) ? p.sections : [];
      const kws = Array.isArray(p.keywords) ? p.keywords : [];
      return `
      <div class="item">
        <div class="item-row">
          <div style="flex:1;min-width:0">
            <div class="item-title">${escHtml(p.title || fmtDate(p.date))} ${badge(this.typeLabel(p.type), 'info')}</div>
            <div class="item-sub faint text-xs">${escHtml(p.date || '')}</div>
            ${body ? `<div class="text-sm muted clamp3" style="color:var(--text-soft);margin-top:6px;white-space:pre-wrap">${escHtml(body)}</div>` : '<div class="faint text-xs" style="margin-top:6px">（无正文）</div>'}
            ${secs.length ? `<div class="btn-row mt8">${secs.map(s => badge(typeof s === 'string' ? s : (s.title || s.name || ''), 'muted')).join('')}</div>` : ''}
            ${kws.length ? `<div class="btn-row mt8">${kws.map(k => `<span class="badge badge-accent">${escHtml(k)}</span>`).join('')}</div>` : ''}
          </div>
          <div class="item-actions">
            <button class="btn btn-xs btn-secondary" data-act="edit" data-id="${p.id}">编辑</button>
            <button class="btn btn-xs btn-danger-soft" data-act="del" data-date="${escAttr(p.date)}" data-type="${escAttr(p.type || 'day')}">删除</button>
          </div>
        </div>
      </div>`;
    }).join('');
  },

  editModal(p) {
    if (!p) { toast('找不到该页面', 'err'); return; }
    const mod = modal({
      title: `编辑 · ${escHtml(p.title || p.date || '')}`,
      wide: true,
      body: `
        <div class="grid grid-2">
          <div class="field"><label>标题</label>${ctl.text('title', p.title || '', '给这一页起个标题…')}</div>
          <div class="field"><label>类型</label>${ctl.select('type', p.type || 'day', [
            { value: 'day', label: '日' }, { value: 'week', label: '周' },
            { value: 'month', label: '月' }, { value: 'quarter', label: '季' }, { value: 'year', label: '年' },
          ])}</div>
        </div>
        <div class="field"><label>正文（diary）</label>${ctl.area('content', p.diary || p.summary || p.digest || '', 12, '这一页的内容…')}</div>
        <div class="field-hint">手动保存后该页 model_used 会标记为 user_edit。</div>`,
      footer: `<button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>保存</button>`,
    });
    mod.root.querySelector('[data-cancel]').onclick = () => mod.close();
    mod.root.querySelector('[data-save]').onclick = async (ev) => {
      const content = mod.root.querySelector('[data-key="content"]').value;
      const title = mod.root.querySelector('[data-key="title"]').value.trim();
      const type = mod.root.querySelector('[data-key="type"]').value;
      setBusy(ev.currentTarget, true, '保存中');
      try {
        await put(`/admin/calendar/${encodeURIComponent(p.date)}`, { content, title, type });
        toast('已保存'); mod.close(); this.loadPages();
      } catch (e) { toast('保存失败：' + e.message, 'err'); setBusy(ev.currentTarget, false); }
    };
  },

  async remove(date, type) {
    if (!date) { toast('缺少日期', 'err'); return; }
    if (!(await confirmDialog({ title: '删除日历页面', message: `确定删除「${date}」这一页？相关评论会一并清除，不可恢复。`, danger: true, okText: '删除' }))) return;
    try {
      await del(`/admin/calendar/${encodeURIComponent(date)}?type=${encodeURIComponent(type || 'day')}`);
      toast('已删除'); this.loadPages();
    } catch (e) { toast('删除失败：' + e.message, 'err'); }
  },

  // ---- 生成整理 ----
  renderGenerate() {
    const today = todayStr(0);
    const yest = todayStr(-1);
    const monthStr = today.slice(0, 7);
    const y = today.slice(0, 4);
    const q = Math.floor(new Date(today).getMonth() / 3) + 1;
    const monStart = todayStr(-6);
    this.root.querySelector('#panel-generate').innerHTML = `
      <div class="banner banner-info"><span>⏳</span><div>下面每个都是后台长任务（调用模型，可能需要几十秒）。点击后按钮会转圈，完成后弹出结果状态。</div></div>

      <div class="card">
        <div class="card-title">📝 每日整理</div>
        <div class="card-desc">把某天的对话提取成记忆碎片与摘要（缺省＝昨天）。</div>
        <div class="toolbar mt8">
          <input type="date" id="d-daily" value="${escAttr(yest)}">
          <button class="btn btn-primary" data-act="gen-daily">运行每日整理</button>
        </div>
      </div>

      <div class="card mt16">
        <div class="card-title">📄 日页面生成</div>
        <div class="card-desc">为某一天生成结构化日页面（sections / keywords）。</div>
        <div class="toolbar mt8">
          <input type="date" id="d-day" value="${escAttr(yest)}">
          <button class="btn btn-primary" data-act="gen-day">生成日页面</button>
        </div>
      </div>

      <div class="card mt16">
        <div class="card-title">🗓️ 周总结</div>
        <div class="card-desc">汇总一周的日页面成周总结。</div>
        <div class="toolbar mt8">
          <label class="text-sm muted">起</label><input type="date" id="d-week-start" value="${escAttr(monStart)}">
          <label class="text-sm muted">止</label><input type="date" id="d-week-end" value="${escAttr(today)}">
          <button class="btn btn-primary" data-act="gen-week">生成周总结</button>
        </div>
      </div>

      <div class="card mt16">
        <div class="card-title">📆 月总结</div>
        <div class="toolbar mt8">
          <input type="month" id="d-month" value="${escAttr(monthStr)}">
          <button class="btn btn-primary" data-act="gen-month">生成月总结</button>
        </div>
      </div>

      <div class="grid grid-2 mt16">
        <div class="card">
          <div class="card-title">📊 季度总结</div>
          <div class="toolbar mt8">
            <input type="text" id="d-quarter" value="${escAttr(y + '-Q' + q)}" placeholder="YYYY-QN" style="width:130px">
            <button class="btn btn-primary" data-act="gen-quarter">生成季度</button>
          </div>
        </div>
        <div class="card">
          <div class="card-title">🎍 年度总结</div>
          <div class="toolbar mt8">
            <input type="number" id="d-year" value="${escAttr(y)}" step="1" style="width:130px">
            <button class="btn btn-primary" data-act="gen-year">生成年度</button>
          </div>
        </div>
      </div>
    `;
  },

  // ---- helpers ----
  val(id) { return this.root.querySelector('#' + id)?.value?.trim() || ''; },
  dateQ(id) { const v = this.val(id); return v ? `?date=${encodeURIComponent(v)}` : ''; },
  weekQ() {
    const s = this.val('d-week-start'), e = this.val('d-week-end');
    const parts = [];
    if (s) parts.push(`start=${encodeURIComponent(s)}`);
    if (e) parts.push(`end=${encodeURIComponent(e)}`);
    return parts.length ? '?' + parts.join('&') : '';
  },

  async runTask(btn, urlFn, label) {
    setBusy(btn, true, '整理中');
    try {
      const r = await get(urlFn());
      const status = r.status || 'ok';
      const extra = [r.date, r.month, r.week, r.label, r.page_id != null ? `页面#${r.page_id}` : '',
        r.fragments != null ? `碎片 ${r.fragments}` : '', r.digests != null ? `摘要 ${r.digests}` : '',
        r.sections != null ? `章节 ${r.sections}` : ''].filter(Boolean).join(' · ');
      toast(`${label}：${status}${extra ? '（' + extra + '）' : ''}`, status === 'error' ? 'err' : 'ok');
      this.loadPages();
    } catch (e) { toast(`${label}失败：${e.message}`, 'err'); }
    finally { setBusy(btn, false); }
  },
};
