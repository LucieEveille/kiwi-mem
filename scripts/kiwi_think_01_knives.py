#!/usr/bin/env python3
"""THINK-01 reasoning-precedence mutations. Clean committed disposable checkout only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    1: ('main.py', ['03', '04', '06'], 'ignore panel configuration'),
    2: ('main.py', ['08'], 'None restores implicit enablement'),
    3: ('main.py', ['02'], 'non-off panel overrides explicit input'),
    4: ('main.py', ['06'], 'tool loop receives unresolved explicit input'),
    5: ('main.py', ['05'], 'invalid configuration bypasses enum validation'),
    6: ('main.py', ['07'], 'skip_prompt no longer suppresses reasoning'),
    7: ('admin-panel/js/config-schema.js', ['10'], 'panel description loses non-enablement boundary'),
    8: ('main.py', ['01', '03'], 'resolve only after forwarding reasoning dispatch'),
    9: ('main.py', ['09'], 'resolved log omits source key'),
    10: ('docs/UPGRADING.md', ['11'], 'remove THINK upgrade paragraph'),
}
RESOLVE = '    reasoning_effort, reasoning_source = await _resolve_reasoning_effort(reasoning_effort, source_hint=reasoning_source_hint)\n'
LOG = '    print(f"event=reasoning_effort_resolved source={reasoning_source} effort={reasoning_effort}")\n'


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError(f'anchor count {source.count(before)}; expected one')
    return source.replace(before, after, 1)


def mutate(n, source):
    if n == 1:
        a = source.index('    if explicit is not None:', source.index('async def _resolve_reasoning_effort'))
        b = source.index('\n\ndef _endpoint_host', a)
        return source[:a] + '    return explicit or "off", "explicit" if explicit is not None else "default"\n' + source[b:]
    if n == 2:
        return replace_once(source, 'if skip_prompt or reasoning_effort in (None, "off"):', 'if skip_prompt or reasoning_effort == "off":')
    if n == 3:
        before = '    if explicit is not None:\n        return explicit, source_hint or "explicit"\n    raw = await get_config("reasoning_effort")'
        after = '    raw = await get_config("reasoning_effort")\n    if explicit is not None and raw == "off":\n        return explicit, "explicit"'
        return replace_once(source, before, after)
    if n == 4:
        source = replace_once(source, RESOLVE, '    _unresolved_effort = reasoning_effort\n' + RESOLVE)
        return replace_once(source, '                reasoning_effort=reasoning_effort,', '                reasoning_effort=_unresolved_effort,')
    if n == 5:
        return replace_once(source, 'if candidate in REASONING_EFFORT_VALUES:', 'if True:')
    if n == 6:
        return replace_once(source, 'if skip_prompt or reasoning_effort in (None, "off"):', 'if reasoning_effort in (None, "off"):')
    if n == 7:
        return replace_once(source, '网关不主动开启思考（默认；模型自身默认推理的不受影响）', '不传')
    if n == 8:
        source = replace_once(source, RESOLVE + LOG, '')
        anchor = '    _apply_reasoning(body, is_openrouter, is_anthropic_fmt, reasoning_effort, skip_prompt, api_url=chat_api_url)\n'
        return replace_once(source, anchor, anchor + RESOLVE + LOG)
    if n == 9:
        return replace_once(source, LOG, LOG.replace('source={reasoning_source} ', ''))
    marker = '### 2.0 思考强度\n'
    start = source.index(marker)
    end = source.index('### English: 2.0 MCP access controls', start)
    return source[:start] + source[end:]


def run_tests(numbers=()):
    import ast
    tree = ast.parse((ROOT / 'scripts/test_kiwi_think_01.py').read_text(encoding='utf-8'))
    methods = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    args = [sys.executable, '-B', str(ROOT / 'scripts/test_kiwi_think_01.py')]
    args += ['ThinkGuards.' + next(m for m in methods if m.startswith('test_T_THINK_01_' + number + '_')) for number in numbers]
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
            results.append(dict(knife=f'K-THINK-{number:02}', mutation=description, tests=tests,
                                status=state, reason=reasons, exit_code=result.returncode))
            print(f'K-THINK-{number:02}: {state}', flush=True)
        finally:
            path.write_bytes(original)
            if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(original).digest():
                raise RuntimeError('restore mismatch')
    restored = run_tests()
    if git('status', '--porcelain'):
        raise RuntimeError('restored tree is not clean')
    files = ['main.py', 'config.py', 'admin-panel/js/config-schema.js',
             'scripts/test_kiwi_think_01.py', 'scripts/kiwi_think_01_knives.py',
             'docs/UPGRADING.md']
    ledger = dict(ticket='KIWI-THINK-01', head=git('rev-parse', 'HEAD'),
                  source_blobs={p: git('rev-parse', 'HEAD:' + p) for p in files},
                  preflight=preflight.returncode, restored_suite=restored.returncode, results=results)
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if not restored.returncode and all(row['status'] == 'RED' for row in results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(execute(parser.parse_args().output))
