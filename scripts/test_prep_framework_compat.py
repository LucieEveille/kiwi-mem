"""Framework compatibility smoke; two fresh app lifespans, no real database/model."""
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

if __name__=='__main__':
    if '--child' not in sys.argv:
        for _ in range(2):
            subprocess.run([sys.executable,__file__,'--child'],check=True,cwd=ROOT,env=dict(os.environ,PYTHONIOENCODING='utf-8'))
        print('PASS: two fresh application lifespans, static admin, multipart upload, CORS')
    else:
        os.environ['MEMORY_ENABLED']='false'
        os.environ['DATABASE_URL']='postgresql://unused:unused@127.0.0.1:1/unused'
        from fastapi.testclient import TestClient
        import main
        with TestClient(main.app) as client:
            r=client.get('/admin',follow_redirects=True)
            assert r.status_code==200 and r.headers['content-type'].startswith('text/html')
            r=client.post('/v1/files/extract',files={'file':('fixture.txt',b'prep upload fixture','text/plain')})
            assert r.status_code==200 and 'prep upload fixture' in r.text
            r=client.options('/v1/chat/completions',headers={'Origin':'https://fixture.example','Access-Control-Request-Method':'POST'})
            assert r.status_code==200 and 'access-control-allow-origin' in r.headers
