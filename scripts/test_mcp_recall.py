"""No-network contracts for MCP memory recall accounting."""

import asyncio
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import database
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


async def check_mcp_explicit_recall_request():
    for payload in (
        {"memories": [], "total_memories": 0},
        {
            "memories": [{
                "id": 7,
                "title": "hit",
                "content": "memory hit",
                "importance": 5,
                "created_at": "2026-08-11T00:00:00Z",
                "memory_type": "fragment",
            }],
            "total_memories": 1,
        },
    ):
        captured = []
        with patch.object(mcp_server.httpx, "AsyncClient", _fake_async_client(payload, captured)):
            await mcp_server.search_memory("recall contract", limit=3)

        check(len(captured) == 1, "MCP search must make exactly one gateway request")
        _url, params = captured[0]
        check(params.get("q") == "recall contract", "MCP search must preserve the query")
        check(params.get("limit") == 3, "MCP search must preserve the limit")
        check(
            params.get("track_recall") in (True, "true"),
            "MCP search must explicitly request recall tracking",
        )


async def check_database_counts_only_real_hits():
    recall_calls = []

    async def no_embedding(_query):
        return None

    async def heat_params():
        return {}

    async def semantic_threshold(*_args, **_kwargs):
        return 0.25

    async def record_recall(memory_ids, query):
        recall_calls.append((list(memory_ids), query))

    async def no_hits(*_args, **_kwargs):
        return []

    hit = {
        "id": 42,
        "content": "real hit",
        "score": 0.9,
        "similarity": 0.0,
        "heat": 0.5,
    }

    async def one_hit(*_args, **_kwargs):
        return [dict(hit)]

    common = (
        patch.object(database, "get_embedding", no_embedding),
        patch.object(database, "get_heat_params", heat_params),
        patch.object(database, "track_memory_recall", record_recall),
        patch("config.get_config_float", semantic_threshold),
    )

    for item in common:
        item.start()
    try:
        with patch.object(database, "_keyword_search", no_hits):
            result = await database.search_memories("empty", track_recall=True)
        check(result == [], "empty search contract must return no memories")
        check(recall_calls == [], "empty search must not increase recall heat")

        with patch.object(database, "_keyword_search", one_hit):
            result = await database.search_memories("found", track_recall=True)
        check([item["id"] for item in result] == [42], "real search hit must be returned")
        check(recall_calls == [([42], "found")], "one real search must count recall exactly once")
    finally:
        for item in reversed(common):
            item.stop()


async def main():
    await check_mcp_explicit_recall_request()
    await check_database_counts_only_real_hits()
    print("PASS: MCP recall accounting")


if __name__ == "__main__":
    asyncio.run(main())
