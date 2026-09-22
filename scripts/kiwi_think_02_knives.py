#!/usr/bin/env python3
"""THINK-02: eight reasoning input mutations; mocked storage and upstream.

Run from a clean committed checkout, --output outside that checkout. The full
259-arm suite must pass before and after; each mutation runs all ten groups. Only the named target's assertion failure, with
zero ERROR arms, counts as RED. Embeddings/HTTP use the Stage A test boundaries.
"""
import argparse
import ast
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    0: ('main.py', '00', '', 'remove input aliases'),
    1: ('main.py', '01', '', 'skip reasoning object input'),
    2: ('main.py', '03', '', 'enabled false becomes auto'),
    3: ('main.py', '04', '', 'budget equality drops one level'),
    4: ('main.py', '06', '', 'object overrides explicit string'),
    5: ('main.py', '07', '', 'non-object silently becomes auto'),
    6: ('main.py', '04', '04b-budget-table', 'input budget floor drifts from adapter'),
    7: ('main.py', '08', '', 'echo raw reasoning object'),
}


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError(f'anchor count {source.count(before)}; expected one')
    return source.replace(before, after, 1)


OBJECT_IF = 'if reasoning_effort is None and "reasoning" in body:'


def mutate(number, source):
    if number == 0:
        return replace_once(source, '_REASONING_EFFORT_ALIASES = {"none": "off", "minimal": "low"}', '_REASONING_EFFORT_ALIASES = {}')
    if number == 1:
        return replace_once(source, OBJECT_IF, 'if False:')
    if number == 2:
        return replace_once(source, 'if obj.get("enabled") is False:\n        return "off"', 'if obj.get("enabled") is False:\n        return "auto"')
    if number == 3:
        return replace_once(source, 'if max_tokens >= floor:', 'if max_tokens > floor:')
    if number == 4:
        return replace_once(source, OBJECT_IF, 'if "reasoning" in body:')
    if number == 5:
        before = '        raise ValueError("reasoning 必须是对象，可含 effort（" + "/".join(REASONING_EFFORT_VALUES)\n                         + "）、max_tokens（正整数）或 enabled（布尔）")'
        return replace_once(source, before, '        obj = {}')
    if number == 6:
        return replace_once(source, '(5000, "low")', '(4000, "low")')
    return replace_once(source, 'def _parse_reasoning_object(obj):\n', 'def _parse_reasoning_object(obj):\n    print(obj)\n')


def git(*args):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), *args],
                                   cwd=ROOT, text=True).strip()


def run_tests(folder, label, full=False):
    report = folder / (label + '-arms.json')
    if report.exists():
        report.unlink()
    command = [sys.executable, '-B', str(ROOT / 'scripts/test_kiwi_think_02.py')]
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', KIWI_THINK_02_REPORT=str(report))
    if env.get('KIWI_KNIFE_MUTE', '').strip():
        raise RuntimeError('THINK-02 knives forbid assertion mutes')
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=600)
    log = result.stdout + result.stderr
    (folder / (label + '.log')).write_text(log, encoding='utf-8')
    arms = json.loads(report.read_text(encoding='utf-8')) if report.exists() else None
    return result.returncode, arms, log


def execute(output):
    output = Path(output).resolve()
    if output.is_relative_to(ROOT) or git('status', '--porcelain'):
        raise RuntimeError('requires clean committed checkout and output outside checkout')
    folder = output.parent / (output.stem + '-runs')
    folder.mkdir(parents=True, exist_ok=True)
    preflight, pre_arms, pre_log = run_tests(folder, 'preflight', full=True)
    if preflight or not pre_arms or pre_arms['counts'] != {'PASS': 259, 'FAIL': 0, 'ERROR': 0}:
        raise RuntimeError('259-arm preflight not green; no mutations applied')
    results = []
    for number, (filename, guard, arm, description) in CASES.items():
        path = ROOT / filename
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        try:
            changed = mutate(number, original.decode('utf-8').replace('\r\n', '\n'))
            compile(changed, filename, 'exec')
            path.write_text(changed, encoding='utf-8', newline='\n')
            code, report, log = run_tests(folder, f'K-THINK2-{number}')
            target = [r for r in (report or {}).get('arms', []) if r['guard'].startswith('test_T_THINK_02_' + guard + '_')
                      and arm in json.dumps(r['arm']) and r['status'] == 'FAIL']
            complete = report and len(report['arms']) == 259 and report['counts']['ERROR'] == 0 and report['errors'] == 0
            state = 'RED' if code == 1 and complete and target else 'SURVIVED' if code == 0 else 'CRASH'
            results.append(dict(knife=f'K-THINK2-{number}', mutation=description, status=state,
                                target_guard='T-THINK-02-' + guard, target_arm=arm, failures=target,
                                counts=report['counts'] if report else None, exit_code=code,
                                log_sha256=hashlib.sha256(log.encode('utf-8')).hexdigest(),
                                restored_sha256=digest))
            print(f'K-THINK2-{number}: {state}', flush=True)
        finally:
            path.write_bytes(original)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError('restoration hash mismatch')
    restored, post_arms, post_log = run_tests(folder, 'restored', full=True)
    if git('status', '--porcelain'):
        raise RuntimeError('restored checkout is dirty')
    files = ['main.py', 'config.py', 'anthropic_adapter.py', 'scripts/test_kiwi_think_01.py',
             'scripts/test_kiwi_err_01.py', 'scripts/test_kiwi_think_02.py', 'scripts/kiwi_think_02_knives.py']
    ledger = dict(ticket='THINK-02', head=git('rev-parse', 'HEAD'),
                  source_blobs={p: git('rev-parse', 'HEAD:' + p) for p in files},
                  kind='real ASGI and adapter functions; fake storage/model/HTTP; no production I/O',
                  preflight=preflight, preflight_guards=10, restored_suite=restored,
                  restored_guards=post_arms.get('groups_run') if post_arms else None,
                  preflight_arms=pre_arms['counts'], restored_arms=post_arms['counts'] if post_arms else None,
                  results=results)
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if not restored and ledger['restored_guards'] == 10 and ledger['restored_arms'] == {'PASS': 259, 'FAIL': 0, 'ERROR': 0} and all(r['status'] == 'RED' for r in results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    args = parser.parse_args()
    if not args.output:
        parser.error('--output is required')
    raise SystemExit(execute(args.output))
