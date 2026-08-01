import os
import sys
sys.path.insert(0, os.getcwd())
from app import app
from models import User, Student

with app.test_client() as client:
    with app.app_context():
        user = User.query.filter_by(username='ARABA001').first()
        student = Student.query.filter_by(student_number='ARABA001').first()
        if not user or not student:
            raise SystemExit('Student or user not found')
        print('user:', user.username, 'role:', user.role)
        print('student:', student.full_name(), student.class_name, student.study_area)

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    resp = client.get('/student/dashboard')
    print('status:', resp.status_code)
    html = resp.data.decode('utf-8')
    print('title snippet:', next((line for line in html.splitlines() if '<title>' in line), 'N/A'))
    print('contains student name:', student.full_name() in html)
    print('contains grade point total label:', 'Grade Point' in html)
    print('contains class division label:', 'Class Division' in html)
    print('contains A1:', 'A1' in html)
    print('contains B2:', 'B2' in html)
    print('contains B3:', 'B3' in html)
    print('contains C6:', 'C6' in html)
    print('contains D7:', 'D7' in html)
    print('contains E8:', 'E8' in html)
    print('contains F9:', 'F9' in html)
