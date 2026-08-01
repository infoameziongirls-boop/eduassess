import os
import sys
sys.path.insert(0, os.getcwd())
from app import app
from models import User, Student

with app.test_client() as client:
    with app.app_context():
        user = User.query.filter_by(username='ARABA001').first()
        if not user:
            raise SystemExit('Student user not found')
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    resp = client.get('/student/dashboard')
    html = resp.data.decode('utf-8')
    with open('tmp_student_dashboard.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print('status', resp.status_code)
    print('contains D7', 'D7' in html)
    print('contains physics', 'physics' in html)
    print('contains additional mathematics', 'additional mathematics' in html)
    print('contains Show all teachers', 'Show all teachers' in html)
    print('file written')
