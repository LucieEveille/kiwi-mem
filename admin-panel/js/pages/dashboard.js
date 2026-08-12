// 📊 仪表盘 — 配置清单 + 系统总览（v1.6.2：清单式引导）
import { get, escHtml } from '../api.js';
import { statCard, card, badge, emptyState, loadingBlock } from '../ui.js';
import { runHealthChecks } from '../health.js';

export default {
  title: '仪表盘',
  async mount(root) {
    root.innerHTML = `
      <div id="checklist" class="mb16">${loadingBlock('正在检查配置…')}</div>
      <div class="grid grid-4 mb16" id="stats">${loadingBlock()}</div>
      <div class="grid grid-2">
        <div id="dream-card"></div>
        <div id="recent-card"></div>
      </div>
      <div class="banner banner-accent mt16"><span style="font-size:17px;line-height:1.4">🧵</span><div><b>本网关只支持线性对话</b>——不支持消息分支（重新生成多条分叉、fork 对话树）。记忆提取、上下文压缩与各项注入都按单一线性序列设计。</div></div>
    `;
    this.loadChecklist(root);
    this.loadStats(root);
    this.loadDream(root);
    this.loadRecent(root);
  },

  // ---- 配置清单：固定引导步骤 + 健康自检合并 ----
  async loadChecklist(root) {
    const el = root.querySelector('#checklist');
    const safe = async (p, d) => { try { return await p; } catch { return d; } };
    const [provs, saved, persona, scfg, convs, issues] = await Promise.all([
      safe(get('/admin/providers'), { providers: [] }),
      safe(get('/admin/all-saved-models'), { models: [] }),
      safe(get('/admin/system-prompt'), {}),
      safe(get('/admin/search-config'), {}),
      safe(get('/sync/conversations?limit=1'), { conversations: [] }),
      safe(runHealthChecks(), []),
    ]);

    const items = [];
    const nProv = (provs.providers || []).length;
    const nModel = (saved.models || []).length;
    items.push({ done: nProv > 0, title: '添加 AI 供应商', detail: nProv ? `已接入 ${nProv} 个` : '还没有供应商，聊天无法转发', route: 'providers', action: '去添加' });
    items.push({ done: nModel > 0, title: '保存可用模型', detail: nModel ? `已保存 ${nModel} 个模型` : '前端模型列表会回退到环境变量默认', route: 'providers', action: '去保存' });
    items.push({ done: (convs.conversations || []).length > 0, title: '连接聊天前端', detail: (convs.conversations || []).length ? '已收到过对话' : '前端 Base URL 填网关地址 + /v1', route: '', action: '' });
    items.push({ done: !!(persona.content || '').trim(), title: '写一份人设', detail: (persona.content || '').trim() ? `${persona.content.length} 字` : '决定助手是谁、怎么说话', route: 'persona', action: '去编写' });
    items.push({ done: !!scfg.engine, optional: true, title: '配置联网搜索（可选）', detail: scfg.engine ? `已选 ${scfg.engine}` : '未选择搜索引擎', route: 'websearch', action: '去配置' });
    // 健康自检的问题项接在清单后（error/warn 才占清单名额，info 只列出）
    for (const i of issues) {
      items.push({ done: false, warn: i.level !== 'info', info: i.level === 'info', title: i.title, detail: i.detail, route: i.route, action: '去处理' });
    }

    const need = items.filter(i => !i.optional && !i.info);
    const doneN = need.filter(i => i.done).length;
    const pct = Math.round(doneN / need.length * 100);
    const allDone = doneN === need.length;

    el.innerHTML = card({
      title: allDone ? '✅ 一切就绪' : `把 kiwi-mem 配置到能用，还差 ${need.length - doneN} 步`,
      desc: allDone ? '没有发现「启用了却没配好」的地方。' : '按顺序完成下面的清单，每一项都能点过去直接处理。',
      actions: `<div class="ck-progress"><div class="ck-bar"><span style="width:${pct}%"></span></div><span class="ck-num mono">${doneN}/${need.length}</span></div>`,
      body: items.map(i => `
        <div class="ck-item ${i.done ? 'done' : ''} ${i.warn ? 'warn' : ''}">
          <span class="ck-dot">${i.done ? '✓' : (i.warn ? '!' : '·')}</span>
          <div class="ck-body"><span class="ck-title">${escHtml(i.title)}</span><span class="ck-detail">${escHtml(i.detail)}</span></div>
          ${!i.done && i.route ? `<a class="btn btn-xs btn-secondary nowrap" href="#/${i.route}">${i.action} →</a>` : ''}
        </div>`).join(''),
    });
  },

  async loadStats(root) {
    const box = root.querySelector('#stats');
    const safe = async (p, d) => { try { return await p; } catch { return d; } };
    try {
      // 状态是必需的（拿不到就是后端不通）；热度与 Dream 是锦上添花，各自失败不影响整排卡。
      const status = await get('/');
      const [mems, heat, dream] = await Promise.all([
        safe(get('/debug/memories?limit=200'), {}),
        safe(get('/debug/memory-heat?limit=200'), {}),
        safe(get('/dream/status'), {}),
      ]);

      const total = mems.total_memories ?? mems.memories?.length ?? status.memories ?? 0;
      const locked = (mems.memories || []).filter(m => m.is_permanent).length;
      const memOn = status.memory_enabled;

      // 平均热度：/debug/memory-heat 取的是最近 N 条（按 created_at 倒序），
      // 所以这是「近期样本」的平均值，不是全库平均——副标题里写清楚样本量。
      const hs = heat.summary || {};
      const hList = (heat.memories || []).filter(m => typeof m.heat === 'number');
      const avgHeat = hList.length
        ? (hList.reduce((s, m) => s + m.heat, 0) / hList.length).toFixed(2)
        : '—';
      const heatSub = hList.length
        ? `高热 ${hs.hot ?? 0} · 冷 ${hs.cold ?? 0}`
        : (heat.error ? '热度数据不可用' : '还没有记忆');

      // 待整合碎片：Dream 攒够多少条会犯困，副标题给出阈值与是否已越线。
      const pending = dream.unprocessed_count ?? dream.unprocessed_fragments ?? 0;
      const threshold = dream.drowsy_threshold;
      const pendingSub = threshold == null
        ? 'Dream 尚未配置阈值'
        : (pending >= threshold ? `已过犯困阈值 ${threshold}` : `犯困阈值 ${threshold}`);

      box.innerHTML =
        statCard({ label: '🧩 记忆总数', value: total, cls: 'accent', sub: `${locked} 条已锁定` }) +
        statCard({ label: '🔥 平均热度', value: avgHeat, cls: 'gold', sub: heatSub }) +
        statCard({ label: '🌙 待整合碎片', value: pending, cls: 'purple', sub: pendingSub }) +
        statCard({ label: '记忆系统', value: memOn ? '✅ 开启' : '⛔ 关闭', cls: memOn ? 'accent' : '' });

      const pill = document.getElementById('status-pill');
      if (pill) { pill.textContent = '● 运行中'; pill.className = 'badge badge-accent'; }
      const foot = document.getElementById('foot-version');
      if (foot && status.version) foot.textContent = status.version;
    } catch (e) {
      box.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>无法连接后端：${escHtml(e.message)}</div></div>`;
      const pill = document.getElementById('status-pill');
      if (pill) { pill.textContent = '● 离线'; pill.className = 'badge badge-danger'; }
    }
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
        <div class="kv"><span class="k">未处理碎片</span><span class="v">${d.unprocessed_count ?? d.unprocessed_fragments ?? 0} ${d.is_drowsy ? badge('😴 犯困', 'warn') : ''}</span></div>
        <div class="kv"><span class="k">上次 Dream</span><span class="v">${escHtml(d.last_dream_date || '从未')}</span></div>
      ` });
    } catch (e) { el.innerHTML = card({ title: '🌙 Dream 状态', body: `<p class="muted">加载失败：${escHtml(e.message)}</p>` }); }
  },

  async loadRecent(root) {
    const el = root.querySelector('#recent-card');
    try {
      const data = await get('/debug/memories?limit=6&sort=newest');
      const list = data.memories || [];
      const body = list.length ? list.map(m => `
        <div class="kv">
          <span class="v truncate" style="flex:1">${escHtml(m.title || m.content?.slice(0, 70) || '#' + m.id)}</span>
          <span class="mono imp ${m.importance >= 8 ? 'imp-hi' : m.importance >= 5 ? 'imp-mid' : ''}">imp ${m.importance}</span>${m.is_permanent ? ' 🔒' : ''}
        </div>`).join('') : emptyState({ msg: '还没有记忆', hint: '聊几句，记忆会自动生成' });
      el.innerHTML = card({ title: '🧩 最近记忆', actions: `<a class="btn btn-sm btn-secondary" href="#/memories">全部</a>`, body });
    } catch (e) { el.innerHTML = card({ title: '🧩 最近记忆', body: `<p class="muted">加载失败：${escHtml(e.message)}</p>` }); }
  },
};
