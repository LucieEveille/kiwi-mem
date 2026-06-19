"""
tool_drawer.py - Vector Tool Drawer (Auto-Discovery)
=====================================================
启动时自动从 mcp_server.py 发现工具、提取 schema、归类。
新增工具只需在 mcp_server.py 写函数并加 [category: xxx] 标签。
"""

import ast
import asyncio
import hashlib
import json
import os
import re
import time
from typing import Dict, List, Optional, Set, Tuple

# ============================================================
# 1. Category Metadata (静态配置，很少变动)
#    加新类别时在这里加一条即可
# ============================================================

CATEGORY_META = {
    "memory": {
        "label": "记忆",
        "description": "记忆搜索、保存记忆、查看最近记忆、锁定解锁记忆、提取摘要。用户想回忆过去说过的话、保存重要信息、管理记忆碎片时需要。",
        "keywords": ["记忆", "记得", "记住", "碎片", "忘了", "忘记", "回忆",
                     "记一下", "存一下", "想起", "记下", "保存记忆"],
    },
    "calendar": {
        "label": "日历",
        "description": "日历日志、日页面读写、周月年总结、评论系统。用户想写日记、查看某天的记录、回顾一段时间的日志时需要。",
        "keywords": ["日记", "日志", "日历", "写日记", "那天", "那一天",
                     "昨天的", "上周记", "今天写"],
    },
    "dream": {
        "label": "Dream",
        "description": "做梦、整理记忆、触发Dream流程、查看梦境状态和历史、查看记忆场景。用户说去做梦、整理一下、让 AI 睡觉时需要。",
        "keywords": ["做梦", "梦境", "整理记忆", "睡觉", "睡吧", "去睡",
                     "睡一觉", "做个梦", "Dream", "dream"],
    },
    "profile": {
        "label": "画像",
        "description": "用户画像、人格印象、对用户的认知。查看 AI 对用户的理解和印象标签。",
        "keywords": ["你怎么看我", "你眼里的我", "你眼中我", "在你心里",
                     "我是什么样", "你觉得我", "你对我的印象", "画像"],
    },
    "search": {
        "label": "搜索",
        "description": "联网搜索、查询实时信息、新闻、天气、价格。用户需要最新资讯或事实核查时需要。",
        "keywords": ["搜索", "搜一下", "查一下", "新闻", "天气", "最新",
                     "帮我查", "搜搜", "查查"],
    },
    "conversation": {
        "label": "对话",
        "description": "搜索过去的对话记录、查找之前聊过的话题和细节。用户提到之前讨论过、上次说的时需要。",
        "keywords": ["还记得", "之前聊", "之前说", "上次说", "上次",
                     "那次", "聊过", "讨论过", "你说过", "我说过",
                     "我跟你说过", "我和你说过", "印象中", "印象里",
                     "以前聊", "之前提"],
    },
    "reminder": {
        "label": "提醒",
        "description": "提醒、闹钟、定时任务。创建提醒、查看列表、完成、删除。用户说提醒我、几点叫我、别忘了时需要。",
        "keywords": ["提醒", "闹钟", "定时", "叫我", "别忘了", "记得叫",
                     "点钟", "每天", "每周", "到点"],
    },
}

# ============================================================
# 2. Gateway-builtin Tool Schemas (不在 mcp_server.py 里的工具)
#    这些工具由 main.py 的 _execute_gateway_tool 处理
# ============================================================

GATEWAY_TOOL_SCHEMAS = {
    "_gateway_web_search": {"type":"function","function":{"name":"_gateway_web_search","description":"联网搜索实时信息。仅在需要最新新闻/天气/实时数据时调用。","parameters":{"type":"object","properties":{"query":{"type":"string","description":"搜索关键词"}},"required":["query"]}}},
    "_gateway_search_conversations": {"type":"function","function":{"name":"_gateway_search_conversations","description":"搜索过去的对话记录。当用户提到之前聊过、上次说的时调用。","parameters":{"type":"object","properties":{"query":{"type":"string","description":"搜索关键词"},"limit":{"type":"integer","description":"最多返回条数（默认10）"}},"required":["query"]}}},
    "_gateway_create_reminder": {"type":"function","function":{"name":"_gateway_create_reminder","description":"为用户创建一条提醒。当用户说提醒我、几点叫我、别忘了时调用。title用简洁中文描述，notes记录上下文。","parameters":{"type":"object","properties":{"title":{"type":"string","description":"提醒标题"},"notes":{"type":"string","description":"备注信息"},"trigger_time":{"type":"string","description":"触发时间ISO8601格式"},"repeat_type":{"type":"string","enum":["once","daily","weekly","hourly"],"description":"重复类型"},"repeat_config":{"type":"object","description":"循环配置"}},"required":["title","trigger_time"]}}},
    "_gateway_list_reminders": {"type":"function","function":{"name":"_gateway_list_reminders","description":"查看用户当前的所有活跃提醒。","parameters":{"type":"object","properties":{}}}},
    "_gateway_complete_reminder": {"type":"function","function":{"name":"_gateway_complete_reminder","description":"标记一条提醒为已完成。用户说做完了、回来了时调用。","parameters":{"type":"object","properties":{"reminder_id":{"type":"string","description":"提醒ID"}},"required":["reminder_id"]}}},
    "_gateway_delete_reminder": {"type":"function","function":{"name":"_gateway_delete_reminder","description":"删除一条提醒。用户说取消提醒、不用提醒了时调用。","parameters":{"type":"object","properties":{"reminder_id":{"type":"string","description":"提醒ID"}},"required":["reminder_id"]}}},
}

# Gateway 工具 → 类别映射
GATEWAY_CATEGORY_MAP = {
    "_gateway_web_search": "search",
    "_gateway_search_conversations": "conversation",
    "_gateway_create_reminder": "reminder",
    "_gateway_list_reminders": "reminder",
    "_gateway_complete_reminder": "reminder",
    "_gateway_delete_reminder": "reminder",
}

# ============================================================
# 3. Dynamic registries (populated at startup by init_drawer)
# ============================================================

TOOL_SCHEMAS = {}      # tool_name -> OpenAI schema (all tools)
CATEGORIES = {}        # cat_id -> {label, description, tool_names}
_tool_to_category = {} # tool_name -> cat_id
_external_categories = {}   # cat_id -> external drawer metadata + execution map
_external_config_hash = None
_refresh_lock = asyncio.Lock()   # Bug #4：串行化 refresh_external_drawers，避免半重建的注册表被并发读到

# ============================================================
# 4. Meta-tools (always available)
# ============================================================

def _build_meta_tools():
    cats = list(CATEGORIES.keys()) if CATEGORIES else list(CATEGORY_META.keys())
    return [
        {"type":"function","function":{"name":"_drawer_request_tools","description":"手动请求展开工具类别。可用：" + "/".join(cats),"parameters":{"type":"object","properties":{"category":{"type":"string","enum":cats,"description":"工具类别ID"}},"required":["category"]}}},
        {"type":"function","function":{"name":"_drawer_return_tools","description":"归还当前展开的工具，释放token空间。","parameters":{"type":"object","properties":{}}}},
        {"type":"function","function":{"name":"list_tool_categories","description":"列出当前可展开的工具抽屉类别，包括外部 MCP 动态类别。","parameters":{"type":"object","properties":{}}}},
    ]

META_TOOLS = []  # populated after CATEGORIES is built

# ============================================================
# 5. Auto-discovery from mcp_server.py
# ============================================================

_TYPE_MAP = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}

def _auto_discover_mcp_tools():
    """Parse mcp_server.py with AST, extract tools, build schemas."""
    global TOOL_SCHEMAS, CATEGORIES, _tool_to_category, META_TOOLS

    mcp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.py")
    if not os.path.exists(mcp_path):
        print("\u26a0\ufe0f  auto-discover: mcp_server.py not found")
        return

    with open(mcp_path, "r", encoding="utf-8") as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"\u26a0\ufe0f  auto-discover: parse error: {e}")
        return

    discovered = 0
    cat_tools = {}  # cat_id -> [tool_names]

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        # Check for @mcp_xxx.tool() decorator
        is_tool = False
        for dec in node.decorator_list:
            if hasattr(dec, 'func') and hasattr(dec.func, 'attr') and dec.func.attr == 'tool':
                is_tool = True
                break
        if not is_tool:
            continue

        func_name = node.name
        doc = ast.get_docstring(node) or ""

        # Extract [category: xxx]
        cat_match = re.search(r'\[category:\s*(\w+)\]', doc)
        category = cat_match.group(1) if cat_match else "uncategorized"

        # system_internal 类工具不暴露给 LLM（如 trigger_digest）
        if category == "system_internal":
            continue

        # Clean description: remove tag, remove params section
        desc = re.sub(r'\[category:\s*\w+\]\s*', '', doc).strip()
        desc_parts = re.split(r'\n\s*参数[：:]', desc)
        description = re.sub(r'\s+', ' ', desc_parts[0].strip())

        # Parse parameter descriptions from docstring
        param_descs = {}
        if len(desc_parts) > 1:
            for pm in re.finditer(r'-\s*(\w+)\s*[:：]\s*(.+?)(?=\n\s*-|\n\n|$)', desc_parts[1], re.DOTALL):
                param_descs[pm.group(1)] = re.sub(r'\s+', ' ', pm.group(2).strip())

        # Build parameters from function signature
        properties = {}
        required = []
        args = node.args
        num_defaults = len(args.defaults)
        num_args = len(args.args)

        for idx, arg in enumerate(args.args):
            arg_name = arg.arg
            # Get type annotation
            type_str = "string"
            if arg.annotation and isinstance(arg.annotation, ast.Name):
                type_str = _TYPE_MAP.get(arg.annotation.id, "string")

            prop = {"type": type_str}
            if arg_name in param_descs:
                prop["description"] = param_descs[arg_name]

            properties[arg_name] = prop

            # Required if no default value
            default_idx = idx - (num_args - num_defaults)
            if default_idx < 0:
                required.append(arg_name)

        # Build OpenAI schema
        schema = {
            "type": "function",
            "function": {
                "name": func_name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            },
        }
        if required:
            schema["function"]["parameters"]["required"] = required

        TOOL_SCHEMAS[func_name] = schema
        _tool_to_category[func_name] = category

        if category not in cat_tools:
            cat_tools[category] = []
        cat_tools[category].append(func_name)
        discovered += 1

    # Register gateway-builtin tools
    for tool_name, schema in GATEWAY_TOOL_SCHEMAS.items():
        TOOL_SCHEMAS[tool_name] = schema
        cat = GATEWAY_CATEGORY_MAP.get(tool_name, "uncategorized")
        _tool_to_category[tool_name] = cat
        if cat not in cat_tools:
            cat_tools[cat] = []
        cat_tools[cat].append(tool_name)

    # Build CATEGORIES from CATEGORY_META + discovered tools
    for cat_id, tools in cat_tools.items():
        meta = CATEGORY_META.get(cat_id, {
            "label": cat_id,
            "description": f"{cat_id} category tools",
            "keywords": [],
        })
        CATEGORIES[cat_id] = {
            "label": meta["label"],
            "description": meta["description"],
            "tool_names": tools,
        }

    # Build META_TOOLS now that CATEGORIES is populated
    META_TOOLS.clear()
    META_TOOLS.extend(_build_meta_tools())

    total = discovered + len(GATEWAY_TOOL_SCHEMAS)
    print(f"\U0001f5c3\ufe0f  自动发现：{discovered} 个 MCP 工具 + {len(GATEWAY_TOOL_SCHEMAS)} 个 gateway 工具 = {total} 个，{len(CATEGORIES)} 个类别")

# ============================================================
# 6. Directory Text (for system prompt)
# ============================================================

def get_directory_text():
    if not CATEGORIES:
        # Fallback before init
        return ""
    lines = ["", "【工具抽屉】", "系统会根据对话内容自动为你展开需要的工具。可用类别："]
    for cat_id, cat in CATEGORIES.items():
        short = cat["description"].split("。")[0]
        lines.append(f"  - {cat['label']}（{cat_id}）：{short}")
    lines.append("如果自动路由没有展开你需要的工具，调用 _drawer_request_tools(category) 手动请求。")
    lines.append("用完工具后调用 _drawer_return_tools() 归还。")
    return "\n".join(lines)

# ============================================================
# 7. Embedding Pre-computation + Init
# ============================================================

_category_embeddings = {}
_initialized = False
_COMMON_EXTERNAL_KEYWORDS = {
    "get", "set", "list", "search", "query", "read", "write", "create", "delete",
    "update", "run", "exec", "call", "fetch", "send", "add", "remove", "tool", "mcp",
}


def _safe_identifier(value, max_len=40, fallback="server"):
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return (slug or fallback)[:max_len].strip("_") or fallback


def _external_cat_id(server, used_ids):
    url_hash = hashlib.md5((server.get("url") or "").encode("utf-8")).hexdigest()[:6]
    name_slug = _safe_identifier(server.get("name") or "", 24, fallback="")
    base = f"ext_{name_slug}_{url_hash}" if name_slug else f"ext_{url_hash}"
    cat_id = base
    idx = 2
    while cat_id in used_ids:
        suffix = f"_{idx}"
        cat_id = f"{base[:40 - len(suffix)]}{suffix}"
        idx += 1
    return cat_id


def _prefixed_external_tool_name(cat_id, origin_name, used_names):
    origin_slug = _safe_identifier(origin_name, 24)
    base = f"ext_{cat_id}__{origin_slug}"
    candidate = base
    idx = 2
    while candidate in used_names:
        suffix = f"_{idx}"
        candidate = f"{base[:64 - len(suffix)]}{suffix}"
        idx += 1
    return candidate[:64]


def _clone_tool_schema(schema, exposed_name):
    cloned = json.loads(json.dumps(schema, ensure_ascii=False))
    cloned.setdefault("function", {})["name"] = exposed_name
    return cloned


def _split_external_tokens(value):
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_]{2,}", str(value or ""))
        if token.lower() not in _COMMON_EXTERNAL_KEYWORDS
    ]


def _external_keywords(server_name, origin_names):
    keywords = []
    full_name = str(server_name or "").strip()
    full_name_lower = full_name.lower()
    if full_name and not (
        full_name_lower in _COMMON_EXTERNAL_KEYWORDS
        and re.fullmatch(r"[a-z0-9_]+", full_name_lower)
    ):
        keywords.append(full_name.lower())
    keywords.extend(_split_external_tokens(full_name))
    for origin_name in origin_names:
        tool_name = str(origin_name or "").strip()
        if tool_name and tool_name.lower() not in _COMMON_EXTERNAL_KEYWORDS:
            keywords.append(tool_name.lower())
    return list(dict.fromkeys(keywords))


def _external_keyword_match(user_message):
    msg = (user_message or "").lower()
    matched = set()
    if not msg:
        return matched
    for cat_id in _external_categories:
        keywords = CATEGORIES.get(cat_id, {}).get("keywords", [])
        for kw in keywords:
            keyword = str(kw or "").lower()
            if not keyword:
                continue
            if re.fullmatch(r"[a-z0-9_]+", keyword):
                if re.search(rf"(?<![a-z0-9_]){re.escape(keyword)}(?![a-z0-9_])", msg):
                    matched.add(cat_id)
                    break
            elif keyword in msg:
                matched.add(cat_id)
                break
    return matched


def _truncate_text(text, limit=500):
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def _normalize_external_servers(raw_config):
    if not raw_config:
        return []
    try:
        servers = json.loads(raw_config) if isinstance(raw_config, str) else raw_config
    except Exception as e:
        print(f"\u26a0\ufe0f  外部 MCP 配置解析失败，跳过：{e}")
        return []
    if not isinstance(servers, list):
        return []

    normalized = []
    for server in servers:
        if not isinstance(server, dict):
            continue
        if server.get("enabled") is False:
            continue
        url = (server.get("url") or "").strip()
        if not url:
            continue
        url_lower = url.lower()
        if "/memory/mcp" in url_lower or "/calendar/mcp" in url_lower:
            print(f"\u26a0\ufe0f  外部 MCP [{server.get('name') or url}] 跳过：自家工具已在内部抽屉")
            continue
        name = (server.get("name") or url).strip()
        normalized.append({
            "url": url,
            "name": name,
            "transport": server.get("transport") or "streamable_http",
        })
    return normalized


def _unregister_external_drawers():
    global _external_categories
    if not _external_categories:
        return

    old_cat_ids = set(_external_categories.keys())
    for cat_id, meta in list(_external_categories.items()):
        CATEGORIES.pop(cat_id, None)
        _category_embeddings.pop(cat_id, None)
        for tool_name in meta.get("tool_names", []):
            TOOL_SCHEMAS.pop(tool_name, None)
            _tool_to_category.pop(tool_name, None)

    for session in _sessions.values():
        session["expanded"] = {c for c in session.get("expanded", set()) if c not in old_cat_ids}

    _external_categories = {}
    META_TOOLS.clear()
    META_TOOLS.extend(_build_meta_tools())


async def refresh_external_drawers(force=False):
    # Bug #4：刷新会先清空注册表再逐个重建，期间有多个 await；并发刷新会让其他请求读到
    # 半重建的注册表。用锁把整个刷新串行化。
    async with _refresh_lock:
        await _refresh_external_drawers_impl(force)


async def _refresh_external_drawers_impl(force=False):
    """Register external MCP servers as dynamic tool drawer categories."""
    global _external_config_hash

    try:
        from config import get_config

        servers = _normalize_external_servers(await get_config("mcp_servers"))
        config_hash = hashlib.sha256(
            json.dumps(servers, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        if not force and config_hash == _external_config_hash:
            return

        _unregister_external_drawers()
        _external_config_hash = config_hash

        if not servers:
            return

        from database import get_embedding
        from mcp_client import get_tools_for_servers

        used_cat_ids = set(CATEGORIES.keys())
        reserved_tool_names = set(TOOL_SCHEMAS.keys())
        used_tool_names = set(TOOL_SCHEMAS.keys())
        registered = 0

        for server in servers:
            cat_id = _external_cat_id(server, used_cat_ids)
            used_cat_ids.add(cat_id)

            try:
                openai_tools, raw_tool_map = await get_tools_for_servers([server])
            except Exception as e:
                print(f"\u26a0\ufe0f  外部 MCP [{server['name']}] 工具拉取失败，跳过：{e}")
                continue

            if not openai_tools:
                print(f"\u26a0\ufe0f  外部 MCP [{server['name']}] 没有可注册工具，跳过")
                continue

            tool_names = []
            tool_map = {}
            origin_names = []
            seen_descriptions = set()
            condensed_descriptions = []

            for schema in openai_tools:
                func = schema.get("function") or {}
                origin_name = func.get("name")
                if not origin_name:
                    continue

                has_conflict = origin_name in reserved_tool_names or origin_name in used_tool_names
                exposed_name = (
                    _prefixed_external_tool_name(cat_id, origin_name, used_tool_names)
                    if has_conflict else origin_name
                )
                used_tool_names.add(exposed_name)

                TOOL_SCHEMAS[exposed_name] = _clone_tool_schema(schema, exposed_name)
                _tool_to_category[exposed_name] = cat_id
                tool_names.append(exposed_name)

                server_info = raw_tool_map.get(origin_name, {})
                tool_map[exposed_name] = {
                    "type": "external_mcp",
                    "server_url": server_info.get("url") or server["url"],
                    "url": server_info.get("url") or server["url"],
                    "transport": server_info.get("transport") or server["transport"],
                    "server_name": server_info.get("server_name") or server["name"],
                    "origin_name": origin_name,
                }

                desc = (func.get("description") or "").strip()
                desc = re.sub(r"\s+", " ", desc)
                if desc and desc not in seen_descriptions:
                    condensed_descriptions.append(desc[:120])
                    seen_descriptions.add(desc)
                origin_names.append(origin_name)

            if not tool_names:
                continue

            tool_list = "、".join(origin_names)
            desc_text = "；".join(condensed_descriptions) or "外部 MCP 工具"
            description = _truncate_text(
                f"{server['name']}：{desc_text}。用户提到{server['name']}或需要{tool_list}相关操作时需要。",
                500,
            )
            keywords = _external_keywords(server["name"], origin_names)

            CATEGORIES[cat_id] = {
                "label": server["name"],
                "description": description,
                "tool_names": tool_names,
                "external": True,
                "keywords": keywords,
            }
            _external_categories[cat_id] = {
                "label": server["name"],
                "description": description,
                "tool_names": tool_names,
                "tool_map": tool_map,
                "server": server,
                "server_name": server["name"],
            }

            try:
                emb = await get_embedding(description)
                if emb:
                    _category_embeddings[cat_id] = emb
            except Exception as e:
                print(f"\u26a0\ufe0f  外部 MCP [{server['name']}] 类别 embedding 失败，走关键词降级：{e}")

            registered += 1

        META_TOOLS.clear()
        META_TOOLS.extend(_build_meta_tools())
        if registered:
            print(f"\U0001f5c3\ufe0f  外部 MCP 抽屉：注册 {registered} 个动态类别")

    except Exception as e:
        print(f"\u26a0\ufe0f  外部 MCP 抽屉刷新失败，保留现有抽屉：{e}")


async def force_refresh_external_drawers():
    global _external_config_hash
    _external_config_hash = None
    await refresh_external_drawers(force=True)


async def _get_pinned_external_categories():
    if not _external_categories:
        return set()
    try:
        from config import get_config
        raw = await get_config("mcp_manual_ids")
        manual_ids = json.loads(raw or "[]")
    except Exception:
        manual_ids = []
    if not isinstance(manual_ids, list):
        return set()

    wanted = {str(x).strip().lower() for x in manual_ids if str(x).strip()}
    if not wanted:
        return set()

    pinned = set()
    for cat_id, meta in _external_categories.items():
        names = {
            cat_id.lower(),
            str(meta.get("label", "")).lower(),
            str(meta.get("server_name", "")).lower(),
        }
        if names & wanted:
            pinned.add(cat_id)
    return pinned

async def init_drawer():
    """初始化工具抽屉（自动发现工具 + 预计算类别 embedding）。

    幂等：已初始化时直接返回，重复调用零成本。这让 lifespan 启动时
    没初始化（tool_drawer_enabled=false）、运行时改成 true 也能 lazy init，
    无需重启进程。
    """
    global _category_embeddings, _initialized
    if _initialized:
        return
    from database import get_embeddings_batch

    # Step 1: Auto-discover tools from mcp_server.py
    _auto_discover_mcp_tools()

    if not CATEGORIES:
        print("\u26a0\ufe0f  工具抽屉：没有发现任何工具类别")
        _initialized = True
        return

    # Step 2: Compute category embeddings
    cat_ids = list(CATEGORIES.keys())
    descriptions = [CATEGORIES[c]["description"] for c in cat_ids]
    print(f"\U0001f5c3\ufe0f  工具抽屉：正在预计算 {len(cat_ids)} 个类别的 embedding...")
    embeddings = await get_embeddings_batch(descriptions)
    success = 0
    for cat_id, emb in zip(cat_ids, embeddings):
        if emb:
            _category_embeddings[cat_id] = emb
            success += 1
    _initialized = True
    if success == len(cat_ids):
        print(f"\U0001f5c3\ufe0f  工具抽屉：{success} 个类别 embedding 就绪")
    elif success > 0:
        print(f"\U0001f5c3\ufe0f  工具抽屉：{success}/{len(cat_ids)} 就绪（部分降级）")
    else:
        print(f"\U0001f5c3\ufe0f  工具抽屉：embedding 全部失败，使用关键词降级")

    await refresh_external_drawers()

# ============================================================
# 8. Keyword Fallback
# ============================================================

def _keyword_match(user_message):
    matched = set()
    for cat_id, meta in CATEGORY_META.items():
        keywords = meta.get("keywords", [])
        if any(kw in user_message for kw in keywords):
            matched.add(cat_id)
    return matched

# ============================================================
# 9. Session State
# ============================================================

_sessions = {}
_SESSION_TTL = 7200
_AUTO_COLLAPSE_ROUNDS = 3

def _get_session(session_id):
    now = time.time()
    if session_id not in _sessions:
        _sessions[session_id] = {"expanded": set(), "rounds_no_use": 0, "last_active": now}
    s = _sessions[session_id]
    s["last_active"] = now
    return s

def _cleanup_sessions():
    now = time.time()
    # Phase 1: 删真过期的
    expired = [sid for sid, s in _sessions.items() if now - s["last_active"] > _SESSION_TTL]
    for sid in expired:
        del _sessions[sid]
    # Phase 2: 还超 200 就按 LRU 删一半
    if len(_sessions) > 200:
        oldest = sorted(_sessions.items(), key=lambda kv: kv[1]["last_active"])
        for sid, _ in oldest[:len(_sessions) // 2]:
            del _sessions[sid]

# ============================================================
# 10. Core Routing
# ============================================================

SIMILARITY_THRESHOLD = 0.45


def _limit_external_matches(external_candidates, keyword_hits, scores, max_open):
    if max_open <= 0:
        return set()
    if len(external_candidates) <= max_open:
        return set(external_candidates)

    def _rank(cat_id):
        keyword_bonus = 1.0 if cat_id in keyword_hits else 0.0
        return (keyword_bonus, scores.get(cat_id, 0.0))

    ranked = sorted(external_candidates, key=_rank, reverse=True)
    kept = set(ranked[:max_open])
    dropped = [c for c in ranked[max_open:]]
    if dropped:
        dropped_str = ", ".join(f"{c}={scores.get(c, 0.0):.3f}" for c in dropped)
        print(f"\U0001f5c3\ufe0f  外部抽屉同开限流：保留 {kept}，收起 {dropped_str}")
    return kept


async def route_tools(user_message, session_id, user_embedding=None, mem_enabled=True, search_enabled=False, project_id=None, mcp_mode="auto"):
    from database import cosine_similarity
    try:
        from config import get_config_float, get_config_int
        ext_threshold = await get_config_float("ext_drawer_threshold", fallback=0.40)
        ext_max_open = max(0, await get_config_int("ext_drawer_max_open", fallback=3))
    except Exception:
        ext_threshold = 0.40
        ext_max_open = 3

    mode = str(mcp_mode or "auto").strip().lower()
    if mode not in ("off", "auto", "manual"):
        mode = "auto"
    external_auto = mode == "auto"
    external_pinned = mode in ("auto", "manual")

    await refresh_external_drawers()
    # Bug #4：在锁内对注册表做一次快照，避免遍历期间被并发刷新改成半成品
    async with _refresh_lock:
        cat_embeddings_snapshot = dict(_category_embeddings)
    if len(_sessions) > 200:
        _cleanup_sessions()

    session = _get_session(session_id)
    session["mcp_mode"] = mode
    matched_categories = set()
    pinned_external = await _get_pinned_external_categories() if external_pinned else set()
    external_keyword_hits = _external_keyword_match(user_message) if external_auto else set()
    external_scores = {}

    if user_embedding and cat_embeddings_snapshot:
        scores = {}
        for cat_id, cat_emb in cat_embeddings_snapshot.items():
            is_external = cat_id in _external_categories
            if is_external and not external_auto:
                continue
            score = cosine_similarity(user_embedding, cat_emb)
            scores[cat_id] = score
            if is_external:
                external_scores[cat_id] = score
            threshold = ext_threshold if is_external else SIMILARITY_THRESHOLD
            if score >= threshold:
                matched_categories.add(cat_id)
        top3 = sorted(scores.items(), key=lambda x: -x[1])[:3]
        top3_str = ", ".join(f"{c}={s:.3f}" for c, s in top3)
        if matched_categories:
            print(f"\U0001f5c3\ufe0f  抽屉路由：命中 {matched_categories}（top3: {top3_str}）")
        else:
            print(f"\U0001f5c3\ufe0f  抽屉路由：未命中（top3: {top3_str}）")
        internal_keyword_hits = _keyword_match(user_message)
        fallback_hits = {c for c in internal_keyword_hits if c not in cat_embeddings_snapshot}
        if fallback_hits:
            matched_categories |= fallback_hits
            print(f"\U0001f5c3\ufe0f  抽屉路由（关键词补位）：命中 {fallback_hits}")
    else:
        matched_categories = _keyword_match(user_message)
        if matched_categories:
            print(f"\U0001f5c3\ufe0f  抽屉路由（关键词降级）：命中 {matched_categories}")

    external_category_ids = set(_external_categories.keys())
    if external_auto:
        external_candidates = (matched_categories & external_category_ids) | external_keyword_hits
        if external_keyword_hits:
            print(f"\U0001f5c3\ufe0f  外部抽屉关键词命中：{external_keyword_hits}")
        kept_external = _limit_external_matches(external_candidates, external_keyword_hits, external_scores, ext_max_open)
        matched_categories = (matched_categories - external_category_ids) | kept_external
    else:
        matched_categories -= external_category_ids
        if external_category_ids:
            session["expanded"] -= external_category_ids

    # Filter by feature flags (also filter expanded)
    if not search_enabled:
        matched_categories.discard("search")
        session["expanded"].discard("search")
    if not mem_enabled:
        matched_categories.discard("memory")
        matched_categories.discard("conversation")
        session["expanded"].discard("memory")
        session["expanded"].discard("conversation")

    active_categories = matched_categories | session["expanded"] | pinned_external

    # Auto-collapse
    if session["expanded"] and not matched_categories:
        session["rounds_no_use"] += 1
        if session["rounds_no_use"] >= _AUTO_COLLAPSE_ROUNDS:
            print(f"\U0001f5c3\ufe0f  抽屉自动收回：{session['expanded']}")
            session["expanded"] = set()
            session["rounds_no_use"] = 0
            active_categories = matched_categories | pinned_external
    else:
        session["rounds_no_use"] = 0

    session["expanded"] = (active_categories - pinned_external).copy()

    # Assemble tool list
    openai_tools = []
    tool_map = {}
    for cat_id in active_categories:
        cat = CATEGORIES.get(cat_id)
        if not cat:
            continue
        for tool_name in cat["tool_names"]:
            schema = TOOL_SCHEMAS.get(tool_name)
            if not schema:
                continue
            openai_tools.append(schema)
            if tool_name.startswith("_gateway_"):
                route_info = {"type": "gateway_builtin", "handler": _infer_handler(tool_name)}
                if tool_name == "_gateway_search_conversations":
                    route_info["project_id"] = project_id
                tool_map[tool_name] = route_info
            elif cat.get("external"):
                ext_map = _external_categories.get(cat_id, {}).get("tool_map", {})
                tool_map[tool_name] = ext_map.get(tool_name, {
                    "type": "external_mcp",
                    "server_url": "",
                    "url": "",
                    "transport": "streamable_http",
                    "server_name": cat.get("label", cat_id),
                    "origin_name": tool_name,
                })
            else:
                tool_map[tool_name] = {"type": "drawer", "handler": tool_name}

    # Always include meta-tools
    for mt in META_TOOLS:
        openai_tools.append(mt)
        tool_map[mt["function"]["name"]] = {"type": "meta", "handler": "drawer_meta"}

    expanded_count = len(openai_tools) - len(META_TOOLS)
    if expanded_count > 0:
        print(f"\U0001f5c3\ufe0f  展开 {expanded_count} 个工具 + {len(META_TOOLS)} meta = {len(openai_tools)} total")
    else:
        print(f"\U0001f5c3\ufe0f  无工具展开，仅 {len(META_TOOLS)} 个 meta-tool")

    return openai_tools, tool_map

def _infer_handler(tool_name):
    if "web_search" in tool_name: return "web_search"
    if "search_conversations" in tool_name: return "search_conversations"
    if "reminder" in tool_name: return "reminder"
    return tool_name

# ============================================================
# 11. Meta-tool Execution
# ============================================================

async def handle_meta_tool(tool_name, args, session_id):
    session = _get_session(session_id)
    mode = str(session.get("mcp_mode") or "auto").strip().lower()
    if mode not in ("off", "auto", "manual"):
        mode = "auto"
    pinned_external = await _get_pinned_external_categories() if mode == "manual" else set()
    if tool_name == "list_tool_categories":
        cats = []
        for cat_id, cat in CATEGORIES.items():
            is_external = bool(cat.get("external"))
            if is_external:
                if mode == "off":
                    continue
                if mode == "manual" and cat_id not in pinned_external:
                    continue
            cats.append({
                "id": cat_id,
                "label": cat.get("label", cat_id),
                "description": cat.get("description", ""),
                "tool_count": len(cat.get("tool_names", [])),
                "external": is_external,
            })
        return json.dumps(cats, ensure_ascii=False)

    if tool_name == "_drawer_request_tools":
        category = args.get("category", "")
        if category not in CATEGORIES:
            visible_categories = []
            for cat_id, cat in CATEGORIES.items():
                if cat.get("external"):
                    if mode == "off":
                        continue
                    if mode == "manual" and cat_id not in pinned_external:
                        continue
                visible_categories.append(cat_id)
            return f"未知类别：{category}。可用：{', '.join(visible_categories)}"
        cat = CATEGORIES[category]
        if cat.get("external"):
            if mode == "off":
                return "外部 MCP 工具当前已被用户禁用，无法展开"
            if mode == "manual" and category not in pinned_external:
                return "该外部工具未在手动列表中启用"
        session["expanded"].add(category)
        session["rounds_no_use"] = 0
        names = ", ".join(cat["tool_names"])
        print(f"\U0001f5c3\ufe0f  手动展开：{category}（{names}）")
        return f"已展开『{cat['label']}』类工具：{names}。下一轮对话即可使用。"

    if tool_name == "_drawer_return_tools":
        if session["expanded"]:
            returned = ", ".join(CATEGORIES[c]["label"] for c in session["expanded"] if c in CATEGORIES)
            print(f"\U0001f5c3\ufe0f  主动归还：{session['expanded']}")
            session["expanded"] = set()
            session["rounds_no_use"] = 0
            return f"已归还工具：{returned}。"
        return "当前没有展开的工具。"

    return f"未知meta-tool：{tool_name}"

# ============================================================
# 12. Drawer Tool Execution
# ============================================================

async def execute_drawer_tool(tool_name, arguments):
    extra = {}
    try:
        import mcp_server
        func = getattr(mcp_server, tool_name, None)
        if not func:
            return f"[tool_error] tool_not_found: {tool_name}", extra
        result = await func(**arguments)
        return result, extra
    except TypeError as e:
        msg = str(e)
        import re as _re
        m = _re.search(r"missing \d+ required.*?: '(\w+)'", msg)
        if m:
            return f"[tool_error] {tool_name}: missing required arg '{m.group(1)}'", extra
        m = _re.search(r"unexpected keyword argument '(\w+)'", msg)
        if m:
            return f"[tool_error] {tool_name}: unknown arg '{m.group(1)}'", extra
        return f"[tool_error] {tool_name}: argument mismatch", extra
    except Exception as e:
        print(f"\u274c drawer\u5de5\u5177 {tool_name} \u6267\u884c\u5931\u8d25: {e}")
        import traceback
        traceback.print_exc()
        return f"[tool_error] {tool_name}: execution failed", extra

# ============================================================
# 13. Helpers
# ============================================================

def record_tool_use(session_id, tool_name):
    if session_id in _sessions:
        _sessions[session_id]["rounds_no_use"] = 0

def get_drawer_stats():
    return {
        "initialized": _initialized,
        "categories": len(CATEGORIES),
        "tools": len(TOOL_SCHEMAS),
        "embeddings_ready": len(_category_embeddings),
        "active_sessions": len(_sessions),
        "threshold": SIMILARITY_THRESHOLD,
        "external_categories": len(_external_categories),
    }
