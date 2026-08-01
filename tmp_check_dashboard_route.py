import os
import sys
sys.path.insert(0, os.getcwd())
from app import app, bcrypt
from models import Student, User

with app.test_client() as client:
    with app.app_context():
        student = Student.query.filter_by(student_number='ARABA001').first()
        if not student:
            raise SystemExit('Student ARABA001 not found')
        user = User.query.filter_by(username='ARABA001').first()
        print('Found user', user and user.username, 'role', user.role)
    # login by student number using POST to /student/login
    resp = client.post('/student/login', data={'identifier': 'ARABA001'}, follow_redirects=True)
    print('login status', resp.status_code)
    if resp.status_code == 200:
        print('response title snippet:', resp.data.decode('utf-8')[:400])
    # try dashboard access directly
    resp = client.get('/student/dashboard')
    print('dashboard status', resp.status_code)
    print('dashboard content snippet:', resp.data.decode('utf-8')[:400])
