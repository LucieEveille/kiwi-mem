"""No-network transaction contract for calendar page deletion."""

import asyncio
import copy
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import database


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class FakeStore:
    def __init__(self):
        self.pages = {
            (date(2026, 7, 17), "day"): 1,
            (date(2026, 7, 18), "day"): 2,
        }
        self.comments = {
            10: {"target_type": "calendar_page", "target_id": 1, "parent_id": None},
            11: {"target_type": "calendar_page", "target_id": 1, "parent_id": 10},
            12: {"target_type": "calendar_page", "target_id": 2, "parent_id": None},
            13: {"target_type": "memory", "target_id": 1, "parent_id": None},
        }
        self.fail_comments = False
        self.fail_page = False
        self.transaction_entries = 0
        self.commits = 0
        self.rollbacks = 0

    def snapshot(self):
        return copy.deepcopy((self.pages, self.comments))

    def restore(self, snapshot):
        self.pages, self.comments = copy.deepcopy(snapshot)


class FakeTransaction:
    def __init__(self, store):
        self.store = store
        self.before = None

    async def __aenter__(self):
        self.store.transaction_entries += 1
        self.before = self.store.snapshot()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.store.commits += 1
        else:
            self.store.restore(self.before)
            self.store.rollbacks += 1
        return False


class FakeConnection:
    def __init__(self, store):
        self.store = store

    def transaction(self):
        return FakeTransaction(self.store)

    async def fetchrow(self, sql, *args):
        normalized = " ".join(sql.split()).upper()
        key = (args[0], args[1])
        if normalized.startswith("SELECT ID FROM CALENDAR_PAGES"):
            page_id = self.store.pages.get(key)
            return {"id": page_id} if page_id is not None else None
        if normalized.startswith("DELETE FROM CALENDAR_PAGES") and "RETURNING ID" in normalized:
            if self.store.fail_page:
                raise RuntimeError("forced page delete failure")
            page_id = self.store.pages.pop(key, None)
            return {"id": page_id} if page_id is not None else None
        raise AssertionError(f"unexpected fetchrow SQL: {normalized}")

    async def execute(self, sql, *args):
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("DELETE FROM COMMENTS"):
            if self.store.fail_comments:
                raise RuntimeError("forced comment delete failure")
            target_id = args[0]
            doomed = {
                comment_id
                for comment_id, comment in self.store.comments.items()
                if comment["target_type"] == "calendar_page" and comment["target_id"] == target_id
            }
            while True:
                children = {
                    comment_id
                    for comment_id, comment in self.store.comments.items()
                    if comment["parent_id"] in doomed
                }
                expanded = doomed | children
                if expanded == doomed:
                    break
                doomed = expanded
            for comment_id in doomed:
                self.store.comments.pop(comment_id, None)
            return f"DELETE {len(doomed)}"
        if normalized.startswith("DELETE FROM CALENDAR_PAGES"):
            if self.store.fail_page:
                raise RuntimeError("forced page delete failure")
            removed = self.store.pages.pop((args[0], args[1]), None)
            return "DELETE 1" if removed is not None else "DELETE 0"
        raise AssertionError(f"unexpected execute SQL: {normalized}")


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, store):
        self.conn = FakeConnection(store)

    def acquire(self):
        return FakeAcquire(self.conn)


async def call_delete(store, date_str="2026-07-17"):
    pool = FakePool(store)

    async def fake_get_pool():
        return pool

    with patch.object(database, "get_pool", fake_get_pool):
        return await database.delete_calendar_page(date_str, "day")


async def check_success_and_idempotency():
    store = FakeStore()
    check(await call_delete(store), "existing calendar page must report deleted")
    check((date(2026, 7, 17), "day") not in store.pages, "target page survived deletion")
    check(10 not in store.comments and 11 not in store.comments, "target comments/replies survived deletion")
    check(12 in store.comments, "another page's comment was deleted")
    check(13 in store.comments, "another target type with the same id was deleted")
    check(store.transaction_entries == 1 and store.commits == 1, "delete did not use one transaction")

    check(not await call_delete(store), "repeated delete must report not_found")
    check(12 in store.comments and 13 in store.comments, "idempotent delete touched unrelated comments")


async def check_failure_rolls_back(failure_attr):
    store = FakeStore()
    before = store.snapshot()
    setattr(store, failure_attr, True)
    try:
        await call_delete(store)
    except RuntimeError:
        pass
    else:
        raise AssertionError(f"{failure_attr} did not interrupt deletion")
    check(store.snapshot() == before, f"{failure_attr} left a partially deleted page/comment set")
    check(store.transaction_entries == 1 and store.rollbacks == 1, "failure did not roll back one transaction")


async def main():
    await check_success_and_idempotency()
    await check_failure_rolls_back("fail_page")
    await check_failure_rolls_back("fail_comments")
    print("PASS: calendar page and comments delete atomically")


if __name__ == "__main__":
    asyncio.run(main())
