import os
import re
import sys
import http.cookiejar
import urllib.parse
import urllib.request

os.chdir(r'C:\Users\HP\Documents\school_assess_app_EXPERIMENTAL_ver_1')
from app import app
from models import User, Student

with app.app_context():
    admin = User.query.filter_by(role='admin').first()
    student = Student.query.order_by(Student.id).first()
    if not admin or not student:
        print('Failure: missing admin or student data')
        sys.exit(1)
    print('admin:', admin.username)
    print('student_id:', student.id)

base = 'http://127.0.0.1:5000'

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(cj),
    urllib.request.HTTPRedirectHandler(),
)

# Retrieve login page for CSRF token and session cookie
login_page = opener.open(base + '/login')
login_body = login_page.read().decode('utf-8', errors='replace')
csrf_match = re.search(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"', login_body)
if not csrf_match:
    print('Failed to extract CSRF token from login page')
    sys.exit(1)
csrf_token = csrf_match.group(1)
print('login page status', login_page.getcode(), 'csrf_token found')

login_data = urllib.parse.urlencode({
    'username': admin.username,
    'password': 'Admin@123',
    'csrf_token': csrf_token,
}).encode('utf-8')

login_req = urllib.request.Request(
    base + '/login', data=login_data,
    headers={'Content-Type': 'application/x-www-form-urlencoded'},
)
try:
    login_resp = opener.open(login_req)
    login_url = login_resp.geturl()
    print('login status', login_resp.getcode(), 'url:', login_url)
    if '/login' in login_url:
        print('Login did not succeed; still at login page')
        sys.exit(1)
except Exception as exc:
    print('login failed:', exc)
    sys.exit(1)

for path in ['/admin/class-register', f'/students/{student.id}']:
    try:
        r = opener.open(base + path)
        body = r.read(10240).decode('utf-8', errors='replace')
        title = 'NO TITLE'
        if '<title>' in body and '</title>' in body:
            title = body.split('<title>', 1)[1].split('</title>', 1)[0]
        print(path, 'status', r.getcode(), 'title:', title)
    except Exception as exc:
        print(path, 'failed:', exc)
        sys.exit(1)
