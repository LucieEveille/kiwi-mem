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
from contextlib import redirect_stderr, redirect_stdout
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
        "conversations",
        "memory_extraction_state",
        "session_tombstones",
        "turn_tombstones",
        "message_tombstones",
        "session_source_rev",
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
        require([d["code"] for d in body["error_details"]] == ["write_failed"],
                f"message-write failure code must be write_failed: {[d.get('code') for d in body['error_details']]}")
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
        require([d["code"] for d in body["error_details"]] == ["write_failed"],
                f"project failure code must be write_failed: {[d.get('code') for d in body['error_details']]}")
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
        require([d["code"] for d in body["error_details"]] == ["write_failed"],
                f"metadata failure code must be write_failed: {[d.get('code') for d in body['error_details']]}")
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
    dup_conv, dup_proj = f"{prefix}dup-c", f"{prefix}dup-p"
    fine_conv, fine_proj = f"{prefix}fine-c", f"{prefix}fine-p"
    response = await client.post("/sync/import", json={
        "conversations": [
            "not-a-dict",
            {"title": "missing id"},
            {"id": dup_conv, "title": "first", "messages": []},
            {"id": dup_conv, "title": "second", "messages": []},
            {"id": f"{prefix}badmsgs", "title": "bad messages", "messages": "nope"},
            {"id": f"{prefix}badmsgitem", "title": "bad message item", "messages": ["x"]},
            {"id": fine_conv, "title": "healthy", "messages": []},
        ],
        "projects": [
            "not-a-dict",
            {"name": "missing id"},
            {"id": dup_proj, "name": "p-first"},
            {"id": dup_proj, "name": "p-second"},
            {"id": fine_proj, "name": "healthy"},
        ],
    })
    require(response.status_code == 200, "per-entity rejects must not fail the whole batch")
    body = response.json()
    codes = [d["code"] for d in body["rejected_details"]]
    for expected in ("invalid_item", "missing_id", "duplicate_id", "invalid_messages", "invalid_message_item"):
        require(expected in codes, f"reject code {expected} missing from {codes}")
    # 重复实体 ID：每一份副本都必须自己进 rejected，先到者不得静默胜出
    conv_dups = [d for d in body["rejected_details"]
                 if d["type"] == "conversation" and d["code"] == "duplicate_id"]
    proj_dups = [d for d in body["rejected_details"]
                 if d["type"] == "project" and d["code"] == "duplicate_id"]
    require(len(conv_dups) == 2, f"both duplicate conversation copies must be rejected, got {len(conv_dups)}")
    require(len(proj_dups) == 2, f"both duplicate project copies must be rejected, got {len(proj_dups)}")
    require(body["counts"]["conversations"]["rejected"] == 6,
            f"conversation rejected count wrong: {body['counts']['conversations']}")
    require(body["counts"]["projects"]["rejected"] == 4,
            f"project rejected count wrong: {body['counts']['projects']}")
    require(body["counts"]["conversations"]["success"] == 1, "the one valid conversation did not import")
    require(body["counts"]["projects"]["success"] == 1, "the one valid project did not import")
    require(body["imported_conversation_ids"] == [fine_conv],
            f"conversation success IDs wrong: {body['imported_conversation_ids']}")
    require(body["imported_project_ids"] == [fine_proj],
            f"project success IDs wrong: {body['imported_project_ids']}")
    require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = $1)", dup_conv),
            "a duplicated conversation id reached the database")
    require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_projects WHERE id = $1)", dup_proj),
            "a duplicated project id reached the database")
    require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = '')"),
            "an id-less conversation was silently written with an empty id")
    require(body["counts"]["conversations"]["failed"] == 0 and body["counts"]["projects"]["failed"] == 0,
            "rejects must not be counted as failures")
    passed("T-W2-02-14 duplicate entity IDs reject every copy and never reach the database")

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

    # ---- per-column landing against an independent expectation table -------
    # Channel-vs-channel comparison (T-W2-02-6) cannot catch a shift that both
    # channels share, because they assemble through the same function.  These
    # expectations are written by hand here and never derived from production code.
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    col_conv, col_msg = f"{prefix}col-c", f"{prefix}col-m"
    await client.post("/sync/conversations", json={"id": col_conv, "title": "columns"})
    response = await client.put(f"/sync/conversations/{col_conv}/messages/{col_msg}", json={
        "role": "assistant", "content": "col-content", "time": "2026-03-04T05:06:07Z",
        "model": "col-model", "error": True, "thinking": "col-thinking",
        "summary": "col-summary", "versionIndex": 7, "sortOrder": 41,
        "tokenInfo": {"col": "token_info"}, "statusEvents": [{"col": "status_events"}],
        "toolEvents": [{"col": "tool_events"}], "memoryResult": {"col": "memory_result"},
        "memoryEvent": {"col": "memory_event"}, "handoffInfo": {"col": "handoff_info"},
        "webSearchResults": [{"col": "web_search_results"}], "versions": [{"col": "versions"}],
        "images": [{"col": "images"}], "attachments": [{"col": "attachments"}],
        "usage": {"col": "usage"}, "dreamEvent": {"col": "dream_event"}, "turnKey": "col-turn-key",
    })
    require(response.status_code == 200, f"per-column upsert failed: {response.status_code} {response.text}")
    row = await _pool_fetchrow(
        f"SELECT {', '.join(_MESSAGE_CONTENT_COLUMNS)}, sort_order FROM chat_messages WHERE id = $1",
        col_msg,
    )
    for col, want in {
        "role": "assistant", "content": "col-content", "model": "col-model",
        "streaming": False, "error": True, "thinking": "col-thinking",
        "version_index": 7, "summary": "col-summary", "turn_key": "col-turn-key",
        "sort_order": 41,
    }.items():
        require(row[col] == want, f"column {col} landed as {row[col]!r}, expected {want!r}")
    for col in ("token_info", "status_events", "tool_events", "memory_result", "memory_event",
                "handoff_info", "web_search_results", "versions", "images", "attachments",
                "usage", "dream_event"):
        want = [{"col": col}] if col in {
            "status_events", "tool_events", "web_search_results", "versions", "images", "attachments"
        } else {"col": col}
        require(json.loads(row[col]) == want, f"column {col} landed as {row[col]!r}, expected {want!r}")
    require((row["time"].year, row["time"].month, row["time"].day) == (2026, 3, 4),
            f"time column landed as {row['time']!r}")

    # Update the two new fields while omitting sortOrder: they must change, it must survive.
    response = await client.put(f"/sync/conversations/{col_conv}/messages/{col_msg}", json={
        "role": "assistant", "content": "col-content-2",
        "dreamEvent": {"col": "dream_event_2"}, "turnKey": "col-turn-key-2",
    })
    require(response.status_code == 200, "second per-column upsert failed")
    row = await _pool_fetchrow(
        "SELECT dream_event, turn_key, sort_order, content FROM chat_messages WHERE id = $1", col_msg
    )
    require(json.loads(row["dream_event"]) == {"col": "dream_event_2"}, "dream_event did not update")
    require(row["turn_key"] == "col-turn-key-2", "turn_key did not update")
    require(row["content"] == "col-content-2", "content did not update")
    require(row["sort_order"] == 41,
            f"sort_order must survive an update that omits sortOrder, got {row['sort_order']!r}")
    passed("T-W2-02-18 every content column lands on its own independently expected value")

    # ---- duplicate explicit message IDs are input errors, not write failures ----
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    dupmsg_conv, idless_conv = f"{prefix}dupmsg-c", f"{prefix}idless-c"
    response = await client.post("/sync/import", json={
        "conversations": [
            {"id": dupmsg_conv, "title": "dup messages", "messages": [
                {"id": f"{prefix}dm1", "role": "user", "content": "a"},
                {"id": f"{prefix}dm1", "role": "assistant", "content": "b"},
            ]},
            {"id": idless_conv, "title": "id-less messages", "messages": [
                {"role": "user", "content": "no explicit id"},
                {"role": "assistant", "content": "also no explicit id"},
            ]},
        ],
        "projects": [],
    })
    require(response.status_code == 200, "duplicate message id must not fail the whole batch")
    body = response.json()
    dup_msg_rejects = [d for d in body["rejected_details"] if d["code"] == "duplicate_message_id"]
    require(len(dup_msg_rejects) == 1 and dup_msg_rejects[0]["id"] == dupmsg_conv,
            f"duplicate_message_id reject missing: {body['rejected_details']}")
    require(body["counts"]["conversations"]["rejected"] == 1, "duplicate message id was not counted as rejected")
    require(body["counts"]["conversations"]["failed"] == 0,
            "an input-level duplicate message id must not be counted as a write failure")
    require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = $1)", dupmsg_conv),
            "rejected conversation metadata reached the database")
    require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_messages WHERE conversation_id = $1)", dupmsg_conv),
            "rejected conversation messages reached the database")
    # Messages without an explicit id keep synthesizing distinct ids and must still commit.
    require(await _pool_fetchval("SELECT COUNT(*) FROM chat_messages WHERE conversation_id = $1", idless_conv) == 2,
            "id-less messages must not be treated as duplicates")
    require(body["counts"]["conversations"]["success"] == 1, "healthy sibling conversation did not commit")
    passed("T-W2-02-19 duplicate explicit message IDs reject the conversation before any write")

    # ---- whole-request crash path leaks nothing --------------------------------
    crash_sentinel = f"W2_02_CRASH_{uuid.uuid4().hex}"

    async def _crashing_import(*args, **kwargs):
        raise RuntimeError(crash_sentinel)

    out_capture, err_capture = io.StringIO(), io.StringIO()
    with patch.object(app_module, "sync_import_all", _crashing_import):
        with redirect_stdout(out_capture), redirect_stderr(err_capture):
            response = await client.post("/sync/import", json={"conversations": [], "projects": []})
    require(response.status_code == 500, f"top-level crash must return 500, got {response.status_code}")
    require(crash_sentinel not in response.text, "top-level exception text leaked into the HTTP response")
    require(response.json() == {"error": "导入失败"},
            f"top-level 500 must use the fixed safe message, got {response.text}")
    require(crash_sentinel not in out_capture.getvalue(), "top-level exception text leaked into stdout")
    require(crash_sentinel not in err_capture.getvalue(), "top-level exception text leaked into stderr")
    passed("T-W2-02-20 whole-request crash returns a fixed safe message and leaks nothing")

    # ---- cleaned ids must equal the actual primary keys ------------------------
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    padded_proj, padded_conv = f"{prefix}pad-p", f"{prefix}pad-c"
    response = await client.post("/sync/import", json={
        "conversations": [{"id": f"  {padded_conv}  ", "title": "padded", "messages": []}],
        "projects": [{"id": f"  {padded_proj}  ", "name": "padded"}],
    })
    require(response.status_code == 200, "whitespace-padded ids failed to import")
    body = response.json()
    require(body["imported_project_ids"] == [padded_proj],
            f"project receipt must report the cleaned id: {body['imported_project_ids']}")
    require(body["imported_conversation_ids"] == [padded_conv],
            f"conversation receipt must report the cleaned id: {body['imported_conversation_ids']}")
    for table, cleaned in (("chat_projects", padded_proj), ("chat_conversations", padded_conv)):
        require(await _pool_fetchval(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE id = $1)", cleaned),
                f"{table}: the cleaned id is not the actual primary key")
        require(not await _pool_fetchval(f"SELECT EXISTS(SELECT 1 FROM {table} WHERE id = $1)", f"  {cleaned}  "),
                f"{table}: the raw padded id reached the database as a separate primary key")
    passed("T-W2-02-21 receipt ids and database primary keys agree after whitespace cleanup")

    # ---- observability events carry codes, never entity IDs -------------------
    # Scope: ordinary logs only.  The HTTP receipt deliberately keeps entity IDs so
    # callers can reconcile (see T-W2-02-12), so nothing here asserts on the response.
    # T-W2-02-16 guards database exception text and T-W2-02-20 guards whole-request
    # crash text; this guard is about the IDs themselves and does not replace either.
    await _truncate("chat_messages", "chat_conversations", "chat_projects")
    reject_id = f"W2_02_REJECT_ID_{uuid.uuid4().hex}"
    failure_id = f"W2_02_FAILURE_ID_{uuid.uuid4().hex}"
    # The injected exception text is a fixed safe sentinel: never put the entity ID
    # into the database error itself, or a leak could not be attributed to logging.
    trigger_text = "W2_02_OBSERVABILITY_TRIGGER_FAILURE"

    reject_out, reject_err = io.StringIO(), io.StringIO()
    with redirect_stdout(reject_out), redirect_stderr(reject_err):
        response = await client.post("/sync/import", json={
            "conversations": [{"id": reject_id, "title": "rejected", "messages": "not-an-array"}],
            "projects": [],
        })
    require(response.status_code == 200, "reject-path import must stay 200")
    reject_logs = reject_out.getvalue() + reject_err.getvalue()

    await _install_fail_trigger("chat_messages", "w202_obs", "conversation_id", failure_id, trigger_text)
    try:
        failure_out, failure_err = io.StringIO(), io.StringIO()
        with redirect_stdout(failure_out), redirect_stderr(failure_err):
            response = await client.post("/sync/import", json={
                "conversations": [{"id": failure_id, "title": "doomed", "messages": [
                    {"id": f"{prefix}obs-m", "role": "user", "content": "x"},
                ]}],
                "projects": [],
            })
        require(response.status_code == 200, "failure-path import must stay 200")
        failure_logs = failure_out.getvalue() + failure_err.getvalue()
    finally:
        await _drop_fail_trigger("chat_messages", "w202_obs")

    require(reject_id not in reject_logs, "reject observability leaked the entity ID into ordinary logs")
    require(failure_id not in failure_logs, "failure observability leaked the entity ID into ordinary logs")
    reject_events = [line.strip() for line in reject_logs.splitlines()
                     if line.startswith("event=sync_import_reject ")]
    failure_events = [line.strip() for line in failure_logs.splitlines()
                      if line.startswith("event=sync_import_failure ")]
    require(reject_events, f"no sync_import_reject event was emitted: {reject_logs!r}")
    require(failure_events, f"no sync_import_failure event was emitted: {failure_logs!r}")
    for event in reject_events + failure_events:
        for field in ("entity=", "code=", "increment="):
            require(field in event, f"observability event lost the controlled field {field}: {event!r}")
    # The rejected entity must also stay out of the database entirely.
    require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = $1)", reject_id),
            "rejected conversation reached the database")
    require(not await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = $1)", failure_id),
            "failed conversation left a half state")
    passed("T-W2-02-22 reject and failure observability keep codes and drop entity IDs")


# ---------------------------------------------------------------------------
# W2-03 | M1 ledger schema, authoritative scope, and dark writes
# ---------------------------------------------------------------------------

_LEDGER_NEW_COLUMNS = {
    "project_id": "text",
    "scope_known": "boolean",
    "usage": "jsonb",
    "turn_id": "bigint",
    "turn_key": "text",
}


async def _ledger_rows(session_id: str) -> list:
    return await _pool_fetch(
        "SELECT id, role, content, model, project_id, scope_known, usage, turn_id, turn_key "
        "FROM conversations WHERE session_id = $1 ORDER BY id",
        session_id,
    )


async def _await_ledger(session_id: str, expected: int, timeout: float = 5.0) -> list:
    """等后台落账 task 跑完。

    暗写被 _spawn_background_task 提成独立任务（断连也要跑完），HTTP 响应返回时
    它通常还没落库，所以这里轮询而不是直接断言。
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    rows = await _ledger_rows(session_id)
    while len(rows) < expected and loop.time() < deadline:
        await asyncio.sleep(0.05)
        rows = await _ledger_rows(session_id)
    return rows


async def _settle_background(seconds: float = 0.4) -> None:
    """给后台任务一个真实的落库窗口，再断言「什么都没写」。"""
    await asyncio.sleep(seconds)


async def _set_ledger_gate(enabled: bool) -> None:
    await _upsert_config("memory_event_ledger_write_enabled", "true" if enabled else "false")


async def _set_identity_gate(enabled: bool) -> None:
    await _upsert_config("session_identity_v2_enabled", "true" if enabled else "false")


async def test_w2_03_schema_and_atomic() -> None:
    """T-W2-03-1..10: schema, migration, atomic turn writes, regenerate."""
    # ---- 1. five columns + extraction state table --------------------------
    rows = {
        r["column_name"]: r
        for r in await _pool_fetch(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = 'conversations'"
        )
    }
    missing = sorted(set(_LEDGER_NEW_COLUMNS) - set(rows))
    require(not missing, f"W2-03 conversations columns missing: {missing}")
    for col, want_type in _LEDGER_NEW_COLUMNS.items():
        require(rows[col]["data_type"] == want_type,
                f"{col} must be {want_type}, got {rows[col]['data_type']}")
    require(rows["scope_known"]["is_nullable"] == "NO", "scope_known must be NOT NULL")
    require("false" in (rows["scope_known"]["column_default"] or "").lower(),
            f"scope_known must default FALSE, got {rows['scope_known']['column_default']!r}")
    for col in ("project_id", "usage", "turn_id", "turn_key"):
        require(rows[col]["is_nullable"] == "YES", f"{col} must be nullable")
        require(rows[col]["column_default"] is None, f"{col} must have no default")
    state_cols = {
        r["column_name"]
        for r in await _pool_fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'memory_extraction_state'"
        )
    }
    require({"session_id", "last_extracted_message_id", "claimed_until", "updated_at", "claim_token"}
            <= state_cols, f"memory_extraction_state columns missing: {sorted(state_cols)}")
    passed("T-W2-03-1 ledger gains five columns and memory_extraction_state exists")

    # ---- 2/3. idempotent migration, untouched legacy rows -------------------
    await _truncate("conversations")
    legacy_id = await _pool_fetchval(
        "INSERT INTO conversations (session_id, role, content, model) "
        "VALUES ('w203-legacy', 'user', 'legacy-body', 'm') RETURNING id"
    )
    await database.init_tables()
    await database.init_tables()
    recheck = await _pool_fetchval(
        "SELECT COUNT(*) FROM information_schema.columns WHERE table_name = 'conversations' "
        "AND column_name = ANY($1::text[])",
        list(_LEDGER_NEW_COLUMNS),
    )
    require(recheck == 5, "repeat init_tables() disturbed the W2-03 columns")
    passed("T-W2-03-2 repeat init_tables() is idempotent for the ledger columns")

    legacy = await _pool_fetchrow(
        "SELECT content, project_id, scope_known, usage, turn_id, turn_key "
        "FROM conversations WHERE id = $1", legacy_id
    )
    require(legacy["content"] == "legacy-body", "migration damaged an existing ledger row")
    require(legacy["scope_known"] is False, "legacy rows must stay scope_known = FALSE")
    for col in ("project_id", "usage", "turn_id", "turn_key"):
        require(legacy[col] is None, f"legacy row must keep {col} NULL, got {legacy[col]!r}")
    passed("T-W2-03-3 legacy ledger rows stay blank and unclaimed")

    # ---- 4. atomic normal turn ---------------------------------------------
    await _truncate("conversations", "chat_conversations", "chat_projects")
    sid = "w203-atomic"
    result = await database.append_turn_events_atomic(
        sid, "u-body", "a-body", "m-1",
        usage={"prompt_tokens": 10, "completion_tokens": 4,
               "prompt_tokens_details": {"cached_tokens": 3}},
        turn_key="tk-1",
    )
    require(result.get("ok") is True, f"atomic append failed: {result!r}")
    rows = await _ledger_rows(sid)
    require(len(rows) == 2, f"atomic turn must write exactly two rows, got {len(rows)}")
    user_row, asst_row = rows
    require((user_row["role"], asst_row["role"]) == ("user", "assistant"),
            f"row order wrong: {[r['role'] for r in rows]}")
    require(user_row["turn_id"] == user_row["id"],
            f"user turn_id must anchor to its own id: {user_row['turn_id']} != {user_row['id']}")
    require(asst_row["turn_id"] == user_row["id"],
            "assistant must share the user's turn_id")
    require(user_row["turn_key"] == "tk-1" and asst_row["turn_key"] == "tk-1",
            "both rows must carry the same turn_key")
    require(user_row["usage"] is None, "usage belongs on the assistant row only")
    require(json.loads(asst_row["usage"]) == {"prompt": 10, "completion": 4, "cached": 3},
            f"usage was not normalized: {asst_row['usage']!r}")
    passed("T-W2-03-4 an atomic turn writes both rows with shared identity and normalized usage")

    # ---- 5. transaction rollback + safe failure event -----------------------
    await _truncate("conversations")
    fail_sid = "w203-rollback"
    await _pool_execute(
        """
        CREATE OR REPLACE FUNCTION w203_fail_assistant() RETURNS trigger AS $fn$
        BEGIN
            IF NEW.role = 'assistant' AND NEW.session_id = 'w203-rollback'
            THEN RAISE EXCEPTION 'W2_03_INJECTED_LEDGER_FAILURE'; END IF;
            RETURN NEW;
        END; $fn$ LANGUAGE plpgsql
        """
    )
    await _pool_execute("DROP TRIGGER IF EXISTS w203_fail_assistant_trg ON conversations")
    await _pool_execute(
        "CREATE TRIGGER w203_fail_assistant_trg BEFORE INSERT ON conversations "
        "FOR EACH ROW EXECUTE FUNCTION w203_fail_assistant()"
    )
    try:
        capture = io.StringIO()
        with redirect_stdout(capture):
            result = await database.append_turn_events_atomic(fail_sid, "u", "a", "m")
        require(result.get("ok") is False, "a failed atomic append must report ok=False")
        require(not await _ledger_rows(fail_sid),
                "half-written turn survived: the user row was not rolled back")
        events = [ln.strip() for ln in capture.getvalue().splitlines()
                  if ln.startswith("event=ledger_write_failed ")]
        require(events, f"no ledger_write_failed event: {capture.getvalue()!r}")
        require(all("code=write_failed" in e for e in events),
                f"ledger_write_failed must use the stable code: {events}")
        require(all("exception_type=" in e for e in events),
                f"ledger_write_failed must name the exception type: {events}")
        require(all("W2_03_INJECTED_LEDGER_FAILURE" not in e for e in events),
                "ledger_write_failed leaked the exception body")
        require(all(fail_sid not in e for e in events),
                "ledger_write_failed leaked the session id")
        passed("T-W2-03-5 a failed turn rolls back entirely and emits a safe coded event")
    finally:
        await _pool_execute("DROP TRIGGER IF EXISTS w203_fail_assistant_trg ON conversations")
        await _pool_execute("DROP FUNCTION IF EXISTS w203_fail_assistant()")

    # ---- 6/7. gate exclusivity ---------------------------------------------
    await _truncate("conversations")
    gate_key = "memory_event_ledger_write_enabled"
    gate_had_row = await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM gateway_config WHERE key = $1)", gate_key)
    gate_previous = await _config_row(gate_key)
    try:
        require(config.CONFIG_SCHEMA.get(gate_key, (None, None))[1] == "true",
                "memory_event_ledger_write_enabled must exist and default to true")
        await _set_ledger_gate(True)
        open_sid = "w203-gate-open"
        await database.append_turn_events_atomic(open_sid, "u", "a", "m", turn_key="tk")
        rows = await _ledger_rows(open_sid)
        require(len(rows) == 2, f"gate-open path must write exactly 2 rows, got {len(rows)} (double write?)")
        passed("T-W2-03-6 the open gate writes one atomic pair, never a doubled turn")

        source = (ROOT / "database.py").read_text(encoding="utf-8")
        legacy_sql = re.search(r"async def save_message\(.*?\n\n", source, re.S)
        require(legacy_sql, "save_message not found for the static legacy-SQL guard")
        body = legacy_sql.group(0)
        for forbidden in ("project_id", "scope_known", "usage", "turn_id", "turn_key"):
            require(forbidden not in body,
                    f"save_message must stay byte-compatible; it now mentions {forbidden}")
        passed("T-W2-03-7 the closed-gate path keeps save_message free of the new columns")
    finally:
        if gate_had_row:
            await _upsert_config(gate_key, gate_previous)
        else:
            await _pool_execute("DELETE FROM gateway_config WHERE key = $1", gate_key)

    # ---- 8/9/10. regenerate ------------------------------------------------
    await _truncate("conversations")
    regen_sid = "w203-regen"
    await database.append_turn_events_atomic(regen_sid, "u1", "a1", "m", turn_key="k1")
    before = await _ledger_rows(regen_sid)
    target_turn = before[0]["id"]
    result = await database.append_turn_events_atomic(
        regen_sid, "u1", "a1-regenerated", "m", turn_key=None, is_regenerate=True
    )
    require(result.get("ok") is True, f"regenerate failed: {result!r}")
    rows = await _ledger_rows(regen_sid)
    require(len(rows) == 2, f"regenerate must replace, not append: {len(rows)} rows")
    require(rows[0]["id"] == before[0]["id"], "regenerate must not touch the user row")
    require(rows[1]["content"] == "a1-regenerated", "regenerate did not replace the assistant body")
    require(rows[1]["turn_id"] == target_turn, "regenerated assistant lost its turn anchor")
    # A keyless regenerate must not blank the turn's key: the user row still says k1,
    # so an assistant carrying NULL would split the turn's identity in half.
    require(rows[1]["turn_key"] == "k1",
            f"replacement assistant must inherit the user's turn_key, got {rows[1]['turn_key']!r}")

    # The turn's scope is decided once, when the turn is written.  If the conversation
    # is later moved into a project (or its metadata only syncs afterwards), a regenerate
    # must still inherit the original attribution — otherwise one turn ends up "question
    # global, answer in project", and W2-06's scope-based consumers tear it apart.
    await _truncate("conversations", "chat_conversations", "chat_projects")
    moved_sid = "w203-moved"
    await _pool_execute("INSERT INTO chat_projects (id, name) VALUES ('w203-moved-p', 'moved')")
    await _pool_execute(
        "INSERT INTO chat_conversations (id, title, project_id) VALUES ($1, 'c', NULL)", moved_sid
    )
    await database.append_turn_events_atomic(
        moved_sid, "u", "a", "m", client_gave_conv_id=True, turn_key="mk"
    )
    original = await _ledger_rows(moved_sid)
    await _pool_execute(
        "UPDATE chat_conversations SET project_id = 'w203-moved-p' WHERE id = $1", moved_sid
    )
    await database.append_turn_events_atomic(
        moved_sid, "u", "a-after-move", "m", client_gave_conv_id=True, is_regenerate=True
    )
    after = await _ledger_rows(moved_sid)
    require(len(after) == 2, f"regenerate after a move must still leave one turn: {len(after)} rows")
    require((after[0]["scope_known"], after[0]["project_id"])
            == (after[1]["scope_known"], after[1]["project_id"]),
            f"regenerate split the turn's scope: user={(after[0]['scope_known'], after[0]['project_id'])} "
            f"assistant={(after[1]['scope_known'], after[1]['project_id'])}")
    require((after[1]["scope_known"], after[1]["project_id"])
            == (original[0]["scope_known"], original[0]["project_id"]),
            "replacement assistant re-judged scope instead of inheriting the original turn's")
    require(after[1]["turn_key"] == "mk", "replacement assistant lost the original turn_key")
    passed("T-W2-03-8 keyless regenerate replaces within the turn and inherits its whole identity")

    # historical key -> abandon, unknown key -> abandon; the old assistant survives both
    await _truncate("conversations")
    await database.append_turn_events_atomic(regen_sid, "u1", "a1", "m", turn_key="k1")
    await database.append_turn_events_atomic(regen_sid, "u2", "a2", "m", turn_key="k2")
    for bad_key, label in (("k1", "historical"), ("k-nope", "unknown")):
        capture = io.StringIO()
        with redirect_stdout(capture):
            result = await database.append_turn_events_atomic(
                regen_sid, "u2", "should-not-land", "m", turn_key=bad_key, is_regenerate=True
            )
        require(result.get("ok") is False,
                f"{label} turn_key regenerate must be abandoned, got {result!r}")
        rows = await _ledger_rows(regen_sid)
        require(len(rows) == 4, f"{label} key regenerate changed the ledger: {len(rows)} rows")
        require(rows[-1]["content"] == "a2",
                f"{label} key regenerate destroyed the newest assistant")
        require(any(ln.startswith("event=regen_target_invalid ") for ln in capture.getvalue().splitlines()),
                f"{label} key abandon did not emit regen_target_invalid: {capture.getvalue()!r}")
    passed("T-W2-03-9 regenerate abandons on historical or unknown turn_key and keeps the old reply")

    # Mixed era (gate on -> off -> on): the dangerous shape is a gate-off row written
    # AFTER a proper turn.  Ordering by time alone would then pick the NULL row, so the
    # legacy row must be the *newest* one here — a legacy row placed before the turn
    # would be selected correctly even by a broken OR-merged candidate set.
    await _truncate("conversations")
    mix_sid = "w203-mixed"
    await database.append_turn_events_atomic(mix_sid, "new-u", "new-a", "m", turn_key="mk")
    await _pool_execute(
        "INSERT INTO conversations (session_id, role, content, model, created_at) "
        "VALUES ($1, 'assistant', 'gate-off-a', 'm', NOW() + INTERVAL '1 minute')", mix_sid
    )
    await database.append_turn_events_atomic(
        mix_sid, "new-u", "new-a-regen", "m", is_regenerate=True
    )
    rows = await _ledger_rows(mix_sid)
    require("gate-off-a" in [r["content"] for r in rows],
            "mixed-era regenerate deleted the gate-off row: the candidate branches were OR-merged")
    require([r["content"] for r in rows if r["turn_id"] is not None] == ["new-u", "new-a-regen"],
            f"mixed-era regenerate did not replace within its own turn: {[r['content'] for r in rows]}")
    require("new-a" not in [r["content"] for r in rows],
            "mixed-era regenerate left the superseded reply of its own turn behind")
    passed("T-W2-03-10 mixed-era regenerate stays inside its own turn branch")


async def test_w2_03_scope_and_order() -> None:
    """T-W2-03-12, 16(pure), 17, 18, 19: scope authority, usage shape, observability, read order."""
    # ---- 12. authority table, row by row -----------------------------------
    await _truncate("conversations", "chat_conversations", "chat_projects")
    await _pool_execute("INSERT INTO chat_projects (id, name) VALUES ('w203-p-live', 'live')")
    await _pool_execute(
        "INSERT INTO chat_conversations (id, title, project_id) VALUES "
        "('w203-c-live','c','w203-p-live'), ('w203-c-dead','c','w203-p-gone'), ('w203-c-null','c',NULL)"
    )

    async def scope_of(sid, **kwargs):
        capture = io.StringIO()
        with redirect_stdout(capture):
            await database.append_turn_events_atomic(sid, "u", "a", "m", **kwargs)
        row = (await _ledger_rows(sid))[0]
        codes = {ln.split()[0].split("=", 1)[1]
                 for ln in capture.getvalue().splitlines() if ln.startswith("event=scope_")}
        return row["scope_known"], row["project_id"], codes

    # row 1: metadata wins even when payload disagrees
    known, pid, codes = await scope_of("w203-c-live", client_gave_conv_id=True,
                                       project_id_present=True, payload_project_id="w203-p-other")
    require((known, pid) == (True, "w203-p-live"),
            f"row 1: metadata must win, got {(known, pid)}")
    require("scope_mismatch" in codes, f"row 1 must emit scope_mismatch, got {codes}")
    # row 2: project deleted -> keep the historical attribution, never global
    known, pid, codes = await scope_of("w203-c-dead", client_gave_conv_id=True)
    require((known, pid) == (True, "w203-p-gone"),
            f"row 2: deleted project keeps TRUE + original id, got {(known, pid)}")
    require("scope_project_missing" in codes, f"row 2 must emit scope_project_missing, got {codes}")
    # row 3: metadata says global
    known, pid, _ = await scope_of("w203-c-null", client_gave_conv_id=True)
    require((known, pid) == (True, None), f"row 3: metadata NULL means global, got {(known, pid)}")
    # row 4/5: only a server-generated session may trust the payload
    known, pid, _ = await scope_of("w203-gen-null", client_gave_conv_id=False,
                                   project_id_present=True, payload_project_id=None)
    require((known, pid) == (True, None), f"row 4: explicit null is trusted, got {(known, pid)}")
    known, pid, codes = await scope_of("w203-gen-proj", client_gave_conv_id=False,
                                       project_id_present=True, payload_project_id="w203-p-live")
    require((known, pid) == (True, "w203-p-live"), f"row 5: payload trusted, got {(known, pid)}")
    require("scope_payload_trusted" in codes, f"row 5 must emit scope_payload_trusted, got {codes}")
    # row 6: client supplied a conversation_id but metadata is missing -> never trust payload
    known, pid, codes = await scope_of("w203-c-missing", client_gave_conv_id=True,
                                       project_id_present=True, payload_project_id="w203-p-live")
    require((known, pid) == (False, None),
            f"row 6: unverified session must stay FALSE+NULL regardless of payload, got {(known, pid)}")
    require("scope_unverified" in codes, f"row 6 must emit scope_unverified, got {codes}")
    # row 7: absent key on a generated session stays unknown
    known, pid, _ = await scope_of("w203-gen-absent", client_gave_conv_id=False)
    require((known, pid) == (False, None), f"row 7: absent key stays unknown, got {(known, pid)}")
    known, pid, codes = await scope_of("w203-gen-blank", client_gave_conv_id=False,
                                       project_id_present=True, payload_project_id="")
    require((known, pid) == (False, None), f"row 7: blank payload stays unknown, got {(known, pid)}")
    require("scope_unverified" in codes, f"row 7 blank must emit scope_unverified, got {codes}")
    passed("T-W2-03-12 the scope authority table holds row by row against a real database")

    # ---- 16 (pure half). usage normalization shapes ------------------------
    normalize = app_module._normalize_usage_for_storage
    # OpenAI: prompt_tokens already includes the cached part — adding it again double counts.
    require(normalize({"prompt_tokens": 7, "completion_tokens": 2,
                       "prompt_tokens_details": {"cached_tokens": 5}})
            == {"prompt": 7, "completion": 2, "cached": 5},
            "OpenAI prompt_tokens already counts cached tokens; it must not be added twice")
    # Anthropic: input_tokens EXCLUDES cache creation and cache read, so the real total
    # input is input + creation + read (Anthropic's own billing definition).  Three
    # distinct values so a dropped term cannot coincidentally produce the right sum.
    require(normalize({"input_tokens": 9, "output_tokens": 3,
                       "cache_creation_input_tokens": 40, "cache_read_input_tokens": 100})
            == {"prompt": 149, "completion": 3, "cached": 100},
            "Anthropic prompt must add cache creation and cache read to input_tokens")
    require(normalize({"input_tokens": 9, "output_tokens": 3, "cache_read_input_tokens": 1})
            == {"prompt": 10, "completion": 3, "cached": 1},
            "Anthropic read-only cache still belongs in the prompt total")
    require(normalize({"input_tokens": 9, "output_tokens": 3})
            == {"prompt": 9, "completion": 3, "cached": 0},
            "Anthropic without cache must stay unchanged")
    require(normalize({"prompt": 149, "completion": 3, "cached": 100})
            == {"prompt": 149, "completion": 3, "cached": 100},
            "already-normalized usage must pass through unchanged (streams re-normalize on write)")
    # Multi-round aggregation adds field by field.
    acc = app_module._accumulate_usage(None, normalize(
        {"input_tokens": 9, "output_tokens": 3, "cache_creation_input_tokens": 40,
         "cache_read_input_tokens": 100}))
    acc = app_module._accumulate_usage(acc, normalize(
        {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 7}))
    require(acc == {"prompt": 157, "completion": 5, "cached": 107},
            f"multi-round usage aggregation is wrong: {acc}")
    for empty in (None, "", [], {}, 0):
        require(normalize(empty) is None, f"non-dict usage must normalize to None: {empty!r}")
    # Counted once, together with the streaming half, as T-W2-03-16.

    # ---- 17. observability sentinels ---------------------------------------
    await _truncate("conversations", "chat_conversations", "chat_projects")
    obs_sid = f"W2_03_OBS_SID_{uuid.uuid4().hex}"
    obs_pid = f"W2_03_OBS_PID_{uuid.uuid4().hex}"
    await _pool_execute("INSERT INTO chat_projects (id, name) VALUES ($1, 'obs')", obs_pid)
    await _pool_execute(
        "INSERT INTO chat_conversations (id, title, project_id) VALUES ($1, 'obs', $2)", obs_sid, obs_pid
    )
    out_cap, err_cap = io.StringIO(), io.StringIO()
    with redirect_stdout(out_cap), redirect_stderr(err_cap):
        await database.append_turn_events_atomic(
            obs_sid, "u", "a", "m", client_gave_conv_id=True,
            project_id_present=True, payload_project_id="w203-p-other",
        )
    logs = out_cap.getvalue() + err_cap.getvalue()
    require(obs_sid not in logs, "observability leaked the session id")
    require(obs_pid not in logs, "observability leaked the project id")
    events = [ln.strip() for ln in logs.splitlines() if ln.startswith("event=scope_mismatch ")]
    require(events, f"scope_mismatch event missing: {logs!r}")
    require(all("increment=" in e for e in events), f"scope event lost increment: {events}")
    passed("T-W2-03-17 scope observability keeps counters and drops session/project IDs")

    # ---- 18. turn_key must never be joined across tables --------------------
    db_source = (ROOT / "database.py").read_text(encoding="utf-8")
    # Scan code only: the prohibition itself is spelled out in comments, and a
    # comment saying "never JOIN on turn_key" must not read as a JOIN on turn_key.
    code_only = "\n".join(ln for ln in db_source.splitlines() if not ln.strip().startswith("#"))
    joined = re.findall(r"JOIN[^;]{0,200}turn_key|turn_key[^;]{0,200}JOIN", code_only, re.I)
    require(not joined, f"turn_key appears in a JOIN: {joined[:1]}")
    require(db_source.count("同名不同义") >= 2,
            "both turn_key columns must carry the same-name-different-meaning warning")
    passed("T-W2-03-18 the two turn_key columns stay unjoined and both warn in place")

    # ---- 19. deterministic read order on tied timestamps --------------------
    await _truncate("conversations")
    tie_sid = "w203-tie"
    # Identical timestamps on purpose: PG's NOW() is constant inside one transaction,
    # so an atomic turn writes both rows with the exact same created_at.
    tied = StdDateTime(2026, 5, 5, 5, 5, 5, tzinfo=timezone.utc)
    await _pool_execute(
        "INSERT INTO conversations (session_id, role, content, model, created_at) VALUES "
        "($1,'user','u-first','m',$2), "
        "($1,'assistant','a-second','m',$2), "
        "($1,'assistant','a-third','m',$2)",
        tie_sid, tied,
    )
    recent = await database.get_recent_messages(tie_sid, limit=10)
    require([r["content"] for r in recent] == ["u-first", "a-second", "a-third"],
            f"get_recent_messages is unstable on tied timestamps: {[r['content'] for r in recent]}")
    # A behavioural check alone is not enough here: on a small table PG's sequential
    # scan happens to return insertion (= id) order, so a missing tiebreak can pass by
    # luck.  Pin the tiebreak in the SQL of every ledger reader as well.
    reader_source = (ROOT / "database.py").read_text(encoding="utf-8")
    for reader in ("get_recent_messages", "get_recent_conversation",
                   "delete_latest_assistant_message"):
        body = re.search(rf"async def {reader}\(.*?(?=\nasync def )", reader_source, re.S)
        require(body, f"{reader} not found for the read-order guard")
        require("ORDER BY created_at DESC, id DESC" in body.group(0),
                f"{reader} orders by time without an id tiebreak; tied rows sort arbitrarily")
    await database.delete_latest_assistant_message(tie_sid)
    left = [r["content"] for r in await _ledger_rows(tie_sid)]
    require(left == ["u-first", "a-second"],
            f"delete_latest_assistant_message removed the wrong tied row: {left}")
    passed("T-W2-03-19 ledger readers break timestamp ties by id, deterministically")


async def test_w2_03_entry_and_panel(client: httpx.AsyncClient) -> None:
    """T-W2-03-11, 23, 24, 25: request-entry validation, project turns, panel wiring, CORS."""
    # ---- 11. turn_key entry validation -------------------------------------
    # Rejections happen while parsing the body, before any upstream call, so no
    # model boundary is exercised here.
    for bad, label in ((["x"], "list"), ({"a": 1}, "dict"), (7, "int"),
                       ("", "empty"), ("   ", "blank"), ("k" * 201, "201 chars")):
        response = await client.post("/v1/chat/completions", json={
            "model": "mock-model", "stream": False, "turn_key": bad,
            "messages": [{"role": "user", "content": "hi"}],
        })
        require(response.status_code == 400,
                f"explicit invalid turn_key ({label}) must be 400, got {response.status_code}")
    passed("T-W2-03-11 explicitly invalid turn_key is rejected at the request entry")

    # ---- 23. project turns keep their scope and still skip extraction -------
    # This must go through process_memories_background with memory ON and a trigger
    # word present, so the turn would genuinely reach extraction if the project skip
    # were removed.  Calling append_turn_events_atomic directly would never enter the
    # extraction path at all, and the guard would stay green with the skip deleted.
    await _truncate("conversations", "chat_conversations", "chat_projects", "memories")
    await _pool_execute("INSERT INTO chat_projects (id, name) VALUES ('w203-proj', 'p')")
    await _pool_execute(
        "INSERT INTO chat_conversations (id, title, project_id) VALUES ('w203-proj-c','c','w203-proj')"
    )
    mem_key = "memory_enabled"
    mem_had = await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM gateway_config WHERE key = $1)", mem_key)
    mem_prev = await _config_row(mem_key)
    try:
        await _upsert_config(mem_key, "true")
        trigger_word = next(w for w in app_module.MEMORY_TRIGGER_WORDS if w)
        result = await app_module.process_memories_background(
            "w203-proj-c", f"{trigger_word}我最喜欢奇异果", "好，我记住了", "m",
            project_id="w203-proj", extract_enabled=True,
            client_gave_conv_id=True, turn_key="pk",
        )
        require(isinstance(result, dict) and result.get("action") == "skip_project",
                f"a project turn must short-circuit before extraction, got {result!r}")
        rows = await _ledger_rows("w203-proj-c")
        require(len(rows) == 2, f"project turn must still land two ledger rows, got {len(rows)}")
        require(all(r["scope_known"] is True and r["project_id"] == "w203-proj" for r in rows),
                f"project turn lost its scope: {[(r['scope_known'], r['project_id']) for r in rows]}")
        require(await _pool_fetchval("SELECT COUNT(*) FROM memories") == 0,
                "a project turn leaked fragments into the global memory pool")
        require(not await _pool_fetchval(
            "SELECT EXISTS(SELECT 1 FROM conversations WHERE session_id = 'w203-proj-c' "
            "AND scope_known = TRUE AND project_id IS NULL)"),
            "a project turn must never satisfy the global scope condition")
    finally:
        if mem_had:
            await _upsert_config(mem_key, mem_prev)
        else:
            await _pool_execute("DELETE FROM gateway_config WHERE key = $1", mem_key)
    passed("T-W2-03-23 project turns record their scope and never reach global extraction")

    # ---- 24. both gates are registered on both sides and settable ----------
    schema_js = (ROOT / "admin-panel" / "js" / "config-schema.js").read_text(encoding="utf-8")
    for key in ("memory_event_ledger_write_enabled", "session_identity_v2_enabled"):
        require(key in config.CONFIG_SCHEMA, f"{key} is missing from the backend registry")
        require(re.search(rf"\b{key}\s*:", schema_js),
                f"{key} is missing from config-schema.js CONFIG_META (the panel would not show it)")
        # Split at the *first* CONFIG_PAGES (its definition); the name also appears
        # later where the table is consumed, and splitting on that would drop the groups.
        require(re.search(rf"['\"]{key}['\"]", schema_js.split("CONFIG_PAGES", 1)[-1]),
                f"{key} is registered but never placed in a CONFIG_PAGES group")
    gate_key = "memory_event_ledger_write_enabled"
    had_row = await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM gateway_config WHERE key = $1)", gate_key)
    previous = await _config_row(gate_key)
    try:
        response = await client.put(f"/admin/config/{gate_key}", json={"value": "false"})
        require(response.status_code == 200, f"PUT /admin/config failed: {response.status_code}")
        require(await config.get_config_bool(gate_key, True) is False,
                "PUT /admin/config did not actually change the gate")
        response = await client.put(f"/admin/config/{gate_key}", json={"value": "true"})
        require(await config.get_config_bool(gate_key, False) is True, "gate could not be turned back on")
    finally:
        if had_row:
            await _upsert_config(gate_key, previous)
        else:
            await _pool_execute("DELETE FROM gateway_config WHERE key = $1", gate_key)
    passed("T-W2-03-24 both gates are dual-registered and settable through the admin endpoint")

    # ---- 25. CORS actually exposes the session header ----------------------
    # Use an origin the deployment actually allows: CORS headers are only emitted
    # for allowed origins, so a foreign origin would fail this guard for the wrong reason.
    allowed_origin = (os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")[0]).strip()
    response = await client.get("/", headers={"Origin": allowed_origin})
    exposed = response.headers.get("access-control-expose-headers", "")
    require("X-Kiwi-Session-Id" in exposed,
            f"CORS does not expose X-Kiwi-Session-Id (browsers could not read it): {exposed!r}")
    passed("T-W2-03-25 a real cross-origin response exposes X-Kiwi-Session-Id")


def _fake_upstream(*, sse_events=None, json_body=None, status_code=200):
    """Fake httpx.AsyncClient serving one canned upstream reply (streaming or not).

    Only the surface main.py actually uses is implemented: async context manager,
    .post() for the buffered path and .stream() for the streaming path.
    """
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self.headers = {"content-type": "text/event-stream"}

        def json(self):
            return json_body or {"choices": [{"message": {"content": "a-body"}}], "model": "mock-model"}

        @property
        def text(self):
            return json.dumps(self.json(), ensure_ascii=False)

        async def aiter_bytes(self, chunk_size=None):
            for event in (sse_events or []):
                yield event if isinstance(event, bytes) else event.encode("utf-8")

        async def aread(self):
            return b""

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, *args):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, *args, **kwargs):
            return _StreamCtx()

        async def post(self, *args, **kwargs):
            return _Resp()

    return _Client


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


_DELTA = _sse({"choices": [{"delta": {"content": "hello"}, "finish_reason": None}], "model": "mock-model"})
_USAGE_TAIL = _sse({"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 5,
                                             "prompt_tokens_details": {"cached_tokens": 2}}})


async def _chat(client, body, *, sse_events=None, json_body=None, status_code=200):
    """POST /v1/chat/completions against a canned upstream; returns the response."""
    async def fake_provider(_model, provider_model_id=None):
        return {
            "model_id": "mock-model",
            "api_key": "mock-key",
            "api_format": "openai",
            "api_base_url": "http://127.0.0.1:9/mock-chat",
            "provider_name": "mock-provider",
        }

    with (
        patch.object(app_module.httpx, "AsyncClient",
                     _fake_upstream(sse_events=sse_events, json_body=json_body, status_code=status_code)),
        patch.object(app_module, "resolve_provider_for_model", fake_provider),
    ):
        return await client.post("/v1/chat/completions", json=body)


async def test_w2_03_chat_paths(client: httpx.AsyncClient) -> None:
    """T-W2-03-13, 14, 15, 16b, 20, 21, 22: identity v2, ev_session, usage, layering."""
    mem_key = "memory_enabled"
    mem_had = await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM gateway_config WHERE key = $1)", mem_key)
    mem_prev = await _config_row(mem_key)
    id_key = "session_identity_v2_enabled"
    id_had = await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM gateway_config WHERE key = $1)", id_key)
    id_prev = await _config_row(id_key)
    try:
        # Memory off for the whole block: proves the layering contract and keeps the
        # embedding/extraction boundaries out of these guards entirely.
        await _upsert_config(mem_key, "false")

        # ---- 20. memory off still records events, never extracts ------------
        # memories is cleared too: earlier guards seed it, and "zero extraction"
        # must be measured against an empty table, not against their leftovers.
        await _truncate("conversations", "memories")
        await _set_identity_gate(False)
        response = await _chat(client, {
            "model": "mock-model", "stream": False, "conversation_id": "w203-layer-a",
            "messages": [{"role": "user", "content": "hi"}],
        }, json_body={"choices": [{"message": {"content": "a-body"}}], "model": "mock-model"})
        require(response.status_code == 200, f"buffered chat failed: {response.status_code} {response.text[:200]}")
        rows = await _await_ledger("w203-layer-a", 2)
        require(len(rows) == 2, f"memory-off chat must still write 2 ledger rows, got {len(rows)}")
        require(await _pool_fetchval("SELECT COUNT(*) FROM memories") == 0,
                "memory-off chat must not extract any memory")
        passed("T-W2-03-20 with memory off the ledger still records the turn and nothing is extracted")

        # ---- 21. internal requests write nothing ----------------------------
        await _truncate("conversations")
        response = await _chat(client, {
            "model": "mock-model", "stream": False, "conversation_id": "w203-internal",
            "skip_system_prompt": True,
            "messages": [{"role": "user", "content": "summarize"}],
        }, json_body={"choices": [{"message": {"content": "title"}}], "model": "mock-model"})
        require(response.status_code == 200, "internal request failed")
        await _settle_background()
        require(not await _ledger_rows("w203-internal"),
                "an internal request (skip_system_prompt) must not touch the ledger")
        passed("T-W2-03-21 internal requests write neither events nor memories")

        # ---- 13/22. session identity v2 -------------------------------------
        await _truncate("conversations")
        await _set_identity_gate(True)
        seen = []
        for _ in range(2):
            response = await _chat(client, {
                "model": "mock-model", "stream": False,
                "messages": [{"role": "user", "content": "same opening line"}],
            }, json_body={"choices": [{"message": {"content": "a"}}], "model": "mock-model"})
            require(response.status_code == 200, "identity-v2 chat failed")
            sid = response.headers.get("x-kiwi-session-id")
            require(sid, "server-generated session must be returned in X-Kiwi-Session-Id")
            seen.append(sid)
        require(seen[0] != seen[1],
                f"identical opening lines must not collapse into one session: {seen}")
        require(all(s.startswith("auto-r-") and len(s) == len("auto-r-") + 32 for s in seen),
                f"identity v2 must be auto-r- plus a full uuid4 hex: {seen}")
        response = await _chat(client, {
            "model": "mock-model", "stream": False, "conversation_id": "w203-own-id",
            "messages": [{"role": "user", "content": "hi"}],
        }, json_body={"choices": [{"message": {"content": "a"}}], "model": "mock-model"})
        require("x-kiwi-session-id" not in response.headers,
                "a client-supplied conversation_id must never be echoed back")
        passed("T-W2-03-13 identity v2 gives distinct full-uuid sessions and never echoes client IDs")

        await _set_identity_gate(False)
        # Let the previous block's background writes land before truncating, or
        # their late rows reappear inside this guard's window.
        await _settle_background()
        await _truncate("conversations")
        for _ in range(2):
            await _chat(client, {
                "model": "mock-model", "stream": False,
                "messages": [{"role": "user", "content": "same opening line"}],
            }, json_body={"choices": [{"message": {"content": "a"}}], "model": "mock-model"})
        await _settle_background()
        legacy_sessions = {r["session_id"] for r in await _pool_fetch(
            "SELECT DISTINCT session_id FROM conversations")}
        require(len(legacy_sessions) == 1 and next(iter(legacy_sessions)).startswith("auto-"),
                f"gate-off must fall back to the md5 session exactly: {legacy_sessions}")
        require(not next(iter(legacy_sessions)).startswith("auto-r-"),
                "gate-off must not use the v2 prefix")
        passed("T-W2-03-22 with identity v2 off the legacy md5 session is restored byte for byte")

        # ---- 14/15. ev_session contract on streams --------------------------
        await _set_identity_gate(True)
        await _truncate("conversations")
        response = await _chat(client, {
            "model": "mock-model", "stream": True,
            "messages": [{"role": "user", "content": "stream me"}],
        }, sse_events=[_DELTA, _USAGE_TAIL, "data: [DONE]\n\n"])
        require(response.status_code == 200, "streaming chat failed")
        require(response.headers.get("x-kiwi-session-id"), "stream response lost X-Kiwi-Session-Id")
        events = [e for e in response.text.split("\n\n") if e.strip()]
        ev_indexes = [i for i, e in enumerate(events) if '"ev_session"' in e]
        require(len(ev_indexes) == 1, f"ev_session must appear exactly once per stream: {ev_indexes}")
        require(ev_indexes[0] == 0, f"ev_session must precede every other stream event: {events[:2]}")
        require(events[-1].strip() == "data: [DONE]", f"[DONE] must stay last: {events[-1]!r}")
        payload = json.loads(events[0].split("data: ", 1)[1])
        require(payload["ev_session"]["generated"] is True and payload["ev_session"]["id"],
                f"ev_session payload malformed: {payload}")
        passed("T-W2-03-14 ev_session is emitted once, first, and the header travels with the stream")

        response = await _chat(client, {
            "model": "mock-model", "stream": True,
            "messages": [{"role": "user", "content": "upstream will fail"}],
        }, sse_events=[], status_code=502)
        require(response.headers.get("x-kiwi-session-id"),
                "an upstream failure must still carry the retry identity (headers cannot be recalled)")
        require('"ev_session"' in response.text,
                "ev_session must still be present when the upstream fails")
        bad = await client.post("/v1/chat/completions", json={
            "model": "mock-model", "stream": True, "turn_key": "",
            "messages": [{"role": "user", "content": "rejected before identity"}],
        })
        require(bad.status_code == 400, "entry validation must still reject before identity")
        require("x-kiwi-session-id" not in bad.headers,
                "a request rejected before identity generation must not carry a session header")
        passed("T-W2-03-15 identity survives upstream failure but is absent on pre-identity 4xx")

        # ---- 16b. usage aggregation across the stream -----------------------
        await _truncate("conversations")
        response = await _chat(client, {
            "model": "mock-model", "stream": True, "conversation_id": "w203-usage",
            "messages": [{"role": "user", "content": "count me"}],
        }, sse_events=[_DELTA, _USAGE_TAIL, "data: [DONE]\n\n"],
           json_body={"choices": [{"message": {"content": "a-body"}}], "model": "mock-model",
                      "usage": {"prompt_tokens": 11, "completion_tokens": 5,
                                "prompt_tokens_details": {"cached_tokens": 2}}})
        require(response.status_code == 200, "usage stream failed")
        rows = await _await_ledger("w203-usage", 2)
        require(len(rows) == 2, f"usage stream must land a full turn: {len(rows)} rows")
        require(json.loads(rows[1]["usage"]) == {"prompt": 11, "completion": 5, "cached": 2},
                f"streamed usage was not captured/normalized: {rows[1]['usage']!r}")

        await _truncate("conversations")
        response = await _chat(client, {
            "model": "mock-model", "stream": True, "conversation_id": "w203-nousage",
            "messages": [{"role": "user", "content": "no usage block"}],
        }, sse_events=[_DELTA, "data: [DONE]\n\n"])
        rows = await _await_ledger("w203-nousage", 2)
        require(rows and rows[1]["usage"] is None,
                f"a stream without a usage block must store NULL: {rows[1]['usage'] if rows else 'no rows'!r}")

        # End to end with an Anthropic-shaped usage block.  The tool loop normalizes the
        # raw upstream usage *before* from_anthropic_response(), so this is the shape that
        # actually reaches the ledger there — a dropped cache term shows up as a low prompt.
        await _truncate("conversations")
        await _chat(client, {
            "model": "mock-model", "stream": True, "conversation_id": "w203-anthropic-usage",
            "messages": [{"role": "user", "content": "cached prompt"}],
        }, sse_events=[_DELTA, "data: [DONE]\n\n"],
           json_body={"choices": [{"message": {"content": "a-body"}}], "model": "mock-model",
                      "usage": {"input_tokens": 9, "output_tokens": 3,
                                "cache_creation_input_tokens": 40, "cache_read_input_tokens": 100}})
        rows = await _await_ledger("w203-anthropic-usage", 2)
        require(json.loads(rows[1]["usage"]) == {"prompt": 149, "completion": 3, "cached": 100},
                f"Anthropic cache tokens were lost end to end: {rows[1]['usage']!r}")
        passed("T-W2-03-16 usage is normalized for both vendors and captured/NULL across streams")
    finally:
        for key, had, prev in ((mem_key, mem_had, mem_prev), (id_key, id_had, id_prev)):
            if had:
                await _upsert_config(key, prev)
            else:
                await _pool_execute("DELETE FROM gateway_config WHERE key = $1", key)


# ---------------------------------------------------------------------------
# W2-04 | session deletion and privacy semantics
# ---------------------------------------------------------------------------

_W204_TOMBSTONE_TABLES = ("session_tombstones", "turn_tombstones", "message_tombstones")


async def _w204_reset_tables() -> None:
    await _truncate(
        "conversations", "chat_messages", "chat_conversations", "chat_projects",
        "compression_summaries", "memory_extraction_state",
        "session_tombstones", "turn_tombstones", "message_tombstones", "session_source_rev",
    )


async def _source_rev(session_id: str) -> int:
    value = await _pool_fetchval(
        "SELECT rev FROM session_source_rev WHERE session_id = $1", session_id
    )
    return 0 if value is None else value


async def _has_session_tombstone(session_id: str) -> bool:
    return bool(await _pool_fetchval(
        "SELECT EXISTS(SELECT 1 FROM session_tombstones WHERE session_id = $1)", session_id
    ))


async def _seed_conversation(sid: str, *, messages=(), events=(), summaries=0,
                             extraction_state=False, project_id=None) -> None:
    """Seed one conversation across every original-copy table W2-04 must purge."""
    await _pool_execute(
        "INSERT INTO chat_conversations (id, title, project_id) VALUES ($1, $2, $3) "
        "ON CONFLICT (id) DO NOTHING",
        sid, f"title-{sid}", project_id,
    )
    for mid, role, content, turn_key in messages:
        await _pool_execute(
            "INSERT INTO chat_messages (id, conversation_id, role, content, turn_key) "
            "VALUES ($1, $2, $3, $4, $5)",
            mid, sid, role, content, turn_key,
        )
    for role, content, turn_key in events:
        await _pool_execute(
            "INSERT INTO conversations (session_id, role, content, model, turn_key, scope_known) "
            "VALUES ($1, $2, $3, 'm', $4, TRUE)",
            sid, role, content, turn_key,
        )
    for index in range(summaries):
        await _pool_execute(
            "INSERT INTO compression_summaries (conversation_id, summary, msg_count) "
            "VALUES ($1, $2, $3)",
            sid, f"summary-{sid}-{index}", 1,
        )
    if extraction_state:
        await _pool_execute(
            "INSERT INTO memory_extraction_state (session_id, last_extracted_message_id) "
            "VALUES ($1, 0) ON CONFLICT (session_id) DO NOTHING",
            sid,
        )


async def _original_copy_counts(sid: str) -> dict:
    return {
        "conversation": await _pool_fetchval(
            "SELECT COUNT(*) FROM chat_conversations WHERE id = $1", sid),
        "messages": await _pool_fetchval(
            "SELECT COUNT(*) FROM chat_messages WHERE conversation_id = $1", sid),
        "events": await _pool_fetchval(
            "SELECT COUNT(*) FROM conversations WHERE session_id = $1", sid),
        "summaries": await _pool_fetchval(
            "SELECT COUNT(*) FROM compression_summaries WHERE conversation_id = $1", sid),
        "extraction_state": await _pool_fetchval(
            "SELECT COUNT(*) FROM memory_extraction_state WHERE session_id = $1", sid),
    }


async def test_w2_04_schema_and_conversation_delete(client: httpx.AsyncClient) -> None:
    """T-W2-04-1..6: tombstone/rev/epoch schema and whole-conversation deletion."""
    # ---- 1. schema ---------------------------------------------------------
    expected_columns = {
        "session_tombstones": {"session_id", "deleted_at"},
        "turn_tombstones": {"session_id", "turn_key", "deleted_at"},
        "message_tombstones": {"session_id", "message_id", "deleted_at"},
        "session_source_rev": {"session_id", "rev", "updated_at"},
        "deletion_epoch": {"id", "reset_generation"},
    }
    for table, columns in expected_columns.items():
        actual = {
            r["column_name"]
            for r in await _pool_fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = $1", table
            )
        }
        require(actual, f"W2-04 table {table} is missing entirely")
        require(columns <= actual, f"{table} columns missing: {sorted(columns - actual)}")

    async def primary_key(table):
        return {
            r["column_name"]
            for r in await _pool_fetch(
                "SELECT a.attname AS column_name FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = $1::regclass AND i.indisprimary", table
            )
        }

    require(await primary_key("session_tombstones") == {"session_id"},
            "session_tombstones must key on session_id alone")
    require(await primary_key("turn_tombstones") == {"session_id", "turn_key"},
            "turn_tombstones must key on (session_id, turn_key) so keys never collide across sessions")
    require(await primary_key("message_tombstones") == {"session_id", "message_id"},
            "message_tombstones must key on (session_id, message_id)")
    require(await primary_key("session_source_rev") == {"session_id"},
            "session_source_rev must key on session_id")
    require(await _pool_fetchval("SELECT COUNT(*) FROM deletion_epoch") == 1,
            "deletion_epoch must hold exactly one seeded row")
    require(await _pool_fetchval("SELECT id FROM deletion_epoch") == 1,
            "the deletion_epoch singleton must use id = 1")
    epoch_before = await _pool_fetchval("SELECT reset_generation FROM deletion_epoch")
    await database.init_tables()
    await database.init_tables()
    require(await _pool_fetchval("SELECT COUNT(*) FROM deletion_epoch") == 1,
            "repeat init_tables() duplicated the deletion_epoch singleton")
    require(await _pool_fetchval("SELECT reset_generation FROM deletion_epoch") == epoch_before,
            "repeat init_tables() must not disturb the reset generation")
    passed("T-W2-04-1 tombstone, source-rev and epoch tables exist and re-migrate idempotently")

    # ---- 2. deleting a conversation purges all five original copies --------
    await _w204_reset_tables()
    conv_a = "w204-a"
    await _seed_conversation(
        conv_a,
        messages=[("w204-a-m1", "user", "u1", "k1"), ("w204-a-m2", "assistant", "a1", "k1")],
        events=[("user", "u1", "k1"), ("assistant", "a1", "k1"),
                ("user", "u2", "k2"), ("assistant", "a2", "k2")],
        summaries=1, extraction_state=True,
    )
    response = await client.delete(f"/sync/conversations/{conv_a}")
    require(response.status_code == 200, f"conversation delete failed: {response.status_code}")
    require(response.json() == {"deleted": True,
                                "purged": {"events": 4, "summaries": 1, "extraction_state": 1}},
            f"delete response shape drifted (nesting?): {response.text}")
    counts = await _original_copy_counts(conv_a)
    require(all(v == 0 for v in counts.values()),
            f"original copies survived the delete: {counts}")
    require(await _has_session_tombstone(conv_a), "deleting a conversation must leave a session tombstone")
    require(await _source_rev(conv_a) == 1, "deleting a conversation must bump its source rev")
    passed("T-W2-04-2 deleting a conversation purges all five original copies and stamps it")

    # ---- 3. neighbours are untouched ---------------------------------------
    await _w204_reset_tables()
    conv_b = "w204-b"
    await _seed_conversation(
        conv_b,
        messages=[("w204-b-m1", "user", "u", "bk1")],
        events=[("user", "u", "bk1")], summaries=1, extraction_state=True,
    )
    await _seed_conversation("w204-b-victim", messages=[("w204-b-v1", "user", "u", "vk")],
                             events=[("user", "u", "vk")])
    await client.delete("/sync/conversations/w204-b-victim")
    counts = await _original_copy_counts(conv_b)
    require(counts == {"conversation": 1, "messages": 1, "events": 1,
                       "summaries": 1, "extraction_state": 1},
            f"a neighbouring conversation was damaged: {counts}")
    require(not await _has_session_tombstone(conv_b), "a neighbour must not be stamped")
    require(await _source_rev(conv_b) == 0, "a neighbour's source rev must not move")
    passed("T-W2-04-3 deleting one conversation leaves its neighbours completely alone")

    # ---- 4. the whole delete is one transaction ----------------------------
    await _w204_reset_tables()
    conv_r = "w204-rollback"
    await _seed_conversation(
        conv_r,
        messages=[("w204-r-m1", "user", "u", "rk")],
        events=[("user", "u", "rk")], summaries=1, extraction_state=True,
    )
    await _pool_execute(
        """
        CREATE OR REPLACE FUNCTION w204_fail_state_delete() RETURNS trigger AS $fn$
        BEGIN
            RAISE EXCEPTION 'W2_04_INJECTED_DELETE_FAILURE';
        END; $fn$ LANGUAGE plpgsql
        """
    )
    await _pool_execute("DROP TRIGGER IF EXISTS w204_fail_state_delete_trg ON memory_extraction_state")
    await _pool_execute(
        "CREATE TRIGGER w204_fail_state_delete_trg BEFORE DELETE ON memory_extraction_state "
        "FOR EACH ROW EXECUTE FUNCTION w204_fail_state_delete()"
    )
    try:
        capture, err_capture = io.StringIO(), io.StringIO()
        with redirect_stdout(capture), redirect_stderr(err_capture):
            response = await client.delete(f"/sync/conversations/{conv_r}")
        require(response.status_code == 500, f"injected delete failure must be 500, got {response.status_code}")
        require(response.json() == {"error": "删除失败"},
                f"delete crash must use the fixed safe message: {response.text}")
        logs = capture.getvalue() + err_capture.getvalue()
        require("W2_04_INJECTED_DELETE_FAILURE" not in (response.text + logs),
                "the injected exception body leaked out of the delete path")
        counts = await _original_copy_counts(conv_r)
        require(counts == {"conversation": 1, "messages": 1, "events": 1,
                           "summaries": 1, "extraction_state": 1},
                f"a failed delete left partial damage: {counts}")
        require(not await _has_session_tombstone(conv_r),
                "a rolled-back delete must not leave a tombstone behind")
        require(await _source_rev(conv_r) == 0, "a rolled-back delete must not bump the source rev")
        passed("T-W2-04-4 a failed delete rolls back stamp, rev and every table together")
    finally:
        await _pool_execute("DROP TRIGGER IF EXISTS w204_fail_state_delete_trg ON memory_extraction_state")
        await _pool_execute("DROP FUNCTION IF EXISTS w204_fail_state_delete()")

    # ---- 5. derived products are explicitly preserved ----------------------
    await _w204_reset_tables()
    await _truncate("memories", "calendar_pages", "mem_scenes", "dream_logs")
    conv_k = "w204-keep"
    await _seed_conversation(conv_k, messages=[("w204-k-m1", "user", "u", "kk")],
                             events=[("user", "u", "kk")])
    await _pool_execute(
        "INSERT INTO memories (content, importance, source_session) VALUES ($1, 5, $2)",
        "w204-keep-fragment", conv_k,
    )
    await _pool_execute(
        "INSERT INTO calendar_pages (date, type, diary) VALUES ('2026-08-15', 'day', 'w204-keep-page')"
    )
    await _pool_execute(
        "INSERT INTO mem_scenes (title, description) VALUES ('w204-keep-scene', 'd')"
    )
    await _pool_execute("INSERT INTO dream_logs (status) VALUES ('completed')")
    before = {t: await _pool_fetchval(f"SELECT COUNT(*) FROM {t}")
              for t in ("memories", "calendar_pages", "mem_scenes", "dream_logs")}
    await client.delete(f"/sync/conversations/{conv_k}")
    after = {t: await _pool_fetchval(f"SELECT COUNT(*) FROM {t}")
             for t in ("memories", "calendar_pages", "mem_scenes", "dream_logs")}
    require(before == after, f"derived products must survive a conversation delete: {before} -> {after}")
    require(await _pool_fetchval(
        "SELECT content FROM memories WHERE source_session = $1", conv_k) == "w204-keep-fragment",
        "a memory fragment lost its content when its source conversation was deleted")
    passed("T-W2-04-5 memories, calendar pages, scenes and dreams all survive the delete")

    # ---- 6. privacy wins even when the directory row is already gone -------
    await _w204_reset_tables()
    conv_o = "w204-orphan"
    await _pool_execute(
        "INSERT INTO conversations (session_id, role, content, model, turn_key, scope_known) "
        "VALUES ($1, 'user', 'orphan-body', 'm', 'ok1', TRUE)", conv_o,
    )
    await _pool_execute(
        "INSERT INTO memory_extraction_state (session_id, last_extracted_message_id) VALUES ($1, 0)",
        conv_o,
    )
    response = await client.delete(f"/sync/conversations/{conv_o}")
    require(response.status_code == 200, "orphan delete failed")
    body = response.json()
    require(body["deleted"] is False,
            f"a missing directory row must report deleted=false, got {body}")
    require(body["purged"]["events"] == 1 and body["purged"]["extraction_state"] == 1,
            f"orphan ledger rows must still be purged: {body}")
    counts = await _original_copy_counts(conv_o)
    require(counts["events"] == 0 and counts["extraction_state"] == 0,
            f"orphan original copies survived: {counts}")
    require(await _has_session_tombstone(conv_o),
            "the stamp keys on session_id, not on the directory row existing")
    passed("T-W2-04-6 a missing directory row never blocks purging the remaining copies")


async def _seed_divider(sid: str, mid: str, *, summary: str, handoff: bool = False) -> None:
    """Auto-compression dividers carry a summary and no handoff_info; handoff ones do."""
    await _pool_execute(
        "INSERT INTO chat_messages (id, conversation_id, role, content, summary, handoff_info) "
        "VALUES ($1, $2, 'divider', '', $3, $4)",
        mid, sid, summary, json.dumps({"from": "x"}) if handoff else None,
    )


async def test_w2_04_message_delete_and_ledger(client: httpx.AsyncClient) -> None:
    """T-W2-04-7..9: message mirroring, tombstoned writes, interleaved race."""
    # ---- 7. message-level mirroring, stamps, compression purge, fallback ----
    await _w204_reset_tables()
    conv_c, conv_d = "w204-c", "w204-d"
    await _seed_conversation(
        conv_c,
        messages=[("w204-c-u1", "user", "u1", "k1"), ("w204-c-a1", "assistant", "a1", "k1"),
                  ("w204-c-u2", "user", "u2", "k2"), ("w204-c-a2", "assistant", "a2", "k2")],
        events=[("user", "u1", "k1"), ("assistant", "a1", "k1"),
                ("user", "u2", "k2"), ("assistant", "a2", "k2")],
        summaries=2,
    )
    await _seed_divider(conv_c, "w204-c-d1", summary="auto-1")
    await _seed_divider(conv_c, "w204-c-d2", summary="auto-2")
    await _seed_divider(conv_c, "w204-c-h1", summary="handoff-sum", handoff=True)
    # A different conversation reusing the same turn_key / message id must stay untouched.
    await _seed_conversation(conv_d, messages=[("w204-c-a1", "assistant", "d-a1", "k1")],
                             events=[("assistant", "d-a1", "k1")])

    # ① delete the k1 assistant: mirror one ledger row, stamp the message, keep the turn alive
    response = await client.delete(f"/sync/conversations/{conv_c}/messages/w204-c-a1")
    require(response.status_code == 200, f"message delete failed: {response.status_code}")
    body = response.json()
    require(body["deleted"] is True and body["ledger_mode"] == "turn",
            f"a keyed message delete must mirror through the turn branch: {body}")
    require(body["purged"] == {"compression_summaries": 2, "compression_dividers": 2},
            f"compression copies were not purged exactly: {body}")
    require(body["source_rev"] == 1, f"message delete must bump and report the rev: {body}")
    k1_roles = [r["role"] for r in await _pool_fetch(
        "SELECT role FROM conversations WHERE session_id = $1 AND turn_key = 'k1'", conv_c)]
    require(k1_roles == ["user"], f"the k1 ledger should keep only its user row, got {k1_roles}")
    require(not await _pool_fetchval(
        "SELECT EXISTS(SELECT 1 FROM turn_tombstones WHERE session_id = $1 AND turn_key = 'k1')", conv_c),
        "deleting one assistant must not stamp the whole turn — it can still be regenerated")
    require(await _pool_fetchval(
        "SELECT EXISTS(SELECT 1 FROM message_tombstones WHERE session_id = $1 AND message_id = $2)",
        conv_c, "w204-c-a1"), "a deleted message must be stamped so old devices cannot restore it")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM compression_summaries WHERE conversation_id = $1", conv_c) == 0,
        "internal compression summaries must be purged with the message")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM chat_messages WHERE conversation_id = $1 AND role = 'divider' "
        "AND summary IS NOT NULL AND handoff_info IS NULL", conv_c) == 0,
        "auto-compression dividers must be purged with the message")
    require(await _pool_fetchval(
        "SELECT EXISTS(SELECT 1 FROM chat_messages WHERE id = 'w204-c-h1')"),
        "handoff dividers are not compression copies and must survive")
    # the stamped id can never be pushed back, but a new id in the same turn still works
    response = await client.put(f"/sync/conversations/{conv_c}/messages/w204-c-a1",
                                json={"role": "assistant", "content": "resurrect", "turnKey": "k1"})
    require(response.status_code == 410 and response.json().get("code") == "message_deleted",
            f"a stamped message id must be refused with 410/message_deleted: {response.status_code} {response.text}")
    response = await client.put(f"/sync/conversations/{conv_c}/messages/w204-c-a1b",
                                json={"role": "assistant", "content": "regenerated", "turnKey": "k1"})
    require(response.status_code == 200,
            f"regenerating the same turn under a fresh message id must succeed: {response.text}")

    # ② delete the k1 user too: now the whole turn is stamped
    response = await client.delete(f"/sync/conversations/{conv_c}/messages/w204-c-u1")
    require(response.status_code == 200, "second message delete failed")
    require(await _pool_fetchval(
        "SELECT EXISTS(SELECT 1 FROM turn_tombstones WHERE session_id = $1 AND turn_key = 'k1')", conv_c),
        "emptying a turn must stamp it so the old turn can never be re-landed")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM conversations WHERE session_id = $1 AND turn_key = 'k1'", conv_c) == 0,
        "an emptied turn must leave no ledger rows")
    # ③ the other turn is untouched
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM conversations WHERE session_id = $1 AND turn_key = 'k2'", conv_c) == 2,
        "deleting turn k1 damaged turn k2")
    # ④ the same key/id in another conversation is untouched
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM conversations WHERE session_id = $1", conv_d) == 1,
        "stamps and mirrors must be scoped per session")
    require(await _pool_fetchval("SELECT EXISTS(SELECT 1 FROM chat_messages WHERE id = 'w204-c-a1' "
                                 "AND conversation_id = $1)", conv_d),
            "another conversation's identically-named message was deleted")

    # ⑤ fallback branch: NULL turn_key means we cannot locate the turn -> purge the session ledger
    conv_e = "w204-e"
    await _seed_conversation(
        conv_e,
        messages=[("w204-e-m1", "user", "u1", None), ("w204-e-m2", "assistant", "a1", None),
                  ("w204-e-m3", "user", "u2", None)],
        events=[("user", "u1", None), ("assistant", "a1", None), ("user", "u2", None),
                ("assistant", "a2", None), ("user", "u3", None), ("assistant", "a3", None)],
        summaries=1,
    )
    await _seed_divider(conv_e, "w204-e-d1", summary="auto-e")
    await _seed_divider(conv_e, "w204-e-h1", summary="handoff-e", handoff=True)
    response = await client.delete(f"/sync/conversations/{conv_e}/messages/w204-e-m2")
    require(response.status_code == 200, "fallback message delete failed")
    body = response.json()
    require(body["ledger_mode"] == "session_fallback",
            f"a keyless message delete must report the fallback branch: {body}")
    require(body["ledger_events_deleted"] == 6,
            f"the fallback must purge the whole session ledger: {body}")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM conversations WHERE session_id = $1", conv_e) == 0,
        "privacy first: an unlocatable turn purges the session's ledger entirely")
    surviving = sorted(r["id"] for r in await _pool_fetch(
        "SELECT id FROM chat_messages WHERE conversation_id = $1 ORDER BY id", conv_e))
    require(surviving == ["w204-e-h1", "w204-e-m1", "w204-e-m3"],
            f"the fallback must keep the surviving originals and the handoff divider: {surviving}")
    require(not await _has_session_tombstone(conv_e),
            "the fallback must NOT stamp the session — the conversation is still alive")
    require(await _source_rev(conv_e) == 1, "the fallback must still bump the source rev")
    # the conversation keeps working afterwards
    result = await database.append_turn_events_atomic(conv_e, "u-new", "a-new", "m", turn_key="ek-new")
    require(result.get("ok") is True,
            f"a conversation that took the fallback must keep accepting new turns: {result}")
    passed("T-W2-04-7 message deletes mirror, stamp, purge compression copies, and degrade safely")

    # ---- 8. writes stop at every stamp and at an old generation -------------
    await _w204_reset_tables()
    stamped = "w204-stamped"
    await _seed_conversation(stamped)
    await client.delete(f"/sync/conversations/{stamped}")
    result = await database.append_turn_events_atomic(stamped, "u", "a", "m", turn_key="sk")
    require(result.get("path") == "tombstoned" and result.get("reason") == "session",
            f"a stamped session must refuse new ledger writes: {result}")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM conversations WHERE session_id = $1", stamped) == 0,
        "a refused write must leave zero rows")

    turn_sid = "w204-turnstamp"
    await _seed_conversation(turn_sid,
                             messages=[("w204-t-u1", "user", "u", "tk1")],
                             events=[("user", "u", "tk1")])
    await client.delete(f"/sync/conversations/{turn_sid}/messages/w204-t-u1")
    result = await database.append_turn_events_atomic(
        turn_sid, "u", "a-regen", "m", turn_key="tk1", is_regenerate=True)
    require(result.get("path") == "tombstoned" and result.get("reason") == "turn",
            f"a stamped turn must refuse regeneration: {result}")
    result = await database.append_turn_events_atomic(turn_sid, "u", "a", "m", turn_key="tk2")
    require(result.get("ok") is True, f"an unstamped turn must still land: {result}")

    generation = await _pool_fetchval("SELECT reset_generation FROM deletion_epoch")
    result = await database.append_turn_events_atomic(
        "w204-gen", "u", "a", "m", turn_key="gk", reset_generation=generation - 1)
    require(result.get("path") == "tombstoned" and result.get("reason") == "reset",
            f"a write carrying a stale generation must be refused: {result}")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM conversations WHERE session_id = 'w204-gen'") == 0,
        "a stale-generation write must leave zero rows")
    passed("T-W2-04-8 session stamps, turn stamps and stale generations all stop the write")

    # ---- 9. interleaved delete vs in-flight write: one deterministic outcome
    await _w204_reset_tables()
    race_sid = "w204-race"
    await _seed_conversation(race_sid)
    reached_write = asyncio.Event()
    release_write = asyncio.Event()
    original_status = database._tombstone_status_tx

    async def _paused_status(conn, session_id, *args, **kwargs):
        # Runs inside the real production transaction, after the real stamp lookup,
        # while the real session lock is still held.
        outcome = await original_status(conn, session_id, *args, **kwargs)
        if session_id == race_sid:
            reached_write.set()
            await release_write.wait()
        return outcome

    with patch.object(database, "_tombstone_status_tx", _paused_status):
        writer = asyncio.create_task(
            database.append_turn_events_atomic(race_sid, "u", "a", "m", turn_key="rk"))
        await asyncio.wait_for(reached_write.wait(), timeout=15)
        deleter = asyncio.create_task(database.sync_delete_conversation(race_sid))
        await asyncio.sleep(0.6)
        require(not deleter.done(),
                "the delete did not wait for the in-flight write: the session lock is missing")
        blocked = await _pool_fetchval(
            "SELECT COUNT(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
        require(blocked >= 1,
                "expected the deleting connection to be parked on an advisory lock")
        release_write.set()
        await asyncio.wait_for(writer, timeout=20)
        await asyncio.wait_for(deleter, timeout=20)
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM conversations WHERE session_id = $1", race_sid) == 0,
        "the interleaved race left ledger rows behind: delete must win the final state")
    require(await _has_session_tombstone(race_sid),
            "the interleaved race lost the session tombstone")
    passed("T-W2-04-9 an interleaved delete and ledger write serialize to one clean final state")


def _backup_zip(conversations: list, projects=()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("conversations.json", json.dumps(conversations, ensure_ascii=False))
        zf.writestr("projects.json", json.dumps(list(projects), ensure_ascii=False))
    return buf.getvalue()


async def test_w2_04_no_resurrection(client: httpx.AsyncClient) -> None:
    """T-W2-04-10..11: no ordinary sync may resurrect; only backup restore lifts a stamp."""
    # ---- 10. every ordinary write channel refuses a deleted conversation ----
    await _w204_reset_tables()
    dead = "w204-dead"
    await _seed_conversation(dead, messages=[("w204-dead-m1", "user", "u", "dk")],
                             events=[("user", "u", "dk")])
    await client.delete(f"/sync/conversations/{dead}")

    response = await client.post("/sync/conversations", json={"id": dead, "title": "back?"})
    require(response.status_code == 410 and response.json().get("code") == "deleted",
            f"conversation POST resurrected a deleted id: {response.status_code} {response.text}")
    response = await client.put(f"/sync/conversations/{dead}", json={"title": "back?"})
    require(response.status_code == 410 and response.json().get("code") == "deleted",
            f"legacy PUT resurrected a deleted id: {response.status_code}")
    response = await client.put(f"/sync/conversations/{dead}/messages/w204-dead-m9",
                                json={"role": "user", "content": "back?"})
    require(response.status_code == 410 and response.json().get("code") == "deleted",
            f"single-message PUT resurrected a deleted conversation: {response.status_code}")
    response = await client.put(f"/sync/conversations/{dead}",
                                json={"title": "back?", "messages": [
                                    {"id": "w204-dead-m8", "role": "user", "content": "x"}]})
    require(response.status_code == 410, "legacy full replace resurrected a deleted conversation")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM chat_conversations WHERE id = $1", dead) == 0,
        "a refused write still created the conversation")

    alive = "w204-alive"
    response = await client.post("/sync/import", json={
        "conversations": [
            {"id": dead, "title": "back?", "messages": []},
            {"id": alive, "title": "healthy", "messages": [
                {"id": "w204-alive-m1", "role": "user", "content": "hi"}]},
        ],
        "projects": [],
    })
    require(response.status_code == 200, "import must stay 200 for per-entity rejects")
    body = response.json()
    dead_rejects = [d for d in body["rejected_details"]
                    if d["id"] == dead and d["code"] == "deleted"]
    require(dead_rejects, f"import must reject a deleted conversation with code=deleted: {body['rejected_details']}")
    require(alive in body["imported_conversation_ids"],
            "a deleted sibling must not block healthy entities in the same batch")

    # a stamped message id inside a still-alive conversation
    live = "w204-live"
    await _seed_conversation(live, messages=[("w204-live-m1", "user", "u1", "lk1"),
                                             ("w204-live-m2", "assistant", "a1", "lk1")],
                             events=[("user", "u1", "lk1"), ("assistant", "a1", "lk1")])
    await client.delete(f"/sync/conversations/{live}/messages/w204-live-m2")
    response = await client.put(f"/sync/conversations/{live}/messages/w204-live-m2",
                                json={"role": "assistant", "content": "back?", "turnKey": "lk1"})
    require(response.status_code == 410 and response.json().get("code") == "message_deleted",
            f"a stamped message id must be refused: {response.status_code} {response.text}")
    require(await _pool_fetchval(
        "SELECT EXISTS(SELECT 1 FROM chat_conversations WHERE id = $1)", live),
        "a message-level 410 must never take down the whole conversation")
    # full replace / import must filter that id but keep the rest
    response = await client.put(f"/sync/conversations/{live}", json={
        "title": "still here", "messages": [
            {"id": "w204-live-m1", "role": "user", "content": "u1"},
            {"id": "w204-live-m2", "role": "assistant", "content": "back?"},
            {"id": "w204-live-m3", "role": "user", "content": "u2"},
        ]})
    require(response.status_code == 200,
            f"a stamped message must not fail the whole replace: {response.status_code} {response.text}")
    require(response.json().get("skipped_deleted_messages") == ["w204-live-m2"],
            f"the replace must name the message ids it refused to restore: {response.text}")
    ids = sorted(r["id"] for r in await _pool_fetch(
        "SELECT id FROM chat_messages WHERE conversation_id = $1", live))
    require(ids == ["w204-live-m1", "w204-live-m3"],
            f"the stamped message came back through the replace channel: {ids}")

    # ---- the one and only place a stamp is lifted: explicit backup restore --
    backup = _backup_zip([
        {"id": dead, "title": "restored", "messages": [
            {"id": "w204-dead-m1", "role": "user", "content": "restored-body"}]},
        {"id": live, "title": "restored-live", "messages": [
            {"id": "w204-live-m2", "role": "assistant", "content": "restored-a1"}]},
    ])
    response = await client.post("/sync/import-backup",
                                 files={"file": ("backup.zip", backup, "application/zip")})
    require(response.status_code == 200, f"backup restore failed: {response.status_code} {response.text}")
    require(not await _has_session_tombstone(dead),
            "an explicit backup restore must lift the session stamp")
    require(not await _pool_fetchval(
        "SELECT EXISTS(SELECT 1 FROM message_tombstones WHERE session_id = $1)", live),
        "an explicit backup restore must lift the message stamps of the restored conversation")
    require(await _pool_fetchval(
        "SELECT EXISTS(SELECT 1 FROM chat_messages WHERE id = 'w204-dead-m1')"),
        "the restored conversation's messages are missing")
    result = await database.append_turn_events_atomic(dead, "u", "a", "m", turn_key="dk-new")
    require(result.get("ok") is True,
            f"a restored conversation must accept new ledger writes again: {result}")

    # restore must be atomic per conversation: a mid-way failure keeps the old stamp and data
    atomic = "w204-restore-atomic"
    await _seed_conversation(atomic, messages=[("w204-ra-m1", "user", "old-body", "rk")],
                             events=[("user", "old-body", "rk")])
    await client.delete(f"/sync/conversations/{atomic}")
    await _pool_execute(
        """
        CREATE OR REPLACE FUNCTION w204_fail_restore_msg() RETURNS trigger AS $fn$
        BEGIN
            IF NEW.conversation_id = 'w204-restore-atomic'
            THEN RAISE EXCEPTION 'W2_04_INJECTED_RESTORE_FAILURE'; END IF;
            RETURN NEW;
        END; $fn$ LANGUAGE plpgsql
        """
    )
    await _pool_execute("DROP TRIGGER IF EXISTS w204_fail_restore_msg_trg ON chat_messages")
    await _pool_execute(
        "CREATE TRIGGER w204_fail_restore_msg_trg BEFORE INSERT ON chat_messages "
        "FOR EACH ROW EXECUTE FUNCTION w204_fail_restore_msg()"
    )
    try:
        capture = io.StringIO()
        with redirect_stdout(capture), redirect_stderr(io.StringIO()):
            await client.post("/sync/import-backup", files={"file": (
                "backup.zip",
                _backup_zip([{"id": atomic, "title": "half", "messages": [
                    {"id": "w204-ra-m2", "role": "user", "content": "new-body"}]}]),
                "application/zip")})
        require(await _has_session_tombstone(atomic),
                "a failed restore must leave the stamp in place: unstamping is not a separate commit")
        require(await _pool_fetchval(
            "SELECT COUNT(*) FROM chat_conversations WHERE id = $1", atomic) == 0,
            "a failed restore must not leave half-restored metadata behind")
        passed("T-W2-04-10 no ordinary channel resurrects; only an explicit backup restore does, atomically")
    finally:
        await _pool_execute("DROP TRIGGER IF EXISTS w204_fail_restore_msg_trg ON chat_messages")
        await _pool_execute("DROP FUNCTION IF EXISTS w204_fail_restore_msg()")

    # ---- 11. reset stamps the union of all four original-copy tables --------
    await _w204_reset_tables()
    await _truncate("memories", "calendar_pages")
    await _seed_conversation("w204-f", messages=[("w204-f-m1", "user", "u", "fk")])
    await _pool_execute(
        "INSERT INTO conversations (session_id, role, content, model, scope_known) "
        "VALUES ('w204-g', 'user', 'g-body', 'm', TRUE)")
    await _pool_execute(
        "INSERT INTO memory_extraction_state (session_id, last_extracted_message_id) "
        "VALUES ('w204-h', 0)")
    await _pool_execute(
        "INSERT INTO compression_summaries (conversation_id, summary, msg_count) "
        "VALUES ('w204-i', 'orphan-summary', 1)")
    for index in range(3):
        await _pool_execute(
            "INSERT INTO memories (content, importance) VALUES ($1, 5)", f"w204-keep-mem-{index}")
    await _pool_execute(
        "INSERT INTO calendar_pages (date, type, diary) VALUES ('2026-08-14', 'day', 'keep-page')")
    await _upsert_config("memory_enabled", "true")
    epoch_before = await _pool_fetchval("SELECT reset_generation FROM deletion_epoch")

    response = await client.delete("/sync/reset", json={"confirm": "RESET_ALL_DATA"})
    require(response.status_code == 200, f"reset failed: {response.status_code} {response.text}")
    body = response.json()
    require("purged_events" in body and "purged_extraction_state" in body,
            f"reset must report what it purged: {body}")
    for table, column, value in (("chat_conversations", "id", "w204-f"),
                                 ("conversations", "session_id", "w204-g"),
                                 ("memory_extraction_state", "session_id", "w204-h"),
                                 ("compression_summaries", "conversation_id", "w204-i")):
        require(await _pool_fetchval(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = $1", value) == 0,
            f"reset left rows behind in {table}")
    for sid in ("w204-f", "w204-g", "w204-h", "w204-i"):
        require(await _has_session_tombstone(sid),
                f"reset must stamp {sid}: the union of all four tables, not just one")
        require(await _source_rev(sid) == 1, f"reset must bump the source rev of {sid}")
    require(await _pool_fetchval("SELECT reset_generation FROM deletion_epoch") == epoch_before + 1,
            "reset must advance the deletion epoch so in-flight requests are refused")
    require(await _pool_fetchval("SELECT COUNT(*) FROM memories") == 3,
            "reset must keep memories")
    require(await _pool_fetchval("SELECT COUNT(*) FROM calendar_pages") == 1,
            "reset must keep calendar pages")
    require(await _config_row("memory_enabled") == "true",
            "reset must keep gateway configuration")
    passed("T-W2-04-11 reset stamps the union of every original-copy table and advances the epoch")


def _single_statement_snapshot(source: str, func_name: str) -> str:
    """Return the body of func_name, for asserting it reads body+rev in ONE statement."""
    match = re.search(rf"async def {func_name}\(.*?(?=\nasync def |\ndef )", source, re.S)
    require(match, f"{func_name} not found for the snapshot guard")
    return match.group(0)


async def test_w2_04_background_snapshots(client: httpx.AsyncClient) -> None:
    """T-W2-04-12..14: extraction and day-page snapshot/recompute contracts."""
    db_source = (ROOT / "database.py").read_text(encoding="utf-8")

    # ---- 12/13 part one: body and rev must come from ONE statement ---------
    # A two-query design ("read messages, then read revs") has a window where a
    # delete lands between them, producing the one forbidden combination:
    # stale body + fresh rev, which then passes the save-time comparison.
    for func in ("get_recent_conversation", "get_chat_messages_for_date"):
        body = _single_statement_snapshot(db_source, func)
        require("session_source_rev" in body and "deletion_epoch" in body,
                f"{func} must return source_rev and reset_generation itself, not via a second query")
        statements = re.findall(r"(?:fetch|fetchrow|fetchval)\s*\(", body)
        require(len(statements) == 1,
                f"{func} must read body+rev+generation in a single statement, found {len(statements)} reads")
    passed("T-W2-04-12 material readers take body, source rev and generation in one snapshot")

    # ---- 12 part two: save compares under the same locks -------------------
    await _w204_reset_tables()
    await _truncate("memories")
    src_a, src_b = "w204-src-a", "w204-src-b"
    for sid in (src_a, src_b):
        await _seed_conversation(sid, events=[("user", f"body-{sid}", f"{sid}-k")])

    snapshot = await database.snapshot_recent_conversation(limit=20)
    require(snapshot["sources"], "the extraction snapshot must record its source sessions")
    require(set(snapshot["sources"]) >= {src_a, src_b},
            f"snapshot must cover every source session it read: {snapshot['sources']}")

    async def _save_one(conn):
        await database._insert_memory_tx(conn, content="w204-should-not-land", importance=5,
                                         source_session=src_a)
        return "saved"

    await client.delete(f"/sync/conversations/{src_a}")
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            status, _ = await database.save_if_sources_unchanged(conn, snapshot, _save_one)
    require(status == "changed",
            f"a save must be refused once one of its sources changed, got {status}")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM memories WHERE content = 'w204-should-not-land'") == 0,
        "a refused save still wrote memories")

    # an unchanged snapshot still saves
    fresh = await database.snapshot_recent_conversation(limit=20)
    async with pool.acquire() as conn:
        async with conn.transaction():
            status, _ = await database.save_if_sources_unchanged(
                conn, fresh,
                lambda c: database._insert_memory_tx(c, content="w204-should-land",
                                                     importance=5, source_session=src_b))
    require(status == "saved", f"an unchanged snapshot must save, got {status}")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM memories WHERE content = 'w204-should-land'") == 1,
        "an unchanged snapshot failed to save")

    # a reset also invalidates an in-flight snapshot
    stale = await database.snapshot_recent_conversation(limit=20)
    await client.delete("/sync/reset", json={"confirm": "RESET_ALL_DATA"})
    async with pool.acquire() as conn:
        async with conn.transaction():
            status, _ = await database.save_if_sources_unchanged(conn, stale, _save_one)
    require(status == "changed", f"a reset must invalidate every in-flight snapshot, got {status}")
    passed("T-W2-04-13 saves are refused when any source session changed or a reset intervened")

    # ---- 14. calendar three-state double check (W2-06a hook) ---------------
    await _w204_reset_tables()
    await _truncate("calendar_pages")
    day = "2026-08-13"
    conv_x, conv_y = "w204-cal-x", "w204-cal-y"
    for sid, body in ((conv_x, "cal-body-x"), (conv_y, "cal-body-y")):
        await _seed_conversation(sid)
        await _pool_execute(
            "INSERT INTO chat_messages (id, conversation_id, role, content, time, turn_key) "
            "VALUES ($1, $2, 'user', $3, $4::date, $5)",
            f"{sid}-m1", sid, body, day, f"{sid}-k",
        )
        await _pool_execute(
            "INSERT INTO conversations (session_id, role, content, model, turn_key, scope_known, created_at) "
            "VALUES ($1, 'user', $2, 'm', $3, TRUE, $4::date)",
            sid, body, f"{sid}-k", day,
        )

    async def _material_agreement(date_str):
        """chat_messages readers and the ledger must agree on 'is there material'."""
        rows = await database.get_chat_messages_for_date(date_str)
        ledger = await _pool_fetchval(
            f"SELECT COUNT(*) FROM conversations WHERE created_at::date = $1::date "
            f"AND {database.CONVERSATIONS_GLOBAL_SCOPE}", date_str)
        return bool(rows), bool(ledger)

    chat_has, ledger_has = await _material_agreement(day)
    require(chat_has and ledger_has,
            f"seeded day must have material on both sides: chat={chat_has} ledger={ledger_has}")
    # delete one of two conversations: material remains on both sides
    await client.delete(f"/sync/conversations/{conv_x}")
    chat_has, ledger_has = await _material_agreement(day)
    require(chat_has == ledger_has == True,
            f"after deleting one of two, both sides must still see material: {chat_has} {ledger_has}")
    # delete the last one: both sides go empty together
    await client.delete(f"/sync/conversations/{conv_y}")
    chat_has, ledger_has = await _material_agreement(day)
    require(chat_has == ledger_has == False,
            f"after deleting the last conversation both sides must be empty: {chat_has} {ledger_has}")
    passed("T-W2-04-14 chat-message and ledger material views stay in agreement across deletes")


async def test_w2_04_privacy_and_contracts(client: httpx.AsyncClient) -> None:
    """T-W2-04-15..17: observability sentinels, structural contracts, legacy guard counts."""
    # ---- 15. no identifier or exception body escapes any delete path -------
    await _w204_reset_tables()
    secret_sid = f"W204_SID_{uuid.uuid4().hex}"
    secret_key = f"W204_TURNKEY_{uuid.uuid4().hex}"
    secret_title = f"W204_TITLE_{uuid.uuid4().hex}"
    await _pool_execute(
        "INSERT INTO chat_conversations (id, title) VALUES ($1, $2)", secret_sid, secret_title)
    await _pool_execute(
        "INSERT INTO chat_messages (id, conversation_id, role, content, turn_key) "
        "VALUES ('w204-sec-m1', $1, 'user', 'body', $2)", secret_sid, secret_key)
    await _pool_execute(
        "INSERT INTO conversations (session_id, role, content, model, turn_key, scope_known) "
        "VALUES ($1, 'user', 'body', 'm', $2, TRUE)", secret_sid, secret_key)

    secrets = (secret_sid, secret_key, secret_title)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        r_msg = await client.delete(f"/sync/conversations/{secret_sid}/messages/w204-sec-m1")
        r_write = await database.append_turn_events_atomic(
            secret_sid, "u", "a", "m", turn_key=secret_key, reset_generation=-1)
        r_conv = await client.delete(f"/sync/conversations/{secret_sid}")
        r_410 = await client.post("/sync/conversations", json={"id": secret_sid, "title": "x"})
        r_reset = await client.delete("/sync/reset", json={"confirm": "RESET_ALL_DATA"})
    logs = out.getvalue() + err.getvalue()
    require(r_write.get("path") == "tombstoned", f"stale-generation write should be refused: {r_write}")
    for label, text in (("message delete", r_msg.text), ("conversation delete", r_conv.text),
                        ("410 response", r_410.text), ("reset", r_reset.text), ("logs", logs)):
        for secret in secrets:
            require(secret not in text,
                    f"{label} leaked an identifier read from the database ({secret[:12]}…)")
    events = [ln.strip() for ln in logs.splitlines() if ln.startswith("event=")]
    require(events, f"the delete paths must still emit structured events: {logs[:200]!r}")
    for event in events:
        for secret in secrets:
            require(secret not in event, f"a structured event carried an identifier: {event}")

    # the one sanctioned exception: /sync/import echoes back the ids the caller just submitted
    submitted = f"w204-echo-{uuid.uuid4().hex[:8]}"
    response = await client.post("/sync/import", json={
        "conversations": ["not-a-dict", {"id": submitted, "title": "t", "messages": []}],
        "projects": [],
    })
    require(submitted in response.text,
            "the import receipt must echo submitted ids so callers can reconcile")
    passed("T-W2-04-15 delete paths leak no identifiers, bodies or exception text")

    # ---- 16. structural contracts -----------------------------------------
    db_source = (ROOT / "database.py").read_text(encoding="utf-8")
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")

    # every ledger DELETE is scoped by session_id
    for statement in re.findall(r"DELETE FROM conversations[^\"']*", db_source):
        flat = " ".join(statement.split())
        require("session_id" in flat, f"a ledger DELETE is not scoped by session_id: {flat}")

    # the global-scope predicate is referenced, never hand-written
    hand_written = re.findall(r"scope_known = TRUE AND project_id IS NULL", db_source)
    require(len(hand_written) == 1,
            f"CONVERSATIONS_GLOBAL_SCOPE must be referenced, not re-typed ({len(hand_written)} copies)")

    # advisory locks only ever appear inside an explicit transaction helper
    for helper in ("_lock_global_shared", "_lock_global_exclusive",
                   "_lock_session", "_lock_sessions_shared"):
        require(helper in db_source, f"lock helper {helper} is missing")
    lock_calls = re.findall(r"pg_advisory_xact_lock\w*", db_source)
    require(lock_calls, "no advisory locks found at all")
    lock_sites = re.findall(r"async def (_lock_\w+)\(", db_source)
    require(len(lock_calls) <= len(lock_sites) + 1,
            f"advisory locks are being hand-rolled outside the lock helpers: {lock_calls}")

    # restore is the single place a stamp is lifted
    unstamp = re.findall(r"DELETE FROM (?:session|turn|message)_tombstones", db_source)
    require(unstamp, "nothing ever lifts a stamp — backup restore cannot work")
    restore_body = _single_statement_snapshot.__doc__ and re.search(
        r"async def _restore_conversation_tx\(.*?(?=\nasync def |\ndef )", db_source, re.S)
    require(restore_body, "_restore_conversation_tx must exist as the only un-stamping path")
    for statement in unstamp:
        require(statement in restore_body.group(0),
                f"a stamp is lifted outside _restore_conversation_tx: {statement}")

    # conn-aware transaction primitives never grab a second connection or call outward
    for primitive in re.findall(r"async def (_\w+_tx)\(", db_source):
        body = re.search(rf"async def {primitive}\(.*?(?=\nasync def |\ndef )", db_source, re.S)
        if not body:
            continue
        text = body.group(0)
        require("pool.acquire" not in text and "get_pool()" not in text,
                f"{primitive} takes its own connection — it must reuse the caller's transaction")
        for outward in ("get_embedding", "extract_memories", "web_search", "httpx"):
            require(outward not in text,
                    f"{primitive} makes an outward call ({outward}) while holding locks")

    require('{"error": "删除失败"}' in main_source or '"删除失败"' in main_source,
            "the delete routes must use a fixed safe crash message")
    passed("T-W2-04-16 locks, scoped deletes, single un-stamp path and lock-free primitives all hold")

    # ---- 17. the 107 inherited guards are untouched -------------------------
    inherited = {"T-S": 34, "T-W1-01-": 4, "T-W1-06-": 4, "T-W1-08-": 6,
                 "T-W2-01-": 12, "T-W2-02-": 22, "T-W2-03-": 25}
    for prefix, expected in inherited.items():
        actual = len([name for name in PASSED if name.startswith(prefix)])
        require(actual == expected,
                f"inherited guard count for {prefix} changed: {actual} != {expected}")
    require(sum(inherited.values()) == 107, "the inherited baseline must stay at 107")
    passed("T-W2-04-17 all 107 inherited guards still ran and still pass unchanged")


async def test_w2_04_concurrency_and_compression(client: httpx.AsyncClient) -> None:
    """T-W2-04-18..20: per-session locking granularity, batch atomicity, compression rev."""
    # ---- 18. different sessions never serialize against each other ---------
    await _w204_reset_tables()
    sid_a, sid_b = "w204-par-a", "w204-par-b"
    await _seed_conversation(sid_a)
    await _seed_conversation(sid_b)
    reached_a = asyncio.Event()
    release_a = asyncio.Event()
    original_status = database._tombstone_status_tx

    async def _hold_a(conn, session_id, *args, **kwargs):
        outcome = await original_status(conn, session_id, *args, **kwargs)
        if session_id == sid_a:
            reached_a.set()
            await release_a.wait()
        return outcome

    with patch.object(database, "_tombstone_status_tx", _hold_a):
        writer_a = asyncio.create_task(
            database.append_turn_events_atomic(sid_a, "u", "a", "m", turn_key="pk"))
        await asyncio.wait_for(reached_a.wait(), timeout=15)
        try:
            # B must finish while A still holds its own session lock.  If ordinary writes
            # took the GLOBAL exclusive lock, or shared one session key, this would hang.
            result_b = await asyncio.wait_for(
                database.append_turn_events_atomic(sid_b, "u", "a", "m", turn_key="pk"),
                timeout=8,
            )
        except asyncio.TimeoutError:
            release_a.set()
            await writer_a
            require(False, "session B blocked behind session A: ordinary writes are over-locking")
        require(result_b.get("ok") is True, f"session B failed while A was held: {result_b}")
        release_a.set()
        await asyncio.wait_for(writer_a, timeout=15)
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM conversations WHERE session_id = $1", sid_b) == 2,
        "session B's turn did not land")
    passed("T-W2-04-18 ordinary writes lock per session, so unrelated sessions never queue")

    # ---- 19. memory batches are atomic and take no outward calls under lock -
    await _w204_reset_tables()
    await _truncate("memories")
    batch_sid = "w204-batch"
    await _seed_conversation(batch_sid, events=[("user", "batch-body", "bk")])
    snapshot = await database.snapshot_recent_conversation(limit=20)
    await _pool_execute(
        """
        CREATE OR REPLACE FUNCTION w204_fail_second_memory() RETURNS trigger AS $fn$
        BEGIN
            IF NEW.content = 'w204-batch-second'
            THEN RAISE EXCEPTION 'W2_04_INJECTED_BATCH_FAILURE'; END IF;
            RETURN NEW;
        END; $fn$ LANGUAGE plpgsql
        """
    )
    await _pool_execute("DROP TRIGGER IF EXISTS w204_fail_second_memory_trg ON memories")
    await _pool_execute(
        "CREATE TRIGGER w204_fail_second_memory_trg BEFORE INSERT ON memories "
        "FOR EACH ROW EXECUTE FUNCTION w204_fail_second_memory()"
    )
    outward_calls = []

    async def _forbidden_outward(*args, **kwargs):
        outward_calls.append("outward")
        raise AssertionError("an outward call was made while holding the save locks")

    async def _save_batch(conn):
        await database._insert_memory_tx(conn, content="w204-batch-first", importance=5,
                                         source_session=batch_sid)
        await database._insert_memory_tx(conn, content="w204-batch-second", importance=5,
                                         source_session=batch_sid)
        return "saved"

    pool = await database.get_pool()
    try:
        with patch.object(database, "get_embedding", _forbidden_outward):
            failed = False
            try:
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await database.save_if_sources_unchanged(conn, snapshot, _save_batch)
            except Exception as exc:
                failed = True
                require("W2_04_INJECTED_BATCH_FAILURE" in str(exc),
                        f"the batch failed for an unexpected reason: {exc}")
        require(failed, "the injected batch failure did not propagate")
        require(not outward_calls, "an embedding call happened inside the locked save")
        require(await _pool_fetchval(
            "SELECT COUNT(*) FROM memories WHERE content LIKE 'w204-batch-%'") == 0,
            "the first memory of a failed batch survived: the batch is not atomic")
        passed("T-W2-04-19 memory batches commit all-or-nothing with no outward calls under lock")
    finally:
        await _pool_execute("DROP TRIGGER IF EXISTS w204_fail_second_memory_trg ON memories")
        await _pool_execute("DROP FUNCTION IF EXISTS w204_fail_second_memory()")

    # ---- 20. compression summaries follow the source revision --------------
    await _w204_reset_tables()
    comp_sid = "w204-comp"
    await _seed_conversation(
        comp_sid,
        messages=[("w204-comp-u1", "user", "u1", "ck1"),
                  ("w204-comp-a1", "assistant", "a1", "ck1"),
                  ("w204-comp-u2", "user", "u2", "ck2")],
        events=[("user", "u1", "ck1"), ("assistant", "a1", "ck1")],
        summaries=1,
    )
    await _seed_divider(comp_sid, "w204-comp-d1", summary="auto-comp")
    await _seed_divider(comp_sid, "w204-comp-h1", summary="handoff-comp", handoff=True)

    conv = await client.get(f"/sync/conversations/{comp_sid}")
    require(conv.status_code == 200, "reading the conversation failed")
    rev_before = conv.json().get("source_rev")
    require(rev_before == 0, f"a untouched conversation must report source_rev 0, got {rev_before}")

    response = await client.delete(f"/sync/conversations/{comp_sid}/messages/w204-comp-a1")
    rev_after = response.json()["source_rev"]
    require(rev_after == rev_before + 1, f"the delete must advance the rev: {rev_before} -> {rev_after}")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM compression_summaries WHERE conversation_id = $1", comp_sid) == 0,
        "the delete must clear the internal compression summaries")
    require(await _pool_fetchval(
        "SELECT EXISTS(SELECT 1 FROM chat_messages WHERE id = 'w204-comp-h1')"),
        "the handoff divider must survive")

    # a summary computed from the pre-delete material is refused
    response = await client.post("/admin/compression-summary", json={
        "conversation_id": comp_sid, "summary": "stale-summary",
        "msg_count": 2, "expected_source_rev": rev_before,
    })
    require(response.status_code == 409 and response.json() == {
        "error": "对话素材已变化", "code": "sources_changed"},
        f"a stale compression summary must be refused with 409: {response.status_code} {response.text}")
    require(await _pool_fetchval(
        "SELECT COUNT(*) FROM compression_summaries WHERE conversation_id = $1", comp_sid) == 0,
        "a refused summary still wrote a row")

    # an auto-compression divider carrying the stale rev is refused the same way
    response = await client.put(f"/sync/conversations/{comp_sid}/messages/w204-comp-d9", json={
        "role": "divider", "content": "", "summary": "stale-divider",
        "summarySourceRev": rev_before,
    })
    require(response.status_code == 409 and response.json().get("code") == "sources_changed",
            f"a stale auto divider must be refused: {response.status_code} {response.text}")
    response = await client.put(f"/sync/conversations/{comp_sid}/messages/w204-comp-d8", json={
        "role": "divider", "content": "", "summary": "no-rev-divider",
    })
    require(response.status_code == 409,
            f"an auto divider without a source rev must be refused: {response.status_code}")

    # recomputing against the current rev works
    response = await client.post("/admin/compression-summary", json={
        "conversation_id": comp_sid, "summary": "fresh-summary",
        "msg_count": 1, "expected_source_rev": rev_after,
    })
    require(response.status_code == 200,
            f"a summary at the current rev must be accepted: {response.status_code} {response.text}")

    # once the conversation itself is gone, both channels are 410
    await client.delete(f"/sync/conversations/{comp_sid}")
    response = await client.post("/admin/compression-summary", json={
        "conversation_id": comp_sid, "summary": "after-delete",
        "msg_count": 1, "expected_source_rev": rev_after + 1,
    })
    require(response.status_code == 410, f"summaries for a deleted conversation must be 410: {response.status_code}")
    response = await client.put(f"/sync/conversations/{comp_sid}/messages/w204-comp-d7", json={
        "role": "divider", "content": "", "summary": "after-delete", "summarySourceRev": rev_after + 1,
    })
    require(response.status_code == 410, f"dividers for a deleted conversation must be 410: {response.status_code}")
    passed("T-W2-04-20 compression copies are purged, version-gated, and dead after deletion")


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
        await test_w2_03_schema_and_atomic()
        await test_w2_03_scope_and_order()
        await test_w2_03_entry_and_panel(client)
        await test_w2_03_chat_paths(client)
        await test_w2_04_schema_and_conversation_delete(client)
        await test_w2_04_message_delete_and_ledger(client)
        await test_w2_04_no_resurrection(client)
        await test_w2_04_background_snapshots(client)
        await test_w2_04_privacy_and_contracts(client)
        await test_w2_04_concurrency_and_compression(client)


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
        w2_03_passed = [name for name in PASSED if name.startswith("T-W2-03-")]
        w2_04_passed = [name for name in PASSED if name.startswith("T-W2-04-")]
        print(f"\nPASS: {len(legacy_passed)} permanent S1-S6 behavior guards")
        print(f"PASS: {len(w1_01_passed)} W1-01 isolation/permanent guards")
        print(f"PASS: {len(w1_06_passed)} W1-06 calendar-delete atomicity guards")
        print(f"PASS: {len(w1_08_passed)} W1-08 calendar-period guards")
        print(f"PASS: {len(w2_01_passed)} W2-01 granular-sync guards")
        print(f"PASS: {len(w2_02_passed)} W2-02 message-identity/atomic-import guards")
        print(f"PASS: {len(w2_03_passed)} W2-03 ledger-schema/scope/dark-write guards")
        print(f"PASS: {len(w2_04_passed)} W2-04 session-delete/privacy guards")
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
