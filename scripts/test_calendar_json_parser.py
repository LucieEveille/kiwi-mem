"""No-network contracts for calendar model JSON parsing and safe persistence."""

import asyncio
from copy import deepcopy
import json
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
import daily_digest
import database


DAY_RESULT = {
    "summary": "day summary",
    "digest": "day digest",
    "sections": [{
        "period": "上午",
        "title": "记录",
        "content": "正文",
        "keywords": ["日常"],
    }],
    "diary": "day diary",
    "all_keywords": ["day"],
}

SUMMARY_RESULT = {
    "summary": "summary",
    "digest": "digest",
    "sections": {"emotion": "e", "life": "l", "growth": "g"},
    "highlights": ["highlight"],
    "diary": "diary",
}


class _FakeResponse:
    status_code = 200

    def __init__(self, text, finish_reason="stop"):
        self._text = text
        self._finish_reason = finish_reason

    def json(self):
        return {
            "choices": [{
                "message": {"content": self._text},
                "finish_reason": self._finish_reason,
            }],
            "usage": {"completion_tokens": 100},
        }


def _fake_async_client(text, finish_reason="stop"):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return _FakeResponse(text, finish_reason)

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


async def _messages(*args, **kwargs):
    return [{"role": "user", "content": "hello"}]


async def _pool(*args, **kwargs):
    return _FakePool()


async def _calendar_range(start, end, page_type):
    if page_type != "day":
        return []
    return [{
        "type": "day",
        "date": start,
        "sections": [{"period": "上午", "title": "记录", "content": "source"}],
        "keywords": [],
        "diary": "",
    }]


async def _run_day(text, save_hook=None, finish_reason="stop"):
    saves = []

    async def fake_save(*args, **kwargs):
        saves.append(kwargs)
        if save_hook:
            save_hook(kwargs)
        return 101

    with (
        patch.object(database, "get_chat_messages_for_date", _messages),
        patch.object(database, "get_pool", _pool),
        patch.object(database, "resolve_model_endpoint", _model_endpoint),
        patch.object(database, "save_calendar_page", fake_save),
        patch.object(config, "get_config", _empty_config),
        patch.object(
            daily_digest.httpx,
            "AsyncClient",
            _fake_async_client(text, finish_reason),
        ),
    ):
        result = await daily_digest.generate_day_page(
            "2026-07-01", model_override="test-model"
        )
    return result, saves


async def _run_week(text):
    saves = []

    async def fake_save(*args, **kwargs):
        saves.append(kwargs)
        return 202

    with (
        patch.object(database, "get_calendar_range", _calendar_range),
        patch.object(database, "resolve_model_endpoint", _model_endpoint),
        patch.object(database, "save_calendar_page", fake_save),
        patch.object(config, "get_config", _empty_config),
        patch.object(daily_digest.httpx, "AsyncClient", _fake_async_client(text)),
    ):
        result = await daily_digest.generate_week_summary(
            "2026-06-29", "2026-07-05", model_override="test-model"
        )
    return result, saves


async def case_normal_json():
    result, saves = await _run_day(json.dumps(DAY_RESULT, ensure_ascii=False))
    assert result["status"] == "success" and len(saves) == 1


async def case_fenced_json():
    text = "```json\n" + json.dumps(DAY_RESULT, ensure_ascii=False) + "\n```"
    result, saves = await _run_day(text)
    assert result["status"] == "success" and len(saves) == 1


async def case_explanatory_text_with_braces():
    text = (
        "说明：{这段只是自然语言，不是 JSON}\n"
        + json.dumps(DAY_RESULT, ensure_ascii=False)
        + "\n以上是整理结果。"
    )
    result, saves = await _run_day(text)
    assert result["status"] == "success" and len(saves) == 1


async def case_raw_content_quotes():
    payload = deepcopy(DAY_RESULT)
    payload["summary"] = '她说"你好"，然后笑了'
    text = json.dumps(payload, ensure_ascii=False).replace('\\"你好\\"', '"你好"')
    result, saves = await _run_day(text)
    assert result["status"] == "success" and len(saves) == 1
    assert saves[0]["summary"] == payload["summary"]


async def case_truncated_json_rejected():
    text = json.dumps(DAY_RESULT, ensure_ascii=False)[:-1]
    result, saves = await _run_day(text)
    assert result["status"] == "error" and saves == []


async def case_length_finish_rejected_even_when_parseable():
    text = json.dumps(DAY_RESULT, ensure_ascii=False)
    result, saves = await _run_day(text, finish_reason="length")
    assert result["status"] == "error" and saves == []


async def case_empty_response_rejected():
    result, saves = await _run_day("   ")
    assert result["status"] == "error" and saves == []


async def case_day_field_types_rejected():
    payload = deepcopy(DAY_RESULT)
    payload["sections"] = {"content": "wrong container"}
    result, saves = await _run_day(json.dumps(payload, ensure_ascii=False))
    assert result["status"] == "error" and saves == []


async def case_summary_field_types_rejected():
    payload = deepcopy(SUMMARY_RESULT)
    payload["sections"] = ["wrong container"]
    payload["highlights"] = "wrong list"
    result, saves = await _run_week(json.dumps(payload, ensure_ascii=False))
    assert result["status"] == "error" and saves == []


async def case_authored_page_survives_failure():
    authored = {"model_used": "user_edit", "diary": "用户原文", "summary": "用户概要"}
    before = deepcopy(authored)

    def overwrite_if_saved(kwargs):
        authored.update({"diary": kwargs["diary"], "summary": kwargs["summary"]})

    payload = deepcopy(DAY_RESULT)
    payload["all_keywords"] = {"wrong": "container"}
    result, saves = await _run_day(
        json.dumps(payload, ensure_ascii=False), save_hook=overwrite_if_saved
    )
    assert result["status"] == "error" and saves == []
    assert authored == before


async def case_failure_can_retry():
    failed, failed_saves = await _run_day(json.dumps(DAY_RESULT, ensure_ascii=False)[:-1])
    retried, retry_saves = await _run_day(json.dumps(DAY_RESULT, ensure_ascii=False))
    assert failed["status"] == "error" and failed_saves == []
    assert retried["status"] == "success" and len(retry_saves) == 1


async def main():
    cases = [
        case_normal_json,
        case_fenced_json,
        case_explanatory_text_with_braces,
        case_raw_content_quotes,
        case_truncated_json_rejected,
        case_length_finish_rejected_even_when_parseable,
        case_empty_response_rejected,
        case_day_field_types_rejected,
        case_summary_field_types_rejected,
        case_authored_page_survives_failure,
        case_failure_can_retry,
    ]
    failures = []
    for case in cases:
        try:
            await case()
            print(f"PASS {case.__name__}")
        except Exception as exc:
            failures.append(f"FAIL {case.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        raise AssertionError("\n".join(failures))
    print("test_calendar_json_parser: all tests passed")


if __name__ == "__main__":
    asyncio.run(main())
