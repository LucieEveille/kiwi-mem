#!/usr/bin/env python3
"""COMPAT-02-A six Python-only mutations; a green committed preflight is mandatory.

SDK replay is a separate clean-tree consumer check, never part of knife counts.
Every knife must produce target AssertionErrors with complete dynamic identity
sets and no environmental errors. ANCHOR_LOST is recorded and does not abort the
remaining knives. Original files are restored byte-for-byte in finally.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    '01': ('main.py', ['00', '01', '02'], 'remove ordinary-forward memory choices'),
    '02': ('main.py', ['00', '01', '02'], 'tool memory choices null'),
    '03': ('main.py', ['00', '01', '02'], 'remove session and both handoff choices'),
    '04': ('security.py', ['03'], 'add choices to frozen error payload'),
    '05': ('main.py', ['05', '06'], 'rewrite upstream length finish to stop'),
    '06': ('main.py', ['01'], 'reverse per-round tool event key order'),
}


class AnchorLost(RuntimeError):
    """The precise intended mutation target no longer exists."""


def one(items):
    items = list(items)
    if len(items) != 1:
        raise AnchorLost(f'anchor count {len(items)}, expected one')
    return items[0]


def function(tree, name):
    return one(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def replace_expression(source, node, replacement):
    # AST column offsets are UTF-8 byte offsets, not Unicode character indexes.
    lines = source.encode('utf-8').splitlines(keepends=True)
    start = sum(map(len, lines[:node.lineno - 1])) + node.col_offset
    end = sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset
    raw = source.encode('utf-8')
    return (raw[:start] + replacement.encode('utf-8') + raw[end:]).decode('utf-8')


def event_dict(tree, fn, key, ordinal=0, count=1):
    nodes = sorted((n.args[0] for n in ast.walk(function(tree, fn))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name) and n.func.value.id == 'json'
        and n.func.attr == 'dumps' and n.args and isinstance(n.args[0], ast.Dict)
        and any(isinstance(k, ast.Constant) and k.value == key for k in n.args[0].keys)), key=lambda n: n.lineno)
    if len(nodes) != count:
        raise AnchorLost(f'{fn}/{key}: expected {count}, found {len(nodes)}')
    node = nodes[ordinal]
    if ([k.value if isinstance(k, ast.Constant) else None for k in node.keys] != [key, 'choices']
            or not isinstance(node.values[1], ast.List) or node.values[1].elts):
        raise AnchorLost(f'{fn}/{key}: ordered two-key empty-choices anchor missing')
    return node


def mutate(number, source):
    tree = ast.parse(source)
    if number in ('01', '02', '03', '06'):
        specs = {
            '01': [('stream_and_capture', 'ev_memory', 0, 1)],
            '02': [('_stream_with_tools', 'ev_memory', 0, 1)],
            '03': [('_ev_session_frame', 'ev_session', 0, 1),
                   ('_stream_with_tools', 'ev_handoff', 0, 1), ('stream_and_capture', 'ev_handoff', 0, 1)],
            '06': [('_stream_with_tools', 'ev_tool', 1, 2)],
        }[number]
        nodes = [event_dict(tree, *spec) for spec in specs]
        for node in sorted(nodes, key=lambda n: (n.lineno, n.col_offset), reverse=True):
            if number in ('01', '03'):
                node.keys.pop(); node.values.pop()
            elif number == '02':
                node.values[1] = ast.Constant(value=None)
            else:
                node.keys.reverse(); node.values.reverse()
            source = replace_expression(source, node, ast.unparse(node))
        return source
    if number == '04':
        node = one(n.value for n in ast.walk(function(tree, 'stable_payload'))
                   if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict))
        if [k.value for k in node.keys] != ['error', 'error_code']:
            raise AnchorLost('stable_payload frozen keys missing')
        node.keys.append(ast.Constant(value='choices')); node.values.append(ast.List(elts=[], ctx=ast.Load()))
        return replace_expression(source, node, ast.unparse(node))
    if number == '05':
        nodes = [n for n in ast.walk(function(tree, 'stream_and_capture')) if isinstance(n, ast.Yield)
                 and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                 and n.value.func.attr == 'encode' and isinstance(n.value.func.value, ast.BinOp)
                 and isinstance(n.value.func.value.left, ast.Name) and n.value.func.value.left.id == 'event']
        if len(nodes) != 2:
            raise AnchorLost(f'event-forward yield count {len(nodes)}, expected two')
        for node in sorted(nodes, key=lambda n: n.lineno, reverse=True):
            node.value.func.value.left = ast.Call(func=ast.Attribute(value=ast.Name(id='event', ctx=ast.Load()),
                attr='replace', ctx=ast.Load()), args=[ast.Constant(value='"finish_reason": "length"'),
                ast.Constant(value='"finish_reason": "stop"')], keywords=[])
            source = replace_expression(source, node, ast.unparse(node))
        return source
    raise ValueError(number)


def identities(report, assertions=False):
    key = 'assertions' if assertions else 'arms'
    return [json.dumps([r['guard'], r['arm']] + ([r['assertion']] if assertions else []), ensure_ascii=False)
            for r in (report or {}).get(key, [])]


def complete(report, arms, assertions):
    if not report or report.get('groups_run') != 8 or report.get('errors'):
        return False
    for key, expected, count_key in (('arms', arms, 'counts'), ('assertions', assertions, 'assertion_counts')):
        actual = identities(report, key == 'assertions')
        counts = {s: sum(r['status'] == s for r in report[key]) for s in ('PASS', 'FAIL', 'ERROR')}
        if len(actual) != len(expected) or len(actual) != len(set(actual)) or set(actual) != expected:
            return False
        if counts != report.get(count_key) or counts['ERROR']:
            return False
    return all(r.get('failure_kind') == 'AssertionError' for r in report['assertions'] if r['status'] == 'FAIL')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def dirty():
    # npm ci creates this disposable directory in CI before this Python step.
    # All tracked edits and every other untracked path still fail preflight.
    return git('status', '--porcelain', '--untracked-files=all', '--', '.',
               ':(exclude)scripts/sdk_probe/node_modules')


def run_tests(folder, label):
    target = folder / (label + '.json')
    target.unlink(missing_ok=True)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', KIWI_COMPAT_02A_REPORT=str(target),
               KIWI_COMPAT_02A_CAPTURE_DIR=str(folder / (label + '-streams')))
    run = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/test_kiwi_compat_02a.py')], cwd=ROOT,
                         env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    (folder / (label + '.log')).write_text(run.stdout + run.stderr, encoding='utf-8')
    return run.returncode, json.loads(target.read_text(encoding='utf-8')) if target.exists() else None


def execute(output):
    output = Path(output).resolve()
    if output.is_relative_to(ROOT) or dirty():
        raise RuntimeError('requires clean committed checkout and output outside checkout')
    folder = output.parent / (output.stem + '-runs')
    folder.mkdir(parents=True, exist_ok=True)
    rc, pre = run_tests(folder, 'preflight')
    expected, checks = set(identities(pre)), set(identities(pre, True))
    ledger = dict(ticket='COMPAT-02-A', head=git('rev-parse', 'HEAD'),
                  source_blobs={f: git('rev-parse', 'HEAD:' + f) for f in
                    ('main.py', 'security.py', 'anthropic_adapter.py', 'scripts/test_kiwi_out_01.py', 'scripts/test_kiwi_think_02.py', 'scripts/test_kiwi_compat_02a.py', 'scripts/kiwi_compat_02a_knives.py', '.github/workflows/ci.yml')},
                  preflight_returncode=rc, expected_arm_count=len(expected), expected_assertion_count=len(checks),
                  preflight_counts=pre.get('counts') if pre else None, results=[])
    if rc or not expected or not checks or not complete(pre, expected, checks) or pre['counts']['FAIL']:
        ledger['status'] = 'PREFLIGHT_NOT_GREEN_NO_MUTATIONS'
        output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('C2A preflight not green; no mutations applied')
        return 1
    for number, (filename, targets, description) in CASES.items():
        path = ROOT / filename
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        try:
            try:
                changed = mutate(number, original.decode('utf-8').replace('\r\n', '\n'))
            except AnchorLost as exc:
                ledger['results'].append(dict(knife='K-C2A-' + number, mutation=description,
                    status='ANCHOR_LOST', returncode=None, behavioural=False,
                    environmental=[], reason=str(exc), restored_sha256=digest))
                print('K-C2A-' + number + ': ANCHOR_LOST', flush=True)
                continue
            compile(changed, filename, 'exec')
            path.write_text(changed, encoding='utf-8', newline='\n')
            rc, report = run_tests(folder, 'K-C2A-' + number)
            failed = [r for r in (report or {}).get('assertions', []) if r['status'] == 'FAIL']
            hit = {g: any(r['guard'].startswith('test_T_C2A_' + g + '_') for r in failed) for g in targets}
            environmental = [r for r in (report or {}).get('assertions', []) if r['status'] == 'ERROR']
            if not report or report.get('errors'):
                environmental.append({'reason': 'missing report or test-level error'})
            sets_equal = complete(report, expected, checks)
            behavioural = all(hit.values()) and bool(failed)
            caught = rc == 1 and behavioural and not environmental and sets_equal
            ledger['results'].append(dict(knife='K-C2A-' + number, mutation=description,
                status='RED' if caught else 'SURVIVED' if rc == 0 else 'CRASH', returncode=rc,
                behavioural=behavioural, environmental=environmental, targets=hit,
                identity_sets_equal=sets_equal, counts=report.get('counts') if report else None,
                assertion_counts=report.get('assertion_counts') if report else None,
                restored_sha256=digest))
            print('K-C2A-' + number + ': ' + ledger['results'][-1]['status'], flush=True)
        finally:
            path.write_bytes(original)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError('restoration hash mismatch')
    rc, restored = run_tests(folder, 'restored')
    ledger['restored_returncode'] = rc
    ledger['restored_identity_sets_equal'] = complete(restored, expected, checks)
    ledger['arm_identities_sha256'] = hashlib.sha256('\n'.join(sorted(expected)).encode()).hexdigest()
    ledger['assertion_identities_sha256'] = hashlib.sha256('\n'.join(sorted(checks)).encode()).hexdigest()
    if dirty():
        raise RuntimeError('restored checkout is dirty')
    ok = (rc == 0 and ledger['restored_identity_sets_equal'] and
          all(r['status'] == 'RED' for r in ledger['results']) and len(ledger['results']) == 6)
    ledger['status'] = 'PASS' if ok else 'FAIL'
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if ok else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(execute(parser.parse_args().output))
