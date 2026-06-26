// 👤 用户画像 — AI 对你的长期认知（配置 + 立即更新动作）
import { post, escHtml } from '../api.js';
import { card, toast, delegate, setBusy, loadingBlock } from '../ui.js';
import { loadConfig, renderConfigGroups, wireConfig, ensureModelDatalist } from '../config.js';

export default {
  title: '用户画像',
  async mount(root) {
    this.root = root;
    ensureModelDatalist();
    root.innerHTML = `
      <p class="page-intro">用户画像是 AI 对你的整体认知（喜好、习惯、在意的事），会注入到 system prompt 的静态层。它由每日整理自动慢更新，也可以在下方手动编辑，或随时点「立即更新」让 AI 重新整理一遍。</p>
      <div id="profile-action" class="mb16"></div>
      <div id="profile-cfg">${loadingBlock()}</div>
    `;

    this.renderAction();
    delegate(root, { 'update-now': (el) => this.updateNow(el) });

    try {
      const cfg = await loadConfig();
      const el = this.root.querySelector('#profile-cfg');
      el.innerHTML = renderConfigGroups('profile', cfg);
      wireConfig(el, cfg);
    } catch (e) {
      this.root.querySelector('#profile-cfg').innerHTML =
        `<div class="banner banner-warn"><span>⚠️</span><div>配置加载失败：${escHtml(e.message)}</div></div>`;
    }
  },

  renderAction() {
    this.root.querySelector('#profile-action').innerHTML = card({
      title: '🔄 立即更新画像',
      desc: '让模型根据近期记忆重新整理一次用户画像（LLM 任务，可能需要几秒到几十秒）。',
      actions: `<button class="btn btn-primary" data-act="update-now">立即更新</button>`,
      body: `<div id="profile-result" class="text-sm muted"></div>`,
    });
  },

  async updateNow(btn) {
    const res = this.root.querySelector('#profile-result');
    setBusy(btn, true, '整理中');
    if (res) res.textContent = '正在让 AI 整理画像…';
    try {
      const r = await post('/admin/update-profile-now');
      const status = r.status || 'unknown';
      const map = {
        updated:   { msg: `画像已更新（${r.length ?? '—'} 字）`, type: 'ok' },
        unchanged: { msg: '画像无需更新：本次没有明显变化', type: 'info' },
        skipped:   { msg: `已跳过：${r.reason || '近期没有足够新内容'}`, type: 'info' },
        error:     { msg: `更新失败：${r.reason || '未知错误'}`, type: 'err' },
      };
      const out = map[status] || { msg: `返回状态：${status}`, type: 'info' };
      toast(out.msg, out.type);
      if (res) res.textContent = out.msg;
      // 更新成功后刷新画像配置区，显示最新内容
      if (status === 'updated') {
        const cfg = await loadConfig();
        const el = this.root.querySelector('#profile-cfg');
        el.innerHTML = renderConfigGroups('profile', cfg);
        wireConfig(el, cfg);
      }
    } catch (e) {
      toast('更新失败：' + e.message, 'err');
      if (res) res.textContent = '更新失败：' + e.message;
    } finally {
      setBusy(btn, false);
    }
  },
};
