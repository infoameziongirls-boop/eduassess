import os
import sys
import re
sys.path.insert(0, os.getcwd())
from app import app
from models import User, Student

with app.test_client() as client:
    with app.app_context():
        student = Student.query.filter_by(student_number='ARABA001').first()
        if not student:
            raise SystemExit('Student ARABA001 not found')
        user = User.query.filter_by(username='ARABA001').first()
        print('Found user', user and user.username, 'role', user.role if user else None)

    resp = client.get('/student/login')
    html = resp.data.decode('utf-8')
    print('GET /student/login status', resp.status_code)
    token_match = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html)
    print('Found csrf token:', bool(token_match))
    token = token_match.group(1) if token_match else None

    resp = client.post('/student/login', data={'identifier': 'ARABA001', 'csrf_token': token}, follow_redirects=True)
    print('POST /student/login status', resp.status_code)
    print('POST redirected to path', resp.request.path)
    body = resp.data.decode('utf-8')
    print('Body snippet:', body[:400].replace('\n', ' '))

    resp = client.get('/student/dashboard')
    print('GET /student/dashboard status', resp.status_code)
    print('Dashboard location', resp.location)
    print('Dashboard snippet:', resp.data.decode('utf-8')[:400].replace('\n', ' '))
