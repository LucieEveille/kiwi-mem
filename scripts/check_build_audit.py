"""BUILD removes the PREP exception: every dependency must be audited, zero IDs."""
import json
import sys

def check(path):
    with open(path, encoding='utf-8') as handle:
        data=json.load(handle)
    packages=data['dependencies']
    assert packages, 'empty audit'
    assert not any(p.get('skip_reason') for p in packages), 'skipped dependency'
    assert not any(p.get('vulns') for p in packages), 'BUILD requires zero vulnerabilities'
    print(f'PASS: {len(packages)} dependencies, zero vulnerability IDs')

if __name__=='__main__': check(sys.argv[1])
