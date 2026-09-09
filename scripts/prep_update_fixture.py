"""Disposable git + command doubles. Never invokes real Docker or curl."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FAKE = r'''
import sys, os, json, pathlib, subprocess
p=pathlib.Path(os.environ['PREP_FIXTURE'])
c=json.loads((p/'control.json').read_text(encoding='utf-8'))
kind=sys.argv[1]; args=sys.argv[2:]
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
with (p/'calls.jsonl').open('a') as f: f.write(json.dumps([kind,args,head])+'\n')
if kind=='docker':
    if args[:2]==['compose','version']: print('Docker Compose version fixture'); sys.exit(0)
    if args[:2]==['compose','config']:
        if c.get('compose_fail'): sys.exit(1)
        print(json.dumps({'services':{'kiwi-mem':{'environment':{'MCP_ALLOWED_HOSTS':c.get('hosts','')}}}})); sys.exit(0)
    if args[:2]==['compose','ps']: print('fixture-db'); sys.exit(0)
    if args[0]=='inspect': print('true'); sys.exit(0)
    if args[:2]==['compose','exec']: print('-- fixture dump'); sys.exit(0)
    if args[:2]==['compose','up']: sys.exit(0)
    sys.exit(0)
if kind=='sleep': sys.exit(0)
if kind=='curl':
    url=next((x for x in args if x.startswith('http://')), '')
    status=200; body='{"status":"ok"}'
    if url.endswith('/admin/mcp-access-status'):
        status=c.get('status_code',200); body=c.get('status_body',json.dumps({'foreign_host_seen':c.get('foreign',True)}))
    elif url.endswith('/memory/mcp'):
        status=c.get('mcp_code',200); body=c.get('mcp_body','{"jsonrpc":"2.0","id":1,"result":{}}')
    elif c.get('root_fail'): status=503
    if status==0: sys.exit(28)
    if '-o' in args: pathlib.Path(args[args.index('-o')+1]).write_text(body)
    elif '--output' in args: pathlib.Path(args[args.index('--output')+1]).write_text(body)
    else: sys.stdout.write(body)
    if '-w' in args or '--write-out' in args: sys.stdout.write(str(status))
    if any(x in args for x in ['-f','-fsS','-sf'] ) and status>=400: sys.exit(22)
'''


class UpdateFixture:
    def __init__(self, **control):
        self.temp = tempfile.TemporaryDirectory(prefix='kiwi-prep-')
        self.root = Path(self.temp.name)
        self.repo = self.root/'deploy'
        self.source = self.root/'source'
        self.remote = self.root/'remote.git'
        self.bin = self.root/'bin'; self.bin.mkdir()
        self.control = control
        self.save()
        (self.root/'fake.py').write_text(FAKE, encoding='utf-8')
        self.env = dict(os.environ)
        self.env.pop('MCP_ALLOWED_HOSTS', None)
        self.env.pop('MCP_ALLOWED_ORIGINS', None)
        self.env.update(PREP_FIXTURE=str(self.root), GIT_CONFIG_NOSYSTEM='1',
                        GIT_AUTHOR_NAME='PREP fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                        GIT_COMMITTER_NAME='PREP fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
        self.bash = 'C:/Program Files/Git/bin/bash.exe' if os.name=='nt' else shutil.which('bash')
        for kind in ('docker','curl','sleep'):
            path=self.bin/kind
            path.write_text('#!/usr/bin/env bash\nexec "'+sys.executable.replace('\\','/')+'" "'+str(self.root/'fake.py').replace('\\','/')+'" '+kind+' "$@"\n',encoding='utf-8',newline='\n')
            path.chmod(0o755)
        if os.name=='nt':
            (self.bin/'python3').write_text('#!/usr/bin/env bash\nexec "'+sys.executable.replace('\\','/')+'" "$@"\n',newline='\n')
        self.env['PATH'] = str(self.bin)+os.pathsep+self.env['PATH']
        self.env['PREP_BIN'] = self.bin.as_posix()
        self.git(self.root,'init','--bare',str(self.remote))
        self.git(self.root,'init','-b','main',str(self.source))
        (self.source/'scripts').mkdir()
        for rel in ('scripts/update.sh','scripts/update_support.py','mcp_access.py'):
            if (ROOT/rel).exists():
                (self.source/rel).write_text((ROOT/rel).read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
        (self.source/'docker-compose.yml').write_text('services: {}\n')
        (self.source/'.gitignore').write_text('.env\n.update-state.json\nbackups/\n')
        self.git(self.source,'add','.'); self.git(self.source,'commit','-m','old version')
        self.git(self.source,'remote','add','origin',str(self.remote))
        self.git(self.source,'push','-u','origin','main')
        self.git(self.root,'clone','-b','main',str(self.remote),str(self.repo))
        self.prev = self.head()
        (self.repo/'.env').write_text('PORT=8080\n',encoding='utf-8')

    def save(self):
        (self.root/'control.json').write_text(json.dumps(self.control),encoding='utf-8')

    def git(self,cwd,*args):
        return subprocess.check_output(['git','-c','safe.directory='+str(cwd),'-c','core.autocrlf=false',*args],cwd=cwd,env=self.env if hasattr(self,'env') else None,stderr=subprocess.DEVNULL,text=True).strip()

    def head(self): return self.git(self.repo,'rev-parse','HEAD')

    def target(self, gate=True, revised=False):
        if gate is not None:
            (self.source/'scripts/upgrade_gates.json').write_text(json.dumps({'schema':1,'gates':{'mcp_access_control':gate}}))
        (self.source/'revision.txt').write_text('new')
        if revised:
            p=self.source/'scripts/update.sh'
            s=p.read_text(encoding='utf-8'); s=s.replace('set -uo pipefail','set -uo pipefail\nprintf "new-script\\n" >> "$PREP_FIXTURE/executed"',1)
            p.write_text(s,encoding='utf-8',newline='\n')
        self.git(self.source,'add','.'); self.git(self.source,'commit','-m','target version')
        self.git(self.source,'push','origin','main')
        return self.git(self.source,'rev-parse','HEAD')

    def run(self,*args,input=''):
        output=self.root/'output.txt'
        stdin=self.root/'input.txt'; stdin.write_text(input)
        prefix='$(cygpath -u "$PREP_BIN")' if os.name=='nt' else '$PREP_BIN'
        command=[self.bash,'-c','export PATH="'+prefix+':$PATH"; exec bash scripts/update.sh "$@"','prep',*args]
        with output.open('w',encoding='utf-8') as out, stdin.open() as inp:
            process=subprocess.Popen(command,cwd=self.repo,env=self.env,stdin=inp,stdout=out,stderr=subprocess.STDOUT)
            try:
                code=process.wait(timeout=35)
            except subprocess.TimeoutExpired:
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                else:
                    process.kill()
                process.wait()
                raise AssertionError('update fixture exceeded 35s: '+output.read_text(errors='replace'))
        return subprocess.CompletedProcess(command,code,output.read_text(encoding='utf-8',errors='replace'))

    def calls(self, kind='docker'):
        p=self.root/'calls.jsonl'
        return [r for r in (json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()) if r[0]==kind] if p.exists() else []

    def close(self): self.temp.cleanup()
