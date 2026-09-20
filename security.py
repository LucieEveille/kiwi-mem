"""Public credential serializers and bounded diagnostics (no authentication).

Internal configuration readers deliberately keep original credentials. Apply
these serializers only at public response/export boundaries.
"""
import ipaddress
import json
import logging
import re
from urllib.parse import urlsplit, urlunsplit

import httpx
from starlette.responses import JSONResponse


class _HTTPReasonFilter(logging.Filter):
    """Bound the upstream-controlled reason in the HTTP client's summary only."""
    _kiwi_http_reason_filter = True

    def filter(self, record):
        if (record.msg == 'HTTP Request: %s %s "%s %d %s"'
                and isinstance(record.args, tuple) and len(record.args) == 5):
            record.args = (*record.args[:4], '<reason-redacted>')
        if (record.name == 'httpcore.http11' and not record.args
                and isinstance(record.msg, str)
                and record.msg.startswith('receive_response_headers.complete return_value=')):
            record.msg = re.sub(
                r"^(receive_response_headers\.complete return_value=\(b['\"]HTTP/1\.[01]['\"], \d+, )b(?:'[^'\\]*(?:\\.[^'\\]*)*'|\"[^\"\\]*(?:\\.[^\"\\]*)*\")(?=, )",
                lambda match: match[1] + "b'<reason-redacted>'", record.msg, count=1,
            )
        return True


def _install_http_reason_filters():
    for name in ('httpx', 'httpcore', 'httpcore.http11', 'httpcore.http2'):
        logger = logging.getLogger(name)
        if not any(getattr(f, '_kiwi_http_reason_filter', False) for f in logger.filters):
            logger.addFilter(_HTTPReasonFilter())


_install_http_reason_filters()


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
    if (not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 or c == '\x7f' for c in url)
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
    if not re.fullmatch(r'(?:invalid_request|not_found|internal_error|upstream_error|parse_failed|timeout|no_route|deprecated|no_embedding_route|invalid_response|http_[1-5][0-9]{2}|network:RequestError)', code):
        code = 'internal_error'
    return {'error': code, 'error_code': code}


def stable_error(error, status_code=None, headers=None):
    code = exception_code(error) if isinstance(error, Exception) else error
    body = stable_payload(code)
    code = body['error_code']
    if status_code is None:
        status_code = 410 if code == 'deprecated' else 409 if code == 'no_embedding_route' else 400 if code == 'invalid_request' else 404 if code == 'not_found' else 500 if code == 'internal_error' else 502
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def safe_log(event, error):
    code = exception_code(error) if isinstance(error, Exception) else error
    # Event identifiers are code-owned; do not interpolate provider/user text.
    print(json.dumps({'event': event, 'code': stable_payload(code)['error_code']}, sort_keys=True, ensure_ascii=True))


def sse_error(error):
    code = exception_code(error) if isinstance(error, Exception) else error
    return 'data: ' + json.dumps(stable_payload(code)) + '\n\n'


def require_sse_event(event):
    """Reject non-SSE upstream bodies before forwarding either events or tails."""
    if not event.splitlines()[0].startswith(('data:', 'event:', 'id:', 'retry:', ':')):
        raise UpstreamFailure('parse_failed')


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
        code = result.get('error_code')
        if not isinstance(code, str) or not re.fullmatch(
                r'(?:invalid_request|internal_error|upstream_error|parse_failed|timeout|http_[1-5][0-9]{2}|network:RequestError)', code):
            code = 'upstream_error'
        return stable_error(code)
    return result


def public_model_summary(result):
    """Bound background-result logs by both field name and value shape."""
    if not isinstance(result, dict):
        return {}
    summary = {}
    for key, value in result.items():
        if key == 'status' and isinstance(value, str) and value in ('ok', 'error', 'skipped'):
            summary[key] = value
        elif key == 'date' and isinstance(value, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            summary[key] = value
        elif key in ('fragments', 'digests', 'backfilled', 'skipped', 'retired', 'softened') and type(value) is int:
            summary[key] = value
        elif key == 'error_code':
            summary[key] = stable_payload(value if isinstance(value, str) else 'internal_error')['error_code']
    return summary


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
