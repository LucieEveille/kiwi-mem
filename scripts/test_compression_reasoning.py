"""No-network contracts for compression placeholders and reasoning effort."""

import asyncio
import copy
import os
import sys
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
import database
import main as gateway


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class _FakeConnection:
    def __init__(self):
        self.writes = []

    async def execute(self, *args):
        self.writes.append(args)
        return "INSERT 0 1"


class _FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _FakeAcquire(self.conn)


async def check_reasoning_config_contract():
    conn = _FakeConnection()

    async def fake_pool():
        return _FakePool(conn)

    allowed = ("off", "auto", "low", "medium", "high")
    rejected = ("", "xhigh", "max", "ultra", "HIGH")
    with patch.object(config, "get_pool", fake_pool):
        for value in allowed:
            check(await config.set_config("reasoning_effort", value), f"config must accept {value}")
        accepted_writes = len(conn.writes)
        for value in rejected:
            check(
                not await config.set_config("reasoning_effort", value),
                f"config must reject unsupported reasoning effort {value!r}",
            )
        check(len(conn.writes) == accepted_writes, "rejected config values must never reach the database")

        transport = httpx.ASGITransport(app=gateway.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://kiwi.test") as client:
            admin_response = await client.put(
                "/admin/config/reasoning_effort",
                json={"value": "xhigh"},
            )
            check("error" in admin_response.json(), "admin config must return an explicit invalid-value error")

            sync_response = await client.put(
                "/sync/settings",
                json={"reasoning_effort": "max"},
            )
            check(
                sync_response.json().get("rejected") == ["reasoning_effort"],
                "sync settings must report an invalid reasoning value as rejected",
            )

    panel_source = (ROOT / "admin-panel" / "js" / "config-schema.js").read_text(encoding="utf-8")
    check(
        "options:['off','auto','low','medium','high']" in panel_source,
        "admin panel must expose exactly the public five-value reasoning contract",
    )


async def check_request_reasoning_contract():
    for value in ("off", "auto", "low", "medium", "high"):
        check(gateway._normalize_reasoning_effort(value) == value, f"request must accept {value}")
    check(gateway._normalize_reasoning_effort(None) is None, "omitted effort must preserve legacy behavior")
    check(gateway._normalize_reasoning_effort(" HIGH ") == "high", "request effort may normalize case/space")

    for value in ("", "xhigh", "max", "ultra", 7):
        try:
            gateway._normalize_reasoning_effort(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"request must reject unsupported reasoning effort {value!r}")

    provider_calls = []

    async def forbidden_provider_call(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError("invalid reasoning must fail before provider routing")

    transport = httpx.ASGITransport(app=gateway.app)
    with patch.object(gateway, "resolve_provider_for_model", forbidden_provider_call):
        async with httpx.AsyncClient(transport=transport, base_url="http://kiwi.test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "test/model",
                    "messages": [{"role": "user", "content": "reasoning contract"}],
                    "reasoning_effort": "xhigh",
                },
            )

    check(response.status_code == 400, "unsupported request effort must return HTTP 400")
    payload = response.json()
    error = payload.get("error", {})
    check(error.get("param") == "reasoning_effort", "400 response must identify reasoning_effort")
    check("off/auto/low/medium/high" in error.get("message", ""), "400 response must list allowed values")
    check(provider_calls == [], "invalid request must not touch provider routing or upstream I/O")

    body = {"reasoning": {"enabled": False}, "reasoning_effort": "stale"}
    gateway._apply_reasoning(body, True, False, "auto")
    check(body == {"reasoning": {"enabled": True}}, "auto must enable OpenRouter reasoning without effort")
    body = {}
    gateway._apply_reasoning(body, False, False, "high")
    check(body == {"reasoning_effort": "high"}, "direct OpenAI-compatible high must remain supported")
    body = {"reasoning": {"enabled": True}, "reasoning_effort": "high"}
    gateway._apply_reasoning(body, True, False, "off")
    check(body == {}, "off must remove every outbound reasoning field")


class _FakeCompressionResponse:
    status_code = 200

    def json(self):
        return {
            "choices": [{
                "message": {"content": "compressed summary"},
                "finish_reason": "stop",
            }]
        }


def _compression_client(captured):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured.append({"url": url, "headers": copy.deepcopy(headers), "body": copy.deepcopy(json)})
            return _FakeCompressionResponse()

    return FakeAsyncClient


async def _run_compression_case(get_float, get_int):
    captured = []

    async def fake_get_config(key):
        values = {
            "handoff_summary_model": "test/model",
            "prompt_compress": "比例={compress_ratio}；上限={compress_output_max}",
        }
        return values.get(key, "")

    async def fake_resolve(_model):
        return "https://upstream.invalid/v1/chat/completions", "test-key", "openai"

    with (
        patch.object(gateway, "get_config", fake_get_config),
        patch.object(gateway, "get_config_float", get_float),
        patch.object(gateway, "get_config_int", get_int),
        patch.object(database, "resolve_model_endpoint", fake_resolve),
        patch.object(gateway.httpx, "AsyncClient", _compression_client(captured)),
    ):
        result = await gateway._compress_for_handoff(
            "old summary",
            [{"role": "user", "content": "new material"}],
        )

    check(result == "compressed summary", "compression response must remain compatible")
    check(len(captured) == 1, "compression must make one background request")
    body = captured[0]["body"]
    system_prompt = body["messages"][0]["content"]
    check("{" not in system_prompt and "}" not in system_prompt, "compression placeholders must not reach the model")
    check(body["max_tokens"] == 2000, "placeholder output max must not rewrite provider token policy")
    return system_prompt


async def check_compression_placeholders():
    async def ratio(*_args, **_kwargs):
        return 0.42

    async def output_max(*_args, **_kwargs):
        return 7777

    configured = await _run_compression_case(ratio, output_max)
    check("比例=42%" in configured, "configured compression ratio must be rendered as a percentage")
    check("上限=7777 token" in configured, "configured compression output max must be rendered")

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("forced config outage")

    fallback = await _run_compression_case(unavailable, unavailable)
    check("比例=35%" in fallback, "compression ratio must use the safe default on config failure")
    check("上限=4000 token" in fallback, "compression output max must use the safe default on config failure")


async def main():
    failures = []
    for name, case in (
        ("reasoning config", check_reasoning_config_contract),
        ("request reasoning", check_request_reasoning_contract),
        ("compression placeholders", check_compression_placeholders),
    ):
        try:
            await case()
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"FAIL {failures[-1]}")
    if failures:
        raise AssertionError("; ".join(failures))
    print("PASS: compression placeholders and reasoning effort contracts")


if __name__ == "__main__":
    asyncio.run(main())
