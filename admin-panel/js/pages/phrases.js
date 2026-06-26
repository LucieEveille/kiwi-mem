// ⚡ 指令与快捷短语 — custom_skills / quick_phrases（JSON 配置，同步给聊天前端）
import { escHtml } from '../api.js';
import { loadConfig, renderConfigGroups, wireConfig } from '../config.js';

export default {
  title: '指令与快捷短语',
  async mount(root) {
    root.innerHTML = `
      <p class="page-intro">这两组配置会同步给聊天前端，供「快捷输入」与「自定义技能」使用。两者都是 JSON 文本，改动即时保存。</p>
      <div class="banner banner-info"><span>💡</span><div>
        <b>JSON 格式提示：</b>「自定义技能」常为对象数组，如
        <code>[{"name":"翻译","prompt":"把以下内容翻译成英文"}]</code>；
        「快捷短语」常为字符串数组，如 <code>["今天天气如何？","帮我总结一下"]</code>。
        留空表示不启用。格式以聊天前端的约定为准，保存后请在前端验证生效。
      </div></div>
      <div id="cfg"></div>`;

    const el = root.querySelector('#cfg');
    try {
      const cfg = await loadConfig();
      el.innerHTML = renderConfigGroups('phrases', cfg);
      wireConfig(el, cfg);
    } catch (e) {
      el.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>加载配置失败：${escHtml(e.message)}</div></div>`;
    }
  },
};
