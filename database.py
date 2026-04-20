"""
数据库模块 —— 负责所有跟 PostgreSQL 打交道的事情
==============================================
包括：
- 创建表结构
- 存储对话记录
- 存储/检索记忆（RRF 混合检索：向量 + 关键词并行 → 融合排序）
- 删除/清空/更新记忆
- 记忆去重检测
- Embedding 向量生成与存储

v5.7 升级：RRF 混合检索
- 向量搜索和关键词搜索并行执行（asyncio.gather）
- Reciprocal Rank Fusion 合并两路结果
- 关键词搜索增加标题匹配（标题命中权重 1.5x）
- 召回追踪统一在合并后执行（不重复追踪）
"""

import os
import re
import json
import math
import hashlib
from datetime import datetime, timezone
from typing import Optional, List

import asyncio
import asyncpg
import httpx
import jieba
import jieba.analyse

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ============================================================
# Embedding 配置
# ============================================================

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")

# 搜索权重（向量版）
WEIGHT_SEMANTIC = float(os.getenv("WEIGHT_SEMANTIC", "0.5"))
WEIGHT_IMPORTANCE = float(os.getenv("WEIGHT_IMPORTANCE", "0.15"))
WEIGHT_RECENCY = float(os.getenv("WEIGHT_RECENCY", "0.1"))
WEIGHT_HEAT = float(os.getenv("WEIGHT_HEAT", "0.25"))

# 语义搜索最低相似度阈值（低于此值不返回）
SEMANTIC_THRESHOLD = float(os.getenv("SEMANTIC_THRESHOLD", "0.25"))

# RRF（Reciprocal Rank Fusion）参数
# k 值越大，排名靠后的结果权重衰减越慢（推荐 60，业界标准）
RRF_K = int(os.getenv("RRF_K", "60"))

# 记忆去重阈值（字符重叠度，0-1）
DEDUP_THRESHOLD = float(os.getenv("DEDUP_THRESHOLD", "0.55"))

# API 配置（和 main.py 共用环境变量）
API_KEY = os.getenv("API_KEY", "")
API_BASE_URL = os.getenv("API_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")


def _get_embedding_url() -> str:
    """从 API_BASE_URL 推导 embedding endpoint"""
    base = API_BASE_URL.split("/chat/completions")[0].rstrip("/")
    return f"{base}/embeddings"


# ============================================================
# 连接池管理
# ============================================================

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL 未设置！")
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        print("✅ 数据库连接池已创建")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        print("✅ 数据库连接池已关闭")


# ============================================================
# 表结构初始化
# ============================================================

async def init_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id              SERIAL PRIMARY KEY,
                session_id      TEXT NOT NULL,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                model           TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id              SERIAL PRIMARY KEY,
                content         TEXT NOT NULL,
                importance      INTEGER DEFAULT 5,
                source_session  TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                last_accessed   TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        
        # v3.0：添加 embedding 列（如果不存在）
        has_embedding = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'memories' AND column_name = 'embedding'
            )
        """)
        if not has_embedding:
            await conn.execute("ALTER TABLE memories ADD COLUMN embedding TEXT")
            print("✅ 已添加 embedding 列")
        
        # v3.2：添加 title 列（如果不存在）
        has_title = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'memories' AND column_name = 'title'
            )
        """)
        if not has_title:
            await conn.execute("ALTER TABLE memories ADD COLUMN title TEXT DEFAULT ''")
            print("✅ 已添加 title 列")
        
        # v3.3：添加 memory_type 列（fragment / daily_digest / digested）
        has_memory_type = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'memories' AND column_name = 'memory_type'
            )
        """)
        if not has_memory_type:
            await conn.execute("ALTER TABLE memories ADD COLUMN memory_type TEXT DEFAULT 'fragment'")
            print("✅ 已添加 memory_type 列")
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_session 
            ON conversations (session_id, created_at);
        """)
        
        # v3.1：动态配置表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS gateway_config (
                key             TEXT PRIMARY KEY,
                value           TEXT NOT NULL,
                label           TEXT,
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        # v3.4：供应商管理表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS providers (
                id              SERIAL PRIMARY KEY,
                name            TEXT NOT NULL,
                api_base_url    TEXT NOT NULL,
                api_key         TEXT DEFAULT '',
                enabled         BOOLEAN DEFAULT TRUE,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # v3.5：供应商模型配置表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS provider_models (
                id              SERIAL PRIMARY KEY,
                provider_id     INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
                model_id        TEXT NOT NULL,
                display_name    TEXT DEFAULT '',
                model_type      TEXT DEFAULT 'chat',
                input_modes     TEXT DEFAULT 'text',
                output_modes    TEXT DEFAULT 'text',
                capabilities    TEXT DEFAULT '',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(provider_id, model_id)
            );
        """)

        # v3.7：记忆分类表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_categories (
                id              SERIAL PRIMARY KEY,
                name            TEXT NOT NULL UNIQUE,
                color           TEXT DEFAULT '#6B7280',
                icon            TEXT DEFAULT '📁',
                sort_order      INTEGER DEFAULT 0,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # v3.7：记忆表添加 category_id 列（nullable）
        has_category_id = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'memories' AND column_name = 'category_id'
            )
        """)
        if not has_category_id:
            await conn.execute("ALTER TABLE memories ADD COLUMN category_id INTEGER REFERENCES memory_categories(id) ON DELETE SET NULL")
            print("✅ 已添加 category_id 列")

        # v3.9：记忆来源追踪列
        has_source = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'memories' AND column_name = 'source'
            )
        """)
        if not has_source:
            await conn.execute("ALTER TABLE memories ADD COLUMN source TEXT DEFAULT 'ai_extracted'")
            # 回填已有记忆的来源
            await conn.execute("UPDATE memories SET source = 'ai_digest' WHERE memory_type = 'daily_digest'")
            await conn.execute("UPDATE memories SET source = 'user_explicit' WHERE source_session = 'manual'")
            await conn.execute("UPDATE memories SET source = 'seed_import' WHERE source_session = 'seed-import'")
            print("✅ 已添加 source 列（并回填已有记忆）")

        # v4.1：云端同步 — 对话表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_conversations (
                id              TEXT PRIMARY KEY,
                title           TEXT DEFAULT '新对话',
                model           TEXT DEFAULT '',
                project_id      TEXT,
                pinned          BOOLEAN DEFAULT FALSE,
                sort_order      INTEGER DEFAULT 0,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # v4.1：云端同步 — 消息表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
                role            TEXT NOT NULL,
                content         TEXT DEFAULT '',
                time            TIMESTAMPTZ DEFAULT NOW(),
                model           TEXT DEFAULT '',
                streaming       BOOLEAN DEFAULT FALSE,
                error           BOOLEAN DEFAULT FALSE,
                token_info      JSONB,
                thinking        TEXT,
                tool_events     JSONB,
                memory_result   JSONB,
                web_search_results JSONB,
                versions        JSONB,
                version_index   INTEGER DEFAULT 0,
                attachments     JSONB,
                usage           JSONB,
                summary         TEXT,
                sort_order      INTEGER DEFAULT 0
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_messages_conv
            ON chat_messages (conversation_id, sort_order);
        """)

        # v4.1：云端同步 — 项目表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_projects (
                id              TEXT PRIMARY KEY,
                name            TEXT DEFAULT '新项目',
                icon            TEXT DEFAULT '📁',
                description     TEXT DEFAULT '',
                instructions    TEXT DEFAULT '',
                files           JSONB DEFAULT '[]',
                memory          TEXT DEFAULT '',
                expanded        BOOLEAN DEFAULT FALSE,
                sort_order      INTEGER DEFAULT 0,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # v4.2：提醒系统
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id              TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                notes           TEXT DEFAULT '',
                trigger_time    TIMESTAMPTZ NOT NULL,
                repeat_type     TEXT DEFAULT 'once',
                repeat_config   JSONB DEFAULT '{}',
                status          TEXT DEFAULT 'pending',
                enabled         BOOLEAN DEFAULT TRUE,
                last_fired_at   TIMESTAMPTZ,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # v5.0：日历记忆页面（记忆桥核心表）
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS calendar_pages (
                id              SERIAL PRIMARY KEY,
                date            DATE NOT NULL,
                type            TEXT NOT NULL DEFAULT 'day',
                sections        JSONB DEFAULT '[]',
                diary           TEXT DEFAULT '',
                keywords        JSONB DEFAULT '[]',
                model_used      TEXT DEFAULT '',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(date, type)
            );
        """)

        # v5.0：通用评论表（记忆桥所有内容通用）
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id              SERIAL PRIMARY KEY,
                target_type     TEXT NOT NULL,
                target_id       INTEGER NOT NULL,
                parent_id       INTEGER REFERENCES comments(id) ON DELETE CASCADE,
                author          TEXT NOT NULL DEFAULT 'user',
                content         TEXT NOT NULL,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_comments_target
            ON comments (target_type, target_id);
        """)

        # v5.1：Dream 记忆场景表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mem_scenes (
                id              SERIAL PRIMARY KEY,
                title           VARCHAR(200) NOT NULL,
                narrative       TEXT NOT NULL,
                atomic_facts    JSONB DEFAULT '[]',
                foresight       JSONB DEFAULT '[]',
                related_memory_ids JSONB DEFAULT '[]',
                status          TEXT DEFAULT 'active',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW(),
                created_by_dream_id INTEGER
            );
        """)

        # v5.1：Dream 执行记录表
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dream_logs (
                id              SERIAL PRIMARY KEY,
                started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at     TIMESTAMPTZ,
                status          TEXT DEFAULT 'running',
                trigger_type    TEXT DEFAULT 'manual',
                model_used      TEXT DEFAULT '',
                memories_processed INTEGER DEFAULT 0,
                memories_deleted   INTEGER DEFAULT 0,
                memories_merged    INTEGER DEFAULT 0,
                scenes_created     INTEGER DEFAULT 0,
                scenes_updated     INTEGER DEFAULT 0,
                foresights_generated INTEGER DEFAULT 0,
                dream_narrative TEXT DEFAULT '',
                structured_result JSONB,
                interrupted_at_memory_id INTEGER
            );
        """)

        # dream_logs 表扩展 — 新增列自动迁移
        for col_name, col_def in [
            ("links_created", "INTEGER DEFAULT 0"),
        ]:
            has_col = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'dream_logs' AND column_name = $1
                )
            """, col_name)
            if not has_col:
                await conn.execute(f"ALTER TABLE dream_logs ADD COLUMN {col_name} {col_def}")
                print(f"✅ dream_logs 表已添加 {col_name} 列")

        # v5.1：memories 表扩展 — Dream 相关字段
        for col_name, col_def in [
            ("is_permanent", "BOOLEAN DEFAULT FALSE"),
            ("scene_id", "INTEGER"),
            ("dream_processed_at", "TIMESTAMPTZ"),
        ]:
            has_col = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'memories' AND column_name = $1
                )
            """, col_name)
            if not has_col:
                await conn.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def}")
                print(f"✅ memories 表已添加 {col_name} 列")

        # v5.2：记忆热度系统 — 召回追踪 + 情绪标记
        for col_name, col_def in [
            ("emotional_weight", "INTEGER DEFAULT 0"),
            ("access_count", "INTEGER DEFAULT 0"),
            ("access_query_hashes", "JSONB DEFAULT '[]'"),
        ]:
            has_col = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'memories' AND column_name = $1
                )
            """, col_name)
            if not has_col:
                await conn.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def}")
                print(f"✅ memories 表已添加 {col_name} 列（热度系统）")

        # v5.2：chat_messages 表扩展 — 情绪标记
        has_emotion = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'chat_messages' AND column_name = 'emotion_flag'
            )
        """)
        if not has_emotion:
            await conn.execute("ALTER TABLE chat_messages ADD COLUMN emotion_flag TEXT DEFAULT 'normal'")
            print("✅ chat_messages 表已添加 emotion_flag 列")

        # v5.3：时间有效期窗口（MemPalace 启发）
        for col_name, col_def in [
            ("valid_from", "TIMESTAMPTZ DEFAULT NOW()"),
            ("valid_until", "TIMESTAMPTZ"),
        ]:
            has_col = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'memories' AND column_name = $1
                )
            """, col_name)
            if not has_col:
                await conn.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def}")
                print(f"✅ memories 表已添加 {col_name} 列（时间有效期）")

        # v5.4：日历页面添加 summary 字段（内容概要层级）
        has_summary = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'calendar_pages' AND column_name = 'summary'
            )
        """)
        if not has_summary:
            await conn.execute("ALTER TABLE calendar_pages ADD COLUMN summary TEXT DEFAULT ''")
            print("✅ calendar_pages 表已添加 summary 列（内容概要）")

        # v5.5：日历页面添加 digest 字段（模型注入用的中间层概要）
        has_digest = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'calendar_pages' AND column_name = 'digest'
            )
        """)
        if not has_digest:
            await conn.execute("ALTER TABLE calendar_pages ADD COLUMN digest TEXT DEFAULT ''")
            print("✅ calendar_pages 表已添加 digest 列（模型注入概要）")

        # v5.2：记忆关系标注表（typed edge）
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_edges (
                id          SERIAL PRIMARY KEY,
                from_id     INTEGER NOT NULL,
                from_type   TEXT DEFAULT 'memory',
                to_id       INTEGER NOT NULL,
                to_type     TEXT DEFAULT 'memory',
                edge_type   TEXT NOT NULL,
                reason      TEXT DEFAULT '',
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                created_by  TEXT DEFAULT 'dream'
            );
        """)

    print("✅ 数据库表结构已就绪（v5.3 时间有效期 + 矛盾检测）")


# ============================================================
# Embedding 生成
# ============================================================

async def get_embedding(text: str) -> Optional[List[float]]:
    """
    调用 OpenRouter Embedding API 生成向量
    
    使用与聊天相同的 API_KEY，接口完全兼容 OpenAI 格式
    失败时返回 None（触发降级搜索）
    """
    if not API_KEY:
        print("⚠️  API_KEY 未设置，无法生成 embedding")
        return None
    
    url = _get_embedding_url()
    
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": EMBEDDING_MODEL,
                    "input": text,
                },
            )
            
            if resp.status_code == 200:
                data = resp.json()
                embedding = data["data"][0]["embedding"]
                return embedding
            else:
                print(f"⚠️  Embedding API 返回 {resp.status_code}: {resp.text[:200]}")
                return None
                
    except Exception as e:
        print(f"⚠️  Embedding 生成失败: {e}")
        return None


async def get_embeddings_batch(texts: List[str]) -> List[Optional[List[float]]]:
    """
    批量生成 embedding（OpenRouter 支持批量输入）
    返回与 texts 等长的列表，失败的位置为 None
    """
    if not API_KEY or not texts:
        return [None] * len(texts)
    
    url = _get_embedding_url()
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": EMBEDDING_MODEL,
                    "input": texts,
                },
            )
            
            if resp.status_code == 200:
                data = resp.json()
                # API 返回的 data 列表按 index 排序
                results = [None] * len(texts)
                for item in data["data"]:
                    idx = item["index"]
                    results[idx] = item["embedding"]
                return results
            else:
                print(f"⚠️  批量 Embedding API 返回 {resp.status_code}: {resp.text[:200]}")
                return [None] * len(texts)
                
    except Exception as e:
        print(f"⚠️  批量 Embedding 生成失败: {e}")
        return [None] * len(texts)


# ============================================================
# 向量数学工具
# ============================================================

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ============================================================
# 记忆热度系统（遗忘曲线 + 召回追踪 + 情绪标记）
# ============================================================

# 热度参数默认值（config 表未配置时使用）
_HEAT_DEFAULTS = {
    "half_life_normal": 3.0,
    "half_life_important": 7.0,
    "recall_extend": 0.5,
    "threshold_high": 0.7,
    "threshold_medium": 0.3,
    "importance_line": 8,
    "emotion_line": 6,
}


async def get_heat_params() -> dict:
    """
    从 config 表加载热度参数（v5.4）
    异步调用，调用方加载一次后传给同步的 calculate_heat()
    """
    try:
        from config import get_config_float, get_config_int
        return {
            "half_life_normal": await get_config_float("heat_half_life_normal", _HEAT_DEFAULTS["half_life_normal"]),
            "half_life_important": await get_config_float("heat_half_life_important", _HEAT_DEFAULTS["half_life_important"]),
            "recall_extend": await get_config_float("heat_recall_extend", _HEAT_DEFAULTS["recall_extend"]),
            "threshold_high": await get_config_float("heat_threshold_high", _HEAT_DEFAULTS["threshold_high"]),
            "threshold_medium": await get_config_float("heat_threshold_medium", _HEAT_DEFAULTS["threshold_medium"]),
            "importance_line": await get_config_int("heat_importance_line", _HEAT_DEFAULTS["importance_line"]),
            "emotion_line": await get_config_int("heat_emotion_line", _HEAT_DEFAULTS["emotion_line"]),
        }
    except Exception:
        return dict(_HEAT_DEFAULTS)


def calculate_heat(row, params: dict = None) -> float:
    """
    计算一条记忆的当前热度（0.0 ~ 1.0）
    
    热度 = 初始温度 × 时间衰减 + 召回加成
    
    - 锁定记忆（is_permanent）热度永远 1.0
    - 初始温度由 importance + emotional_weight 决定
    - 时间衰减用半衰期模型，半衰期随 access_count 延长（艾宾浩斯）
    - 召回加成由 access_count + query_diversity 决定
    
    params: 从 get_heat_params() 加载的可配置参数，None 时用默认值
    """
    p = params or _HEAT_DEFAULTS
    # 已失效记忆热度直接归零（v5.4：与 SQL 的 valid_until > NOW() 保持一致）
    valid_until = row.get("valid_until")
    if valid_until is not None:
        try:
            vu = valid_until.replace(tzinfo=timezone.utc) if valid_until.tzinfo is None else valid_until.astimezone(timezone.utc)
            if vu <= datetime.now(timezone.utc):
                return 0.0
        except Exception:
            return 0.0
    
    # 锁定记忆不衰减
    if row.get("is_permanent"):
        return 1.0
    
    importance = row.get("importance", 5)
    emotional_weight = row.get("emotional_weight", 0) or 0
    access_count = row.get("access_count", 0) or 0
    created_at = row.get("created_at")
    
    # --- 冷启动保护 ---
    # 如果一条记忆从未被搜到过（热度系统还没有数据），
    # 不走遗忘曲线，给一个基于 importance 的稳定热度。
    # 等第一次被搜到后（access_count > 0），遗忘曲线才开始生效。
    # emotional_weight <= 2 视为低情绪，也走冷启动保护
    if access_count == 0 and emotional_weight <= 2:
        return min(1.0, 0.3 + importance / 10.0 * 0.5)  # importance=5 → 0.55, importance=8 → 0.7
    
    # --- 初始温度（0.3 ~ 1.0）---
    # importance(1-10) 和 emotional_weight(0-10) 各占一半
    imp_factor = importance / 10.0
    emo_factor = emotional_weight / 10.0
    initial_temp = 0.3 + 0.7 * max(imp_factor, emo_factor)
    initial_temp = min(1.0, initial_temp)
    
    # --- 半衰期（天）---
    # 基础半衰期：普通 vs 重要/高情绪（v5.4：可配置）
    if importance >= p["importance_line"] or emotional_weight >= p["emotion_line"]:
        base_half_life = p["half_life_important"]
    else:
        base_half_life = p["half_life_normal"]
    
    # 每次被召回，半衰期延长（被想起的事忘得更慢）
    half_life = base_half_life * (1.0 + access_count * p["recall_extend"])
    
    # --- 时间衰减 ---
    if created_at:
        try:
            # v5.4：安全时区处理（已有时区信息则转换，无则假设 UTC）
            if created_at.tzinfo is not None:
                created_utc = created_at.astimezone(timezone.utc)
            else:
                created_utc = created_at.replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - created_utc).total_seconds()
            age_days = age_seconds / 86400.0
            # 指数衰减：heat = 2^(-age/half_life)
            decay = math.pow(2, -age_days / half_life)
        except Exception:
            decay = 0.5
    else:
        decay = 0.5
    
    # --- 召回加成 ---
    # query_diversity 给额外加分（跨话题都有用的记忆更热）
    query_hashes = row.get("access_query_hashes") or []
    if isinstance(query_hashes, str):
        try:
            query_hashes = json.loads(query_hashes)
        except Exception:
            query_hashes = []
    query_diversity = len(set(query_hashes))
    recall_bonus = min(0.2, access_count * 0.02 + query_diversity * 0.03)
    
    # --- 最终热度 ---
    heat = initial_temp * decay + recall_bonus
    return max(0.0, min(1.0, heat))


# ============================================================
# 对话记录操作
# ============================================================

async def save_message(session_id: str, role: str, content: str, model: str = ""):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (session_id, role, content, model) VALUES ($1, $2, $3, $4)",
            session_id, role, content, model,
        )


async def get_recent_messages(session_id: str, limit: int = 20):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content, created_at FROM conversations WHERE session_id = $1 ORDER BY created_at DESC LIMIT $2",
            session_id, limit,
        )
        return list(reversed(rows))


async def get_recent_conversation(limit: int = 20):
    """获取最近 N 条对话记录（不限 session，按时间倒序取再正序返回）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content, created_at FROM conversations ORDER BY created_at DESC LIMIT $1",
            limit,
        )
        return list(reversed(rows))


async def get_handoff_messages(limit: int = 6):
    """
    获取最近一个有足够消息的对话的最后 N 条消息，用于无缝切窗。
    只取 user 和 assistant 角色的消息，按时间正序返回。
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 找最近一个至少有 4 条消息（2 轮来回）的对话
        conv = await conn.fetchrow("""
            SELECT c.id, c.title FROM chat_conversations c
            WHERE (
                SELECT COUNT(*) FROM chat_messages m 
                WHERE m.conversation_id = c.id AND m.role IN ('user', 'assistant')
            ) >= 4
            ORDER BY c.updated_at DESC
            LIMIT 1
        """)
        if not conv:
            return [], ""
        
        # 取最后 N 条消息
        rows = await conn.fetch("""
            SELECT role, content FROM chat_messages 
            WHERE conversation_id = $1 AND role IN ('user', 'assistant')
            ORDER BY sort_order DESC LIMIT $2
        """, conv['id'], limit)
        
        messages = list(reversed([dict(r) for r in rows]))
        return messages, conv.get('title', '')


# ============================================================
# 记忆操作
# ============================================================

async def save_memory(content: str, importance: int = 5, source_session: str = "", title: str = "", category_id: int = None, source: str = "ai_extracted", emotional_weight: int = 0) -> int:
    """
    存储新记忆，自动生成 embedding 向量
    如果 embedding 生成失败，记忆仍会存储（只是没有向量，降级为关键词搜索）
    
    source 取值：
    - 'user_explicit': 用户手动添加 / 明确陈述
    - 'ai_extracted': AI 从对话中自动提取
    - 'ai_digest': 每日整理合并生成
    - 'seed_import': 种子记忆导入
    
    emotional_weight: 情绪浓度 0-10，0=普通，越高越浓
    
    返回：新记忆的 ID（v5.3）
    """
    # 生成 embedding（title + content 合并生成，提升语义搜索精度）
    embed_text = f"{title} {content}" if title else content
    embedding = await get_embedding(embed_text)
    embedding_json = json.dumps(embedding) if embedding else None
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        new_id = await conn.fetchval(
            "INSERT INTO memories (content, importance, source_session, embedding, title, category_id, source, emotional_weight) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
            content, importance, source_session, embedding_json, title, category_id, source, emotional_weight,
        )
    
    title_tag = f"[{title}] " if title else ""
    emo_tag = f" 🩷emo={emotional_weight}" if emotional_weight > 0 else ""
    if embedding:
        print(f"💎 记忆已存储 #{new_id}（含向量，{len(embedding)}维{emo_tag}）: {title_tag}{content[:50]}...")
    else:
        print(f"📝 记忆已存储 #{new_id}（无向量{emo_tag}）: {title_tag}{content[:50]}...")
    
    return new_id


async def delete_memory(memory_id: int) -> bool:
    """删除单条记忆，返回是否成功"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM memories WHERE id = $1", memory_id
        )
        return result == "DELETE 1"


async def clear_all_memories() -> int:
    """清空所有记忆，返回删除的条数"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchrow("SELECT COUNT(*) as cnt FROM memories")
        await conn.execute("DELETE FROM memories")
        return count["cnt"]


async def update_memory(memory_id: int, content: str = None, importance: int = None, title: str = None, category_id: object = "UNSET") -> bool:
    """更新单条记忆的内容、标题、重要程度或分类（内容/标题变化时重新生成 embedding）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 先获取当前记录（用于合并 embedding 生成）
        current = await conn.fetchrow(
            "SELECT content, title FROM memories WHERE id = $1", memory_id
        )
        if not current:
            return False
        
        new_content = content if content is not None else current["content"]
        new_title = title if title is not None else (current["title"] or "")
        
        # 内容或标题变了，重新生成 embedding
        need_re_embed = (content is not None) or (title is not None)
        
        sets = []
        params = []
        idx = 1
        
        if need_re_embed:
            embed_text = f"{new_title} {new_content}" if new_title else new_content
            embedding = await get_embedding(embed_text)
            embedding_json = json.dumps(embedding) if embedding else None
            
            sets.append(f"embedding = ${idx}")
            params.append(embedding_json)
            idx += 1
            
            if content is not None:
                sets.append(f"content = ${idx}")
                params.append(content)
                idx += 1
            
            if title is not None:
                sets.append(f"title = ${idx}")
                params.append(title)
                idx += 1
        
        if importance is not None:
            sets.append(f"importance = ${idx}")
            params.append(importance)
            idx += 1
        
        # category_id: None = clear category, int = set category, "UNSET" = don't change
        if category_id != "UNSET":
            sets.append(f"category_id = ${idx}")
            params.append(category_id)
            idx += 1
        
        if not sets:
            return False
        
        params.append(memory_id)
        sql = f"UPDATE memories SET {', '.join(sets)} WHERE id = ${idx}"
        result = await conn.execute(sql, *params)
        return result == "UPDATE 1"


# ============================================================
# 记忆搜索（v3.0 向量语义搜索）
# ============================================================

async def search_memories(query: str, limit: int = 10, track_recall: bool = True):
    """
    搜索相关记忆 —— RRF 混合检索（v5.7）
    
    流程：
    1. 生成查询向量
    2. 并行执行向量搜索 + 关键词搜索
    3. RRF（Reciprocal Rank Fusion）合并两路结果
    4. 更新召回追踪数据（可关闭）
    5. 返回 top-K
    
    参数：
        track_recall: 是否记录召回追踪数据。聊天注入时=True，去重对比时=False
    
    降级：如果 embedding 生成失败，只用关键词搜索
    """
    # 候选池扩大到 3 倍，给 RRF 合并留充足的候选
    expanded_limit = limit * 3
    
    # 第一步：生成查询向量
    query_embedding = await get_embedding(query)
    
    heat_params = await get_heat_params()
    
    if query_embedding is None:
        # embedding 失败，只用关键词搜索
        print("⚠️  向量搜索不可用 → 仅关键词搜索")
        results = await _keyword_search(query, limit, heat_params)
    else:
        # 第二步：并行执行两路搜索
        vec_task = _vector_search(query_embedding, expanded_limit, heat_params)
        kw_task = _keyword_search(query, expanded_limit, heat_params)
        vec_results, kw_results = await asyncio.gather(vec_task, kw_task)
        
        # 第三步：RRF 合并
        if vec_results and kw_results:
            results = _rrf_merge(vec_results, kw_results, k=RRF_K, final_limit=limit)
            v_only = sum(1 for r in results if r.get("_source") == "vector_only")
            k_only = sum(1 for r in results if r.get("_source") == "keyword_only")
            both = sum(1 for r in results if r.get("_source") == "both")
            print(f"🔍 RRF 混合搜索 '{query[:30]}...' → 向量{len(vec_results)}条 + 关键词{len(kw_results)}条 → 合并top-{len(results)}（双命中{both}/仅向量{v_only}/仅关键词{k_only}）")
        elif vec_results:
            results = vec_results[:limit]
            print(f"🔍 向量搜索 '{query[:30]}...' → {len(vec_results)}条（关键词无结果）")
        elif kw_results:
            results = kw_results[:limit]
            print(f"🔍 关键词搜索 '{query[:30]}...' → {len(kw_results)}条（向量无结果）")
        else:
            results = []
            print(f"🔍 搜索 '{query[:30]}...' → 无结果")
    
    # 打印 top-3 详情
    for r in results[:3]:
        src_tag = r.get("_source", "?")
        print(f"   📌 [score={r['score']:.3f}, sim={r.get('similarity', 0):.3f}, heat={r.get('heat', 0):.2f}, src={src_tag}] {r['content'][:60]}...")
    
    # 清理内部标记
    for r in results:
        r.pop("_source", None)
    
    # 第四步：更新召回追踪（统一在这里做，两路搜索不各自追踪）
    if results and track_recall:
        query_hash = hashlib.md5(query.strip()[:100].encode()).hexdigest()[:8]
        ids = [r["id"] for r in results]
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE memories 
                SET last_accessed = NOW(),
                    access_count = COALESCE(access_count, 0) + 1
                WHERE id = ANY($1::int[])
            """, ids)
            
            try:
                await conn.execute("""
                    UPDATE memories
                    SET access_query_hashes = (
                        SELECT jsonb_agg(elem)
                        FROM (
                            SELECT DISTINCT elem
                            FROM jsonb_array_elements(
                                COALESCE(access_query_hashes, '[]'::jsonb) || $2::jsonb
                            ) AS elem
                            LIMIT 50
                        ) sub
                    )
                    WHERE id = ANY($1::int[])
                """, ids, json.dumps([query_hash]))
            except Exception:
                pass
        
        # v5.4：自动锁定检测
        try:
            await _check_auto_lock(ids, heat_params)
        except Exception as e:
            print(f"   ⚠️ 自动锁定检测出错（不影响搜索）: {e}")
    
    return results


async def _vector_search(query_embedding: list, limit: int, heat_params: dict) -> list:
    """
    纯向量语义搜索 —— 不做召回追踪，仅返回评分结果。
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT m.id, m.content, m.importance, m.created_at, m.embedding, 
                      COALESCE(m.title, '') as title, COALESCE(m.memory_type, 'fragment') as memory_type,
                      m.category_id, COALESCE(c.name, '') as category_name, COALESCE(c.color, '') as category_color,
                      COALESCE(m.source, 'ai_extracted') as source,
                      COALESCE(m.emotional_weight, 0) as emotional_weight,
                      COALESCE(m.access_count, 0) as access_count,
                      COALESCE(m.access_query_hashes, '[]'::jsonb) as access_query_hashes,
                      COALESCE(m.is_permanent, false) as is_permanent,
                      m.valid_until
               FROM memories m LEFT JOIN memory_categories c ON m.category_id = c.id
               WHERE COALESCE(m.memory_type, 'fragment') NOT IN ('digested', 'dream_deleted')
                 AND (m.valid_until IS NULL OR m.valid_until > NOW())"""
        )
    
    if not rows:
        return []
    
    scored = []
    no_embedding_count = 0
    
    for row in rows:
        if row["embedding"] is None:
            no_embedding_count += 1
            continue
        
        try:
            mem_embedding = json.loads(row["embedding"])
        except (json.JSONDecodeError, TypeError):
            no_embedding_count += 1
            continue
        
        sim = cosine_similarity(query_embedding, mem_embedding)
        
        if sim < SEMANTIC_THRESHOLD:
            continue
        
        _ca = row["created_at"]
        _ca_utc = _ca.astimezone(timezone.utc) if _ca.tzinfo is not None else _ca.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - _ca_utc).total_seconds()
        recency = 1.0 / (1.0 + age_seconds / 86400.0)
        
        heat = calculate_heat(row, heat_params)
        
        score = (
            WEIGHT_SEMANTIC * sim +
            WEIGHT_IMPORTANCE * row["importance"] / 10.0 +
            WEIGHT_RECENCY * recency +
            WEIGHT_HEAT * heat
        )
        
        scored.append({
            "id": row["id"],
            "title": row["title"],
            "content": row["content"],
            "importance": row["importance"],
            "created_at": row["created_at"],
            "memory_type": row.get("memory_type", "fragment"),
            "category_id": row.get("category_id"),
            "category_name": row.get("category_name", ""),
            "category_color": row.get("category_color", ""),
            "source": row.get("source", "ai_extracted"),
            "is_permanent": row.get("is_permanent", False),
            "emotional_weight": row.get("emotional_weight", 0),
            "heat": round(heat, 4),
            "similarity": round(sim, 4),
            "score": round(score, 4),
        })
    
    scored.sort(key=lambda x: x["score"], reverse=True)
    
    if no_embedding_count:
        print(f"   ⚠️  {no_embedding_count} 条记忆缺少向量")
    
    return scored[:limit]


def _rrf_merge(vec_results: list, kw_results: list, k: int = 60, final_limit: int = 10) -> list:
    """
    Reciprocal Rank Fusion（RRF）合并两路搜索结果。
    
    RRF 公式：rrf_score(d) = Σ 1 / (k + rank_i)
    k=60 是业界标准值，让排名靠后的结果权重衰减温和。
    
    两路搜到同一条记忆 → 分数叠加（双命中加权更高）
    只有一路搜到 → 也保留（单路命中仍有价值）
    """
    rrf_scores = {}   # id → rrf_score
    result_map = {}   # id → result dict
    source_map = {}   # id → set of sources
    
    # 向量搜索结果按排名计分
    for rank, item in enumerate(vec_results):
        mid = item["id"]
        rrf_scores[mid] = rrf_scores.get(mid, 0) + 1.0 / (k + rank + 1)
        result_map[mid] = item
        source_map.setdefault(mid, set()).add("vector")
    
    # 关键词搜索结果按排名计分
    for rank, item in enumerate(kw_results):
        mid = item["id"]
        rrf_scores[mid] = rrf_scores.get(mid, 0) + 1.0 / (k + rank + 1)
        # 如果向量搜索已经有这条，保留向量版（字段更全，有similarity和heat）
        if mid not in result_map:
            result_map[mid] = item
        source_map.setdefault(mid, set()).add("keyword")
    
    # 按 RRF 分数降序排列
    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    
    merged = []
    for mid in sorted_ids[:final_limit]:
        item = result_map[mid]
        sources = source_map[mid]
        item["score"] = round(rrf_scores[mid], 6)
        if "vector" in sources and "keyword" in sources:
            item["_source"] = "both"
        elif "vector" in sources:
            item["_source"] = "vector_only"
        else:
            item["_source"] = "keyword_only"
        merged.append(item)
    
    return merged


# ============================================================
# v5.4：记忆自动锁定（模拟高敏感人脑）
# ============================================================

async def _check_auto_lock(memory_ids: list, heat_params: dict = None):
    """
    检查刚被召回的记忆是否达到自动锁定条件。
    
    高敏感人脑模型：
    - 普通记忆：access_count >= 10 且 query_diversity >= 5（跨了很多场景都被想起 → 核心认知）
    - 高情绪记忆：门槛降低到 access_count >= 6 且 query_diversity >= 3（情绪浓的事更容易记死）
    - 已锁定/已失效的跳过
    
    阈值可通过 config 表调整。
    """
    if not memory_ids:
        return
    
    # 加载自动锁定参数
    try:
        from config import get_config_int
        ac_threshold = await get_config_int("autolock_access_count", 10)
        div_threshold = await get_config_int("autolock_diversity", 5)
        emo_ac_threshold = await get_config_int("autolock_emo_access", 6)
        emo_div_threshold = await get_config_int("autolock_emo_diversity", 3)
    except Exception:
        ac_threshold, div_threshold = 10, 5
        emo_ac_threshold, emo_div_threshold = 6, 3
    
    p = heat_params or _HEAT_DEFAULTS
    emotion_line = p.get("emotion_line", 6)
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 查询刚被召回的记忆的最新状态
        rows = await conn.fetch("""
            SELECT id, COALESCE(title, '') as title,
                   COALESCE(access_count, 0) as access_count,
                   COALESCE(access_query_hashes, '[]'::jsonb) as access_query_hashes,
                   COALESCE(emotional_weight, 0) as emotional_weight,
                   COALESCE(is_permanent, false) as is_permanent
            FROM memories
            WHERE id = ANY($1::int[])
              AND COALESCE(is_permanent, false) = FALSE
              AND (valid_until IS NULL OR valid_until > NOW())
        """, memory_ids)
        
        for row in rows:
            ac = row["access_count"]
            qh = row["access_query_hashes"]
            if isinstance(qh, str):
                try:
                    qh = json.loads(qh)
                except Exception:
                    qh = []
            diversity = len(set(qh))
            emo = row["emotional_weight"]
            
            # 高情绪记忆：门槛更低（情绪浓的事更容易刻进脑子）
            if emo >= emotion_line:
                should_lock = ac >= emo_ac_threshold and diversity >= emo_div_threshold
            else:
                should_lock = ac >= ac_threshold and diversity >= div_threshold
            
            if should_lock:
                await conn.execute(
                    "UPDATE memories SET is_permanent = TRUE WHERE id = $1",
                    row["id"]
                )
                title = row["title"] or f"#{row['id']}"
                emo_tag = "（高情绪加成）" if emo >= emotion_line else ""
                print(f"   🔒 自动锁定: {title}（召回{ac}次，跨{diversity}话题{emo_tag}）")


# ============================================================
# 关键词搜索（降级方案）
# ============================================================

# 同义词表（保留用于降级搜索，可自行扩展）
SYNONYM_GROUPS = [
    {"吃药", "用药", "药物", "服药", "药方"},
    {"名字", "叫什么", "称呼", "昵称", "小名"},
    {"身高", "体重", "多高", "多重", "体型"},
    {"外貌", "长相", "外表", "样子", "容貌"},
    {"性格", "脾气", "个性", "人格"},
    {"工作", "职业", "职位", "职务"},
    {"喜欢", "偏好", "爱好", "兴趣"},
    {"健康", "身体", "疾病", "病史", "生病"},
    {"情感", "感情", "情绪", "心理"},
    {"写作", "创作", "文章", "文案"},
    {"投资", "理财", "资产", "财务"},
    # 可按需添加更多同义词组
]

CJK_PATTERN = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
EN_WORD_PATTERN = re.compile(r'[a-zA-Z0-9]+')
NUM_PATTERN = re.compile(r'\d{2,}')

# ---- jieba 初始化 ----
# 系统内置词汇（防止被错误切分）
_JIEBA_SYSTEM_WORDS = [
    "记忆碎片", "日页面", "用户画像",
]

# 用户自定义词汇：通过环境变量 JIEBA_CUSTOM_WORDS 配置，逗号分隔
# 示例：JIEBA_CUSTOM_WORDS=用户昵称,助手名字,项目名称
_custom_words_env = os.getenv("JIEBA_CUSTOM_WORDS", "")
_JIEBA_USER_WORDS = [w.strip() for w in _custom_words_env.split(",") if w.strip()]

for _w in _JIEBA_SYSTEM_WORDS + _JIEBA_USER_WORDS:
    jieba.add_word(_w)
if _JIEBA_USER_WORDS:
    print(f"📖 jieba 自定义词汇：{', '.join(_JIEBA_USER_WORDS)}")

# 中文停用词（搜索时过滤掉这些无意义的词）
_CHINESE_STOPWORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "他", "她", "吗", "什么", "啊", "呢", "吧", "哦", "嗯",
    "那", "还", "把", "给", "让", "用", "被", "从", "对", "但", "而", "或",
    "如果", "因为", "所以", "可以", "这个", "那个", "就是", "已经", "可能",
    "然后", "但是", "还是", "虽然", "比较", "应该", "一些", "这些", "那些",
    "怎么", "怎么样", "时候", "现在", "今天", "昨天", "明天", "最近",
    "觉得", "知道", "想", "来", "过", "做",
}

# 预热 jieba（首次 cut 会加载词典，启动时就加载好）
jieba.initialize()
print("✅ jieba 分词引擎已初始化")


def _expand_synonyms(keywords: set) -> set:
    """根据同义词表扩展关键词"""
    expanded = set(keywords)
    for group in SYNONYM_GROUPS:
        matched = False
        for kw in keywords:
            if kw in group:
                matched = True
                break
            for syn in group:
                if kw in syn or syn in kw:
                    matched = True
                    break
            if matched:
                break
        
        if not matched:
            for kw in keywords:
                kw_chars = set(c for c in kw if '\u4e00' <= c <= '\u9fff')
                if kw_chars:
                    hit_count = sum(1 for syn in group if kw_chars & set(syn))
                    if hit_count >= 2:
                        matched = True
                        break
        
        if matched:
            expanded.update(group)
    return expanded


def extract_search_keywords(query: str) -> List[str]:
    """
    从查询中提取搜索关键词（v5.7：jieba 分词版）
    
    使用 jieba.cut_for_search 搜索引擎模式：
    - 先精确切分，再把长词拆成子词
    - 例："中华人民共和国" → "中华/华人/人民/共和/共和国/中华人民共和国"
    - 比滑动窗口准确得多，不会切出"糖控""近血"这种垃圾
    """
    keywords = set()
    
    # 英文单词（保留原逻辑）
    for match in EN_WORD_PATTERN.finditer(query):
        word = match.group()
        if len(word) >= 2:
            keywords.add(word.lower())
    
    # 数字（保留原逻辑）
    for match in NUM_PATTERN.finditer(query):
        keywords.add(match.group())
    
    # 中文：jieba 搜索模式分词
    for word in jieba.cut_for_search(query):
        word = word.strip()
        # 跳过：非中文、单字、停用词
        if not word or len(word) < 2:
            continue
        if not CJK_PATTERN.search(word):
            continue
        if word in _CHINESE_STOPWORDS:
            continue
        keywords.add(word)
    
    # 同义词扩展（保留原逻辑）
    keywords = _expand_synonyms(keywords)
    return list(keywords)


async def _keyword_search(query: str, limit: int = 10, heat_params: dict = None):
    """
    关键词搜索（v5.7：升级为 RRF 混合检索的一路）
    
    改进：
    - 同时搜索标题和内容（标题命中权重更高）
    - 返回格式与向量搜索完全一致（含热度字段）
    - 不做召回追踪（由 search_memories 统一处理）
    """
    keywords = extract_search_keywords(query)
    
    if not keywords:
        return []
    
    if heat_params is None:
        heat_params = await get_heat_params()
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 内容命中计分（每个关键词命中 +1）
        content_case_parts = []
        # 标题命中计分（每个关键词命中 +1.5，标题匹配更有价值）
        title_case_parts = []
        params = []
        for i, kw in enumerate(keywords):
            content_case_parts.append(f"CASE WHEN m.content ILIKE '%' || ${i+1} || '%' THEN 1 ELSE 0 END")
            title_case_parts.append(f"CASE WHEN COALESCE(m.title, '') ILIKE '%' || ${i+1} || '%' THEN 1.5 ELSE 0 END")
            params.append(kw)
        
        hit_count_expr = " + ".join(content_case_parts) + " + " + " + ".join(title_case_parts)
        max_hits = len(keywords) * 2.5  # 内容最多 N 分 + 标题最多 1.5N 分
        
        # WHERE：内容 OR 标题命中任一关键词
        content_where = [f"m.content ILIKE '%' || ${i+1} || '%'" for i in range(len(keywords))]
        title_where = [f"COALESCE(m.title, '') ILIKE '%' || ${i+1} || '%'" for i in range(len(keywords))]
        where_clause = " OR ".join(content_where + title_where)
        
        limit_idx = len(keywords) + 1
        params.append(limit)
        
        sql = f"""
            SELECT 
                m.id, m.content, m.importance, m.created_at, 
                COALESCE(m.title, '') as title, COALESCE(m.memory_type, 'fragment') as memory_type,
                m.category_id, COALESCE(c.name, '') as category_name, COALESCE(c.color, '') as category_color,
                COALESCE(m.source, 'ai_extracted') as source,
                COALESCE(m.emotional_weight, 0) as emotional_weight,
                COALESCE(m.access_count, 0) as access_count,
                COALESCE(m.access_query_hashes, '[]'::jsonb) as access_query_hashes,
                COALESCE(m.is_permanent, false) as is_permanent,
                ({hit_count_expr}) AS hit_count,
                (
                    0.5 * ({hit_count_expr})::float / {max_hits} +
                    0.3 * m.importance::float / 10.0 +
                    0.2 * (1.0 / (1.0 + EXTRACT(EPOCH FROM (NOW() - m.created_at)) / 86400.0))
                ) AS score
            FROM memories m LEFT JOIN memory_categories c ON m.category_id = c.id
            WHERE ({where_clause})
              AND COALESCE(m.memory_type, 'fragment') NOT IN ('digested', 'dream_deleted')
              AND (m.valid_until IS NULL OR m.valid_until > NOW())
            ORDER BY score DESC, m.importance DESC, m.created_at DESC
            LIMIT ${limit_idx}
        """
        
        rows = await conn.fetch(sql, *params)

        results = []
        for r in rows:
            heat = calculate_heat(r, heat_params)
            results.append({
                "id": r["id"],
                "title": r["title"],
                "content": r["content"],
                "importance": r["importance"],
                "created_at": r["created_at"],
                "memory_type": r["memory_type"],
                "category_id": r["category_id"],
                "category_name": r["category_name"],
                "category_color": r["category_color"],
                "source": r["source"],
                "is_permanent": r.get("is_permanent", False),
                "emotional_weight": r.get("emotional_weight", 0),
                "heat": round(heat, 4),
                "similarity": 0.0,
                "score": round(float(r["score"]), 4),
            })

        return results


# ============================================================
# 常用查询
# ============================================================

async def get_recent_memories(limit: int = 20, category_id: int = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if category_id is not None:
            return await conn.fetch(
                """SELECT m.id, m.content, m.importance, m.created_at, 
                          COALESCE(m.title, '') as title, COALESCE(m.memory_type, 'fragment') as memory_type,
                          m.category_id, COALESCE(c.name, '') as category_name, COALESCE(c.color, '') as category_color,
                          COALESCE(m.source, 'ai_extracted') as source
                   FROM memories m LEFT JOIN memory_categories c ON m.category_id = c.id
                   WHERE COALESCE(m.memory_type, 'fragment') NOT IN ('digested', 'dream_deleted')
                     AND (m.valid_until IS NULL OR m.valid_until > NOW())
                     AND m.category_id = $1
                   ORDER BY m.created_at DESC LIMIT $2""",
                category_id, limit,
            )
        else:
            return await conn.fetch(
                """SELECT m.id, m.content, m.importance, m.created_at, 
                          COALESCE(m.title, '') as title, COALESCE(m.memory_type, 'fragment') as memory_type,
                          m.category_id, COALESCE(c.name, '') as category_name, COALESCE(c.color, '') as category_color,
                          COALESCE(m.source, 'ai_extracted') as source
                   FROM memories m LEFT JOIN memory_categories c ON m.category_id = c.id
                   WHERE COALESCE(m.memory_type, 'fragment') NOT IN ('digested', 'dream_deleted')
                     AND (m.valid_until IS NULL OR m.valid_until > NOW())
                   ORDER BY m.created_at DESC LIMIT $1""",
                limit,
            )


async def get_all_memories_count():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) as cnt FROM memories")
        return row["cnt"]


# ============================================================
# 记忆去重检测
# ============================================================

async def check_memory_duplicate(new_content: str, threshold: float = None, new_title: str = ""):
    """
    检查新记忆是否与已有记忆重复（v5.4：标题不同时不判重复）
    
    三层检测：
    1. 精确匹配
    2. 包含关系
    3. 字符重叠度 + 标题保护（标题明显不同 → 不同主题 → 放行）
    
    返回：(is_duplicate: bool, similar_results: list)
    
    注意：去重仍用字符级检测（而非向量），因为去重需要精确判断，
    而向量搜索更适合"模糊相关"的场景。
    """
    if threshold is None:
        threshold = DEDUP_THRESHOLD
    
    pool = await get_pool()
    
    # 第1层：精确匹配
    async with pool.acquire() as conn:
        exact_count = await conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE content = $1",
            new_content,
        )
        if exact_count > 0:
            print(f"🔄 精确重复，跳过: {new_content[:60]}...")
            return True, []
    
    # 第2层 + 第3层：先用向量搜索找候选，再做精确对比
    try:
        similar = await search_memories(new_content, limit=15, track_recall=False)
    except Exception:
        return False, []
    
    if not similar:
        return False, []
    
    new_chars = set(c for c in new_content if '\u4e00' <= c <= '\u9fff')
    
    for mem in similar:
        existing_content = mem["content"]
        
        # 第2层：包含关系
        new_clean = re.sub(r'[^\u4e00-\u9fffa-zA-Z0-9]', '', new_content)
        old_clean = re.sub(r'[^\u4e00-\u9fffa-zA-Z0-9]', '', existing_content)
        
        if len(new_clean) >= 6 and len(old_clean) >= 6:
            if new_clean in old_clean or old_clean in new_clean:
                print(f"🔄 包含关系重复，跳过: {new_content[:60]}...")
                print(f"   已有: {existing_content[:60]}...")
                return True, similar
        
        # 第3层：字符重叠度
        if len(new_chars) < 3:
            continue
        
        existing_chars = set(c for c in existing_content if '\u4e00' <= c <= '\u9fff')
        if len(existing_chars) < 3:
            continue
        
        overlap = new_chars & existing_chars
        ratio_new_to_old = len(overlap) / len(new_chars)
        ratio_old_to_new = len(overlap) / len(existing_chars)
        max_ratio = max(ratio_new_to_old, ratio_old_to_new)
        
        if max_ratio >= threshold:
            # v5.4：标题保护——如果模型给了不同的标题，说明是不同主题，放行
            if new_title:
                old_title = mem.get("title", "")
                if old_title and new_title != old_title:
                    # 标题字符重叠度低于 50% → 不同主题，不判重复
                    t_new = set(c for c in new_title if '\u4e00' <= c <= '\u9fff' or c.isalpha())
                    t_old = set(c for c in old_title if '\u4e00' <= c <= '\u9fff' or c.isalpha())
                    if t_new and t_old:
                        t_overlap = len(t_new & t_old) / max(len(t_new), len(t_old))
                        if t_overlap < 0.5:
                            print(f"🔄 字符重叠 {max_ratio:.0%} 但标题不同（{new_title} vs {old_title}），放行")
                            continue
            print(f"🔄 字符重叠 {max_ratio:.0%}，跳过: {new_content[:60]}...")
            print(f"   已有: {existing_content[:60]}...")
            return True, similar
    
    return False, similar


# ============================================================
# Embedding 迁移工具
# ============================================================

async def migrate_embeddings(batch_size: int = 20) -> dict:
    """
    为所有缺少 embedding 的记忆生成向量
    
    分批处理，避免一次性调用太多 API
    返回迁移统计信息
    """
    pool = await get_pool()
    
    async with pool.acquire() as conn:
        # 找出所有没有 embedding 的记忆
        rows = await conn.fetch(
            "SELECT id, content FROM memories WHERE embedding IS NULL ORDER BY id"
        )
    
    if not rows:
        return {"status": "done", "message": "所有记忆都已有向量", "migrated": 0, "failed": 0}
    
    total = len(rows)
    migrated = 0
    failed = 0
    
    print(f"🔄 开始迁移 {total} 条记忆的向量...")
    
    # 分批处理
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        texts = [row["content"] for row in batch]
        ids = [row["id"] for row in batch]
        
        print(f"   批次 {i//batch_size + 1}: 处理 {len(batch)} 条 (#{ids[0]} ~ #{ids[-1]})")
        
        embeddings = await get_embeddings_batch(texts)
        
        async with pool.acquire() as conn:
            for j, (row_id, emb) in enumerate(zip(ids, embeddings)):
                if emb is not None:
                    await conn.execute(
                        "UPDATE memories SET embedding = $1 WHERE id = $2",
                        json.dumps(emb), row_id
                    )
                    migrated += 1
                else:
                    failed += 1
                    print(f"   ⚠️  #{row_id} embedding 生成失败")
    
    print(f"✅ 迁移完成：{migrated} 成功，{failed} 失败，共 {total} 条")
    
    return {
        "status": "done",
        "total": total,
        "migrated": migrated,
        "failed": failed,
    }


async def get_embedding_stats() -> dict:
    """获取 embedding 覆盖统计"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM memories")
        with_embedding = await conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL"
        )
    return {
        "total_memories": total,
        "with_embedding": with_embedding,
        "without_embedding": total - with_embedding,
        "coverage": f"{with_embedding/total*100:.1f}%" if total > 0 else "N/A",
    }

async def get_all_providers():
    """获取所有供应商"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, api_base_url, api_key, enabled, created_at, updated_at
            FROM providers ORDER BY created_at ASC
        """)
        return [dict(r) for r in rows]


async def get_provider(provider_id: int):
    """获取单个供应商"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, api_base_url, api_key, enabled, created_at, updated_at
            FROM providers WHERE id = $1
        """, provider_id)
        return dict(row) if row else None


async def create_provider(name: str, api_base_url: str, api_key: str = '', enabled: bool = True):
    """创建供应商"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO providers (name, api_base_url, api_key, enabled)
            VALUES ($1, $2, $3, $4)
            RETURNING id, name, api_base_url, api_key, enabled, created_at, updated_at
        """, name, api_base_url, api_key, enabled)
        return dict(row)


async def update_provider(provider_id: int, **kwargs):
    """更新供应商"""
    pool = await get_pool()
    allowed = {'name', 'api_base_url', 'api_key', 'enabled'}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return None

    sets = []
    vals = []
    for i, (k, v) in enumerate(fields.items(), 1):
        sets.append(f"{k} = ${i}")
        vals.append(v)
    sets.append(f"updated_at = NOW()")
    vals.append(provider_id)

    query = f"""
        UPDATE providers SET {', '.join(sets)}
        WHERE id = ${len(vals)}
        RETURNING id, name, api_base_url, api_key, enabled, created_at, updated_at
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *vals)
        return dict(row) if row else None


async def delete_provider(provider_id: int):
    """删除供应商"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM providers WHERE id = $1", provider_id
        )
        return "DELETE 1" in result


# ============================================================
# 供应商模型管理
# ============================================================

async def get_provider_models(provider_id: int):
    """获取供应商已保存的模型"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, provider_id, model_id, display_name, model_type,
                   input_modes, output_modes, capabilities, created_at
            FROM provider_models WHERE provider_id = $1
            ORDER BY created_at ASC
        """, provider_id)
        return [dict(r) for r in rows]


async def get_all_saved_models():
    """获取所有供应商的已保存模型（含供应商名称，用于默认模型选择器）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT pm.id, pm.provider_id, pm.model_id, pm.display_name, pm.model_type,
                   pm.input_modes, pm.output_modes, pm.capabilities, pm.created_at,
                   p.name as provider_name
            FROM provider_models pm
            JOIN providers p ON pm.provider_id = p.id
            ORDER BY p.name ASC, pm.display_name ASC
        """)
        return [dict(r) for r in rows]


async def add_provider_model(provider_id: int, model_id: str, display_name: str = '',
                             model_type: str = 'chat', input_modes: str = 'text',
                             output_modes: str = 'text', capabilities: str = ''):
    """添加模型到供应商"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO provider_models (provider_id, model_id, display_name, model_type,
                                         input_modes, output_modes, capabilities)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (provider_id, model_id) DO NOTHING
            RETURNING id, provider_id, model_id, display_name, model_type,
                      input_modes, output_modes, capabilities, created_at
        """, provider_id, model_id, display_name or model_id, model_type,
             input_modes, output_modes, capabilities)
        return dict(row) if row else None


async def update_provider_model(model_pk_id: int, **kwargs):
    """更新模型配置"""
    pool = await get_pool()
    allowed = {'display_name', 'model_type', 'input_modes', 'output_modes', 'capabilities'}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return None

    sets = []
    vals = []
    for i, (k, v) in enumerate(fields.items(), 1):
        sets.append(f"{k} = ${i}")
        vals.append(v)
    vals.append(model_pk_id)

    query = f"""
        UPDATE provider_models SET {', '.join(sets)}
        WHERE id = ${len(vals)}
        RETURNING id, provider_id, model_id, display_name, model_type,
                  input_modes, output_modes, capabilities, created_at
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *vals)
        return dict(row) if row else None


async def delete_provider_model(model_pk_id: int):
    """删除已保存的模型"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM provider_models WHERE id = $1", model_pk_id
        )
        return "DELETE 1" in result


async def resolve_provider_for_model(model_id: str):
    """根据 model_id 查找对应的已启用供应商，返回 {api_base_url, api_key, provider_name} 或 None"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT p.api_base_url, p.api_key, p.name as provider_name
            FROM provider_models pm
            JOIN providers p ON pm.provider_id = p.id
            WHERE pm.model_id = $1 AND p.enabled = TRUE
            LIMIT 1
        """, model_id)
        return dict(row) if row else None


# ============================================================
# 记忆分类管理（v3.7）
# ============================================================

async def get_all_categories():
    """获取所有分类"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id, c.name, c.color, c.icon, c.sort_order, c.created_at,
                   COUNT(m.id) as memory_count
            FROM memory_categories c 
            LEFT JOIN memories m ON c.id = m.category_id AND COALESCE(m.memory_type, 'fragment') NOT IN ('digested', 'dream_deleted') AND (m.valid_until IS NULL OR m.valid_until > NOW())
            GROUP BY c.id
            ORDER BY c.sort_order ASC, c.created_at ASC
        """)
        return [dict(r) for r in rows]


async def create_category(name: str, color: str = '#6B7280', icon: str = '📁', sort_order: int = 0):
    """创建分类"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO memory_categories (name, color, icon, sort_order)
            VALUES ($1, $2, $3, $4)
            RETURNING id, name, color, icon, sort_order, created_at
        """, name, color, icon, sort_order)
        return dict(row) if row else None


async def update_category(category_id: int, **kwargs):
    """更新分类"""
    pool = await get_pool()
    allowed = {'name', 'color', 'icon', 'sort_order'}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return None
    
    sets = []
    vals = []
    for i, (k, v) in enumerate(fields.items(), 1):
        sets.append(f"{k} = ${i}")
        vals.append(v)
    vals.append(category_id)
    
    query = f"""
        UPDATE memory_categories SET {', '.join(sets)}
        WHERE id = ${len(vals)}
        RETURNING id, name, color, icon, sort_order, created_at
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *vals)
        return dict(row) if row else None


async def delete_category(category_id: int):
    """删除分类（记忆的 category_id 会自动设为 NULL）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM memory_categories WHERE id = $1", category_id
        )
        return "DELETE 1" in result


async def match_category_by_name(name_hint: str):
    """
    根据名称模糊匹配分类（用于自动归类）
    返回匹配到的 category_id，没匹配到返回 None
    """
    if not name_hint:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 精确匹配
        row = await conn.fetchrow(
            "SELECT id FROM memory_categories WHERE name = $1", name_hint
        )
        if row:
            return row["id"]
        # 模糊匹配（分类名包含提示词，或提示词包含分类名）
        rows = await conn.fetch("SELECT id, name FROM memory_categories")
        for r in rows:
            cat_name = r["name"]
            if cat_name in name_hint or name_hint in cat_name:
                return r["id"]
        return None


# ============================================================
# System Prompt 数据库存储（v3.7）
# ============================================================

async def get_system_prompt_from_db() -> Optional[str]:
    """从数据库读取 system prompt"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM gateway_config WHERE key = 'system_prompt'"
        )
        return row["value"] if row else None


async def set_system_prompt_in_db(content: str) -> bool:
    """保存 system prompt 到数据库"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO gateway_config (key, value, label, updated_at) 
            VALUES ('system_prompt', $1, 'System Prompt', NOW())
            ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = NOW()
        """, content)
        return True

# ============================================================
# 云端同步 — 对话 CRUD（v4.1）
# ============================================================

async def sync_get_conversations():
    """获取所有对话（不含消息体，侧边栏列表用）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, title, model, project_id, pinned, sort_order, created_at, updated_at
            FROM chat_conversations
            ORDER BY pinned DESC, updated_at DESC
        """)
        return [dict(r) for r in rows]


async def sync_get_conversation(conv_id: str):
    """获取单个对话 + 全部消息"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            "SELECT * FROM chat_conversations WHERE id = $1", conv_id
        )
        if not conv:
            return None
        msgs = await conn.fetch("""
            SELECT * FROM chat_messages
            WHERE conversation_id = $1
            ORDER BY sort_order ASC, time ASC
        """, conv_id)
        result = dict(conv)
        result["messages"] = [dict(m) for m in msgs]
        return result


async def sync_upsert_conversation(conv: dict):
    """创建或更新对话元数据（不含消息）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO chat_conversations (id, title, model, project_id, pinned, sort_order, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                model = EXCLUDED.model,
                project_id = EXCLUDED.project_id,
                pinned = EXCLUDED.pinned,
                sort_order = EXCLUDED.sort_order,
                updated_at = EXCLUDED.updated_at
        """,
            str(conv.get("id", "")),
            conv.get("title", "新对话") or "新对话",
            conv.get("model") or "",
            conv.get("projectId") or conv.get("project_id") or None,
            bool(conv.get("pinned", False)),
            int(conv.get("sortOrder", conv.get("sort_order", 0)) or 0),
            _parse_time(conv.get("createdAt") or conv.get("created_at")),
            _parse_time(conv.get("updatedAt") or conv.get("updated_at")),
        )
    return True


async def sync_delete_conversation(conv_id: str):
    """删除对话（级联删除消息）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM chat_conversations WHERE id = $1", conv_id
        )
        return "DELETE" in result


async def sync_upsert_messages(conv_id: str, messages: list):
    """批量写入/更新消息（全量替换该对话的所有消息）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 先删除该对话的旧消息
            await conn.execute(
                "DELETE FROM chat_messages WHERE conversation_id = $1", conv_id
            )
            # 批量插入新消息
            for idx, msg in enumerate(messages):
                await conn.execute("""
                    INSERT INTO chat_messages (
                        id, conversation_id, role, content, time, model,
                        streaming, error, token_info, thinking, tool_events,
                        memory_result, web_search_results, versions, version_index,
                        attachments, usage, summary, sort_order
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6,
                        $7, $8, $9, $10, $11,
                        $12, $13, $14, $15,
                        $16, $17, $18, $19
                    )
                """,
                    str(msg.get("id") or f"m-{conv_id}-{idx}"),
                    conv_id,
                    msg.get("role") or "user",
                    msg.get("content") or "",
                    _parse_time(msg.get("time")),
                    msg.get("model") or "",
                    False,  # streaming 存盘时永远 false
                    bool(msg.get("error", False)),
                    _to_json(msg.get("tokenInfo") or msg.get("token_info")),
                    msg.get("thinking") if isinstance(msg.get("thinking"), str) else None,
                    _to_json(msg.get("toolEvents") or msg.get("tool_events")),
                    _to_json(msg.get("memoryResult") or msg.get("memory_result")),
                    _to_json(msg.get("webSearchResults") or msg.get("web_search_results")),
                    _to_json(msg.get("versions")),
                    int(msg.get("versionIndex", msg.get("version_index", 0)) or 0),
                    _to_json(msg.get("attachments")),
                    _to_json(msg.get("usage")),
                    msg.get("summary") if isinstance(msg.get("summary"), str) else None,
                    idx,
                )
    return True


# ============================================================
# 云端同步 — 项目 CRUD（v4.1）
# ============================================================

async def sync_get_projects():
    """获取所有项目"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM chat_projects ORDER BY sort_order ASC, created_at ASC
        """)
        return [dict(r) for r in rows]


async def sync_upsert_project(proj: dict):
    """创建或更新项目"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO chat_projects (id, name, icon, description, instructions, files, memory, expanded, sort_order, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                icon = EXCLUDED.icon,
                description = EXCLUDED.description,
                instructions = EXCLUDED.instructions,
                files = EXCLUDED.files,
                memory = EXCLUDED.memory,
                expanded = EXCLUDED.expanded,
                sort_order = EXCLUDED.sort_order,
                updated_at = EXCLUDED.updated_at
        """,
            str(proj.get("id", "")),
            proj.get("name", "新项目") or "新项目",
            proj.get("icon", "📁") or "📁",
            proj.get("description") or "",
            proj.get("instructions") or "",
            _to_json(proj.get("files") or []),
            proj.get("memory") or "",
            bool(proj.get("expanded", False)),
            int(proj.get("sortOrder", proj.get("sort_order", 0)) or 0),
            _parse_time(proj.get("createdAt") or proj.get("created_at")),
            _parse_time(proj.get("updatedAt") or proj.get("updated_at")),
        )
    return True


async def sync_delete_project(proj_id: str):
    """删除项目"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM chat_projects WHERE id = $1", proj_id
        )
        return "DELETE" in result


# ============================================================
# 云端同步 — 批量导入（首次迁移用）（v4.1）
# ============================================================

async def sync_import_all(conversations: list, projects: list):
    """一次性导入所有对话和项目（localStorage → 数据库）"""
    imported_convs = 0
    imported_msgs = 0
    imported_projs = 0
    errors = []

    # 导入项目
    for proj in projects:
        try:
            await sync_upsert_project(proj)
            imported_projs += 1
        except Exception as e:
            errors.append(f"项目 {proj.get('id', '?')}: {e}")
            print(f"⚠️ 项目导入失败: {proj.get('id', '?')} — {e}")

    # 导入对话 + 消息
    for conv in conversations:
        try:
            # 用 .get() 而非 .pop()，避免修改调用方的原始数据
            messages = conv.get("messages", [])
            # 传给 sync_upsert_conversation 时排除 messages 字段
            conv_meta = {k: v for k, v in conv.items() if k != "messages"}
            await sync_upsert_conversation(conv_meta)
            if messages:
                await sync_upsert_messages(conv_meta.get("id", conv.get("id", "")), messages)
                imported_msgs += len(messages)
            imported_convs += 1
        except Exception as e:
            errors.append(f"对话 {conv.get('id', '?')}: {e}")
            print(f"⚠️ 对话导入失败: {conv.get('id', '?')} — {e}")

    return {
        "conversations": imported_convs,
        "messages": imported_msgs,
        "projects": imported_projs,
        "errors": errors,
    }


# ============================================================
# 云端同步 — 辅助函数（v4.1）
# ============================================================

import json as _json
from datetime import datetime as _dt, timezone as _tz

def _to_json(val):
    """将值转为 JSON 字符串（用于 JSONB 列），None 原样返回"""
    if val is None:
        return None
    if isinstance(val, str):
        # 验证是否为合法 JSON，不合法则包装为 JSON 字符串
        try:
            _json.loads(val)
            return val  # 已经是合法 JSON 字符串
        except (ValueError, _json.JSONDecodeError):
            return _json.dumps(val, ensure_ascii=False)  # 包装为 JSON 字符串
    return _json.dumps(val, ensure_ascii=False)


def _parse_time(val):
    """将前端的 ISO 时间字符串转为 datetime 对象"""
    if val is None:
        return _dt.now(_tz.utc)
    if isinstance(val, _dt):
        return val
    try:
        # ISO 格式 "2026-03-28T10:30:00.000Z"
        return _dt.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return _dt.now(_tz.utc)


# ============================================================
# 提醒系统（v4.2）
# ============================================================

async def create_reminder(reminder: dict) -> dict:
    """创建一条提醒"""
    pool = await get_pool()
    r = reminder
    rid = r.get("id", f"rem-{_dt.now(_tz.utc).strftime('%Y%m%d%H%M%S')}-{os.urandom(3).hex()}")
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO reminders (id, title, notes, trigger_time, repeat_type, repeat_config, status, enabled)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title, notes = EXCLUDED.notes,
                trigger_time = EXCLUDED.trigger_time, repeat_type = EXCLUDED.repeat_type,
                repeat_config = EXCLUDED.repeat_config, enabled = EXCLUDED.enabled,
                updated_at = NOW()
        """,
            rid,
            r.get("title", ""),
            r.get("notes", ""),
            _parse_time(r.get("trigger_time")),
            r.get("repeat_type", "once"),
            _to_json(r.get("repeat_config", {})),
            r.get("status", "pending"),
            r.get("enabled", True),
        )
    return {"id": rid, **r}


async def get_reminders(include_completed=False) -> list:
    """获取所有提醒（默认只返回 pending + enabled）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if include_completed:
            rows = await conn.fetch("SELECT * FROM reminders ORDER BY trigger_time ASC")
        else:
            rows = await conn.fetch(
                "SELECT * FROM reminders WHERE enabled = TRUE AND status = 'pending' ORDER BY trigger_time ASC"
            )
    result = []
    for row in rows:
        d = dict(row)
        # datetime → ISO string
        for k in ("trigger_time", "last_fired_at", "created_at", "updated_at"):
            if d.get(k) and isinstance(d[k], _dt):
                d[k] = d[k].isoformat()
        # JSONB → dict
        if isinstance(d.get("repeat_config"), str):
            try:
                d["repeat_config"] = _json.loads(d["repeat_config"])
            except Exception:
                d["repeat_config"] = {}
        result.append(d)
    return result


async def update_reminder(rid: str, updates: dict) -> bool:
    """更新提醒的指定字段"""
    pool = await get_pool()
    allowed = {"title", "notes", "trigger_time", "repeat_type", "repeat_config", "status", "enabled", "last_fired_at"}
    sets = []
    vals = []
    idx = 1
    for k, v in updates.items():
        if k not in allowed:
            continue
        if k == "trigger_time" or k == "last_fired_at":
            v = _parse_time(v)
        elif k == "repeat_config":
            v = _to_json(v)
        sets.append(f"{k} = ${idx}")
        vals.append(v)
        idx += 1
    if not sets:
        return False
    sets.append(f"updated_at = ${idx}")
    vals.append(_dt.now(_tz.utc))
    idx += 1
    vals.append(rid)
    sql = f"UPDATE reminders SET {', '.join(sets)} WHERE id = ${idx}"
    async with pool.acquire() as conn:
        result = await conn.execute(sql, *vals)
    return "UPDATE 1" in result


async def delete_reminder(rid: str) -> bool:
    """删除一条提醒"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM reminders WHERE id = $1", rid)
    return "DELETE 1" in result


async def get_due_reminders() -> list:
    """获取所有到期但还没触发的提醒"""
    pool = await get_pool()
    now = _dt.now(_tz.utc)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM reminders WHERE enabled = TRUE AND status = 'pending' AND trigger_time <= $1 ORDER BY trigger_time ASC",
            now,
        )
    result = []
    for row in rows:
        d = dict(row)
        for k in ("trigger_time", "last_fired_at", "created_at", "updated_at"):
            if d.get(k) and isinstance(d[k], _dt):
                d[k] = d[k].isoformat()
        if isinstance(d.get("repeat_config"), str):
            try:
                d["repeat_config"] = _json.loads(d["repeat_config"])
            except Exception:
                d["repeat_config"] = {}
        result.append(d)
    return result


async def fire_reminder(rid: str, repeat_type: str, repeat_config: dict = None) -> bool:
    """
    触发一条提醒：
    - 一次性(once)：标记为 completed
    - 循环(daily/weekly/custom)：计算下一次触发时间，保持 pending
    """
    pool = await get_pool()
    now = _dt.now(_tz.utc)
    async with pool.acquire() as conn:
        if repeat_type == "once":
            await conn.execute(
                "UPDATE reminders SET status = 'completed', last_fired_at = $1, updated_at = $1 WHERE id = $2",
                now, rid,
            )
        else:
            # 计算下一次触发时间
            row = await conn.fetchrow("SELECT trigger_time FROM reminders WHERE id = $1", rid)
            if not row:
                return False
            current = row["trigger_time"]
            from datetime import timedelta
            if repeat_type == "daily":
                next_time = current + timedelta(days=1)
                # 如果算出来的下次时间还是过去的，跳到最近的将来时间
                while next_time <= now:
                    next_time += timedelta(days=1)
            elif repeat_type == "weekly":
                next_time = current + timedelta(weeks=1)
                while next_time <= now:
                    next_time += timedelta(weeks=1)
            elif repeat_type == "hourly":
                hours = max(1, int((repeat_config or {}).get("hours", 1) or 1))
                next_time = current + timedelta(hours=hours)
                while next_time <= now:
                    next_time += timedelta(hours=hours)
            else:
                # 未知循环类型，当一次性处理
                await conn.execute(
                    "UPDATE reminders SET status = 'completed', last_fired_at = $1, updated_at = $1 WHERE id = $2",
                    now, rid,
                )
                return True
            await conn.execute(
                "UPDATE reminders SET trigger_time = $1, last_fired_at = $2, updated_at = $2 WHERE id = $3",
                next_time, now, rid,
            )
    return True


# ============================================================
# 日历记忆页面 CRUD
# ============================================================

async def save_calendar_page(date_str: str, page_type: str, sections: list, diary: str = "",
                              keywords: list = None, model_used: str = "", summary: str = "", digest: str = ""):
    """保存或更新日历页面（upsert），v5.4 summary / v5.5 digest"""
    from datetime import date as date_cls
    pool = await get_pool()
    d = date_cls.fromisoformat(date_str)
    kw = json.dumps(keywords or [], ensure_ascii=False)
    sec = json.dumps(sections, ensure_ascii=False)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO calendar_pages (date, type, sections, diary, keywords, model_used, summary, digest, updated_at)
            VALUES ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $7, $8, NOW())
            ON CONFLICT (date, type) DO UPDATE SET
                sections = EXCLUDED.sections,
                diary = EXCLUDED.diary,
                keywords = EXCLUDED.keywords,
                model_used = EXCLUDED.model_used,
                summary = EXCLUDED.summary,
                digest = EXCLUDED.digest,
                updated_at = NOW()
            RETURNING id
        """, d, page_type, sec, diary, kw, model_used, summary, digest)
    return row["id"] if row else None


async def get_calendar_page(date_str: str, page_type: str = "day"):
    """读取指定日期的日历页面"""
    from datetime import date as date_cls
    pool = await get_pool()
    d = date_cls.fromisoformat(date_str)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM calendar_pages WHERE date = $1 AND type = $2", d, page_type
        )
    if not row:
        return None
    return dict(row)


async def get_calendar_range(start: str, end: str, page_type: str = None):
    """读取一段时间的日历页面"""
    from datetime import date as date_cls
    pool = await get_pool()
    s = date_cls.fromisoformat(start)
    e = date_cls.fromisoformat(end)
    async with pool.acquire() as conn:
        if page_type:
            rows = await conn.fetch(
                "SELECT * FROM calendar_pages WHERE date >= $1 AND date <= $2 AND type = $3 ORDER BY date ASC",
                s, e, page_type
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM calendar_pages WHERE date >= $1 AND date <= $2 ORDER BY date ASC, type ASC",
                s, e
            )
    return [dict(r) for r in rows]


async def get_calendar_for_injection(lookback_days: int = 365):
    """
    v5.5 俄罗斯套娃式日历层级注入：
    查询最近 N 天内所有日历页面，返回按层级去重后的条目列表。
    已被更高层级覆盖的条目不返回。
    返回 [{type, date, label, digest, summary, keywords}, ...]
    """
    from datetime import date as date_cls, timedelta
    import calendar as cal_mod
    pool = await get_pool()
    today = date_cls.today()
    start = today - timedelta(days=lookback_days)

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT date, type, digest, summary, keywords
            FROM calendar_pages
            WHERE date >= $1
            ORDER BY date ASC
        """, start)

    if not rows:
        return []

    pages = [dict(r) for r in rows]

    # 按类型分组
    by_type = {}
    for p in pages:
        t = p["type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(p)

    # 计算每个高层级页面覆盖的日期范围
    covered_dates = set()

    # 层级优先级：year > quarter > month > week > day
    result = []

    # 年总结：覆盖该年所有日期
    for p in by_type.get("year", []):
        year = p["date"].year
        yr_start = date_cls(year, 1, 1)
        yr_end = date_cls(year, 12, 31)
        for d_offset in range((yr_end - yr_start).days + 1):
            covered_dates.add(yr_start + timedelta(days=d_offset))
        result.append({**p, "label": f"{year}年总结"})

    # 季度总结：覆盖该季度（date 字段存的是季度首日）
    for p in by_type.get("quarter", []):
        q_start = p["date"]
        q_end_month = q_start.month + 2
        q_end_year = q_start.year
        if q_end_month > 12:
            q_end_month -= 12
            q_end_year += 1
        q_end_day = cal_mod.monthrange(q_end_year, q_end_month)[1]
        q_end = date_cls(q_end_year, q_end_month, q_end_day)
        for d_offset in range((q_end - q_start).days + 1):
            d = q_start + timedelta(days=d_offset)
            if d not in covered_dates:
                covered_dates.add(d)
        q_num = (q_start.month - 1) // 3 + 1
        result.append({**p, "label": f"{q_start.year}年Q{q_num}总结"})

    # 月总结：覆盖该月（date 字段存的是月首日）
    for p in by_type.get("month", []):
        m_start = p["date"]
        m_end_day = cal_mod.monthrange(m_start.year, m_start.month)[1]
        m_end = date_cls(m_start.year, m_start.month, m_end_day)
        for d_offset in range((m_end - m_start).days + 1):
            d = m_start + timedelta(days=d_offset)
            if d not in covered_dates:
                covered_dates.add(d)
        result.append({**p, "label": f"{m_start.year}年{m_start.month}月总结"})

    # 周总结：覆盖周一~周日（date 字段存的是周一）
    for p in by_type.get("week", []):
        w_start = p["date"]
        for d_offset in range(7):
            d = w_start + timedelta(days=d_offset)
            if d not in covered_dates:
                covered_dates.add(d)
        w_end = w_start + timedelta(days=6)
        result.append({**p, "label": f"{w_start.strftime('%m/%d')}-{w_end.strftime('%m/%d')}周总结"})

    # 日页面：只加没被覆盖的
    for p in by_type.get("day", []):
        if p["date"] not in covered_dates:
            result.append({**p, "label": f"{p['date'].strftime('%m/%d')}"})

    # 按日期排序
    result.sort(key=lambda x: x["date"])

    return result


async def get_chat_messages_for_date(date_str: str):
    """读取指定日期的所有聊天消息（用于生成日页面）"""
    from datetime import date as date_cls
    pool = await get_pool()
    d = date_cls.fromisoformat(date_str)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT role, content, time, conversation_id
            FROM chat_messages
            WHERE time::date = $1
              AND role IN ('user', 'assistant')
              AND content != ''
            ORDER BY time ASC
        """, d)
    return [dict(r) for r in rows]


# ============================================================
# 评论 CRUD
# ============================================================

async def create_comment(target_type: str, target_id: int, content: str,
                          author: str = "user", parent_id: int = None):
    """创建评论"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO comments (target_type, target_id, parent_id, author, content)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
        """, target_type, target_id, parent_id, author, content)
    return dict(row) if row else None


async def get_comments(target_type: str, target_id: int):
    """读取某个内容的所有评论（含嵌套）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM comments
            WHERE target_type = $1 AND target_id = $2
            ORDER BY created_at ASC
        """, target_type, target_id)
    return [dict(r) for r in rows]


async def delete_comment(comment_id: int):
    """删除评论"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM comments WHERE id = $1", comment_id)
    return "DELETE 1" in result


# ============================================================
# Dream 记忆场景 CRUD
# ============================================================

async def create_mem_scene(title: str, narrative: str, atomic_facts: list = None,
                            foresight: list = None, related_memory_ids: list = None,
                            dream_id: int = None):
    """创建记忆场景"""
    pool = await get_pool()
    af = json.dumps(atomic_facts or [], ensure_ascii=False)
    fs = json.dumps(foresight or [], ensure_ascii=False)
    rm = json.dumps(related_memory_ids or [], ensure_ascii=False)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO mem_scenes (title, narrative, atomic_facts, foresight, related_memory_ids, created_by_dream_id)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6)
            RETURNING id
        """, title, narrative, af, fs, rm, dream_id)
    return row["id"] if row else None


async def update_mem_scene(scene_id: int, **kwargs):
    """更新记忆场景"""
    pool = await get_pool()
    sets = []
    vals = []
    idx = 1
    for key, val in kwargs.items():
        if key in ("title", "narrative", "status"):
            sets.append(f"{key} = ${idx}")
            vals.append(val)
            idx += 1
        elif key in ("atomic_facts", "foresight", "related_memory_ids"):
            sets.append(f"{key} = ${idx}::jsonb")
            vals.append(json.dumps(val, ensure_ascii=False))
            idx += 1
    if not sets:
        return False
    sets.append(f"updated_at = NOW()")
    vals.append(scene_id)
    sql = f"UPDATE mem_scenes SET {', '.join(sets)} WHERE id = ${idx}"
    async with pool.acquire() as conn:
        await conn.execute(sql, *vals)
    return True


async def get_active_scenes():
    """获取所有活跃的记忆场景"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM mem_scenes WHERE status = 'active' ORDER BY updated_at DESC"
        )
    return [dict(r) for r in rows]


async def get_unprocessed_memories():
    """获取未被Dream处理过的碎片记忆"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, title, content, importance, category_id, created_at
            FROM memories
            WHERE dream_processed_at IS NULL
              AND memory_type IN ('fragment', 'daily_digest')
              AND (valid_until IS NULL OR valid_until > NOW())
            ORDER BY created_at ASC
        """)
    return [dict(r) for r in rows]


async def get_permanent_memories():
    """获取长期设定记忆"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, content FROM memories WHERE is_permanent = TRUE AND (valid_until IS NULL OR valid_until > NOW()) ORDER BY created_at ASC"
        )
    return [dict(r) for r in rows]


async def mark_memories_dreamed(memory_ids: list):
    """标记碎片已被Dream处理"""
    if not memory_ids:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE memories SET dream_processed_at = NOW()
            WHERE id = ANY($1::int[])
        """, memory_ids)


async def soft_delete_memories(memory_ids: list):
    """软删除记忆（标记为deleted，不真正删除）"""
    if not memory_ids:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE memories SET memory_type = 'dream_deleted'
            WHERE id = ANY($1::int[])
        """, memory_ids)


async def promote_memory(memory_id: int):
    """升格碎片为长期设定"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE memories SET is_permanent = TRUE WHERE id = $1", memory_id
        )


# ============================================================
# Dream 日志 CRUD
# ============================================================

async def create_dream_log(trigger_type: str = "manual", model: str = ""):
    """创建Dream执行记录，返回ID"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO dream_logs (trigger_type, model_used)
            VALUES ($1, $2)
            RETURNING id
        """, trigger_type, model)
    return row["id"] if row else None


async def update_dream_log(dream_id: int, **kwargs):
    """更新Dream执行记录"""
    pool = await get_pool()
    sets = []
    vals = []
    idx = 1
    for key, val in kwargs.items():
        if key == "structured_result":
            sets.append(f"{key} = ${idx}::jsonb")
            vals.append(json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else val)
        else:
            sets.append(f"{key} = ${idx}")
            vals.append(val)
        idx += 1
    if not sets:
        return
    vals.append(dream_id)
    sql = f"UPDATE dream_logs SET {', '.join(sets)} WHERE id = ${idx}"
    async with pool.acquire() as conn:
        await conn.execute(sql, *vals)


async def get_dream_status():
    """获取当前Dream状态"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 只认 4 小时内的 running 状态，超时视为崩溃
        running = await conn.fetchrow(
            "SELECT * FROM dream_logs WHERE status = 'running' AND started_at > NOW() - INTERVAL '4 hours' ORDER BY started_at DESC LIMIT 1"
        )
        # 自动清理超时的 running 记录
        await conn.execute("""
            UPDATE dream_logs SET status = 'error', finished_at = NOW(),
                dream_narrative = COALESCE(dream_narrative, '') || '\n[超时自动标记为失败]'
            WHERE status = 'running' AND started_at <= NOW() - INTERVAL '4 hours'
        """)
        last = await conn.fetchrow(
            "SELECT * FROM dream_logs WHERE status IN ('completed', 'interrupted') ORDER BY started_at DESC LIMIT 1"
        )
    return {
        "is_running": running is not None,
        "current": dict(running) if running else None,
        "last_completed": dict(last) if last else None,
    }


async def get_dream_history(limit: int = 10):
    """获取Dream执行历史"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM dream_logs ORDER BY started_at DESC LIMIT $1", limit
        )
    return [dict(r) for r in rows]


# ============================================================
# 记忆热度报告（v5.2）
# ============================================================

async def get_memory_heat_report(limit: int = 50):
    """
    获取记忆热度报告 — 按热度排序，显示每条记忆的热度和召回数据
    用于 /debug/memory-heat 接口
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, COALESCE(title, '') as title, content, importance,
                   COALESCE(emotional_weight, 0) as emotional_weight,
                   COALESCE(access_count, 0) as access_count,
                   COALESCE(access_query_hashes, '[]'::jsonb) as access_query_hashes,
                   COALESCE(is_permanent, false) as is_permanent,
                   COALESCE(memory_type, 'fragment') as memory_type,
                   created_at, last_accessed, valid_until
            FROM memories
            WHERE COALESCE(memory_type, 'fragment') NOT IN ('digested', 'dream_deleted')
            ORDER BY created_at DESC
            LIMIT $1
        """, limit)
    
    results = []
    heat_params = await get_heat_params()
    for row in rows:
        heat = calculate_heat(row, heat_params)
        query_hashes = row.get("access_query_hashes") or []
        if isinstance(query_hashes, str):
            try:
                query_hashes = json.loads(query_hashes)
            except Exception:
                query_hashes = []
        
        results.append({
            "id": row["id"],
            "title": row["title"],
            "content": row["content"][:100] + ("..." if len(row["content"]) > 100 else ""),
            "importance": row["importance"],
            "emotional_weight": row["emotional_weight"],
            "access_count": row["access_count"],
            "query_diversity": len(set(query_hashes)),
            "is_permanent": row["is_permanent"],
            "memory_type": row["memory_type"],
            "heat": round(heat, 4),
            "heat_level": "🔥高" if heat > heat_params["threshold_high"] else ("🌡中" if heat > heat_params["threshold_medium"] else "🧊低"),
            "created_at": str(row["created_at"]),
            "last_accessed": str(row["last_accessed"]) if row["last_accessed"] else None,
            "valid_until": str(row["valid_until"]) if row["valid_until"] else None,
        })
    
    # 按热度排序
    results.sort(key=lambda x: x["heat"], reverse=True)
    return results


# ============================================================
# v5.3：时间有效期 + 矛盾检测
# ============================================================

async def invalidate_memory(memory_id: int, reason: str = ""):
    """
    标记记忆失效（设置 valid_until = NOW()）
    不删除数据，仅标记——搜索时会自动过滤，Dream 查历史仍可见
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE memories SET valid_until = NOW() WHERE id = $1 AND valid_until IS NULL",
            memory_id,
        )
    reason_tag = f" | {reason}" if reason else ""
    print(f"⏰ 记忆 #{memory_id} 已标记失效{reason_tag}")
    return result == "UPDATE 1"


async def create_memory_edge(from_id: int, from_type: str, to_id: int, to_type: str, edge_type: str, reason: str = "", created_by: str = "system", validate_ids: bool = False):
    """
    创建记忆关系边（通用辅助函数）
    - 同一对 (from_id, to_id, edge_type) 不重复创建
    - validate_ids=True 时校验 ID 是否存在（Dream 调用时开启）
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # 可选：校验引用的 ID 是否存在，防止垃圾 edge
        if validate_ids:
            from_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM memories WHERE id = $1)" if from_type == "memory"
                else "SELECT EXISTS(SELECT 1 FROM mem_scenes WHERE id = $1)",
                from_id
            )
            to_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM memories WHERE id = $1)" if to_type == "memory"
                else "SELECT EXISTS(SELECT 1 FROM mem_scenes WHERE id = $1)",
                to_id
            )
            if not from_exists or not to_exists:
                print(f"⚠️ 关系标注跳过：引用的 ID 不存在 (from={from_id} exists={from_exists}, to={to_id} exists={to_exists})")
                return False

        # 去重：同一对不重复创建
        exists = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM memory_edges
                WHERE from_id = $1 AND to_id = $2 AND edge_type = $3
            )
        """, from_id, to_id, edge_type)
        if exists:
            print(f"🔗 关系已存在，跳过: #{from_id} --{edge_type}--> #{to_id}")
            return False

        await conn.execute("""
            INSERT INTO memory_edges (from_id, from_type, to_id, to_type, edge_type, reason, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, from_id, from_type, to_id, to_type, edge_type, reason, created_by)
    print(f"🔗 关系标注: #{from_id}({from_type}) --{edge_type}--> #{to_id}({to_type}) | {reason[:60]}")
    return True


def detect_contradictions(new_title: str, new_content: str, similar_results: list, title_threshold: float = 0.7) -> list:
    """
    从搜索结果中检测疑似矛盾的旧记忆（纯计算，不调 API）
    
    判断逻辑（v5.3）：
    1. 标题相似度 > title_threshold（同一主题）
    2. 内容相似度在 0.4-0.85 之间（相关但不同——>0.85 是重复不是矛盾）
    3. 新记忆比旧记忆更新（自然成立，因为新记忆还没存入库）
    
    参数：
        new_title: 新记忆的标题
        new_content: 新记忆的内容
        similar_results: check_memory_duplicate 返回的搜索结果（复用，不重复调 embedding）
        title_threshold: 标题相似度阈值，默认 0.7（Code 建议从 0.85 降低）
    
    返回：疑似矛盾的旧记忆 ID 列表
    """
    if not new_title or not similar_results:
        return []
    
    contradicted_ids = []
    new_title_chars = set(c for c in new_title if '\u4e00' <= c <= '\u9fff' or c.isalpha())
    
    for mem in similar_results:
        old_title = mem.get("title", "")
        if not old_title:
            continue
        
        # v5.3 保护：手动录入的记忆置信度最高，不被自动矛盾检测标失效
        # 只有用户手动编辑或 Dream 裁决才能改变手动记忆
        if mem.get("source") == "user_explicit":
            continue
        
        # v5.3 保护：锁定记忆也不被自动标失效
        if mem.get("is_permanent"):
            continue
        
        # 标题相似度：用字符重叠度（和去重逻辑一致的简单方式）
        old_title_chars = set(c for c in old_title if '\u4e00' <= c <= '\u9fff' or c.isalpha())
        if len(new_title_chars) < 2 or len(old_title_chars) < 2:
            continue
        
        overlap = new_title_chars & old_title_chars
        title_sim = len(overlap) / max(len(new_title_chars), len(old_title_chars))
        
        if title_sim < title_threshold:
            continue
        
        # 内容相似度：用 search_memories 已经算好的 similarity
        content_sim = mem.get("similarity", 0)
        
        # 相似度在 0.4-0.85 之间 = 相关但不同（疑似矛盾/更新）
        # > 0.85 已经被去重检测处理了，< 0.4 说明不是同一件事
        if 0.4 <= content_sim <= 0.85:
            contradicted_ids.append(mem["id"])
            print(f"   ⚡ 疑似矛盾: 新[{new_title}] vs 旧#{mem['id']}[{old_title}]（标题sim={title_sim:.2f}, 内容sim={content_sim:.2f}）")
    
    return contradicted_ids


# ============================================================
# v5.4：后台任务供应商路由
# ============================================================

async def resolve_model_endpoint(model_id: str) -> tuple:
    """
    为后台任务（记忆提取 / Dream / 每日整理）解析模型的 API 端点。
    
    解析顺序：
    1. 供应商数据库（模型在某个 provider 下注册了）
    2. 环境变量降级（MEMORY_API_BASE_URL / API_BASE_URL + 对应 key）
    
    返回：(api_url, api_key) — api_url 以 /chat/completions 结尾
    """
    if model_id:
        try:
            provider_info = await resolve_provider_for_model(model_id)
            if provider_info:
                base = provider_info["api_base_url"].rstrip("/")
                api_url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
                api_key = provider_info["api_key"]
                print(f"🔀 后台任务路由到 [{provider_info['provider_name']}]: {model_id}")
                return api_url, api_key
        except Exception as e:
            print(f"⚠️ 供应商路由查询失败，降级到环境变量: {e}")

    # 降级：环境变量
    _raw = os.getenv("MEMORY_API_BASE_URL", "") or os.getenv("API_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
    api_url = _raw if _raw.rstrip("/").endswith("/chat/completions") else f"{_raw.rstrip('/')}/chat/completions"
    api_key = os.getenv("MEMORY_API_KEY", "") or os.getenv("API_KEY", "")
    return api_url, api_key
