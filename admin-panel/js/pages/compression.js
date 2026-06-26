// 🗜️ 上下文压缩 — 纯配置页（含总开关 + 触发/保留/模型等参数）
import { loadConfig, renderConfigPage, wireConfig, ensureModelDatalist } from '../config.js';

export default {
  title: '上下文压缩',
  async mount(root) {
    ensureModelDatalist();
    root.innerHTML = `
      <p class="page-intro">对话太长时，自动把靠前的消息压成摘要塞回上下文——省 token 又不失忆。下方旋钮决定何时触发、保留多少原文、用哪个模型。改动即时生效。</p>
      <div id="cfg"></div>`;
    const cfg = await loadConfig().catch(() => ({}));
    const el = root.querySelector('#cfg');
    el.innerHTML = renderConfigPage('compression', cfg);
    wireConfig(el, cfg);
  },
};
