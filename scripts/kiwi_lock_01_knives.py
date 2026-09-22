#!/usr/bin/env python3
"""LOCK-01: seven promotion/retirement mutations on disposable localhost PG16.

Run from a clean committed checkout, --output outside that checkout. The full
198-guard suite must pass before and after; each mutation runs the frozen 31
LOCK-01 arms in a fresh database. Only the named target's assertion failure, with
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
    1: ('database.py', '01', 'row-unchanged', 'promote removes user-lock predicate'),
    2: ('database.py', '04', 'row-unchanged', 'promote removes global-row predicate'),
    3: ('database.py', '01', 'return', 'promote always reports success'),
    4: ('dream.py', '05', 'user/success', 'Dream treats rejected promote as success'),
    5: ('dream.py', '05', 'log', 'Dream omits rejected-promote event'),
    6: ('daily_digest.py', '07', 'user-lock', 'retirement omits atomic lock recheck'),
    7: ('daily_digest.py', '07', 'actual-count', 'retirement reports SELECT candidates'),
}


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError(f'anchor count {source.count(before)}; expected one')
    return source.replace(before, after, 1)


def mutate(number, source):
    if number <= 3:
        fn = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'promote_memory')
        lines = source.splitlines(keepends=True)
        block = ''.join(lines[fn.lineno - 1:fn.end_lineno])
        before, after = {
            1: (" AND lock_source IS DISTINCT FROM 'user' ", " "),
            2: (' AND project_id IS NULL', ''),
            3: ('return row is not None', 'return True'),
        }[number]
        return ''.join(lines[:fn.lineno - 1]) + replace_once(block, before, after) + ''.join(lines[fn.end_lineno:])
    if number == 4:
        return replace_once(source, '                if promoted:', '                if True:')
    if number == 5:
        return replace_once(source, '                    print(f"event=dream_promote_skipped memory_id={mid} reason=user_locked_or_out_of_scope")', '                    pass')
    if number == 6:
        return replace_once(source, "                      AND is_permanent = TRUE\n                      AND lock_source IN ('auto', 'dream')\n", '')
    return replace_once(source, ' if row["id"] in retired_ids]', ']')


async def run_arms():
    import test_kiwi_safety_sync as suite
    admin_dsn = suite._validated_admin_dsn()
    name = ''
    try:
        name, dsn = await suite._create_disposable_database(admin_dsn)
        os.environ.update(DATABASE_URL=dsn, MEMORY_ENABLED='true', API_KEY='', MEMORY_API_KEY='',
                          API_BASE_URL='http://127.0.0.1:9/mock-chat',
                          MEMORY_API_BASE_URL='http://127.0.0.1:9/mock-memory')
        for attr, module in [('database', 'database'), ('config', 'config'),
                             ('memory_extractor', 'memory_extractor'), ('app_module', 'main')]:
            setattr(suite, attr, importlib.import_module(module))
        suite.require(suite.database.DATABASE_URL == dsn, 'wrong disposable database')
        await suite.database.init_tables()
        await suite.database.init_tables()
        return 0 if await suite.test_lock_01() else 1
    finally:
        if suite.database is not None:
            await suite.database.close_pool()
        if name:
            await suite._drop_disposable_database(admin_dsn, name)


def git(*args):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), *args],
                                   cwd=ROOT, text=True).strip()


def run_tests(folder, label, full=False):
    report = folder / (label + '-arms.json')
    if report.exists():
        report.unlink()
    command = [sys.executable, '-B', str(ROOT / 'scripts/test_kiwi_safety_sync.py')] if full else [
        sys.executable, '-B', str(Path(__file__).resolve()), '--arms']
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', KIWI_LOCK_01_REPORT=str(report))
    if env.get('KIWI_KNIFE_MUTE', '').strip():
        raise RuntimeError('LOCK-01 knives forbid assertion mutes')
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
    guard_tree = ast.parse((ROOT / 'scripts/test_kiwi_safety_sync.py').read_text(encoding='utf-8'))
    expected_total = 191 + (7 if any(isinstance(n, ast.AsyncFunctionDef) and n.name == 'test_lock_01'
                                    for n in guard_tree.body) else 0)
    preflight, pre_arms, pre_log = run_tests(folder, 'preflight', full=True)
    if preflight or not pre_arms or pre_arms['counts'] != {'PASS': 31, 'FAIL': 0, 'ERROR': 0} or f'PASS: {expected_total} total' not in pre_log:
        raise RuntimeError('full permanent-guard preflight not green; no mutations applied')
    results = []
    for number, (filename, guard, arm, description) in CASES.items():
        path = ROOT / filename
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        try:
            changed = mutate(number, original.decode('utf-8').replace('\r\n', '\n'))
            compile(changed, filename, 'exec')
            path.write_text(changed, encoding='utf-8', newline='\n')
            code, report, log = run_tests(folder, f'K-LOCK-{number}')
            target = [r for r in (report or {}).get('arms', []) if r['guard'] == 'T-LOCK-01-' + guard
                      and arm in r['arm'] and r['status'] == 'FAIL']
            complete = report and len(report['arms']) == 31 and report['counts']['ERROR'] == 0
            state = 'RED' if code == 1 and complete and target else 'SURVIVED' if code == 0 else 'CRASH'
            results.append(dict(knife=f'K-LOCK-{number}', mutation=description, status=state,
                                target_guard='T-LOCK-01-' + guard, target_arm=arm, failures=target,
                                counts=report['counts'] if report else None, exit_code=code,
                                log_sha256=hashlib.sha256(log.encode('utf-8')).hexdigest(),
                                restored_sha256=digest))
            print(f'K-LOCK-{number}: {state}', flush=True)
        finally:
            path.write_bytes(original)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError('restoration hash mismatch')
    restored, post_arms, post_log = run_tests(folder, 'restored', full=True)
    if git('status', '--porcelain'):
        raise RuntimeError('restored checkout is dirty')
    files = ['database.py', 'tool_drawer.py', 'mcp_server.py', 'main.py', 'daily_digest.py', 'security.py',
             'scripts/test_kiwi_safety_sync.py', 'dream.py', 'config.py',
             'scripts/kiwi_lock_01_knives.py']
    ledger = dict(ticket='LOCK-01', head=git('rev-parse', 'HEAD'),
                  source_blobs={p: git('rev-parse', 'HEAD:' + p) for p in files},
                  kind='disposable PostgreSQL 16; frozen Stage A guards; mocked embeddings/model/HTTP',
                  preflight=preflight, preflight_guards=expected_total, restored_suite=restored,
                  restored_guards=expected_total if f'PASS: {expected_total} total' in post_log else None,
                  preflight_arms=pre_arms['counts'], restored_arms=post_arms['counts'] if post_arms else None,
                  results=results)
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if not restored and ledger['restored_guards'] == expected_total and all(r['status'] == 'RED' for r in results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    parser.add_argument('--arms', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.arms:
        raise SystemExit(asyncio.run(run_arms()))
    if not args.output:
        parser.error('--output is required')
    raise SystemExit(execute(args.output))
