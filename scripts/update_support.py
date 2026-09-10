"""Updater data handling. No dotenv execution, shell eval, or address output."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp_access import valid_host


def dotenv(key):
    value = ''
    try:
        for line in Path('.env').read_text(encoding='utf-8-sig').splitlines():
            match = re.fullmatch(r'\s*'+re.escape(key)+r'\s*=(.*)', line)
            if match:
                value = match[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1].strip()
    except OSError:
        pass
    return os.environ.get(key, value)


def port():
    value = dotenv('PORT')
    return value if re.fullmatch('[0-9]{1,5}', value) and 1 <= int(value) <= 65535 else '8080'


def request(url, method='GET', body=None):
    with tempfile.TemporaryDirectory(prefix='kiwi-probe-') as tmp:
        output = str(Path(tmp)/'body')
        args = ['curl', '-sS', '--max-time', '5', '-o', output, '-w', '%{http_code}', '-X', method]
        if body is not None:
            args += ['-H', 'Accept: application/json, text/event-stream', '-H', 'Content-Type: application/json', '--data', json.dumps(body)]
        using_curl = shutil.which('curl') is not None
        if not using_curl:
            args = ['wget','-q','-T','5','-t','1','--max-redirect=0','--server-response','-O',output]
            if body is not None:
                args += ['--header=Accept: application/json, text/event-stream','--header=Content-Type: application/json','--post-data='+json.dumps(body)]
        result = subprocess.run(['sh','-c','exec "$@"','kiwi-probe',*args,url], capture_output=True, text=True, timeout=7)
        codes = re.findall(r'HTTP/\S+\s+(\d{3})',result.stderr)
        code = result.stdout if using_curl else (codes[-1] if codes else '')
        if result.returncode or code != '200':
            return None
        raw = Path(output).read_text(encoding='utf-8')
        try:
            return json.loads(raw)
        except ValueError:
            for event in raw.replace('\r\n','\n').split('\n\n'):
                data = '\n'.join(line[5:].lstrip(' ') for line in event.splitlines() if line.startswith('data:'))
                try:
                    parsed = json.loads(data)
                    if isinstance(parsed, dict) and parsed.get('id') == 1:
                        return parsed
                except ValueError:
                    pass
    return None


def preflight(target, compose, listen_port):
    try:
        raw = subprocess.check_output(['git','show',target+':scripts/upgrade_gates.json'],stderr=subprocess.DEVNULL)
        gate = json.loads(raw)['gates']['mcp_access_control'] is True
    except (subprocess.CalledProcessError, ValueError, KeyError, TypeError):
        print('预检跳过：无法读取升级门')
        return 0
    if not gate:
        return 0
    try:
        state = request('http://127.0.0.1:'+listen_port+'/admin/mcp-access-status')
    except Exception:
        state = None
    if not isinstance(state, dict) or state.get('foreign_host_seen') is not True:
        print('预检：未能验证 MCP 远程使用情况，仅提示——若你用域名访问 MCP，请先登记')
        return 0
    hosts = dotenv('MCP_ALLOWED_HOSTS')
    try:
        result = subprocess.run(['sh','-c','exec "$@"','kiwi-config',*compose.split(),'config','--format','json'],capture_output=True,text=True,timeout=10)
        if result.returncode == 0:
            rendered = json.loads(result.stdout)['services']['kiwi-mem']['environment']
            if 'MCP_ALLOWED_HOSTS' in rendered:
                hosts = rendered['MCP_ALLOWED_HOSTS'] or ''
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        pass
    registered = isinstance(hosts, str) and any(valid_host(item.strip()) for item in hosts.split(',') if item.strip())
    return 0 if registered else 3


def load_state(path):
    if Path(path) != Path('.update-state.json'):
        raise ValueError('state path')
    state = json.loads(Path(path).read_text(encoding='utf-8'))
    if state.get('stage') != 'post-merge' or state.get('resumed') != 1:
        raise ValueError('stage')
    for key in ('prev','target'):
        if not re.fullmatch('[0-9a-f]{40,64}',state[key]):
            raise ValueError('commit')
    if subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip() != state['target']:
        raise ValueError('head')
    if state['compose'] not in ('docker compose','docker-compose'):
        raise ValueError('compose')
    if not re.fullmatch('[0-9]{1,5}',state['port']) or not 1 <= int(state['port']) <= 65535:
        raise ValueError('port')
    if not isinstance(state['args'],list) or not all(isinstance(a,str) for a in state['args']):
        raise ValueError('args')
    if not isinstance(state['backup_file'],str) or any(c in state['backup_file'] for c in '\r\n\0'):
        raise ValueError('backup')
    return state


def main():
    command, *args = sys.argv[1:]
    if command == 'port': print(port())
    elif command == 'preflight': return preflight(*args)
    elif command == 'save':
        prev,target,compose,listen_port,backup,*original = args
        state = dict(prev=prev,target=target,stage='post-merge',backup_file=backup,compose=compose,port=listen_port,args=original,resumed=1)
        path=Path('.update-state.json')
        # Mode 0600 and atomic replacement; never interpret state as commands.
        fd,tmp=tempfile.mkstemp(prefix='.update-state-',dir='.')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as out: json.dump(state,out)
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    elif command == 'load':
        state=load_state(args[0])
        for key in ('prev','target','compose','port','backup_file'):
            print(state[key])
    elif command == 'probe':
        result=request('http://127.0.0.1:'+args[0]+'/memory/mcp','POST',{
            'jsonrpc':'2.0','id':1,'method':'initialize','params':{
                'protocolVersion':'2025-06-18','capabilities':{},
                'clientInfo':{'name':'update.sh','version':'1.7.0'}}})
        return 0 if isinstance(result,dict) and result.get('id') == 1 and 'result' in result and 'error' not in result else 1
    else: return 2
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('更新辅助步骤未能验证',file=sys.stderr)
        raise SystemExit(2)
