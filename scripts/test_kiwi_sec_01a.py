"""SEC-01a: real ASGI/production functions, fake DB and recorded HTTP only.

No lifespan, external service or developer .env is used. PostgreSQL coverage
remains in test_kiwi_safety_sync.py. Run directly; failures are named assertions.
"""
import asyncio
import ast
import io
import json
import os
import sys
import unittest
import zipfile
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DATABASE_URL'] = 'postgresql://unused:unused@127.0.0.1:1/unused'
import httpx
import config as cfg
import database as db
import main as app
import web_search as search

KEY = 'Kiwi_Sentinel_6qV2wR9xJ3pL8zB4'
ROW = dict(id=7, name='fixture', api_base_url='https://relay.example/v1',
           api_key=KEY, enabled=True, api_format='openai', created_at=None, updated_at=None)
PROVIDER_KEYS = {'id','name','api_base_url','api_format','enabled','created_at',
                 'updated_at','has_credential','api_key_last4','api_key_preview'}


class Pool:
    def __init__(self):
        self.values = {}
        self.writes = []
    def acquire(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def fetchrow(self, sql, key):
        return {'value': self.values[key]} if key in self.values else None
    async def fetch(self, sql, *args):
        if 'gateway_config' in sql:
            return [{'key': k, 'value': v} for k, v in self.values.items()]
        return []
    async def execute(self, sql, *args):
        self.writes.append((sql, args))
        if 'DELETE' in sql: self.values.pop(args[0], None)
        else: self.values[args[0]] = args[1]
        return 'DELETE 1' if 'DELETE' in sql else 'INSERT 0 1'


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pool = Pool()
        self.patches = [patch.object(cfg, 'get_pool', AsyncMock(return_value=self.pool)),
                        patch.object(app, 'get_pool', AsyncMock(return_value=self.pool)),
                        patch.dict(os.environ, {'SEARCH_API_KEY': ''})]
        for p in self.patches: p.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url='http://localhost:8000')
    async def asyncTearDown(self):
        await self.client.aclose()
        for p in reversed(self.patches): p.stop()
    def safe(self, value, key=KEY):
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        for i in range(len(key)-4): self.assertNotIn(key[i:i+5], text)
    def provider(self, row, key=KEY):
        self.assertEqual(set(row), PROVIDER_KEYS)
        self.assertEqual(row['has_credential'], bool(key))
        self.assertEqual(row['api_key_last4'], key[-4:] if len(key)>=12 else '')
        self.assertEqual(row['api_key_preview'], ('•••• •••• •••• '+key[-4:] if len(key)>=12 else '已配置') if key else '')
        self.safe(row, key)

    async def test_provider_three_exits(self):
        for key in ('', '12345678901', '123456789012', KEY):
            row = dict(ROW, api_key=key, private_future_column=KEY)
            with self.subTest(length=len(key)), patch.object(app,'get_all_providers',AsyncMock(return_value=[row])), patch.object(app,'create_provider',AsyncMock(return_value=row)), patch.object(app,'update_provider',AsyncMock(return_value=row)):
                r = await self.client.get('/admin/providers'); self.provider(r.json()['providers'][0], key)
                r = await self.client.post('/admin/providers',json={'name':'fixture','api_base_url':ROW['api_base_url'],'api_key':key}); self.provider(r.json()['provider'], key)
                r = await self.client.put('/admin/providers/7',json={'name':'fixture'}); self.provider(r.json()['provider'], key)

    async def test_config_read_write_and_log(self):
        log = io.StringIO()
        with redirect_stdout(log):
            r = await self.client.put('/admin/config/search_api_key',json={'value':KEY})
        self.assertEqual(r.status_code,200); self.safe(r.json()); self.safe(log.getvalue())
        self.assertNotIn(KEY[:4],log.getvalue()); self.assertNotIn(KEY[-4:],log.getvalue())
        self.assertEqual(await cfg.get_config('search_api_key'),KEY)
        r = await self.client.get('/admin/config')
        secret = r.json()['config']['search_api_key']; self.safe(secret)
        self.assertEqual(set(secret),{'value','label','type','source','has_value','last4'})
        self.assertEqual((secret['value'],secret['type'],secret['last4']),('','secret',KEY[-4:]))
        r = await self.client.get('/admin/search-config'); self.safe(r.json())
        self.assertNotIn('api_key',r.json()); self.assertTrue(r.json()['has_value'])
        self.assertEqual(r.json()['last4'],KEY[-4:]); self.assertIn('engine',r.json())

    async def test_secret_empty_preserves_and_invalid_rejected(self):
        for endpoint, field in [('/admin/config/search_api_key','value'),('/admin/search-config','api_key')]:
            for value in ('', '   ', None, 42, [], {}):
                with self.subTest(endpoint=endpoint,value=value):
                    self.pool.values['search_api_key']=KEY; self.pool.writes.clear()
                    r=await self.client.put(endpoint,json={field:value})
                    self.assertEqual(r.status_code,200 if isinstance(value,str) else 400)
                    self.assertEqual(self.pool.values['search_api_key'],KEY); self.assertFalse(self.pool.writes)
            r=await self.client.put(endpoint,json={}); self.assertEqual(r.status_code,200)
            self.assertEqual(self.pool.values['search_api_key'],KEY)

    async def test_clear_deletes_override_and_restores_env(self):
        self.pool.values['search_api_key']='old'
        with patch.dict(os.environ,{'SEARCH_API_KEY':KEY}):
            r=await self.client.put('/admin/config/search_api_key',json={'clear':True})
            self.assertEqual(r.status_code,200); self.assertNotIn('search_api_key',self.pool.values)
            self.assertEqual(await cfg.get_config('search_api_key'),KEY); self.safe(r.json())
            self.assertTrue(r.json()['config']['has_value']); self.assertEqual(r.json()['config']['source'],'env')

    async def test_config_failure_does_not_echo_submission(self):
        with patch.object(app,'set_config',AsyncMock(return_value=False)):
            r=await self.client.put('/admin/config/search_api_key',json={'value':KEY})
        self.assertEqual(r.status_code,400); self.safe(r.json())
        self.assertEqual(r.json(),{'error':'invalid_request','error_code':'invalid_request'})

    async def test_export_omits_secret_and_metadata_is_separate(self):
        self.pool.values['search_api_key']=KEY
        with patch.object(app,'sync_get_conversations',AsyncMock(return_value=[])),patch.object(app,'sync_get_projects',AsyncMock(return_value=[])):
            r=await self.client.get('/sync/export')
        self.assertEqual(r.status_code,200)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            self.assertEqual(json.loads(z.read('config.json'))['search_api_key'],'')
            self.assertEqual(json.loads(z.read('backup_meta.json')),{'format_version':2,'secrets_configured':['search_api_key']})
            for name in z.namelist(): self.safe(z.read(name).decode())

    async def import_zip(self, config, meta=None, projects=None):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:
            z.writestr('config.json',json.dumps(config))
            if meta is not None:z.writestr('backup_meta.json',json.dumps(meta))
            if projects is not None:z.writestr('projects.json',json.dumps(projects))
        return await self.client.post('/sync/import-backup',files={'file':('fixture.zip',b.getvalue(),'application/zip')})

    async def test_import_matrix(self):
        meta={'format_version':2,'secrets_configured':['search_api_key']}
        for source in ('empty','db','env'):
            self.pool.values.clear()
            if source=='db': self.pool.values['search_api_key']=KEY
            with patch.dict(os.environ,{'SEARCH_API_KEY':KEY if source=='env' else ''}):
                r=await self.import_zip({'search_api_key':''},meta)
                self.assertEqual(r.status_code,200)
                self.assertEqual(r.json()['secrets_requiring_input'],['search_api_key'] if source=='empty' else [])
                if source=='env': self.assertNotIn('search_api_key',self.pool.values)
        r=await self.import_zip({'search_api_key':KEY})
        self.assertEqual(r.status_code,200); self.assertEqual(self.pool.values['search_api_key'],KEY)

    async def test_invalid_meta_rejected_before_any_write(self):
        for meta in ({'format_version':3,'secrets_configured':[]},{'format_version':2,'secrets_configured':['not_secret']},[],{'format_version':True,'secrets_configured':[]},
                     {'format_version':2,'secrets_configured':['search_api_key','search_api_key']},
                     {'format_version':2,'secrets_configured':[],'extra':True}):
            with self.subTest(meta=meta),patch.object(app,'sync_upsert_project',AsyncMock()) as save:
                r=await self.import_zip({'search_api_key':KEY},meta,[{'id':'test'}])
                self.assertEqual(r.status_code,400); save.assert_not_awaited(); self.assertFalse(self.pool.writes)

    async def test_credits_destination_and_both_paths(self):
        real_client=httpx.AsyncClient
        for source in ('env','provider'):
            for base in ('https://relay.example/openrouter/v1','https://openrouter.ai:9443/api/v1'):
                calls=[]
                def handler(req):
                    calls.append(req)
                    return httpx.Response(200,json={'data':{'usage':1,'total_credits':3,'total_usage':1},'hard_limit_usd':3,'total_usage':1})
                def client(*a,**kw):return real_client(transport=httpx.MockTransport(handler),**kw)
                with self.subTest(source=source,base=base),patch.object(app,'get_all_providers',AsyncMock(return_value=[] if source=='env' else [dict(ROW,api_base_url=base)])),patch.object(app,'API_KEY',KEY),patch.object(app,'API_BASE_URL',base),patch.object(httpx,'AsyncClient',client):
                    r=await self.client.get('/admin/credits')
                self.assertEqual(r.status_code,200);self.assertEqual(len(calls),2)
                expected=httpx.URL(base)
                for req in calls:
                    self.assertEqual((req.url.scheme,req.url.host,req.url.port),(expected.scheme,expected.host,expected.port))
                    self.assertEqual(req.headers['authorization'],'Bearer '+KEY)
                if expected.host=='openrouter.ai':self.assertEqual([q.url.path for q in calls],['/api/v1/auth/key','/api/v1/credits'])

    async def test_invalid_urls_never_send_credentials(self):
        for base in ('https://user@openrouter.ai/v1','//openrouter.ai/v1','https://openrouter.ai:bad/v1','https://relay.example/v1?token=x','https://relay.example/v1#x'):
            with self.subTest(base=base),patch.object(app,'get_all_providers',AsyncMock(return_value=[dict(ROW,api_base_url=base)])),patch.object(httpx,'AsyncClient') as client:
                r=await self.client.get('/admin/credits')
                self.assertEqual(r.status_code,200)
                self.assertEqual(r.json()['providers'][0]['error_code'],'invalid_request')
                client.assert_not_called()

    async def test_provider_errors_are_stable(self):
        for name,path in [('get_all_providers','/admin/providers'),('get_provider','/admin/providers/7/models'),('get_all_providers','/admin/credits')]:
            with self.subTest(path=path),patch.object(app,name,AsyncMock(side_effect=RuntimeError(KEY))):
                r=await self.client.get(path)
                self.assertEqual(r.status_code,500); self.assertEqual(r.json(),{'error':'internal_error','error_code':'internal_error'})

    async def test_search_test_failure_and_chat_fallback(self):
        log=io.StringIO()
        with patch.object(search,'_search_tavily',AsyncMock(side_effect=httpx.ReadTimeout(KEY))),redirect_stdout(log):
            r=await self.client.post('/admin/search-test',json={'engine':'tavily','query':'fixture','api_key':KEY})
            self.assertEqual(r.status_code,502); self.assertEqual(r.json(),{'error':'timeout','error_code':'timeout'})
            self.assertEqual(await search.web_search('fixture','tavily',KEY),[])
        self.safe(log.getvalue())

    async def test_embedding_failure_contract_and_logs(self):
        class Client:
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
            async def post(self,*a,**kw):return httpx.Response(502,text=KEY)
        log=io.StringIO()
        with patch.object(db,'_resolve_embedding_endpoint',AsyncMock(return_value=('https://relay.example/v1/embeddings',KEY,'fixture','env'))),patch.object(httpx,'AsyncClient',return_value=Client()),redirect_stdout(log):
            self.assertIsNone(await db.get_embedding('x'))
            self.assertEqual(await db.get_embeddings_batch(['x','y']),[None,None])
        self.safe(log.getvalue())

    async def test_stream_errors_are_not_assistant_content(self):
        class Response:
            status_code=502
            async def aiter_bytes(self, **kw):
                raise AssertionError('error body must not be buffered')
                yield b''
        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self,*a): pass
            def stream(self,*a,**kw): return self
        class StreamClient(Client):
            def stream(self,*a,**kw):
                class Context:
                    async def __aenter__(self): return Response()
                    async def __aexit__(self,*a): pass
                return Context()
        for fmt in ('openai','anthropic'):
            with self.subTest(format=fmt), patch.object(httpx,'AsyncClient',return_value=StreamClient()), patch.object(app,'process_memories_background',AsyncMock()) as persist:
                iterator=app.stream_and_capture({}, {'messages':[]},'fixture','','fixture',api_url='https://relay.example/v1/chat/completions',api_format=fmt,api_key=KEY,mem_enabled=False)
                chunks=[c async for c in app._with_ev_session(iterator,'fixture',False)]
                text=b''.join(chunks).decode(); self.safe(text)
                self.assertEqual(text.count('[DONE]'),1); self.assertNotIn('choices',text)
                self.assertIn('http_502',text); persist.assert_not_awaited()

    async def test_post_start_exception_and_embedded_error_frame(self):
        async def broken():
            yield b'data: {"choices":[]}\n\n'
            raise httpx.ReadTimeout(KEY)
        for generated in (True,False):
            text=b''.join([c async for c in app._with_ev_session(broken(),'fixture',generated)]).decode()
            self.safe(text); self.assertEqual(text.count('[DONE]'),1); self.assertIn('timeout',text)
        import security
        with self.assertRaises(security.UpstreamFailure):
            security.require_success_event('data: '+json.dumps({'error':{'message':KEY}}))

    async def test_anthropic_error_frame_is_stable(self):
        from anthropic_adapter import anthropic_stream_to_openai
        class Response:
            async def aiter_bytes(self,**kw):
                yield ('data: '+json.dumps({'type':'error','error':{'message':KEY}})+'\n\n').encode()
        text=b''.join([c async for c in anthropic_stream_to_openai(Response(),'fixture')]).decode()
        self.safe(text); self.assertNotIn('choices',text);self.assertEqual(text.count('[DONE]'),1)
        class BrokenResponse:
            async def aiter_bytes(self, **kw):
                raise httpx.ReadTimeout(KEY)
                yield b''
        text=b''.join([c async for c in anthropic_stream_to_openai(BrokenResponse(),'fixture')]).decode()
        self.safe(text); self.assertIn('timeout',text)
        self.assertNotIn('choices',text); self.assertEqual(text.count('[DONE]'),1)

    async def test_legacy_dream_errors_are_safe_on_read(self):
        row={'id':1,'status':'error','dream_narrative':KEY,'started_at':None,'finished_at':None}
        with patch.object(db,'get_dream_history',AsyncMock(return_value=[row])):
            r=await self.client.get('/dream/history')
        self.assertEqual(r.status_code,200);self.safe(r.json())
        self.assertEqual(row['dream_narrative'],KEY) # no DB/history rewrite

    async def test_returned_generator_error_maps_to_failure(self):
        import daily_digest
        with patch.object(daily_digest,'generate_day_page',AsyncMock(return_value={'error':KEY})):
            r=await self.client.get('/admin/day-page')
        self.assertEqual(r.status_code,502);self.safe(r.json());self.assertEqual(r.json()['error_code'],'upstream_error')

    async def test_redirect_never_follows(self):
        real_client=httpx.AsyncClient; calls=[]
        def handler(req):
            calls.append(req)
            return httpx.Response(302,headers={'location':'https://other.example/steal'},text=KEY)
        with patch.object(app,'get_all_providers',AsyncMock(return_value=[dict(ROW,api_base_url='https://openrouter.ai:9443/v1')])),patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)):
            r=await self.client.get('/admin/credits')
        self.assertEqual(r.status_code,200);self.safe(r.json())
        self.assertEqual(r.json()['providers'][0]['error_code'],'http_302')
        self.assertEqual(len(calls),1);self.assertEqual(calls[0].url.host,'openrouter.ai')

    async def test_credits_failure_is_isolated_per_provider(self):
        real_client=httpx.AsyncClient
        for bad_base in ('https://bad.example/v1','https://openrouter.ai:9443/api/v1'):
            for failure in ('http_500','timeout'):
                calls=[]
                def handler(req):
                    calls.append(req.url.host)
                    if req.url.host in ('bad.example','openrouter.ai'):
                        if failure=='timeout': raise httpx.ReadTimeout(KEY,request=req)
                        return httpx.Response(500,text=KEY)
                    return httpx.Response(200,json={'hard_limit_usd':3,'total_usage':1})
                rows=[dict(ROW,id=i,name='provider-'+str(i),api_base_url=base) for i,base in enumerate(('https://one.example/v1',bad_base,'https://three.example/v1'),1)]
                with self.subTest(base=bad_base,failure=failure),patch.object(app,'get_all_providers',AsyncMock(return_value=rows)),patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)):
                    r=await self.client.get('/admin/credits')
                self.assertEqual(r.status_code,200); self.safe(r.json())
                entries=r.json()['providers']
                self.assertEqual([e['provider_id'] for e in entries],[1,2,3])
                self.assertEqual(entries[1]['error_code'],failure)
                self.assertIn('total_credits',entries[0]); self.assertIn('total_credits',entries[2])
                self.assertEqual(len(calls),5); self.assertEqual(calls[-2:],['three.example']*2)
                with patch.object(app,'get_all_providers',AsyncMock(return_value=[])),patch.object(app,'API_KEY',KEY),patch.object(app,'API_BASE_URL',bad_base),patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)):
                    r=await self.client.get('/admin/credits')
                self.assertEqual(r.status_code,200); self.safe(r.json())
                self.assertEqual(r.json()['providers'][0]['error_code'],failure)

    async def test_null_sse_error_is_not_failure(self):
        import security
        normal={'choices':[{'delta':{'content':'fixture'}}],'error':None}
        try:
            security.require_success_event('data: '+json.dumps(normal))
        except security.UpstreamFailure:
            self.fail('error:null must preserve a normal SSE frame')
        for event in ({'error':{'message':KEY}}, {'type':'error','error':None}):
            with self.assertRaises(security.UpstreamFailure):
                security.require_success_event('data: '+json.dumps(event))

    async def test_generic_redirect_never_follows(self):
        real_client=httpx.AsyncClient; calls=[]
        def handler(req):
            calls.append(req)
            return httpx.Response(302,headers={'location':'https://other.example/steal'},text=KEY)
        with patch.object(app,'get_all_providers',AsyncMock(return_value=[ROW])),patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)):
            r=await self.client.get('/admin/credits')
        self.safe(r.json()); self.assertEqual(len(calls),1)
        self.assertEqual(calls[0].url.host,'relay.example')
        self.assertEqual(calls[0].headers['authorization'],'Bearer '+KEY)

    async def test_nonstream_upstream_error_is_stable(self):
        real_client=httpx.AsyncClient
        for status in (401,500):
            for raw in (False,True):
                calls=[]
                def handler(req):
                    calls.append(req)
                    return httpx.Response(status,text=KEY) if raw else httpx.Response(status,json={'error':{'message':KEY}})
                with ExitStack() as stack:
                    for name,value in {'resolve_scope_snapshot':(True,None,'global',None,None),'get_reset_generation':0,'get_memory_enabled':False,'resolve_provider_for_model':None}.items():
                        stack.enter_context(patch.object(app,name,AsyncMock(return_value=value)))
                    stack.enter_context(patch.object(app,'API_KEY',KEY))
                    stack.enter_context(patch.object(app,'API_BASE_URL','https://relay.example/v1/chat/completions'))
                    stack.enter_context(patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)))
                    r=await self.client.post('/v1/chat/completions',json={'model':'fixture','stream':False,'skip_system_prompt':True,'messages':[{'role':'user','content':'fixture'}]})
                self.assertEqual(len(calls),1);self.assertEqual(r.status_code,502)
                self.assertEqual(r.json(),{'error':f'http_{status}','error_code':f'http_{status}'})
                self.safe(r.text)

    async def test_dream_stores_stable_error(self):
        import dream
        real_client=httpx.AsyncClient
        def handler(req): raise RuntimeError(KEY)
        saved=AsyncMock()
        with ExitStack() as stack:
            stack.enter_context(patch.object(dream,'_dream_running',False))
            stack.enter_context(patch.object(dream,'_dream_cancelled',False))
            stack.enter_context(patch.object(dream,'_dream_lock',asyncio.Lock()))
            for name,value in {'create_dream_log':1,'get_calendar_range':[{'date':'2026-09-01','diary':'fixture'}],'get_unprocessed_memories':[],'get_aging_memories':[],'get_active_scenes':[],'get_permanent_memories':[],'resolve_model_endpoint':('https://relay.example/v1/chat/completions',KEY,'openai')}.items():
                stack.enter_context(patch.object(db,name,AsyncMock(return_value=value)))
            stack.enter_context(patch.object(db,'update_dream_log',saved))
            stack.enter_context(patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)))
            events=[e async for e in dream.run_dream(model_override='fixture')]
        saved.assert_awaited_once()
        self.assertEqual(saved.await_args.kwargs['status'],'error')
        self.assertEqual(saved.await_args.kwargs['dream_narrative'],'internal_error')
        self.safe(str(saved.await_args.kwargs));self.safe(events)

    async def test_reasoning_dispatch_uses_real_hostname(self):
        for base, native in [('https://relay.example/openrouter/v1/chat/completions',False),('https://openrouter.ai:9443/api/v1/chat/completions',True)]:
            requests=[]
            class Client:
                async def __aenter__(self):return self
                async def __aexit__(self,*a):pass
                async def post(self,url,**kw):
                    requests.append((url,kw))
                    return httpx.Response(200,json={'choices':[{'message':{'content':'fixture'}}]})
            with patch.object(httpx,'AsyncClient',return_value=Client()):
                iterator=app._stream_with_tools([],[],{},'openai/gpt-5',0.7,[],'fixture','',False,api_url=base,api_key=KEY,record_events=False,extract_enabled=False,reasoning_effort='high')
                chunks=[c async for c in iterator]
            self.assertEqual(len(requests),1)
            self.assertEqual('HTTP-Referer' in requests[0][1]['headers'],native)
            self.assertEqual(app._detect_provider_type(base),'openrouter' if native else 'generic')

    async def test_tool_loop_embedded_error_is_failure(self):
        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self,*a): pass
            async def post(self,*a,**kw):
                return httpx.Response(200,json={'error':{'message':KEY}})
        with patch.object(httpx,'AsyncClient',return_value=Client()):
            iterator=app._stream_with_tools([],[],{},'fixture',0.7,[],'fixture','',False,api_url='https://relay.example/v1/chat/completions',api_key=KEY,record_events=False,extract_enabled=False)
            chunks=[c async for c in app._with_ev_session(iterator,'fixture',False)]
        text=''.join(c.decode() if isinstance(c,bytes) else c for c in chunks)
        self.safe(text); self.assertIn('upstream_error',text)
        self.assertNotIn('choices',text); self.assertEqual(text.count('[DONE]'),1)

    async def test_generic_credits_preserve_authority_and_path(self):
        real_client=httpx.AsyncClient
        cases=[('https://v1.example/api','/api'),('https://v10.example/openai','/openai'),
               ('https://v1-api.example/svc','/svc'),('https://api.example/openai/v1beta','/openai/v1beta'),
               ('https://relay.example/v1',''),('https://h.example:8443/v1/chat/completions',''),
               ('http://v1.example:8097/api','/api'),('https://v1.example/api/chat/completions','/api'),
               ('http://[::1]:8097/openai/v10','/openai/v10')]
        for source in ('provider','env'):
            for base,prefix in cases:
                with self.subTest(source=source,base=base):
                    calls=[]
                    def handler(req):
                        calls.append(req)
                        return httpx.Response(200,json={'hard_limit_usd':3,'total_usage':1})
                    with patch.object(app,'get_all_providers',AsyncMock(return_value=[dict(ROW,api_base_url=base)] if source=='provider' else [])),patch.object(app,'API_KEY',KEY),patch.object(app,'API_BASE_URL',base),patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)):
                        r=await self.client.get('/admin/credits')
                    self.assertEqual(r.status_code,200);self.assertEqual(len(calls),2)
                    origin=httpx.URL(base)
                    for req in calls:
                        self.assertEqual((req.url.scheme,req.url.host,req.url.port),(origin.scheme,origin.host,origin.port))
                        self.assertEqual(req.headers['authorization'],'Bearer '+KEY)
                    self.assertEqual([q.url.path for q in calls],[prefix+'/v1/dashboard/billing/'+p for p in ('subscription','usage')])

    async def test_url_rejection_matrix_and_hostname_dispatch(self):
        import security
        for base in ('https://relay.example/a\x01b','https://relay.example/a\x7fb',
                     'https://relay.example/a\\b','https://relay.example:0/v1','https://relay.example:/v1'):
            with self.subTest(base=base),self.assertRaises(security.InvalidRequest):
                security.validate_upstream_url(base)
        real_client=httpx.AsyncClient
        for base in ('https://evil-openrouter.ai/v1','https://openrouter.ai.evil.example/v1',
                     'https://relay.example/openrouter.ai/v1'):
            with self.subTest(base=base):
                self.assertFalse(security.is_openrouter_url(base))
                calls=[]
                def handler(req):
                    calls.append(req)
                    return httpx.Response(200,json={'hard_limit_usd':3,'total_usage':1})
                with patch.object(app,'get_all_providers',AsyncMock(return_value=[dict(ROW,api_base_url=base)])),patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)):
                    await self.client.get('/admin/credits')
                self.assertEqual(len(calls),2)
                self.assertTrue(calls[0].url.path.endswith('/v1/dashboard/billing/subscription'))
                self.assertTrue(calls[1].url.path.endswith('/v1/dashboard/billing/usage'))

    async def test_provider_url_and_credential_inputs_reject_before_write(self):
        for method,path,write_name in (('POST','/admin/providers','create_provider'),('PUT','/admin/providers/7','update_provider')):
            for base in ('https://user@relay.example/v1','https://relay.example:0/v1','https://relay.example/a\x01b'):
                with self.subTest(method=method,base=base),patch.object(app,write_name,AsyncMock(return_value=ROW)) as write:
                    r=await self.client.request(method,path,json={'name':'fixture','api_base_url':base,'api_key':KEY})
                    self.assertEqual(r.status_code,400);self.assertEqual(r.json()['error_code'],'invalid_request');write.assert_not_awaited()
        for key in (None,123,[],{},False):
            with self.subTest(key=key),patch.object(app,'create_provider',AsyncMock(return_value=ROW)) as write:
                r=await self.client.post('/admin/providers',json={'name':'fixture','api_base_url':ROW['api_base_url'],'api_key':key})
                self.assertEqual(r.status_code,400);self.assertEqual(r.json()['error_code'],'invalid_request');write.assert_not_awaited()

    async def test_clear_contract_and_not_found_status(self):
        for path,payload in (('/admin/config/search_api_key',{'clear':False}),('/admin/search-config',{'clear':True,'engine':'tavily'})):
            # A destructive mutation in one arm must not poison the next arm.
            self.pool.values['search_api_key']=KEY
            self.pool.writes.clear()
            with self.subTest(path=path):
                r=await self.client.put(path,json=payload)
                self.assertEqual(r.status_code,400);self.assertEqual(r.json()['error_code'],'invalid_request')
                self.assertEqual(self.pool.values['search_api_key'],KEY);self.assertFalse(self.pool.writes)
        with patch.object(app,'get_provider',AsyncMock(return_value=None)):
            r=await self.client.get('/admin/providers/999/models')
        self.assertEqual(r.status_code,404);self.assertEqual(r.json(),{'error':'not_found','error_code':'not_found'})

    async def test_second_credit_path_failure_is_not_success(self):
        real_client=httpx.AsyncClient
        for base in ('https://relay.example/v1','https://openrouter.ai:9443/api/v1'):
            with self.subTest(base=base):
                calls=[]
                def handler(req):
                    calls.append(req)
                    return httpx.Response(500,text=KEY) if len(calls)==2 else httpx.Response(200,json={'hard_limit_usd':3,'data':{'usage':1}})
                with patch.object(app,'get_all_providers',AsyncMock(return_value=[dict(ROW,api_base_url=base)])),patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)):
                    r=await self.client.get('/admin/credits')
                self.assertEqual(len(calls),2);self.assertEqual(r.status_code,200)
                self.assertEqual(r.json()['providers'],[{'provider_id':7,'provider_name':'fixture','error_code':'http_500'}]);self.safe(r.text)

    async def chat_with_upstream(self,raw,*,stream=True,fmt='openai'):
        # Actual HTTP chat entry, fake DB reads and recorded upstream transport.
        self.pool.values.update(memory_enabled='false',reminder_tools_enabled='false',mcp_mode='off')
        real_client=httpx.AsyncClient; calls=[]
        def handler(req):
            calls.append(req)
            return httpx.Response(200,content=raw.encode(),headers={'content-type':'application/octet-stream'})
        with ExitStack() as stack:
            provider=dict(ROW,provider_name='fixture',api_format=fmt)
            for name,value in {'resolve_scope_snapshot':(True,None,'global',None,None),'get_reset_generation':0,'get_memory_enabled':False,'resolve_provider_for_model':provider}.items():
                stack.enter_context(patch.object(app,name,AsyncMock(return_value=value)))
            stack.enter_context(patch.object(httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw)))
            r=await self.client.post('/v1/chat/completions',json={'model':'fixture','stream':stream,'skip_system_prompt':True,'messages':[{'role':'user','content':'fixture'}]})
        self.assertEqual(len(calls),1)
        self.assertEqual(json.loads(calls[0].content)['stream'],stream)
        self.assertEqual(calls[0].url.path,'/v1/messages' if fmt=='anthropic' else '/v1/chat/completions')
        return r

    def assert_stream_error(self,response,code):
        self.assertEqual(response.status_code,200);self.safe(response.text)
        data=[json.loads(l[6:]) for l in response.text.splitlines() if l.startswith('data: ') and l!='data: [DONE]']
        errors=[d for d in data if d.get('error_code')]
        self.assertEqual(errors,[{'error':code,'error_code':code}])
        self.assertEqual(response.text.count('[DONE]'),1)
        self.assertTrue(response.text.endswith('data: [DONE]\n\n'))

    async def test_direct_stream_rejects_non_sse_body(self):
        bodies=[json.dumps({'error':{'message':KEY}}),'<html>'+KEY+'</html>',json.dumps({'choices':[{'message':{'content':KEY}}]})]
        for raw in bodies:
            for end in ('','\n\n'):
                with self.subTest(raw=raw,end=end):
                    r=await self.chat_with_upstream(raw+end)
                    self.assert_stream_error(r,'parse_failed');self.assertNotIn('choices',r.text)

    def anthropic_prefix(self):
        def event(kind,**fields):
            return 'event: '+kind+'\ndata: '+json.dumps({'type':kind,**fields})+'\n\n'
        return (': keepalive\n\nid: fixture\nretry: 1000\n'+event('ping')+
                event('message_start',message={'role':'assistant','usage':{}})+
                event('content_block_delta',index=0,delta={'type':'text_delta','text':'part-'})+
                event('content_block_delta',index=0,delta={'type':'text_delta','text':'one'}))

    async def test_adapted_stream_rejects_non_sse_event(self):
        # Raw upstream bytes pass through the real adapter and outer safe_sse.
        bodies=[json.dumps({'error':{'message':KEY}}),'<html>'+KEY+'</html>',json.dumps({'choices':[{'message':{'content':KEY}}]})]
        for raw in bodies:
            for end in ('','\n\n'):
                with self.subTest(raw=raw,end=end):
                    r=await self.chat_with_upstream(raw+end,fmt='anthropic')
                    self.assert_stream_error(r,'parse_failed');self.assertNotIn('choices',r.text)
        with self.subTest(kind='valid_anthropic_stream'):
            raw=self.anthropic_prefix()+'event: message_stop\ndata: {"type":"message_stop"}\n\n'
            r=await self.chat_with_upstream(raw,fmt='anthropic')
            self.assertEqual(r.status_code,200);self.assertNotIn('error_code',r.text)
            data=[json.loads(l[6:]) for l in r.text.splitlines() if l.startswith('data: ') and l!='data: [DONE]']
            content=''.join(c.get('delta',{}).get('content','') for d in data for c in d.get('choices',[]))
            self.assertEqual(content,'part-one');self.assertEqual(r.text.count('[DONE]'),1)
            self.assertTrue(r.text.endswith('data: [DONE]\n\n'))
        with self.subTest(kind='empty_body_unchanged'):
            r=await self.chat_with_upstream('',fmt='anthropic')
            self.assertEqual(r.status_code,200);self.assertNotIn('choices',r.text)
            self.assertNotIn('error_code',r.text);self.assertEqual(r.text.count('[DONE]'),1)

    async def test_direct_stream_inband_error_preserves_prior_content(self):
        normal='data: '+json.dumps({'choices':[{'delta':{'content':'part-one'}}],'error':None})+'\n\n'
        for fmt in ('openai','anthropic'):
            for end in (('','\n\n') if fmt=='openai' else ('\n','\n\n')):
                with self.subTest(fmt=fmt,end=end):
                    raw=(normal+'data: '+json.dumps({'error':{'message':KEY}})+end if fmt=='openai' else
                         self.anthropic_prefix()+'event: error\ndata: '+json.dumps({'type':'error','error':{'message':KEY}})+end)
                    r=await self.chat_with_upstream(raw,fmt=fmt)
                    self.assert_stream_error(r,'upstream_error')
                    data=[json.loads(l[6:]) for l in r.text.splitlines() if l.startswith('data: ') and l!='data: [DONE]']
                    content=''.join(c.get('delta',{}).get('content','') for d in data for c in d.get('choices',[]))
                    self.assertEqual(content,'part-one')
                    self.assertLess(r.text.index('part-'),r.text.index('error_code'))

    async def test_direct_stream_preserves_sse_fields_and_null(self):
        raw=': keepalive\n\nevent: message\nid: fixture\nretry: 1000\ndata: '+json.dumps({'choices':[{'delta':{'content':'fixture-ok'}}],'error':None})+'\n\ndata: [DONE]\n\n'
        r=await self.chat_with_upstream(raw)
        self.assertEqual(r.status_code,200);self.assertIn('fixture-ok',r.text);self.assertNotIn('error_code',r.text)
        self.assertIn(': keepalive',r.text);self.assertIn('retry: 1000',r.text);self.assertEqual(r.text.count('[DONE]'),1)

    async def test_buffered_chat_200_error_is_not_success(self):
        for raw,code in ((json.dumps({'error':{'message':KEY}}),'upstream_error'),(json.dumps({'type':'error','error':None,'message':KEY}),'upstream_error'),('<html>'+KEY+'</html>','parse_failed')):
            with self.subTest(code=code):
                r=await self.chat_with_upstream(raw,stream=False)
                self.assertEqual(r.status_code,502);self.assertEqual(r.json(),{'error':code,'error_code':code});self.safe(r.text)

    async def test_scope_has_no_raw_exception_returns(self):
        # Completeness supplement; behavior is exercised above and by the PG suite.
        names={'api_migrate_embeddings','api_embedding_stats','api_extract_now','api_get_config','api_set_config','api_get_providers','api_create_provider','api_update_provider','api_delete_provider','api_test_provider','api_get_provider_models','api_set_search_config','api_search_test','api_get_credits','api_process_file_chunks','api_sync_export','api_sync_import_backup','update_single_memory','add_memory_manual','api_daily_digest','api_generate_day_page','api_generate_week_summary','api_generate_month_summary','api_generate_quarter_summary','api_generate_year_summary','api_dream_status','api_dream_history','api_update_scene','api_get_all_saved_models','api_get_saved_models','api_add_saved_model','api_update_saved_model','api_delete_saved_model','api_update_profile_now'}
        source=(ROOT/'main.py').read_text(encoding='utf-8')
        found={n.name:n for n in ast.parse(source).body if getattr(n,'name',None) in names}
        self.assertEqual(set(found),names)
        for name,n in found.items():
            with self.subTest(function=name):
                for child in ast.walk(n):
                    if isinstance(child,ast.Return):self.assertNotIn('str(e)',ast.get_source_segment(source,child))


if __name__=='__main__': unittest.main(verbosity=2)
