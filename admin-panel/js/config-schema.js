// ============================================================
// config-schema.js — 全部配置项的权威登记表（单一事实源）
//
// 与后端 config.py 的 CONFIG_SCHEMA 一一对应。每个 key 都登记：
//   label  中文标签
//   type   值类型 bool|int|float|text
//   def    默认值（字符串）
//   input  控件形态 bool|int|float|text|model|prompt|json|longtext|engine
//   desc   人话说明（解决「忘了这参数干嘛」）
//   hasDefault  prompt 类是否可「恢复默认」（对应 /admin/default-prompts 的 8 个）
//
// CONFIG_PAGES 把 key 编排到各功能页：master（总开关）+ 分组旋钮。
// 任何 META 里有、却没编排进任何页的 key 会被「全部配置」页兜底列出。
// ============================================================

export const CONFIG_META = {
  // —— 记忆基础 ——
  memory_enabled:        { label:'记忆系统总开关', type:'bool', def:'true', input:'bool', desc:'关闭后不提取记忆、不注入碎片，但对话仍正常保存转发。' },
  extract_interval:      { label:'提取间隔（轮）', type:'int', def:'5', input:'int', desc:'每隔多少轮对话提取一次记忆。越小越频繁但更费 token。建议 3–10。' },
  max_inject:            { label:'每次注入条数', type:'int', def:'15', input:'int', desc:'每次对话注入多少条语义相关碎片。太多占 token，太少易遗漏。建议 5–30。' },
  semantic_threshold:    { label:'语义搜索阈值', type:'float', def:'0.25', input:'float', desc:'低于此相似度的碎片不会被注入。建议 0.15–0.5。' },
  dedup_threshold:       { label:'去重相似度阈值', type:'float', def:'0.55', input:'float', desc:'新碎片与已有碎片文字重叠超过此值判为重复、不存储。建议 0.4–0.7。' },
  default_memory_model:  { label:'记忆提取模型', type:'text', def:'', input:'model', desc:'记忆提取用的模型。建议小模型（如 Haiku）省成本。留空跟随聊天模型。' },
  default_embedding_model:{ label:'嵌入模型', type:'text', def:'', input:'model', desc:'向量嵌入模型，决定语义搜索质量。更换后需在「记忆碎片」页执行向量迁移。' },
  prompt_memory_extract: { label:'记忆提取提示词', type:'text', def:'', input:'prompt', hasDefault:true, desc:'指导模型如何从对话中抽取记忆碎片。留空用内置默认。' },

  // —— 热度系统 ——
  heat_half_life_normal:  { label:'普通记忆半衰期（天）', type:'float', def:'3', input:'float', desc:'普通碎片（重要度 < 分界线）的热度半衰期。越大淡忘越慢。' },
  heat_half_life_important:{ label:'重要记忆半衰期（天）', type:'float', def:'7', input:'float', desc:'重要碎片（重要度 ≥ 分界线）的热度半衰期。' },
  heat_recall_extend:     { label:'召回延长倍率', type:'float', def:'0.5', input:'float', desc:'每次被召回时半衰期延长的倍率。0.5 = 延长 50%。' },
  heat_threshold_high:    { label:'高热度阈值（全文注入）', type:'float', def:'0.7', input:'float', desc:'热度高于此值的碎片全文注入对话。' },
  heat_threshold_medium:  { label:'中热度阈值（摘要注入）', type:'float', def:'0.3', input:'float', desc:'热度在此值与高阈值之间的碎片只注入摘要；低于此值跳过。' },
  heat_importance_line:   { label:'重要度分界线', type:'int', def:'8', input:'int', desc:'重要度 ≥ 此值的碎片使用更长的半衰期。' },
  heat_emotion_line:      { label:'高情绪分界线', type:'int', def:'6', input:'int', desc:'情绪浓度 ≥ 此值的碎片视为高情绪，自动锁定条件更宽松、衰减更慢。' },
  heat_medium_truncate:   { label:'中热度摘要截断字数', type:'int', def:'60', input:'int', desc:'中热度碎片摘要注入时截断到多少字。' },
  cleanup_heat_threshold: { label:'清理低热度阈值', type:'float', def:'0.15', input:'float', desc:'热度低于此值且又冷又老的碎片会被清理（软删除）。' },

  // —— 自动软化 ——
  auto_soften_enabled:    { label:'自动软化', type:'bool', def:'true', input:'bool', desc:'是否每晚温柔模糊老旧碎片：细节褪色、要点保留（模拟人脑遗忘）。' },
  auto_soften_daily_limit:{ label:'每日软化上限', type:'int', def:'10', input:'int', desc:'每天最多软化多少条，防止一次性大量重写。' },
  auto_soften_min_age:    { label:'软化最小天数', type:'int', def:'5', input:'int', desc:'碎片至少存在多少天才会被考虑软化。' },
  soften_cooldown_days:   { label:'软化冷却天数', type:'int', def:'21', input:'int', desc:'同一碎片两次软化之间的冷却期。' },

  // —— 自动锁定 / 退役 ——
  autolock_access_count:  { label:'自动锁定·召回次数', type:'int', def:'10', input:'int', desc:'普通碎片被召回多少次后自动锁定保护。' },
  autolock_diversity:     { label:'自动锁定·话题多样性', type:'int', def:'5', input:'int', desc:'普通碎片被多少个不同话题召回后自动锁定。' },
  autolock_emo_access:    { label:'自动锁定·高情绪召回', type:'int', def:'6', input:'int', desc:'高情绪碎片被召回多少次后自动锁定（更宽松）。' },
  autolock_emo_diversity: { label:'自动锁定·高情绪多样性', type:'int', def:'3', input:'int', desc:'高情绪碎片被多少个不同话题召回后自动锁定。' },
  lock_retire_enabled:    { label:'锁定退役', type:'bool', def:'true', input:'bool', desc:'长期未召回的「自动锁定」碎片是否自动退役（解锁但不删除，让出注入空间）。手动锁定永不退役。' },
  lock_retire_days:       { label:'锁定退役天数', type:'int', def:'90', input:'int', desc:'自动锁定碎片超过多少天未召回则退役。' },
  merge_retention_days:   { label:'合并保留天数', type:'int', def:'90', input:'int', desc:'被 Dream 合并后的旧碎片保留多少天后清理。' },
  merge_min_keep:         { label:'合并保留下限', type:'int', def:'20', input:'int', desc:'即便符合清理条件，也至少保留多少条碎片。' },

  // —— 场景注入（Dream 产出）——
  scene_inject_enabled:   { label:'场景注入', type:'bool', def:'true', input:'bool', desc:'是否在聊天时注入 Dream 整合出的叙事场景，提供长期记忆的宏观视角。' },
  scene_inject_limit:     { label:'场景注入条数', type:'int', def:'2', input:'int', desc:'每次最多注入多少条场景。' },
  scene_inject_min_sim:   { label:'场景注入相似度', type:'float', def:'0.5', input:'float', desc:'场景与当前对话的最低相似度。' },

  // —— Dream ——
  dream_model:            { label:'Dream 模型', type:'text', def:'', input:'model', desc:'Dream 记忆整合用的模型。' },
  prompt_dream:           { label:'Dream 提示词', type:'text', def:'', input:'prompt', hasDefault:true, desc:'指导 Dream 如何清理、融合碎片并推断前瞻。留空用内置默认。' },
  dream_drowsy_threshold: { label:'犯困碎片阈值', type:'int', def:'30', input:'int', desc:'未处理碎片积累超过此数量后，AI 开始表现犯困、提示该睡了。' },
  last_dream_date:        { label:'上次 Dream 日期', type:'text', def:'', input:'text', desc:'自动更新，一般无需手动改。' },

  // —— 用户/助手画像 ——
  user_profile:           { label:'用户画像', type:'text', def:'', input:'prompt', hasDefault:false, desc:'AI 对用户的整体认知，注入 system prompt。由每日整理自动更新，也可手动编辑。' },
  prompt_user_profile:    { label:'画像更新提示词', type:'text', def:'', input:'prompt', hasDefault:true, desc:'指导每日整理如何更新用户画像。留空用内置默认。' },

  // —— 日历 / 每日整理 ——
  calendar_inject_enabled:{ label:'日历注入', type:'bool', def:'true', input:'bool', desc:'是否把日/周/月/季/年总结注入 system prompt，让 AI 知道最近发生了什么。' },
  default_digest_model:   { label:'每日整理模型', type:'text', def:'', input:'model', desc:'日页面与各级总结生成用的模型。建议小模型。' },
  prompt_daily_digest:    { label:'每日整理提示词', type:'text', def:'', input:'prompt', hasDefault:true, desc:'每日整理主提示词。留空用内置默认。' },
  prompt_daily_digest_page:{ label:'日页面生成提示词', type:'text', def:'', input:'prompt', hasDefault:true, desc:'生成单日页面的提示词。' },
  prompt_weekly_summary:  { label:'周总结提示词', type:'text', def:'', input:'prompt', hasDefault:true, desc:'生成周总结的提示词。' },
  prompt_monthly_summary: { label:'月总结提示词', type:'text', def:'', input:'prompt', hasDefault:true, desc:'生成月总结的提示词。' },
  prompt_period_summary:  { label:'季度/年总结提示词', type:'text', def:'', input:'prompt', hasDefault:true, desc:'生成季度与年度总结的提示词。' },

  // —— 上下文压缩 ——
  auto_compress_enabled:  { label:'自动压缩', type:'bool', def:'true', input:'bool', desc:'对话过长时自动把前文压成摘要，省 token 又不失忆。' },
  auto_compress_msg_limit:{ label:'压缩触发条数', type:'int', def:'40', input:'int', desc:'对话消息数超过此值触发压缩。' },
  auto_compress_token_limit:{ label:'压缩触发 token', type:'int', def:'30000', input:'int', desc:'估算 token 超过此值触发压缩。' },
  auto_compress_keep_last:{ label:'压缩后保留原文条数', type:'int', def:'4', input:'int', desc:'压缩时末尾保留多少条原文不被压缩。' },
  default_compress_model: { label:'压缩模型', type:'text', def:'', input:'model', desc:'上下文压缩用的模型。建议小模型。' },
  prompt_compress:        { label:'压缩提示词', type:'text', def:'', input:'prompt', hasDefault:false, desc:'指导如何压缩前文。留空用内置默认。' },

  // —— 无缝换窗 handoff ——
  handoff_enabled:        { label:'无缝换窗', type:'bool', def:'true', input:'bool', desc:'新对话自动衔接上一个对话——注入全程概要 + 结尾原文，避免「失忆」。仅新对话首条注入一次。' },
  handoff_tail_count:     { label:'衔接结尾原文条数', type:'int', def:'6', input:'int', desc:'衔接时带上一对话结尾多少条原文（约 3 轮）。' },
  handoff_summary_model:  { label:'衔接概要模型', type:'text', def:'', input:'model', desc:'生成衔接概要的模型。留空跟随压缩模型。' },

  // —— 工具抽屉 / 外部 MCP ——
  tool_drawer_enabled:    { label:'工具抽屉', type:'bool', def:'false', input:'bool', desc:'内部工具是否走向量路由按需展开。关闭则所有内部工具每次都传给模型。' },
  mcp_mode:               { label:'外部 MCP 模式', type:'text', def:'auto', input:'text', desc:'off=全禁用，auto=按语义自动路由，manual=只启用手动选择的。只影响配置来源的外部抽屉。' },
  mcp_servers:            { label:'外部 MCP 服务器', type:'text', def:'', input:'json', desc:'外部 MCP server 列表（JSON 数组）。在「工具抽屉」页用专用编辑器维护。' },
  mcp_manual_ids:         { label:'手动 MCP 选择', type:'text', def:'', input:'json', desc:'manual 模式下启用的 MCP 服务器 ID 列表（JSON 数组）。' },
  ext_drawer_threshold:   { label:'外部抽屉相似度阈值', type:'float', def:'0.40', input:'float', desc:'外部工具与对话内容的语义相似度门槛，低于此值不展开。' },
  ext_drawer_max_open:    { label:'外部抽屉同开上限', type:'int', def:'3', input:'int', desc:'单次对话最多同时展开几个外部工具抽屉。' },

  // —— 联网搜索 ——
  search_engine:          { label:'搜索引擎', type:'text', def:'', input:'engine', desc:'联网搜索使用的引擎。' },
  search_api_key:         { label:'搜索 API Key', type:'text', def:'', input:'pass', desc:'所选搜索引擎的 API Key（local 类型引擎无需）。' },
  search_max_results:     { label:'搜索结果条数', type:'int', def:'5', input:'int', desc:'每次搜索返回多少条结果。' },

  // —— 模型默认（通用）——
  default_chat_model:     { label:'默认聊天模型', type:'text', def:'', input:'model', desc:'未在前端指定时使用的默认聊天模型。' },
  default_title_model:    { label:'标题生成模型', type:'text', def:'', input:'model', desc:'自动生成对话标题用的模型。建议小模型。' },
  prompt_title_summary:   { label:'标题生成提示词', type:'text', def:'', input:'prompt', hasDefault:false, desc:'指导如何生成对话标题。留空用内置默认。' },

  // —— 网关 / 性能 ——
  prompt_cache_enabled:   { label:'Prompt 缓存', type:'bool', def:'true', input:'bool', desc:'Claude 模型的显式缓存：重复的 system prompt 前缀只收 1/10 费用。非 Claude 自动跳过。' },
};

// 各功能页的配置编排：master 总开关 + 分组旋钮
export const CONFIG_PAGES = {
  memories: {
    master: 'memory_enabled',
    groups: [
      { title:'提取与注入', desc:'记忆系统的核心节奏。', keys:['extract_interval','max_inject','semantic_threshold','dedup_threshold'] },
      { title:'模型', desc:'后台任务建议用小模型省成本。', keys:['default_memory_model','default_embedding_model'] },
      { title:'提示词', keys:['prompt_memory_extract'] },
    ],
  },
  metabolism: {
    groups: [
      { title:'🔥 热度系统', desc:'热度决定碎片如何被注入（全文/摘要/跳过）以及何时被淡忘。', keys:['heat_half_life_normal','heat_half_life_important','heat_recall_extend','heat_threshold_high','heat_threshold_medium','heat_importance_line','heat_emotion_line','heat_medium_truncate','cleanup_heat_threshold'] },
      { title:'🌫️ 自动软化', desc:'模拟人脑遗忘：老碎片细节褪色、要点保留。', master:'auto_soften_enabled', keys:['auto_soften_daily_limit','auto_soften_min_age','soften_cooldown_days'] },
      { title:'🔒 自动锁定与退役', desc:'反复跨话题召回的碎片自动锁定保护；长期不用的自动锁定碎片可退役。', master:'lock_retire_enabled', keys:['autolock_access_count','autolock_diversity','autolock_emo_access','autolock_emo_diversity','lock_retire_days','merge_retention_days','merge_min_keep'] },
    ],
  },
  dream: {
    groups: [
      { title:'Dream 整合', keys:['dream_model','dream_drowsy_threshold','last_dream_date','prompt_dream'] },
      { title:'🎬 场景注入', desc:'Dream 产出的叙事场景在聊天时自动注入。', master:'scene_inject_enabled', keys:['scene_inject_limit','scene_inject_min_sim'] },
    ],
  },
  profile: {
    groups: [
      { title:'用户画像', keys:['user_profile','prompt_user_profile'] },
    ],
  },
  calendar: {
    master: 'calendar_inject_enabled',
    groups: [
      { title:'模型', keys:['default_digest_model'] },
      { title:'提示词', desc:'日/周/月/季/年各级总结的提示词。', keys:['prompt_daily_digest','prompt_daily_digest_page','prompt_weekly_summary','prompt_monthly_summary','prompt_period_summary'] },
    ],
  },
  compression: {
    master: 'auto_compress_enabled',
    groups: [
      { title:'触发条件', keys:['auto_compress_msg_limit','auto_compress_token_limit','auto_compress_keep_last'] },
      { title:'模型与提示词', keys:['default_compress_model','prompt_compress'] },
    ],
  },
  handoff: {
    master: 'handoff_enabled',
    groups: [ { title:'参数', keys:['handoff_tail_count','handoff_summary_model'] } ],
  },
  tools: {
    master: 'tool_drawer_enabled',
    groups: [
      { title:'外部 MCP 抽屉', desc:'外部工具按语义相关性自动展开。', keys:['mcp_mode','ext_drawer_threshold','ext_drawer_max_open'] },
      { title:'高级（JSON）', keys:['mcp_manual_ids'] },
    ],
  },
  websearch: {
    groups: [ { title:'搜索配置', keys:['search_engine','search_api_key','search_max_results'] } ],
  },
  providers: {
    groups: [ { title:'默认模型', desc:'未指定时的兜底模型。', keys:['default_chat_model','default_title_model','prompt_title_summary'] } ],
  },
  gateway: {
    groups: [ { title:'性能', keys:['prompt_cache_enabled'] } ],
  },
};

// 这 8 个 prompt 有内置默认、可恢复（对应 /admin/default-prompts）
export const RESTORABLE_PROMPTS = [
  'prompt_memory_extract','prompt_daily_digest','prompt_user_profile','prompt_daily_digest_page',
  'prompt_weekly_summary','prompt_monthly_summary','prompt_period_summary','prompt_dream',
];

// 返回未被任何页编排的 key（兜底用）
export function orphanKeys() {
  const placed = new Set();
  for (const pg of Object.values(CONFIG_PAGES)) {
    if (pg.master) placed.add(pg.master);
    for (const g of pg.groups) { if (g.master) placed.add(g.master); (g.keys || []).forEach(k => placed.add(k)); }
  }
  return Object.keys(CONFIG_META).filter(k => !placed.has(k));
}
