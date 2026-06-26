// ☁️ 云同步与零件箱 — 同步设置（只读）+ 备份导入导出 + 对话管理 + 危险区
import { get, del, download, API, escHtml, escAttr, fmtDateTime } from '../api.js';
import { card, badge, emptyState, loadingBlock, errorBlock, toast, modal, confirmDialog, delegate, setBusy } from '../ui.js';
import { loadConfig, renderConfigGroups, wireConfig } from '../config.js';

// 同步设置 8 键 → 标签 + 可跳转编辑的页面
const SETTING_KEYS = [
  { key: 'user_nickname',      label: '用户昵称',   page: 'profile' },
  { key: 'user_avatar',        label: '用户头像',   page: 'profile' },
  { key: 'assistant_avatar',   label: '助手头像',   page: 'profile' },
  { key: 'assistant_settings', label: '助手参数',   page: 'profile' },
  { key: 'custom_skills',      label: '自定义技能', page: 'phrases' },
  { key: 'quick_phrases',      label: '快捷短语',   page: 'phrases' },
  { key: 'mcp_switches',       label: 'MCP 开关',   page: 'tools' },
  { key: 'theme_preference',   label: '主题偏好',   page: 'sync' },
];

export default {
  title: '云同步与零件箱',
  state: { tab: 'parts', cfg: {} },

  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">「零件箱」是聊天前端与网关共享的一组同步设置（昵称、头像、技能、快捷短语、MCP 开关、主题）。这里还能整体备份/恢复数据、管理对话、以及在危险区重置同步数据。</p>
      <div class="pill-tabs" id="tabs">
        <div class="pill-tab active" data-act="tab" data-tab="parts">🧰 零件箱</div>
        <div class="pill-tab" data-act="tab" data-tab="convos">💬 对话</div>
        <div class="pill-tab" data-act="tab" data-tab="danger">⚠️ 危险区</div>
      </div>
      <div id="panel-parts"></div>
      <div id="panel-convos" style="display:none"></div>
      <div id="panel-danger" style="display:none"></div>
    `;

    this.cfg = await loadConfig().catch(() => ({}));
    this.renderParts();
    this.renderDanger();

    delegate(root, {
      tab: (el) => this.switchTab(el.dataset.tab),
      export: (el) => this.doExport(el),
      import: () => this.root.querySelector('#backup-file')?.click(),
      convoOpen: (el) => this.openConvo(el.dataset.id),
      convoDel: (el) => this.delConvo(el.dataset.id),
      reset: (el) => this.doReset(el),
    });

    // 备份文件选择 → 上传
    root.querySelector('#backup-file')?.addEventListener('change', (e) => this.doImport(e.target));
  },

  switchTab(tab) {
    this.state.tab = tab;
    this.root.querySelectorAll('.pill-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    this.root.querySelector('#panel-parts').style.display = tab === 'parts' ? '' : 'none';
    this.root.querySelector('#panel-convos').style.display = tab === 'convos' ? '' : 'none';
    this.root.querySelector('#panel-danger').style.display = tab === 'danger' ? '' : 'none';
    if (tab === 'convos' && !this._convosLoaded) { this._convosLoaded = true; this.loadConvos(); }
  },

  // ===== 零件箱（同步设置 只读 + 备份）=====
  renderParts() {
    const el = this.root.querySelector('#panel-parts');
    el.innerHTML = `
      <div id="settings-card">${loadingBlock()}</div>
      <div class="card mt16">
        <div class="card-title">📦 整体备份</div>
        <div class="card-desc">导出包含对话、项目、记忆、配置与同步设置的 zip 备份；导入会按备份内容合并恢复。</div>
        <div class="btn-row mt8">
          <button class="btn btn-secondary" data-act="export">⬇️ 导出备份（zip）</button>
          <button class="btn btn-primary" data-act="import">⬆️ 导入备份</button>
          <input type="file" id="backup-file" accept=".zip,application/zip" style="display:none">
        </div>
        <div id="import-result" class="mt8"></div>
      </div>`;
    this.loadSettings();
  },

  async loadSettings() {
    const box = this.root.querySelector('#settings-card');
    try {
      const s = await get('/sync/settings');
      const rows = SETTING_KEYS.map(({ key, label, page }) => {
        const raw = s[key];
        const val = raw == null ? '' : String(raw);
        const shown = val
          ? `<span class="mono text-sm truncate" style="max-width:260px;display:inline-block;vertical-align:bottom">${escHtml(val.slice(0, 80))}${val.length > 80 ? '…' : ''}</span>`
          : `<span class="faint text-sm">（空）</span>`;
        return `<div class="kv">
          <span class="k">${escHtml(label)} <span class="faint text-xs mono">${escHtml(key)}</span></span>
          <span class="v">${shown} <a class="btn btn-xs btn-ghost" href="#/${page}">编辑 →</a></span>
        </div>`;
      }).join('');
      box.innerHTML = card({
        title: '🧰 同步设置（只读）',
        desc: '这些键由聊天前端与各功能页读写，此处仅展示当前值，点「编辑」前往对应页修改。',
        body: rows,
      });
      // 主题偏好等同步配置（theme_preference）即时编辑
      const cfgWrap = document.createElement('div');
      cfgWrap.className = 'mt16';
      cfgWrap.innerHTML = renderConfigGroups('sync', this.cfg);
      box.appendChild(cfgWrap);
      wireConfig(cfgWrap, this.cfg);
    } catch (e) {
      box.innerHTML = errorBlock('加载同步设置失败：' + e.message);
    }
  },

  doExport(btn) {
    try { download('/sync/export'); toast('已开始下载备份', 'ok'); }
    catch (e) { toast('导出失败：' + e.message, 'err'); }
  },

  async doImport(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const resultEl = this.root.querySelector('#import-result');
    resultEl.innerHTML = loadingBlock('导入中，请稍候…');
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch(API + '/sync/import-backup', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) throw new Error(data.error || `服务器错误 (${res.status})`);
      const n = (k) => data[k] ?? 0;
      resultEl.innerHTML = `<div class="banner banner-info"><span>✅</span><div>
        导入完成：对话 ${n('conversations')} · 消息 ${n('messages')} · 项目 ${n('projects')} · 记忆 ${n('memories')} · 设置 ${n('settings')} · 配置 ${n('config')}
      </div></div>`;
      toast('备份导入成功', 'ok');
      this._convosLoaded = false; // 让对话列表下次重新加载
      this.loadSettings();
    } catch (e) {
      resultEl.innerHTML = errorBlock('导入失败：' + e.message);
      toast('导入失败：' + e.message, 'err');
    } finally {
      input.value = ''; // 允许再次选同一文件
    }
  },

  // ===== 对话 =====
  async loadConvos() {
    const el = this.root.querySelector('#panel-convos');
    el.innerHTML = loadingBlock();
    try {
      const d = await get('/sync/conversations');
      this.convos = d.conversations || [];
      if (!this.convos.length) { el.innerHTML = emptyState({ icon: '💬', msg: '还没有对话' }); return; }
      el.innerHTML = `<div class="toolbar"><span class="info">共 ${this.convos.length} 个对话</span></div>` +
        this.convos.map(c => `
          <div class="item">
            <div class="item-row">
              <div style="flex:1;min-width:0">
                <div class="item-title">${c.pinned ? '📌 ' : ''}${escHtml(c.title || '（无标题）')}</div>
                <div class="item-sub">
                  ${c.model ? badge(c.model, 'info') : ''}
                  ${c.project_id ? badge('项目 ' + c.project_id, 'purple') : ''}
                  <span class="faint text-xs">更新于 ${fmtDateTime(c.updated_at)}</span>
                </div>
              </div>
              <div class="item-actions">
                <button class="btn btn-xs btn-secondary" data-act="convoOpen" data-id="${escAttr(c.id)}">查看</button>
                <button class="btn btn-xs btn-danger-soft" data-act="convoDel" data-id="${escAttr(c.id)}">删除</button>
              </div>
            </div>
          </div>`).join('');
    } catch (e) {
      el.innerHTML = errorBlock('加载对话失败：' + e.message);
    }
  },

  async openConvo(id) {
    const mod = modal({ title: '对话详情', wide: true, body: loadingBlock() });
    try {
      const d = await get(`/sync/conversations/${id}`);
      const msgs = d.messages || [];
      const head = `
        <div class="kv"><span class="k">标题</span><span class="v">${escHtml(d.title || '（无标题）')}</span></div>
        <div class="kv"><span class="k">模型</span><span class="v mono">${escHtml(d.model || '—')}</span></div>
        <div class="kv"><span class="k">消息数</span><span class="v">${msgs.length}</span></div>
        <div class="kv"><span class="k">更新于</span><span class="v">${fmtDateTime(d.updated_at)}</span></div>`;
      const list = msgs.length ? `<div class="section-title mt16">消息预览</div>` + msgs.map(m => `
        <div class="item" style="padding:8px 12px">
          <div class="item-sub">${badge(m.role || '?', m.role === 'user' ? 'info' : 'accent')} <span class="faint text-xs">${fmtDateTime(m.time)}</span></div>
          <div class="text-sm clamp3" style="color:var(--text-soft)">${escHtml(String(m.content || '').slice(0, 300))}</div>
        </div>`).join('') : `<p class="muted mt16">这个对话没有消息。</p>`;
      mod.body.innerHTML = head + list;
    } catch (e) {
      mod.body.innerHTML = errorBlock('加载失败：' + e.message);
    }
  },

  async delConvo(id) {
    if (!(await confirmDialog({ title: '删除对话', message: '确定删除这个对话？其消息会一并删除，不可恢复。', danger: true, okText: '删除' }))) return;
    try { await del(`/sync/conversations/${id}`); toast('对话已删除', 'ok'); this.loadConvos(); }
    catch (e) { toast('删除失败：' + e.message, 'err'); }
  },

  // ===== 危险区 =====
  renderDanger() {
    const el = this.root.querySelector('#panel-danger');
    el.innerHTML = `
      <div class="card" style="border:1px solid var(--danger,#e5484d)">
        <div class="card-title" style="color:var(--danger,#e5484d)">⚠️ 重置同步数据</div>
        <div class="banner banner-warn mt8"><span>⚠️</span><div>
          此操作会<b>清空全部对话、项目与同步设置键</b>（记忆碎片与其他配置会被保留）。删除后<b>无法恢复</b>，请先在零件箱导出备份。
        </div></div>
        <div class="field mt16">
          <label>请输入确认码 <code>RESET_ALL_DATA</code> 以解锁重置按钮</label>
          <input type="text" id="reset-code" placeholder="RESET_ALL_DATA" spellcheck="false" autocomplete="off">
        </div>
        <div class="btn-row mt8">
          <button class="btn btn-danger" id="reset-btn" data-act="reset" disabled>重置全部同步数据</button>
        </div>
      </div>`;
    const codeInput = el.querySelector('#reset-code');
    const btn = el.querySelector('#reset-btn');
    codeInput.addEventListener('input', () => { btn.disabled = codeInput.value.trim() !== 'RESET_ALL_DATA'; });
  },

  async doReset(btn) {
    const code = this.root.querySelector('#reset-code')?.value.trim();
    if (code !== 'RESET_ALL_DATA') { toast('确认码不正确', 'err'); return; }
    // 二次确认
    if (!(await confirmDialog({
      title: '最终确认',
      message: '真的要清空全部对话、项目与同步设置吗？此操作不可恢复。',
      danger: true, okText: '我确认，清空',
    }))) return;
    setBusy(btn, true, '重置中');
    try {
      const r = await del('/sync/reset', { confirm: 'RESET_ALL_DATA' });
      toast(`已重置：对话 ${r.deleted_conversations ?? 0} · 项目 ${r.deleted_projects ?? 0}`, 'ok');
      const codeInput = this.root.querySelector('#reset-code');
      if (codeInput) codeInput.value = '';
      this._convosLoaded = false;
      if (this.state.tab === 'convos') this.loadConvos();
    } catch (e) {
      toast('重置失败：' + e.message, 'err');
    } finally {
      setBusy(btn, false);
      const codeInput = this.root.querySelector('#reset-code');
      if (codeInput) this.root.querySelector('#reset-btn').disabled = codeInput.value.trim() !== 'RESET_ALL_DATA';
    }
  },
};
