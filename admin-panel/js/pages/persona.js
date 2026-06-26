// 📝 人设 — system prompt 编辑器（最顶层、最静态的那一层）
import { get, put, escHtml } from '../api.js';
import { badge, toast, loadingBlock, setBusy } from '../ui.js';

export default {
  title: '人设',
  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">这是注入给模型的最顶层 system prompt——决定助手是谁、怎么说话。它是整条消息旅程里最静态的一层，放在缓存前缀的最开头。</p>
      <div class="banner banner-info">
        <span>💡</span>
        <div>支持模板变量 <code>{user_name}</code>、<code>{assistant_name}</code>，会在转发时替换。<b>请勿在此写入时间或日期</b>——当前时间由网关在最后一刻自动注入，手写会破坏 prompt 缓存、让输入费用飙升。</div>
      </div>
      <div id="persona-box">${loadingBlock()}</div>
    `;
    await this.load();
  },

  async load() {
    const box = this.root.querySelector('#persona-box');
    try {
      const d = await get('/admin/system-prompt');
      this.content = d.content || '';
      box.innerHTML = `
        <div class="card-head">
          <div>
            <div class="card-title">📝 system prompt</div>
            <div class="card-desc">
              来源：${d.source === 'database' ? badge('数据库', 'accent') : badge(d.source === 'file' ? '文件' : (d.source || '未知'), 'muted')}
              <span class="faint text-xs">字数：<b data-len>${(this.content || '').length}</b></span>
            </div>
          </div>
          <div class="btn-row">
            <button class="btn btn-secondary btn-sm" data-act="reset">还原改动</button>
            <button class="btn btn-primary" data-act="save">保存</button>
          </div>
        </div>
        <textarea class="mono" id="persona-text" rows="20" spellcheck="false" placeholder="写下助手的人设、语气与底线…">${escHtml(this.content)}</textarea>
      `;
      const ta = box.querySelector('#persona-text');
      const lenEl = box.querySelector('[data-len]');
      ta.addEventListener('input', () => { lenEl.textContent = ta.value.length; });
      box.querySelector('[data-act="reset"]').addEventListener('click', () => {
        ta.value = this.content; lenEl.textContent = this.content.length; toast('已还原到上次保存的内容', 'info');
      });
      box.querySelector('[data-act="save"]').addEventListener('click', (e) => this.save(e.currentTarget, ta));
    } catch (e) {
      box.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>加载失败：${escHtml(e.message)}</div></div>`;
    }
  },

  async save(btn, ta) {
    const content = ta.value;
    setBusy(btn, true, '保存中');
    try {
      const r = await put('/admin/system-prompt', { content });
      this.content = content;
      toast(`已保存（${r.length ?? content.length} 字）`);
    } catch (e) {
      toast('保存失败：' + e.message, 'err');
    } finally {
      setBusy(btn, false);
    }
  },
};
