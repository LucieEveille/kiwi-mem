// 🌐 联网搜索 — 引擎选择 + API Key + 条数（配置）+ 实时测试
import { get, put, post, escHtml, escAttr } from '../api.js';
import { toast, emptyState, loadingBlock, setBusy, delegate } from '../ui.js';

export default {
  title: '联网搜索',
  engines: [],
  config: { engine: '', api_key: '', max_results: 5 },
  hasKey: false,  // 后端已存在 API Key（不回显原文，留空＝不修改）

  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">为模型接入实时联网搜索。选择搜索引擎、填好 API Key（部分本地引擎无需），即可在对话中检索最新信息。</p>
      <div id="ws-form">${loadingBlock()}</div>
      <div class="section-title mt24">🔎 测试搜索</div>
      <div class="toolbar">
        <input type="search" id="ws-query" class="grow" placeholder="输入要搜索的内容…（回车）">
        <button class="btn btn-primary" data-act="test">测试搜索</button>
      </div>
      <div id="ws-results"></div>
    `;

    delegate(root, {
      save: (el) => this.save(el),
      test: (el) => this.test(el),
    });

    await this.load();
    root.querySelector('#ws-query')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') this.test(root.querySelector('[data-act="test"]'));
    });
  },

  async load() {
    const el = this.root.querySelector('#ws-form');
    try {
      const [eng, cfg] = await Promise.all([
        get('/admin/search-engines'),
        get('/admin/search-config'),
      ]);
      this.engines = eng.engines || [];
      // 后端可能只回传遮罩/预览的 api_key，绝不回显原文。
      // 「已配置」检测优先用显式布尔 has_api_key/api_key_set；否则看返回值是否像遮罩（含 … 或 *）或非空。
      const rawKey = typeof cfg.api_key === 'string' ? cfg.api_key : '';
      const looksMasked = rawKey.includes('…') || rawKey.includes('*');
      this.hasKey = (cfg.has_api_key ?? cfg.api_key_set) ?? (looksMasked || rawKey.length > 0);
      this.config = {
        engine: cfg.engine ?? '',
        api_key: '',  // 永不回显，输入框始终留空
        max_results: cfg.max_results ?? 5,
      };
      this.renderForm();
    } catch (e) {
      el.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>${escHtml(e.message)}</div></div>`;
    }
  },

  currentEngine() {
    return this.engines.find(e => String(e.id) === String(this.config.engine));
  },

  // local 类型引擎不需要 api_key
  needsKey() {
    const e = this.currentEngine();
    if (!e) return true;
    return e.type !== 'local';
  },

  renderForm() {
    const el = this.root.querySelector('#ws-form');
    const opts = this.engines.length
      ? this.engines.map(e => `<option value="${escAttr(e.id)}" ${String(e.id) === String(this.config.engine) ? 'selected' : ''}>${escHtml(e.name)}${e.type === 'local' ? ' · 本地' : ''}</option>`).join('')
      : '';
    el.innerHTML = `
      <div class="card">
        <div class="field">
          <label>搜索引擎</label>
          <select id="ws-engine">
            <option value="">（请选择）</option>
            ${opts}
          </select>
        </div>
        <div class="field" id="ws-key-field" style="${this.needsKey() ? '' : 'display:none'}">
          <label>API Key</label>
          <input type="password" id="ws-apikey" value="" placeholder="${this.hasKey ? '（已配置，留空不修改）' : '所选引擎的 API Key'}">
          <div class="field-hint">本地引擎无需 Key；切换引擎时此项会自动显隐。${this.hasKey ? '已配置 Key 不回显，留空＝不修改。' : ''}</div>
        </div>
        <div class="field">
          <label>结果条数</label>
          <input type="number" id="ws-max" step="1" min="1" value="${escAttr(this.config.max_results)}">
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" data-act="save">保存配置</button>
        </div>
      </div>`;

    el.querySelector('#ws-engine').addEventListener('change', (ev) => {
      this.config.engine = ev.target.value;
      const kf = el.querySelector('#ws-key-field');
      if (kf) kf.style.display = this.needsKey() ? '' : 'none';
    });
  },

  readForm() {
    const el = this.root.querySelector('#ws-form');
    const maxRaw = el.querySelector('#ws-max')?.value;
    return {
      engine: el.querySelector('#ws-engine')?.value || '',
      api_key: el.querySelector('#ws-apikey')?.value ?? '',
      max_results: maxRaw === '' || maxRaw == null ? 5 : Number(maxRaw),
    };
  },

  async save(btn) {
    const form = this.readForm();
    if (!form.engine) { toast('请先选择搜索引擎', 'err'); return; }
    const body = { engine: form.engine, max_results: form.max_results };
    // 只有用户输入了非空 Key 才提交 api_key；留空＝保留已存的（不覆盖）。
    if (this.needsKey() && form.api_key.trim() !== '') body.api_key = form.api_key;
    setBusy(btn, true, '保存中');
    try {
      await put('/admin/search-config', body);
      // 用户填了新 Key 即视为「已配置」；不回写明文到 config。
      if (body.api_key !== undefined) this.hasKey = true;
      this.config = { engine: form.engine, api_key: '', max_results: form.max_results };
      toast('已保存');
    } catch (e) {
      toast('保存失败：' + e.message, 'err');
    } finally {
      setBusy(btn, false);
    }
  },

  async test(btn) {
    const query = this.root.querySelector('#ws-query')?.value.trim();
    const box = this.root.querySelector('#ws-results');
    if (!query) { toast('请输入搜索内容', 'err'); return; }
    const form = this.readForm();
    const body = { query, max_results: form.max_results };
    if (form.engine) body.engine = form.engine;
    if (this.needsKey() && form.api_key) body.api_key = form.api_key;
    setBusy(btn, true, '搜索中');
    box.innerHTML = loadingBlock('搜索中…');
    try {
      const d = await post('/admin/search-test', body);
      this.renderResults(d);
    } catch (e) {
      box.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>${escHtml(e.message)}</div></div>`;
    } finally {
      setBusy(btn, false);
    }
  },

  renderResults(d) {
    const box = this.root.querySelector('#ws-results');
    const results = d.results || [];
    if (!results.length) {
      box.innerHTML = emptyState({ icon: '🔍', msg: '没有搜索到结果', hint: '换个关键词或检查引擎配置' });
      return;
    }
    box.innerHTML = `
      <p class="text-sm muted mb12">引擎 <b>${escHtml(d.engine || '')}</b> · 共 ${d.count ?? results.length} 条</p>
      ${results.map(r => `
        <div class="item">
          <div class="item-title"><a href="${escAttr(r.url || '#')}" target="_blank" rel="noopener">${escHtml(r.title || '(无标题)')}</a></div>
          <div class="item-sub mono truncate">${escHtml(r.url || '')}</div>
          ${r.snippet ? `<div class="text-sm muted mt8" style="line-height:1.6">${escHtml(r.snippet)}</div>` : ''}
        </div>`).join('')}`;
  },
};
