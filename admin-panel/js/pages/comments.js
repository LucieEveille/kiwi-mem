// 💬 评论系统 — 按目标对象浏览 / 新增 / 删除（HTTP 200 + {error} 约定）
import { get, post, del, escHtml, fmtDateTime } from '../api.js';
import { badge, emptyState, loadingBlock, toast, confirmDialog, delegate, setBusy, ctl } from '../ui.js';

const TARGET_TYPES = [
  { value: 'memory', label: '记忆碎片 memory' },
  { value: 'calendar', label: '日历页 calendar' },
  { value: 'scene', label: '场景 scene' },
];

export default {
  title: '评论系统',
  state: { target_type: 'memory', target_id: '' },

  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">评论挂在某个对象上（记忆 / 日历页 / 场景等），可用来给它做批注。先选好「目标类型 + 目标 ID」再加载评论。</p>
      <div class="toolbar">
        ${ctl.select('target_type', this.state.target_type, TARGET_TYPES)}
        <input type="number" id="cm-target-id" class="grow" placeholder="目标 ID（数字）" style="max-width:200px" value="${escHtml(this.state.target_id)}">
        <button class="btn btn-primary" data-act="load">加载评论</button>
      </div>
      <div id="cm-panel">${emptyState({ icon: '💬', msg: '选择目标类型并输入 ID 后加载评论' })}</div>
    `;

    const sel = root.querySelector('[data-key="target_type"]');
    sel?.addEventListener('change', e => { this.state.target_type = e.target.value; });
    const idInput = root.querySelector('#cm-target-id');
    idInput?.addEventListener('keydown', e => { if (e.key === 'Enter') this.load(); });

    delegate(root, {
      load: () => this.load(),
      add: (el) => this.add(el),
      del: (el) => this.remove(el.dataset.id),
    });
  },

  readTarget() {
    this.state.target_type = this.root.querySelector('[data-key="target_type"]').value;
    this.state.target_id = this.root.querySelector('#cm-target-id').value.trim();
    return this.state;
  },

  async load() {
    const { target_type, target_id } = this.readTarget();
    const panel = this.root.querySelector('#cm-panel');
    if (!target_type || target_id === '') { toast('请填写目标类型与目标 ID', 'err'); return; }
    panel.innerHTML = loadingBlock();
    try {
      const data = await get(`/comments?target_type=${encodeURIComponent(target_type)}&target_id=${encodeURIComponent(target_id)}`);
      this.comments = data.comments || [];
      this.render();
    } catch (e) {
      panel.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>${escHtml(e.message)}</div></div>`;
    }
  },

  render() {
    const { target_type, target_id } = this.state;
    const panel = this.root.querySelector('#cm-panel');
    const list = this.comments.length
      ? this.comments.map(c => `
        <div class="item">
          <div class="item-row">
            <div style="flex:1;min-width:0">
              <div class="btn-row mb8">
                ${badge('👤 ' + (c.author || 'user'), 'info')}
                ${c.parent_id != null ? badge('↳ 回复 #' + c.parent_id, 'muted') : ''}
                <span class="faint text-xs">${escHtml(fmtDateTime(c.created_at))}</span>
              </div>
              <div class="text-sm" style="color:var(--text-soft);white-space:pre-wrap;word-break:break-word">${escHtml(c.content || '')}</div>
            </div>
            <div class="item-actions">
              <button class="btn btn-xs btn-danger-soft" data-act="del" data-id="${c.id}">删除</button>
            </div>
          </div>
        </div>`).join('')
      : emptyState({ icon: '💬', msg: '该对象还没有评论' });

    panel.innerHTML = `
      <div class="section-title">${escHtml(target_type)} #${escHtml(target_id)} 的评论 · 共 ${this.comments.length} 条</div>
      <div id="cm-list">${list}</div>
      <div class="card mt16">
        <div class="card-title">添加评论</div>
        <div class="field mt8">${ctl.area('new_content', '', 4, '写下批注…')}</div>
        <div class="btn-row"><button class="btn btn-primary" data-act="add">发表评论</button></div>
      </div>
    `;
  },

  async add(btn) {
    const { target_type, target_id } = this.state;
    const area = this.root.querySelector('[data-key="new_content"]');
    const content = (area?.value || '').trim();
    if (!content) { toast('评论内容不能为空', 'err'); return; }
    setBusy(btn, true, '发表中');
    try {
      await post('/comments', { target_type, target_id: Number(target_id), content, author: 'admin', parent_id: null });
      toast('评论已发表');
      this.load();
    } catch (e) { toast('发表失败：' + e.message, 'err'); setBusy(btn, false); }
  },

  async remove(id) {
    if (!(await confirmDialog({ title: '删除评论', message: '确定删除这条评论？其子评论会一并级联删除。', danger: true, okText: '删除' }))) return;
    try { await del(`/comments/${id}`); toast('已删除'); this.load(); }
    catch (e) { toast('删除失败：' + e.message, 'err'); }
  },
};
