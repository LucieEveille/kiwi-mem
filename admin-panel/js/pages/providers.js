// 🔌 供应商与模型 — CRUD + 连接测试 + 模型管理（决定 /v1/models 与聊天路由）+ 额度 + 默认模型
import { get, post, put, del, escHtml, escAttr } from '../api.js';
import { badge, emptyState, loadingBlock, toast, modal, confirmDialog, delegate, setBusy, ctl } from '../ui.js';
import { loadConfig, renderConfigGroups, wireConfig, ensureModelDatalist } from '../config.js';

export default {
  title: '供应商与模型',
  async mount(root) {
    this.root = root;
    ensureModelDatalist();
    root.innerHTML = `
      <div class="banner banner-info"><span>💡</span><div><b>只有在「模型」里保存过的模型</b>才会出现在前端模型列表（<code>/v1/models</code>）、并能被聊天路由调用。一个都没保存时，前端会回退到环境变量默认（通常是 OpenRouter）。</div></div>
      <div class="card-head"><div class="card-title">供应商</div><button class="btn btn-primary" data-act="add">+ 添加供应商</button></div>
      <div id="prov-list">${loadingBlock()}</div>
      <div id="default-models" class="mt24"></div>
    `;
    this.cfg = await loadConfig().catch(() => ({}));
    this.renderDefaults();
    this.load();

    delegate(root, {
      add: () => this.form(null),
      edit: (el) => this.form(this.find(el.dataset.id)),
      del: (el) => this.remove(el.dataset.id),
      test: (el) => this.test(el.dataset.id, el),
      models: (el) => this.modelsModal(this.find(el.dataset.id)),
    });
  },

  renderDefaults() {
    const el = this.root.querySelector('#default-models');
    el.innerHTML = `<div class="section-title">默认模型与路由</div>` + renderConfigGroups('providers', this.cfg);
    wireConfig(el, this.cfg);
  },

  async load() {
    const el = this.root.querySelector('#prov-list');
    try {
      const d = await get('/admin/providers');
      this.list = d.providers || [];
      if (!this.list.length) { el.innerHTML = emptyState({ icon: '🔌', msg: '还没有供应商', hint: '点右上「添加供应商」接入你的中转站或官方 API' }); return; }
      el.innerHTML = this.list.map(p => `
        <div class="item">
          <div class="item-row">
            <div style="flex:1;min-width:0">
              <div class="item-title">${escHtml(p.name)} ${badge(p.api_format || 'openai', p.api_format === 'anthropic' ? 'purple' : 'info')}</div>
              <div class="item-sub mono truncate">${escHtml(p.api_base_url || '')}</div>
              <div class="item-sub">Key：${escHtml(p.api_key_preview || '（未设置）')}</div>
            </div>
            <div class="item-actions">
              <button class="btn btn-xs btn-primary" data-act="models" data-id="${p.id}">模型</button>
              <button class="btn btn-xs btn-secondary" data-act="test" data-id="${p.id}">测试</button>
              <button class="btn btn-xs btn-secondary" data-act="edit" data-id="${p.id}">编辑</button>
              <button class="btn btn-xs btn-danger-soft" data-act="del" data-id="${p.id}">删除</button>
            </div>
          </div>
        </div>`).join('');
    } catch (e) { el.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>${escHtml(e.message)}</div></div>`; }
  },

  find(id) { return (this.list || []).find(p => String(p.id) === String(id)); },

  form(p) {
    const isNew = !p;
    const mod = modal({
      title: isNew ? '添加供应商' : '编辑供应商',
      body: `
        <div class="grid grid-2">
          <div class="field"><label>名称</label>${ctl.text('name', p?.name || '', '如：深度求索')}</div>
          <div class="field"><label>API 格式</label>${ctl.select('api_format', p?.api_format || 'openai', [{ value: 'openai', label: 'OpenAI 格式' }, { value: 'anthropic', label: 'Anthropic 格式' }])}</div>
        </div>
        <div class="field"><label>API Base URL</label>${ctl.text('api_base_url', p?.api_base_url || '', 'https://api.deepseek.com/v1/chat/completions')}</div>
        <div class="field"><label>API Key${isNew ? '' : '（留空＝不修改）'}</label>${ctl.pass('api_key', '', 'sk-…')}</div>`,
      footer: `<button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>保存</button>`,
    });
    mod.root.querySelector('[data-cancel]').onclick = () => mod.close();
    mod.root.querySelector('[data-save]').onclick = async (ev) => {
      const keyVal = mod.root.querySelector('[data-key="api_key"]').value;
      const body = {
        name: mod.root.querySelector('[data-key="name"]').value.trim(),
        api_base_url: mod.root.querySelector('[data-key="api_base_url"]').value.trim(),
        api_format: mod.root.querySelector('[data-key="api_format"]').value,
      };
      // 编辑时留空 API Key ＝ 不修改：不带 api_key，后端就不会覆盖已存的。新增时照常发送。
      if (isNew || keyVal.trim() !== '') body.api_key = keyVal;
      if (!body.name || !body.api_base_url) { toast('名称和 Base URL 必填', 'err'); return; }
      setBusy(ev.currentTarget, true, '保存中');
      try {
        if (isNew) await post('/admin/providers', body);
        else await put(`/admin/providers/${p.id}`, body);
        toast('已保存'); mod.close(); this.load();
      } catch (e) { toast('保存失败：' + e.message, 'err'); setBusy(ev.currentTarget, false); }
    };
  },

  async remove(id) {
    if (!(await confirmDialog({ title: '删除供应商', message: '确定删除该供应商？其已保存的模型也会一并清除。', danger: true, okText: '删除' }))) return;
    try { await del(`/admin/providers/${id}`); toast('已删除'); this.load(); }
    catch (e) { toast('删除失败：' + e.message, 'err'); }
  },

  async test(id, btn) {
    setBusy(btn, true, '测试中');
    try { const r = await post(`/admin/test-provider/${id}`); toast('✅ ' + (r.message || '连接成功')); }
    catch (e) { toast('❌ ' + e.message, 'err'); }
    finally { setBusy(btn, false); }
  },

  // ===== 模型管理 =====
  modelsModal(p) {
    const pid = p.id;
    const mod = modal({
      title: `管理「${p.name}」的模型`,
      wide: true,
      body: `
        <p class="card-desc mb12">只有这里保存的模型会进入 <code>/v1/models</code> 列表并可被路由调用。</p>
        <div class="section-title">已保存的模型</div>
        <div id="pm-saved">${loadingBlock()}</div>
        <div class="section-title mt16">添加模型</div>
        <div class="toolbar">
          <input type="text" id="pm-manual" class="grow" placeholder="手动输入模型 ID，如 deepseek-chat">
          <button class="btn btn-secondary" data-act="manual">+ 添加</button>
          <button class="btn btn-primary" data-act="fetch">从供应商拉取可用模型</button>
          <span id="pm-status" class="text-xs muted"></span>
        </div>
        <div id="pm-avail"></div>`,
      footer: `<button class="btn btn-secondary" data-close>关闭</button>`,
    });
    const m = mod.root;
    const loadSaved = async () => {
      const box = m.querySelector('#pm-saved');
      try {
        const d = await get(`/admin/providers/${pid}/saved-models`);
        const list = d.models || [];
        box.innerHTML = list.length ? list.map(x => `
          <div class="item" style="padding:9px 12px"><div class="item-row">
            <div><b>${escHtml(x.display_name || x.model_id)}</b> <span class="mono faint text-xs">${escHtml(x.model_id)}</span> ${badge(x.model_type || 'chat', 'muted')}</div>
            <button class="btn btn-xs btn-danger-soft" data-del="${x.id}">删除</button>
          </div></div>`).join('')
          : `<p class="muted text-sm">还没有保存任何模型。先「从供应商拉取」选，或手动输入模型 ID 添加。</p>`;
      } catch (e) { box.innerHTML = `<p class="muted">${escHtml(e.message)}</p>`; }
    };
    const addModel = async (model_id) => {
      try { await post(`/admin/providers/${pid}/saved-models`, { model_id }); toast('已添加 ' + model_id); loadSaved(); }
      catch (e) { toast('添加失败：' + e.message, 'err'); }
    };
    m.addEventListener('click', async (e) => {
      const delBtn = e.target.closest('[data-del]');
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (delBtn) { try { await del(`/admin/saved-models/${delBtn.dataset.del}`); toast('已删除'); loadSaved(); } catch (er) { toast(er.message, 'err'); } }
      if (act === 'manual') {
        const mid = m.querySelector('#pm-manual').value.trim();
        if (!mid) { toast('请输入模型 ID', 'err'); return; }
        await addModel(mid); m.querySelector('#pm-manual').value = '';
      }
      if (act === 'fetch') {
        const btn = e.target.closest('[data-act]'); const status = m.querySelector('#pm-status'); const box = m.querySelector('#pm-avail');
        setBusy(btn, true, '拉取中'); box.innerHTML = '';
        try {
          const d = await get(`/admin/providers/${pid}/models`);
          const models = (d.models || []).filter(x => !x._is_embedding).map(x => x.id || x.model || x).filter(Boolean);
          status.textContent = `共 ${models.length} 个模型`;
          box.innerHTML = models.length ? models.map(mid => `
            <div class="item" style="padding:8px 12px"><div class="item-row">
              <span class="mono text-sm">${escHtml(mid)}</span>
              <button class="btn btn-xs btn-primary" data-add="${escAttr(mid)}">+ 添加</button>
            </div></div>`).join('') : `<p class="muted text-sm">供应商没有返回可用模型。</p>`;
        } catch (er) { status.textContent = ''; box.innerHTML = `<p class="muted">${escHtml(er.message)}</p>`; }
        finally { setBusy(btn, false); }
      }
      const addBtn = e.target.closest('[data-add]');
      if (addBtn) addModel(addBtn.dataset.add);
    });
    m.querySelector('#pm-manual').addEventListener('keydown', e => { if (e.key === 'Enter') m.querySelector('[data-act="manual"]').click(); });
    loadSaved();
  },
};
