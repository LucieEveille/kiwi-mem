// 🌡️ 记忆机制 — 热度 / 软化 / 自动锁定退役（纯配置页：旋钮全摆出来）
import { loadConfig, renderConfigPage, wireConfig, ensureModelDatalist } from '../config.js';

export default {
  title: '记忆机制',
  async mount(root) {
    ensureModelDatalist();
    root.innerHTML = `
      <p class="page-intro">这些旋钮共同决定记忆如何像人脑一样运转：高情绪、被反复提起的会升温变牢，又冷又老的会被温柔地软化、淡忘。改动即时生效。</p>
      <div id="cfg"></div>`;
    const cfg = await loadConfig().catch(() => ({}));
    const el = root.querySelector('#cfg');
    el.innerHTML = renderConfigPage('metabolism', cfg);
    wireConfig(el, cfg);
  },
};
