#!/usr/bin/env python3
from app import app
from models import Student, User

with app.app_context():
    app.config['WTF_CSRF_ENABLED'] = False
    client = app.test_client()

    tests = [
        {
            'name': 'AYITEY HELEN',
            'password': 'STU250030606104',
            'expect': True
        },
        {
            'name': 'ayitey helen',
            'password': 'STU892048',
            'expect': True
        },
        {
            'name': 'EHUN SARAH',
            'password': 'STU860326',
            'expect': True
        },
        {
            'name': 'EHUN SARAH',
            'password': 'wrongpassword',
            'expect': False
        },
        {
            'name': 'AYITEY',
            'password': 'STU250030606104',
            'expect': False
        }
    ]

    for test in tests:
        response = client.post('/student/login', data={
            'username': test['name'],
            'password': test['password']
        }, follow_redirects=False)

        status = response.status_code
        location = response.headers.get('Location', '')
        body = response.get_data(as_text=True)

        success = (status == 302 and '/student/dashboard' in location)
        print('TEST:', test['name'], test['password'], 'EXPECT', test['expect'], 'GOT', success, 'STATUS', status, 'LOCATION', location)
        if not success and test['expect']:
            print('BODY SNIPPET:', body[:400])
            print('---')
        if success and not test['expect']:
            print('UNEXPECTED SUCCESS', body[:400])
            print('---')
