// 📜 提示词模板 — 集中编辑全部 prompt_* 与 user_profile（自实现弹窗，不依赖 config.js 私有函数）
import { get, post, escHtml } from '../api.js';
import { card, badge, emptyState, loadingBlock, toast, modal, delegate, setBusy } from '../ui.js';
import { loadConfig, saveConfig } from '../config.js';
import { CONFIG_META, RESTORABLE_PROMPTS } from '../config-schema.js';

// 从登记表里筛出所有「提示词」类配置项（input==='prompt'，含 user_profile）
const PROMPT_KEYS = Object.keys(CONFIG_META).filter(k => CONFIG_META[k].input === 'prompt');

function preview(val) {
  const s = String(val ?? '');
  if (!s) return '（空 · 用代码内置默认）';
  return s.slice(0, 60) + (s.length > 60 ? '…' : '');
}

export default {
  title: '提示词模板',
  async mount(root) {
    this.root = root;
    this.cfg = {};
    root.innerHTML = `
      <p class="page-intro">这里集中编辑所有提示词模板（记忆提取、每日整理、Dream、用户画像等）。留空则使用代码内置的默认提示词；可恢复默认的项会显示「恢复默认」按钮。</p>
      <div id="pr-list">${loadingBlock()}</div>
    `;

    delegate(root, {
      edit:    (el) => this.openEditor(el.dataset.key),
      restore: (el) => this.restore(el.dataset.key, el),
    });

    await this.load();
  },

  async load() {
    const el = this.root.querySelector('#pr-list');
    try {
      this.cfg = await loadConfig();
    } catch (e) {
      el.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>加载配置失败：${escHtml(e.message)}</div></div>`;
      toast(e.message, 'err');
      return;
    }
    this.render();
  },

  render() {
    const el = this.root.querySelector('#pr-list');
    if (!PROMPT_KEYS.length) {
      el.innerHTML = emptyState({ icon: '📜', msg: '没有可编辑的提示词' });
      return;
    }
    el.innerHTML = PROMPT_KEYS.map(k => this.rowHtml(k)).join('');
  },

  rowHtml(key) {
    const m = CONFIG_META[key] || {};
    const val = this.cfg[key];
    const restorable = RESTORABLE_PROMPTS.includes(key);
    const filled = !!String(val ?? '');
    return `
      <div class="item" data-row="${escHtml(key)}">
        <div class="item-row">
          <div style="flex:1;min-width:0">
            <div class="item-title">${escHtml(m.label || key)} ${filled ? badge('已自定义', 'accent') : badge('默认', 'muted')}</div>
            <div class="item-sub mono faint">${escHtml(key)}</div>
            ${m.desc ? `<div class="item-sub">${escHtml(m.desc)}</div>` : ''}
            <div class="item-sub mono truncate" data-preview style="margin-top:6px">${escHtml(preview(val))}</div>
          </div>
          <div class="item-actions">
            <button class="btn btn-xs btn-secondary" data-act="edit" data-key="${escHtml(key)}">✎ 编辑</button>
            ${restorable ? `<button class="btn btn-xs btn-ghost" data-act="restore" data-key="${escHtml(key)}">恢复默认</button>` : ''}
          </div>
        </div>
      </div>`;
  },

  // 刷新单行的预览与「已自定义/默认」徽章
  refreshRow(key) {
    const row = this.root.querySelector(`[data-row="${CSS.escape(key)}"]`);
    if (!row) return;
    const prev = row.querySelector('[data-preview]');
    if (prev) prev.textContent = preview(this.cfg[key]);
    const title = row.querySelector('.item-title');
    const filled = !!String(this.cfg[key] ?? '');
    if (title) {
      const b = title.querySelector('.badge');
      if (b) { b.textContent = filled ? '已自定义' : '默认'; b.className = 'badge ' + (filled ? 'badge-accent' : 'badge-muted'); }
    }
  },

  openEditor(key) {
    const m = CONFIG_META[key] || {};
    const val = this.cfg[key] ?? '';
    const restorable = RESTORABLE_PROMPTS.includes(key);
    const mod = modal({
      title: m.label || key,
      wide: true,
      body: `${m.desc ? `<div class="card-desc mb12">${escHtml(m.desc)}</div>` : ''}
        <textarea class="mono" id="pr-edit-area" rows="20" spellcheck="false" placeholder="留空则使用代码内置默认提示词">${escHtml(val)}</textarea>`,
      footer: `${restorable ? `<button class="btn btn-ghost" data-load-default>载入内置默认</button>` : ''}<span class="spacer"></span><button class="btn btn-secondary" data-cancel>取消</button><button class="btn btn-primary" data-save>保存</button>`,
    });
    const area = mod.root.querySelector('#pr-edit-area');
    mod.root.querySelector('[data-cancel]').addEventListener('click', () => mod.close());
    mod.root.querySelector('[data-save]').addEventListener('click', async (ev) => {
      const btn = ev.currentTarget;
      setBusy(btn, true, '保存中');
      try {
        await saveConfig(key, area.value);
        this.cfg[key] = area.value;
        this.refreshRow(key);
        toast('已保存');
        mod.close();
      } catch (e) {
        toast('保存失败：' + e.message, 'err');
        setBusy(btn, false);
      }
    });
    // 仅把内置默认载入文本框（需用户再点保存才落库）——与「恢复默认」按钮区分
    mod.root.querySelector('[data-load-default]')?.addEventListener('click', async (ev) => {
      const btn = ev.currentTarget;
      setBusy(btn, true, '载入中');
      try {
        const d = await get('/admin/default-prompts');
        const def = (d.prompts || {})[key];
        if (def == null) { toast('没有该项的内置默认', 'err'); }
        else { area.value = def; toast('已载入内置默认（记得点保存）'); }
      } catch (e) {
        toast('载入失败：' + e.message, 'err');
      } finally {
        setBusy(btn, false);
      }
    });
  },

  async restore(key, btn) {
    setBusy(btn, true, '恢复中');
    try {
      await post(`/admin/restore-prompt/${key}`);
      // 重新拉取该 key 的最新值（restore 会写库为内置默认或清空）
      const fresh = await loadConfig();
      this.cfg[key] = fresh[key];
      this.refreshRow(key);
      toast('已恢复内置默认');
    } catch (e) {
      toast('恢复失败：' + e.message, 'err');
    } finally {
      setBusy(btn, false);
    }
  },
};
