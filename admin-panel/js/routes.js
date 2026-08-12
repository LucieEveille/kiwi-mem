// ============================================================
// routes.js — 侧栏导航结构（v1.6.2）
// 每个 item.key 对应 js/pages/<key>.js，由 app.js 懒加载。
//
// 本次改版：
//   · 移除「提示词模板」页（prompts）：11 条提示词只在各自功能页编辑，
//     不再有第二个入口。app.js 的 REMOVED 会给旧链接明确提示。
//   · 新增 LEDES：每页顶部讲解条的文案（外壳统一渲染，页面文件无需改动）。
// ============================================================
export const NAV = [
  { title: '概览', items: [
    { key: 'dashboard',   icon: '📊', label: '仪表盘' },
  ]},
  { title: '接入配置', items: [
    { key: 'providers',   icon: '🔌', label: '供应商与模型' },
    { key: 'websearch',   icon: '🌐', label: '联网搜索' },
    { key: 'tools',       icon: '🛠️', label: '工具抽屉' },
  ]},
  { title: '人设与记忆', items: [
    { key: 'persona',     icon: '📝', label: '人设' },
    { key: 'profile',     icon: '👤', label: '用户画像' },
    { key: 'memories',    icon: '🧩', label: '记忆碎片' },
    { key: 'categories',  icon: '🏷️', label: '碎片分类' },
  ]},
  { title: '记忆机制', items: [
    { key: 'metabolism',  icon: '🌡️', label: '记忆机制' },
    { key: 'dream',       icon: '🌙', label: 'Dream' },
    { key: 'calendar',    icon: '📅', label: '日历与整理' },
    { key: 'compression', icon: '🗜️', label: '上下文压缩' },
    { key: 'handoff',     icon: '🪟', label: '无缝换窗' },
    { key: 'projects',    icon: '📁', label: '项目分隔' },
  ]},
  { title: '运维与安全', items: [
    { key: 'gateway',     icon: '🚦', label: '网关与延迟' },
    { key: 'sync',        icon: '💾', label: '备份与数据' },
    { key: 'security',    icon: '🔐', label: '认证与安全' },
  ]},
  { title: '系统', items: [
    { key: 'rawconfig',   icon: '⚙️', label: '全部配置' },
  ]},
];

// 每页讲解条（外壳在 route() 里渲染；页面自身的 .page-intro 已由 CSS 隐藏）
// key → [一句话讲清这页管什么, 补充说明]
export const LEDES = {
  providers:  ['接上你买的 AI 服务', 'kiwi-mem 把消息转发给这里配置的供应商。保存过的模型才会出现在前端列表。'],
  websearch:  ['让 AI 能查到今天的事', '选一个搜索引擎、填好 Key，模型就能在对话里联网检索。'],
  tools:      ['工具按需拿，不浪费 token', '每句话只把可能用到的工具递给模型；外部 MCP 按语义自动展开。'],
  persona:    ['AI 是谁、怎么说话', '最顶层的 system prompt，整条消息旅程里最静态的一层。'],
  profile:    ['AI 眼中的你', '由每日整理自动更新的结构化认知，注入缓存静态层。'],
  memories:   ['记忆的原子单位', '每条碎片带重要度、热度、分类与锁定；会淡忘，也会因反复提起而升温。'],
  categories: ['给碎片打标签', '纯组织手段，便于筛选，不影响检索逻辑。'],
  metabolism: ['记忆如何淡忘与变牢', '热度衰减、夜间软化、自动锁定与退役——这页是遗忘曲线的旋钮。'],
  dream:      ['睡一觉，把碎片整理成理解', '清理 → 融合成场景 → 前瞻推断；碎片积压时 AI 会犯困。'],
  calendar:   ['近的清晰，远的模糊', '日→周→月→季→年逐级压缩，AI 始终知道「最近发生了什么」。'],
  compression:['对话太长时自动瘦身', '把靠前的消息压成摘要塞回上下文，省 token 不失忆。'],
  handoff:    ['换个窗口不失忆', '新对话自动衔接上一个对话的概要与结尾原文，仅首条注入一次。'],
  projects:   ['不同生活，互不串门', '每个项目的记忆、Dream、日历完全隔离，自动生效。'],
  gateway:    ['所有消息的必经之路', '看网关状态、测接口延迟，调转发行为与 Prompt 缓存。'],
  sync:       ['数据是你的', '整库备份导出/导入；重置操作有确认码保护。'],
  security:   ['公开版的安全边界', '无内建鉴权——用反向代理或私有网络保护你的部署。'],
  rawconfig:  ['一个旋钮都不漏', '全部配置项的兜底视图，含未编排的冷门项。找参数用顶栏搜索更快。'],
};

// 扁平索引：key → {label, icon, group}
export const ROUTE_INDEX = {};
for (const grp of NAV) for (const it of grp.items) {
  ROUTE_INDEX[it.key] = { ...it, group: grp.title || '' };
}
