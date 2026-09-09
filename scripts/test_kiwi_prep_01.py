#!/usr/bin/env python3
"""PREP-01 application guards; real FastMCP, fake observation database only.

No application lifespan, background jobs, model calls or external database.
The real PostgreSQL storage guard lives in test_kiwi_safety_sync.py.
Script/update guards T-06..10 and delivery guards T-11..12 follow in stage B.
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import asynccontextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Never inherit a developer's database/provider configuration.
os.environ["DATABASE_URL"] = "postgresql://unused:unused@127.0.0.1:1/unused"
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {},
    "clientInfo": {"name": "prep-test", "version": "1.7.0"}}}
HEADERS = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}
KEYS = {"protection", "hosts_registered", "origins_registered", "hosts_invalid",
        "origins_invalid", "ip_literal_allowed", "foreign_host_seen",
        "foreign_host_last_seen_at", "version"}
SENTINEL = "SENTINEL-host-7f3a.example"


class ObservationDB:
    """SQL boundary fake; records every argument so leak assertions cover writes."""
    def __init__(self):
        self.row = None
        self.calls = []
        self.broken = False

    def acquire(self):
        return self

    async def __aenter__(self):
        if self.broken:
            raise RuntimeError(SENTINEL)
        return self

    async def __aexit__(self, *_):
        pass

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        if "mcp_access_observation" in sql and "INSERT" in sql.upper():
            self.row = {"id": 1, "foreign_host_seen": True,
                        "last_seen_at": datetime.now(timezone.utc)}
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self.row

    async def fetch(self, sql, *args):
        row = await self.fetchrow(sql, *args)
        return [] if row is None else [row]

    async def pool(self):
        if self.broken:
            raise RuntimeError(SENTINEL)
        return self


class ApplicationGuards(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.output))
        self.enterContext(patch.dict(os.environ, {
            "MCP_ALLOWED_HOSTS": "", "MCP_ALLOWED_ORIGINS": ""}))
        self.db = ObservationDB()
        import database
        self.enterContext(patch.object(database, "get_pool", self.db.pool))

    def module(self):
        # Missing implementation is an assertion failure, never ImportError red.
        self.assertIsNotNone(importlib.util.find_spec("mcp_access"),
                             "PREP observation implementation is missing")
        module = importlib.import_module("mcp_access")
        module = importlib.reload(module)  # isolate the per-process write throttle
        if hasattr(module, "get_pool"):
            self.enterContext(patch.object(module, "get_pool", self.db.pool))
        return module

    def client(self, prefix, wrapper=None):
        # Real SDK and its real session manager. Only persistence is replaced.
        sdk = FastMCP("PREP test", stateless_http=True)
        child = sdk.streamable_http_app()

        @asynccontextmanager
        async def lifespan(app):
            async with sdk.session_manager.run():
                yield

        app = FastAPI(lifespan=lifespan)
        app.mount(prefix, wrapper(child) if wrapper else child)
        return TestClient(app)

    def no_values(self, *values):
        evidence = self.output.getvalue() + json.dumps(
            {"row": self.db.row, "calls": self.db.calls}, default=str)
        for value in values:
            self.assertNotIn(value, evidence)

    def test_T_PREP_01_01_status_shape(self):
        self.module()
        import main
        env = {"MCP_ALLOWED_HOSTS": "a.example, b.example:*, bad item, *.evil, ",
               "MCP_ALLOWED_ORIGINS": "https://a.example, https://b.example:*, null, *"}
        with patch.dict(os.environ, env):
            # No context manager: do not start the main application lifespan.
            client = TestClient(main.app)
            self.addCleanup(client.close)
            response = client.get("/admin/mcp-access-status")
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(set(result), KEYS)
            for key in ("hosts_registered", "origins_registered", "hosts_invalid", "origins_invalid"):
                self.assertIs(type(result[key]), int)
                self.assertEqual(result[key], 2)
            self.assertEqual(result["protection"], "preview")
            self.assertEqual(result["version"], "1.7.0")
            self.assertIs(result["ip_literal_allowed"], True)
            self.assertIs(result["foreign_host_seen"], False)
            self.assertIsNone(result["foreign_host_last_seen_at"])
            for value in ("a.example", "b.example", "*.evil"):
                self.assertNotIn(value, response.text)
            self.no_values("a.example", "b.example", "*.evil")
            self.db.broken = True
            failed = client.get("/admin/mcp-access-status")
            self.assertEqual(failed.status_code, 500)
            self.assertEqual(failed.json(), {"error": "internal_error", "error_code": "internal_error"})
            self.no_values(SENTINEL)

    def test_T_PREP_01_02_observation(self):
        module = self.module()
        wrapper = getattr(module, "observe_mcp_access", None)
        self.assertTrue(callable(wrapper), "observe_mcp_access must exist")
        with self.client("/memory", wrapper) as client:
            for host in ("localhost:8080", "127.0.0.1:8080", "[::1]:8080",
                         "192.168.1.10:8080", "[2001:db8::1]:8080"):
                with self.subTest(host_kind=host.split(":")[0]):
                    response = client.post("/memory/mcp", json=INIT,
                                           headers={**HEADERS, "Host": host})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('"result"', response.text)
                    self.assertIsNone(self.db.row)
            for _ in range(3):
                response = client.post("/memory/mcp", json=INIT,
                                       headers={**HEADERS, "Host": SENTINEL + ":443"})
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(SENTINEL, response.text)
            self.assertIsNotNone(self.db.row, "foreign access must be observed")
            self.assertIs(self.db.row["foreign_host_seen"], True)
            self.assertIsInstance(self.db.row["last_seen_at"], datetime)
            writes = [sql for sql, _ in self.db.calls if "INSERT" in sql.upper()]
            self.assertEqual(len(writes), 1, "at most one observation write per 60 seconds")
            self.no_values(SENTINEL)

    def test_T_PREP_01_03_passthrough(self):
        module = self.module()
        wrapper = getattr(module, "observe_mcp_access", None)
        self.assertTrue(callable(wrapper), "observe_mcp_access must exist")
        for prefix in ("/memory", "/calendar"):
            for body in (json.dumps(INIT), "{broken"):
                with self.subTest(prefix=prefix, valid=body != "{broken"):
                    with self.client(prefix) as baseline:
                        before = baseline.post(prefix + "/mcp", content=body, headers=HEADERS)
                    with self.client(prefix, wrapper) as guarded:
                        after = guarded.post(prefix + "/mcp", content=body, headers=HEADERS)
                    self.assertEqual(after.status_code, before.status_code)
                    self.assertEqual(list(after.headers.multi_items()), list(before.headers.multi_items()))
                    self.assertEqual(after.content, before.content)
        # A failed observation store must also leave the protocol available.
        self.db.broken = True
        with self.client("/memory", wrapper) as client:
            response = client.post("/memory/mcp", json=INIT,
                                   headers={**HEADERS, "Host": SENTINEL})
            self.assertEqual(response.status_code, 200)
            self.assertIn('"result"', response.text)
        self.no_values(SENTINEL)

    def test_T_PREP_01_05_startup(self):
        module = self.module()
        preview = getattr(module, "log_mcp_access_preview", None)
        self.assertTrue(callable(preview), "startup preview entrypoint must exist")
        preview()
        self.assertIn("event=mcp_allowlist_preview hosts=0 origins=0 increment=1", self.output.getvalue())
        self.assertIn("MCP_ALLOWED_HOSTS", self.output.getvalue())
        self.output.seek(0)
        self.output.truncate()
        with patch.dict(os.environ, {"MCP_ALLOWED_HOSTS": "a.example, bad item",
                                    "MCP_ALLOWED_ORIGINS": "https://b.example, null"}):
            preview()
        self.assertIn("event=mcp_allowlist_preview hosts=1 origins=1 increment=1", self.output.getvalue())
        for field in ("hosts", "origins"):
            self.assertEqual(self.output.getvalue().count(
                f"event=mcp_allowlist_invalid_item field={field} increment=1"), 1)
        self.no_values("a.example", "b.example", "bad item", "null")


if __name__ == "__main__":
    unittest.main(verbosity=2)
