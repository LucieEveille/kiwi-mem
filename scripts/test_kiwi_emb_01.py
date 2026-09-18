#!/usr/bin/env python3
"""EMB-01: disposable PG16, real persistence/ASGI, deterministic outbound HTTP.

Never uses DATABASE_URL as an admin DSN; no application lifespan or real model.
Stage A missing symbols are named assertion failures, not import errors.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
import logging
import math
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch
import uuid
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DATABASE_URL'] = 'postgresql://unused@127.0.0.1:1/unused'
import asyncpg
import httpx
import config
import database as db
import main as appmod
import tool_drawer as drawer

REAL_CLIENT = httpx.AsyncClient
KEY = 'EMB_synthetic_secret_f01877'
COLUMNS = ('embedding', 'embedding_profile', 'embedding_model', 'embedding_dim', 'embedding_source_hash')
B2 = {'11', '13', '16'}


class EmbGuards(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.admin = os.environ.get('KIWI_TEST_DATABASE_URL', '')
        u = urlsplit(self.admin)
        if u.scheme not in ('postgres','postgresql') or u.hostname not in ('127.0.0.1','localhost','::1') or not u.path.strip('/'):
            raise RuntimeError('explicit loopback KIWI_TEST_DATABASE_URL required')
        self.name = 'kiwi_emb_' + uuid.uuid4().hex
        admin = await asyncpg.connect(self.admin)
        try:
            self.assertGreaterEqual(int(await admin.fetchval('SHOW server_version_num')), 160000)
            await admin.execute(f'CREATE DATABASE "{self.name}"')
        finally:
            await admin.close()
        db.DATABASE_URL = urlunsplit((u.scheme,u.netloc,'/'+self.name,u.query,''))
        db._pool = None
        with redirect_stdout(io.StringIO()):
            await db.init_tables()
        self.pool = await db.get_pool()
        self.client = REAL_CLIENT(transport=httpx.ASGITransport(app=appmod.app), base_url='http://localhost')

    async def asyncTearDown(self):
        await self.client.aclose()
        with redirect_stdout(io.StringIO()):
            await db.close_pool()
        admin = await asyncpg.connect(self.admin)
        try:
            await admin.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=$1 AND pid<>pg_backend_pid()', self.name)
            await admin.execute(f'DROP DATABASE "{self.name}"')
        finally:
            await admin.close()

    def need(self, name, module=db):
        self.assertTrue(hasattr(module, name), f'missing_seam:{name}')
        return getattr(module, name)

    def route(self, model='model-A', provider=7, url='https://embedding.example/v1/embeddings'):
        cls = self.need('EmbeddingRoute')
        r = cls(url=url, api_key=KEY, model_id=model, provider_id=provider,
                api_format='openai', source='env' if provider is None else 'provider',
                provider_name=None if provider is None else 'fixture', profile='')
        return replace(r, profile=self.need('embedding_profile_for_route')(r))

    def result(self, r=None, vector=None):
        r = r or self.route()
        v = [1., 0.] if vector is None else vector
        return self.need('EmbeddingResult')(vector=v, model_id=r.model_id, profile=r.profile, dim=len(v), provider_id=r.provider_id)

    def outbound(self, handler):
        return patch.object(httpx,'AsyncClient',lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))

    async def seed(self, text='source', title='', kind='fragment', permanent=False):
        return await self.pool.fetchval('INSERT INTO memories(content,title,memory_type,is_permanent) VALUES($1,$2,$3,$4) RETURNING id',text,title,kind,permanent)

    async def configure(self, key, value):
        await self.pool.execute("INSERT INTO gateway_config(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",key,value)

    async def stamp(self, mid, result, text):
        payload = self.need('embedding_db_payload')(result,text)
        await self.pool.execute('UPDATE memories SET embedding=$1,embedding_profile=$2,embedding_model=$3,embedding_dim=$4,embedding_source_hash=$5 WHERE id=$6',*payload,mid)

    async def test_T_EMB_01_schema(self):
        columns = await self.pool.fetch("SELECT table_name,column_name FROM information_schema.columns WHERE table_name=ANY($1)",['memories','mem_scenes','project_file_chunks'])
        for table in ('memories','mem_scenes','project_file_chunks'):
            with self.subTest(table=table):
                self.assertTrue(set(COLUMNS)<= {r['column_name'] for r in columns if r['table_name']==table},'missing identity columns')
        self.need('EmbeddingResult')
        mid = await self.seed()
        await self.pool.execute('UPDATE memories SET embedding=$1 WHERE id=$2','[1,0]',mid)
        for _ in range(2):
            with redirect_stdout(io.StringIO()): await db.init_tables()
        self.assertEqual(await self.pool.fetchval('SELECT embedding_profile FROM memories WHERE id=$1',mid),'unknown')
        self.assertIsNotNone(await self.pool.fetchval("SELECT to_regclass('embedding_rebuild_items')"))
        self.assertIsNotNone(await self.pool.fetchval("SELECT to_regclass('uq_embedding_rebuild_active')"))

    async def test_T_EMB_02_identity(self):
        r = self.route()
        profile = self.need('embedding_profile_for_route')
        self.assertNotEqual(r.profile,self.route(provider=None).profile)
        self.assertNotEqual(r.profile,self.route(provider=8).profile)
        self.assertNotEqual(r.profile,self.route(model='model-B').profile)
        self.assertEqual(r.profile,profile(replace(r,api_key='rotated-key')))
        self.assertEqual(r.profile,profile(replace(r,url='https://EMBEDDING.example:443/v1/embeddings/')))
        self.assertEqual(len(r.profile),64)

    async def test_T_EMB_03_routes(self):
        resolve = self.need('_resolve_embedding_route_detail')
        provider = dict(provider_id=7,provider_name='fixture',api_base_url='https://provider.example/v1',api_key=KEY,api_format='openai')
        with patch.object(config,'get_config',AsyncMock(return_value='panel-model')), patch.object(db,'API_KEY','env-key'), patch.object(db,'API_BASE_URL','https://env.example/v1/chat/completions'), patch.object(db,'EMBEDDING_MODEL',''):
            with patch.object(db,'resolve_provider_for_model',AsyncMock(return_value=provider)):
                r, reason = await resolve()
                self.assertEqual((r.source,r.provider_id,r.api_key,r.model_id,reason),('provider',7,KEY,'panel-model','ok'))
            with patch.object(db,'resolve_provider_for_model',AsyncMock(return_value={**provider,'api_format':'anthropic'})):
                r, _ = await resolve()
                self.assertEqual((r.source,r.api_key,r.model_id),('env','env-key','panel-model'))
            with patch.object(db,'resolve_provider_for_model',AsyncMock(return_value={**provider,'api_key':''})),patch.object(db,'EMBEDDING_MODEL','env-model'):
                r, _ = await resolve()
                self.assertEqual((r.url,r.api_key,r.model_id),('https://env.example/v1/embeddings','env-key','panel-model'))
            with patch.object(db,'resolve_provider_for_model',AsyncMock(side_effect=RuntimeError(KEY))):
                r, reason = await resolve()
                self.assertIsNone(r)
                self.assertEqual(reason,'db_error')

    async def test_T_EMB_04_write_identities(self):
        result = self.result()
        payload = self.need('embedding_db_payload')
        for vector in ([0.,0.],[],[True],[float('nan')],[float('inf')]):
            self.assertEqual(payload(self.result(vector=vector),'text'),(None,)*5)
        self.assertEqual(payload(self.result(vector=[1e308]),'text')[3],1)
        with patch.object(db,'get_embedding',AsyncMock(return_value=result)):
            mid = await db.save_memory('source',title='title')
            await db.update_memory(mid, content='edited')
            row = await self.pool.fetchrow('SELECT * FROM memories WHERE id=$1',mid)
            self.assertEqual(tuple(row[k] for k in COLUMNS),payload(result,'title edited'))
            async with self.pool.acquire() as conn:
                with patch.object(db,'get_embedding',AsyncMock(side_effect=AssertionError('locked outward'))):
                    locked = await db._insert_memory_tx(conn,content='locked',embedding=result)
            self.assertEqual(await self.pool.fetchval('SELECT embedding_profile FROM memories WHERE id=$1',locked),result.profile)
            scene = await db.create_mem_scene('scene','narrative',['fact'])
            await db.update_mem_scene(scene,atomic_facts=['edited'])
            scene_row = await self.pool.fetchrow('SELECT * FROM mem_scenes WHERE id=$1',scene)
            self.assertEqual(scene_row['embedding_source_hash'],db.embedding_source_hash(db.build_scene_embedding_text('scene',['edited'])))
            await db.save_file_chunks('project','file','fixture','chunk text')
            self.assertEqual(await self.pool.fetchval('SELECT embedding_profile FROM project_file_chunks LIMIT 1'),result.profile)
            import daily_digest, dream
            from datetime import datetime, timezone
            permanent = await self.seed('locked missing', permanent=True)
            with patch.object(db,'get_embeddings_batch',AsyncMock(return_value=[result])):
                await db.backfill_permanent_memory_embeddings()
            self.assertEqual(await self.pool.fetchval('SELECT embedding_profile FROM memories WHERE id=$1',permanent),result.profile)
            await self.pool.execute('UPDATE mem_scenes SET embedding=NULL WHERE id=$1',scene)
            await daily_digest.backfill_scene_embeddings()
            self.assertEqual(await self.pool.fetchval('SELECT embedding_profile FROM mem_scenes WHERE id=$1',scene),result.profile)
            outcome = await dream._execute_dream_action({'type':'merge','memory_ids':[mid],'merged_title':'merged','merged_content':'merged content'},0,{'memories_merged':0})
            self.assertTrue(outcome['success'])
            merged = await self.pool.fetchrow("SELECT * FROM memories WHERE source='dream_merge'")
            self.assertEqual(tuple(merged[k] for k in COLUMNS),payload(result,'merged merged content'))
            await self.pool.execute("UPDATE memories SET created_at='2026-09-10T10:00:00+08:00' WHERE id=$1",locked)
            for text in ('digest source 2','digest source 3'):
                extra=await self.seed(text)
                await self.pool.execute("UPDATE memories SET created_at='2026-09-10T10:00:00+08:00' WHERE id=$1",extra)
            data = {'choices':[{'message':{'content':json.dumps([{'title':'digest','content':'digest text'}])}}]}
            with patch.object(db,'resolve_model_endpoint',AsyncMock(return_value=('https://fixture.example/v1/chat/completions',KEY,'openai'))),self.outbound(lambda req:httpx.Response(200,json=data)):
                receipt = await daily_digest._run_daily_digest_impl('2026-09-10',datetime.now(timezone.utc))
            self.assertEqual(receipt.get('digests'),1)
            digest = await self.pool.fetchrow("SELECT * FROM memories WHERE source='ai_digest'")
            self.assertEqual(tuple(digest[k] for k in COLUMNS),payload(result,db.build_memory_embedding_text(digest['title'],digest['content'])))

    async def test_T_EMB_05_changed_text_failure(self):
        result = self.result()
        mid = await self.seed('a sufficiently long original memory text',title='title')
        await self.stamp(mid,result,'title a sufficiently long original memory text')
        with patch.object(db,'get_embedding',AsyncMock(return_value=None)):
            await db.update_memory(mid,content='new content')
            row = await self.pool.fetchrow('SELECT * FROM memories WHERE id=$1',mid)
            self.assertEqual(tuple(row[k] for k in COLUMNS),(None,)*5)
            await self.stamp(mid,result,'title new content')
            await db.soften_memory(mid,'summary',target_resolution=0.5)
        row = await self.pool.fetchrow('SELECT * FROM memories WHERE id=$1',mid)
        self.assertEqual(tuple(row[k] for k in COLUMNS),(None,)*5)

    async def test_T_EMB_06_comparison(self):
        classify = self.need('classify_embedding_row')
        r = self.result()
        for a,b in (([],[]),([1],[1,0]),([0],[0]),([math.nan],[1]),([True],[1])):
            self.assertIsNone(db.cosine_similarity(a,b))
        self.assertAlmostEqual(db.cosine_similarity([1e308],[1e308]),1.)
        for kind, embedding, profile, text_hash in [('wrong-profile','[1,0]','other',db.embedding_source_hash('source')),('wrong-source','[1,0]',r.profile,'old'),('zero','[0,0]',r.profile,db.embedding_source_hash('source'))]:
            mid = await self.seed()
            await self.pool.execute('UPDATE memories SET embedding=$1,embedding_profile=$2,embedding_dim=2,embedding_source_hash=$3 WHERE id=$4',embedding,profile,text_hash,mid)
        good = await self.seed()
        await self.stamp(good,r,'source')
        found = await db._vector_search(r,10,{'_semantic_threshold':0})
        self.assertEqual({x['id'] for x in found},{good})
        self.assertEqual(classify('[1,0]',r.profile,2,'old',r.profile,'source'),'stale')
        self.assertEqual(classify('[0,0]',r.profile,2,db.embedding_source_hash('source'),r.profile,'source'),'missing')
        with patch.object(db,'get_embedding',AsyncMock(return_value=r)):
            sid = await db.create_mem_scene('scene','narrative',['fact'])
            await db.save_file_chunks('p','f','file','chunk')
            self.assertEqual(len(await db.search_scenes(r,limit=10,min_sim=0)),1)
            self.assertEqual(len(await db.search_file_chunks('p','query')),1)
            await self.pool.execute("UPDATE mem_scenes SET embedding_profile='other'")
            await self.pool.execute("UPDATE project_file_chunks SET embedding_profile='other'")
            self.assertEqual(await db.search_scenes(r,limit=10,min_sim=0),[])
            self.assertEqual(await db.search_file_chunks('p','query'),[])

    async def test_T_EMB_07_drawer(self):
        refresh = self.need('refresh_category_embeddings',drawer)
        r = self.result()
        saved = (drawer.CATEGORIES.copy(),drawer._category_embeddings.copy(),drawer._category_profile,drawer._refresh_generation)
        try:
            drawer.CATEGORIES.clear(); drawer.CATEGORIES.update({'a':{'description':'a'},'b':{'description':'b'}})
            with patch.object(db,'get_embeddings_batch',AsyncMock(return_value=[None,r])):
                await refresh()
            self.assertEqual(set(drawer._category_embeddings),{'b'})
            self.assertEqual(drawer._category_profile,r.profile)
            started, release = asyncio.Event(), asyncio.Event()
            async def late(_):
                started.set(); await release.wait(); return [None,None]
            with patch.object(db,'get_embeddings_batch',late):
                task=asyncio.create_task(refresh()); await asyncio.wait_for(started.wait(),2)
                with patch.object(db,'get_embeddings_batch',AsyncMock(return_value=[r,r])): await refresh()
                release.set(); await asyncio.wait_for(task,2)
            self.assertEqual(set(drawer._category_embeddings),{'a','b'})
        finally:
            drawer.CATEGORIES.clear(); drawer.CATEGORIES.update(saved[0])
            drawer._category_embeddings=saved[1]; drawer._category_profile=saved[2]; drawer._refresh_generation=saved[3]

    async def test_T_EMB_08_status(self):
        status = self.need('get_embedding_status')
        r = self.route()
        await self.seed('one'); await self.seed('excluded',kind='dream_deleted')
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=r)),patch.object(db,'get_embedding',AsyncMock(side_effect=AssertionError('status outward'))),self.outbound(lambda req: self.fail('status HTTP')):
            out = await status()
        self.assertEqual(out['totals']['total'],1)
        self.assertEqual(out['totals']['pending_rows'],1)
        self.assertEqual(out['job']['state'],'idle')

    async def test_T_EMB_09_jobs(self):
        create = self.need('create_or_resume_rebuild_job')
        run = self.need('run_embedding_rebuild_job')
        r = self.route(); current=[r]
        async def resolve(): return current[0]
        with patch.object(db,'_resolve_embedding_route',resolve):
            await self.seed('one')
            job,spawn=await create('stale'); self.assertTrue(spawn)
            jid=job['id']
            await self.pool.execute("UPDATE embedding_rebuild_jobs SET owner_token='first',lease_until=NOW()+INTERVAL '1 minute' WHERE id=$1",jid)
            same,spawn=await create('stale'); self.assertEqual(same['id'],jid); self.assertFalse(spawn)
            await self.pool.execute("UPDATE embedding_rebuild_jobs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=$1",jid)
            same,spawn=await create('stale'); self.assertTrue(spawn)
            started, release=asyncio.Event(),asyncio.Event()
            async def upstream(req):
                started.set(); await release.wait()
                return httpx.Response(200,json={'data':[{'index':0,'embedding':[1.,0.]}]})
            with self.outbound(upstream):
                task=asyncio.create_task(run(jid)); await asyncio.wait_for(started.wait(),3)
                current[0]=self.route(model='B'); release.set(); await asyncio.wait_for(task,4)
            state=await self.pool.fetchrow('SELECT * FROM embedding_rebuild_jobs WHERE id=$1',jid)
            self.assertEqual(state['state'],'target_changed'); self.assertEqual(state['done'],0)
            self.assertIsNone(await self.pool.fetchval('SELECT embedding FROM memories LIMIT 1'))

            job,_=await create('stale')
            with patch.object(db,'get_embeddings_batch',AsyncMock(return_value=[self.result(self.route(model='wrong'))])):
                await run(job['id'])
            self.assertEqual(await self.pool.fetchval('SELECT state FROM embedding_rebuild_jobs WHERE id=$1',job['id']),'target_changed')
            self.assertIsNone(await self.pool.fetchval('SELECT embedding FROM memories LIMIT 1'))
            current[0]=r
            job,_=await create('stale')
            async def lost_route(texts): current[0]=None; return [self.result(r) for _ in texts]
            with patch.object(db,'get_embeddings_batch',lost_route): await run(job['id'])
            self.assertEqual(await self.pool.fetchval('SELECT state FROM embedding_rebuild_jobs WHERE id=$1',job['id']),'target_changed')
            current[0]=r
            job,_=await create('stale'); jid=job['id']
            claim=self.need('_claim_embedding_job'); renew=self.need('_renew_embedding_lease'); finish=self.need('_finish_embedding_job')
            claimed=await asyncio.gather(claim(jid,'owner-A'),claim(jid,'owner-B'))
            self.assertEqual(sum(claimed),1,'two workers claimed the same live job')
            owner='owner-A' if claimed[0] else 'owner-B'
            self.assertFalse(await finish(jid,'old-owner','done'),'old owner wrote terminal state')
            self.assertEqual(await self.pool.fetchval('SELECT state FROM embedding_rebuild_jobs WHERE id=$1',jid),'running')
            await self.pool.execute("UPDATE embedding_rebuild_jobs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=$1",jid)
            self.assertFalse(await renew(jid,owner),'expired owner renewed lease')
            self.assertTrue(await claim(jid,'new-owner'))
            self.assertFalse(await finish(jid,owner,'done'),'superseded owner wrote terminal state')
            self.assertTrue(await finish(jid,'new-owner','target_changed'))
            job,_=await create('stale'); jid=job['id']
            async def changed(texts):
                await self.pool.execute("UPDATE memories SET content='concurrent edit'")
                return [self.result(r) for _ in texts]
            with patch.object(db,'get_embeddings_batch',changed): await run(jid)
            state=await self.pool.fetchrow('SELECT * FROM embedding_rebuild_jobs WHERE id=$1',jid)
            self.assertEqual((state['done'],state['skipped'],state['state']),(0,1,'done'))
            self.assertIsNone(await self.pool.fetchval('SELECT embedding FROM memories LIMIT 1'))
            # Steal an expired lease while the original worker is awaiting HTTP.
            job,_=await create('stale'); jid=job['id']
            started,release=asyncio.Event(),asyncio.Event()
            async def held(texts):
                started.set(); await release.wait(); return [self.result(r) for _ in texts]
            with patch.object(db,'get_embeddings_batch',held):
                task=asyncio.create_task(run(jid)); await asyncio.wait_for(started.wait(),3)
                await self.pool.execute("UPDATE embedding_rebuild_jobs SET lease_until=NOW()-INTERVAL '1 second' WHERE id=$1",jid)
                self.assertTrue(await claim(jid,'replacement'))
                release.set(); await asyncio.wait_for(task,3)
            state=await self.pool.fetchrow('SELECT * FROM embedding_rebuild_jobs WHERE id=$1',jid)
            self.assertEqual((state['done'],state['failed'],state['skipped'],state['state']),(0,0,0,'running'))
            self.assertIsNone(await self.pool.fetchval('SELECT embedding FROM memories LIMIT 1'))
            self.assertTrue(await finish(jid,'replacement','target_changed'))
            # Rebuild only writes the five vector fields; concurrent scene edits win.
            with patch.object(db,'get_embedding',AsyncMock(return_value=None)):
                scene=await db.create_mem_scene('scene','narrative',['before'])
                await db.save_file_chunks('p','f','name','before')
            job,_=await create('stale')
            async def changed_all(texts):
                await self.pool.execute("UPDATE mem_scenes SET atomic_facts='[\"after\"]'::jsonb")
                await self.pool.execute("UPDATE project_file_chunks SET content='after'")
                return [self.result(r) for _ in texts]
            with patch.object(db,'get_embeddings_batch',changed_all): await run(job['id'])
            # Scene/chunk snapshots may be read after the earlier memory batch.
            # Direct CAS checks hold the original snapshots deterministically.
            async with self.pool.acquire() as conn:
                for table,column,value in (('mem_scenes','title','new title'),('project_file_chunks','content','new content')):
                    row=await conn.fetchrow(f'SELECT * FROM {table} LIMIT 1')
                    before_vector=tuple(row[k] for k in COLUMNS)
                    await conn.execute(f'UPDATE {table} SET {column}=$1 WHERE id=$2',value,row['id'])
                    self.assertFalse(await db._cas_embedding(conn,table,row,self.result(r)))
                    after=await conn.fetchrow(f'SELECT * FROM {table} WHERE id=$1',row['id'])
                    self.assertEqual(tuple(after[k] for k in COLUMNS),before_vector)

    async def test_T_EMB_10_compatibility(self):
        self.need('get_embedding_status')
        response=await self.client.get('/admin/migrate-embeddings')
        self.assertEqual(response.status_code,410)
        self.assertEqual(response.json(),{'error':'deprecated','error_code':'deprecated'})
        self.assertFalse(hasattr(db,'migrate_embeddings'))
        await self.seed('archived',kind='digested')
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=self.route())):
            stats=await db.get_embedding_stats()
        self.assertEqual(stats['total_memories'],1)
        self.assertEqual(stats['embedding_status']['totals']['total'],0)

    async def probe(self, response, route=None):
        self.need('api_embedding_probe',appmod)
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=route or self.route())),self.outbound(lambda req: response):
            return await self.client.post('/admin/embedding-probe')

    async def test_T_EMB_11_probe(self):
        self.need('api_embedding_probe',appmod)
        out=await self.probe(httpx.Response(502,json={'error':{'message':'not implemented'}}))
        self.assertEqual(out.status_code,200)
        body=out.json(); self.assertFalse(body['ok']); self.assertNotIn('error',body)
        self.assertEqual((body['error_code'],body['upstream_message']),('http_502','not implemented'))
        out=await self.probe(httpx.Response(200,json={'data':[{'embedding':[1,0]}]}))
        self.assertTrue(out.json()['ok']); self.assertEqual(out.json()['dim'],2)
        out=await self.probe(httpx.Response(200,json={'data':[{'embedding':[0,0]}]}))
        self.assertEqual(out.json()['error_code'],'invalid_response')
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=None)):
            self.assertEqual((await self.client.post('/admin/embedding-probe')).status_code,409)
        for error,code in ((httpx.ReadTimeout(KEY),'timeout'),(httpx.ConnectError(KEY),'network:RequestError')):
            def fail(req): raise error
            with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=self.route())),self.outbound(fail):
                out=await self.client.post('/admin/embedding-probe')
            self.assertEqual(out.status_code,200); self.assertEqual(out.json()['error_code'],code)
            self.assertNotIn(KEY,out.text)

    async def test_T_EMB_12_partial_failures(self):
        create=self.need('create_or_resume_rebuild_job'); run=self.need('run_embedding_rebuild_job')
        for i in range(5): await self.seed(str(i))
        r=self.route(); result=self.result(r)
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=r)),patch.object(db,'get_embeddings_batch',AsyncMock(return_value=[result,None,result,None,result])):
            job,_=await create('stale'); await run(job['id'])
        row=await self.pool.fetchrow('SELECT * FROM embedding_rebuild_jobs WHERE id=$1',job['id'])
        self.assertEqual((row['state'],row['done'],row['failed']),('done',3,2))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM embedding_rebuild_items WHERE state='failed'"),2)
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=r)),patch.object(db,'get_embeddings_batch',AsyncMock(return_value=[None,None])):
            retry,_=await create('stale'); await run(retry['id'])
        row=await self.pool.fetchrow('SELECT * FROM embedding_rebuild_jobs WHERE id=$1',retry['id'])
        self.assertEqual((row['state'],row['done'],row['failed']),('done',0,2))

    async def test_T_EMB_13_relay_boundary(self):
        self.need('api_embedding_probe',appmod)
        out=await self.probe(httpx.Response(500,json={'error':{'message':'unsupported model'}}))
        self.assertFalse(out.json()['ok']); self.assertEqual(out.json()['error_code'],'http_500')
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=self.route())):
            status=await db.get_embedding_status()
        self.assertTrue(status['route']['available']); self.assertIsNotNone(status['route']['profile'])

    async def test_T_EMB_14_fixture_contract(self):
        result=self.result(vector=[.1,.2,.3])
        console=io.StringIO()
        with patch.object(db,'get_embedding',AsyncMock(return_value=result)),redirect_stdout(console): await db.save_memory('fixture')
        self.assertIn('含向量，3维',console.getvalue())
        with patch.object(db,'get_embedding',AsyncMock(return_value=None)),redirect_stdout(console): await db.save_memory('missing')
        self.assertIn('无向量',console.getvalue())

    async def test_T_EMB_16_diagnostics(self):
        self.need('api_embedding_probe',appmod)
        for key in ('abcde','sentinel-secret-a19a7358'):
            r=replace(self.route(),api_key=key)
            out=await self.probe(httpx.Response(401,json={'error':{'message':'invalid '+key}},headers={'x-request-id':key}),r)
            body=out.json()
            self.assertIsNone(body['upstream_message']); self.assertIsNone(body['upstream_request_id'])
            self.assertTrue(body['upstream_message_hidden']); self.assertNotIn(key,out.text)
        r=self.route()
        out=await self.probe(httpx.Response(400,json={'error':{'message':'x'*2500+KEY}}),r)
        self.assertIsNone(out.json()['upstream_message'])
        out=await self.probe(httpx.Response(400,json={'error':{'message':'x'*2500}}),r)
        self.assertEqual(len(out.json()['upstream_message']),2000); self.assertTrue(out.json()['upstream_message_truncated'])
        from urllib.parse import quote
        for unsafe in ('Bearer sample-token','sk-12345678','https://user:pass@example.org','bad\x01text',quote('space key',safe='')):
            out=await self.probe(httpx.Response(400,json={'error':{'message':unsafe}}),replace(r,api_key='space key'))
            self.assertIsNone(out.json()['upstream_message']); self.assertTrue(out.json()['upstream_message_hidden'])
        r=replace(r,api_key='a',provider_name='a',model_id='a',url='https://a.example/v1/embeddings')
        out=await self.probe(httpx.Response(401,json={'error':{'message':'a'}},headers={'x-request-id':'a'}),r)
        for field in ('provider_name','model_id','endpoint_host','upstream_message','upstream_request_id'):
            self.assertIsNone(out.json()[field])
        self.assertEqual(out.json()['error_code'],'http_401'); self.assertEqual(out.json()['source'],'provider')
        self.assertEqual(out.json()['profile'],r.profile); self.assertTrue(out.json()['upstream_message_hidden'])
        log=io.StringIO(); handler=logging.StreamHandler(log); logging.getLogger().addHandler(handler)
        try:
            with redirect_stdout(log),redirect_stderr(log):
                out=await self.probe(httpx.Response(401,json={'error':{'message':KEY}},headers={'x-request-id':KEY}))
            self.assertNotIn(KEY,out.text+log.getvalue())
        finally: logging.getLogger().removeHandler(handler)

    async def test_T_EMB_18_batch_attribution(self):
        r=self.route()
        for indices in ((-1,0),(0,0),(False,1),(0,2),(0,1.0),(0,),(0,1,2)):
            with self.subTest(indices=indices),patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=r)),self.outbound(lambda req: httpx.Response(200,json={'data':[{'index':i,'embedding':[1,0]} for i in indices]})):
                self.assertEqual(await db.get_embeddings_batch(['a','b']),[None,None])
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=r)),self.outbound(lambda req: httpx.Response(200,json={'data':[{'index':1,'embedding':[0,1]},{'index':0,'embedding':[1,0]}]})):
            results=await db.get_embeddings_batch(['a','b'])
        self.assertEqual([r.vector for r in results],[[1,0],[0,1]])
        with patch.object(db,'_resolve_embedding_route',AsyncMock(return_value=r)),self.outbound(lambda req:httpx.Response(200,json={'data':[{'index':0,'embedding':[0,0]},{'index':1,'embedding':[1,0]}]})):
            results=await db.get_embeddings_batch(['a','b'])
        self.assertIsNone(results[0]); self.assertEqual(results[1].vector,[1,0])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',choices=['b1','all'],default='all')
    parser.add_argument('--case',action='append',default=[])
    args=parser.parse_args()
    methods=unittest.defaultTestLoader.getTestCaseNames(EmbGuards)
    methods=[m for m in methods if (args.stage!='b1' or m.split('_')[3] not in B2) and (not args.case or m.split('_')[3] in args.case)]
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(EmbGuards(m) for m in methods))
    print(f'EMB guards: tests={result.testsRun} failures={len(result.failures)} errors={len(result.errors)}; PG=real disposable; model=mock')
    sys.exit(0 if result.wasSuccessful() else 1)
