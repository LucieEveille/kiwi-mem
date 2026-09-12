#!/usr/bin/env python3
"""SEC-01b: actual main router and SDK; fake persistence, no background jobs.

T-03/04/09/10 preserve behavior already available on the baseline. T-09 uses
the real streamable HTTP client, whose initialize/list_tools use POST.
PREP T-12 and BUILD T-10 share assert_exact_mcp_routes from this module.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import io
import json
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from contextlib import asynccontextmanager, redirect_stdout, redirect_stderr
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
os.environ['DATABASE_URL'] = 'postgresql://unused:unused@127.0.0.1:1/unused'
from test_kiwi_prep_01 import ObservationDB, INIT

PATHS = ('/memory/mcp', '/calendar/mcp')
FACTORIES = ('get_memory_mcp_endpoint', 'get_calendar_mcp_endpoint')
NAMES = ('Memory Garden', 'Calendar & Dream')
TOOLS = (
    {'search_memory', 'save_memory', 'get_recent', 'trigger_digest', 'lock_memory', 'unlock_memory'},
    {'get_day_page', 'get_calendar_range', 'save_calendar_page', 'get_comments',
     'add_comment', 'get_user_profile', 'trigger_dream', 'stop_dream',
     'get_dream_status', 'get_dream_history', 'get_dream_scenes'},
)
SENTINELS = ('SEC1B-7f91-host.example', 'https://SEC1B-89ab-origin.example',
             'SEC1B-1c54-content-type')


def assert_exact_mcp_routes(case, tree):
    """Check explicit calls or the contract's constant tuple loop, including bindings."""
    mounts = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == 'mount'
              and n.args and isinstance(n.args[0], ast.Constant)
              and n.args[0].value in ('/memory', '/calendar')]
    case.assertEqual(len(mounts), 0, 'broad MCP mounts must be removed')
    found = []

    def inspect_call(call, bindings):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name) and call.func.value.id == 'app'
                and call.func.attr == 'add_route' and len(call.args) >= 2):
            return
        def resolve(node):
            return bindings.get(node.id, node) if isinstance(node, ast.Name) else node
        path = resolve(call.args[0])
        if not isinstance(path, ast.Constant) or path.value not in PATHS:
            return
        endpoint = call.args[1]
        for layer in ('AsgiEndpoint', 'observe_mcp_access', 'guard_mcp_access'):
            case.assertIsInstance(endpoint, ast.Call)
            case.assertEqual(getattr(endpoint.func, 'id', None), layer)
            case.assertEqual(len(endpoint.args), 2 if layer == 'guard_mcp_access' else 1)
            if layer == 'guard_mcp_access':
                case.assertEqual(ast.dump(endpoint.args[1]), ast.dump(ast.Name(id='_SECURITY', ctx=ast.Load())))
            endpoint = resolve(endpoint.args[0])
        case.assertIsInstance(endpoint, ast.Call)
        case.assertEqual(getattr(endpoint.func, 'id', None), FACTORIES[PATHS.index(path.value)])
        methods = next((k.value for k in call.keywords if k.arg == 'methods'), None)
        case.assertTrue(methods is None or isinstance(methods, ast.Constant) and methods.value is None)
        found.append(path.value)

    for node in tree.body:
        if isinstance(node, ast.For) and isinstance(node.target, (ast.Tuple, ast.List)):
            case.assertIsInstance(node.iter, (ast.Tuple, ast.List))
            for row in node.iter.elts:
                case.assertIsInstance(row, (ast.Tuple, ast.List))
                bindings = {key.id: value for key, value in zip(node.target.elts, row.elts)}
                for child in ast.walk(node):
                    inspect_call(child, bindings)
        elif isinstance(node, ast.Expr):
            inspect_call(node.value, {})
    case.assertCountEqual(found, PATHS, 'two exact MCP routes must be registered')


class MountGuards(unittest.TestCase):
    def setUp(self):
        self.console, self.logs = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.console))
        self.enterContext(redirect_stderr(self.console))
        for logger in (logging.getLogger(), logging.getLogger('mcp')):
            handler = logging.StreamHandler(self.logs)
            level = logger.level
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
            self.addCleanup(logger.removeHandler, handler)
            self.addCleanup(logger.setLevel, level)
        self.enterContext(patch.dict(os.environ, {
            'MCP_ALLOWED_HOSTS': 'reg.example:*', 'MCP_ALLOWED_ORIGINS': ''}))
        self.db = ObservationDB()
        import database
        self.database = database
        self.enterContext(patch.object(database, 'get_pool', self.db.pool))
        self.access = importlib.reload(importlib.import_module('mcp_access'))
        self.enterContext(patch.object(self.access, 'get_pool', self.db.pool))
        if 'mcp_server' in sys.modules:
            importlib.reload(sys.modules['mcp_server'])
        if 'main' in sys.modules:
            self.main = importlib.reload(sys.modules['main'])
        else:
            self.main = importlib.import_module('main')

    @asynccontextmanager
    async def lifespan(self, app=None):
        async with self.main.mcp_memory.session_manager.run():
            async with self.main.mcp_calendar.session_manager.run():
                yield

    async def request(self, method, url, *, host='127.0.0.1:8080',
                      accept='application/json, text/event-stream', origin=None,
                      content_type='application/json'):
        parsed = urlsplit(url)
        headers = [(b'host', host.encode('ascii')), (b'accept', accept.encode('ascii')),
                   (b'content-type', content_type.encode('ascii'))]
        if origin is not None:
            headers.append((b'origin', origin.encode('ascii')))
        scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
                 'http_version': '1.1', 'method': method, 'scheme': 'http',
                 'path': parsed.path, 'raw_path': parsed.path.encode('ascii'),
                 'root_path': '', 'query_string': parsed.query.encode('ascii'),
                 'headers': headers, 'server': ('127.0.0.1', 8080),
                 'client': ('127.0.0.1', 12345)}
        messages, sent = [], False
        disconnect = asyncio.Event()
        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {'type': 'http.request', 'body': json.dumps(INIT).encode() if method == 'POST' else b'',
                        'more_body': False}
            await disconnect.wait()
            return {'type': 'http.disconnect'}
        async def send(message):
            messages.append(message.copy())
            # Stateless GET SSE is intentionally open. Disconnect only once
            # the real app has sent its response headers; never wait unbounded.
            if method == 'GET' and message['type'] == 'http.response.start':
                if b'text/event-stream' in dict(message['headers']).get(b'content-type', b''):
                    disconnect.set()
        try:
            await asyncio.wait_for(self.main.app(scope, receive, send), 5)
        except Exception:
            # Like TestClient(raise_server_exceptions=False), retain an actual
            # HTTP 500 emitted by ServerErrorMiddleware (K-07). Setup failures
            # and timeouts without a response must still surface as errors.
            if not any(m['type'] == 'http.response.start' and m['status'] == 500 for m in messages):
                raise
        start = next(m for m in messages if m['type'] == 'http.response.start')
        body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
        return start['status'], dict(start['headers']), body

    def run_requests(self, requests):
        async def run():
            async with self.lifespan():
                return [await self.request(*args, **kwargs) for args, kwargs in requests]
        return asyncio.run(run())

    def payload(self, body):
        try:
            if body.startswith(b'event:') or body.startswith(b'data:'):
                return json.loads(next(line[5:].strip() for line in body.splitlines() if line.startswith(b'data:')))
            return json.loads(body)
        except (ValueError, StopIteration):
            self.fail('response must contain the expected JSON or SSE JSON payload')

    def test_T_SEC_01b_01_routes(self):
        from fastapi.routing import APIRoute
        from starlette.routing import Mount, Route
        routes = self.main.app.router.routes
        with self.subTest(arm='runtime'):
            exact = [(i, r) for i, r in enumerate(routes) if r.path in PATHS]
            self.assertEqual(len(exact), 2, 'exact MCP routes are missing')
            business = [i for i, r in enumerate(routes) if isinstance(r, APIRoute)]
            for i, route in exact:
                self.assertIs(type(route), Route)
                self.assertIsNone(route.methods)
                self.assertLess(i, min(business))
            self.assertFalse(any(isinstance(r, Mount) and r.path in ('/memory', '/calendar') for r in routes))
        with self.subTest(arm='ast'):
            assert_exact_mcp_routes(self, ast.parse((ROOT / 'main.py').read_text(encoding='utf-8')))

    def test_T_SEC_01b_02_get(self):
        page = AsyncMock(return_value=None)
        with patch.object(self.database, 'get_calendar_page', page):
            items = [(('GET', path), {'accept': accept}) for path in PATHS
                     for accept in ('text/event-stream', 'application/json')]
            results = self.run_requests(items)
        for ((_, path), options), (status, headers, _) in zip(items, results):
            with self.subTest(path=path, accept=options['accept']):
                sse = options['accept'] == 'text/event-stream'
                self.assertEqual(status, 200 if sse else 406)
                if sse:
                    self.assertIn(b'text/event-stream', headers[b'content-type'])
        self.assertEqual(page.call_args_list, [], 'MCP GET must never call calendar business handler')

    def test_T_SEC_01b_03_initialize(self):
        results = self.run_requests([(('POST', path), {}) for path in PATHS])
        for name, (status, _, body) in zip(NAMES, results):
            with self.subTest(instance=name):
                self.assertEqual(status, 200)
                self.assertEqual(self.payload(body)['result']['serverInfo']['name'], name)

    def test_T_SEC_01b_04_delete(self):
        for status, _, body in self.run_requests([(('DELETE', path), {}) for path in PATHS]):
            self.assertEqual(status, 405)
            payload = self.payload(body)
            self.assertIn('error', payload, 'DELETE must reach the SDK JSON-RPC error response')
            self.assertEqual(payload['error']['code'], -32600)

    def test_T_SEC_01b_05_redirect(self):
        items = [((method, path + '/'), {'host': host}) for path in PATHS
                 for host in ('127.0.0.1:8080', 'reg.example:8080') for method in ('GET', 'POST', 'DELETE')]
        for ((method, path), options), (status, headers, _) in zip(items, self.run_requests(items)):
            with self.subTest(method=method, path=path, host=options['host']):
                self.assertEqual(status, 307)
                self.assertEqual(headers[b'location'].decode(), 'http://' + options['host'] + path[:-1])

    def test_T_SEC_01b_06_non_endpoints(self):
        items = [((method, path), {'host': SENTINELS[0]})
                 for path in ('/memory', '/memory/', '/memory/mcp/extra', '/calendar/mcp/extra')
                 for method in ('GET', 'POST', 'DELETE')]
        for ((method, path), _), (status, _, _) in zip(items, self.run_requests(items)):
            with self.subTest(method=method, path=path):
                self.assertEqual(status, 404)
        with self.subTest(arm='zero_observation'):
            self.assertEqual(self.db.calls, [])
        self.assertNotIn('event=mcp_access_rejected', self.logs.getvalue())

    def test_T_SEC_01b_07_calendar(self):
        page, span = AsyncMock(return_value=None), AsyncMock(return_value=[])
        items = [(('GET', '/calendar?start=2026-09-01&end=2026-09-12&type=day'), {}),
                 (('GET', '/calendar/2026-09-12'), {}),
                 (('POST', '/calendar/2026-09-12'), {}), (('DELETE', '/calendar/2026-09-12'), {})]
        with patch.object(self.database, 'get_calendar_page', page), patch.object(self.database, 'get_calendar_range', span):
            results = self.run_requests(items)
        span.assert_awaited_once_with('2026-09-01', '2026-09-12', 'day')
        page.assert_awaited_once_with('2026-09-12', 'day')
        self.assertEqual(results[0][0], 200)
        self.assertEqual(self.payload(results[0][2]), {'status': 'ok', 'pages': [], 'count': 0})
        self.assertEqual(results[1][0], 200)
        self.assertEqual(self.payload(results[1][2]), {'status': 'ok', 'page': None})
        for result in results[2:]:
            with self.subTest(status=result[0]):
                self.assertEqual(result[0], 405)

    def test_T_SEC_01b_08_layers(self):
        with self.subTest(arm='ast'):
            assert_exact_mcp_routes(self, ast.parse((ROOT / 'main.py').read_text(encoding='utf-8')))
        items = [(('POST', path), opts) for path in PATHS for opts in (
            {'host': SENTINELS[0]}, {'origin': SENTINELS[1]}, {'content_type': SENTINELS[2]})]
        results = self.run_requests(items)
        for i, (status, _, body) in enumerate(results):
            with self.subTest(request=i):
                expected = (421, 403, 400)[i % 3]
                code = ('mcp_host_not_allowed', 'mcp_origin_not_allowed', 'invalid_content_type')[i % 3]
                self.assertEqual(status, expected)
                self.assertEqual(self.payload(body)['error_code'], code)
        self.assertIsNotNone(self.db.row, 'outer observation must record rejected foreign Host')
        evidence = self.console.getvalue() + self.logs.getvalue() + repr(self.db.calls) + repr(self.db.row) + repr(results)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, evidence)

    def test_T_SEC_01b_09_real_client(self):
        import uvicorn
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(self.main.app, log_level='error', lifespan='on', timeout_graceful_shutdown=1))
        async def clients():
            result = []
            for path in PATHS:
                async with streamablehttp_client(f'http://127.0.0.1:{port}{path}') as (read, write, _):
                    async with ClientSession(read, write) as session:
                        hello = await session.initialize()
                        tools = await session.list_tools()
                        result.append((hello.serverInfo.name, {tool.name for tool in tools.tools}))
            return result
        with patch.object(self.main.app.router, 'lifespan_context', self.lifespan):
            thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(server.started, 'real main uvicorn failed to start')
                self.assertEqual(asyncio.run(asyncio.wait_for(clients(), 10)), list(zip(NAMES, TOOLS)))
            finally:
                server.should_exit = True
                thread.join(5)
                sock.close()
                self.assertFalse(thread.is_alive(), 'real main uvicorn failed to stop')

    def test_T_SEC_01b_10_unused_token(self):
        paths = [p for p in ROOT.rglob('*.py') if '.git' not in p.parts and '__pycache__' not in p.parts]
        paths += [ROOT / '.env.example', ROOT / 'docker-compose.yml']
        paths += [p for p in (ROOT / '.github').rglob('*') if p.is_file()]
        token = 'MCP_' + 'AUTH_TOKEN'  # do not count this guard's own sentinel
        self.assertEqual([str(p.relative_to(ROOT)) for p in paths
                          if token in p.read_text(encoding='utf-8')], [])

    def test_T_SEC_01b_11_lifespan_factories(self):
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        lifespan = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'lifespan')
        calls = [ast.unparse(n) for n in ast.walk(lifespan) if isinstance(n, ast.Call)
                 and ast.unparse(n.func).endswith('.session_manager.run')]
        self.assertCountEqual(calls, ['mcp_memory.session_manager.run()', 'mcp_calendar.session_manager.run()'])
        sdk = importlib.reload(sys.modules['mcp_server'])
        for factory, server in zip(FACTORIES, (sdk.mcp_memory, sdk.mcp_calendar)):
            with self.subTest(factory=factory):
                build = getattr(sdk, factory, None)
                self.assertTrue(callable(build), factory + ' is missing')
                endpoint = build()
                self.assertTrue(callable(endpoint))
                try:
                    manager = server.session_manager
                except RuntimeError as exc:
                    self.fail('factory must warm up its session manager: ' + str(exc))
                self.assertIsNotNone(manager)

    def test_T_SEC_01b_12_docs(self):
        doc = (ROOT / 'docs/mcp-transport-security.md').read_text(encoding='utf-8')
        for text in ('挂载与路径', '/calendar/mcp/', '/memory/mcp/extra'):
            with self.subTest(required=text):
                self.assertIn(text, doc)
        with self.subTest(doc='upgrade'):
            self.assertNotIn('不宣称 /calendar/mcp', (ROOT / 'docs/UPGRADING.md').read_text(encoding='utf-8'))
        with self.subTest(doc='known_issues'):
            self.assertNotIn('外部路由修复归 SEC-01b', (ROOT / 'KNOWN_ISSUES.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
