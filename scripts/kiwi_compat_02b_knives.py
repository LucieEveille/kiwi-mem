#!/usr/bin/env python3
"""COMPAT-02-B v1.4: eighteen AST mutations, explicit M and tagged A.

Locate every anchor even on the red Stage A tree (ANCHOR_LOST is evidence,
never RED). Mutations run only after a green preflight, in a git-archive
temporary checkout. The active checkout is never mutated. Requires the same
loopback disposable PostgreSQL configuration as the guards.
"""
import argparse
import ast
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASE = 'a1b01a4b50f27d27bd165a4b359b4497c97e303d'
PATHS = ('N', 'P', 'T')
TAG_DICTIONARY = {'hdr-id', 'task-ledger', 'task-identity', 'row6',
                  'single-user-ledger', 'tool-collect', 'search', 'private-frames'}


def ids(group, paths, checks):
    return [f'{group}/{path}/{check}' for path in paths for check in checks]


def spec(file, scope, locator, must, allowed=(), tags=(), tag_group=None):
    return dict(file=file, scope=scope, locator=locator, M=list(must),
                explicit_A=list(allowed), A_tags=list(tags), tag_group=tag_group)


# Assertion IDs are fixed here; no prefix matching expands mandatory sets.
CASES = {
    '01': spec('main.py', '_request_session_identity', 'hdr source JoinedStr',
        ids('T-01', ('cid','sid','owc'), ('source_segment','hdr_shape')) +
        ['T-01/cross/same_value_diff_header_diff_session'], tags=['hdr-id']),
    '02': spec('main.py', '_resolve_header_identity', 'three-header priority literal',
        ids('T-02', ['priority'], ['cid_over_sid_owc','sid_over_owc'])),
    '03a': spec('main.py', '_resolve_header_identity', 'length upper bound 200 Compare',
        ['T-03/201chars/bad_cid_falls_to_sid']),
    '03b': spec('main.py', '_resolve_header_identity', 'isprintable Call',
        ids('T-03', ['nul','newline'], ['bad_cid_falls_to_sid'])),
    '04': spec('database.py', '_resolve_scope_tx', 'identity_source == header Compare',
        ids('T-04',['header'],['header_zero_metadata_fetch','header_scope_global']),
        ['T-04/live/header_payload_live','T-04/unverified/header_payload_unverified'],
        ['hdr-id'], 'T-04'),
    '05': spec('main.py', 'chat_completions', 'record_events = not memory_bypass Assign',
        ids('T-06',PATHS,['ledger_zero_rows']) + ['T-06/N/non_stream_zero_process_memories'],
        tags=['task-ledger']),
    '06': spec('main.py', 'chat_completions', 'task_request If, first body statement assigns openai_tools=[]',
        ids('T-06',(*PATHS,'traditional'),['collectors_zero_calls']) + ['T-07/e/task_never_enters_tool_loop'],
        tags=['tool-collect','search','private-frames']),
    '07a': spec('main.py', 'chat_completions', 'nonstream task Dream IfExp',
        ['T-07/a/non_stream_zero_launch']),
    '07b': spec('main.py', '_stream_with_tools', 'tool task Dream IfExp',
        ['T-07/c/tools_direct_zero_fallback']),
    '07c': spec('main.py', 'stream_and_capture._spawn_dream_fallback_if_needed', 'fallback task Dream IfExp',
        ['T-07/d/stream_disconnect_zero_fallback'], ['T-07/b/stream_finish_zero_fallback']),
    '07d': spec('main.py', 'stream_and_capture', 'normal-finish task Dream IfExp, excluding nested functions',
        ['T-07/b/stream_finish_zero_ev_dream']),
    '08': spec('main.py', '_resolve_task_signal', 'nonempty predicate',
        ['T-08/empty/empty_is_normal','T-08/blank/blank_is_normal']),
    '09': spec('main.py', 'chat_completions', 'two print Calls: task_request and session_from_header, each unique',
        ids('T-12', ['cid','sid','owc','task'], ['logs_no_header_values'])),
    '10a': spec('main.py', 'chat_completions', 'session_header_identity_enabled config Await',
        ['T-11/row4/header_ignored'], tags=['row6']),
    '10b': spec('main.py', 'chat_completions', 'task_signal_enabled config Await',
        ['T-11/row5/records_normally','T-11/row5/hdr_identity'], tags=['row6']),
    '11': spec('main.py', 'chat_completions', 'record_events = not memory_bypass Assign',
        ['T-10/history/single_user_with_history_records'], tags=['single-user-ledger']),
    '12': spec('main.py', 'chat_completions', 'not task_request If around client system template replacement',
        ids('T-06',PATHS,['no_kiwi_system[client_template]'])),
    '13': spec('main.py', 'chat_completions', 'force-search BoolOp with not task_request',
        ids('T-06',PATHS,['web_search_true_zero_search']) + ids('T-06',['P','T'],['zero_ev_tool']),
        tags=['private-frames']),
}


class AnchorLost(RuntimeError):
    pass


def one(nodes):
    nodes = list(nodes)
    if len(nodes) != 1:
        raise AnchorLost(f'anchor count {len(nodes)}, expected one')
    return nodes[0]


def function(tree, name):
    owner = tree
    for part in name.split('.'):
        owner = one(n for n in owner.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == part)
    return owner


def lexical_nodes(fn):
    """Do not count a nested function's Dream expression in its parent scope."""
    def walk(node):
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda,ast.ClassDef)):
                continue
            yield from walk(child)
    for stmt in fn.body:
        if not isinstance(stmt,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            yield from walk(stmt)


def same(node, expression):
    expected=ast.parse(expression,mode='eval').body
    if isinstance(node,ast.Name) and isinstance(expected,ast.Name):
        return node.id==expected.id  # Assign targets have Store rather than Load.
    return ast.dump(node, include_attributes=False) == ast.dump(expected,include_attributes=False)


def has_const(node, value):
    return any(isinstance(n,ast.Constant) and n.value == value for n in ast.walk(node))


def replace(source, node, expression):
    lines = source.encode('utf-8').splitlines(keepends=True)
    start = sum(map(len,lines[:node.lineno-1])) + node.col_offset
    end = sum(map(len,lines[:node.end_lineno-1])) + node.end_col_offset
    raw = source.encode('utf-8')
    return (raw[:start]+expression.encode('utf-8')+raw[end:]).decode('utf-8')


def comparison_without(node, predicate):
    operands = [node.left,*node.comparators]
    parts = [(left,op,right) for left,op,right in zip(operands,node.ops,operands[1:])]
    removed = [p for p in parts if predicate(*p)]
    one(removed)
    kept = [ast.Compare(left=a,ops=[op],comparators=[b]) for a,op,b in parts if (a,op,b) not in removed]
    return ast.unparse(ast.BoolOp(op=ast.And(),values=kept)) if len(kept)>1 else ast.unparse(kept[0]) if kept else 'True'


def mutate(number, source):
    rule = CASES[number]
    fn = function(ast.parse(source),rule['scope'])
    nodes = list(lexical_nodes(fn))
    edits = []
    if number == '01':
        node = one(n for n in nodes if isinstance(n,ast.JoinedStr)
                   and any(isinstance(v,ast.Constant) and isinstance(v.value,str) and v.value.startswith('hdr-') for v in n.values)
                   and any(isinstance(v,ast.FormattedValue) and same(v.value,'src') for v in n.values))
        changed = copy.deepcopy(node)
        index = one(i for i,v in enumerate(changed.values) if isinstance(v,ast.FormattedValue) and same(v.value,'src'))
        if index+1 >= len(changed.values) or not isinstance(changed.values[index+1],ast.Constant) or not changed.values[index+1].value.startswith('-'):
            raise AnchorLost('src must be followed by literal hyphen')
        changed.values[index+1].value = changed.values[index+1].value[1:]
        changed.values.pop(index)
        edits.append((node,ast.unparse(changed)))
    elif number == '02':
        names = ['x-conversation-id','x-session-id','x-openwebui-chat-id']
        def ordered(n):
            if not isinstance(n,(ast.Tuple,ast.List)) or len(n.elts)!=3:
                return False
            found=[]
            for element in n.elts:
                found.extend(v.value.lower() for v in ast.walk(element) if isinstance(v,ast.Constant)
                             and isinstance(v.value,str) and v.value.lower() in names)
            return found == names
        node=one(n for n in nodes if ordered(n))
        changed=copy.deepcopy(node); changed.elts.reverse()
        edits.append((node,ast.unparse(changed)))
    elif number == '03a':
        node=one(n for n in nodes if isinstance(n,ast.Compare) and has_const(n,200)
                 and any(isinstance(v,ast.Call) and same(v.func,'len') for v in ast.walk(n)))
        def upper(a,op,b):
            return (isinstance(b,ast.Constant) and b.value==200 and isinstance(op,(ast.Lt,ast.LtE))
                    or isinstance(a,ast.Constant) and a.value==200 and isinstance(op,(ast.Gt,ast.GtE)))
        edits.append((node,comparison_without(node,upper)))
    elif number == '03b':
        node=one(n for n in nodes if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='isprintable')
        edits.append((node,'True'))
    elif number == '04':
        node=one(n for n in nodes if isinstance(n,ast.Compare) and same(n,'identity_source == "header"'))
        edits.append((node,'False'))
    elif number in ('05','11'):
        node=one(n for n in nodes if isinstance(n,ast.Assign) and len(n.targets)==1
                 and same(n.targets[0],'record_events') and same(n.value,'not memory_bypass'))
        value='not skip_prompt' if number=='05' else 'not memory_bypass and _count_real_user_messages(messages) > 1'
        edits.append((node.value,value))
    elif number == '06':
        def tools_first(n):
            if not isinstance(n,ast.If) or not same(n.test,'task_request') or not n.body:
                return False
            first=n.body[0]
            return isinstance(first,ast.Assign) and any(same(t,'openai_tools') for t in first.targets) and same(first.value,'[]')
        node=one(n for n in nodes if tools_first(n))
        edits.append((node.test,'False'))
    elif number in ('07a','07b','07c','07d'):
        node=one(n for n in nodes if isinstance(n,ast.IfExp) and same(n.test,'task_request') and same(n.body,'False')
                 and isinstance(n.orelse,ast.Call) and same(n.orelse.func,'detect_dream_trigger'))
        edits.append((node,ast.unparse(node.orelse)))
    elif number == '08':
        # Accept either an explicit lower bound, bool(value), or a bare value
        # inside an and-chain. Never delete the 64 limit or printable predicate.
        candidates=[]
        for n in nodes:
            if isinstance(n,ast.Compare) and any(isinstance(v,ast.Call) and same(v.func,'len') for v in ast.walk(n)):
                def lower(a,op,b):
                    return (isinstance(a,ast.Constant) and (a.value==1 and isinstance(op,ast.LtE) or a.value==0 and isinstance(op,ast.Lt))
                            or isinstance(b,ast.Constant) and (b.value==1 and isinstance(op,ast.GtE) or b.value==0 and isinstance(op,ast.Gt)))
                try:
                    replacement=comparison_without(n,lower)
                except AnchorLost:
                    continue
                candidates.append((n,replacement))
            elif isinstance(n,ast.Call) and same(n.func,'bool') and len(n.args)==1 and isinstance(n.args[0],ast.Name):
                candidates.append((n,'True'))
            elif isinstance(n,ast.BoolOp) and isinstance(n.op,ast.And):
                candidates.extend((v,'True') for v in n.values if isinstance(v,ast.Name))
        edits.append(one(candidates))
    elif number == '09':
        for event in ('task_request','session_from_header'):
            node=one(n for n in nodes if isinstance(n,ast.Call) and same(n.func,'print') and n.args
                     and any(isinstance(v,ast.Constant) and isinstance(v.value,str) and 'event='+event in v.value for v in ast.walk(n.args[0])))
            raw='request.headers.get("X-Kiwi-Task", "")' if event=='task_request' else (
                'next((request.headers.get(h, "") for h in ("X-Conversation-Id", "X-Session-ID", "X-OpenWebUI-Chat-Id") if request.headers.get(h)), "")')
            edits.append((node.args[0],f'({ast.unparse(node.args[0])}) + " value=" + {raw}'))
    elif number in ('10a','10b'):
        key='session_header_identity_enabled' if number=='10a' else 'task_signal_enabled'
        node=one(n for n in nodes if isinstance(n,ast.Await) and isinstance(n.value,ast.Call)
                 and same(n.value.func,'get_config_bool') and n.value.args and isinstance(n.value.args[0],ast.Constant)
                 and n.value.args[0].value==key)
        edits.append((node,'True'))
    elif number == '12':
        node=one(n for n in nodes if isinstance(n,ast.If) and same(n.test,'not task_request')
                 and any(isinstance(v,ast.Call) and same(v.func,'replace_template_variables') for stmt in n.body for v in ast.walk(stmt)))
        edits.append((node.test,'True'))
    elif number == '13':
        node=one(n for n in nodes if isinstance(n,ast.BoolOp) and isinstance(n.op,ast.And)
                 and any(same(v,'not task_request') for v in n.values)
                 and any(same(v,'do_search_force') for v in n.values))
        changed=copy.deepcopy(node); changed.values=[v for v in changed.values if not same(v,'not task_request')]
        edits.append((node,ast.unparse(changed)))
    else:
        raise ValueError(number)
    hits=[dict(line=n.lineno,column=n.col_offset,original=ast.unparse(n),replacement=v) for n,v in edits]
    for node,value in sorted(edits,key=lambda e:(e[0].lineno,e[0].col_offset),reverse=True):
        source=replace(source,node,value)
    ast.parse(source)
    return source,hits


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()


def dirty():
    return git('status','--porcelain','--untracked-files=all','--','.',':(exclude)scripts/sdk_probe/node_modules')


def run_guards(root, folder, label):
    target=folder/(label+'.json')
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',KIWI_C2B_REPORT=str(target))
    target.unlink(missing_ok=True)
    try:
        proc=subprocess.run([sys.executable,'-B',str(root/'scripts/test_kiwi_compat_02b.py')],
                            cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600)
        (folder/(label+'.log')).write_text(proc.stdout+proc.stderr,encoding='utf-8')
        return proc.returncode,json.loads(target.read_text(encoding='utf-8')) if target.exists() else None
    except subprocess.TimeoutExpired:
        (folder/(label+'.log')).write_text('guard timed out after 600s\n',encoding='utf-8')
        return 124,None


def identities(report, key):
    return {row['id'] for row in report.get(key,[])}


def complete(report, baseline=None):
    if not report or {r.get('group') for r in report.get('assertions',[])} != {f'T-{i:02d}' for i in range(13)}:
        return False
    for key,count_key in (('arms','counts'),('assertions','assertion_counts')):
        rows=report.get(key,[])
        if len(identities(report,key)) != len(rows) or not rows:
            return False
        counts={s:sum(r['status']==s for r in rows) for s in ('PASS','FAIL','ERROR')}
        if sum(counts.values())!=len(rows) or counts!=report.get(count_key) or counts['ERROR']:
            return False
        if baseline and identities(report,key)!=identities(baseline,key):
            return False
    for row in report['assertions']:
        tags=row.get('tags')
        if not isinstance(tags,list) or len(tags)!=len(set(tags)) or not set(tags)<=TAG_DICTIONARY:
            return False
        if row['status']=='FAIL' and row.get('failure_kind')!='AssertionError':
            return False
    if baseline:
        expected={r['id']:r['tags'] for r in baseline['assertions']}
        if any(r['tags']!=expected[r['id']] for r in report['assertions']):
            return False
    return report.get('disposable_database_removed') is True


def expand(rule, report):
    known=identities(report,'assertions')
    mandatory=set(rule['M']); allowed=set(rule['explicit_A'])
    if not mandatory or not (mandatory|allowed)<=known:
        raise ValueError('contract assertion IDs absent: '+repr(sorted((mandatory|allowed)-known)))
    for row in report['assertions']:
        if set(rule['A_tags']) & set(row['tags']) and (rule['tag_group'] is None or row['group']==rule['tag_group']):
            allowed.add(row['id'])
    return mandatory,allowed


def main(output):
    output=Path(output).resolve()
    if output.is_relative_to(ROOT):
        raise ValueError('evidence output must be outside checkout')
    output.parent.mkdir(parents=True,exist_ok=True)
    folder=output.parent/(output.stem+'-runs'); folder.mkdir(exist_ok=True)
    tracked=['main.py','database.py','config.py','anthropic_adapter.py','security.py',
             'scripts/test_kiwi_compat_02b.py','scripts/kiwi_compat_02b_knives.py','.github/workflows/ci.yml']
    ledger=dict(ticket='COMPAT-02-B',base=BASE,head=git('rev-parse','HEAD'),
                source_blobs={p:git('rev-parse','HEAD:'+p) for p in tracked},knives=[])
    if dirty():
        ledger['status']='DIRTY_CHECKOUT'
        output.write_text(json.dumps(ledger,indent=2)+'\n',encoding='utf-8')
        return 2
    archive=subprocess.check_output(['git','-c','core.autocrlf=false','archive','HEAD'],cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix='kiwi-c2b-knives-') as tmp:
        root=Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(archive)) as pack:
            pack.extractall(root,filter='data')
        rc,baseline=run_guards(root,folder,'preflight')
        valid=complete(baseline)
        green=rc==0 and valid and baseline['assertion_counts']['FAIL']==0
        ledger['preflight']=dict(returncode=rc,complete=valid,green=green,
                                 counts=(baseline or {}).get('counts'),assertion_counts=(baseline or {}).get('assertion_counts'))
        originals={p:(root/p).read_text(encoding='utf-8') for p in ('main.py','database.py')}
        for number,rule in CASES.items():
            entry=dict(id='K-'+number,**rule,returncode=None,behavioural=False,environmental=[],actual_FAIL=[])
            ledger['knives'].append(entry)
            try:
                if valid:
                    mandatory,allowed=expand(rule,baseline)
                    entry.update(M=sorted(mandatory),A=sorted(allowed))
                else:
                    entry['A']=[]
                changed,hits=mutate(number,originals[rule['file']])
                entry['anchors']=hits
            except AnchorLost as exc:
                entry.update(status='ANCHOR_LOST',reason=str(exc))
                continue
            except Exception as exc:
                entry.update(status='DEFINITION_ERROR',environmental=[type(exc).__name__],reason=str(exc))
                continue
            if not green:
                entry['status']='PREFLIGHT_NOT_GREEN_NO_MUTATIONS'
                continue
            target=root/rule['file']
            try:
                target.write_text(changed,encoding='utf-8',newline='\n')
                code,result=run_guards(root,folder,'K-'+number)
                equal_ids=complete(result,baseline)
                failures={r['id'] for r in (result or {}).get('assertions',[]) if r['status']=='FAIL'}
                errors=[r['id'] for r in (result or {}).get('assertions',[]) if r['status']=='ERROR']
                environmental=errors or ([] if equal_ids else ['incomplete_or_changed_identity_set'])
                red=code==1 and equal_ids and mandatory<=failures<=mandatory|allowed
                status='RED' if red else 'OVERREACH' if equal_ids and failures-(mandatory|allowed) else 'NOT_KILLED'
                entry.update(status=status,returncode=code,behavioural=red,environmental=environmental,
                             identity_sets_equal=equal_ids,actual_FAIL=sorted(failures),
                             missing_M=sorted(mandatory-failures),outside_M_A=sorted(failures-(mandatory|allowed)))
            finally:
                target.write_text(originals[rule['file']],encoding='utf-8',newline='\n')
        if green:
            code,restored=run_guards(root,folder,'restored')
            ledger['restored_returncode']=code
            ledger['restored_identity_sets_equal']=complete(restored,baseline)
        else:
            ledger['restored_returncode']=None
        ledger['temporary_sources_restored']=all((root/p).read_text(encoding='utf-8')==s for p,s in originals.items())
    passed=green and all(e['status']=='RED' for e in ledger['knives']) and ledger['restored_returncode']==0 and ledger['restored_identity_sets_equal']
    ledger['status']='PASS' if passed else 'STAGE_A_ANCHOR_LOST' if valid and rc==1 and all(e['status']=='ANCHOR_LOST' for e in ledger['knives']) else 'FAIL'
    ledger['counts']={s:sum(e['status']==s for e in ledger['knives']) for s in sorted({e['status'] for e in ledger['knives']})}
    ledger['checkout_clean_after']=not bool(dirty())
    if not ledger['checkout_clean_after']:
        ledger['status']='CHECKOUT_CHANGED'; passed=False
    output.write_text(json.dumps(ledger,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
    for e in ledger['knives']:
        print(e['id'],e['status'])
    print('SUMMARY '+json.dumps({'status':ledger['status'],'counts':ledger['counts']},sort_keys=True))
    return 0 if passed else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    raise SystemExit(main(args.output))
