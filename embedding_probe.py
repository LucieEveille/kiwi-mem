"""Opt-in, non-persistent embedding diagnostics with a bounded public receipt."""
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import httpx
import database as db
from security import exception_code, validate_upstream_url


def redact_for_diagnostic(value, secrets):
    if not isinstance(value, str):
        return None
    if any(secret and secret in value for secret in secrets):
        return None
    if re.search(r'Bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|://[^/\s]+@|[\x00-\x08\x0b\x0c\x0e-\x1f]', value, re.I):
        return None
    return re.sub(r'\s+', ' ', value).strip()


def describe_embedding_probe(route, *, response=None, error_code=None, elapsed_ms=0, tested_at=None):
    """Only these fixed fields can cross the admin boundary; never a raw body."""
    data = None
    status = response.status_code if response is not None else None
    if response is not None:
        try:
            data = response.json()
        except (ValueError, UnicodeError):
            pass
        if status != 200:
            error_code = f'http_{status}'
    vector = None
    if status == 200 and isinstance(data, dict):
        entries = data.get('data')
        if isinstance(entries, list) and entries and isinstance(entries[0], dict):
            vector = entries[0].get('embedding')
    ok = status == 200 and db.is_usable_vector(vector)
    if status == 200 and not ok:
        error_code = 'invalid_response'
    message = None
    if isinstance(data, dict):
        error = data.get('error')
        if isinstance(error, dict) and isinstance(error.get('message'), str):
            message = error['message']
        elif isinstance(data.get('message'), str):
            message = data['message']
    request_id = None
    if response is not None:
        request_id = response.headers.get('x-request-id') or response.headers.get('request-id')
    parsed = urlsplit(route.url)
    host = parsed.hostname
    if ':' in host:
        host = f'[{host}]'
    if parsed.port is not None:
        host += f':{parsed.port}'
    controlled = dict(provider_name=route.provider_name, model_id=route.model_id,
                      endpoint_host=host, upstream_message=message, upstream_request_id=request_id)
    secrets = [route.api_key, quote(route.api_key, safe='')]
    hidden = False
    for name, value in controlled.items():
        clean = redact_for_diagnostic(value, secrets)
        if isinstance(value, str) and clean is None:
            hidden = True
        controlled[name] = clean
    if controlled['upstream_request_id'] is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', controlled['upstream_request_id']):
        controlled['upstream_request_id'] = None
    truncated = controlled['upstream_message'] is not None and len(controlled['upstream_message']) > 2000
    for name, limit in (('provider_name',64),('model_id',128),('upstream_message',2000)):
        if controlled[name] is not None:
            controlled[name] = controlled[name][:limit]
    return dict(ok=ok, error_code=None if ok else error_code or 'invalid_response',
                source=route.source, provider_id=route.provider_id, http_status=status,
                profile=route.profile, dim=len(vector) if ok else None,
                elapsed_ms=max(0,int(elapsed_ms)), tested_at=tested_at or datetime.now(timezone.utc).isoformat(),
                upstream_message_truncated=truncated, upstream_message_hidden=hidden, **controlled)


async def probe_embedding(route):
    start = time.monotonic()
    response = None
    error = None
    try:
        url = validate_upstream_url(route.url)
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(url, headers={'Authorization':f'Bearer {route.api_key}'},
                                         json={'model':route.model_id,'input':'kiwi-mem embedding probe'})
    except httpx.RequestError as exc:
        error = exception_code(exc)
    return describe_embedding_probe(route, response=response, error_code=error,
                                    elapsed_ms=(time.monotonic()-start)*1000)
