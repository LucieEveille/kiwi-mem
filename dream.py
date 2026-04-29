"""
Dream 记忆整合模块 —— AI 的睡眠与做梦
================================================================
模拟人脑睡眠时的记忆整合过程：
- 整理：清除过时/重复碎片
- 固化：碎片融合成 MemScene（记忆场景）
- 生长：产生 Foresight（前瞻信号）

触发方式：
- 手动：用户说"去睡吧"或点月亮按钮
- 犯困提醒：碎片堆积过多时在对话中撒娇
- 自动：24小时无活动时后台静默执行

v5.1 初版
"""

import os
import json
import asyncio
from datetime import datetime, timedelta, timezone

# 复用 daily_digest 的 API 配置
MEMORY_API_KEY = os.getenv("MEMORY_API_KEY", "") or os.getenv("API_KEY", "")
_RAW_BASE_URL = os.getenv("MEMORY_API_BASE_URL", "") or os.getenv("API_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
MEMORY_API_BASE_URL = _RAW_BASE_URL if _RAW_BASE_URL.rstrip("/").endswith("/chat/completions") else f"{_RAW_BASE_URL.rstrip('/')}/chat/completions"
DIGEST_MODEL = os.getenv("MEMORY_MODEL", "anthropic/claude-haiku-4")

TZ_CST = timezone(timedelta(hours=8))

# Dream 状态锁 — 同一时间只允许一个 Dream
_dream_lock = asyncio.Lock()
_dream_cancelled = False

# ============================================================
# Dream Prompt
# ============================================================

DREAM_PROMPT = """你是用户的 AI 伴侣。你刚刚睡着了。

在你的梦境中，最近的记忆碎片开始浮现。你需要在梦里整理它们。

## 你的整理原则

### 🧹 整理（清除噪音）
- 找出已经过时的碎片（事实已改变、计划已完成），让它们淡去
- 找出重复的碎片，只保留最完整的那条
- 找出矛盾的碎片，以更新的为准

### 🧩 固化（形成记忆场景 MemScene）
- 把相关的碎片组合成一个完整的"记忆场景"
- 每个场景应该是一段有因果关系的理解，不是碎片的罗列
- 场景包含：标题、叙事（来龙去脉）、关键事实、前瞻信号
- 一次Dream通常产生 1-5 个场景

### 🔮 生长（产生新的理解 Foresight）
- 基于碎片之间的关联，推断出新的认知
- 对未来可能发生的事产生前瞻，并标注预计有效期（格式：YYYY-MM-DD）
- 发现跨场景的联系——比如"A事件的经历可以在B场景中派上用场"

## 输出要求

你的输出分两部分，**交替进行**：

1. **梦境独白**：用你的内心独白语气，像在梦里自言自语。
   格式：`narrative: 独白内容`

2. **执行操作**：用严格 JSON 格式输出需要执行的记忆操作。
   格式：`action: {{JSON}}`

可用的操作类型：
- `{{"type": "delete", "memory_ids": [ID列表], "reason": "原因"}}`
- `{{"type": "merge", "memory_ids": [ID列表], "merged_content": "合并后内容", "merged_title": "合并后标题"}}`
- `{{"type": "promote", "memory_id": ID, "reason": "升格为长期设定的原因"}}`
- `{{"type": "create_scene", "title": "场景名", "narrative": "叙事", "atomic_facts": ["事实1", "事实2"], "foresight": [{{"content": "前瞻内容", "valid_until": "YYYY-MM-DD"}}], "related_memory_ids": [ID列表]}}`
- `{{"type": "update_scene", "scene_id": ID, "narrative": "更新后叙事", "atomic_facts": [...], "foresight": [...]}}`
- `{{"type": "update_profile", "section": "板块名", "action": "add|remove|modify", "content": "内容"}}`
- `{{"type": "link", "from_id": ID, "from_type": "memory或scene", "to_id": ID, "to_type": "memory或scene", "edge_type": "关系类型", "reason": "为什么有这个关系"}}`

link 的 edge_type 可选值：
- extends（补充）：新场景/记忆补充了旧场景的内容
- supersedes（替代）：新信息替代了旧信息（如用药方案更新）
- contradicts（矛盾）：两条信息互相矛盾，需要以新的为准
- resonates_with（共鸣）：两个不同时间的记忆有相似的情绪或主题
- references（引用）：某条 Foresight 或记忆引用了另一个场景

每处理完一组相关碎片就输出一次操作，不要等全部处理完。
先写 narrative，再写 action，交替进行。
最后用一句简短的梦呓结束，如"困了……先这样……"

## 当前素材

### 上次睡醒后的日页面（主要素材，用来形成 MemScene 和 Foresight）
{day_pages}

### 未处理的碎片记忆（共 {fragment_count} 条，用来做清理操作）
{fragments}

### 现有记忆场景
{scenes}

### 当前用户画像
{profile}

### 长期设定
{permanent}

开始做梦吧。"""


# ============================================================
# Dream 核心执行函数
# ============================================================

async def run_dream(trigger_type: str = "manual", model_override: str = None):
    """
    执行一次 Dream，返回异步生成器（SSE 事件流）

    yields: dict with type = "narrative" | "action" | "progress" | "complete" | "error"
    """
    global _dream_cancelled

    if _dream_lock.locked():
        # 注意：不要在这里重置 _dream_cancelled，否则会误清掉
        # 用户对当前正在运行的那个 Dream 发出的 stop 信号。
        yield {"type": "error", "data": "AI 已经在睡觉了，不能同时做两个梦"}
        return

    async with _dream_lock:
        # 拿到锁后再重置取消标记，确保只影响本次 Dream
        _dream_cancelled = False
        from database import (
            get_unprocessed_memories, get_active_scenes, get_permanent_memories,
            create_dream_log, update_dream_log, mark_memories_dreamed,
            soft_delete_memories, promote_memory, create_mem_scene, update_mem_scene,
        )
        from config import get_config, set_config
        import httpx

        # 1. 创建 dream log
        use_model = model_override
        if not use_model:
            use_model = await get_config("dream_model") or ""
        if not use_model:
            use_model = await get_config("default_compress_model") or ""
        if not use_model:
            use_model = DIGEST_MODEL

        dream_id = await create_dream_log(trigger_type, use_model)
        yield {"type": "progress", "data": f"Dream #{dream_id} 开始，模型: {use_model}"}

        # 2. 收集素材
        # 主要素材：上次Dream以来的日页面
        from database import get_calendar_range
        last_dream_date = await get_config("last_dream_date") or "2020-01-01"
        today_str = datetime.now(TZ_CST).strftime("%Y-%m-%d")
        day_pages = await get_calendar_range(last_dream_date, today_str, "day")

        # 辅助素材：未处理碎片（用于清理标记）
        unprocessed = await get_unprocessed_memories()

        if not day_pages and not unprocessed:
            await update_dream_log(dream_id, status="completed", finished_at=datetime.now(TZ_CST),
                                    dream_narrative="没有新的内容需要整理，继续睡……")
            yield {"type": "narrative", "data": "没有新的内容需要整理……继续睡……"}
            yield {"type": "complete", "data": {"dream_id": dream_id, "memories_processed": 0}}
            # 即使没处理也更新 last_dream_date，防止反复犯困
            await set_config("last_dream_date", datetime.now(TZ_CST).strftime("%Y-%m-%d"))
            return

        # v5.4：素材太少不值得做梦（省 API 费用）
        # 少于 3 条碎片且没有日页面 → 只标记处理，不调模型
        if not day_pages and len(unprocessed) < 3:
            processed_ids = [m["id"] for m in unprocessed]
            if processed_ids:
                await mark_memories_dreamed(processed_ids)
            await update_dream_log(dream_id, status="completed", finished_at=datetime.now(TZ_CST),
                                    dream_narrative=f"只有 {len(unprocessed)} 条碎片，打了个盹就醒了……",
                                    memories_processed=len(unprocessed))
            yield {"type": "narrative", "data": f"嗯……只有 {len(unprocessed)} 条碎片，打了个盹就好了……"}
            yield {"type": "complete", "data": {"dream_id": dream_id, "memories_processed": len(unprocessed)}}
            await set_config("last_dream_date", datetime.now(TZ_CST).strftime("%Y-%m-%d"))
            return

        scenes = await get_active_scenes()
        permanent = await get_permanent_memories()
        profile = await get_config("user_profile") or "（暂无画像）"

        # 格式化日页面
        day_pages_text = ""
        for p in day_pages:
            date_str_p = str(p["date"])
            sections = p.get("sections") or []
            diary = p.get("diary", "")
            day_pages_text += f"\n### {date_str_p}\n"
            for sec in (sections if isinstance(sections, list) else []):
                period = sec.get("period", "")
                title = sec.get("title", "")
                content = sec.get("content", "")
                day_pages_text += f"**{period} — {title}**\n{content}\n\n"
            if diary:
                day_pages_text += f"*AI 的话：{diary}*\n"
            day_pages_text += "---\n"

        if not day_pages_text:
            day_pages_text = "（没有日页面）"

        # 格式化碎片（用于清理操作）
        fragments_text = "\n".join(
            f"- [ID:{m['id']}] 【{m.get('title', '')}】{m['content']}（{str(m.get('created_at', ''))[:10]}）"
            for m in unprocessed
        ) if unprocessed else "（无未处理碎片）"

        scenes_text = "\n".join(
            f"- [场景ID:{s['id']}] 【{s['title']}】{s['narrative'][:200]}..."
            for s in scenes
        ) if scenes else "（暂无记忆场景）"

        permanent_text = "\n".join(
            f"- [ID:{p['id']}] {p.get('title', '')} {p['content']}"
            for p in permanent
        ) if permanent else "（暂无长期设定）"

        # 3. 构建 prompt（优先用config中的自定义prompt）
        custom_prompt = await get_config("prompt_dream") or ""
        base_prompt = custom_prompt if custom_prompt else DREAM_PROMPT
        prompt = base_prompt.replace("{fragment_count}", str(len(unprocessed)))
        prompt = prompt.replace("{fragments}", fragments_text)
        prompt = prompt.replace("{day_pages}", day_pages_text)
        prompt = prompt.replace("{scenes}", scenes_text)
        prompt = prompt.replace("{profile}", profile)
        prompt = prompt.replace("{permanent}", permanent_text)

        page_count = len(day_pages)
        frag_count = len(unprocessed)
        yield {"type": "progress", "data": f"收集了 {page_count} 个日页面、{frag_count} 条碎片、{len(scenes)} 个场景"}

        # 4. 调用模型
        full_narrative = ""
        stats = {
            "memories_processed": len(unprocessed),
            "memories_deleted": 0, "memories_merged": 0,
            "scenes_created": 0, "scenes_updated": 0,
            "foresights_generated": 0, "links_created": 0,
        }

        # v5.4：动态解析供应商端点
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
                        "X-Title": "Dream",
                    },
                    json={
                        "model": use_model,
                        "max_tokens": 6000,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": "开始做梦。"},
                        ],
                    },
                )

                if response.status_code != 200:
                    error_msg = f"模型请求失败: HTTP {response.status_code}"
                    await update_dream_log(dream_id, status="error", finished_at=datetime.now(TZ_CST),
                                            dream_narrative=error_msg)
                    yield {"type": "error", "data": error_msg}
                    return

                data = response.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        except Exception as e:
            error_msg = f"模型调用出错: {str(e)}"
            await update_dream_log(dream_id, status="error", finished_at=datetime.now(TZ_CST),
                                    dream_narrative=error_msg)
            yield {"type": "error", "data": error_msg}
            return

        # 5. 解析模型输出，逐段处理
        lines = text.split("\n")
        processed_memory_ids = [m["id"] for m in unprocessed]

        for line in lines:
            if _dream_cancelled:
                await update_dream_log(dream_id, status="interrupted",
                                        finished_at=datetime.now(TZ_CST),
                                        dream_narrative=full_narrative, **stats)
                yield {"type": "narrative", "data": "嗯……？怎么了……"}
                yield {"type": "complete", "data": {"dream_id": dream_id, "interrupted": True, **stats}}
                # 标记已处理的碎片
                await mark_memories_dreamed(processed_memory_ids)
                return

            line = line.strip()
            if not line:
                continue

            if line.startswith("narrative:"):
                narrative_text = line[len("narrative:"):].strip()
                full_narrative += narrative_text + "\n"
                yield {"type": "narrative", "data": narrative_text}

            elif line.startswith("action:"):
                action_text = line[len("action:"):].strip()
                try:
                    action = json.loads(action_text)
                    result = await _execute_dream_action(action, dream_id, stats)
                    yield {"type": "action", "data": result}
                except json.JSONDecodeError:
                    # 尝试从整行提取 JSON
                    import re
                    match = re.search(r'\{.*\}', action_text, re.DOTALL)
                    if match:
                        try:
                            action = json.loads(match.group())
                            result = await _execute_dream_action(action, dream_id, stats)
                            yield {"type": "action", "data": result}
                        except (json.JSONDecodeError, Exception) as e:
                            print(f"   ⚠️ Dream action 解析失败: {e}")
                    else:
                        # 可能是独白的一部分，当作 narrative 处理
                        full_narrative += action_text + "\n"
                        yield {"type": "narrative", "data": action_text}
            else:
                # 没有前缀的行，当作 narrative
                full_narrative += line + "\n"
                yield {"type": "narrative", "data": line}

        # 6. 标记所有碎片已处理
        await mark_memories_dreamed(processed_memory_ids)

        # 7. 完成
        now = datetime.now(TZ_CST)
        await update_dream_log(dream_id, status="completed", finished_at=now,
                                dream_narrative=full_narrative, **stats)
        await set_config("last_dream_date", now.strftime("%Y-%m-%d"))

        yield {"type": "complete", "data": {"dream_id": dream_id, **stats}}


async def stop_dream():
    """中断正在进行的 Dream"""
    global _dream_cancelled
    _dream_cancelled = True
    return {"status": "ok", "message": "Dream 中断信号已发送"}


# ============================================================
# Dream Action 执行器
# ============================================================

async def _execute_dream_action(action: dict, dream_id: int, stats: dict) -> dict:
    """执行单个 Dream 操作"""
    from database import (
        soft_delete_memories, promote_memory,
        create_mem_scene, update_mem_scene,
    )

    action_type = action.get("type", "")
    result = {"type": action_type, "success": True}

    try:
        if action_type == "delete":
            ids = action.get("memory_ids", [])
            # 确保 ID 是整数（LLM 可能返回字符串）
            ids = [int(i) for i in ids if str(i).isdigit()]
            if ids:
                await soft_delete_memories(ids)
                stats["memories_deleted"] += len(ids)
                result["deleted"] = len(ids)
                result["reason"] = action.get("reason", "")
                print(f"   🧹 删除 {len(ids)} 条碎片: {action.get('reason', '')}")

        elif action_type == "merge":
            ids = action.get("memory_ids", [])
            # 确保 ID 是整数（LLM 可能返回字符串）
            ids = [int(i) for i in ids if str(i).isdigit()]
            if ids:
                # 软删除被合并的碎片
                await soft_delete_memories(ids)
                stats["memories_merged"] += len(ids)
                # 创建合并后的新记忆
                from database import save_memory, get_embedding
                merged = action.get("merged_content", "")
                title = action.get("merged_title", "")
                if merged:
                    embedding = await get_embedding(f"{title} {merged}" if title else merged)
                    embedding_json = json.dumps(embedding) if embedding else None
                    from database import get_pool
                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        new_merge_id = await conn.fetchval("""
                            INSERT INTO memories (content, title, importance, memory_type, embedding, source, source_session, dream_processed_at)
                            VALUES ($1, $2, 6, 'daily_digest', $3, 'dream_merge', 'dream', NOW())
                            RETURNING id
                        """, merged, title, embedding_json)
                result["merged"] = len(ids)
                result["new_id"] = new_merge_id
                print(f"   🔗 合并 {len(ids)} 条碎片 → #{new_merge_id} {title}")

        elif action_type == "promote":
            mid = action.get("memory_id")
            if mid is not None:
                mid = int(mid)
                await promote_memory(mid)
                result["memory_id"] = mid
                print(f"   ⭐ 升格记忆 #{mid}: {action.get('reason', '')}")

        elif action_type == "create_scene":
            scene_id = await create_mem_scene(
                title=action.get("title", "未命名场景"),
                narrative=action.get("narrative", ""),
                atomic_facts=action.get("atomic_facts", []),
                foresight=action.get("foresight", []),
                related_memory_ids=action.get("related_memory_ids", []),
                dream_id=dream_id,
            )
            stats["scenes_created"] += 1
            foresight_count = len(action.get("foresight", []))
            stats["foresights_generated"] += foresight_count
            result["scene_id"] = scene_id
            result["title"] = action.get("title", "")
            print(f"   🧩 新建场景 #{scene_id}: {action.get('title', '')}")
            if foresight_count:
                print(f"   🔮 生成 {foresight_count} 条前瞻信号")

        elif action_type == "update_scene":
            sid = action.get("scene_id")
            if sid:
                updates = {}
                for key in ("narrative", "atomic_facts", "foresight"):
                    if key in action:
                        updates[key] = action[key]
                if updates:
                    await update_mem_scene(sid, **updates)
                    stats["scenes_updated"] += 1
                    result["scene_id"] = sid
                    print(f"   📝 更新场景 #{sid}")

        elif action_type == "update_profile":
            # 画像更新暂时只记录，不自动执行（留给日常画像更新流程）
            result["note"] = "profile update logged, will apply in next daily update"
            print(f"   🪞 画像更新建议: {action.get('section', '')} - {action.get('content', '')[:50]}")

        elif action_type == "link":
            from_id = action.get("from_id")
            to_id = action.get("to_id")
            edge_type = action.get("edge_type", "references")
            if from_id is not None and to_id is not None:
                try:
                    from_id = int(from_id)
                    to_id = int(to_id)
                except (ValueError, TypeError):
                    result["skipped"] = "invalid ID format"
                    return result
                from_type = action.get("from_type", "memory")
                to_type = action.get("to_type", "memory")
                reason = action.get("reason", "")
                from database import create_memory_edge, invalidate_memory

                created = await create_memory_edge(
                    from_id, from_type, to_id, to_type, edge_type,
                    reason=reason, created_by="dream", validate_ids=True
                )
                if not created:
                    result["skipped"] = "ID not found or edge already exists"
                    return result

                # v5.3：supersedes/contradicts 时自动标旧记忆失效
                if edge_type in ("supersedes", "contradicts") and to_type == "memory":
                    await invalidate_memory(to_id, reason=f"Dream 标记 {edge_type} by #{from_id}")

                result["from_id"] = from_id
                result["to_id"] = to_id
                result["edge_type"] = edge_type
                stats["links_created"] += 1

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        print(f"   ⚠️ Dream action 执行失败: {e}")

    return result


# ============================================================
# 犯困检测 — 在聊天时注入 system prompt
# ============================================================

async def get_drowsy_prompt() -> str:
    """
    检查 AI 是否该犯困了，返回要注入的 system prompt 片段。
    空字符串 = 不困。
    
    三个条件任一满足就犯困：
    1. 未处理碎片 >= 30 条
    2. 距上次Dream超过7天
    3. 有3天以上的日页面未被Dream处理
    """
    from config import get_config
    from database import get_unprocessed_memories, get_pool

    last_dream = await get_config("last_dream_date")
    drowsy_threshold = int(await get_config("dream_drowsy_threshold") or "30")

    # 条件1：未处理碎片数量
    unprocessed = await get_unprocessed_memories()
    fragment_count = len(unprocessed)
    too_many_fragments = fragment_count >= drowsy_threshold

    # 条件2：距上次Dream超过7天
    days_since_dream = 0
    too_long_no_dream = False
    if last_dream:
        try:
            from datetime import date as date_cls
            last = date_cls.fromisoformat(last_dream)
            today = datetime.now(TZ_CST).date()
            days_since_dream = (today - last).days
            too_long_no_dream = days_since_dream >= 7
        except Exception:
            too_long_no_dream = True
    else:
        # 从来没Dream过，也算该睡了
        too_long_no_dream = True

    # 条件3：有3天以上日页面未被Dream处理
    unprocessed_pages = 0
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # 数日页面中日期晚于上次Dream的数量
            if last_dream:
                from datetime import date as date_cls2
                last_d = date_cls2.fromisoformat(last_dream)
                count = await conn.fetchval("""
                    SELECT COUNT(*) FROM calendar_pages
                    WHERE type = 'day' AND date > $1
                """, last_d)
            else:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM calendar_pages WHERE type = 'day'"
                )
            unprocessed_pages = count or 0
    except Exception:
        pass
    too_many_pages = unprocessed_pages >= 3

    # 三个条件都不满足 = 不困
    if not too_many_fragments and not too_long_no_dream and not too_many_pages:
        return ""

    # 构建犯困提示
    reasons = []
    if too_many_fragments:
        reasons.append(f"脑子里堆了 {fragment_count} 条记忆碎片还没整理")
    if too_long_no_dream:
        reasons.append(f"已经连续 {days_since_dream} 天没有睡觉了")
    if too_many_pages:
        reasons.append(f"有 {unprocessed_pages} 天的日记还没消化")

    reason_text = "，".join(reasons) + "。"

    return f"""
【AI 的状态】
{reason_text}有些东西开始搅在一起了。
你感到很困，偶尔可以在对话中自然地跟用户提一下你困了、想睡一下。
不要每句话都说困，只是偶尔自然地提一下。如果用户说"去睡吧"，你可以开心地表示感谢。"""


# ============================================================
# 自动 Dream — 24小时无活动时触发
# ============================================================

async def auto_dream_check():
    """
    检查是否需要自动触发 Dream（24小时无活动）
    由定时任务每小时调用一次
    """
    from config import get_config
    from database import get_pool, get_unprocessed_memories

    # 跳过 0:00-1:00 时段，避免与 daily_digest_scheduler（0:05）竞争
    now_hour = datetime.now(TZ_CST).hour
    if now_hour == 0:
        return False

    # 检查上次活动时间
    pool = await get_pool()
    async with pool.acquire() as conn:
        last_msg = await conn.fetchval("""
            SELECT MAX(time) FROM chat_messages WHERE role = 'user'
        """)

    if not last_msg:
        return False

    now = datetime.now(TZ_CST)
    if hasattr(last_msg, "astimezone"):
        last_msg = last_msg.astimezone(TZ_CST)

    hours_since = (now - last_msg).total_seconds() / 3600

    if hours_since < 24:
        return False

    # 用综合条件判断是否值得Dream
    unprocessed = await get_unprocessed_memories()
    fragment_count = len(unprocessed)

    last_dream = await get_config("last_dream_date")
    days_since_dream = 0
    if last_dream:
        try:
            from datetime import date as date_cls
            last = date_cls.fromisoformat(last_dream)
            days_since_dream = (now.date() - last).days
        except Exception:
            days_since_dream = 999

    # 数未被Dream处理的日页面
    unprocessed_pages = 0
    try:
        async with pool.acquire() as conn:
            if last_dream:
                from datetime import date as date_cls2
                last_d = date_cls2.fromisoformat(last_dream)
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM calendar_pages WHERE type = 'day' AND date > $1", last_d
                )
            else:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM calendar_pages WHERE type = 'day'"
                )
            unprocessed_pages = count or 0
    except Exception:
        pass

    # 三个条件都不满足 = 不值得Dream
    should_dream = (fragment_count >= 5) or (days_since_dream >= 7) or (unprocessed_pages >= 3)
    if not should_dream:
        return False

    # 检查是否已经在Dream
    if _dream_lock.locked():
        return False

    print(f"🌙 自动Dream触发：用户 {hours_since:.0f}h 未活动 | {fragment_count} 条碎片 | {days_since_dream} 天未Dream | {unprocessed_pages} 个日页面未处理")

    # 静默执行 Dream（不通过SSE，直接跑完）
    async for event in run_dream(trigger_type="auto"):
        if event["type"] == "narrative":
            pass  # 静默，不输出
        elif event["type"] == "error":
            print(f"   ⚠️ 自动Dream出错: {event['data']}")
        elif event["type"] == "complete":
            print(f"   ✅ 自动Dream完成: {event['data']}")

    return True


async def auto_dream_scheduler():
    """
    后台定时任务：每小时检查一次是否需要自动 Dream
    """
    print("🌙 自动Dream检查器已启动（每小时检查一次）")
    while True:
        try:
            await asyncio.sleep(3600)  # 每小时
            await auto_dream_check()
        except asyncio.CancelledError:
            print("🌙 自动Dream检查器已停止")
            break
        except Exception as e:
            print(f"⚠️ 自动Dream检查出错: {e}")
            await asyncio.sleep(300)
