#!/usr/bin/env python3
"""COMPAT-02-B v1.4: disposable PostgreSQL, real entry/scope/ledger, fake providers.

Never uses ambient DATABASE_URL. No lifespan, external model, MCP or Dream jobs.
All assertions have stable IDs and baseline expectations; failures do not stop
later assertions. Goldens are captured only with BASE production blobs present.
"""
import argparse
import asyncio
import copy
import functools
import hashlib
import importlib
import inspect
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import httpx
import test_kiwi_safety_sync as dbtest

BASE = 'a1b01a4b50f27d27bd165a4b359b4497c97e303d'
MODEL, USER, TEXT = 'c2b-model', 'c2b-user', 'c2b-answer'
PERSONA, DREAM = 'C2B_PERSONA', '<!--dream:trigger-->'
HEADS = {'cid': 'X-Conversation-Id', 'sid': 'X-Session-ID', 'owc': 'X-OpenWebUI-Chat-Id'}
TOOL = {'type': 'function', 'function': {'name': '_gateway_list_reminders',
        'parameters': {'type': 'object', 'properties': {}}}}
CLIENT_TOOL = {'type': 'function', 'function': {'name': 'client_owned',
               'parameters': {'type': 'object', 'properties': {}}}}
TOOL_MAP = {'_gateway_list_reminders': {'type': 'gateway_builtin', 'handler': 'reminder'}}
FIELDS = ('session_id', 'role', 'content', 'model', 'project_id', 'scope_known', 'turn_key')
# Frozen on BASE; never updated by a normal test run.
GOLDEN = {
    'skip': {'body_sha': ['7e5433896eb9f2ac7146821a8349a747b069baaba61147a5c219001f52d28115'], 'ledger': []},
    'chat': {'body_sha': ['698b599169fa5e0f389ca9deea7db3194a9e9b1b0ba654b35c90e2edbe092451'],
             'ledger': [['c2b-chat', 'user', 'c2b-user', 'c2b-model', None, True, 'c2b-turn'],
                        ['c2b-chat', 'assistant', 'c2b-answer', 'c2b-model', None, True, 'c2b-turn']]},
}
ROWS, CAPTURES = [], {}
app = database = config = drawer = None


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 9, 12, 0, 0, tzinfo=tz)


def hdr(src, value):
    return 'hdr-' + src + '-' + hashlib.sha256(value.strip().encode()).hexdigest()[:24]


TAG_DICTIONARY = ('hdr-id', 'task-ledger', 'task-identity', 'row6',
                  'single-user-ledger', 'tool-collect', 'search', 'private-frames')


def assertion_tags(group, path, name):
    """Contract minimum memberships; semantics, not mutation outcomes, assign tags."""
    tags = set()
    if (group == 'T-01' and name in ('hdr_shape', 'source_segment', 'same_value_diff_header_diff_session')
        or group == 'T-02'
        or group == 'T-03' and name in ('bad_cid_falls_to_sid', 'dup_cid_first_valid')
        or group == 'T-04' and name == 'header_identity_is_hdr'
        or group == 'T-11' and name == 'hdr_identity'):
        tags.add('hdr-id')
    if (group == 'T-06' and name in ('ledger_zero_rows', 'non_stream_zero_process_memories')
        or group == 'T-08' and name == 'dup_first_valid_is_task'
        or group == 'T-11' and name == 'task_bypass'):
        tags.add('task-ledger')
    if (group == 'T-06' and name == 'no_session_header_v2_on'
        or group == 'T-11' and name in ('task_bypass', 'baseline_unchanged[identity]')):
        tags.add('task-identity')
    if group == 'T-11' and path == 'row6':
        tags.add('row6')
    if (group == 'T-00' and name == 'real_ledger_rows'
        or group == 'T-08' and name.endswith('_is_normal')
        or group == 'T-10' and name == 'single_user_with_history_records'
        or group == 'T-11' and name in ('records_normally', 'baseline_unchanged[ledger]')
        or group == 'T-12' and name == 'chat_ledger_golden'):
        tags.add('single-user-ledger')
    if (group == 'T-06' and (name == 'collectors_zero_calls' or name == 'tools_passthrough_only' and path == 'T')
        or group == 'T-07' and path == 'e'):
        tags.add('tool-collect')
    if group == 'T-06' and name in ('web_search_true_zero_search', 'zero_ev_tool'):
        tags.add('search')
    if group == 'T-06' and name == 'zero_kiwi_private_frames':
        tags.add('private-frames')
    return sorted(tags)


def equal(group, path, name, actual, expected, stage='PASS'):
    ident = f'{group}/{path}/{name}'
    if any(r['id'] == ident for r in ROWS):
        raise RuntimeError('duplicate assertion ID: ' + ident)
    try:
        assert actual == expected, f'actual={actual!r}; expected={expected!r}'
    except AssertionError as exc:
        status, reason = 'FAIL', str(exc)
    else:
        status, reason = 'PASS', 'assertion reached'
    ROWS.append(dict(id=ident, arm=f'{group}/{path}', group=group, path=path, check=name,
                     status=status, expected_stage_a=stage, reason=reason,
                     tags=assertion_tags(group, path, name),
                     failure_kind='AssertionError' if status == 'FAIL' else None))


def decoded(raw):
    result = []
    for line in raw.decode('utf-8').splitlines():
        if line.startswith('data: ') and line != 'data: [DONE]':
            result.append(json.loads(line[6:]))
    return result


async def sql(query, *args):
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def reset():
    await dbtest._truncate('conversations', 'chat_conversations', 'chat_projects',
                           'gateway_config', 'session_source_rev', 'memory_extraction_state')


class CountedConnection:
    """Proxy real asyncpg connection; do not assign to its read-only methods."""
    def __init__(self, conn, counts):
        self.conn, self.counts = conn, counts
    def __getattr__(self, key):
        return getattr(self.conn, key)
    async def fetchrow(self, query, *args):
        if 'SELECT project_id FROM chat_conversations' in query:
            self.counts.append(args[0])
        return await self.conn.fetchrow(query, *args)


async def capture(*, path='N', headers=(), payload=None, task=False, v2=False,
                  identity_on=True, task_on=True, memory=False, dream=False,
                  seed=False, clean=True, fmt='openai', template=False,
                  direct=False, disconnect=False, force=False, traditional=False, handoff=False):
    if clean:
        await reset()
    values = dict(memory_enabled=str(memory).lower(), session_identity_v2_enabled=str(v2).lower(),
                  session_header_identity_enabled=str(identity_on).lower(),
                  task_signal_enabled=str(task_on).lower(), reminder_tools_enabled='false',
                  tool_drawer_enabled=str(not traditional).lower(), mcp_mode='off',
                  web_search_mode='off', search_engine='fixture', search_api_key='fixture',
                  prompt_cache_enabled='false', reasoning_effort='off',
                  memory_event_ledger_write_enabled='true')
    for key, value in values.items():
        await dbtest._upsert_config(key, value)
    if seed:
        await sql("INSERT INTO chat_projects (id,name) VALUES ('c2b-live','fixture')")
        await sql("INSERT INTO chat_conversations (id,title,project_id) VALUES ($1,'fixture','c2b-live')",
                  hdr('cid', 'C2B-ID'))
    body = dict(model=MODEL, messages=[{'role': 'user', 'content': USER}], stream=path != 'N',
                turn_key='c2b-turn', temperature=0.7)
    if template:
        body.update(user_name='C2B_NAME')
        body['messages'].insert(0, {'role': 'system', 'content': 'client {user_name}'})
    if path == 'T':
        body['web_search'] = 'auto'
    if force:
        body['web_search'] = True
    if traditional:
        body['mcp_servers'] = ['c2b-fake-server']
    body.update(copy.deepcopy(payload or {}))
    incoming = list(headers) + ([('X-Kiwi-Task', 'C2B-TASK')] if task else [])
    upstream_bodies, request_bytes, tasks, scopes, identities, metadata_reads = [], [], [], [], [], []
    inners, bg_results = [], []
    text = TEXT + (DREAM if dream else '')
    real_client = httpx.AsyncClient
    real_scope, real_identity = database._resolve_scope_tx, app._request_session_identity
    real_process, real_stream, real_tools = app.process_memories_background, app.stream_and_capture, app._stream_with_tools
    async def scope(conn, *args, **kw):
        value = await real_scope(CountedConnection(conn, metadata_reads), *args, **kw)
        scopes.append(value)
        return value
    async def identity(*args, **kw):
        value = await real_identity(*args, **kw)
        identities.append(value)
        return value
    @functools.wraps(real_stream)
    def stream(*args, **kw):
        gen = real_stream(*args, **kw)
        inners.append(gen)
        return gen
    async def process(*args, **kw):
        result = await real_process(*args, **kw)
        bg_results.append(result)
        return result
    def spawn(coro):
        job = asyncio.create_task(coro)
        tasks.append(job)
        return job
    def upstream(req):
        sent = json.loads(req.content)
        upstream_bodies.append(sent)
        request_bytes.append(req.content)
        if fmt == 'anthropic':
            return httpx.Response(200, json={'id':'c2b-upstream','type':'message','role':'assistant',
                'model':MODEL,'content':[{'type':'text','text':text}], 'stop_reason':'end_turn',
                'usage':{'input_tokens':1,'output_tokens':1}})
        if sent.get('stream'):
            events = [{'id':'c2b-upstream','model':MODEL,'created':1,
                       'choices':[{'index':0,'delta':{'content':text},'finish_reason':None}]},
                      {'id':'c2b-upstream','model':MODEL,'created':1,
                       'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
            raw = ''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n'
            return httpx.Response(200, content=raw.encode(), headers={'content-type':'text/event-stream'})
        return httpx.Response(200, json={'id':'c2b-upstream','choices':[{'index':0,
            'message':{'role':'assistant','content':text},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1,'completion_tokens':1}})
    def outbound(*args, **kw):
        return real_client(*args, transport=httpx.MockTransport(upstream), **kw)
    route = AsyncMock(return_value=([TOOL], TOOL_MAP) if path == 'T' else ([], {}))
    init = AsyncMock()
    mcp = AsyncMock(return_value=([TOOL], TOOL_MAP))
    launch, fallback = Mock(), AsyncMock()
    extract = AsyncMock(return_value=('extract', [{'id':1,'content':'synthetic-memory'}],0,0,None))
    search = AsyncMock(return_value=[SimpleNamespace(to_dict=lambda: {'title':'fixture','url':'https://example.invalid'})])
    processed = AsyncMock(side_effect=process)
    tool_spy = Mock(wraps=real_tools)
    address = 'https://anthropic.example/v1' if fmt == 'anthropic' else 'https://relay.example/v1'
    provider = dict(id=7, provider_id=7, name='fixture', provider_name='fixture',
                    api_base_url=address, api_key='c2b-fake-key', api_format=fmt, enabled=True)
    logs = io.StringIO()
    with ExitStack() as stack:
        stack.enter_context(redirect_stdout(logs)); stack.enter_context(redirect_stderr(logs))
        for logger in (logging.getLogger(), logging.getLogger('httpx'), logging.getLogger('mcp')):
            handler = logging.StreamHandler(logs); logger.addHandler(handler)
            stack.callback(logger.removeHandler, handler)
        for name, value in {'resolve_provider_for_model':provider, 'get_active_system_prompt':PERSONA,
            'build_system_prompt_with_memories':(PERSONA, {'handoff': {'sourceId':'fixture-source','sourceRev':7}} if handoff else {}), 'get_extract_interval':1,
            'search_memories':[], 'get_recent_memories':[], 'get_all_categories':[],
            'get_all_memories_count':1}.items():
            stack.enter_context(patch.object(app, name, AsyncMock(return_value=value)))
        for obj, name, value in [(database,'_resolve_scope_tx',scope),(app,'_request_session_identity',identity),
            (app,'process_memories_background',processed),(app,'stream_and_capture',stream),
            (app,'_stream_with_tools',tool_spy),(app,'_spawn_background_task',spawn),
            (app,'_launch_dream_detached',launch),(app,'_dream_fallback_after_grace',fallback),
            (app,'_extract_and_save_batch',extract),(app,'_conversation_counter',0),
            (app,'_counter_lock',asyncio.Lock()),(app,'datetime',Clock),
            (drawer,'init_drawer',init),(drawer,'route_tools',route),
            (drawer,'build_full_fallback_tools',Mock(return_value=([],{}))),
            (app,'get_tools_for_servers',mcp),(app,'web_search',search),
            (app,'format_results_for_prompt',Mock(return_value='C2B_SEARCH'))]:
            stack.enter_context(patch.object(obj,name,value))
        seq = iter(uuid.UUID(int=n) for n in range(1,100))
        uuid_mock=stack.enter_context(patch.object(uuid,'uuid4',side_effect=lambda:next(seq)))
        fixture_clock,fixture_uuid=app.datetime.now().isoformat(),str(uuid.uuid4())
        seq = iter(uuid.UUID(int=n) for n in range(1,100))
        uuid_mock.reset_mock()
        stack.enter_context(patch.object(httpx,'AsyncClient',outbound))
        if direct:
            kw = dict(api_url=address+'/chat/completions',api_key='c2b-fake-key',
                      record_events=False,extract_enabled=False)
            if 'task_request' in inspect.signature(real_tools).parameters:
                kw['task_request'] = True
            gen = real_tools(body['messages'],[TOOL],TOOL_MAP,MODEL,0.7,[],
                             'c2b-direct',USER,False,**kw)
            chunks = [chunk async for chunk in gen]
            raw = b''.join(c.encode() if isinstance(c,str) else c for c in chunks)
            response_headers, status = {}, 200
        elif disconnect:
            from starlette.requests import Request
            async def receive():
                return {'type':'http.request','body':json.dumps(body).encode(),'more_body':False}
            request = Request({'type':'http','method':'POST','path':'/v1/chat/completions',
                               'headers':[(k.lower().encode(),v.encode()) for k,v in incoming]},receive)
            response = await app.chat_completions(request)
            if not inners:
                raise AssertionError('disconnect fixture did not obtain real stream generator')
            gen = inners[0]; chunks = []
            while True:
                chunk = await gen.__anext__(); chunks.append(chunk)
                if DREAM.encode() in chunk:
                    break
            await gen.aclose()
            raw = b''.join(chunks); status = response.status_code; response_headers = dict(response.headers)
        else:
            async with real_client(transport=httpx.ASGITransport(app=app.app),base_url='http://localhost') as client:
                response = await client.post('/v1/chat/completions',json=body,headers=incoming)
            raw, status, response_headers = response.content,response.status_code,dict(response.headers)
        done = 0
        while done < len(tasks):
            batch = tasks[done:]; done = len(tasks)
            await asyncio.gather(*batch)
    records = [dict(row) for row in await sql('SELECT '+','.join(FIELDS)+' FROM conversations ORDER BY id')]
    events = decoded(raw) if body.get('stream') or direct else []
    return dict(status=status,raw=raw,headers=response_headers,bodies=upstream_bodies,
                body_sha=[hashlib.sha256(b).hexdigest() for b in request_bytes],
                records=records,ledger=[[r[k] for k in FIELDS] for r in records],
                session=identities[-1][0] if identities else None,scope=scopes[-1] if scopes else None,
                metadata_queries=len(metadata_reads),events=events,
                private=[k for e in events for k in e if k.startswith('ev_')],
                collectors=init.call_count+route.call_count+mcp.call_count,
                process_calls=processed.call_count,extract_calls=extract.call_count,
                search_calls=search.call_count,launch_calls=launch.call_count,
                fallback_calls=fallback.call_count,tool_calls=tool_spy.call_count,
                logs=logs.getvalue(),background=bg_results,
                fixture_clock=fixture_clock,fixture_uuid=fixture_uuid,uuid_calls=uuid_mock.call_count)


async def cases():
    for src, head in HEADS.items():
        c = await capture(headers=[(head,'C2B-ID')])
        equal('T-00',src,'handler_and_upstream',[c['status'],len(c['bodies'])],[200,1])
        equal('T-00',src,'real_ledger_rows',len(c['records']),2)
        equal('T-00',src,'clock_and_uuid',(c['fixture_clock'],c['fixture_uuid']),
              ('2026-10-09T12:00:00','00000000-0000-0000-0000-000000000001'))
        d = await capture(headers=[(head,'C2B-ID')])
        e = await capture(headers=[(head,'C2B-OTHER')])
        equal('T-01',src,'same_value_same_session',c['session'],d['session'])
        equal('T-01',src,'hdr_shape',bool(re.fullmatch(r'hdr-(cid|sid|owc)-[0-9a-f]{24}',c['session'])),True,'FAIL')
        equal('T-01',src,'source_segment',c['session'].split('-')[1],src,'FAIL')
        equal('T-01',src,'diff_value_diff_session',c['session']!=e['session'],True,'FAIL')
    ids = [(await capture(headers=[(head,'C2B-ID')]))['session'] for head in HEADS.values()]
    equal('T-01','cross','same_value_diff_header_diff_session',len(set(ids)),3,'FAIL')
    all_heads = [(h,'C2B-ID') for h in HEADS.values()]
    for name, heads, body, expected, stage in [
        ('body_wins',all_heads,{'conversation_id':'c2b-body'},'c2b-body','PASS'),
        ('cid_over_sid_owc',all_heads,{},hdr('cid','C2B-ID'),'FAIL'),
        ('sid_over_owc',all_heads[1:],{},hdr('sid','C2B-ID'),'FAIL')]:
        c=await capture(headers=heads,payload=body)
        equal('T-02','priority',name,c['session'],expected,stage)
    bad={'empty':'','blank':'   ','201chars':'x'*201,'nul':'x\x00y','newline':'x\ny'}
    for label,value in bad.items():
        c=await capture(headers=[(HEADS['cid'],value),(HEADS['sid'],'C2B-ID')])
        equal('T-03',label,'bad_cid_falls_to_sid',c['session'],hdr('sid','C2B-ID'),'FAIL')
    c=await capture(headers=[(h,'') for h in HEADS.values()])
    equal('T-03','all','all_bad_fallback_auto',c['session'].startswith('auto-'),True)
    c=await capture(headers=[(HEADS['cid'],''),(HEADS['cid'],'C2B-ID'),(HEADS['cid'],'C2B-OTHER')])
    equal('T-03','repeat','dup_cid_first_valid',c['session'],hdr('cid','C2B-ID'),'FAIL')
    c=await capture(headers=[(HEADS['cid'],'C2B-ID')],seed=True)
    equal('T-04','header','header_identity_is_hdr',c['session'],hdr('cid','C2B-ID'),'FAIL')
    equal('T-04','header','header_zero_metadata_fetch',c['metadata_queries'],0,'FAIL')
    equal('T-04','header','header_scope_global',c['scope'],(True,None,'global',None,'scope_default_global'))
    c=await capture(payload={'conversation_id':hdr('cid','C2B-ID')},seed=True)
    equal('T-04','body','body_hdr_string_queries_metadata',(c['scope'][2],c['metadata_queries']),('live_project',1))
    for label,pid,expected in [('live','c2b-live',(True,'c2b-live','live_project','c2b-live','scope_payload_trusted')),
                                ('unverified','c2b-unknown',(False,None,'quarantined_project',None,'scope_unverified'))]:
        c=await capture(headers=[(HEADS['cid'],'C2B-ID')],payload={'project_id':pid},seed=True)
        equal('T-04',label,'header_payload_'+label,c['scope'],expected)
    for v2 in (False,True):
        c=await capture(path='P',headers=[(HEADS['cid'],'C2B-ID')],v2=v2)
        equal('T-05','v2-'+str(v2),'v2_'+('on' if v2 else 'off')+'_no_header_no_frame',
              'x-kiwi-session-id' not in c['headers'] and 'ev_session' not in c['private'],True,'FAIL' if v2 else 'PASS')
    for path in ('N','P','T'):
        c=await capture(path=path,task=True,memory=True,v2=True,payload={'tools':[CLIENT_TOOL]})
        equal('T-06',path,'no_kiwi_system',PERSONA not in json.dumps(c['bodies']),True,'FAIL')
        equal('T-06',path,'ledger_zero_rows',len(c['records']),0,'FAIL')
        if path=='N': equal('T-06',path,'non_stream_zero_process_memories',c['process_calls'],0,'FAIL')
        equal('T-06',path,'zero_extract',c['extract_calls'],0,'FAIL')
        # Non-stream and ordinary stream preserve client tools already; only
        # the baseline tool-loop path replaces them with gateway tools.
        equal('T-06',path,'tools_passthrough_only',c['bodies'][0].get('tools'),[CLIENT_TOOL], 'FAIL' if path=='T' else 'PASS')
        equal('T-06',path,'collectors_zero_calls',c['collectors'],0,'FAIL')
        equal('T-06',path,'no_session_header_v2_on','x-kiwi-session-id' not in c['headers'],True,'FAIL')
        if path!='N': equal('T-06',path,'zero_kiwi_private_frames',c['private'],[],'FAIL')
        c=await capture(path=path,task=True,template=True)
        equal('T-06',path,'no_kiwi_system[client_template]',
              [m['content'] for m in c['bodies'][0]['messages'] if m['role']=='system'],['client {user_name}'],'FAIL')
        c=await capture(path=path,task=True,force=True)
        equal('T-06',path,'web_search_true_zero_search',c['search_calls'],0,'FAIL')
        if path!='N': equal('T-06',path,'zero_ev_tool','ev_tool' in c['private'],False,'FAIL')
        a=await capture(path=path,payload={'reasoning_effort':'high'})
        b=await capture(path=path,task=True,payload={'reasoning_effort':'high'})
        fields=lambda c: [{k:v for k,v in body.items() if k in ('reasoning','reasoning_effort','thinking')} for body in c['bodies']]
        equal('T-06',path,'reasoning_equal_with_and_without_task_header',fields(a),fields(b))
    c=await capture(task=True,traditional=True)
    equal('T-06','traditional','collectors_zero_calls',c['collectors'],0,'FAIL')
    c=await capture(task=True,dream=True)
    equal('T-07','a','non_stream_zero_launch',c['launch_calls'],0,'FAIL')
    c=await capture(path='P',task=True,dream=True)
    equal('T-07','b','stream_finish_zero_ev_dream','ev_dream' in c['private'],False,'FAIL')
    equal('T-07','b','stream_finish_zero_fallback',c['fallback_calls'],0,'FAIL')
    c=await capture(path='T',direct=True,dream=True)
    equal('T-07','c','tools_direct_zero_fallback',c['fallback_calls'],0,'FAIL')
    c=await capture(path='P',task=True,dream=True,disconnect=True)
    equal('T-07','d','stream_disconnect_zero_fallback',c['fallback_calls'],0,'FAIL')
    c=await capture(path='T',task=True)
    equal('T-07','e','task_never_enters_tool_loop',c['tool_calls'],0,'FAIL')
    for label,value in [('empty',''),('blank','   '),('65chars','x'*65),('control','x\x00y')]:
        c=await capture(headers=[('X-Kiwi-Task',value)])
        equal('T-08',label,label+'_is_normal',len(c['records']),2)
    c=await capture(headers=[('X-Kiwi-Task',''),('X-Kiwi-Task','C2B-TASK')])
    equal('T-08','repeat','dup_first_valid_is_task',len(c['records']),0,'FAIL')
    for label,options in [('out_normalized_equal',{'payload':{'max_completion_tokens':64}}),
                          ('invalid_limit_400_equal',{'payload':{'max_completion_tokens':0}}),
                          ('include_usage_equal',{'path':'P','payload':{'stream_options':{'include_usage':True}}}),
                          ('anthropic_shape_equal',{'fmt':'anthropic','payload':{'max_completion_tokens':64,'stop':'END'}})]:
        a,b=await capture(**options),await capture(task=True,**options)
        if label=='invalid_limit_400_equal':
            equal('T-09','protocol',label,(a['status'],b['status'],a['raw']==b['raw'],len(a['bodies']),len(b['bodies'])),(400,400,True,0,0))
        else:
            # Only the protocol envelope is invariant. Task bypass intentionally
            # changes injected system messages; T-06 tests that independently.
            keys=('max_tokens','max_completion_tokens','stop','stop_sequences','stream_options')
            project=lambda c: [{k:body[k] for k in keys if k in body} for body in c['bodies']]
            wanted={'out_normalized_equal':{'max_completion_tokens':64},
                    'include_usage_equal':{'stream_options':{'include_usage':True}},
                    'anthropic_shape_equal':{'max_tokens':64,'stop_sequences':['END']}}[label]
            equal('T-09','protocol',label,(project(a),project(b)),([wanted],[wanted]))
    await capture(payload={'conversation_id':'c2b-history','turn_key':'c2b-first'})
    c=await capture(clean=False,payload={'conversation_id':'c2b-history','turn_key':'c2b-second'})
    equal('T-10','history','single_user_with_history_records',len(c['records']),4)
    c=await capture(payload={'skip_system_prompt':True,'reasoning_effort':'high'})
    CAPTURES['skip']={'body_sha':c['body_sha'],'ledger':c['ledger']}
    equal('T-10','skip','skip_prompt_body_sha_golden',c['body_sha'],GOLDEN.get('skip',{}).get('body_sha'))
    equal('T-10','skip','skip_prompt_zero_rows',len(c['records']),0)
    equal('T-10','skip','skip_prompt_reasoning_cleared','reasoning_effort' in c['bodies'][0],False)
    for row,i,t,h,task in [(1,True,True,True,False),(2,True,True,True,True),(3,True,True,False,True),
                           (4,False,True,True,False),(5,True,False,True,True),(6,False,False,True,True)]:
        c=await capture(headers=[(HEADS['cid'],'C2B-ID')] if h else [],task=task,identity_on=i,task_on=t)
        p='row'+str(row)
        if row in (1,5): equal('T-11',p,'hdr_identity',c['session'],hdr('cid','C2B-ID'),'FAIL')
        if row in (2,3): equal('T-11',p,'task_bypass',(c['session'],len(c['records'])),(None,0),'FAIL')
        if row==4: equal('T-11',p,'header_ignored',c['session'].startswith('auto-'),True)
        if row in (4,5): equal('T-11',p,'records_normally',len(c['records']),2)
        if row==6:
            equal('T-11',p,'baseline_unchanged[identity]',c['session'] is not None and c['session'].startswith('auto-'),True)
            equal('T-11',p,'baseline_unchanged[task]',c['session'] is not None,True)
            equal('T-11',p,'baseline_unchanged[ledger]',len(c['records']),2)
    c=await capture(payload={'conversation_id':'c2b-chat','turn_key':'c2b-turn'})
    CAPTURES['chat']={'body_sha':c['body_sha'],'ledger':c['ledger']}
    equal('T-12','chat','chat_body_sha_golden',c['body_sha'],GOLDEN.get('chat',{}).get('body_sha'))
    equal('T-12','chat','chat_ledger_golden',c['ledger'],GOLDEN.get('chat',{}).get('ledger'))
    for src,head in HEADS.items():
        value='C2B-PRIVATE-'+src
        c=await capture(headers=[(head,value)])
        equal('T-12',src,'logs_no_header_values',value in c['logs'],False)
    c=await capture(task=True)
    equal('T-12','task','logs_no_header_values','C2B-TASK' in c['logs'],False)
    # Existing C2A guards run separately in CI. Exercise actual private frames here too.
    c=await capture(path='P',v2=True,memory=True,dream=True,force=True,handoff=True)
    private=[e for e in c['events'] if any(k.startswith('ev_') for k in e)]
    equal('T-12','frames','c2a_frames_choices',bool(private) and all(e.get('choices')==[] for e in private),True)
    for key in ('ev_session','ev_handoff','ev_tool','ev_memory','ev_dream'):
        found=[e for e in private if key in e]
        equal('T-12','frames','c2a_frames_choices['+key+']',
              (len(found),[sorted(e) for e in found],[e.get('choices') for e in found]),
              (1,[sorted([key,'choices'])],[[]]))


async def run(golden_output=None):
    global app,database,config,drawer
    admin=dbtest._validated_admin_dsn(); name=''
    try:
        name,dsn=await dbtest._create_disposable_database(admin)
        os.environ.update(DATABASE_URL=dsn,API_KEY='',MEMORY_API_KEY='',MEMORY_ENABLED='false',
                          API_BASE_URL='http://127.0.0.1:9/mock',MEMORY_API_BASE_URL='http://127.0.0.1:9/mock')
        database=importlib.import_module('database'); config=importlib.import_module('config')
        app=importlib.import_module('main'); drawer=importlib.import_module('tool_drawer')
        dbtest.database=database
        assert database.DATABASE_URL==dsn and app.app.title=='Kiwi-Mem'
        await database.init_tables()
        await cases()
    except Exception as exc:
        ROWS.append(dict(id='fixture/execution',arm='fixture',status='ERROR',tags=[],failure_kind=type(exc).__name__,reason=str(exc)))
    finally:
        if database is not None: await database.close_pool()
        if name: await dbtest._drop_disposable_database(admin,name)
    if golden_output:
        for file in ('main.py','database.py','config.py','anthropic_adapter.py'):
            frozen=subprocess.check_output(['git','show',BASE+':'+file],cwd=ROOT)
            assert (ROOT/file).read_bytes().replace(b'\r\n',b'\n')==frozen, 'golden requires BASE production blobs'
        assert set(CAPTURES)=={'skip','chat'}, 'capture incomplete'
        Path(golden_output).write_text(json.dumps(CAPTURES,indent=2)+'\n',encoding='utf-8')
    counts={s:sum(r['status']==s for r in ROWS) for s in ('PASS','FAIL','ERROR')}
    arms={}
    for r in ROWS:
        old=arms.setdefault(r['arm'],dict(id=r['arm'],status='PASS'))
        if r['status']=='ERROR' or r['status']=='FAIL' and old['status']!='ERROR': old['status']=r['status']
    arm_counts={s:sum(r['status']==s for r in arms.values()) for s in counts}
    report=dict(ticket='COMPAT-02-B',base=BASE,counts=arm_counts,assertion_counts=counts,
                arms=list(arms.values()),assertions=ROWS,tag_dictionary=list(TAG_DICTIONARY),
                golden=GOLDEN,disposable_database_removed=bool(name),
                evidence='real PostgreSQL; fake model/search/MCP/Dream; no lifespan')
    for r in ROWS: print('ASSERT '+json.dumps(r,ensure_ascii=True,sort_keys=True))
    print('SUMMARY '+json.dumps(arm_counts,sort_keys=True))
    print('assertion_counts '+json.dumps(counts,sort_keys=True))
    target=os.environ.get('KIWI_C2B_REPORT')
    if target: Path(target).write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
    return 2 if counts['ERROR'] else 1 if counts['FAIL'] else 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-golden',help='BASE-only one-time output outside the checkout')
    args=parser.parse_args()
    if args.capture_golden and Path(args.capture_golden).resolve().is_relative_to(ROOT):
        parser.error('golden output must be outside checkout')
    raise SystemExit(asyncio.run(run(args.capture_golden)))
