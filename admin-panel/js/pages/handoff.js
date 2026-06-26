// 🪟 无缝换窗 — 纯配置（含总开关）+ v1 现状 / v2 立项标注
import { loadConfig, renderConfigPage, wireConfig, ensureModelDatalist } from '../config.js';

export default {
  title: '无缝换窗',
  async mount(root) {
    ensureModelDatalist();
    root.innerHTML = `
      <p class="page-intro">开启后，新对话会自动衔接上一个对话，避免「一开新窗就失忆」。</p>
      <div class="banner banner-info">
        <span>🪟</span>
        <div>
          <b>v1 现状：</b>新对话开始时，注入上一个对话的「全程概要 + 结尾若干条原文」，<b>仅在首条消息注入一次</b>。概要由衔接模型生成，结尾原文条数由 <code>handoff_tail_count</code> 控制。<br>
          <b>v2 已立项：</b>更平滑的跨窗衔接（增量续接、按需补全更多上下文），正在开发中，敬请期待。
        </div>
      </div>
      <div id="cfg"></div>
    `;
    const cfg = await loadConfig().catch(() => ({}));
    const el = root.querySelector('#cfg');
    el.innerHTML = renderConfigPage('handoff', cfg);
    wireConfig(el, cfg);
  },
};
