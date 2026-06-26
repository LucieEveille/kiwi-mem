// 📁 项目分隔 — 浏览项目 + 指令 + 文件（重新切块/删块）+ 编辑/删除
import { get, post, put, del, escHtml, escAttr, fmtDateTime } from '../api.js';
import { card, badge, emptyState, loadingBlock, errorBlock, toast, modal, confirmDialog, delegate, setBusy, ctl } from '../ui.js';

export default {
  title: '项目分隔',

  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">项目用于隔离不同主题的对话与记忆：每个项目可带专属指令与参考文件，文件会被切块、向量化后供该项目的对话检索。</p>
      <div class="card-head"><div class="card-title">项目</div><span id="proj-count" class="info"></span></div>
      <div id="proj-list">${loadingBlock()}</div>
    `;
    this.load();

    delegate(root, {
      detail: (el) => this.detail(el.dataset.id),
      edit: (el) => this.editForm(this.find(el.dataset.id)),
      del: (el) => this.remove(el.dataset.id),
    });
  },

  find(id) { return (this.list || []).find(p => String(p.id) === String(id)); },

  async load() {
    const el = this.root.querySelector('#proj-list');
    try {
      const d = await get('/sync/projects');
      this.list = d.projects || [];
      const cnt = this.root.querySelector('#proj-count');
      if (cnt) cnt.textContent = this.list.length ? `共 ${this.list.length} 个项目` : '';
      if (!this.list.length) {
        el.innerHTML = emptyState({ icon: '📁', msg: '还没有项目', hint: '项目通常由客户端创建，用于把不同主题的对话与记忆分开。' });
        return;
      }
      el.innerHTML = `<div class="grid grid-2">` + this.list.map(p => {
        const files = p.files || [];
        return `<div class="item">
          <div class="item-row">
            <div style="flex:1;min-width:0">
              <div class="item-title">${escHtml(p.icon || '📁')} ${escHtml(p.name || '（未命名项目）')}</div>
              ${p.description ? `<div class="item-sub clamp3" style="color:var(--text-soft)">${escHtml(p.description)}</div>` : ''}
              <div class="btn-row mt8">
                ${badge('📄 ' + files.length + ' 文件', 'muted')}
                ${p.instructions ? badge('含指令', 'info') : ''}
                <span class="faint text-xs">更新于 ${fmtDateTime(p.updated_at)}</span>
              </div>
            </div>
          </div>
          <div class="btn-row mt8">
            <button class="btn btn-xs btn-primary" data-act="detail" data-id="${escAttr(p.id)}">详情 / 文件</button>
            <button class="btn btn-xs btn-secondary" data-act="edit" data-id="${escAttr(p.id)}">编辑</button>
            <button class="btn btn-xs btn-danger-soft" data-act="del" data-id="${escAttr(p.id)}">删除</button>
          </div>
        </div>`;
      }).join('') + `</div>`;
    } catch (e) {
      el.innerHTML = errorBlock('加载项目失败：' + e.message);
    }
  },

  // ===== 详情：指令 + 文件 =====
  detail(id) {
    const p = this.find(id);
    if (!p) { toast('找不到该项目', 'err'); return; }
    const mod = modal({ title: `${p.icon || '📁'} ${p.name || '项目'}`, wide: true, body: loadingBlock() });
    this._curMod = mod;
    this.renderDetail(mod, p);
    // 模态内文件操作事件委托
    delegate(mod.root, {
      fileProcess: (el) => this.fileProcess(p, el.dataset.fid, el),
      fileDelChunks: (el) => this.fileDelChunks(p, el.dataset.fid, el),
    });
  },

  renderDetail(mod, p) {
    const files = p.files || [];
    const instr = p.instructions
      ? `<pre class="mono" style="white-space:pre-wrap;word-break:break-word;background:var(--surface-2,#1a1a1a);padding:12px;border-radius:8px;max-height:220px;overflow:auto">${escHtml(p.instructions)}</pre>`
      : `<p class="muted text-sm">（未设置项目指令）</p>`;
    const filesHtml = files.length ? files.map(f => {
      const fid = f.id ?? f.file_id ?? '';
      const fname = f.name || f.file_name || ('文件 ' + fid);
      const hasChunks = (f.chunks ?? f.chunk_count ?? 0);
      return `<div class="item" style="padding:9px 12px">
        <div class="item-row">
          <div style="flex:1;min-width:0">
            <div class="item-title text-sm truncate">${escHtml(fname)}</div>
            <div class="item-sub">
              ${hasChunks ? badge(hasChunks + ' 块', 'accent') : badge('未切块', 'muted')}
              <span class="faint text-xs mono">${escHtml(String(fid))}</span>
            </div>
          </div>
          <div class="item-actions">
            <button class="btn btn-xs btn-secondary" data-act="fileProcess" data-fid="${escAttr(fid)}">重新切块</button>
            <button class="btn btn-xs btn-danger-soft" data-act="fileDelChunks" data-fid="${escAttr(fid)}">删块</button>
          </div>
        </div>
      </div>`;
    }).join('') : `<p class="muted text-sm">这个项目还没有文件。</p>`;

    mod.body.innerHTML = `
      ${p.description ? `<p class="card-desc mb12">${escHtml(p.description)}</p>` : ''}
      <div class="section-title">项目指令（instructions）</div>
      ${instr}
      <div class="section-title mt16">参考文件（${files.length}）</div>
      <div class="card-desc mb8">「重新切块」会用文件文本重新向量化（长任务）；「删块」清除该文件已生成的向量块。</div>
      <div id="file-list">${filesHtml}</div>`;
  },

  // 重新切块/向量化：需 file_name + text_content，弹窗收集后调用
  fileProcess(p, fid, btn) {
    const f = (p.files || []).find(x => String(x.id ?? x.file_id) === String(fid)) || {};
    const fname = f.name || f.file_name || '';
    const content = f.text_content || f.content || f.text || '';
    const mod = modal({
      title: '重新切块 / 向量化',
      wide: true,
      body: `
        <div class="field"><label>文件名 file_name</label>${ctl.text('file_name', fname, '如：需求文档.md')}</div>
        <div class="field"><label>文本内容 text_content</label>${ctl.areaMono('text_content', content, 10, '把要切块向量化的文本粘贴到这里…')}</div>
        <div class="field-hint">将重新切块并生成向量（长任务）。文本为空则不会生成任何块。</div>`,
      footer: `<button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>开始处理</button>`,
    });
    mod.root.querySelector('[data-cancel]').onclick = () => mod.close();
    mod.root.querySelector('[data-save]').onclick = async (ev) => {
      const file_name = mod.root.querySelector('[data-key="file_name"]').value.trim();
      const text_content = mod.root.querySelector('[data-key="text_content"]').value;
      if (!file_name) { toast('文件名不能为空', 'err'); return; }
      setBusy(ev.currentTarget, true, '处理中');
      try {
        const r = await post(`/projects/${p.id}/files/${fid}/process`, { file_name, text_content });
        if (r.chunks > 0) toast(`已生成 ${r.chunks} 个向量块`, 'ok');
        else toast(r.message || '无文本内容，未生成块', 'info');
        mod.close();
        await this.refreshAfterFileOp(p.id);
      } catch (e) {
        toast('处理失败：' + e.message, 'err');
        setBusy(ev.currentTarget, false);
      }
    };
  },

  async fileDelChunks(p, fid, btn) {
    if (!(await confirmDialog({ title: '删除文件向量块', message: '确定删除该文件已生成的向量块？文件本身保留，可再次「重新切块」。', danger: true, okText: '删块' }))) return;
    setBusy(btn, true, '删除中');
    try {
      const r = await del(`/projects/${p.id}/files/${fid}/chunks`);
      toast(`已删除 ${r.deleted ?? 0} 个向量块`, 'ok');
      await this.refreshAfterFileOp(p.id);
    } catch (e) {
      toast('删除失败：' + e.message, 'err');
    } finally {
      setBusy(btn, false);
    }
  },

  // 文件操作后重新拉取项目并刷新当前详情模态
  async refreshAfterFileOp(pid) {
    try {
      const d = await get('/sync/projects');
      this.list = d.projects || [];
      const fresh = this.find(pid);
      if (fresh && this._curMod && document.body.contains(this._curMod.root)) this.renderDetail(this._curMod, fresh);
    } catch { /* 静默：详情仍显示旧数据 */ }
  },

  // ===== 编辑项目 =====
  editForm(p) {
    if (!p) { toast('找不到该项目', 'err'); return; }
    const mod = modal({
      title: `编辑项目 #${p.id}`,
      wide: true,
      body: `
        <div class="grid grid-2">
          <div class="field"><label>名称</label>${ctl.text('name', p.name || '', '项目名称')}</div>
          <div class="field"><label>图标 icon</label>${ctl.text('icon', p.icon || '', '如 📁 / 🚀')}</div>
        </div>
        <div class="field"><label>描述</label>${ctl.area('description', p.description || '', 2, '一句话说明这个项目…')}</div>
        <div class="field"><label>项目指令 instructions</label>${ctl.areaMono('instructions', p.instructions || '', 8, '该项目对话的专属系统指令…')}</div>`,
      footer: `<button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>保存</button>`,
    });
    mod.root.querySelector('[data-cancel]').onclick = () => mod.close();
    mod.root.querySelector('[data-save]').onclick = async (ev) => {
      const name = mod.root.querySelector('[data-key="name"]').value.trim();
      if (!name) { toast('项目名称不能为空', 'err'); return; }
      const body = {
        ...p,
        name,
        icon: mod.root.querySelector('[data-key="icon"]').value.trim(),
        description: mod.root.querySelector('[data-key="description"]').value,
        instructions: mod.root.querySelector('[data-key="instructions"]').value,
      };
      delete body.files; // 不在此处全量替换文件
      setBusy(ev.currentTarget, true, '保存中');
      try {
        await put(`/sync/projects/${p.id}`, body);
        toast('项目已更新', 'ok');
        mod.close();
        this.load();
      } catch (e) {
        toast('保存失败：' + e.message, 'err');
        setBusy(ev.currentTarget, false);
      }
    };
  },

  async remove(id) {
    if (!(await confirmDialog({ title: '删除项目', message: '确定删除这个项目？其文件向量块会一并删除，此操作不可恢复。', danger: true, okText: '删除' }))) return;
    try { await del(`/sync/projects/${id}`); toast('项目已删除', 'ok'); this.load(); }
    catch (e) { toast('删除失败：' + e.message, 'err'); }
  },
};
