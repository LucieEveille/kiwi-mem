"""
MCP Server — kiwi-mem 记忆系统的 MCP 接口层
==========================================================
按功能域拆分为独立模块，客户端只连需要的模块，不用的不占 token。

模块一：记忆碎片（/memory/mcp）— 6 个工具
  search_memory, save_memory, get_recent, trigger_digest, lock_memory, unlock_memory

模块二：日历 + Dream（/calendar/mcp）— 11 个工具
  get_day_page, get_calendar_range, save_calendar_page,
  get_comments, add_comment,
  get_user_profile,
  trigger_dream, get_dream_status, get_dream_history, get_dream_scenes, stop_dream

部署方式：挂载到 FastAPI 主应用，共用同一个进程和端口。
薄包装层：不直接碰数据库，通过 HTTP 调用网关自身的 API。
"""

import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

# ============================================================
# 配置
# ============================================================

GATEWAY_PORT = int(os.getenv("PORT", "8080"))
GATEWAY_BASE = f"http://127.0.0.1:{GATEWAY_PORT}"
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")

# 内部调用网关 API 时需要带上 ACCESS_TOKEN（认证中间件会检查）
_access_token = os.getenv("ACCESS_TOKEN", "")
GATEWAY_HEADERS = {"Authorization": f"Bearer {_access_token}"} if _access_token else {}


# ============================================================
# 模块一：记忆碎片
# ============================================================

mcp_memory = FastMCP("Memory Garden", stateless_http=True)


@mcp_memory.tool()
async def search_memory(query: str, limit: int = 10) -> str:
    """
    搜索记忆 — 用自然语言描述你想找的内容，向量语义搜索会返回最相关的记忆。

    参数：
    - query: 搜索关键词或自然语言描述，比如"用户的健康记录"、"上周聊了什么"
    - limit: 返回条数上限（默认10，最大50）

    返回匹配的记忆列表，每条包含标题、内容、重要度、日期。
    """
    if limit > 50:
        limit = 50

    try:
        async with httpx.AsyncClient(timeout=15, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(
                f"{GATEWAY_BASE}/debug/memories",
                params={"q": query, "limit": limit},
            )
            data = resp.json()

        if "error" in data:
            return f"搜索失败：{data['error']}"

        results = data.get("results", [])
        if not results:
            return f"没有找到与「{query}」相关的记忆。"

        lines = [f"找到 {len(results)} 条相关记忆（共 {data.get('total_memories', '?')} 条）：\n"]
        for i, mem in enumerate(results, 1):
            title = mem.get("title", "")
            title_tag = f"【{title}】" if title else ""
            date = mem.get("created_at", "")[:10]
            importance = mem.get("importance", "?")
            memory_type = mem.get("memory_type", "fragment")
            content = mem.get("content", "")

            lines.append(
                f"{i}. [{date}] {title_tag}{content}\n"
                f"   重要度: {importance} | 类型: {memory_type}"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"搜索出错：{str(e)}"


@mcp_memory.tool()
async def save_memory(content: str, title: str = "", importance: int = 5) -> str:
    """
    保存一条新记忆到记忆库。

    参数：
    - content: 记忆内容（必填），比如"用户今天搬到了新城市"
    - title: 标题（可选，4-10字概括），比如"台湾搬家"
    - importance: 重要度 1-10（默认5），日常琐事1-4，重要事件5-6，关键转折7-8，核心记忆9-10

    记忆保存后会自动生成向量，可以被语义搜索找到。
    """
    if not content.strip():
        return "内容不能为空。"

    if importance < 1:
        importance = 1
    elif importance > 10:
        importance = 10

    try:
        async with httpx.AsyncClient(timeout=15, headers=GATEWAY_HEADERS) as client:
            resp = await client.post(
                f"{GATEWAY_BASE}/debug/memories",
                json={
                    "content": content.strip(),
                    "title": title.strip(),
                    "importance": importance,
                },
            )
            data = resp.json()

        if "error" in data:
            return f"保存失败：{data['error']}"

        total = data.get("total", "?")
        title_tag = f"【{title}】" if title else ""
        return f"✅ 记忆已保存：{title_tag}{content[:60]}...\n重要度: {importance} | 记忆总数: {total}"

    except Exception as e:
        return f"保存出错：{str(e)}"


@mcp_memory.tool()
async def get_recent(limit: int = 20) -> str:
    """
    获取最近的记忆，按时间倒序排列。

    参数：
    - limit: 返回条数（默认20，最大50）

    用于快速了解最近发生了什么、最近聊了什么。
    """
    if limit > 50:
        limit = 50

    try:
        async with httpx.AsyncClient(timeout=15, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(
                f"{GATEWAY_BASE}/debug/memories",
                params={"limit": limit},
            )
            data = resp.json()

        if "error" in data:
            return f"获取失败：{data['error']}"

        results = data.get("results", [])
        if not results:
            return "记忆库为空。"

        lines = [f"最近 {len(results)} 条记忆（共 {data.get('total_memories', '?')} 条）：\n"]
        for i, mem in enumerate(results, 1):
            title = mem.get("title", "")
            title_tag = f"【{title}】" if title else ""
            date = mem.get("created_at", "")[:10]
            content = mem.get("content", "")

            lines.append(f"{i}. [{date}] {title_tag}{content[:80]}")

        return "\n".join(lines)

    except Exception as e:
        return f"获取出错：{str(e)}"


@mcp_memory.tool()
async def trigger_digest(date: str = "") -> str:
    """
    手动触发每日记忆整理 — 把当天的碎片记忆合并成独立事件条目。

    参数：
    - date: 要整理的日期，格式 YYYY-MM-DD（默认整理昨天的）

    通常不需要手动调用，系统每天凌晨自动执行。
    只在需要立即整理时使用。
    """
    try:
        params = {}
        if date.strip():
            params["date"] = date.strip()

        async with httpx.AsyncClient(timeout=30, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(
                f"{GATEWAY_BASE}/admin/daily-digest",
                params=params,
            )
            data = resp.json()

        if "error" in data:
            return f"整理失败：{data['error']}"

        return f"✅ 每日整理完成：{json.dumps(data, ensure_ascii=False, indent=2)}"

    except Exception as e:
        return f"整理出错：{str(e)}"


@mcp_memory.tool()
async def lock_memory(memory_id: int) -> str:
    """
    锁定一条记忆 — 锁定后热度永远为 1.0，不会衰减遗忘，每次聊天都会注入。

    参数：
    - memory_id: 记忆 ID（从搜索结果中获取）

    用于标记核心记忆，比如重要的个人信息、关键决定、重要约定。
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=GATEWAY_HEADERS) as client:
            resp = await client.post(
                f"{GATEWAY_BASE}/debug/memories/batch-update",
                json={"ids": [memory_id], "is_permanent": True},
            )
            data = resp.json()

        if "error" in data:
            return f"锁定失败：{data['error']}"

        return f"🔒 记忆 #{memory_id} 已锁定（永不遗忘）"

    except Exception as e:
        return f"锁定出错：{str(e)}"


@mcp_memory.tool()
async def unlock_memory(memory_id: int) -> str:
    """
    解锁一条记忆 — 解锁后恢复正常热度衰减。

    参数：
    - memory_id: 记忆 ID

    用于取消之前锁定的记忆，让它回到正常的遗忘曲线。
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=GATEWAY_HEADERS) as client:
            resp = await client.post(
                f"{GATEWAY_BASE}/debug/memories/batch-update",
                json={"ids": [memory_id], "is_permanent": False},
            )
            data = resp.json()

        if "error" in data:
            return f"解锁失败：{data['error']}"

        return f"🔓 记忆 #{memory_id} 已解锁（恢复正常遗忘曲线）"

    except Exception as e:
        return f"解锁出错：{str(e)}"


# ============================================================
# 模块二：日历 + Dream
# ============================================================

mcp_calendar = FastMCP("Calendar & Dream", stateless_http=True)


# ---- 日历页面 ----

@mcp_calendar.tool()
async def get_day_page(date: str, type: str = "day") -> str:
    """
    查看某一天的日历页面（日记/周总结/月总结等）。

    参数：
    - date: 日期，格式 YYYY-MM-DD，如 "2026-04-14"
    - type: 页面类型，可选 day/week/month/quarter/year（默认 day）

    返回这一天的标题、内容概要、时段详情和 AI 日记。
    """
    if not date.strip():
        return "请提供日期，格式 YYYY-MM-DD"

    try:
        async with httpx.AsyncClient(timeout=15, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(
                f"{GATEWAY_BASE}/calendar/{date.strip()}",
                params={"type": type},
            )
            data = resp.json()

        if "error" in data:
            return f"读取出错：{data['error']}"

        page = data.get("page")
        if not page:
            return f"没有找到 {date} 的{type}页面。"

        title = page.get("title", "")
        summary = page.get("summary", "")
        sections = page.get("sections") or []
        diary = page.get("diary", "")
        keywords = page.get("keywords") or []

        lines = [f"📅 {date} 的{type}页面"]
        if title:
            lines[0] += f" — {title}"
        lines.append("")

        if summary:
            lines.append(f"【概要】{summary}\n")

        if isinstance(sections, list):
            for sec in sections:
                period = sec.get("period", "")
                sec_title = sec.get("title", "")
                content = sec.get("content", "")
                lines.append(f"**{period} — {sec_title}**\n{content}\n")

        if diary:
            lines.append(f"📝 AI 的日记：{diary}")

        if keywords:
            kw = "、".join(keywords[:15]) if isinstance(keywords, list) else str(keywords)
            lines.append(f"\n🏷 关键词：{kw}")

        return "\n".join(lines)

    except Exception as e:
        return f"读取出错：{str(e)}"


@mcp_calendar.tool()
async def get_calendar_range(start: str, end: str, type: str = "") -> str:
    """
    查看一段时间内的日历页面列表。

    参数：
    - start: 开始日期，格式 YYYY-MM-DD
    - end: 结束日期，格式 YYYY-MM-DD
    - type: 过滤类型（可选），day/week/month/quarter/year，留空返回所有类型

    返回每个页面的日期、类型、标题和关键词概览。
    """
    if not start.strip() or not end.strip():
        return "请提供起止日期，格式 YYYY-MM-DD"

    try:
        params = {"start": start.strip(), "end": end.strip()}
        if type.strip():
            params["type"] = type.strip()

        async with httpx.AsyncClient(timeout=15, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(f"{GATEWAY_BASE}/calendar", params=params)
            data = resp.json()

        if "error" in data:
            return f"查询失败：{data['error']}"

        pages = data.get("pages", [])
        if not pages:
            return f"{start} ~ {end} 没有日历页面。"

        lines = [f"📅 {start} ~ {end} 共 {len(pages)} 个页面：\n"]
        for p in pages:
            d = p.get("date", "")
            t = p.get("type", "day")
            title = p.get("title", "")
            kw = p.get("keywords") or []
            summary = p.get("summary", "")

            label = f"[{d}] ({t})"
            if title:
                label += f" {title}"
            if kw:
                kw_str = "、".join(kw[:8]) if isinstance(kw, list) else str(kw)
                label += f" | {kw_str}"
            elif summary:
                label += f" | {summary[:60]}"
            lines.append(label)

        return "\n".join(lines)

    except Exception as e:
        return f"查询出错：{str(e)}"


@mcp_calendar.tool()
async def save_calendar_page(date: str, content: str, title: str = "", type: str = "day") -> str:
    """
    写入或更新日历页面（日记）。

    参数：
    - date: 日期，格式 YYYY-MM-DD
    - content: 正文内容（Markdown 格式）
    - title: 标题（可选）
    - type: 页面类型，day/week/month/quarter/year（默认 day）

    用于 AI 在对话中为用户写日记、补充周记等。
    """
    if not date.strip():
        return "请提供日期，格式 YYYY-MM-DD"
    if not content.strip():
        return "内容不能为空。"

    try:
        async with httpx.AsyncClient(timeout=15, headers=GATEWAY_HEADERS) as client:
            resp = await client.put(
                f"{GATEWAY_BASE}/admin/calendar/{date.strip()}",
                json={
                    "content": content.strip(),
                    "title": title.strip(),
                    "type": type.strip(),
                },
            )
            data = resp.json()

        if "error" in data:
            return f"保存失败：{data['error']}"

        page_id = data.get("id", "?")
        return f"✅ 日历页面已保存：{date}（{type}）| ID: {page_id}"

    except Exception as e:
        return f"保存出错：{str(e)}"


# ---- 评论 ----

@mcp_calendar.tool()
async def get_comments(target_type: str, target_id: int) -> str:
    """
    读取某个页面的评论列表。

    参数：
    - target_type: 目标类型，如 "day_page"、"scene"
    - target_id: 目标 ID（日历页面的 ID 或场景的 ID）

    返回该页面下的所有评论。
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(
                f"{GATEWAY_BASE}/comments",
                params={"target_type": target_type, "target_id": target_id},
            )
            data = resp.json()

        if "error" in data:
            return f"读取失败：{data['error']}"

        comments = data.get("comments", [])
        if not comments:
            return "暂无评论。"

        lines = [f"💬 共 {len(comments)} 条评论：\n"]
        for c in comments:
            author = c.get("author", "?")
            content = c.get("content", "")
            time = str(c.get("created_at", ""))[:16]
            cid = c.get("id", "?")
            parent = c.get("parent_id")
            prefix = f"  ↳ 回复 #{parent} " if parent else ""
            lines.append(f"#{cid} [{time}] {prefix}{author}：{content}")

        return "\n".join(lines)

    except Exception as e:
        return f"读取出错：{str(e)}"


@mcp_calendar.tool()
async def add_comment(target_type: str, target_id: int, content: str, parent_id: int = 0) -> str:
    """
    在日历页面或场景下添加评论。

    参数：
    - target_type: 目标类型，如 "day_page"、"scene"
    - target_id: 目标 ID
    - content: 评论内容
    - parent_id: 回复的评论 ID（0 表示顶层评论）

    AI 可以用这个工具在日记下面写备注、标记或补充。
    """
    if not content.strip():
        return "评论内容不能为空。"

    try:
        body = {
            "target_type": target_type,
            "target_id": target_id,
            "content": content.strip(),
            "author": "assistant",
        }
        if parent_id > 0:
            body["parent_id"] = parent_id

        async with httpx.AsyncClient(timeout=10, headers=GATEWAY_HEADERS) as client:
            resp = await client.post(
                f"{GATEWAY_BASE}/comments",
                json=body,
            )
            data = resp.json()

        if "error" in data:
            return f"评论失败：{data['error']}"

        comment = data.get("comment", {})
        cid = comment.get("id", "?")
        return f"✅ 评论已发布（#{cid}）"

    except Exception as e:
        return f"评论出错：{str(e)}"


# ---- 用户画像 ----

@mcp_calendar.tool()
async def get_user_profile() -> str:
    """
    查看当前的用户画像 — AI 对用户的认知。

    画像包含四个板块：基本档案、洞察、近期重点、长期偏好。
    由每日整理自动更新，也可手动触发更新。
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(f"{GATEWAY_BASE}/admin/config")
            data = resp.json()

        profile = data.get("user_profile", {}).get("value", "")
        if not profile:
            return "暂无用户画像。"

        return f"🪞 用户画像\n\n{profile}"

    except Exception as e:
        return f"读取出错：{str(e)}"


# ---- Dream ----

@mcp_calendar.tool()
async def trigger_dream() -> str:
    """
    让 AI 去睡觉（触发 Dream 记忆整合）。

    Dream 会整理碎片记忆、形成记忆场景（MemScene）、产生前瞻信号（Foresight）。
    通常在碎片堆积较多或长时间未整理时使用。
    """
    try:
        # /dream/start 返回 SSE 流，不能当 JSON 解析
        # 只需要触发启动，不等待完成（Dream 可能跑几分钟）
        async with httpx.AsyncClient(timeout=30, headers=GATEWAY_HEADERS) as client:
            resp = await client.post(
                f"{GATEWAY_BASE}/dream/start",
                json={"trigger_type": "manual"},
            )

        if resp.status_code == 200:
            return "🌙 Dream 已启动，可以用 get_dream_status 查看进度。"
        else:
            # 尝试读取错误信息
            try:
                data = resp.json()
                return f"Dream 启动失败：{data.get('error', resp.text)}"
            except Exception:
                return f"Dream 启动失败（HTTP {resp.status_code}）：{resp.text[:200]}"

    except Exception as e:
        return f"启动出错：{str(e)}"


@mcp_calendar.tool()
async def stop_dream() -> str:
    """
    中断正在进行的 Dream。

    用于在 Dream 过程中需要紧急打断时使用。
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=GATEWAY_HEADERS) as client:
            resp = await client.post(f"{GATEWAY_BASE}/dream/stop")
            data = resp.json()

        if "error" in data:
            return f"中断失败：{data['error']}"

        return f"⏹ Dream 已中断：{json.dumps(data, ensure_ascii=False)}"

    except Exception as e:
        return f"中断出错：{str(e)}"


@mcp_calendar.tool()
async def get_dream_status() -> str:
    """
    查看 Dream 状态 — 是否正在做梦、上次做梦的结果、待处理碎片数量。
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(f"{GATEWAY_BASE}/dream/status")
            data = resp.json()

        is_running = data.get("is_running", False)
        last = data.get("last_completed")

        lines = []
        if is_running:
            lines.append("🌙 AI 正在做梦中…")
            current = data.get("current", {})
            if current:
                lines.append(f"   Dream #{current.get('id', '?')} | 开始于 {str(current.get('started_at', ''))[:19]}")
        else:
            lines.append("😴 AI 目前醒着。")

        # 待处理碎片
        unprocessed = data.get("unprocessed_count", 0)
        drowsy = data.get("is_drowsy", False)
        if unprocessed > 0:
            drowsy_tag = "（已犯困，建议做梦）" if drowsy else ""
            lines.append(f"   待处理碎片：{unprocessed} 条{drowsy_tag}")

        if last:
            lines.append(f"\n上次 Dream：#{last.get('id', '?')}")
            lines.append(f"   时间：{str(last.get('started_at', ''))[:19]} → {str(last.get('finished_at', ''))[:19]}")
            lines.append(f"   处理碎片：{last.get('memories_processed', 0)} 条")
            lines.append(f"   删除：{last.get('memories_deleted', 0)} | 合并：{last.get('memories_merged', 0)}")
            lines.append(f"   新建场景：{last.get('scenes_created', 0)} | 前瞻信号：{last.get('foresights_generated', 0)}")

        return "\n".join(lines) if lines else "暂无 Dream 记录。"

    except Exception as e:
        return f"查询出错：{str(e)}"


@mcp_calendar.tool()
async def get_dream_history(limit: int = 10) -> str:
    """
    查看 Dream 执行历史记录。

    参数：
    - limit: 返回条数（默认10）

    显示每次 Dream 的时间、处理碎片数、新建场景数等。
    """
    if limit > 50:
        limit = 50

    try:
        async with httpx.AsyncClient(timeout=10, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(
                f"{GATEWAY_BASE}/dream/history",
                params={"limit": limit},
            )
            data = resp.json()

        if "error" in data:
            return f"查询失败：{data['error']}"

        history = data.get("history", [])
        if not history:
            return "还没有 Dream 记录。"

        lines = [f"🌙 Dream 历史（最近 {len(history)} 次）：\n"]
        for h in history:
            did = h.get("id", "?")
            status = h.get("status", "?")
            started = str(h.get("started_at", ""))[:16]
            finished = str(h.get("finished_at", ""))[:16]
            processed = h.get("memories_processed", 0)
            deleted = h.get("memories_deleted", 0)
            merged = h.get("memories_merged", 0)
            scenes = h.get("scenes_created", 0)
            foresights = h.get("foresights_generated", 0)

            status_icon = {"completed": "✅", "running": "🔄", "interrupted": "⏹", "failed": "❌"}.get(status, "❓")
            lines.append(
                f"{status_icon} Dream #{did} | {started} → {finished}\n"
                f"   碎片: {processed} | 删除: {deleted} | 合并: {merged} | 场景: {scenes} | 前瞻: {foresights}"
            )

        return "\n".join(lines)

    except Exception as e:
        return f"查询出错：{str(e)}"


@mcp_calendar.tool()
async def get_dream_scenes() -> str:
    """
    查看所有活跃的记忆场景（MemScene）。

    记忆场景是 Dream 过程中将相关碎片记忆凝聚成的主题叙事。
    每个场景包含标题、叙事文本和前瞻信号（Foresight）。
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=GATEWAY_HEADERS) as client:
            resp = await client.get(f"{GATEWAY_BASE}/dream/scenes")
            data = resp.json()

        if "error" in data:
            return f"查询失败：{data['error']}"

        scenes = data.get("scenes", [])
        if not scenes:
            return "还没有记忆场景。"

        lines = [f"🎭 活跃场景共 {len(scenes)} 个：\n"]
        for s in scenes:
            sid = s.get("id", "?")
            title = s.get("title", "无标题")
            narrative = s.get("narrative", "")
            foresight = s.get("foresight") or []
            created = str(s.get("created_at", ""))[:10]
            memory_count = s.get("memory_count", 0)

            lines.append(f"🎬 #{sid}「{title}」({created}，{memory_count} 条碎片)")
            if narrative:
                lines.append(f"   {narrative[:120]}{'…' if len(narrative) > 120 else ''}")
            if foresight:
                fs_list = foresight if isinstance(foresight, list) else [foresight]
                for f in fs_list[:3]:
                    lines.append(f"   🔮 {f}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return f"查询出错：{str(e)}"


# ============================================================
# 获取 ASGI app（用于挂载到 FastAPI）
# ============================================================

def get_memory_mcp_app():
    """
    记忆碎片模块 MCP。
    挂载路径：/memory → URL：/memory/mcp
    6 个工具：search_memory, save_memory, get_recent, trigger_digest, lock_memory, unlock_memory
    """
    return mcp_memory.streamable_http_app()


def get_calendar_mcp_app():
    """
    日历 + Dream 模块 MCP。
    挂载路径：/calendar → URL：/calendar/mcp
    11 个工具：get_day_page, get_calendar_range, save_calendar_page,
              get_comments, add_comment, get_user_profile,
              trigger_dream, stop_dream, get_dream_status, get_dream_history, get_dream_scenes
    """
    return mcp_calendar.streamable_http_app()


# 向后兼容（旧代码 import 用）
mcp = mcp_memory

def get_mcp_app():
    """向后兼容：返回记忆模块"""
    return get_memory_mcp_app()
