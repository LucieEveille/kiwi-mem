#!/usr/bin/env python3
"""THINK-02 Stage A: real entry/dispatch/adapter, fake config DB and upstream.

Ten guard groups; subtests report assertion failures without hiding later arms.
No model API or PostgreSQL is called here. The separate safety suite covers PG.
The request fixture follows THINK-01; its existing tests remain unchanged.
"""
import ast
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import test_kiwi_think_01 as fixture
import httpx
import config
import main as gateway

MISSING = fixture.MISSING
KEY, MODEL, USER = fixture.KEY, fixture.MODEL, fixture.USER
PROVIDERS, ConfigPool = fixture.PROVIDERS, fixture.ConfigPool
LEVELS = ('off', 'auto', 'low', 'medium', 'high', 'xhigh', 'max')
INPUTS = [(x, x) for x in LEVELS] + [('none', 'off'), ('minimal', 'low')]
SENTINEL = 'ZZ-SENTINEL-think02-private'
BUDGETS = {'low': 5000, 'medium': 10000, 'high': 20000, 'xhigh': 32000, 'max': 64000}


def source_slice(filename, name, assignment=False):
    text = (ROOT / filename).read_text(encoding='utf-8')
    tree = ast.parse(text)
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and
               any(isinstance(t, ast.Name) and t.id == name for t in n.targets)] if assignment else [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(matches) != 1:
        raise AssertionError('expected one source node: ' + name)
    node = matches[0]
    return ''.join(text.splitlines(keepends=True)[node.lineno - 1:node.end_lineno]), node


class Think02Guards(unittest.IsolatedAsyncioTestCase):
    async def request_case(self, provider='router', *, explicit=MISSING,
                           panel=MISSING, raw=MISSING, tools=False,
                           skip=False, max_tokens=70000, reasoning=MISSING, include=MISSING):
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
        if reasoning is not MISSING: body['reasoning'] = reasoning
        if include is not MISSING: body['include_reasoning'] = include
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
        if response.status_code == 200:
            self.assertEqual(len(calls), 1, console.getvalue())
            address, sent = calls[0]
            self.assertEqual(address, url + ('/messages' if fmt == 'anthropic' else '/chat/completions'))
            self.assertFalse(sent.get('stream', False))
            if tools:
                self.assertTrue(sent.get('tools'), 'must enter the real tool loop')
        else:
            self.assertEqual(calls, [], 'rejected input must not reach upstream')
            sent = None
        return response, sent, console.getvalue() + logs.getvalue(), pool

    def resolved(self, log, source, effort):
        lines = [x for x in log.splitlines() if x.startswith('event=reasoning_effort_resolved')]
        self.assertEqual(lines, [f'event=reasoning_effort_resolved source={source} effort={effort}'])

    def success(self, result):
        response, sent, log, pool = result
        self.assertEqual(response.status_code, 200, response.text)
        return sent, log, pool

    def outbound_effort(self, sent, provider, level):
        fields = {k: sent[k] for k in ('reasoning', 'reasoning_effort', 'thinking') if k in sent}
        if level == 'off' or (level == 'auto' and provider in ('openai', 'relay')):
            self.assertEqual(fields, {})
        elif provider == 'router':
            self.assertEqual(fields, {'reasoning': {'enabled': True, **({'effort': level} if level != 'auto' else {})}})
        elif provider == 'anthropic':
            self.assertEqual(fields, {'thinking': {'type': 'enabled', 'budget_tokens': BUDGETS.get(level, 10000)}})
            self.assertEqual(sent['temperature'], 1)
        else:
            # THINK-01 trusts only the registered hosts; api.openai.com also
            # retains its existing high ceiling. Do not widen it in this ticket.
            applied = 'high' if provider in ('relay', 'openai') and level in ('xhigh', 'max') else level
            self.assertEqual(fields, {'reasoning_effort': applied})

    def rejected(self, result, param, prefix):
        response, _, log, _ = result
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(set(response.json()), {'error'})
        error = response.json()['error']
        self.assertEqual(set(error), {'message', 'type', 'param', 'code'})
        self.assertEqual(error['type'], 'invalid_request_error')
        self.assertEqual(error['code'], 'invalid_value')
        self.assertEqual(error['param'], param)
        self.assertTrue(error['message'].startswith(prefix), error['message'])
        self.assertNotIn(SENTINEL, response.text + log)
        return error

    async def test_T_THINK_02_00_aliases(self):
        for provider in PROVIDERS:
            for tools in (False, True):
                for alias, level in [('none', 'off'), ('minimal', 'low'), (' NONE ', 'off'), (' MiNiMaL ', 'low')]:
                    with self.subTest(arm='aliases', provider=provider, tools=tools, alias=alias):
                        sent, log, _ = self.success(await self.request_case(provider, explicit=alias, tools=tools))
                        self.outbound_effort(sent, provider, level)
                        self.resolved(log, 'explicit', level)
        with self.subTest(arm='ultra-continuation'):
            error = self.rejected(await self.request_case(explicit='ultra'), 'reasoning_effort', 'reasoning_effort 必须是')
            self.assertIn('/'.join(LEVELS), error['message'])
        with self.subTest(arm='explicit-log-continuation'):
            _, log, _ = self.success(await self.request_case(explicit='high'))
            self.resolved(log, 'explicit', 'high')

    async def test_T_THINK_02_01_object_entry(self):
        for value, level in INPUTS + [(' NoNe ', 'off'), (' MINIMAL ', 'low')]:
            with self.subTest(arm='entry', effort=value):
                _, log, pool = self.success(await self.request_case(reasoning={'effort': value}, panel='high'))
                self.resolved(log, 'explicit_object', level)
                self.assertNotIn('reasoning_effort', pool.reads)

    async def test_T_THINK_02_02_outbound(self):
        for provider in PROVIDERS:
            for tools in (False, True):
                for value, level in INPUTS:
                    with self.subTest(arm='object-outbound', provider=provider, tools=tools, effort=value):
                        sent, log, _ = self.success(await self.request_case(provider, tools=tools, reasoning={'effort': value}))
                        self.outbound_effort(sent, provider, level)
                        if provider == 'relay' and level in ('xhigh', 'max'):
                            # 0cbd1af already applies at entry and again in the
                            # tool loop; preserve that existing logging shape.
                            self.assertEqual(log.count('event=reasoning_effort_downgrade'), 2 if tools else 1)
        # Existing explicit entry proves the unchanged output layer independently.
        for provider in PROVIDERS:
            for tools in (False, True):
                for level in LEVELS:
                    with self.subTest(arm='legacy-output-continuation', provider=provider, tools=tools, effort=level):
                        sent, _, _ = self.success(await self.request_case(provider, tools=tools, explicit=level))
                        self.outbound_effort(sent, provider, level)
        with self.subTest(arm='low-cap-continuation'):
            sent, log, _ = self.success(await self.request_case('anthropic', explicit='low', max_tokens=1024))
            self.outbound_effort(sent, 'anthropic', 'off')
            self.assertEqual(log.count('event=reasoning_effort_disable'), 1)

    async def test_T_THINK_02_03_panel_conflict(self):
        for provider in PROVIDERS:
            for tools in (False, True):
                with self.subTest(provider=provider, tools=tools):
                    sent, log, _ = self.success(await self.request_case(provider, tools=tools, panel='high', reasoning={'enabled': False}))
                    self.outbound_effort(sent, provider, 'off')
                    self.resolved(log, 'explicit_object', 'off')

    async def test_T_THINK_02_04_budget(self):
        boundaries = [(1,'low'), (1024,'low'), (4999,'low'), (5000,'low'), (9999,'low'),
                      (10000,'medium'), (19999,'medium'), (20000,'high'), (31999,'high'),
                      (32000,'xhigh'), (63999,'xhigh'), (64000,'max'), (64001,'max')]
        for budget, level in boundaries:
            with self.subTest(arm='04a-entry', budget=budget):
                _, log, _ = self.success(await self.request_case(reasoning={'max_tokens': budget}))
                self.resolved(log, 'explicit_object', level)
        with self.subTest(arm='04b-budget-table'):
            floors = getattr(gateway, '_REASONING_BUDGET_FLOORS', None)
            self.assertIsNotNone(floors, 'missing seam: _REASONING_BUDGET_FLOORS')
            _, node = source_slice('anthropic_adapter.py', '_EFFORT_BUDGET', True)
            self.assertEqual({level: budget for budget, level in floors}, ast.literal_eval(node.value))
            self.assertEqual(len(floors), 5)

    async def test_T_THINK_02_05_auto(self):
        values = [{}, {'enabled': True}, {'unknown': SENTINEL}, {'enabled': 'false'}]
        values += [{'max_tokens': n} for n in (0, -1, True, '5000', 5000.0)]
        for index, value in enumerate(values):
            with self.subTest(case=index):
                _, log, _ = self.success(await self.request_case(reasoning=value, panel='high'))
                self.resolved(log, 'explicit_object', 'auto')

    async def test_T_THINK_02_06_precedence(self):
        for other in ({'effort': 'low'}, {'enabled': False}, SENTINEL, [], 42):
            with self.subTest(arm='string-wins-continuation', other_type=type(other).__name__, other=str(other)):
                sent, log, _ = self.success(await self.request_case(explicit='high', reasoning=other))
                self.outbound_effort(sent, 'router', 'high')
                self.resolved(log, 'explicit', 'high')
        for explicit in (SENTINEL, 1, True, []):
            with self.subTest(arm='invalid-string-continuation', value_type=type(explicit).__name__):
                self.rejected(await self.request_case(explicit=explicit, reasoning={'effort': 'high'}),
                              'reasoning_effort', 'reasoning_effort 必须是')
        for label, explicit, obj, level in [
            ('null', None, {'effort': 'high'}, 'high'),
            ('table12', MISSING, {'effort': 'high', 'max_tokens': 100}, 'high'),
            ('table13', MISSING, {'enabled': False, 'effort': 'high'}, 'off'),
            ('disabled-invalid', MISSING, {'enabled': False, 'effort': SENTINEL}, 'off'),
            ('table14', MISSING, {'effort': None, 'max_tokens': 12000}, 'medium'),
            ('table15', MISSING, {'exclude': True, 'effort': 'low'}, 'low'),
        ]:
            with self.subTest(arm=label):
                _, log, _ = self.success(await self.request_case(explicit=explicit, reasoning=obj))
                self.resolved(log, 'explicit_object', level)
        for explicit, obj in ((MISSING, MISSING), (None, None), (MISSING, None)):
            with self.subTest(arm='absent-panel-continuation', explicit_null=explicit is None, object_null=obj is None):
                _, log, _ = self.success(await self.request_case(explicit=explicit, reasoning=obj, panel='high'))
                self.resolved(log, 'panel', 'high')
        for provider in PROVIDERS:
            for tools in (False, True):
                with self.subTest(arm='include-reasoning-continuation', provider=provider, tools=tools):
                    sent, _, _ = self.success(await self.request_case(provider, tools=tools, explicit='high', include=True))
                    if not tools and provider != 'anthropic':
                        self.assertIs(sent.get('include_reasoning'), True)
                    else:
                        self.assertNotIn('include_reasoning', sent)

    async def test_T_THINK_02_07_rejection(self):
        for value in (SENTINEL, [SENTINEL], 1, True):
            with self.subTest(arm='non-object', kind=type(value).__name__):
                self.rejected(await self.request_case(reasoning=value), 'reasoning', 'reasoning 必须是对象')
        for value in (SENTINEL, '', 4):
            with self.subTest(arm='invalid-effort', value=value):
                error = self.rejected(await self.request_case(reasoning={'effort': value}),
                                      'reasoning', 'reasoning.effort 必须是')
                self.assertIn('/'.join(LEVELS), error['message'])
        with self.subTest(arm='string-rejection-continuation'):
            self.rejected(await self.request_case(explicit=SENTINEL), 'reasoning_effort', 'reasoning_effort 必须是')

    async def test_T_THINK_02_08_logs(self):
        for provider in PROVIDERS:
            for tools in (False, True):
                result = await self.request_case(provider, tools=tools, reasoning={'effort': 'high', 'private': SENTINEL})
                with self.subTest(arm='source', provider=provider, tools=tools):
                    _, log, _ = self.success(result)
                    self.resolved(log, 'explicit_object', 'high')
                with self.subTest(arm='no-echo', provider=provider, tools=tools):
                    self.assertNotIn(SENTINEL, result[2])

    async def test_T_THINK_02_09_regression(self):
        for file, name, assign, expected in [
            ('main.py', '_apply_reasoning', False, '429e1e5e41ad269d9ec6d0fac13e6f9edc05dba694c91d073e48705b99af81e7'),
            ('anthropic_adapter.py', '_EFFORT_BUDGET', True, '56e4593182cdf8b7a1439808632ec6afac945ea13f609f7c6330892f0de0bc1f'),
        ]:
            with self.subTest(arm='zero-diff', node=name):
                text, _ = source_slice(file, name, assign)
                self.assertEqual(hashlib.sha256(text.encode('utf-8')).hexdigest(), expected,
                                 'must equal 0cbd1af source slice (normalized checkout newlines)')
        for name, command in [
            ('THINK-01-12', [sys.executable, str(ROOT/'scripts/test_kiwi_think_01.py')]),
            ('ERR-01-X1', [sys.executable, '-m', 'unittest',
                           'test_kiwi_err_01.ErrGuards.test_T10_x1_parameter_diagnostics']),
        ]:
            with self.subTest(arm=name):
                run = subprocess.run(command, cwd=ROOT/'scripts', capture_output=True, text=True,
                                     encoding='utf-8', env={**os.environ, 'PYTHONUTF8': '1'}, timeout=120)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.arms = []

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        status = 'PASS' if err is None else ('FAIL' if issubclass(err[0], test.failureException) else 'ERROR')
        self.arms.append({'guard': test._testMethodName, 'arm': dict(subtest.params), 'status': status,
                          'reason': 'assertions reached' if err is None else str(err[1]),
                          'failure_kind': None if err is None else err[0].__name__})


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Think02Guards)
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    counts = {s: sum(r['status'] == s for r in result.arms) for s in ('PASS', 'FAIL', 'ERROR')}
    print('THINK-02 SUMMARY ' + json.dumps(counts, sort_keys=True))
    report = {'groups_run': result.testsRun, 'counts': counts, 'arms': result.arms,
              'errors': len(result.errors), 'failures': len(result.failures)}
    if os.environ.get('KIWI_THINK_02_REPORT'):
        Path(os.environ['KIWI_THINK_02_REPORT']).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
