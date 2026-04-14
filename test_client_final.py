from app import app
import sys

def test_endpoints():
    """Test Flask app endpoints using test client"""
    with app.test_client() as client:
        print("Testing Flask app endpoints with test client...")

        # Test login page
        response = client.get('/login')
        print(f'Login page: {response.status_code}')

        # Test students page (should be 403 without login)
        response = client.get('/students')
        print(f'Students page: {response.status_code}')

        # Test assessments page (should be 403 without login)
        response = client.get('/assessments')
        print(f'Assessments page: {response.status_code}')

        # Test dashboard (should redirect to login)
        response = client.get('/dashboard')
        print(f'Dashboard: {response.status_code}')

        # Test index page
        response = client.get('/')
        print(f'Index page: {response.status_code}')

        # Test admin login page
        response = client.get('/admin/login')
        print(f'Admin login: {response.status_code}')

        # Test class register page (should be 403 without login)
        response = client.get('/admin/class-register')
        print(f'Class register: {response.status_code}')

        print("All endpoint tests completed successfully!")

if __name__ == '__main__':
    test_endpoints()