import os
import sys

os.chdir(r'c:\Users\HP\Documents\school_assess_app_EXPERIMENTAL_ver_1')
sys.path.insert(0, os.getcwd())

print("\nIntegration Validation Script")
print("=" * 70)

try:
    from app import app
    from models import Student, Assessment, User
    print("[OK] App and models imported")
except Exception as e:
    print(f"[ERROR] Import failed: {e}")
    sys.exit(1)

print("\nChecking routes...")
with app.app_context():
    routes = {
        'promotion.promote_class_view',
        'promotion.execute_promotion', 
        'promotion.order_of_merit',
        'promotion.order_of_merit_print',
        'assessments_archived',
    }
    
    registered = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint in routes:
            registered.add(rule.endpoint)
            print(f"  [OK] {rule.endpoint:40} {rule.rule}")
    
    missing = routes - registered
    if missing:
        for m in missing:
            print(f"  [MISSING] {m}")
    else:
        print(f"\n  All {len(routes)} routes registered!")

print("\nChecking templates...")
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))

for tmpl in ['promote_class.html', 'order_of_merit.html', 'archive_view.html']:
    try:
        env.get_template(tmpl)
        print(f"  [OK] {tmpl}")
    except Exception as e:
        print(f"  [ERROR] {tmpl}: {e}")

print("\nChecking database...")
with app.app_context():
    students = Student.query.count()
    assessments = Assessment.query.count()
    admins = User.query.filter_by(is_admin=True).count()
    archived = Assessment.query.filter_by(archived=True).count()
    
    print(f"  Students: {students}")
    print(f"  Assessments: {assessments} ({archived} archived)")
    print(f"  Admin users: {admins}")
    
    if admins == 0:
        print("  [WARNING] No admin accounts found!")

print("\n" + "=" * 70)
print("Validation complete - ready for testing!")
print("=" * 70)
print("\nNext: python -m flask run (then login and test features)")
print()
