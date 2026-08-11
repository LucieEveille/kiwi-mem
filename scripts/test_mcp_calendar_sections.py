"""No-network contracts for MCP calendar page section rendering."""

import asyncio
import os
import sys
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mcp_server


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _fake_async_client(payload, captured):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params):
            captured.append((url, dict(params)))
            return _FakeResponse(payload)

    return FakeAsyncClient


async def render(page, page_type="day"):
    captured = []
    payload = {"status": "ok", "page": page}
    with patch.object(mcp_server.httpx, "AsyncClient", _fake_async_client(payload, captured)):
        result = await mcp_server.get_day_page("2026-08-11", type=page_type)
    check(len(captured) == 1, "MCP get_day_page must make exactly one gateway request")
    check(captured[0][1] == {"type": page_type}, "MCP get_day_page changed the requested page type")
    return result


async def check_day_sections_and_existing_fields():
    result = await render({
        "title": "一天",
        "summary": "既有概要",
        "sections": [
            {"period": "上午", "title": "对话", "content": "日页面正文"},
            {"period": "", "title": "", "content": ""},
        ],
        "diary": "既有日记",
        "keywords": ["甲", "乙"],
    })
    check("📅 2026-08-11 的day页面 — 一天" in result, "title output regressed")
    check("【概要】既有概要" in result, "summary output regressed")
    check("**上午 — 对话**\n日页面正文" in result, "day-style section was not rendered")
    check("** — **" not in result, "empty day-style section produced a blank block")
    check("📝 AI 的日记：既有日记" in result, "diary output regressed")
    check("🏷 关键词：甲、乙" in result, "keywords output regressed")


async def check_summary_sections_for_every_type():
    for page_type in ("week", "month", "quarter", "year"):
        result = await render({
            "sections": [{
                "emotion": f"{page_type}-情感",
                "life": f"{page_type}-生活",
                "growth": f"{page_type}-成长",
            }],
        }, page_type=page_type)
        check(f"**情感与陪伴**\n{page_type}-情感" in result, f"{page_type} emotion was dropped")
        check(f"**生活与日常**\n{page_type}-生活" in result, f"{page_type} life was dropped")
        check(f"**项目与成长**\n{page_type}-成长" in result, f"{page_type} growth was dropped")
        check("** — **" not in result, f"{page_type} summary produced a blank day block")


async def check_mixed_and_malformed_sections():
    result = await render({
        "summary": "混合概要",
        "sections": [
            "malformed",
            None,
            {},
            {"period": "夜间", "title": "回声", "content": "日式正文", "emotion": "混合情感"},
            {"life": "混合生活", "growth": ""},
        ],
        "diary": "混合日记",
        "keywords": "旧式关键词",
    }, page_type="week")
    check("读取出错" not in result, "non-dict section crashed the whole MCP read")
    check("**夜间 — 回声**\n日式正文" in result, "mixed day-style content was dropped")
    check("**情感与陪伴**\n混合情感" in result, "mixed emotion content was dropped")
    check("**生活与日常**\n混合生活" in result, "mixed life content was dropped")
    check("项目与成长" not in result, "empty growth field produced a heading")
    check("【概要】混合概要" in result, "mixed summary output regressed")
    check("📝 AI 的日记：混合日记" in result, "mixed diary output regressed")
    check("🏷 关键词：旧式关键词" in result, "legacy string keywords output regressed")


async def check_no_new_body_fallback():
    result = await render({"digest": "W3-C1 才处理的正文", "sections": []}, page_type="month")
    check("W3-C1 才处理的正文" not in result, "W1-07 crossed into digest fallback semantics")


async def main():
    failures = []
    for name, case in (
        ("day sections", check_day_sections_and_existing_fields),
        ("summary sections", check_summary_sections_for_every_type),
        ("mixed/malformed", check_mixed_and_malformed_sections),
        ("no fallback", check_no_new_body_fallback),
    ):
        try:
            await case()
        except Exception as exc:
            failure = f"{name}: {type(exc).__name__}: {exc}"
            failures.append(failure)
            print(f"FAIL {failure}")
    if failures:
        raise AssertionError("; ".join(failures))
    print("PASS: MCP calendar sections render both page structures")


if __name__ == "__main__":
    asyncio.run(main())
