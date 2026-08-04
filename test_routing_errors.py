"""
Comprehensive test to find routing and Jinja template errors
"""
import importlib
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import User, Student
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt(app)

def test_endpoints():
    """Test all endpoints for errors"""
    with app.app_context():
        ext = app.extensions.get('sqlalchemy')
        if ext and hasattr(ext, '_app_engines'):
            ext._app_engines[app].clear()
            options = {'url': app.config['SQLALCHEMY_DATABASE_URI'], **ext._engine_options}
            engine = ext._make_engine(None, options, app)
            ext._app_engines[app][None] = engine
            db.create_all()
        
        # Create test admin user
        admin = User(
            username='test_admin',
            password_hash=bcrypt.generate_password_hash('Test@123'),
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()
        
        with app.test_client() as client:
            # Login
            response = client.post('/login', data={
                'username': 'test_admin',
                'password': 'Test@123'
            }, follow_redirects=True)
            
            print(f"Login response: {response.status_code}")
            
            # Test critical endpoints
            test_endpoints = [
                ('/', 'GET'),
                ('/dashboard', 'GET'),
                ('/students', 'GET'),
                ('/assessments', 'GET'),
                ('/users', 'GET'),
                ('/admin/settings', 'GET'),
                ('/admin/activity-logs', 'GET'),
                ('/admin/class-management', 'GET'),
                ('/messages', 'GET'),
            ]
            
            for endpoint, method in test_endpoints:
                try:
                    if method == 'GET':
                        response = client.get(endpoint)
                    else:
                        response = client.post(endpoint)
                    
                    print(f"✓ {endpoint}: {response.status_code}")
                    
                    # Check for Jinja2 errors in response
                    if b'UndefinedError' in response.data or b'TemplateAssertionError' in response.data:
                        print(f"  ✗ Template error found in {endpoint}")
                        print(response.data[:500])
                    if b'BuildError' in response.data or b'werkzeug' in response.data:
                        print(f"  ✗ Routing error found in {endpoint}")
                        print(response.data[:500])
                        
                except Exception as e:
                    print(f"✗ {endpoint}: {str(e)}")


def test_error_handler_survives_session_store_and_rollback_failures(monkeypatch):
    """A broken session store should not crash the 500 page renderer."""

    app_module = importlib.import_module('app')
    app.testing = True

    @app.route('/test-session-failure')
    def test_session_failure():
        raise RuntimeError('simulated app error')

    def fail_open_session(*args, **kwargs):
        raise RuntimeError('session store unavailable')

    def fail_rollback():
        raise RuntimeError('rollback failed')

    monkeypatch.setattr(app_module, '_original_open_session', fail_open_session)
    monkeypatch.setattr(db.session, 'rollback', fail_rollback)

    try:
        with app.test_client() as client:
            response = client.get('/test-session-failure')
    finally:
        app.view_functions.pop('/test-session-failure', None)

    assert response.status_code == 500
    assert b'Something Went Wrong' in response.data


if __name__ == '__main__':
    test_endpoints()
