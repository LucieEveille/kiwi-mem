#!/usr/bin/env python3
"""OUT-01 ten mutations. Green preflight required; Stage A never mutates.

Run in a clean committed checkout with --output outside the checkout. Assertions
and arm identities/counts are derived from the green preflight, not hard-coded.
Only returncode 1 + target AssertionError + complete identity sets + no errors
counts as RED. Each changed file is restored byte-for-byte in finally.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    '01': ('main.py', ['03', '04', '05'], 'drop mct limit, retain tuple and stop'),
    '02': ('main.py', ['00', '02'], 'mct wins over max_tokens'),
    '03a': ('main.py', ['04'], 'omit tool-loop OpenAI stop'),
    '03b': ('anthropic_adapter.py', ['03', '05'], 'omit Anthropic stop_sequences'),
    '04': ('main.py', ['09'], 'raw exception expression in parameter return'),
    '05': ('main.py', ['04'], 'hard-code tool-loop output key max_tokens'),
    '06': ('main.py', ['08'], 'restore truthiness for skip_system_prompt'),
    '07': ('anthropic_adapter.py', ['03', '05', '06'], 'change default 8192 to 4096'),
    '08': ('main.py', ['07'], 'emit alias event before validation'),
    '09': ('main.py', ['00', '02'], 'retain null input keys'),
}


class AnchorLost(RuntimeError):
    """The source no longer has the exact mutation target."""


def one(items):
    items = list(items)
    if len(items) != 1:
        raise AnchorLost(f'anchor count {len(items)}, expected one')
    return items[0]


def function(tree, name):
    return one(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def rewrite(source, node, replacement):
    lines = source.splitlines(keepends=True)
    indent = ' ' * node.col_offset
    lines[node.lineno - 1:node.end_lineno] = [textwrap.indent(replacement, indent) + '\n']
    return ''.join(lines)


def assignment_key(node, key):
    return (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.targets[0].value, ast.Name) and node.targets[0].value.id == 'body'
            and isinstance(node.targets[0].slice, ast.Constant) and node.targets[0].slice.value == key)


def mutate(number, source):
    tree = ast.parse(source)
    if number == '01':
        fn = function(tree, '_parse_output_controls')
        # There are two `if mct_present` nodes: the nested dual-limit cleanup
        # and the alias-only elif. Select the latter by its direct assignment.
        branch = one(n for n in ast.walk(fn) if isinstance(n, ast.If)
                     and isinstance(n.test, ast.Name) and n.test.id == 'mct_present'
                     and any(isinstance(s, ast.Assign) and any(isinstance(t, ast.Name)
                             and t.id == 'out_limit' for t in s.targets) for s in n.body))
        last = branch.body[-1]
        return rewrite(source, last, ast.unparse(last) + '\nreturn None, stop_seqs')
    if number == '02':
        fn = function(tree, '_parse_output_controls')
        branch = one(n for n in ast.walk(fn) if isinstance(n, ast.If)
                     and isinstance(n.test, ast.Name) and n.test.id == 'mt_present')
        branch.body[:0] = ast.parse('''if mct_present:
    body.pop("max_tokens")
    return {"value": body["max_completion_tokens"], "source": "max_completion_tokens"}, stop_seqs
''').body
        return rewrite(source, branch, ast.unparse(branch))
    if number in ('03a', '03b'):
        fn = function(tree, '_stream_with_tools' if number == '03a' else 'to_anthropic_request')
        key = 'stop' if number == '03a' else 'stop_sequences'
        node = one(n for n in ast.walk(fn) if assignment_key(n, key))
        return rewrite(source, node, 'pass  # OUT-01 mutation: omitted stop')
    if number == '04':
        fn = function(tree, 'chat_completions')
        handler = one(n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)
                      and isinstance(n.type, ast.Name) and n.type.id == '_ParamError')
        node = one(n for n in ast.walk(handler) if isinstance(n, ast.Return)
                   and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                   and n.value.func.id == '_param_400')
        if len(node.value.args) != 2 or node.value.keywords:
            raise AnchorLost('_param_400 positional arguments missing')
        node.value.args[0] = ast.parse(f'str({handler.name})', mode='eval').body
        return rewrite(source, node, ast.unparse(node))
    if number == '05':
        fn = function(tree, '_stream_with_tools')
        node = one(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                           and t.value.id == 'body' and isinstance(t.slice, ast.Subscript)
                           and ast.unparse(t.slice) in ("out_limit['source']", 'out_limit["source"]')
                           for t in n.targets))
        node.targets[0].slice = ast.Constant(value='max_tokens')
        return rewrite(source, node, ast.unparse(node))  # retain the defined RHS
    if number == '06':
        fn = function(tree, 'chat_completions')
        node = one(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'skip_prompt' for t in n.targets))
        if not (isinstance(node.value, ast.Compare) and len(node.value.ops) == 1
                and isinstance(node.value.ops[0], ast.Is) and isinstance(node.value.comparators[0], ast.Constant)
                and node.value.comparators[0].value is True):
            raise AnchorLost('skip_prompt is True anchor missing')
        node.value = node.value.left
        return rewrite(source, node, ast.unparse(node))
    if number == '07':
        fn = function(tree, 'to_anthropic_request')
        node = one(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                   and isinstance(n.value, ast.Dict) and any(isinstance(k, ast.Constant)
                   and k.value == 'max_tokens' for k in n.value.keys))
        value = one(v for k, v in zip(node.value.keys, node.value.values)
                    if isinstance(k, ast.Constant) and k.value == 'max_tokens')
        constant = one(n for n in ast.walk(value) if isinstance(n, ast.Constant) and n.value == 8192)
        constant.value = 4096
        return rewrite(source, node, ast.unparse(node))
    if number == '08':
        fn = function(tree, '_parse_output_controls')
        statements = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                               and isinstance(n.value.value, str))]
        first = one(statements[:1])
        return rewrite(source, first, 'print("event=max_completion_tokens_aliased")\n' + ast.unparse(first))
    if number == '09':
        fn = function(tree, '_parse_output_controls')
        nodes = [n for n in fn.body if isinstance(n, ast.If)
                 and any(isinstance(c, ast.Compare) and any(isinstance(op, ast.Is) for op in c.ops)
                         and any(isinstance(v, ast.Constant) and v.value is None for v in c.comparators)
                         for c in ast.walk(n.test))
                 and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                         and c.func.attr == 'pop' for c in ast.walk(n))]
        if len(nodes) != 3:
            raise AnchorLost(f'null cleanup anchor count {len(nodes)}, expected three')
        for node in sorted(nodes, key=lambda n: n.lineno, reverse=True):
            source = rewrite(source, node, 'pass  # OUT-01 mutation: retain null key')
        return source
    raise ValueError(number)


def identities(report, assertions=False):
    key = 'assertions' if assertions else 'arms'
    return [json.dumps([r['guard'], r['arm']] + ([r['assertion']] if assertions else []), ensure_ascii=False)
            for r in (report or {}).get(key, [])]


def complete(report, arms, assertions):
    if not report or report.get('groups_run') != 10 or report.get('errors'):
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


def run_tests(folder, label):
    target = folder / (label + '.json')
    target.unlink(missing_ok=True)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', KIWI_OUT_01_REPORT=str(target))
    run = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/test_kiwi_out_01.py')], cwd=ROOT,
                         env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
    (folder / (label + '.log')).write_text(run.stdout + run.stderr, encoding='utf-8')
    return run.returncode, json.loads(target.read_text(encoding='utf-8')) if target.exists() else None


def execute(output):
    output = Path(output).resolve()
    if output.is_relative_to(ROOT) or git('status', '--porcelain'):
        raise RuntimeError('requires clean committed checkout and output outside checkout')
    folder = output.parent / (output.stem + '-runs')
    folder.mkdir(parents=True, exist_ok=True)
    rc, pre = run_tests(folder, 'preflight')
    expected, checks = set(identities(pre)), set(identities(pre, True))
    ledger = dict(ticket='OUT-01', head=git('rev-parse', 'HEAD'),
                  source_blobs={f: git('rev-parse', 'HEAD:' + f) for f in
                    ('main.py', 'anthropic_adapter.py', 'scripts/test_kiwi_out_01.py', 'scripts/kiwi_out_01_knives.py', '.github/workflows/ci.yml')},
                  preflight_returncode=rc, expected_arm_count=len(expected), expected_assertion_count=len(checks),
                  preflight_counts=pre.get('counts') if pre else None, results=[])
    if rc or not expected or not checks or not complete(pre, expected, checks) or pre['counts']['FAIL']:
        ledger['status'] = 'PREFLIGHT_NOT_GREEN_NO_MUTATIONS'
        output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('OUT-01 preflight not green; no mutations applied')
        return 1
    for number, (filename, targets, description) in CASES.items():
        path = ROOT / filename
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        try:
            try:
                changed = mutate(number, original.decode('utf-8').replace('\r\n', '\n'))
            except AnchorLost as exc:
                ledger['results'].append(dict(knife='K-OUT-01-' + number, mutation=description,
                    status='ANCHOR_LOST', returncode=None, behavioural=False,
                    environmental=[], reason=str(exc), restored_sha256=digest))
                print('K-OUT-01-' + number + ': ANCHOR_LOST', flush=True)
                continue
            compile(changed, filename, 'exec')
            path.write_text(changed, encoding='utf-8', newline='\n')
            rc, report = run_tests(folder, 'K-OUT-01-' + number)
            failed = [r for r in (report or {}).get('assertions', []) if r['status'] == 'FAIL']
            hit = {g: any(r['guard'].startswith('test_T_OUT_01_' + g + '_') for r in failed) for g in targets}
            environmental = [r for r in (report or {}).get('assertions', []) if r['status'] == 'ERROR']
            if not report or report.get('errors'):
                environmental.append({'reason': 'missing report or test-level error'})
            sets_equal = complete(report, expected, checks)
            behavioural = all(hit.values()) and bool(failed)
            caught = rc == 1 and behavioural and not environmental and sets_equal
            ledger['results'].append(dict(knife='K-OUT-01-' + number, mutation=description,
                status='RED' if caught else 'SURVIVED' if rc == 0 else 'CRASH', returncode=rc,
                behavioural=behavioural, environmental=environmental, targets=hit,
                identity_sets_equal=sets_equal, counts=report.get('counts') if report else None,
                assertion_counts=report.get('assertion_counts') if report else None,
                restored_sha256=digest))
            print('K-OUT-01-' + number + ': ' + ledger['results'][-1]['status'], flush=True)
        finally:
            path.write_bytes(original)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError('restoration hash mismatch')
    rc, restored = run_tests(folder, 'restored')
    ledger['restored_returncode'] = rc
    ledger['restored_identity_sets_equal'] = complete(restored, expected, checks)
    ledger['arm_identities_sha256'] = hashlib.sha256('\n'.join(sorted(expected)).encode()).hexdigest()
    ledger['assertion_identities_sha256'] = hashlib.sha256('\n'.join(sorted(checks)).encode()).hexdigest()
    if git('status', '--porcelain'):
        raise RuntimeError('restored checkout is dirty')
    ok = (rc == 0 and ledger['restored_identity_sets_equal'] and
          all(r['status'] == 'RED' for r in ledger['results']) and len(ledger['results']) == 10)
    ledger['status'] = 'PASS' if ok else 'FAIL'
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if ok else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(execute(parser.parse_args().output))
