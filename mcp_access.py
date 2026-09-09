"""MCP access preview only. Never authorizes or rejects a request.

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
    return parse_authority(value, wildcard_port=True) is not None


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


async def mcp_access_status():
    from starlette.responses import JSONResponse
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow('SELECT foreign_host_seen, last_seen_at FROM mcp_access_observation WHERE id=1')
        timestamp = row['last_seen_at'] if row else None
        return {'protection': 'preview', **read_allowlists(), 'ip_literal_allowed': True,
                'foreign_host_seen': bool(row and row['foreign_host_seen']),
                'foreign_host_last_seen_at': timestamp.isoformat() if timestamp else None,
                'version': '1.7.0'}
    except Exception:
        return JSONResponse({'error': 'internal_error', 'error_code': 'internal_error'}, status_code=500)


def log_mcp_access_preview():
    counts = read_allowlists()
    for field in ('hosts', 'origins'):
        if counts[field+'_invalid']:
            print(f"event=mcp_allowlist_invalid_item field={field} increment={counts[field+'_invalid']}")
    print(f"event=mcp_allowlist_preview hosts={counts['hosts_registered']} origins={counts['origins_registered']} increment=1")
    if not counts['hosts_registered']:
        print('预告：下一大版本起 MCP 只接受登记过的访问地址（本机与 IP 直连无需登记）；用域名访问 MCP 请先在 .env 登记 MCP_ALLOWED_HOSTS / MCP_ALLOWED_ORIGINS，见 docs/UPGRADING.md')
