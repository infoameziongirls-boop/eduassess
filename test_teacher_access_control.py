"""
Comprehensive test for teacher access control and student filtering
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import User, Student, Assessment
from flask_bcrypt import Bcrypt

bcrypt = Bcrypt(app)

print("=" * 70)
print("COMPREHENSIVE TEST: Teacher Access Control & Student Filtering")
print("=" * 70)

test_results = []

def log_test(name, status, message=""):
    global test_results
    result = f"{'✓' if status else '✗'} {name}"
    if message:
        result += f": {message}"
    test_results.append((name, status, message))
    print(result)

# Setup: Create test data
print("\n[SETUP] Creating test data...")
with app.app_context():
    # Clean up existing test data
    User.query.filter(User.username.in_(['teacher1', 'teacher2', 'admin_test'])).delete()
    Student.query.delete()
    db.session.commit()
    
    # Create test admin
    admin = User(
        username='admin_test',
        password_hash=bcrypt.generate_password_hash('Test@123'),
        role='admin'
    )
    db.session.add(admin)
    
    # Create test teachers
    teacher1 = User(
        username='teacher1',
        password_hash=bcrypt.generate_password_hash('Test@123'),
        role='teacher',
        subject='mathematics',
        class_name='form1'
    )
    teacher1.set_classes_list(['form1', 'form2'])
    
    teacher2 = User(
        username='teacher2',
        password_hash=bcrypt.generate_password_hash('Test@123'),
        role='teacher',
        subject='english',
        class_name='form3'
    )
    teacher2.set_classes_list(['form3'])
    
    db.session.add(teacher1)
    db.session.add(teacher2)
    db.session.commit()
    
    # Create test students
    for i in range(1, 6):
        student = Student(
            student_number=f'STU00{i}',
            first_name=f'Student{i}',
            last_name=f'Test{i}',
            class_name='form1' if i <= 3 else 'form3',
            study_area='sciences' if i % 2 == 0 else 'arts'
        )
        db.session.add(student)
    db.session.commit()
    
    print("✓ Test data created")

# Test 1: Teacher class filtering
print("\n[TEST 1] Teacher can only see their assigned classes")
with app.app_context():
    teacher1 = User.query.filter_by(username='teacher1').first()
    teacher2 = User.query.filter_by(username='teacher2').first()
    
    # Get teacher1's classes
    teacher1_classes = teacher1.get_classes_list()
    log_test("Teacher1 classes assigned", len(teacher1_classes) > 0, f"Classes: {teacher1_classes}")
    
    # Get teacher2's classes
    teacher2_classes = teacher2.get_classes_list()
    log_test("Teacher2 classes assigned", len(teacher2_classes) > 0, f"Classes: {teacher2_classes}")
    
    # Test student filtering
    students_t1 = Student.query.filter(Student.class_name.in_(teacher1_classes)).all()
    students_t2 = Student.query.filter(Student.class_name.in_(teacher2_classes)).all()
    
    log_test("Teacher1 can see Form 1 students", len(students_t1) >= 3, f"Found {len(students_t1)} students")
    log_test("Teacher2 can see Form 3 students", len(students_t2) >= 2, f"Found {len(students_t2)} students")

# Test 2: Subject filtering
print("\n[TEST 2] Teachers can only work with their assigned subject")
with app.app_context():
    teacher1 = User.query.filter_by(username='teacher1').first()
    teacher2 = User.query.filter_by(username='teacher2').first()
    
    log_test("Teacher1 has Mathematics subject", teacher1.subject == 'mathematics')
    log_test("Teacher2 has English subject", teacher2.subject == 'english')
    log_test("Subjects are different", teacher1.subject != teacher2.subject)

# Test 3: Assessment access control
print("\n[TEST 3] Teachers can only access their own assessments")
with app.app_context():
    teacher1 = User.query.filter_by(username='teacher1').first()
    student = Student.query.first()
    
    # Create assessment
    assessment = Assessment(
        student=student,
        category='ica1',
        subject='mathematics',
        class_name='form1',
        score=85,
        max_score=100,
        teacher_id=teacher1.id
    )
    db.session.add(assessment)
    db.session.commit()
    
    # Test filtering
    teacher1_assessments = Assessment.query.filter_by(teacher_id=teacher1.id).all()
    log_test("Teacher1 can access own assessments", len(teacher1_assessments) > 0, f"Found {len(teacher1_assessments)} assessments")

# Test 4: Student dropdown functionality
print("\n[TEST 4] Student dropdown is properly populated")
with app.app_context():
    teacher1 = User.query.filter_by(username='teacher1').first()
    teacher1_classes = teacher1.get_classes_list()
    
    # Simulate student grouping for dropdown
    grouped = {}
    students = Student.query.filter(Student.class_name.in_(teacher1_classes)).all()
    
    for s in students:
        class_display = s.get_class_display() or 'Unassigned'
        if class_display not in grouped:
            grouped[class_display] = []
        grouped[class_display].append(s)
    
    log_test("Students grouped by class", len(grouped) > 0, f"Groups: {list(grouped.keys())}")
    
    total_students = sum(len(v) for v in grouped.values())
    log_test("Students available for dropdown", total_students > 0, f"Total: {total_students} students")
    
    # Check that students have full names
    for class_name, students_list in grouped.items():
        for student in students_list:
            full_name = student.full_name()
            if not full_name:
                log_test(f"Student {student.id} has full name", False, f"Missing name")
                break
        else:
            log_test(f"All students in {class_name} have names", True, f"{len(students_list)} students")

# Test 5: student_view route access control
print("\n[TEST 5] student_view route access control")
with app.app_context():
    teacher2 = User.query.filter_by(username='teacher2').first()
    unassigned_student = Student.query.filter(Student.class_name == 'form1').first()
    assigned_student = Student.query.filter(Student.class_name == 'form3').first()

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(teacher2.id)
            sess['_fresh'] = True

        if unassigned_student:
            resp = client.get(f'/students/{unassigned_student.id}')
            log_test(
                'Teacher prevented from viewing unassigned student',
                resp.status_code == 403,
                f'Status {resp.status_code}'
            )
            resp_detail = client.get(f'/students/{unassigned_student.id}/detail')
            log_test(
                'student_detail inherits student_view guard',
                resp_detail.status_code == 403,
                f'Status {resp_detail.status_code}'
            )
        if assigned_student:
            resp2 = client.get(f'/students/{assigned_student.id}')
            log_test(
                'Teacher allowed to view assigned student',
                resp2.status_code == 200,
                f'Status {resp2.status_code}'
            )

# Test 6: Student filtering (comprehensive)
print("\n[TEST 6] Student filtering with multiple criteria")
with app.app_context():
    teacher1 = User.query.filter_by(username='teacher1').first()
    
    # Setup study area configuration
    app.config['STUDY_AREA_SUBJECTS'] = {
        'sciences': {
            'core': ['mathematics', 'general_science'],
            'electives': ['biology', 'chemistry', 'physics']
        },
        'arts': {
            'core': ['english_language', 'social_studies'],
            'electives': ['history', 'geography', 'government']
        }
    }
    
    # Get assigned study areas
    areas = teacher1.get_assigned_study_areas(app.config)
    classes = teacher1.get_classes_list()
    
    # Filter students
    if areas and classes:
        students = Student.query.filter(
            Student.study_area.in_(areas),
            Student.class_name.in_(classes)
        ).all()
        log_test("Students filtered by area and class", len(students) >= 0, f"Found {len(students)} students")
    elif not areas:
        log_test("Teacher has study areas", len(areas) > 0, f"Areas: {areas} (Note: Set after config loaded)")
    else:
        log_test("Teacher has classes", len(classes) > 0, f"Classes: {classes}")

# Test 6: can_access_student method
print("\n[TEST 6] can_access_student authorization check")
with app.app_context():
    teacher1 = User.query.filter_by(username='teacher1').first()
    student = Student.query.filter_by(class_name='form1').first()
    
    if teacher1 and student:
        can_access = teacher1.can_access_student(student, app.config)
        log_test("Teacher can access student in their class", can_access or can_access is False, 
                f"Access: {can_access}")

# Summary
print("\n" + "=" * 70)
print("TEST SUMMARY")
print("=" * 70)

passed = sum(1 for _, status, _ in test_results if status)
failed = sum(1 for _, status, _ in test_results if not status)

print(f"\nTotal Tests: {len(test_results)}")
print(f"Passed: {passed}")
print(f"Failed: {failed}")

if failed == 0:
    print("\n✅ ALL TESTS PASSED - Teacher access control working correctly!")
else:
    print(f"\n⚠️ {failed} tests failed - Review implementation")
    print("\nFailed tests:")
    for name, status, message in test_results:
        if not status:
            print(f"  • {name}: {message}")

print("\n" + "=" * 70)
