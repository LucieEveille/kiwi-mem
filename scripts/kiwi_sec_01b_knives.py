#!/usr/bin/env python3
"""SEC-01b exact-route mutations. Clean committed disposable checkout only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ROUTES = '''for _mcp_path, _mcp_endpoint, _mcp_name in (
    ("/memory/mcp", get_memory_mcp_endpoint(), "mcp-memory"),
    ("/calendar/mcp", get_calendar_mcp_endpoint(), "mcp-calendar"),
):
    app.add_route(
        _mcp_path,
        AsgiEndpoint(observe_mcp_access(guard_mcp_access(_mcp_endpoint, _SECURITY))),
        methods=None,
        name=_mcp_name,
        include_in_schema=False,
    )
'''
WRAPPER = 'AsgiEndpoint(observe_mcp_access(guard_mcp_access(_mcp_endpoint, _SECURITY)))'
CASES = {
    1: ('main.py', ['01', '02'], 'exact routes registered after calendar date business route'),
    2: ('main.py', ['01', '06', '07'], 'calendar prefix Mount restored'),
    3: ('main.py', ['08'], 'observation layer removed'),
    4: ('main.py', ['08'], 'access guard removed'),
    5: ('main.py', ['03', '09'], 'memory and calendar factories swapped'),
    6: ('main.py', ['02', '04'], 'only POST accepted by route'),
    7: ('main.py', ['03'], 'ASGI closure passed as Request handler without object wrapper'),
    8: ('main.py', ['03', '05'], 'calendar endpoint registered with trailing slash'),
    9: ('mcp_server.py', ['11'], 'memory factory manager warmup removed'),
    10: ('docs/mcp-transport-security.md', ['12'], 'mounting and paths documentation removed'),
}


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError(f'anchor count {source.count(before)}; expected one')
    return source.replace(before, after, 1)


def mutate(n, source):
    if n == 1:
        return replace_once(replace_once(source, ROUTES, ''), '@app.get("/calendar")', ROUTES + '\n@app.get("/calendar")')
    if n == 2:
        return replace_once(source, ROUTES, '''app.add_route("/memory/mcp", AsgiEndpoint(observe_mcp_access(guard_mcp_access(get_memory_mcp_endpoint(), _SECURITY))), methods=None)
app.mount("/calendar", observe_mcp_access(guard_mcp_access(__import__("mcp_server").get_calendar_mcp_app(), _SECURITY)))
''')
    if n in (3, 4, 7):
        after = {3: 'AsgiEndpoint(guard_mcp_access(_mcp_endpoint, _SECURITY))',
                 4: 'AsgiEndpoint(observe_mcp_access(_mcp_endpoint))',
                 7: 'observe_mcp_access(guard_mcp_access(_mcp_endpoint, _SECURITY))'}[n]
        return replace_once(source, WRAPPER, after)
    if n == 5:
        after = ROUTES.replace('get_memory_mcp_endpoint()', '_swap()').replace('get_calendar_mcp_endpoint()', 'get_memory_mcp_endpoint()').replace('_swap()', 'get_calendar_mcp_endpoint()')
        return replace_once(source, ROUTES, after)
    if n == 6:
        return replace_once(source, ROUTES, ROUTES.replace('methods=None', 'methods=["POST"]'))
    if n == 8:
        return replace_once(source, '("/calendar/mcp", get_calendar_mcp_endpoint()', '("/calendar/mcp/", get_calendar_mcp_endpoint()')
    if n == 9:
        before = '''def get_memory_mcp_endpoint():
    # Warm up the lazy manager before main's lifespan enters run().
    mcp_memory.streamable_http_app()
'''
        return replace_once(source, before, 'def get_memory_mcp_endpoint():\n')
    marker = '## 挂载与路径 / Mounting and paths'
    if source.count(marker) != 1:
        raise RuntimeError('documentation anchor is not unique')
    return source.split(marker)[0]


def run_tests(numbers=()):
    import ast
    tree = ast.parse((ROOT / 'scripts/test_kiwi_sec_01b.py').read_text(encoding='utf-8'))
    methods = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    args = [sys.executable, '-B', str(ROOT / 'scripts/test_kiwi_sec_01b.py')]
    args += ['MountGuards.' + next(m for m in methods if m.startswith('test_T_SEC_01b_' + number + '_')) for number in numbers]
    return subprocess.run(args, cwd=ROOT, env=dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1'),
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)


def git(*args):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), *args], cwd=ROOT, text=True).strip()


def execute(output):
    output = Path(output).resolve()
    if output.is_relative_to(ROOT):
        raise RuntimeError('ledger output must be outside checkout')
    if git('status', '--porcelain'):
        raise RuntimeError('clean committed checkout required')
    preflight = run_tests()
    if preflight.returncode:
        raise RuntimeError('preflight not green: ' + preflight.stderr[-3000:])
    results = []
    for number, (filename, tests, description) in CASES.items():
        path = ROOT / filename
        original = path.read_bytes()
        try:
            path.write_text(mutate(number, original.decode('utf-8').replace('\r\n', '\n')), encoding='utf-8', newline='\n')
            result = run_tests(tests)
            log = result.stdout + result.stderr
            reasons = re.findall(r'^AssertionError: (.*)$', log, re.M)
            crash = bool(re.search(r'^ERROR:|errors=[1-9]', log, re.M))
            state = 'RED' if result.returncode and reasons and not crash else 'SURVIVED' if not result.returncode else 'CRASH'
            results.append(dict(knife=f'K-SEC-01b-{number:02}', mutation=description, tests=tests,
                                status=state, reason=reasons, exit_code=result.returncode))
            print(f'K-SEC-01b-{number:02}: {state}', flush=True)
        finally:
            path.write_bytes(original)
            if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(original).digest():
                raise RuntimeError('restore mismatch')
    restored = run_tests()
    if git('status', '--porcelain'):
        raise RuntimeError('restored tree is not clean')
    files = ['main.py', 'mcp_server.py', 'mcp_access.py', 'scripts/test_kiwi_sec_01b.py',
             'scripts/kiwi_sec_01b_knives.py', 'docs/mcp-transport-security.md']
    ledger = dict(ticket='KIWI-SEC-01b', head=git('rev-parse', 'HEAD'),
                  source_blobs={p: git('rev-parse', 'HEAD:' + p) for p in files},
                  preflight=preflight.returncode, restored_suite=restored.returncode, results=results)
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if not restored.returncode and all(row['status'] == 'RED' for row in results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(execute(parser.parse_args().output))
