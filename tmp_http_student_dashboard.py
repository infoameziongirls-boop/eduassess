import os
import sys
import re
import requests

BASE = 'http://127.0.0.1:5000'

s = requests.Session()
resp = s.get(f'{BASE}/student/login')
print('GET /student/login:', resp.status_code)
if resp.status_code != 200:
    print(resp.text[:400])
    sys.exit(1)
match = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', resp.text)
print('csrf token found:', bool(match))
token = match.group(1) if match else None
resp = s.post(f'{BASE}/student/login', data={'identifier': 'ARABA001', 'csrf_token': token}, allow_redirects=True)
print('POST /student/login:', resp.status_code)
print('final path:', resp.url)
print('redirect history:', [r.status_code for r in resp.history])
print('body title snippet:', resp.text[:300])
resp = s.get(f'{BASE}/student/dashboard')
print('GET /student/dashboard:', resp.status_code)
print('dashboard url:', resp.url)
print('headers set-cookie:', resp.headers.get('set-cookie'))
print('body snippet:', resp.text[:400])
