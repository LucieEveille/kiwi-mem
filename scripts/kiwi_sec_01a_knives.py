"""Opt-in, no-network negative mutations; restore exact bytes after each run.

Run: python scripts/kiwi_sec_01a_knives.py --run --output <outside-repo.json>
The ledger distinguishes assertion failures from crashes or missing anchors.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CASES=[
 ('K-SEC-01','security.py',"result.update(has_credential=state['has_value'], api_key_last4=state['last4'])","result.update(api_key=row.get('api_key'), has_credential=state['has_value'], api_key_last4=state['last4'])",'test_provider_three_exits'),
 ('K-SEC-02','security.py',"'last4': value[-4:] if len(value) >= 12 else ''","'last4': value[-5:] if len(value) >= 12 else ''",'test_provider_three_exits'),
 ('K-SEC-03','security.py',"'last4': value[-4:] if len(value) >= 12 else ''","'last4': value[-4:] if len(value) >= 1 else ''",'test_provider_three_exits'),
 ('K-SEC-04','security.py',"result['api_key_preview'] = (","result['api_key_preview'] = (row.get('api_key') or '')[:6] + (",'test_provider_three_exits'),
 ('K-SEC-05','config.py','return "已设置" if value else "已清除"','return value[:4] + "…" + value[-3:] if value else "已清除"','test_config_read_write_and_log'),
 ('K-SEC-06','security.py',"flat[key] = ''","flat[key] = value",'test_export_omits_secret_and_metadata_is_separate'),
 ('K-SEC-07','security.py',"if field not in data: return 'keep', None","if field not in data: return 'set', ''",'test_secret_empty_preserves_and_invalid_rejected'),
 ('K-SEC-08','security.py',"if not isinstance(value, str): raise InvalidRequest()","if not isinstance(value, str): value = str(value)",'test_secret_empty_preserves_and_invalid_rejected'),
 ('K-SEC-09','main.py','origin = upstream_origin(base_url)','origin = "https://openrouter.ai"','test_credits_destination_and_both_paths'),
 ('K-SEC-10','security.py',"return urlsplit(validate_upstream_url(url)).hostname == 'openrouter.ai'","return 'openrouter' in validate_upstream_url(url)",'test_reasoning_dispatch_uses_real_hostname'),
 ('K-SEC-11','security.py',' or parsed.username is not None or parsed.password is not None','', 'test_invalid_urls_never_send_credentials'),
 ('K-SEC-12','security.py',"('\\\\', '?', '#')","('\\\\', '#')",'test_invalid_urls_never_send_credentials'),
 ('K-SEC-13','main.py','async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:\n        resp1', 'async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:\n        resp1','test_redirect_never_follows'),
 ('K-SEC-14','security.py',"body = stable_payload(code)","body = {'error': str(error), 'error_code': str(error)}",'test_provider_errors_are_stable'),
 ('K-SEC-15','security.py',"        record['dream_narrative'] = 'upstream_error'","        record['dream_narrative'] = record['dream_narrative']",'test_legacy_dream_errors_are_safe_on_read'),
 ('K-SEC-16','security.py',"        yield sse_error(exc).encode('utf-8')","        yield b'data: {\"choices\":[{\"delta\":{\"content\":\"failed\"}}]}\\n\\n'",'test_post_start_exception_and_embedded_error_frame'),
 ('K-SEC-17','security.py',"or meta['format_version'] != 2","or meta['format_version'] not in (2, 3)",'test_invalid_meta_rejected_before_any_write'),
 ('K-SEC-18','main.py','async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:\n        # 方式1','async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:\n        # 方式1','test_generic_redirect_never_follows'),
 ('K-SEC-19','main.py','return JSONResponse(status_code=502, content=stable_payload(f"http_{response.status_code}"),','return JSONResponse(status_code=response.status_code, content=response.json(),','test_nonstream_upstream_error_is_stable'),
 ('K-SEC-20','dream.py','error_msg = exception_code(e)','error_msg = f"模型调用出错: {e}"','test_dream_stores_stable_error'),
 ('K-SEC-21','main.py','entry["error_code"] = stable_payload(exception_code(exc))["error_code"]','raise exc','test_credits_failure_is_isolated_per_provider'),
 ('K-SEC-22','security.py',"(data.get('error') or data.get('type') == 'error')","('error' in data or data.get('type') == 'error')",'test_null_sse_error_is_not_failure'),
 # K-SEC-23..39 map in order to independent review KX-01..17.
 ('K-SEC-23','security.py',' or ord(c) < 32','','test_url_rejection_matrix_and_hostname_dispatch'),
 ('K-SEC-24','security.py',"('\\\\', '?', '#')","('?', '#')",'test_url_rejection_matrix_and_hostname_dispatch'),
 ('K-SEC-25','security.py',' or port == 0','','test_url_rejection_matrix_and_hostname_dispatch'),
 ('K-SEC-26','security.py',"parsed.netloc.endswith(':') or ",'','test_url_rejection_matrix_and_hostname_dispatch'),
 ('K-SEC-27','security.py',"return urlsplit(validate_upstream_url(url)).hostname == 'openrouter.ai'","return urlsplit(validate_upstream_url(url)).hostname.endswith('openrouter.ai')",'test_url_rejection_matrix_and_hostname_dispatch'),
 ('K-SEC-28','security.py','if len(keys) != len(set(keys)): raise InvalidRequest()','pass # mutation: duplicate metadata allowed','test_invalid_meta_rejected_before_any_write'),
 ('K-SEC-29','security.py',"set(meta) != {'format_version', 'secrets_configured'}","not {'format_version', 'secrets_configured'} <= set(meta)",'test_invalid_meta_rejected_before_any_write'),
 ('K-SEC-30','security.py',"data['clear'] is not True or field in data","field in data",'test_clear_contract_and_not_found_status'),
 ('K-SEC-31','security.py',"else 404 if code == 'not_found'","else 400 if code == 'not_found'",'test_clear_contract_and_not_found_status'),
 ('K-SEC-32','main.py','require_success_event(event)','pass # mutation: skip in-band error check','test_direct_stream_inband_error_preserves_prior_content',2),
 ('K-SEC-33','main.py',' or resp_data.get("error")','','test_buffered_chat_200_error_is_not_success'),
 ('K-SEC-34','main.py','if is_openrouter_url(base):',"if 'openrouter' in base:",'test_url_rejection_matrix_and_hostname_dispatch'),
 ('K-SEC-35','main.py','data["api_base_url"] = validate_upstream_url(data["api_base_url"])','data["api_base_url"] = data["api_base_url"]','test_provider_url_and_credential_inputs_reject_before_write'),
 ('K-SEC-36','main.py','api_base_url = validate_upstream_url(data.get("api_base_url", "").strip())','api_base_url = data.get("api_base_url", "").strip()','test_provider_url_and_credential_inputs_reject_before_write'),
 ('K-SEC-37','main.py','not isinstance(data, dict) or "clear" in data','not isinstance(data, dict)','test_clear_contract_and_not_found_status'),
 ('K-SEC-38','main.py','if resp2.status_code != 200:\n            raise UpstreamFailure(f"http_{resp2.status_code}")','if resp2.status_code != 200:\n            pass','test_second_credit_path_failure_is_not_success'),
 ('K-SEC-39','main.py','if resp2.status_code not in (200, 404):\n                raise UpstreamFailure(f"http_{resp2.status_code}")','if resp2.status_code not in (200, 404):\n                pass','test_second_credit_path_failure_is_not_success'),
 ('K-SEC-40','anthropic_adapter.py','raise UpstreamFailure("parse_failed")','pass # mutation: swallow non-SSE body','test_adapted_stream_rejects_non_sse_event'),
 ('K-SEC-41','main.py',' or resp_data.get("type") == "error"','','test_buffered_chat_200_error_is_not_success'),
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    base=subprocess.check_output(['git','-c',f'safe.directory={ROOT.as_posix()}','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    source_files=sorted({case[1] for case in CASES} | {'scripts/test_kiwi_sec_01a.py', 'scripts/kiwi_sec_01a_knives.py'})
    source_blobs={file:subprocess.check_output(['git','-c',f'safe.directory={ROOT.as_posix()}','rev-parse',f'{base}:{file}'],cwd=ROOT,text=True).strip() for file in source_files}
    command=[sys.executable,'-X','utf8',str(ROOT/'scripts/test_kiwi_sec_01a.py')]
    pre=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    if pre.returncode: raise SystemExit('Preflight not green; no mutations applied')
    results=[]
    for case in CASES:
        knife,file,before,after,test = case[:5]
        expected_count = case[5] if len(case) == 6 else 1
        path=ROOT/file; original=path.read_bytes(); source=original.decode('utf-8')
        if '\r\n' in source:
            before = before.replace('\n', '\r\n')
            after = after.replace('\n', '\r\n')
        if source.count(before)!=expected_count: raise SystemExit(f'{knife}: anchor count {source.count(before)}, expected {expected_count}; no mutation applied')
        try:
            path.write_bytes(source.replace(before,after).encode('utf-8'))
            r=subprocess.run(command+['SecurityTests.'+test],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=45)
            output=r.stdout+r.stderr
            caught=r.returncode!=0 and f'FAIL: {test}' in output and 'AssertionError' in output and 'ERROR:' not in output
            reason=next((line for line in output.splitlines() if line.startswith('AssertionError:')),'')
            results.append({'knife':knife,'test':test,'result':'RED' if caught else 'SURVIVED' if r.returncode==0 else 'CRASH','reason':reason})
            print(knife,results[-1]['result'],flush=True)
        finally:
            path.write_bytes(original)
            if hashlib.sha256(path.read_bytes()).digest()!=hashlib.sha256(original).digest():
                raise SystemExit(f'{knife}: restore hash mismatch')
    post=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    ledger={'ticket':'KIWI-SEC-01a','head':base,'source_blobs':source_blobs,'kind':'ASGI/functions; fake DB and HTTP; no external calls','preflight':pre.returncode,'restored_suite':post.returncode,'results':results}
    args.output.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if post.returncode==0 and all(r['result']=='RED' for r in results) else 1


if __name__=='__main__': raise SystemExit(main())
