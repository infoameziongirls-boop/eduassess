"""
Comprehensive test to find Jinja template errors
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import User, Student, Admin
from flask_login import login_user
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt(app)

def test_all_templates():
    """Test all templates for undefined variables and methods"""
    with app.app_context():
        # Clean up test users
        User.query.filter_by(username='test_admin').delete()
        db.session.commit()
        
        # Create test admin user
        admin_user = User(
            username='test_admin',
            password_hash=bcrypt.generate_password_hash('Test@123'),
            role='admin'
        )
        db.session.add(admin_user)
        db.session.commit()
        
        with app.test_request_context():
            login_user(admin_user)
            
            with app.test_client() as client:
                # First, login properly
                response = client.post('/login', data={
                    'username': 'test_admin',
                    'password': 'Test@123'
                })
                
                print("=" * 60)
                print("TESTING CRITICAL ENDPOINTS")
                print("=" * 60)
                
                # Test critical endpoints
                critical_endpoints = [
                    '/',
                    '/dashboard',
                    '/students',
                    '/assessments',
                    '/users',
                    '/admin/settings',
                    '/admin/activity-logs',
                    '/admin/class-management',
                    '/admin/messages',
                    '/messages',
                    '/teacher/question-bank',
                    '/teacher/quizzes',
                ]
                
                for endpoint in critical_endpoints:
                    try:
                        response = client.get(endpoint, follow_redirects=True)
                        
                        # Check for template errors
                        response_text = response.data.decode('utf-8', errors='ignore')
                        
                        if 'UndefinedError' in response_text or 'jinja2.exceptions' in response_text:
                            print(f"✗ {endpoint}: JINJA2 ERROR")
                            # Extract error details
                            if 'has no attribute' in response_text:
                                error_line = [line for line in response_text.split('\n') if 'has no attribute' in line][0]
                                print(f"  Error: {error_line.strip()}")
                        elif 'BuildError' in response_text or 'werkzeug.routing' in response_text:
                            print(f"✗ {endpoint}: ROUTING ERROR")
                            if 'Could not build url' in response_text:
                                error_line = [line for line in response_text.split('\n') if 'Could not build' in line]
                                if error_line:
                                    print(f"  Error: {error_line[0].strip()}")
                        else:
                            print(f"✓ {endpoint}: {response.status_code}")
                            
                    except Exception as e:
                        print(f"✗ {endpoint}: Exception - {str(e)}")
                
                print("\n" + "=" * 60)
                print("TESTING COMPLETE")
                print("=" * 60)

if __name__ == '__main__':
    test_all_templates()
