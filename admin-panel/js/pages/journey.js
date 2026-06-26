// 🗺️ 消息旅程 — 一条消息如何走完十二层 system prompt（只读讲解 / 诊断）
import { get, escHtml } from '../api.js';
import { card, badge, loadingBlock } from '../ui.js';

// system prompt 的注入层次：静态在前（命中缓存），动态在后。
const LAYERS = [
  { static: true,  emoji: '🎭', name: '人设 / system prompt',   desc: '助手是谁、说话风格、底线规则。最静态，放最前面，作为缓存前缀的开头。' },
  { static: true,  emoji: '👤', name: '用户画像',               desc: 'AI 对你长期累积的整体认知。由每日整理慢更新，单次对话内不变。' },
  { static: true,  emoji: '🔒', name: '锁定记忆',               desc: '被手动 / 自动锁定的核心记忆，始终在场，不随检索波动。' },
  { static: true,  emoji: '📅', name: '日历摘要',               desc: '最近的日 / 周 / 月 / 季 / 年总结，让 AI 知道近来发生了什么。当天内基本稳定。' },
  { static: true,  emoji: '🎬', name: '场景',                   desc: 'Dream 整合出的叙事场景，长期记忆的宏观视角。变化缓慢。' },
];

const DYNAMIC = [
  { emoji: '🧠', name: '语义检索碎片',   desc: '按当前这句话实时检索出的相关记忆碎片（RRF 排序）。每轮都可能不同——所以放在缓存分界线之后。' },
  { emoji: '🪟', name: '衔接概要',       desc: '无缝换窗：新对话开头注入上一对话的全程概要 + 结尾原文。仅首条注入一次。' },
  { emoji: '🕒', name: '当前时间',       desc: '由网关在最后一刻自动注入，确保 AI 知道「现在」。正因为它每次都变，必须放最后，否则会击穿前面的缓存。' },
  { emoji: '😴', name: '犯困提示',       desc: '未处理碎片堆积过多时追加的提示，AI 会表现得有点困、提醒该让它 Dream 一下了。' },
];

export default {
  title: '消息旅程',
  async mount(root) {
    this.root = root;
    root.innerHTML = `
      <p class="page-intro">一条消息发给 kiwi-mem，并不是「裸」地丢给模型——网关会在它前面拼起一整摞 system prompt，从最静态的人设到最动态的当前时间，层层叠好再转发。理解这条旅程，就理解了整个记忆系统如何「上桌」。</p>

      <div id="jr-stats" class="grid grid-4 mb16">${loadingBlock()}</div>

      <div class="section-title">📚 system prompt 的注入层次</div>
      <p class="page-intro">原则只有一句：<b>静态在前、动态在后</b>。前面这几层在一次对话里几乎不变，正好被 Claude 的 prompt 缓存整段命中，重复输入只收约 1/10 费用——省下的常常是 90% 的输入开销。</p>

      <div id="jr-static"></div>

      <div class="banner banner-accent" style="margin:18px 0">
        <span>✂️</span>
        <div><b>缓存分界线</b>　以上是稳定前缀（缓存命中区），以下是每轮都会变的动态内容。分界线一旦被「下面的东西往上挪」打乱，缓存就会失效、费用飙升——这也是<b>千万别在 prompt 里手写时间</b>的原因。</div>
      </div>

      <div id="jr-dynamic"></div>

      <div class="section-title mt24">🖼️ 特殊消息怎么走</div>
      <div class="grid grid-2" id="jr-special"></div>

      <div class="section-title mt24">🚪 继续逛逛</div>
      <div class="grid grid-3" id="jr-links"></div>
    `;

    this.renderLayers();
    this.renderSpecial();
    this.renderLinks();
    this.loadStats();
  },

  layerCard(l, idx, cached) {
    return `
      <div class="item">
        <div class="item-row">
          <div style="flex:1;min-width:0">
            <div class="item-title">${l.emoji} ${escHtml(l.name)} ${cached ? badge('静态 · 缓存区', 'accent') : badge('动态 · 每轮变化', 'warn')}</div>
            <div class="item-sub" style="line-height:1.6">${escHtml(l.desc)}</div>
          </div>
          <span class="badge badge-muted">第 ${idx} 层</span>
        </div>
      </div>`;
  },

  renderLayers() {
    let i = 0;
    this.root.querySelector('#jr-static').innerHTML = LAYERS.map(l => this.layerCard(l, ++i, true)).join('');
    this.root.querySelector('#jr-dynamic').innerHTML = DYNAMIC.map(l => this.layerCard(l, ++i, false)).join('');
  },

  renderSpecial() {
    this.root.querySelector('#jr-special').innerHTML =
      card({
        title: '🖼️ 图片消息',
        body: `<p class="text-sm muted" style="line-height:1.7">带图的消息会按所选模型的多模态能力转发：支持视觉的模型直接收到图像内容；不支持的则在转发前做降级处理，避免请求报错。图片本身不进记忆库——记忆抽取只针对文字内容，所以拍给 AI 的图，记住的是你围绕它说了什么。</p>`,
      }) +
      card({
        title: '🛠️ 工具调用怎么转发',
        body: `<p class="text-sm muted" style="line-height:1.7">模型决定调用工具时，网关把工具调用请求转发给对应的内部能力或外部 MCP 服务器，拿到结果再回灌给模型续写。工具抽屉会按语义相关性按需展开，避免每次把全部工具定义都塞进 prompt（那同样会撑大输入、拖慢响应）。</p>`,
      });
  },

  renderLinks() {
    const links = [
      { href: '#/persona',  emoji: '📝', title: '人设',     desc: '编辑最顶层的 system prompt。' },
      { href: '#/profile',  emoji: '👤', title: '用户画像', desc: '看看 / 调整 AI 对你的长期认知。' },
      { href: '#/memories', emoji: '🧩', title: '记忆碎片', desc: '浏览会被语义检索注入的那些碎片。' },
    ];
    this.root.querySelector('#jr-links').innerHTML = links.map(l => `
      <a class="card" href="${l.href}" style="text-decoration:none;display:block">
        <div class="card-title">${l.emoji} ${escHtml(l.title)} →</div>
        <div class="card-desc">${escHtml(l.desc)}</div>
      </a>`).join('');
  },

  async loadStats() {
    const box = this.root.querySelector('#jr-stats');
    try {
      const s = await get('/');
      box.innerHTML = `
        <div class="stat"><div class="label">🤖 默认模型</div><div class="value mono" style="font-size:16px">${escHtml(s.default_model || '—')}</div></div>
        <div class="stat"><div class="label">🧩 单次注入上限</div><div class="value accent">${escHtml(String(s.max_inject ?? '—'))}<span style="font-size:13px;font-weight:400"> 条</span></div></div>
        <div class="stat"><div class="label">⏱️ 记忆提取间隔</div><div class="value info">${escHtml(String(s.extract_interval ?? '—'))}<span style="font-size:13px;font-weight:400"> 轮 / 次</span></div></div>
        <div class="stat"><div class="label">🧠 记忆系统</div><div class="value ${s.memory_enabled ? 'accent' : ''}">${s.memory_enabled ? '✅ 开启' : '⛔ 关闭'}</div></div>`;
    } catch (e) {
      box.innerHTML = `<div class="banner banner-warn" style="grid-column:1/-1"><span>⚠️</span><div>无法获取实时数值：${escHtml(e.message)}（讲解内容不受影响）</div></div>`;
    }
  },
};
