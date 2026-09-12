#!/usr/bin/env python3
"""BUILD-01: real SDK transport, fake observation DB, no provider/production calls.

Direct ASGI calls preserve missing/duplicate/raw headers. T-07 additionally uses
a recording downstream for scope identity; that does not replace SDK proof.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import importlib
import importlib.metadata
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
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DATABASE_URL'] = 'postgresql://unused:unused@127.0.0.1:1/unused'
from test_kiwi_prep_01 import ObservationDB, INIT, KEYS

HOSTS = ['localhost', 'localhost:*', '127.0.0.1', '127.0.0.1:*', '[::1]', '[::1]:*']
ORIGINS = ['http://' + item for item in HOSTS]


def scope_for(host='127.0.0.1', origin=None, ct='application/json', extra=()):
    headers = [(b'accept', b'application/json, text/event-stream')]
    if host is not None:
        headers.append((b'host', host.encode('latin-1')))
    if origin is not None:
        headers.append((b'origin', origin.encode('latin-1')))
    if ct is not None:
        headers.append((b'content-type', ct.encode('latin-1')))
    headers.extend(extra)
    return {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': 'POST', 'scheme': 'http', 'path': '/mcp', 'raw_path': b'/mcp',
            'query_string': b'', 'root_path': '', 'headers': headers,
            'server': ('127.0.0.1', 8080), 'client': ('127.0.0.1', 50000)}


async def request(app, scope, body=None):
    messages = []
    first = True
    sent = asyncio.Event()

    async def receive():
        nonlocal first
        if first:
            first = False
            return {'type': 'http.request', 'body': body if body is not None else json.dumps(INIT).encode(),
                    'more_body': False}
        await sent.wait()
        return {'type': 'http.disconnect'}

    async def send(message):
        messages.append(message)
        if message['type'] == 'http.response.body' and not message.get('more_body', False):
            sent.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    starts = [m for m in messages if m['type'] == 'http.response.start']
    assert len(starts) == 1, 'one HTTP response start required'
    return starts[0]['status'], b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')


@contextmanager
def captures():
    streams = [io.StringIO() for _ in range(5)]
    handlers = []
    for logger, stream in zip((logging.getLogger(), logging.getLogger('mcp'),
                               logging.getLogger('mcp.server.transport_security')), streams):
        handler = logging.StreamHandler(stream)
        handlers.append((logger, handler, logger.level))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    try:
        with redirect_stdout(streams[3]), redirect_stderr(streams[4]):
            yield streams
    finally:
        for logger, handler, level in handlers:
            logger.removeHandler(handler)
            logger.setLevel(level)


class BuildGuards(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'MCP_ALLOWED_HOSTS': '', 'MCP_ALLOWED_ORIGINS': '',
                                                 'CORS_ORIGINS': '*'}))
        self.db = ObservationDB()
        import database
        self.enterContext(patch.object(database, 'get_pool', self.db.pool))
        self.access = importlib.reload(importlib.import_module('mcp_access'))
        self.enterContext(patch.object(self.access, 'get_pool', self.db.pool))

    def required(self, name):
        value = getattr(self.access, name, None)
        self.assertTrue(callable(value), name + ' BUILD implementation missing')
        return value

    def settings(self, hosts='', origins=''):
        os.environ.update(MCP_ALLOWED_HOSTS=hosts, MCP_ALLOWED_ORIGINS=origins)
        return self.required('build_transport_security')()

    def checked_servers(self, settings):
        from mcp.server.fastmcp import FastMCP
        from mcp.server.transport_security import TransportSecuritySettings
        # Import before recording to avoid counting an initial import plus reload.
        module = importlib.import_module('mcp_server')
        seen = []
        real_init = FastMCP.__init__
        def recording_init(instance, *args, **kwargs):
            seen.append(kwargs.get('transport_security'))
            return real_init(instance, *args, **kwargs)
        with patch.object(FastMCP, '__init__', recording_init):
            servers = importlib.reload(module)
        self.assertEqual(len(seen), 2)
        for obj in seen:
            self.assertIs(obj, settings)
        self.assertIs(servers._SECURITY, settings)
        for sdk in (servers.mcp_memory, servers.mcp_calendar):
            internal = sdk.settings.transport_security
            self.assertIsInstance(internal, TransportSecuritySettings)
            self.assertEqual(internal.model_dump(), settings.model_dump())
            self.assertIs(internal.enable_dns_rebinding_protection, True)
        return servers

    def run_sdk(self, scopes, *, hosts='', origins='', guarded=True):
        settings = self.settings(hosts, origins)
        guard = self.required('guard_mcp_access')
        self.required('install_transport_security_log_filter')()
        servers = self.checked_servers(settings)
        objects = [settings, servers.mcp_memory.settings.transport_security, servers.mcp_calendar.settings.transport_security]
        before = [repr(obj) for obj in objects]

        async def run():
            results = []
            for sdk, factory in ((servers.mcp_memory, servers.get_mcp_app),
                                 (servers.mcp_calendar, servers.get_calendar_mcp_app)):
                app = factory()
                if guarded:
                    app = guard(app, settings)
                async with sdk.session_manager.run():
                    results.append([await request(app, copy.deepcopy(s)) for s in scopes])
            return results
        results = asyncio.run(run())
        self.assertEqual([repr(obj) for obj in objects], before, 'settings or SDK copies mutated by requests')
        return results

    def assert_result(self, result, status, code=None):
        actual, body = result
        self.assertEqual(actual, status, body.decode(errors='replace'))
        if code:
            self.assertTrue(body.startswith(b'{'), 'rejection must use stable JSON, not SDK plaintext')
            data = json.loads(body)
            self.assertEqual(data['error'], code)
            self.assertEqual(data['error_code'], code)
            self.assertEqual(set(data), {'error', 'error_code', 'hint'} if code.startswith('mcp_') else {'error', 'error_code'})
        elif status == 200:
            self.assertIn(b'"result"', body)

    def test_T_BUILD_01_01_dependencies(self):
        text = (ROOT/'requirements.txt').read_text()
        for name, version in [('mcp','1.29.1'), ('httpx','0.27.2'), ('uvicorn','0.31.1'),
                              ('fastapi','0.141.1'), ('starlette','1.3.1')]:
            self.assertIn(name+'=='+version, text.splitlines())
            self.assertEqual(importlib.metadata.version(name), version)
        self.assertIn('FROM public.ecr.aws/docker/library/python:3.12-slim', (ROOT/'Dockerfile').read_text())
        evidence = ROOT/'docs/acceptance/evidence/kiwi_build_01_audit.json'
        self.assertTrue(evidence.is_file(), 'zero-vulnerability audit evidence missing')
        audit = json.loads(evidence.read_text())
        deps = audit['dependencies'] if isinstance(audit, dict) else audit
        self.assertTrue(deps, 'audit must include installed dependencies')
        self.assertFalse([v for dep in deps for v in dep.get('vulns', [])])

    def test_T_BUILD_01_02_constructor(self):
        settings = self.settings('a.example, a.example, b.example:*, *.evil, *, bad/path, ',
                                 'https://a.example, https://b.example:*, no-scheme, *')
        for item in HOSTS:
            self.assertIn(item, settings.allowed_hosts)
        for item in ORIGINS:
            self.assertIn(item, settings.allowed_origins)
        self.assertEqual(settings.allowed_hosts, HOSTS+['a.example','b.example:*'])
        self.assertEqual(settings.allowed_origins, ORIGINS+['https://a.example','https://b.example:*'])
        counts = self.access.read_allowlists()
        self.assertEqual(counts['hosts_invalid'], 3)
        self.assertEqual(counts['origins_invalid'], 2)
        self.assertIs(self.access.build_transport_security(), settings)
        servers = self.checked_servers(settings)

    def test_T_BUILD_01_03_host_matrix(self):
        good = ['localhost','localhost:8123','127.0.0.1','127.0.0.1:8123','[::1]','[::1]:8123',
                '192.0.2.1','10.0.0.5:8080','[2001:db8::1]:8080','Allowed.example','ports.example:3210']
        bad = ['unregistered.example','allowed.example',None]
        scopes = [scope_for(x) for x in good+bad]+[scope_for(extra=[(b'host',b'evil.example')])]
        for results in self.run_sdk(scopes, hosts='Allowed.example,ports.example:*'):
            for i, result in enumerate(results):
                self.assert_result(result, 200 if i<len(good) else 421,
                                   None if i<len(good) else 'mcp_host_not_allowed')

    def test_T_BUILD_01_04_origin_matrix(self):
        good = [None,'http://localhost','http://localhost:8123','http://127.0.0.1',
                'http://127.0.0.1:8123','http://[::1]','http://[::1]:8123','https://ok.example',
                'https://port.example:8123']
        bad = ['https://evil.example','https://named.example','https://ok.example.evil',
               'https://evil.example/https://port.example:8123']
        for results in self.run_sdk([scope_for('10.0.0.5:8080',o) for o in good+bad],
                                    hosts='named.example', origins='https://ok.example,https://port.example:*'):
            for i, result in enumerate(results):
                self.assert_result(result,200 if i<len(good) else 403,
                                   None if i<len(good) else 'mcp_origin_not_allowed')

    def test_T_BUILD_01_05_content_type(self):
        bad = [None,'text/plain','application/x-www-form-urlencoded',' application/json']
        scopes = [scope_for(ct=x) for x in bad+['application/json; charset=utf-8','APPLICATION/JSON']]
        scopes += [scope_for('localhost:garbage'),scope_for(extra=[(b'host',b'localhost')])]
        for results in self.run_sdk(scopes):
            for i,result in enumerate(results):
                status,code = (400,'invalid_content_type') if i<4 else ((200,None) if i==4 else ((415,None) if i==5 else (421,'mcp_host_not_allowed')))
                if i == 5:
                    self.assertEqual(result[0], 415)
                    self.assertNotIn(b'invalid_content_type', result[1])
                else:
                    self.assert_result(result,status,code)

    def test_T_BUILD_01_06_no_values(self):
        sentinels = ['BUILD-HOST-91c7.example','https://BUILD-ORIGIN-a617.example','BUILD-CONTENT-382f']
        scopes = [scope_for(sentinels[0]),scope_for(origin=sentinels[1]),scope_for(ct=sentinels[2])]
        with captures() as streams:
            results = self.run_sdk(scopes)
        evidence = [s.getvalue() for s in streams]+[b.decode() for group in results for _,b in group]
        for sentinel in sentinels:
            for output in evidence:
                self.assertNotIn(sentinel,output)
        # One event per rejection (each case ran once per SDK instance). Use a
        # single sink, not the sum of logger ancestors that see one record twice.
        one_sink = streams[0].getvalue()+streams[3].getvalue()
        for reason in ('host','origin','content_type'):
            self.assertEqual(one_sink.count('event=mcp_access_rejected reason='+reason+' increment=1'),2)

    def test_T_BUILD_01_07_ip_scope(self):
        bad = ['1.2.3.4@evil','01.2.3.4','1.2.3.4/x','127.0.0.1\x01','[::1','::1']
        good = ['10.0.0.5:8080','[fe80::1]:9000']
        for results in self.run_sdk([scope_for(x) for x in bad+good],hosts='named.example'):
            for i,result in enumerate(results):
                self.assert_result(result,421 if i<len(bad) else 200,
                                   'mcp_host_not_allowed' if i<len(bad) else None)
        settings = self.access.build_transport_security()
        settings_before = repr(settings)
        seen = []
        async def recorder(scope,receive,send):
            seen.append(scope)
            await receive()
            await send({'type':'http.response.start','status':200,'headers':[]})
            await send({'type':'http.response.body','body':b'{"result":{}}'})
        guard = self.access.guard_mcp_access(recorder,settings)
        async def run():
            for host in ('named.example','10.0.0.5:8080'):
                original = scope_for(host,extra=[(b'x-test',b'unchanged')])
                before = copy.deepcopy(original)
                await request(guard,original)
                self.assertEqual(original,before)
                expected = copy.deepcopy(before)
                if host.startswith('10.'):
                    expected['headers']=[(k,b'127.0.0.1' if k==b'host' else v) for k,v in expected['headers']]
                    self.assertIsNot(seen[-1],original)
                else:
                    self.assertIs(seen[-1],original)
                self.assertEqual(seen[-1],expected)
            paired = await asyncio.gather(request(guard,scope_for('10.0.0.5:8080')),
                                          request(guard,scope_for('foreign.example')))
            self.assertEqual([s for s,b in paired],[200,421])
        asyncio.run(run())
        self.assertEqual(repr(settings),settings_before)

    def test_T_BUILD_01_08_status(self):
        import main
        from fastapi.testclient import TestClient
        main = importlib.reload(main)
        with patch.dict(os.environ,{'MCP_ALLOWED_HOSTS':'BUILD-status.example'}):
            client = TestClient(main.app)
            self.addCleanup(client.close)
            response = client.get('/admin/mcp-access-status')
            self.assertEqual(response.status_code,200)
            data = response.json()
            self.assertEqual(set(data),KEYS)
            self.assertEqual(data['protection'],'enabled')
            self.assertEqual(data['version'],main.VERSION)
            self.assertIs(type(data['ip_literal_allowed']),bool)
            for key in ('hosts_registered','origins_registered','hosts_invalid','origins_invalid'):
                self.assertIs(type(data[key]),int)
            self.assertNotIn('BUILD-status.example',response.text)
            self.db.broken=True
            response=client.get('/admin/mcp-access-status')
            self.assertEqual(response.status_code,500)
            self.assertEqual(response.json(),{'error':'internal_error','error_code':'internal_error'})

    def test_T_BUILD_01_09_startup(self):
        log = self.required('log_mcp_access_summary')
        with captures() as streams:
            log()
        output=''.join(s.getvalue() for s in streams)
        self.assertIn('event=mcp_access_control hosts=0 origins=0 ip_literal=true',output)
        self.assertIn('MCP_ALLOWED_HOSTS',output)
        self.assertNotIn('预告',output)
        with patch.dict(os.environ,{'MCP_ALLOWED_HOSTS':'registered.example, bad item'}),captures() as streams:
            log()
        output=''.join(s.getvalue() for s in streams)
        self.assertIn('event=mcp_access_control hosts=1 origins=0 ip_literal=true',output)
        self.assertIn('event=mcp_allowlist_invalid_item field=hosts increment=1',output)
        self.assertNotIn('MCP_ALLOWED_HOSTS',output)
        for value in ('registered.example','bad item','预告'):
            self.assertNotIn(value,output)

    def test_T_BUILD_01_10_wiring(self):
        tree=ast.parse((ROOT/'mcp_server.py').read_text(encoding='utf-8-sig'))
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='FastMCP']
        self.assertEqual(len(calls),2)
        names=[]
        for call in calls:
            values=[k.value for k in call.keywords if k.arg=='transport_security']
            self.assertEqual(len(values),1,'FastMCP transport_security keyword missing')
            self.assertIsInstance(values[0],ast.Name)
            names.append(values[0].id)
        self.assertEqual(names[0],names[1])
        tree=ast.parse((ROOT/'main.py').read_text(encoding='utf-8-sig'))
        from test_kiwi_sec_01b import assert_exact_mcp_routes
        assert_exact_mcp_routes(self, tree)
        access=(ROOT/'mcp_access.py').read_text()
        self.assertNotIn('CORS_ORIGINS',access)
        for node in ast.walk(ast.parse(access)):
            if isinstance(node,ast.Import): self.assertNotIn('main',[a.name for a in node.names])
            if isinstance(node,ast.ImportFrom): self.assertNotEqual(node.module,'main')
        self.assertIs(json.loads((ROOT/'scripts/upgrade_gates.json').read_text())['gates']['mcp_access_control'],False)

    def test_T_BUILD_01_11_clients(self):
        # Target SDK compatibility must be tested with the actual target SDK.
        self.assertEqual(importlib.metadata.version('mcp'),'1.29.1')
        self.required('build_transport_security')
        from mcp.server.fastmcp import FastMCP
        import mcp_client
        import uvicorn
        for transport in ('streamable_http','sse'):
            sdk=FastMCP('BUILD local compatibility',stateless_http=True,
                        transport_security=self.access.build_transport_security())
            @sdk.tool()
            def build_ping() -> str:
                return 'pong'
            sock=socket.socket()
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            app=sdk.streamable_http_app() if transport=='streamable_http' else sdk.sse_app()
            server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='on', timeout_graceful_shutdown=1))
            thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
            thread.start()
            try:
                deadline=time.monotonic()+5
                while not server.started and thread.is_alive() and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertTrue(server.started,'local SDK server did not start')
                url=f'http://127.0.0.1:{port}/'+('mcp' if transport=='streamable_http' else 'sse')
                result=asyncio.run(asyncio.wait_for(mcp_client._connect_and_list(url,transport),5))
                self.assertEqual([tool.name for tool in result],['build_ping'])
            finally:
                server.should_exit=True
                thread.join(timeout=5)
                sock.close()
                self.assertFalse(thread.is_alive(),'local SDK server failed to stop')

    def test_T_BUILD_01_12_sdk_second_layer(self):
        with captures() as streams:
            results=self.run_sdk([scope_for('BUILD-direct.example'),scope_for('10.0.0.5:8080'),
                                  scope_for(ct=' application/json')],guarded=False)
        for group in results:
            self.assertEqual([status for status,body in group],[421,421,400])
        logs=''.join(s.getvalue() for s in streams)
        self.assertNotIn('BUILD-direct.example',logs)
        self.assertNotIn('10.0.0.5',logs)
        self.assertIn('mcp_transport_security_rejected reason=host',logs)
        self.assertIn('mcp_transport_security_rejected reason=content_type',logs)

    def test_T_BUILD_01_13_upgrade(self):
        self.required('guard_mcp_access')
        # The fixture supplies a rendered Compose environment; use exactly that
        # shape to initialize the real transport, never source a dotenv file.
        rendered={'services':{'kiwi-mem':{'environment':{'MCP_ALLOWED_HOSTS':'upgrade.example',
                                                        'MCP_ALLOWED_ORIGINS':''}}}}
        env=rendered['services']['kiwi-mem']['environment']
        for group in self.run_sdk([scope_for('upgrade.example')],hosts=env['MCP_ALLOWED_HOSTS']):
            self.assert_result(group[0],200)
        if os.name != 'nt':
            from prep_update_fixture import UpdateFixture
            fixture=UpdateFixture(foreign=False,mcp_code=421)
            self.addCleanup(fixture.close)
            fixture.target(False)
            outcome=fixture.run('--auto')
            self.assertEqual(outcome.returncode,1,outcome.stdout)
            self.assertEqual(fixture.head(),fixture.prev)


if __name__ == '__main__':
    unittest.main(verbosity=2)
