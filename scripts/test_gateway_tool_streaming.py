"""Local ASGI white-box checks for tool-loop drawer stability.

The test builds a real ASGITransport client first, then replaces only the
upstream HTTP client used inside the gateway. It never opens a database or
network connection.
"""

import ast
import asyncio
import contextvars
import copy
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import httpx

import config as config_module
import main as gateway
import tool_drawer as td


RETURN_MESSAGE = "工具抽屉已是常驻模式：本会话展开的工具会一直保持可用，无需归还。"
REMINDER_NAMES = {
    "_gateway_create_reminder",
    "_gateway_list_reminders",
    "_gateway_complete_reminder",
    "_gateway_delete_reminder",
}
REQUEST_CONFIG = contextvars.ContextVar("gateway_test_request_config", default={})
ACTIVE_UPSTREAM = None
MCP_BATCH_CALLS = 0


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def case_tool_loop_limit_source_contract():
    tree = ast.parse((Path(ROOT) / "main.py").read_text(encoding="utf-8"))
    tool_loop = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_stream_with_tools"
    )
    values = [
        node.value.value
        for node in ast.walk(tool_loop)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "max_rounds" for target in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    check(values == [30], "tool-loop max_rounds must remain exactly 30")


def tool_call(name, arguments=None, call_id=None):
    return {
        "id": call_id or f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments or {}, ensure_ascii=False)},
    }


def tool_response(*calls):
    return {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": None, "tool_calls": list(calls)},
            "finish_reason": "tool_calls",
        }]
    }


def final_response(text):
    return {
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


def request_key(messages):
    for message in messages or []:
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
    raise AssertionError("captured upstream body has no user request key")


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = copy.deepcopy(payload)
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return copy.deepcopy(self._payload)


class UpstreamController:
    def __init__(self):
        self.plans = {}
        self.captured = defaultdict(list)

    def add_plan(self, key, *responses):
        self.plans[key] = [copy.deepcopy(item) for item in responses]

    async def post(self, _url, headers=None, json=None):
        body = copy.deepcopy(json or {})
        key = request_key(body.get("messages"))
        self.captured[key].append(body)
        plan = self.plans.get(key)
        check(plan is not None, f"no fake-upstream plan for {key!r}")
        check(plan, f"fake-upstream plan exhausted for {key!r}")
        return FakeResponse(plan.pop(0))

    def assert_consumed(self, key):
        check(not self.plans.get(key), f"fake-upstream plan still has responses for {key!r}")


class FakeUpstreamClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        check(ACTIVE_UPSTREAM is not None, "fake upstream controller is not installed")
        return await ACTIVE_UPSTREAM.post(url, headers=headers, json=json)


async def fake_get_config_bool(key, fallback=False):
    values = REQUEST_CONFIG.get()
    if key == "memory_enabled":
        return False
    if key == "tool_drawer_enabled":
        return bool(values.get("drawer_enabled", False))
    if key == "reminder_tools_enabled":
        return bool(values.get("reminder_tools_enabled", False))
    if key in ("prompt_cache_enabled", "dream_enabled"):
        return False
    return fallback


async def fake_get_config(key):
    if key == "mcp_mode":
        return "off"
    if key == "default_chat_model":
        return "test/model"
    if key == "mcp_servers":
        return ""
    if key == "mcp_manual_ids":
        return "[]"
    return ""


async def fake_get_config_float(_key, fallback=0.0):
    return fallback


async def fake_get_config_int(_key, fallback=0):
    return fallback


async def fake_provider(_model, provider_model_id=None):
    return {
        "model_id": "test/model",
        "api_key": "test-key",
        "api_format": "openai",
        "api_base_url": "https://upstream.invalid/v1",
        "provider_name": "local-fake",
    }


async def fake_init_drawer():
    return None


async def fake_execute_drawer_tool(tool_name, arguments):
    check(tool_name == "probe_tool", f"unexpected drawer tool execution: {tool_name}")
    return json.dumps({"ok": True, "echo": arguments}, ensure_ascii=False), {}


async def fake_finalize(*_args, **_kwargs):
    return {"action": "skip"}


async def fake_get_tools_for_servers(_servers):
    schema = {
        "type": "function",
        "function": {
            "name": "request_mcp_probe",
            "description": "local request-body MCP sentinel",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    return [schema], {
        "request_mcp_probe": {
            "url": "https://mcp.invalid/endpoint",
            "transport": "streamable_http",
            "server_name": "local-request-mcp",
        }
    }


async def fake_call_tools_batch(_calls, _tool_map):
    global MCP_BATCH_CALLS
    MCP_BATCH_CALLS += 1
    return {}


def gateway_request(key, session_id, *, mcp_servers=None):
    body = {
        "model": "test/model",
        "messages": [{"role": "user", "content": key}],
        "stream": True,
        "skip_system_prompt": True,
        "conversation_id": session_id,
        "mcp_mode": "off",
        "temperature": 0,
    }
    if mcp_servers is not None:
        body["mcp_servers"] = mcp_servers
    return body


async def post_gateway(client, key, session_id, config, *, mcp_servers=None):
    token = REQUEST_CONFIG.set(dict(config))
    try:
        response = await client.post(
            "/v1/chat/completions",
            json=gateway_request(key, session_id, mcp_servers=mcp_servers),
        )
    finally:
        REQUEST_CONFIG.reset(token)
    check(response.status_code == 200, f"gateway returned {response.status_code}: {response.text}")
    check("data: [DONE]" in response.text, "gateway stream must terminate with [DONE]")
    return response


def names_for(body):
    return [item["function"]["name"] for item in body.get("tools", [])]


def streamed_text(response):
    chunks = []
    for line in response.text.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        payload = json.loads(line[6:])
        choices = payload.get("choices") or []
        if choices:
            chunks.append(choices[0].get("delta", {}).get("content", ""))
    return "".join(chunks)


def assert_only_appends(captured):
    name_lists = [names_for(body) for body in captured]
    for names in name_lists:
        check("_drawer_return_tools" not in names, "legacy tombstone must never enter upstream tools schema")
    for previous, current in zip(name_lists, name_lists[1:]):
        check(len(current) >= len(previous), "upstream tools must never shrink")
        check(current[:len(previous)] == previous, "upstream tool ordering must keep the prior list as a prefix")
    return name_lists


async def case_normal_four_rounds(client, controller):
    key = "normal-four-rounds"
    sid = "stream-normal"
    td._sessions.pop(sid, None)
    controller.add_plan(
        key,
        tool_response(tool_call("_drawer_request_tools", {"category": "probe"}, "normal-request")),
        tool_response(tool_call("probe_tool", {"value": 7}, "normal-probe")),
        tool_response(tool_call("_drawer_return_tools", {}, "normal-return")),
        final_response("normal final"),
    )

    response = await post_gateway(
        client,
        key,
        sid,
        {"drawer_enabled": True, "reminder_tools_enabled": True},
    )
    controller.assert_consumed(key)
    captured = controller.captured[key]
    check(len(captured) == 4, "normal scenario must make four upstream rounds")
    name_lists = assert_only_appends(captured)
    check("probe_tool" not in name_lists[0], "probe must start collapsed")
    check("probe_tool" in name_lists[1], "approved category must be available in the same response loop")
    check(name_lists[1] == name_lists[2] == name_lists[3], "tools must stay stable after the one allowed append")
    check(RETURN_MESSAGE in response.text, "legacy return call must receive the compatibility message")
    session = td._get_session(sid)
    check("probe" in session["expanded"], "legacy return must preserve expanded categories")
    check("_drawer_return_tools" not in td.get_directory_text(), "directory must not instruct models to return tools")


async def case_long_valid_loop_and_hard_stop(client, controller):
    release_key = "long-release"
    release_sid = "stream-long-release"
    td._sessions.pop(release_sid, None)
    release_rounds = [
        tool_response(tool_call("_drawer_return_tools", {}, f"long-release-{index}"))
        for index in range(1, 17)
    ]
    controller.add_plan(release_key, *release_rounds, final_response("long valid loop complete"))

    released = await post_gateway(
        client,
        release_key,
        release_sid,
        {"drawer_enabled": True, "reminder_tools_enabled": True},
    )
    controller.assert_consumed(release_key)
    check(streamed_text(released) == "long valid loop complete", "16 valid tool rounds must reach the final answer")
    check(len(controller.captured[release_key]) == 17, "16 tool rounds plus final answer must use 17 model rounds")

    cap_key = "hard-stop"
    cap_sid = "stream-hard-stop"
    td._sessions.pop(cap_sid, None)
    cap_rounds = [
        tool_response(tool_call("_drawer_return_tools", {}, f"hard-stop-{index}"))
        for index in range(1, 31)
    ]
    controller.add_plan(cap_key, *cap_rounds)

    capped = await post_gateway(
        client,
        cap_key,
        cap_sid,
        {"drawer_enabled": True, "reminder_tools_enabled": True},
    )
    controller.assert_consumed(cap_key)
    check(len(controller.captured[cap_key]) == 30, "tool-loop hard stop must remain exactly 30 model rounds")
    check("工具调用轮次过多，已停止" in streamed_text(capped), "round 30 must still trigger the safety stop")


async def case_classic_legacy_return(client, controller):
    key = "classic-legacy-return"
    sid = "stream-classic"
    td._sessions.pop(sid, None)
    session = td._get_session(sid)
    session["expanded"] = ["memory"]
    session["rounds_no_use"] = 9
    controller.add_plan(
        key,
        tool_response(tool_call("_drawer_return_tools", {}, "classic-return")),
        final_response("classic final"),
    )

    response = await post_gateway(
        client,
        key,
        sid,
        {"drawer_enabled": False, "reminder_tools_enabled": True},
    )
    controller.assert_consumed(key)
    name_lists = assert_only_appends(controller.captured[key])
    check(all(REMINDER_NAMES.issubset(set(names)) for names in name_lists), "classic mode must keep four reminder tools resident")
    check(RETURN_MESSAGE in response.text, "classic legacy return must stay on the meta compatibility path")
    check(session["expanded"] == ["memory"], "classic legacy return must not shrink drawer session state")
    check(session["rounds_no_use"] == 9, "classic legacy return must not alter rounds_no_use")


async def case_route_exception_with_request_mcp(client, controller):
    global MCP_BATCH_CALLS
    key = "route-exception-request-mcp"
    sid = "stream-route-exception"
    td._sessions.pop(sid, None)
    MCP_BATCH_CALLS = 0
    controller.add_plan(
        key,
        tool_response(tool_call("_drawer_return_tools", {}, "exception-return")),
        final_response("exception final"),
    )

    async def route_failure(*_args, **_kwargs):
        raise RuntimeError("forced route failure")

    with patch.object(td, "route_tools", route_failure):
        response = await post_gateway(
            client,
            key,
            sid,
            {"drawer_enabled": True, "reminder_tools_enabled": False},
            mcp_servers=[{
                "name": "local-request-mcp",
                "url": "https://mcp.invalid/endpoint",
                "transport": "streamable_http",
            }],
        )

    controller.assert_consumed(key)
    name_lists = assert_only_appends(controller.captured[key])
    check(all("request_mcp_probe" in names for names in name_lists), "request-body MCP must force entry into the tool loop")
    check(RETURN_MESSAGE in response.text, "route-exception legacy call must still hit the meta tombstone")
    check(MCP_BATCH_CALLS == 0, "legacy return must not fall through to MCP batch execution")


async def case_concurrent_request_isolation(client, controller):
    key_a = "concurrent-A"
    key_b = "concurrent-B"
    sid = "stream-concurrent-shared"
    td._sessions.pop(sid, None)
    controller.add_plan(
        key_a,
        tool_response(tool_call("_drawer_request_tools", {"category": "reminder"}, "concurrent-a-request")),
        final_response("A final"),
    )
    controller.add_plan(
        key_b,
        tool_response(tool_call("_drawer_request_tools", {"category": "reminder"}, "concurrent-b-request")),
        final_response("B final"),
    )

    original_handler = td.handle_meta_tool
    blocked_entered = asyncio.Event()
    allowed_finished = asyncio.Event()

    async def interleaved_handler(tool_name, args, session_id, **context):
        disabled = set(context.get("disabled_categories") or ())
        if tool_name == "_drawer_request_tools" and args.get("category") == "reminder":
            if "reminder" in disabled:
                blocked_entered.set()
                await asyncio.wait_for(allowed_finished.wait(), timeout=5)
            else:
                await asyncio.wait_for(blocked_entered.wait(), timeout=5)
                result = await original_handler(tool_name, args, session_id, **context)
                allowed_finished.set()
                return result
        return await original_handler(tool_name, args, session_id, **context)

    with patch.object(td, "handle_meta_tool", interleaved_handler):
        response_b, response_a = await asyncio.gather(
            post_gateway(
                client,
                key_b,
                sid,
                {"drawer_enabled": True, "reminder_tools_enabled": False},
            ),
            post_gateway(
                client,
                key_a,
                sid,
                {"drawer_enabled": True, "reminder_tools_enabled": True},
            ),
        )

    controller.assert_consumed(key_a)
    controller.assert_consumed(key_b)
    names_a = assert_only_appends(controller.captured[key_a])
    names_b = assert_only_appends(controller.captured[key_b])
    check(len(names_a) == 2 and len(names_b) == 2, "both concurrent requests must complete two upstream rounds")
    check(REMINDER_NAMES.isdisjoint(names_a[0]), "allowed request must begin with reminder collapsed")
    check(REMINDER_NAMES.issubset(set(names_a[1])), "allowed request must add reminder in its own same-round merge")
    check(all(REMINDER_NAMES.isdisjoint(names) for names in names_b), "disabled request must never inherit concurrent reminder expansion")
    check("该类工具当前已被用户设置关闭，无法展开" in response_b.text, "disabled request must receive gate rejection")
    check("已展开" in response_a.text, "allowed request must receive successful expansion")


async def main():
    global ACTIVE_UPSTREAM

    if not td.CATEGORIES:
        td._auto_discover_mcp_tools()
    snapshots = {
        "schemas": dict(td.TOOL_SCHEMAS),
        "categories": dict(td.CATEGORIES),
        "tool_to_category": dict(td._tool_to_category),
        "meta": list(td.META_TOOLS),
        "initialized": td._initialized,
    }
    td.TOOL_SCHEMAS["probe_tool"] = {
        "type": "function",
        "function": {
            "name": "probe_tool",
            "description": "local drawer probe",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "integer"}},
            },
        },
    }
    td.CATEGORIES["probe"] = {
        "label": "Probe",
        "description": "local integration probe",
        "tool_names": ["probe_tool"],
        "keywords": [],
    }
    td._tool_to_category["probe_tool"] = "probe"
    td.META_TOOLS.clear()
    td.META_TOOLS.extend(td._build_meta_tools())
    td._initialized = True

    controller = UpstreamController()
    ACTIVE_UPSTREAM = controller

    transport = httpx.ASGITransport(app=gateway.app)
    asgi_client = httpx.AsyncClient(transport=transport, base_url="http://kiwi.test", timeout=20)

    patches = (
        patch.object(gateway, "get_config_bool", fake_get_config_bool),
        patch.object(gateway, "get_config", fake_get_config),
        patch.object(gateway, "resolve_provider_for_model", fake_provider),
        patch.object(gateway, "get_tools_for_servers", fake_get_tools_for_servers),
        patch.object(gateway, "call_tools_batch", fake_call_tools_batch),
        patch.object(gateway, "_finalize_stream_memories", fake_finalize),
        patch.object(gateway, "detect_dream_trigger", lambda _text: False),
        patch.object(config_module, "get_config", fake_get_config),
        patch.object(config_module, "get_config_bool", fake_get_config_bool),
        patch.object(config_module, "get_config_float", fake_get_config_float),
        patch.object(config_module, "get_config_int", fake_get_config_int),
        patch.object(td, "init_drawer", fake_init_drawer),
        patch.object(td, "execute_drawer_tool", fake_execute_drawer_tool),
        patch.object(httpx, "AsyncClient", FakeUpstreamClient),
    )

    try:
        for item in patches:
            item.start()
        case_tool_loop_limit_source_contract()
        await case_normal_four_rounds(asgi_client, controller)
        await case_long_valid_loop_and_hard_stop(asgi_client, controller)
        await case_classic_legacy_return(asgi_client, controller)
        await case_route_exception_with_request_mcp(asgi_client, controller)
        await case_concurrent_request_isolation(asgi_client, controller)
    finally:
        for item in reversed(patches):
            item.stop()
        await asgi_client.aclose()
        ACTIVE_UPSTREAM = None
        td.TOOL_SCHEMAS.clear()
        td.TOOL_SCHEMAS.update(snapshots["schemas"])
        td.CATEGORIES.clear()
        td.CATEGORIES.update(snapshots["categories"])
        td._tool_to_category.clear()
        td._tool_to_category.update(snapshots["tool_to_category"])
        td.META_TOOLS.clear()
        td.META_TOOLS.extend(snapshots["meta"])
        td._initialized = snapshots["initialized"]

    print("PASS: local ASGI tool streaming stability")


if __name__ == "__main__":
    asyncio.run(main())
