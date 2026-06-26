"""
config.py — 动态配置管理（v3.1）

配置优先级：数据库 > 环境变量 > 默认值
修改后即时生效，不需要重启服务

配置表 gateway_config 的建表由 database.py 的 init_tables() 负责
"""

import os
from typing import Optional
from database import get_pool


# ============================================================
# 配置项定义
# ============================================================
# key → (环境变量名, 默认值, 中文标签, 值类型)

CONFIG_SCHEMA = {
    "memory_enabled":        ("MEMORY_ENABLED",         "true",  "记忆系统开关",      "bool"),
    "extract_interval":      ("MEMORY_EXTRACT_INTERVAL", "5",    "提取间隔（轮）",    "int"),
    "max_inject":            ("MAX_MEMORIES_INJECT",     "15",   "每次注入条数",      "int"),
    "semantic_threshold":    ("SEMANTIC_THRESHOLD",      "0.25", "语义搜索阈值",      "float"),
    "dedup_threshold":       ("DEDUP_THRESHOLD",         "0.55", "去重相似度阈值",    "float"),
    "scene_inject_enabled":  ("SCENE_INJECT_ENABLED",  "true", "场景注入开关",      "bool"),
    "scene_inject_limit":    ("SCENE_INJECT_LIMIT",    "2",    "场景注入条数",      "int"),
    "scene_inject_min_sim":  ("SCENE_INJECT_MIN_SIM",  "0.5",  "场景注入相似度阈值", "float"),
    # 默认模型配置（v3.7）
    "default_chat_model":    ("DEFAULT_MODEL",           "",     "默认聊天模型",      "text"),
    "default_title_model":   ("",                        "",     "标题总结模型",      "text"),
    "default_memory_model":  ("MEMORY_MODEL",            "",     "记忆提取模型",      "text"),
    "default_digest_model":  ("",                        "",     "每日整理模型",      "text"),
    "default_embedding_model":("EMBEDDING_MODEL",        "",     "嵌入模型",          "text"),
    # 提示词模板（v3.7）
    "prompt_title_summary":  ("",                        "",     "标题总结提示词",    "text"),
    "prompt_memory_extract": ("",                        "",     "记忆提取提示词",    "text"),
    "prompt_daily_digest":   ("",                        "",     "每日整理提示词",    "text"),
    # 上下文压缩（v3.9）
    "default_compress_model":("",                        "",     "上下文压缩模型",    "text"),
    "prompt_compress":       ("",                        "",     "上下文压缩提示词",  "text"),
    # 自动上下文压缩（v6.1）
    "auto_compress_enabled":    ("", "true",  "自动压缩开关",        "bool"),
    "auto_compress_msg_limit":  ("", "40",    "压缩触发条数",        "int"),
    "auto_compress_token_limit":("", "30000", "压缩触发 token 上限",  "int"),
    "auto_compress_keep_last":  ("", "4",     "压缩后保留原文条数",   "int"),
    # 用户画像（v4.0）
    "user_profile":          ("",                        "",     "用户画像",          "text"),
    "prompt_user_profile":   ("",                        "",     "画像更新提示词",    "text"),
    # Dream 记忆整合（v5.1）
    "dream_model":           ("",                        "",     "Dream 模型",        "text"),
    "prompt_dream":          ("",                        "",     "Dream 提示词",      "text"),
    "prompt_daily_digest_page":("",                      "",     "日页面生成提示词",  "text"),
    "prompt_weekly_summary": ("",                        "",     "周总结提示词",      "text"),
    "prompt_monthly_summary":("",                        "",     "月总结提示词",      "text"),
    "prompt_period_summary": ("",                        "",     "季度/年总结提示词", "text"),
    "dream_drowsy_threshold":("",                        "30",   "犯困碎片阈值",      "int"),
    "last_dream_date":       ("",                        "",     "上次 Dream 日期",   "text"),
    # v5.9：记忆新陈代谢
    "auto_soften_enabled":   ("AUTO_SOFTEN_ENABLED",   "true", "自动软化开关",      "bool"),
    "auto_soften_daily_limit":("AUTO_SOFTEN_DAILY_LIMIT","10",   "每日软化上限",      "int"),
    "auto_soften_min_age":   ("AUTO_SOFTEN_MIN_AGE",   "5",    "自动软化最小天数",  "int"),
    "soften_cooldown_days":  ("SOFTEN_COOLDOWN_DAYS",  "21",   "软化冷却天数",      "int"),
    "lock_retire_enabled":   ("LOCK_RETIRE_ENABLED",   "true", "自动锁定退役开关",  "bool"),
    "lock_retire_days":      ("LOCK_RETIRE_DAYS",      "90",   "锁定退役天数",      "int"),
    # v5.5：日历层级注入
    "calendar_inject_enabled":("",                       "true", "日历注入开关",      "bool"),
    # v5.5：Prompt 缓存（Claude 模型省 90% 输入费用）
    "prompt_cache_enabled":   ("",                       "true", "Prompt 缓存",      "bool"),
    # v6.1：无缝换窗 v2（新对话衔接上一个对话的全程概要 + 结尾原文）
    "handoff_enabled":        ("",                       "true", "无缝换窗开关",      "bool"),
    "handoff_tail_count":     ("",                       "6",    "衔接结尾原文条数",  "int"),
    "handoff_summary_model":  ("",                       "",     "衔接概要模型",      "text"),
    # v5.4：热度系统参数（从代码硬编码提取为可配置）
    "heat_half_life_normal": ("",                        "3",    "普通记忆半衰期（天）",  "float"),
    "heat_half_life_important":("",                      "7",    "重要记忆半衰期（天）",  "float"),
    "heat_recall_extend":    ("",                        "0.5",  "召回延长半衰期倍率",    "float"),
    "heat_threshold_high":   ("",                        "0.7",  "高热度阈值（全文注入）", "float"),
    "heat_threshold_medium": ("",                        "0.3",  "中热度阈值（摘要注入）", "float"),
    "heat_importance_line":  ("",                        "8",    "重要度分界线",          "int"),
    "heat_emotion_line":     ("",                        "6",    "高情绪分界线",          "int"),
    "heat_medium_truncate":  ("",                        "60",   "中热度摘要截断字数",    "int"),
    "cleanup_heat_threshold":("CLEANUP_HEAT_THRESHOLD", "0.15", "清理低热度阈值",    "float"),
    "merge_retention_days":  ("MERGE_RETENTION_DAYS",  "90",   "合并记忆保留天数",  "int"),
    "merge_min_keep":        ("MERGE_MIN_KEEP",        "20",   "合并记忆保留下限",  "int"),
    # v5.4：记忆自动锁定
    "autolock_access_count": ("",                        "10",   "自动锁定：召回次数阈值",   "int"),
    "autolock_diversity":    ("",                        "5",    "自动锁定：话题多样性阈值", "int"),
    "autolock_emo_access":   ("",                        "6",    "自动锁定：高情绪召回阈值", "int"),
    "autolock_emo_diversity": ("",                       "3",    "自动锁定：高情绪多样性阈值","int"),
    # 联网搜索配置（v3.8）
    "search_engine":         ("SEARCH_ENGINE",           "",     "搜索引擎",          "text"),
    "search_api_key":        ("SEARCH_API_KEY",          "",     "搜索 API Key",      "text"),
    "search_max_results":    ("SEARCH_MAX_RESULTS",      "5",    "搜索结果条数",      "int"),
    # 云端同步 — 用户/助手配置（v4.1）
    "user_avatar":           ("",                        "",     "用户头像",          "text"),
    "user_nickname":         ("",                        "",     "用户昵称",          "text"),
    "assistant_avatar":      ("",                        "",     "助手头像",          "text"),
    "assistant_settings":    ("",                        "",     "助手参数",          "text"),
    "custom_skills":         ("",                        "",     "自定义技能",        "text"),
    "quick_phrases":         ("",                        "",     "快捷短语",          "text"),
    "mcp_switches":          ("",                        "",     "MCP开关状态",       "text"),
    "mcp_servers":           ("",                        "",     "MCP服务器列表",     "text"),
    "mcp_manual_ids":        ("",                        "",     "手动MCP选择",       "text"),
    "mcp_mode":              ("",                        "auto", "MCP模式",           "text"),
    "ext_drawer_threshold":  ("EXT_DRAWER_THRESHOLD",   "0.40", "外部抽屉相似度阈值", "float"),
    "ext_drawer_max_open":   ("EXT_DRAWER_MAX_OPEN",    "3",    "外部抽屉同开上限",   "int"),
    "theme_preference":      ("",                        "",     "主题偏好",          "text"),
    # v6.3：工具抽屉（向量路由按需展开工具）。默认关闭——开启后内部工具走向量路由，
    #       外部 mcp_servers 仍走原路径并合并，对模型表现为一组完整工具
    "tool_drawer_enabled":   ("",                        "false","工具抽屉开关",      "bool"),
}


# ============================================================
# 读取配置
# ============================================================

def _env_or_default(env_name: str, default_val: str) -> tuple:
    """解析"环境变量 > 默认值"。

    环境变量未设置、或被设成空串 / 纯空白时一律视为"未设置"，回落到默认值，
    避免空环境变量（如 docker-compose 里 KEY=${KEY} 而 KEY 未定义）把默认值冲掉。
    返回 (值, 来源)，来源为 'env' 或 'default'。
    """
    if env_name:
        env_val = os.getenv(env_name)
        if env_val is not None and env_val.strip() != "":
            return env_val, "env"
    return default_val, "default"


async def get_config(key: str) -> Optional[str]:
    """
    获取单个配置值
    优先级：数据库 > 环境变量 > 默认值
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM gateway_config WHERE key = $1", key
        )
        if row:
            return row["value"]
    
    # 降级到环境变量和默认值
    if key in CONFIG_SCHEMA:
        env_name, default_val, _, _ = CONFIG_SCHEMA[key]
        value, _ = _env_or_default(env_name, default_val)
        return value
    
    return None


async def get_all_config() -> dict:
    """获取所有配置（合并数据库、环境变量、默认值）"""
    result = {}
    
    # 先填默认值和环境变量
    for key, (env_name, default_val, label, val_type) in CONFIG_SCHEMA.items():
        env_val, source = _env_or_default(env_name, default_val)
        result[key] = {
            "value": env_val,
            "label": label,
            "type": val_type,
            "source": source,
        }
    
    # 覆盖数据库里的值
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM gateway_config")
        for row in rows:
            if row["key"] in result:
                result[row["key"]]["value"] = row["value"]
                result[row["key"]]["source"] = "database"
    
    return result


# ============================================================
# 写入配置
# ============================================================

_ENUM_VALUES = {"mcp_mode": {"off", "auto", "manual"}}


def _mask_secret(value: str) -> str:
    v = value or ""
    return (v[:4] + "…" + v[-3:]) if len(v) > 10 else ("•" * min(len(v), 8))


def _safe_log_value(key: str, value: str) -> str:
    """日志脱敏：密钥类只显脱敏值；提示词/长文本只显长度，避免进 Zeabur 日志。"""
    low = key.lower()
    if "key" in low or "token" in low or "secret" in low or "password" in low:
        return _mask_secret(value)
    if key.startswith("prompt_") or key in (
        "user_profile", "assistant_settings", "custom_skills", "quick_phrases",
        "mcp_servers", "mcp_switches", "mcp_manual_ids", "user_avatar", "assistant_avatar",
    ) or len(value or "") > 80:
        return f"<{len(value or '')} 字符>"
    return value


async def set_config(key: str, value: str) -> bool:
    """设置配置值（存入数据库，带类型验证）"""
    if key not in CONFIG_SCHEMA:
        return False

    # 类型验证
    _, _, _, val_type = CONFIG_SCHEMA[key]
    try:
        if val_type == "int":
            int(value)
        elif val_type == "float":
            float(value)
        elif val_type == "bool":
            if value.lower() not in ("true", "false"):
                return False
        # text 类型不需要验证
    except ValueError:
        return False

    # 枚举值校验：非法值直接拒绝，不再悄悄按默认跑
    if key in _ENUM_VALUES and value not in _ENUM_VALUES[key]:
        return False
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO gateway_config (key, value, label, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()
        """, key, value, CONFIG_SCHEMA[key][2])
    
    print(f"⚙️  配置更新: {key} = {_safe_log_value(key, value)}")
    return True


# ============================================================
# 类型便捷读取
# ============================================================

async def get_config_int(key: str, fallback: int = 0) -> int:
    """获取整数配置"""
    val = await get_config(key)
    try:
        return int(val) if val else fallback
    except (ValueError, TypeError):
        return fallback


async def get_config_float(key: str, fallback: float = 0.0) -> float:
    """获取浮点数配置"""
    val = await get_config(key)
    try:
        return float(val) if val else fallback
    except (ValueError, TypeError):
        return fallback


async def get_config_bool(key: str, fallback: bool = False) -> bool:
    """获取布尔配置（接受 true/1/yes/on 与 false/0/no/off 等常见写法）"""
    val = await get_config(key)
    if val is None:
        return fallback
    v = val.strip().lower()
    if v in ("true", "1", "yes", "on"):
        return True
    if v in ("false", "0", "no", "off"):
        return False
    return fallback
