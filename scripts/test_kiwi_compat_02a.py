#!/usr/bin/env python3
"""COMPAT-02-A v1.1.1: production emitters, SDK captures, immutable base golden.

Controlled tests only: fake config/storage/extraction/tool/model boundaries.
Real ASGI/session wrapper, stream functions, adapter, memory finalization and
notification predicate. No real database, provider or Dream job is contacted.
All captures are written before assertions. No golden-update mode is provided.
"""
import ast
import asyncio
import copy
import hashlib
import inspect
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import datetime
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
import test_kiwi_out_01 as old
import config
import httpx
import main as app
import security

BASE = '22d2c68d0811032e01a59d0afd2e29f94e7456ee'
MODEL, USER = 'compat02a-model', 'compat02a-user'
TEXT = 'hello'
DREAM = '<!--dream:trigger-->'
SESSION = 'auto-r-' + '0' * 31 + '1'
PRESET = {'type': 'fixture', 'name': 'preset', 'result': 'synthetic'}
HANDOFF = {'sourceId': 'fixture-source', 'sourceRev': 7}
ITEM = {'title': 'synthetic-title', 'content': 'synthetic-memory'}
PRIVATE = {'ev_session', 'ev_handoff', 'ev_tool', 'ev_memory', 'ev_dream'}
ANCHORS = [('_stream_with_tools', 'ev_handoff', 0),
           ('_stream_with_tools', 'ev_tool', 0),
           ('_stream_with_tools', 'ev_memory', 0),
           ('_stream_with_tools', 'ev_dream', 0),
           ('_stream_with_tools', 'ev_tool', 1),
           ('_simulate_stream', 'ev_tool', 0),
           ('_ev_session_frame', 'ev_session', 0),
           ('stream_and_capture', 'ev_handoff', 0),
           ('stream_and_capture', 'ev_tool', 0),
           ('stream_and_capture', 'ev_memory', 0),
           ('stream_and_capture', 'ev_dream', 0)]

# Frozen once from BASE; includes complete standard/DONE byte hashes and private
# payloads/absolute event positions. Never derive expected values from a mutant.
GOLDEN = {'P-anthropic-length': {'full_sha256': '356d158bb589ce6d8841b3234cf84c244b86d0c8c73bba6b59204a22a64aa081',
                        'private': [],
                        'standard_sha256': '356d158bb589ce6d8841b3234cf84c244b86d0c8c73bba6b59204a22a64aa081'},
 'P-anthropic-stop': {'full_sha256': 'b485e4471ed26783c2a7f2eeb6b9326fc018c672be7cba593f786338b3dde9c6',
                      'private': [],
                      'standard_sha256': 'b485e4471ed26783c2a7f2eeb6b9326fc018c672be7cba593f786338b3dde9c6'},
 'P-openai-length': {'full_sha256': '488bdca97a55568d8b989c6ccb781cf3a2cdb1bb46c795ff622e5a925bfe4c23',
                     'private': [],
                     'standard_sha256': '488bdca97a55568d8b989c6ccb781cf3a2cdb1bb46c795ff622e5a925bfe4c23'},
 'P-openai-stop': {'full_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac',
                   'private': [],
                   'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'P-v0-all': {'full_sha256': '0d936c3c68c545f8a3348005a8cc87b6795c715a5c0f827476aae0fa5d670560',
              'private': [{'key': 'ev_handoff',
                           'payload': {'sourceId': 'fixture-source', 'sourceRev': 7},
                           'position': 0},
                          {'key': 'ev_tool',
                           'payload': {'name': 'preset', 'result': 'synthetic', 'type': 'fixture'},
                           'position': 1},
                          {'key': 'ev_memory',
                           'payload': {'action': 'extract',
                                       'contradictions': 0,
                                       'items': [{'content': 'synthetic-memory', 'title': 'synthetic-title'}],
                                       'saved': 1,
                                       'skipped': 0,
                                       'total': 1},
                           'position': 4},
                          {'key': 'ev_dream', 'payload': {'triggered': True}, 'position': 5}],
              'standard_sha256': 'd9a3d2546d8bc994397549872f5bea04d3715714a606ca2c94fa8b12fa32bfd1'},
 'P-v0-dream': {'full_sha256': 'facdddc4b819b8893aa6a8da28be0bada532240c39e3dad337ab717f3f9333d7',
                'private': [{'key': 'ev_dream', 'payload': {'triggered': True}, 'position': 2}],
                'standard_sha256': 'd9a3d2546d8bc994397549872f5bea04d3715714a606ca2c94fa8b12fa32bfd1'},
 'P-v0-handoff': {'full_sha256': '4f62326e424f7bb9a9c8e556838a1380ccc142a8a9eec7f3cb2ed892e7fe4172',
                  'private': [{'key': 'ev_handoff',
                               'payload': {'sourceId': 'fixture-source', 'sourceRev': 7},
                               'position': 0}],
                  'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'P-v0-memory': {'full_sha256': '69a107207cebc9383c6a936276c340192f7ff97f8780be8944d9f498427c2e4d',
                 'private': [{'key': 'ev_memory',
                              'payload': {'action': 'extract',
                                          'contradictions': 0,
                                          'items': [{'content': 'synthetic-memory', 'title': 'synthetic-title'}],
                                          'saved': 1,
                                          'skipped': 0,
                                          'total': 1},
                              'position': 2}],
                 'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'P-v0-plain': {'full_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac',
                'private': [],
                'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'P-v0-tool': {'full_sha256': '4eebff7737d620a876159b95f67c18f2d91fae408d86208d0520ffe88c6bf016',
               'private': [{'key': 'ev_tool',
                            'payload': {'name': 'preset', 'result': 'synthetic', 'type': 'fixture'},
                            'position': 0}],
               'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'P-v1-all': {'full_sha256': '649dda00153e5ce49821176f5e313f79f5fa573bf3fa8959b81cfe9098860602',
              'private': [{'key': 'ev_session',
                           'payload': {'generated': True, 'id': 'auto-r-00000000000000000000000000000001'},
                           'position': 0},
                          {'key': 'ev_handoff',
                           'payload': {'sourceId': 'fixture-source', 'sourceRev': 7},
                           'position': 1},
                          {'key': 'ev_tool',
                           'payload': {'name': 'preset', 'result': 'synthetic', 'type': 'fixture'},
                           'position': 2},
                          {'key': 'ev_memory',
                           'payload': {'action': 'extract',
                                       'contradictions': 0,
                                       'items': [{'content': 'synthetic-memory', 'title': 'synthetic-title'}],
                                       'saved': 1,
                                       'skipped': 0,
                                       'total': 1},
                           'position': 5},
                          {'key': 'ev_dream', 'payload': {'triggered': True}, 'position': 6}],
              'standard_sha256': 'd9a3d2546d8bc994397549872f5bea04d3715714a606ca2c94fa8b12fa32bfd1'},
 'P-v1-dream': {'full_sha256': '4a810767d819fc1631f7955dd2633e6f8c3285d5eb858bcc496b0acc769b5279',
                'private': [{'key': 'ev_session',
                             'payload': {'generated': True, 'id': 'auto-r-00000000000000000000000000000001'},
                             'position': 0},
                            {'key': 'ev_dream', 'payload': {'triggered': True}, 'position': 3}],
                'standard_sha256': 'd9a3d2546d8bc994397549872f5bea04d3715714a606ca2c94fa8b12fa32bfd1'},
 'P-v1-extract-failed': {'full_sha256': 'aaec641769e2ea731e831599462ebae1aaef02a81944876005bb39869058af56',
                         'private': [{'key': 'ev_session',
                                      'payload': {'generated': True,
                                                  'id': 'auto-r-00000000000000000000000000000001'},
                                      'position': 0},
                                     {'key': 'ev_memory',
                                      'payload': {'action': 'extract_failed',
                                                  'reason': 'synthetic_failure',
                                                  'saved': 0},
                                      'position': 3}],
                         'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'P-v1-handoff': {'full_sha256': '05960a13659e3b678ac06bac8bbeadea3a43199467511ff31160844b14ded717',
                  'private': [{'key': 'ev_session',
                               'payload': {'generated': True, 'id': 'auto-r-00000000000000000000000000000001'},
                               'position': 0},
                              {'key': 'ev_handoff',
                               'payload': {'sourceId': 'fixture-source', 'sourceRev': 7},
                               'position': 1}],
                  'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'P-v1-memory': {'full_sha256': 'd5c8fcab3676b56574f6fa35fc3bf442d7c56b2d3df7ea77186d44e3aea1a2fb',
                 'private': [{'key': 'ev_session',
                              'payload': {'generated': True, 'id': 'auto-r-00000000000000000000000000000001'},
                              'position': 0},
                             {'key': 'ev_memory',
                              'payload': {'action': 'extract',
                                          'contradictions': 0,
                                          'items': [{'content': 'synthetic-memory', 'title': 'synthetic-title'}],
                                          'saved': 1,
                                          'skipped': 0,
                                          'total': 1},
                              'position': 3}],
                 'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'P-v1-plain': {'full_sha256': 'ccdcc70a10760128c7ae8ec9e51e9f76db595069c009b7dfdb915c1dc1e56a04',
                'private': [{'key': 'ev_session',
                             'payload': {'generated': True, 'id': 'auto-r-00000000000000000000000000000001'},
                             'position': 0}],
                'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'P-v1-tool': {'full_sha256': '3b73bb170bc6e96e12387845447c348b1b64aeefca7a21fa1dc793079a677f40',
               'private': [{'key': 'ev_session',
                            'payload': {'generated': True, 'id': 'auto-r-00000000000000000000000000000001'},
                            'position': 0},
                           {'key': 'ev_tool',
                            'payload': {'name': 'preset', 'result': 'synthetic', 'type': 'fixture'},
                            'position': 1}],
               'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'T-control': {'full_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592',
               'private': [],
               'standard_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592'},
 'T-v0-all': {'full_sha256': '9daec2bf6acbaad0bf6c92911e7d82066ee186d4b8c10d2b5a7f589b020d0a53',
              'private': [{'key': 'ev_handoff',
                           'payload': {'sourceId': 'fixture-source', 'sourceRev': 7},
                           'position': 0},
                          {'key': 'ev_tool',
                           'payload': {'name': 'preset', 'result': 'synthetic', 'type': 'fixture'},
                           'position': 1},
                          {'key': 'ev_tool',
                           'payload': {'arguments': {},
                                       'name': '_gateway_list_reminders',
                                       'result': 'synthetic-tool-result',
                                       'type': 'tool_call'},
                           'position': 2},
                          {'key': 'ev_memory',
                           'payload': {'action': 'extract',
                                       'contradictions': 0,
                                       'items': [{'content': 'synthetic-memory', 'title': 'synthetic-title'}],
                                       'saved': 1,
                                       'skipped': 0,
                                       'total': 1},
                           'position': 6},
                          {'key': 'ev_dream', 'payload': {'triggered': True}, 'position': 7}],
              'standard_sha256': 'c5ffeabbb1be38a1afa009e0f653f448c7176b909a6ff4e162c38756afd48e75'},
 'T-v0-dream': {'full_sha256': 'd9db9f12265862b14ce80b1dfea59f2d4a96b1d84acd613adefc677c5fa1643c',
                'private': [{'key': 'ev_tool',
                             'payload': {'arguments': {},
                                         'name': '_gateway_list_reminders',
                                         'result': 'synthetic-tool-result',
                                         'type': 'tool_call'},
                             'position': 0},
                            {'key': 'ev_dream', 'payload': {'triggered': True}, 'position': 4}],
                'standard_sha256': 'c5ffeabbb1be38a1afa009e0f653f448c7176b909a6ff4e162c38756afd48e75'},
 'T-v0-memory': {'full_sha256': 'e67c44c84238d76cd1b911c983477b498ff5c6dd5d5e2a92cf0c35e359501123',
                 'private': [{'key': 'ev_tool',
                              'payload': {'arguments': {},
                                          'name': '_gateway_list_reminders',
                                          'result': 'synthetic-tool-result',
                                          'type': 'tool_call'},
                              'position': 0},
                             {'key': 'ev_memory',
                              'payload': {'action': 'extract',
                                          'contradictions': 0,
                                          'items': [{'content': 'synthetic-memory', 'title': 'synthetic-title'}],
                                          'saved': 1,
                                          'skipped': 0,
                                          'total': 1},
                              'position': 3}],
                 'standard_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592'},
 'T-v1-all': {'full_sha256': '9da0101151d8e08b3d1951fc8370090aceaefe2da4ccc73292522decb28906b6',
              'private': [{'key': 'ev_session',
                           'payload': {'generated': True, 'id': 'auto-r-00000000000000000000000000000001'},
                           'position': 0},
                          {'key': 'ev_handoff',
                           'payload': {'sourceId': 'fixture-source', 'sourceRev': 7},
                           'position': 1},
                          {'key': 'ev_tool',
                           'payload': {'name': 'preset', 'result': 'synthetic', 'type': 'fixture'},
                           'position': 2},
                          {'key': 'ev_tool',
                           'payload': {'arguments': {},
                                       'name': '_gateway_list_reminders',
                                       'result': 'synthetic-tool-result',
                                       'type': 'tool_call'},
                           'position': 3},
                          {'key': 'ev_memory',
                           'payload': {'action': 'extract',
                                       'contradictions': 0,
                                       'items': [{'content': 'synthetic-memory', 'title': 'synthetic-title'}],
                                       'saved': 1,
                                       'skipped': 0,
                                       'total': 1},
                           'position': 7},
                          {'key': 'ev_dream', 'payload': {'triggered': True}, 'position': 8}],
              'standard_sha256': 'c5ffeabbb1be38a1afa009e0f653f448c7176b909a6ff4e162c38756afd48e75'},
 'T-v1-dream': {'full_sha256': '31abf44b0c57c13bc65dd10bcc31c087d1450b39ca3a3667edaf9ec80b7a84aa',
                'private': [{'key': 'ev_session',
                             'payload': {'generated': True, 'id': 'auto-r-00000000000000000000000000000001'},
                             'position': 0},
                            {'key': 'ev_tool',
                             'payload': {'arguments': {},
                                         'name': '_gateway_list_reminders',
                                         'result': 'synthetic-tool-result',
                                         'type': 'tool_call'},
                             'position': 1},
                            {'key': 'ev_dream', 'payload': {'triggered': True}, 'position': 5}],
                'standard_sha256': 'c5ffeabbb1be38a1afa009e0f653f448c7176b909a6ff4e162c38756afd48e75'},
 'T-v1-extract-failed': {'full_sha256': '19de69c2e0b9ffdd32fcb17ba013e392165bc2dcfb9aba07a0aee70bc30382cc',
                         'private': [{'key': 'ev_session',
                                      'payload': {'generated': True,
                                                  'id': 'auto-r-00000000000000000000000000000001'},
                                      'position': 0},
                                     {'key': 'ev_tool',
                                      'payload': {'arguments': {},
                                                  'name': '_gateway_list_reminders',
                                                  'result': 'synthetic-tool-result',
                                                  'type': 'tool_call'},
                                      'position': 1},
                                     {'key': 'ev_memory',
                                      'payload': {'action': 'extract_failed',
                                                  'reason': 'synthetic_failure',
                                                  'saved': 0},
                                      'position': 4}],
                         'standard_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592'},
 'T-v1-memory': {'full_sha256': 'f149570a0389848e5a76d8fb9899416f71f80de14551fa89e05374a0a8335b75',
                 'private': [{'key': 'ev_session',
                              'payload': {'generated': True, 'id': 'auto-r-00000000000000000000000000000001'},
                              'position': 0},
                             {'key': 'ev_tool',
                              'payload': {'arguments': {},
                                          'name': '_gateway_list_reminders',
                                          'result': 'synthetic-tool-result',
                                          'type': 'tool_call'},
                              'position': 1},
                             {'key': 'ev_memory',
                              'payload': {'action': 'extract',
                                          'contradictions': 0,
                                          'items': [{'content': 'synthetic-memory', 'title': 'synthetic-title'}],
                                          'saved': 1,
                                          'skipped': 0,
                                          'total': 1},
                              'position': 4}],
                 'standard_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592'},
 'entry-P-v0-explicit0': {'full_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac',
                          'private': [],
                          'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'entry-P-v0-explicit1': {'full_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac',
                          'private': [],
                          'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'entry-P-v1-explicit0': {'full_sha256': 'ccdcc70a10760128c7ae8ec9e51e9f76db595069c009b7dfdb915c1dc1e56a04',
                          'private': [{'key': 'ev_session',
                                       'payload': {'generated': True,
                                                   'id': 'auto-r-00000000000000000000000000000001'},
                                       'position': 0}],
                          'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'entry-P-v1-explicit1': {'full_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac',
                          'private': [],
                          'standard_sha256': '9f4554074885cb94b1cfd73c8378dbeaa6411089118ba567b254111320e876ac'},
 'entry-T-v0-explicit0': {'full_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592',
                          'private': [],
                          'standard_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592'},
 'entry-T-v0-explicit1': {'full_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592',
                          'private': [],
                          'standard_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592'},
 'entry-T-v1-explicit0': {'full_sha256': '42dd40770de0d26efc9be0c928e01831151de068f4ef7d9cf2757f1d04935adb',
                          'private': [{'key': 'ev_session',
                                       'payload': {'generated': True,
                                                   'id': 'auto-r-00000000000000000000000000000001'},
                                       'position': 0}],
                          'standard_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592'},
 'entry-T-v1-explicit1': {'full_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592',
                          'private': [],
                          'standard_sha256': '837791e0ae80b7820ad5dfe536bf40d8c3800b6b0accc4591eb4fd794bf69592'},
 'simulate': {'full_sha256': 'f9c1886747ab31a537ff1fae0b0eabb3954736e77ebe9432c65e7e4176ac528a',
              'private': [{'key': 'ev_tool',
                           'payload': {'name': 'preset', 'result': 'synthetic', 'type': 'fixture'},
                           'position': 0}],
              'standard_sha256': '52a988197e07ce83a8ff27cf566d49c92cb9517e5316dbd57e1ef9f9e81e3ca8'}}


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 4, 12, 0, 0, tzinfo=tz)


def spec(identifier, path='P', v2=False, kind='plain', fmt='openai', **kw):
    return dict(id=identifier, path=path, v2=v2, kind=kind, fmt=fmt,
                memory=kind in ('memory', 'all', 'extract-failed'),
                dream=kind in ('dream', 'all'), preset=kind in ('tool', 'all'),
                handoff=kind in ('handoff', 'all'),
                rounds=1 if path == 'T' and kind != 'plain' else 0,
                finish='stop', sdk=False, entry=False, **kw)


SPECS = []
for route, kinds in [('P', ('plain', 'memory', 'dream', 'tool', 'handoff', 'all')),
                     ('T', ('memory', 'dream', 'all'))]:
    for enabled in (False, True):
        for kind in kinds:
            s = spec(f'{route}-v{int(enabled)}-{kind}', route, enabled, kind)
            s['sdk'] = True
            SPECS.append(s)
for route in ('P', 'T'):
    SPECS.append(spec(f'{route}-v1-extract-failed', route, True, 'extract-failed'))
    for enabled in (False, True):
        for explicit in (False, True):
            s = spec(f'entry-{route}-v{int(enabled)}-explicit{int(explicit)}', route, enabled)
            s.update(entry=True, explicit=explicit)
            SPECS.append(s)
SPECS.extend([spec('T-control', 'T'), spec('simulate', 'S', kind='tool')])
for fmt in ('openai', 'anthropic'):
    for finish in ('stop', 'length'):
        s = spec(f'P-{fmt}-{finish}', fmt=fmt)
        s['finish'] = finish
        SPECS.append(s)


def packets(raw):
    return [x + b'\n\n' for x in raw.split(b'\n\n') if x]


def decoded(raw):
    out = []
    for frame in packets(raw):
        data = frame.decode('utf-8').removeprefix('data: ').strip()
        out.append('[DONE]' if data == '[DONE]' else json.loads(data))
    return out


def private_rows(raw):
    return [dict(key=key, position=i, payload=data[key])
            for i, data in enumerate(decoded(raw)) if isinstance(data, dict)
            for key in data if key.startswith('ev_')]


def standard(raw):
    return b''.join(frame for frame, data in zip(packets(raw), decoded(raw))
                    if not isinstance(data, dict) or not any(k.startswith('ev_') for k in data))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def expected_keys(s):
    keys = []
    if s['v2'] and not s.get('explicit'):
        keys.append('ev_session')
    if s['handoff']:
        keys.append('ev_handoff')
    if s['preset']:
        keys.append('ev_tool')
    if s['path'] == 'T':
        keys += ['ev_tool'] * s['rounds']
    if s['memory']:
        keys.append('ev_memory')
    if s['dream']:
        keys.append('ev_dream')
    return keys


def upstream_sse(s):
    text = TEXT + (DREAM if s['dream'] else '')
    if s['fmt'] == 'openai':
        meta = dict(id='fixture-upstream', model=MODEL, created=1)
        events = [dict(meta, choices=[dict(index=0, delta={'content': text}, finish_reason=None)]),
                  dict(meta, choices=[dict(index=0, delta={}, finish_reason=s['finish'])])]
        return ''.join('data: ' + json.dumps(e) + '\n\n' for e in events) + 'data: [DONE]\n\n'
    return old.sse('anthropic').replace('"ok"', json.dumps(text)).replace(
        '"end_turn"', '"max_tokens"' if s['finish'] == 'length' else '"end_turn"')


async def capture(s):
    values = {'memory_enabled': str(s['memory']).lower(), 'session_identity_v2_enabled': str(s['v2']).lower(),
              'reminder_tools_enabled': 'false', 'tool_drawer_enabled': 'false', 'mcp_mode': 'off',
              'web_search_mode': 'off', 'prompt_cache_enabled': 'false', 'reasoning_effort': 'off',
              'memory_event_ledger_write_enabled': 'true'}
    pool = old.fixture.ConfigPool(values)
    fmt = s['fmt']
    url = 'https://anthropic.example/v1' if fmt == 'anthropic' else 'https://relay.example/v1'
    row = dict(id=7, provider_id=7, name='fixture', provider_name='fixture', api_base_url=url,
               api_key='synthetic-key', api_format=fmt, enabled=True)
    requests, tasks, chunk_types = [], [], []
    real_client = httpx.AsyncClient
    execute = AsyncMock(return_value=('synthetic-tool-result', {}))
    ledger = AsyncMock(return_value={'path': 'inserted'})
    extract = AsyncMock(return_value=('extract_failed', [], 0, 0, 'synthetic_failure')
                        if s['kind'] == 'extract-failed' else ('extract', [ITEM], 0, 0, None))
    dream_job = AsyncMock()
    def upstream(req):
        body = json.loads(req.content)
        requests.append(body)
        if body.get('stream'):
            return httpx.Response(200, text=upstream_sse(s), headers={'content-type': 'text/event-stream'})
        tool = len(requests) <= s['rounds']
        msg = {'role': 'assistant', 'content': None if tool else TEXT + (DREAM if s['dream'] else '')}
        if tool:
            msg['tool_calls'] = [dict(id='call-fixture', type='function', function={
                'name': '_gateway_list_reminders', 'arguments': '{}'})]
        return httpx.Response(200, json={'id': 'fixture', 'choices': [{'message': msg,
            'finish_reason': 'tool_calls' if tool else 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})
    def outbound(**kw):
        return real_client(transport=httpx.MockTransport(upstream), **kw)
    def spawn(coro):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task
    with ExitStack() as stack:
        stack.enter_context(redirect_stdout(io.StringIO()))
        stack.enter_context(redirect_stderr(io.StringIO()))
        # Keep library diagnostics inside the synthetic fixture too.
        for logger in (logging.getLogger(), logging.getLogger('httpx'), logging.getLogger('mcp')):
            saved = logger.disabled
            logger.disabled = True
            stack.callback(setattr, logger, 'disabled', saved)
        stack.enter_context(patch.object(config, 'get_pool', AsyncMock(return_value=pool)))
        for name, value in {'resolve_scope_snapshot': (True, None, 'global', None, None),
            'get_reset_generation': 0, 'get_memory_enabled': s['memory'],
            'get_active_system_prompt': 'synthetic-persona', 'resolve_provider_for_model': row,
            'build_system_prompt_with_memories': ('synthetic-persona', {}),
            'get_extract_interval': 1, 'search_memories': [], 'get_recent_memories': [],
            'get_all_categories': [], 'get_all_memories_count': 1}.items():
            stack.enter_context(patch.object(app, name, AsyncMock(return_value=value)))
        for name, value in {'append_turn_events_atomic': ledger, '_extract_and_save_batch': extract,
            '_execute_gateway_tool': execute, '_spawn_background_task': spawn,
            '_dream_fallback_after_grace': dream_job, '_conversation_counter': 0,
            '_counter_lock': asyncio.Lock(), 'datetime': Clock}.items():
            stack.enter_context(patch.object(app, name, value))
        uuid_values = iter(uuid.UUID(int=n) for n in range(1, 100))
        stack.enter_context(patch.object(uuid, 'uuid4', side_effect=lambda: next(uuid_values)))
        stack.enter_context(patch.object(httpx, 'AsyncClient', outbound))
        if s['entry']:
            body = {'model': MODEL, 'messages': [{'role': 'user', 'content': USER}], 'stream': True}
            if s.get('explicit'):
                body['conversation_id'] = 'explicit-fixture'
            # Entry T selected via actual registered tool configuration.
            pool.values['reminder_tools_enabled'] = str(s['path'] == 'T').lower()
            async with real_client(transport=httpx.ASGITransport(app=app.app), base_url='http://localhost') as c:
                response = await c.post('/v1/chat/completions', json=body)
            raw, headers, status = response.content, dict(response.headers), response.status_code
        else:
            messages = [{'role': 'user', 'content': USER}]
            presets = [copy.deepcopy(PRESET)] if s['preset'] else []
            meta = {'handoff': copy.deepcopy(HANDOFF)} if s['handoff'] else {}
            shared = dict(api_url=url + ('/messages' if fmt == 'anthropic' else '/chat/completions'),
                          api_key='synthetic-key', api_format=fmt, prompt_meta=meta,
                          record_events=s['memory'], extract_enabled=s['memory'])
            if s['path'] == 'T':
                tools = [{'type': 'function', 'function': {'name': '_gateway_list_reminders',
                         'parameters': {'type': 'object', 'properties': {}}}}] if s['rounds'] else []
                tool_map = {'_gateway_list_reminders': {'type': 'gateway_builtin', 'handler': 'reminder'}}
                inner = app._stream_with_tools(messages, tools, tool_map, MODEL, 0.7, presets,
                    SESSION, USER, s['memory'], **shared)
            elif s['path'] == 'S':
                inner = app._simulate_stream(TEXT, MODEL, presets)
            else:
                inner = app.stream_and_capture({}, {'model': MODEL, 'messages': messages, 'stream': True},
                    SESSION, USER, MODEL, tool_events=presets, mem_enabled=s['memory'], **shared)
            async def typed():
                async for chunk in inner:
                    chunk_types.append(type(chunk).__name__)
                    yield chunk
            chunks = [c async for c in app._with_ev_session(typed(), SESSION, s['v2'])]
            raw = b''.join(c.encode('utf-8') if isinstance(c, str) else c for c in chunks)
            headers, status = {}, 200
        if tasks:
            await asyncio.gather(*tasks)
    return dict(raw=raw, headers=headers, status=status, types=chunk_types,
                request_count=len(requests), tool_calls=execute.await_count,
                ledger_calls=ledger.await_count, extract_calls=extract.await_count,
                dream_calls=dream_job.await_count)


async def collect():
    return {s['id']: await capture(s) for s in SPECS}


def manifest_for(captures):
    # Expectations originate in the committed golden and explicit specs, never
    # from the candidate's observed events (which might be absent under a knife).
    return [dict(id=s['id'], file=s['id'] + '.sse', expect_ok=True,
                 expect_text=TEXT + (DREAM if s['dream'] else ''), expect_finish='stop',
                 expect_private=[{'key': p['key'], 'position': p['position']}
                                 for p in GOLDEN[s['id']]['private']])
            for s in SPECS if s['sdk']]


def validate_manifest(rows):
    required = {'id', 'file', 'expect_ok', 'expect_text', 'expect_finish', 'expect_private'}
    expected = {s['id'] for s in SPECS if s['sdk']}
    return (isinstance(rows, list) and bool(rows)
            and all(isinstance(r, dict) and required <= r.keys() and isinstance(r['expect_private'], list)
                    for r in rows)
            and len(rows) == len(expected) and {r['id'] for r in rows} == expected)


CAPTURES = {}
MANIFEST = []


class CompatGuards(unittest.IsolatedAsyncioTestCase):
    def equal(self, arm, check, actual, expected):
        with self.subTest(arm=arm, check=check):
            self.assertEqual(actual, expected)

    def test_T_C2A_00_static(self):
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        found = {}
        for fn in tree.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            counts = {}
            for n in sorted(ast.walk(fn), key=lambda n: getattr(n, 'lineno', 0)):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == 'json'
                        and n.func.attr == 'dumps' and n.args and isinstance(n.args[0], ast.Dict)):
                    continue
                d = n.args[0]
                keys = [k.value if isinstance(k, ast.Constant) else None for k in d.keys]
                for key in keys:
                    if isinstance(key, str) and key.startswith('ev_'):
                        ordinal = counts.get(key, 0); counts[key] = ordinal + 1
                        found[(fn.name, key, ordinal)] = (keys, d)
        self.equal('inventory', 'eleven-producer-identities', set(found), set(ANCHORS))
        for anchor in ANCHORS:
            keys, d = found.get(anchor, ([], None))
            valid = keys == [anchor[1], 'choices'] and isinstance(d.values[1], ast.List) and not d.values[1].elts
            self.equal('/'.join(map(str, anchor)), 'two-keys-empty-choices', valid, True)
        self.equal('error', 'error-payload-no-choices', 'choices' in security.stable_payload('http_502'), False)

    def test_T_C2A_01_dynamic(self):
        for s in SPECS:
            ident = s['id']; c = CAPTURES[ident]; baseline = GOLDEN[ident]
            events = decoded(c['raw'])
            self.equal(ident, 'event-order-counts', [p['key'] for p in private_rows(c['raw'])], expected_keys(s))
            self.equal(ident, 'event-positions', [(p['key'], p['position']) for p in private_rows(c['raw'])],
                       [(p['key'], p['position']) for p in baseline['private']])
            for ordinal, expected in enumerate(baseline['private']):
                arm = f'{ident}/{ordinal}-{expected["key"]}'
                event = events[expected['position']] if len(events) > expected['position'] else {}
                event = event if isinstance(event, dict) else {}
                self.equal(arm, 'a-keys-exact', list(event) == [expected['key'], 'choices']
                           and event.get('choices') == [], True)
                self.equal(arm, 'b-payload-equal', event.get(expected['key']), expected['payload'])
            self.equal(ident, 'd-standard-done-bytes', sha(standard(c['raw'])), baseline['standard_sha256'])
            self.equal(ident, 'done-once-last', (events.count('[DONE]'), events[-1]), (1, '[DONE]'))
            self.equal(ident, 'http-status', c['status'], 200)
            if s['entry']:
                self.equal(ident, 'e-session-header', c['headers'].get('x-kiwi-session-id'),
                           SESSION if s['v2'] and not s.get('explicit') else None)
            else:
                self.equal(ident, 'producer-types', set(c['types']), {'bytes'} if s['path'] == 'P' else {'str'})
            self.equal(ident, 'tool-executions', c['tool_calls'], s['rounds'])
            self.equal(ident, 'real-memory-extraction-reached', c['extract_calls'], int(s['memory']))
            self.equal(ident, 'dream-boundary-reached', c['dream_calls'], int(s['dream']))

    def test_T_C2A_02_schema(self):
        self.equal('manifest', 'complete-unique-required-fields', validate_manifest(MANIFEST), True)
        for label, bad in [('empty', []), ('duplicate', MANIFEST + MANIFEST[:1]),
                           ('missing-field', [{k:v for k,v in r.items() if k != 'expect_private'} for r in MANIFEST])]:
            self.equal('manifest-' + label, 'invalid-rejected', validate_manifest(bad), False)
        for row in MANIFEST:
            events = [e for e in decoded(CAPTURES[row['id']]['raw']) if isinstance(e, dict) and 'error' not in e]
            self.equal(row['id'], 'choices-array-every-event', all(isinstance(e.get('choices'), list) for e in events), True)
            self.equal(row['id'], 'expected-private-occurrences',
                       [{'key': p['key'], 'position': p['position']} for p in private_rows(CAPTURES[row['id']]['raw'])],
                       row['expect_private'])

    async def test_T_C2A_03_errors(self):
        for name, exc, code in [('upstream', security.UpstreamFailure('http_502'), 'http_502'),
                                 ('internal', RuntimeError('synthetic'), 'internal_error')]:
            for enabled in (False, True):
                async def broken():
                    raise exc
                    yield b''
                with redirect_stdout(io.StringIO()):
                    chunks = [c async for c in app._with_ev_session(broken(), SESSION, enabled)]
                events = decoded(b''.join(chunks)); arm = f'{name}-v{int(enabled)}'
                self.equal(arm, 'error-shape-frozen', events[-2], {'error': code, 'error_code': code})
                self.equal(arm, 'done-last', events[-1], '[DONE]')
                self.equal(arm, 'event-count', len(events), 3 if enabled else 2)
                self.equal(arm, 'session-first', events[0].get('ev_session') if enabled else None,
                           {'id': SESSION, 'generated': True} if enabled else None)
            # Same stable_error HTTP boundary used by the nonstream error exits.
            r = security.stable_error(exc)
            self.equal(name + '-nonstream', 'status', r.status_code, 502 if name == 'upstream' else 500)
            self.equal(name + '-nonstream', 'body', json.loads(r.body), {'error': code, 'error_code': code})

    def test_T_C2A_04_payloads(self):
        seen = set()
        for s in SPECS:
            ident = s['id']; raw = CAPTURES[ident]['raw']
            self.equal(ident, 'callback-payloads', private_rows(raw), GOLDEN[ident]['private'])
            for index, event in enumerate(decoded(raw)):
                if isinstance(event, dict) and any(k.startswith('ev_') for k in event):
                    seen.update(k for k in event if k.startswith('ev_'))
                    self.equal(f'{ident}/{index}', 'no-unrelated-top-level-keys', set(event) - PRIVATE - {'choices'}, set())
        self.equal('inventory', 'five-event-names', seen, PRIVATE)

    def test_T_C2A_05_finish(self):
        for fmt in ('openai', 'anthropic'):
            for finish in ('stop', 'length'):
                ident = f'P-{fmt}-{finish}'; raw = CAPTURES[ident]['raw']
                if fmt == 'openai':
                    s = next(s for s in SPECS if s['id'] == ident)
                    self.equal(ident, 'canonical-upstream-bytes', raw, upstream_sse(s).encode())
                self.equal(ident, 'adapter-baseline-bytes', sha(raw), GOLDEN[ident]['full_sha256'])
                reasons = [c.get('finish_reason') for e in decoded(raw) if isinstance(e, dict)
                           for c in (e.get('choices') if isinstance(e.get('choices'), list) else [])
                           if c.get('finish_reason')]
                self.equal(ident, 'finish-preserved', reasons, [finish])
        for s in SPECS:
            if s['path'] == 'T':
                reasons = [c.get('finish_reason') for e in decoded(CAPTURES[s['id']]['raw']) if isinstance(e, dict)
                           for c in (e.get('choices') if isinstance(e.get('choices'), list) else [])
                           if c.get('finish_reason')]
                self.equal(s['id'], 'existing-tool-finish-stop', reasons, ['stop'])

    def test_T_C2A_06_golden(self):
        for s in SPECS:
            ident = s['id']; raw = CAPTURES[ident]['raw']
            self.equal(ident, 'standard-golden-sha256', sha(standard(raw)), GOLDEN[ident]['standard_sha256'])
            if not expected_keys(s):
                self.equal(ident, 'entire-control-golden-sha256', sha(raw), GOLDEN[ident]['full_sha256'])

    def test_T_C2A_07_substring(self):
        for fn in (app._stream_with_tools, app.stream_and_capture):
            src = inspect.getsource(fn)
            self.equal(fn.__name__, 'handoff-frozen-substring', "'ev_handoff': prompt_meta['handoff']" in src, True)
            self.equal(fn.__name__, 'no-source-revision-reread', 'source_rev' in src, False)


def main():
    global CAPTURES, MANIFEST
    CAPTURES = asyncio.run(collect())
    MANIFEST = manifest_for(CAPTURES)
    folder = Path(os.environ.get('KIWI_COMPAT_02A_CAPTURE_DIR') or tempfile.mkdtemp(prefix='kiwi-c2a-captures-'))
    folder.mkdir(parents=True, exist_ok=True)
    # Finish every capture before any test can fail. Extra regression captures
    # stay outside this success-only SDK manifest/directory.
    for row in MANIFEST:
        (folder / row['file']).write_bytes(CAPTURES[row['id']]['raw'])
    (folder / 'manifest.json').write_text(json.dumps(MANIFEST, indent=2) + '\n', encoding='utf-8')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CompatGuards)
    result = unittest.TextTestRunner(verbosity=2, resultclass=old.EvidenceResult).run(suite)
    arms = {}
    for row in result.rows:
        key = (row['guard'], row['arm'])
        arm = arms.setdefault(key, dict(guard=key[0], arm=key[1], status='PASS', failures=[]))
        if row['status'] != 'PASS':
            arm['status'] = 'ERROR' if row['status'] == 'ERROR' or arm['status'] == 'ERROR' else 'FAIL'
            arm['failures'].append(row['assertion'])
    counts = {s: sum(r['status'] == s for r in arms.values()) for s in ('PASS', 'FAIL', 'ERROR')}
    assertions = {s: sum(r['status'] == s for r in result.rows) for s in ('PASS', 'FAIL', 'ERROR')}
    report = dict(ticket='COMPAT-02-A', baseline=BASE, groups_run=result.testsRun, counts=counts,
                  assertion_counts=assertions, arms=list(arms.values()), assertions=result.rows,
                  errors=len(result.errors), failures=len(result.failures), capture_count=len(MANIFEST),
                  scope='real emitters/session/ASGI/adapter/memory gates; fake storage/extraction/upstream/tools/Dream')
    path = os.environ.get('KIWI_COMPAT_02A_REPORT')
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('SUMMARY ' + json.dumps(counts, sort_keys=True))
    print('assertion_counts ' + json.dumps(assertions, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
