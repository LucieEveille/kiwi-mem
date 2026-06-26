// 🧩 记忆碎片 — 总开关 + 参数 + 碎片浏览/CRUD/搜索/热度
import { get, post, put, del, escHtml, escAttr, fmtDate } from '../api.js';
import { card, badge, emptyState, loadingBlock, toast, modal, confirmDialog, delegate, setBusy, ctl } from '../ui.js';
import { loadConfig, renderConfigGroups, wireConfig, ensureModelDatalist } from '../config.js';
import { masterSwitch } from '../ui.js';
import { CONFIG_META } from '../config-schema.js';

const PAGE_SIZE = 20;

export default {
  title: '记忆碎片',
  state: { tab: 'browse', page: 0, sort: 'newest', imp: '', cat: '', q: '', cfg: {}, cats: [], heat: {} },

  async mount(root) {
    this.root = root;
    ensureModelDatalist();
    root.innerHTML = `
      <p class="page-intro">记忆碎片是 kiwi-mem 的原子单位：每条都带重要度、热度、情绪、分类、锁定等属性，会随时间软化、淡忘，也会因反复提起而升温。</p>
      <div id="master-slot">${loadingBlock()}</div>
      <div class="pill-tabs" id="tabs">
        <div class="pill-tab active" data-act="tab" data-tab="browse">🗂️ 碎片浏览</div>
        <div class="pill-tab" data-act="tab" data-tab="settings">⚙️ 参数设置</div>
      </div>
      <div id="panel-browse"></div>
      <div id="panel-settings" style="display:none"></div>
    `;

    this.state.cfg = await loadConfig().catch(() => ({}));
    this.renderMaster();
    this.renderSettings();
    this.renderBrowseShell();
    this.loadCats();
    this.loadList();

    delegate(root, {
      tab: (el) => this.switchTab(el.dataset.tab),
      add: () => this.editModal(null),
      edit: (el) => this.editModal(this.findMem(el.dataset.id)),
      del: (el) => this.remove(el.dataset.id),
      lock: (el) => this.toggleLock(el.dataset.id),
      extract: (el) => this.runAction(el, '/admin/extract-now', 'post', '已触发记忆提取'),
      seed: (el) => this.runAction(el, '/import/seed-memories', 'get', '种子记忆已导入'),
      migrate: (el) => this.runAction(el, '/admin/migrate-embeddings', 'get', '向量迁移完成'),
      search: () => this.doSearch(),
      page: (el) => { this.state.page = Number(el.dataset.p); this.loadList(); },
    });
    root.querySelector('#mem-search')?.addEventListener('keydown', e => { if (e.key === 'Enter') this.doSearch(); });
    ['sort', 'imp', 'cat'].forEach(k => root.querySelector(`#flt-${k}`)?.addEventListener('change', e => {
      this.state[k] = e.target.value; this.state.page = 0; this.loadList();
    }));
  },

  renderMaster() {
    const on = String(this.state.cfg.memory_enabled) === 'true';
    this.root.querySelector('#master-slot').innerHTML =
      masterSwitch({ key: 'memory_enabled', emoji: '🧠', label: '记忆系统', on, desc: CONFIG_META.memory_enabled.desc });
    wireConfig(this.root.querySelector('#master-slot'), this.state.cfg);
  },

  renderSettings() {
    const el = this.root.querySelector('#panel-settings');
    el.innerHTML = renderConfigGroups('memories', this.state.cfg);
    wireConfig(el, this.state.cfg);
  },

  renderBrowseShell() {
    this.root.querySelector('#panel-browse').innerHTML = `
      <div class="toolbar">
        <input type="search" id="mem-search" class="grow" placeholder="语义搜索记忆…（回车）">
        <button class="btn btn-secondary" data-act="search">搜索</button>
        <select id="flt-sort" style="width:130px">
          <option value="newest">最近创建</option><option value="oldest">最早创建</option>
          <option value="importance">按重要度</option><option value="heat">按热度</option>
        </select>
        <select id="flt-imp" style="width:120px">
          <option value="">全部重要度</option><option value="9">9-10 核心</option>
          <option value="7">7-8 重要</option><option value="5">5-6 普通</option><option value="1">1-4 低</option>
        </select>
        <select id="flt-cat" style="width:140px"><option value="">全部分类</option></select>
        <span class="spacer"></span>
        <button class="btn btn-primary" data-act="add">+ 添加记忆</button>
      </div>
      <div class="btn-row mb16">
        <button class="btn btn-sm btn-secondary" data-act="extract">🧩 立即提取</button>
        <button class="btn btn-sm btn-secondary" data-act="seed">📦 导入种子</button>
        <button class="btn btn-sm btn-secondary" data-act="migrate">🔄 向量迁移</button>
      </div>
      <div id="mem-list">${loadingBlock()}</div>
      <div id="mem-pager" class="pagination"></div>
    `;
  },

  switchTab(tab) {
    this.state.tab = tab;
    this.root.querySelectorAll('.pill-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    this.root.querySelector('#panel-browse').style.display = tab === 'browse' ? '' : 'none';
    this.root.querySelector('#panel-settings').style.display = tab === 'settings' ? '' : 'none';
  },

  async loadCats() {
    try {
      const d = await get('/admin/categories');
      this.state.cats = d.categories || [];
      const sel = this.root.querySelector('#flt-cat');
      if (sel) sel.innerHTML = '<option value="">全部分类</option>' +
        this.state.cats.map(c => `<option value="${c.id}">${escHtml((c.icon || '📁') + ' ' + c.name)}</option>`).join('');
    } catch {}
  },

  buildUrl() {
    const s = this.state;
    if (s.q) return `/debug/memories?q=${encodeURIComponent(s.q)}&limit=50`;
    let u = `/debug/memories?limit=${PAGE_SIZE}&offset=${s.page * PAGE_SIZE}&sort=${s.sort}`;
    if (s.imp) u += `&min_importance=${s.imp}`;
    if (s.cat) u += `&category_id=${s.cat}`;
    return u;
  },

  async loadList() {
    const listEl = this.root.querySelector('#mem-list');
    listEl.innerHTML = loadingBlock();
    try {
      const data = await get(this.buildUrl());
      // 热度图（非搜索路径 heat 可能为 0）
      try { const h = await get('/debug/memory-heat?limit=500'); this.state.heat = {}; (h.memories || []).forEach(m => this.state.heat[m.id] = m.heat); } catch {}
      this.mems = data.memories || [];
      this.renderList(this.mems, data.total_memories || 0);
    } catch (e) { listEl.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>${escHtml(e.message)}</div></div>`; }
  },

  findMem(id) { return (this.mems || []).find(m => String(m.id) === String(id)); },

  heatBadge(m) {
    const h = this.state.heat[m.id] ?? m.heat;
    if (h == null) return '';
    const v = parseFloat(h);
    const cls = v > 0.7 ? 'dot-hot' : v >= 0.3 ? 'dot-warm' : 'dot-cold';
    return `<span class="badge badge-muted"><span class="dot ${cls}"></span>${v.toFixed(2)}</span>`;
  },

  renderList(mems, total) {
    const listEl = this.root.querySelector('#mem-list');
    if (!mems.length) { listEl.innerHTML = emptyState({ msg: '没有找到记忆' }); this.root.querySelector('#mem-pager').innerHTML = ''; return; }
    listEl.innerHTML = mems.map(m => `
      <div class="item">
        <div class="item-row">
          <div style="flex:1;min-width:0">
            ${m.title ? `<div class="item-title">${escHtml(m.title)}</div>` : ''}
            <div class="text-sm muted clamp3" style="color:var(--text-soft)">${escHtml(m.content || '')}</div>
            <div class="btn-row mt8">
              ${badge('重要度 ' + m.importance, m.importance >= 8 ? 'purple' : m.importance >= 5 ? 'info' : 'accent')}
              ${m.is_permanent ? badge('🔒 锁定', 'purple') : ''}
              ${this.heatBadge(m)}
              ${m.category_name ? `<span class="badge">${escHtml((m.category_color ? '' : '') + m.category_name)}</span>` : ''}
              <span class="badge badge-muted">${escHtml(m.source || '')}</span>
              <span class="faint text-xs">${fmtDate(m.created_at)}</span>
            </div>
          </div>
          <div class="item-actions">
            <button class="btn btn-xs btn-secondary" data-act="edit" data-id="${m.id}">编辑</button>
            <button class="btn btn-xs btn-secondary" data-act="lock" data-id="${m.id}">${m.is_permanent ? '🔓 解锁' : '🔒 锁定'}</button>
            <button class="btn btn-xs btn-danger-soft" data-act="del" data-id="${m.id}">删除</button>
          </div>
        </div>
      </div>`).join('');

    const pager = this.root.querySelector('#mem-pager');
    if (this.state.q) { pager.innerHTML = `<span class="info">搜索结果 ${mems.length} 条</span>`; return; }
    const pages = Math.ceil(total / PAGE_SIZE);
    if (pages <= 1) { pager.innerHTML = ''; return; }
    const p = this.state.page;
    pager.innerHTML =
      `${p > 0 ? `<button class="btn btn-sm btn-secondary" data-act="page" data-p="${p - 1}">← 上一页</button>` : ''}
       <span class="info">${p + 1} / ${pages} · 共 ${total} 条</span>
       ${p < pages - 1 ? `<button class="btn btn-sm btn-secondary" data-act="page" data-p="${p + 1}">下一页 →</button>` : ''}`;
  },

  doSearch() {
    this.state.q = this.root.querySelector('#mem-search').value.trim();
    this.state.page = 0;
    this.loadList();
  },

  editModal(m) {
    const isNew = !m;
    const cats = this.state.cats;
    const mod = modal({
      title: isNew ? '添加记忆' : `编辑记忆 #${m.id}`,
      body: `
        <div class="field"><label>标题（可选）</label>${ctl.text('title', m?.title || '', '给记忆起个标题…')}</div>
        <div class="field"><label>内容 *</label>${ctl.area('content', m?.content || '', 5, '写下你想让 AI 记住的事…')}</div>
        <div class="field"><label>重要度：<b id="imp-v">${m?.importance ?? 5}</b></label>
          <input type="range" data-key="importance" min="1" max="10" value="${m?.importance ?? 5}" style="width:100%">
          <div class="field-hint">9-10 核心 · 7-8 重要 · 5-6 普通 · 1-4 低</div>
        </div>`,
      footer: `<button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>保存</button>`,
    });
    const rng = mod.root.querySelector('[data-key="importance"]');
    rng.addEventListener('input', () => mod.root.querySelector('#imp-v').textContent = rng.value);
    mod.root.querySelector('[data-cancel]').onclick = () => mod.close();
    mod.root.querySelector('[data-save]').onclick = async (ev) => {
      const content = mod.root.querySelector('[data-key="content"]').value.trim();
      const title = mod.root.querySelector('[data-key="title"]').value.trim();
      const importance = Number(rng.value);
      if (!content) { toast('内容不能为空', 'err'); return; }
      setBusy(ev.currentTarget, true, '保存中');
      try {
        if (isNew) await post('/debug/memories', { content, title, importance });
        else await put(`/debug/memories/${m.id}`, { content, title, importance });
        toast(isNew ? '记忆已添加' : '已更新'); mod.close(); this.loadList();
      } catch (e) { toast('保存失败：' + e.message, 'err'); setBusy(ev.currentTarget, false); }
    };
  },

  async remove(id) {
    if (!(await confirmDialog({ title: '删除记忆', message: '确定删除这条记忆？不可恢复。', danger: true, okText: '删除' }))) return;
    try { await del(`/debug/memories/${id}`); toast('已删除'); this.loadList(); }
    catch (e) { toast('删除失败：' + e.message, 'err'); }
  },

  async toggleLock(id) {
    try { await post(`/debug/memories/${id}/toggle-permanent`); toast('锁定状态已切换'); this.loadList(); }
    catch (e) { toast('操作失败：' + e.message, 'err'); }
  },

  async runAction(btn, path, method, okMsg) {
    setBusy(btn, true, '执行中');
    try { await (method === 'post' ? post(path) : get(path)); toast(okMsg); this.loadList(); }
    catch (e) { toast('失败：' + e.message, 'err'); }
    finally { setBusy(btn, false); }
  },
};
