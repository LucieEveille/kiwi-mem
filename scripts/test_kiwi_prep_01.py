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
import logging
import ast
import shutil
import subprocess
import tempfile
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
        self.log_output = io.StringIO()
        for logger in (logging.getLogger(), logging.getLogger("mcp")):
            handler = logging.StreamHandler(self.log_output)
            old_level = logger.level
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
            self.addCleanup(logger.removeHandler, handler)
            self.addCleanup(logger.setLevel, old_level)
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
        evidence = self.output.getvalue() + self.log_output.getvalue() + json.dumps(
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
        import main

        @asynccontextmanager
        async def protocol_lifespan(app):
            # Actual production mount; omit database initialization/schedulers only.
            async with main.mcp_memory.session_manager.run():
                async with main.mcp_calendar.session_manager.run():
                    yield

        with patch.object(main.app.router, 'lifespan_context', protocol_lifespan), TestClient(main.app) as client:
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

        for host in ("", "[SENTINEL-malformed-7f3a", "bad host"):
            with self.subTest(malformed=bool(host)):
                self.db.row = None
                self.db.calls.clear()
                module = self.module()
                with self.client("/memory", module.observe_mcp_access) as client:
                    response = client.post("/memory/mcp", json=INIT,
                                           headers={**HEADERS, "Host": host})
                    self.assertEqual(response.status_code, 200)
                self.assertIsNotNone(self.db.row, "malformed/empty Host must count foreign")
                self.assertIs(self.db.row["foreign_host_seen"], True)
                self.no_values("SENTINEL-malformed-7f3a", "bad host")


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
        module._next_write = 0
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
                                    "MCP_ALLOWED_ORIGINS": "https://b.example, SENTINEL-invalid-origin"}):
            preview()
        self.assertIn("event=mcp_allowlist_preview hosts=1 origins=1 increment=1", self.output.getvalue())
        for field in ("hosts", "origins"):
            self.assertEqual(self.output.getvalue().count(
                f"event=mcp_allowlist_invalid_item field={field} increment=1"), 1)
        self.no_values("a.example", "b.example", "bad item", "SENTINEL-invalid-origin")


from prep_update_fixture import UpdateFixture


class UpdateGuards(unittest.TestCase):
    def fixture(self, **control):
        f = UpdateFixture(**control)
        self.addCleanup(f.close)
        return f

    @unittest.skipIf(os.name == 'nt', 'minimal POSIX PATH matrix runs in Linux CI')
    def test_fallback_runtime_paths(self):
        from mcp_access import valid_host
        values=['x.example','x.example:*','localhost','127.0.0.1','[::1]',
                '[::1]:8080','[2001:db8::1]:*','[::ffff:192.0.2.1]',
                '[::ffff:01.2.3.4]','[:::]','[1:2:3:4:5:6:7:8:9]',
                'x:0','x:65535','x:65536','x:','*.evil','bad host',
                'https://example.com','user@host','host/path','host.','host..','']
        checked=subprocess.run(['jq','-c','-L',str(ROOT/'scripts'),
                'include "prep_authority"; map(validhost)'],input=json.dumps(values),
                capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(checked.stdout),[bool(valid_host(v)) for v in values])
        for python, http in ((False,'curl'),(False,'wget'),(True,'wget')):
            with self.subTest(python=python,http=http):
                f=self.fixture(compose_fail=True)
                f.restrict_runtime(python=python,http=http)
                target=f.target(True,True)
                sentinel=f.root/'PWNED'
                (f.repo/'.env').write_text('MCP_ALLOWED_HOSTS=$(touch "'+sentinel.as_posix()+'")\n')
                r=f.run('--auto')
                self.assertEqual(r.returncode,3,r.stdout)
                self.assertFalse(sentinel.exists())
                self.assertEqual(f.head(),f.prev)
                (f.repo/'.env').write_text('MCP_ALLOWED_HOSTS="[2001:db8::1]:*"\r\n')
                r=f.run('--auto')
                self.assertEqual(r.returncode,0,r.stdout)
                self.assertEqual(f.head(),target)
                self.assertEqual((f.root/'executed').read_text().splitlines(),['new-script'])
                self.assertEqual(sum(c[1][:2]==['compose','exec'] for c in f.calls()),1)
                self.assertFalse((f.repo/'.update-state.json').exists())
                calls=[c[1] for c in f.calls(http) if any(x.endswith('/memory/mcp') for x in c[1])]
                self.assertEqual(len(calls),1)
                self.assertIn('--max-time' if http=='curl' else '-T',calls[0])
                self.assertTrue(any('initialize' in x for x in calls[0]))
                f=self.fixture(foreign=False,mcp_code=405)
                f.restrict_runtime(python=python,http=http)
                f.target(False,True)
                r=f.run('--auto')
                self.assertEqual(r.returncode,1,r.stdout)
                self.assertEqual(f.head(),f.prev)
                self.assertFalse((f.repo/'.update-state.json').exists())

    def test_T_PREP_01_06_three_conditions(self):
        f = self.fixture(); f.target()
        r = f.run('--auto')
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn('MCP_ALLOWED_HOSTS', r.stdout)
        self.assertEqual(f.head(), f.prev)
        self.assertTrue(all(c[1][:2] in (['compose','version'],['compose','config']) for c in f.calls()))
        for args, reply, expected in [((), 'n\n', False), ((), 'y\ny\n', True)]:
            f = self.fixture(); target = f.target()
            r = f.run(*args, input=reply)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertEqual(f.head(), target if expected else f.prev)
        for control, gate in [({'status_code':0},True),({'foreign':False},True),({},False),({},None),({'status_body':'not json'},True)]:
            f = self.fixture(**control); target=f.target(gate)
            r=f.run('--auto'); self.assertEqual(r.returncode,0,r.stdout); self.assertEqual(f.head(),target)

    def test_T_PREP_01_07_configuration(self):
        for control, env, shell in [({'hosts':'x.example'},'',None),({'compose_fail':True},'MCP_ALLOWED_HOSTS="y.example"\r\n',None),({'compose_fail':True},'MCP_ALLOWED_HOSTS=\n','z.example')]:
            f=self.fixture(**control); target=f.target()
            (f.repo/'.env').write_text(env)
            if shell is not None: f.env['MCP_ALLOWED_HOSTS']=shell
            r=f.run('--auto'); self.assertEqual(r.returncode,0,r.stdout); self.assertEqual(f.head(),target)
        f=self.fixture(compose_fail=True); f.target()
        sentinel=f.root/'PWNED'
        (f.repo/'.env').write_text('MCP_ALLOWED_HOSTS=$(touch "'+sentinel.as_posix()+'")\n')
        r=f.run('--auto')
        self.assertFalse(sentinel.exists(), 'dotenv was executed')
        self.assertEqual(r.returncode,3,r.stdout)
        # Real user flow: change only pending dotenv, then retry.
        (f.repo/'.env').write_text('MCP_ALLOWED_HOSTS=wrong-but-valid.example\n')
        r=f.run('--auto'); self.assertEqual(r.returncode,0,r.stdout)
        self.assertNotIn('wrong-but-valid.example',r.stdout)

    def test_T_PREP_01_08_preflight_before_mutation(self):
        f=self.fixture(); f.target()
        r=f.run('--auto')
        self.assertEqual(r.returncode,3,r.stdout)
        self.assertEqual(f.head(),f.prev)
        self.assertFalse((f.repo/'.update-state.json').exists())
        self.assertFalse((f.repo/'backups').exists())
        self.assertTrue(all(c[1][:2] in (['compose','version'],['compose','config']) for c in f.calls()))

    def test_T_PREP_01_09_resume(self):
        for broken in (False,True):
            f=self.fixture(foreign=False,root_fail=broken); target=f.target(False,True)
            r=f.run(input='y\n')
            self.assertEqual(r.returncode,1 if broken else 0,r.stdout)
            self.assertEqual(f.head(),f.prev if broken else target)
            marker=f.root/'executed'
            self.assertTrue(marker.exists(),'updated script must execute')
            self.assertEqual(marker.read_text(encoding='utf-8').splitlines(),['new-script'])
            calls=f.calls(); builds=[c for c in calls if c[1][:2]==['compose','up']]
            self.assertEqual(len(builds),2 if broken else 1)
            self.assertEqual(builds[0][2],target)
            if broken: self.assertEqual(builds[-1][2],f.prev)
            self.assertEqual(sum(c[1][:2]==['compose','exec'] for c in calls),1)
            self.assertEqual(r.stdout.count('现在更新吗'),1)
            self.assertFalse((f.repo/'.update-state.json').exists())
        f=self.fixture(); f.target(False,True)
        r=f.run('--check'); self.assertEqual(r.returncode,0,r.stdout)
        self.assertEqual(f.head(),f.prev); self.assertEqual(f.calls(),[])

    def test_T_PREP_01_10_initialize_probe(self):
        for code in (200,405,0):
            f=self.fixture(foreign=False,mcp_code=code); target=f.target(False)
            r=f.run('--auto')
            self.assertEqual(r.returncode,0 if code==200 else 1,r.stdout)
            self.assertEqual(f.head(),target if code==200 else f.prev)
            calls=[c[1] for c in f.calls('curl') if any(x.endswith('/memory/mcp') for x in c[1])]
            self.assertEqual(len(calls),1,'must issue exactly one bounded MCP initialize')
            args=calls[0]
            self.assertIn('POST',args); self.assertIn('--max-time',args)
            self.assertEqual(args[args.index('--max-time')+1],'5')
            self.assertIn('Accept: application/json, text/event-stream',args)
            self.assertTrue(any('"initialize"' in x for x in args))


class DeliveryGuards(unittest.TestCase):
    def test_T_PREP_01_11_delivery_contract(self):
        for path, tokens in {
            'docs/UPGRADING.md':['不改变任何访问行为','不支持 SSE','up -d --build','${ZEABUR_WEB_DOMAIN}','CVE-2025-66416','CVE-2026-52869','CVE-2026-59950','BUILD-01'],
            'CHANGELOG.md':['1.7.0','CVE-2026-59950'],
            'README.md':['不支持流式与 MCP'], 'README_EN.md':['2.0 notice'],
            '.env.example':['MCP_ALLOWED_HOSTS','MCP_ALLOWED_ORIGINS'],
            'docker-compose.yml':['MCP_ALLOWED_HOSTS','MCP_ALLOWED_ORIGINS'],
            'requirements.txt':['fastapi==0.141.1','starlette==1.3.1','mcp>=1.8.0','httpx==0.27.0','uvicorn==0.30.0'],
        }.items():
            with self.subTest(file=path):
                self.assertTrue((ROOT/path).exists(),path+' missing')
                text=(ROOT/path).read_text(encoding='utf-8')
                for token in tokens: self.assertIn(token,text)
        p=ROOT/'scripts/upgrade_gates.json'; self.assertTrue(p.exists())
        self.assertIs(json.loads(p.read_text(encoding='utf-8'))['gates']['mcp_access_control'],False)
        text=(ROOT/'main.py').read_text(encoding='utf-8')
        self.assertIn('VERSION = "1.7.0"',text); self.assertIn('version="1.7.0"',text)
        # Frozen blob from 98e7d5c, also works in CI's shallow checkout.
        content=(ROOT/'mcp_server.py').read_bytes().replace(b'\r\n',b'\n')
        blob=subprocess.check_output(['git','hash-object','--stdin'],input=content,cwd=ROOT).decode().strip()
        self.assertEqual(blob,'bc7c1892a21b719b5733bfae9ec3cf69cb0b719f')

    def test_T_PREP_01_12_no_protection_wiring(self):
        self.assertFalse((ROOT/'security.py').exists())
        for p in ROOT.glob('*.py'):
            tree=ast.parse(p.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node,(ast.Import,ast.ImportFrom)):
                    names=[a.name for a in node.names]+[getattr(node,'module','') or '']
                    self.assertFalse(any('transport_security' in n or 'TransportSecuritySettings' in n for n in names),str(p))
                if isinstance(node,ast.Call):
                    self.assertFalse(any(k.arg=='transport_security' for k in node.keywords),str(p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
