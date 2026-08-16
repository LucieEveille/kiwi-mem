"""No-network contracts for calendar period identity and completed-period writes."""

import asyncio
import calendar
from datetime import date, datetime, timedelta, timezone
import importlib
import os
from pathlib import Path
import sys
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import daily_digest
import database
import config
import main as gateway


SUMMARY_RESULT = {
    "summary": "summary",
    "digest": "digest",
    "sections": {"emotion": "emotion", "life": "life", "growth": "growth"},
    "highlights": ["highlight"],
    "diary": "diary",
}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def _periods(today):
    current_monday = today - timedelta(days=today.weekday())
    week_end = current_monday - timedelta(days=1)
    week_start = week_end - timedelta(days=6)

    month_end = today.replace(day=1) - timedelta(days=1)
    month_start = month_end.replace(day=1)

    current_q_month = ((today.month - 1) // 3) * 3 + 1
    current_q_start = date(today.year, current_q_month, 1)
    quarter_end = current_q_start - timedelta(days=1)
    quarter_start_month = ((quarter_end.month - 1) // 3) * 3 + 1
    quarter_start = date(quarter_end.year, quarter_start_month, 1)

    year_start = date(today.year - 1, 1, 1)
    year_end = date(today.year - 1, 12, 31)
    return {
        "week": (week_start, week_end),
        "month": (month_start, month_end),
        "quarter": (quarter_start, quarter_end),
        "year": (year_start, year_end),
    }


def _expect_value_error(fn, label):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} must be rejected")


async def _expect_async_value_error(awaitable, label):
    try:
        await awaitable
    except ValueError:
        return
    raise AssertionError(f"{label} must be rejected")


async def check_shared_period_contract():
    periods = importlib.import_module("calendar_periods")
    fixed_today = date(2026, 8, 11)

    check(
        periods.validate_calendar_period_identity("2099-02-03", "day", today=fixed_today).start
        == date(2099, 2, 3),
        "day pages must accept any valid calendar date",
    )
    periods.validate_calendar_period_identity(
        "2026-08-03", "week", end_value="2026-08-09", today=fixed_today
    )
    periods.validate_calendar_period_identity(
        "2026-08-03", "week", today=fixed_today,
        created_at=datetime(2026, 8, 10, 0, 5, tzinfo=timezone(timedelta(hours=8))),
    )
    periods.validate_calendar_period_identity("2026-07-01", "month", today=fixed_today)
    periods.validate_calendar_period_identity("2026-04-01", "quarter", today=fixed_today)
    periods.validate_calendar_period_identity("2025-01-01", "year", today=fixed_today)

    invalid = (
        ("unknown type", lambda: periods.validate_calendar_period_identity("2026-08-01", "fortnight", today=fixed_today)),
        ("non-string type", lambda: periods.validate_calendar_period_identity("2026-08-01", ["week"], today=fixed_today)),
        ("week start", lambda: periods.validate_calendar_period_identity("2026-08-04", "week", end_value="2026-08-10", today=fixed_today)),
        ("week end", lambda: periods.validate_calendar_period_identity("2026-08-03", "week", end_value="2026-08-08", today=fixed_today)),
        ("reversed week", lambda: periods.validate_calendar_period_identity("2026-08-03", "week", end_value="2026-08-02", today=fixed_today)),
        ("incomplete week", lambda: periods.validate_calendar_period_identity("2026-08-10", "week", end_value="2026-08-16", today=fixed_today)),
        ("premature authored week", lambda: periods.validate_calendar_period_identity(
            "2026-08-03", "week", today=fixed_today,
            created_at=datetime(2026, 8, 9, 12, 0, tzinfo=timezone(timedelta(hours=8))),
        )),
        ("month anchor", lambda: periods.validate_calendar_period_identity("2026-07-02", "month", today=fixed_today)),
        ("incomplete month", lambda: periods.validate_calendar_period_identity("2026-08-01", "month", today=fixed_today)),
        ("quarter anchor", lambda: periods.validate_calendar_period_identity("2026-05-01", "quarter", today=fixed_today)),
        ("incomplete quarter", lambda: periods.validate_calendar_period_identity("2026-07-01", "quarter", today=fixed_today)),
        ("year anchor", lambda: periods.validate_calendar_period_identity("2025-02-01", "year", today=fixed_today)),
        ("incomplete year", lambda: periods.validate_calendar_period_identity("2026-01-01", "year", today=fixed_today)),
    )
    for label, call in invalid:
        _expect_value_error(call, label)


class _FakeConnection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.fetchrow_calls = []

    async def fetchrow(self, *args):
        self.fetchrow_calls.append(args)
        return {"id": len(self.fetchrow_calls)}

    async def fetch(self, *args):
        return self.rows


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


async def check_database_write_boundary():
    today = datetime.now(database.TZ_CST).date()
    p = _periods(today)
    conn = _FakeConnection()

    async def fake_pool():
        return _FakePool(conn)

    invalid_month = today.replace(day=1)
    invalid_calls = (
        (lambda: database.save_calendar_page(invalid_month.isoformat(), "month", []), "incomplete generated month"),
        (lambda: database.save_calendar_page((p["month"][0] + timedelta(days=1)).isoformat(), "month", []), "misanchored generated month"),
        (lambda: database.save_calendar_page(p["week"][0].isoformat(), "fortnight", []), "unknown generated type"),
        (lambda: database.update_calendar_page_user_edit(invalid_month.isoformat(), "month", diary="manual"), "incomplete manual month"),
        (lambda: database.update_calendar_page_user_edit((p["week"][0] + timedelta(days=1)).isoformat(), "week", diary="manual"), "misanchored manual week"),
    )
    with patch.object(database, "get_pool", fake_pool):
        for make_awaitable, label in invalid_calls:
            await _expect_async_value_error(make_awaitable(), label)
        check(conn.fetchrow_calls == [], "invalid DB writes must fail before acquiring/writing")

        await database.save_calendar_page(today.isoformat(), "day", [])
        await database.save_calendar_page(p["week"][0].isoformat(), "week", [])
        await database.update_calendar_page_user_edit(p["month"][0].isoformat(), "month", diary="manual")
    check(len(conn.fetchrow_calls) == 3, "valid day/summary identities must still reach the DB boundary")


async def check_generation_boundaries():
    today = datetime.now(database.TZ_CST).date()
    p = _periods(today)
    io_calls = []

    async def fake_range(*args, **kwargs):
        io_calls.append(("range", args))
        return []

    async def fake_model(*args, **kwargs):
        io_calls.append(("model", args))
        return SUMMARY_RESULT

    async def fake_save(*args, **kwargs):
        io_calls.append(("save", args))
        return 1

    current_month_start = today.replace(day=1)
    current_month_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    current_q_month = ((today.month - 1) // 3) * 3 + 1
    current_q_start = date(today.year, current_q_month, 1)
    current_q_end_month = current_q_month + 2
    current_q_end = date(today.year, current_q_end_month, calendar.monthrange(today.year, current_q_end_month)[1])

    with (
        patch.object(database, "get_calendar_range", fake_range),
        patch.object(database, "save_calendar_page", fake_save),
        patch.object(daily_digest, "_call_model_for_json", fake_model),
    ):
        await _expect_async_value_error(
            daily_digest.generate_week_summary(
                (p["week"][0] + timedelta(days=1)).isoformat(),
                (p["week"][1] + timedelta(days=1)).isoformat(),
            ),
            "direct invalid week generator",
        )
        await _expect_async_value_error(
            daily_digest.generate_month_summary(
                current_month_start.isoformat(), current_month_end.isoformat(),
                current_month_start.strftime("%Y-%m"),
            ),
            "direct incomplete month generator",
        )
        await _expect_async_value_error(
            daily_digest.generate_period_summary(
                current_q_start.isoformat(), current_q_end.isoformat(),
                "quarter", f"{today.year}Q{((today.month - 1) // 3) + 1}", "月总结",
            ),
            "direct incomplete quarter generator",
        )
    check(io_calls == [], "invalid direct generators must fail before material/model/DB I/O")


async def check_http_boundaries():
    today = datetime.now(database.TZ_CST).date()
    p = _periods(today)
    calls = []

    async def fake_week(*args, **kwargs):
        calls.append(("week", args))
        return {"status": "success", "week": f"{args[0]}~{args[1]}"}

    async def fake_month(*args, **kwargs):
        calls.append(("month", args))
        return {"status": "success", "month": args[2]}

    async def fake_period(*args, **kwargs):
        calls.append((args[2], args))
        return {"status": "success", "label": args[3]}

    async def fake_update(*args, **kwargs):
        calls.append(("put", kwargs))
        return 9

    transport = httpx.ASGITransport(app=gateway.app)
    with (
        patch.object(daily_digest, "generate_week_summary", fake_week),
        patch.object(daily_digest, "generate_month_summary", fake_month),
        patch.object(daily_digest, "generate_period_summary", fake_period),
        patch.object(database, "update_calendar_page_user_edit", fake_update),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://kiwi.test") as client:
            response = await client.get(f"/admin/week-summary?start={p['week'][0].isoformat()}")
            check(response.status_code == 400, "week start/end partial input must return HTTP 400")
            check(calls == [], "partial week input must not reach the generator")

            response = await client.get("/admin/week-summary")
            check(response.status_code == 200, "omitted week range must default successfully")
            check(calls.pop(0) == ("week", (p["week"][0].isoformat(), p["week"][1].isoformat())),
                  "omitted week range must choose the previous complete natural week")

            bad_week_start = p["week"][0] + timedelta(days=1)
            bad_week_end = bad_week_start + timedelta(days=6)
            response = await client.get(
                f"/admin/week-summary?start={bad_week_start.isoformat()}&end={bad_week_end.isoformat()}"
            )
            check(response.status_code == 400, "misanchored week HTTP input must return 400")
            check(calls == [], "misanchored week HTTP input must not reach the generator")

            response = await client.get(f"/admin/month-summary?month={today.strftime('%Y-%m')}")
            check(response.status_code == 400, "incomplete month HTTP input must return 400")
            response = await client.get(
                f"/admin/quarter-summary?quarter={today.year}-Q{((today.month - 1) // 3) + 1}"
            )
            check(response.status_code == 400, "incomplete quarter HTTP input must return 400")
            response = await client.get(f"/admin/year-summary?year={today.year}")
            check(response.status_code == 400, "incomplete year HTTP input must return 400")
            check(calls == [], "incomplete summary HTTP inputs must not reach generators")

            response = await client.put(
                f"/admin/calendar/{today.isoformat()}", json={"type": "fortnight", "content": "bad"}
            )
            check(response.status_code == 400, "unknown manual page type must return 400")
            response = await client.put(
                f"/admin/calendar/{today.isoformat()}", json={"type": ["week"], "content": "bad"}
            )
            check(response.status_code == 400, "non-string manual page type must return 400")
            response = await client.put(
                f"/admin/calendar/{(p['week'][0] + timedelta(days=1)).isoformat()}",
                json={"type": "week", "content": "bad"},
            )
            check(response.status_code == 400, "misanchored manual week must return 400")
            response = await client.put(
                f"/admin/calendar/{today.replace(day=1).isoformat()}",
                json={"type": "month", "content": "bad"},
            )
            check(response.status_code == 400, "incomplete manual month must return 400")
            check(calls == [], "invalid manual pages must fail before the DB function")

            response = await client.put(
                f"/admin/calendar/{today.isoformat()}", json={"type": "day", "content": "valid"}
            )
            check(response.status_code == 200, "valid day manual page must remain writable")
            check(len(calls) == 1 and calls[0][0] == "put", "valid day must reach the DB function once")


def _day_page(d):
    return {
        "type": "day", "date": d, "sections": [], "keywords": [],
        "summary": f"DAY_{d.isoformat()}", "digest": "", "diary": "",
    }


async def check_material_and_injection_isolation():
    today = datetime.now(database.TZ_CST).date()
    p = _periods(today)
    month_start, month_end = p["month"]
    invalid_week_start = next(
        d for d in (month_start + timedelta(days=i) for i in range(0, 7))
        if d.weekday() != 0 and d + timedelta(days=6) <= month_end
    )
    days = [_day_page(month_start + timedelta(days=i)) for i in range((month_end - month_start).days + 1)]
    invalid_week = {
        "type": "week", "date": invalid_week_start,
        "sections": [{"emotion": "INVALID_WEEK_MATERIAL"}], "keywords": [], "diary": "",
    }
    prompts = []

    async def calendar_range(start, end, page_type):
        if page_type == "week":
            return [invalid_week]
        if page_type == "day":
            return days
        return []

    async def no_messages(*args, **kwargs):
        return []

    async def fake_model(prompt, *args, **kwargs):
        prompts.append(prompt)
        return SUMMARY_RESULT

    async def fake_save(*args, **kwargs):
        return 77

    async def empty_config(*args, **kwargs):
        return ""

    with (
        patch.object(database, "get_calendar_range", calendar_range),
        patch.object(database, "get_chat_messages_for_date", no_messages),
        patch.object(database, "save_calendar_page", fake_save),
        patch.object(config, "get_config", empty_config),
        patch.object(daily_digest, "_call_model_for_json", fake_model),
    ):
        result = await daily_digest.generate_month_summary(
            month_start.isoformat(), month_end.isoformat(), month_start.strftime("%Y-%m")
        )
    check(result["status"] == "success", "month generation must recover with day-page material")
    check("INVALID_WEEK_MATERIAL" not in prompts[0], "invalid historical week must not feed month material")
    check(f"DAY_{invalid_week_start.isoformat()}" in prompts[0], "invalid week span must fall back to day material")

    q_start, q_end = p["quarter"]
    invalid_month = {
        "type": "month", "date": q_start + timedelta(days=1),
        "sections": [{"emotion": "INVALID_MONTH_MATERIAL"}], "diary": "",
    }
    model_calls = []

    async def invalid_month_range(*args, **kwargs):
        return [invalid_month]

    async def forbidden_model(*args, **kwargs):
        model_calls.append(args)
        return SUMMARY_RESULT

    with (
        patch.object(database, "get_calendar_range", invalid_month_range),
        patch.object(config, "get_config", empty_config),
        patch.object(daily_digest, "_call_model_for_json", forbidden_model),
    ):
        result = await daily_digest.generate_period_summary(
            q_start.isoformat(), q_end.isoformat(), "quarter",
            f"{q_start.year}Q{((q_start.month - 1) // 3) + 1}", "月总结",
        )
    check(result["status"] == "skipped", "period generator must skip when only invalid source pages exist")
    check(model_calls == [], "invalid source pages must never reach the period model")

    invalid_month_date = month_start + timedelta(days=1)
    invalid_week_date = invalid_week_start
    canonical_week_start, canonical_week_end = p["week"]
    premature_created_at = datetime(
        canonical_week_end.year, canonical_week_end.month, canonical_week_end.day,
        12, 0, tzinfo=database.TZ_CST,
    )
    rows = [
        {"id": 1, "date": invalid_month_date, "type": "month", "digest": "BAD_MONTH", "summary": "", "keywords": []},
        {"id": 2, "date": invalid_week_date, "type": "week", "digest": "BAD_WEEK", "summary": "", "keywords": []},
        {"id": 3, "date": invalid_month_date, "type": "day", "digest": "GOOD_DAY_MONTH", "summary": "", "keywords": []},
        {"id": 4, "date": invalid_week_date, "type": "day", "digest": "GOOD_DAY_WEEK", "summary": "", "keywords": []},
        {"id": 5, "date": month_start, "type": "fortnight", "digest": "BAD_TYPE", "summary": "", "keywords": []},
        {"id": 6, "date": canonical_week_start, "type": "week", "digest": "PREMATURE_WEEK", "summary": "", "keywords": [], "created_at": premature_created_at},
        {"id": 7, "date": canonical_week_start, "type": "day", "digest": "GOOD_DAY_PREMATURE", "summary": "", "keywords": []},
    ]
    conn = _FakeConnection(rows)

    async def fake_pool():
        return _FakePool(conn)

    with patch.object(database, "get_pool", fake_pool):
        injected = await database.get_calendar_for_injection(lookback_days=400)
        audited = await database.get_invalid_calendar_period_pages()
    check(not any(x["type"] in {"week", "month", "fortnight"} for x in injected),
          "invalid historical summaries must not inject or claim coverage")
    # 判据是"这些日子还在不在注入里"，不是 digest 字面：v6.1 三级注入对 4~7 天前的日页面
    # **故意**清空 digest、让注入端回落 summary，而 canonical_week_start 每逢周一（CST）
    # 正好是 7 天前——按字面判会让这条守卫每周一误红一次。
    injected_days = {x["date"] for x in injected if x["type"] == "day"}
    check({invalid_month_date, invalid_week_date, canonical_week_start} <= injected_days,
          "day pages under invalid summaries must remain eligible")
    today = datetime.now(database.TZ_CST).date()
    concise = {x["date"] for x in injected if x["type"] == "day" and not x.get("digest")}
    check(all((today - d).days <= 7 for d in concise),
          "a day outside the concise window must keep its digest")
    audited_ids = {x["id"] for x in audited}
    check({1, 2, 5, 6} <= audited_ids, "read-only audit must diagnose every invalid historical identity")


async def main():
    failures = []
    cases = (
        ("shared validator", check_shared_period_contract),
        ("DB write boundary", check_database_write_boundary),
        ("generation boundary", check_generation_boundaries),
        ("HTTP boundary", check_http_boundaries),
        ("material/injection isolation", check_material_and_injection_isolation),
    )
    for name, case in cases:
        try:
            await case()
        except Exception as exc:
            failure = f"{name}: {type(exc).__name__}: {exc}"
            failures.append(failure)
            print(f"FAIL {failure}")
    if failures:
        raise AssertionError("; ".join(failures))
    print("PASS: calendar period identity and completed-period boundaries")


if __name__ == "__main__":
    asyncio.run(main())
