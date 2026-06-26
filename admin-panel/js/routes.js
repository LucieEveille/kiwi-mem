// ============================================================
// routes.js — 侧栏导航结构（照搬四大模块分章）
// 每个 item.key 对应 js/pages/<key>.js，由 app.js 懒加载。
// ============================================================
export const NAV = [
  { items: [
    { key: 'dashboard', icon: '📊', label: '仪表盘' },
  ]},
  { title: '记忆与注入', items: [
    { key: 'journey',     icon: '🗺️', label: '消息旅程' },
    { key: 'persona',     icon: '📝', label: '人设' },
    { key: 'memories',    icon: '🧩', label: '记忆碎片' },
    { key: 'categories',  icon: '🏷️', label: '碎片分类' },
    { key: 'metabolism',  icon: '🌡️', label: '记忆机制' },
    { key: 'profile',     icon: '👤', label: '用户画像' },
    { key: 'dream',       icon: '🌙', label: 'Dream' },
    { key: 'calendar',    icon: '📅', label: '日历与整理' },
    { key: 'compression', icon: '🗜️', label: '上下文压缩' },
    { key: 'handoff',     icon: '🪟', label: '无缝换窗' },
    { key: 'projects',    icon: '📁', label: '项目分隔' },
  ]},
  { title: '后端接口', items: [
    { key: 'providers',   icon: '🔌', label: '供应商与模型' },
    { key: 'tools',       icon: '🛠️', label: '工具抽屉' },
    { key: 'websearch',   icon: '🌐', label: '联网搜索' },
    { key: 'phrases',     icon: '⚡', label: '指令与短语' },
    { key: 'fileextract', icon: '📎', label: '文件提取' },
  ]},
  { title: '日常活动', items: [
    { key: 'reminders',   icon: '⏰', label: '提醒' },
    { key: 'comments',    icon: '💬', label: '评论' },
  ]},
  { title: '数据', items: [
    { key: 'sync',        icon: '☁️', label: '云同步与零件箱' },
    { key: 'gateway',     icon: '🚦', label: '网关与延迟' },
    { key: 'search',      icon: '🔍', label: '对话搜索' },
    { key: 'security',    icon: '🔐', label: '认证与安全' },
  ]},
  { title: '系统', items: [
    { key: 'prompts',     icon: '📜', label: '提示词模板' },
    { key: 'rawconfig',   icon: '⚙️', label: '全部配置' },
  ]},
];

// 扁平索引：key → {label, icon, group}
export const ROUTE_INDEX = {};
for (const grp of NAV) for (const it of grp.items) {
  ROUTE_INDEX[it.key] = { ...it, group: grp.title || '' };
}
