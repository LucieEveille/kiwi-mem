#!/usr/bin/env python3
"""ENC-01 four Python-only mutations; a green committed preflight is mandatory.

Only the Python guards judge mutations; no provider or real database is used.
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
    '01': (['main.py'], [('01', 'P-O/'), ('04', 'P-O')], 'revert OpenAI chunk decoding'),
    '02': (['anthropic_adapter.py'], [('02', 'A-direct/'), ('03', 'P-A/'),
           ('04', 'A-direct'), ('04', 'P-A')], 'revert Anthropic chunk decoding'),
    '03': (['main.py', 'anthropic_adapter.py'], [('07', 'P-O/A'), ('07', 'P-O/B'),
           ('07', 'A-direct/A'), ('07', 'A-direct/B')], 'module-shared incremental decoders'),
    '04': (['main.py', 'anthropic_adapter.py'], [('06', 'P-O/invalid-byte'),
           ('06', 'A-direct/invalid-byte'), ('06', 'P-A/invalid-byte')], 'strict instead of ignore'),
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


def mutate(number, source, filename):
    tree = ast.parse(source)
    fn = function(tree, 'stream_and_capture' if filename == 'main.py' else 'anthropic_stream_to_openai')
    if number in ('01', '02'):
        node = one(n for n in ast.walk(fn) if isinstance(n, ast.Call)
                   and ast.unparse(n) == 'decoder.decode(chunk)')
        return replace_expression(source, node, 'chunk.decode("utf-8", errors="ignore")')
    assignment = one(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                     and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                     and n.targets[0].id == 'decoder')
    # Check both semantic and exact textual anchors from instruction book 3.1.
    expected = 'decoder = codecs.getincrementaldecoder("utf-8")(errors="ignore")'
    if ast.get_source_segment(source, assignment) != expected:
        raise AnchorLost('per-stream ignore decoder assignment missing')
    if number == '04':
        return replace_expression(source, assignment, expected.replace('"ignore"', '"strict"'))
    if number == '03':
        changed = replace_expression(source, assignment, 'decoder = _enc_shared_decoder')
        imports = [n for n in tree.body if isinstance(n, ast.Import)
                   and any(a.name == 'codecs' and a.asname is None for a in n.names)]
        anchor = one(imports)
        lines = changed.splitlines(keepends=True)
        lines.insert(anchor.end_lineno,
                     '_enc_shared_decoder = codecs.getincrementaldecoder("utf-8")(errors="ignore")\n')
        return ''.join(lines)
    raise ValueError(number)


def identities(report, assertions=False):
    key = 'assertions' if assertions else 'arms'
    return [json.dumps([r['guard'], r['arm']] + ([r['assertion']] if assertions else []), ensure_ascii=False)
            for r in (report or {}).get(key, [])]


def complete(report, arms, assertions):
    if not report or report.get('groups_run') != 9 or report.get('errors'):
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
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', KIWI_ENC_01_REPORT=str(target))
    run = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/test_kiwi_enc_01.py')], cwd=ROOT,
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
    ledger = dict(ticket='ENC-01', head=git('rev-parse', 'HEAD'),
                  source_blobs={f: git('rev-parse', 'HEAD:' + f) for f in
                    ('main.py', 'security.py', 'anthropic_adapter.py', 'scripts/test_kiwi_out_01.py', 'scripts/test_kiwi_think_02.py', 'scripts/test_kiwi_enc_01.py', 'scripts/kiwi_enc_01_knives.py', '.github/workflows/ci.yml')},
                  preflight_returncode=rc, expected_arm_count=len(expected), expected_assertion_count=len(checks),
                  preflight_counts=pre.get('counts') if pre else None, results=[])
    if rc or not expected or not checks or not complete(pre, expected, checks) or pre['counts']['FAIL']:
        ledger['status'] = 'PREFLIGHT_NOT_GREEN_NO_MUTATIONS'
        output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('ENC preflight not green; no mutations applied')
        return 1
    for number, (filenames, targets, description) in CASES.items():
        originals = {f: (ROOT / f).read_bytes() for f in filenames}
        digests = {f: hashlib.sha256(raw).hexdigest() for f, raw in originals.items()}
        try:
            try:
                changed = {f: mutate(number, raw.decode('utf-8').replace('\r\n', '\n'), f)
                           for f, raw in originals.items()}
            except AnchorLost as exc:
                ledger['results'].append(dict(knife='K-ENC-' + number, mutation=description,
                    status='ANCHOR_LOST', returncode=None, behavioural=False,
                    environmental=[], reason=str(exc), restored_sha256=digests))
                print('K-ENC-' + number + ': ANCHOR_LOST', flush=True)
                continue
            for f, text in changed.items():
                compile(text, f, 'exec')
            for f, text in changed.items():
                (ROOT / f).write_text(text, encoding='utf-8', newline='\n')
            rc, report = run_tests(folder, 'K-ENC-' + number)
            failed = [r for r in (report or {}).get('assertions', []) if r['status'] == 'FAIL']
            hit = {g + '/' + arm: any(r['guard'].startswith('test_T_ENC_' + g + '_')
                    and r['arm'].startswith(arm) for r in failed) for g, arm in targets}
            environmental = [r for r in (report or {}).get('assertions', []) if r['status'] == 'ERROR']
            if not report or report.get('errors'):
                environmental.append({'reason': 'missing report or test-level error'})
            sets_equal = complete(report, expected, checks)
            behavioural = all(hit.values()) and bool(failed)
            caught = rc == 1 and behavioural and not environmental and sets_equal
            ledger['results'].append(dict(knife='K-ENC-' + number, mutation=description,
                status='RED' if caught else 'SURVIVED' if rc == 0 else 'CRASH', returncode=rc,
                behavioural=behavioural, environmental=environmental, targets=hit,
                identity_sets_equal=sets_equal, counts=report.get('counts') if report else None,
                assertion_counts=report.get('assertion_counts') if report else None,
                restored_sha256=digests))
            print('K-ENC-' + number + ': ' + ledger['results'][-1]['status'], flush=True)
        finally:
            for f, raw in originals.items():
                (ROOT / f).write_bytes(raw)
                if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != digests[f]:
                    raise RuntimeError('restoration hash mismatch: ' + f)
    rc, restored = run_tests(folder, 'restored')
    ledger['restored_returncode'] = rc
    ledger['restored_identity_sets_equal'] = complete(restored, expected, checks)
    ledger['arm_identities_sha256'] = hashlib.sha256('\n'.join(sorted(expected)).encode()).hexdigest()
    ledger['assertion_identities_sha256'] = hashlib.sha256('\n'.join(sorted(checks)).encode()).hexdigest()
    if dirty():
        raise RuntimeError('restored checkout is dirty')
    ok = (rc == 0 and ledger['restored_identity_sets_equal'] and
          all(r['status'] == 'RED' for r in ledger['results']) and len(ledger['results']) == 4)
    ledger['status'] = 'PASS' if ok else 'FAIL'
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if ok else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(execute(parser.parse_args().output))
