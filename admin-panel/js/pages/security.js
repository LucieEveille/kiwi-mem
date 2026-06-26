// 🔐 认证与安全 — 说明为主：访问密码已移除、密钥脱敏。只读列出供应商 key 预览。
import { get, escHtml } from '../api.js';
import { card, badge, emptyState, loadingBlock, toast } from '../ui.js';

export default {
  title: '认证与安全',
  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">这一页讲清 kiwi-mem 公开版的认证现状与密钥保护方式。本页仅作信息展示与只读核对，无任何破坏性操作。</p>

      <div class="banner banner-warn"><span>🔓</span><div>
        <b>公开版已移除访问密码。</b> 后端 <code>/auth/verify</code> 始终放行——任何能访问到本服务地址的人都能使用。
        如需保护，请把服务部署在<b>私有网络 / 反向代理鉴权</b>之后，不要把公网地址直接公开。
      </div></div>

      ${card({
        title: '① 前端访问密码',
        body: `<p class="muted" style="line-height:1.7;margin:0">
          公开版<b>不再校验前端访问密码</b>（<code>/auth/verify</code> 恒返回「无需密码」）。
          私人后端如需密码门禁，由配套的 React 聊天前端自带的登录逻辑处理，与本网关无关。
        </p>`,
      })}

      ${card({
        title: '② 管理密钥',
        cls: 'mt16',
        body: `<p class="muted" style="line-height:1.7;margin:0">
          本管理面板与后端之间<b>不携带额外认证头</b>。若你的部署需要管理密钥，
          应在<b>反向代理（如 Nginx / Caddy）或环境变量</b>层面施加，而非依赖前端。
          切勿把可写的管理接口暴露到公网。
        </p>`,
      })}

      ${card({
        title: '③ API Key 脱敏',
        cls: 'mt16',
        body: `<p class="muted" style="line-height:1.7;margin:0">
          面板里所有供应商 / 搜索引擎的密钥<b>从不回显明文</b>。供应商接口只返回
          <code>api_key_preview</code>（如 <code>sk-…abc</code>）。编辑时<b>留空表示保持原值不变</b>，
          填新值才会覆盖。下方为当前已配置供应商的脱敏预览，供你核对而不泄露密钥。
        </p>`,
      })}

      <div class="section-title mt24">已配置供应商（只读·脱敏）</div>
      <div id="sec-provs">${loadingBlock()}</div>
    `;

    this.loadProviders();
  },

  async loadProviders() {
    const el = this.root.querySelector('#sec-provs');
    try {
      const d = await get('/admin/providers');
      const list = d.providers || [];
      if (!list.length) {
        el.innerHTML = emptyState({ icon: '🔌', msg: '还没有配置供应商', hint: '前往「供应商与模型」页接入 API' });
        return;
      }
      el.innerHTML = list.map(p => {
        const hasKey = !!p.api_key_preview;
        return `
        <div class="item">
          <div class="item-row">
            <div style="flex:1;min-width:0">
              <div class="item-title">${escHtml(p.name || '未命名')} ${badge(p.api_format || 'openai', p.api_format === 'anthropic' ? 'purple' : 'info')}</div>
              <div class="item-sub mono truncate">${escHtml(p.api_base_url || '')}</div>
              <div class="item-sub">Key 预览：<span class="mono">${escHtml(p.api_key_preview || '（未设置）')}</span></div>
            </div>
            <div class="item-actions">
              ${hasKey ? badge('🔒 已脱敏', 'accent') : badge('未设置密钥', 'muted')}
            </div>
          </div>
        </div>`;
      }).join('');
    } catch (e) {
      el.innerHTML = `<div class="banner banner-warn"><span>⚠️</span><div>加载供应商失败：${escHtml(e.message)}</div></div>`;
      toast(e.message, 'err');
    }
  },
};
