#!/usr/bin/env python3
"""BUILD-01 exact-anchor mutation runner.

Run on a clean committed tree; write the evidence outside the checkout.
"""
import argparse
import json

INVENTORY = [
    ('memory transport_security keyword removed', ['T-10','T-12']),
    ('calendar passes TransportSecuritySettings(**_SECURITY.model_dump()), an equal distinct object', ['T-02','T-10']),
    ('unregistered Host accepted by guard', ['T-03']),
    ('IP parsed using a numeric string prefix', ['T-07']),
    ('IP skips Origin validation', ['T-04']),
    ('IP appended to shared allowed_hosts', ['T-02','T-07']),
    ('rejection body contains original Host', ['T-06']),
    ('transport-security logger filter removed', ['T-06','T-12']),
    ('wildcard domain registration accepted', ['T-02']),
    ('Origin list derived from CORS_ORIGINS', ['T-02','T-10']),
    ('missing Host accepted', ['T-03']),
    ('Content-Type guard removed', ['T-05']),
    ('SDK rebinding protection disabled', ['T-12']),
    ('bare 127.0.0.1 missing from builtins', ['T-03']),
    ('mcp pin replaced with open lower bound', ['T-01']),
    ('status returns preview', ['T-08']),
    ('startup output contains registration value', ['T-09']),
    ('guard wrapped outside observation', ['T-10']),
    ('authority accepts unbracketed multi-colon host', ['T-07']),
    ('Origin wildcard port uses substring matching', ['T-04']),
    ('IP Host rewrite removed', ['T-03','T-07']),
    ('Host rewrite applied to non-IP requests', ['T-07']),
    ('Content-Type stripped before validation', ['T-05']),
]


import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = {1: ('mcp_server.py', 'FastMCP("Memory Garden", stateless_http=True, transport_security=_SECURITY)', 'FastMCP("Memory Garden", stateless_http=True)', '10'), 2: ('mcp_server.py', 'FastMCP("Calendar & Dream", stateless_http=True, transport_security=_SECURITY)', 'FastMCP("Calendar & Dream", stateless_http=True, transport_security=__import__("mcp.server.transport_security", fromlist=["TransportSecuritySettings"]).TransportSecuritySettings(**_SECURITY.model_dump()))', '02'), 3: ('mcp_access.py', 'if not is_ip and not _listed(raw, settings.allowed_hosts):', 'if False:', '03'), 4: ('mcp_access.py', '            is_ip = False', "            is_ip = raw.split(':')[0].replace('.','').isdigit()", '07'), 5: ('mcp_access.py', 'if origin is not None and not _listed(origin, settings.allowed_origins):', 'if not is_ip and origin is not None and not _listed(origin, settings.allowed_origins):', '04'), 6: ('mcp_access.py', '        if is_ip:\n', '        if is_ip:\n            settings.allowed_hosts.append(raw)\n', '07'), 7: ('mcp_access.py', "payload = {'error': code, 'error_code': code}", "payload = {'error': code, 'error_code': code, 'host': dict(scope['headers']).get(b'host', b'').decode('latin-1')}", '06'), 8: ('mcp_access.py', '    logger.addFilter(TransportFilter())', '    # mutation: filter not installed', '12'), 9: ('mcp_access.py', 'return value.isascii() and parse_authority(value, wildcard_port=True) is not None', 'return value.startswith("*.") or (value.isascii() and parse_authority(value, wildcard_port=True) is not None)', '02'), 10: ('mcp_access.py', "os.getenv('MCP_ALLOWED_ORIGINS', '')", "os.getenv('CORS_ORIGINS', '')", '02'), 11: ('mcp_access.py', 'authority = parse_authority(raw)', "raw = raw or 'localhost'\n        authority = parse_authority(raw)", '03'), 12: ('mcp_access.py', "if scope.get('method') == 'POST' and not (bool(ct) and ct.lower().startswith('application/json')):", 'if False:', '05'), 13: ('mcp_access.py', 'enable_dns_rebinding_protection=True,', 'enable_dns_rebinding_protection=False,', '12'), 14: ('mcp_access.py', "_BUILTIN_HOSTS = ['localhost', 'localhost:*', '127.0.0.1', '127.0.0.1:*', '[::1]', '[::1]:*']", "_BUILTIN_HOSTS = ['localhost', 'localhost:*', '127.0.0.1:*', '[::1]', '[::1]:*']", '03'), 15: ('requirements.txt', 'mcp==1.29.1', 'mcp>=1.8.0', '01'), 16: ('mcp_access.py', "'protection': 'enabled'", "'protection': 'preview'", '08'), 17: ('mcp_access.py', 'def log_mcp_access_summary():', "def log_mcp_access_summary():\n    print(os.getenv('MCP_ALLOWED_HOSTS', ''))", '09'), 18: ('main.py', 'observe_mcp_access(guard_mcp_access(_mcp_endpoint, _SECURITY))', 'guard_mcp_access(observe_mcp_access(_mcp_endpoint), _SECURITY)', '10'), 19: ('mcp_access.py', "if value.count(':') > 1:\n            return None", "if value.count(':') > 1:\n            return value", '07'), 20: ('mcp_access.py', "raw.startswith(p[:-2] + ':')", "(p[:-2] + ':') in raw", '04'), 21: ('mcp_access.py', 'return await app(forwarded, receive, send)', 'return await app(scope, receive, send)', '07'), 22: ('mcp_access.py', '        if is_ip:\n', '        if True:\n', '07'), 23: ('mcp_access.py', "ct.lower().startswith('application/json')", "ct.strip().lower().startswith('application/json')", '05')}


def run_tests(number=None):
    args = [sys.executable, '-B', str(ROOT/'scripts/test_kiwi_build_01.py')]
    if number:
        import ast
        tree=ast.parse((ROOT/'scripts/test_kiwi_build_01.py').read_text(encoding='utf-8'))
        method=next(n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_T_BUILD_01_'+number+'_'))
        args.append('BuildGuards.'+method)
    return subprocess.run(args,cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',timeout=120)


def execute(output, selected):
    output=Path(output).resolve()
    if output.is_relative_to(ROOT): raise RuntimeError('output must be outside checkout')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip(): raise RuntimeError('clean committed tree required')
    preflight=run_tests()
    if preflight.returncode: raise RuntimeError('preflight failed: '+preflight.stdout[-3000:])
    rows=[]
    for n in selected:
        filename,before,after,test=MUTATIONS[n];path=ROOT/filename;original=path.read_bytes()
        source=original.decode('utf-8').replace('\r\n','\n')
        if source.count(before)!=1: raise RuntimeError(f'K-BUILD-{n}: anchor count {source.count(before)}')
        try:
            path.write_text(source.replace(before,after,1),encoding='utf-8',newline='\n')
            result=run_tests(test)
            reasons=re.findall(r'^AssertionError: (.*)$',result.stdout,re.M)
            crash=bool(re.search(r'^ERROR:|errors=[1-9]',result.stdout,re.M))
            status='RED' if result.returncode and reasons and not crash else ('SURVIVED' if not result.returncode else 'CRASH')
            # K-2 must also be caught by the independent static guard.
            if n==18:
                linked=subprocess.run([sys.executable, "-B", str(ROOT/"scripts/test_kiwi_sec_01b.py"), "MountGuards.test_T_SEC_01b_08_layers"], cwd=ROOT, env=dict(os.environ,PYTHONUTF8="1",PYTHONDONTWRITEBYTECODE="1"), capture_output=True,text=True,encoding="utf-8",timeout=120)
                linked_output=linked.stdout+linked.stderr
                linked_reasons=re.findall(r"^AssertionError: (.*)$",linked_output,re.M)
                if not linked.returncode or not linked_reasons or re.search(r"^ERROR:|errors=[1-9]",linked_output,re.M): status="CRASH"
                reasons+=linked_reasons
            if n==2:
                static=run_tests('10'); static_reasons=re.findall(r'^AssertionError: (.*)$',static.stdout,re.M)
                if not static.returncode or not static_reasons or re.search(r'^ERROR:|errors=[1-9]',static.stdout,re.M): status='CRASH'
                reasons+=static_reasons
            rows.append(dict(knife=f'K-BUILD-{n}',status=status,test=test,reason=reasons,exit_code=result.returncode))
            print(f'K-BUILD-{n}: {status}',flush=True)
        finally:
            path.write_bytes(original)
            if path.read_bytes()!=original: raise RuntimeError('restore mismatch')
    restored=run_tests()
    files=sorted({v[0] for v in MUTATIONS.values()}|{'Dockerfile','.github/workflows/ci.yml','scripts/test_kiwi_build_01.py','scripts/test_kiwi_sec_01b.py','scripts/kiwi_build_01_knives.py'})
    blobs={f:subprocess.check_output(['git','rev-parse','HEAD:'+f],cwd=ROOT,text=True).strip() for f in files}
    data=dict(head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_blobs=blobs,
        preflight=preflight.returncode,restored=restored.returncode,results=rows)
    output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if restored.returncode==0 and all(x['status']=='RED' for x in rows) else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list',action='store_true');parser.add_argument('--output');parser.add_argument('--only')
    args=parser.parse_args()
    if args.list:
        print(json.dumps([dict(id=f'K-BUILD-{i}',mutation=name,guards=guards) for i,(name,guards) in enumerate(INVENTORY,1)],indent=2))
    else:
        if not args.output: parser.error('--output required')
        raise SystemExit(execute(args.output,[int(x) for x in args.only.split(',')] if args.only else list(MUTATIONS)))
