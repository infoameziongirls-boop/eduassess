"""
Test the timezone fix for the 'online now' indicator.
Verifies that the TypeError from naive/aware datetime mismatch is resolved.
"""
from app import app
import re

def test_login_and_dashboard():
    client = app.test_client()
    
    # Get the login page and extract CSRF token
    r = client.get('/login')
    html = r.data.decode('utf-8')
    csrf_match = re.search(r'csrf_token["\']?\s+value=["\']([^"\']+)["\']', html)
    csrf_token = csrf_match.group(1) if csrf_match else None
    print('1. CSRF Token extracted:', bool(csrf_token))
    
    if not csrf_token:
        print('ERROR: Could not extract CSRF token')
        return False
    
    # Login with proper CSRF token  
    r = client.post('/login', data={
        'username': 'admin',
        'password': 'admin123',
        'csrf_token': csrf_token
    }, follow_redirects=True)
    print(f'2. Login request: {r.status_code}')
    
    if r.status_code != 200:
        print(f'   ERROR: Login failed with {r.status_code}')
        return False
    
    # Test dashboard loads without 500
    r = client.get('/', follow_redirects=True)
    print(f'3. First dashboard request: {r.status_code}')
    
    if r.status_code != 200:
        print(f'   ERROR: Dashboard failed with {r.status_code}')
        return False
    
    # Simulate multiple requests (exercise the before_request hook multiple times)
    # This tests both the first-write path and the subsequent-read path
    print('4. Multiple consecutive requests:')
    for i in range(3):
        r = client.get('/', follow_redirects=True)
        print(f'   Request {i+1}: {r.status_code}')
        
        if r.status_code != 200:
            print(f'   ERROR: Request {i+1} failed with {r.status_code}')
            return False
    
    print('\n✓ All tests passed - timezone fix is working!')
    return True

if __name__ == '__main__':
    success = test_login_and_dashboard()
    exit(0 if success else 1)
