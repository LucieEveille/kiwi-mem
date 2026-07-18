"""No-network contracts for calendar summary token budgets and truncation."""

import asyncio
from contextlib import redirect_stdout
import io
import json
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
import daily_digest
import database


SUMMARY_RESULT = {
    "summary": "summary",
    "digest": "digest",
    "sections": {"emotion": "e", "life": "l", "growth": "g"},
    "highlights": ["highlight"],
    "diary": "diary",
}

DAY_RESULT = {
    "summary": "day summary",
    "digest": "day digest",
    "sections": [{"period": "上午", "title": "记录", "content": "正文", "keywords": []}],
    "diary": "day diary",
    "all_keywords": ["day"],
}


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _fake_async_client(payload, request_bodies):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers=None, json=None):
            request_bodies.append(json)
            return _FakeResponse(payload)

    return FakeAsyncClient


class _FakeConnection:
    async def fetch(self, *args, **kwargs):
        return []


class _FakeAcquire:
    async def __aenter__(self):
        return _FakeConnection()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def acquire(self):
        return _FakeAcquire()


async def _empty_config(*args, **kwargs):
    return ""


async def _model_endpoint(*args, **kwargs):
    return "https://model.test/v1/chat/completions", "test-key", "openai"


async def _calendar_range(start, end, page_type):
    pages = {
        "day": [{
            "type": "day",
            "date": "2026-07-01",
            "sections": [{"period": "上午", "title": "记录", "content": "day source"}],
            "keywords": [],
            "diary": "",
        }],
        "week": [{
            "type": "week",
            "date": "2026-07-01",
            "sections": [{"emotion": "week source"}],
            "keywords": [],
            "diary": "",
        }],
        "month": [{
            "type": "month",
            "date": "2026-04-01",
            "sections": [{"emotion": "month source"}],
            "diary": "",
        }],
        "quarter": [{
            "type": "quarter",
            "date": "2026-01-01",
            "sections": [{"emotion": "quarter source"}],
            "diary": "",
        }],
    }
    return pages.get(page_type, [])


async def run_budget_contract():
    request_bodies = []
    save_calls = []

    async def fake_messages(*args, **kwargs):
        return [{"role": "user", "content": "hello"}]

    async def fake_get_pool(*args, **kwargs):
        return _FakePool()

    async def fake_save(*args, **kwargs):
        save_calls.append(kwargs)
        return 101

    day_payload = {
        "choices": [{
            "message": {"content": json.dumps(DAY_RESULT, ensure_ascii=False)},
            "finish_reason": "stop",
        }],
        "usage": {"completion_tokens": 300},
    }
    with (
        patch.object(database, "get_chat_messages_for_date", fake_messages),
        patch.object(database, "get_pool", fake_get_pool),
        patch.object(database, "resolve_model_endpoint", _model_endpoint),
        patch.object(database, "save_calendar_page", fake_save),
        patch.object(config, "get_config", _empty_config),
        patch.object(daily_digest.httpx, "AsyncClient", _fake_async_client(day_payload, request_bodies)),
    ):
        result = await daily_digest.generate_day_page("2026-07-01", model_override="test-model")

    assert result["status"] == "success"
    assert request_bodies[0]["max_tokens"] == 6000

    summary_budgets = []

    async def fake_model(prompt, user_msg, model, max_tokens=2000):
        summary_budgets.append(max_tokens)
        return SUMMARY_RESULT

    with (
        patch.object(database, "get_calendar_range", _calendar_range),
        patch.object(database, "save_calendar_page", fake_save),
        patch.object(config, "get_config", _empty_config),
        patch.object(daily_digest, "_call_model_for_json", fake_model),
    ):
        await daily_digest.generate_week_summary(
            "2026-07-01", "2026-07-07", model_override="test-model"
        )
        await daily_digest.generate_month_summary(
            "2026-07-01", "2026-07-31", "2026-07", model_override="test-model"
        )
        await daily_digest.generate_period_summary(
            "2026-04-01", "2026-06-30", "quarter", "2026Q2", "月总结",
            model_override="test-model",
        )
        await daily_digest.generate_period_summary(
            "2026-01-01", "2026-12-31", "year", "2026", "季度总结",
            model_override="test-model",
        )

    assert summary_budgets == [6000, 3500, 2500, 2500]


async def run_length_contract():
    secret = "PARSEABLE_TRUNCATED_BODY_MUST_NOT_BE_LOGGED_OR_SAVED"
    text = json.dumps({"summary": secret})
    payload = {
        "choices": [{
            "message": {"content": text},
            "finish_reason": "length",
        }],
        "usage": {"completion_tokens": 6000},
    }
    request_bodies = []
    save_calls = []

    async def fake_save(*args, **kwargs):
        save_calls.append(kwargs)
        return 999

    output = io.StringIO()
    with (
        patch.object(database, "get_calendar_range", _calendar_range),
        patch.object(database, "resolve_model_endpoint", _model_endpoint),
        patch.object(database, "save_calendar_page", fake_save),
        patch.object(config, "get_config", _empty_config),
        patch.object(daily_digest.httpx, "AsyncClient", _fake_async_client(payload, request_bodies)),
        redirect_stdout(output),
    ):
        result = await daily_digest.generate_week_summary(
            "2026-07-01", "2026-07-07", model_override="test-model"
        )

    log = output.getvalue()
    assert result == {"status": "error", "error": "model returned invalid format"}
    assert request_bodies[0]["max_tokens"] == 6000
    assert save_calls == []
    assert "finish_reason=length" in log
    assert "completion_tokens=6000" in log
    assert f"text_chars={len(text)}" in log
    assert "max_tokens=6000" in log
    assert secret not in log


async def main():
    await run_budget_contract()
    await run_length_contract()
    print("test_calendar_summary_generation: all tests passed")


if __name__ == "__main__":
    asyncio.run(main())
