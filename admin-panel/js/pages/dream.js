// 🌙 Dream — 记忆整合（状态 + 触发流 + 场景 + 历史 + 参数）。动作驱动，pill-tabs。
import { get, post, put, del, sse, escHtml, escAttr, fmtDateTime, relTime } from '../api.js';
import { card, badge, emptyState, loadingBlock, errorBlock, toast, modal, confirmDialog, delegate, setBusy, ctl } from '../ui.js';
import { loadConfig, renderConfigPage, wireConfig, ensureModelDatalist } from '../config.js';

export default {
  title: 'Dream',
  state: { tab: 'status', cfg: {}, scenes: [], history: [] },

  async mount(root) {
    this.root = root;
    this.stream = null;       // 当前 SSE 句柄
    this.dreaming = false;    // 是否正在做梦（流式中）
    ensureModelDatalist();

    root.innerHTML = `
      <p class="page-intro">Dream 是 kiwi-mem 的「睡眠」：在空闲时把零散碎片清理、融合、推断前瞻，凝结成叙事场景。未处理碎片积太多时 AI 会犯困、提示该睡了。</p>
      <div class="pill-tabs" id="tabs">
        <div class="pill-tab active" data-tab="status">🌙 状态</div>
        <div class="pill-tab" data-tab="scenes">🎬 场景</div>
        <div class="pill-tab" data-tab="history">📜 历史</div>
        <div class="pill-tab" data-tab="settings">⚙️ 参数</div>
      </div>
      <div id="panel-status"></div>
      <div id="panel-scenes" style="display:none"></div>
      <div id="panel-history" style="display:none"></div>
      <div id="panel-settings" style="display:none"></div>
    `;

    this.renderStatusShell();
    this.loadStatus();

    this.state.cfg = await loadConfig().catch(() => ({}));
    this.renderSettings();

    delegate(root, {
      tab: (el) => this.switchTab(el.dataset.tab),
      refreshStatus: () => this.loadStatus(),
      startDream: (el) => this.startDream(el),
      stopDream: (el) => this.stopDream(el),
      forceStop: (el) => this.forceStop(el),
      clearLog: () => this.clearLog(),
      editScene: (el) => this.editScene(this.findScene(el.dataset.id)),
      delDream: (el) => this.removeDream(el.dataset.id),
    });
  },

  // SSE 在切页/卸载时必须中止
  unmount() {
    if (this.stream) { try { this.stream.abort(); } catch {} this.stream = null; }
    this.dreaming = false;
  },

  switchTab(tab) {
    this.state.tab = tab;
    this.root.querySelectorAll('.pill-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    ['status', 'scenes', 'history', 'settings'].forEach(name => {
      const p = this.root.querySelector(`#panel-${name}`);
      if (p) p.style.display = name === tab ? '' : 'none';
    });
    if (tab === 'scenes' && !this.state.scenes.length) this.loadScenes();
    if (tab === 'history' && !this.state.history.length) this.loadHistory();
  },

  // ============ 状态 ============
  renderStatusShell() {
    this.root.querySelector('#panel-status').innerHTML = `
      <div class="btn-row mb16">
        <button class="btn btn-primary" data-act="startDream">🌙 开始 Dream</button>
        <button class="btn btn-secondary" data-act="stopDream">停止</button>
        <button class="btn btn-danger-soft" data-act="forceStop">强制中断</button>
        <span class="spacer"></span>
        <button class="btn btn-sm btn-secondary" data-act="refreshStatus">刷新状态</button>
      </div>
      <div id="dream-status">${loadingBlock()}</div>
      <div class="card mt16">
        <div class="card-head">
          <div><div class="card-title">做梦实况</div><div class="card-desc">点「开始 Dream」后，整合过程会逐条流式呈现。</div></div>
          <button class="btn btn-xs btn-ghost" data-act="clearLog">清空</button>
        </div>
        <div id="dream-log" class="mono text-xs" style="white-space:pre-wrap;max-height:360px;overflow:auto;line-height:1.7;color:var(--text-soft)"></div>
      </div>
    `;
    this.logEmpty();
  },

  async loadStatus() {
    const el = this.root.querySelector('#dream-status');
    if (!el) return;
    el.innerHTML = loadingBlock();
    try {
      const d = await get('/dream/status');
      const running = d.is_running || d.is_dreaming;
      const unprocessed = d.unprocessed_count ?? d.unprocessed_fragments ?? 0;
      const cur = d.current;
      const last = d.last_completed;
      el.innerHTML = card({
        body: `
        <div class="kv"><span class="k">当前状态</span><span class="v">${running ? badge('做梦中…', 'purple') : badge('空闲', 'muted')}</span></div>
        <div class="kv"><span class="k">未处理碎片</span><span class="v">${unprocessed} ${d.is_drowsy ? badge('😴 犯困', 'warn') : ''}</span></div>
        <div class="kv"><span class="k">犯困阈值</span><span class="v">${escHtml(String(d.drowsy_threshold ?? '—'))}</span></div>
        <div class="kv"><span class="k">上次 Dream</span><span class="v">${escHtml(d.last_dream_date || '从未')}</span></div>
        ${cur ? `<div class="kv"><span class="k">进行中</span><span class="v">${this.dreamSummary(cur)}</span></div>` : ''}
        ${last ? `<div class="kv"><span class="k">最近完成</span><span class="v">${this.dreamSummary(last)}</span></div>` : ''}
      ` });
    } catch (e) { el.innerHTML = errorBlock(e.message); }
  },

  dreamSummary(row) {
    if (!row || typeof row !== 'object') return '—';
    const bits = [];
    if (row.status) bits.push(escHtml(row.status));
    if (row.started_at) bits.push(escHtml(fmtDateTime(row.started_at)));
    const narr = row.dream_narrative ? escHtml(String(row.dream_narrative).slice(0, 60)) : '';
    return (bits.join(' · ') || '—') + (narr ? `<br><span class="faint">${narr}…</span>` : '');
  },

  // ---- 做梦实况日志 ----
  logEmpty() {
    const log = this.root.querySelector('#dream-log');
    if (log) log.innerHTML = `<span class="faint" data-placeholder>（还没开始做梦）</span>`;
  },
  clearLog() { const log = this.root.querySelector('#dream-log'); if (log) log.innerHTML = ''; },
  appendLog(line, cls = '') {
    const log = this.root.querySelector('#dream-log');
    if (!log) return;
    log.querySelector('[data-placeholder]')?.remove();
    const div = document.createElement('div');
    if (cls) div.className = cls;
    div.innerHTML = line;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  },

  startDream(btn) {
    if (this.dreaming) { toast('正在做梦中…', 'info'); return; }
    this.dreaming = true;
    setBusy(btn, true, '做梦中');
    this.clearLog();
    this.appendLog(`<span class="faint">[${new Date().toLocaleTimeString('zh-CN')}] 开始 Dream（手动触发）…</span>`);
    this.loadStatus();

    const ts = () => `<span class="faint">[${new Date().toLocaleTimeString('zh-CN')}]</span> `;
    this.stream = sse('/dream/start', { trigger_type: 'manual' },
      (evType, data) => {
        // data 多为对象（可能含 message/error/narrative/step 等），也可能是纯文本
        let text;
        if (data && typeof data === 'object') {
          text = data.message || data.text || data.narrative || data.content || data.error || JSON.stringify(data);
        } else {
          text = String(data ?? '');
        }
        const err = (data && typeof data === 'object' && data.error) || evType === 'error';
        this.appendLog(`${ts()}<b>${escHtml(evType)}</b> ${escHtml(text)}`, err ? 'muted' : '');
      },
      {
        onDone: () => {
          this.appendLog(`${ts()}<span class="badge badge-accent">Dream 完成</span>`);
          this.dreaming = false; this.stream = null;
          setBusy(btn, false);
          toast('Dream 完成');
          this.loadStatus();
          this.state.history = []; this.state.scenes = [];   // 失效缓存，下次切页重拉
        },
        onError: (e) => {
          this.appendLog(`${ts()}<span class="badge badge-danger">出错：${escHtml(e.message)}</span>`);
          this.dreaming = false; this.stream = null;
          setBusy(btn, false);
          toast('Dream 出错：' + e.message, 'err');
          this.loadStatus();
        },
      });
  },

  async stopDream(btn) {
    setBusy(btn, true, '停止中');
    try {
      await post('/dream/stop');
      toast('已请求停止');
      this.appendLog(`<span class="faint">[${new Date().toLocaleTimeString('zh-CN')}] 已请求停止…</span>`);
    } catch (e) { toast('停止失败：' + e.message, 'err'); }
    finally { setBusy(btn, false); this.loadStatus(); }
  },

  async forceStop(btn) {
    if (!(await confirmDialog({ title: '强制中断 Dream', message: '强制中断会立刻终止当前 Dream 任务（可能留下半成品状态）。确定？', danger: true, okText: '强制中断' }))) return;
    setBusy(btn, true, '中断中');
    try {
      const r = await post('/admin/dream/force-stop');
      // SSE 已被服务端断开，本地也清理一下
      if (this.stream) { try { this.stream.abort(); } catch {} this.stream = null; }
      this.dreaming = false;
      const startBtn = this.root.querySelector('[data-act="startDream"]');
      if (startBtn) setBusy(startBtn, false);
      toast(r.message || '已强制中断');
      this.appendLog(`<span class="badge badge-warn">已强制中断</span>`);
    } catch (e) { toast('中断失败：' + e.message, 'err'); }
    finally { setBusy(btn, false); this.loadStatus(); }
  },

  // ============ 场景 ============
  async loadScenes() {
    const el = this.root.querySelector('#panel-scenes');
    el.innerHTML = loadingBlock();
    try {
      const d = await get('/dream/scenes');
      this.state.scenes = d.scenes || [];
      this.renderScenes();
    } catch (e) { el.innerHTML = errorBlock(e.message); }
  },

  findScene(id) { return (this.state.scenes || []).find(s => String(s.id) === String(id)); },

  renderScenes() {
    const el = this.root.querySelector('#panel-scenes');
    const scenes = this.state.scenes;
    if (!scenes.length) { el.innerHTML = emptyState({ icon: '🎬', msg: '还没有场景', hint: '做几次 Dream，碎片会被凝结成叙事场景' }); return; }
    el.innerHTML = `<div class="section-title">叙事场景 · 共 ${scenes.length} 个</div>` + scenes.map(s => {
      const facts = Array.isArray(s.atomic_facts) ? s.atomic_facts : [];
      const fore = Array.isArray(s.foresight) ? s.foresight : [];
      const rel = Array.isArray(s.related_memory_ids) ? s.related_memory_ids : [];
      return `
      <div class="item">
        <div class="item-row">
          <div style="flex:1;min-width:0">
            <div class="item-title">${escHtml(s.title || '（无标题场景）')} <span class="faint text-xs">#${escHtml(String(s.id))}</span></div>
            <div class="text-sm muted clamp3" style="margin-top:4px">${escHtml(s.narrative || '')}</div>
            <div class="btn-row mt8">
              ${s.status ? badge(String(s.status), 'muted') : ''}
              ${facts.length ? badge('原子事实 ' + facts.length, 'info') : ''}
              ${fore.length ? badge('前瞻 ' + fore.length, 'purple') : ''}
              ${rel.length ? badge('关联碎片 ' + rel.length, 'accent') : ''}
              <span class="faint text-xs">${escHtml(relTime(s.updated_at || s.created_at))}</span>
            </div>
          </div>
          <div class="item-actions">
            <button class="btn btn-xs btn-secondary" data-act="editScene" data-id="${escAttr(s.id)}">编辑</button>
          </div>
        </div>
      </div>`;
    }).join('');
  },

  editScene(s) {
    if (!s) { toast('场景不存在', 'err'); return; }
    const fore = Array.isArray(s.foresight) ? s.foresight.join('\n') : (s.foresight || '');
    const mod = modal({
      title: `编辑场景 #${s.id}`,
      wide: true,
      body: `
        <div class="field"><label>标题</label>${ctl.text('title', s.title || '', '场景标题…')}</div>
        <div class="field"><label>叙事</label>${ctl.area('narrative', s.narrative || '', 8, '这个场景讲了什么…')}</div>
        <div class="field"><label>前瞻（每行一条）</label>${ctl.area('foresight', fore, 4, '对未来的推断，每行一条…')}
          <div class="field-hint">每行一条，保存时合并为列表。</div>
        </div>`,
      footer: `<button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>保存</button>`,
    });
    mod.root.querySelector('[data-cancel]').onclick = () => mod.close();
    mod.root.querySelector('[data-save]').onclick = async (ev) => {
      const title = mod.root.querySelector('[data-key="title"]').value.trim();
      const narrative = mod.root.querySelector('[data-key="narrative"]').value.trim();
      const foresight = mod.root.querySelector('[data-key="foresight"]').value
        .split('\n').map(x => x.trim()).filter(Boolean);
      setBusy(ev.currentTarget, true, '保存中');
      try {
        const r = await put(`/admin/scene/${s.id}`, { title, narrative, foresight });
        if (r && r.status === 'not_found') { toast('场景已不存在', 'err'); setBusy(ev.currentTarget, false); return; }
        // 本地同步，避免整列表重拉
        Object.assign(s, { title, narrative, foresight });
        toast('已保存'); mod.close(); this.renderScenes();
      } catch (e) { toast('保存失败：' + e.message, 'err'); setBusy(ev.currentTarget, false); }
    };
  },

  // ============ 历史 ============
  async loadHistory() {
    const el = this.root.querySelector('#panel-history');
    el.innerHTML = loadingBlock();
    try {
      const d = await get('/dream/history?limit=20');
      this.state.history = d.history || [];
      this.renderHistory();
    } catch (e) { el.innerHTML = errorBlock(e.message); }
  },

  renderHistory() {
    const el = this.root.querySelector('#panel-history');
    const list = this.state.history;
    if (!list.length) { el.innerHTML = emptyState({ icon: '📜', msg: '还没有 Dream 记录', hint: '在「状态」页点「开始 Dream」试试' }); return; }
    const statusBadge = (st) => {
      const v = st === 'completed' ? 'accent' : st === 'running' ? 'purple' : st === 'interrupted' ? 'warn' : 'muted';
      return badge(st || '未知', v);
    };
    el.innerHTML = `<div class="section-title">Dream 历史 · 最近 ${list.length} 次</div>` + list.map(h => {
      const counts = [
        ['处理', h.memories_processed], ['合并', h.memories_merged], ['软化', h.memories_softened],
        ['删除', h.memories_deleted], ['新场景', h.scenes_created], ['更场景', h.scenes_updated],
        ['前瞻', h.foresights_generated], ['连接', h.links_created],
      ].filter(([, n]) => n != null && n !== 0)
        .map(([lbl, n]) => `<span class="badge badge-muted">${lbl} ${escHtml(String(n))}</span>`).join('');
      const narr = h.dream_narrative ? `<div class="text-sm muted clamp3" style="margin-top:6px">${escHtml(h.dream_narrative)}</div>` : '';
      return `
      <div class="item">
        <div class="item-row">
          <div style="flex:1;min-width:0">
            <div class="item-title">${escHtml(fmtDateTime(h.started_at))} ${statusBadge(h.status)} ${h.trigger_type ? badge(String(h.trigger_type), 'info') : ''}</div>
            <div class="item-sub">${h.model_used ? '模型 ' + escHtml(h.model_used) + ' · ' : ''}${h.finished_at ? '结束 ' + escHtml(fmtDateTime(h.finished_at)) : '未结束'}</div>
            <div class="btn-row mt8">${counts || '<span class="faint text-xs">无计数</span>'}</div>
            ${narr}
          </div>
          <div class="item-actions">
            <button class="btn btn-xs btn-danger-soft" data-act="delDream" data-id="${escAttr(h.id)}">删除</button>
          </div>
        </div>
      </div>`;
    }).join('');
  },

  async removeDream(id) {
    if (!(await confirmDialog({ title: '删除 Dream 记录', message: '确定删除这次 Dream 记录？由它创建的场景也会一并删除，不可恢复。', danger: true, okText: '删除' }))) return;
    try {
      await del(`/admin/dream/${id}`);
      toast('已删除');
      this.state.history = this.state.history.filter(h => String(h.id) !== String(id));
      this.state.scenes = [];   // 关联场景可能被删，失效缓存
      this.renderHistory();
    } catch (e) { toast('删除失败：' + e.message, 'err'); }
  },

  // ============ 参数 ============
  renderSettings() {
    const el = this.root.querySelector('#panel-settings');
    if (!el) return;
    el.innerHTML = renderConfigPage('dream', this.state.cfg);
    wireConfig(el, this.state.cfg);
  },
};
