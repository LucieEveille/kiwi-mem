// ============================================================
// health.js — 配置健康自检
// 找出「启用了却没配好 / 可能坏了」的地方，给首页状态面板用。
// 返回 [{level:'error'|'warn'|'info', title, detail, route}]
// ============================================================
import { get } from './api.js';
import { loadConfig } from './config.js';

export async function runHealthChecks() {
  const safe = async (p, d) => { try { return await p; } catch { return d; } };
  const [cfg, provs, saved, embed, scfg, engines, scenes, cal, dream] = await Promise.all([
    safe(loadConfig(), {}),
    safe(get('/admin/providers'), { providers: [] }),
    safe(get('/admin/all-saved-models'), { models: [] }),
    safe(get('/admin/embedding-stats'), {}),
    safe(get('/admin/search-config'), {}),
    safe(get('/admin/search-engines'), { engines: [] }),
    safe(get('/dream/scenes'), { scenes: [] }),
    safe(get('/calendar'), { pages: [] }),
    safe(get('/dream/status'), {}),
  ]);
  const on = (k) => String(cfg[k]) === 'true';
  const providers = provs.providers || [];
  const models = saved.models || [];
  const issues = [];

  if (providers.length === 0) {
    issues.push({ level: 'error', title: '没有配置任何供应商', detail: '聊天请求无法转发。去添加你的中转站或官方 API。', route: 'providers' });
  } else if (models.length === 0) {
    issues.push({ level: 'warn', title: '没有保存任何模型', detail: '前端模型列表（/v1/models）会回退到环境变量默认（通常是 OpenRouter），聊天可能路由不到你的供应商。去供应商页点「模型」保存。', route: 'providers' });
  }

  if (on('memory_enabled') && embed && !embed.error && embed.total_memories > 0 && embed.without_embedding > 0) {
    issues.push({ level: 'warn', title: `有 ${embed.without_embedding} 条记忆缺少向量`, detail: `向量覆盖 ${embed.coverage || ''}，语义搜索不完整。去记忆碎片页执行「向量迁移」。`, route: 'memories' });
  }

  if (scfg && scfg.engine) {
    const eng = (engines.engines || []).find(e => e.id === scfg.engine);
    if (eng && eng.needs_key && !scfg.api_key) {
      issues.push({ level: 'warn', title: '联网搜索缺 API Key', detail: `已选「${eng.name}」但没填 Key，搜索会失败。`, route: 'websearch' });
    }
  }

  if (cfg.mcp_mode === 'manual') {
    let ids = []; try { ids = JSON.parse(cfg.mcp_manual_ids || '[]'); } catch {}
    if (!Array.isArray(ids) || ids.length === 0) {
      issues.push({ level: 'warn', title: 'MCP 手动模式未选服务器', detail: 'mcp_mode=manual 但没选任何 MCP server，外部工具不会展开。', route: 'tools' });
    }
  }

  if (on('scene_inject_enabled') && (scenes.scenes || []).length === 0) {
    issues.push({ level: 'info', title: '场景注入已开，但还没有场景', detail: '先跑一次 Dream 生成叙事场景，注入才有内容。', route: 'dream' });
  }

  if (on('calendar_inject_enabled') && (cal.pages || []).length === 0) {
    issues.push({ level: 'info', title: '日历注入已开，但还没有日历内容', detail: '先做一次「每日整理」生成日页面。', route: 'calendar' });
  }

  const unproc = dream.unprocessed_count ?? dream.unprocessed_fragments;
  if (dream && (dream.is_drowsy || (unproc != null && dream.drowsy_threshold != null && unproc >= dream.drowsy_threshold))) {
    issues.push({ level: 'info', title: `碎片积压（${unproc} 条），该 Dream 了`, detail: '未处理碎片已达犯困阈值，建议触发一次 Dream 整合。', route: 'dream' });
  }

  return issues;
}
