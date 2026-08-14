"""No-network regression checks for ``stream_and_capture``.

The fake upstream emits real SSE byte fragments through the production async
generator.  The checks intentionally close the downstream generator directly
after a yielded model event so a capture-after-yield regression loses the same
chunk that the client has already received.
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main as gateway


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def sse_content(text):
    return (
        "data: "
        + json.dumps(
            {"choices": [{"delta": {"content": text}, "finish_reason": None}]},
            ensure_ascii=False,
        )
    ).encode("utf-8")


def sse_usage():
    return (
        "data: "
        + json.dumps(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 2,
                    "total_tokens": 9,
                },
            }
        )
    ).encode("utf-8")


@dataclass
class UpstreamPlan:
    chunks: list[bytes]
    requests: list[dict] = field(default_factory=list)


ACTIVE_PLAN = None
FINALIZE_CALLS = []
SPAWNED_TASKS = []


class FakeResponse:
    status_code = 200

    async def aiter_bytes(self, chunk_size=None):
        del chunk_size
        for chunk in ACTIVE_PLAN.chunks:
            yield chunk


class FakeStreamContext:
    async def __aenter__(self):
        return FakeResponse()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, headers=None, json=None):
        ACTIVE_PLAN.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "json": dict(json or {}),
            }
        )
        return FakeStreamContext()


async def fake_anthropic_adapter(_response, _model):
    for chunk in ACTIVE_PLAN.chunks:
        yield chunk


async def fake_finalize(
    mem_enabled,
    session_id,
    user_message,
    assistant_msg,
    model,
    emotion_level,
    project_id,
    is_regenerate,
    **ledger_kwargs,
):
    # W2-03 扩了 _finalize_stream_memories 的关键字参数（record_events / extract_enabled /
    # usage / ledger_ctx）。替身照单收下并记录，本脚本断言的仍是 W1-02 的流式合同：
    # 何时 spawn、spawn 几次、正文捕获是否完整。
    FINALIZE_CALLS.append(
        {
            "mem_enabled": mem_enabled,
            "session_id": session_id,
            "user_message": user_message,
            "assistant_msg": assistant_msg,
            "model": model,
            "emotion_level": emotion_level,
            "project_id": project_id,
            "is_regenerate": is_regenerate,
            **ledger_kwargs,
        }
    )
    return {"action": "skip"}


def fake_spawn(coro):
    task = asyncio.create_task(coro)
    SPAWNED_TASKS.append(task)
    return task


def new_stream(api_format="openai"):
    return gateway.stream_and_capture(
        {"Authorization": "Bearer test", "accept-encoding": "gzip"},
        {"model": "test-model", "messages": []},
        "test-session",
        "test-user-message",
        "test-model",
        api_url="https://upstream.invalid/v1/chat/completions",
        api_format=api_format,
        api_key="test-key",
        mem_enabled=True,
    )


async def wait_for_spawned():
    if SPAWNED_TASKS:
        await asyncio.gather(*SPAWNED_TASKS)


def reset(plan):
    global ACTIVE_PLAN
    ACTIVE_PLAN = plan
    FINALIZE_CALLS.clear()
    SPAWNED_TASKS.clear()


async def collect_stream(stream):
    events = []
    async for chunk in stream:
        events.append(chunk.decode("utf-8"))
    await wait_for_spawned()
    return events


async def close_after_matching_event(stream, marker):
    events = []
    while True:
        chunk = await anext(stream)
        text = chunk.decode("utf-8")
        events.append(text)
        if marker in text:
            check(not FINALIZE_CALLS, "delta loop must not finalize or write before downstream closes")
            await stream.aclose()
            await wait_for_spawned()
            return events


def assert_single_finalize(expected_text):
    check(len(FINALIZE_CALLS) == 1, f"finalizer must run once, got {len(FINALIZE_CALLS)}")
    check(
        FINALIZE_CALLS[0]["assistant_msg"] == expected_text,
        f"saved assistant text must be {expected_text!r}, got {FINALIZE_CALLS[0]['assistant_msg']!r}",
    )


async def case_openai_normal_usage_tail():
    reset(
        UpstreamPlan(
            [
                sse_content("alpha") + b"\n\n" + sse_content("beta")[:19],
                sse_content("beta")[19:] + b"\n\n",
                sse_usage(),
            ]
        )
    )
    events = await collect_stream(new_stream("openai"))

    assert_single_finalize("alphabeta")
    check(events[-1] == "data: [DONE]\n\n", "[DONE] must remain the final downstream event")
    check(any('"usage"' in event for event in events), "usage tail must still be forwarded")
    check("usage" not in FINALIZE_CALLS[0]["assistant_msg"], "usage must not enter assistant text")
    headers = ACTIVE_PLAN.requests[0]["headers"]
    check(headers.get("Authorization") == "Bearer test", "OpenAI headers must be preserved")
    check(headers.get("Accept-Encoding") == "identity", "OpenAI stream must disable compression")
    check("accept-encoding" not in headers, "OpenAI stream must replace case-insensitive encoding headers")


async def case_openai_cancel_after_complete_event():
    reset(UpstreamPlan([sse_content("delivered") + b"\n\n", sse_content("unread") + b"\n\n"]))
    await close_after_matching_event(new_stream("openai"), "delivered")
    assert_single_finalize("delivered")


async def case_openai_cancel_after_residual_tail():
    reset(UpstreamPlan([sse_content("first") + b"\n\n", sse_content("tail")]))
    await close_after_matching_event(new_stream("openai"), "tail")
    assert_single_finalize("firsttail")


async def case_anthropic_capture_before_yield_and_tail():
    reset(UpstreamPlan([sse_content("anthropic") + b"\n\n", sse_content("-tail")]))
    events = await collect_stream(new_stream("anthropic"))

    assert_single_finalize("anthropic-tail")
    check(events[-1] == "data: [DONE]\n\n", "Anthropic stream must finish with one [DONE]")
    headers = ACTIVE_PLAN.requests[0]["headers"]
    check(headers.get("Accept-Encoding") == "identity", "Anthropic identity header must remain")


async def case_anthropic_cancel_after_complete_event():
    reset(UpstreamPlan([sse_content("anthropic-delivered") + b"\n\n", sse_content("unread") + b"\n\n"]))
    await close_after_matching_event(new_stream("anthropic"), "anthropic-delivered")
    assert_single_finalize("anthropic-delivered")


async def case_upstream_done_is_deduplicated():
    reset(UpstreamPlan([sse_content("done") + b"\n\ndata: [DONE]\n\n"]))
    events = await collect_stream(new_stream("openai"))
    assert_single_finalize("done")
    check(events.count("data: [DONE]\n\n") == 1, "upstream [DONE] must be replaced by one final event")
    check(events[-1] == "data: [DONE]\n\n", "[DONE] must remain last")


async def main():
    patches = (
        patch.object(gateway.httpx, "AsyncClient", FakeAsyncClient),
        patch.object(gateway, "anthropic_stream_to_openai", fake_anthropic_adapter),
        patch.object(gateway, "_finalize_stream_memories", fake_finalize),
        patch.object(gateway, "_spawn_background_task", fake_spawn),
        patch.object(gateway, "detect_dream_trigger", lambda _text: False),
    )
    failures = []
    try:
        for item in patches:
            item.start()
        cases = (
            case_openai_normal_usage_tail,
            case_openai_cancel_after_complete_event,
            case_openai_cancel_after_residual_tail,
            case_anthropic_capture_before_yield_and_tail,
            case_anthropic_cancel_after_complete_event,
            case_upstream_done_is_deduplicated,
        )
        for case in cases:
            try:
                await case()
            except Exception as exc:
                failures.append(f"{case.__name__}: {exc}")
    finally:
        for item in reversed(patches):
            item.stop()

    if failures:
        raise AssertionError("stream capture guards failed:\n- " + "\n- ".join(failures))
    print("PASS: stream capture-before-yield and single-finalize guards")


if __name__ == "__main__":
    asyncio.run(main())
