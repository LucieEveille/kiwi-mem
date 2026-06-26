// 🏷️ 碎片分类 — 给记忆碎片归类（CRUD）
import { get, post, put, del, escHtml, escAttr } from '../api.js';
import { badge, emptyState, loadingBlock, toast, modal, confirmDialog, delegate, setBusy } from '../ui.js';

const DEFAULT_COLOR = '#74a838';

export default {
  title: '碎片分类',
  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">分类用于给记忆碎片打标签、便于在「记忆碎片」页按类筛选。每个分类有颜色和图标，纯粹是组织手段，不影响检索逻辑。</p>
      <div class="card mb16">
        <div class="card-title mb12">➕ 新建分类</div>
        <div class="toolbar" style="margin-bottom:0">
          <input type="text" id="cat-name" class="grow" placeholder="分类名称，如：工作 / 情感 / 健康">
          <input type="color" id="cat-color" value="${DEFAULT_COLOR}" title="颜色" style="width:46px;padding:2px;height:36px">
          <input type="text" id="cat-icon" placeholder="图标 emoji，如 💼" style="width:120px">
          <button class="btn btn-primary" data-act="add">添加</button>
        </div>
      </div>
      <div id="cat-list">${loadingBlock()}</div>
    `;

    delegate(root, {
      add: (el) => this.add(el),
      edit: (el) => this.edit(this.find(el.dataset.id)),
      del: (el) => this.remove(el.dataset.id),
    });
    root.querySelector('#cat-name')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') this.root.querySelector('[data-act="add"]').click();
    });

    await this.load();
  },

  async load() {
    const el = this.root.querySelector('#cat-list');
    el.innerHTML = loadingBlock();
    try {
      const d = await get('/admin/categories');
      this.list = d.categories || [];
      if (!this.list.length) { el.innerHTML = emptyState({ icon: '🏷️', msg: '还没有分类', hint: '用上面的表单建一个吧' }); return; }
      el.innerHTML = this.list.map(c => `
        <div class="item">
          <div class="item-row">
            <div style="flex:1;min-width:0;display:flex;align-items:center;gap:10px">
              <span class="dot" style="width:14px;height:14px;background:${escAttr(c.color || DEFAULT_COLOR)}"></span>
              <span style="font-size:18px">${escHtml(c.icon || '📁')}</span>
              <span class="item-title">${escHtml(c.name)}</span>
              ${badge('#' + c.id, 'muted')}
            </div>
            <div class="item-actions">
              <button class="btn btn-xs btn-secondary" data-act="edit" data-id="${c.id}">编辑</button>
              <button class="btn btn-xs btn-danger-soft" data-act="del" data-id="${c.id}">删除</button>
            </div>
          </div>
        </div>`).join('');
    } catch (e) {
      el.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>${escHtml(e.message)}</div></div>`;
    }
  },

  find(id) { return (this.list || []).find(c => String(c.id) === String(id)); },

  async add(btn) {
    const name = this.root.querySelector('#cat-name').value.trim();
    const color = this.root.querySelector('#cat-color').value || DEFAULT_COLOR;
    const icon = this.root.querySelector('#cat-icon').value.trim();
    if (!name) { toast('请输入分类名称', 'err'); return; }
    setBusy(btn, true, '添加中');
    try {
      await post('/admin/categories', { name, color, icon });
      toast('分类已添加');
      this.root.querySelector('#cat-name').value = '';
      this.root.querySelector('#cat-icon').value = '';
      this.root.querySelector('#cat-color').value = DEFAULT_COLOR;
      this.load();
    } catch (e) {
      toast('添加失败：' + e.message, 'err');
    } finally {
      setBusy(btn, false);
    }
  },

  edit(c) {
    if (!c) return;
    const mod = modal({
      title: `编辑分类 #${c.id}`,
      body: `
        <div class="field"><label>名称</label><input type="text" data-k="name" value="${escAttr(c.name || '')}" placeholder="分类名称"></div>
        <div class="grid grid-2">
          <div class="field"><label>颜色</label><input type="color" data-k="color" value="${escAttr(c.color || DEFAULT_COLOR)}" style="width:100%;height:38px;padding:2px"></div>
          <div class="field"><label>图标 emoji</label><input type="text" data-k="icon" value="${escAttr(c.icon || '')}" placeholder="💼"></div>
        </div>`,
      footer: `<button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>保存</button>`,
    });
    mod.root.querySelector('[data-cancel]').onclick = () => mod.close();
    mod.root.querySelector('[data-save]').onclick = async (ev) => {
      const name = mod.root.querySelector('[data-k="name"]').value.trim();
      const color = mod.root.querySelector('[data-k="color"]').value || DEFAULT_COLOR;
      const icon = mod.root.querySelector('[data-k="icon"]').value.trim();
      if (!name) { toast('名称不能为空', 'err'); return; }
      setBusy(ev.currentTarget, true, '保存中');
      try {
        await put(`/admin/categories/${c.id}`, { name, color, icon });
        toast('已更新'); mod.close(); this.load();
      } catch (e) {
        toast('保存失败：' + e.message, 'err'); setBusy(ev.currentTarget, false);
      }
    };
  },

  async remove(id) {
    if (!(await confirmDialog({ title: '删除分类', message: '确定删除该分类？已归入此类的记忆不会被删除，只是失去分类标签。', danger: true, okText: '删除' }))) return;
    try { await del(`/admin/categories/${id}`); toast('已删除'); this.load(); }
    catch (e) { toast('删除失败：' + e.message, 'err'); }
  },
};
