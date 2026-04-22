"""
Comprehensive test to find routing and Jinja template errors
"""
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

if __name__ == '__main__':
    test_endpoints()
