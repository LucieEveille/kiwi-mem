#!/usr/bin/env python3
"""OUT-01 v1.2: real ASGI, dispatch, two-round tools, adapter and memory gates.

No real model, external tool or database is used. Config/storage/extraction are
boundary fakes; process_memories_background and its record/extract gates are real.
All assertion identities are stable between Stage A and B. Missing new helpers
are assertion failures, never import/collection errors. Raw request golden hashes
were captured on 180d857 with a frozen clock, not generated from the tested tree.
"""
import ast
import asyncio
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import datetime
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import test_kiwi_think_01 as fixture
import anthropic_adapter as adapter
import config
import httpx
import main as gateway
from test_kiwi_err_01 import find_raw_exception_returns

BASE = '180d857d051c97482d159c2821493ce084b05795'
MODEL, USER, KEY = 'out01-model', 'out01-user', 'out01-fake-key'
PERSONA = 'OUT01_PERSONA'
SENTINEL = 'SENTINEL-7f3a'
ABSENT = '<OUT01:absent>'
ALIASED = 'event=max_completion_tokens_aliased'
IGNORED = 'event=max_completion_tokens_ignored reason=max_tokens_present'
ERRORS = {
    'max_tokens': 'max_tokens 须为正整数',
    'max_completion_tokens': 'max_completion_tokens 须为正整数',
    'stop': 'stop 须为非空字符串或 1～4 个非空字符串的数组',
}
# Immutable byte-level request captures from BASE. Includes all rounds, not a
# projection of the fields under test. Filled once during tests-only Stage A.
GOLDEN = {'P-O/0/mt': ['87fa5d2c993546533df27508eed0486393aee5f9b804fca9d59c41ef1d8d1957'],
 'P-O/0/mct': ['ba8262b0eb7568ae2f41cbf6502ab13e1b27aeb646d3d4dec061a119647e4402'],
 'P-O/0/stop-str': ['d21e3cb8be23cb8bc9fc1f3eb9b42540d3d9a74a11c0f7a6125d7f354bc3d42d'],
 'P-O/0/stop-list': ['d479a337267245240525e8b41a9a03179a4903198fb25330717d4eddc3e22c3a'],
 'P-O/1/mt': ['9e37b19d163cd7cf02862589b057444f5bd85a085c2cfba6b0034cbd4c81a358'],
 'P-O/1/mct': ['a2d51cc8e31af8f46213685d5f1063096798b9f03c8518778b7630323993207a'],
 'P-O/1/stop-str': ['e1113a7281d353211c87e81bbc987de0f6b69af57ce09108cd77ec6e12e5595b'],
 'P-O/1/stop-list': ['ec96af57eb4076e81d6d93c6025c1bdb2e205792dbe408cbb813238771e08ce0'],
 'regression/openai/P0/mt': ['87fa5d2c993546533df27508eed0486393aee5f9b804fca9d59c41ef1d8d1957'],
 'regression/openai/P0/reasoning-off': ['f46576373c324931766ebf939952faee6ed020c5c2da6d89a113be8c7a61475c'],
 'regression/openai/P0/reasoning-auto': ['80b1686404278f8601e9eccaf69a714913963b1701b93de9f529069a02838393'],
 'regression/openai/P0/reasoning-low': ['9b972387d071ce2c348575c8d5069c0181c670292a7ec2fb56827d79b9842a4c'],
 'regression/openai/P0/reasoning-medium': ['13a1ac6e2c619dd9906c30313e686f1374e2e92a5a721350e5a05f219e5e3887'],
 'regression/openai/P0/reasoning-high': ['fa531178d67e453b31fa6eff400ac24d36a14fd9281e78de915ee07e3aedc9c2'],
 'regression/openai/P0/reasoning-xhigh': ['24391b256ba04851686f3d5f9fab18370819fb7c22a3dd96e30e660be433de7b'],
 'regression/openai/P0/reasoning-max': ['ab515a095c2d1d0c6225553dc99e36ad4c339276c4e293822d963143e0c938b7'],
 'regression/openai/P0/reasoning-none': ['f46576373c324931766ebf939952faee6ed020c5c2da6d89a113be8c7a61475c'],
 'regression/openai/P1/mt': ['9e37b19d163cd7cf02862589b057444f5bd85a085c2cfba6b0034cbd4c81a358'],
 'regression/openai/P1/reasoning-off': ['86a1d01a6301467942cc7fe3ec6ca0c8562fe8aef09b6b0f72781befef0ca9f1'],
 'regression/openai/P1/reasoning-auto': ['4b22637f9a9460fc4f249465544b4e290557c1ac9fb7a20659ca51a8ccefce99'],
 'regression/openai/P1/reasoning-low': ['b159cc43cfdc17c9622e4ef27ee2bf4e9816d9ee2848ae709269d96a075e8b99'],
 'regression/openai/P1/reasoning-medium': ['853b925f8caec657a25853d154124dca6a4e8d7580fb4059b2ce18abc05ec8d1'],
 'regression/openai/P1/reasoning-high': ['fe2f85ab121fcaa3eef971050e0b636d990d08a2e8116b7bc523905f30aacbd1'],
 'regression/openai/P1/reasoning-xhigh': ['4731e9491d1d34ba045695ce325cc8e1c05574d4d720465ac602053d1a4f5b04'],
 'regression/openai/P1/reasoning-max': ['f7a8ec3677adc53de36ad4b812cb7af2fdd143a66b066b205ab9a82a5216d992'],
 'regression/openai/P1/reasoning-none': ['86a1d01a6301467942cc7fe3ec6ca0c8562fe8aef09b6b0f72781befef0ca9f1'],
 'regression/openai/T/mt': ['6f3c06e9d52b08de63ed35c5df7ca9661b4a321827c4a1cb1809db57b524af72',
                            '6e18f99005ec2e97ba6cf3d98c647012373845e5ccac8817cea3c5077fedcdbc'],
 'regression/openai/T/reasoning-off': ['1f3b8001e9dd2f8cb7c6c53721283add3df221316ed2e6a2dca707c3908982ed',
                                       'bd02b5ac39af354ad900687c33e8892deca530f8dbc9d8a55eff3bed44f7a38a'],
 'regression/openai/T/reasoning-auto': ['2d1c0922797e0e78ade6cae0e5c501d572eb43ff43c88e5e15d3e73af7b7deee',
                                        'a615b6448bd4293017810d04f66e3dc6b63e7a8187c4b2458593f6f70722234e'],
 'regression/openai/T/reasoning-low': ['4023062a1a3a7262cb3771248a318bd8753218d99b3be577a1cf91fa5632d9e0',
                                       '7f3e84c2e7422a5f6f0677b86f89406e734f262e91bcde1d486fec5dbe1d00fb'],
 'regression/openai/T/reasoning-medium': ['ed806edee9a4cfa6fbfd3ea35c9eff5deb87125e5106d96ded2a176f38b9c7a5',
                                          'fb41b3b5dfc953980b53ba223b592a9433e68956b64f4f4061ccdfe94e92f78a'],
 'regression/openai/T/reasoning-high': ['bb10cd52e4810fcc8d1fe99a3b4dd6a1aea84daaccfc525ba73babf127fe5ee6',
                                        '402728dd5f52490085177eeaaca6dd6e64f2843afffb19c50ec32c90a347c022'],
 'regression/openai/T/reasoning-xhigh': ['154f0c3519bf297d4e29103c5f3e3299655919ffc265c8d280ea754e5aeb1d60',
                                         '70e1b4ecd456cf8e7d7035b7ef648440baaee2f8dce138e0845049f991107df1'],
 'regression/openai/T/reasoning-max': ['015eb002182b9ee04f724f8daca7df43921ac8d7efd85e4a41bdf7f47b4d9506',
                                       '614b219cde594e3b2b62b3197e95acadc1a4befa0a457d59b23c71f7ac1bf203'],
 'regression/openai/T/reasoning-none': ['1f3b8001e9dd2f8cb7c6c53721283add3df221316ed2e6a2dca707c3908982ed',
                                        'bd02b5ac39af354ad900687c33e8892deca530f8dbc9d8a55eff3bed44f7a38a'],
 'regression/anthropic/P0/mt': ['07e8618e432920982aadd26f6324efc1b5ea4df45c478bc0c70c8b05b747d859'],
 'regression/anthropic/P0/reasoning-off': ['c667da44ddaa3873d769bc1a800123ac3954463f3d8b8e6d5433b1676930ed8d'],
 'regression/anthropic/P0/reasoning-auto': ['6f5ddf535653871dddac88b32451dd306a2ba0682035315c4fec504fb7721384'],
 'regression/anthropic/P0/reasoning-low': ['c5475b7c1b129ea70da1469704f3df0ce2b9af80b3d22579d0c5b4cead3b044b'],
 'regression/anthropic/P0/reasoning-medium': ['6f5ddf535653871dddac88b32451dd306a2ba0682035315c4fec504fb7721384'],
 'regression/anthropic/P0/reasoning-high': ['f5ac42b9ab8e31712d9112d416442784fda5a89cc146b50dbf890830e3f8ed8a'],
 'regression/anthropic/P0/reasoning-xhigh': ['fdba518e1f7398ffd99889820fe985811a7bab3678ab963cdbfe73f58de9c211'],
 'regression/anthropic/P0/reasoning-max': ['f7d3fe765cb4939a1bdc48ddacf69f53bdfa53a2968b88af8529fc81e3b1dbc8'],
 'regression/anthropic/P0/reasoning-none': ['c667da44ddaa3873d769bc1a800123ac3954463f3d8b8e6d5433b1676930ed8d'],
 'regression/anthropic/P1/mt': ['1de691be884b2f6b7b0f7afd188a93576bb4b066a4b215bc771c095b7fee86bb'],
 'regression/anthropic/P1/reasoning-off': ['f452b4935ae189ebb9d1d25d4f4945f26c2e2af03348a5af6125a9df073431ad'],
 'regression/anthropic/P1/reasoning-auto': ['45be312f2b72a47a8435d4893f462523647cd6a46389442af3f5bf69a57cf598'],
 'regression/anthropic/P1/reasoning-low': ['9bb91211f351378db55a0ed3981507c8282b0515d65ee73a3f1440bc3cd483e7'],
 'regression/anthropic/P1/reasoning-medium': ['45be312f2b72a47a8435d4893f462523647cd6a46389442af3f5bf69a57cf598'],
 'regression/anthropic/P1/reasoning-high': ['3a1633f9da29cc905289006255b772ef560bf4a1424ae9adef0c4692c3d1fdc8'],
 'regression/anthropic/P1/reasoning-xhigh': ['bcc91a6853ad2c453fbf9aa0e5b28bea08ece6dad96541ac2211ca59349e5943'],
 'regression/anthropic/P1/reasoning-max': ['e01474b49fa0c85c835bd1c418789a8818744b95aee72a61d126a45b7a69a2d5'],
 'regression/anthropic/P1/reasoning-none': ['f452b4935ae189ebb9d1d25d4f4945f26c2e2af03348a5af6125a9df073431ad'],
 'regression/anthropic/T/mt': ['6449e084df915729e55f9cd173969059eb3ecef06f9bf0a51e31f492388a55c9',
                               'dd54a82d530bddb8a6067c2c43efdcc34d89a0c4ba0673191e85a7077e2f3f4e'],
 'regression/anthropic/T/reasoning-off': ['d8c7e485829870cb6eac166f3a7386a29ab5cde25c0f27c29fba6099baba5240',
                                          'b8c8a93cb8ce57dcf0e9af33b23e55e80ba31f407b41d86fedb9a86bf6a359f9'],
 'regression/anthropic/T/reasoning-auto': ['287d53558163ba60f57ee6fb8a9c33c93b8e5af7003c67c001d49ea45d5799a2',
                                           '3de362198315ad7c17cfd8c379bdecac652c5b6b8fc0a4572430f4c438968dae'],
 'regression/anthropic/T/reasoning-low': ['97197a78c6c80294cd93310d91e32b690ce41413e8d56e5e033c2e6021783d2e',
                                          '8d4221a5392b663111ec4cdcedb0ece0b76041f85e3e5591901704a58214f6fb'],
 'regression/anthropic/T/reasoning-medium': ['287d53558163ba60f57ee6fb8a9c33c93b8e5af7003c67c001d49ea45d5799a2',
                                             '3de362198315ad7c17cfd8c379bdecac652c5b6b8fc0a4572430f4c438968dae'],
 'regression/anthropic/T/reasoning-high': ['ecd53d4f4fab2b92a3f1bb958380bcf81d5bb75584e7684823b83b9889238933',
                                           'fd2f7778ba66b5fb5c79710fc562522d1b23d3670a188c864b0537772036265b'],
 'regression/anthropic/T/reasoning-xhigh': ['27b97a9029cece87b901277d223258333af83b1ae9eedd05c13d007cd1e800c6',
                                            '7f10ca97628dc0b91be901eddc2f707e79e3b4fdf6aa1941c5786e5b04b7ea94'],
 'regression/anthropic/T/reasoning-max': ['84df7dc82aedd0857b42112d1574dcd2386c3d4018cb00b89745a6dbbedf22ea',
                                          'e2cd854afe6101dfcbe2f2132cf1dc71dc8788f6636055816b0fcd9677c39d65'],
 'regression/anthropic/T/reasoning-none': ['d8c7e485829870cb6eac166f3a7386a29ab5cde25c0f27c29fba6099baba5240',
                                           'b8c8a93cb8ce57dcf0e9af33b23e55e80ba31f407b41d86fedb9a86bf6a359f9']}


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 3, 12, 0, 0, tzinfo=tz)


def out_events(log):
    return [s for s in log.splitlines() if s.startswith('event=max_completion_tokens_')]


def error_payload(param):
    return {'error': {'message': ERRORS[param], 'type': 'invalid_request_error',
                      'param': param, 'code': 'invalid_value'}}


def digests(result):
    return [hashlib.sha256(raw).hexdigest() for raw in result['raw']]


def sse(fmt):
    if fmt == 'openai':
        events = [{'choices': [{'delta': {'content': 'ok'}, 'finish_reason': None}]},
                  {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}]
        return ''.join('data: ' + json.dumps(x) + '\n\n' for x in events) + 'data: [DONE]\n\n'
    events = [
        {'type': 'message_start', 'message': {'id': 'out01', 'model': MODEL,
          'usage': {'input_tokens': 1, 'output_tokens': 0}}},
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'ok'}},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 1}},
        {'type': 'message_stop'},
    ]
    return ''.join('event: ' + x['type'] + '\ndata: ' + json.dumps(x) + '\n\n' for x in events)


async def request_case(controls=None, *, fmt='openai', stream=False, tools=False,
                       skip=False, memory=False, effort='off', direct=False):
    """Capture actual HTTP bytes; fake tool executes between two real loop rounds."""
    values = {'memory_enabled': str(memory).lower(), 'reminder_tools_enabled': str(tools).lower(),
              'tool_drawer_enabled': 'false', 'mcp_mode': 'off', 'web_search_mode': 'off',
              'prompt_cache_enabled': 'false', 'reasoning_effort': effort,
              'memory_event_ledger_write_enabled': 'true'}
    pool = fixture.ConfigPool(values)
    url = 'https://anthropic.example/v1' if fmt == 'anthropic' else 'https://openrouter.ai/api/v1'
    row = dict(id=7, provider_id=7, name='fixture', provider_name='fixture',
               api_base_url=url, api_key=KEY, api_format=fmt, enabled=True)
    sent, raw, addresses, tasks = [], [], [], []
    console = io.StringIO()
    real_client = httpx.AsyncClient
    execute = AsyncMock(return_value=('OUT01_TOOL_RESULT', {}))
    ledger = AsyncMock(return_value={'path': 'inserted'})
    extract = AsyncMock(return_value=('skip', [], 0, 0, None))

    def upstream(req):
        body = json.loads(req.content)
        sent.append(body)
        raw.append(req.content)
        addresses.append(str(req.url))
        # Tool response cannot happen without the registered tool in the request.
        call_tool = tools and len(sent) == 1
        if call_tool:
            assert body.get('tools'), 'fixture expected tools in first model request'
        if tools and len(sent) == 2:
            assert execute.await_count == 1, 'second model request preceded tool execution'
        if body.get('stream'):
            return httpx.Response(200, text=sse(fmt), headers={'content-type': 'text/event-stream'})
        if fmt == 'anthropic':
            content = ([{'type': 'tool_use', 'id': 'call-out01', 'name': '_gateway_list_reminders', 'input': {}}]
                       if call_tool else [{'type': 'text', 'text': 'ok'}])
            result = {'id': 'out01', 'type': 'message', 'role': 'assistant', 'model': MODEL,
                      'content': content, 'stop_reason': 'tool_use' if call_tool else 'end_turn',
                      'usage': {'input_tokens': 1, 'output_tokens': 1}}
        else:
            message = {'role': 'assistant', 'content': None if call_tool else 'ok'}
            if call_tool:
                message['tool_calls'] = [{'id': 'call-out01', 'type': 'function',
                    'function': {'name': '_gateway_list_reminders', 'arguments': '{}'}}]
            result = {'id': 'out01', 'choices': [{'index': 0, 'message': message,
                      'finish_reason': 'tool_calls' if call_tool else 'stop'}],
                      'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}
        return httpx.Response(200, json=result)

    def outbound(**kwargs):
        return real_client(transport=httpx.MockTransport(upstream), **kwargs)

    def spawn(coro):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    body = {'model': MODEL, 'messages': [{'role': 'user', 'content': USER}],
            'temperature': 0.7, 'top_p': 0.8, 'stream': stream or tools,
            'conversation_id': 'out01-fixture', 'skip_system_prompt': skip}
    body.update(copy.deepcopy(controls or {}))
    with ExitStack() as stack:
        stack.enter_context(redirect_stdout(console))
        stack.enter_context(redirect_stderr(console))
        stack.enter_context(patch.object(config, 'get_pool', AsyncMock(return_value=pool)))
        for name, value in {
            'resolve_scope_snapshot': (True, None, 'global', None, None),
            'get_reset_generation': 0, 'get_memory_enabled': memory,
            'get_active_system_prompt': PERSONA, 'resolve_provider_for_model': row,
            'build_system_prompt_with_memories': (PERSONA, {}),
            'get_extract_interval': 1, 'search_memories': [],
            'get_recent_memories': [], 'get_all_categories': [], 'get_all_memories_count': 0,
        }.items():
            stack.enter_context(patch.object(gateway, name, AsyncMock(return_value=value)))
        stack.enter_context(patch.object(gateway, 'append_turn_events_atomic', ledger))
        stack.enter_context(patch.object(gateway, '_extract_and_save_batch', extract))
        stack.enter_context(patch.object(gateway, '_execute_gateway_tool', execute))
        stack.enter_context(patch.object(gateway, '_spawn_background_task', spawn))
        stack.enter_context(patch.object(gateway, '_conversation_counter', 0))
        stack.enter_context(patch.object(gateway, '_counter_lock', asyncio.Lock()))
        stack.enter_context(patch.object(gateway, 'datetime', Clock))
        stack.enter_context(patch.object(httpx, 'AsyncClient', outbound))
        if direct:
            chunks = [x async for x in gateway._stream_with_tools(
                [{'role': 'user', 'content': USER}], [], {}, MODEL, 0.7, [],
                'out01-fixture', USER, False, api_url=url + '/chat/completions',
                api_key=KEY, max_tokens=512, record_events=False)]
            response = httpx.Response(200, text=''.join(chunks))
        else:
            async with real_client(transport=httpx.ASGITransport(app=gateway.app),
                                   base_url='http://localhost') as client:
                response = await client.post('/v1/chat/completions', json=body)
        if tasks:
            await asyncio.gather(*tasks)
    return dict(response=response, sent=sent, raw=raw, addresses=addresses,
                log=console.getvalue(), tool_calls=execute.await_count,
                ledger_calls=ledger.await_count, extract_calls=extract.await_count)


def parser_case(body):
    body = copy.deepcopy(body)
    before = copy.deepcopy(body)
    fn = getattr(gateway, '_parse_output_controls', None)
    result, error = ABSENT, None
    console = io.StringIO()
    if callable(fn):
        with redirect_stdout(console):
            try:
                result = fn(body)
            except Exception as exc:
                error = exc
    return dict(exists=callable(fn), result=result, error=error, body=body,
                before=before, events=out_events(console.getvalue()))


INVALID = []
for field in ('max_tokens', 'max_completion_tokens'):
    for label, value in (('zero', 0), ('negative', -1), ('float', 1.5),
                         ('string', '512'), ('bool', True), ('list', []), ('sentinel', SENTINEL)):
        INVALID.append((field + '-' + label, {field: value}, field))
INVALID += [('lower-invalid', {'max_tokens': 512, 'max_completion_tokens': 0}, 'max_completion_tokens')]
for label, value in (('empty', ''), ('empty-list', []), ('empty-item', ['a', '']),
                     ('five', ['1', '2', '3', '4', '5']), ('number', 5), ('object', {'a': 1}),
                     ('sentinel', [SENTINEL, ''])):
    INVALID.append(('stop-' + label, {'stop': value}, 'stop'))
INVALID += [('alias-bad-stop', {'max_completion_tokens': 512, 'stop': []}, 'stop')]


class OutGuards(unittest.IsolatedAsyncioTestCase):
    def equal(self, arm, check, actual, expected):
        with self.subTest(arm=arm, check=check):
            self.assertEqual(actual, expected)

    def valid_route(self, arm, result, *, fmt, tools=False):
        self.equal(arm, 'http-status', result['response'].status_code, 200)
        self.equal(arm, 'model-request-count', len(result['sent']), 2 if tools else 1)
        self.equal(arm, 'executed-tool-count', result['tool_calls'], 1 if tools else 0)
        suffix = '/messages' if fmt == 'anthropic' else '/chat/completions'
        self.equal(arm, 'endpoint', all(u.endswith(suffix) for u in result['addresses']), True)
        self.equal(arm, 'no-stream-error', '"error"' in result['response'].text, False)
        if tools:
            second = result['sent'][1] if len(result['sent']) > 1 else {}
            self.equal(arm, 'round2-contains-tool-result',
                       'OUT01_TOOL_RESULT' in json.dumps(second.get('messages')), True)

    def byte_regression(self, arm, result):
        self.equal(arm, 'raw-bytes-vs-180d857', digests(result), GOLDEN.get(arm, ABSENT))

    async def test_T_OUT_01_00_parser(self):
        cases = [
            ('mt', {'max_tokens': 512}, {'value': 512, 'source': 'max_tokens'}, None, {'max_tokens': 512}, []),
            ('mct', {'max_completion_tokens': 512}, {'value': 512, 'source': 'max_completion_tokens'}, None,
             {'max_completion_tokens': 512}, [ALIASED]),
            ('dual', {'max_tokens': 300, 'max_completion_tokens': 900}, {'value': 300, 'source': 'max_tokens'},
             None, {'max_tokens': 300}, [IGNORED]),
            ('null-mt-mct', {'max_tokens': None, 'max_completion_tokens': 512},
             {'value': 512, 'source': 'max_completion_tokens'}, None, {'max_completion_tokens': 512}, [ALIASED]),
            ('null-mct', {'max_completion_tokens': None}, None, None, {}, []),
            ('absent', {}, None, None, {}, []),
            ('stop-str', {'stop': 'END'}, None, ['END'], {'stop': 'END'}, []),
            ('stop-list', {'stop': ['a', 'b']}, None, ['a', 'b'], {'stop': ['a', 'b']}, []),
            ('stop-null', {'stop': None}, None, None, {}, []),
        ]
        for arm, body, limit, stop, final, events in cases:
            r = parser_case(body)
            self.equal(arm, 'helper-exists', r['exists'], True)
            self.equal(arm, 'no-exception', r['error'], None)
            self.equal(arm, 'tuple-shape', isinstance(r['result'], tuple) and len(r['result']) == 2, True)
            self.equal(arm, 'limit-and-stop', r['result'], (limit, stop))
            self.equal(arm, 'body-after', r['body'], final)
            self.equal(arm, 'events', r['events'], events)

    async def test_T_OUT_01_01_invalid(self):
        for arm, body, param in INVALID:
            p = parser_case(body)
            self.equal(arm, 'parser-helper-exists', p['exists'], True)
            self.equal(arm, 'parser-exception-type', type(p['error']).__name__, '_ParamError')
            self.equal(arm, 'parser-fixed-message', getattr(p['error'], 'message', ABSENT), ERRORS[param])
            self.equal(arm, 'parser-error-param', getattr(p['error'], 'param', ABSENT), param)
            self.equal(arm, 'parser-input-unchanged', p['body'], p['before'])
            self.equal(arm, 'parser-zero-out-events', p['events'], [])
            # Every rejection is checked at the real entry with tools enabled too.
            for fmt in ('openai', 'anthropic'):
                r = await request_case(body, fmt=fmt, tools=True)
                key = arm + '/' + fmt
                response = r['response']
                try:
                    payload = response.json()
                except ValueError:
                    payload = '<non-JSON response>'
                self.equal(key, 'http-400', response.status_code, 400)
                self.equal(key, 'fixed-error-envelope', payload, error_payload(param))
                self.equal(key, 'zero-upstream', len(r['sent']), 0)
                self.equal(key, 'zero-out-events', out_events(r['log']), [])
                self.equal(key, 'no-sentinel', SENTINEL in response.text, False)

    async def test_T_OUT_01_02_plain_openai(self):
        cases = [('mt', {'max_tokens': 512}, {'max_tokens': 512}),
                 ('mct', {'max_completion_tokens': 512}, {'max_completion_tokens': 512}),
                 ('dual', {'max_tokens': 300, 'max_completion_tokens': 900}, {'max_tokens': 300}),
                 ('null-mt-mct', {'max_tokens': None, 'max_completion_tokens': 512}, {'max_completion_tokens': 512}),
                 ('stop-str', {'max_tokens': 512, 'stop': 'END'}, {'max_tokens': 512, 'stop': 'END'}),
                 ('stop-list', {'max_tokens': 512, 'stop': ['a', 'b']}, {'max_tokens': 512, 'stop': ['a', 'b']})]
        for stream in (False, True):
            for label, body, expected in cases:
                arm = f'P-O/{int(stream)}/{label}'
                r = await request_case(body, stream=stream)
                self.valid_route(arm, r, fmt='openai')
                sent = r['sent'][0] if r['sent'] else {}
                self.equal(arm, 'controls', {k: sent[k] for k in ('max_tokens', 'max_completion_tokens', 'stop') if k in sent}, expected)
                self.equal(arm, 'stream-path', sent.get('stream'), stream)
                if label not in ('dual', 'null-mt-mct'):
                    self.byte_regression(arm, r)

    async def test_T_OUT_01_03_plain_anthropic(self):
        cases = [('mct', {'max_completion_tokens': 512}, 512, None),
                 ('dual', {'max_tokens': 300, 'max_completion_tokens': 900}, 300, None),
                 ('absent', {}, 8192, None), ('stop-str', {'stop': 'END'}, 8192, ['END']),
                 ('stop-list', {'stop': ['a', 'b']}, 8192, ['a', 'b'])]
        for stream in (False, True):
            for label, body, limit, stop in cases:
                arm = f'P-A/{int(stream)}/{label}'
                r = await request_case(body, fmt='anthropic', stream=stream)
                self.valid_route(arm, r, fmt='anthropic')
                sent = r['sent'][0] if r['sent'] else {}
                self.equal(arm, 'limit', sent.get('max_tokens'), limit)
                self.equal(arm, 'stop-sequences', sent.get('stop_sequences', ABSENT), ABSENT if stop is None else stop)
                self.equal(arm, 'no-raw-keys', any(k in sent for k in ('stop', 'max_completion_tokens')), False)
                self.equal(arm, 'stream-path', sent.get('stream', False), stream)

    async def tool_cases(self, fmt):
        for label, body, limit, source, stop in [
            ('mct', {'max_completion_tokens': 512}, 512, 'max_completion_tokens', None),
            ('mt', {'max_tokens': 512}, 512, 'max_tokens', None),
            ('stop-str', {'max_completion_tokens': 512, 'stop': 'END'}, 512, 'max_completion_tokens', ['END']),
            ('stop-list', {'max_tokens': 512, 'stop': ['a', 'b']}, 512, 'max_tokens', ['a', 'b']),
            ('absent', {}, None, None, None),
        ]:
            arm = f'T-{fmt}/{label}'
            r = await request_case(body, fmt=fmt, tools=True)
            self.valid_route(arm, r, fmt=fmt, tools=True)
            # Fixed two-round assertion identities even if the subject drops a round.
            for index in range(2):
                sent = r['sent'][index] if len(r['sent']) > index else {}
                key = arm + '/round' + str(index + 1)
                self.equal(key, 'non-streamed-model-turn', sent.get('stream', False), False)
                expected = ({'max_tokens': limit or 8192} if fmt == 'anthropic'
                            else ({source: limit} if source else {}))
                self.equal(key, 'limit-and-source', {k: sent[k] for k in ('max_tokens', 'max_completion_tokens') if k in sent}, expected)
                name = 'stop_sequences' if fmt == 'anthropic' else 'stop'
                self.equal(key, 'stop', sent.get(name, ABSENT), ABSENT if stop is None else stop)
                if fmt == 'anthropic':
                    self.equal(key, 'no-raw-stop', 'stop' in sent, False)

    async def test_T_OUT_01_04_tools_openai(self):
        await self.tool_cases('openai')

    async def test_T_OUT_01_05_tools_anthropic(self):
        await self.tool_cases('anthropic')

    async def test_T_OUT_01_06_regressions(self):
        for fmt in ('openai', 'anthropic'):
            for mode, stream, tools in (('P0', False, False), ('P1', True, False), ('T', True, True)):
                arm = f'regression/{fmt}/{mode}/mt'
                r = await request_case({'max_tokens': 512}, fmt=fmt, stream=stream, tools=tools)
                self.valid_route(arm, r, fmt=fmt, tools=tools)
                self.byte_regression(arm, r)
                for i, sent in enumerate(r['sent']):
                    self.equal(arm, f'no-stop-{i}', any(k in sent for k in ('stop', 'stop_sequences')), False)
                    self.equal(arm, f'sampling-{i}', (sent.get('top_p'), sent.get('temperature')), (0.8, 0.7))
                # THINK-02 aliases included; 8 selected inputs plus seven canonical levels.
                for effort in ('off', 'auto', 'low', 'medium', 'high', 'xhigh', 'max', 'none'):
                    key = f'regression/{fmt}/{mode}/reasoning-{effort}'
                    out = await request_case({'max_tokens': 70000, 'reasoning_effort': effort},
                                             fmt=fmt, stream=stream, tools=tools)
                    self.valid_route(key, out, fmt=fmt, tools=tools)
                    self.byte_regression(key, out)
        _, body = adapter.prepare_background_request(KEY, 'anthropic',
            {'model': MODEL, 'messages': [{'role': 'user', 'content': USER}]})
        self.equal('background', 'default-8192', body.get('max_tokens'), 8192)
        self.equal('background', 'no-stop', 'stop_sequences' in body, False)
        for mode, stream, tools in (('P0', False, False), ('P1', True, False), ('T', True, True)):
            for source in ('max_tokens', 'max_completion_tokens'):
                for limit in (512, 1024, 1025, 8192, 30000):
                    arm = f'FUT18/{mode}/{source}/{limit}'
                    r = await request_case({source: limit}, fmt='anthropic', stream=stream, tools=tools, effort='high')
                    self.valid_route(arm, r, fmt='anthropic', tools=tools)
                    for i in range(2 if tools else 1):
                        sent = r['sent'][i] if len(r['sent']) > i else {}
                        expected = ABSENT if limit <= 1024 else {'type': 'enabled', 'budget_tokens': min(20000, limit - 1)}
                        self.equal(arm, f'limit-{i}', sent.get('max_tokens'), limit)
                        self.equal(arm, f'budget-{i}', sent.get('thinking', ABSENT), expected)
                    reason = ('reason=max_tokens_below_minimum' if limit <= 1024 else
                              'reason=max_tokens_limit' if limit < 20001 else None)
                    self.equal(arm, 'disabled-log', r['log'].count('reason=max_tokens_below_minimum'),
                               (2 if tools else 1) if reason == 'reason=max_tokens_below_minimum' else 0)
                    self.equal(arm, 'clamped-log', r['log'].count('reason=max_tokens_limit'),
                               (2 if tools else 1) if reason == 'reason=max_tokens_limit' else 0)
        direct = await request_case(direct=True)
        self.equal('legacy-kwarg', 'limit', direct['sent'][0].get('max_tokens'), 512)

    async def test_T_OUT_01_07_events(self):
        for fmt in ('openai', 'anthropic'):
            for tools in (False, True):
                for label, body, expected in (
                    ('alias', {'max_completion_tokens': 512}, [ALIASED]),
                    ('dual', {'max_tokens': 300, 'max_completion_tokens': 900}, [IGNORED]),
                    ('absent', {}, []),
                ):
                    arm = f'{fmt}/{tools}/{label}'
                    r = await request_case(body, fmt=fmt, tools=tools)
                    self.equal(arm, 'exact-once-without-values', out_events(r['log']), expected)
                for label, body, _ in INVALID:
                    arm = f'{fmt}/{tools}/invalid/{label}'
                    r = await request_case(body, fmt=fmt, tools=tools)
                    self.equal(arm, 'rejection-no-event', out_events(r['log']), [])

    async def test_T_OUT_01_08_skip_prompt(self):
        for label, skip in (('bool-true', True), ('str-true', 'true'), ('one', 1),
                            ('yes', 'yes'), ('str-false', 'false'), ('zero', 0)):
            for memory in (False, True):
                for mode, stream, tools in (('P0', False, False), ('P1', True, False), ('T', True, True)):
                    arm = f'{label}/memory-{memory}/{mode}'
                    r = await request_case({'max_tokens': 70000}, skip=skip, memory=memory,
                                           effort='high', stream=stream, tools=tools)
                    self.valid_route(arm, r, fmt='openai', tools=tools)
                    normal = skip is not True
                    self.equal(arm, 'persona', PERSONA in json.dumps(r['sent'][0].get('messages')), normal)
                    self.equal(arm, 'ledger-writes', r['ledger_calls'], int(normal))
                    self.equal(arm, 'extract-called', r['extract_calls'], int(normal and memory))
                    for i in range(2 if tools else 1):
                        sent = r['sent'][i] if len(r['sent']) > i else {}
                        self.equal(arm, f'reasoning-{i}', sent.get('reasoning', ABSENT),
                                   {'enabled': True, 'effort': 'high'} if normal else ABSENT)

    async def test_T_OUT_01_09_error_scanner(self):
        source = (ROOT / 'main.py').read_text(encoding='utf-8')
        self.equal('scanner', 'raw-exception-returns', find_raw_exception_returns(source), [])
        entry = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'chat_completions')
        handlers = [n for n in ast.walk(entry) if isinstance(n, ast.ExceptHandler)
                    and isinstance(n.type, ast.Name) and n.type.id == '_ParamError']
        unsafe = []
        for h in handlers:
            for ret in (n for n in ast.walk(h) if isinstance(n, ast.Return)):
                for n in ast.walk(ret):
                    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'str'
                            and any(isinstance(x, ast.Name) and x.id == h.name for x in n.args)):
                        unsafe.append(n.lineno)
                    if isinstance(n, ast.JoinedStr) and any(isinstance(x, ast.Name) and x.id == h.name for x in ast.walk(n)):
                        unsafe.append(n.lineno)
        self.equal('handler', 'no-raw-exception-interpolation-if-present', unsafe, [])


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.rows.append(dict(guard=test._testMethodName, arm=subtest.params['arm'],
                              assertion=subtest.params['check'], status='PASS' if err is None else
                              'FAIL' if issubclass(err[0], AssertionError) else 'ERROR',
                              failure_kind=err[0].__name__ if err else None,
                              reason=str(err[1]) if err else None))


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OutGuards)
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    arms = {}
    for row in result.rows:
        key = (row['guard'], row['arm'])
        arm = arms.setdefault(key, dict(guard=key[0], arm=key[1], status='PASS', failures=[]))
        if row['status'] != 'PASS':
            arm['status'] = 'ERROR' if row['status'] == 'ERROR' else ('FAIL' if arm['status'] != 'ERROR' else 'ERROR')
            arm['failures'].append(row['assertion'])
    counts = {s: sum(r['status'] == s for r in arms.values()) for s in ('PASS', 'FAIL', 'ERROR')}
    assertions = {s: sum(r['status'] == s for r in result.rows) for s in ('PASS', 'FAIL', 'ERROR')}
    report = dict(ticket='OUT-01', baseline=BASE, groups_run=result.testsRun,
                  counts=counts, assertion_counts=assertions, arms=list(arms.values()),
                  assertions=result.rows, errors=len(result.errors), failures=len(result.failures),
                  scope='real ASGI/dispatch/adapter/memory gates; fake storage, tool execution, extraction and upstream')
    path = os.environ.get('KIWI_OUT_01_REPORT')
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('SUMMARY ' + json.dumps(counts, sort_keys=True))
    print('assertion_counts ' + json.dumps(assertions, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
