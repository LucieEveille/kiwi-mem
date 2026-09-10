"""The approved exception is an exact ID set; duplicate feed rows stay visible."""
import json
import sys

def check(path):
    data=json.load(open(path,encoding='utf-8'))
    found=set()
    count=0
    for package in data['dependencies']:
        if package.get('skip_reason'):
            raise AssertionError('audit skipped a dependency')
        for vulnerability in package.get('vulns',[]):
            assert package['name']=='mcp' and package['version']=='1.12.4', 'unapproved vulnerable package'
            found.add(vulnerability['id']); count+=1
    assert found=={'PYSEC-2026-1617','PYSEC-2026-3482','PYSEC-2026-3483'}, 'vulnerability set differs from exception'
    print(f'PASS: exactly 3 approved vulnerability IDs; {count} original rows retained')

if __name__=='__main__': check(sys.argv[1])
