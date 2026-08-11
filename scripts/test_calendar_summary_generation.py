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
            assert kwargs.get("timeout") == 400

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
            "date": "2025-01-01",
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

    async def fake_no_messages(*args, **kwargs):
        return []

    with (
        patch.object(database, "get_calendar_range", _calendar_range),
        patch.object(database, "get_chat_messages_for_date", fake_no_messages),
        patch.object(database, "save_calendar_page", fake_save),
        patch.object(config, "get_config", _empty_config),
        patch.object(daily_digest, "_call_model_for_json", fake_model),
    ):
        await daily_digest.generate_week_summary(
            "2026-06-29", "2026-07-05", model_override="test-model"
        )
        await daily_digest.generate_month_summary(
            "2026-07-01", "2026-07-31", "2026-07", model_override="test-model"
        )
        await daily_digest.generate_period_summary(
            "2026-04-01", "2026-06-30", "quarter", "2026Q2", "月总结",
            model_override="test-model",
        )
        await daily_digest.generate_period_summary(
            "2025-01-01", "2025-12-31", "year", "2025", "季度总结",
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
            "2026-06-29", "2026-07-05", model_override="test-model"
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


# ============================================================
# 月总结素材契约（自然周与自然月不嵌套，跨月周不串账）
# 2026-07：周一为 6/29、7/6、7/13、7/20、7/27；6/29 与 7/27 两周跨月界
# ============================================================


def _week_page(monday: str) -> dict:
    return {
        "type": "week",
        "date": monday,
        "sections": [{"emotion": f"周素材 {monday}"}],
        "keywords": [],
        "diary": "",
    }


def _day_page(datestr: str, **overrides) -> dict:
    page = {
        "type": "day",
        "date": datestr,
        "summary": f"日素材 {datestr}",
        "digest": "",
        "sections": [],
        "keywords": [],
        "diary": "",
    }
    page.update(overrides)
    return page


def _make_calendar_range(weeks: list, days: list):
    from datetime import date as date_cls

    async def _range(start, end, page_type=None):
        s, e = date_cls.fromisoformat(start), date_cls.fromisoformat(end)
        pool = {"week": weeks, "day": days}.get(page_type, [])
        return [p for p in pool if s <= date_cls.fromisoformat(p["date"]) <= e]

    return _range


async def _run_july_month(weeks: list, days: list, message_dates=None):
    """跑一次 2026-07 月总结，返回 (result, prompts, saves)。"""
    prompts, saves = [], []
    message_dates = set(message_dates or [])

    async def fake_model(prompt, user_msg, model, max_tokens=2000):
        prompts.append(prompt)
        return SUMMARY_RESULT

    async def fake_save(*args, **kwargs):
        saves.append(kwargs)
        return 202

    async def fake_messages(datestr, *args, **kwargs):
        if datestr in message_dates:
            return [{"role": "user", "content": "material"}]
        return []

    with (
        patch.object(database, "get_calendar_range", _make_calendar_range(weeks, days)),
        patch.object(database, "get_chat_messages_for_date", fake_messages),
        patch.object(database, "save_calendar_page", fake_save),
        patch.object(config, "get_config", _empty_config),
        patch.object(daily_digest, "_call_model_for_json", fake_model),
    ):
        result = await daily_digest.generate_month_summary(
            "2026-07-01", "2026-07-31", "2026-07", model_override="test-model"
        )
    return result, prompts, saves


async def run_month_material_contract():
    july_days = [_day_page(f"2026-07-{d:02d}") for d in range(1, 32)]
    weeks_on_time = [_week_page("2026-06-29"), _week_page("2026-07-06"),
                     _week_page("2026-07-13"), _week_page("2026-07-20")]

    # 场景 A：8/1 按时生成——7/27 周尚不存在，两端由日页面补齐
    result, prompts, _ = await _run_july_month(weeks_on_time, july_days)
    assert result["status"] == "success", result
    material = prompts[0]
    for monday in ("2026-07-06", "2026-07-13", "2026-07-20"):
        assert f"周素材 {monday}" in material, monday
    assert "2026-06-29" not in material          # 跨入的上月周不采用
    for d in (1, 2, 3, 4, 5, 27, 28, 29, 30, 31):
        assert f"**2026-07-{d:02d}**" in material, d   # 两端日页面补齐
    for d in (6, 15, 26):
        assert f"**2026-07-{d:02d}**" not in material, d  # 周覆盖的日子不重复进

    # 场景 B：8/3 后延迟/手动重建——7/27 周已存在，仍不得整张采用（防混入 8/1–2）
    weeks_late = weeks_on_time + [_week_page("2026-07-27")]
    result, prompts, _ = await _run_july_month(weeks_late, july_days)
    assert result["status"] == "success", result
    material = prompts[0]
    assert "周素材 2026-07-27" not in material    # 跨出的周整张排除
    for d in (27, 28, 29, 30, 31):
        assert f"**2026-07-{d:02d}**" in material, d
    # 与场景 A 素材一致：无论何时生成/重建，结果确定

    # 场景 C：月中缺一张周总结（7/13 周缺失）→ 那七天由日页面兜底
    weeks_gap = [_week_page("2026-07-06"), _week_page("2026-07-20")]
    result, prompts, _ = await _run_july_month(weeks_gap, july_days)
    assert result["status"] == "success", result
    material = prompts[0]
    for d in range(13, 20):
        assert f"**2026-07-{d:02d}**" in material, d

    # 场景 D：缺口日页面缺失但当天有聊天素材 → 延迟成文，不落库
    days_missing_28 = [p for p in july_days if p["date"] != "2026-07-28"]
    result, prompts, saves = await _run_july_month(
        weeks_on_time, days_missing_28, message_dates={"2026-07-28"}
    )
    assert result["status"] == "skipped", result
    assert result["reason"] == "missing_day_pages", result
    assert result["missing_dates"] == ["2026-07-28"], result
    assert prompts == [] and saves == []

    # 场景 D'：缺口日无页面也无素材（empty）→ 正常成文
    result, prompts, _ = await _run_july_month(weeks_on_time, days_missing_28)
    assert result["status"] == "success", result
    assert "**2026-07-28**" not in prompts[0]

    # 场景 E：diary-only 手写日页面，正文不得写成「无记录」
    diary_only = [_day_page("2026-07-01", summary="", diary="手写的一天")]
    result, prompts, _ = await _run_july_month([], diary_only)
    assert result["status"] == "success", result
    assert "手写的一天" in prompts[0]
    assert "（无记录）" not in prompts[0]

    print("month material contract: ok")


# ============================================================
# 注入端契约：周与月/季/年部分重叠时的三态处理
# ============================================================


class _RowsConnection:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, *args, **kwargs):
        return self._rows


class _RowsAcquire:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return _RowsConnection(self._rows)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _RowsPool:
    def __init__(self, rows):
        self._rows = rows

    def acquire(self):
        return _RowsAcquire(self._rows)


async def run_injection_overlap_contract():
    from datetime import date as date_cls, datetime, timedelta
    import calendar as cal_mod

    today = datetime.now(database.TZ_CST).date()

    # 找一个足够久远（跨月周七天都在"最近三天/七天"窗口之外）、
    # 且最后一天不是周日的月份，保证存在跨月自然周
    y, m = today.year, today.month
    while True:
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        last = date_cls(y, m, cal_mod.monthrange(y, m)[1])
        if last.weekday() != 6 and last + timedelta(days=6) < today - timedelta(days=7):
            break
    month_start = date_cls(y, m, 1)
    month_end = last
    w_cross = month_end - timedelta(days=month_end.weekday())  # 含月末的那周的周一
    assert w_cross + timedelta(days=6) > month_end
    cross_days = [w_cross + timedelta(days=i) for i in range(7)]
    spill_days = [d for d in cross_days if d > month_end]      # 溢入下月的日子
    in_month_days = [d for d in cross_days if d <= month_end]
    w_full = w_cross - timedelta(days=7)                       # 完整落在月内的一周

    rows = [
        {"date": month_start, "type": "month", "digest": "月总结正文", "summary": "", "keywords": []},
        {"date": w_full, "type": "week", "digest": "整月内周正文", "summary": "", "keywords": []},
        {"date": w_cross, "type": "week", "digest": "跨月周正文", "summary": "", "keywords": []},
    ] + [
        {"date": d, "type": "day", "digest": f"日正文 {d}", "summary": "", "keywords": []}
        for d in cross_days
    ]

    async def fake_get_pool(*args, **kwargs):
        return _RowsPool(rows)

    with patch.object(database, "get_pool", fake_get_pool):
        entries = await database.get_calendar_for_injection(lookback_days=365)

    types_dates = {(e["type"], e["date"]) for e in entries}

    # 月总结入选；两张周都不得入选（一张被整月覆盖、一张部分重叠）
    assert ("month", month_start) in types_dates, entries
    assert not any(t == "week" for t, _ in types_dates), entries
    # 部分重叠的周不认领日子：溢入下月的日页面必须入选
    for d in spill_days:
        assert ("day", d) in types_dates, (d, entries)
    # 月内日子已被月总结覆盖，不重复入选
    for d in in_month_days:
        assert ("day", d) not in types_dates, (d, entries)

    print("injection overlap contract: ok")


async def main():
    await run_budget_contract()
    await run_length_contract()
    await run_month_material_contract()
    await run_injection_overlap_contract()
    print("test_calendar_summary_generation: all tests passed")


if __name__ == "__main__":
    asyncio.run(main())
