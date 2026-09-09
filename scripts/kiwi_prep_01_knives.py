#!/usr/bin/env python3
"""PREP-01 mutation runner: exact anchors, restoration and explicit RED/CRASH.

Run on a clean committed tree with output outside the checkout. K-2 has
stdout and logging variants. K-7 needs the disposable PostgreSQL test DSN.
"""
import argparse
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

# Each anchor must occur exactly once. Tuple: file, before, after, test method.
MUTATIONS = {
 1: ('mcp_access.py','                    local = True','                    local = False','ApplicationGuards.test_T_PREP_01_02_observation'),
 2: ('mcp_access.py',"            host = parse_authority(authority)","            print(authority)\n            host = parse_authority(authority)",'ApplicationGuards.test_T_PREP_01_02_observation'),
 3: ('mcp_access.py',"return {'protection': 'preview',", "return {'last_host': 'configured', 'protection': 'preview',",'ApplicationGuards.test_T_PREP_01_01_status_shape'),
 4: ('mcp_access.py',"'protection': 'preview'", "'protection': 'enabled'",'ApplicationGuards.test_T_PREP_01_01_status_shape'),
 5: ('mcp_access.py','return value.isascii() and parse_authority(value, wildcard_port=True) is not None','return value.startswith("*.") or parse_authority(value, wildcard_port=True) is not None','ApplicationGuards.test_T_PREP_01_01_status_shape'),
 6: ('mcp_access.py','        await app(scope, receive, send)',"        from starlette.responses import Response\n        await Response(status_code=400)(scope, receive, send)",'ApplicationGuards.test_T_PREP_01_03_passthrough'),
 7: ('database.py','id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1)','id SMALLINT PRIMARY KEY DEFAULT 1','PG'),
 8: ('scripts/update_support.py','    if not gate:','    if False:','UpdateGuards.test_T_PREP_01_06_three_conditions'),
 9: ('scripts/update_support.py','return 0 if registered else 3','return 3','UpdateGuards.test_T_PREP_01_07_configuration'),
 10: ('scripts/update_support.py','def dotenv(key):',"def dotenv(key):\n    subprocess.run(['sh', '-c', '. ./.env'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",'UpdateGuards.test_T_PREP_01_07_configuration'),
 11: ('scripts/update.sh','PORT=8080','git reset --hard "$LATEST" --quiet\nPORT=8080','UpdateGuards.test_T_PREP_01_08_preflight_before_mutation'),
 12: ('scripts/update.sh','[ "$AUTO_MODE" = "1" ] && exit 3','[ "$AUTO_MODE" = "1" ] && exit 0','UpdateGuards.test_T_PREP_01_06_three_conditions'),
 13: ('scripts/update.sh','PREV_COMMIT="${STATE_FIELDS[0]}"','PREV_COMMIT="${STATE_FIELDS[1]}"','UpdateGuards.test_T_PREP_01_09_resume'),
 14: ('scripts/update.sh','    PORT="${STATE_FIELDS[3]}"','    PORT="${STATE_FIELDS[3]}"\n    $COMPOSE exec -T db sh -c pg_dump >/dev/null','UpdateGuards.test_T_PREP_01_09_resume'),
 15: ('scripts/update.sh','if [ "$RESUMED" = "0" ] && [ -n "$(git diff','if [ -n "$(git diff','UpdateGuards.test_T_PREP_01_09_resume'),
 16: ('scripts/update_support.py',"'/memory/mcp','POST'", "'/memory/mcp','GET'",'UpdateGuards.test_T_PREP_01_10_initialize_probe'),
 17: ('scripts/update_support.py',"code != '200'", "code not in ('200', '405')",'UpdateGuards.test_T_PREP_01_10_initialize_probe'),
 18: ('scripts/update_support.py',"'--max-time', '5', ", "",'UpdateGuards.test_T_PREP_01_10_initialize_probe'),
 19: ('requirements.txt','starlette==1.3.1\n','', 'DeliveryGuards.test_T_PREP_01_11_delivery_contract'),
 20: ('scripts/upgrade_gates.json','"mcp_access_control":false','"mcp_access_control":true','DeliveryGuards.test_T_PREP_01_11_delivery_contract'),
 21: ('mcp_server.py','import os\n','import os\n# mutation\n','DeliveryGuards.test_T_PREP_01_11_delivery_contract'),
 22: ('mcp_access.py','import ipaddress','from mcp.server.transport_security import TransportSecuritySettings\nimport ipaddress','DeliveryGuards.test_T_PREP_01_12_no_protection_wiring'),
}


def run_tests(method=None):
    args=[sys.executable, '-B', str(ROOT/'scripts/test_kiwi_prep_01.py')]
    if method=='PG': args=[sys.executable,'-B',str(ROOT/'scripts/test_kiwi_safety_sync.py')]
    elif method: args.append(method)
    env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run(args,cwd=ROOT,env=env,text=True,encoding='utf-8',errors='replace',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240)


def execute(output, selected):
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():
        raise RuntimeError('knife execution requires a clean committed tree')
    preflight=run_tests()
    if preflight.returncode:
        raise RuntimeError('preflight failed: '+preflight.stdout[-3000:])
    results=[]
    for number in selected:
        variants=['stdout','logging'] if number==2 else ['default']
        for variant in variants:
            filename,before,after,method=MUTATIONS[number]
            if variant=='logging': after="            import logging\n            logging.getLogger('mcp').warning(authority)\n            host = parse_authority(authority)"
            path=ROOT/filename; original=path.read_bytes()
            text=original.decode('utf-8').replace('\r\n','\n')
            if text.count(before)!=1: raise RuntimeError(f'K-PREP-{number}: anchor count {text.count(before)}')
            try:
                path.write_text(text.replace(before,after,1),encoding='utf-8',newline='\n')
                result=run_tests(method)
                reasons=re.findall(r'^AssertionError: (.*)$',result.stdout,re.M)
                crashed=bool(re.search(r'^ERROR:|errors=[1-9]|update fixture exceeded 35s',result.stdout,re.M))
                status='RED' if result.returncode and reasons and not crashed else ('SURVIVED' if result.returncode==0 else 'CRASH')
                if method=='PG' and 'BEGIN T-PREP-01-PG-01' not in result.stdout: status='CRASH'
                results.append(dict(knife=f'K-PREP-{number}',variant=variant,test=method,status=status,reason=reasons,exit_code=result.returncode))
                print(f'K-PREP-{number} {variant}: {status}',flush=True)
            finally:
                path.write_bytes(original)
                if path.read_bytes()!=original: raise RuntimeError('restoration failed')
    restored=run_tests()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    files=sorted({v[0] for v in MUTATIONS.values()}|{'main.py','scripts/test_kiwi_prep_01.py','scripts/test_kiwi_safety_sync.py','scripts/prep_update_fixture.py','scripts/update_support_jq.sh','scripts/prep_authority.jq','scripts/kiwi_prep_01_knives.py','scripts/test_prep_framework_compat.py','scripts/check_prep_audit.py'})
    blobs={p:subprocess.check_output(['git','rev-parse',head+':'+p],cwd=ROOT,text=True).strip() for p in files}
    ledger=dict(head=head,source_blobs=blobs,preflight=preflight.returncode,restored=restored.returncode,results=results)
    Path(output).write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if restored.returncode==0 and all(r['status']=='RED' for r in results) else 1

KNIVES = [
    (1, "02", "Count IP literal as foreign"),
    (2, "02", "Persist or log Host"),
    (3, "01", "Return an extra last_host field"),
    (4, "01", "Claim protection is enabled"),
    (5, "01", "Accept wildcard hostname"),
    (6, "03", "Reject body in observation wrapper"),
    (7, "PG-01", "Remove single-row CHECK"),
    (8, "06", "Ignore target upgrade gate"),
    (9, "07", "Ignore pending deployment configuration"),
    (10, "07", "Execute dotenv as shell"),
    (11, "08", "Run preflight after merge"),
    (12, "06", "Exit zero on automatic block"),
    (13, "09", "Lose previous commit in resume state"),
    (14, "09", "Repeat backup during resume"),
    (15, "09", "Remove resume loop guard"),
    (16, "10", "Probe MCP with GET"),
    (17, "10", "Treat HTTP 405 as healthy"),
    (18, "10", "Remove MCP probe timeout"),
    (19, "11", "Remove Starlette pin"),
    (20, "11", "Enable upgrade gate early"),
    (21, "11", "Change mcp_server.py baseline blob"),
    (22, "12", "Import transport protection in production"),
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument('--output')
    parser.add_argument('--only',help='comma-separated knife numbers; omitted means all 22')
    args = parser.parse_args()
    if not args.list:
        if not args.output: parser.error('--output is required; write outside the checkout')
        raise SystemExit(execute(args.output,[int(n) for n in args.only.split(',')] if args.only else list(MUTATIONS)))
    print(json.dumps([{"knife": f"K-PREP-{n}", "guard": f"T-PREP-01-{guard}",
                       "mutation": description, "status": "PLANNED"}
                      for n, guard, description in KNIVES], indent=2))
