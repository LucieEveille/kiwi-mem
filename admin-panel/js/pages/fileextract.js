// 📎 文件提取 — multipart 上传 → 提取文本（调试侧栏文件处理）
import { escHtml, fmtBytes } from '../api.js';
import { toast, emptyState, setBusy, delegate, badge, copyText } from '../ui.js';

export default {
  title: '文件提取',
  result: null,

  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">上传文件，提取其中的文本内容。支持 PDF / DOCX / XLSX / ZIP 及纯文本等格式，便于调试聊天侧栏的文件处理逻辑（超长会截断到约 10 万字）。</p>
      <div class="card">
        <div class="toolbar" style="margin-bottom:0">
          <input type="file" id="fx-file" class="grow">
          <button class="btn btn-primary" data-act="upload">上传并提取</button>
        </div>
      </div>
      <div id="fx-result" class="mt16">${emptyState({ icon: '📄', msg: '还没有提取结果', hint: '选择一个文件后点「上传并提取」' })}</div>
    `;

    delegate(root, {
      upload: (el) => this.upload(el),
      copy: () => { if (this.result?.text) copyText(this.result.text); },
    });
  },

  async upload(btn) {
    const input = this.root.querySelector('#fx-file');
    const file = input?.files?.[0];
    if (!file) { toast('请先选择文件', 'err'); return; }

    const box = this.root.querySelector('#fx-result');
    setBusy(btn, true, '提取中');
    box.innerHTML = '';
    try {
      const formData = new FormData();
      formData.append('file', file);
      // multipart 必须用原生 fetch，且不要手动设置 Content-Type（让浏览器带 boundary）
      const res = await fetch(window.location.origin + '/v1/files/extract', {
        method: 'POST',
        body: formData,
      });
      const text = await res.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; }
      catch { throw new Error(res.ok ? '响应解析失败' : `服务器错误 (${res.status})`); }
      if (!res.ok) throw new Error(data?.error || `服务器错误 (${res.status})`);
      if (data && data.error) throw new Error(data.error);
      this.result = data;
      this.renderResult(data);
    } catch (e) {
      this.result = null;
      box.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>提取失败：${escHtml(e.message || '未知错误')}</div></div>`;
    } finally {
      setBusy(btn, false);
    }
  },

  renderResult(d) {
    const box = this.root.querySelector('#fx-result');
    const txt = d.text ?? '';
    box.innerHTML = `
      <div class="card">
        <div class="card-head">
          <div>
            <div class="card-title">${escHtml(d.filename || '(未命名)')} ${d.type ? badge(d.type, 'info') : ''}</div>
            <div class="card-desc">大小 ${fmtBytes(d.size)} · 文本 ${txt.length} 字</div>
          </div>
          <div class="btn-row"><button class="btn btn-sm btn-secondary" data-act="copy">复制文本</button></div>
        </div>
        <textarea class="mono" rows="18" readonly spellcheck="false" placeholder="（无文本内容）">${escHtml(txt)}</textarea>
      </div>`;
  },
};
