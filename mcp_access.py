"""MCP access observation and transport security.

Authority parsing is dependency-free so the host updater can use the same
registration rules without installing the application's Python dependencies.
"""
import ipaddress
import os
import re
import time

_next_write = 0.0


def parse_authority(value, wildcard_port=False):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
        return None
    if any(c in value for c in '/\\@?#%'):
        return None
    port = None
    if value.startswith('['):
        end = value.find(']')
        if end < 0:
            return None
        host, rest = value[1:end], value[end+1:]
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return None
        if rest:
            if not rest.startswith(':'):
                return None
            port = rest[1:]
    else:
        if value.count(':') > 1:
            return None
        host, sep, port_text = value.partition(':')
        if sep:
            port = port_text
        try:
            ascii_host = host.encode('idna').decode('ascii').rstrip('.')
        except UnicodeError:
            return None
        if len(ascii_host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', p) for p in ascii_host.split('.')):
            return None
    if port is not None and not (wildcard_port and port == '*'):
        if not re.fullmatch(r'[0-9]{1,5}', port) or not 1 <= int(port) <= 65535:
            return None
    return host.lower().rstrip('.')


def valid_host(value):
    return value.isascii() and parse_authority(value, wildcard_port=True) is not None


def valid_origin(value):
    scheme, sep, authority = value.partition('://')
    return bool(sep and scheme in ('http', 'https') and valid_host(authority))


def read_allowlists():
    result = {}
    for field, validator in (('hosts', valid_host), ('origins', valid_origin)):
        items = [v.strip() for v in os.getenv('MCP_ALLOWED_'+field.upper(), '').split(',') if v.strip()]
        good = sum(validator(v) for v in items)
        result[field+'_registered'] = good
        result[field+'_invalid'] = len(items)-good
    return result


async def get_pool():
    from database import get_pool as database_pool
    return await database_pool()


def observe_mcp_access(app):
    async def observed(scope, receive, send):
        global _next_write
        if scope['type'] == 'http':
            hosts = [v for k,v in scope.get('headers', []) if k.lower() == b'host']
            authority = hosts[0].decode('latin-1') if len(hosts) == 1 else ''
            host = parse_authority(authority)
            local = host == 'localhost'
            if host is not None:
                try:
                    ipaddress.ip_address(host)
                    local = True
                except ValueError:
                    pass
            if not local and time.monotonic() >= _next_write:
                # Reserve before awaiting: concurrent requests share the throttle.
                _next_write = time.monotonic() + 60
                try:
                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        await conn.execute('''INSERT INTO mcp_access_observation
                            (id, foreign_host_seen, last_seen_at) VALUES (1, TRUE, now())
                            ON CONFLICT (id) DO UPDATE SET foreign_host_seen=TRUE,
                                last_seen_at=EXCLUDED.last_seen_at''')
                except Exception:
                    # Observation availability cannot change MCP access.
                    pass
        await app(scope, receive, send)
    return observed


async def mcp_access_status(version='1.7.0'):
    from starlette.responses import JSONResponse
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow('SELECT foreign_host_seen, last_seen_at FROM mcp_access_observation WHERE id=1')
        timestamp = row['last_seen_at'] if row else None
        return {'protection': 'enabled', **read_allowlists(), 'ip_literal_allowed': True,
                'foreign_host_seen': bool(row and row['foreign_host_seen']),
                'foreign_host_last_seen_at': timestamp.isoformat() if timestamp else None,
                'version': version}
    except Exception:
        return JSONResponse({'error': 'internal_error', 'error_code': 'internal_error'}, status_code=500)


def log_mcp_access_summary():
    counts = read_allowlists()
    for field in ('hosts', 'origins'):
        if counts[field+'_invalid']:
            print(f"event=mcp_allowlist_invalid_item field={field} increment={counts[field+'_invalid']}")
    print(f"event=mcp_access_control hosts={counts['hosts_registered']} origins={counts['origins_registered']} ip_literal=true")
    if not counts['hosts_registered']:
        print('当前 MCP 只接受本机与 IP 直连；用域名访问 MCP 需登记 MCP_ALLOWED_HOSTS / MCP_ALLOWED_ORIGINS，见 docs/UPGRADING.md')


_BUILTIN_HOSTS = ['localhost', 'localhost:*', '127.0.0.1', '127.0.0.1:*', '[::1]', '[::1]:*']
_BUILTIN_ORIGINS = ['http://localhost', 'http://localhost:*', 'http://127.0.0.1', 'http://127.0.0.1:*', 'http://[::1]', 'http://[::1]:*']
_transport_security = None


def build_transport_security():
    # Lazy SDK import preserves dependency-free host updater parsing.
    from mcp.server.transport_security import TransportSecuritySettings
    global _transport_security
    if _transport_security is None:
        hosts = [v.strip() for v in os.getenv('MCP_ALLOWED_HOSTS', '').split(',') if v.strip() and valid_host(v.strip())]
        origins = [v.strip() for v in os.getenv('MCP_ALLOWED_ORIGINS', '').split(',') if v.strip() and valid_origin(v.strip())]
        _transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(dict.fromkeys(_BUILTIN_HOSTS + hosts)),
            allowed_origins=list(dict.fromkeys(_BUILTIN_ORIGINS + origins)),
        )
    return _transport_security


def install_transport_security_log_filter():
    import logging
    logger = logging.getLogger('mcp.server.transport_security')
    if any(getattr(f, '_kiwi_transport_filter', False) for f in logger.filters):
        return

    class TransportFilter(logging.Filter):
        _kiwi_transport_filter = True

        def filter(self, record):
            message = record.getMessage()
            for prefix, reason in (
                ('Invalid Host header', 'host'), ('Missing Host header', 'host'),
                ('Invalid Origin header', 'origin'),
                ('Invalid Content-Type header', 'content_type'),
                ('Missing Content-Type header', 'content_type'),
            ):
                if message.startswith(prefix):
                    record.msg = 'mcp_transport_security_rejected reason=' + reason
                    record.args = ()
                    break
            return True

    logger.addFilter(TransportFilter())


def _listed(raw, allowed):
    return raw in allowed or any(p.endswith(':*') and raw.startswith(p[:-2] + ':') for p in allowed)


def guard_mcp_access(app, settings):
    async def reject(scope, receive, send, status, code, reason, field=None):
        import logging
        from starlette.responses import JSONResponse
        payload = {'error': code, 'error_code': code}
        if field:
            payload['hint'] = '请配置 ' + field + '，见 docs/UPGRADING.md'
        logging.getLogger(__name__).warning('event=mcp_access_rejected reason=%s increment=1', reason)
        await JSONResponse(payload, status_code=status)(scope, receive, send)

    async def guarded(scope, receive, send):
        if scope['type'] != 'http':
            return await app(scope, receive, send)
        from starlette.datastructures import Headers
        headers = Headers(scope=scope)
        ct = headers.get('content-type')
        if scope.get('method') == 'POST' and not (bool(ct) and ct.lower().startswith('application/json')):
            return await reject(scope, receive, send, 400, 'invalid_content_type', 'content_type')
        host_values = [v for k, v in scope.get('headers', []) if k.lower() == b'host']
        raw = host_values[0].decode('latin-1') if len(host_values) == 1 else ''
        authority = parse_authority(raw)
        if authority is None:
            return await reject(scope, receive, send, 421, 'mcp_host_not_allowed', 'host', 'MCP_ALLOWED_HOSTS')
        try:
            ipaddress.ip_address(authority)
            is_ip = True
        except ValueError:
            is_ip = False
        if not is_ip and not _listed(raw, settings.allowed_hosts):
            return await reject(scope, receive, send, 421, 'mcp_host_not_allowed', 'host', 'MCP_ALLOWED_HOSTS')
        origin = headers.get('origin')
        if origin is not None and not _listed(origin, settings.allowed_origins):
            return await reject(scope, receive, send, 403, 'mcp_origin_not_allowed', 'origin', 'MCP_ALLOWED_ORIGINS')
        if is_ip:
            # MCP 1.29.1 consumes Host only in its security layer. Reaudit on upgrade.
            forwarded = dict(scope)
            forwarded['headers'] = [(k, b'127.0.0.1' if k.lower() == b'host' else v) for k, v in scope.get('headers', [])]
            return await app(forwarded, receive, send)
        return await app(scope, receive, send)
    return guarded
