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
    # v5.5：日历层级注入
    "calendar_inject_enabled":("",                       "true", "日历注入开关",      "bool"),
    # v5.5：Prompt 缓存（Claude 模型省 90% 输入费用）
    "prompt_cache_enabled":   ("",                       "true", "Prompt 缓存",      "bool"),
    # v5.6：无缝切窗（新对话衔接上一个对话的上下文）
    "handoff_enabled":        ("",                       "true", "对话衔接开关",      "bool"),
    "handoff_msg_count":      ("",                       "6",    "衔接注入条数",      "int"),
    "handoff_stop_rounds":    ("",                       "3",    "衔接停止轮数",      "int"),
    "handoff_summary_model":  ("",                       "",     "衔接摘要模型",      "text"),
    "prompt_handoff_summary": ("",                       "",     "衔接摘要提示词",    "text"),
    # v5.4：热度系统参数（从代码硬编码提取为可配置）
    "heat_half_life_normal": ("",                        "3",    "普通记忆半衰期（天）",  "float"),
    "heat_half_life_important":("",                      "7",    "重要记忆半衰期（天）",  "float"),
    "heat_recall_extend":    ("",                        "0.5",  "召回延长半衰期倍率",    "float"),
    "heat_threshold_high":   ("",                        "0.7",  "高热度阈值（全文注入）", "float"),
    "heat_threshold_medium": ("",                        "0.3",  "中热度阈值（摘要注入）", "float"),
    "heat_importance_line":  ("",                        "8",    "重要度分界线",          "int"),
    "heat_emotion_line":     ("",                        "6",    "高情绪分界线",          "int"),
    "heat_medium_truncate":  ("",                        "60",   "中热度摘要截断字数",    "int"),
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
    "theme_preference":      ("",                        "",     "主题偏好",          "text"),
    # v6.3：工具抽屉（向量路由按需展开工具）。默认关闭——开启后内部工具走向量路由，
    #       外部 mcp_servers 仍走原路径并合并，对模型表现为一组完整工具
    "tool_drawer_enabled":   ("",                        "false","工具抽屉开关",      "bool"),
}


# ============================================================
# 读取配置
# ============================================================

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
        if env_name:
            return os.getenv(env_name, default_val)
        return default_val
    
    return None


async def get_all_config() -> dict:
    """获取所有配置（合并数据库、环境变量、默认值）"""
    result = {}
    
    # 先填默认值和环境变量
    for key, (env_name, default_val, label, val_type) in CONFIG_SCHEMA.items():
        env_val = os.getenv(env_name, default_val) if env_name else default_val
        result[key] = {
            "value": env_val,
            "label": label,
            "type": val_type,
            "source": "env" if (env_name and os.getenv(env_name)) else "default",
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
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO gateway_config (key, value, label, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()
        """, key, value, CONFIG_SCHEMA[key][2])
    
    print(f"⚙️  配置更新: {key} = {value}")
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
    """获取布尔配置"""
    val = await get_config(key)
    if val is None:
        return fallback
    return val.lower() == "true"
