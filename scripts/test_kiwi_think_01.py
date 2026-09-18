#!/usr/bin/env python3
"""THINK-01 contract guards: real /v1 entry, dispatch and Anthropic adapter.

Only persistence and external HTTP are faked. Real config.get_config is used
against an in-memory DB protocol (not PostgreSQL) for absent/present rows.
Tool tests traverse the real entry and _stream_with_tools; no provider is called.
Stage A expects 01/03/05/06/08/09/10/11 assertion failures, never ERROR.
"""
import ast
import io
import json
import logging
import os
from pathlib import Path
import re
import sys
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DATABASE_URL'] = 'postgresql://unused:unused@127.0.0.1:1/unused'
import httpx
import config
import main as gateway

MISSING = object()
KEY = 'THINK-key-6d21-sentinel'
MODEL = 'THINK-model-8b93-sentinel'
USER = 'THINK-user-4a67-sentinel'
PROVIDERS = {
    'router': ('https://openrouter.ai/api/v1', 'openai'),
    'anthropic': ('https://anthropic.example/v1', 'anthropic'),
    'openai': ('https://api.openai.com/v1', 'openai'),
    'relay': ('https://relay.example/v1', 'openai'),
}


class ConfigPool:
    def __init__(self, values):
        self.values = values
        self.reads = []
    def acquire(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def fetchrow(self, sql, key):
        assert 'gateway_config' in sql, sql
        self.reads.append(key)
        return {'value': self.values[key]} if key in self.values else None


class ThinkGuards(unittest.IsolatedAsyncioTestCase):
    async def request_case(self, provider='router', *, explicit=MISSING,
                           panel=MISSING, raw=MISSING, tools=False,
                           skip=False, max_tokens=32768):
        values = {'memory_enabled': 'false', 'reminder_tools_enabled': str(tools).lower(),
                  'tool_drawer_enabled': 'false', 'mcp_mode': 'off',
                  'web_search_mode': 'off', 'prompt_cache_enabled': 'false'}
        if panel is not MISSING: values['reasoning_effort'] = panel
        pool = ConfigPool(values)
        url, fmt = PROVIDERS[provider]
        row = dict(id=7, provider_id=7, name='fixture', provider_name='fixture', api_base_url=url,
                   api_key=KEY, api_format=fmt, enabled=True)
        calls = []
        console, logs = io.StringIO(), io.StringIO()
        real_client = httpx.AsyncClient
        def upstream(req):
            payload = json.loads(req.content)
            calls.append((str(req.url), payload))
            if fmt == 'anthropic':
                result = {'id':'test','type':'message','role':'assistant','model':MODEL,
                          'content':[{'type':'text','text':'ok'}], 'stop_reason':'end_turn',
                          'usage':{'input_tokens':1,'output_tokens':1}}
            else:
                result = {'id':'test','choices':[{'index':0,'message':{'role':'assistant','content':'ok'},
                           'finish_reason':'stop'}], 'usage':{'prompt_tokens':1,'completion_tokens':1}}
            return httpx.Response(200, json=result)
        def outbound(**kwargs):
            return real_client(transport=httpx.MockTransport(upstream), **kwargs)
        body = {'model':MODEL,'messages':[{'role':'user','content':USER}],
                'temperature':0.7,'max_tokens':max_tokens,'stream':tools,
                'conversation_id':'think-fixture', 'skip_system_prompt':skip}
        if explicit is not MISSING: body['reasoning_effort'] = explicit
        async with real_client(transport=httpx.ASGITransport(app=gateway.app),
                               base_url='http://localhost') as client:
            with ExitStack() as stack:
                stack.enter_context(redirect_stdout(console))
                stack.enter_context(redirect_stderr(console))
                for logger in (logging.getLogger(), logging.getLogger('mcp')):
                    handler = logging.StreamHandler(logs)
                    logger.addHandler(handler)
                    stack.callback(logger.removeHandler, handler)
                stack.enter_context(patch.object(config,'get_pool',AsyncMock(return_value=pool)))
                for name, value in {
                    'resolve_scope_snapshot':(True,None,'global',None,None),
                    'get_reset_generation':0, 'get_memory_enabled':False,
                    'get_active_system_prompt':'fixture', 'resolve_provider_for_model':row,
                }.items():
                    stack.enter_context(patch.object(gateway,name,AsyncMock(return_value=value)))
                # Preserve real get_config for all unrelated keys, even in invalid-value probes.
                if raw is not MISSING:
                    async def raw_config(key):
                        return raw if key == 'reasoning_effort' else await config.get_config(key)
                    stack.enter_context(patch.object(gateway,'get_config',raw_config))
                stack.enter_context(patch.object(gateway,'process_memories_background',AsyncMock()))
                stack.enter_context(patch.object(httpx,'AsyncClient',outbound))
                response = await client.post('/v1/chat/completions',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(calls),1,console.getvalue())
        address, sent = calls[0]
        self.assertEqual(address,url + ('/messages' if fmt == 'anthropic' else '/chat/completions'))
        self.assertEqual(sent['max_tokens'],max_tokens)
        # The real tool loop requests a non-streamed model turn, then emits SSE.
        self.assertFalse(sent.get('stream',False))
        if tools: self.assertTrue(sent.get('tools'), 'must enter the real tool loop')
        return sent, console.getvalue() + logs.getvalue(), pool

    def assert_off(self, sent, provider):
        for field in ('reasoning','reasoning_effort','thinking'):
            self.assertNotIn(field,sent)
        if provider == 'anthropic': self.assertEqual(sent['temperature'],0.7)

    def assert_high(self, sent, provider):
        if provider == 'router': self.assertEqual(sent.get('reasoning'),{'enabled':True,'effort':'high'})
        elif provider == 'anthropic':
            self.assertEqual(sent.get('thinking'),{'type':'enabled','budget_tokens':20000})
            self.assertEqual(sent['temperature'],1)
        else: self.assertEqual(sent.get('reasoning_effort'),'high')

    def assert_resolved(self, log, source, effort):
        lines = [line for line in log.splitlines() if line.startswith('event=reasoning_effort_resolved')]
        self.assertEqual(lines,[f'event=reasoning_effort_resolved source={source} effort={effort}'])
        for value in (KEY,MODEL,USER): self.assertNotIn(value, ''.join(lines))

    async def test_T_THINK_01_01_omitted(self):
        for provider in ('router','anthropic','openai'):
            for panel in (MISSING,'off'):
                with self.subTest(provider=provider, absent=panel is MISSING):
                    sent, _, _ = await self.request_case(provider,panel=panel)
                    self.assert_off(sent,provider)

    async def test_T_THINK_01_02_explicit(self):
        for provider in ('router','anthropic','openai'):
            for effort, panel in (('high','off'),('off','high')):
                with self.subTest(provider=provider,effort=effort):
                    sent, _, pool = await self.request_case(provider,explicit=effort,panel=panel)
                    (self.assert_high if effort == 'high' else self.assert_off)(sent,provider)
                    self.assertNotIn('reasoning_effort',pool.reads,'explicit must not read panel')

    async def test_T_THINK_01_03_panel(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                sent, log, _ = await self.request_case(provider,panel='max' if provider=='relay' else 'high')
                self.assert_high(sent,provider)
                if provider=='relay': self.assertEqual(log.count('event=reasoning_effort_downgrade'),1)

    async def test_T_THINK_01_04_auto(self):
        for provider in ('router','anthropic','openai'):
            with self.subTest(provider=provider):
                sent, _, _ = await self.request_case(provider,panel='auto')
                if provider=='router': self.assertEqual(sent.get('reasoning'),{'enabled':True})
                elif provider=='anthropic':
                    self.assertEqual(sent.get('thinking'),{'type':'enabled','budget_tokens':10000})
                    self.assertEqual(sent['temperature'],1)
                else: self.assert_off(sent,provider)

    async def test_T_THINK_01_05_fallback(self):
        for provider in ('router','anthropic','openai'):
            for raw in ('ultra','',None):
                with self.subTest(provider=provider,raw=raw):
                    sent, log, _ = await self.request_case(provider,raw=raw)
                    self.assert_off(sent,provider)
                    self.assert_resolved(log,'default','off')
                    self.assertEqual(log.count('event=reasoning_effort_config_invalid'),int(raw=='ultra'))
                    self.assertNotIn('ultra',log)
        with self.subTest(real_config_absent=True):
            sent, log, pool = await self.request_case()
            self.assert_off(sent,'router')
            self.assert_resolved(log,'panel','off')
            self.assertEqual(pool.reads.count('reasoning_effort'),1)

    async def test_T_THINK_01_06_tools(self):
        for effort in (MISSING,'off'):
            with self.subTest(explicit_off=effort=='off'):
                sent, _, _ = await self.request_case(panel='high',explicit=effort,tools=True)
                (self.assert_off if effort=='off' else self.assert_high)(sent,'router')

    async def test_T_THINK_01_07_internal(self):
        for provider in ('router','anthropic','openai'):
            with self.subTest(provider=provider):
                sent, _, _ = await self.request_case(provider,panel='high',skip=True)
                self.assert_off(sent,provider)

    async def test_T_THINK_01_08_none_defense(self):
        for native, anthropic, initial in ((True,False,{}),(False,True,{'reasoning':{'enabled':True}})):
            with self.subTest(anthropic=anthropic):
                gateway._apply_reasoning(initial,native,anthropic,None)
                self.assertEqual(initial,{})
        self.assertIsNone(gateway._normalize_reasoning_effort(None))

    async def test_T_THINK_01_09_logs(self):
        for params,source,effort in (({'explicit':'high','panel':'off'},'explicit','high'),
                                     ({},'panel','off'),({'panel':'high'},'panel','high'),
                                     ({'raw':None},'default','off')):
            with self.subTest(source=source,effort=effort):
                _, log, pool = await self.request_case(**params)
                self.assert_resolved(log,source,effort)
                if source=='panel': self.assertEqual(pool.reads.count('reasoning_effort'),1)
        with self.subTest(invalid=True):
            _, log, _ = await self.request_case(raw='ultra')
            self.assertEqual([x for x in log.splitlines() if x.startswith('event=reasoning_effort_config_invalid')],
                             ['event=reasoning_effort_config_invalid increment=1'])
            self.assertNotIn('ultra',log)

    async def test_T_THINK_01_10_panel_schema(self):
        text = (ROOT/'admin-panel/js/config-schema.js').read_text(encoding='utf-8')
        entry = re.search(r"reasoning_effort:\s*\{([^}]+)\}",text)
        self.assertIsNotNone(entry)
        options = re.search(r"options:\s*(\[[^]]+\])",entry[1])
        self.assertIsNotNone(options)
        self.assertEqual(ast.literal_eval(options[1]),['off','auto','low','medium','high'])
        self.assertRegex(entry[1],r"def:\s*'off'")
        self.assertEqual(config.CONFIG_SCHEMA['reasoning_effort'][1],'off')
        self.assertEqual(config._ENUM_VALUES['reasoning_effort'],set(config.REASONING_EFFORT_VALUES))
        desc = re.search(r"desc:\s*'([^']*)'",entry[1])
        self.assertIsNotNone(desc)
        for token in ('显式','不主动开启','xhigh / max'):
            with self.subTest(token=token): self.assertIn(token,desc[1])

    async def test_T_THINK_01_11_docs(self):
        for filename,tokens in {
            'docs/reasoning-effort.md':('显式','面板','off','不主动开启','budget_tokens'),
            'docs/UPGRADING.md':('不再主动开启思考','no longer enables thinking by default'),
            'CHANGELOG.md':('THINK-01',),
            'KNOWN_ISSUES.md':('## KIWI-THINK-01','不等于强制关闭'),
        }.items():
            with self.subTest(file=filename):
                path=ROOT/filename
                self.assertTrue(path.is_file(),filename+' must exist')
                text=path.read_text(encoding='utf-8')
                for token in tokens: self.assertIn(token,text)

    async def test_T_THINK_01_12_regression(self):
        sent,log,_=await self.request_case('relay',explicit='max')
        self.assert_high(sent,'relay')
        self.assertEqual(log.count('event=reasoning_effort_downgrade'),1)
        sent,log,_=await self.request_case('anthropic',explicit='low',max_tokens=1024)
        self.assert_off(sent,'anthropic')
        self.assertEqual(log.count('event=reasoning_effort_disable'),1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
