// 🔍 对话搜索 — 标题命中 + 消息命中（带上下文，高亮命中条）。真实 HTTP 状态码
import { get, escHtml, fmtDateTime } from '../api.js';
import { badge, emptyState, loadingBlock, toast, delegate } from '../ui.js';

const ROLE_LABEL = { user: '我', assistant: '助手', system: '系统', tool: '工具' };
function roleLabel(role) { return ROLE_LABEL[role] || (role || '消息'); }

export default {
  title: '对话搜索',
  state: { q: '', limit: 20 },

  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">在所有对话里搜索：分「标题命中」与「消息命中」两区展示；消息命中会带上下文，并高亮真正匹配的那一条。</p>
      <div class="toolbar">
        <input type="search" id="search-q" class="grow" placeholder="搜索对话标题或消息内容…（回车）" value="${escHtml(this.state.q)}">
        <select id="search-limit" style="width:120px">
          <option value="20">最多 20 条</option>
          <option value="50">最多 50 条</option>
          <option value="100">最多 100 条</option>
        </select>
        <button class="btn btn-primary" data-act="search">搜索</button>
      </div>
      <div id="search-results">${emptyState({ icon: '🔍', msg: '输入关键词开始搜索' })}</div>
    `;

    const input = root.querySelector('#search-q');
    input?.addEventListener('keydown', e => { if (e.key === 'Enter') this.doSearch(); });
    root.querySelector('#search-limit')?.addEventListener('change', e => { this.state.limit = Number(e.target.value); });

    delegate(root, { search: () => this.doSearch() });
  },

  async doSearch() {
    const input = this.root.querySelector('#search-q');
    const q = (input?.value || '').trim();
    this.state.q = q;
    const box = this.root.querySelector('#search-results');
    if (!q) { box.innerHTML = emptyState({ icon: '🔍', msg: '请输入搜索关键词' }); return; }
    box.innerHTML = loadingBlock('搜索中…');
    try {
      const data = await get(`/search/messages?q=${encodeURIComponent(q)}&limit=${this.state.limit}`);
      this.render(data || {});
    } catch (e) {
      box.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>${escHtml(e.message)}</div></div>`;
      toast('搜索失败：' + e.message, 'err');
    }
  },

  render(data) {
    const titles = data.title_matches || [];
    const messages = data.message_matches || [];
    const box = this.root.querySelector('#search-results');

    if (!titles.length && !messages.length) {
      box.innerHTML = emptyState({ icon: '🍃', msg: `没有找到与「${this.state.q}」匹配的对话` });
      return;
    }

    box.innerHTML = `
      <div class="section-title">📌 标题命中 · ${titles.length}</div>
      ${titles.length ? titles.map(t => `
        <div class="item">
          <div class="item-row">
            <div style="flex:1;min-width:0">
              <div class="item-title truncate">${escHtml(t.title || '（无标题对话）')}</div>
              <div class="item-sub">对话 #${escHtml(t.conversation_id)}${t.project_id != null ? ' · 项目 ' + escHtml(t.project_id) : ''}</div>
            </div>
            <span class="faint text-xs">${escHtml(fmtDateTime(t.date))}</span>
          </div>
        </div>`).join('') : `<p class="muted text-sm mb16">无标题命中。</p>`}

      <div class="section-title mt24">💬 消息命中 · ${messages.length}</div>
      ${messages.length ? messages.map(m => this.renderConversation(m)).join('') : `<p class="muted text-sm">无消息命中。</p>`}
    `;
  },

  renderConversation(m) {
    const matches = m.matches || [];
    const matchCount = matches.length;
    return `
      <div class="card mb16">
        <div class="card-head">
          <div>
            <div class="card-title truncate">${escHtml(m.title || '（无标题对话）')}</div>
            <div class="card-desc">对话 #${escHtml(m.conversation_id)}${m.project_id != null ? ' · 项目 ' + escHtml(m.project_id) : ''} · ${escHtml(fmtDateTime(m.date))}</div>
          </div>
          ${badge(matchCount + ' 处命中', 'accent')}
        </div>
        ${matches.map(mt => this.renderContext(mt)).join('')}
      </div>`;
  },

  renderContext(mt) {
    const ctx = mt.context || [];
    return `
      <div class="item" style="margin-bottom:10px">
        ${ctx.map(c => {
          const hit = !!c.is_match;
          const wrapStyle = hit
            ? 'background:var(--c-accent-soft);border-radius:8px;padding:8px 10px;margin:4px 0'
            : 'padding:6px 10px;margin:4px 0';
          return `
          <div style="${wrapStyle}">
            <div class="btn-row" style="margin-bottom:4px">
              <span class="badge ${hit ? 'badge-accent' : 'badge-muted'}">${escHtml(roleLabel(c.role))}</span>
              ${hit ? badge('命中', 'accent') : ''}
              ${c.time ? `<span class="faint text-xs">${escHtml(fmtDateTime(c.time))}</span>` : ''}
            </div>
            <div class="text-sm" style="color:var(--text-soft);white-space:pre-wrap;word-break:break-word">${escHtml(c.content || '')}</div>
          </div>`;
        }).join('')}
      </div>`;
  },
};
