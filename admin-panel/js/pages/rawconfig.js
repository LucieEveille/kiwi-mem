// ⚙️ 全部配置 — 兜底全量视图：遍历所有页分组 + orphan 兜底，一次 wireConfig 即时保存
import { escHtml } from '../api.js';
import { card, cfgRow, badge, loadingBlock, toast } from '../ui.js';
import { loadConfig, renderConfigGroups, wireConfig, ensureModelDatalist } from '../config.js';
import { CONFIG_META, CONFIG_PAGES, RESTORABLE_PROMPTS, orphanKeys } from '../config-schema.js';

// 各页的中文小标题（仅本兜底页展示用；页 key 来自 CONFIG_PAGES）
const PAGE_TITLES = {
  memories: '🧩 记忆系统',
  metabolism: '🌡️ 记忆机制',
  dream: '🌙 Dream',
  profile: '👤 用户画像',
  calendar: '📅 日历与整理',
  compression: '🗜️ 上下文压缩',
  handoff: '🪟 无缝换窗',
  tools: '🛠️ 工具抽屉',
  websearch: '🌐 联网搜索',
  phrases: '⚡ 指令与短语',
  providers: '🔌 供应商与模型',
  gateway: '🚦 网关与性能',
  sync: '☁️ 云同步偏好',
};

// 为 orphan key 生成与 config.js 一致的控件（带 data-cfg + data-key 供 wireConfig 自动保存）。
// 不引入 config.js 私有函数，按 input 类型自行拼装。
function orphanControl(key, val) {
  const m = CONFIG_META[key] || { input: 'text' };
  const v = val ?? '';
  const attr = `data-cfg data-key="${escHtml(key)}"`;
  switch (m.input) {
    case 'bool':
      return `<label class="switch"><input type="checkbox" ${attr} data-bool ${String(v) === 'true' ? 'checked' : ''}><span class="slider"></span></label>`;
    case 'int':
      return `<input type="number" step="1" ${attr} value="${escHtml(v)}">`;
    case 'float':
      return `<input type="number" step="0.01" ${attr} value="${escHtml(v)}">`;
    case 'pass':
      return `<input type="password" ${attr} value="${escHtml(v)}" placeholder="••••••">`;
    case 'model':
      return `<input type="text" list="model-datalist" ${attr} value="${escHtml(v)}" placeholder="留空跟随聊天模型">`;
    case 'json':
      return `<textarea class="mono" ${attr} rows="4" spellcheck="false" placeholder="JSON">${escHtml(v)}</textarea>`;
    case 'prompt':
      // 兜底页对 prompt 也用 mono textarea 直接编辑（改动即时保存，无需弹窗）
      return `<textarea class="mono" ${attr} rows="6" spellcheck="false" placeholder="留空用内置默认">${escHtml(v)}</textarea>`;
    default:
      return `<input type="text" ${attr} value="${escHtml(v)}">`;
  }
}

function orphanRow(key, cfg) {
  const m = CONFIG_META[key] || {};
  const restorable = RESTORABLE_PROMPTS.includes(key);
  return cfgRow({
    key,
    label: m.label || key,
    control: orphanControl(key, cfg[key]),
    desc: (m.desc || '') + (restorable ? ' （可在「提示词模板」页恢复默认）' : ''),
    def: m.def && m.def !== '' ? m.def : '',
  });
}

export default {
  title: '全部配置',
  async mount(root) {
    this.root = root;
    ensureModelDatalist();
    root.innerHTML = `
      <p class="page-intro">这是所有配置项的全量兜底视图，确保「一个旋钮都不漏」。改动即时保存。</p>
      <div class="banner banner-info"><span>💡</span><div>
        平时建议去对应的<b>功能页</b>修改——那里有更友好的分组、说明与专用编辑器。
        这一页主要用于排查「某项配置藏在哪」或修改尚未编排进功能页的冷门项。
      </div></div>
      <div id="rc-body">${loadingBlock()}</div>
    `;

    let cfg;
    try {
      cfg = await loadConfig();
    } catch (e) {
      this.root.querySelector('#rc-body').innerHTML =
        `<div class="banner banner-warn"><span>⚠️</span><div>加载配置失败：${escHtml(e.message)}</div></div>`;
      toast(e.message, 'err');
      return;
    }

    const box = this.root.querySelector('#rc-body');
    let html = '';

    // 各功能页的分组
    for (const pageKey of Object.keys(CONFIG_PAGES)) {
      const groups = renderConfigGroups(pageKey, cfg);
      if (!groups) continue;
      html += `<div class="section-title mt24">${escHtml(PAGE_TITLES[pageKey] || pageKey)}</div>`;
      html += groups;
    }

    // orphan 兜底：未编排进任何页的 key
    const orphans = orphanKeys();
    if (orphans.length) {
      html += `<div class="section-title mt24">🧷 其它（未编排）${badge(String(orphans.length), 'muted')}</div>`;
      html += card({ body: orphans.map(k => orphanRow(k, cfg)).join('') });
    }

    box.innerHTML = html;
    // 整页一次 wireConfig 即可即时保存（含 master 联动；orphan 控件也带 data-cfg）
    wireConfig(box, cfg);
  },
};
