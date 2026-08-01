import os
import sys
import re
import requests
BASE = 'http://127.0.0.1:5000'

s = requests.Session()
resp = s.get(f'{BASE}/student/login')
print('GET login', resp.status_code)
print('cookies after GET login:', s.cookies.get_dict())
match = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', resp.text)
print('token found', bool(match))
token = match.group(1) if match else None
resp = s.post(f'{BASE}/student/login', data={'identifier': 'ARABA001', 'csrf_token': token}, allow_redirects=False)
print('POST login status', resp.status_code)
print('POST headers set-cookie', resp.headers.get('Set-Cookie'))
print('cookies after POST login:', s.cookies.get_dict())
print('location', resp.headers.get('Location'))
if resp.status_code == 302 and resp.headers.get('Location'):
    resp = s.get(BASE + resp.headers['Location'], allow_redirects=False)
    print('GET redirect status', resp.status_code)
    print('GET redirect headers set-cookie', resp.headers.get('Set-Cookie'))
    print('cookies after redirect get', s.cookies.get_dict())
    print('body snippet', resp.text[:400])

resp = s.get(f'{BASE}/student/dashboard', allow_redirects=False)
print('GET dashboard status', resp.status_code)
print('GET dashboard headers set-cookie', resp.headers.get('Set-Cookie'))
print('cookies at dashboard request', s.cookies.get_dict())
print('dashboard body snippet', resp.text[:400])
