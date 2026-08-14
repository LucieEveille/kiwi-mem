#!/usr/bin/env python3
"""Permanent S1-S6 safety regression suite for kiwi-mem.

This script intentionally uses a disposable PostgreSQL database.  It refuses
ambient/production-looking database hosts, sets DATABASE_URL before importing
application modules, never starts the FastAPI lifespan, and replaces every
model/embedding/HTTP boundary used by the tests with deterministic fakes.

Run with:

    KIWI_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
      python scripts/test_kiwi_safety_sync.py
"""

from __future__ import annotations

import asyncio
import inspect
import io
import json
import os
import re
import sys
import uuid
import zipfile
from contextlib import redirect_stdout
from datetime import date, datetime as StdDateTime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALLOWED_TEST_HOSTS = {"127.0.0.1", "localhost", "::1"}
DATABASE_PREFIX = "kiwi_safety_"
SYNC_KEYS = (
    "user_avatar",
    "user_nickname",
    "assistant_avatar",
    "assistant_settings",
    "custom_skills",
    "quick_phrases",
    "mcp_switches",
    "theme_preference",
    "reasoning_effort",
)

database: Any = None
config: Any = None
app_module: Any = None
memory_extractor: Any = None
PASSED: list[str] = []


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def passed(name: str) -> None:
    PASSED.append(name)
    print(f"  PASS {name}")


def _validated_admin_dsn() -> str:
    dsn = os.environ.get("KIWI_TEST_DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError(
            "KIWI_TEST_DATABASE_URL is required; the safety suite never falls back "
            "to DATABASE_URL or a developer .env file"
        )
    parsed = urlsplit(dsn)
    require(parsed.scheme in {"postgres", "postgresql"}, "test DSN must be PostgreSQL")
    require(parsed.hostname in ALLOWED_TEST_HOSTS, "test PostgreSQL host must be loopback")
    require(bool(parsed.path.strip("/")), "test DSN must name a maintenance database")
    return dsn


def _dsn_for_database(admin_dsn: str, database_name: str) -> str:
    parsed = urlsplit(admin_dsn)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", parsed.query, ""))


async def _create_disposable_database(admin_dsn: str) -> tuple[str, str]:
    database_name = f"{DATABASE_PREFIX}{uuid.uuid4().hex}"
    require(re.fullmatch(r"kiwi_safety_[0-9a-f]{32}", database_name), "unsafe test DB name")
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await conn.close()
    return database_name, _dsn_for_database(admin_dsn, database_name)


async def _drop_disposable_database(admin_dsn: str, database_name: str) -> None:
    require(re.fullmatch(r"kiwi_safety_[0-9a-f]{32}", database_name), "refusing unsafe DROP")
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await conn.close()


async def _pool_fetchval(sql: str, *args: Any) -> Any:
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


async def _pool_fetchrow(sql: str, *args: Any) -> Any:
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(sql, *args)


async def _pool_fetch(sql: str, *args: Any) -> Any:
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(sql, *args)


async def _pool_execute(sql: str, *args: Any) -> str:
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(sql, *args)


async def _truncate(*tables: str) -> None:
    allowed = {
        "gateway_config",
        "memories",
        "chat_messages",
        "chat_conversations",
        "chat_projects",
        "compression_summaries",
        "project_file_chunks",
        "calendar_pages",
        "comments",
        "dream_logs",
        "mem_scenes",
    }
    require(bool(tables) and set(tables) <= allowed, "unsafe TRUNCATE table")
    await _pool_execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")


async def _upsert_config(key: str, value: str) -> None:
    await _pool_execute(
        """
        INSERT INTO gateway_config (key, value, label, updated_at)
        VALUES ($1, $2, 'safety-test', NOW())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        key,
        value,
    )


async def _config_row(key: str) -> Any:
    return await _pool_fetchval("SELECT value FROM gateway_config WHERE key = $1", key)


async def _seed_memory(
    content: str,
    *,
    locked: bool = False,
    title: str = "",
    project_id: str | None = None,
    memory_type: str = "fragment",
    source: str = "safety_test",
    created_at: Any = None,
    dream_processed: bool = False,
    valid_until: Any = None,
) -> int:
    created_at = created_at or StdDateTime.now(database.TZ_CST)
    dream_processed_at = created_at if dream_processed else None
    return await _pool_fetchval(
        """
        INSERT INTO memories (
            content, title, importance, is_permanent, source, project_id,
            memory_type, created_at, dream_processed_at, valid_until
        )
        VALUES ($1, $2, 5, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        content,
        title,
        locked,
        source,
        project_id,
        memory_type,
        created_at,
        dream_processed_at,
        valid_until,
    )


async def _seed_dream(
    *,
    status: str = "running",
    deleted: bool = False,
    started_at: Any = None,
    narrative: str = "dream-original",
    processed: int = 7,
) -> int:
    started_at = started_at or StdDateTime.now(database.TZ_CST)
    return await _pool_fetchval(
        """
        INSERT INTO dream_logs (
            started_at, status, trigger_type, model_used, memories_processed,
            dream_narrative, deleted
        ) VALUES ($1, $2, 'manual', 'safety-model', $3, $4, $5)
        RETURNING id
        """,
        started_at,
        status,
        processed,
        narrative,
        deleted,
    )


async def _seed_scene(dream_id: int, *, status: str = "active", title: str = "scene") -> int:
    return await _pool_fetchval(
        """
        INSERT INTO mem_scenes (
            title, narrative, atomic_facts, foresight, related_memory_ids,
            embedding, status, created_by_dream_id
        ) VALUES ($1, 'scene-narrative', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
                  '[1.0, 0.0]'::jsonb, $2, $3)
        RETURNING id
        """,
        title,
        status,
        dream_id,
    )


async def test_s1(client: httpx.AsyncClient) -> None:
    print("\nS1 /sync/settings whitelist")
    require(tuple(config.SYNC_SETTING_KEYS) == SYNC_KEYS, "SYNC_SETTING_KEYS/order drifted")
    require(all(key in config.CONFIG_SCHEMA for key in SYNC_KEYS), "sync key outside schema")
    passed("T-S1-1 exact ordered nine-key contract")

    await _truncate("gateway_config", "chat_conversations", "chat_projects", "compression_summaries")
    dangerous_before = {
        "search_api_key": "SAFE-SEARCH-SENTINEL",
        "prompt_title_summary": "SAFE-PROMPT-SENTINEL",
        "memory_enabled": "true",
        "default_chat_model": "SAFE-MODEL-SENTINEL",
    }
    for key, value in dangerous_before.items():
        await _upsert_config(key, value)

    seen_set_config: list[str] = []
    real_set_config = config.set_config

    async def spying_set_config(key: str, value: str) -> bool:
        seen_set_config.append(key)
        return await real_set_config(key, value)

    attack = {
        "user_nickname": "安全昵称",
        "search_api_key": "ATTACK-SEARCH",
        "prompt_title_summary": "ATTACK-PROMPT",
        "memory_enabled": "false",
        "default_chat_model": "ATTACK-MODEL",
    }
    with patch.object(app_module, "set_config", spying_set_config):
        response = await client.put("/sync/settings", json=attack)
    require(response.status_code == 200, f"mixed settings PUT failed: {response.text}")
    body = response.json()
    require(body["updated"] == ["user_nickname"], f"wrong updated set: {body}")
    require(body["rejected"] == list(dangerous_before), f"wrong rejected set: {body}")
    require(seen_set_config == ["user_nickname"], f"dangerous key reached set_config: {seen_set_config}")
    passed("T-S1-2 mixed PUT rejects before set_config")

    require(await _config_row("user_nickname") == "安全昵称", "allowed setting did not persist")
    for key, value in dangerous_before.items():
        require(await _config_row(key) == value, f"dangerous DB value changed: {key}")
    passed("T-S1-3 real PostgreSQL values remain protected")

    response = await client.get("/sync/settings")
    require(response.status_code == 200, response.text)
    require(tuple(response.json().keys()) == SYNC_KEYS, "GET settings keys/order drifted")
    passed("T-S1-4 GET exact key set and order")

    response = await client.get("/sync/export")
    require(response.status_code == 200, response.text)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        settings_json = json.loads(archive.read("settings.json"))
        config_json = json.loads(archive.read("config.json"))
    require(tuple(settings_json.keys()) == SYNC_KEYS, "settings.json contract drifted")
    require(config_json["search_api_key"] == dangerous_before["search_api_key"], "full backup lost config")
    passed("T-S1-5 export keeps nine-key settings and full config backup")

    for key in SYNC_KEYS:
        await _upsert_config(key, f"sync-{key}")
    response = await client.request("DELETE", "/sync/reset", json={"confirm": "RESET_ALL_DATA"})
    require(response.status_code == 200 and response.json()["status"] == "ok", response.text)
    remaining_sync = await _pool_fetchval(
        "SELECT COUNT(*) FROM gateway_config WHERE key = ANY($1::text[])", list(SYNC_KEYS)
    )
    require(remaining_sync == 0, "reset did not remove exactly the sync settings")
    for key, value in dangerous_before.items():
        require(await _config_row(key) == value, f"reset removed management config: {key}")
    passed("T-S1-6 reset removes sync settings only")

    consumers = (
        app_module.api_sync_get_settings,
        app_module.api_sync_put_settings,
        app_module.api_sync_export,
        app_module.api_sync_reset,
    )
    for consumer in consumers:
        source = inspect.getsource(consumer)
        require("SYNC_SETTING_KEYS" in source, f"{consumer.__name__} bypasses shared constant")
        require("sync_keys =" not in source, f"{consumer.__name__} has a local key copy")
    passed("T-S1-7 all four consumers use the single constant")

    readme_zh = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = (ROOT / "README_EN.md").read_text(encoding="utf-8")
    for endpoint in ("/admin", "/sync/export", "/sync/import-backup"):
        require(endpoint in readme_zh and endpoint in readme_en, f"README warning misses {endpoint}")
    require("整个" in readme_zh and "entire service" in readme_en, "whole-service warning missing")
    require("没有内建鉴权" in readme_zh, "Chinese README must disclose missing built-in auth")
    require("not authenticated" in readme_en, "README must not claim built-in authentication")
    passed("T-S1-8 bilingual deployment warning")


async def test_s2() -> None:
    print("\nS2 log redaction")
    await _truncate("memories", "gateway_config")
    content_secret = "内容密钥-ASCII-SECRET-9988-🧪-尾巴"
    title_secret = "标题密钥-TITLE-SECRET-7766-🌙"

    async def vector_embedding(_text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    output = io.StringIO()
    with patch.object(database, "get_embedding", vector_embedding), redirect_stdout(output):
        memory_id = await database.save_memory(
            content_secret,
            title=title_secret,
            emotional_weight=4,
            project_id="project-safety",
        )
    log = output.getvalue()
    require(str(memory_id) in log and str(len(content_secret)) in log and "3维" in log, "allowed metadata missing")
    for forbidden in (content_secret, title_secret, content_secret[:10], title_secret[:10]):
        require(forbidden not in log, f"memory log leaked content: {forbidden}")
    passed("T-S2-1 memory title/content sentinels absent")
    passed("T-S2-2 vector metadata remains useful")

    async def no_embedding(_text: str) -> None:
        return None

    output = io.StringIO()
    with patch.object(database, "get_embedding", no_embedding), redirect_stdout(output):
        await database.save_memory("NO-VECTOR-CONTENT-SECRET", title="NO-VECTOR-TITLE-SECRET")
    require("无向量" in output.getvalue(), "no-vector metadata missing")
    require("NO-VECTOR-CONTENT" not in output.getvalue(), "no-vector path leaked content")

    extraction_secret = "EXTRACT-RAW-SECRET-556677-中文🧪"
    extracted = [
        {
            "content": extraction_secret,
            "importance": 7,
            "emotional_weight": 2,
            "category": "",
        }
    ]

    async def fake_resolve(_model: str) -> tuple[str, str, str]:
        return "http://127.0.0.1:9/mock-memory", "mock-key", "openai"

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "choices": [
                    {"message": {"content": json.dumps(extracted, ensure_ascii=False)}}
                ]
            }

    class FakeAsyncClient:
        calls = 0

        def __init__(self, *args: Any, **kwargs: Any):
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, *args: Any, **kwargs: Any) -> FakeResponse:
            type(self).calls += 1
            return FakeResponse()

    output = io.StringIO()
    with (
        patch.object(database, "resolve_model_endpoint", fake_resolve),
        patch.object(memory_extractor.httpx, "AsyncClient", FakeAsyncClient),
        redirect_stdout(output),
    ):
        result = await memory_extractor.extract_memories(
            [{"role": "user", "content": "test input"}], model_override="mock-model"
        )
    require(FakeAsyncClient.calls == 1, "mock HTTP boundary was not exercised exactly once")
    require(result and result[0]["content"] == extraction_secret, "extractor behavior changed")
    require(extraction_secret not in output.getvalue(), "raw extraction response leaked")
    require(str(len(json.dumps(extracted, ensure_ascii=False))) in output.getvalue(), "length metadata missing")
    passed("T-S2-3 extractor HTTP mocked and raw response redacted")

    key_secret = "sk-VERY-LONG-SECRET-1234567890"
    prompt_secret = "PROMPT-PRIVATE-SENTINEL-" + ("x" * 100)
    output = io.StringIO()
    with redirect_stdout(output):
        await config.set_config("search_api_key", key_secret)
        await config.set_config("prompt_title_summary", prompt_secret)
    safe_log = output.getvalue()
    require(key_secret not in safe_log and prompt_secret not in safe_log, "set_config leaked a secret")
    require(str(len(prompt_secret)) in safe_log, "prompt redaction lost allowed length")
    passed("T-S2-4 existing set_config redaction remains active")

    db_source = inspect.getsource(database.save_memory)
    extractor_source = inspect.getsource(memory_extractor.extract_memories)
    require("content[:50]" not in db_source and "text[:200]" not in extractor_source, "old log slice remains")
    passed("T-S2-5 old content slices absent from source")


async def test_s3() -> None:
    print("\nS3 CST calendar anchor")
    await _truncate("calendar_pages")

    tz_calls: list[Any] = []
    utc_instant = StdDateTime(2026, 7, 16, 16, 30, tzinfo=timezone.utc)

    class FixedDateTime(StdDateTime):
        @classmethod
        def now(cls, tz: Any = None) -> StdDateTime:
            tz_calls.append(tz)
            return utc_instant.astimezone(tz) if tz is not None else utc_instant.replace(tzinfo=None)

    await _pool_execute(
        """
        INSERT INTO calendar_pages (date, type, digest, summary)
        VALUES ('2026-07-15', 'day', 'old', 'old'),
               ('2026-07-16', 'day', 'current', 'current')
        """
    )
    with patch.object(database, "datetime", FixedDateTime):
        result = await database.get_calendar_for_injection(lookback_days=1)
    require(tz_calls == [database.TZ_CST], f"calendar anchor did not request TZ_CST: {tz_calls}")
    require(utc_instant.date() == date(2026, 7, 16), "test UTC fixture drifted")
    require(utc_instant.astimezone(database.TZ_CST).date() == date(2026, 7, 17), "test CST fixture drifted")
    returned_dates = {item["date"] for item in result}
    require(date(2026, 7, 16) in returned_dates, "CST previous day was omitted")
    require(date(2026, 7, 15) not in returned_dates, "UTC-yesterday anchor leaked an extra day")
    passed("T-S3-1 UTC 16:30 maps to CST next natural day")

    await _pool_execute(
        """
        INSERT INTO calendar_pages (date, type, digest, summary)
        VALUES ('2025-01-01', 'year', 'year', 'year'),
               ('2025-07-16', 'day', 'year-source', 'year-source'),
               ('2026-07-01', 'quarter', 'quarter', 'quarter'),
               ('2026-07-01', 'month', 'month', 'month')
        """
    )
    tz_calls.clear()
    with patch.object(database, "datetime", FixedDateTime):
        hierarchical = await database.get_calendar_for_injection(lookback_days=800)
    require(tz_calls == [database.TZ_CST], f"hierarchy path did not request TZ_CST: {tz_calls}")
    require(any(item.get("label") == "2025年总结" for item in hierarchical), "date_cls hierarchy path broke")
    source = inspect.getsource(database.get_calendar_for_injection)
    require("datetime.now(TZ_CST).date()" in source, "CST anchor missing")
    require("date_cls.today()" not in source, "local container date anchor remains")
    require("date as date_cls" in source, "hierarchical date constructor import missing")
    passed("T-S3-2 source guard plus year/quarter/month regression")

    needle_date = ".".join(("date", "today")) + "("
    needle_datetime = ".".join(("datetime", "today")) + "("
    offenders: list[str] = []
    for path in ROOT.rglob("*.py"):
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        if needle_date in text or needle_datetime in text:
            offenders.append(str(path.relative_to(ROOT)))
    require(not offenders, f"today() natural-date calls remain: {offenders}")
    passed("T-S3-3 repository natural-date scan")


async def test_s4(client: httpx.AsyncClient) -> None:
    print("\nS4 guarded memory deletion")
    await _truncate("memories")
    await _upsert_config("memory_enabled", "true")

    unlocked = await _seed_memory("single-unlocked")
    response = await client.delete(f"/debug/memories/{unlocked}")
    require(response.status_code == 200 and response.json()["status"] == "deleted", response.text)
    require(await _pool_fetchval("SELECT COUNT(*) FROM memories WHERE id=$1", unlocked) == 0, "unlocked row remains")

    locked = await _seed_memory("single-locked", locked=True)
    response = await client.delete(f"/debug/memories/{locked}")
    require(response.status_code == 403, response.text)
    require(await _pool_fetchval("SELECT is_permanent FROM memories WHERE id=$1", locked) is True, "locked row changed")
    response = await client.delete(f"/debug/memories/{locked}?force=true")
    require(response.status_code == 200 and response.json()["status"] == "deleted", response.text)
    response = await client.delete("/debug/memories/99999999")
    require(response.status_code == 404, response.text)
    passed("T-S4-1 single-delete behavior matrix")

    unlocked = await _seed_memory("batch-unlocked")
    locked = await _seed_memory("batch-locked", locked=True)
    missing = 99999998
    response = await client.post(
        "/debug/memories/batch-delete",
        json={"ids": [unlocked, locked, missing, unlocked, locked]},
    )
    body = response.json()
    require(response.status_code == 200, response.text)
    require(body["deleted"] == 1, body)
    require(body["rejected"] == [locked] and body["not_found"] == [missing], body)
    require(await _pool_fetchval("SELECT COUNT(*) FROM memories WHERE id=$1", locked) == 1, "locked batch row deleted")
    passed("T-S4-2 mixed batch, dedupe, rejected and not_found")

    force_variants = [False, "true", "false", 1, 0, None]
    for variant in force_variants:
        response = await client.post(
            "/debug/memories/batch-delete", json={"ids": [locked], "force": variant}
        )
        require(response.json()["rejected"] == [locked], f"force variant penetrated: {variant!r}")
    response = await client.post("/debug/memories/batch-delete", json={"ids": [locked]})
    require(response.json()["rejected"] == [locked], "missing force penetrated")
    require(await _pool_fetchval("SELECT COUNT(*) FROM memories WHERE id=$1", locked) == 1, "locked row changed")
    response = await client.post(
        "/debug/memories/batch-delete", json={"ids": [locked], "force": True}
    )
    require(response.json()["deleted"] == 1 and response.json()["rejected"] == [], response.text)
    passed("T-S4-3 JSON force requires identity true")

    await _truncate("memories")
    await _seed_memory("clear-a")
    await _seed_memory("clear-b", locked=True)
    invalid_bodies = [
        {},
        {"force": True},
        {"confirm": "DELETE_ALL_MEMORIES"},
        {"force": "true", "confirm": "DELETE_ALL_MEMORIES"},
        {"force": False, "confirm": "DELETE_ALL_MEMORIES"},
        {"force": 1, "confirm": "DELETE_ALL_MEMORIES"},
        {"force": 0, "confirm": "DELETE_ALL_MEMORIES"},
        {"force": True, "confirm": "delete_all_memories"},
        {"force": None, "confirm": "DELETE_ALL_MEMORIES"},
    ]
    for body in invalid_bodies:
        response = await client.request("DELETE", "/debug/memories", json=body)
        require(response.status_code == 400, f"invalid clear gate passed: {body!r}")
        require(await _pool_fetchval("SELECT COUNT(*) FROM memories") == 2, "invalid clear changed DB")
    response = await client.request(
        "DELETE",
        "/debug/memories",
        content=b"not-json",
        headers={"content-type": "application/json"},
    )
    require(response.status_code == 400 and await _pool_fetchval("SELECT COUNT(*) FROM memories") == 2, "malformed JSON passed")
    passed("T-S4-4 clear double-gate negative matrix")

    response = await client.request(
        "DELETE",
        "/debug/memories",
        json={"force": True, "confirm": "DELETE_ALL_MEMORIES"},
    )
    require(response.status_code == 200 and response.json()["deleted_count"] == 2, response.text)
    require(await _pool_fetchval("SELECT COUNT(*) FROM memories") == 0, "clear did not delete all")
    response = await client.request(
        "DELETE",
        "/debug/memories",
        json={"force": True, "confirm": "DELETE_ALL_MEMORIES"},
    )
    require(response.status_code == 200 and response.json()["deleted_count"] == 0, response.text)
    passed("T-S4-5 guarded clear returns actual row count including empty DB")

    admin_source = (ROOT / "admin-panel/js/pages/memories.js").read_text(encoding="utf-8")
    require("/debug/memories/${id}" in admin_source, "admin single-delete URL missing")
    require("/debug/memories/${id}?force" not in admin_source, "admin silently forces locked delete")
    require("force=true" not in admin_source, "admin panel acquired an automatic force path")
    passed("T-S4-6 admin panel does not auto-force")


async def test_s5(client: httpx.AsyncClient) -> None:
    print("\nS5 DELETE 0 truthfulness")
    truth_table = {
        "DELETE 0": False,
        "DELETE 1": True,
        "UPDATE 0": False,
        "UPDATE 1": True,
        "INSERT 0 0": False,
        "INSERT 0 1": True,
        None: False,
        "": False,
        "DELETE nope": False,
        "DELETE": False,
        "DELETE -1": False,
    }
    for status, expected in truth_table.items():
        require(database._rowcount_nonzero(status) is expected, f"rowcount mismatch: {status!r}")
    passed("T-S5-1 strict command-tag truth table")

    await _truncate("chat_conversations", "compression_summaries")
    response = await client.delete("/sync/conversations/missing-conv")
    require(response.status_code == 200 and response.json() == {"deleted": False}, response.text)
    await _pool_execute("INSERT INTO chat_conversations (id, title) VALUES ('conv-live', 'live')")
    await _pool_execute(
        "INSERT INTO compression_summaries (conversation_id, summary) VALUES ('conv-live', 'summary')"
    )
    response = await client.delete("/sync/conversations/conv-live")
    require(response.json() == {"deleted": True}, response.text)
    require(await _pool_fetchval("SELECT COUNT(*) FROM compression_summaries WHERE conversation_id='conv-live'") == 0, "summary cleanup regressed")

    await _truncate("chat_projects", "project_file_chunks")
    response = await client.delete("/sync/projects/missing-project")
    require(response.status_code == 200 and response.json() == {"deleted": False}, response.text)
    await _pool_execute("INSERT INTO chat_projects (id, name) VALUES ('project-live', 'live')")
    await _pool_execute(
        """
        INSERT INTO project_file_chunks (project_id, file_id, content)
        VALUES ('project-live', 'file-1', 'chunk')
        """
    )
    response = await client.delete("/sync/projects/project-live")
    require(response.json() == {"deleted": True}, response.text)
    require(await _pool_fetchval("SELECT COUNT(*) FROM project_file_chunks WHERE project_id='project-live'") == 0, "file chunks cleanup regressed")

    await _truncate("calendar_pages", "comments")
    response = await client.delete("/admin/calendar/2026-07-17?type=day")
    require(response.status_code == 200 and response.json() == {"status": "not_found"}, response.text)
    page_id = await _pool_fetchval(
        "INSERT INTO calendar_pages (date, type) VALUES ('2026-07-17', 'day') RETURNING id"
    )
    await _pool_execute(
        "INSERT INTO comments (target_type, target_id, content) VALUES ('calendar_page', $1, 'comment')",
        page_id,
    )
    response = await client.delete("/admin/calendar/2026-07-17?type=day")
    require(response.json() == {"status": "ok"}, response.text)
    require(await _pool_fetchval("SELECT COUNT(*) FROM comments WHERE target_id=$1", page_id) == 0, "calendar comments cleanup regressed")
    passed("T-S5-2 three real route paths report missing/existing truthfully")
    passed("T-S5-4 summary, file-chunk and comment cleanup preserved")

    sources = (
        inspect.getsource(database.sync_delete_conversation),
        inspect.getsource(database.sync_delete_project),
        inspect.getsource(database.delete_calendar_page),
    )
    require(all("_rowcount_nonzero" in source for source in sources), "a real caller bypasses helper")
    db_text = (ROOT / "database.py").read_text(encoding="utf-8")
    require('"DELETE" in result' not in db_text and "'DELETE' in result" not in db_text, "bare DELETE substring remains")
    passed("T-S5-3 all three callers use the fail-closed helper")


async def test_s6(client: httpx.AsyncClient) -> None:
    print("\nS6 Dream soft-delete/source chain")
    column = await _pool_fetchrow(
        """
        SELECT is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='dream_logs' AND column_name='deleted'
        """
    )
    require(column and column["is_nullable"] == "NO", "dream deleted column is nullable/missing")
    require("false" in str(column["column_default"]).lower(), "dream deleted default drifted")
    default_dream = await _pool_fetchval(
        "INSERT INTO dream_logs (status, trigger_type) VALUES ('running', 'default-check') RETURNING id"
    )
    require(
        await _pool_fetchval("SELECT deleted FROM dream_logs WHERE id=$1", default_dream) is False,
        "omitting dream_logs.deleted did not use FALSE",
    )
    passed("T-S6-1 init_tables is idempotent and deleted column is safe")

    await _truncate("dream_logs", "mem_scenes")
    dream_id = await _seed_dream(status="completed", narrative="keep-narrative", processed=11)
    scene_id = await _seed_scene(dream_id, title="keep-scene")
    dream_before = dict(await _pool_fetchrow("SELECT * FROM dream_logs WHERE id=$1", dream_id))
    scene_before = dict(await _pool_fetchrow("SELECT * FROM mem_scenes WHERE id=$1", scene_id))
    response = await client.delete(f"/admin/dream/{dream_id}")
    require(response.status_code == 200 and response.json() == {"status": "ok", "deleted": dream_id}, response.text)
    dream = dict(await _pool_fetchrow("SELECT * FROM dream_logs WHERE id=$1", dream_id))
    scene = dict(await _pool_fetchrow("SELECT * FROM mem_scenes WHERE id=$1", scene_id))
    require(dream and dream["deleted"] is True, "dream row was hard-deleted/not marked")
    require(scene and scene["status"] == "deleted" and scene["created_by_dream_id"] == dream_id, "scene source chain broke")
    for key, old_value in dream_before.items():
        if key != "deleted":
            require(dream[key] == old_value, f"soft-delete rewrote dream_logs.{key}")
    for key, old_value in scene_before.items():
        if key != "status":
            require(scene[key] == old_value, f"soft-delete rewrote mem_scenes.{key}")
    passed("T-S6-2 log and scene survive with soft-delete state")

    missing_dream = 987654
    orphan_id = await _seed_scene(missing_dream, title="orphan-scene")
    before = dict(await _pool_fetchrow("SELECT * FROM mem_scenes WHERE id=$1", orphan_id))
    response = await client.delete(f"/admin/dream/{missing_dream}")
    require(response.status_code == 200 and "error" in response.json(), response.text)
    after = dict(await _pool_fetchrow("SELECT * FROM mem_scenes WHERE id=$1", orphan_id))
    require(before == after, "missing dream mutated its orphan scene")
    passed("T-S6-3 missing Dream leaves same-ID orphan scene untouched")

    repeat_dream_before = dict(await _pool_fetchrow("SELECT * FROM dream_logs WHERE id=$1", dream_id))
    repeat_scene_before = dict(await _pool_fetchrow("SELECT * FROM mem_scenes WHERE id=$1", scene_id))
    response = await client.delete(f"/admin/dream/{dream_id}")
    require(response.status_code == 200 and "error" in response.json(), "repeat delete reported success")
    repeat_dream_after = dict(await _pool_fetchrow("SELECT * FROM dream_logs WHERE id=$1", dream_id))
    repeat_scene_after = dict(await _pool_fetchrow("SELECT * FROM mem_scenes WHERE id=$1", scene_id))
    require(repeat_dream_after == repeat_dream_before, "repeat delete changed Dream row")
    require(repeat_scene_after == repeat_scene_before, "repeat delete changed scene row")
    passed("T-S6-4 repeat delete is idempotent and truthful")

    rollback_dream = await _seed_dream(narrative="rollback-dream")
    rollback_scene = await _seed_scene(rollback_dream, title="rollback-scene")
    await _pool_execute(
        """
        CREATE OR REPLACE FUNCTION kiwi_safety_fail_scene_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status = 'deleted' THEN
                RAISE EXCEPTION 'kiwi safety injected scene failure';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    await _pool_execute(
        """
        CREATE TRIGGER kiwi_safety_fail_scene_update
        BEFORE UPDATE ON mem_scenes
        FOR EACH ROW EXECUTE FUNCTION kiwi_safety_fail_scene_update()
        """
    )
    try:
        response = await client.delete(f"/admin/dream/{rollback_dream}")
        require(response.status_code == 200 and "error" in response.json(), "injected failure was hidden as success")
        require(await _pool_fetchval("SELECT deleted FROM dream_logs WHERE id=$1", rollback_dream) is False, "dream update did not roll back")
        require(await _pool_fetchval("SELECT status FROM mem_scenes WHERE id=$1", rollback_scene) == "active", "scene update did not roll back")
    finally:
        await _pool_execute("DROP TRIGGER IF EXISTS kiwi_safety_fail_scene_update ON mem_scenes")
        await _pool_execute("DROP FUNCTION IF EXISTS kiwi_safety_fail_scene_update()")
    passed("T-S6-5 scene failure rolls back the whole transaction")

    await _truncate("dream_logs", "mem_scenes")
    now = StdDateTime.now(database.TZ_CST)
    active_running = await _seed_dream(status="running", started_at=now - timedelta(minutes=30))
    await _seed_dream(status="running", deleted=True, started_at=now - timedelta(minutes=10))
    active_stale = await _seed_dream(status="running", started_at=now - timedelta(hours=5))
    deleted_stale = await _seed_dream(status="running", deleted=True, started_at=now - timedelta(hours=6))
    active_completed = await _seed_dream(status="completed", started_at=now - timedelta(hours=2))
    deleted_completed = await _seed_dream(status="completed", deleted=True, started_at=now - timedelta(hours=1))
    deleted_stale_before = dict(
        await _pool_fetchrow(
            """
            SELECT status, finished_at, dream_narrative, memories_processed,
                   memories_deleted, memories_merged, scenes_created, scenes_updated,
                   foresights_generated
            FROM dream_logs WHERE id=$1
            """,
            deleted_stale,
        )
    )
    status = await database.get_dream_status()
    require(status["current"] and status["current"]["id"] == active_running, "deleted running Dream became current")
    require(status["last_completed"] and status["last_completed"]["id"] == active_completed, "deleted completed Dream became last")
    require(await _pool_fetchval("SELECT status FROM dream_logs WHERE id=$1", active_stale) == "error", "active stale Dream not maintained")
    deleted_stale_after = dict(
        await _pool_fetchrow(
            """
            SELECT status, finished_at, dream_narrative, memories_processed,
                   memories_deleted, memories_merged, scenes_created, scenes_updated,
                   foresights_generated
            FROM dream_logs WHERE id=$1
            """,
            deleted_stale,
        )
    )
    require(deleted_stale_after == deleted_stale_before, "deleted stale Dream lifecycle snapshot changed")
    history_ids = {row["id"] for row in await database.get_dream_history(limit=20)}
    require(deleted_completed not in history_ids and deleted_stale not in history_ids, "deleted Dream appears in history")
    require(active_running in history_ids and active_completed in history_ids, "active Dream disappeared")
    passed("T-S6-6 status, timeout maintenance and history exclude deleted rows")

    active_scene = await _seed_scene(active_running, title="active-visible")
    deleted_scene = await _seed_scene(active_running, status="deleted", title="deleted-hidden")
    active_ids = {row["id"] for row in await database.get_active_scenes()}
    search_ids = {row["id"] for row in await database.search_scenes([1.0, 0.0], limit=10, min_sim=0.0)}
    require(active_scene in active_ids and deleted_scene not in active_ids, "active scene query leaks deleted scene")
    require(active_scene in search_ids and deleted_scene not in search_ids, "scene search leaks deleted scene")
    passed("T-S6-7 soft-deleted scenes are absent from active/search paths")

    late_dream = await _seed_dream(status="running", narrative="before-late", processed=3)
    await _seed_scene(late_dream, title="late-scene")
    advisory_key = 730017
    controller = await asyncpg.connect(database.DATABASE_URL)

    async def wait_for_blocked_query(fragment: str, *, event: str | None = None) -> None:
        deadline = asyncio.get_running_loop().time() + 8
        while asyncio.get_running_loop().time() < deadline:
            row = await controller.fetchrow(
                """
                SELECT wait_event_type, wait_event
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND state = 'active'
                  AND query ILIKE $1
                ORDER BY query_start DESC
                LIMIT 1
                """,
                f"%{fragment}%",
            )
            if row and (event is None or str(row["wait_event"]).lower() == event.lower()):
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"timed out waiting for blocked query: {fragment} / {event}")

    await _pool_execute(
        f"""
        CREATE OR REPLACE FUNCTION kiwi_safety_pause_scene_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock({advisory_key});
            RETURN NEW;
        END;
        $$
        """
    )
    await _pool_execute(
        """
        CREATE TRIGGER kiwi_safety_pause_scene_update
        BEFORE UPDATE ON mem_scenes
        FOR EACH ROW EXECUTE FUNCTION kiwi_safety_pause_scene_update()
        """
    )
    delete_task: asyncio.Task[Any] | None = None
    update_task: asyncio.Task[Any] | None = None
    lock_held = False
    try:
        await controller.execute("SELECT pg_advisory_lock($1)", advisory_key)
        lock_held = True
        delete_task = asyncio.create_task(client.delete(f"/admin/dream/{late_dream}"))
        # The route has already UPDATEd dream_logs (holding its row lock) and is
        # now paused in the scene trigger before transaction commit.
        await wait_for_blocked_query("UPDATE mem_scenes", event="advisory")
        update_task = asyncio.create_task(
            database.update_dream_log(
                late_dream,
                status="completed",
                dream_narrative="late-write-must-not-land",
                memories_processed=999,
            )
        )
        # Prove the late writer is genuinely waiting on the row/transaction lock,
        # rather than merely being scheduled after a completed delete.
        await wait_for_blocked_query("UPDATE dream_logs SET status")
        require(not update_task.done(), "late update did not block behind soft-delete")
        await controller.execute("SELECT pg_advisory_unlock($1)", advisory_key)
        lock_held = False
        response = await delete_task
        await update_task
        require(response.json().get("status") == "ok", response.text)
    finally:
        if lock_held:
            await controller.execute("SELECT pg_advisory_unlock($1)", advisory_key)
        if delete_task is not None and not delete_task.done():
            await delete_task
        if update_task is not None and not update_task.done():
            await update_task
        await controller.close()
        await _pool_execute("DROP TRIGGER IF EXISTS kiwi_safety_pause_scene_update ON mem_scenes")
        await _pool_execute("DROP FUNCTION IF EXISTS kiwi_safety_pause_scene_update()")
    late_row = await _pool_fetchrow(
        "SELECT deleted, status, dream_narrative, memories_processed FROM dream_logs WHERE id=$1",
        late_dream,
    )
    require(late_row["deleted"] is True and late_row["status"] == "running", "late lifecycle update landed")
    require(late_row["dream_narrative"] == "before-late" and late_row["memories_processed"] == 3, "late payload landed")
    control_dream = await _seed_dream(status="running", narrative="control", processed=1)
    await database.update_dream_log(control_dream, status="completed", dream_narrative="control-updated")
    require(await _pool_fetchval("SELECT status FROM dream_logs WHERE id=$1", control_dream) == "completed", "active Dream update regressed")
    passed("T-S6-8 row-lock interleaving blocks late lifecycle writes; active control updates")


async def test_w1_06() -> None:
    print("\nW1-06 calendar page/comment delete atomicity")
    await _truncate("calendar_pages", "comments")

    target_id = await _pool_fetchval(
        "INSERT INTO calendar_pages (date, type) VALUES ('2026-07-18', 'day') RETURNING id"
    )
    target_comment = await _pool_fetchval(
        """
        INSERT INTO comments (target_type, target_id, content)
        VALUES ('calendar_page', $1, 'target') RETURNING id
        """,
        target_id,
    )
    await _pool_execute(
        """
        INSERT INTO comments (target_type, target_id, parent_id, content)
        VALUES ('calendar_page', $1, $2, 'reply')
        """,
        target_id,
        target_comment,
    )

    await _pool_execute(
        """
        CREATE OR REPLACE FUNCTION w1_06_fail_calendar_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'forced W1-06 page delete failure';
        END;
        $$
        """
    )
    await _pool_execute(
        """
        CREATE TRIGGER w1_06_fail_calendar_delete_trigger
        BEFORE DELETE ON calendar_pages
        FOR EACH ROW WHEN (OLD.date = DATE '2026-07-18')
        EXECUTE FUNCTION w1_06_fail_calendar_delete()
        """
    )
    try:
        try:
            await database.delete_calendar_page("2026-07-18", "day")
        except asyncpg.PostgresError:
            pass
        else:
            raise AssertionError("forced page delete failure did not escape")
        require(
            await _pool_fetchval("SELECT COUNT(*) FROM calendar_pages WHERE id=$1", target_id) == 1,
            "failed deletion removed the calendar page",
        )
        require(
            await _pool_fetchval(
                "SELECT COUNT(*) FROM comments WHERE target_type='calendar_page' AND target_id=$1",
                target_id,
            ) == 2,
            "failed deletion did not restore calendar comments",
        )
    finally:
        await _pool_execute("DROP TRIGGER IF EXISTS w1_06_fail_calendar_delete_trigger ON calendar_pages")
        await _pool_execute("DROP FUNCTION IF EXISTS w1_06_fail_calendar_delete()")
    passed("T-W1-06-1 injected second-step failure preserves page and comments")

    keep_page_id = await _pool_fetchval(
        "INSERT INTO calendar_pages (date, type) VALUES ('2026-07-19', 'day') RETURNING id"
    )
    keep_comment_id = await _pool_fetchval(
        """
        INSERT INTO comments (target_type, target_id, content)
        VALUES ('calendar_page', $1, 'keep-page') RETURNING id
        """,
        keep_page_id,
    )
    other_target_id = await _pool_fetchval(
        """
        INSERT INTO comments (target_type, target_id, content)
        VALUES ('memory', $1, 'keep-type') RETURNING id
        """,
        target_id,
    )

    require(await database.delete_calendar_page("2026-07-18", "day"), "existing page was not deleted")
    require(
        await _pool_fetchval("SELECT COUNT(*) FROM calendar_pages WHERE id=$1", target_id) == 0,
        "target page survived successful delete",
    )
    require(
        await _pool_fetchval(
            "SELECT COUNT(*) FROM comments WHERE target_type='calendar_page' AND target_id=$1",
            target_id,
        ) == 0,
        "target comments/replies survived successful delete",
    )
    passed("T-W1-06-2 successful delete removes page and its comment tree")

    require(
        await _pool_fetchval("SELECT COUNT(*) FROM comments WHERE id=$1", keep_comment_id) == 1,
        "another page's comment was deleted",
    )
    require(
        await _pool_fetchval("SELECT COUNT(*) FROM comments WHERE id=$1", other_target_id) == 1,
        "another target type with the same numeric id was deleted",
    )
    passed("T-W1-06-3 unrelated comments remain untouched")

    require(
        not await database.delete_calendar_page("2026-07-18", "day"),
        "repeated delete did not report not_found",
    )
    passed("T-W1-06-4 repeated delete is idempotent")


async def test_w1_08() -> None:
    print("\nW1-08 calendar period identity and legacy isolation")
    import importlib

    periods = importlib.import_module("calendar_periods")
    today = StdDateTime.now(database.TZ_CST).date()
    current_monday = today - timedelta(days=today.weekday())
    previous_week_end = current_monday - timedelta(days=1)
    previous_week_start = previous_week_end - timedelta(days=6)
    previous_month_end = today.replace(day=1) - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)

    await _truncate("calendar_pages", "comments")
    invalid_factories = (
        lambda: database.save_calendar_page(today.replace(day=1).isoformat(), "month", []),
        lambda: database.save_calendar_page((previous_week_start + timedelta(days=1)).isoformat(), "week", []),
        lambda: database.save_calendar_page(previous_week_start.isoformat(), "fortnight", []),
        lambda: database.update_calendar_page_user_edit(today.replace(day=1).isoformat(), "month", diary="bad"),
    )
    for make_awaitable in invalid_factories:
        try:
            await make_awaitable()
        except periods.CalendarPeriodValidationError:
            pass
        else:
            raise AssertionError("invalid/incomplete calendar identity crossed the DB write boundary")
    require(
        await _pool_fetchval("SELECT COUNT(*) FROM calendar_pages") == 0,
        "rejected calendar identities left rows behind",
    )
    passed("T-W1-08-1 DB writes reject unknown, misanchored, and incomplete periods")

    await database.save_calendar_page(today.isoformat(), "day", [])
    await database.save_calendar_page(previous_week_start.isoformat(), "week", [])
    await database.update_calendar_page_user_edit(
        previous_month_start.isoformat(), "month", diary="valid manual summary"
    )
    require(
        await _pool_fetchval("SELECT COUNT(*) FROM calendar_pages") == 3,
        "valid day/completed summaries did not remain writable",
    )
    passed("T-W1-08-2 valid day and completed canonical periods remain writable")

    await _truncate("calendar_pages", "comments")
    bad_week_date = previous_week_start - timedelta(days=13)  # Tuesday, safely older than seven days.
    bad_month_date = previous_month_start + timedelta(days=1)
    bad_week_id = await _pool_fetchval(
        "INSERT INTO calendar_pages (date, type, digest) VALUES ($1, 'week', 'BAD_WEEK') RETURNING id",
        bad_week_date,
    )
    bad_month_id = await _pool_fetchval(
        "INSERT INTO calendar_pages (date, type, digest) VALUES ($1, 'month', 'BAD_MONTH') RETURNING id",
        bad_month_date,
    )
    bad_type_id = await _pool_fetchval(
        "INSERT INTO calendar_pages (date, type, digest) VALUES ($1, 'fortnight', 'BAD_TYPE') RETURNING id",
        previous_month_start,
    )
    premature_created_at = StdDateTime(
        previous_week_end.year, previous_week_end.month, previous_week_end.day,
        12, 0, tzinfo=database.TZ_CST,
    )
    premature_week_id = await _pool_fetchval(
        """
        INSERT INTO calendar_pages (date, type, digest, created_at, updated_at)
        VALUES ($1, 'week', 'PREMATURE_WEEK', $2, $2) RETURNING id
        """,
        previous_week_start,
        premature_created_at,
    )
    source_dates = {bad_week_date, bad_month_date, previous_week_start}
    for index, source_date in enumerate(sorted(source_dates), start=1):
        await _pool_execute(
            """
            INSERT INTO calendar_pages (date, type, digest)
            VALUES ($1, 'day', $2)
            ON CONFLICT (date, type) DO UPDATE SET digest=EXCLUDED.digest
            """,
            source_date,
            f"GOOD_DAY_{index}",
        )

    count_before = await _pool_fetchval("SELECT COUNT(*) FROM calendar_pages")
    audited = await database.get_invalid_calendar_period_pages()
    count_after = await _pool_fetchval("SELECT COUNT(*) FROM calendar_pages")
    require(count_before == count_after, "legacy period audit mutated stored pages")
    audited_ids = {row["id"] for row in audited}
    require(
        {bad_week_id, bad_month_id, bad_type_id, premature_week_id} <= audited_ids,
        f"legacy audit missed invalid identities: {audited_ids}",
    )
    passed("T-W1-08-3 read-only audit diagnoses legacy invalid pages without mutation")

    injected = await database.get_calendar_for_injection(lookback_days=400)
    require(
        not any(row["type"] in {"week", "month", "fortnight"} for row in injected),
        "invalid legacy summaries entered injection or claimed coverage",
    )
    injected_digests = {row.get("digest") for row in injected}
    expected_day_digests = {f"GOOD_DAY_{i}" for i in range(1, len(source_dates) + 1)}
    require(
        expected_day_digests <= injected_digests,
        f"invalid summaries hid their source days: {injected_digests}",
    )
    passed("T-W1-08-4 invalid legacy summaries cannot inject or claim day coverage")

    for source_date in source_dates:
        require(
            await _pool_fetchval(
                "SELECT COUNT(*) FROM calendar_pages WHERE date=$1 AND type='day'", source_date
            ) == 1,
            "legacy isolation moved or deleted a source day",
        )
    passed("T-W1-08-5 legacy isolation preserves original rows for explicit rebuild")

    await database.save_calendar_page(
        previous_week_start.isoformat(), "week", [], digest="REBUILT_WEEK"
    )
    rebuilt = await _pool_fetchrow(
        "SELECT created_at, digest FROM calendar_pages WHERE id=$1", premature_week_id
    )
    require(
        rebuilt["created_at"].astimezone(database.TZ_CST).date() > previous_week_end
        and rebuilt["digest"] == "REBUILT_WEEK",
        "explicit regeneration did not refresh the quarantined authorship epoch",
    )
    audited_after_rebuild = await database.get_invalid_calendar_period_pages()
    require(
        premature_week_id not in {row["id"] for row in audited_after_rebuild},
        "explicit canonical rebuild did not restore period eligibility",
    )
    passed("T-W1-08-6 explicit regeneration releases premature-page quarantine")


async def test_w1_01() -> None:
    print("\nW1-01 project isolation and Dream permanent-memory protection")
    import importlib

    daily_digest = importlib.import_module("daily_digest")
    issues: list[str] = []

    # Dream 的输入池只能看见全局、未锁定的普通碎片。项目碎片与永久记忆都必须留在原位。
    await _truncate("memories", "calendar_pages")
    global_normal = await _seed_memory("dream-global-normal")
    project_a = await _seed_memory("dream-project-a", project_id="project-a")
    project_b = await _seed_memory("dream-project-b", project_id="project-b")
    global_locked = await _seed_memory("dream-global-locked", locked=True)
    candidate_ids = {row["id"] for row in await database.get_unprocessed_memories()}
    expected_candidates = {global_normal}
    if candidate_ids != expected_candidates:
        issues.append(
            "Dream candidates escaped scope/lock guard: "
            f"expected {sorted(expected_candidates)}, got {sorted(candidate_ids)}; "
            f"project ids={[project_a, project_b]}, locked id={global_locked}"
        )

    # 主清理候选：只能删除有日页面兜底的全局普通碎片。
    await _truncate("memories", "calendar_pages")
    old_at = StdDateTime.now(database.TZ_CST) - timedelta(days=40)
    await _pool_execute(
        "INSERT INTO calendar_pages (date, type, diary) VALUES ($1, 'day', 'safety-day')",
        old_at.date(),
    )
    cleanup_global = await _seed_memory(
        "cleanup-global", created_at=old_at, dream_processed=True
    )
    cleanup_project_a = await _seed_memory(
        "cleanup-project-a", project_id="project-a", created_at=old_at, dream_processed=True
    )
    cleanup_project_b = await _seed_memory(
        "cleanup-project-b", project_id="project-b", created_at=old_at, dream_processed=True
    )
    cleanup_locked = await _seed_memory(
        "cleanup-locked", locked=True, created_at=old_at, dream_processed=True
    )
    await daily_digest.cleanup_expired_fragments()
    remaining_cleanup = {
        row["id"] for row in await _pool_fetch("SELECT id FROM memories ORDER BY id")
    }
    expected_cleanup = {cleanup_project_a, cleanup_project_b, cleanup_locked}
    if remaining_cleanup != expected_cleanup or cleanup_global in remaining_cleanup:
        issues.append(
            "expired-fragment cleanup crossed project/lock boundary: "
            f"expected remaining {sorted(expected_cleanup)}, got {sorted(remaining_cleanup)}"
        )

    # dream_merge 的最小保留数只按全局 merge 计算；项目 merge 不能放大可删除额度。
    await _truncate("memories", "calendar_pages")
    await _upsert_config("merge_retention_days", "0")
    await _upsert_config("merge_min_keep", "2")
    global_merges = {
        await _seed_memory(
            f"merge-global-{index}",
            source="dream_merge",
            memory_type="daily_digest",
            created_at=old_at,
            dream_processed=True,
        )
        for index in range(3)
    }
    project_merges = {
        await _seed_memory(
            f"merge-project-{index}",
            project_id="project-a" if index % 2 == 0 else "project-b",
            source="dream_merge",
            memory_type="daily_digest",
            created_at=old_at,
            dream_processed=True,
        )
        for index in range(4)
    }
    await daily_digest.cleanup_expired_fragments()
    remaining_global_merges = {
        row["id"]
        for row in await _pool_fetch(
            "SELECT id FROM memories WHERE source='dream_merge' AND project_id IS NULL"
        )
    }
    remaining_project_merges = {
        row["id"]
        for row in await _pool_fetch(
            "SELECT id FROM memories WHERE source='dream_merge' AND project_id IS NOT NULL"
        )
    }
    if len(remaining_global_merges) != 2 or remaining_project_merges != project_merges:
        issues.append(
            "dream_merge retention counted or deleted project rows: "
            f"global before={sorted(global_merges)}, global after={sorted(remaining_global_merges)}, "
            f"project before={sorted(project_merges)}, project after={sorted(remaining_project_merges)}"
        )

    # 两条 30 天硬删路径都只能触碰全局普通行；项目行和永久行必须保留。
    await _truncate("memories", "calendar_pages")
    deleted_global = await _seed_memory(
        "deleted-global", memory_type="dream_deleted", created_at=old_at
    )
    deleted_project = await _seed_memory(
        "deleted-project", project_id="project-a", memory_type="dream_deleted", created_at=old_at
    )
    deleted_locked = await _seed_memory(
        "deleted-locked", locked=True, memory_type="dream_deleted", created_at=old_at
    )
    expired_at = StdDateTime.now(database.TZ_CST) - timedelta(days=31)
    invalid_global = await _seed_memory(
        "invalid-global", created_at=old_at, valid_until=expired_at
    )
    invalid_project = await _seed_memory(
        "invalid-project", project_id="project-b", created_at=old_at, valid_until=expired_at
    )
    invalid_locked = await _seed_memory(
        "invalid-locked", locked=True, created_at=old_at, valid_until=expired_at
    )
    await daily_digest.cleanup_expired_fragments()
    remaining_hard_delete = {
        row["id"] for row in await _pool_fetch("SELECT id FROM memories ORDER BY id")
    }
    expected_hard_delete = {
        deleted_project,
        deleted_locked,
        invalid_project,
        invalid_locked,
    }
    if remaining_hard_delete != expected_hard_delete:
        issues.append(
            "30-day hard delete crossed project/lock boundary: "
            f"expected remaining {sorted(expected_hard_delete)}, got {sorted(remaining_hard_delete)}; "
            f"allowed deletions={[deleted_global, invalid_global]}"
        )

    require(not issues, " | ".join(issues))
    passed("T-W1-01-1 Dream candidates are global and non-permanent")
    passed("T-W1-01-2 expired-fragment cleanup preserves projects and locks")
    passed("T-W1-01-3 dream_merge retention counts only global rows")
    passed("T-W1-01-4 hard-delete paths preserve projects and locks")


async def test_w2_01(client: httpx.AsyncClient) -> None:
    """W2-01 G1 granular-sync, ownership, gate, and observability guards."""
    expected_routes = {
        ("/sync/conversations", "POST"),
        ("/sync/conversations/{conv_id}", "PATCH"),
        ("/sync/conversations/{conv_id}/messages/{msg_id}", "PUT"),
        ("/sync/conversations/{conv_id}/messages/{msg_id}", "DELETE"),
        ("/sync/projects", "POST"),
        ("/sync/projects/{proj_id}", "PATCH"),
    }
    actual_routes = {
        (route.path, method)
        for route in app_module.app.routes
        for method in (getattr(route, "methods", None) or set())
    }
    missing = sorted(expected_routes - actual_routes)
    require(not missing, f"W2-01 granular routes missing: {missing}")
    require(
        config.CONFIG_SCHEMA.get("sync_legacy_write_enabled", (None, None))[1] == "true",
        "sync_legacy_write_enabled must exist and default to true",
    )

    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    prefix = "w201-"
    proj_a, proj_b = f"{prefix}pa", f"{prefix}pb"
    conv_a, conv_b = f"{prefix}ca", f"{prefix}cb"

    # Create-only project endpoints use server timestamps and never overwrite on replay.
    response = await client.post(
        "/sync/projects",
        json={"id": proj_a, "name": "Project A", "icon": "A", "createdAt": "2000-01-01T00:00:00Z"},
    )
    require(response.status_code == 200, f"project POST failed: {response.status_code} {response.text}")
    response = await client.post("/sync/projects", json={"id": proj_a, "name": "overwritten"})
    require(response.status_code == 409, "duplicate project POST must return 409")
    project_row = await _pool_fetchrow(
        "SELECT name, icon, created_at FROM chat_projects WHERE id = $1", proj_a
    )
    require(project_row["name"] == "Project A" and project_row["icon"] == "A", "project replay overwrote data")
    require(project_row["created_at"].year >= 2026, "project POST trusted client createdAt")
    passed("T-W2-01-1 project POST is create-only and server-timed")

    response = await client.patch(f"/sync/projects/{proj_a}", json={"icon": "PATCHED"})
    require(response.status_code == 200, "project PATCH failed")
    response = await client.patch(f"/sync/projects/{proj_a}", json={"unknown": "x"})
    require(response.status_code == 400, "empty/unknown project PATCH must return 400")
    response = await client.patch(f"/sync/projects/{prefix}missing", json={"name": "x"})
    require(response.status_code == 404, "missing project PATCH must return 404")
    project_row = await _pool_fetchrow("SELECT name, icon FROM chat_projects WHERE id = $1", proj_a)
    require(project_row["name"] == "Project A" and project_row["icon"] == "PATCHED", "project PATCH was not partial")
    passed("T-W2-01-2 project PATCH is partial and never creates")

    await client.post("/sync/projects", json={"id": proj_b, "name": "Project B"})
    response = await client.post(
        "/sync/conversations",
        json={
            "id": conv_a,
            "title": "Conversation A",
            "projectId": proj_a,
            "createdAt": "2000-01-01T00:00:00Z",
            "messages": [{"id": f"{prefix}ignored", "content": "must-not-insert"}],
        },
    )
    require(response.status_code == 200 and response.json().get("warning") == "messages ignored", "conversation POST contract failed")
    response = await client.post("/sync/conversations", json={"id": conv_a, "title": "overwritten"})
    require(response.status_code == 409, "duplicate conversation POST must return 409")
    conv_row = await _pool_fetchrow(
        "SELECT title, project_id, created_at FROM chat_conversations WHERE id = $1", conv_a
    )
    require(conv_row["title"] == "Conversation A" and conv_row["project_id"] == proj_a, "conversation replay overwrote data")
    require(conv_row["created_at"].year >= 2026, "conversation POST trusted client createdAt")
    require(await _pool_fetchval("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = $1", conv_a) == 0, "POST inserted messages")
    passed("T-W2-01-3 conversation POST is metadata-only, create-only, and server-timed")

    response = await client.patch(f"/sync/conversations/{conv_a}", json={"pinned": True})
    require(response.status_code == 200, "conversation PATCH failed")
    response = await client.patch(f"/sync/conversations/{conv_a}", json={"messages": []})
    require(response.status_code == 400, "messages-only conversation PATCH must return 400")
    response = await client.patch(f"/sync/conversations/{prefix}missing", json={"title": "x"})
    require(response.status_code == 404, "missing conversation PATCH must return 404")
    conv_row = await _pool_fetchrow("SELECT title, pinned FROM chat_conversations WHERE id = $1", conv_a)
    require(conv_row["title"] == "Conversation A" and conv_row["pinned"] is True, "conversation PATCH was not partial")
    passed("T-W2-01-4 conversation PATCH is partial and never creates")

    msg_id = f"{prefix}message"
    message_url = f"/sync/conversations/{conv_a}/messages/{msg_id}"
    response = await client.put(message_url, json={"id": "body-id-ignored", "role": "user", "content": "v1", "sortOrder": 7})
    require(response.status_code == 200, "single-message insert failed")
    before_touch = await _pool_fetchval("SELECT updated_at FROM chat_conversations WHERE id = $1", conv_a)
    await asyncio.sleep(0.01)
    response = await client.put(message_url, json={"role": "assistant", "content": "v2"})
    require(response.status_code == 200, "same-ID message replay failed")
    message_row = await _pool_fetchrow(
        "SELECT id, conversation_id, role, content, sort_order FROM chat_messages WHERE id = $1", msg_id
    )
    after_touch = await _pool_fetchval("SELECT updated_at FROM chat_conversations WHERE id = $1", conv_a)
    require(message_row["id"] == msg_id and message_row["conversation_id"] == conv_a, "URL IDs were not authoritative")
    require(message_row["role"] == "assistant" and message_row["content"] == "v2", "message replay did not update snapshot")
    require(message_row["sort_order"] == 7 and after_touch > before_touch, "sort order/timestamp replay contract failed")
    require(await _pool_fetchval("SELECT COUNT(*) FROM chat_messages WHERE id = $1", msg_id) == 1, "message replay created duplicates")
    passed("T-W2-01-5 same message ID replay is idempotent and URL-authoritative")

    await client.post("/sync/conversations", json={"id": conv_b, "title": "Conversation B", "projectId": proj_b})
    original = dict(await _pool_fetchrow("SELECT * FROM chat_messages WHERE id = $1", msg_id))
    response = await client.put(
        f"/sync/conversations/{conv_b}/messages/{msg_id}",
        json={"role": "assistant", "content": "forged-cross-project"},
    )
    require(response.status_code == 409, "cross-project/cross-conversation message forgery must return 409")
    require(dict(await _pool_fetchrow("SELECT * FROM chat_messages WHERE id = $1", msg_id)) == original, "409 changed original message")
    passed("T-W2-01-6 cross-conversation and cross-project message forgery is rejected")

    concurrent_id = f"{prefix}concurrent"
    responses = await asyncio.gather(
        client.put(f"/sync/conversations/{conv_a}/messages/{concurrent_id}", json={"content": "from-a"}),
        client.put(f"/sync/conversations/{conv_b}/messages/{concurrent_id}", json={"content": "from-b"}),
    )
    require(sorted(r.status_code for r in responses) == [200, 409], "concurrent cross-owner writes must yield one 200 and one 409")
    winner = conv_a if responses[0].status_code == 200 else conv_b
    require(await _pool_fetchval("SELECT conversation_id FROM chat_messages WHERE id = $1", concurrent_id) == winner, "concurrent winner ownership changed")
    passed("T-W2-01-7 concurrent same-ID cross-owner writes have exactly one winner")

    response = await client.delete(f"/sync/conversations/{conv_b}/messages/{msg_id}")
    require(response.status_code == 200 and response.json() == {"deleted": False}, "wrong-owner delete was not rejected")
    response = await client.delete(message_url)
    require(response.status_code == 200 and response.json() == {"deleted": True}, "correct-owner delete failed")
    response = await client.delete(message_url)
    require(response.status_code == 200 and response.json() == {"deleted": False}, "repeat delete was not idempotent")
    passed("T-W2-01-8 single-message delete is owner-scoped and idempotent")

    atomic_conv, atomic_msg = f"{prefix}atomic-conv", f"{prefix}atomic-msg"
    await client.post("/sync/conversations", json={"id": atomic_conv, "title": "atomic"})
    await _pool_execute(
        """
        CREATE OR REPLACE FUNCTION w201_fail_parent_touch() RETURNS trigger AS $fn$
        BEGIN
            IF NEW.id = 'w201-atomic-conv' THEN RAISE EXCEPTION 'W2-01 injected parent-touch failure'; END IF;
            RETURN NEW;
        END; $fn$ LANGUAGE plpgsql
        """
    )
    await _pool_execute(
        "CREATE TRIGGER w201_fail_parent_touch_trg BEFORE UPDATE ON chat_conversations "
        "FOR EACH ROW EXECUTE FUNCTION w201_fail_parent_touch()"
    )
    try:
        response = await client.put(
            f"/sync/conversations/{atomic_conv}/messages/{atomic_msg}", json={"content": "must-roll-back"}
        )
        require(response.status_code == 500, "injected transaction failure must surface as 500")
        require(
            not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_messages WHERE id = $1)", atomic_msg),
            "message half-state survived parent-touch failure",
        )
    finally:
        await _pool_execute("DROP TRIGGER IF EXISTS w201_fail_parent_touch_trg ON chat_conversations")
        await _pool_execute("DROP FUNCTION IF EXISTS w201_fail_parent_touch()")
    passed("T-W2-01-9 message write and parent timestamp are one transaction")

    legacy_conv, legacy_proj = f"{prefix}legacy-conv", f"{prefix}legacy-proj"
    sentinel = "W2_01_PAYLOAD_MUST_STAY_PRIVATE"
    gate_key = "sync_legacy_write_enabled"
    gate_had_row = await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM gateway_config WHERE key = $1)", gate_key)
    gate_previous = await _config_row(gate_key)
    try:
        require(await config.get_config_bool(gate_key, True) is True, "legacy gate is not open by default")
        capture = io.StringIO()
        with redirect_stdout(capture):
            response_conv_open = await client.put(
                f"/sync/conversations/{legacy_conv}",
                json={"title": sentinel, "messages": [{"id": f"{prefix}legacy-msg", "content": sentinel}]},
            )
            response_proj_open = await client.put(
                f"/sync/projects/{legacy_proj}", json={"name": sentinel, "description": sentinel}
            )
        require(response_conv_open.status_code == 200 and response_proj_open.status_code == 200, "default-open legacy PUT failed")
        require(await _pool_fetchval("SELECT content FROM chat_messages WHERE id = $1", f"{prefix}legacy-msg") == sentinel, "old conversation payload broke")
        passed("T-W2-01-10 default-open legacy PUTs preserve old-client payloads")

        await _upsert_config(gate_key, "false")
        blocked_capture = io.StringIO()
        with redirect_stdout(blocked_capture):
            response_conv_closed = await client.put(f"/sync/conversations/{legacy_conv}", json={"title": sentinel})
            response_proj_closed = await client.put(f"/sync/projects/{legacy_proj}", json={"name": sentinel})
        require(response_conv_closed.status_code == 410 and response_proj_closed.status_code == 410, "closed gate did not retire both legacy PUTs")
        import_response = await client.post("/sync/import", json={"conversations": [], "projects": []})
        require(import_response.status_code == 200 and import_response.json().get("status") == "ok", "/sync/import was incorrectly gated")
        fresh_response = await client.post("/sync/projects", json={"id": f"{prefix}gate-fresh", "name": "fresh"})
        require(fresh_response.status_code == 200, "new granular endpoint was incorrectly gated")
        passed("T-W2-01-11 closed gate affects only two legacy PUTs; import stays W2-02")

        events = capture.getvalue() + blocked_capture.getvalue()
        expected_events = {
            "event=sync_legacy_write endpoint=conversation_put outcome=allowed increment=1",
            "event=sync_legacy_write endpoint=project_put outcome=allowed increment=1",
            "event=sync_legacy_write endpoint=conversation_put outcome=blocked increment=1",
            "event=sync_legacy_write endpoint=project_put outcome=blocked increment=1",
        }
        actual_events = {line.strip() for line in events.splitlines() if line.startswith("event=sync_legacy_write ")}
        require(actual_events == expected_events, f"legacy counter events mismatch: {sorted(actual_events)}")
        require(sentinel not in events and legacy_conv not in events and legacy_proj not in events, "legacy observability leaked payload or entity IDs")
        passed("T-W2-01-12 legacy structured count events contain no payload or entity IDs")
    finally:
        if gate_had_row:
            await _upsert_config(gate_key, gate_previous)
        else:
            await _pool_execute("DELETE FROM gateway_config WHERE key = $1", gate_key)

    malformed = await client.post("/sync/conversations", content=b"[1,2,3]", headers={"content-type": "application/json"})
    require(malformed.status_code == 400, "new JSON-object endpoint accepted an array body")


# ---------------------------------------------------------------------------
# W2-02 | G1.1 message identity fields and atomic import
# ---------------------------------------------------------------------------

_MESSAGE_CONTENT_COLUMNS = (
    "role", "content", "time", "model", "streaming", "error",
    "token_info", "thinking", "status_events", "tool_events",
    "memory_result", "memory_event", "handoff_info", "web_search_results",
    "versions", "version_index", "images", "attachments", "usage", "summary",
    "dream_event", "turn_key",
)


async def _install_fail_trigger(table: str, name: str, column: str, match: str, message: str) -> None:
    """Raise a server-side exception for one specific row, to prove transaction edges."""
    await _pool_execute(
        f"""
        CREATE OR REPLACE FUNCTION {name}() RETURNS trigger AS $fn$
        BEGIN
            IF NEW.{column} = '{match}' THEN RAISE EXCEPTION '{message}'; END IF;
            RETURN NEW;
        END; $fn$ LANGUAGE plpgsql
        """
    )
    await _pool_execute(f"DROP TRIGGER IF EXISTS {name}_trg ON {table}")
    await _pool_execute(
        f"CREATE TRIGGER {name}_trg BEFORE INSERT OR UPDATE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {name}()"
    )


async def _drop_fail_trigger(table: str, name: str) -> None:
    await _pool_execute(f"DROP TRIGGER IF EXISTS {name}_trg ON {table}")
    await _pool_execute(f"DROP FUNCTION IF EXISTS {name}()")


async def test_w2_02(client: httpx.AsyncClient) -> None:
    """W2-02 G1.1 message identity fields, atomic import, and receipt guards."""
    prefix = "w202-"

    # ---- schema: additive, nullable, no default, no index -------------------
    schema_rows = {
        row["column_name"]: row
        for row in await _pool_fetch(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'chat_messages' AND column_name = ANY($1::text[])
            """,
            ["dream_event", "turn_key"],
        )
    }
    missing_cols = sorted({"dream_event", "turn_key"} - set(schema_rows))
    require(not missing_cols, f"W2-02 chat_messages columns missing: {missing_cols}")
    require(schema_rows["dream_event"]["data_type"] == "jsonb", "dream_event must be jsonb")
    require(schema_rows["turn_key"]["data_type"] == "text", "turn_key must be text")
    for col in ("dream_event", "turn_key"):
        require(schema_rows[col]["is_nullable"] == "YES", f"{col} must be nullable")
        require(schema_rows[col]["column_default"] is None, f"{col} must have no default")
    indexed = await _pool_fetchval(
        """
        SELECT COUNT(*) FROM pg_indexes
        WHERE tablename = 'chat_messages'
          AND (indexdef LIKE '%dream_event%' OR indexdef LIKE '%turn_key%')
        """
    )
    require(indexed == 0, "W2-02 columns must not be indexed in this ticket")
    passed("T-W2-02-1 dream_event/turn_key are nullable, default-free, unindexed")

    # init_tables() already ran twice in run_suite; re-running here proves the new
    # migration block is still idempotent after the columns exist.
    await database.init_tables()
    recheck = await _pool_fetchval(
        """
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_name = 'chat_messages' AND column_name = ANY($1::text[])
        """,
        ["dream_event", "turn_key"],
    )
    require(recheck == 2, "repeat init_tables() disturbed the W2-02 columns")
    passed("T-W2-02-2 repeat init_tables() is idempotent for the new columns")

    # ---- legacy database upgrade path --------------------------------------
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    legacy_conv, legacy_msg = f"{prefix}old-conv", f"{prefix}old-msg"
    await _pool_execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS dream_event")
    await _pool_execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS turn_key")
    await _pool_execute(
        "INSERT INTO chat_conversations (id, title) VALUES ($1, $2)", legacy_conv, "legacy"
    )
    await _pool_execute(
        "INSERT INTO chat_messages (id, conversation_id, role, content) VALUES ($1, $2, $3, $4)",
        legacy_msg, legacy_conv, "user", "legacy-body",
    )
    await database.init_tables()
    upgraded = await _pool_fetchrow(
        "SELECT content, dream_event, turn_key FROM chat_messages WHERE id = $1", legacy_msg
    )
    require(upgraded is not None, "legacy row vanished during migration")
    require(upgraded["content"] == "legacy-body", "migration damaged existing message content")
    require(upgraded["dream_event"] is None and upgraded["turn_key"] is None,
            "existing rows must backfill to NULL, never to a synthesized value")
    passed("T-W2-02-3 old databases upgrade in place with NULL backfill")

    # ---- field assembly: both channels, both key styles ---------------------
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    imp_conv, imp_msg_camel, imp_msg_snake = f"{prefix}imp-c", f"{prefix}imp-m1", f"{prefix}imp-m2"
    response = await client.post(
        "/sync/import",
        json={
            "conversations": [{
                "id": imp_conv, "title": "import",
                "messages": [
                    {"id": imp_msg_camel, "role": "user", "content": "a",
                     "dreamEvent": {"stage": "camel"}, "turnKey": "tk-camel"},
                    {"id": imp_msg_snake, "role": "assistant", "content": "b",
                     "dream_event": {"stage": "snake"}, "turn_key": "tk-snake"},
                ],
            }],
            "projects": [],
        },
    )
    require(response.status_code == 200, f"import failed: {response.status_code} {response.text}")
    camel_row = await _pool_fetchrow(
        "SELECT dream_event, turn_key FROM chat_messages WHERE id = $1", imp_msg_camel
    )
    snake_row = await _pool_fetchrow(
        "SELECT dream_event, turn_key FROM chat_messages WHERE id = $1", imp_msg_snake
    )
    require(json.loads(camel_row["dream_event"])["stage"] == "camel" and camel_row["turn_key"] == "tk-camel",
            "import dropped camelCase dreamEvent/turnKey")
    require(json.loads(snake_row["dream_event"])["stage"] == "snake" and snake_row["turn_key"] == "tk-snake",
            "import dropped snake_case dream_event/turn_key")
    passed("T-W2-02-4 import writes the new fields in both key styles")

    gran_conv, gran_msg = f"{prefix}gran-c", f"{prefix}gran-m"
    await client.post("/sync/conversations", json={"id": gran_conv, "title": "granular"})
    response = await client.put(
        f"/sync/conversations/{gran_conv}/messages/{gran_msg}",
        json={"role": "user", "content": "a", "dreamEvent": {"stage": "camel"}, "turnKey": "tk-camel"},
    )
    require(response.status_code == 200, "granular upsert with new fields failed")
    gran_row = await _pool_fetchrow(
        "SELECT dream_event, turn_key FROM chat_messages WHERE id = $1", gran_msg
    )
    require(json.loads(gran_row["dream_event"])["stage"] == "camel" and gran_row["turn_key"] == "tk-camel",
            "granular upsert dropped the new fields")
    passed("T-W2-02-5 granular upsert writes the new fields")

    # Same payload through both channels must land byte-identical on every content column.
    both_conv, both_msg = f"{prefix}both-c", f"{prefix}both-m"
    shared_payload = {
        "role": "assistant", "content": "shared-body", "model": "m-1",
        "thinking": "t", "summary": "s", "versionIndex": 3,
        "tokenInfo": {"in": 1}, "statusEvents": [{"e": 1}], "toolEvents": [{"t": 1}],
        "memoryResult": {"m": 1}, "memoryEvent": {"me": 1}, "handoffInfo": {"h": 1},
        "webSearchResults": [{"w": 1}], "versions": [{"v": 1}], "images": [{"i": 1}],
        "attachments": [{"a": 1}], "usage": {"u": 1},
        "dreamEvent": {"d": 1}, "turnKey": "tk-shared", "error": True,
        "time": "2026-05-05T05:05:05Z",
    }
    await client.post("/sync/import", json={
        "conversations": [{"id": both_conv, "title": "both",
                           "messages": [dict(shared_payload, id=both_msg)]}],
        "projects": [],
    })
    import_cols = await _pool_fetchrow(
        f"SELECT {', '.join(_MESSAGE_CONTENT_COLUMNS)} FROM chat_messages WHERE id = $1", both_msg
    )
    await _pool_execute("DELETE FROM chat_messages WHERE id = $1", both_msg)
    response = await client.put(
        f"/sync/conversations/{both_conv}/messages/{both_msg}", json=dict(shared_payload)
    )
    require(response.status_code == 200, "granular upsert of the shared payload failed")
    granular_cols = await _pool_fetchrow(
        f"SELECT {', '.join(_MESSAGE_CONTENT_COLUMNS)} FROM chat_messages WHERE id = $1", both_msg
    )
    divergent = [c for c in _MESSAGE_CONTENT_COLUMNS if import_cols[c] != granular_cols[c]]
    require(not divergent, f"import and granular channels diverged on: {divergent}")
    passed("T-W2-02-6 both write channels assemble all 22 content columns identically")

    # ---- old-client compatibility: missing fields fall back to NULL ---------
    await client.put(
        f"/sync/conversations/{gran_conv}/messages/{gran_msg}",
        json={"role": "user", "content": "refilled", "dreamEvent": {"x": 1}, "turnKey": "tk-x"},
    )
    response = await client.put(
        f"/sync/conversations/{gran_conv}/messages/{gran_msg}",
        json={"role": "user", "content": "old-client"},
    )
    require(response.status_code == 200, "old-client payload without the new fields was rejected")
    stale = await _pool_fetchrow(
        "SELECT dream_event, turn_key, content FROM chat_messages WHERE id = $1", gran_msg
    )
    require(stale["content"] == "old-client", "full-snapshot semantics broke for content")
    require(stale["dream_event"] is None and stale["turn_key"] is None,
            "old payload must clear the new fields, not retain stale values")
    old_import_conv, old_import_msg = f"{prefix}oldimp-c", f"{prefix}oldimp-m"
    await client.post("/sync/import", json={
        "conversations": [{"id": old_import_conv, "title": "old",
                           "messages": [{"id": old_import_msg, "role": "user", "content": "x"}]}],
        "projects": [],
    })
    old_row = await _pool_fetchrow(
        "SELECT dream_event, turn_key FROM chat_messages WHERE id = $1", old_import_msg
    )
    require(old_row["dream_event"] is None and old_row["turn_key"] is None,
            "old import payload must write NULL for the new fields")
    passed("T-W2-02-7 payloads lacking the new fields write NULL on both channels")

    # ---- import atomicity: no shell conversations ---------------------------
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    fail_conv, ok_conv = f"{prefix}fail-c", f"{prefix}ok-c"
    await _install_fail_trigger(
        "chat_messages", "w202_fail_msg", "conversation_id", fail_conv,
        "W2-02 injected message failure",
    )
    try:
        response = await client.post("/sync/import", json={
            "conversations": [
                {"id": fail_conv, "title": "doomed",
                 "messages": [{"id": f"{prefix}fail-m", "role": "user", "content": "x"}]},
                {"id": ok_conv, "title": "healthy",
                 "messages": [{"id": f"{prefix}ok-m", "role": "user", "content": "y"}]},
            ],
            "projects": [],
        })
        require(response.status_code == 200, "import must stay 200 for per-entity failures")
        body = response.json()
        require(
            not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = $1)", fail_conv),
            "metadata survived a failed message write: half-imported shell conversation",
        )
        require(body["counts"]["conversations"]["failed"] == 1, "failed conversation was not counted as failed")
        require(fail_conv not in body["imported_conversation_ids"], "failed conversation entered the success IDs")
        require(
            await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_messages WHERE conversation_id = $1)", ok_conv),
            "a sibling failure blocked a healthy conversation",
        )
        require(ok_conv in body["imported_conversation_ids"], "healthy conversation missing from success IDs")
        passed("T-W2-02-8 message failure rolls back its conversation and spares siblings")
    finally:
        await _drop_fail_trigger("chat_messages", "w202_fail_msg")

    # Update path: metadata must not be overwritten when the message write fails.
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    upd_conv, upd_msg = f"{prefix}upd-c", f"{prefix}upd-m"
    await client.post("/sync/import", json={
        "conversations": [{"id": upd_conv, "title": "original-title", "model": "original-model",
                           "messages": [{"id": upd_msg, "role": "user", "content": "original-body"}]}],
        "projects": [],
    })
    await _install_fail_trigger(
        "chat_messages", "w202_fail_upd", "conversation_id", upd_conv,
        "W2-02 injected update failure",
    )
    try:
        await client.post("/sync/import", json={
            "conversations": [{"id": upd_conv, "title": "NEW-title", "model": "NEW-model",
                               "messages": [{"id": f"{prefix}upd-m2", "role": "user", "content": "NEW-body"}]}],
            "projects": [],
        })
        meta = await _pool_fetchrow("SELECT title, model FROM chat_conversations WHERE id = $1", upd_conv)
        require(meta["title"] == "original-title" and meta["model"] == "original-model",
                "conversation metadata was overwritten while its messages rolled back")
        body_row = await _pool_fetchrow("SELECT content FROM chat_messages WHERE id = $1", upd_msg)
        require(body_row is not None and body_row["content"] == "original-body",
                "original messages were lost to a failed update")
        passed("T-W2-02-9 failed update leaves metadata and messages on the same old version")
    finally:
        await _drop_fail_trigger("chat_messages", "w202_fail_upd")

    # ---- per-entity isolation: project / metadata / message failures --------
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    bad_proj, good_proj = f"{prefix}bad-p", f"{prefix}good-p"
    await _install_fail_trigger("chat_projects", "w202_fail_proj", "id", bad_proj,
                                "W2-02 injected project failure")
    try:
        response = await client.post("/sync/import", json={
            "conversations": [{"id": f"{prefix}iso-c", "title": "iso", "messages": []}],
            "projects": [{"id": bad_proj, "name": "doomed"}, {"id": good_proj, "name": "healthy"}],
        })
        body = response.json()
        require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_projects WHERE id = $1)", bad_proj),
                "failed project left a half state")
        require(await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_projects WHERE id = $1)", good_proj),
                "a failed project blocked a healthy sibling project")
        require(await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = $1)", f"{prefix}iso-c"),
                "a failed project blocked conversation import")
        require(body["counts"]["projects"] == {"success": 1, "rejected": 0, "failed": 1},
                f"project counts wrong: {body['counts']['projects']}")
        require(body["imported_project_ids"] == [good_proj], "project success IDs include a failed entity")
        passed("T-W2-02-10 project write failure is isolated to that project")
    finally:
        await _drop_fail_trigger("chat_projects", "w202_fail_proj")

    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    meta_fail_conv = f"{prefix}metafail-c"
    await _install_fail_trigger("chat_conversations", "w202_fail_meta", "id", meta_fail_conv,
                                "W2-02 injected metadata failure")
    try:
        response = await client.post("/sync/import", json={
            "conversations": [
                {"id": meta_fail_conv, "title": "doomed",
                 "messages": [{"id": f"{prefix}metafail-m", "role": "user", "content": "x"}]},
                {"id": f"{prefix}metaok-c", "title": "healthy", "messages": []},
            ],
            "projects": [{"id": f"{prefix}metaok-p", "name": "healthy"}],
        })
        body = response.json()
        require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = $1)", meta_fail_conv),
                "failed metadata write left a conversation row")
        require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_messages WHERE conversation_id = $1)", meta_fail_conv),
                "messages survived a failed metadata write")
        require(await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = $1)", f"{prefix}metaok-c"),
                "a failed conversation blocked a healthy sibling")
        require(await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_projects WHERE id = $1)", f"{prefix}metaok-p"),
                "a failed conversation blocked project import")
        require(body["counts"]["conversations"]["failed"] == 1, "metadata failure was not counted")
        passed("T-W2-02-11 metadata write failure is isolated and leaves no messages")
    finally:
        await _drop_fail_trigger("chat_conversations", "w202_fail_meta")

    # ---- structured receipt and reconciliation ------------------------------
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    response = await client.post("/sync/import", json={
        "conversations": [
            {"id": f"{prefix}r1", "title": "r1", "messages": [
                {"id": f"{prefix}r1m1", "role": "user", "content": "a"},
                {"id": f"{prefix}r1m2", "role": "assistant", "content": "b"},
            ]},
            {"id": f"{prefix}r2", "title": "r2", "messages": []},
            {"title": "no id at all", "messages": []},
        ],
        "projects": [{"id": f"{prefix}rp1", "name": "p1"}],
    })
    require(response.status_code == 200, "receipt import failed")
    body = response.json()
    for legacy_key in ("conversations", "messages", "projects", "errors",
                       "imported_conversation_ids", "imported_project_ids", "error_details"):
        require(legacy_key in body, f"receipt dropped the legacy key {legacy_key}")
    require(body["conversations"] == body["counts"]["conversations"]["success"],
            "legacy conversation count != counts.conversations.success")
    require(body["projects"] == body["counts"]["projects"]["success"],
            "legacy project count != counts.projects.success")
    require(body["messages"] == body["counts"]["messages"]["success"],
            "legacy message count != counts.messages.success")
    require(body["conversations"] == len(body["imported_conversation_ids"]),
            "conversation success count != committed ID array length")
    require(body["projects"] == len(body["imported_project_ids"]),
            "project success count != committed ID array length")
    require(body["counts"]["conversations"]["rejected"] == 1, "id-less conversation was not rejected")
    require(len(body["rejected_details"]) == 1 and body["rejected_details"][0]["code"] == "missing_id",
            f"rejected_details wrong: {body.get('rejected_details')}")
    require(body["messages"] == 2, "message success count did not match committed rows")
    passed("T-W2-02-12 receipt keeps legacy keys and reconciles against committed rows")

    # ---- input precheck: top-level 400, per-entity rejected -----------------
    for bad_body in ([1, 2, 3], {"conversations": "nope"}, {"projects": {"a": 1}}):
        response = await client.post("/sync/import", json=bad_body)
        require(response.status_code == 400,
                f"malformed top-level import body was not 400: {bad_body!r} -> {response.status_code}")
    passed("T-W2-02-13 malformed top-level import bodies return 400")

    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    dup = f"{prefix}dup-c"
    response = await client.post("/sync/import", json={
        "conversations": [
            "not-a-dict",
            {"title": "missing id"},
            {"id": dup, "title": "first", "messages": []},
            {"id": dup, "title": "second", "messages": []},
            {"id": f"{prefix}badmsgs", "title": "bad messages", "messages": "nope"},
            {"id": f"{prefix}badmsgitem", "title": "bad message item", "messages": ["x"]},
        ],
        "projects": ["not-a-dict", {"name": "missing id"}],
    })
    require(response.status_code == 200, "per-entity rejects must not fail the whole batch")
    body = response.json()
    codes = [d["code"] for d in body["rejected_details"]]
    for expected in ("invalid_item", "missing_id", "duplicate_id", "invalid_messages", "invalid_message_item"):
        require(expected in codes, f"reject code {expected} missing from {codes}")
    require(body["counts"]["conversations"]["rejected"] == 5,
            f"conversation rejected count wrong: {body['counts']['conversations']}")
    require(body["counts"]["projects"]["rejected"] == 2,
            f"project rejected count wrong: {body['counts']['projects']}")
    require(body["counts"]["conversations"]["success"] == 1, "the one valid conversation did not import")
    require(await _pool_fetchval("SELECT title FROM chat_conversations WHERE id = $1", dup) == "first",
            "duplicate id overwrote the first accepted conversation")
    require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = '')"),
            "an id-less conversation was silently written with an empty id")
    require(body["counts"]["conversations"]["failed"] == 0, "rejects must not be counted as failures")
    passed("T-W2-02-14 per-entity rejects are coded, counted, and never written")

    # ---- message semantics: absent / empty / shorter array ------------------
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    sem_conv = f"{prefix}sem-c"
    await client.post("/sync/import", json={
        "conversations": [{"id": sem_conv, "title": "v1", "messages": [
            {"id": f"{prefix}sem-m1", "role": "user", "content": "1"},
            {"id": f"{prefix}sem-m2", "role": "assistant", "content": "2"},
            {"id": f"{prefix}sem-m3", "role": "user", "content": "3"},
        ]}],
        "projects": [],
    })
    require(await _pool_fetchval("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = $1", sem_conv) == 3,
            "seed import did not write three messages")

    response = await client.post("/sync/import", json={
        "conversations": [{"id": sem_conv, "title": "v2-metadata-only"}], "projects": [],
    })
    require(response.status_code == 200, "metadata-only import failed")
    require(await _pool_fetchval("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = $1", sem_conv) == 3,
            "absent messages key must preserve existing messages")
    require(await _pool_fetchval("SELECT title FROM chat_conversations WHERE id = $1", sem_conv) == "v2-metadata-only",
            "metadata-only import did not update metadata")
    require(response.json()["counts"]["messages"]["success"] == 0,
            "metadata-only import must not claim message writes")

    await client.post("/sync/import", json={
        "conversations": [{"id": sem_conv, "title": "v3", "messages": [
            {"id": f"{prefix}sem-m1", "role": "user", "content": "1-kept"},
        ]}],
        "projects": [],
    })
    remaining = await _pool_fetch(
        "SELECT id FROM chat_messages WHERE conversation_id = $1 ORDER BY id", sem_conv
    )
    require([r["id"] for r in remaining] == [f"{prefix}sem-m1"],
            "a shorter array must replace the set and delete the difference")

    response = await client.post("/sync/import", json={
        "conversations": [{"id": sem_conv, "title": "v4", "messages": []}], "projects": [],
    })
    require(response.status_code == 200, "explicit empty-array import failed")
    require(await _pool_fetchval("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = $1", sem_conv) == 0,
            "explicit empty array must clear the conversation")
    passed("T-W2-02-15 absent / empty / shorter message arrays have distinct semantics")

    # ---- error safety: no sentinel leaks anywhere ---------------------------
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    sentinel = f"W2_02_SECRET_{uuid.uuid4().hex}"
    leak_conv = f"{prefix}leak-c"
    await _install_fail_trigger("chat_messages", "w202_leak", "conversation_id", leak_conv, sentinel)
    try:
        capture = io.StringIO()
        with redirect_stdout(capture):
            response = await client.post("/sync/import", json={
                "conversations": [{"id": leak_conv, "title": "leaky",
                                   "messages": [{"id": f"{prefix}leak-m", "role": "user", "content": "x"}]}],
                "projects": [],
            })
        raw = response.text
        body = response.json()
        require(sentinel not in raw, "database error text leaked into the import HTTP response")
        require(all(sentinel not in str(e) for e in body["errors"]), "sentinel leaked into errors[]")
        require(all(sentinel not in str(d.get("error", "")) for d in body["error_details"]),
                "sentinel leaked into error_details[].error")
        require(sentinel not in capture.getvalue(), "sentinel leaked into structured logs")
        require(body["error_details"] and body["error_details"][0].get("code"),
                "error_details must carry a controlled code")
        require(body["error_details"][0]["id"] == leak_conv,
                "error_details must still name the entity for reconciliation")
        passed("T-W2-02-16 database error text never reaches responses or logs")
    finally:
        await _drop_fail_trigger("chat_messages", "w202_leak")

    # ---- frozen rule: no 'delete latest assistant message' inference --------
    # Scope note: this guard covers the chat_messages sync channel only.  The
    # conversations event-ledger helper delete_latest_assistant_message() is a
    # known W2-07 debt and is deliberately out of this guard's reach.
    source = (ROOT / "database.py").read_text(encoding="utf-8")
    deletes = re.findall(r"DELETE FROM chat_messages[^\"']*", source)
    require(deletes, "expected at least one chat_messages delete statement to audit")
    for statement in deletes:
        flat = " ".join(statement.split())
        require("WHERE" in flat, f"unconditional chat_messages delete: {flat}")
        require("ORDER BY" not in flat and "LIMIT" not in flat,
                f"chat_messages delete infers rows by ordering: {flat}")
        require("role" not in flat.lower(),
                f"chat_messages delete branches on role: {flat}")
    passed("T-W2-02-17 chat_messages deletes stay deterministic, never role/order inferred")


async def run_suite(test_dsn: str) -> None:
    global database, config, app_module, memory_extractor

    # Hard overwrite every captured-at-import boundary.  Do not use setdefault.
    os.environ["DATABASE_URL"] = test_dsn
    os.environ["MEMORY_ENABLED"] = "true"
    os.environ["API_KEY"] = ""
    os.environ["MEMORY_API_KEY"] = ""
    os.environ["API_BASE_URL"] = "http://127.0.0.1:9/mock-chat"
    os.environ["MEMORY_API_BASE_URL"] = "http://127.0.0.1:9/mock-memory"

    import importlib

    database = importlib.import_module("database")
    config = importlib.import_module("config")
    memory_extractor = importlib.import_module("memory_extractor")
    app_module = importlib.import_module("main")

    require(database.DATABASE_URL == test_dsn, "database module captured the wrong DATABASE_URL")
    require(app_module.app.title == "Kiwi-Mem", "FastAPI title is not Kiwi-Mem")

    # Dedicated DB makes the legacy information_schema migrations safe and lets
    # us prove the S6 ALTER is idempotent without touching any other database.
    await database.init_tables()
    await database.init_tables()

    transport = httpx.ASGITransport(app=app_module.app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://kiwi.test") as client:
        # ASGITransport does not enter app lifespan: no schedulers, MCP sessions,
        # embedding backfill, model calls or external HTTP are started.
        await test_s1(client)
        await test_s2()
        await test_s3()
        await test_s4(client)
        await test_s5(client)
        await test_s6(client)
        await test_w1_06()
        await test_w1_08()
        await test_w1_01()
        await test_w2_01(client)
        await test_w2_02(client)


async def async_main() -> int:
    admin_dsn = _validated_admin_dsn()
    database_name = ""
    try:
        database_name, test_dsn = await _create_disposable_database(admin_dsn)
        print(f"Created disposable PostgreSQL database: {database_name}")
        await run_suite(test_dsn)
        legacy_passed = [name for name in PASSED if name.startswith("T-S")]
        w1_01_passed = [name for name in PASSED if name.startswith("T-W1-01-")]
        w1_06_passed = [name for name in PASSED if name.startswith("T-W1-06-")]
        w1_08_passed = [name for name in PASSED if name.startswith("T-W1-08-")]
        w2_01_passed = [name for name in PASSED if name.startswith("T-W2-01-")]
        w2_02_passed = [name for name in PASSED if name.startswith("T-W2-02-")]
        print(f"\nPASS: {len(legacy_passed)} permanent S1-S6 behavior guards")
        print(f"PASS: {len(w1_01_passed)} W1-01 isolation/permanent guards")
        print(f"PASS: {len(w1_06_passed)} W1-06 calendar-delete atomicity guards")
        print(f"PASS: {len(w1_08_passed)} W1-08 calendar-period guards")
        print(f"PASS: {len(w2_01_passed)} W2-01 granular-sync guards")
        print(f"PASS: {len(w2_02_passed)} W2-02 message-identity/atomic-import guards")
        print(f"PASS: {len(PASSED)} total permanent behavior guards")
        print("Real database path: disposable PostgreSQL verified")
        print("Real model/API path: not called; embedding/model/HTTP boundaries were mocked")
        return 0
    finally:
        if database is not None:
            await database.close_pool()
        if database_name:
            await _drop_disposable_database(admin_dsn, database_name)
            print(f"Removed disposable PostgreSQL database: {database_name}")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(async_main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
