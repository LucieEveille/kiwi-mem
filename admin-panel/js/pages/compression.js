// 🗜️ 上下文压缩 — 配置（含总开关）+ 查看某对话的压缩摘要
import { get, escHtml, escAttr, fmtDateTime } from '../api.js';
import { badge, emptyState, loadingBlock, errorBlock, toast, delegate, setBusy } from '../ui.js';
import { loadConfig, renderConfigPage, wireConfig, ensureModelDatalist } from '../config.js';

export default {
  title: '上下文压缩',

  async mount(root) {
    this.root = root;
    ensureModelDatalist();
    root.innerHTML = `
      <p class="page-intro">对话太长时，自动把靠前的消息压成摘要塞回上下文——省 token 又不失忆。下方旋钮决定何时触发、保留多少原文、用哪个模型。</p>
      <div id="cfg">${loadingBlock()}</div>

      <div class="card mt24">
        <div class="card-title">🔍 查看压缩摘要</div>
        <div class="card-desc">输入对话 ID，查看它已生成的压缩摘要记录。</div>
        <div class="toolbar mt8">
          <input type="text" id="cs-cid" class="grow" placeholder="conversation_id，如 conv_xxx">
          <button class="btn btn-primary" data-act="load">查看</button>
        </div>
        <div id="cs-list"></div>
      </div>
    `;

    const cfg = await loadConfig().catch(() => ({}));
    const cfgEl = root.querySelector('#cfg');
    cfgEl.innerHTML = renderConfigPage('compression', cfg);
    wireConfig(cfgEl, cfg);

    delegate(root, { load: (el) => this.loadSummaries(el) });
    root.querySelector('#cs-cid')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') root.querySelector('[data-act="load"]').click();
    });
  },

  async loadSummaries(btn) {
    const cid = this.root.querySelector('#cs-cid').value.trim();
    const listEl = this.root.querySelector('#cs-list');
    if (!cid) { toast('请输入 conversation_id', 'err'); return; }
    setBusy(btn, true, '查询中');
    listEl.innerHTML = loadingBlock();
    try {
      const data = await get(`/admin/compression-summaries?conversation_id=${encodeURIComponent(cid)}`);
      const rows = Array.isArray(data) ? data : [];
      if (!rows.length) { listEl.innerHTML = emptyState({ icon: '🫧', msg: '该对话还没有压缩摘要' }); return; }
      listEl.innerHTML = rows.map(r => `
        <div class="item">
          <div class="item-row">
            <div style="flex:1;min-width:0">
              <div class="btn-row">
                ${badge(r.summary_type || 'auto', 'info')}
                ${r.model ? `<span class="badge badge-muted">${escHtml(r.model)}</span>` : ''}
                ${r.msg_count != null ? `<span class="badge badge-accent">压缩 ${r.msg_count} 条</span>` : ''}
                <span class="faint text-xs">${escHtml(fmtDateTime(r.compressed_at))}</span>
              </div>
              <div class="text-sm muted" style="color:var(--text-soft);margin-top:8px;white-space:pre-wrap">${escHtml(r.summary || '')}</div>
            </div>
          </div>
        </div>`).join('');
    } catch (e) { listEl.innerHTML = errorBlock(e.message); }
    finally { setBusy(btn, false); }
  },
};
