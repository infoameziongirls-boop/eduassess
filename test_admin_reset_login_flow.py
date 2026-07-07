import re
import uuid

from app import app, db, bcrypt
from models import User


def extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"', html)
    if not match:
        match = re.search(r'value="([^"]+)"\s+name="csrf_token"', html)
    return match.group(1) if match else ''


def test_admin_reset_teacher_password_then_teacher_can_login(monkeypatch):
    app.config['TESTING'] = True

    admin_username = f'admin_test_{uuid.uuid4().hex[:8]}'
    teacher_username = f'teacher_test_{uuid.uuid4().hex[:8]}'
    admin_password = 'AdminPass123'
    teacher_password = 'InitialPass123'
    reset_password = 'NewTeacherPass123'

    with app.app_context():
        teacher = User(
            username=teacher_username,
            password_hash=bcrypt.generate_password_hash(teacher_password).decode('utf-8'),
            role='teacher',
        )
        db.session.add(teacher)
        admin = User(
            username=admin_username,
            password_hash=bcrypt.generate_password_hash(admin_password).decode('utf-8'),
            role='admin',
        )
        db.session.add(admin)
        db.session.commit()
        teacher_id = teacher.id

    with app.test_client() as client:
        login_page = client.get('/login')
        csrf_token = extract_csrf_token(login_page.data.decode('utf-8', errors='replace'))
        assert csrf_token, 'Missing CSRF token on login page'

        response = client.post(
            '/login',
            data={'username': admin_username, 'password': admin_password, 'csrf_token': csrf_token},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b'Invalid credentials' not in response.data

        reset_page = client.get(f'/users/{teacher_id}/reset_password')
        reset_csrf_token = extract_csrf_token(reset_page.data.decode('utf-8', errors='replace'))
        assert reset_csrf_token, 'Missing CSRF token on password reset page'

        response = client.post(
            f'/users/{teacher_id}/reset_password',
            data={'password': reset_password, 'csrf_token': reset_csrf_token},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b'Password reset for' in response.data

        response = client.get('/logout', follow_redirects=True)
        assert response.status_code == 200

        login_page = client.get('/login')
        csrf_token = extract_csrf_token(login_page.data.decode('utf-8', errors='replace'))
        assert csrf_token, 'Missing CSRF token on login page before teacher login'

        response = client.post(
            '/login',
            data={'username': teacher_username, 'password': reset_password, 'csrf_token': csrf_token},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b'Invalid credentials' not in response.data

    with app.app_context():
        admin = User.query.filter_by(username=admin_username).first()
        if admin:
            db.session.delete(admin)

        teacher = User.query.filter_by(username=teacher_username).first()
        if teacher:
            db.session.delete(teacher)

        db.session.commit()
