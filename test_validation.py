#!/usr/bin/env python3
"""Quick validation of integration components"""

import os
import sys
from datetime import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

def main():
    print("\n" + "="*70)
    print("PROMOTION + ARCHIVE INTEGRATION - VALIDATION".center(70))
    print("="*70)
    
    # Test 1: Import check
    print("\n[1] Checking imports...")
    try:
        from app import app
        from models import Student, Assessment, User
        print("    ✓ App and models import successfully")
    except ImportError as e:
        print(f"    ✗ Import error: {e}")
        return 1
    
    # Test 2: Route check
    print("\n[2] Checking routes...")
    with app.app_context():
        routes_to_check = {
            'promotion.promote_class_view': '/admin/promote-class',
            'promotion.execute_promotion': '/admin/promote-class/execute',
            'promotion.order_of_merit': '/admin/order-of-merit',
            'promotion.order_of_merit_print': '/admin/order-of-merit/print',
            'assessments_archived': '/assessments/archived',
        }
        
        found = 0
        for endpoint, path in routes_to_check.items():
            try:
                rule = app.url_map._rules_by_endpoint.get(endpoint)
                if rule:
                    found += 1
                    print(f"    ✓ {endpoint:40} {path}")
            except:
                print(f"    ✗ {endpoint:40} NOT FOUND")
        
        print(f"\n    Result: {found}/{len(routes_to_check)} routes registered")
        if found != len(routes_to_check):
            return 1
    
    # Test 3: Template check
    print("\n[3] Checking templates...")
    from jinja2 import Environment, FileSystemLoader
    
    template_files = [
        'promote_class.html',
        'order_of_merit.html', 
        'archive_view.html'
    ]
    
    env = Environment(loader=FileSystemLoader('templates'))
    for tmpl in template_files:
        try:
            env.get_template(tmpl)
            print(f"    ✓ {tmpl}")
        except Exception as e:
            print(f"    ✗ {tmpl}: {str(e)[:50]}")
            return 1
    
    # Test 4: Database check
    print("\n[4] Checking database...")
    with app.app_context():
        try:
            student_count = Student.query.count()
            assessment_count = Assessment.query.count()
            admin_count = User.query.filter_by(is_admin=True).count()
            archived_count = Assessment.query.filter_by(archived=True).count()
            
            print(f"    Students: {student_count}")
            print(f"    Assessments: {assessment_count} ({archived_count} archived)")
            print(f"    Admins: {admin_count}")
            
            if admin_count == 0:
                print("    ⚠️  WARNING: No admin accounts found")
        except Exception as e:
            print(f"    ✗ Database error: {e}")
            return 1
    
    print("\n" + "="*70)
    print("VALIDATION COMPLETE - All checks passed!".center(70))
    print("="*70)
    print("\nNext steps:")
    print("  1. Start the app: python -m flask run")
    print("  2. Login as admin")
    print("  3. Test promotion, merit rankings, and archive features")
    print("  4. See INTEGRATION_SUMMARY.md for detailed testing guide")
    print()
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
