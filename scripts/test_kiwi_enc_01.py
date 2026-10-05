#!/usr/bin/env python3
"""ENC-01 v1.1: real stream/adapter/session/finalization, synthetic I/O only.

UTF-8 fixtures are byte-positioned before they enter HTTPX's real 256-byte
iterator. No decoder implementation is substituted. Golden values were frozen
once on 7763634; there is deliberately no golden-update command.
"""
import asyncio
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import test_kiwi_out_01 as old
from test_kiwi_compat_02a import Clock
import anthropic_adapter as adapter
import config
import httpx
import main as app

BASE = '776363437ef707167eebee9dc12e3277356110ca'
MODEL, USER, SESSION = 'enc01-model', 'enc01-user', 'auto-r-enc01-synthetic'
PATHS = ('P-O', 'A-direct', 'P-A')
CUTS = [(c, cut) for c in ('✓', '好', '🥝', 'é') for cut in range(1, len(c.encode()))]
LONG = ''.join(chr(0x4e00 + n) for n in range(400))
GOLDEN = {
    'P-O/ascii': '952e8148d182f1c9a733d9d805ae770ea94a272474b986ef76c8f6df8788751f',
    'P-O/aligned-chinese': '8af4634273b31c187f7c7d08aca881dc124f5a180e7737d0cb1054062004fbf6',
    'A-direct/ascii': '81695fb6fdd46952532610091a6db639f15587cf5b7d10bbd8ce3a40d4bf7356',
    'A-direct/aligned-chinese': '9cd11574fd9523da49a0ea0c28828dbed420c3d150ba1ab5e5a1a6bc6c393c87',
    'P-A/ascii': '6c271a6e72d477532ba0d2b642781540947ec60be195de7c11dfec0f8f633b24',
    'P-A/aligned-chinese': '5fc6eb47825f963b72a5f45f7bd311c9efae00e6ff0d3dc956f8110d5c81569e',
}


def frame(obj):
    return ('data: ' + json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n\n').encode()


def text_frame(fmt, text):
    if fmt == 'openai':
        return frame({'id': 'enc01-upstream', 'model': MODEL, 'created': 1,
                      'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': None}]})
    return frame({'type': 'content_block_delta', 'index': 0,
                  'delta': {'type': 'text_delta', 'text': text}})


def ending(fmt):
    if fmt == 'openai':
        return frame({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}) + b'data: [DONE]\n\n'
    return (frame({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'},
                   'usage': {'output_tokens': 1}}) + frame({'type': 'message_stop'}))


def spec(fmt, name, raw, expected, **extra):
    return dict(fmt=fmt, name=name, raw=raw, expected=expected, **extra)


def positioned(fmt, char, cut):
    # Padding is itself a valid content event, not ignored junk or a decoder mock.
    target = text_frame(fmt, char + '-tail')
    before = target.index(char.encode())
    pad = (256 - cut - len(text_frame(fmt, '')) - before) % 256
    prefix = text_frame(fmt, 'a' * pad)
    raw = prefix + target + ending(fmt)
    return spec(fmt, f'U+{ord(char):04X}/cut-{cut}', raw, 'a' * pad + char + '-tail',
                offset=len(prefix) + before, char=char, cut=cut)


def split_offsets(raw):
    # A boundary is inside UTF-8 iff the next chunk starts on a continuation byte.
    return [i for i in range(256, len(raw), 256) if raw[i] & 0xc0 == 0x80]


def long_spec(fmt):
    for n in range(256):
        raw = text_frame(fmt, 'a' * n) + text_frame(fmt, LONG) + ending(fmt)
        if len(split_offsets(raw)) == 4:
            return spec(fmt, 'long-400', raw, 'a' * n + LONG)
    raise AssertionError('fixture cannot arrange four split Chinese characters')


def golden_spec(fmt, name):
    if name == 'ascii':
        return spec(fmt, name, text_frame(fmt, 'plain-ascii') + ending(fmt), 'plain-ascii')
    event = text_frame(fmt, '好')
    n = (-len(event)) % 256
    raw = text_frame(fmt, 'a' * n + '好') + ending(fmt)
    return spec(fmt, name, raw, 'a' * n + '好')


def malformed_spec(fmt, name):
    raw = text_frame(fmt, 'safe-text')
    if name == 'invalid-byte':
        raw = raw.replace(b'safe-text', b'safe-\x80text') + ending(fmt)
    else:
        # A complete event, then an incomplete UTF-8 tail; no message_stop.
        raw += '✓'.encode()[:2]
    return spec(fmt, name, raw, 'safe-text')


def interleaved_spec(fmt, char):
    # Exactly one completed text event per full read block, followed by the
    # leading byte of the next event's character. A generator yield therefore
    # suspends while its decoder retains a partial character. Final short block
    # completes the last event and terminates the stream normally.
    raw, expected = b'', ''
    for i in range(4):
        text = (char if i else '') + f'-{ord(char):x}-{i}-'
        next_prefix = text_frame(fmt, char).index(char.encode())
        pad = (255 - len(raw) - len(text_frame(fmt, text)) - next_prefix) % 256
        text += 'a' * pad
        raw += text_frame(fmt, text)
        expected += text
    raw += text_frame(fmt, char + '-last') + ending(fmt)
    expected += char + '-last'
    return spec(fmt, 'interleaved-' + str(ord(char)), raw, expected)


def parsed(raw):
    events, text, errors = [], [], []
    for part in raw.decode('utf-8', errors='replace').split('\n\n'):
        for line in part.splitlines():
            if not line.startswith('data: '):
                continue
            value = line[6:]
            if value == '[DONE]':
                events.append(value)
                continue
            try:
                event = json.loads(value)
            except (ValueError, TypeError):
                errors.append('invalid-json')
                continue
            events.append(event)
            if not isinstance(event, dict):
                errors.append('non-object')
                continue
            if 'error' in event:
                errors.append('error-frame')
            choices = event.get('choices')
            if isinstance(choices, list):
                for choice in choices:
                    delta = choice.get('delta') if isinstance(choice, dict) else None
                    content = delta.get('content') if isinstance(delta, dict) else None
                    if isinstance(content, str):
                        text.append(content)
    return dict(events=events, text=''.join(text), errors=errors)


class Harness:
    """Shared patch scope for both streams, but actual per-request production state."""
    def __enter__(self):
        self.stack = ExitStack()
        self.tasks, self.requests, self.reads = [], [], []
        self.ledger = AsyncMock(return_value={'path': 'inserted'})
        pool = old.fixture.ConfigPool({'memory_event_ledger_write_enabled': 'true',
            'memory_enabled': 'false', 'reasoning_effort': 'off', 'prompt_cache_enabled': 'false',
            'reminder_tools_enabled': 'false', 'tool_drawer_enabled': 'false', 'mcp_mode': 'off'})
        self.real_client = httpx.AsyncClient
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        for logger in (logging.getLogger(), logging.getLogger('httpx'), logging.getLogger('mcp')):
            saved = logger.disabled
            logger.disabled = True
            self.stack.callback(setattr, logger, 'disabled', saved)
        self.stack.enter_context(patch.object(config, 'get_pool', AsyncMock(return_value=pool)))
        for name, value in {'resolve_scope_snapshot': (True, None, 'global', None, None),
                            'get_reset_generation': 0, 'get_memory_enabled': False}.items():
            self.stack.enter_context(patch.object(app, name, AsyncMock(return_value=value)))
        for name, value in {'append_turn_events_atomic': self.ledger,
                            '_spawn_background_task': self.spawn, 'datetime': Clock}.items():
            self.stack.enter_context(patch.object(app, name, value))
        self.stack.enter_context(patch.object(uuid, 'uuid4', return_value=uuid.UUID(int=1)))
        self.stack.enter_context(patch.object(httpx, 'AsyncClient', self.client))
        original_iterator = httpx.Response.aiter_bytes
        async def observed(response, chunk_size=None):
            async for chunk in original_iterator(response, chunk_size=chunk_size):
                self.reads.append((response.extensions.get('enc_label'), len(chunk)))
                yield chunk
        self.stack.enter_context(patch.object(httpx.Response, 'aiter_bytes', observed))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task

    def client(self, **kwargs):
        return self.real_client(transport=httpx.MockTransport(self.upstream), **kwargs)

    def upstream(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        key = body['messages'][-1]['content']
        if isinstance(key, list):
            key = key[0]['text']
        s = self.specs[key]
        if not body.get('stream'):
            if s['fmt'] == 'anthropic':
                value = {'id': 'enc01', 'role': 'assistant', 'type': 'message',
                         'content': [{'type': 'text', 'text': s['expected']}],
                         'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
            else:
                value = {'choices': [{'message': {'role': 'assistant', 'content': s['expected']},
                                      'finish_reason': 'stop'}]}
            return httpx.Response(200, json=value)
        return httpx.Response(200, content=s['raw'], headers={'content-type': 'text/event-stream'},
                              extensions={'enc_label': key})

    async def generator(self, path, s, key):
        if path == 'A-direct':
            async with self.real_client(transport=httpx.MockTransport(self.upstream)) as client:
                async with client.stream('POST', 'https://fixture.example/messages',
                    json={'messages': [{'role': 'user', 'content': key}], 'stream': True}) as response:
                    async for chunk in adapter.anthropic_stream_to_openai(response, MODEL):
                        yield chunk
            return
        messages = [{'role': 'user', 'content': key}]
        shared = dict(api_url='https://fixture.example/' + ('messages' if s['fmt'] == 'anthropic' else 'chat/completions'),
                      api_key='synthetic-key', api_format=s['fmt'], record_events=True, extract_enabled=False)
        if path.startswith('T-'):
            inner = app._stream_with_tools(messages, [], {}, MODEL, 0.7, [], SESSION + key, USER, False, **shared)
        else:
            inner = app.stream_and_capture({}, {'model': MODEL, 'messages': messages, 'stream': True},
                                          SESSION + key, USER, MODEL, mem_enabled=False, **shared)
        async for chunk in app._with_ev_session(inner, SESSION + key, True):
            yield chunk

    async def run(self, path, specs, interleave=False):
        self.specs = {str(n): s for n, s in enumerate(specs)}
        chunks = [[] for _ in specs]
        exceptions = [None for _ in specs]
        generators = [self.generator(path, s, str(n)) for n, s in enumerate(specs)]
        active = set(range(len(specs)))
        while active:
            for n in sorted(active):
                try:
                    chunks[n].append(await generators[n].__anext__())
                except StopAsyncIteration:
                    active.remove(n)
                except Exception as exc:
                    exceptions[n] = type(exc).__name__
                    active.remove(n)
                if not interleave and n in active:
                    break
        if self.tasks:
            await asyncio.gather(*self.tasks)
        results = []
        for n, output in enumerate(chunks):
            raw = b''.join(x.encode() if isinstance(x, str) else x for x in output)
            ledger = [call.args[2] for call in self.ledger.await_args_list
                      if call.args[0] == SESSION + str(n)]
            results.append(dict(raw=raw, types=[type(x).__name__ for x in output],
                                exception=exceptions[n], ledger=ledger, **parsed(raw)))
        return results


async def capture(path, s):
    with Harness() as harness:
        return (await harness.run(path, [s]))[0]


class EncGuards(unittest.IsolatedAsyncioTestCase):
    maxDiff = 1800

    def eq(self, arm, check, actual, expected):
        with self.subTest(arm=arm, check=check):
            self.assertEqual(actual, expected)

    def sound(self, arm, result, bytes_only=True):
        self.eq(arm, 'no_exception', result['exception'], None)
        self.eq(arm, 'no_error_event', result['errors'], [])
        if bytes_only:
            self.eq(arm, 'chunk_types_bytes', set(result['types']), {'bytes'})
        self.eq(arm, 'done_exactly_once', result['events'].count('[DONE]'), 1)
        self.eq(arm, 'done_last', result['events'][-1:] == ['[DONE]'], True)

    async def test_T_ENC_00_fixture(self):
        for fmt in ('openai', 'anthropic'):
            for char, cut in CUTS:
                s = positioned(fmt, char, cut)
                arm = fmt + '/' + s['name']
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=s['raw']))) as c:
                    async with c.stream('GET', 'https://fixture.example') as response:
                        chunks = [x async for x in response.aiter_bytes(chunk_size=256)]
                self.eq(arm, 'first_chunk_256', len(chunks[0]), 256)
                self.eq(arm, 'designed_offset', s['offset'] % 256, 256 - cut)
                self.eq(arm, 'target_at_offset', s['raw'][s['offset']:s['offset'] + len(char.encode())], char.encode())
                self.eq(arm, 'utf8_valid', s['raw'].decode().encode(), s['raw'])
                self.eq(arm, 'chunks_reassemble', b''.join(chunks), s['raw'])

    async def crossings(self, path):
        fmt = 'openai' if path == 'P-O' else 'anthropic'
        for char, cut in CUTS:
            s = positioned(fmt, char, cut)
            arm = path + '/' + s['name']
            result = await capture(path, s)
            self.sound(arm, result)
            self.eq(arm, 'client_text', result['text'], s['expected'])
            if path != 'A-direct':
                self.eq(arm, 'ledger_text', result['ledger'], [s['expected']])

    async def test_T_ENC_01_openai(self):
        await self.crossings('P-O')

    async def test_T_ENC_02_adapter(self):
        await self.crossings('A-direct')

    async def test_T_ENC_03_anthropic_e2e(self):
        await self.crossings('P-A')

    async def test_T_ENC_04_long(self):
        for path in PATHS:
            s = long_spec('openai' if path == 'P-O' else 'anthropic')
            result = await capture(path, s)
            self.eq(path, 'four_boundary_cuts', len(split_offsets(s['raw'])), 4)
            self.sound(path, result)
            self.eq(path, 'client_text', result['text'], s['expected'])
            if path != 'A-direct':
                self.eq(path, 'ledger_text', result['ledger'], [s['expected']])

    async def test_T_ENC_05_golden(self):
        for path in PATHS:
            for name in ('ascii', 'aligned-chinese'):
                arm = path + '/' + name
                s = golden_spec('openai' if path == 'P-O' else 'anthropic', name)
                result = await capture(path, s)
                self.eq(arm, 'no_split_character', split_offsets(s['raw']), [])
                if name == 'aligned-chinese':
                    self.eq(arm, 'event_separator_at_256', s['raw'][254:256], b'\n\n')
                self.sound(arm, result)
                self.eq(arm, 'client_text', result['text'], s['expected'])
                self.eq(arm, 'baseline_sha256', hashlib.sha256(result['raw']).hexdigest(), GOLDEN.get(arm))

    async def test_T_ENC_06_ignore_tail(self):
        for path in PATHS:
            for name in ('invalid-byte', 'truncated-tail'):
                s = malformed_spec('openai' if path == 'P-O' else 'anthropic', name)
                arm = path + '/' + name
                result = await capture(path, s)
                self.sound(arm, result)
                self.eq(arm, 'client_text', result['text'], s['expected'])

    async def test_T_ENC_07_interleaved(self):
        for path in ('P-O', 'A-direct'):
            fmt = 'openai' if path == 'P-O' else 'anthropic'
            specs = [interleaved_spec(fmt, c) for c in ('好', '✓')]
            for label, s in zip(('A', 'B'), specs):
                self.eq(path + '/' + label, 'four_partial_full_chunks', split_offsets(s['raw']), [256, 512, 768, 1024])
            with Harness() as harness:
                concurrent = await harness.run(path, specs, interleave=True)
                trace = list(harness.reads)
            self.eq(path + '/schedule', 'real_read_blocks_alternate',
                    trace[:8], [('0', 256), ('1', 256)] * 4)
            # Keep the same request/session labels and deterministic UUID in both runs.
            with Harness() as harness:
                isolated = await harness.run(path, specs, interleave=False)
            for n, label in enumerate(('A', 'B')):
                arm = path + '/' + label
                self.sound(arm, concurrent[n])
                self.sound(arm + '/isolated', isolated[n])
                self.eq(arm, 'interleaved_equals_isolated', concurrent[n]['raw'], isolated[n]['raw'])

    async def test_T_ENC_08_tools(self):
        for path, fmt in (('T-O', 'openai'), ('T-A', 'anthropic')):
            s = spec(fmt, 'tools', b'', '✓好🥝é' + LONG)
            result = await capture(path, s)
            self.sound(path, result, bytes_only=False)
            self.eq(path, 'client_text', result['text'], s['expected'])
            self.eq(path, 'ledger_text', result['ledger'], [s['expected']])


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EncGuards)
    result = unittest.TextTestRunner(verbosity=2, resultclass=old.EvidenceResult).run(suite)
    arms = {}
    for row in result.rows:
        key = (row['guard'], row['arm'])
        arm = arms.setdefault(key, dict(guard=key[0], arm=key[1], status='PASS', failures=[]))
        if row['status'] != 'PASS':
            arm['status'] = 'ERROR' if row['status'] == 'ERROR' else ('FAIL' if arm['status'] != 'ERROR' else 'ERROR')
            arm['failures'].append(row['assertion'])
    counts = {s: sum(r['status'] == s for r in arms.values()) for s in ('PASS', 'FAIL', 'ERROR')}
    assertions = {s: sum(r['status'] == s for r in result.rows) for s in ('PASS', 'FAIL', 'ERROR')}
    report = dict(ticket='ENC-01', baseline=BASE, groups_run=result.testsRun, counts=counts,
                  assertion_counts=assertions, arms=list(arms.values()), assertions=result.rows,
                  errors=len(result.errors), failures=len(result.failures), golden=GOLDEN,
                  scope='real stream/adapter/session/finalization; fake HTTP/config/storage; no provider or database')
    path = os.environ.get('KIWI_ENC_01_REPORT')
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('SUMMARY ' + json.dumps(counts, sort_keys=True))
    print('assertion_counts ' + json.dumps(assertions, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
