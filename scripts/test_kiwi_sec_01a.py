"""SEC-01a: real ASGI/production functions, fake DB and recorded HTTP only.

No lifespan, external service or developer .env is used. PostgreSQL coverage
remains in test_kiwi_safety_sync.py. Run directly; failures are named assertions.
"""
import asyncio
import io
import json
import os
import sys
import unittest
import zipfile
from contextlib import redirect_stdout
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
        for meta in ({'format_version':3,'secrets_configured':[]},{'format_version':2,'secrets_configured':['not_secret']},[],{'format_version':True,'secrets_configured':[]}):
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
                self.assertEqual(r.status_code,400); client.assert_not_called()

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


if __name__=='__main__': unittest.main(verbosity=2)
