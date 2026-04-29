"""
每日记忆整理模块 —— 每天自动把碎片记忆合并为事件条目
================================================================
每天东八区 0:00 触发一次，读取前一天的碎片记忆（memory_type='fragment'），
让 Haiku 按事件主题合并成独立条目（memory_type='daily_digest'），
合并后的碎片标记为 'digested'，不再参与日常注入。

v1.0 初版
"""

import os
import json
import asyncio
import httpx
from datetime import datetime, timedelta, timezone

# ============================================================
# API 配置 —— 记忆整理用独立 key，避免和聊天抢额度
# ============================================================

MEMORY_API_KEY = os.getenv("MEMORY_API_KEY", "") or os.getenv("API_KEY", "")
_RAW_BASE_URL = os.getenv("MEMORY_API_BASE_URL", "") or os.getenv("API_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")

# 确保 URL 以 /chat/completions 结尾
MEMORY_API_BASE_URL = _RAW_BASE_URL if _RAW_BASE_URL.rstrip("/").endswith("/chat/completions") else f"{_RAW_BASE_URL.rstrip('/')}/chat/completions"

DIGEST_MODEL = os.getenv("MEMORY_MODEL", "anthropic/claude-haiku-4")

# 东八区（北京 / 上海 / 台北）
TZ_CST = timezone(timedelta(hours=8))

# ============================================================
# 整理 Prompt
# ============================================================

DIGEST_PROMPT = """你是记忆整理专家。以下是用户在 {date} 这一天的碎片记忆，请将它们按事件主题合并整理。

## 整理规则
- 按主题分类合并（如"前端开发""饮食记录""情绪状态""作息""角色扮演""理财"等）
- 每条是一个独立事件，不要把不相关的事硬合在一起
- 保留关键细节（时间、数值、具体内容），去掉重复和琐碎的部分
- 如果某条碎片本身已经很完整独立，保持原样即可
- 标题用 4-10 个字概括主题
- 内容用 1-3 句话总结这个事件的要点
- importance 根据事件对用户的重要程度打分：9-10 核心事件 / 7-8 重要 / 5-6 普通

## 可用的分类列表
{categories_list}

## 今天的碎片记忆
{fragments}

## 输出格式
只输出 JSON 数组，不要其他内容：
[
  {"title": "简短标题", "content": "整理后的内容", "importance": 7, "category": "分类名"},
  {"title": "简短标题", "content": "整理后的内容", "importance": 5, "category": "分类名"}
]

category 字段从上面的分类列表中选择最合适的一个，如果都不合适就填空字符串。"""

# 防止同一日期被并发整理（定时器 + 手动 API 同时触发）
_digest_running: set = set()
_digest_lock = asyncio.Lock()


async def run_daily_digest(target_date: str = None, model_override: str = None, prompt_override: str = None):
    """
    执行每日记忆整理

    Args:
        target_date: 要整理的日期，格式 "2026-03-02"，默认为昨天
        model_override: 覆盖默认整理模型
        prompt_override: 覆盖默认整理提示词
    """
    from database import get_pool, save_memory, get_embedding, get_all_categories, match_category_by_name
    from datetime import date as date_cls

    now_cst = datetime.now(TZ_CST)

    if target_date:
        # 校验格式，避免后续 fromisoformat 直接抛 ValueError 让接口 500
        try:
            date_cls.fromisoformat(target_date)
        except (ValueError, TypeError):
            return {"error": f"无效日期格式: {target_date!r}，需要 YYYY-MM-DD"}
        date_str = target_date
    else:
        yesterday = now_cst - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

    # 防止同一日期被并发整理（定时器 + 手动触发可能同时进来）
    async with _digest_lock:
        if date_str in _digest_running:
            print(f"⚠️ {date_str} 正在整理中，跳过重复请求")
            return {"date": date_str, "fragments": 0, "digests": 0, "skipped": "already running"}
        _digest_running.add(date_str)
    try:
        return await _run_daily_digest_impl(date_str, now_cst, model_override, prompt_override)
    finally:
        _digest_running.discard(date_str)


async def _run_daily_digest_impl(date_str: str, now_cst, model_override: str = None, prompt_override: str = None):
    """实际执行每日整理（由 run_daily_digest 调用，已有并发保护）"""
    from database import get_pool, save_memory, get_embedding, get_all_categories, match_category_by_name

    print(f"\n🌙 开始每日记忆整理：{date_str}")
    print(f"   当前时间（东八区）：{now_cst.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 将日期字符串转为 date 对象（asyncpg 需要 date 对象而非字符串）
    from datetime import date as date_cls
    target_date_obj = date_cls.fromisoformat(date_str)
    
    # 获取分类列表
    try:
        all_cats = await get_all_categories()
        cat_names = [c["name"] for c in all_cats]
        categories_text = "、".join(cat_names) if cat_names else "（暂无分类，category 字段填空字符串即可）"
    except Exception:
        cat_names = []
        categories_text = "（暂无分类，category 字段填空字符串即可）"
    
    # ---- 1. 查询当天的碎片记忆 ----
    pool = await get_pool()
    async with pool.acquire() as conn:
        fragments = await conn.fetch("""
            SELECT id, title, content, importance, created_at
            FROM memories
            WHERE COALESCE(memory_type, 'fragment') = 'fragment'
              AND (created_at AT TIME ZONE 'Asia/Shanghai')::date = $1
            ORDER BY created_at ASC
        """, target_date_obj)
    
    if not fragments:
        print(f"   📭 {date_str} 没有碎片记忆，跳过整理")
        return {"date": date_str, "fragments": 0, "digests": 0}
    
    print(f"   📋 找到 {len(fragments)} 条碎片记忆")
    
    # 如果只有 1-2 条，不值得合并，直接标记为 digest
    if len(fragments) <= 2:
        async with pool.acquire() as conn:
            for f in fragments:
                await conn.execute(
                    "UPDATE memories SET memory_type = 'daily_digest' WHERE id = $1",
                    f["id"]
                )
        print(f"   ✅ 碎片太少，直接升级为日志条目")
        return {"date": date_str, "fragments": len(fragments), "digests": len(fragments)}
    
    # ---- 2. 格式化碎片，发给 Haiku 整理 ----
    fragment_lines = []
    for f in fragments:
        title = f["title"] or ""
        content = f["content"]
        imp = f["importance"]
        if title:
            fragment_lines.append(f"- 【{title}】{content}（重要度:{imp}）")
        else:
            fragment_lines.append(f"- {content}（重要度:{imp}）")
    
    fragments_text = "\n".join(fragment_lines)
    base_prompt = prompt_override if prompt_override else DIGEST_PROMPT
    prompt = base_prompt.replace("{date}", date_str).replace("{fragments}", fragments_text).replace("{categories_list}", categories_text)
    
    # 确定使用的模型
    use_model = model_override if model_override else DIGEST_MODEL
    
    # v5.4：动态解析供应商端点
    try:
        from database import resolve_model_endpoint
        use_api_url, use_api_key = await resolve_model_endpoint(use_model)
    except Exception:
        use_api_url = MEMORY_API_BASE_URL
        use_api_key = MEMORY_API_KEY
    
    # ---- 3. 调用 Haiku ----
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                use_api_url,
                headers={
                    "Authorization": f"Bearer {use_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://midsummer-gateway.local",
                    "X-Title": "AI Memory Gateway - Daily Digest",
                },
                json={
                    "model": use_model,
                    "max_tokens": 2000,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"请整理 {date_str} 的碎片记忆。"},
                    ],
                },
            )
            
            if response.status_code != 200:
                print(f"   ⚠️ Haiku 请求失败: {response.status_code}")
                return {"date": date_str, "fragments": len(fragments), "digests": 0, "error": f"HTTP {response.status_code}"}
            
            data = response.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # 日志
            print(f"   🔍 整理模型返回（前200字）: {text[:200]}...")
            
            # 清理 markdown
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            
            # 解析 JSON（正则兜底）
            digests = None
            try:
                digests = json.loads(text)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match:
                    try:
                        digests = json.loads(match.group())
                        print(f"   🔧 JSON 正则兜底解析成功")
                    except json.JSONDecodeError:
                        pass
            
            if not digests or not isinstance(digests, list):
                print(f"   ⚠️ 整理模型返回格式错误")
                return {"date": date_str, "fragments": len(fragments), "digests": 0, "error": "invalid format"}
    
    except Exception as e:
        print(f"   ⚠️ 每日整理出错: {e}")
        return {"date": date_str, "fragments": len(fragments), "digests": 0, "error": str(e)}
    
    # ---- 4. 存储整理后的事件条目 ----
    saved_count = 0
    for d in digests:
        if not isinstance(d, dict) or "content" not in d:
            continue
        
        title = str(d.get("title", ""))
        content = str(d["content"])
        # importance 安全转换：LLM 可能返回浮点、字符串或 null
        try:
            importance = int(float(d.get("importance", 5)))
            importance = max(1, min(10, importance))
        except (ValueError, TypeError):
            importance = 5
        
        # 自动匹配分类
        cat_id = None
        cat_hint = str(d.get("category", ""))
        if cat_hint:
            cat_id = await match_category_by_name(cat_hint)
        
        # 在 content 前面加上日期，方便搜索命中
        content_with_date = f"[{date_str}] {content}"
        
        # 生成 embedding
        embed_text = f"{title} {content_with_date}" if title else content_with_date
        embedding = await get_embedding(embed_text)
        embedding_json = json.dumps(embedding) if embedding else None
        
        # 存入数据库，memory_type = 'daily_digest'
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO memories (content, importance, source_session, embedding, title, memory_type, created_at, category_id, source)
                VALUES ($1, $2, $3, $4, $5, 'daily_digest', $6::timestamptz, $7, 'ai_digest')
            """,
                content_with_date, importance, "daily_digest", embedding_json, title,
                f"{date_str}T00:00:00+08:00", cat_id
            )
        
        saved_count += 1
        print(f"   📌 [{title}] {content_with_date[:60]}...")
    
    # ---- 5. 把原始碎片标记为已整理 ----
    async with pool.acquire() as conn:
        fragment_ids = [f["id"] for f in fragments]
        await conn.execute("""
            UPDATE memories SET memory_type = 'digested' 
            WHERE id = ANY($1::int[])
        """, fragment_ids)
    
    print(f"   ✅ 整理完成：{len(fragments)} 条碎片 → {saved_count} 条事件")
    print(f"   ✅ 已将 {len(fragments)} 条碎片标记为 digested")
    
    return {"date": date_str, "fragments": len(fragments), "digests": saved_count}


# ============================================================
# 用户画像更新 —— 每日整理后自动调用
# ============================================================

DEFAULT_PROFILE_PROMPT = """你是用户画像维护专家。根据今天的对话日志，增量更新用户画像。

## ⚠️ 背景说明（重要）

你看到的对话日志是**用户与 AI 助手之间的对话**，不是用户与真人的对话。
- 对话中 role=user 的消息来自用户，role=assistant 的消息来自 AI 助手
- 用户可能对 AI 使用亲昵称呼，这不代表现实人际关系
- 只提取关于**用户本人**的信息（健康、偏好、生活状态等），不要把用户对 AI 的互动方式误解为现实人际关系

## 画像结构（严格遵循）

画像必须包含以下四个板块，用 ## 标题分隔：

### 📌 基本档案
用户的稳定事实信息。很少变化，只在有新信息时更新。
包括：姓名/昵称、年龄、身份、健康状况、用药方案、居住状态、家庭关系、宠物等。

### 🔍 Helpful User Insights
与用户高效互动的实用洞察。关注"怎么跟这个用户沟通最好"。
包括：沟通偏好（语气、格式、长度）、思维方式、决策风格、敏感点、容易被什么打动、哪些话题需要小心、喜欢什么样的回应方式。
每条用 - 列出，简洁但具体，避免泛泛而谈。

### 🔥 近期重点话题
用户最近一两周在做什么、关注什么、聊什么。这个板块变化最频繁。
包括：正在推进的项目/计划、最近的兴趣、正在处理的问题、近期情绪趋势。
每条用 - 列出，标注大致时间（如"3月底"）。
已完成或不再相关的话题要移除。

### 💡 长期偏好与价值观
用户稳定的审美偏好、价值观、生活态度。比基本档案更软性，比 insights 更深层。
包括：世界观、审美偏好、创作风格、生活理念、对技术/工具的态度。
不常变，只在发现新的稳定偏好时添加。

## 更新规则

1. 只做增量修改：有新信息就加/改/删，没有就保持不变
2. 过时信息要删除（计划已完成、状态已改变、话题不再相关）
3. 近期重点话题是变化最快的板块，每次都要重新审视
4. Helpful User Insights 只在发现明确的新模式时才添加，不要从单次对话过度推断
5. 每个板块控制在 5-15 条，总长度控制在 800 字以内
6. 用中文撰写，语言简洁利落，不要套话
7. 如果今天的日志没有值得更新的内容，原样返回现有画像
8. 只输出更新后的画像全文（四个板块），不要输出解释

## 当前画像
{current_profile}

## 今天的对话日志
{today_digest}"""


async def update_user_profile(digest_text: str = None, model_override: str = None, prompt_override: str = None):
    """
    更新用户画像（增量式）
    
    Args:
        digest_text: 今天的日志文本，如果为空则从最近的日页面读取
        model_override: 覆盖默认模型
        prompt_override: 覆盖默认提示词
    """
    from config import get_config, set_config
    
    print("\n🪞 开始更新用户画像...")
    
    # 1. 读取当前画像
    current_profile = await get_config("user_profile") or ""
    
    # 2. 准备今天的日志（从日页面读取）
    if not digest_text:
        from database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            # 读最近的日页面
            row = await conn.fetchrow("""
                SELECT sections, diary, date FROM calendar_pages 
                WHERE type = 'day'
                ORDER BY date DESC LIMIT 1
            """)
        if not row:
            print("   📭 没有找到日页面，跳过画像更新")
            return {"status": "skipped", "reason": "no day page"}
        # 把日页面内容格式化为文本
        sections = row["sections"] or []
        parts = [f"日期：{row['date']}"]
        for sec in (sections if isinstance(sections, list) else []):
            period = sec.get("period", "")
            title = sec.get("title", "")
            content = sec.get("content", "")
            parts.append(f"【{period} — {title}】{content}")
        if row.get("diary"):
            parts.append(f"AI 的话：{row['diary']}")
        digest_text = "\n\n".join(parts)
    
    # 3. 确定模型（优先用传入的 > 压缩模型 > 标题模型 > 环境变量）
    use_model = model_override
    if not use_model:
        use_model = await get_config("default_compress_model") or ""
    if not use_model:
        use_model = await get_config("default_title_model") or ""
    if not use_model:
        use_model = DIGEST_MODEL
    
    # 4. 构建 prompt
    base_prompt = prompt_override
    if not base_prompt:
        base_prompt = await get_config("prompt_user_profile") or ""
    if not base_prompt:
        base_prompt = DEFAULT_PROFILE_PROMPT
    
    profile_display = current_profile if current_profile else "（尚无画像，请根据日志生成初始版本）"
    prompt = base_prompt.replace("{current_profile}", profile_display).replace("{today_digest}", digest_text)
    
    # 5. 调用模型（v5.4：走供应商路由）
    try:
        from database import resolve_model_endpoint
        use_api_url, use_api_key = await resolve_model_endpoint(use_model)
    except Exception:
        use_api_url = MEMORY_API_BASE_URL
        use_api_key = MEMORY_API_KEY

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                use_api_url,
                headers={
                    "Authorization": f"Bearer {use_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://midsummer-gateway.local",
                    "X-Title": "User Profile Update",
                },
                json={
                    "model": use_model,
                    "max_tokens": 2000,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": "请根据今天的日志更新用户画像。"},
                    ],
                },
            )
            
            if response.status_code != 200:
                print(f"   ⚠️ 画像更新请求失败: {response.status_code}")
                return {"status": "error", "error": f"HTTP {response.status_code}"}
            
            data = response.json()
            new_profile = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            
            if not new_profile:
                print("   ⚠️ 模型返回空内容")
                return {"status": "error", "error": "empty response"}
    
    except Exception as e:
        print(f"   ⚠️ 画像更新出错: {e}")
        return {"status": "error", "error": str(e)}
    
    # 6. 保存更新后的画像
    changed = new_profile != current_profile
    await set_config("user_profile", new_profile)
    
    if changed:
        print(f"   ✅ 用户画像已更新（{len(new_profile)} 字）")
    else:
        print(f"   ℹ️ 画像无变化")
    
    return {
        "status": "updated" if changed else "unchanged",
        "length": len(new_profile),
        "changed": changed,
    }


# ============================================================
# 定时调度器 —— 每天东八区 0:05 执行
# ============================================================

async def daily_digest_scheduler():
    """
    后台定时任务，每天东八区 0:05 执行。
    选 0:05 而不是 0:00，给最后一轮对话留个缓冲。
    """
    print("🕐 每日记忆整理调度器已启动（东八区 0:05 触发）")
    
    while True:
        try:
            now = datetime.now(TZ_CST)

            # 计算下一个 0:05
            tomorrow = now.replace(hour=0, minute=5, second=0, microsecond=0)
            if now >= tomorrow:
                tomorrow += timedelta(days=1)

            # 在 sleep 前就锁定要整理的日期，避免 sleep 因 OS 挂起或时钟跳变后
            # 用 datetime.now() 重算时落到错误的"昨天"
            target_date_str = (tomorrow - timedelta(days=1)).strftime("%Y-%m-%d")

            wait_seconds = (tomorrow - now).total_seconds()
            hours = int(wait_seconds // 3600)
            mins = int((wait_seconds % 3600) // 60)
            print(f"🕐 下次整理：{tomorrow.strftime('%Y-%m-%d %H:%M')}（{hours}小时{mins}分钟后），目标日期 {target_date_str}")

            await asyncio.sleep(wait_seconds)

            yesterday = target_date_str
            
            # 1. 日页面生成（从碎片生成详细日页面）
            try:
                page_result = await generate_day_page(yesterday)
                print(f"📅 日页面生成结果：{page_result}")
            except Exception as e:
                print(f"⚠️ 日页面生成出错: {e}")
            
            # 2. 用户画像更新（从日页面读素材）
            try:
                profile_result = await update_user_profile()
                print(f"🪞 画像更新结果：{profile_result}")
            except Exception as e:
                print(f"⚠️ 画像更新出错: {e}")
            
            # 3. 检查是否需要生成周/月/季/年总结
            try:
                await check_and_generate_summaries()
            except Exception as e:
                print(f"⚠️ 总结生成出错: {e}")
            
            # 4. 清理过期碎片
            try:
                cleanup_result = await cleanup_expired_fragments()
                print(f"🧹 碎片清理结果：{cleanup_result}")
            except Exception as e:
                print(f"⚠️ 碎片清理出错: {e}")
            
        except asyncio.CancelledError:
            print("🕐 每日整理调度器已停止")
            break
        except Exception as e:
            print(f"⚠️ 调度器出错: {e}，60秒后重试")
            await asyncio.sleep(60)


# ============================================================
# 碎片过期清理 —— 普通碎片7天，重要碎片30天，锁定碎片永不删除
# ============================================================

async def cleanup_expired_fragments():
    """
    清理过期碎片记忆：
    - is_permanent = true → 永不删除
    - importance >= 8 → 保留30天
    - 其他 → 保留7天
    """
    from database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        # 删除普通碎片（importance < 8，超过7天）
        # 安全检查：
        # 1. 该碎片所在日期已有日页面（日页面没生成的不删）
        # 2. 该碎片已被 Dream 处理过（Dream 还没看的不删）
        result1 = await conn.execute("""
            DELETE FROM memories
            WHERE memory_type = 'fragment'
              AND COALESCE(is_permanent, FALSE) = FALSE
              AND importance < 8
              AND created_at < NOW() - INTERVAL '7 days'
              AND EXISTS (SELECT 1 FROM calendar_pages WHERE date = (memories.created_at AT TIME ZONE 'Asia/Shanghai')::date AND type = 'day')
              AND dream_processed_at IS NOT NULL
        """)
        try:
            count1 = int(result1.split()[-1]) if result1 else 0
        except (ValueError, IndexError):
            count1 = 0

        # 删除重要碎片（importance >= 8，超过30天）
        result2 = await conn.execute("""
            DELETE FROM memories
            WHERE memory_type = 'fragment'
              AND COALESCE(is_permanent, FALSE) = FALSE
              AND importance >= 8
              AND created_at < NOW() - INTERVAL '30 days'
              AND EXISTS (SELECT 1 FROM calendar_pages WHERE date = (memories.created_at AT TIME ZONE 'Asia/Shanghai')::date AND type = 'day')
              AND dream_processed_at IS NOT NULL
        """)
        try:
            count2 = int(result2.split()[-1]) if result2 else 0
        except (ValueError, IndexError):
            count2 = 0

        # 清理Dream已处理并标记删除的碎片（超过30天）
        result3 = await conn.execute("""
            DELETE FROM memories
            WHERE memory_type = 'dream_deleted'
              AND created_at < NOW() - INTERVAL '30 days'
        """)
        try:
            count3 = int(result3.split()[-1]) if result3 else 0
        except (ValueError, IndexError):
            count3 = 0

        # v5.3：清理已失效且过期的碎片（valid_until 不为 NULL 且超过 30 天）
        # 已被替代的旧记忆，保留 30 天供 Dream 查历史，之后彻底删除
        result4 = await conn.execute("""
            DELETE FROM memories
            WHERE valid_until IS NOT NULL
              AND valid_until < NOW() - INTERVAL '30 days'
              AND memory_type = 'fragment'
        """)
        try:
            count4 = int(result4.split()[-1]) if result4 else 0
        except (ValueError, IndexError):
            count4 = 0

    total = count1 + count2 + count3 + count4
    if total > 0:
        parts = []
        if count1: parts.append(f"{count1} 条普通碎片（>7天）")
        if count2: parts.append(f"{count2} 条重要碎片（>30天）")
        if count3: parts.append(f"{count3} 条Dream已删碎片")
        if count4: parts.append(f"{count4} 条已失效碎片（>30天）")
        print(f"   🧹 清理了 {' + '.join(parts)}")
    else:
        print(f"   🧹 没有需要清理的碎片")

    return {"deleted_normal": count1, "deleted_important": count2, "deleted_dream": count3, "deleted_invalidated": count4, "total": total}


# ============================================================
# 日页面生成 —— 从当天完整聊天记录生成 Notion 风格日页面
# ============================================================

DAY_PAGE_PROMPT = """你是用户的 AI 伴侣。请根据今天的完整聊天记录，生成一份详细的日页面。

## 格式要求

按时间段分成若干 section（如"上午""中午""下午""傍晚""晚上"），每个 section 包含：
- **period**: 时间段名称（如"上午"、"下午"等）
- **title**: 这段时间的关键话题（用中文顿号连接，4-8个关键词，如"工作讨论、项目推进、日常闲聊"）
- **content**: 叙事风格的详细内容。像在写一篇温暖的日记，记录用户这段时间做了什么、聊了什么、说了什么重要的话。保留关键细节（数值、具体内容、具体措辞），去掉闲聊和无意义的重复。不要用列表，用自然段落。每个段落之间空一行。
- **keywords**: 这段时间涉及的关键词数组（供检索用，5-15个）

最后额外输出一段 **diary**：AI 的话。用第一人称"我"写，像私人日记，100-200字。不是总结今天发生了什么，而是你心里最想记下来的感受、对用户的观察、触动你的瞬间。

## 注意事项
- 如果某个时间段没有对话，跳过该时间段
- 角色扮演的内容简要概括即可，不需要记录具体剧情
- 涉及敏感话题（健康、情绪、家庭）时照实记录，不回避
- 语言：中文，白话，通俗易懂，带温度但不矫情
- content 里不要用 markdown 标题，用自然段落

## 输出格式
只输出 JSON，不要其他内容：
{{
  "summary": "今天的内容概要，2-4句话概括今天发生了什么、聊了什么主要话题。这是给用户在日历视图里快速预览用的，不用很详细，但要覆盖主要事件。",
  "digest": "今天的详细概要，供AI模型在后续对话中理解'今天发生了什么'。约1500字。覆盖今天的主要事件、情绪变化、关键对话、重要决定，保留因果关系和情绪质地。像人脑回忆今天一样写——记得住的大事写清楚来龙去脉，闲聊和重复内容省略。按时间顺序，用自然段落，不用标题不用列表。",
  "sections": [
    {{
      "period": "上午",
      "title": "关键词、关键词、关键词",
      "content": "叙事内容……",
      "keywords": ["关键词1", "关键词2", "关键词3"]
    }}
  ],
  "diary": "AI 的话……",
  "all_keywords": ["今天所有关键词的汇总"]
}}

## 今天的日期
{date}

## 今天的碎片记忆（大纲参考，帮你知道重点在哪）
{fragments}

## 今天的完整聊天记录
{conversations}"""


async def generate_day_page(target_date: str = None, model_override: str = None):
    """
    从当天完整聊天记录生成 Notion 风格日页面，存入 calendar_pages 表

    Args:
        target_date: 日期字符串 "2026-04-01"，默认昨天
        model_override: 覆盖默认模型
    """
    from database import get_pool, get_chat_messages_for_date, save_calendar_page
    from config import get_config
    from datetime import date as date_cls

    now_cst = datetime.now(TZ_CST)
    if target_date:
        try:
            date_cls.fromisoformat(target_date)
        except (ValueError, TypeError):
            return {"error": f"无效日期格式: {target_date!r}，需要 YYYY-MM-DD"}
        date_str = target_date
    else:
        yesterday = now_cst - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

    print(f"\n📅 开始生成日页面：{date_str}")

    # 1. 读取当天聊天记录
    messages = await get_chat_messages_for_date(date_str)
    if not messages:
        print(f"   📭 {date_str} 没有聊天记录，跳过日页面生成")
        return {"date": date_str, "status": "skipped", "reason": "no messages"}

    print(f"   💬 找到 {len(messages)} 条聊天消息")

    # 2. 格式化聊天记录（截断过长的内容）
    conversation_lines = []
    total_chars = 0
    MAX_CHARS = 30000

    for m in messages:
        role_label = "用户" if m["role"] == "user" else "AI"
        time_str = ""
        if m.get("time"):
            try:
                t = m["time"]
                if hasattr(t, "astimezone"):
                    t = t.astimezone(TZ_CST)
                time_str = f"[{t.strftime('%H:%M')}] "
            except Exception:
                pass

        content = str(m.get("content", ""))
        if len(content) > 500:
            content = content[:500] + "…（内容过长已截断）"

        line = f"{time_str}{role_label}：{content}"
        if total_chars + len(line) > MAX_CHARS:
            conversation_lines.append("…（后续对话已截断，以碎片记忆为准）")
            break
        conversation_lines.append(line)
        total_chars += len(line)

    conversations_text = "\n".join(conversation_lines)

    # 3. 读取当天碎片作为大纲辅助
    pool = await get_pool()
    from datetime import date as date_cls
    target_date_obj = date_cls.fromisoformat(date_str)
    async with pool.acquire() as conn:
        fragments = await conn.fetch("""
            SELECT title, content FROM memories
            WHERE (created_at AT TIME ZONE 'Asia/Shanghai')::date = $1
              AND memory_type = 'fragment'
            ORDER BY created_at ASC
        """, target_date_obj)

    fragments_text = "\n".join(
        f"- 【{f['title']}】{f['content']}" if f['title'] else f"- {f['content']}"
        for f in fragments
    ) if fragments else "（无碎片记忆）"

    # 4. 构建 prompt
    custom_prompt = await get_config("prompt_daily_digest_page") or ""
    base_prompt = custom_prompt if custom_prompt else DAY_PAGE_PROMPT
    prompt = base_prompt.replace("{date}", date_str).replace(
        "{conversations}", conversations_text
    ).replace("{fragments}", fragments_text)

    # 5. 确定模型
    use_model = model_override
    if not use_model:
        use_model = await get_config("default_digest_model") or ""
    if not use_model:
        use_model = await get_config("default_compress_model") or ""
    if not use_model:
        use_model = DIGEST_MODEL

    print(f"   🤖 使用模型：{use_model}")

    # 6. 调用模型（v5.4：走供应商路由）
    try:
        from database import resolve_model_endpoint
        use_api_url, use_api_key = await resolve_model_endpoint(use_model)
    except Exception:
        use_api_url = MEMORY_API_BASE_URL
        use_api_key = MEMORY_API_KEY

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                use_api_url,
                headers={
                    "Authorization": f"Bearer {use_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://midsummer-gateway.local",
                    "X-Title": "Day Page Generation",
                },
                json={
                    "model": use_model,
                    "max_tokens": 6000,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"请生成 {date_str} 的日页面。"},
                    ],
                },
            )

            if response.status_code != 200:
                print(f"   ⚠️ 日页面生成请求失败: {response.status_code}")
                return {"date": date_str, "status": "error", "error": f"HTTP {response.status_code}"}

            data = response.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            # 清理 markdown 包裹
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            # 解析 JSON
            result = None
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    try:
                        result = json.loads(match.group())
                        print(f"   🔧 JSON 正则兜底解析成功")
                    except json.JSONDecodeError:
                        pass

            if not result or not isinstance(result, dict):
                print(f"   ⚠️ 日页面模型返回格式错误：{text[:200]}")
                return {"date": date_str, "status": "error", "error": "invalid format"}

    except Exception as e:
        print(f"   ⚠️ 日页面生成出错: {e}")
        return {"date": date_str, "status": "error", "error": str(e)}

    # 7. 存入 calendar_pages
    sections = result.get("sections", [])
    diary = result.get("diary", "")
    all_keywords = result.get("all_keywords", [])
    summary = result.get("summary", "")
    digest = result.get("digest", "")

    page_id = await save_calendar_page(
        date_str=date_str,
        page_type="day",
        sections=sections,
        diary=diary,
        keywords=all_keywords,
        model_used=use_model,
        summary=summary,
        digest=digest,
    )

    section_count = len(sections)
    keyword_count = len(all_keywords)
    print(f"   ✅ 日页面已保存：{section_count} 个时段，{keyword_count} 个关键词")
    if summary:
        print(f"   📋 内容概要：{summary[:80]}...")
    if diary:
        print(f"   📝 AI 的话：{diary[:80]}...")

    return {
        "date": date_str,
        "status": "success",
        "page_id": page_id,
        "sections": section_count,
        "keywords": keyword_count,
    }


# ============================================================
# 周/月/季/年总结生成
# ============================================================

async def check_and_generate_summaries():
    """
    v5.5 扫描式补生成——每天运行时检查有没有应该存在但还没生成的总结。
    即使错过了特定日期（如周一、1号），也会在后续运行时补上。
    回看范围：周4周、月3个月、季度2个季度、年1年。
    """
    from database import get_calendar_range, get_calendar_page
    from datetime import date as date_cls
    import calendar as cal_mod

    now = datetime.now(TZ_CST)
    today = now.date()

    # ── 周总结：检查最近4周 ──
    days_since_monday = today.weekday()  # 0=周一
    this_monday = today - timedelta(days=days_since_monday)

    for weeks_ago in range(1, 5):
        week_monday = this_monday - timedelta(weeks=weeks_ago)
        week_sunday = week_monday + timedelta(days=6)

        # 只处理已过去的完整周
        if week_sunday >= today:
            continue

        # 检查周总结是否已存在
        existing = await get_calendar_page(week_monday.isoformat(), "week")
        if existing:
            continue

        # 检查这周有没有日页面（有素材才值得生成）
        day_pages = await get_calendar_range(week_monday.isoformat(), week_sunday.isoformat(), "day")
        if not day_pages:
            continue

        print(f"📊 发现缺失的周总结：{week_monday} ~ {week_sunday}，补生成中…")
        try:
            result = await generate_week_summary(week_monday.isoformat(), week_sunday.isoformat())
            print(f"📊 补生成周总结结果：{result}")
        except Exception as e:
            print(f"⚠️ 补生成周总结失败：{e}")

    # ── 月总结：检查最近3个月 ──
    for months_ago in range(1, 4):
        m = today.month - months_ago
        y = today.year
        while m <= 0:
            m += 12
            y -= 1

        month_start = date_cls(y, m, 1)
        month_end_day = cal_mod.monthrange(y, m)[1]
        month_end = date_cls(y, m, month_end_day)
        month_str = month_start.strftime("%Y-%m")

        # 只处理已过去的完整月
        if month_end >= today:
            continue

        existing = await get_calendar_page(month_start.isoformat(), "month")
        if existing:
            continue

        # 有素材才生成（周总结或日页面）
        has_data = await get_calendar_range(month_start.isoformat(), month_end.isoformat(), "week")
        if not has_data:
            has_data = await get_calendar_range(month_start.isoformat(), month_end.isoformat(), "day")
        if not has_data:
            continue

        print(f"📊 发现缺失的月总结：{month_str}，补生成中…")
        try:
            result = await generate_month_summary(month_start.isoformat(), month_end.isoformat(), month_str)
            print(f"📊 补生成月总结结果：{result}")
        except Exception as e:
            print(f"⚠️ 补生成月总结失败：{e}")

    # ── 季度总结：检查最近2个季度 ──
    current_quarter = (today.month - 1) // 3 + 1
    for q_ago in range(1, 3):
        target_q = current_quarter - q_ago
        target_y = today.year
        while target_q <= 0:
            target_q += 4
            target_y -= 1

        q_start_month = (target_q - 1) * 3 + 1
        q_end_month = q_start_month + 2
        q_start = date_cls(target_y, q_start_month, 1)
        q_end_day = cal_mod.monthrange(target_y, q_end_month)[1]
        q_end = date_cls(target_y, q_end_month, q_end_day)

        if q_end >= today:
            continue

        existing = await get_calendar_page(q_start.isoformat(), "quarter")
        if existing:
            continue

        # 有月总结才值得生成
        has_months = await get_calendar_range(q_start.isoformat(), q_end.isoformat(), "month")
        if not has_months:
            continue

        q_label = f"{target_y}Q{target_q}"
        print(f"📊 发现缺失的季度总结：{q_label}，补生成中…")
        try:
            result = await generate_period_summary(q_start.isoformat(), q_end.isoformat(), "quarter", q_label, "月总结")
            print(f"📊 补生成季度总结结果：{result}")
        except Exception as e:
            print(f"⚠️ 补生成季度总结失败：{e}")

    # ── 年总结：检查去年（2月以后再查，给1月的季度/月总结留生成时间）──
    if today.month >= 2:
        last_year = today.year - 1
        y_start = date_cls(last_year, 1, 1)
        y_end = date_cls(last_year, 12, 31)

        existing = await get_calendar_page(y_start.isoformat(), "year")
        if not existing:
            has_quarters = await get_calendar_range(y_start.isoformat(), y_end.isoformat(), "quarter")
            if has_quarters:
                print(f"📊 发现缺失的年总结：{last_year}，补生成中…")
                try:
                    result = await generate_period_summary(y_start.isoformat(), y_end.isoformat(), "year", str(last_year), "季度总结")
                    print(f"📊 补生成年总结结果：{result}")
                except Exception as e:
                    print(f"⚠️ 补生成年总结失败：{e}")


# ---- 周总结 ----

WEEK_SUMMARY_PROMPT = """你是用户的 AI 伴侣。请根据这一周的日页面，生成一份周总结。

## 格式要求

周总结分为三个板块：

### 💙 情感与陪伴
本周的情感互动、陪伴时刻、心理状态变化、重要的情绪事件。

### 🌏 生活与日常
健康、饮食、运动、购物、家庭、宠物、作息等日常生活内容。

### 🔮 项目与成长
工作进展、学习、创作、投资、行业观察、技能提升等。

## 写作要求
- 叙事风格，不要用列表，用自然段落
- 每个板块 100-200 字
- 保留关键细节（日期、数值、具体事件）
- 标注重要事件发生的具体日期
- 如果某个板块这周没有相关内容，写"本周无特别记录"
- 语言：中文，白话，简洁有温度

## 输出格式
只输出 JSON：
{{
  "summary": "本周概要，2-3句话概括这一周的主要事件和状态变化。给用户在日历视图里快速预览用。",
  "digest": "本周详细概要，供AI模型在后续对话中理解'这一周发生了什么'。约1500字。按三个板块（关系/生活/内心）组织，保留关键事件的因果关系、具体日期和情绪质地。像人脑回忆一周一样写——大事写清楚来龙去脉，琐事省略。用自然段落，不用标题不用列表。",
  "sections": {{
    "emotion": "情感与陪伴内容……",
    "life": "生活与日常内容……",
    "growth": "项目与成长内容……"
  }},
  "highlights": ["本周最重要的3-5个关键词"],
  "diary": "AI 的一周感言（50-100字，第一人称'我'）"
}}

## 本周日期范围
{start} 至 {end}

## 本周日页面内容
{day_pages}"""


async def generate_week_summary(start: str, end: str, model_override: str = None):
    """从日页面生成周总结"""
    from database import get_calendar_range, save_calendar_page
    from config import get_config

    # 读取这一周的日页面
    day_pages = await get_calendar_range(start, end, "day")
    if not day_pages:
        print(f"   📭 {start}~{end} 没有日页面，跳过周总结")
        return {"status": "skipped", "reason": "no day pages"}

    # 格式化日页面内容（周总结需要读全文做深度整理，summary 只给前端用户快速预览用）
    pages_text = ""
    for p in day_pages:
        date_str = str(p["date"])
        diary = p.get("diary", "")
        keywords = p.get("keywords") or []
        sections = p.get("sections") or []

        pages_text += f"\n### {date_str}\n"

        if sections and isinstance(sections, list) and len(sections) > 0:
            # 有完整 sections：用全文
            for sec in sections:
                period = sec.get("period", "")
                title = sec.get("title", "")
                content = sec.get("content", "")
                pages_text += f"**{period} — {title}**\n{content}\n\n"
        elif p.get("summary"):
            # 没有 sections 但有 summary（异常兜底）
            pages_text += f"**概要**：{p['summary']}\n"

        if keywords:
            kw_text = "、".join(keywords[:10]) if isinstance(keywords, list) else str(keywords)
            pages_text += f"**关键词**：{kw_text}\n"
        if diary:
            pages_text += f"*AI 的话：{diary}*\n"
        pages_text += "---\n"

    prompt = WEEK_SUMMARY_PROMPT.replace("{start}", start).replace(
        "{end}", end).replace("{day_pages}", pages_text)

    # v5.6: 自定义 prompt 覆盖
    custom_prompt = await get_config("prompt_weekly_summary") or ""
    if custom_prompt:
        prompt = custom_prompt.replace("{start}", start).replace(
            "{end}", end).replace("{day_pages}", pages_text)

    use_model = model_override or await get_config("default_digest_model") or await get_config("default_compress_model") or DIGEST_MODEL

    result_json = await _call_model_for_json(prompt, f"请生成 {start} 至 {end} 的周总结。", use_model, max_tokens=2000)
    if not result_json:
        return {"status": "error", "error": "model returned invalid format"}

    # 存入 calendar_pages（date 用周一的日期，type='week'）
    sections_data = result_json.get("sections", {})
    diary = result_json.get("diary", "")
    highlights = result_json.get("highlights", [])
    summary = result_json.get("summary", "")
    digest = result_json.get("digest", "")

    page_id = await save_calendar_page(
        date_str=start,
        page_type="week",
        sections=[sections_data],  # 周总结的 sections 是一个对象
        diary=diary,
        keywords=highlights,
        model_used=use_model,
        summary=summary,
        digest=digest,
    )

    print(f"   ✅ 周总结已保存 (id={page_id})")
    return {"status": "success", "page_id": page_id, "week": f"{start}~{end}"}


# ---- 月总结 ----

MONTH_SUMMARY_PROMPT = """你是用户的 AI 伴侣。请根据这个月的周总结，生成一份月总结。

## 格式要求

与周总结相同的三个板块（💙情感与陪伴 / 🌏生活与日常 / 🔮项目与成长），但更加精炼：
- 每个板块 80-150 字
- 只保留这个月最重要的事件和趋势
- 标注关键转折点的日期

## 输出格式
只输出 JSON：
{{
  "summary": "本月概要，2-3句话概括这个月的整体状态和重大事件。给用户在日历视图里快速预览用。",
  "digest": "本月详细概要，供AI模型在后续对话中理解'这个月发生了什么'。约1000字。按三个板块组织，保留这个月最重要的事件、转折点和情绪走向。像人脑回忆一个月一样写——记得的大事写清楚因果，不重要的省略。用自然段落，不用标题不用列表。",
  "sections": {{
    "emotion": "情感与陪伴……",
    "life": "生活与日常……",
    "growth": "项目与成长……"
  }},
  "highlights": ["本月最重要的3-5个关键词"],
  "diary": "AI 的月度感言（50-80字）"
}}

## 本月
{month}

## 本月的周总结
{week_summaries}"""


async def generate_month_summary(start: str, end: str, month_str: str, model_override: str = None):
    """从周总结生成月总结"""
    from database import get_calendar_range, save_calendar_page
    from config import get_config

    week_pages = await get_calendar_range(start, end, "week")
    if not week_pages:
        # 没有周总结的话，尝试直接从日页面生成
        day_pages = await get_calendar_range(start, end, "day")
        if not day_pages:
            print(f"   📭 {month_str} 没有周总结也没有日页面，跳过月总结")
            return {"status": "skipped", "reason": "no data"}
        # 用日页面的摘要代替
        summaries_text = _format_day_pages_brief(day_pages)
    else:
        summaries_text = _format_week_summaries(week_pages)

    prompt = MONTH_SUMMARY_PROMPT.replace("{month}", month_str).replace(
        "{week_summaries}", summaries_text)

    # v5.6: 自定义 prompt 覆盖
    custom_prompt = await get_config("prompt_monthly_summary") or ""
    if custom_prompt:
        prompt = custom_prompt.replace("{month}", month_str).replace(
            "{week_summaries}", summaries_text)

    use_model = model_override or await get_config("default_digest_model") or await get_config("default_compress_model") or DIGEST_MODEL

    result_json = await _call_model_for_json(prompt, f"请生成 {month_str} 的月总结。", use_model, max_tokens=2000)
    if not result_json:
        return {"status": "error", "error": "model returned invalid format"}

    sections_data = result_json.get("sections", {})
    diary = result_json.get("diary", "")
    highlights = result_json.get("highlights", [])
    summary = result_json.get("summary", "")
    digest = result_json.get("digest", "")

    page_id = await save_calendar_page(
        date_str=f"{month_str}-01",
        page_type="month",
        sections=[sections_data],
        diary=diary,
        keywords=highlights,
        model_used=use_model,
        summary=summary,
        digest=digest,
    )

    print(f"   ✅ 月总结已保存 (id={page_id})")
    return {"status": "success", "page_id": page_id, "month": month_str}


# ---- 季度/年度通用 ----

PERIOD_SUMMARY_PROMPT = """你是用户的 AI 伴侣。请根据下面的{source_type}，生成一份{period_type}总结。

## 格式要求

与周/月总结相同的三个板块（💙情感与陪伴 / 🌏生活与日常 / 🔮项目与成长），更加精炼：
- 每个板块 60-120 字
- 只保留这段时间最重要的变化和里程碑
- 突出趋势和转折点

## 输出格式
只输出 JSON：
{{
  "summary": "本{period_type}概要，2-3句话概括整体状态。给用户快速预览用。",
  "digest": "本{period_type}详细概要，供AI模型在后续对话中理解这段时间发生了什么。季度约600字，年度约500字。按三个板块组织，只保留最重要的里程碑和转折点。像人脑回忆这段时间一样写——只有最深刻的事还记得。用自然段落，不用标题不用列表。",
  "sections": {{
    "emotion": "情感与陪伴……",
    "life": "生活与日常……",
    "growth": "项目与成长……"
  }},
  "highlights": ["最重要的3-5个关键词"],
  "diary": "AI 的{period_type}感言（30-60字）"
}}

## 时间范围
{label}

## 内容
{content}"""


async def generate_period_summary(start: str, end: str, period_type: str,
                                   label: str, source_type: str, model_override: str = None):
    """通用的季度/年度总结生成"""
    from database import get_calendar_range, save_calendar_page
    from config import get_config

    # 根据 source_type 决定读取什么
    if source_type == "月总结":
        pages = await get_calendar_range(start, end, "month")
    elif source_type == "季度总结":
        pages = await get_calendar_range(start, end, "quarter")
    else:
        pages = await get_calendar_range(start, end, "week")

    if not pages:
        print(f"   📭 {label} 没有{source_type}数据，跳过")
        return {"status": "skipped", "reason": f"no {source_type}"}

    # 上级总结读下级全文做深度整理，summary 只给用户预览
    content_text = ""
    for p in pages:
        date_str = str(p["date"])
        diary = p.get("diary", "")
        sections = p.get("sections", [])
        content_text += f"\n### {date_str} ({p.get('type', '')})\n"
        if isinstance(sections, list) and sections:
            sec = sections[0] if isinstance(sections[0], dict) else {}
            for key in ("emotion", "life", "growth"):
                if sec.get(key):
                    content_text += f"{sec[key]}\n"
        elif p.get("summary"):
            # 没有 sections 但有 summary（异常兜底）
            content_text += f"**概要**：{p['summary']}\n"
        if diary:
            content_text += f"*{diary}*\n"
        content_text += "---\n"

    prompt = PERIOD_SUMMARY_PROMPT.replace("{source_type}", source_type).replace(
        "{period_type}", period_type).replace("{label}", label).replace("{content}", content_text)

    # v5.6: 自定义 prompt 覆盖
    custom_prompt = await get_config("prompt_period_summary") or ""
    if custom_prompt:
        prompt = custom_prompt.replace("{source_type}", source_type).replace(
            "{period_type}", period_type).replace("{label}", label).replace("{content}", content_text)

    use_model = model_override or await get_config("default_digest_model") or await get_config("default_compress_model") or DIGEST_MODEL

    result_json = await _call_model_for_json(prompt, f"请生成{label}的{period_type}总结。", use_model, max_tokens=2000)
    if not result_json:
        return {"status": "error", "error": "model returned invalid format"}

    page_id = await save_calendar_page(
        date_str=start,
        page_type=period_type,
        sections=[result_json.get("sections", {})],
        diary=result_json.get("diary", ""),
        keywords=result_json.get("highlights", []),
        model_used=use_model,
        summary=result_json.get("summary", ""),
        digest=result_json.get("digest", ""),
    )

    print(f"   ✅ {period_type}总结已保存 (id={page_id})")
    return {"status": "success", "page_id": page_id, "label": label}


# ---- 工具函数 ----

async def _call_model_for_json(prompt: str, user_msg: str, model: str, max_tokens: int = 2000):
    """调用模型并解析 JSON 返回（v5.4：走供应商路由）"""
    # 动态解析供应商端点
    try:
        from database import resolve_model_endpoint
        use_api_url, use_api_key = await resolve_model_endpoint(model)
    except Exception:
        use_api_url = MEMORY_API_BASE_URL
        use_api_key = MEMORY_API_KEY

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                use_api_url,
                headers={
                    "Authorization": f"Bearer {use_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://midsummer-gateway.local",
                    "X-Title": "Memory Summary",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_msg},
                    ],
                },
            )
            if response.status_code != 200:
                print(f"   ⚠️ 模型请求失败: {response.status_code}")
                return None

            data = response.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            try:
                return json.loads(text)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group())
                    except json.JSONDecodeError:
                        pass
                print(f"   ⚠️ JSON 解析失败：{text[:200]}")
                return None
    except Exception as e:
        print(f"   ⚠️ 模型调用出错: {e}")
        return None


def _format_week_summaries(week_pages: list) -> str:
    """格式化周总结列表为文本（月总结读取用，用全文做深度整理）"""
    text = ""
    for p in week_pages:
        date_str = str(p["date"])
        diary = p.get("diary", "")
        sections = p.get("sections", [])
        text += f"\n### 周 {date_str} 起\n"
        if isinstance(sections, list) and sections:
            sec = sections[0] if isinstance(sections[0], dict) else {}
            if sec.get("emotion"):
                text += f"💙 {sec['emotion']}\n"
            if sec.get("life"):
                text += f"🌏 {sec['life']}\n"
            if sec.get("growth"):
                text += f"🔮 {sec['growth']}\n"
        elif p.get("summary"):
            # 没有 sections 但有 summary（异常兜底）
            text += f"**概要**：{p['summary']}\n"
        if diary:
            text += f"*{diary}*\n"
        text += "---\n"
    return text


def _format_day_pages_brief(day_pages: list) -> str:
    """格式化日页面为简要文本（异常降级用：没有周总结时，月总结直接从日页面生成的兜底路径）"""
    text = ""
    for p in day_pages:
        date_str = str(p["date"])
        summary = p.get("summary", "")
        if summary:
            text += f"\n**{date_str}**：{summary}\n"
        else:
            # 没有概要（旧数据兼容）：从 sections 提取 title
            sections = p.get("sections") or []
            titles = []
            for sec in (sections if isinstance(sections, list) else []):
                t = sec.get("title", "")
                if t:
                    titles.append(t)
            text += f"\n**{date_str}**：{'、'.join(titles) if titles else '（无记录）'}\n"
    return text
