"""Core no-network regression checks for the permanent tool drawer."""

import asyncio
import inspect
import json
import os
import sys
import types
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tool_drawer as td

RETURN_MESSAGE = "工具抽屉已是常驻模式：本会话展开的工具会一直保持可用，无需归还。"
REMINDER_NAMES = {
    "_gateway_create_reminder",
    "_gateway_list_reminders",
    "_gateway_complete_reminder",
    "_gateway_delete_reminder",
}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def tool_names(tools):
    return [
        item.get("function", {}).get("name")
        for item in tools
        if item.get("function", {}).get("name")
    ]


def ensure_categories():
    if not td.CATEGORIES:
        td._auto_discover_mcp_tools()
    check("reminder" in td.CATEGORIES, "reminder category must be discoverable")


async def check_permanent_expansion():
    td._sessions.clear()
    session = td._get_session("stability-core")
    session["expanded"] = ["memory"]
    session["rounds_no_use"] = 7

    td._append_expanded(session, "search")
    td._append_expanded(session, "memory")
    td._append_expanded_many(session, ["reminder", "search", "conversation"])
    check(
        session["expanded"] == ["memory", "search", "reminder", "conversation"],
        "expanded categories must append in first-seen order without duplicates",
    )

    expanded_before = list(session["expanded"])
    rounds_before = session["rounds_no_use"]
    result = await td.handle_meta_tool("_drawer_return_tools", {}, "stability-core")
    check(result == RETURN_MESSAGE, "legacy return must use the compatibility message")
    check(session["expanded"] == expanded_before, "legacy return must not shrink expanded")
    check(session["rounds_no_use"] == rounds_before, "legacy return must not change rounds_no_use")


async def check_request_context_gates():
    sid = "shared-request-context"
    td._sessions.pop(sid, None)
    allowed_approved = set()
    blocked_approved = set()

    allowed_result, blocked_result = await asyncio.gather(
        td.handle_meta_tool(
            "_drawer_request_tools",
            {"category": "reminder"},
            sid,
            approved_categories=allowed_approved,
        ),
        td.handle_meta_tool(
            "_drawer_request_tools",
            {"category": "reminder"},
            sid,
            disabled_categories={"reminder"},
            approved_categories=blocked_approved,
        ),
    )
    check(allowed_result.startswith("已展开"), "allowed request must expand reminder")
    check(blocked_result == "该类工具当前已被用户设置关闭，无法展开", "disabled request must be rejected")
    check(allowed_approved == {"reminder"}, "allowed request must record its own approved category")
    check(not blocked_approved, "disabled concurrent request must not approve reminder for same-round merge")

    listed = json.loads(await td.handle_meta_tool(
        "list_tool_categories", {}, sid, disabled_categories={"reminder"}
    ))
    check("reminder" not in {item["id"] for item in listed}, "disabled category must be hidden from listing")
    unknown = await td.handle_meta_tool(
        "_drawer_request_tools",
        {"category": "missing-category"},
        sid,
        disabled_categories={"reminder"},
    )
    check("reminder" not in unknown, "unknown-category availability text must hide disabled categories")

    default_sid = "default-compatible"
    td._sessions.pop(default_sid, None)
    default_result = await td.handle_meta_tool(
        "_drawer_request_tools", {"category": "reminder"}, default_sid
    )
    check(default_result.startswith("已展开"), "omitting request context must preserve current default behavior")
    check(td._get_session(default_sid)["expanded"] == ["reminder"], "default request must expand reminder")


async def check_mcp_mode_isolation():
    sid = "shared-mcp-mode"
    ext_id = "ext_stability_mock"
    td._sessions.pop(sid, None)
    td.CATEGORIES[ext_id] = {
        "label": "Mock MCP",
        "description": "mock external tools",
        "tool_names": ["mock_external_tool"],
        "external": True,
    }
    try:
        off_list, auto_list = await asyncio.gather(
            td.handle_meta_tool("list_tool_categories", {}, sid, mcp_mode="off"),
            td.handle_meta_tool("list_tool_categories", {}, sid, mcp_mode="auto"),
        )
        check(ext_id not in {item["id"] for item in json.loads(off_list)}, "off context must hide external category")
        check(ext_id in {item["id"] for item in json.loads(auto_list)}, "auto context must expose external category")

        off_approved = set()
        auto_approved = set()
        off_result, auto_result = await asyncio.gather(
            td.handle_meta_tool(
                "_drawer_request_tools", {"category": ext_id}, sid,
                mcp_mode="off", approved_categories=off_approved,
            ),
            td.handle_meta_tool(
                "_drawer_request_tools", {"category": ext_id}, sid,
                mcp_mode="auto", approved_categories=auto_approved,
            ),
        )
        check(off_result == "外部 MCP 工具当前已被用户禁用，无法展开", "off request must reject external category")
        check(not off_approved, "off request must not approve external category")
        check(auto_result.startswith("已展开"), "auto request must allow external category")
        check(auto_approved == {ext_id}, "auto request must keep its own approval")
    finally:
        td.CATEGORIES.pop(ext_id, None)
        td._remove_expanded(td._get_session(sid), {ext_id})


async def check_reminder_route_gate():
    fake_config = types.ModuleType("config")
    fake_database = types.ModuleType("database")

    async def get_config_float(_key, fallback=0.0):
        return fallback

    async def get_config_int(_key, fallback=0):
        return fallback

    fake_config.get_config_float = get_config_float
    fake_config.get_config_int = get_config_int
    fake_database.cosine_similarity = lambda _a, _b: 0.0

    sid = "reminder-route-gate"
    td._sessions.pop(sid, None)
    with patch.dict(sys.modules, {"config": fake_config, "database": fake_database}):
        enabled_tools, enabled_map = await td.route_tools(
            "每天提醒我吃药",
            sid,
            mem_enabled=False,
            search_enabled=False,
            mcp_mode="off",
            reminder_tools_enabled=True,
        )
        enabled_names = {tool["function"]["name"] for tool in enabled_tools}
        check("_gateway_create_reminder" in enabled_names, "reminder must remain available while memory is paused")
        enabled_context = enabled_map["_drawer_request_tools"]
        check("reminder" not in enabled_context["disabled_categories"], "enabled route must not disable reminder")
        check(
            {"memory", "conversation"}.issubset(enabled_context["disabled_categories"]),
            "memory pause must stay separate from reminder availability",
        )

        disabled_tools, disabled_map = await td.route_tools(
            "每天提醒我吃药",
            sid,
            mem_enabled=False,
            search_enabled=False,
            mcp_mode="off",
            reminder_tools_enabled=False,
        )
        disabled_names = {tool["function"]["name"] for tool in disabled_tools}
        check("_gateway_create_reminder" not in disabled_names, "disabled route must remove reminder tools")
        disabled_context = disabled_map["_drawer_request_tools"]
        check("reminder" in disabled_context["disabled_categories"], "meta context must carry reminder gate")
        blocked = await td.handle_meta_tool(
            "_drawer_request_tools",
            {"category": "reminder"},
            sid,
            disabled_categories=disabled_context["disabled_categories"],
            mcp_mode=disabled_context["mcp_mode"],
            pinned_external=disabled_context["pinned_external"],
        )
        check(blocked == "该类工具当前已被用户设置关闭，无法展开", "manual request must respect route gate")
        check("reminder" not in td._get_session(sid)["expanded"], "disabled route must keep reminder collapsed")


async def check_fallback_builder_gates():
    ext_id = "ext_fallback_contract"
    ext_tool = "fallback_external_probe"
    ext_schema = {
        "type": "function",
        "function": {
            "name": ext_tool,
            "description": "fallback external probe",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    td.TOOL_SCHEMAS[ext_tool] = ext_schema
    td._tool_to_category[ext_tool] = ext_id
    td.CATEGORIES[ext_id] = {
        "label": "Fallback MCP",
        "description": "fallback external probe",
        "tool_names": [ext_tool],
        "external": True,
    }
    td._external_categories[ext_id] = {
        "label": "Fallback MCP",
        "server_name": "Fallback MCP",
        "tool_names": [ext_tool],
        "tool_map": {
            ext_tool: {
                "type": "external_mcp",
                "url": "https://invalid.test/mcp",
                "transport": "streamable_http",
                "server_name": "Fallback MCP",
                "origin_name": ext_tool,
            }
        },
    }
    try:
        blocked_tools, blocked_map = td.build_full_fallback_tools(
            search_enabled=False,
            mem_enabled=False,
            reminder_tools_enabled=False,
            mcp_mode="off",
            project_id="project-hidden",
        )
        blocked_names = tool_names(blocked_tools)
        meta_names = tool_names(td.META_TOOLS)
        check(blocked_names[:len(meta_names)] == meta_names, "fallback must keep meta tools as the stable prefix")
        check(len(blocked_names) == len(set(blocked_names)), "fallback must not duplicate tool schemas")
        forbidden = {
            name for name, category in td._tool_to_category.items()
            if category in {"search", "memory", "conversation", "reminder"}
        }
        check(not (set(blocked_names) & forbidden), "fallback must filter every disabled internal category")
        check(ext_tool not in blocked_names, "mcp_mode=off must hide fallback external tools")
        check(
            {"calendar", "dream", "profile"} <= {
                td._tool_to_category.get(name) for name in blocked_names
            },
            "fallback must retain every allowed internal base category",
        )
        meta_context = blocked_map["_drawer_request_tools"]
        check(
            set(meta_context["disabled_categories"]) == {"search", "memory", "conversation", "reminder"},
            "fallback meta context must freeze every request-level disabled category",
        )
        check(meta_context["mcp_mode"] == "off", "fallback meta context must freeze MCP mode")

        manual_tools, manual_map = td.build_full_fallback_tools(
            search_enabled=False,
            mem_enabled=True,
            reminder_tools_enabled=False,
            mcp_mode="manual",
            pinned_external={ext_id},
            project_id="project-42",
        )
        manual_names = tool_names(manual_tools)
        check(ext_tool in manual_names, "manual fallback must include a pinned external category")
        check("_gateway_web_search" not in manual_names, "manual fallback must keep disabled search hidden")
        check(REMINDER_NAMES.isdisjoint(manual_names), "manual fallback must keep disabled reminders hidden")
        check(
            manual_map["_gateway_search_conversations"]["project_id"] == "project-42",
            "fallback conversation search must retain the request project scope",
        )

        unpinned_tools, _ = td.build_full_fallback_tools(
            mcp_mode="manual",
            pinned_external=set(),
        )
        auto_tools, _ = td.build_full_fallback_tools(mcp_mode="auto")
        check(ext_tool not in tool_names(unpinned_tools), "manual fallback must hide unpinned external tools")
        check(ext_tool in tool_names(auto_tools), "auto fallback may expose registered external tools")
    finally:
        td.TOOL_SCHEMAS.pop(ext_tool, None)
        td._tool_to_category.pop(ext_tool, None)
        td.CATEGORIES.pop(ext_id, None)
        td._external_categories.pop(ext_id, None)


async def check_reserved_external_name():
    snapshots = {
        "schemas": dict(td.TOOL_SCHEMAS),
        "categories": dict(td.CATEGORIES),
        "tool_to_category": dict(td._tool_to_category),
        "external": dict(td._external_categories),
        "embeddings": dict(td._category_embeddings),
        "meta": list(td.META_TOOLS),
        "hash": td._external_config_hash,
    }
    fake_config = types.ModuleType("config")
    fake_database = types.ModuleType("database")
    fake_mcp = types.ModuleType("mcp_client")

    async def get_config(key):
        if key == "mcp_servers":
            return json.dumps([{
                "name": "reserved-name-test",
                "url": "https://invalid.test/mcp",
                "transport": "streamable_http",
                "enabled": True,
            }])
        return ""

    async def get_embedding(_text):
        return []

    async def get_tools_for_servers(_servers):
        schema = {
            "type": "function",
            "function": {
                "name": "_drawer_return_tools",
                "description": "must be renamed",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        return [schema], {
            "_drawer_return_tools": {
                "url": "https://invalid.test/mcp",
                "transport": "streamable_http",
                "server_name": "reserved-name-test",
            }
        }

    fake_config.get_config = get_config
    fake_database.get_embedding = get_embedding
    fake_mcp.get_tools_for_servers = get_tools_for_servers

    try:
        td._external_config_hash = None
        with patch.dict(sys.modules, {
            "config": fake_config,
            "database": fake_database,
            "mcp_client": fake_mcp,
        }):
            await td._refresh_external_drawers_impl(force=True)

        added_ids = set(td._external_categories) - set(snapshots["external"])
        check(len(added_ids) == 1, "mock external drawer must register exactly once")
        ext_id = next(iter(added_ids))
        exposed_names = td.CATEGORIES[ext_id]["tool_names"]
        check("_drawer_return_tools" not in exposed_names, "reserved meta name must never be exposed unchanged")
        check(len(exposed_names) == 1 and exposed_names[0].startswith("ext_"), "conflicting external name must be prefixed")
        exposed = exposed_names[0]
        check(
            td._external_categories[ext_id]["tool_map"][exposed]["origin_name"] == "_drawer_return_tools",
            "renamed external tool must retain its upstream origin name",
        )
    finally:
        td.TOOL_SCHEMAS.clear()
        td.TOOL_SCHEMAS.update(snapshots["schemas"])
        td.CATEGORIES.clear()
        td.CATEGORIES.update(snapshots["categories"])
        td._tool_to_category.clear()
        td._tool_to_category.update(snapshots["tool_to_category"])
        td._external_categories.clear()
        td._external_categories.update(snapshots["external"])
        td._category_embeddings.clear()
        td._category_embeddings.update(snapshots["embeddings"])
        td.META_TOOLS.clear()
        td.META_TOOLS.extend(snapshots["meta"])
        td._external_config_hash = snapshots["hash"]


def check_source_guards():
    meta_names = {item["function"]["name"] for item in td._build_meta_tools()}
    check("_drawer_return_tools" not in meta_names, "legacy return must not be model-visible")

    with open(os.path.join(ROOT, "tool_drawer.py"), encoding="utf-8") as f:
        drawer_source = f.read()
    with open(os.path.join(ROOT, "config.py"), encoding="utf-8") as f:
        config_source = f.read()
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        main_source = f.read()
    with open(os.path.join(ROOT, "admin-panel", "js", "config-schema.js"), encoding="utf-8") as f:
        admin_schema_source = f.read()
    with open(os.path.join(ROOT, "admin-panel", "js", "pages", "tools.js"), encoding="utf-8") as f:
        admin_tools_source = f.read()
    for source_name, source in (
        ("tool_drawer.py", drawer_source),
        ("config.py", config_source),
        ("admin config schema", admin_schema_source),
    ):
        check("_AUTO_COLLAPSE_ROUNDS" not in source, f"{source_name} must not contain auto-collapse constant")
        check("drawer_auto_collapse_enabled" not in source, f"{source_name} must not contain auto-collapse config")
    route_source = inspect.getsource(td.route_tools)
    handler_source = inspect.getsource(td.handle_meta_tool)
    check(
        'session["mcp_mode"]' not in route_source and "session['mcp_mode']" not in route_source,
        "route must not store request mcp_mode in shared session",
    )
    check(
        'session.get("mcp_mode")' not in handler_source and "session.get('mcp_mode')" not in handler_source,
        "handler must not read request mcp_mode from shared session",
    )
    check("_REMINDER_TRIGGER_KEYWORDS" not in main_source, "keyword-gated reminder registration must be removed")
    check("_need_reminder_tools" not in main_source, "per-message reminder decision must be removed")
    check("_expanded_before" not in main_source and "_expanded_after" not in main_source, "same-round merge must not diff shared session")
    check("approved_categories" in main_source, "same-round merge must use request-local approvals")
    check(
        'tool_map["_drawer_return_tools"] = {"type": "meta"' in main_source
        and 'tool_map.setdefault("_drawer_return_tools"' not in main_source,
        "legacy tombstone must force-overwrite the tool map",
    )
    check(
        "if not drawer_enabled and reminder_tools_enabled:" in main_source,
        "classic mode must register reminders from the global config instead of message keywords",
    )
    check("reminder_tools_enabled" in config_source, "backend config must register reminder switch")
    check("reminder_tools_enabled" in admin_schema_source, "admin schema must register reminder switch")
    check(
        admin_tools_source.index('id="reminder-cfg"') < admin_tools_source.index('id="cfg"'),
        "independent reminder group must render outside and before the drawer master container",
    )
    check("renderConfigPage('reminderTools'" in admin_tools_source, "tools page must render the independent reminder group")
    check(main_source.startswith('"""\nKiwi-Mem —'), "main.py must keep the Kiwi-Mem title sentinel")


async def main():
    ensure_categories()
    await check_permanent_expansion()
    await check_request_context_gates()
    await check_mcp_mode_isolation()
    await check_reminder_route_gate()
    await check_fallback_builder_gates()
    await check_reserved_external_name()
    check_source_guards()

    print("PASS: permanent drawer request isolation and reminder stability")


if __name__ == "__main__":
    asyncio.run(main())
