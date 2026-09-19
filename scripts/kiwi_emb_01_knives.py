#!/usr/bin/env python3
"""EMB-01 counterexamples. Disposable PG and clean committed checkout only.

Each mutation is restored byte-for-byte; only assertions count as RED.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
CASES={
 '01':('embedding_versioning.py','06'), '02':('database.py','06'),
 '03':('database.py','06'), '04':('database.py','06'), '05':('database.py','06'),
 '05e':('database.py','06'), '06':('embedding_versioning.py','02'),
 '07':('database.py','03'), '08':('database.py','03'), '09':('database.py','04'),
 '10':('database.py','05'), '11':('embedding_jobs.py','09'), '11e':('embedding_jobs.py','09'),
 '12':('embedding_jobs.py','09'), '13':('embedding_jobs.py','09'), '14':('embedding_jobs.py','09'),
 '15':('embedding_versioning.py','06'), '16':('embedding_jobs.py','08'),
 '17':('embedding_jobs.py','08'), '18':('embedding_jobs.py','12'),
 '19':('main.py','10'), '20':('tool_drawer.py','07'),
 '21':('embedding_probe.py','11'), '22':('embedding_probe.py','16'),
 '23':('embedding_probe.py','16'), '24':('embedding_probe.py','16'),
 '25':('database.py','18'), '26':('embedding_versioning.py','04'),
 '27':('embedding_jobs.py','09'), '28':('embedding_jobs.py','12'), '29':('tool_drawer.py','07'),
 '30':('embedding_probe.py','16'), '31a':('security.py','16'), '31b':('security.py','16'),
 '32':('embedding_jobs.py','09'), '32e':('embedding_jobs.py','09'),
}


def once(s,a,b):
    if s.count(a)!=1: raise RuntimeError(f'anchor count {s.count(a)}: {a[:80]}')
    return s.replace(a,b,1)


def function(s,name,change):
    match=re.search(r'^(?:async )?def '+re.escape(name)+r'\(',s,re.M)
    if not match: raise RuntimeError('missing function '+name)
    start=match.start(); end=re.search(r'\n(?:async )?def ',s[match.end():])
    stop=match.end()+end.start() if end else len(s)
    return s[:start]+change(s[start:stop])+s[stop:]


def mutate(k,s):
    if k=='01':
        return function(s,'cosine_similarity',lambda _: 'def cosine_similarity(a,b):\n    return sum(x*y for x,y in zip(a,b))\n')
    if k in ('02','03','04','05','05e'):
        name={'02':'_vector_search','03':'search_scenes','04':'search_file_chunks','05':'_vector_search','05e':'_vector_search'}[k]
        def change(part):
            if k!='05':
                part=re.sub(r'(?:m\.)?embedding_profile = (\$[12])',r'\1::text IS NOT NULL',part)
            if k!='05e': part=once(part,"if kind != 'current':","if False:")
            return part
        return function(s,name,change)
    if k=='06': return once(s,"['emb-v1', source_tag,", "['emb-v1', 'source-omitted',")
    if k=='07': return once(s,"elif (provider.get('api_format') or 'openai') != 'openai':",'elif False:')
    if k=='08':
        s=once(s,"if not provider.get('api_key'):","if not (provider.get('api_key') or API_KEY):")
        return once(s,"EmbeddingRoute(url,provider['api_key'],model", "EmbeddingRoute(url,provider.get('api_key') or API_KEY,model")
    if k=='09': return function(s,'_insert_memory_tx',lambda p:once(p,'    new_id = await conn.fetchval(',"    payload = (payload[0],None,*payload[2:])\n    new_id = await conn.fetchval("))
    if k=='10': return function(s,'soften_memory',lambda p:once(p,'embedding = $3,','embedding = COALESCE($3,embedding),'))
    if k in ('11','11e'):
        if k=='11': s=function(s,'_assert_owner',lambda p:once(p,'lease_until > clock_timestamp()','TRUE'))
        return function(s,'_renew_embedding_lease',lambda p:once(p,' AND lease_until > clock_timestamp()',''))
    if k=='12': return once(s,' AND content IS NOT DISTINCT FROM $8',' AND $8::text IS NOT NULL')
    if k=='13': return once(s,'if result.profile!=target:','if False:')
    if k=='14':
        return function(s,'_finish_embedding_job',lambda p:once(once(p,'            await _assert_owner(conn,job_id,token)\n',''),'AND owner_token=$2 AND lease_until > clock_timestamp()', 'AND $2::text IS NOT NULL'))
    if k=='15':
        return once(s,'    if scale == 0:\n        return None','    if scale == 0:\n        return [0.]*len(vector), 1.')
    if k=='16': return once(s,'async def get_embedding_status():','async def get_embedding_status():\n    await db.get_embedding("status mutation")')
    if k=='17': return once(s,"NOT IN ('digested','dream_deleted')","NOT IN ('digested')")
    if k=='18': return once(s,'SET {counter}={counter}+1,','SET {counter}={counter}+{0 if counter == "failed" else 1},')
    if k=='19': return once(s,"return stable_error('deprecated')","return {'status':'done'}")
    if k=='20': return once(s,'if generation != _refresh_generation:','if False:')
    if k=='21': return once(s,"message = error['message']","message = str(data)")
    if k=='22': return once(s,'secret and any(secret in candidate','secret and len(secret)>=8 and any(secret in candidate')
    if k=='23': return once(s,'    for name, value in controlled.items():',"    if controlled['upstream_message'] is not None: controlled['upstream_message']=controlled['upstream_message'][:2000]\n    for name, value in controlled.items():")
    if k=='24': return once(s,'clean = redact_for_diagnostic(value, secrets)',"clean = value if name == 'upstream_request_id' else redact_for_diagnostic(value, secrets)")
    if k=='25':
        a=s.index('        valid = isinstance(data,list)');b=s.index('        results = [None] * n',a)
        return s[:a]+s[b:]
    if k=='26': return once(s,' and not isinstance(x, bool)','')
    if k=='27': return once(s,'if after is None or after.profile!=target:','if False:')
    if k=='28': return once(s,'                if result is None:',"                if result.profile != target:\n                    await _finish_embedding_job(job_id,token,'target_changed'); return\n                if result is None:")
    if k=='29': return once(s,'if generation != _refresh_generation:', 'if any(result is not None for result in results) and generation != _refresh_generation:')
    # Normalization alone is redundant with unquote: remove both comparison
    # copies to test the encoded-key boundary, rather than claiming a false RED.
    if k=='30': return once(s,'candidates = (value, normalized, unquote(value))','candidates = (value,)')
    if k=='31a': return once(s,"for name in ('httpx', 'httpcore', 'httpcore.http11', 'httpcore.http2'):", 'for name in ():')
    if k=='31b': return once(s,"for name in ('httpx', 'httpcore', 'httpcore.http11', 'httpcore.http2'):", "for name in ('httpx',):")
    if k=='32': return function(s,'_assert_owner',lambda p:once(p,'clock_timestamp()','NOW()'))
    if k=='32e': return function(s,'_renew_embedding_lease',lambda p:once(p,'lease_until > clock_timestamp()','lease_until > NOW()'))
    raise ValueError(k)


def run(case=None):
    cmd=[sys.executable,'-B','scripts/test_kiwi_emb_01.py']
    if case: cmd+=['--case',case]
    return subprocess.run(cmd,cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,encoding='utf-8',timeout=180)


def execute(output, selected):
    output=Path(output).resolve()
    if output.is_relative_to(ROOT): raise RuntimeError('write evidence outside checkout')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(): raise RuntimeError('clean committed tree required')
    before=run()
    if before.returncode: raise RuntimeError('preflight failed: '+before.stderr[-3000:])
    rows=[]
    for k in selected:
        filename,case=CASES[k];path=ROOT/filename;original=path.read_bytes()
        try:
            path.write_text(mutate(k,original.decode('utf-8').replace('\r\n','\n')),encoding='utf-8',newline='\n')
            result=run(case);log=result.stdout+result.stderr
            reasons=re.findall(r'^AssertionError: (.*)',log,re.M)
            crash=bool(re.search(r'^ERROR:|errors=[1-9]',log,re.M))
            equivalent=k.endswith('e')
            state='EQUIVALENT' if equivalent and result.returncode==0 else ('RED' if not equivalent and result.returncode and reasons and not crash else 'CRASH' if crash or not reasons and result.returncode else 'SURVIVED')
            row=dict(knife='K-'+k,test='T-EMB-'+case,result=state,reason=reasons)
            if equivalent: row['mechanism']='Python classification retains isolation' if k=='05e' else '_assert_owner rejects expired leases'
            rows.append(row);print(k,state,flush=True)
        finally:
            path.write_bytes(original)
            assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256(original).digest()
    after=run();head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    files=sorted({file for file,_ in CASES.values()}|{'daily_digest.py','dream.py','security.py','scripts/test_kiwi_emb_01.py','scripts/test_kiwi_emb_01_panel.mjs','scripts/kiwi_emb_01_knives.py','admin-panel/js/embedding-panel.mjs','admin-panel/js/config.js','admin-panel/js/pages/providers.js'})
    blobs={p:subprocess.check_output(['git','rev-parse',f'{head}:{p}'],cwd=ROOT,text=True).strip() for p in files}
    output.write_text(json.dumps(dict(ticket='KIWI-EMB-01',head=head,source_blobs=blobs,preflight=before.returncode,restored=after.returncode,kind='disposable PG16; simulated providers; no production',results=rows),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if after.returncode==0 and all(r['result'] in ('RED','EQUIVALENT') for r in rows) else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);parser.add_argument('--only')
    args=parser.parse_args();sys.exit(execute(args.output,args.only.split(',') if args.only else list(CASES)))
