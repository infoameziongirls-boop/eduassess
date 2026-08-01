import os
import sys
import re
sys.path.insert(0, os.getcwd())
from app import app
from models import Student

app.testing = True
app.debug = True

with app.test_client() as client:
    with app.app_context():
        student = Student.query.filter_by(student_number='ARABA001').first()
        if not student:
            raise SystemExit('Student ARABA001 not found')
    resp = client.get('/student/login')
    html = resp.data.decode('utf-8')
    token = None
    match = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', html)
    if match:
        token = match.group(1)
    print('csrf token present', bool(token))
    try:
        resp = client.post('/student/login', data={'identifier': 'ARABA001', 'csrf_token': token}, follow_redirects=True)
        print('POST status', resp.status_code)
        print('Response location', resp.request.path)
        print('Body snippet', resp.data.decode('utf-8')[:500])
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise
