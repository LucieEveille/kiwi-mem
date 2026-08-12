// ============================================================
// wizard.js — 首次配置三步向导（v1.6.1 新增，当前 v1.6.2）
//
// 触发：localStorage 无 kiwi-wizard-done 且后端没有任何供应商。
// 三步：① 添加供应商（真实保存+测试）② 勾选模型（真实保存）
//       ③ 前端连接说明（Base URL 复制）。
// 任何一步都能跳过；跳过/完成后写 localStorage，不再出现。
// 仪表盘的配置清单会接着引导没做完的事，进度不丢。
// ============================================================
import { get, post, escHtml, escAttr } from './api.js';
import { toast, setBusy } from './ui.js';

const DONE_KEY = 'kiwi-wizard-done';

export async function maybeShowWizard() {
  if (localStorage.getItem(DONE_KEY)) return;
  let providers = [];
  try { providers = (await get('/admin/providers')).providers || []; } catch { return; } // 后端不可用则不打扰
  if (providers.length > 0) { localStorage.setItem(DONE_KEY, '1'); return; }
  showWizard();
}

function finish() {
  localStorage.setItem(DONE_KEY, '1');
  document.getElementById('kiwi-wizard')?.remove();
}

function stepDots(cur) {
  const steps = [[1, '供应商'], [2, '选模型'], [3, '连前端']];
  return `<div class="wiz-steps">${steps.map(([n, label], i) => `
    <div class="wiz-step ${cur >= n ? 'on' : ''}" style="${i < 2 ? 'flex:1' : ''}">
      <span class="wiz-dot">${cur > n ? '✓' : n}</span><span class="wiz-lbl">${label}</span>
      ${i < 2 ? `<span class="wiz-line ${cur > n ? 'on' : ''}"></span>` : ''}
    </div>`).join('')}</div>`;
}

function shell(cur, bodyHtml, footHtml) {
  return `
    <div class="wiz-card">
      <div class="wiz-head">
        <div class="flex center gap12">
          <span class="wiz-logo">🥝</span>
          <div><div class="wiz-title">初次配置 · 三步连通</div><div class="wiz-sub">配完这三步，你的聊天软件就带上记忆了</div></div>
        </div>
        <button class="btn btn-ghost btn-sm" data-wiz="skip">跳过向导</button>
      </div>
      ${stepDots(cur)}
      <div class="wiz-body">${bodyHtml}</div>
      <div class="wiz-foot">${footHtml}</div>
      <div class="wiz-note">跳过后随时可以从仪表盘的配置清单继续，进度不会丢。</div>
    </div>`;
}

function showWizard() {
  const mask = document.createElement('div');
  mask.className = 'wiz-mask';
  mask.id = 'kiwi-wizard';
  document.body.appendChild(mask);
  const state = { providerId: null };
  renderStep1(mask, state);
  mask.addEventListener('click', (e) => {
    if (e.target.closest('[data-wiz="skip"]')) finish();
  });
}

// ---------- ① 供应商 ----------
function renderStep1(mask, state) {
  mask.innerHTML = shell(1, `
    <p class="wiz-p">kiwi-mem 自己不是 AI——它把你的话转发给你买的 AI 服务。先填上你的<b>中转站或官方 API</b>：</p>
    <div class="grid grid-2">
      <div class="field"><label>名称</label><input type="text" id="wz-name" placeholder="如：我的 OpenRouter"></div>
      <div class="field"><label>API 格式</label><select id="wz-fmt"><option value="openai">OpenAI 格式（大部分中转站）</option><option value="anthropic">Anthropic 原生</option></select></div>
    </div>
    <div class="field"><label>API 地址</label><input type="text" id="wz-url" class="mono" placeholder="https://openrouter.ai/api/v1"></div>
    <div class="field"><label>API Key</label><input type="password" id="wz-key" placeholder="sk-…"></div>
    <div class="field-hint">这是<b>中转站</b>的地址和 Key，不是 kiwi-mem 的。保存后会自动测试连接。</div>
  `, `<span></span><button class="btn btn-primary" data-wiz="save1">保存并测试 →</button>`);

  mask.querySelector('[data-wiz="save1"]').addEventListener('click', async (ev) => {
    const name = mask.querySelector('#wz-name').value.trim() || '我的供应商';
    const api_base_url = mask.querySelector('#wz-url').value.trim();
    const api_key = mask.querySelector('#wz-key').value;
    const api_format = mask.querySelector('#wz-fmt').value;
    if (!api_base_url) { toast('请填写 API 地址', 'err'); return; }
    setBusy(ev.currentTarget, true, '保存中');
    try {
      const r = await post('/admin/providers', { name, api_base_url, api_key, api_format });
      state.providerId = r.id ?? r.provider?.id;
      try { const t = await post(`/admin/test-provider/${state.providerId}`); toast('✅ ' + (t.message || '连接成功')); }
      catch (e) { toast('已保存，但测试失败：' + e.message + '（可稍后在供应商页重试）', 'err'); }
      renderStep2(mask, state);
    } catch (e) {
      toast('保存失败：' + e.message, 'err');
      setBusy(ev.currentTarget, false);
    }
  });
}

// ---------- ② 模型 ----------
async function renderStep2(mask, state) {
  mask.innerHTML = shell(2, `
    <p class="wiz-p">正在从供应商拉取可用模型…只有<b>保存过的模型</b>会出现在你聊天软件的模型列表里。</p>
    <div id="wz-models" class="wiz-models"><div class="loading-block"><span class="spinner"></span> 拉取中…</div></div>
    <div class="toolbar mt12" style="margin-bottom:0">
      <input type="text" id="wz-manual" class="grow mono" placeholder="拉不到？手动输入模型 ID，如 claude-sonnet-4-20250514">
      <button class="btn btn-secondary btn-sm" data-wiz="manual">+ 添加</button>
    </div>
  `, `<button class="btn btn-secondary" data-wiz="back1">← 上一步</button><button class="btn btn-primary" data-wiz="next3">下一步 →</button>`);

  mask.querySelector('[data-wiz="back1"]').addEventListener('click', () => renderStep1(mask, state));
  mask.querySelector('[data-wiz="next3"]').addEventListener('click', () => renderStep3(mask));
  const box = mask.querySelector('#wz-models');
  const addModel = async (mid, btn) => {
    if (btn) setBusy(btn, true, '');
    try { await post(`/admin/providers/${state.providerId}/saved-models`, { model_id: mid }); toast('已保存 ' + mid); if (btn) { btn.textContent = '✓ 已保存'; btn.disabled = true; } }
    catch (e) { toast('保存失败：' + e.message, 'err'); if (btn) setBusy(btn, false); }
  };
  mask.querySelector('[data-wiz="manual"]').addEventListener('click', () => {
    const mid = mask.querySelector('#wz-manual').value.trim();
    if (!mid) { toast('请输入模型 ID', 'err'); return; }
    addModel(mid); mask.querySelector('#wz-manual').value = '';
  });
  try {
    const d = await get(`/admin/providers/${state.providerId}/models`);
    const models = (d.models || []).map(x => x.id || x.model || x).filter(Boolean).slice(0, 30);
    box.innerHTML = models.length
      ? models.map(m => `<div class="wiz-model"><span class="mono text-sm">${escHtml(m)}</span><button class="btn btn-xs btn-primary" data-add="${escAttr(m)}">+ 保存</button></div>`).join('')
      : `<p class="muted text-sm">供应商没有返回模型列表（不一定是配错了）。用下面的输入框手动添加要用的模型 ID。</p>`;
    box.addEventListener('click', (e) => {
      const b = e.target.closest('[data-add]');
      if (b) addModel(b.dataset.add, b);
    });
  } catch (e) {
    box.innerHTML = `<p class="muted text-sm">拉取失败：${escHtml(e.message)}。用下面的输入框手动添加模型 ID。</p>`;
  }
}

// ---------- ③ 连前端 ----------
function renderStep3(mask) {
  const base = location.origin + '/v1';
  mask.innerHTML = shell(3, `
    <p class="wiz-p">最后，去你的聊天软件（ChatBox / Kelivo / SillyTavern…）的供应商设置里填：</p>
    <div class="wiz-terminal">
      <div class="wiz-t-label">API BASE URL</div>
      <div class="wiz-t-row"><span class="wiz-t-val">${escHtml(base)}</span><button class="btn btn-xs" data-wiz="copy" style="background:transparent;border:1px solid #3d4433;color:#c3c9b4">复制</button></div>
      <div class="wiz-t-label" style="margin-top:12px">API KEY</div>
      <div class="wiz-t-val">kiwi <span class="wiz-t-hint">（随便填，不能留空）</span></div>
    </div>
    <div class="banner banner-warn" style="margin:12px 0 0">⚠️ <div><b>最容易填错的地方</b>：这里填的是 <b>kiwi-mem 网关</b>的地址，<b>不是</b>刚才那个中转站的地址。前端连网关，网关连中转站。</div></div>
  `, `<button class="btn btn-secondary" data-wiz="back2">← 上一步</button><button class="btn btn-primary" data-wiz="done">完成，进入面板 →</button>`);

  mask.querySelector('[data-wiz="copy"]').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(base); toast('已复制'); } catch { toast('复制失败', 'err'); }
  });
  mask.querySelector('[data-wiz="back2"]').addEventListener('click', () => renderStep2(mask, { providerId: null }));
  mask.querySelector('[data-wiz="done"]').addEventListener('click', () => { finish(); toast('配置完成 🎉 试着在前端发条消息吧'); });
}
