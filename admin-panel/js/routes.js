// ============================================================
// routes.js — 侧栏导航结构（整改后：去掉前端重合页，按使用习惯重排）
// 每个 item.key 对应 js/pages/<key>.js，由 app.js 懒加载。
//
// 本次整改：
//   · 移除 6 个页面：journey(消息旅程)、fileextract(文件提取)、
//     reminders(提醒)、comments(评论)、search(对话搜索)、phrases(指令与短语)
//   · 分组按「自部署者的使用动线」重排：先接入、再人设记忆、
//     然后记忆机制、最后运维与系统。
//   · sync 标签改为「备份与数据」（去掉对话浏览，只做数据运维）。
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
    { key: 'prompts',     icon: '📜', label: '提示词模板' },
    { key: 'rawconfig',   icon: '⚙️', label: '全部配置' },
  ]},
];

// 扁平索引：key → {label, icon, group}
export const ROUTE_INDEX = {};
for (const grp of NAV) for (const it of grp.items) {
  ROUTE_INDEX[it.key] = { ...it, group: grp.title || '' };
}
