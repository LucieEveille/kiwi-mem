// 🚦 网关与延迟 — 状态总览 + 连接自检（逐接口测耗时）+ 性能配置（Prompt 缓存）
import { get, escHtml } from '../api.js';
import { card, statCard, badge, kv, emptyState, loadingBlock, toast, delegate, setBusy } from '../ui.js';
import { loadConfig, renderConfigGroups, wireConfig } from '../config.js';

// 连接自检要 ping 的关键接口
const PINGS = [
  { path: '/',             label: '网关根（/）',          desc: '基础状态与版本' },
  { path: '/admin/config', label: '配置（/admin/config）', desc: '管理配置读取' },
  { path: '/v1/models',    label: '模型列表（/v1/models）', desc: '前端可见模型' },
];

export default {
  title: '网关与延迟',
  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">网关是所有消息的必经之路。这里查看网关状态、逐个接口测一测往返延迟，并调节影响成本与速度的「Prompt 缓存」。</p>
      <div class="grid grid-4 mb16" id="gw-stats">${loadingBlock()}</div>
      <div id="gw-info"></div>
      ${card({
        title: '连接自检',
        desc: '逐个 ping 关键接口，测量往返耗时（performance.now），体现网关与消息延迟。',
        actions: `<button class="btn btn-primary btn-sm" data-act="ping">开始自检</button>`,
        id: 'gw-diag',
        body: `<div id="gw-ping">${emptyState({ icon: '📡', msg: '尚未自检', hint: '点右上「开始自检」逐接口测延迟' })}</div>`,
      })}
      <div class="section-title mt24">性能</div>
      <div id="gw-cfg">${loadingBlock()}</div>
    `;

    delegate(root, {
      ping: (el) => this.runPings(el),
    });

    this.loadStatus();
    this.loadCfg();
  },

  async loadStatus() {
    const stats = this.root.querySelector('#gw-stats');
    const info = this.root.querySelector('#gw-info');
    try {
      const s = await get('/');
      const memOn = s.memory_enabled;
      stats.innerHTML =
        statCard({ label: '🚦 版本', value: escHtml(s.version || s.gateway || '—'), cls: 'accent' }) +
        statCard({ label: '🧠 记忆系统', value: memOn ? '✅ 开启' : '⛔ 关闭', cls: memOn ? 'accent' : '' }) +
        statCard({ label: '⏱️ 提取间隔', value: (s.extract_interval ?? '—') + ' 轮', cls: 'info' }) +
        statCard({ label: '📥 注入上限', value: (s.max_inject ?? '—') + ' 条', cls: 'purple' });
      info.innerHTML = card({
        title: '网关概览',
        body:
          kv('网关', escHtml(s.gateway || '—')) +
          kv('版本', escHtml(s.version || '—')) +
          kv('默认模型', `<span class="mono">${escHtml(s.default_model || '—')}</span>`) +
          kv('记忆系统', s.memory_enabled ? badge('开启', 'accent') : badge('关闭', 'danger')) +
          kv('记忆提取间隔', `每 ${escHtml(String(s.extract_interval ?? '—'))} 轮`) +
          kv('单次注入上限', `${escHtml(String(s.max_inject ?? '—'))} 条`),
      });
    } catch (e) {
      stats.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>无法连接网关：${escHtml(e.message)}</div></div>`;
      info.innerHTML = '';
      toast(e.message, 'err');
    }
  },

  async runPings(btn) {
    const box = this.root.querySelector('#gw-ping');
    setBusy(btn, true, '自检中');
    box.innerHTML = loadingBlock('正在逐个 ping 接口…');
    const rows = [];
    for (const p of PINGS) {
      const t0 = performance.now();
      let ok = true, errMsg = '';
      try {
        await get(p.path);
      } catch (e) {
        ok = false;
        errMsg = e.message;
      }
      const ms = Math.round(performance.now() - t0);
      rows.push({ ...p, ok, ms, errMsg });
    }
    const total = rows.reduce((a, r) => a + r.ms, 0);
    box.innerHTML = `
      <table class="table">
        <thead><tr><th>接口</th><th>状态</th><th class="num">耗时</th></tr></thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td><div><b>${escHtml(r.label)}</b></div><div class="item-sub">${escHtml(r.desc)}${r.ok ? '' : ` · <span style="color:var(--c-danger)">${escHtml(r.errMsg)}</span>`}</div></td>
              <td>${r.ok ? badge('✓ 通', 'accent') : badge('✗ 失败', 'danger')}</td>
              <td class="num mono">${r.ms} ms</td>
            </tr>`).join('')}
        </tbody>
        <tfoot><tr><td colspan="2" class="muted">合计</td><td class="num mono">${total} ms</td></tr></tfoot>
      </table>`;
    setBusy(btn, false);
  },

  async loadCfg() {
    const el = this.root.querySelector('#gw-cfg');
    try {
      const cfg = await loadConfig();
      el.innerHTML = renderConfigGroups('gateway', cfg);
      wireConfig(el, cfg);
    } catch (e) {
      el.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>加载配置失败：${escHtml(e.message)}</div></div>`;
    }
  },
};
