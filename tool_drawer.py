"""
tool_drawer.py - Vector Tool Drawer (Auto-Discovery)
=====================================================
启动时自动从 mcp_server.py 发现工具、提取 schema、归类。
新增工具只需在 mcp_server.py 写函数并加 [category: xxx] 标签。
"""

import ast
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

# ============================================================
# 4. Meta-tools (always available)
# ============================================================

def _build_meta_tools():
    cats = list(CATEGORIES.keys()) if CATEGORIES else list(CATEGORY_META.keys())
    return [
        {"type":"function","function":{"name":"_drawer_request_tools","description":"手动请求展开工具类别。可用：" + "/".join(cats),"parameters":{"type":"object","properties":{"category":{"type":"string","enum":cats,"description":"工具类别ID"}},"required":["category"]}}},
        {"type":"function","function":{"name":"_drawer_return_tools","description":"归还当前展开的工具，释放token空间。","parameters":{"type":"object","properties":{}}}},
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

async def route_tools(user_message, session_id, user_embedding=None, mem_enabled=True, search_enabled=False, project_id=None):
    from database import cosine_similarity
    if len(_sessions) > 200:
        _cleanup_sessions()

    session = _get_session(session_id)
    matched_categories = set()

    if user_embedding and _category_embeddings:
        scores = {}
        for cat_id, cat_emb in _category_embeddings.items():
            score = cosine_similarity(user_embedding, cat_emb)
            scores[cat_id] = score
            if score >= SIMILARITY_THRESHOLD:
                matched_categories.add(cat_id)
        top3 = sorted(scores.items(), key=lambda x: -x[1])[:3]
        top3_str = ", ".join(f"{c}={s:.3f}" for c, s in top3)
        if matched_categories:
            print(f"\U0001f5c3\ufe0f  抽屉路由：命中 {matched_categories}（top3: {top3_str}）")
        else:
            print(f"\U0001f5c3\ufe0f  抽屉路由：未命中（top3: {top3_str}）")
    else:
        matched_categories = _keyword_match(user_message)
        if matched_categories:
            print(f"\U0001f5c3\ufe0f  抽屉路由（关键词降级）：命中 {matched_categories}")

    # Filter by feature flags (also filter expanded)
    if not search_enabled:
        matched_categories.discard("search")
        session["expanded"].discard("search")
    if not mem_enabled:
        matched_categories.discard("memory")
        matched_categories.discard("conversation")
        session["expanded"].discard("memory")
        session["expanded"].discard("conversation")

    active_categories = matched_categories | session["expanded"]

    # Auto-collapse
    if session["expanded"] and not matched_categories:
        session["rounds_no_use"] += 1
        if session["rounds_no_use"] >= _AUTO_COLLAPSE_ROUNDS:
            print(f"\U0001f5c3\ufe0f  抽屉自动收回：{session['expanded']}")
            session["expanded"] = set()
            session["rounds_no_use"] = 0
            active_categories = matched_categories
    else:
        session["rounds_no_use"] = 0

    session["expanded"] = active_categories.copy()

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
            else:
                tool_map[tool_name] = {"type": "drawer", "handler": tool_name}

    # Always include meta-tools
    for mt in META_TOOLS:
        openai_tools.append(mt)
        tool_map[mt["function"]["name"]] = {"type": "meta", "handler": "drawer_meta"}

    expanded_count = len(openai_tools) - len(META_TOOLS)
    if expanded_count > 0:
        print(f"\U0001f5c3\ufe0f  展开 {expanded_count} 个工具 + 2 meta = {len(openai_tools)} total")
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
    if tool_name == "_drawer_request_tools":
        category = args.get("category", "")
        if category not in CATEGORIES:
            return f"未知类别：{category}。可用：{', '.join(CATEGORIES.keys())}"
        session["expanded"].add(category)
        session["rounds_no_use"] = 0
        cat = CATEGORIES[category]
        names = ", ".join(cat["tool_names"])
        print(f"\U0001f5c3\ufe0f  手动展开：{category}（{names}）")
        return f"已展开「{cat['label']}」类工具：{names}。下一轮对话即可使用。"

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
    }
