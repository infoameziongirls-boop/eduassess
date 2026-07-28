"""Quick script to render student dashboard HTML for a created student and print the class division snippet.
Run with: python tools/check_dashboard_division.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, db
from models import Student, User

os.environ.setdefault('FLASK_ENV', 'development')

with app.app_context():
    # Ensure clean DB for the quick check
    db.create_all()
    # Remove any previous test entries to avoid UNIQUE constraint conflicts
    Student.query.filter_by(student_number='STU001').delete()
    User.query.filter_by(username='STU001').delete()
    db.session.commit()

    # Create student and user
    student = Student(first_name='Student1', last_name='Test1', student_number='STU001', reference_number='REF001', class_name='Form 1', study_area='Arts')
    db.session.add(student)
    db.session.commit()
    # Create associated user for login (username == student_number)
    user = User(username=student.student_number, password_hash='x', role='student')
    db.session.add(user)
    db.session.commit()

    client = app.test_client()
    # Log in by setting session user id
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True

    r = client.get('/student/dashboard')
    print('Status:', r.status_code)
    html = r.data.decode('utf-8')
    # Print snippet around Class Division
    idx = html.find('Class Division')
    if idx != -1:
        print(html[idx:idx+300])
    else:
        print('Class Division not found in rendered page')
