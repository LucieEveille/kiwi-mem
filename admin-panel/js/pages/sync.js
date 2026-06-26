// 💾 备份与数据 — 整体备份导出/导入 + 危险区重置（不做内容浏览，内容浏览交给客户端）
import { del, download, API } from '../api.js';
import { loadingBlock, errorBlock, toast, confirmDialog, delegate, setBusy } from '../ui.js';

export default {
  title: '备份与数据',

  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">整库备份与恢复（对话、项目、记忆、配置一并打包），以及危险区的同步数据重置。对话与记忆的内容浏览交给客户端，后端面板只做数据运维。</p>

      <div class="card">
        <div class="card-title">📦 整体备份</div>
        <div class="card-desc">导出 zip：对话、项目、记忆、配置、同步设置。导入会按备份内容合并恢复。</div>
        <div class="btn-row mt8">
          <button class="btn btn-secondary" data-act="export">⬇️ 导出备份（zip）</button>
          <button class="btn btn-primary" data-act="import">⬆️ 导入备份</button>
          <input type="file" id="backup-file" accept=".zip,application/zip" style="display:none">
        </div>
        <div id="import-result" class="mt8"></div>
      </div>

      <div class="card" style="border-color:rgba(192,73,47,.4)">
        <div class="card-title" style="color:var(--c-danger)">⚠️ 危险区 · 重置同步数据</div>
        <div class="banner banner-danger mt8"><span>⚠️</span><div>
          此操作会<b>清空全部对话、项目与同步设置键</b>（记忆碎片与其他配置会被保留）。删除后<b>无法恢复</b>，请先导出备份。
        </div></div>
        <div class="field mt16">
          <label>输入确认码 <code>RESET_ALL_DATA</code> 以解锁重置按钮</label>
          <input type="text" id="reset-code" placeholder="RESET_ALL_DATA" spellcheck="false" autocomplete="off">
        </div>
        <div class="btn-row mt8">
          <button class="btn btn-danger" id="reset-btn" data-act="reset" disabled>重置全部同步数据</button>
        </div>
      </div>
    `;

    delegate(root, {
      export: () => this.doExport(),
      import: () => this.root.querySelector('#backup-file')?.click(),
      reset: (el) => this.doReset(el),
    });
    this.root.querySelector('#backup-file').addEventListener('change', (e) => this.doImport(e.target));
    const code = this.root.querySelector('#reset-code');
    const btn = this.root.querySelector('#reset-btn');
    code.addEventListener('input', () => { btn.disabled = code.value.trim() !== 'RESET_ALL_DATA'; });
  },

  doExport() {
    try { download('/sync/export'); toast('已开始下载备份'); }
    catch (e) { toast('导出失败：' + e.message, 'err'); }
  },

  async doImport(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    const resultEl = this.root.querySelector('#import-result');
    resultEl.innerHTML = loadingBlock('导入中，请稍候…');
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await fetch(API + '/sync/import-backup', { method: 'POST', body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) throw new Error(data.error || `服务器错误 (${res.status})`);
      const n = (k) => data[k] ?? 0;
      resultEl.innerHTML = `<div class="banner banner-info"><span>✅</span><div>
        导入完成：对话 ${n('conversations')} · 消息 ${n('messages')} · 项目 ${n('projects')} · 记忆 ${n('memories')} · 设置 ${n('settings')} · 配置 ${n('config')}
      </div></div>`;
      toast('备份导入成功');
    } catch (e) {
      resultEl.innerHTML = errorBlock('导入失败：' + e.message);
      toast('导入失败：' + e.message, 'err');
    } finally {
      input.value = ''; // 允许再次选同一文件
    }
  },

  async doReset(btn) {
    const code = this.root.querySelector('#reset-code')?.value.trim();
    if (code !== 'RESET_ALL_DATA') { toast('确认码不正确', 'err'); return; }
    if (!(await confirmDialog({
      title: '最终确认',
      message: '真的要清空全部对话、项目与同步设置吗？此操作不可恢复。',
      danger: true, okText: '我确认，清空',
    }))) return;
    setBusy(btn, true, '重置中');
    try {
      const r = await del('/sync/reset', { confirm: 'RESET_ALL_DATA' });
      toast(`已重置：对话 ${r.deleted_conversations ?? 0} · 项目 ${r.deleted_projects ?? 0}`);
      const c = this.root.querySelector('#reset-code'); if (c) c.value = '';
    } catch (e) {
      toast('重置失败：' + e.message, 'err');
    } finally {
      setBusy(btn, false);
      const c = this.root.querySelector('#reset-code');
      this.root.querySelector('#reset-btn').disabled = !c || c.value.trim() !== 'RESET_ALL_DATA';
    }
  },
};
