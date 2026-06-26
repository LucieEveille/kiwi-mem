// 🌙 Dream — 记忆整合（状态 + 触发流 + 参数）。动作驱动，pill-tabs。
import { get, post, sse, escHtml, fmtDateTime } from '../api.js';
import { card, badge, loadingBlock, errorBlock, toast, confirmDialog, delegate, setBusy } from '../ui.js';
import { loadConfig, renderConfigPage, wireConfig, ensureModelDatalist } from '../config.js';

export default {
  title: 'Dream',
  state: { tab: 'status', cfg: {} },

  async mount(root) {
    this.root = root;
    this.stream = null;       // 当前 SSE 句柄
    this.dreaming = false;    // 是否正在做梦（流式中）
    ensureModelDatalist();

    root.innerHTML = `
      <p class="page-intro">Dream 是 kiwi-mem 的「睡眠」：在空闲时把零散碎片清理、融合、推断前瞻，凝结成叙事场景。未处理碎片积太多时 AI 会犯困、提示该睡了。</p>
      <div class="pill-tabs" id="tabs">
        <div class="pill-tab active" data-act="tab" data-tab="status">🌙 状态</div>
        <div class="pill-tab" data-act="tab" data-tab="settings">⚙️ 参数</div>
      </div>
      <div id="panel-status"></div>
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
    ['status', 'settings'].forEach(name => {
      const p = this.root.querySelector(`#panel-${name}`);
      if (p) p.style.display = name === tab ? '' : 'none';
    });
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
    return bits.join(' · ') || '—';
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

  // ============ 参数 ============
  renderSettings() {
    const el = this.root.querySelector('#panel-settings');
    if (!el) return;
    el.innerHTML = renderConfigPage('dream', this.state.cfg);
    wireConfig(el, this.state.cfg);
  },
};
