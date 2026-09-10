#!/usr/bin/env python3
"""BUILD-01 stage A inventory. Executable mutation anchors follow in stage B.

--list is read-only. This stage must not claim mutations were executed before
an implementation exists and the preflight guards are green.
"""
import argparse
import json

INVENTORY = [
    ('memory transport_security keyword removed', ['T-10','T-12']),
    ('calendar settings replaced with another object', ['T-02']),
    ('unregistered Host accepted by guard', ['T-03']),
    ('IP parsed using a numeric string prefix', ['T-07']),
    ('IP skips Origin validation', ['T-04']),
    ('IP appended to shared allowed_hosts', ['T-02','T-07']),
    ('rejection body contains original Host', ['T-06']),
    ('transport-security logger filter removed', ['T-06','T-12']),
    ('wildcard domain registration accepted', ['T-02']),
    ('Origin list derived from CORS_ORIGINS', ['T-02','T-10']),
    ('missing Host accepted', ['T-03']),
    ('Content-Type guard removed', ['T-05']),
    ('SDK rebinding protection disabled', ['T-12']),
    ('bare 127.0.0.1 missing from builtins', ['T-03']),
    ('mcp pin replaced with open lower bound', ['T-01']),
    ('status returns preview', ['T-08']),
    ('startup output contains registration value', ['T-09']),
    ('guard wrapped outside observation', ['T-10']),
    ('authority accepts unbracketed multi-colon host', ['T-07']),
    ('Origin wildcard port uses substring matching', ['T-04']),
    ('IP Host rewrite removed', ['T-03','T-07']),
    ('Host rewrite applied to non-IP requests', ['T-07']),
    ('Content-Type stripped before validation', ['T-05']),
]

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if not args.list:
        parser.error('stage A inventory only; execution requires stage B anchors and green preflight')
    print(json.dumps([{'id':f'K-BUILD-{i}', 'mutation':name, 'guards':guards,
                       'state':'planned-not-executed'}
                      for i,(name,guards) in enumerate(INVENTORY,1)],indent=2))
