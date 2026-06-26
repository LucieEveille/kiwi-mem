// 🪟 无缝换窗 — 纯配置（含总开关）+ v2 机制说明
import { loadConfig, renderConfigPage, wireConfig, ensureModelDatalist } from '../config.js';

export default {
  title: '无缝换窗',
  async mount(root) {
    ensureModelDatalist();
    root.innerHTML = `
      <p class="page-intro">开启后，新对话会自动衔接上一个对话，避免「一开新窗就失忆」。</p>
      <div class="banner banner-accent">
        <span>🪟</span>
        <div>
          <b>v2 已上线。</b>新对话开始时，自动注入上一个对话的「全程概要 + 结尾若干条原文」，<b>仅在首条消息注入一次</b>，之后随对话自身的压缩机制流转。概要由衔接模型生成（<code>handoff_summary_model</code>，留空跟随压缩模型），结尾原文条数由 <code>handoff_tail_count</code> 控制。
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
