#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Manual Testing Guide - Validation Script
"""

import os
import sys
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

try:
    from app import app
    from models import Student, Assessment, User
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

def print_header(title):
    print(f'\n{"=" * 70}')
    print(f'{title:^70}')
    print(f'{"=" * 70}')

def print_section(title):
    print(f'\n{title}')
    print('-' * 70)

def test_database_state():
    """Check database has required data"""
    print_header('DATABASE STATE CHECK')
    
    with app.app_context():
        try:
            # Count records
            student_count = Student.query.count()
            assessment_count = Assessment.query.count()
            admin_users = User.query.filter(User.is_admin == True).count()
            archived_count = Assessment.query.filter_by(archived=True).count()
            
            print_section('Record Counts')
            print(f'  Students:           {student_count:>6}')
            print(f'  Assessments (total): {assessment_count:>6}')
            print(f'  Assessments (archived): {archived_count:>6}')
            print(f'  Admin users:        {admin_users:>6}')
            
            if student_count == 0:
                print('\n  ⚠️  WARNING: No students in database!')
                print('      You need to add students before testing promotions.')
            
            if assessment_count == 0:
                print('\n  ⚠️  WARNING: No assessments in database!')
                print('      Create assessments to test order of merit.')
            
            if admin_users == 0:
                print('\n  ⚠️  WARNING: No admin users found!')
                print('      Create an admin account to access promotion routes.')
            
            return student_count > 0 and admin_users > 0
            
        except Exception as e:
            print(f'  ERROR: {e}')
            return False

def test_routes_exist():
    """Verify all routes are registered"""
    print_header('ROUTE REGISTRATION CHECK')
    
    with app.app_context():
        required_routes = {
            'promotion.promote_class_view': 'GET /admin/promote-class',
            'promotion.execute_promotion': 'POST /admin/promote-class/execute',
            'promotion.order_of_merit': 'GET /admin/order-of-merit',
            'promotion.order_of_merit_print': 'GET /admin/order-of-merit/print',
            'assessments_archived': 'GET /assessments/archived',
        }
        
        all_endpoints = {}
        for rule in app.url_map.iter_rules():
            all_endpoints[rule.endpoint] = rule.rule
        
        missing = []
        for endpoint, expected_rule in required_routes.items():
            if endpoint in all_endpoints:
                actual_rule = all_endpoints[endpoint]
                status = '✓'
                print(f'  {status} {endpoint:40} {actual_rule}')
            else:
                status = '✗'
                print(f'  {status} {endpoint:40} NOT FOUND')
                missing.append(endpoint)
        
        if missing:
            print(f'\n  ERROR: {len(missing)} routes missing!')
            return False
        
        return True

def test_template_rendering():
    """Test templates render with mock data"""
    print_header('TEMPLATE RENDERING CHECK')
    
    from flask import render_template
    
    with app.app_context():
        test_cases = {
            'promote_class.html': {
                'total_students': 150,
                'class_levels': ['Form 1', 'Form 2', 'Form 3'],
                'class_student_counts': {'Form 1': 50, 'Form 2': 50, 'Form 3': 50},
                'class_assessment_counts': {'Form 1': 45, 'Form 2': 48, 'Form 3': 50},
                'class_completion': {'Form 1': 90, 'Form 2': 96, 'Form 3': 100},
                'current_academic_year': '2024-2025',
                'current_term': 'term1',
                'next_academic_year': '2025-2026',
                'terms': [('term1', 'Term 1'), ('term2', 'Term 2')],
                'promotion_history': [],
                'now': datetime.now(),
            },
            'order_of_merit.html': {
                'view': 'all',
                'merit_list': [],
                'class_levels': ['Form 1', 'Form 2', 'Form 3'],
                'learning_areas': ['Math', 'Science', 'English'],
                'terms': [('term1', 'Term 1')],
                'selected_class': 'Form 1',
                'selected_subject': '',
                'selected_term': '',
                'selected_class_label': 'Form 1',
                'current_academic_year': '2024-2025',
                'subjects': [],
                'now': datetime.now(),
            },
            'archive_view.html': {
                'assessments': [],
                'pagination': type('Pagination', (), {
                    'items': [], 'pages': 1, 'total': 0, 'page': 1,
                    'has_prev': False, 'has_next': False
                })(),
                'search': '',
                'selected_subject': '',
                'selected_class': '',
                'selected_term': '',
                'selected_year': '',
                'group': 'all',
                'learning_areas': ['Math', 'Science'],
                'class_levels': ['Form 1', 'Form 2', 'Form 3'],
                'terms': [('term1', 'Term 1')],
                'total_archived': 0,
                'archived_students': 0,
                'archived_terms': 0,
                'last_archive_date': None,
                'term_summary': [],
            }
        }
        
        for tmpl, context in test_cases.items():
            try:
                with app.test_request_context():
                    html = render_template(tmpl, **context)
                    size_kb = len(html) / 1024
                    print(f'  ✓ {tmpl:30} ({size_kb:.1f} KB)')
            except Exception as e:
                print(f'  ✗ {tmpl:30} ERROR: {str(e)[:40]}')
                return False
        
        return True

def print_testing_guide():
    """Print manual testing checklist"""
    print_header('MANUAL TESTING GUIDE')
    
    print_section('Step 1: Start the Application')
    print('''
  Run:
    python -m flask run
  
  Expected: Flask starts on http://127.0.0.1:5000 without errors
    ''')
    
    print_section('Step 2: Login as Admin')
    print('''
  1. Navigate to http://127.0.0.1:5000/login
  2. Login with admin account
  3. Verify "Admin Settings" appears in navigation
    ''')
    
    print_section('Step 3: Test Class Promotion')
    print('''
  1. Navigate to Admin Dashboard
  2. Click "Class Promotion" in the Promotion Panel
  3. Verify class cards appear with student counts
  4. Click a class card (should turn gold)
  5. Scroll to configuration panel
  6. Select target academic year and term
  7. Check "Archive previous assessments"
  8. Type "CONFIRM" in confirmation field
  9. Click "Execute Promotion"
  10. Verify success message and history update
    ''')
    
    print_section('Step 4: Test Order of Merit')
    print('''
  1. Navigate to Admin Dashboard
  2. Click "Order of Merit" in the Promotion Panel
  3. Verify top 3 students show in podium display:
     - 1st place: Gold background
     - 2nd place: Silver background
     - 3rd place: Bronze background
  4. Verify full ranking table shows below
  5. Click "By Class" tab and verify filtering works
  6. Click "By Subject" tab and verify filtering works
  7. Click "Print" button and verify print dialog opens
  8. Click "Export CSV" and verify download works
    ''')
    
    print_section('Step 5: Test Archive Management')
    print('''
  1. Navigate to Admin Settings
  2. Click "View Archive" button
  3. Verify KPI hero with archive statistics
  4. Verify term summary cards appear
  5. Try searching for student name
  6. Try filtering by subject, class, term
  7. Click a restore button (↩️) on an assessment
  8. Verify record moves to active assessments
  9. Select multiple rows with checkboxes
  10. Click "Bulk Restore" or "Bulk Delete"
  11. Verify bulk operation completes
    ''')
    
    print_section('Success Criteria')
    print('''
  ✓ All pages load without JavaScript errors
  ✓ All filters work and return correct data
  ✓ All buttons are clickable and functional
  ✓ Promotion history updates after promotion
  ✓ Print view opens in browser
  ✓ Archive search/filter work correctly
  ✓ Bulk operations complete successfully
    ''')

def main():
    print('\n' + '█' * 70)
    print('  PROMOTION + ARCHIVE INTEGRATION - VALIDATION SUITE'.center(70))
    print('█' * 70)
    
    # Run automated checks
    db_ok = test_database_state()
    routes_ok = test_routes_exist()
    render_ok = test_template_rendering()
    
    # Print results
    print_header('AUTOMATED VALIDATION RESULTS')
    print(f'  Database State:         {"✓ PASS" if db_ok else "✗ FAIL"}')
    print(f'  Route Registration:     {"✓ PASS" if routes_ok else "✗ FAIL"}')
    print(f'  Template Rendering:     {"✓ PASS" if render_ok else "✗ FAIL"}')
    
    overall = db_ok and routes_ok and render_ok
    print(f'\n  Overall Status: {"✓ READY FOR TESTING" if overall else "✗ FIX ISSUES FIRST"}')
    
    if not overall:
        print('\n⚠️  Some issues found. Review above for details.')
        return 1
    
    # Print manual testing guide
    print_testing_guide()
    
    print_header('NEXT STEPS')
    print('''
  1. Review the INTEGRATION_SUMMARY.md document
  2. Start the Flask application
  3. Follow the Manual Testing Guide above
  4. Report any issues or unexpected behavior
    ''')
    
    print('\n' + '█' * 70 + '\n')
    return 0

if __name__ == '__main__':
    sys.exit(main())
