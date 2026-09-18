"""Durable embedding rebuilds. Only loop-local workers; SQL owns concurrency."""
import asyncio
import json
import secrets
import database as db

MEMORY_ELIGIBLE = "COALESCE(memory_type,'fragment') NOT IN ('digested','dream_deleted') AND (valid_until IS NULL OR valid_until > NOW())"
TABLES = {'memories': MEMORY_ELIGIBLE, 'mem_scenes': "status='active'", 'project_file_chunks': 'TRUE'}


class LeaseLost(Exception):
    pass


async def _init_embedding_schema(conn):
    for table in TABLES:
        for name, kind in (('embedding_profile','TEXT'),('embedding_model','TEXT'),('embedding_dim','INTEGER'),('embedding_source_hash','TEXT')):
            await conn.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {kind}')
        await conn.execute(f"UPDATE {table} SET embedding_profile='unknown' WHERE embedding IS NOT NULL AND embedding_profile IS NULL")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding_rebuild_jobs (
            id SERIAL PRIMARY KEY, singleton_key TEXT NOT NULL DEFAULT 'embedding_rebuild',
            target_profile TEXT NOT NULL, target_model TEXT, target_provider_id INTEGER,
            scope TEXT NOT NULL CHECK (scope IN ('stale','all')),
            state TEXT NOT NULL CHECK (state IN ('running','done','target_changed')),
            total INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
            total_characters BIGINT NOT NULL DEFAULT 0, owner_token TEXT, lease_until TIMESTAMPTZ,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_error_code TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_embedding_rebuild_active
            ON embedding_rebuild_jobs (singleton_key) WHERE state='running';
        CREATE TABLE IF NOT EXISTS embedding_rebuild_items (
            id SERIAL PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES embedding_rebuild_jobs(id) ON DELETE CASCADE,
            table_name TEXT NOT NULL CHECK(table_name IN ('memories','mem_scenes','project_file_chunks')),
            row_id INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','done','failed','changed')),
            error_code TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(job_id,table_name,row_id));
        CREATE INDEX IF NOT EXISTS idx_embedding_rebuild_items_job ON embedding_rebuild_items(job_id,state);
    """)


def source_text(table, row):
    if table == 'memories':
        return db.build_memory_embedding_text(row.get('title'),row['content'])
    if table == 'mem_scenes':
        return db.build_scene_embedding_text(row.get('title'),row.get('atomic_facts'))
    return db.build_file_chunk_embedding_text(row['content'])


def classification(table, row, profile):
    return db.classify_embedding_row(row['embedding'],row.get('embedding_profile'),row.get('embedding_dim'),
                                     row.get('embedding_source_hash'),profile,source_text(table,row))


async def _eligible_rows(conn):
    return {table:await conn.fetch(f'SELECT * FROM {table} WHERE {condition} ORDER BY id') for table,condition in TABLES.items()}


def job_public(job):
    if not job:
        return {'state':'idle'}
    keys=('state','id','scope','total','done','failed','skipped','total_characters','started_at','updated_at','last_error_code','lease_expired')
    return {key:job[key] for key in keys}


async def get_embedding_status():
    route=await db._resolve_embedding_route()
    reason='ok' if route else (await db._resolve_embedding_route_detail())[1]
    pool=await db.get_pool()
    async with pool.acquire() as conn:
        rows=await _eligible_rows(conn)
        job=await conn.fetchrow("""SELECT *, state='running' AND (lease_until IS NULL OR lease_until<=NOW()) AS lease_expired
            FROM embedding_rebuild_jobs WHERE state='running' OR updated_at>NOW()-INTERVAL '24 hours'
            ORDER BY (state='running') DESC,id DESC LIMIT 1""")
    profile=route.profile if route else None
    tables={}; totals=dict(total=0,current=0,stale=0,missing=0,pending_rows=0,pending_characters=0); dim=None
    for table, entries in rows.items():
        counts=dict(total=len(entries),current=0,stale=0,missing=0)
        for row in entries:
            kind=classification(table,row,profile)
            counts[kind]+=1
            if kind!='current':
                totals['pending_rows']+=1; totals['pending_characters']+=len(source_text(table,row))
            elif dim is None:
                dim=row['embedding_dim']
        tables[table]=counts
        for key,value in counts.items(): totals[key]+=value
    import tool_drawer
    drawer_profile=tool_drawer._category_profile
    return {'status':'ok','route':{'available':route is not None,'reason':reason,'source':route.source if route else None,
             'provider_id':route.provider_id if route else None,'model_id':route.model_id if route else None,'profile':profile,'dim':dim if route else None},
            'tables':tables,'totals':totals,'drawer':{'ready':bool(tool_drawer._category_embeddings),
             'profile':drawer_profile,'matches_current':profile is not None and drawer_profile==profile},'job':job_public(job)}


async def create_or_resume_rebuild_job(scope='stale'):
    if scope not in ('stale','all'):
        raise ValueError('invalid_request')
    route=await db._resolve_embedding_route()
    if route is None:
        return None
    pool=await db.get_pool()
    async with pool.acquire() as conn:
        existing=await conn.fetchrow("SELECT *, lease_until>NOW() AS live FROM embedding_rebuild_jobs WHERE state='running'")
        if existing:
            return dict(existing),not bool(existing['live'])
        rows=await _eligible_rows(conn)
        selected=[(table,row) for table,entries in rows.items() for row in entries if scope=='all' or classification(table,row,route.profile)!='current']
        try:
            async with conn.transaction():
                job=await conn.fetchrow("""INSERT INTO embedding_rebuild_jobs(target_profile,target_model,target_provider_id,scope,state,total,total_characters)
                    VALUES($1,$2,$3,$4,'running',$5,$6) RETURNING *""",route.profile,route.model_id,route.provider_id,scope,len(selected),sum(len(source_text(t,r)) for t,r in selected))
                await conn.executemany("INSERT INTO embedding_rebuild_items(job_id,table_name,row_id,state) VALUES($1,$2,$3,'pending')",
                                      [(job['id'],table,row['id']) for table,row in selected])
            return dict(job),True
        except db.asyncpg.UniqueViolationError:
            existing=await conn.fetchrow("SELECT *, lease_until>NOW() AS live FROM embedding_rebuild_jobs WHERE state='running'")
            if existing: return dict(existing),not bool(existing['live'])
    return await create_or_resume_rebuild_job(scope)


async def _assert_owner(conn, job_id, token):
    row=await conn.fetchrow("""SELECT id FROM embedding_rebuild_jobs
        WHERE id=$1 AND owner_token=$2 AND lease_until > NOW() AND state='running' FOR UPDATE""",job_id,token)
    if not row:
        raise LeaseLost()


async def _claim_embedding_job(job_id,token):
    pool=await db.get_pool()
    return bool(await pool.fetchval("""UPDATE embedding_rebuild_jobs SET owner_token=$2,
        lease_until=NOW()+INTERVAL '2 minutes',updated_at=NOW() WHERE id=$1 AND state='running'
        AND (owner_token IS NULL OR lease_until IS NULL OR lease_until<=NOW()) RETURNING id""",job_id,token))


async def _renew_embedding_lease(job_id,token):
    pool=await db.get_pool()
    try:
        async with pool.acquire() as conn,conn.transaction():
            await _assert_owner(conn,job_id,token)
            return bool(await conn.fetchval("""UPDATE embedding_rebuild_jobs SET lease_until=NOW()+INTERVAL '2 minutes',updated_at=NOW()
                WHERE id=$1 AND owner_token=$2 AND lease_until > NOW() AND state='running' RETURNING id""",job_id,token))
    except LeaseLost:
        return False


async def _finish_embedding_job(job_id,token,state):
    if state not in ('done','target_changed'): raise ValueError('invalid state')
    pool=await db.get_pool()
    try:
        async with pool.acquire() as conn,conn.transaction():
            await _assert_owner(conn,job_id,token)
            return bool(await conn.fetchval("""UPDATE embedding_rebuild_jobs SET state=$3,updated_at=NOW(),lease_until=NULL
                WHERE id=$1 AND owner_token=$2 AND lease_until > NOW() AND state='running' RETURNING id""",job_id,token,state))
    except LeaseLost:
        return False


async def _cas_embedding(conn,table,row,result,*,missing_only=False):
    if table not in TABLES: raise ValueError('invalid table')
    payload=db.embedding_db_payload(result,source_text(table,row))
    cast='::jsonb' if table=='mem_scenes' else ''
    sql=f'UPDATE {table} SET embedding=$1{cast},embedding_profile=$2,embedding_model=$3,embedding_dim=$4,embedding_source_hash=$5 WHERE id=$6'
    args=[*payload,row['id']]
    if table=='memories':
        sql+=" AND title IS NOT DISTINCT FROM $7 AND content IS NOT DISTINCT FROM $8 AND COALESCE(memory_type,'fragment')=$9"
        args.extend([row.get('title'),row['content'],row.get('memory_type') or 'fragment'])
    elif table=='mem_scenes':
        sql+=' AND title IS NOT DISTINCT FROM $7 AND atomic_facts IS NOT DISTINCT FROM $8::jsonb AND status=$9'
        facts=row.get('atomic_facts')
        args.extend([row.get('title'),facts if isinstance(facts,str) else json.dumps(facts),row['status']])
    else:
        sql+=' AND content IS NOT DISTINCT FROM $7'; args.append(row['content'])
    sql+=' AND '+TABLES[table]
    if missing_only: sql+=' AND embedding IS NULL'
    return (await conn.execute(sql,*args))=='UPDATE 1'


async def _record_item(conn,job_id,item_id,state,error=None):
    counter={'done':'done','failed':'failed','changed':'skipped'}[state]
    changed=await conn.fetchval("UPDATE embedding_rebuild_items SET state=$3,error_code=$4,updated_at=NOW() WHERE id=$1 AND job_id=$2 AND state='pending' RETURNING id",item_id,job_id,state,error)
    if changed:
        await conn.execute(f'UPDATE embedding_rebuild_jobs SET {counter}={counter}+1,updated_at=NOW() WHERE id=$1',job_id)


async def run_embedding_rebuild_job(job_id,wait_for_lease=False):
    token=secrets.token_hex(16)
    pool=await db.get_pool()
    while not await _claim_embedding_job(job_id,token):
        state=await pool.fetchval('SELECT state FROM embedding_rebuild_jobs WHERE id=$1',job_id)
        if not wait_for_lease or state!='running': return
        await asyncio.sleep(10)
    target=await pool.fetchval('SELECT target_profile FROM embedding_rebuild_jobs WHERE id=$1',job_id)
    try:
        while True:
            if not await _renew_embedding_lease(job_id,token): raise LeaseLost()
            before=await db._resolve_embedding_route()
            if before is None or before.profile!=target:
                await _finish_embedding_job(job_id,token,'target_changed'); return
            items=await pool.fetch("""SELECT * FROM embedding_rebuild_items WHERE job_id=$1 AND state='pending'
                AND table_name=(SELECT table_name FROM embedding_rebuild_items WHERE job_id=$1 AND state='pending' ORDER BY id LIMIT 1)
                ORDER BY id LIMIT 20""",job_id)
            if not items:
                await _finish_embedding_job(job_id,token,'done'); return
            table=items[0]['table_name']
            snapshots=[]
            for item in items:
                row=await pool.fetchrow(f'SELECT * FROM {table} WHERE id=$1 AND {TABLES[table]}',item['row_id'])
                if row: snapshots.append((item,row))
                else:
                    async with pool.acquire() as conn,conn.transaction():
                        await _assert_owner(conn,job_id,token)
                        await _record_item(conn,job_id,item['id'],'changed')
            if not snapshots: continue
            results=await db.get_embeddings_batch([source_text(table,row) for _,row in snapshots])
            after=await db._resolve_embedding_route()
            if after is None or after.profile!=target:
                await _finish_embedding_job(job_id,token,'target_changed'); return
            for (item,row),result in zip(snapshots,results):
                if result is None:
                    async with pool.acquire() as conn,conn.transaction():
                        await _assert_owner(conn,job_id,token)
                        await _record_item(conn,job_id,item['id'],'failed','upstream_error')
                    continue
                if result.profile!=target:
                    await _finish_embedding_job(job_id,token,'target_changed'); return
                async with pool.acquire() as conn,conn.transaction():
                    await _assert_owner(conn,job_id,token)
                    wrote=await _cas_embedding(conn,table,row,result)
                    await _record_item(conn,job_id,item['id'],'done' if wrote else 'changed')
    except LeaseLost:
        db.safe_log('embedding_rebuild_lease_lost','internal_error')
    except Exception:
        db.safe_log('embedding_rebuild_failed','internal_error')
        try:
            async with pool.acquire() as conn,conn.transaction():
                await _assert_owner(conn,job_id,token)
                await conn.execute("UPDATE embedding_rebuild_jobs SET last_error_code='internal_error',updated_at=NOW() WHERE id=$1",job_id)
        except Exception:
            pass


async def resume_embedding_rebuilds(spawn):
    pool=await db.get_pool()
    jobs=await pool.fetch("SELECT id FROM embedding_rebuild_jobs WHERE state='running'")
    for job in jobs: spawn(run_embedding_rebuild_job(job['id'],wait_for_lease=True))
