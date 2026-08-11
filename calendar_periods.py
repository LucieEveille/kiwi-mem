"""Canonical calendar-period identities shared by every write/selection boundary."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Mapping, Optional


TZ_CST = timezone(timedelta(hours=8))
ALLOWED_CALENDAR_PAGE_TYPES = frozenset({"day", "week", "month", "quarter", "year"})


class CalendarPeriodValidationError(ValueError):
    """Raised when a calendar page does not identify a canonical completed period."""


@dataclass(frozen=True)
class CalendarPeriod:
    page_type: str
    start: date
    end: date


def _coerce_date(value, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise CalendarPeriodValidationError(
            f"{field_name} 必须是 YYYY-MM-DD 格式的合法日期"
        ) from exc


def _authored_date(value) -> date:
    if isinstance(value, datetime):
        authored = value
    elif isinstance(value, date):
        return value
    else:
        try:
            authored = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise CalendarPeriodValidationError("created_at 不是合法时间") from exc
    if authored.tzinfo is None:
        authored = authored.replace(tzinfo=TZ_CST)
    return authored.astimezone(TZ_CST).date()


def _period_end(start: date, page_type: str) -> date:
    if page_type == "day":
        return start
    if page_type == "week":
        if start.weekday() != 0:
            raise CalendarPeriodValidationError("week 的 date/start 必须是周一")
        return start + timedelta(days=6)
    if page_type == "month":
        if start.day != 1:
            raise CalendarPeriodValidationError("month 的 date/start 必须是每月 1 日")
        return date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    if page_type == "quarter":
        if start.day != 1 or start.month not in {1, 4, 7, 10}:
            raise CalendarPeriodValidationError("quarter 的 date/start 必须是 1/4/7/10 月 1 日")
        end_month = start.month + 2
        return date(start.year, end_month, calendar.monthrange(start.year, end_month)[1])
    if page_type == "year":
        if start.month != 1 or start.day != 1:
            raise CalendarPeriodValidationError("year 的 date/start 必须是 1 月 1 日")
        return date(start.year, 12, 31)
    raise CalendarPeriodValidationError(
        "type 只允许 day/week/month/quarter/year"
    )


def validate_calendar_period_identity(
    start_value,
    page_type: str,
    *,
    end_value=None,
    today: Optional[date] = None,
    created_at=None,
) -> CalendarPeriod:
    """Validate one page key and, when supplied, its explicit range end.

    Summary pages are authoritative only after their entire canonical period has
    ended in Asia/Taipei. Day pages remain writable for any valid date.
    """
    if not isinstance(page_type, str) or page_type not in ALLOWED_CALENDAR_PAGE_TYPES:
        raise CalendarPeriodValidationError(
            "type 只允许 day/week/month/quarter/year"
        )
    start = _coerce_date(start_value, "date/start")
    expected_end = _period_end(start, page_type)
    if end_value is not None:
        supplied_end = _coerce_date(end_value, "end")
        if supplied_end != expected_end:
            raise CalendarPeriodValidationError(
                f"{page_type} 的 end 必须是 {expected_end.isoformat()}"
            )

    today = _coerce_date(today, "today") if today is not None else datetime.now(TZ_CST).date()
    if page_type != "day" and expected_end >= today:
        raise CalendarPeriodValidationError(
            f"{page_type} 只允许已经结束的完整周期（本周期结束于 {expected_end.isoformat()}）"
        )
    if page_type != "day" and created_at is not None and _authored_date(created_at) <= expected_end:
        raise CalendarPeriodValidationError(
            f"{page_type} 页面在周期结束前成文，需按完整周期明确重新生成"
        )
    return CalendarPeriod(page_type=page_type, start=start, end=expected_end)


def calendar_period_invalid_reason(
    start_value, page_type: str, *, today: Optional[date] = None, created_at=None
) -> Optional[str]:
    try:
        validate_calendar_period_identity(
            start_value, page_type, today=today, created_at=created_at
        )
    except CalendarPeriodValidationError as exc:
        return str(exc)
    return None


def is_calendar_period_identity_valid(
    start_value, page_type: str, *, today: Optional[date] = None, created_at=None
) -> bool:
    return calendar_period_invalid_reason(
        start_value, page_type, today=today, created_at=created_at
    ) is None


def filter_valid_calendar_period_pages(
    pages: Iterable[Mapping], page_type: str, *, today: Optional[date] = None
) -> list:
    """Return only pages whose stored key is canonical and fully completed."""
    return [
        page for page in pages
        if page.get("type", page_type) == page_type
        and is_calendar_period_identity_valid(
            page.get("date"), page_type, today=today, created_at=page.get("created_at")
        )
    ]
