#!/usr/bin/env python3
"""W2-05b: 13 scoped-memory mutations on disposable localhost PG16.

Run from a clean committed checkout, --output outside that checkout. The full
191-guard suite must pass before and after; each mutation runs the frozen 61
W2-05b arms in a fresh database. Only the named target's assertion failure, with
zero ERROR arms, counts as RED. Embeddings/HTTP use the Stage A test boundaries.
"""
import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ('    if tool_name in _SCOPED_MEMORY_TOOLS:\n'
            '        return await _execute_scoped_memory_tool(tool_name, arguments, scope), extra\n')
CASES = {
    1: ('tool_drawer.py', '03', 'live_project/save-and-total', 'save omits project ID'),
    2: ('database.py', '04', 'denied/', 'lock update omits visible predicate'),
    3: ('tool_drawer.py', '02', 'get_recent/members', 'live recent loses global foundation'),
    4: ('tool_drawer.py', '01', 'get_recent/members', 'global recent reads every project'),
    5: ('tool_drawer.py', '02', 'search_memory/members', 'live search omits project ID'),
    6: ('tool_drawer.py', '05', '/no-loop', 'remove private dispatch'),
    7: ('tool_drawer.py', '04', 'denied/', 'distinguish absent from invisible IDs'),
    8: ('tool_drawer.py', '07', 'error/', 'echo exception text'),
    9: ('tool_drawer.py', '05', '/quarantine', 'dispatch before quarantine'),
    10: ('database.py', '07', "_scope/('global', None)", 'accept both project_id and visible_scope'),
    11: ('database.py', '04', 'retire', 'user lock fails to replace auto lock source'),
    12: ('tool_drawer.py', '01', '/total', 'count all projects'),
    13: ('tool_drawer.py', '07', 'importance/', 'remove importance clamp'),
}


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError(f'anchor count {source.count(before)}; expected one')
    return source.replace(before, after, 1)


def mutate(number, source):
    if number == 1:
        return replace_once(source, 'None, "user_explicit", 0, project_id=pid)',
                            'None, "user_explicit", 0, project_id=None)')
    if number == 2:
        # Keep the live parameter consumed so this is a behavioral SQL mutation.
        return replace_once(source, 'f"WHERE id = ANY($2) AND {predicate} RETURNING id", *params)',
                            '"WHERE id = ANY($2) RETURNING id", *params[:2])')
    if number in (3, 4):
        condition = 'mode == "live_project"' if number == 3 else 'mode == "global"'
        return replace_once(source, 'results = await database.get_recent_memories(limit, visible_scope=visible)',
                            f'results = (await database.get_recent_memories(limit, project_id=pid) if {condition}\n'
                            '                           else await database.get_recent_memories(limit, visible_scope=visible))')
    if number == 5:
        return replace_once(source, 'database.search_memories(query, limit, track_recall=True, project_id=pid)',
                            'database.search_memories(query, limit, track_recall=True, project_id=None)')
    if number == 6:
        return replace_once(source, DISPATCH, '')
    if number == 7:
        return replace_once(source, '            if memory_id not in result["updated"]:\n                return rejected',
                            '            if memory_id not in result["updated"]:\n'
                            '                pool = await database.get_pool()\n'
                            '                async with pool.acquire() as conn:\n'
                            '                    exists = await conn.fetchval("SELECT 1 FROM memories WHERE id = $1", memory_id)\n'
                            '                return "其它项目" if exists else "不存在"')
    if number == 8:
        return replace_once(source, '        safe_log("drawer_memory_tool_failed", e)\n'
                            '        return f"[tool_error] {tool_name}: execution failed"',
                            '        safe_log("drawer_memory_tool_failed", e)\n        return str(e)')
    if number == 9:
        source = replace_once(source, DISPATCH, '')
        return replace_once(source, 'async def execute_drawer_tool(tool_name, arguments, scope=None):\n    extra = {}\n',
                            'async def execute_drawer_tool(tool_name, arguments, scope=None):\n    extra = {}\n' + DISPATCH)
    if number == 10:
        return replace_once(source, '    if project_id is not None:\n'
                            '        raise ValueError("visible_scope and project_id are mutually exclusive")\n', '')
    if number == 11:
        return replace_once(source, '            "UPDATE memories SET is_permanent = $1, "\n'
                            '            "lock_source = CASE WHEN $1 THEN \'user\' ELSE NULL END "\n',
                            '            "UPDATE memories SET is_permanent = $1 "\n')
    if number == 12:
        # Both read and save totals are the same narrow contract.
        before = 'database.get_memories_count(visible_scope=visible)'
        if source.count(before) != 2:
            raise RuntimeError('expected two visible-count calls')
        return source.replace(before, 'database.get_memories_count(None)')
    return replace_once(source, 'importance = max(1, min(arguments.get("importance", 5), 10))',
                        'importance = arguments.get("importance", 5)')


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
        return 0 if await suite.test_w2_05b() else 1
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
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', KIWI_W2_05B_REPORT=str(report))
    if env.get('KIWI_KNIFE_MUTE', '').strip():
        raise RuntimeError('W2-05b knives forbid assertion mutes')
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
    if preflight or not pre_arms or pre_arms['counts'] != {'PASS': 61, 'FAIL': 0, 'ERROR': 0} or 'PASS: 191 total' not in pre_log:
        raise RuntimeError('full 191-guard preflight not green; no mutations applied')
    results = []
    for number, (filename, guard, arm, description) in CASES.items():
        path = ROOT / filename
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        try:
            changed = mutate(number, original.decode('utf-8').replace('\r\n', '\n'))
            compile(changed, filename, 'exec')
            path.write_text(changed, encoding='utf-8', newline='\n')
            code, report, log = run_tests(folder, f'K-W5b-{number}')
            target = [r for r in (report or {}).get('arms', []) if r['guard'] == 'T-W2-05b-' + guard
                      and arm in r['arm'] and r['status'] == 'FAIL']
            complete = report and len(report['arms']) == 61 and report['counts']['ERROR'] == 0
            state = 'RED' if code == 1 and complete and target else 'SURVIVED' if code == 0 else 'CRASH'
            results.append(dict(knife=f'K-W5b-{number}', mutation=description, status=state,
                                target_guard='T-W2-05b-' + guard, target_arm=arm, failures=target,
                                counts=report['counts'] if report else None, exit_code=code,
                                log_sha256=hashlib.sha256(log.encode('utf-8')).hexdigest(),
                                restored_sha256=digest))
            print(f'K-W5b-{number}: {state}', flush=True)
        finally:
            path.write_bytes(original)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError('restoration hash mismatch')
    restored, post_arms, post_log = run_tests(folder, 'restored', full=True)
    if git('status', '--porcelain'):
        raise RuntimeError('restored checkout is dirty')
    files = ['database.py', 'tool_drawer.py', 'mcp_server.py', 'main.py', 'daily_digest.py', 'security.py',
             'scripts/test_kiwi_safety_sync.py', 'scripts/fixtures/kiwi_w2_05b_baseline.json',
             'scripts/kiwi_w2_05b_knives.py']
    ledger = dict(ticket='W2-05b', head=git('rev-parse', 'HEAD'),
                  source_blobs={p: git('rev-parse', 'HEAD:' + p) for p in files},
                  kind='disposable PostgreSQL 16; frozen Stage A guards; mocked embeddings/model/HTTP',
                  preflight=preflight, preflight_guards=191, restored_suite=restored,
                  restored_guards=191 if 'PASS: 191 total' in post_log else None,
                  preflight_arms=pre_arms['counts'], restored_arms=post_arms['counts'] if post_arms else None,
                  results=results)
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if not restored and ledger['restored_guards'] == 191 and all(r['status'] == 'RED' for r in results) else 1


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
