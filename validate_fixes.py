"""
Final validation of all routing and template fixes
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import User

print("=" * 70)
print("VALIDATION REPORT: Testing for Routing & Jinja Errors")
print("=" * 70)

errors_found = []
warnings_found = []

# 1. Check if is_parent() method exists
print("\n[1] Checking User.is_parent() method...")
try:
    test_user = User(username='test', role='parent')
    if hasattr(test_user, 'is_parent') and callable(getattr(test_user, 'is_parent')):
        result = test_user.is_parent()
        if result == True:
            print("    ✓ is_parent() method exists and works correctly")
        else:
            print("    ✗ is_parent() method returns unexpected value")
            errors_found.append("is_parent() method returns False for parent role")
    else:
        print("    ✗ is_parent() method not found")
        errors_found.append("is_parent() method does not exist")
except Exception as e:
    print(f"    ✗ Error: {str(e)}")
    errors_found.append(f"Error checking is_parent(): {str(e)}")

# 2. Check if last_login field exists
print("\n[2] Checking User.last_login field...")
try:
    test_user = User(username='test', role='teacher')
    if hasattr(test_user, 'last_login'):
        print("    ✓ last_login field exists in User model")
    else:
        print("    ✗ last_login field not found")
        errors_found.append("last_login field does not exist in User model")
except Exception as e:
    print(f"    ✗ Error: {str(e)}")
    errors_found.append(f"Error checking last_login: {str(e)}")

# 3. Check all User role methods
print("\n[3] Checking all User role methods...")
role_methods = {
    'admin': 'is_admin',
    'teacher': 'is_teacher',
    'student': 'is_student',
    'parent': 'is_parent'
}

for role, method in role_methods.items():
    try:
        user = User(username=f'test_{role}', role=role)
        if hasattr(user, method) and callable(getattr(user, method)):
            print(f"    ✓ {method}() exists for role '{role}'")
        else:
            print(f"    ✗ {method}() missing for role '{role}'")
            errors_found.append(f"{method}() method missing for role '{role}'")
    except Exception as e:
        print(f"    ✗ Error checking {method}(): {str(e)}")
        errors_found.append(f"Error checking {method}(): {str(e)}")

# 4. Check all required Student methods
print("\n[4] Checking Student methods...")
from models import Student

required_student_methods = [
    'full_name',
    'get_class_display',
    'get_study_area_display',
    'calculate_final_grade'
]

for method_name in required_student_methods:
    if hasattr(Student, method_name):
        print(f"    ✓ Student.{method_name}() exists")
    else:
        print(f"    ✗ Student.{method_name}() missing")
        errors_found.append(f"Student.{method_name}() method missing")

# 5. Check all User methods
print("\n[5] Checking User methods...")
required_user_methods = [
    'check_password',
    'is_admin',
    'is_teacher',
    'is_student',
    'is_parent',
    'get_subject_display',
    'get_assigned_study_areas',
    'can_access_student',
    'get_classes_list',
    'set_classes_list'
]

for method_name in required_user_methods:
    if hasattr(User, method_name):
        print(f"    ✓ User.{method_name}() exists")
    else:
        print(f"    ✗ User.{method_name}() missing")
        errors_found.append(f"User.{method_name}() method missing")

# 6. Check critical endpoints
print("\n[6] Checking critical Flask endpoints...")
critical_endpoints = [
    'dashboard',
    'student_dashboard',
    'parent_dashboard',
    'user_messages',
    'students',
    'assessments_list',
    'users',
    'admin_settings',
    'admin_activity_logs',
    'class_management',
    'analytics_dashboard',
    'teacher_question_bank',
    'teacher_quizzes',
    'student_quizzes',
    'student_questions',
    'create_question',
    'bulk_import_questions',
    'admin_question_bank',
    'approve_all_questions',
    'student_login',
    'student_logout',
    'logout',
    'login',
    'archive_term',
    'teacher_subject',
    'class_register',
    'new_assessment',
    'assessments_archived',
    'admin_messages',
    'admin_send_message',
    'teacher_quiz_results',
    'download_question_template',
    'export_csv',
    'export_all_students_excel',
    'import_excel',
    'student_new',
    'student_bulk_import'
]

with app.app_context():
    url_map = app.url_map
    available_endpoints = {rule.endpoint for rule in url_map.iter_rules() if rule.endpoint != 'static'}
    
    for endpoint in critical_endpoints:
        if endpoint in available_endpoints:
            print(f"    ✓ Endpoint '{endpoint}' exists")
        else:
            print(f"    ✗ Endpoint '{endpoint}' NOT FOUND")
            errors_found.append(f"Endpoint '{endpoint}' not defined in app.py")

# Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

if errors_found:
    print(f"\n❌ {len(errors_found)} ERROR(S) FOUND:\n")
    for i, error in enumerate(errors_found, 1):
        print(f"   {i}. {error}")
else:
    print("\n✅ ALL TESTS PASSED - No errors found!")

if warnings_found:
    print(f"\n⚠️  {len(warnings_found)} WARNING(S):\n")
    for i, warning in enumerate(warnings_found, 1):
        print(f"   {i}. {warning}")

print("\n" + "=" * 70)
