"""Public credential serializers and bounded diagnostics (no authentication).

Internal configuration readers deliberately keep original credentials. Apply
these serializers only at public response/export boundaries.
"""
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit

import httpx
from starlette.responses import JSONResponse


class InvalidRequest(ValueError):
    pass


class UpstreamFailure(Exception):
    def __init__(self, code='upstream_error'):
        self.code = code
        super().__init__(code)


def credential_state(value):
    value = value if isinstance(value, str) else ''
    return {'has_value': bool(value), 'last4': value[-4:] if len(value) >= 12 else ''}


def serialize_provider(row):
    state = credential_state(row.get('api_key'))
    result = {k: row.get(k) for k in ('id', 'name', 'api_base_url', 'api_format', 'enabled', 'created_at', 'updated_at')}
    for k in ('created_at', 'updated_at'):
        if result[k] is not None and hasattr(result[k], 'isoformat'):
            result[k] = result[k].isoformat()
    result.update(has_credential=state['has_value'], api_key_last4=state['last4'])
    # Deprecated field retained for clients that use its truthiness.
    result['api_key_preview'] = ('•••• •••• •••• ' + state['last4'] if state['last4'] else '已配置') if state['has_value'] else ''
    return result


def serialize_config(items, schema):
    result = {}
    for key, item in items.items():
        if key in schema and schema[key][3] == 'secret':
            result[key] = {k: item[k] for k in ('label', 'source')}
            result[key].update(value='', type='secret', **credential_state(item.get('value')))
        else:
            result[key] = dict(item)
    return result


def export_config(items, schema):
    flat, configured = {}, []
    for key, item in items.items():
        value = item.get('value', '') if isinstance(item, dict) else item
        if key in schema and schema[key][3] == 'secret':
            flat[key] = ''
            if value: configured.append(key)
        else: flat[key] = value
    return flat, {'format_version': 2, 'secrets_configured': sorted(configured)}


def validate_backup_meta(meta, schema):
    if (not isinstance(meta, dict) or set(meta) != {'format_version', 'secrets_configured'}
            or type(meta['format_version']) is not int or meta['format_version'] != 2
            or not isinstance(meta['secrets_configured'], list)):
        raise InvalidRequest()
    keys = meta['secrets_configured']
    if any(not isinstance(k, str) or k not in schema or schema[k][3] != 'secret' for k in keys):
        raise InvalidRequest()
    if len(keys) != len(set(keys)): raise InvalidRequest()
    return keys


def secret_action(data, field='value'):
    if not isinstance(data, dict): raise InvalidRequest()
    if 'clear' in data:
        if data['clear'] is not True or field in data: raise InvalidRequest()
        return 'clear', None
    if field not in data: return 'keep', None
    value = data[field]
    if not isinstance(value, str): raise InvalidRequest()
    if not value.strip(): return 'keep', None
    return 'set', value  # Preserve nonblank credential bytes.


def validate_upstream_url(url):
    """Reject ambiguous base URLs before attaching credentials; preserve path/port."""
    if (not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url)
            or any(c in url for c in ('\\', '?', '#'))):
        raise InvalidRequest()
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        host = parsed.hostname.lower()
        if ':' in host:
            ipaddress.IPv6Address(host)
            host = '[' + host + ']'
        elif not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9.])?', host, re.ASCII):
            raise ValueError()
        port = parsed.port
        if parsed.netloc.endswith(':') or port == 0: raise ValueError()
        authority = host + (f':{port}' if port is not None else '')
        return urlunsplit((parsed.scheme, authority, parsed.path, '', ''))
    except ValueError:
        raise InvalidRequest() from None


def upstream_origin(url):
    p = urlsplit(validate_upstream_url(url))
    return urlunsplit((p.scheme, p.netloc, '', '', ''))


def is_openrouter_url(url):
    return urlsplit(validate_upstream_url(url)).hostname == 'openrouter.ai'


def exception_code(exc):
    if isinstance(exc, InvalidRequest): return 'invalid_request'
    if isinstance(exc, UpstreamFailure): return exc.code
    if isinstance(exc, httpx.TimeoutException): return 'timeout'
    if isinstance(exc, httpx.HTTPStatusError): return f'http_{exc.response.status_code}'
    if isinstance(exc, httpx.RequestError): return 'network:RequestError'
    if isinstance(exc, json.JSONDecodeError): return 'parse_failed'
    return 'internal_error'


def stable_payload(code):
    if not re.fullmatch(r'(?:invalid_request|not_found|internal_error|upstream_error|parse_failed|timeout|no_route|http_[1-5][0-9]{2}|network:RequestError)', code):
        code = 'internal_error'
    return {'error': code, 'error_code': code}


def stable_error(error, status_code=None, headers=None):
    code = exception_code(error) if isinstance(error, Exception) else error
    body = stable_payload(code)
    if status_code is None:
        status_code = 400 if code == 'invalid_request' else 404 if code == 'not_found' else 500 if code == 'internal_error' else 502
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def safe_log(event, error):
    code = exception_code(error) if isinstance(error, Exception) else error
    # Event identifiers are code-owned; do not interpolate provider/user text.
    print(json.dumps({'event': event, 'code': stable_payload(code)['error_code']}, sort_keys=True, ensure_ascii=True))


def sse_error(error):
    code = exception_code(error) if isinstance(error, Exception) else error
    return 'data: ' + json.dumps(stable_payload(code)) + '\n\n'


def require_success_event(event):
    for line in event.splitlines():
        if not line.startswith('data:'): continue
        raw = line[5:].strip()
        if raw == '[DONE]': continue
        try: data = json.loads(raw)
        except (ValueError, TypeError): continue
        if isinstance(data, dict) and (data.get('error') or data.get('type') == 'error'):
            raise UpstreamFailure()


def public_model_result(result):
    """Legacy generators may return error dicts instead of raising."""
    if isinstance(result, dict) and (result.get('error') or result.get('status') == 'error'):
        return stable_error('upstream_error')
    return result


def public_dream_record(record):
    # Historical error narratives may contain exception text. Never modify DB.
    if isinstance(record, dict) and record.get('status') == 'error':
        record = dict(record)
        record['dream_narrative'] = 'upstream_error'
    return record


async def safe_sse(iterator):
    """Map post-start exceptions without treating diagnostics as assistant text."""
    try:
        async for chunk in iterator:
            yield chunk
    except Exception as exc:
        safe_log('upstream_stream_failed', exc)
        yield sse_error(exc).encode('utf-8')
        yield b'data: [DONE]\n\n'
