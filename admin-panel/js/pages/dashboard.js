// 📊 仪表盘 — 系统总览 + 状态自检
import { get, escHtml, fmtDateTime } from '../api.js';
import { statCard, card, badge, emptyState, loadingBlock } from '../ui.js';
import { runHealthChecks } from '../health.js';

export default {
  title: '仪表盘',
  async mount(root) {
    root.innerHTML = `
      <div class="banner banner-accent mb16"><span style="font-size:17px;line-height:1.4">🧵</span><div><b>本网关只支持线性对话</b><br>不支持消息分支（重新生成多条分叉、fork 对话树）。记忆提取、上下文压缩与各项注入都按单一线性序列设计，分支会让记忆归属与上下文衔接错乱——因此后端有意只做线性对话。</div></div>
      <div id="health" class="mb16">${loadingBlock('正在自检配置…')}</div>
      <div class="grid grid-4 mb16" id="stats">${loadingBlock()}</div>
      <div class="grid grid-2">
        <div id="sys-card"></div>
        <div id="dream-card"></div>
      </div>
      <div id="embed-banner"></div>
      <div id="recent-card"></div>
    `;
    this.loadHealth(root);
    this.loadStats(root);
    this.loadSys(root);
    this.loadDream(root);
    this.loadRecent(root);
    this.loadEmbed(root);
  },

  async loadHealth(root) {
    const el = root.querySelector('#health');
    try {
      const issues = await runHealthChecks();
      if (!issues.length) {
        el.innerHTML = `<div class="banner banner-accent"><span>✅</span><div><b>一切就绪。</b>没有发现「启用了却没配好」的地方。</div></div>`;
        return;
      }
      const order = { error: 0, warn: 1, info: 2 };
      issues.sort((a, b) => order[a.level] - order[b.level]);
      const ic = { error: '⛔', warn: '⚠️', info: '💡' };
      const n = { error: issues.filter(i => i.level === 'error').length, warn: issues.filter(i => i.level === 'warn').length };
      const summary = [n.error ? `${n.error} 项严重` : '', n.warn ? `${n.warn} 项警告` : ''].filter(Boolean).join(' · ') || `${issues.length} 项提示`;
      el.innerHTML = card({
        title: `🩺 状态自检 · ${summary}`,
        desc: '以下是「开了却没配好 / 可能不工作」的地方。',
        body: issues.map(i => `
          <div class="health-item health-${i.level}">
            <span class="health-ic">${ic[i.level]}</span>
            <div class="health-body"><div class="health-title">${escHtml(i.title)}</div><div class="health-detail">${escHtml(i.detail)}</div></div>
            <a class="btn btn-xs btn-secondary nowrap" href="#/${i.route}">去处理 →</a>
          </div>`).join(''),
      });
    } catch (e) {
      el.innerHTML = '';
    }
  },

  async loadStats(root) {
    const box = root.querySelector('#stats');
    try {
      const [status, mems, provs] = await Promise.all([
        get('/').catch(() => ({})),
        get('/debug/memories?limit=200').catch(() => ({})),
        get('/admin/providers').catch(() => ({ providers: [] })),
      ]);
      const total = mems.total_memories ?? mems.memories?.length ?? status.memories ?? 0;
      const locked = (mems.memories || []).filter(m => m.is_permanent).length;
      const memOn = status.memory_enabled;
      box.innerHTML =
        statCard({ label: '🧩 记忆总数', value: total, cls: 'accent' }) +
        statCard({ label: '🔒 锁定记忆', value: locked, cls: 'purple', sub: '当前已加载页中' }) +
        statCard({ label: '🔌 供应商', value: (provs.providers || []).length, cls: 'info' }) +
        statCard({ label: '记忆系统', value: memOn ? '✅ 开启' : '⛔ 关闭', cls: memOn ? 'accent' : '' });

      // topbar 状态丸 + footer 版本
      const pill = document.getElementById('status-pill');
      if (pill) { pill.textContent = status.version ? '● ' + status.version : '● 运行中'; pill.className = 'badge badge-accent'; }
      const foot = document.getElementById('foot-version');
      if (foot && status.version) foot.textContent = status.version;
    } catch (e) {
      box.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>无法连接后端：${escHtml(e.message)}</div></div>`;
      const pill = document.getElementById('status-pill');
      if (pill) { pill.textContent = '● 离线'; pill.className = 'badge badge-danger'; }
    }
  },

  async loadSys(root) {
    const el = root.querySelector('#sys-card');
    try {
      const s = await get('/');
      el.innerHTML = card({ title: '系统状态', body: `
        <div class="kv"><span class="k">版本</span><span class="v">${escHtml(s.version || s.gateway || '—')}</span></div>
        <div class="kv"><span class="k">默认模型</span><span class="v mono">${escHtml(s.default_model || '—')}</span></div>
        <div class="kv"><span class="k">记忆提取间隔</span><span class="v">每 ${escHtml(String(s.extract_interval ?? '—'))} 轮</span></div>
        <div class="kv"><span class="k">单次注入上限</span><span class="v">${escHtml(String(s.max_inject ?? '—'))} 条</span></div>
        <div class="kv"><span class="k">记忆系统</span><span class="v">${s.memory_enabled ? badge('开启', 'accent') : badge('关闭', 'danger')}</span></div>
      ` });
    } catch (e) { el.innerHTML = card({ title: '系统状态', body: `<p class="muted">加载失败：${escHtml(e.message)}</p>` }); }
  },

  async loadDream(root) {
    const el = root.querySelector('#dream-card');
    try {
      const d = await get('/dream/status');
      const running = d.is_running || d.is_dreaming;
      el.innerHTML = card({
        title: '🌙 Dream 状态',
        actions: `<a class="btn btn-sm btn-secondary" href="#/dream">前往</a>`,
        body: `
        <div class="kv"><span class="k">当前</span><span class="v">${running ? badge('做梦中…', 'purple') : badge('空闲', 'muted')}</span></div>
        <div class="kv"><span class="k">未处理碎片</span><span class="v">${d.unprocessed_count ?? d.unprocessed_fragments ?? 0} ${d.is_drowsy ? badge('犯困', 'warn') : ''}</span></div>
        <div class="kv"><span class="k">犯困阈值</span><span class="v">${d.drowsy_threshold ?? '—'}</span></div>
        <div class="kv"><span class="k">上次 Dream</span><span class="v">${escHtml(d.last_dream_date || '从未')}</span></div>
      ` });
    } catch (e) { el.innerHTML = card({ title: '🌙 Dream 状态', body: `<p class="muted">加载失败：${escHtml(e.message)}</p>` }); }
  },

  async loadEmbed(root) {
    const el = root.querySelector('#embed-banner');
    try {
      const e = await get('/admin/embedding-stats');
      if (!e || e.error || !(e.total_memories > 0)) return;
      if (e.without_embedding > 0) {
        el.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>向量覆盖 ${escHtml(e.coverage || '')} — ${e.without_embedding} 条记忆缺少 embedding，语义搜索可能不完整。前往「记忆碎片」执行向量迁移。</div></div>`;
      }
    } catch {}
  },

  async loadRecent(root) {
    const el = root.querySelector('#recent-card');
    try {
      const data = await get('/debug/memories?limit=6&sort=newest');
      const list = data.memories || [];
      const body = list.length ? list.map(m => `
        <div class="kv">
          <span class="v truncate" style="flex:1">${escHtml(m.title || m.content?.slice(0, 70) || '#' + m.id)}</span>
          <span>${badge('重要度 ' + m.importance, m.importance >= 8 ? 'purple' : m.importance >= 5 ? 'info' : 'accent')}${m.is_permanent ? ' 🔒' : ''}</span>
        </div>`).join('') : emptyState({ msg: '还没有记忆', hint: '聊几句，记忆会自动生成' });
      el.innerHTML = card({ title: '最近记忆', actions: `<a class="btn btn-sm btn-secondary" href="#/memories">全部</a>`, body });
    } catch (e) { el.innerHTML = card({ title: '最近记忆', body: `<p class="muted">加载失败：${escHtml(e.message)}</p>` }); }
  },
};
