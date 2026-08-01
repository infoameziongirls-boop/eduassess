import os
import sys
import threading
import time
import re
import requests
from werkzeug.serving import make_server
sys.path.insert(0, os.getcwd())
from app import app

class ServerThread(threading.Thread):
    def __init__(self, app, host='127.0.0.1', port=5001):
        threading.Thread.__init__(self)
        self.server = make_server(host, port, app)
        self.ctx = app.app_context()
        self.ctx.push()
        self.daemon = True

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()

server = ServerThread(app, port=5001)
server.start()
print('server started on http://127.0.0.1:5001')

time.sleep(1)

s = requests.Session()
base = 'http://127.0.0.1:5001'
resp = s.get(f'{base}/student/login')
print('GET login', resp.status_code)
match = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', resp.text)
print('token found', bool(match))
token = match.group(1) if match else None
resp = s.post(f'{base}/student/login', data={'identifier': 'ARABA001', 'csrf_token': token}, allow_redirects=False)
print('POST login status', resp.status_code)
print('location', resp.headers.get('Location'))
print('cookies', s.cookies.get_dict())
if resp.status_code == 302:
    resp2 = s.get(base + resp.headers['Location'], allow_redirects=False)
    print('redirect status', resp2.status_code)
    print('redirect headers', resp2.headers)
    print('redirect body snippet', resp2.text[:400])
resp = s.get(f'{base}/student/dashboard', allow_redirects=False)
print('GET dashboard status', resp.status_code)
print('dashboard url', resp.url)
print('dashboard body snippet', resp.text[:400])

server.shutdown()
print('server stopped')
