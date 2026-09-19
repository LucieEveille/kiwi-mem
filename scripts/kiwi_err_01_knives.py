#!/usr/bin/env python3
"""ERR-01 mutations; clean disposable checkout, external ledger, no production."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    '01': ('main.py', 'T02_D1_runtime', 'raw ordinary exception response'),
    '02': ('main.py', 'T02_D1_runtime', 'raw exception log'),
    '03': ('daily_digest.py', 'T03_digest_exception', 'raw internal error dictionary'),
    '04': ('security.py', 'T03_summary_error_key', 'summary allows raw error'),
    '05': ('security.py', 'T04_invalid_request', 'model result ignores error code'),
    '06': ('main.py', 'T05_2029', 'chat decoder maps client error as upstream failure'),
    '07': ('security.py', 'T06', 'status chosen before code normalization'),
    '08': ('main.py', 'T07_zip', 'fixed ZIP string restored'),
    '09': ('security.py', 'T08_http11_debug', 'HTTP/1.1 trace branch disabled'),
    '09e': ('security.py', 'T08_http11_debug', 'filter only on parent logger'),
    '10': ('scripts/test_kiwi_sec_01a.py', 'SEC', 'remove logging from safe()'),
    '11': ('scripts/test_kiwi_err_01.py', 'T01b_fstring', 'detector misses f-string'),
}


def once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError(f'anchor count {source.count(before)}; expected one')
    return source.replace(before, after, 1)


def in_function(source, name, before, after):
    fn = next(n for n in ast.parse(source).body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    lines = source.splitlines(keepends=True)
    section = ''.join(lines[fn.lineno - 1:fn.end_lineno])
    return ''.join(lines[:fn.lineno - 1]) + once(section, before, after) + ''.join(lines[fn.end_lineno:])


def mutate(key, source):
    if key == '01':
        return in_function(source, 'debug_memories', 'return stable_error(e)', 'return {"error": str(e)}')
    if key == '02':
        return once(source, 'safe_log("debug_memories_failed", e)', 'print(e)')
    if key == '03':
        return in_function(source, '_run_daily_digest_impl', '**stable_payload(exception_code(e))', '"error": str(e)')
    if key == '04':
        return once(source, '    return summary\n', '    if "error" in result: summary["error"] = result["error"]\n    return summary\n')
    if key == '05':
        return once(source, '        return stable_error(code)\n', '        return stable_error("upstream_error")\n')
    if key == '06':
        return in_function(source, 'chat_completions',
                           'except (json.JSONDecodeError, UnicodeDecodeError):\n        return stable_error("invalid_request")',
                           'except (json.JSONDecodeError, UnicodeDecodeError):\n        return stable_error("parse_failed")')
    if key == '07':
        return once(source, "    code = body['error_code']\n", '    # mutation: use unnormalized status code\n')
    if key == '08':
        return once(source, 'if not zipfile.is_zipfile(buf):\n            return stable_error("invalid_request")',
                    'if not zipfile.is_zipfile(buf):\n            return JSONResponse(status_code=400, content={"error": "不是有效的 zip 文件"})')
    if key == '09':
        return once(source, "record.name == 'httpcore.http11' and not record.args", 'False and not record.args')
    if key == '09e':
        return once(source, "('httpx', 'httpcore', 'httpcore.http11', 'httpcore.http2')", "('httpx', 'httpcore')")
    if key == '10':
        return once(source, '        text += self.log_capture.getvalue()\n', '        # mutation: logging omitted from safe()\n')
    if key == '11':
        return once(source, 'isinstance(n,ast.JoinedStr) and any', 'False and any')
    raise ValueError(key)


def git(*args):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), *args], cwd=ROOT, text=True).strip()


def run(selected=None):
    args = [sys.executable, '-B', str(ROOT / 'scripts/test_kiwi_err_01.py')]
    if selected == 'SEC':
        args = [sys.executable, '-B', str(ROOT / 'scripts/test_kiwi_sec_01a.py')]
    elif selected:
        args += ['--filter', selected]
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding='utf8', errors='replace',
                          env=dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1'), timeout=240)


def execute(output):
    output = Path(output).resolve()
    if output.is_relative_to(ROOT) or git('status', '--porcelain'):
        raise RuntimeError('clean committed disposable checkout and external output required')
    pre = run()
    if pre.returncode:
        raise RuntimeError('preflight failed: ' + pre.stderr[-3000:])
    rows = []
    for key, (filename, selected, description) in CASES.items():
        path = ROOT / filename
        original = path.read_bytes()
        original_hash = hashlib.sha256(original).hexdigest()
        try:
            path.write_text(mutate(key, original.decode('utf8').replace('\r\n', '\n')), encoding='utf8', newline='\n')
            result = run(selected)
            log = result.stdout + result.stderr
            reasons = re.findall(r'^AssertionError: (.*)$', log, re.M)
            crash = bool(re.search(r'^ERROR:|errors=[1-9]|Ran 0 tests', log, re.M))
            status = ('RED' if result.returncode and reasons and not crash else
                      'EQUIVALENT' if key == '10' and result.returncode == 0 and 'Ran 37 tests' in log else
                      'SURVIVED' if result.returncode == 0 else 'CRASH')
            rows.append(dict(knife='K-' + key, mutation=description, test=selected, status=status,
                             reason=reasons, exit_code=result.returncode, test_output=log,
                             original_sha256=original_hash))
            print('K-' + key, status, flush=True)
        finally:
            path.write_bytes(original)
            if hashlib.sha256(path.read_bytes()).hexdigest() != original_hash:
                raise RuntimeError('restore mismatch')
        rows[-1]['restored_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    post = run()
    if git('status', '--porcelain'):
        raise RuntimeError('restored tree is dirty')
    files = sorted({x[0] for x in CASES.values()} | {'scripts/kiwi_err_01_knives.py', '.github/workflows/ci.yml',
                    'docs/UPGRADING.md', 'docs/security-model.md', 'KNOWN_ISSUES.md', 'CHANGELOG.md'})
    ledger = dict(ticket='KIWI-ERR-01', head=git('rev-parse', 'HEAD'),
                  source_blobs={p: git('rev-parse', 'HEAD:' + p) for p in files},
                  preflight=pre.returncode, restored_suite=post.returncode,
                  kind='ASGI/functions with fake storage/providers; local HTTP/1.1 TCP', results=rows)
    output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    return 0 if not post.returncode and all(r['status'] == ('EQUIVALENT' if r['knife'] == 'K-10' else 'RED') for r in rows) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(execute(parser.parse_args().output))
